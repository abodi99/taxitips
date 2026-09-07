"""
Hämtar järnvägsstörningar och skriver dem som tips.

Kör så här:
    python manage.py poll_rail            # en cykel
    python manage.py poll_rail --dry-run  # visa utan att skriva
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from core.repository import upsert_opportunities, upsert_source_events
from core.scoring import classify
from core.sources.trafikverket_rail import TrafikverketRail


class Command(BaseCommand):
    help = "Hämtar och poängsätter järnvägsstörningar från Trafikverket"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        key = settings.TRAFIKVERKET_API_KEY
        if not key:
            self.stderr.write("TRAFIKVERKET_API_KEY saknas")
            return

        alerts = TrafikverketRail(key).fetch()
        if not alerts:
            self.stdout.write("inga störningar just nu")
            return

        assessed = [(a, classify(a)) for a in alerts]

        if options["dry_run"]:
            for a, r in sorted(assessed, key=lambda p: -p[1].score):
                self.stdout.write(f"  {r.score:3}  {r.tier:22} {a.header[:56]}")
            self.stdout.write(f"\n{len(alerts)} störningar (inget skrevs)")
            return

        # Källhändelserna först: tipsen citerar deras id:n, och det är den
        # kopplingen förarens förklaringspanel bygger på.
        source_ids = upsert_source_events([
            {
                "source": "trafikverket_rail",
                "external_id": a.external_id,
                "mode": "train",
                "active_from": a.active_from,
                "active_to": a.active_to,
                "raw": json.dumps({
                    "header": a.header, "description": a.description,
                    "station": a.station, "train": a.train,
                    "cancelled": a.cancelled,
                    "departure_at": a.departure_at.isoformat() if a.departure_at else None,
                    "next_departure_minutes": a.next_departure_minutes,
                    "is_last_departure": a.is_last_departure,
                    "operator": a.operator, "information_owner": a.information_owner,
                    "destination": a.destination, "cause": a.cause,
                    "web_link": a.web_link or None, "web_link_name": a.web_link_name or None,
                    "has_replacement": a.has_replacement,
                    "replacement_mode": a.replacement_mode,
                    "replacement_note": a.replacement_note,
                }, ensure_ascii=False),
                "lat": a.lat, "lon": a.lon,
            }
            for a in alerts
        ])

        written = upsert_opportunities([
            {
                "external_id": a.external_id,
                "kind": "transit",
                "mode": "train",
                "severity_tier": r.tier,
                "level": "high" if r.score >= 60 else "medium",
                "title": a.header,
                "summary": a.description,
                "lat": a.lat, "lon": a.lon,
                "h3_index": "",
                "places": json.dumps([a.station], ensure_ascii=False),
                "region": "rail",
                "start_time": a.active_from,
                "end_time": a.active_to,
                "demand_score": r.score,
                "confidence": r.confidence,
                "reasons": json.dumps(r.reasons, ensure_ascii=False),
                "rule_id": r.rule_id,
                "source_event_ids": json.dumps(
                    [source_ids[a.external_id]] if a.external_id in source_ids else []
                ),
            }
            for a, r in assessed
        ])

        spread = sorted({r.score for _, r in assessed}, reverse=True)
        self.stdout.write(self.style.SUCCESS(
            f"skrev {written} tips | poängnivåer: {spread}"
        ))
