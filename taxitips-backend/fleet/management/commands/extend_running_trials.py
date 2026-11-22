"""
Förläng alla väntande och pågående prov till provmånaden.

    manage.py extend_running_trials              # bara listan, inget ändras
    manage.py extend_running_trials --apply      # förläng
    manage.py extend_running_trials --to-days 30 --apply

Engångskörning för ägarens beslut 2026-11-22 (provet 7 -> 30 dagar). Ett pågående
prov får slutet `started_at + to_days`; ett väntande prov får `planned_days =
to_days`. Varje förlängning går genom `trials.extend_trial`, så att den loggas
som `trial_extended` med skäl, precis som när en säljare förlänger.

Hoppar över:
* prov som redan är minst så långa (en säljare har förlängt dem),
* prov där kunden redan beställt med sparat kort (`commerce.has_active_trial_commit`):
  Stripe har ett eget `trial_end` för dem, och att bara flytta vårt slutdatum hade
  gett två olika svar på när första dragningen sker. De listas för hand.

Kan köras flera gånger: ett prov som redan förlängts hoppas över.
"""

from __future__ import annotations

import math
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from fleet import commerce, trials
from fleet.models import Trial

REASON = "Provet blev en månad med allt öppet (ägarens beslut 2026-11-22)."


def plan_for(trial: Trial, to_days: int, now) -> tuple[str, int]:
    """(beslut, dagar att lägga till). Beslutet är "extend" eller ett skäl att låta bli."""
    if commerce.has_active_trial_commit(trial.company_id):
        return "skip_committed", 0
    if trial.status == Trial.Status.PENDING:
        current = trial.planned_days or trials.TRIAL_DAYS
        if current >= to_days:
            return "skip_long_enough", 0
        return "extend", to_days - current
    if not (trial.started_at and trial.ends_at):
        return "skip_no_dates", 0
    target = trial.started_at + timedelta(days=to_days)
    if trial.ends_at >= target:
        return "skip_long_enough", 0
    base = max(trial.ends_at, now)
    if target <= base:
        return "skip_long_enough", 0
    return "extend", math.ceil((target - base).total_seconds() / 86400)


class Command(BaseCommand):
    help = "Förlänger väntande och pågående prov till provmånaden (standard: visar bara listan)."

    def add_arguments(self, parser):
        parser.add_argument("--to-days", type=int, default=trials.TRIAL_DAYS,
                            help="Provets nya längd i dagar (standard: TRIAL_DAYS).")
        parser.add_argument("--apply", action="store_true",
                            help="Förläng. Utan flaggan skrivs bara listan ut.")

    def handle(self, *args, **options):
        now = timezone.now()
        to_days = options["to_days"]
        apply = options["apply"]
        counts: dict[str, int] = {}
        for trial in Trial.objects.filter(
            status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE]
        ).order_by("created_at"):
            decision, days = plan_for(trial, to_days, now)
            counts[decision] = counts.get(decision, 0) + 1
            line = (
                f"{decision:18} company={trial.company_id} trial={trial.id} "
                f"status={trial.status} ends={trial.ends_at:%Y-%m-%d %H:%M}"
                if trial.ends_at else
                f"{decision:18} company={trial.company_id} trial={trial.id} "
                f"status={trial.status} planned={trial.planned_days}"
            )
            if decision != "extend":
                self.stdout.write(line)
                continue
            if not apply:
                self.stdout.write(f"{line} +{days}d")
                continue
            # extend_trial tar bolagets senaste öppna prov; bara ett får vara öppet.
            if trials.active_trial(trial.company_id).id != trial.id:
                counts["skip_not_latest"] = counts.get("skip_not_latest", 0) + 1
                self.stdout.write(f"{line} hoppas över: inte bolagets senaste prov")
                continue
            extended = trials.extend_trial(
                trial.company_id, days, reason=REASON, actor_user_id=None,
                actor_kind="system", now=now,
            )
            after = (
                f"ends={extended.ends_at:%Y-%m-%d %H:%M}" if extended.ends_at
                else f"planned={extended.planned_days}"
            )
            self.stdout.write(f"{line} +{days}d -> {after}")
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "inga öppna prov"
        mode = "förlängt" if apply else "plan (inget ändrat, kör med --apply)"
        self.stdout.write(f"{mode}: {summary}")
