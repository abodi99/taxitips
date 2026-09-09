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

from core import notify, thresholds
from core.alternatives import travel_options
from core.coverage import uncovered_counties
from core.entitlement import entitlement_for_request, verify_supabase_jwt
from core.geo import haversine_km
from core.models import (
    Opportunity,
    OpportunityFavorite,
    OpportunityFeedback,
    PushDelivery,
    ScoringRule,
    SourceEvent,
)

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
    # I DEBUG släpps vilken localhost-port som helst in: `flutter run -d
    # chrome` väljer port själv, och att jaga porten i en lista är en
    # felkälla utan säkerhetsvärde på en maskin där allt ändå kör lokalt.
    # I produktion gäller bara den explicita listan -- svaren är
    # entitlement-gated data, och "*" hör inte hemma framför sådan.
    local = settings.DEBUG and (
        origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:")
    )
    if origin and (origin in allowed or local):
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


def owner_key_for(request) -> str | None:
    """
    Vem "mina favoriter" och "mina notiser" tillhör.

    Entitlement har TVÅ vägar (invariant 6): förarens X-Device-Token, och en
    inloggad ägare/administratörs Supabase-JWT. En nyckel som bara var
    device-token hade gjort favoritlistan tyst tom för varje inloggad ägare
    -- inklusive i webbläsaren, där det här först provas, eftersom en
    e-postinloggning aldrig har någon förartoken.

    Prefixet på ägarvägen ("user:<uuid>") är där för att en förartoken och
    ett användar-id aldrig ska kunna kollidera i samma kolumn.
    """
    token = request.headers.get("X-Device-Token") or request.GET.get("device_token")
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        payload = verify_supabase_jwt(auth[7:].strip())
        if payload and payload.get("sub"):
            return f"user:{payload['sub']}"
    return None


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
        # Den RIKTIGA push-grinden, inte bara poänggolvet. Fältet hette
        # redan notify_worthy men svarade på en annan fråga än den push-
        # steget ställer: golvet ensamt sa "ja" om en försening på 60 poäng,
        # medan core/notify.py aldrig hade skickat den (fel tier), och om en
        # inställd avgång med ersättningsbuss, som inte heller väcker någon.
        # Ett kort som lovar en notis föraren aldrig får är precis den sorts
        # tyst särgång som thresholds.py finns för att förhindra.
        "notify_worthy": thresholds.is_notify_worthy(
            o.severity_tier, o.demand_score, o.has_alternative
        ),
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


def feed_for(
    lat: float | None,
    lon: float | None,
    now=None,
    include_all: bool = False,
    owner_key: str | None = None,
) -> dict:
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
            if not include_all and distance_km > thresholds.MARKET_RADIUS_KM:
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

    # Favoriterna följer ALLTID med, som en egen lista och som en markering
    # på de kort som råkar finnas i flödet ändå.
    #
    # Att skicka dem separat i stället för att lita på att de ligger i
    # `alerts` är hela poängen med en favorit: ett sparat tips ska överleva
    # de tre saker som annars tar bort det ur vyn -- förarens filter,
    # marknadsradien (ett tips 200 km bort som föraren sparat medvetet), och
    # att störningen tagit slut. En app som fick favoriterna först efter att
    # ha filtrerat hade behövt gissa vilka som föll bort och varför.
    favorites = _favorites_for(owner_key, lat, lon, now) if owner_key else []
    favorite_ids = {f["id"] for f in favorites}
    for row in alerts + context:
        row["is_favorite"] = row["id"] in favorite_ids

    return {
        "alerts": alerts,
        "context": context,
        "favorites": favorites,
        "homeRegion": home_region,
        "generatedAt": _iso(now),
    }


def _favorites_for(owner_key: str, lat, lon, now) -> list[dict]:
    """
    Förarens sparade tips, fullt serialiserade.

    Rader vars tips gallrats (`purge_old`, sju dagar) faller tillbaka på
    ögonblicksbilden som sparades när favoriten sattes. En favoritlista som
    tömmer sig själv efter en vecka hade varit svårare att förstå än ingen
    lista alls -- föraren minns att hen sparade något, inte att databasen
    har en retention.
    """
    out = []
    rows = (
        OpportunityFavorite.objects.filter(owner_key=owner_key)
        .select_related("opportunity")
        .order_by("-created_at")
    )
    for fav in rows:
        o = fav.opportunity
        if o is None:
            snapshot = dict(fav.snapshot or {})
            snapshot.update(
                {
                    "is_active": False,
                    "is_favorite": True,
                    "purged": True,
                    "distance_km": None,
                    "worth_it_score": 0,
                    "favorited_at": _iso(fav.created_at),
                }
            )
            out.append(snapshot)
            continue
        distance_km = None
        if o.lat is not None and o.lon is not None and lat is not None and lon is not None:
            distance_km = round(haversine_km(lat, lon, o.lat, o.lon), 1)
        row = _serialize(o, distance_km, now)
        row["is_favorite"] = True
        row["purged"] = False
        row["favorited_at"] = _iso(fav.created_at)
        row["note"] = fav.note
        out.append(row)
    return out


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

    feed = feed_for(
        _float(request.GET.get("lat")),
        _float(request.GET.get("lon")),
        include_all=request.GET.get("all") == "1",
        owner_key=owner_key_for(request),
    )
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


