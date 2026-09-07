"""
Data-endpoint för pipeline-visualiseraren.

Visualiseraren är byggd mot Supabase-REST. Django-datan ligger i en vanlig
Postgres utan REST-lager, så tjänsten serverar samma JSON-form själv --
det är billigare än att lägga PostgREST framför en databas som bara har en
läsare.
"""

from collections import Counter

from django.db.models import Count
from django.http import JsonResponse
from django.utils import timezone

from core.models import Opportunity, RailAssessment, ScoringRule, SourceEvent


def pipeline(request):
    """Samma form som viz/server.js:s /api/pipeline."""
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
        if o.demand_score >= 50:
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
        "totals": {
            "sourceEvents": SourceEvent.objects.count(),
            "opportunities": Opportunity.objects.count(),
            "gtfsStops": 0, "gtfsDepartures": 0,
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
        "driverViews": {},
        "traced": traced,
    }, json_dumps_params={"ensure_ascii": False})
