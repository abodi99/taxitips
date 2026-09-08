"""
Förar-API:t -- det appen läser i stället för Supabase-RPC:erna.

Spår B. Fram tills nu låg tre saker i plpgsql (`get_smart_alerts`,
`get_opportunity_detail`, `current_entitlement`) och en fjärde i Dart
(nivågränserna i severity_labels.dart/api_client.dart), medan
poängsättningen som producerade datan hade flyttat till Python. Samma
bedömning gjordes alltså på tre språk, och `get_smart_alerts` hann bli
omdefinierad sju gånger över 25 migrationsfiler innan någon frågade vilken
version som gällde.

Här görs den en gång. Endpointerna svarar med samma fältnamn som RPC:erna
gjorde -- appen kan byta väg utan att kartan, korten eller sorteringen
skrivs om -- plus de fält som pipelinen räknat fram men RPC:n aldrig
exponerade (`compensation_*`, `level`, `notify_worthy`, `region`).

Ingen DRF: fyra vyer, ingen serializer-hierarki, inga ViewSets. JsonResponse
och en handskriven dict är läsbart och har inget att uppgradera.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core import thresholds
from core.alternatives import travel_options
from core.entitlement import entitlement_for_request
from core.geo import haversine_km
from core.models import Opportunity, OpportunityFeedback, ScoringRule, SourceEvent

log = logging.getLogger(__name__)


def _cors(response, request):
    """
    Tillåter Flutter web / visualiseraren att läsa API:t under lokal
    utveckling. Origins konfigureras explicit (APP_API_ALLOWED_ORIGINS) --
    inget `*`, eftersom svaren är entitlement-gated data.
    """
    from django.conf import settings

    allowed = [o for o in getattr(settings, "APP_API_ALLOWED_ORIGINS", []) if o]
    origin = request.headers.get("Origin", "")
    if origin and origin in allowed:
        response["Access-Control-Allow-Origin"] = origin
        response["Vary"] = "Origin"
        response["Access-Control-Allow-Headers"] = "X-Device-Token, Authorization, Content-Type"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def _json(request, payload, status=200):
    return _cors(
        JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False}),
        request,
    )


def _float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso(dt):
    return dt.isoformat() if dt else None


def _serialize(o: Opportunity, distance_km: float | None, now) -> dict:
    """
    Ett tips som appen läser det.

    Fältnamnen är RPC:ns, med avsikt: `worth_it_score`, `is_active` och
    `distance_km` heter likadant som `get_smart_alerts` kallade dem, så
    kartan och sorteringen i driver_screen.dart fungerar oförändrat.
    """
    is_active = bool(o.end_time and o.end_time > now)
    # Kvar som fält (app, karta och sortering läser det) men svarar numera
    # bara på "hur stark är signalen" -- avståndet är förarens beslut, inte
    # poängens. Se 20260905000006_drop_reachability_from_score.sql.
    worth_it = o.demand_score if is_active else 0
    return {
        "id": str(o.id),
        "title": o.title,
        "summary": o.summary,
        "kind": o.kind,
        "mode": o.mode,
        "severity_tier": o.severity_tier,
        "confidence": o.confidence,
        "rule_id": o.rule_id,
        "lat": o.lat,
        "lon": o.lon,
        "region": o.region,
        "places": o.places,
        "start_time": _iso(o.start_time),
        "end_time": _iso(o.end_time),
        "demand_score": o.demand_score,
        "reasons": o.reasons,
        "distance_km": distance_km,
        "is_active": is_active,
        "worth_it_score": worth_it,
        # Bedömningen görs här nu, inte i Dart -- se core/thresholds.py.
        "level": thresholds.customer_likelihood(o.severity_tier, o.demand_score, worth_it),
        "notify_worthy": o.demand_score >= thresholds.NOTIFY_SCORE_FLOOR,
        # Räknades ut av core/compensation.py men nådde aldrig en förare:
        # get_smart_alerts skrevs innan fälten fanns.
        "compensation_eligible": o.compensation_eligible,
        "compensation_amount_kr": o.compensation_amount_kr,
        "compensation_per_person": o.compensation_per_person,
        # "Vad gör resenären i stället?" -- den fråga som avgör om det är
        # värt att köra dit. Formuleringen görs här, inte i appen, se
        # core/alternatives.py.
        "travel_options": travel_options(
            next_departure_at=o.next_departure_at,
            next_departure_minutes=o.next_departure_minutes,
            is_last_departure=o.is_last_departure,
            has_alternative=o.has_alternative,
            alternative_note=o.alternative_note,
            now=now,
        ),
    }


def feed_for(lat: float | None, lon: float | None, now=None) -> dict:
    """
    Tipsflödet för en position -- urvalet, avståndet och ordningen.

    Egen funktion, inte inbakad i vyn, därför att pipeline-visualiseraren
    ska kunna visa EXAKT vad en förare i Malmö, Stockholm eller Göteborg
    ser (avsnitt 7). En andra implementation "ungefär som API:t" hade
    kunnat visa rätt när verkligheten var fel -- vilket är det enda sättet
    ett sådant avsnitt kan göra skada.

    Port av `get_smart_alerts`, rad för rad, med två skillnader:

    * marknaden för koordinatlösa tips härleds ur REGION_ANCHOR i stället
      för tre hårdkodade rutor -- se core/thresholds.market_region().
    * `level` och `notify_worthy` räknas ut här i stället för i appen.
    """
    now = now or timezone.now()
    home_region = thresholds.market_region(lat, lon)

    rows = Opportunity.objects.filter(
        end_time__gt=now - timedelta(hours=thresholds.FEED_LOOKBACK_HOURS),
        demand_score__gt=0,
    ).exclude(severity_tier="ignore")

    out = []
    for o in rows:
        distance_km = None
        if o.lat is not None and o.lon is not None and lat is not None and lon is not None:
            distance_km = round(haversine_km(lat, lon, o.lat, o.lon), 1)
            if distance_km > thresholds.MARKET_RADIUS_KM:
                continue
        elif o.lat is None or o.lon is None:
            # Utan koordinat avgör regionnyckeln. `region` är NULL, aldrig
            # tom sträng, när marknaden är okänd -- fallbacken 'skane'
            # ärvs från RPC:n så att befintlig data beter sig likadant.
            if not home_region or (o.region or "skane") != home_region:
                continue
        out.append(_serialize(o, distance_km, now))

    out.sort(key=lambda a: (-a["worth_it_score"], a["distance_km"] is None, a["distance_km"] or 0))

    # Väghändelser hålls åtskilda från tipslistan, inte utanför svaret.
    # Skälet står i core/taxi_relevance.score_road_alert: en olycka eller
    # kö försenar dem som redan sitter i bil och skapar inga taxikunder --
    # den är sammanhang för vägen DIT ("räkna med omväg"), inte ett skäl
    # att åka någonstans. Mätt i Skåne en vanlig förmiddag: 129 vägrader
    # mot 5 kollektivtrafiktips. Blandade i samma lista hade de begravt
    # det enda som var värt att köra till.
    alerts = [a for a in out if a["kind"] != "road"]
    context = [a for a in out if a["kind"] == "road"]
    return {
        "alerts": alerts,
        "context": context,
        "homeRegion": home_region,
        "generatedAt": _iso(now),
    }


@require_GET
def alerts(request):
    """GET /api/alerts?lat=..&lon=..  (X-Device-Token eller Bearer-JWT)"""
    ent = entitlement_for_request(request)
    if not ent.ok:
        # Tomt flöde, inte 403: en obetald/okänd token ska se "inga tips",
        # precis som RPC:n returnerade '[]'. `reason` finns med för att
        # felsökning inte ska kräva en databasfråga -- det var just det som
        # gjorde ägar-buggen osynlig i ett halvår.
        return _json(request, {"alerts": [], "entitled": False, "reason": ent.reason})

    feed = feed_for(_float(request.GET.get("lat")), _float(request.GET.get("lon")))
    return _json(request, {**feed, "entitled": True, "config": thresholds.as_config()})


@require_GET
def opportunity_detail(request, opportunity_id):
    """
    GET /api/opportunities/<uuid>  -- "Varför visas detta?"

    Port av `get_opportunity_detail`. Hämtas bara när en förare öppnar
    förklaringspanelen, aldrig för hela listan.
    """
    ent = entitlement_for_request(request)
    if not ent.ok:
        return _json(request, {"error": "not_entitled", "reason": ent.reason}, status=403)

    o = Opportunity.objects.filter(id=opportunity_id).first()
    if o is None:
        return _json(request, {"error": "not_found"}, status=404)

    events = SourceEvent.objects.filter(id__in=[str(i) for i in (o.source_event_ids or [])])
    now = timezone.now()
    return _json(
        request,
        {
            "opportunity": {
                **_serialize(o, None, now),
                "computed_at": _iso(o.computed_at),
                "expired_reason": o.expired_reason,
                "level_label": o.level,
            },
            "source_events": [
                {
                    "source": se.source,
                    "external_id": se.external_id,
                    "fetched_at": _iso(se.fetched_at),
                    "active_from": _iso(se.active_from),
                    "active_to": _iso(se.active_to),
                    "raw": se.raw,
                }
                for se in events
            ],
            # Regeln som gav poängen, inte bara dess id -- förklaringen ska
            # gå att läsa utan att öppna admin.
            "rule": next(
                (
                    {"tier": r.tier, "mode": r.mode, "condition": r.condition,
                     "floor": r.floor, "cap": r.cap, "note": r.note}
                    for r in ScoringRule.objects.filter(tier=o.severity_tier)
                    if r.mode in ("", o.mode)
                ),
                None,
            ),
        },
    )


@csrf_exempt
@require_POST
def feedback(request):
    """
    POST /api/feedback  {"opportunity_id": uuid, "verdict": heading|fare|empty}

    Tar även emot appens äldre form {"alert_id":..., "result": true/false}
    -- inte av bakåtkompatibilitetsnit, utan för att den formen är det enda
    appen skickat hittills och inte ska behöva bytas i samma steg.
    """
    ent = entitlement_for_request(request)
    if not ent.ok:
        return _json(request, {"error": "not_entitled", "reason": ent.reason}, status=403)

    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return _json(request, {"error": "invalid_json"}, status=400)

    opportunity_id = body.get("opportunity_id") or body.get("alert_id")
    verdict = body.get("verdict")
    if verdict is None and "result" in body:
        verdict = OpportunityFeedback.Verdict.FARE if body["result"] else OpportunityFeedback.Verdict.EMPTY
    if not opportunity_id or verdict not in OpportunityFeedback.Verdict.values:
        return _json(request, {"error": "invalid_feedback"}, status=400)

    if not Opportunity.objects.filter(id=opportunity_id).exists():
        # Ett tips som hunnit gallras (purge_old, sju dagar) är inte ett
        # klientfel -- men det finns ingen rad att koppla svaret till.
        return _json(request, {"error": "unknown_opportunity"}, status=404)

    token = request.headers.get("X-Device-Token") or ""
    try:
        # atomic runt insert: en unik-krock markerar annars hela den
        # omgivande transaktionen som trasig, och nästa fråga i samma
        # request dör med TransactionManagementError i stället för att
        # kollisionen hanteras som det den är.
        with transaction.atomic():
            OpportunityFeedback.objects.create(
                opportunity_id=opportunity_id, device_token=token, verdict=verdict
            )
    except IntegrityError:
        # Samma omdöme igen = dubbeltryckning. Idempotent, inte ett fel.
        return _json(request, {"ok": True, "duplicate": True})
    return _json(request, {"ok": True})


@require_GET
def config(request):
    """
    GET /api/config -- tröskelvärdena appen slutar hårdkoda.

    Öppen med avsikt: den innehåller inga tips, bara de tal som avgör hur
    tips presenteras. Poängen är att talet 50 ska ha ETT hem.
    """
    return _json(
        request,
        {
            **thresholds.as_config(),
            "scoringRules": [
                {"tier": r.tier, "mode": r.mode or "", "condition": r.condition,
                 "floor": r.floor, "cap": r.cap, "confidence": r.confidence}
                for r in ScoringRule.objects.all()
            ],
        },
    )
