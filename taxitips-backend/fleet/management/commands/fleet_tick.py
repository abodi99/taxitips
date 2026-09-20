"""
Den tidsstyrda delen av kundlivscykeln.

**Klockan är inte sanningen.** Åtkomsten avgörs vid varje anrop av serverns
UTC-tid mot periodens fält (fleet/access.company_window) -- inte av att det
här kommandot har kört. Ett tick som uteblir kan alltså inte ge någon extra
åtkomst, bara försena en påminnelse och en städning (§9).

Vad det gör:

* Verkställer väntande ändringar vars tid har passerat.
* Avslutar prov som löpt ut -- utan debitering, eftersom en kortfri
  provperiod aldrig övergår till betalning utan order (§8).
* Stoppar löpande förnyelse när betalningsfristen gått ut, så att nya
  månadsfordringar inte fortsätter växa efter avstängning (§8).
* Förfaller gamla ansökningar och parkopplingskoder.
* Skickar utkorgen (bara om en sändare är konfigurerad).
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import Company
from fleet import notifications, orders, trials
from fleet.models import (
    JoinRequest,
    PairingCode,
    PendingChange,
    Subscription,
    SubscriptionStatus,
    Trial,
)


class Command(BaseCommand):
    help = "Verkställer väntande ändringar, avslutar prov och stoppar förnyelser."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        dry = options["dry_run"]
        report = {
            "pending_applied": 0, "trials_ended": 0, "trials_warned": 0,
            "renewals_stopped": 0, "codes_expired": 0, "requests_expired": 0,
        }

        # 1) Väntande ändringar. Ett bolag i taget, så att en trasig rad inte
        # stoppar de andra.
        due_companies = (
            PendingChange.objects.filter(
                status=PendingChange.Status.PENDING, effective_at__lte=now
            )
            .values_list("company_id", flat=True)
            .distinct()
        )
        for company_id in list(due_companies):
            if dry:
                report["pending_applied"] += 1
                continue
            try:
                applied = orders.apply_pending_changes(company_id, now=now)
                report["pending_applied"] += len(applied)
            except Exception as exc:
                self.stderr.write(f"{company_id}: kunde inte verkställa: {exc}")

        # 2) Prov som löpt ut. Utan beställning avslutas de utan debitering.
        for trial in Trial.objects.filter(status=Trial.Status.ACTIVE, ends_at__lte=now):
            if not dry:
                trials.end_trial(trial, reason="trial_period_over", converted=False, now=now)
            report["trials_ended"] += 1

        # 3) Påminnelse tre dagar före provslut.
        soon = now + timedelta(days=3)
        for trial in Trial.objects.filter(
            status=Trial.Status.ACTIVE, ends_at__gt=now, ends_at__lte=soon
        ):
            if not dry:
                company = Company.objects.filter(id=trial.company_id).first()
                notifications.trial_ending(
                    trial.company_id, (company.email if company else ""), trial
                )
            report["trials_warned"] += 1

        # 4) Betalningsfrist som gått ut -> stoppa den löpande förnyelsen.
        for subscription in Subscription.objects.filter(
            status=SubscriptionStatus.PAST_DUE, grace_until__lt=now,
            renewal_stopped_at__isnull=True,
        ):
            if not dry:
                orders.stop_renewal(subscription, reason="grace_period_expired", now=now)
            report["renewals_stopped"] += 1

        # Förfallen period utan frist alls (första felet efter gratisprov):
        # samma stopp, men utan fristen som mellansteg.
        for subscription in Subscription.objects.filter(
            status=SubscriptionStatus.PAST_DUE, grace_until__isnull=True,
            renewal_stopped_at__isnull=True, current_period_end__lt=now,
        ):
            if not dry:
                orders.stop_renewal(subscription, reason="no_grace_after_trial", now=now)
            report["renewals_stopped"] += 1

        # 5) Städning av kortlivade koder och ansökningar.
        expired_codes = PairingCode.objects.filter(
            status=PairingCode.Status.PENDING, expires_at__lte=now
        )
        report["codes_expired"] = expired_codes.count()
        if not dry:
            expired_codes.update(status=PairingCode.Status.REVOKED)

        expired_requests = JoinRequest.objects.filter(
            status=JoinRequest.Status.PENDING, expires_at__lte=now
        )
        report["requests_expired"] = expired_requests.count()
        if not dry:
            expired_requests.update(status=JoinRequest.Status.EXPIRED, resolved_at=now)

        # 6) Utkorgen. Utan konfigurerad sändare skrivs raderna men skickas inte.
        outbox = {"sent": 0, "skipped": "dry_run"} if dry else notifications.send_pending()

        self.stdout.write(
            " ".join(f"{key}={value}" for key, value in report.items())
            + f" outbox={outbox}"
        )
