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

Explicit UTANFÖR scope: portning av fcmPush.js:s förar-opportunity-larm
(NOTIFY_SCORE_FLOOR, notify_prefs-matchning, isNotifyWorthy, pollningen av
opportunities) hit. Det är en separat, större uppgift -- se
billing/tasks.pys docstring för samma avgränsning ur push-sidans perspektiv.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.core.management import call_command

log = logging.getLogger(__name__)


@shared_task(name="core.tasks.poll_rail_task")
def poll_rail_task() -> None:
    _run("poll_rail")


@shared_task(name="core.tasks.poll_trafiklab_task")
def poll_trafiklab_task() -> None:
    _run("poll_trafiklab")


@shared_task(name="core.tasks.poll_sl_task")
def poll_sl_task(skip_sites: bool = True) -> None:
    _run("poll_sl", skip_sites=skip_sites)


@shared_task(name="core.tasks.poll_vasttrafik_task")
def poll_vasttrafik_task(skip_sites: bool = True) -> None:
    _run("poll_vasttrafik", skip_sites=skip_sites)


@shared_task(name="core.tasks.refresh_sites_task")
def refresh_sites_task() -> None:
    """24h-kadens -- kör SL/Västtrafik med skip_sites=False (motsvarar
    run_pipeline.pys refresh_sites-flagga över samma två kommandon)."""
    _run("poll_sl", skip_sites=False)
    _run("poll_vasttrafik", skip_sites=False)


@shared_task(name="core.tasks.review_uncertain_task")
def review_uncertain_task() -> None:
    _run("review_uncertain")


def _run(name: str, **kwargs) -> None:
    try:
        call_command(name, **kwargs)
    except Exception:
        log.exception("core.tasks: %s misslyckades, fortsätter", name)
