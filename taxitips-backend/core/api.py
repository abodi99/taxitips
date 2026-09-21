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

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_GET, require_POST

from core import areas, notify, thresholds
from core.alternatives import travel_options
from core.coverage import county_catalog, uncovered_counties
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
        response["Access-Control-Allow-Headers"] = "X-Device-Token, Authorization, Content-Type, X-TT-Position, If-None-Match"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        # Utan den kan en webbklient inte läsa ETag och skicka den tillbaka.
        response["Access-Control-Expose-Headers"] = "ETag"
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


POSITION_HEADER = "X-TT-Position"


def position_from(request) -> tuple[float | None, float | None]:
    """
    Förarens position för det här anropet, avrundad till två decimaler
    (ungefär en kilometer).

    Appen skickar den i headern `X-TT-Position: lat,lon`, inte i URL:en, där
    den hamnar i åtkomstloggar hos varje proxy på vägen. En header skyddar inte
    i sig: servern sparar aldrig positionen, och core/log_filters.py tar bort
    koordinater ur loggposter. Query-parametrarna läses för äldre appversioner.
    """
    lat = lon = None
    raw = request.headers.get(POSITION_HEADER) or ""
    if "," in raw:
        first, _, second = raw.partition(",")
        lat, lon = _float(first.strip()), _float(second.strip())
    if lat is None or lon is None:
        lat, lon = _float(request.GET.get("lat")), _float(request.GET.get("lon"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return round(lat, 2), round(lon, 2)


def feed_etag(payload: dict) -> str:
    """
    Svag ETag över svarets innehåll, utan generatedAt (som ändras varje anrop).

    Appen skickar tillbaka den i If-None-Match. Är inget ändrat svarar servern 304
    utan kropp och appen behåller det den har. Oförändrade tips skrivs inte om
    (core/repository.upsert_opportunities), så svaret står still mellan
    pollrundor när ingenting hänt.
    """
    import hashlib

    stable = {key: value for key, value in payload.items() if key != "generatedAt"}
    body = json.dumps(stable, sort_keys=True, default=str, ensure_ascii=False)
    return f'W/"{hashlib.sha1(body.encode("utf-8")).hexdigest()}"'


# Hur länge ett uträknat flöde delas mellan förare med samma filter och avrundade
# position. Mätt 2026-09-13: två workers klarade ~45 svar/s när varje anrop räknade
# ut flödet -- även de som blev 304. Pipelinen skriver tips var 90:e sekund och appen
# hämtar var 60:e, så ett flöde som är 20 s gammalt märks inte.
FEED_CACHE_SECONDS = 20


_ROAD_TIER_RANK = {"road_accident_or_closure": 0, "road_work_or_queue": 1}
# SQL-sidan av thresholds.road_shown: road.<nivå>.<ett visat villkor>.
_ROAD_SHOWN_RE = r"^road\.[a-z_]+\.(" + "|".join(sorted(thresholds.ROAD_SHOWN_CONDITIONS)) + r")$"


def _one_per_road_situation(rows: list[dict]) -> list[dict]:
    """
    Den tydligaste avvikelsen per Trafikverket-situation (tv:<situation>:<avvikelse>).

    Allvarligast nivå vinner, sedan en rubrik som säger något ("Olycka") före
    den allmänna "Trafikmeddelande". Ordningen i övrigt behålls.
    """
    best: dict[str, int] = {}
    for i, row in enumerate(rows):
        external = row.get("_external_id") or ""
        if row.get("kind") != "road" or not external.startswith("tv:"):
            continue
        situation = external.rsplit(":", 1)[0]
        rank = (
            _ROAD_TIER_RANK.get(row.get("severity_tier"), 9),
            (row.get("title") or "") == "Trafikmeddelande",
        )
        held = best.get(situation)
        if held is None or rank < (
            _ROAD_TIER_RANK.get(rows[held].get("severity_tier"), 9),
            (rows[held].get("title") or "") == "Trafikmeddelande",
        ):
            best[situation] = i
    keep = set(best.values())
    return [
        row
        for i, row in enumerate(rows)
        if row.get("kind") != "road"
        or not (row.get("_external_id") or "").startswith("tv:")
        or i in keep
    ]


def shared_feed(
    lat, lon, *, include_all: bool, regions: list[str], counties: list[str], municipalities: list[str] | None = None,
    road_all: bool = False,
) -> dict:
    """
    Flödet utan det personliga (favoriterna), med ETag-delen, ur cachen eller nyräknat.

    Nyckeln är allt som påverkar urvalet: avrundad position, län, marknader och
    include_all. Två förare i samma kilometerruta med samma filter får samma svar.
    """
    import hashlib

    parts = json.dumps([
        lat, lon, include_all, sorted(regions), sorted(counties), sorted(municipalities or []), road_all,
    ])
    key = "feed:" + hashlib.sha1(parts.encode("utf-8")).hexdigest()
    shared = cache.get(key)
    if shared is not None:
        return shared
    feed = feed_for(
        lat, lon, include_all=include_all, regions=regions or None, counties=counties or None,
        municipalities=municipalities or None,
    )
    payload = {
        **feed,
        # Väghändelserna kapas i svaret, se thresholds.FEED_CONTEXT_LIMIT. feed_for
        # returnerar alla, så pipeline-sidan fortsätter att räkna dem. `road=all`
        # (appens Väg-läge) ger alla i området upp till ett tak som skyddar
        # telefonen: i Skåne, Halland och Västra Götaland var det 1 800 samtidigt.
        "context": feed["context"][
            : (thresholds.FEED_CONTEXT_FULL_LIMIT if road_all else thresholds.FEED_CONTEXT_LIMIT)
        ],
        "contextTotal": len(feed["context"]),
        "entitled": True,
        "config": thresholds.as_config(),
    }
    payload.pop("favorites", None)
    shared = {"payload": payload, "digest": feed_etag(payload)[3:-1][:24]}
    cache.set(key, shared, FEED_CACHE_SECONDS)
    return shared


def _mark_favorites(rows: list[dict], favorite_ids: set[str]) -> list[dict]:
    if not favorite_ids:
        return rows
    return [{**row, "is_favorite": True} if row["id"] in favorite_ids else row for row in rows]


def _if_none_match(request) -> set[str]:
    return {tag.strip() for tag in (request.headers.get("If-None-Match") or "").split(",") if tag.strip()}


def _iso(dt):
    return dt.isoformat() if dt else None


def _move_favorites(old_key: str, new_key: str) -> None:
    """
    Favoriter sparade med den råa token som nyckel flyttas till telefonens id.
    Kostar en indexerad UPDATE som oftast träffar noll rader. Se också
    core/migrations/0025_favorite_owner_is_device_id.py för dem som aldrig hörs av.
    """
    from django.db import IntegrityError, transaction

    try:
        with transaction.atomic():
            OpportunityFavorite.objects.filter(owner_key=old_key).update(owner_key=new_key)
    except IntegrityError:
        # Samma tips sparat under båda nycklarna: den nya gäller, den gamla tas bort.
        OpportunityFavorite.objects.filter(owner_key=old_key).delete()


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
        # Telefonens id, aldrig dess hemlighet: token är en inloggning, och en
        # kopia i favorittabellen hade gjort hashningen vid parkopplingen verkningslös.
        from fleet.access import device_for_token

        device, _credential, _how = device_for_token(token)
        if device is None:
            return None
        key = f"device:{device.id}"
        _move_favorites(token, key)
        return key
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
        "county": o.county_code,
        "countyName": areas.COUNTY_NAMES.get(o.county_code or ""),
        "municipality": o.municipality_code,
        "places": o.places,
        "start_time": _iso(o.start_time),
        "end_time": _iso(o.end_time),
        "demand_score": o.demand_score,
        "reasons": o.reasons,
        "distance_km": distance_km,
        "is_active": is_active,
        "worth_it_score": worth_it,
        # Bedömningen görs här nu, inte i Dart -- se core/thresholds.py.
        # has_alternative måste med, annars blir planerade
        # ersättningsbussar "high" i listfilter och badge.
        "level": thresholds.customer_likelihood(
            o.severity_tier, o.demand_score, worth_it, o.has_alternative
        ),
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
        # Appen speglar level lokalt när backend-fält saknas; behöver samma
        # signal så Dart-fallbacken inte "återuppväcker" ersättningstrafik.
        "has_alternative": o.has_alternative,
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


def _apply_combinations(rows: list[dict], now) -> list[dict]:
    """
    Kombinationslagrets rader på flödet (core/combine.py): en dubblett döljs bakom sin
    primära rad, ett påslag höjer ordningen. Varje ändring får sin skälrad och sitt
    regel-id i `combined`, så att kortet kan förklara den.
    """
    from core.models import Combination

    by_external = {row["_external_id"]: row for row in rows}
    if not by_external:
        return rows
    hidden: set[str] = set()
    for combination in Combination.objects.filter(primary_external_id__in=list(by_external), expires_at__gt=now):
        row = by_external[combination.primary_external_id]
        row["reasons"] = [*(row.get("reasons") or []), combination.reason]
        row.setdefault("combined", []).append(combination.rule_id)
        if combination.effect == "merge":
            hidden.update(combination.member_external_ids)
        elif combination.boost and row.get("is_active"):
            row["worth_it_score"] = min(100, row["worth_it_score"] + combination.boost)
    return [row for row in rows if row["_external_id"] not in hidden]


def feed_for(
    lat: float | None,
    lon: float | None,
    now=None,
    include_all: bool = False,
    owner_key: str | None = None,
    regions: list[str] | None = None,
    counties: list[str] | None = None,
    municipalities: list[str] | None = None,
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

    `regions` (valda län i appfiltret) byter ut GPS-radien mot samma
    länsankare som pushen (`notify.list_matches_regions`). Annars kapade
    en Malmö-GPS Stockholm/Göteborg innan listfiltret kunde matcha dem.
    """
    now = now or timezone.now()
    home_region = thresholds.market_region(lat, lon)
    chosen_regions = [str(r) for r in (regions or []) if str(r).strip()]
    # Körområde i län (P0-B1). Äldre klienter skickar marknader; de översätts.
    chosen_counties = sorted({str(c) for c in (counties or []) if str(c) in areas.COUNTY_NAMES})
    if not chosen_counties and chosen_regions:
        chosen_counties = areas.device_counties({"regions": chosen_regions})
    chosen_municipalities = areas.device_municipalities({"municipalities": municipalities or []})
    # Län och kommuner som koder att snitta mot tipsens area_codes; en vald kommun
    # ersätter sitt län. Se core/areas.device_area_codes.
    chosen_area = areas.device_area_codes({"counties": chosen_counties, "municipalities": chosen_municipalities})

    if not include_all and not chosen_area and not chosen_regions and (lat is None or lon is None):
        # Varken körområde eller position: vi vet inte var föraren kör. Tidigare
        # kom då varje tips med koordinat i hela landet med. Nu ber appen föraren
        # välja län i stället -- favoriterna följer ändu med.
        return {
            "alerts": [],
            "context": [],
            "favorites": _favorites_for(owner_key, lat, lon, now) if owner_key else [],
            "homeRegion": None,
            "counties": [],
            "municipalities": [],
            "needsArea": True,
            "generatedAt": _iso(now),
        }

    from django.db.models import Q

    rows = (
        Opportunity.objects.filter(
            end_time__gt=now - timedelta(hours=thresholds.FEED_LOOKBACK_HOURS),
            demand_score__gt=0,
        )
        .exclude(severity_tier="ignore")
        # Bara de väghändelser föraren ska se, se thresholds.ROAD_SHOWN_CONDITIONS.
        .exclude(Q(kind="road") & ~Q(rule_id__regex=_ROAD_SHOWN_RE))
    )

    # Förfilter i SQL: läs bara tips som kan hamna i svaret. Slingan nedan fäller
    # fortfarande det slutliga avgörandet med exakt avstånd och län -- filtret får
    # bara vara vidare än den, aldrig snävare.
    if not include_all:
        if chosen_area:
            # Tomma area_codes: rader skrivna innan länen fanns (se backfill_areas).
            rows = rows.filter(Q(area_codes__has_any_keys=chosen_area) | Q(area_codes=[]))
        elif not chosen_regions and lat is not None and lon is not None:
            import math

            dlat = thresholds.MARKET_RADIUS_KM / 110.57
            dlon = thresholds.MARKET_RADIUS_KM / (111.32 * max(math.cos(math.radians(lat)), 0.01))
            rows = rows.filter(
                Q(lat__isnull=True)
                | Q(lon__isnull=True)
                | Q(lat__range=(lat - dlat, lat + dlat), lon__range=(lon - dlon, lon + dlon))
            )

    out = []
    for o in rows:
        distance_km = None
        if o.lat is not None and o.lon is not None and lat is not None and lon is not None:
            distance_km = round(haversine_km(lat, lon, o.lat, o.lon), 1)

        if chosen_area and not include_all:
            # Körområdet äger geografin -- inte var telefonen står just nu.
            # Tipsets län och kommun inklusive grannar inom buffertarna, se core/areas.py.
            if not set(notify.tip_area_codes(o)) & set(chosen_area):
                continue
        elif chosen_regions and not include_all:
            # Bara marknader utan motsvarande län, t.ex. enbart "rail".
            if not notify.list_matches_regions(
                o.region, o.lat, o.lon, chosen_regions
            ):
                continue
        elif o.lat is not None and o.lon is not None and lat is not None and lon is not None:
            if not include_all and distance_km > thresholds.MARKET_RADIUS_KM:
                continue
        elif o.lat is None or o.lon is None:
            # Utan koordinat avgör regionnyckeln. `region` är NULL, aldrig
            # tom sträng, när marknaden är okänd -- fallbacken 'skane'
            # ärvs från RPC:n så att befintlig data beter sig likadant.
            if not home_region or (o.region or "skane") != home_region:
                continue
        row = _serialize(o, distance_km, now)
        # Bara en tiebreak, inte huvudordningen -- poängen avgör om det är
        # värt att köra dit, inte hur nytt tipset är. Utan den här raden
        # låg två likvärdiga tips i godtycklig databasordning, vilket i
        # praktiken innebar äldst-först och gjorde flödet stillastående.
        row["_computed_at"] = o.computed_at
        row["_external_id"] = o.external_id
        out.append(row)

    # Kombinationslagret före sorteringen: ett påslag ska synas i ordningen.
    out = _apply_combinations(out, now)

    out.sort(
        key=lambda a: (
            -a["worth_it_score"],
            a["distance_km"] is None,
            a["distance_km"] or 0,
            -a["_computed_at"].timestamp(),
        )
    )
    # En Trafikverket-situation har ofta flera avvikelser med samma text --
    # "Olycka" och "Trafikmeddelande" om samma krock. Föraren ser en.
    out = _one_per_road_situation(out)
    for row in out:
        del row["_computed_at"]
        del row["_external_id"]

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
        "counties": chosen_counties,
        "municipalities": chosen_municipalities,
        "needsArea": False,
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



def county_gate(ent, counties: list[str], municipalities: list[str]) -> tuple[list[str], list[str]]:
    """
    Snittet mellan licensens länsrättigheter och förarens filter.

    Förarens val får SMALNA AV, aldrig vidga. Två följder som är lätta att
    missa:

    * Utan valda län gäller licensens län -- inte GPS-radien. Annars hade en
      förare som står i ett grannlän sett tips hen inte betalar för, och
      positionen hade blivit en behörighet (§5).
    * En vald kommun måste ligga i ett län licensen har. SCB:s kommunkod bär
      länskoden i de två första siffrorna, så prövningen är ett prefix.

    `ent.unrestricted` betyder att företaget ännu inte migrerats till
    licensmodellen; då gäller filtret som förut.
    """
    if getattr(ent, "unrestricted", True):
        return counties, municipalities
    entitled = set(getattr(ent, "counties", ()) or ())
    chosen = {str(c).strip() for c in counties if str(c).strip()}
    allowed_counties = sorted(entitled & chosen) if chosen else sorted(entitled)
    allowed_municipalities = [
        m for m in municipalities if str(m)[:2] in (set(allowed_counties) or entitled)
    ]
    return allowed_counties, allowed_municipalities


def tip_within_entitlement(ent, opportunity) -> bool:
    """
    Får den här åtkomsten se det HÄR tipset? Används av detaljvyn och
    direktlänkar -- ett id i en URL får inte gå förbi länsrättigheten (§3).

    Tips utan länskoder släpps igenom, samma undantag som listan gör: de är
    rader skrivna innan länen fanns, och tågtips som saknar länsfält i
    Trafikverkets data (invariant 14). Avståndsgrinden i `within_reach()`
    håller dem, inte länsfiltret.
    """
    if getattr(ent, "unrestricted", True):
        return True
    codes = [str(c) for c in (getattr(opportunity, "area_codes", None) or [])]
    if not codes:
        return True
    entitled = set(getattr(ent, "counties", ()) or ())
    return any(code in entitled or code[:2] in entitled for code in codes)


@require_GET
@gzip_page
def alerts(request):
    """GET /api/alerts?lat=..&lon=..  (X-Device-Token eller Bearer-JWT)"""
    ent = entitlement_for_request(request)
    if not ent.ok:
        # Tomt flöde, inte 403: en obetald/okänd token ska se "inga tips",
        # precis som RPC:n returnerade '[]'. `reason` finns med för att
        # felsökning inte ska kräva en databasfråga -- det var just det som
        # gjorde ägar-buggen osynlig i ett halvår.
        return _json(request, {"alerts": [], "entitled": False, "reason": ent.reason})

    raw_regions = request.GET.get("regions") or ""
    regions = [r.strip() for r in raw_regions.split(",") if r.strip()]
    counties = [c.strip() for c in (request.GET.get("counties") or "").split(",") if c.strip()]
    municipalities = [m.strip() for m in (request.GET.get("municipalities") or "").split(",") if m.strip()]
    lat, lon = position_from(request)
    if not counties and not municipalities and not regions and (lat is None or lon is None):
        # Ingen position och inget filter i anropet: enhetens sparade körområde
        # gäller, så att en äldre app utan länsval inte får en tom lista.
        device = _device_for(request)
        if device is not None:
            counties = areas.device_counties(device.notify_prefs)
            municipalities = areas.device_municipalities(device.notify_prefs)

    if not getattr(ent, "unrestricted", True):
        # Licensmodellen gäller: rättigheten äger geografin. `regions` är
        # källornas gamla marknadsnycklar och kan inte kontrolleras mot en
        # länsrättighet -- de översätts till län och prövas som alla andra.
        if regions and not counties:
            counties = areas.device_counties({"regions": regions})
        regions = []
        counties, municipalities = county_gate(ent, counties, municipalities)
        if not counties and not municipalities:
            return _json(request, {
                "alerts": [], "context": [], "favorites": [],
                "entitled": False, "reason": "no_entitled_county",
                "message": "Billicensen har inget län som matchar ditt filter.",
            })

    shared = shared_feed(
        lat, lon, include_all=request.GET.get("all") == "1", regions=regions, counties=counties,
        municipalities=municipalities, road_all=request.GET.get("road") == "all",
    )

    # Favoriterna är personliga och räknas per anrop; resten delas av alla med samma
    # filter och avrundade position. ETag:en bär båda delarna, så en ny favorit syns
    # direkt, och 304 avgörs innan något serialiseras.
    import hashlib

    owner = owner_key_for(request)
    favorites = _favorites_for(owner, lat, lon, timezone.now()) if owner else []
    favorites_digest = hashlib.sha1(
        json.dumps(favorites, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    etag = f'W/"{shared["digest"]}-{favorites_digest}"'
    if etag in _if_none_match(request):
        from django.http import HttpResponseNotModified

        response = _cors(HttpResponseNotModified(), request)
    else:
        favorite_ids = {f["id"] for f in favorites}
        base = shared["payload"]
        response = _json(request, {
            **base,
            "alerts": _mark_favorites(base["alerts"], favorite_ids),
            "context": _mark_favorites(base["context"], favorite_ids),
            "favorites": favorites,
        })
    response["ETag"] = etag
    # Personligt svar som alltid omvalideras: ingen delad cache får spara det.
    response["Cache-Control"] = "private, no-cache"
    return response


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
    if not tip_within_entitlement(ent, o):
        # Samma svar som ett okänt id: en direktlänk ska inte kunna användas
        # för att ta reda på att ett tips finns i ett län man inte betalar för.
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
                    owner, *position_from(request), now
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
    """
    Enheten notisinställningarna hör till, eller None.

    Samma uppslag som åtkomstkontrollen (fleet/access.device_for_token): den
    hashade hemligheten från parkopplingen först, klartexttoken bara för
    telefoner som ännu inte parkopplats om. Tidigare letades bara på
    klartexttoken, och varje nyparkopplad telefon fick då skrivskyddade
    notisinställningar -- valen sparades aldrig, och notiserna följde inte
    förarens regler.
    """
    from fleet.access import device_for_token

    token = request.headers.get("X-Device-Token") or request.GET.get("device_token")
    if not token:
        return None
    device, _credential, _how = device_for_token(token)
    return device


def request_area(request, lat, lon, ent=None) -> tuple[list[str], list[str]]:
    """
    Län och kommuner för anropet: parametrarna `counties` och `municipalities`, annars
    enhetens sparade körområde när positionen saknas. Samma regel som /api/alerts, så att
    tips, färjor och evenemang alltid gäller samma område.

    Med [ent] och licensmodellen gäller licensens län, precis som i /api/alerts: förarens
    val får smalna av, aldrig vidga, och utan val gäller licensens län -- inte radien kring
    positionen. Utan det såg en förare med licens för Skåne Stockholms färjor och
    evenemang så fort hen valde Stockholm eller stod där. Se `county_gate`.
    """
    counties = [c.strip() for c in (request.GET.get("counties") or "").split(",") if c.strip()]
    municipalities = [m.strip() for m in (request.GET.get("municipalities") or "").split(",") if m.strip()]
    if not counties and not municipalities and (lat is None or lon is None):
        device = _device_for(request)
        if device is not None:
            counties = areas.device_counties(device.notify_prefs)
            municipalities = areas.device_municipalities(device.notify_prefs)
    if ent is not None and not getattr(ent, "unrestricted", True):
        counties, municipalities = county_gate(ent, counties, municipalities)
    return counties, municipalities


def area_blocked(ent, counties, municipalities) -> bool:
    """Licensmodellen och inget län kvar efter spärren: svaret ska vara tomt, inte en radie."""
    return not getattr(ent, "unrestricted", True) and not counties and not municipalities


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
        # Orter per län -- appen visar bara dem under valda län. Se
        # core/notify.cities_by_region.
        "citiesByRegion": notify.cities_by_region(),
        # Platt lista för bakåtkompatibilitet (äldre klienter). Samma
        # orter som i citiesByRegion, utan länsnyckel.
        "areaCatalog": sorted(
            {c for cities in notify.cities_by_region().values() for c in cities}
        ),
        # Län vi bevisligen inte hämtar kollektivtrafik för. Visas som en
        # förklaring, aldrig som något att kryssa i: ett val vi inte kan
        # infria hade tolkats som "lugnt där" i stället för "vi hämtar inte
        # där". Se core/coverage.py.
        "uncoveredCounties": uncovered_counties(),
        # Körområde: alla 21 län, med kollektivtrafikkälla eller inte. Ersätter
        # regionCatalog, som finns kvar för äldre klienter.
        "countyCatalog": county_catalog(),
        # Kommunerna per län, för att förfina ett valt län.
        "municipalityCatalog": areas.municipality_catalog(),
        "defaults": notify.default_prefs(),
        "notifyScoreFloor": thresholds.NOTIFY_SCORE_FLOOR,
        # Förarens enkla regler: kategorierna (samma som kartans rad) och nivåerna.
        "categoryCatalog": notify.CATEGORY_CATALOG,
        "levels": list(notify.LEVELS),
        "maxPauseHours": notify.MAX_PAUSE_HOURS,
        # Länen licensen omfattar. Appen erbjuder bara dem; tom lista och
        # `licensedCountiesUnrestricted` = bolaget är inte på licensmodellen än.
        "licensedCounties": sorted(getattr(ent, "counties", ()) or ()),
        "licensedCountiesUnrestricted": bool(getattr(ent, "unrestricted", True)),
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
        return _json(request, {
            "prefs": stored, "readOnly": False,
            # Länen som gäller för notisbeslutet: sparade län, annars de gamla
            # marknadsvalen översatta. Tom lista = inget körområde.
            "counties": areas.device_counties(stored),
            **catalogs,
        })

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
    if isinstance(body.get("counties"), list):
        counties = {str(c) for c in body["counties"] if str(c) in areas.COUNTY_NAMES}
        if not getattr(ent, "unrestricted", True):
            # Bara län licensen omfattar. Ett annat län hade sett ut som ett val
            # men aldrig gett en enda notis (fleet/push_gate.py släpper inte igenom det).
            counties &= set(getattr(ent, "counties", ()) or ())
        current["counties"] = sorted(counties)
    if isinstance(body.get("categories"), dict):
        current["categories"] = {
            k: v is not False for k, v in body["categories"].items() if k in {c["id"] for c in notify.CATEGORY_CATALOG}
        }
    if "minLevel" in body:
        level = str(body.get("minLevel") or "all")
        current["minLevel"] = level if level in notify.LEVELS else "all"
    if "pauseHours" in body:
        # Pausen räknas på servern, från serverns klocka: en telefon med fel tid
        # ska inte kunna pausa i ett år eller "pausa" bakåt i tiden.
        try:
            hours = float(body.get("pauseHours") or 0)
        except (TypeError, ValueError):
            hours = 0
        if hours > 0:
            hours = min(hours, notify.MAX_PAUSE_HOURS)
            current["pausedUntil"] = (timezone.now() + timedelta(hours=hours)).isoformat()
        else:
            current.pop("pausedUntil", None)
    if isinstance(body.get("municipalities"), list):
        current["municipalities"] = areas.device_municipalities({"municipalities": body["municipalities"]})
    if isinstance(body.get("cities"), list):
        current["cities"] = [str(c) for c in body["cities"] if str(c).strip()][:50]
    # Orter som inte hör till något valt län rensas bort. Annars kunde en
    # förare välja Skåne, kryssa Malmö, byta till Stockholm -- och fortfarande
    # ha Malmö kvar i prefs utan att UI:t visar det.
    allowed_cities = {
        c
        for key in current.get("regions") or []
        if key != "rail"
        for c in notify.cities_by_region().get(key, [])
    }
    if allowed_cities:
        current["cities"] = [
            c for c in (current.get("cities") or []) if c in allowed_cities
        ][:50]
    elif current.get("regions"):
        # Bara "rail" valt, eller län utan orter -- ortfiltret har ingen mening.
        current["cities"] = []

    Device.objects.filter(id=device.id).update(notify_prefs=current)
    return _json(request, {"ok": True, "prefs": current, "counties": areas.device_counties(current), **catalogs})


@csrf_exempt
def presence(request):
    """
    GET  /api/presence                 -- {"on": bool, "expiresAt": ...}
    POST /api/presence {"on": true}    -- "i tjänst", med positionen i X-TT-Position
    POST /api/presence {"on": false}   -- av; raden tas bort direkt

    Servern sparar bara rutan (≈ 5 km) och svarar aldrig med den. Se core/presence.py.
    """
    from core import presence as presence_rules

    if request.method == "OPTIONS":
        return _json(request, {"ok": True})
    if request.method not in ("GET", "POST"):
        return _json(request, {"error": "method_not_allowed"}, status=405)

    ent = entitlement_for_request(request)
    if not ent.ok:
        return _json(request, {"error": "not_entitled", "reason": ent.reason}, status=403)
    device = _device_for(request)
    if device is None:
        return _json(request, {"error": "no_device"}, status=400)

    now = timezone.now()
    info = {"radiusKm": presence_rules.RADIUS_KM, "ttlMinutes": int(presence_rules.TTL.total_seconds() // 60)}
    if request.method == "GET":
        row = presence_rules.fresh([device.id], now).get(str(device.id))
        return _json(request, {"on": row is not None, "expiresAt": _iso(row.expires_at) if row else None, **info})

    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return _json(request, {"error": "invalid_json"}, status=400)
    if body.get("on") is not True:
        presence_rules.set_off_duty(device.id)
        return _json(request, {"ok": True, "on": False, **info})

    lat, lon = position_from(request)
    if lat is None:
        return _json(request, {"error": "no_position"}, status=400)
    expires_at = presence_rules.set_on_duty(device.id, lat, lon, now)
    return _json(request, {"ok": True, "on": True, "expiresAt": _iso(expires_at), **info})


@csrf_exempt
@require_POST
def device_session(request):
    """
    Registrera den här telefonen för push och koppla den till inloggat konto.

    Anropas efter e-postinloggning (och vid kontobyte). Skapar eller
    uppdaterar en devices-rad med:
    * installation_id som stabil token (samma telefon → samma rad)
    * user_id från JWT
    * company_id från company_members
    * push_token (FCM)
    * last_seen_at = nu

    Förartoken-vägen (X-Device-Token) uppdaterar bara push + last_seen på
    den befintliga enheten och sätter user_id om JWT också skickas.
    """
    import uuid

    from billing.models import CompanyMember, Device
    from core.entitlement import entitlement_for_request, verify_supabase_jwt

    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return _json(request, {"error": "invalid_json"}, status=400)

    push_token = (body.get("push_token") or "").strip() or None
    installation_id = (body.get("installation_id") or "").strip()
    label = (body.get("label") or "App").strip()[:80] or "App"
    platform = (body.get("platform") or "").strip()[:32]
    now = timezone.now()

    auth = request.headers.get("Authorization", "")
    jwt_payload = None
    if auth.lower().startswith("bearer "):
        jwt_payload = verify_supabase_jwt(auth[7:].strip())
    user_id = (jwt_payload or {}).get("sub")

    device_header = request.headers.get("X-Device-Token") or ""
    # 1) Befintlig förarenhet / tidigare owner_app: spara push + last_seen
    # (+ user_id/company vid kontobyte).
    if device_header:
        # Samma uppslag som åtkomstkontrollen: både den hashade hemligheten
        # från parkopplingen och den äldre klartexttoken. Tidigare slog vyn
        # bara upp `devices.token`, där nyparkopplade telefoner har sitt
        # installations-id -- inte hemligheten. Registreringen svarade då
        # `unknown_device`, push-token sparades aldrig, och en betald,
        # godkänd telefon i en aktiv bil fick aldrig en enda notis.
        # Hittat på en riktig telefon 2026-09-21.
        from fleet.access import device_for_token

        device, credential, _how = device_for_token(device_header)
        if device is None:
            return _json(request, {"error": "unknown_device"}, status=404)
        updates = {"last_seen_at": now}
        if push_token:
            updates["push_token"] = push_token
        if user_id:
            updates["user_id"] = user_id
            member = (
                CompanyMember.objects.filter(user_id=user_id, status="active")
                .order_by("created_at")
                .first()
            )
            if member is not None:
                updates["company_id"] = member.company_id
        Device.objects.filter(id=device.id).update(**updates)
        device.refresh_from_db()
        return _json(
            request,
            {
                "ok": True,
                "device_id": str(device.id),
                # En parkopplad telefon har sin hemlighet redan; att skicka
                # installations-id:t här hade kunnat skriva över den i en
                # klient som sparar det den får.
                "device_token": device_header if credential is not None else device.token,
                "company_id": str(device.company_id),
                "user_id": str(device.user_id) if device.user_id else None,
                "last_seen_at": now.isoformat(),
                "linked": "existing_device",
            },
        )

    # 2) Inloggad ägare/admin utan förartoken: upsert via installation_id.
    if not user_id:
        return _json(request, {"error": "login_required"}, status=401)
    if not installation_id or len(installation_id) < 8:
        return _json(request, {"error": "installation_id_required"}, status=400)

    member = (
        CompanyMember.objects.filter(user_id=user_id, status="active")
        .order_by("created_at")
        .first()
    )
    if member is None:
        return _json(request, {"error": "no_company"}, status=403)

    company_id = member.company_id
    ent = entitlement_for_request(request)
    display_label = f"{label} ({platform})" if platform else label

    device = Device.objects.filter(token=installation_id).first()
    if device is None:
        # Samma FCM-token på en annan rad (kontobyte på samma telefon):
        # flytta pushen hit så gamla kontot inte väcks.
        if push_token:
            Device.objects.filter(push_token=push_token).exclude(
                token=installation_id
            ).update(push_token=None)
        device = Device.objects.create(
            id=uuid.uuid4(),
            company_id=company_id,
            token=installation_id,
            label=display_label,
            kind="owner_app",
            push_token=push_token,
            notify_prefs={},
            created_at=now,
            user_id=user_id,
            last_seen_at=now,
        )
        linked = "created"
    else:
        if push_token:
            Device.objects.filter(push_token=push_token).exclude(
                id=device.id
            ).update(push_token=None)
        Device.objects.filter(id=device.id).update(
            company_id=company_id,
            user_id=user_id,
            push_token=push_token or device.push_token,
            last_seen_at=now,
            label=display_label,
            kind=device.kind or "owner_app",
        )
        linked = "updated"

    # auth.users.last_sign_in_at uppdateras av Supabase Auth vid login.
    # Här speglar vi sessionen på devices.last_seen_at för push/debug.
    return _json(
        request,
        {
            "ok": True,
            "device_id": str(device.id),
            "device_token": installation_id,
            "company_id": str(company_id),
            "user_id": user_id,
            "last_seen_at": now.isoformat(),
            "entitled": bool(ent),
            "entitlement_reason": ent.reason,
            "linked": linked,
        },
    )


# --- Lokal utvecklings-hjälp: lista enheter + skicka test-FCM --------------


@require_GET
def push_devices(request):
    """
    Lista enheter med (eller utan) FCM-token. Bara DEBUG -- annars vore det
    en katalog över alla telefoner i produktion.
    """
    from django.conf import settings

    if not settings.DEBUG:
        return _json(request, {"error": "debug_only"}, status=403)

    from billing.models import Device

    rows = []
    for d in Device.objects.all().order_by("-created_at")[:100]:
        rows.append(
            {
                "id": str(d.id),
                "label": d.label,
                "kind": d.kind,
                "token": d.token,
                "has_push": bool(d.push_token),
                "push_token_prefix": (d.push_token or "")[:16] or None,
                "company_id": str(d.company_id) if d.company_id else None,
                "user_id": str(d.user_id) if d.user_id else None,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
        )
    return _json(request, {"devices": rows, "count": len(rows)})


@csrf_exempt
@require_POST
def push_send(request):
    """
    Skicka en testnotis till en vald enhet. DEBUG-only. Använder samma
    FCM-väg som push_cycle, så en lokal nyckel i .env räcker.
    """
    from django.conf import settings

    if not settings.DEBUG:
        return _json(request, {"error": "debug_only"}, status=403)

    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return _json(request, {"error": "invalid_json"}, status=400)

    from billing.fcm import get_access_token, load_service_account, send_push
    from billing.models import Device

    device_id = body.get("device_id")
    device_token = body.get("device_token")
    title = (body.get("title") or "TaxiTips test").strip()[:120]
    text = (body.get("body") or "Testnotis från pipeline-viz").strip()[:400]

    device = None
    if device_id:
        device = Device.objects.filter(id=device_id).first()
    elif device_token:
        device = Device.objects.filter(token=device_token).first()
    if device is None:
        return _json(request, {"error": "device_not_found"}, status=404)
    if not device.push_token:
        return _json(
            request,
            {
                "error": "no_push_token",
                "hint": "Öppna appen på telefonen och tillåt notiser först.",
                "device": {"id": str(device.id), "label": device.label},
            },
            status=400,
        )

    sa = load_service_account(settings.FIREBASE_SERVICE_ACCOUNT_JSON or "")
    if not sa:
        return _json(
            request,
            {
                "error": "no_service_account",
                "hint": "Sätt FIREBASE_SERVICE_ACCOUNT_JSON i taxitips-backend/.env",
            },
            status=503,
        )

    access = get_access_token(sa)
    result = send_push(
        sa,
        access,
        token=device.push_token,
        title=title,
        body=text,
        data={"source": "pipeline_viz", "kind": "test"},
    )
    return _json(
        request,
        {
            "ok": result.get("ok") is True,
            "fcm": result,
            "device": {
                "id": str(device.id),
                "label": device.label,
                "has_push": True,
            },
        },
        status=200 if result.get("ok") else 502,
    )
