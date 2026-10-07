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
            "trials_awaiting_charge": 0, "renewals_stopped": 0,
            "codes_expired": 0, "requests_expired": 0, "stale_orders": 0,
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

        # 2) Prov som löpt ut. Utan sparat kort + commit avslutas utan
        # debitering. Med trial_commit (kort på fil, Stripe trialing) väntar
        # vi på invoice.paid -- annars hade tick och Stripe kappkörts.
        from fleet import commerce

        for trial in Trial.objects.filter(status=Trial.Status.ACTIVE, ends_at__lte=now):
            if commerce.has_active_trial_commit(trial.company_id):
                report["trials_awaiting_charge"] = report.get("trials_awaiting_charge", 0) + 1
                continue
            if not dry:
                trials.end_trial(trial, reason="trial_period_over", converted=False, now=now)
                company = Company.objects.filter(id=trial.company_id).first()
                notifications.trial_ended(
                    trial.company_id, (company.email if company else ""), trial
                )
            report["trials_ended"] += 1

        # 3) Påminnelser före provslut: tre dagar före, och sista dygnet. Varje
        # stadium skickas en gång (nyckeln i utkorgen), fast kommandot körs
        # varje timme.
        soon = now + timedelta(days=3)
        for trial in Trial.objects.filter(
            status=Trial.Status.ACTIVE, ends_at__gt=now, ends_at__lte=soon
        ):
            if not dry:
                company = Company.objects.filter(id=trial.company_id).first()
                stage = "1d" if trial.ends_at <= now + timedelta(days=1) else "3d"
                # Ett mejl per stadium: utan kort det som ber om kortet, med
                # kort den vanliga påminnelsen. Förut gick båda samma timme.
                status = commerce.trial_commit_status(trial.company_id)
                notifications.trial_ending(
                    trial.company_id, (company.email if company else ""), trial,
                    stage=(stage if status["cardOnFile"] else f"card_missing_{stage}"),
                )
            report["trials_warned"] += 1

        # 3b) Tidig påminnelse om saknat kort (~dag 3 av provet).
        card_nudge_from = now - timedelta(days=4)
        card_nudge_to = now - timedelta(days=2)
        for trial in Trial.objects.filter(
            status=Trial.Status.ACTIVE,
            started_at__lte=card_nudge_to,
            started_at__gte=card_nudge_from,
            ends_at__gt=now + timedelta(days=3),
        ):
            if not dry:
                status = commerce.trial_commit_status(trial.company_id)
                if not status["cardOnFile"]:
                    company = Company.objects.filter(id=trial.company_id).first()
                    notifications.trial_ending(
                        trial.company_id, (company.email if company else ""), trial,
                        stage="card_missing",
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

        # 4b) Obetalda ordrar kunden lämnat (stängd Stripe-sida). Annars
        # ligger de kvar som "väntar på betalning" tills någon rensar för hand.
        from fleet import commerce

        if dry:
            from fleet.models import Order
            report["stale_orders"] = Order.objects.filter(
                status=Order.Status.PENDING_PAYMENT,
                created_at__lte=now - orders.REUSE_PENDING_WITHIN,
            ).count()
        else:
            report["stale_orders"] = commerce.abandon_stale_pending_orders(now=now)

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

        # 5b) Bolagsverket igen för prov där registret inte svarade vid
        # registreringen: säljaren ska se det riktiga namnet innan samtalet
        # (fleet/signup_checks.flags). Några per körning, för registrets kvot.
        report["registry_retried"] = 0 if dry else _retry_registry(now)

        # 6) Utkorgen. Utan konfigurerad sändare skrivs raderna men skickas inte.
        outbox = {"sent": 0, "skipped": "dry_run"} if dry else notifications.send_pending()

        self.stdout.write(
            " ".join(f"{key}={value}" for key, value in report.items())
            + f" outbox={outbox}"
        )


REGISTRY_RETRY_PER_TICK = 10


def _retry_registry(now) -> int:
    from fleet import bolagsverket, signup_checks
    from fleet.models import CompanyProfile

    if not bolagsverket.configured():
        return 0
    open_trials = Trial.objects.filter(
        status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE]
    ).values_list("company_id", flat=True)
    done = 0
    for profile in CompanyProfile.objects.filter(
        company_id__in=list(open_trials), country="SE", registry={},
    ).exclude(org_number="")[:REGISTRY_RETRY_PER_TICK]:
        if signup_checks.org_kind(profile.org_number) != "organisation":
            continue
        info = bolagsverket.try_lookup(profile.org_number)
        if info is None:
            break  # registret svarar fortfarande inte; nästa körning
        bolagsverket.apply_to_profile(profile, info, now=now)
        done += 1
    return done
