"""
Nattrapporten: hur höll tipsen i går, och vad AI:n gjorde.

Siffrorna räknas här, av koden: AI-anrop och kostnad per syfte, där AI:n och
reglerna var oense, notiser som AI-grinden stoppade, notiser per län och regel,
leveranser och förarnas svar. Språkmodellen (thresholds.AI_MODEL_GATE) får
bara siffrorna och skriver en kort sammanfattning och högst fem förslag på
regeländringar. Förslagen ändrar ingenting automatiskt.

Byggs en gång per dygn för föregående dygn, första körningen efter REPORT_HOUR
(beat "quality-report" varje timme; befintlig rapport för dagen hoppas över).
Utan AI sparas siffrorna ändå, utan sammanfattning.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Abs
from django.utils import timezone
from pydantic import BaseModel, Field

from core import ai_client, thresholds
from core.models import AiCall, Opportunity, OpportunityFeedback, PushDelivery, QualityReport, RailAssessment

log = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Stockholm")
# Efter natten: gårdagens tips har hunnit ta slut och svaren hunnit komma in.
REPORT_HOUR = 5
# Oenighet som är värd att titta på: AI:n och regeln skiljer så mycket.
DISAGREEMENT_POINTS = 20
SAMPLES = 8


class QualityText(BaseModel):
    summary: str = Field(default="", max_length=1200)
    suggestions: list[str] = Field(default_factory=list)


PROMPT = """Du skriver en kort morgonrapport på svenska till ägaren av TaxiTips, en app som
tipsar taxiförare om var resenärer blir stående när kollektivtrafiken störs.

Nedan står gårdagens siffror i JSON. Skriv:
- summary: högst åtta korta rader om hur tipsen och AI:n fungerade i går. Nämn
  bara det siffrorna visar. Inga hälsningar.
- suggestions: högst fem konkreta förslag på regeländringar, vart och ett grundat i
  en siffra eller ett exempel nedan. Föreslå inget som siffrorna inte stöder; tom
  lista om inget sticker ut.

## Siffror
{stats}
"""


def window_for(day) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
    return start, start + timedelta(days=1)


def stats(start: datetime, end: datetime) -> dict:
    calls = AiCall.objects.filter(created_at__gte=start, created_at__lt=end)
    by_purpose = {
        row["purpose"]: {
            "anrop": row["n"],
            "lyckade": row["ok_n"],
            "kostnadKr": round(ai_client.kronor(row["cost"] or 0), 2),
        }
        for row in calls.values("purpose").annotate(
            n=Count("id"), ok_n=Count("id", filter=Q(ok=True)),
            cost=Sum("cost_micro_usd"),
        )
    }

    assessed = RailAssessment.objects.filter(created_at__gte=start, created_at__lt=end)
    big = (
        assessed.annotate(diff=Abs(F("final_score") - F("rule_score")))
        .filter(diff__gte=DISAGREEMENT_POINTS)
        .select_related("opportunity")
        .order_by("-diff")
    )
    events = Counter(
        (facts or {}).get("event_type", "?")
        for facts in assessed.exclude(facts__isnull=True).values_list("facts", flat=True)
    )

    notified = Opportunity.objects.filter(notified_at__gte=start, notified_at__lt=end)
    gate_blocked = notified.extra(where=["reasons::text ilike %s"], params=["%AI stoppade notisen%"])

    return {
        "dygn": start.date().isoformat(),
        "ai": {
            "perSyfte": by_purpose,
            "kostnadKr": round(sum(p["kostnadKr"] for p in by_purpose.values()), 2),
            "manadKr": ai_client.spend(end)["costMonthKr"],
            "budgetKr": thresholds.AI_MONTHLY_BUDGET_KR,
        },
        "granskning": {
            "bedomningar": assessed.count(),
            "hojda": assessed.filter(final_score__gt=F("rule_score")).count(),
            "sankta": assessed.filter(final_score__lt=F("rule_score")).count(),
            "oeniga": big.count(),
            "handelser": dict(events.most_common()),
            "exempel": [
                {
                    "titel": (a.opportunity.title or "")[:90],
                    "regel": a.rule_score,
                    "ai": a.final_score,
                    "lasning": (a.facts or {}).get("event_type"),
                    "varfor": (a.verdict or "")[:120],
                }
                for a in big[:SAMPLES]
            ],
        },
        "notiser": {
            "tips": notified.count(),
            "stoppadeAvAi": gate_blocked.count(),
            "perLan": dict(Counter(notified.values_list("county_code", flat=True)).most_common(8)),
            "perRegel": dict(Counter(notified.values_list("rule_id", flat=True)).most_common(8)),
            "leveranser": {
                row["status"]: row["n"]
                for row in PushDelivery.objects.filter(created_at__gte=start, created_at__lt=end)
                .values("status").annotate(n=Count("id"))
            },
        },
        "forare": {
            row["verdict"]: row["n"]
            for row in OpportunityFeedback.objects.filter(created_at__gte=start, created_at__lt=end)
            .values("verdict").annotate(n=Count("id"))
        },
    }


def build(day, *, summarize: bool = True) -> QualityReport:
    start, end = window_for(day)
    numbers = stats(start, end)
    text, model = QualityText(), ""
    if summarize and not ai_client.unavailable_reason():
        try:
            text = ai_client.generate(
                "report", PROMPT.format(stats=json.dumps(numbers, ensure_ascii=False, indent=1)),
                QualityText, model=thresholds.AI_MODEL_GATE, subject=f"kvalitet:{day.isoformat()}",
            )
            model = thresholds.AI_MODEL_GATE
        except Exception as exc:  # siffrorna sparas ändå
            log.warning("quality_report: sammanfattningen misslyckades: %s", type(exc).__name__)
    report, _ = QualityReport.objects.update_or_create(
        day=day,
        defaults={
            "stats": numbers,
            "summary": text.summary.strip(),
            "suggestions": [s.strip() for s in text.suggestions if s and s.strip()][:5],
            "model": model,
        },
    )
    return report


def run(now=None, *, force: bool = False) -> QualityReport | None:
    """Gårdagens rapport, en gång, efter REPORT_HOUR."""
    local = timezone.localtime(now or timezone.now(), LOCAL_TZ)
    if local.hour < REPORT_HOUR and not force:
        return None
    day = (local - timedelta(days=1)).date()
    if not force and QualityReport.objects.filter(day=day).exists():
        return None
    return build(day)
