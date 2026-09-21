"""
Skickar en testnotis till ett bolags telefoner -- genom samma mottagargrind
som riktiga notiser (fleet/push_gate.py).

Push-cykeln skickar bara för NYA störningar. Mitt i natten finns det kanske
inga, och då går det inte att se om notiserna alls fungerar. Det här kommandot
svarar på just den frågan, utan att vänta på en störning:

    manage.py send_test_push --company "Abbe Test AB"

Varje telefon får ett skäl när den hoppas över (ingen push-token, ingen aktiv
bil, spärrad), så svaret "0 skickade" alltid går att förstå.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from billing import fcm
from billing.models import Company, Device
from fleet.push_gate import can_receive


class Command(BaseCommand):
    help = "Skickar en testnotis till ett bolags godkända telefoner."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Bolagets namn.")
        parser.add_argument("--title", default="TaxiTips")
        parser.add_argument("--body", default="Testnotis: notiserna fungerar.")

    def handle(self, *args, **options):
        company = Company.objects.filter(name=options["company"]).first()
        if company is None:
            raise CommandError(f"Hittar inget bolag som heter {options['company']!r}.")

        service_account = fcm.load_service_account(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        if not service_account:
            raise CommandError(
                "FIREBASE_SERVICE_ACCOUNT_JSON saknas i den här containern."
            )
        access_token = fcm.get_access_token(service_account)

        sent = 0
        for device in Device.objects.filter(company_id=company.id):
            label = device.label or str(device.id)[:8]
            if not device.push_token:
                self.stdout.write(f"{label}: hoppar över -- ingen push-token")
                continue
            # Samma grind som riktiga notiser. En tom ögonblicksbild betyder
            # ett tips utan län, så det är sessionen, godkännandet och
            # perioden som prövas -- inte länet.
            verdict = can_receive(device, {})
            if not verdict.ok:
                self.stdout.write(f"{label}: hoppar över -- {verdict.reason}")
                continue
            result = fcm.send_push(
                service_account, access_token, token=device.push_token,
                title=options["title"], body=options["body"],
                data={"kind": "test"},
            )
            status = "skickad" if result.get("ok") else f"FEL {result.get('status')}"
            self.stdout.write(f"{label}: {status}")
            sent += int(bool(result.get("ok")))

        self.stdout.write(self.style.SUCCESS(f"{sent} testnotis(er) skickade."))
