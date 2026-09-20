"""
Data-endpoint för pipeline-visualiseraren.

Visualiseraren är byggd mot Supabase-REST. Django-datan ligger i en vanlig
Postgres utan REST-lager, så tjänsten serverar samma JSON-form själv --
det är billigare än att lägga PostgREST framför en databas som bara har en
läsare.
"""

from collections import Counter

from django.db import connection
from django.db.models import Count, Max
from django.http import JsonResponse
from django.utils import timezone

from core import thresholds
from core.api import feed_for
from core.coverage import coverage_rows
from core.geo import REGION_ANCHOR
from core.models import (
    Opportunity,
    RegionCompensationRule,
    RailAssessment,
    ScoringRule,
    SourceEvent,
    SourceStatus,
    StopArea,
    Station,
)

# Källorna pipelinen SKA ha. Listan är hårdkodad med avsikt: en källa som
# slutat leverera försvinner ur `source_events` helt, och en vy som bara
# räknar det som finns kan därför aldrig visa att något saknas. Det var
# precis så Trafiklabs slut-på-kvot-fel gick obemärkt förbi -- tabellen såg
# ut som en lugn trafikdag.
EXPECTED_SOURCES = [
    ("trafikverket_rail", "Trafikverket järnväg", "Tåg: inställda och försenade avgångar, med tidtabell"),
    ("trafiklab", "Trafiklab GTFS-RT", "Regionala trafikhuvudmän utanför SL/VT"),
    ("sl", "SL", "Stockholm: tunnelbana, pendeltåg, spårvagn, buss"),
    ("vt", "Västtrafik", "Göteborg: spårvagn, buss, båt, tåg"),
    ("trafikverket", "Trafikverket väg", "Olyckor, avstängningar, köer och vägarbeten"),
    ("smhi", "SMHI väder", "Nederbörd och vind -- skärper en signal, skapar aldrig en"),
    ("swedavia", "Swedavia FlightInfo", "Flyg: ankomstvågor på ARN/GOT/MMX sent på kvällen"),
    ("aisstream", "AISStream fartyg", "Färjor: passagerarfartyg som lägger till i åtta hamnar (WebSocket)"),
    ("ticketmaster", "Ticketmaster evenemang", "Konserter, teater och sport i hela Sverige, med plats och sluttid"),
]

# Probe-positioner för avsnitt 7. Tre marknader med olika egenskaper: Skåne
# (fallback-regionen), Stockholm (störst volym) och Göteborg (spårvagn).
DRIVER_PROBES = {
    "Malmö": (55.605, 13.0038),
    "Stockholm": (59.3196, 18.0725),
    "Göteborg": (57.7089, 11.9746),
}


