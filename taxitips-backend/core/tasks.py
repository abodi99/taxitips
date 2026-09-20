"""
Celery Beat-motsvarigheten till run_pipeline.pys loop -- se
config/settings.py:s CELERY_BEAT_SCHEDULE för kadenserna, mappade 1:1 från
run_pipeline.pys POLL_INTERVAL_SECONDS/SITES_REFRESH_SECONDS/
REVIEW_INTERVAL_SECONDS.

poll_*.py-kommandona är HELT oförändrade -- call_command() fungerar
identiskt anropad härifrån som från run_pipeline.pys loop, och kommandona
förblir körbara fristående (`python manage.py poll_rail`) för manuell
felsökning. run_pipeline.py självt lämnas också oförändrat, som en
beroendefri reservväg (ingen Redis behövs) -- se dess docstring.

Varje task fångar och LOGGAR sitt eget fel i stället för att kasta om det
till Celery, för att bevara dagens "en källas fel stoppar aldrig de andra"-
semantik exakt (samma princip som poller.js:s per-källa try/catch). Det är
ett medvetet val, inte det enda rimliga: att låta felet kasta om och
konfigurera task_acks_late/ingen auto-retry hade gett synlighet i
Flower/Djangos admin istället -- värt att ändra till den dagen den
synligheten efterfrågas, men det är en beteendeändring från dagens
"logga och fortsätt", inte en självklar default.

push_cycle_task nedan ÄR den portning som den här docstringen tidigare
förklarade var utanför scope (fcmPush.js:s förar-opportunity-larm:
NOTIFY_SCORE_FLOOR, notify_prefs-matchning, isNotifyWorthy, pollningen av
opportunities). Logiken bor i core/notify.py; tasken är bara kadensen.
Den är därmed inte längre en avgränsning -- billing/tasks.pys motsvarande
mening gäller fortfarande sin egen, separata notiskategori (fakturering).

Tidsgränser och lås: varje task har en mjuk och en hård tidsgräns
(standard i settings, längre jobb nedan), och varje jobb körs under ett
Redis-lås per kommando -- se core/locks.py. En runda som redan pågår hoppas
över i stället för att köras dubbelt.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.core.management import call_command

from core.locks import single_run

log = logging.getLogger(__name__)

# (mjuk, hård) tidsgräns i sekunder för jobb som behöver mer än standarden i
# settings.CELERY_TASK_SOFT_TIME_LIMIT/CELERY_TASK_TIME_LIMIT.
EVENTS_LIMITS = (900, 960)  # Ticketmaster: 120 dagar i fönster, 0,25 s mellan anrop
SITES_LIMITS = (1740, 1800)  # SL:s och Västtrafiks hela hållplatsregister
PUSH_LIMITS = (100, 120)
HEARTBEAT_LIMITS = (20, 30)
PURGE_LIMITS = (600, 660)
# Låset lever den hårda gränsen plus marginal: en worker som dödas mitt i en
# runda får inte låsa jobbet längre än så.
LOCK_MARGIN_SECONDS = 30


@shared_task(name="core.tasks.poll_rail_task")
def poll_rail_task() -> None:
    _run("poll_rail")


@shared_task(name="core.tasks.poll_road_task")
def poll_road_task() -> None:
    _run("poll_road")


@shared_task(name="core.tasks.poll_trafiklab_task")
def poll_trafiklab_task() -> None:
    _run("poll_trafiklab")


@shared_task(name="core.tasks.poll_sl_task")
def poll_sl_task(skip_sites: bool = True) -> None:
    _run("poll_sl", skip_sites=skip_sites)


@shared_task(name="core.tasks.poll_vasttrafik_task")
def poll_vasttrafik_task(skip_sites: bool = True) -> None:
    _run("poll_vasttrafik", skip_sites=skip_sites)


@shared_task(name="core.tasks.poll_events_task", soft_time_limit=EVENTS_LIMITS[0], time_limit=EVENTS_LIMITS[1])
def poll_events_task() -> None:
    _run("poll_events", hard_limit=EVENTS_LIMITS[1])


@shared_task(name="core.tasks.poll_flights_task")
def poll_flights_task() -> None:
    """Kommandot avgör själv vilka flygplatser som är mogna -- se dess docstring."""
    _run("poll_flights")


@shared_task(name="core.tasks.refresh_sites_task", soft_time_limit=SITES_LIMITS[0], time_limit=SITES_LIMITS[1])
def refresh_sites_task() -> None:
    """24h-kadens -- kör SL/Västtrafik med skip_sites=False (motsvarar
    run_pipeline.pys refresh_sites-flagga över samma två kommandon).

    Delar lås med den vanliga pollen och väntar in den: en överhoppad
    registeruppdatering dröjer annars ett dygn."""
    _run("poll_sl", hard_limit=SITES_LIMITS[1], wait_seconds=120, skip_sites=False)
    _run("poll_vasttrafik", hard_limit=SITES_LIMITS[1], wait_seconds=120, skip_sites=False)


@shared_task(name="core.tasks.review_uncertain_task")
def review_uncertain_task() -> None:
    _run("review_uncertain")


@shared_task(name="core.tasks.combine_signals_task")
def combine_signals_task() -> None:
    """Kombinationslagret -- se core/combine.py."""
    _run("combine_signals")


@shared_task(name="core.tasks.purge_old_task", soft_time_limit=PURGE_LIMITS[0], time_limit=PURGE_LIMITS[1])
def purge_old_task() -> None:
    """Gällande sjudygnsregel, i batchar -- se core/repository.purge_old."""
    _run("purge_old", hard_limit=PURGE_LIMITS[1])


@shared_task(
    name="core.tasks.purge_presence_task",
    soft_time_limit=HEARTBEAT_LIMITS[0], time_limit=HEARTBEAT_LIMITS[1],
)
def purge_presence_task() -> int:
    """Utgångna "i tjänst"-rutor tas bort -- se core/presence.py."""
    from django.utils import timezone

    from core.presence import purge_expired

    return purge_expired(timezone.now())


@shared_task(
    name="core.tasks.heartbeat_task", bind=True,
    soft_time_limit=HEARTBEAT_LIMITS[0], time_limit=HEARTBEAT_LIMITS[1],
)
def heartbeat_task(self) -> None:
    """Beat schemalägger, en worker kör: raden bevisar att båda lever. Se core/pipeline_health.py."""
    from core.health import beat_heartbeat

    beat_heartbeat(worker=self.request.hostname or "")


def _run(name: str, *, hard_limit: int | None = None, wait_seconds: float = 0, **kwargs) -> None:
    ttl = (hard_limit or settings.CELERY_TASK_TIME_LIMIT) + LOCK_MARGIN_SECONDS
    try:
        with single_run(name, ttl, wait_seconds=wait_seconds) as acquired:
            if not acquired:
                log.info("core.tasks: %s pågår redan, hoppar över rundan", name)
                return
            call_command(name, **kwargs)
    except Exception:
        # Även SoftTimeLimitExceeded: polling() har redan skrivit felet till
        # source_status, och en källas fel stoppar aldrig de andra.
        log.exception("core.tasks: %s misslyckades, fortsätter", name)


@shared_task(name="core.tasks.push_cycle_task", soft_time_limit=PUSH_LIMITS[0], time_limit=PUSH_LIMITS[1])
def push_cycle_task() -> dict:
    """
    Skickar notiser för tips som just blivit värda att avbryta någon för.

    Egen kadens, tätare än pollningen (se CELERY_BEAT_SCHEDULE): ett tips
    ska nå telefonen medan störningen fortfarande pågår, och ett varv som
    väntar in nästa pollcykel lägger upp till 90 sekunder till den fördröjning
    källan redan har.

    Fångar sitt eget fel som de andra taskarna -- en trasig FCM-nyckel får
    inte se ut som att hela pipelinen ligger nere. core/notify.py kastar
    dessutom aldrig av sig självt; det här är andra bältet.

    Körs under ett lås: två cykler samtidigt kan välja samma kandidat innan
    någon av dem hunnit sätta notified_at, och skicka den två gånger.
    """
    from core.notify import run_push_cycle

    try:
        with single_run("push_cycle", PUSH_LIMITS[1] + LOCK_MARGIN_SECONDS) as acquired:
            if not acquired:
                return {"sent": 0, "skipped": "pågår redan"}
            result = run_push_cycle()
    except Exception:
        log.exception("core.tasks: push_cycle misslyckades")
        return {"sent": 0, "error": "exception"}
    if result.get("sent"):
        log.info("core.tasks: push_cycle skickade %s notiser", result["sent"])
    return result
