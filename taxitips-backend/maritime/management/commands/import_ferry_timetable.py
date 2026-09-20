"""
Färjornas tidtabell ur GTFS Sverige 3 statisk -- se maritime/timetable.py.

    python manage.py import_ferry_timetable --zip /sökväg/sweden.zip   # redan hämtad fil, inget anrop
    python manage.py import_ferry_timetable --download --zip /tmp/sweden3.zip
    python manage.py import_ferry_timetable --zip ... --days 3

`--download` hämtar filen med GTFS_SWEDEN3_STATIC_KEY. Nyckeln får 50 hämtningar i månaden
och delas mellan miljöer, så kommandot vägrar hämta igen inom MIN_DOWNLOAD_GAP (20 h)
utan `--force`. Senaste hämtningen står i source_status (`gtfs_sweden3_ferries`).
"""

from __future__ import annotations

import datetime as dt

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.health import polling
from core.models import SourceStatus
from maritime import timetable


class Command(BaseCommand):
    help = "Importerar färjornas planerade anlöp ur GTFS Sverige 3 statisk"

    def add_arguments(self, parser):
        parser.add_argument("--zip", required=True, help="Sökväg till sweden.zip (läses, eller skrivs med --download).")
        parser.add_argument("--download", action="store_true", help="Hämta filen först (räknas mot 50/månad).")
        parser.add_argument("--force", action="store_true", help="Hämta trots att senaste hämtningen är nyare än 20 h.")
        parser.add_argument("--days", type=int, default=2, help="Trafikdagar från i dag.")

    def handle(self, *args, **options):
        now = timezone.now()
        previous = (SourceStatus.objects.filter(source=timetable.SOURCE).values_list("detail", flat=True).first()) or {}
        with polling(timetable.SOURCE) as status:
            downloaded_at = previous.get("downloadedAt")
            if options["download"]:
                self._download(options, previous, now)
                downloaded_at = now.isoformat()
            today = timezone.localtime(now).date()
            days = [today + dt.timedelta(days=i) for i in range(max(1, options["days"]))]
            calls = timetable.read_calls(options["zip"], days)
            written = timetable.replace_calls(calls, days, now)
            status.events = len(calls)
            status.written = written
            status.detail = {
                "downloadedAt": downloaded_at,
                "days": [d.isoformat() for d in days],
                "calls": written,
                "trips": len({c["trip_id"] for c in calls}),
                "stops": len({c["stop_id"] for c in calls}),
                "agencies": sorted({c["agency"] for c in calls}),
            }
        self.stdout.write(
            f"{written} anlöp, {status.detail['trips']} färjeturer vid {status.detail['stops']} färjelägen "
            f"({', '.join(status.detail['days'])})"
        )

    def _download(self, options, previous: dict, now: dt.datetime) -> None:
        key = settings.GTFS_SWEDEN3_STATIC_KEY
        if not key:
            raise CommandError("GTFS_SWEDEN3_STATIC_KEY saknas")
        last = previous.get("downloadedAt")
        if last and not options["force"] and now - dt.datetime.fromisoformat(last) < timetable.MIN_DOWNLOAD_GAP:
            raise CommandError(
                f"Senaste hämtningen {last} är nyare än {timetable.MIN_DOWNLOAD_GAP}; "
                "nyckeln får 50 hämtningar i månaden. Använd --force om det verkligen behövs."
            )
        try:
            with requests.get(timetable.URL, params={"key": key}, stream=True, timeout=120) as response:
                response.raise_for_status()
                with open(options["zip"], "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        handle.write(chunk)
        except requests.RequestException as exc:
            # Aldrig URL:en i felet: nyckeln står i den.
            raise CommandError(f"Hämtningen misslyckades: {type(exc).__name__}") from None
