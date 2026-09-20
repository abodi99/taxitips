"""
Kalibrering och analys (P2): hur väl tipsen, notiserna och AIS-pilotens kajtider
håller, mätt mot det som faktiskt hände.

Rapporten flyttar inga trösklar själv. Den visar underlaget och säger rakt ut när
det är för tunt för att flytta något; en ändring av thresholds.py görs för hand,
med rapporten som belägg.

Underlaget:

* **Feedback** (🚕 kör dit, 👍 fick körning, 👎 ingen kund) per regel och per
  poängband. Träffkvoten är 👍 / (👍 + 👎); 🚕 är avsikt, inte utfall.
* **Notisutkorgen**: status, försök och tid från köad till skickad.
* **AIS-anlöp** (maritime.FerryCall): förvarning (första uppskattning till kaj) och
  fel i första och sista uppskattade kajtid, per terminal och grund.
* **Kombinationslagret**: bara antal just nu. Raderna är härledda och ersätts varje
  minut, så påslagen går inte att mäta i efterhand förrän feedbacken bär regel-id:t.

Gallringen tar tips och deras feedback efter sju dygn (repository.purge_old), så
fönstret är i praktiken högst sju dygn.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter, defaultdict

MIN_SAMPLES = 20
SCORE_BANDS = ((0, 49), (50, 69), (70, 84), (85, 100))
DEFAULT_DAYS = 7


def _minutes(delta: dt.timedelta) -> float:
    return round(delta.total_seconds() / 60, 1)


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def ferry_report(calls) -> list[dict]:
    """Per terminal: anlöp, framme, förvarning och fel i kajtid (minuter; positivt = för sent framme)."""
    by_terminal: dict[str, list] = defaultdict(list)
    for call in calls:
        by_terminal[call.terminal].append(call)
    rows = []
    for terminal, group in sorted(by_terminal.items()):
        arrived = [c for c in group if c.arrived_at]
        lead = [_minutes(c.arrived_at - c.first_estimate_at) for c in arrived if c.first_estimate_at]
        first_error = [_minutes(c.arrived_at - c.first_berth_eta) for c in arrived if c.first_berth_eta]
        last_error = [_minutes(c.arrived_at - c.berth_eta) for c in arrived if c.berth_eta]
        rows.append({
            "terminal": terminal,
            "calls": len(group),
            "arrived": len(arrived),
            "basis": dict(Counter(c.eta_basis or "none" for c in group)),
            "leadMedianMinutes": _median(lead),
            "firstErrorMedianMinutes": _median(first_error),
            "firstErrorP90AbsMinutes": _p90([abs(v) for v in first_error]),
            "lastErrorMedianMinutes": _median(last_error),
            "lastErrorP90AbsMinutes": _p90([abs(v) for v in last_error]),
            "enough": len(arrived) >= MIN_SAMPLES,
        })
    return rows


def feedback_report(rows) -> list[dict]:
    """`rows`: (verdict, rule_id). Träffkvot bara där 👍 + 👎 räcker."""
    by_rule: dict[str, Counter] = defaultdict(Counter)
    for verdict, rule_id in rows:
        by_rule[rule_id or "okänd"][verdict] += 1
    out = []
    for rule_id, counts in sorted(by_rule.items(), key=lambda kv: -sum(kv[1].values())):
        outcomes = counts["fare"] + counts["empty"]
        out.append({
            "rule": rule_id,
            "heading": counts["heading"],
            "fare": counts["fare"],
            "empty": counts["empty"],
            "fareRate": round(counts["fare"] / outcomes, 2) if outcomes else None,
            "enough": outcomes >= MIN_SAMPLES,
        })
    return out


def score_band_report(rows) -> list[dict]:
    """`rows`: (verdict, demand_score). Underlaget för NOTIFY_SCORE_FLOOR."""
    out = []
    for low, high in SCORE_BANDS:
        counts = Counter(v for v, score in rows if low <= (score or 0) <= high)
        outcomes = counts["fare"] + counts["empty"]
        out.append({
            "band": f"{low}-{high}",
            "fare": counts["fare"],
            "empty": counts["empty"],
            "fareRate": round(counts["fare"] / outcomes, 2) if outcomes else None,
            "enough": outcomes >= MIN_SAMPLES,
        })
    return out


def push_report(deliveries) -> dict:
    """`deliveries`: (status, attempts, created_at, sent_at)."""
    status = Counter()
    attempts = Counter()
    delays = []
    for state, tries, created_at, sent_at in deliveries:
        status[state] += 1
        attempts[tries] += 1
        if sent_at and created_at:
            delays.append(round((sent_at - created_at).total_seconds(), 1))
    total = sum(status.values())
    return {
        "total": total,
        "byStatus": dict(status),
        "attempts": {str(k): v for k, v in sorted(attempts.items())},
        "sentMedianSeconds": _median(delays),
        "sentP90Seconds": _p90(delays),
        "expiredShare": round(status["expired"] / total, 2) if total else None,
    }


def conclusions(feedback: list[dict], bands: list[dict], push: dict, ferry: list[dict], floor: int) -> list[str]:
    """Slutsatser i klartext. Säger hellre "för lite underlag" än gissar."""
    notes = []
    outcomes = sum(r["fare"] + r["empty"] for r in feedback)
    if outcomes < MIN_SAMPLES:
        notes.append(
            f"För lite feedback ({outcomes} utfall, minst {MIN_SAMPLES} behövs) för att flytta "
            f"NOTIFY_SCORE_FLOOR ({floor}) eller någon regels poäng."
        )
    else:
        for band in bands:
            if band["enough"] and band["fareRate"] is not None:
                notes.append(f"Poäng {band['band']}: träffkvot {band['fareRate']} på {band['fare'] + band['empty']} utfall.")
    if push["total"] == 0:
        notes.append("Inga notiser i utkorgen i fönstret: leveranskedjan är inte mätt (Firebase saknas lokalt).")
    elif push["expiredShare"]:
        notes.append(f"{int(push['expiredShare'] * 100)} % av notiserna gick ut innan de skickades.")
    arrived = sum(r["arrived"] for r in ferry)
    if arrived == 0:
        notes.append("Inga AIS-anlöp med faktisk kajtid: iland-fönstret (+10/+45 min) är okalibrerat.")
    elif arrived < MIN_SAMPLES:
        notes.append(f"{arrived} AIS-anlöp med faktisk kajtid: för få för att flytta iland-fönstret.")
    return notes


def build(now: dt.datetime | None = None, days: int = DEFAULT_DAYS) -> dict:
    from django.utils import timezone

    from core import thresholds
    from core.models import OpportunityFeedback, PushDelivery
    from maritime.models import FerryCall

    now = now or timezone.now()
    since = now - dt.timedelta(days=days)
    feedback_rows = list(
        OpportunityFeedback.objects.filter(created_at__gte=since)
        .values_list("verdict", "opportunity__rule_id", "opportunity__demand_score")
    )
    feedback = feedback_report((v, rule) for v, rule, _ in feedback_rows)
    bands = score_band_report([(v, score) for v, _, score in feedback_rows])
    push = push_report(
        PushDelivery.objects.filter(created_at__gte=since).values_list("status", "attempts", "created_at", "sent_at")
    )
    ferry = ferry_report(FerryCall.objects.filter(started_at__gte=since))
    return {
        "window": {"from": since.isoformat(), "to": now.isoformat(), "days": days},
        "minSamples": MIN_SAMPLES,
        "feedback": feedback,
        "scoreBands": bands,
        "push": push,
        "ferry": ferry,
        "notes": conclusions(feedback, bands, push, ferry, thresholds.NOTIFY_SCORE_FLOOR),
    }