# --- Favoriter -----------------------------------------------------------


@csrf_exempt
def favorites(request):
    """
    GET  /api/favorites                     -- förarens sparade tips
    POST /api/favorites {"opportunity_id": uuid, "favorite": true|false}

    En egen endpoint utöver `favorites` i tipsflödet, för att favoritlistan
    ska gå att öppna utan att hämta hela flödet -- och för att den ska
    fungera för en förare som står still med dålig täckning.
    """
    if request.method not in ("GET", "POST", "OPTIONS"):
        return _json(request, {"error": "method_not_allowed"}, status=405)
    if request.method == "OPTIONS":
        return _json(request, {"ok": True})

    ent = entitlement_for_request(request)
    if not ent.ok:
        return _json(request, {"error": "not_entitled", "reason": ent.reason}, status=403)

    owner = owner_key_for(request)
    if not owner:
        # Berättigad men utan identitet att spara på. Kan inträffa om
        # entitlement gick via en väg som inte bär någon nyckel -- svaret
        # säger vad som saknas i stället för att tyst spara i tomma intet.
        return _json(request, {"error": "no_owner_key"}, status=400)

    now = timezone.now()
    if request.method == "GET":
        return _json(
            request,
            {
                "favorites": _favorites_for(
                    owner, _float(request.GET.get("lat")), _float(request.GET.get("lon")), now
                )
            },
        )

    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return _json(request, {"error": "invalid_json"}, status=400)

    opportunity_id = body.get("opportunity_id") or body.get("id")
    if not opportunity_id:
        return _json(request, {"error": "missing_opportunity_id"}, status=400)

    o = Opportunity.objects.filter(id=opportunity_id).first()
    if o is None:
        return _json(request, {"error": "unknown_opportunity"}, status=404)

    # Utelämnat `favorite` betyder "spara" -- den vanligaste avsikten, och
    # samma tolkning som appens stjärnknapp skickar när den slås på.
    wants_favorite = body.get("favorite") is not False

    if not wants_favorite:
        removed, _ = OpportunityFavorite.objects.filter(
            owner_key=owner, opportunity_external_id=o.external_id
        ).delete()
        return _json(request, {"ok": True, "favorite": False, "removed": bool(removed)})

    try:
        with transaction.atomic():
            OpportunityFavorite.objects.create(
                owner_key=owner,
                opportunity=o,
                opportunity_external_id=o.external_id,
                snapshot=notify.snapshot_of(o),
                note=str(body.get("note") or "")[:500],
            )
    except IntegrityError:
        # Redan sparad. Dubbeltryckning, inte ett fel.
        return _json(request, {"ok": True, "favorite": True, "duplicate": True})
    return _json(request, {"ok": True, "favorite": True})


# --- Notishistorik -------------------------------------------------------


@require_GET
def notifications(request):
    """
    GET /api/notifications -- notiserna den här enheten faktiskt fått.

    Läses ur `push_delivery`, inte räknas fram på nytt ur `opportunities`:
    en lista som visade "vad du borde ha fått" hade svarat på en annan fråga
    än förarens, och skulle ändras retroaktivt varje gång någon rörde ett
    reglage i notisinställningarna.

    Bara device-token-vägen har en historik -- notiser går till enheter, och
    en inloggad ägare utan parad telefon har per definition inte fått några.
    Svaret säger det i klartext i stället för att visa en tom lista utan
    förklaring.
    """
    ent = entitlement_for_request(request)
    if not ent.ok:
        return _json(request, {"error": "not_entitled", "reason": ent.reason}, status=403)

    token = request.headers.get("X-Device-Token") or request.GET.get("device_token")
    if not token:
        return _json(
            request,
            {
                "notifications": [],
                "reason": "no_device",
                "hint": "Notiser skickas till en parad enhet. Den här inloggningen har ingen.",
            },
        )

    owner = owner_key_for(request)
    favorite_ids = set(
        OpportunityFavorite.objects.filter(owner_key=owner).values_list(
            "opportunity_external_id", flat=True
        )
    ) if owner else set()

    rows = PushDelivery.objects.filter(device_token=token, ok=True).order_by("-created_at")[:100]
    return _json(
        request,
        {
            "notifications": [
                {
                    "id": str(d.id),
                    "opportunity_id": str(d.opportunity_id) if d.opportunity_id else None,
                    "external_id": d.opportunity_external_id,
                    "title": d.title,
                    "body": d.body,
                    "sentAt": _iso(d.created_at),
                    # Tipset som det såg ut när notisen gick. Bevaras med
                    # avsikt: `purge_old` tar bort tipset efter sju dagar,
                    # och en notishistorik som tömmer sig själv bakvägen är
                    # svårare att förstå än ingen historik.
                    "opportunity": d.snapshot,
                    "is_favorite": d.opportunity_external_id in favorite_ids,
                    "purged": d.opportunity_id is None,
                }
                for d in rows
            ]
        },
    )


