"""
Evenemangskällorna förklarade för pipeline-sidan (avsnitt 2c): vad som hämtades,
hur det bearbetades, och kalendern som föraren ser.

Läser bara, och använder samma regler och frågor som API:t (events/api.py,
events/timing.py), så sidan kan inte visa en annan kalender än appen får.
PredictHQ ingår inte här -- den hämtas live av sidan själv (events/live.py).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from core.models import SourceStatus
from events import ingest, live, matching, timing
from events.rights import rights_for
from events.api import event_row, visible_upcoming
from events.models import Event

# Sammanfattningen (orter, kategorier, sluttider) gäller närmaste månaden;
# kartan och kalendern får hela horisonten, så att man kan bläddra framåt.
SUMMARY_DAYS = 30
CALENDAR_LIMIT = 2000

# Ordagrant ur källornas villkor, hämtade 2026-09-12 och 2026-09-13. Se docs/data-sources.md.
TERMS = [
    {
        "source": "predicthq",
        "label": "PredictHQ",
        "items": [
            "Sparas och visas bara med en rättighetsreferens till ett skriftligt avtal (events/rights.py). "
            "De publicerade villkoren undantar inte lokal testlagring; utan avtal hämtas källan live här och sparas inte.",
            '3.7 d) i): kunden får inte "cache, store, download, scrape, or retain a copy of … any PredictHQ Data '
            'in any form or format, unless otherwise agreed with us in writing".',
            '3.7 c): under provperiod är rätten "limited to internal use for the purposes of testing", och ingen '
            "kommersiell användning får ske förrän en betald Starter- eller Premium-plan finns.",
            "4.8: evenemangen ska attribueras till PredictHQ när de visas.",
        ],
    },
    {
        "source": "ticketmaster",
        "label": "Ticketmaster",
        "items": [
            'API-villkoren förbjuder att man "derive revenues from the use or provision of the Ticketmaster API" — '
            "ett avtal med Ticketmaster behövs innan evenemangen visas i den betalda appen.",
            'Data får bara sparas "for reasonable periods in order to provide the service", och ett evenemang ska '
            "tas bort inom 24 timmar om ägaren begär det.",
            "Appar som gör många anrop som inte kommer från en användare kan strypas; hämtningen hålls därför till "
            "fyra rundor om dygnet.",
        ],
    },
    {
        "source": "thesportsdb",
        "label": "TheSportsDB",
        "items": [
            "Fotboll, ishockey och handboll i svenska ligor med stor publik: bara spelschemat och arenan.",
            '"You cannot publish apps to an appstore unless you are a paid subscriber": visning i förarappen '
            "kräver betald plan och en referens i EVENTS_THESPORTSDB_APP_REFERENCE.",
            "Källan ska anges med länk till thesportsdb.com. Gratisnyckeln: 30 anrop i minuten.",
        ],
    }
]


def build(now: dt.datetime | None = None) -> dict:
    now = now or timezone.now()
    try:
        return _build(now)
    except DatabaseError as exc:
        return {"error": f"{type(exc).__name__}: {exc}. Har `manage.py migrate events` körts?"}


def _build(now: dt.datetime) -> dict:
    status = SourceStatus.objects.filter(source=ingest.TICKETMASTER).first()
    detail = dict((status.detail if status else None) or {})
    horizon = detail.get("horizonDays", ingest.DEFAULT_HORIZON_DAYS)

    rows = [event_row(e, now) for e in visible_upcoming(now, horizon)]
    summary_until = (now.astimezone(timing.STOCKHOLM).date() + dt.timedelta(days=SUMMARY_DAYS)).isoformat()
    soon = [r for r in rows if r["startDate"] <= summary_until]
    by_city = Counter(r["city"] for r in soon)
    by_category = Counter(r["category"] for r in soon)
    basis = Counter(r["endBasis"] for r in soon)

    hidden = Event.objects.exclude(hidden_reason="").order_by("start_date")[:20]
    calendar = rows[:CALENDAR_LIMIT]
    return {
        "status": {
            "ok": status.ok if status else None,
            "message": (status.message if status else "") or "",
            "checkedAt": status.checked_at.isoformat() if status else None,
            "calls": detail.get("calls"),
            "rateLimitAvailable": detail.get("rateLimitAvailable"),
            "windows": detail.get("windows"),
            "splits": detail.get("splits"),
            "truncated": detail.get("truncated"),
            "created": detail.get("created"),
            "updated": detail.get("updated"),
            "markedMissing": detail.get("markedMissing"),
            "purgedPast": detail.get("purgedPast"),
            "purgedMissing": detail.get("purgedMissing"),
        },
        "totals": {
            "stored": Event.objects.count(),
            "upcoming30": len(soon),
            "upcomingAll": len(rows),
            "hidden": Event.objects.exclude(hidden_reason="").count(),
            "missing": Event.objects.filter(missing_since__isnull=False).count(),
        },
        "byCity": [{"city": city, "n": n} for city, n in by_city.most_common(15)],
        "byCategory": [
            {"category": c, "label": timing.CATEGORY_LABELS.get(c, c), "n": n} for c, n in by_category.most_common()
        ],
        "endBasis": {
            key: basis.get(key, 0)
            for key in (timing.BASIS_SOURCE, timing.BASIS_PREDICTED, timing.BASIS_ESTIMATED, timing.BASIS_UNKNOWN)
        },
        "timeUnknown": sum(1 for r in soon if not r["timeKnown"]),
        "calendar": calendar,
        "map": [r for r in calendar if r["lat"] is not None and r["lon"] is not None],
        "hiddenEvents": [
            {"name": e.name, "reason": e.hidden_reason, "startDate": e.start_date.isoformat(), "city": e.city}
            for e in hidden
        ],
        "predicthqLive": {
            "available": bool(settings.DEBUG and settings.PREDICTHQ_ACCESS_TOKEN),
            "endpoint": "/api/pipeline/predicthq",
            "defaultDays": live.DEFAULT_DAYS,
            "maxDays": live.MAX_DAYS,
        },
        "rules": {
            "durations": [
                {"category": c, "label": timing.CATEGORY_LABELS[c], "minutes": m}
                for c, m in timing.TYPICAL_DURATION_MIN.items()
            ],
            "leaveWindowMin": timing.LEAVE_WINDOW_MIN,
            "addonPattern": timing.ADDON_PATTERN.pattern,
            "lookbackHours": int(ingest.LOOKBACK.total_seconds() // 3600),
            "horizonDays": horizon,
            "cadenceHours": ingest.CADENCE_HOURS,
            "missingRetentionHours": int(ingest.MISSING_RETENTION.total_seconds() // 3600),
            "pastRetentionHours": int(ingest.PAST_RETENTION.total_seconds() // 3600),
            "sizeThresholds": {"relevant": timing.TAXI_MIN_ATTENDANCE, "large": timing.LARGE_ATTENDANCE},
            "duplicateMaxMeters": int(matching.MAX_KM * 1000),
            "duplicateMaxStartGapMin": int(matching.MAX_START_GAP.total_seconds() // 60),
            "duplicateMinNameSimilarity": matching.MIN_NAME_SIMILARITY,
        },
        "terms": TERMS,
        # Vad varje källa får användas till, och referensen som säger varför.
        "rights": [rights_for(source).as_dict() for source in ingest.SOURCES],
    }
