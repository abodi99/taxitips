"""
Är pipelinen frisk just nu? Svaret som /health/pipeline och `check_pipeline` ger.

`/health` svarar bara på om webbprocessen når databasen. Den är grön även när
beat stått still i ett dygn -- då slutar alla källor uppdateras, och flödet
visar gamla tips som om de vore nya. Den här kontrollen tittar på två saker:

1. Beat-hjärtslaget. Beat schemalägger `heartbeat_task` varje minut och en
   worker kör den; en färsk rad bevisar att beat, Redis och en worker lever.
2. Senaste LYCKADE hämtning per källa, mot gränsen i
   thresholds.SOURCE_MAX_AGE_MINUTES. `checked_at` räcker inte: den flyttas
   även av ett misslyckat försök.

Bara kärnkällorna (thresholds.CORE_SOURCES) kan göra svaret rött. Flyg, väg,
evenemang och fartyg är tillägg, och ingen valfri källa får blockera kärnappen.

Svaret innehåller aldrig källornas felmeddelanden: de kan innehålla
anrops-URL:er, och endpointen är lika öppen som /health.
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from core import thresholds


def evaluate(now: dt.datetime | None = None) -> dict:
    from core.models import SourceStatus

    now = now or timezone.now()
    statuses = {s.source: s for s in SourceStatus.objects.all()}
    problems: list[str] = []

    beat = statuses.get(thresholds.HEARTBEAT_SOURCE)
    beat_age = int((now - beat.checked_at).total_seconds()) if beat else None
    if beat_age is None:
        problems.append("heartbeat_missing")
    elif beat_age > thresholds.HEARTBEAT_MAX_AGE_SECONDS:
        problems.append("heartbeat_stale")

    sources = []
    for source, max_age in thresholds.SOURCE_MAX_AGE_MINUTES.items():
        status = statuses.get(source)
        last = status.last_success_at if status else None
        age = int((now - last).total_seconds() // 60) if last else None
        stale = age is None or age > max_age
        core = source in thresholds.CORE_SOURCES
        if stale and core:
            problems.append(f"{source}_stale")
        sources.append({
            "source": source,
            "core": core,
            "ok": status.ok if status else None,
            "lastSuccessAt": last.isoformat() if last else None,
            "lastSuccessAgeMinutes": age,
            "maxAgeMinutes": max_age,
            "consecutiveFailures": status.consecutive_failures if status else 0,
            "stale": stale,
        })

    return {
        "ok": not problems,
        "problems": problems,
        "heartbeatAgeSeconds": beat_age,
        "sources": sources,
        "checkedAt": now.isoformat(),
    }