# --- Notisinställningar --------------------------------------------------


def _device_for(request):
    """Enheten notisinställningarna hör till, eller None."""
    from billing.models import Device

    token = request.headers.get("X-Device-Token") or request.GET.get("device_token")
    if not token:
        return None
    return Device.objects.filter(token=token).first()


@csrf_exempt
def notify_prefs(request):
    """
    GET  /api/notify-prefs   -- inställningarna plus katalogerna att välja ur
    POST /api/notify-prefs   -- {"enabled":, "types": {...}, "regions": [], "cities": []}

    Katalogerna (händelsetyper och län) serveras härifrån av samma skäl som
    tröskelvärdena: de fanns i två kopior i två språk -- notifyTypeCatalog i
    api_client.dart och DEFAULT_ON_TYPES i fcmPush.js -- utan något som höll
    ihop dem. Push-steget och reglaget i appen läser nu samma lista, så en
    typ kan inte vara påslagen i appen och okänd för sändaren.

    Inställningarna lagras fortfarande i `devices.notify_prefs` (Supabase
    äger den tabellen). Det som flyttar är vem som TOLKAR dem.
    """
    if request.method not in ("GET", "POST", "OPTIONS"):
        return _json(request, {"error": "method_not_allowed"}, status=405)
    if request.method == "OPTIONS":
        return _json(request, {"ok": True})

    ent = entitlement_for_request(request)
    if not ent.ok:
        return _json(request, {"error": "not_entitled", "reason": ent.reason}, status=403)

    device = _device_for(request)
    catalogs = {
        "typeCatalog": notify.type_catalog(),
        "regionCatalog": notify.region_catalog(),
        # Län vi bevisligen inte hämtar kollektivtrafik för. Visas som en
        # förklaring, aldrig som något att kryssa i: ett val vi inte kan
        # infria hade tolkats som "lugnt där" i stället för "vi hämtar inte
        # där". Se core/coverage.py.
        "uncoveredCounties": uncovered_counties(),
        "defaults": notify.default_prefs(),
        "notifyScoreFloor": thresholds.NOTIFY_SCORE_FLOOR,
    }

    if device is None:
        # Inloggad ägare utan parad enhet. Katalogerna går att visa, men det
        # finns ingen telefon att spara inställningar för -- och det är ett
        # bättre svar än ett tomt formulär som tyst inte sparar.
        return _json(
            request,
            {
                "prefs": notify.default_prefs(),
                "readOnly": True,
                "reason": "no_device",
                **catalogs,
            },
            status=200 if request.method == "GET" else 400,
        )

    if request.method == "GET":
        stored = device.notify_prefs if isinstance(device.notify_prefs, dict) else {}
        return _json(request, {"prefs": stored, "readOnly": False, **catalogs})

    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return _json(request, {"error": "invalid_json"}, status=400)

    from billing.models import Device

    current = dict(device.notify_prefs) if isinstance(device.notify_prefs, dict) else {}
    if "enabled" in body:
        current["enabled"] = body["enabled"] is not False
    if isinstance(body.get("types"), dict):
        known = {t["id"] for t in notify.TYPE_CATALOG}
        # Bara kända typer sparas. En okänd nyckel är antingen ett stavfel
        # eller en klient från framtiden, och båda ska synas som att den
        # inte fastnade -- inte ligga kvar och se ut som en inställning.
        current["types"] = {
            k: v is True for k, v in body["types"].items() if k in known
        }
    if isinstance(body.get("regions"), list):
        known = {r["key"] for r in notify.region_catalog()}
        current["regions"] = [str(r) for r in body["regions"] if str(r) in known]
    if isinstance(body.get("cities"), list):
        current["cities"] = [str(c) for c in body["cities"] if str(c).strip()][:50]

    Device.objects.filter(id=device.id).update(notify_prefs=current)
    return _json(request, {"ok": True, "prefs": current, **catalogs})
