"""
Tar bort data äldre än N dagar.

Svaret på retention-frågan: du behöver inte Firestore för att slippa gammal
data. En delete på schema räcker, och Postgres behåller alla möjligheter
som Firestore saknar -- geo-frågor, arrayer, joins.
"""

from django.core.management.base import BaseCommand

from core.repository import purge_old


class Command(BaseCommand):
    help = "Tar bort opportunities och source_events äldre än N dagar"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        days = options["days"]
        if options["dry_run"]:
            from django.utils import timezone
            from core.models import Opportunity
            cutoff = timezone.now() - timezone.timedelta(days=days)
            n = Opportunity.objects.filter(end_time__lt=cutoff).count()
            self.stdout.write(f"skulle ta bort {n} opportunities (äldre än {days}d)")
            return
        result = purge_old(days=days)
        self.stdout.write(self.style.SUCCESS(
            f"borttaget: {result['opportunities']} opportunities, "
            f"{result['source_events']} source_events"
        ))
        # Appens fel (30 dygn) och klientaktivitet som tystnat (180 dygn).
        # Egna fasta gränser, oberoende av --days: tipsens sju dygn är för
        # kort för en supportfråga som kommer in veckan efter felet. Här och
        # inte i ett eget schema, så att gallringen inte kan glömmas bort när
        # den andra redan körs varje timme (CELERY_BEAT_SCHEDULE "purge-old").
        from fleet import client_activity

        purged = client_activity.purge()
        self.stdout.write(self.style.SUCCESS(
            f"borttaget: {purged['client_errors']} klientfel, "
            f"{purged['client_activity']} tysta klienter"
        ))
