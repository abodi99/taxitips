"""
Delad bedömnings- och skriv-pipeline för textbaserade transitlarm
(Trafiklab/SL/Västtrafik).

Varje källas poll_*.py-kommando hämtar och normaliserar sina egna larm, men
bedömning, platsupplösning och skrivning är identisk oavsett källa -- det
är hela poängen med den delade klassificerarkedjan (core.taxi_relevance /
core.mode / core.text_scoring). Extraherad hit efter att ha skrivits ut
likadant tre gånger.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Sequence

from django.db.models import Q
from django.utils import timezone

from core import places_ai, taxi_context, tip_text
from core.alternatives import alternative_from_text
from core.compensation import compensation_signal
from core.geo import REGION_ANCHOR, resolve_coords
from core.models import Opportunity, SeverityTier, SourceEvent
from core.repository import upsert_opportunities, upsert_source_events
from core.sources.smhi import nearest_weather
from core.taxi_relevance import enrich_alert
from core.text_scoring import (
    _MONTHS,
    Assessment,
    classify_transit_alert,
    departure_clock,
    departure_date,
    stated_next_departure_clock,
)

Assessed = tuple[dict, dict, Assessment, float | None, float | None, str]


def stated_next_departure(alert: dict, now: datetime) -> tuple[datetime, int] | None:
    """
    "Nästa avgång … klockan 15:53" i källans egen text -> (tidpunkt, väntan i
    minuter). Väntan mäts från den inställda avgången när texten anger den, som
    för järnvägen (core/scoring.py): det är väntan resenären står inför, och den
    får inte dra iväg medan tiden går. Utan avgångstid mäts den från nu. None när
    texten inte säger något, eller när tiden redan har passerat.
    """
    text = f"{alert.get('header') or ''} {alert.get('description') or ''}"
    stated = stated_next_departure_clock(text)
    if not stated:
        return None
    (hour, minute), rest = stated
    day = timezone.localtime(alert.get("active_from") or now)
    dated = departure_date(text, day.date())
    if dated:
        day = day.replace(year=dated.year, month=dated.month, day=dated.day)
    next_at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    cancelled = departure_clock(rest)
    if cancelled:
        reference = day.replace(hour=cancelled[0], minute=cancelled[1], second=0, microsecond=0)
        if next_at < reference:
            # 23:50 inställd, nästa 05:10: nästa går i morgon bitti.
            next_at += timedelta(days=1)
    else:
        reference = timezone.localtime(now)
    minutes = round((next_at - reference).total_seconds() / 60)
    if minutes < 0 or minutes > 24 * 60:
        return None
    return next_at, minutes

# En enstaka inställd avgång är över för resenären när nästa har gått. Utan
# tidtabell vet vi inte när, men tre kvart efter den inställda avgången står
# ingen kvar och väntar på just den.
SINGLE_DEPARTURE_LIFETIME = timedelta(minutes=45)


def single_departure_time(alert: dict, result: Assessment, now: datetime) -> datetime | None:
    """Klockslaget för en enstaka inställd avgång ("kl 16:59"), eller None."""
    if not result.rule_id.endswith(".single_departure"):
        return None
    text = f"{alert.get('header') or ''} {alert.get('description') or ''}"
    clock = departure_clock(text)
    if not clock:
        return None
    day = timezone.localtime(alert.get("active_from") or now)
    # "Vy Tåg 382, 7 oktober klockan 06:14": avgången är den 7:e, inte den dag
    # meddelandet publicerades.
    dated = departure_date(text, day.date())
    if dated:
        day = day.replace(year=dated.year, month=dated.month, day=dated.day)
    return day.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)


# En inställd avgång längre fram syns först en stund före avgången -- inte från
# det att trafikbolaget publicerade den (ibland dagar i förväg).
SINGLE_DEPARTURE_LEAD = timedelta(minutes=60)

_WEEKDAY_OPT = r"(?:(?:måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag)(?:en)?(?:\s+den)?\s+)?"
_MONTH_PAT = "|".join(_MONTHS)
_PLANNED_START_RE = re.compile(
    r"(?:"
    r"\bkommande\s*:[^\n.]*?\b(?P<d1>\d{1,2})(?:\s*[–-]\s*\d{1,2})?\s+(?P<m1>" + _MONTH_PAT + r")"
    r"|\b(?:från(?:\s+och\s+med)?|fr\.?\s*o\.?\s*m\.?)\s+" + _WEEKDAY_OPT + r"(?P<d2>\d{1,2})(?:\s*[–-]\s*\d{1,2})?\s+(?P<m2>" + _MONTH_PAT + r")"
    r"|^\s*" + _WEEKDAY_OPT + r"(?P<d3>\d{1,2})(?:\s*[–-]\s*\d{1,2})?\s+(?P<m3>" + _MONTH_PAT + r")"
    r"|\b(?P<d4>\d{1,2})\s*[–-]\s*\d{1,2}\s+(?P<m4>" + _MONTH_PAT + r")"
    r")\b",
    re.IGNORECASE,
)


def planned_start_time(alert: dict, now: datetime) -> datetime | None:
    """
    Starttid för planerade arbeten längre fram ("Kommande: ... 10–15 oktober",
    "Från lördag 10 oktober ..."). Publiceras ofta dagar i förväg med active_from
    satt till publiceringstiden.
    """
    import datetime as _dt

    ref = timezone.localtime(alert.get("active_from") or now)
    today = ref.date()
    for part in (alert.get("header") or "", alert.get("description") or ""):
        match = _PLANNED_START_RE.search(part)
        if not match:
            continue
        day_str = match.group("d1") or match.group("d2") or match.group("d3") or match.group("d4")
        month_str = match.group("m1") or match.group("m2") or match.group("m3") or match.group("m4")
        if not day_str or not month_str:
            continue
        day, month = int(day_str), _MONTHS.index(month_str.lower()) + 1
        for year in (today.year, today.year + 1):
            try:
                candidate = _dt.date(year, month, day)
            except ValueError:
                break
            if (candidate - today).days > -183:
                if candidate > today:
                    return ref.replace(
                        year=candidate.year, month=candidate.month, day=candidate.day,
                        hour=0, minute=0, second=0, microsecond=0,
                    )
                break
    return None


def start_time_for(alert: dict, result: Assessment, now: datetime):
    """Källans starttid, men en framtida enstaka avgång eller planerat arbete börjar först när det gäller."""
    start = alert.get("active_from")
    departure = single_departure_time(alert, result, now)
    if departure and departure - SINGLE_DEPARTURE_LEAD > (start or now):
        return departure - SINGLE_DEPARTURE_LEAD
    planned = planned_start_time(alert, now)
    if planned and (start is None or planned > start):
        return planned
    return start


def affected_time(alert: dict, result: Assessment, now: datetime) -> datetime:
    """
    När störningen drabbar resenären -- tiden omständigheterna räknas mot.

    En enstaka avgång har sitt klockslag i texten ("kl 16:59"). Annars gäller
    nu för en pågående störning, och starttiden för en som ligger framåt.
    """
    departure = single_departure_time(alert, result, now)
    if departure:
        return departure
    start = alert.get("active_from")
    return max(start, now) if start else now


def end_time_for(alert: dict, result: Assessment, when: datetime) -> datetime | None:
    """Källans sluttid, men aldrig längre än störningen faktiskt håller kvar folk."""
    end = alert.get("active_to")
    if result.rule_id.endswith(".single_departure"):
        cap = when + SINGLE_DEPARTURE_LIFETIME
        return min(end, cap) if end else cap
    return end


def assess(alerts: list[dict]) -> list[Assessed]:
    """alert -> (alert, taxi, Assessment, lat, lon, precision) för varje larm."""
    now = timezone.now()
    classified = []
    for alert in alerts:
        # Samma fält som SL fyller från sin tidtabell (sl.enrich_next_departures):
        # då tar glappregeln i classify_transit_alert över, och kortet visar tiden.
        if alert.get("next_departure_minutes") is None:
            stated = stated_next_departure(alert, now)
            if stated:
                alert["next_departure_at"], alert["next_departure_minutes"] = stated
        taxi = enrich_alert(alert)
        result = classify_transit_alert(alert, taxi)
        if result.mode != "road":
            # Linje, hållplats och klockslag ur texten (core/tip_text.py), och
            # textens nyckel: samma meddelande under flera external_id läses en gång.
            alert["_rule_key"] = tip_text.text_key(alert.get("header"), alert.get("description"))
            alert["_text"] = tip_text.extract(
                alert.get("header"), alert.get("description"),
                route_label=alert.get("route_label"), mode=result.mode,
            )
        classified.append((alert, taxi, result))

    # Modellens sparade läsning för samma text (core/places_ai.py) fyller det
    # reglerna inte hittade -- varje pollrunda, så att den överlever upserten.
    read = places_ai.facts_for(a.get("_rule_key") for a, _t, _r in classified)
    out = []
    for alert, taxi, result in classified:
        facts = read.get(alert.get("_rule_key") or "")
        if facts and alert.get("_text") is not None:
            text = f"{alert.get('header') or ''}\n{alert.get('description') or ''}"
            alert["_text"] = places_ai.merge(alert["_text"], facts, text, mode=result.mode)
        lat, lon, precision = resolve_coords(alert, taxi)
        station = alert["_text"].station if alert.get("_text") is not None else ""
        if station and precision in ("region", "none", "gazetteer"):
            # Hållplatsen där resenärerna står, ur registret och inom länet --
            # aldrig en gissad punkt. Slår gazetteerns längsta namn i texten,
            # som lika gärna kan vara slutmålet.
            hit = tip_text.registry_coords(station, alert.get("region"))
            if hit:
                lat, lon, precision = hit[0], hit[1], "stop"
        out.append((alert, taxi, result, lat, lon, precision))
    return out


def text_factors(alert: dict, result: Assessment) -> list:
    """
    Raderna ur texten som läget börjar med: avgången och förseningen, med
    trafikbolagets egna siffror. Ersätter lägets allmänna förseningsrad när
    texten anger minuterna.
    """
    tf = alert.get("_text")
    situation = list(result.factors)
    if tf is None:
        return situation
    detail = [
        taxi_context.departure_factor(
            tf.departure_clock, tf.station, cancelled=result.tier == SeverityTier.VEHICLE_CANCELLED,
        ),
        taxi_context.text_delay_factor(tf.delay_minutes, tf.delay_qualifier, result.mode),
    ]
    detail = [f for f in detail if f is not None]
    if tf.delay_minutes:
        situation = [f for f in situation if f.text not in taxi_context.GENERIC_DELAY_TEXTS]
    return [*detail, *situation]


def _reasons_with_precision(result: Assessment, precision: str, alert: dict) -> list[str]:
    """
    "exact"/"place"/"gazetteer" are all real, named locations -- no extra
    reason needed. "region" is a city-centre stand-in and MUST say so in
    the driver-facing explanation panel (and, today, in the pipeline-viz
    popup that already renders `reasons`), never look like a precise pin.
    """
    if precision != "region":
        return result.reasons
    city = REGION_ANCHOR.get(str(alert.get("region") or "").lower(), "regionen")
    return [*result.reasons, f"plats: ungefärlig ({city}s centrum)"]


def _weather_source_events(region_weather: list[dict]) -> dict[str, str]:
    """
    Vädret får egna source_events, en per punkt. Utan dem kan
    get_opportunity_detail inte visa VARFÖR poängen höjdes -- den panelen
    joinar strikt genom source_event_ids.
    """
    if not region_weather:
        return {}
    return upsert_source_events([
        {
            "source": "smhi",
            "external_id": f"smhi:{w['point']}",
            "mode": "weather",
            "active_from": None,
            "active_to": None,
            "raw": json.dumps(w, ensure_ascii=False),
            "lat": w["lat"],
            "lon": w["lon"],
        }
        for w in region_weather
    ])


def write(
    source: str,
    assessed: list[Assessed],
    region_weather: list[dict] | None = None,
    kind: str = "transit",
    *,
    exclude_regions: Sequence[str] | None = None,
) -> tuple[int, list[int]]:
    """Skriver source_events + opportunities. Returnerar (antal skrivna, poängspridning)."""
    region_weather = region_weather or []
    weather_ids = _weather_source_events(region_weather)

    # Källhändelserna först: tipsen citerar deras id:n, och det är den
    # kopplingen förarens förklaringspanel bygger på.
    source_ids = upsert_source_events([
        {
            "source": source,
            "external_id": alert["id"],
            "mode": result.mode,
            "active_from": alert.get("active_from"),
            "active_to": alert.get("active_to"),
            "raw": json.dumps({
                "header": alert["header"], "description": alert["description"],
                "cause": alert["cause"], "effect": alert["effect"],
                "areas": alert["areas"], "routes": alert["routes"], "stops": alert["stops"],
                "url": alert["url"], "region": alert.get("region"),
                # route_label/direction/journey_departure_at: bara Västtrafik
                # (och route_label även SL) sätter dessa idag -- None/saknas
                # för övriga är korrekt, inte ett fel.
                "route_label": alert.get("route_label"),
                "direction": alert.get("direction"),
                "journey_departure_at": (
                    alert["journey_departure_at"].isoformat()
                    if alert.get("journey_departure_at") else None
                ),
                # Källans egen redaktionella allvarlighet (SL:s
                # importance/influence/urgency, Västtrafiks severity) --
                # tidigare byggd av normalize_deviation()/normalize_situation()
                # men aldrig kopierad hit, så den försvann tyst innan den
                # nådde databasen. None för källor som saknar den (Trafiklab).
                "sl": alert.get("sl"),
                "vt": alert.get("vt"),
                # Samma sak för mode_hint: SL/Västtrafik anger färdsätt
                # strukturellt (se core/mode.py:s modeHint-genväg, som slår
                # nyckelordsgissning), men fältet försvann tyst innan det
                # nådde databasen -- upptäckt när en återuppbyggd alert från
                # lagrad raw-data föll tillbaka på textgissning och missade
                # ett riktigt bussfärdsätt.
                "mode_hint": alert.get("mode_hint"),
                # Vägsträckan som polyline. Bara Trafikverkets vägkälla
                # sätter den; None för alla andra är rätt, inte ett fel.
                "geometry": alert.get("geometry"),
            }, ensure_ascii=False),
            "lat": lat, "lon": lon,
        }
        for alert, _taxi, result, lat, lon, _precision in assessed
    ])

    def _row(alert, taxi, result, lat, lon, precision):
        reasons = _reasons_with_precision(result, precision, alert)
        has_alt, alt_note = alternative_from_text(
            alert.get("header"), alert.get("description")
        )

        # Lagstadgad förseningsersättning -- rör bara motivering/fältet
        # nedan, aldrig demand_score/severity_tier. Se core/compensation.py.
        comp = compensation_signal(alert, result.mode)
        if comp:
            per = (
                " per resenär" if comp.get("per_person") is True
                else (" per resa" if comp.get("per_person") is False else "")
            )
            reasons = [
                *reasons,
                f"ersättning: rätt till taxi upp till {comp['cap_kr']} kr{per} (Lag 2015:953)",
            ]

        # Läge + omständigheter (core/taxi_context.py): tid på dygnet för den
        # drabbade avgången, ersättningsrätt, väder. Aldrig på väg -- vägpoängen
        # är kapad lågt med avsikt (thresholds.ROAD_SCORE_CAP) -- och aldrig på
        # "ignore": omständigheter får förstärka ett läge, aldrig skapa ett.
        source_event_ids = [source_ids[alert["id"]]] if alert["id"] in source_ids else []
        now = timezone.now()
        when = affected_time(alert, result, now)
        end_time = end_time_for(alert, result, when)
        if kind == "road" or (result.tier == SeverityTier.IGNORE and result.mode == "road"):
            score, level, factors = result.score, None, []
        elif result.tier == SeverityTier.IGNORE:
            # "Övrigt" bär också en rad: varför det inte är en körning.
            score, level = result.score, None
            factors = [taxi_context.ignore_factor(result.reasons).as_dict()]
        else:
            weather = nearest_weather(lat, lon, region_weather)
            situation = result.situation()
            situation.factors = text_factors(alert, result)
            outcome = taxi_context.assess(
                situation, when=when, weather=weather,
                compensation=comp, has_alternative=has_alt,
            )
            score, level, factors = outcome.score, outcome.level, outcome.factors
            reasons = [*reasons, *outcome.reasons]
            if taxi_context.weather_factor(weather) is not None:
                weather_id = weather_ids.get(f"smhi:{weather['point']}")
                if weather_id:
                    source_event_ids.append(weather_id)
        if level is None:
            level = taxi_context.final_level(score, False, has_alt, result.confidence)

        tf = alert.get("_text")
        places = taxi.get("places") or (tf.places if tf is not None else [])
        return {
            "external_id": alert["id"],
            "kind": kind,
            # Linjen och hållplatsen föraren ser först (core/tip_text.py).
            "line": (tf.line if tf is not None else "")[:60],
            "station": (tf.station if tf is not None else "")[:120],
            "destination": (tf.destination if tf is not None else "")[:200],
            "rule_key": alert.get("_rule_key"),
            "mode": result.mode,
            "severity_tier": result.tier,
            # Styrkan räknas här, med full kännedom om läge och
            # omständigheter. Flödet och notiserna läser den härifrån.
            "level": level,
            "factors": json.dumps(factors, ensure_ascii=False),
            "title": alert["header"],
            "summary": alert["description"],
            "lat": lat,
            "lon": lon,
            "h3_index": "",
            # Ortlistans platser när texten nämner en ort eller knutpunkt, annars
            # hållplatserna ur texten -- ordagranna (core/tip_text.py).
            "places": json.dumps(places, ensure_ascii=False),
            # NULL, inte "", när marknaden är okänd -- get_smart_alerts gör
            # coalesce(region,'skane') för tips utan koordinat, och "" hade
            # matchat ingen marknad alls. Se Opportunity.region.
            "region": alert.get("region") or None,
            "start_time": start_time_for(alert, result, now),
            "end_time": end_time,
            "demand_score": score,
            "confidence": result.confidence,
            "reasons": json.dumps(reasons, ensure_ascii=False),
            "rule_id": result.rule_id,
            "source_event_ids": json.dumps(source_event_ids),
            "compensation_eligible": bool(comp),
            "compensation_amount_kr": comp["cap_kr"] if comp else None,
            "compensation_per_person": comp.get("per_person") if comp else None,
            # Textkällornas avvikelsetext bär ingen tidtabell -- "Linje 4 är
            # inställd" säger inget om när nästa går. NULL = "vet inte",
            # vilket är sant och skiljer sig från 0 ("nästa går nu").
            #
            # SL är undantaget: poll_sl slår upp nästa avgång på
            # /v1/sites/{id}/departures och lägger den på larmet innan det
            # kommer hit (se sl.enrich_next_departures). Därför läses fältet
            # från larmet i stället för att nollas.
            "next_departure_minutes": alert.get("next_departure_minutes"),
            # En enstaka avgång har sitt klockslag i texten; för en hel linje
            # finns ingen avgång att peka på.
            "departure_at": single_departure_time(alert, result, now),
            "next_departure_at": alert.get("next_departure_at"),
            # Sätts aldrig av en textkälla: departures-endpointen svarar
            # bara för ett fönster framåt, så "inga fler avgångar" betyder
            # "inga inom två timmar" -- inte "sista turen idag".
            "is_last_departure": False,
            # Ersättningstrafik däremot STÅR ofta i texten. Signalen har
            # använts för att sätta tier sedan tidigare (text_scoring.py:s
            # _has_stated_alternative) men kastades sedan bort -- föraren
            # fick se poängen, inte skälet.
            "has_alternative": has_alt,
            "alternative_note": alt_note,
        }

    written = upsert_opportunities([_row(*row) for row in assessed])

    # Avsluta tips som inte längre finns kvar i källans aktiva flöde: många
    # operatörer sätter ett långt slutdatum i larmet och plockar i stället bort
    # larmet ur flödet när störningen är över.
    now = timezone.now()
    current_ids = [alert["id"] for alert, *_ in assessed]
    source_ext_ids = SourceEvent.objects.filter(source=source).values("external_id")
    stale_qs = (
        Opportunity.objects.filter(kind=kind, external_id__in=source_ext_ids)
        .filter(Q(end_time__gt=now) | Q(end_time__isnull=True))
        .exclude(external_id__in=current_ids)
    )
    if exclude_regions:
        stale_qs = stale_qs.exclude(region__in=list(exclude_regions))
    stale_qs.update(end_time=now, expired_reason="source_removed", updated_at=now)

    # Återställ cachad AI-bedömning direkt i skrivsteget så att osäkra tips
    # inte pendlar tillbaka till regelvärden mellan review_uncertain-rundorna.
    if kind == "transit" and current_ids:
        from core.genkit import apply_cached

        uncertain_ids = [
            alert["id"]
            for alert, _t, result, _lat, _lon, _p in assessed
            if result.confidence == "low" and result.tier != SeverityTier.IGNORE
        ]
        if uncertain_ids:
            for opp in Opportunity.objects.filter(external_id__in=uncertain_ids, confidence="low"):
                apply_cached(opp)

    spread = sorted({r.score for _a, _t, r, _lat, _lon, _p in assessed}, reverse=True)
    return written, spread


def dry_run_lines(assessed: list[Assessed]) -> list[str]:
    return [
        f"  {result.score:3}  {result.tier:22} {alert['header'][:56]}"
        for alert, _taxi, result, _lat, _lon, _precision in sorted(assessed, key=lambda p: -p[2].score)
    ]