def _source_health(now) -> list[dict]:
    """En rad per förväntad källa: lever den, hur färsk är den, och vad sa den?"""
    stored = {
        r["source"]: r
        for r in SourceEvent.objects.values("source").annotate(
            n=Count("id"), last=Max("fetched_at")
        )
    }
    statuses = {s.source: s for s in SourceStatus.objects.all()}
    tips = dict(
        Opportunity.objects.filter(end_time__gt=now)
        .values_list("region")
        .annotate(n=Count("id"))
        .values_list("region", "n")
    )
    # region-nyckeln per källa: rail-tips skrivs som "rail", vägtips saknar
    # region, SL/VT skriver sin egen. Bara en etikett i vyn, ingen logik.
    region_key = {"trafikverket_rail": "rail", "sl": "sl", "vt": "vt"}
    # Swedavia passar inte i region_key: samma källa skriver tre olika
    # regioner (ARN->sl, GOT->vt, MMX->skane), så den räknas på `kind` i
    # stället -- "flight" skrivs inte av någon annan källa.
    flight_tips = Opportunity.objects.filter(kind="flight", end_time__gt=now).count()
    # Samma sak för färjorna: aisstream skriver sl, vt, skane, blekinge och gotland.
    ferry_tips = Opportunity.objects.filter(kind="ferry", end_time__gt=now).count()

    out = []
    for key, label, what in EXPECTED_SOURCES:
        st = statuses.get(key)
        rows = stored.get(key)
        from core import thresholds

        age = success_age = None
        if st:
            age = int((now - st.checked_at).total_seconds() // 60)
            if st.last_success_at:
                success_age = int((now - st.last_success_at).total_seconds() // 60)
        # Färskheten räknas från senaste LYCKADE hämtning mot källans gräns:
        # checked_at flyttas även av ett fel. Se core/pipeline_health.py.
        max_age = thresholds.SOURCE_MAX_AGE_MINUTES.get(key)

        if st and not st.ok:
            state = "fel"
        elif st is None and not rows:
            state = "saknas"
        elif age is None:
            state = "okänd"
        elif max_age is None:
            state = "färsk" if age <= 10 else "gammal" if age <= 120 else "inaktuell"
        elif success_age is None:
            # Körd men aldrig hämtad, t.ex. utan nyckel.
            state = "inaktuell"
        elif success_age <= max_age:
            state = "färsk"
        elif success_age <= 3 * max_age:
            state = "gammal"
        else:
            state = "inaktuell"

        out.append({
            "key": key,
            "label": label,
            "what": what,
            "state": state,
            "ok": bool(st.ok) if st else None,
            "message": (st.message or "") if st else "",
            "events": st.events if st else 0,
            "written": st.written if st else 0,
            "durationMs": st.duration_ms if st else 0,
            "checkedAt": st.checked_at.isoformat() if st else None,
            "ageMinutes": age,
            "lastSuccessAt": st.last_success_at.isoformat() if st and st.last_success_at else None,
            "lastSuccessAgeMinutes": success_age,
            "maxAgeMinutes": max_age,
            "consecutiveFailures": st.consecutive_failures if st else 0,
            "core": key in thresholds.CORE_SOURCES,
            "storedEvents": (rows or {}).get("n", 0),
            "lastEvent": (rows or {}).get("last").isoformat() if (rows or {}).get("last") else None,
            "activeTips": (
                flight_tips if key == "swedavia"
                else ferry_tips if key == "aisstream"
                else tips.get(region_key.get(key)) if key in region_key
                else None
            ),
            # Källans egen bokföring: per-operatör för Trafiklab, kvoträknaren
            # och kadensen per flygplats för Swedavia. Utan den syns aldrig
            # att en källa håller på att slå i sitt anropstak.
            "detail": (st.detail or {}) if st else {},
        })
    return out


def _next_departure(active: list[Opportunity]) -> dict:
    """
    Transport Gap: hur länge står man kvar innan nästa avgång?

    Bara källor med tidtabell kan svara (Trafikverkets järnväg idag), så
    `known` mot `total` är i sig ett mått på hur långt P1-arbetet kommit --
    inte ett fel som ska döljas.
    """
    with_gap = [o for o in active if o.next_departure_minutes is not None]
    buckets = {"0-30 min": 0, "31-60 min": 0, "1-3 tim": 0, "över 3 tim": 0}
    for o in with_gap:
        m = o.next_departure_minutes
        if m <= 30:
            buckets["0-30 min"] += 1
        elif m <= 60:
            buckets["31-60 min"] += 1
        elif m <= 180:
            buckets["1-3 tim"] += 1
        else:
            buckets["över 3 tim"] += 1

    last = [o for o in active if o.is_last_departure]
    top = sorted(
        with_gap + [o for o in last if o.next_departure_minutes is None],
        key=lambda o: (-(o.next_departure_minutes or 10**6), -o.demand_score),
    )[:10]
    return {
        "total": len(active),
        "known": len(with_gap),
        "lastDeparture": len(last),
        "buckets": buckets,
        "top": [
            {
                "title": o.title,
                "places": o.places,
                "minutes": o.next_departure_minutes,
                "isLast": o.is_last_departure,
                "score": o.demand_score,
                "tier": o.severity_tier,
            }
            for o in top
        ],
    }


def _compensation_rules() -> list[dict]:
    """
    Lagstadgad förseningsersättning som den ligger i databasen, inte som
    den ligger i ett dokument. Skillnaden är hela poängen: sidan visar det
    pipelinen FAKTISKT använder när den sätter compensation_amount_kr på
    ett tips, så en felaktig siffra syns här i stället för att bara stå
    fel i en motivering en förare läser upp för en resenär.
    """
    return [
        {
            "region": r.region,
            "label": REGION_ANCHOR.get(r.region, r.region),
            "thresholdMinutes": r.threshold_minutes,
            "capKr": r.taxi_cap_kr,
            "perPerson": r.cap_per_person,
            "excludedModes": r.excluded_modes or [],
            "filingDeadlineDays": r.filing_deadline_days,
            "sourceUrl": r.source_url,
            "note": r.note,
            "updatedAt": _iso(r.updated_at),
        }
        for r in RegionCompensationRule.objects.all()
    ]


def _driver_views(now) -> dict:
    """
    Vad en förare faktiskt ser, per marknad -- via samma funktion som
    appens API kallar (core.api.feed_for), inte en efterlikning av den.
    """
    views = {}
    for city, (lat, lon) in DRIVER_PROBES.items():
        feed = feed_for(lat, lon, now)
        rows = feed["alerts"]
        views[city] = {
            "total": len(rows),
            # Väghändelserna ligger i sin egen lista sedan de skildes från
            # tipsflödet -- se core.api.feed_for.
            "roadContext": len(feed["context"]),
            "homeRegion": feed["homeRegion"],
            "top": [
                {
                    "title": r["title"], "mode": r["mode"], "tier": r["severity_tier"],
                    "score": r["demand_score"], "worthIt": r["worth_it_score"],
                    "km": r["distance_km"], "level": r["level"],
                }
                for r in rows[:5]
            ],
            "foreignModes": sum(1 for r in rows if r["mode"] in ("tram", "metro")),
            "pushWorthy": sum(1 for r in rows if r["notify_worthy"]),
        }
    return views


def _register_counts() -> dict:
    """
    Hållplats- och stationsregistren, plus GTFS-tabellerna.

    GTFS-tabellerna ägs av Supabase-migrationerna och har ingen
    Django-modell -- en rå räkning är ärligare än att låtsas att de inte
    finns. Står de på 0 är Next Departure för buss/tunnelbana inte byggt
    än, och det ska synas i vyn i stället för att gissas.
    """
    counts = {
        "stopAreas": StopArea.objects.count(),
        "stopAreasSl": StopArea.objects.filter(operator="sl").count(),
        "stopAreasVt": StopArea.objects.filter(operator="vt").count(),
        "railStations": Station.objects.count(),
        "gtfsStops": 0,
        "gtfsDepartures": 0,
    }
    with connection.cursor() as cur:
        for label, table in (("gtfsStops", "gtfs_stops"), ("gtfsDepartures", "gtfs_stop_departures")):
            try:
                cur.execute(f"select count(*) from {table}")
                counts[label] = cur.fetchone()[0]
            except Exception:
                # Tabellen finns inte i den här databasen -- 0 är rätt svar.
                connection.rollback() if connection.in_atomic_block else None
    return counts


def _events(now) -> dict:
    """Evenemang: kalendern, reglerna och licensvillkoren -- se events/explain.py."""
    from events.explain import build

    return build(now)


def _maritime(now) -> dict:
    """AISStream: tratten, filterreglerna och varje fartygs bedömning -- se maritime/explain.py."""
    from maritime.explain import build

    return build(now)


def _iso(dt):
    return dt.isoformat() if dt else None


def _rail_launch() -> dict:
    row = SourceStatus.objects.filter(source="trafikverket_rail").first()
    detail = (row.detail or {}) if row else {}
    keys = ("window_hours", "cancelled_trains", "cancelled_departures", "delayed_departures", "tip_stations",
            "alerts", "cancelled_alerts", "rows", "pages", "complete")
    robot = detail.get("resrobot") or {}
    return {
        **{key: detail.get(key) for key in keys},
        "resrobot": {
            "month": robot.get("month"), "calls": robot.get("calls"), "budget": robot.get("budget"),
            "run": robot.get("run"), "stops": len(robot.get("stops") or {}),
        },
    }


def _launch(now) -> dict:
    """
    Avsnitt 0b: P0/P1-läget, läst ur samma kod som driften använder -- hälsan som
    /health/pipeline, notisbeslutet som push_cycle --dry-run, körområdena som flödet,
    AIS-pilotens anlöp och evenemangens rättighetsspärr. Ingen egen logik här.
    """
    from collections import Counter

    from django.db import connection

    from core import api as driver_api, areas, calibration, notify, pipeline_health, presence as presence_rules
    from core.models import Combination, DevicePresence, PushDelivery
    from events import ingest as event_ingest
    from events.rights import rights_for
    from maritime.models import FerryCall

    active = Opportunity.objects.filter(end_time__gt=now)
    by_county = dict(
        active.exclude(county_code__isnull=True)
        .values_list("county_code").annotate(n=Count("id")).values_list("county_code", "n")
    )
    plan = notify.plan_cycle(now=now)
    reasons = Counter(r["reason"].split(":")[0] for item in plan for r in item["rejected"])

    pilot_row = SourceStatus.objects.filter(source="aisstream_pilot").first()
    pilot_status = {}
    if pilot_row:
        pilot_status = {
            **(pilot_row.detail or {}),
            "ok": pilot_row.ok,
            "lastSuccessAt": _iso(pilot_row.last_success_at),
            "checkedAt": _iso(pilot_row.checked_at),
        }

    anon_reads_push = None
    try:
        with connection.cursor() as cur:
            cur.execute("select has_table_privilege('anon', 'public.push_delivery', 'SELECT')")
            anon_reads_push = bool(cur.fetchone()[0])
    except Exception:
        pass

    return {
        "health": pipeline_health.evaluate(now),
        "outbox": {
            "byStatus": dict(
                PushDelivery.objects.values_list("status").annotate(n=Count("id")).values_list("status", "n")
            ),
            "candidates": len(plan),
            "wouldSend": sum(len(item["recipients"]) for item in plan),
            "reasons": dict(reasons),
        },
        "areas": {
            "active": active.count(),
            "withCounty": sum(by_county.values()),
            "withMunicipality": active.exclude(municipality_code__isnull=True).count(),
            "byCounty": [
                {"code": code, "name": areas.COUNTY_NAMES.get(code, code), "n": n}
                for code, n in sorted(by_county.items(), key=lambda kv: -kv[1])
            ],
        },
        "pilot": {
            "status": pilot_status,
            "calls": [
                {
                    "ship": call.ship_name or str(call.mmsi),
                    "terminal": call.terminal,
                    "berthEta": _iso(call.berth_eta),
                    "firstBerthEta": _iso(call.first_berth_eta),
                    "basis": call.eta_basis,
                    "distanceKm": call.distance_km,
                    "arrivedAt": _iso(call.arrived_at),
                }
                for call in FerryCall.objects.order_by("-started_at")[:10]
            ],
        },
        "combinations": {
            "byRule": dict(
                Combination.objects.filter(expires_at__gt=now)
                .values_list("rule_id").annotate(n=Count("id")).values_list("rule_id", "n")
            ),
            "examples": [
                {"rule": c.rule_id, "reason": c.reason, "members": len(c.member_external_ids), "boost": c.boost}
                for c in Combination.objects.filter(expires_at__gt=now).order_by("rule_id", "-boost")[:8]
            ],
        },
        "calibration": calibration.build(now),
        # Järnvägens fullständighet och nästa resa -- se _departures och core/sources/resrobot.py.
        "rail": _rail_launch(),
        # Bara antal: rutorna själva visas aldrig.
        "presence": {
            "onDuty": DevicePresence.objects.filter(expires_at__gt=now).count(),
            "ttlMinutes": int(presence_rules.TTL.total_seconds() // 60),
            "radiusKm": presence_rules.RADIUS_KM,
        },
        "eventRights": [rights_for(source).as_dict() for source in event_ingest.SOURCES],
        "feed": {
            "cacheSeconds": driver_api.FEED_CACHE_SECONDS,
            "contextLimit": thresholds.FEED_CONTEXT_LIMIT,
        },
        "security": {"anonCanReadPushDelivery": anon_reads_push},
    }


def pipeline(request):
    """
    Samma form som viz/server.js:s /api/pipeline. Bara med DEBUG: svaret innehåller alla aktiva
    tips och rå källdata, utan inloggning (CLAUDE.md, regel 1).
    """
    from django.conf import settings

    if not settings.DEBUG:
        return JsonResponse({"error": "not_found"}, status=404)
    now = timezone.now()
    active = list(Opportunity.objects.filter(end_time__gt=now))

    by_region: dict[str, dict] = {}
    for o in active:
        r = by_region.setdefault(
            o.region or "?",
            {"total": 0, "scorable": 0, "pushWorthy": 0, "withCoords": 0,
             "tiers": {}, "modes": {}},
        )
        r["total"] += 1
        if o.severity_tier != "ignore" and o.demand_score > 0:
            r["scorable"] += 1
        if o.demand_score >= thresholds.NOTIFY_SCORE_FLOOR:
            r["pushWorthy"] += 1
        if o.lat is not None:
            r["withCoords"] += 1
        r["tiers"][o.severity_tier] = r["tiers"].get(o.severity_tier, 0) + 1
        if o.mode:
            r["modes"][o.mode] = r["modes"].get(o.mode, 0) + 1

    # Källa + rå payload per aktivt tips -- det som låter kartans popup visa
    # "vilken källa, och vad API:t faktiskt svarade", inte bara betyget.
    # Samma nyckling som `traced` nedan (första source_event_id:t), men för
    # hela `active` i en samlad fråga i stället för en i taget.
    # Keys normalized to str: SourceEvent.id comes back from the ORM as a
    # uuid.UUID, but source_event_ids (a JSONField) stores plain strings --
    # a UUID and its string form hash differently, so a dict keyed by one
    # and looked up by the other misses silently, every time.
    first_se_id = {
        o.id: str(o.source_event_ids[0]) for o in active if o.source_event_ids
    }
    se_by_id = {
        str(se.id): se
        for se in SourceEvent.objects.filter(id__in=set(first_se_id.values()))
    }

    # Senaste Genkit-granskningen per tips, en samlad fråga i stället för
    # en per opportunity. DISTINCT ON är Postgres-specifikt men den här
    # tjänsten kör aldrig mot något annat -- se pipeline_view.py:s egen
    # docstring ("Django-datan ligger i en vanlig Postgres").
    assessment_by_opportunity = {
        a.opportunity_id: a
        for a in RailAssessment.objects
        .filter(opportunity__in=active)
        .order_by("opportunity_id", "-created_at")
        .distinct("opportunity_id")
    }

    def as_dict(o: Opportunity) -> dict:
        se = se_by_id.get(first_se_id.get(o.id))
        assessment = assessment_by_opportunity.get(o.id)
        return {
            "title": o.title, "summary": o.summary, "mode": o.mode,
            "severity_tier": o.severity_tier, "confidence": o.confidence,
            "demand_score": o.demand_score, "reasons": o.reasons,
            "rule_id": o.rule_id, "lat": o.lat, "lon": o.lon,
            "region": o.region, "places": o.places,
            "compensation_eligible": o.compensation_eligible,
            "compensation_amount_kr": o.compensation_amount_kr,
            "next_departure_minutes": o.next_departure_minutes,
            "next_departure_at": _iso(o.next_departure_at),
            "is_last_departure": o.is_last_departure,
            "has_alternative": o.has_alternative,
            "alternative_note": o.alternative_note,
            "kind": o.kind,
            "start_time": o.start_time.isoformat() if o.start_time else None,
            "end_time": o.end_time.isoformat() if o.end_time else None,
            "sourceEvent": {
                "source": se.source, "external_id": se.external_id, "raw": se.raw,
            } if se else None,
            "aiReview": {
                "rule_score": assessment.rule_score,
                "model_score": assessment.model_score,
                "final_score": assessment.final_score,
                "verdict": assessment.verdict,
            } if assessment else None,
        }

    # Ett spårat exempel: tipset med sin råa källhändelse bredvid.
    traced = None
    example = next(
        (o for o in sorted(active, key=lambda x: -x.demand_score)
         if o.severity_tier != "ignore" and o.source_event_ids),
        None,
    )
    if example:
        se = SourceEvent.objects.filter(id=example.source_event_ids[0]).first()
        traced = {
            "opportunity": as_dict(example),
            "sourceEvent": {
                "source": se.source, "external_id": se.external_id,
                "raw": se.raw, "lat": se.lat, "lon": se.lon,
            } if se else None,
        }

    # Poängreglerna -- det som gör bearbetningen läsbar i stället för
    # utspridd i scoring.js.
    rules = [
        {"tier": r.tier, "mode": r.mode or "alla", "condition": r.condition or "—",
         "floor": r.floor, "cap": r.cap, "confidence": r.confidence, "note": r.note}
        for r in ScoringRule.objects.all()
    ]

    # Karta 1 (rådata, färgad efter källa): allt som kommit in innan något
    # slagits samman eller klassificerats -- se pipeline-viz index.html:s
    # avsnitt 8a.
    raw_source_events = [
        {
            "id": str(se.id), "source": se.source, "external_id": se.external_id,
            "lat": se.lat, "lon": se.lon, "raw": se.raw,
            "active_from": se.active_from.isoformat() if se.active_from else None,
            "active_to": se.active_to.isoformat() if se.active_to else None,
        }
        for se in SourceEvent.objects.filter(lat__isnull=False, lon__isnull=False)
    ]

    return JsonResponse({
        "generatedAt": now.isoformat(),
        "supabaseUrl": "Django · lokal Postgres",
        "rawSourceEvents": raw_source_events,
        # Tröskelvärdena med i svaret, så att visualiseraren slutar hålla
        # en egen kopia av 50:an. Se core/thresholds.py.
        "config": thresholds.as_config(),
        "sources": _source_health(now),
        # P0/P1-läget i ett block -- se _launch.
        "launch": _launch(now),
        # Färjorna har egen struktur (ström, inte hämtning; fartyg, inte larm)
        # och får därför ett eget block i stället för att tryckas in i tipslistan.
        "maritime": _maritime(now),
        # Evenemangskalendern -- se events/explain.py.
        "events": _events(now),
        # Län för län: hämtas det något där, och om inte -- är det för att
        # källan saknas eller för att det är lugnt? Se core/coverage.py.
        "coverage": coverage_rows(now),
        "compensation": _compensation_rules(),
        "nextDeparture": _next_departure(active),
        "totals": {
            "sourceEvents": SourceEvent.objects.count(),
            "opportunities": Opportunity.objects.count(),
            **_register_counts(),
            "bySource": dict(
                SourceEvent.objects.values_list("source")
                .annotate(n=Count("source")).values_list("source", "n")
            ),
        },
        "active": [as_dict(o) for o in active],
        "byRegion": by_region,
        "scoringRules": rules,
        "scoreSpread": dict(sorted(
            Counter(o.demand_score for o in active
                    if o.severity_tier != "ignore" and o.demand_score > 0).items(),
            reverse=True,
        )),
        "driverViews": _driver_views(now),
        "traced": traced,
    }, json_dumps_params={"ensure_ascii": False})
