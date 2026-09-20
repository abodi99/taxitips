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

from django.db.models import F
from django.utils import timezone

from core import thresholds

log = logging.getLogger(__name__)


class PollResult:
    """Muterbar räknare som poll-kommandot fyller i medan det jobbar."""

    def __init__(self) -> None:
        self.events = 0
        self.written = 0
        self.note = ""
        # Per delkälla, när källan har flera (Trafiklabs operatörer).
        self.detail: dict = {}
        # False när rundan gick igenom utan att hämta något, t.ex. för att
        # nyckeln saknas. Det är inget fel -- men det får inte räknas som en
        # lyckad hämtning, annars ser en källa utan nyckel färsk ut.
        self.fetched = True


@contextmanager
def polling(source: str):
    """
    Kör en hämtning och skriv ner hur det gick.

    Undantag sväljs INTE -- kommandot ska fortfarande fela synligt i
    terminalen och i Celery. Det som ändras är att felet också blir
    läsbart för den som tittar på pipelinen i efterhand.
    """
    started = time.monotonic()
    result = PollResult()
    try:
        yield result
    except Exception as exc:
        record(
            source, ok=False, message=f"{type(exc).__name__}: {exc}", result=result,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        raise
    record(
        source, ok=True, message=result.note, result=result,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def record(source: str, *, ok: bool, message: str, result: PollResult, duration_ms: int, now=None) -> None:
    """Senaste försöket skrivs alltid; senaste lyckade bara när rundan hämtade."""
    from core.models import SourceStatus

    now = now or timezone.now()
    defaults = {
        "ok": ok,
        # Trafikverkets och Trafiklabs felmeddelanden är långa och upprepar
        # sig per region. Det som betyder något (statuskod och orsak) står först.
        "message": message[:500],
        "events": result.events,
        "written": result.written,
        "detail": result.detail,
        "duration_ms": duration_ms,
        "checked_at": now,
    }
    if ok and result.fetched:
        defaults.update(last_success_at=now, consecutive_failures=0)
    SourceStatus.objects.update_or_create(source=source, defaults=defaults)
    if not ok:
        SourceStatus.objects.filter(source=source).update(consecutive_failures=F("consecutive_failures") + 1)


def beat_heartbeat(worker: str = "", now=None) -> None:
    """
    Beat schemalägger `heartbeat_task`, en worker kör den. En färsk rad bevisar
    att beat, Redis och minst en worker lever. Se core/pipeline_health.py.
    """
    from core.models import SourceStatus

    now = now or timezone.now()
    SourceStatus.objects.update_or_create(
        source=thresholds.HEARTBEAT_SOURCE,
        defaults={
            "ok": True, "message": "", "detail": {"worker": worker}, "checked_at": now,
            "last_success_at": now, "consecutive_failures": 0,
        },
    )
