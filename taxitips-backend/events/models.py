"""
Evenemang från externa källor, som senast kända läge.

Källoberoende med avsikt: Ticketmaster är första källan, inte den enda. En rad
per (source, external_id).

Ticketmasters villkor tillåter lagring bara "for reasonable periods in order
to provide the service", och ett evenemang ska bort inom 24 timmar om ägaren
begär det. Därför raderas passerade evenemang ett dygn efter slut, och
evenemang som försvunnit ur källan efter 24 timmar -- se events/ingest.py.
"""

from __future__ import annotations

from django.db import models


class Event(models.Model):
    source = models.CharField(max_length=30, db_index=True)
    external_id = models.CharField(max_length=120)
    name = models.CharField(max_length=300)
    url = models.URLField(max_length=500, blank=True, help_text="Länken tillbaka till källan.")
    source_status = models.CharField(
        max_length=30, blank=True,
        help_text="Källans statuskod: onsale, offsale, cancelled, postponed, rescheduled.",
    )

    category = models.CharField(max_length=20, db_index=True, help_text="Nyckel i events.timing.CATEGORY_LABELS.")
    segment = models.CharField(max_length=60, blank=True)
    genre = models.CharField(max_length=60, blank=True)
    sub_genre = models.CharField(max_length=60, blank=True)

    start_date = models.DateField(db_index=True, help_text="Lokalt datum. Finns även när tiden inte är satt.")
    start_at = models.DateTimeField(null=True, blank=True, help_text="NULL = starttiden inte satt (TBA).")
    time_known = models.BooleanField(default=True)
    end_at = models.DateTimeField(null=True, blank=True, db_index=True)
    end_basis = models.CharField(max_length=10, help_text="source, estimated eller unknown.")
    end_note = models.CharField(max_length=200, blank=True, help_text="Hur sluttiden togs fram, i klartext.")
    multi_day = models.BooleanField(default=False)

    venue_id = models.CharField(max_length=60, blank=True)
    venue_name = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    postal_code = models.CharField(max_length=20, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    region = models.CharField(
        max_length=30, null=True, blank=True, db_index=True,
        help_text="Marknad (sl, vt, skane ...) från koordinaten. NULL, aldrig tom sträng, när den är okänd.",
    )

    # Bara PredictHQ har dem, och de sparas bara när källan får lagras (events/rights.py).
    # Förutsägelser, inte räkningar -- visas avrundade.
    attendance = models.PositiveIntegerField(null=True, blank=True, help_text="PredictHQ phq_attendance: förutsagt antal besökare.")
    rank = models.PositiveSmallIntegerField(null=True, blank=True)
    local_rank = models.PositiveSmallIntegerField(null=True, blank=True)

    hidden_reason = models.CharField(max_length=200, blank=True, help_text="Tomt = visas för föraren. Annars varför inte.")
    raw = models.JSONField(default=dict, blank=True, help_text="Källans svar, nedbantat till det som förklarar raden.")

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()
    missing_since = models.DateTimeField(
        null=True, blank=True,
        help_text="Källan slutade lista evenemanget. Döljs direkt, raderas efter 24 timmar.",
    )

    class Meta:
        db_table = "events"
        ordering = ["start_date", "start_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="events_source_external_id"),
        ]

    def __str__(self) -> str:
        return f"{self.start_date} {self.name} ({self.venue_name or self.city})"
