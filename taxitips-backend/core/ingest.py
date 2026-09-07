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

from core.geo import REGION_ANCHOR, resolve_coords
from core.repository import upsert_opportunities, upsert_source_events
from core.taxi_relevance import enrich_alert
from core.text_scoring import Assessment, classify_transit_alert

Assessed = tuple[dict, dict, Assessment, float | None, float | None, str]


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


def write(source: str, assessed: list[Assessed]) -> tuple[int, list[int]]:
    """Skriver source_events + opportunities. Returnerar (antal skrivna, poängspridning)."""
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
            }, ensure_ascii=False),
            "lat": lat, "lon": lon,
        }
        for alert, _taxi, result, lat, lon, _precision in assessed
    ])

    written = upsert_opportunities([
        {
            "external_id": alert["id"],
            "kind": "transit",
            "mode": result.mode,
            "severity_tier": result.tier,
            "level": "high" if result.score >= 60 else "medium",
            "title": alert["header"],
            "summary": alert["description"],
            "lat": lat,
            "lon": lon,
            "h3_index": "",
            "places": json.dumps(taxi.get("places") or [], ensure_ascii=False),
            "region": alert.get("region") or "",
            "start_time": alert.get("active_from"),
            "end_time": alert.get("active_to"),
            "demand_score": result.score,
            "confidence": result.confidence,
            "reasons": json.dumps(_reasons_with_precision(result, precision, alert), ensure_ascii=False),
            "rule_id": result.rule_id,
            "source_event_ids": json.dumps(
                [source_ids[alert["id"]]] if alert["id"] in source_ids else []
            ),
        }
        for alert, taxi, result, lat, lon, precision in assessed
    ])

    spread = sorted({r.score for _a, _t, r, _lat, _lon, _p in assessed}, reverse=True)
    return written, spread


def dry_run_lines(assessed: list[Assessed]) -> list[str]:
    return [
        f"  {result.score:3}  {result.tier:22} {alert['header'][:56]}"
        for alert, _taxi, result, _lat, _lon, _precision in sorted(assessed, key=lambda p: -p[2].score)
    ]
