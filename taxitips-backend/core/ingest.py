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
from datetime import datetime, timedelta

from django.utils import timezone

from core import taxi_context
from core.alternatives import alternative_from_text
from core.compensation import compensation_signal
from core.geo import REGION_ANCHOR, resolve_coords
from core.models import SeverityTier
from core.repository import upsert_opportunities, upsert_source_events
from core.sources.smhi import nearest_weather
from core.taxi_relevance import enrich_alert
from core.text_scoring import Assessment, classify_transit_alert, departure_clock

Assessed = tuple[dict, dict, Assessment, float | None, float | None, str]

# En enstaka inställd avgång är över för resenären när nästa har gått. Utan
# tidtabell vet vi inte när, men tre kvart efter den inställda avgången står
# ingen kvar och väntar på just den.
SINGLE_DEPARTURE_LIFETIME = timedelta(minutes=45)


def single_departure_time(alert: dict, result: Assessment, now: datetime) -> datetime | None:
    """Klockslaget för en enstaka inställd avgång ("kl 16:59"), eller None."""
    if not result.rule_id.endswith(".single_departure"):
        return None
    clock = departure_clock(f"{alert.get('header') or ''} {alert.get('description') or ''}")
    if not clock:
        return None
    day = timezone.localtime(alert.get("active_from") or now)
    return day.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)


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
    out = []
    for alert in alerts:
        taxi = enrich_alert(alert)
        result = classify_transit_alert(alert, taxi)
        lat, lon, precision = resolve_coords(alert, taxi)
        out.append((alert, taxi, result, lat, lon, precision))
    return out


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
        if result.tier == SeverityTier.IGNORE or kind == "road":
            score, level, factors = result.score, None, []
        else:
            weather = nearest_weather(lat, lon, region_weather)
            outcome = taxi_context.assess(
                result.situation(), when=when, weather=weather,
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

        return {
            "external_id": alert["id"],
            "kind": kind,
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
            "places": json.dumps(taxi.get("places") or [], ensure_ascii=False),
            # NULL, inte "", när marknaden är okänd -- get_smart_alerts gör
            # coalesce(region,'skane') för tips utan koordinat, och "" hade
            # matchat ingen marknad alls. Se Opportunity.region.
            "region": alert.get("region") or None,
            "start_time": alert.get("active_from"),
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

    spread = sorted({r.score for _a, _t, r, _lat, _lon, _p in assessed}, reverse=True)
    return written, spread


def dry_run_lines(assessed: list[Assessed]) -> list[str]:
    return [
        f"  {result.score:3}  {result.tier:22} {alert['header'][:56]}"
        for alert, _taxi, result, _lat, _lon, _precision in sorted(assessed, key=lambda p: -p[2].score)
    ]
