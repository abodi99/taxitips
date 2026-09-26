"""
Återställer ett testbolags telefoner till "inloggad administratör, ingen
telefon kopplad" -- så att flödet "Kör bilen själv med den här telefonen" kan
provas igen utan att någon loggar ut, spärrar och klistrar in koder för hand.

    manage.py reset_phone_pairing --company "jsjjdd"
    manage.py reset_phone_pairing --company "jsjjdd" --stuck-on TEST01

Vad som görs, för varje telefon i bolaget:

* aktiva godkännanden avslutas (`revoke_reason = "test_reset"`) och öppna
  pass stängs,
* telefonens hemlighet återkallas. Appen har kvar den, men servern känner
  inte längre igen den och faller tillbaka på ägarens inloggning -- samma
  läge som innan telefonen någonsin kopplades,
* körområdet (`notify_prefs`: län, kommuner) töms.

`--stuck-on PLATE` återskapar dessutom felet från 2026-09-26: telefonen får ett
öppet pass på en bil i ETT ANNAT bolag, som om den flyttats utan att det gamla
släppts. Då går det att se att appen ändå får rätt län.

**Bara testbolag.** Vägrar röra ett bolag som någon gång betalat
(`had_successful_payment`): det här tar bort förarnas åtkomst, och en riktig
kund ska inte kunna råka ut för det av ett skrivfel. `--dry-run` visar vad som
skulle hända.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from billing.models import Company, Device
from fleet import audit, licensing, sessions
from fleet.models import (
    DeviceApproval,
    DeviceCredential,
    License,
    Subscription,
    Vehicle,
    VehicleSession,
)


class Command(BaseCommand):
    help = "Återställer ett testbolags telefoner så att parkopplingen kan provas igen."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Bolagets namn, exakt.")
        parser.add_argument(
            "--stuck-on", default="",
            help="Regnummer i ett ANNAT bolag att lämna telefonen fast på (återskapar felet).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, company: str, stuck_on: str, dry_run: bool, **options):
        matches = list(Company.objects.filter(name=company))
        if len(matches) != 1:
            raise CommandError(f"{len(matches)} bolag heter {company!r}; ange ett unikt namn.")
        target = matches[0]
        subscription = Subscription.objects.filter(company_id=target.id).first()
        if subscription is not None and subscription.had_successful_payment:
            raise CommandError(f"{company!r} har betalat. Vägrar röra en riktig kund.")

        devices = list(Device.objects.filter(company_id=target.id))
        if not devices:
            raise CommandError(f"{company!r} har inga telefoner att återställa.")

        stuck_license = None
        if stuck_on:
            plate = licensing.normalize_plate(stuck_on)
            vehicle = Vehicle.objects.filter(plate=plate).exclude(company_id=target.id).first()
            if vehicle is None:
                raise CommandError(f"Ingen bil {plate} i ett annat bolag.")
            stuck_license = License.objects.filter(
                assignments__vehicle=vehicle, assignments__ended_at__isnull=True,
                status__in=[License.Status.ACTIVE, License.Status.TRIAL],
            ).first()
            if stuck_license is None:
                raise CommandError(f"{plate} har ingen aktiv licens.")

        now = timezone.now()
        for device in devices:
            approvals = DeviceApproval.objects.filter(
                device_id=device.id, status=DeviceApproval.Status.ACTIVE
            )
            sessions_open = VehicleSession.objects.filter(device_id=device.id, ended_at__isnull=True)
            credentials = DeviceCredential.objects.filter(device_id=device.id, revoked_at__isnull=True)
            self.stdout.write(
                f"{device.label} ({device.id}): {approvals.count()} godkännanden, "
                f"{sessions_open.count()} öppna pass, {credentials.count()} nycklar"
            )
            if dry_run:
                continue
            with transaction.atomic():
                sessions_open.update(ended_at=now, ended_reason="test_reset")
                approvals.update(
                    status=DeviceApproval.Status.REPLACED, revoked_at=now, revoke_reason="test_reset"
                )
                credentials.update(revoked_at=now, revoke_reason="test_reset")
                prefs = dict(device.notify_prefs or {})
                prefs.update({"counties": [], "municipalities": [], "regions": [], "cities": []})
                Device.objects.filter(id=device.id).update(notify_prefs=prefs)
                if stuck_license is not None:
                    _leave_stuck(device, stuck_license, now)
                audit.record(
                    "test_pairing_reset", company_id=target.id, actor_kind="system",
                    subject_type="device", subject_id=device.id,
                    detail={"stuck_on": stuck_on or None},
                )

        if dry_run:
            self.stdout.write("Torrkörning: ingenting ändrat.")
        else:
            self.stdout.write(self.style.SUCCESS(
                "Klart. Öppna appen som administratör och välj en bil -> "
                "'Kör bilen själv med den här telefonen'."
            ))


def _leave_stuck(device: Device, license: License, now) -> None:
    """Felet från 2026-09-26: ett öppet pass på ett annat bolags bil."""
    vehicle = sessions.current_vehicle(license)
    VehicleSession.objects.filter(license=license, ended_at__isnull=True).update(
        ended_at=now, ended_reason="test_reset"
    )
    approval = DeviceApproval.objects.create(
        company_id=license.company_id, device_id=device.id, license=license, vehicle=vehicle,
        label="test_reset", approved_at=now,
    )
    VehicleSession.objects.create(
        company_id=license.company_id, license=license, vehicle=vehicle, device_id=device.id,
        approval=approval, started_at=now, last_seen_at=now,
    )

