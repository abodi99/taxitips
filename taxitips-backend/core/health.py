"""
Källhälsa: gick hämtningen igenom, och när?

Skrivet efter att Trafiklabs nyckel tystnade med 429 "exceeded its quota".
Ingenting i systemet visade det. Tabellen `source_events` saknade bara rader
för den källan, vilket ser exakt likadant ut som "inga störningar just nu" --
och den skillnaden är hela skillnaden mellan ett lugnt trafikläge och en
pipeline som slutat fungera.

En rad per källa, senaste tillståndet. Inte en logg: frågan är "fungerar
källan nu?", och ett historiskt svar på den frågan är sällan intressant
nog att betala lagring för.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from django.utils import timezone

log = logging.getLogger(__name__)


class PollResult:
    """Muterbar räknare som poll-kommandot fyller i medan det jobbar."""

    def __init__(self) -> None:
        self.events = 0
        self.written = 0
        self.note = ""
        # Per delkälla, när källan har flera (Trafiklabs operatörer).
        self.detail: dict = {}


@contextmanager
def polling(source: str):
    """
    Kör en hämtning och skriv ner hur det gick.

    Undantag sväljs INTE -- kommandot ska fortfarande fela synligt i
    terminalen och i Celery. Det som ändras är att felet också blir
    läsbart för den som tittar på pipelinen i efterhand.
    """
    from core.models import SourceStatus

    started = time.monotonic()
    result = PollResult()
    try:
        yield result
    except Exception as exc:
        SourceStatus.objects.update_or_create(
            source=source,
            defaults={
                "ok": False,
                # Trafikverkets och Trafiklabs felmeddelanden är långa och
                # upprepar sig per region. Det som betyder något (statuskod
                # och orsak) står först.
                "message": f"{type(exc).__name__}: {exc}"[:500],
                "events": result.events,
                "written": result.written,
                "detail": result.detail,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "checked_at": timezone.now(),
            },
        )
        raise
    SourceStatus.objects.update_or_create(
        source=source,
        defaults={
            "ok": True,
            "message": result.note,
            "events": result.events,
            "written": result.written,
            "detail": result.detail,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "checked_at": timezone.now(),
        },
    )
