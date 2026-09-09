"""
Kör push-steget en gång, för hand.

    python manage.py push_cycle --dry-run   # vem hade fått vad, och varför inte
    python manage.py push_cycle             # skicka på riktigt

`--dry-run` är inte bara en säkerhetsspärr utan huvudanvändningen under
utveckling: den svarar på frågan som annars kräver att man läser loggar
efter att en notis uteblivit -- *vilken* grind stoppade den, för *vilken*
enhet. Varje avvisad enhet listas med sitt skäl (`type_off:line_paused`,
`region_not_chosen:sl`, `notifications_off`, ...).

Utan FIREBASE_SERVICE_ACCOUNT_JSON går bara --dry-run. Det är avsiktligt
inte ett fel: hela urvalslogiken går att prova, och går att testa, utan ett
Firebase-konto.
"""

from django.core.management.base import BaseCommand

from core.notify import plan_cycle, run_push_cycle


class Command(BaseCommand):
    help = "Skickar FCM-notiser för nya, notisvärda tips."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Visa vad som skulle skickas, och varför enheter valdes bort.",
        )
        parser.add_argument(
            "--simulate",
            action="store_true",
            help=(
                "Kör hela vägen men skicka ingenting: notishistoriken fylls, "
                "notified_at sätts. För att prova notislistan lokalt utan Firebase."
            ),
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            plan = plan_cycle()
            if not plan:
                self.stdout.write("Inga kandidater. Inget att skicka.")
                return
            for item in plan:
                self.stdout.write(
                    self.style.MIGRATE_HEADING(
                        f"\n[{item['score']}] {item['title']}"
                    )
                )
                self.stdout.write(f"  {item['body'] or '(ingen sammanfattning)'}")
                self.stdout.write(
                    f"  tier={item['severity_tier']} region={item['region']} "
                    f"places={item['places'] or '—'}"
                )
                for r in item["recipients"]:
                    self.stdout.write(self.style.SUCCESS(f"  → {r['label']}"))
                for r in item["rejected"]:
                    self.stdout.write(f"  ✗ {r['label']}: {r['reason']}")
            total = sum(len(i["recipients"]) for i in plan)
            self.stdout.write(
                f"\n{len(plan)} kandidater, {total} notiser skulle skickas. "
                "Inget har skickats och inget har markerats som notifierat."
            )
            return

        result = run_push_cycle(simulate=options["simulate"])
        if options["simulate"]:
            self.stdout.write(
                self.style.WARNING(
                    "SIMULERING: inget skickades. Besluten, push_delivery-raderna "
                    "och notified_at är däremot riktiga."
                )
            )
        self.stdout.write(str(result))
