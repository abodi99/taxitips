"""
PredictHQ live i pipeline-sidan: hämtas när sidan visas, sparas aldrig.

PredictHQ:s villkor (hämtade 2026-09-13):
- 3.7 d) i): kunden får inte "cache, store, download, scrape, or retain a copy
  of ... any PredictHQ Data in any form or format, unless otherwise agreed with
  us in writing".
- 3.7 c): under provperiod är rätten "limited to internal use for the purposes
  of testing", utan kommersiell användning förrän en betald plan finns.
- 4.8: evenemangen ska attribueras till PredictHQ när de visas.

Därför:
- inget skrivs till databasen, inte ens source_status (antalet evenemang är
  också deras data);
- endpointen finns bara när DEBUG är på, så den aldrig når någon utanför
  organisationen;
- förarappens /api/events visar inte PredictHQ förrän ett avtal finns.

Svaret paras ihop med de sparade Ticketmaster-evenemangen i minnet
(events.matching), så att sidan kan visa en rad per verkligt evenemang med både
besökarprognos och biljettlänk.
"""

from __future__ import annotations

import datetime as dt
import time
from types import SimpleNamespace

from django.conf import settings
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from events import ingest, matching, timing
from events.api import event_row, visible_upcoming
from events.sources import predicthq

# 14 dagar är ungefär 10 sidor och fyra sekunder. 30 dagar är drygt 20 sidor.
DEFAULT_DAYS = 14
MAX_DAYS = 30


def fetch(now: dt.datetime, days: int) -> dict:
    token = settings.PREDICTHQ_ACCESS_TOKEN
    if not token:
        return {"error": "PREDICTHQ_ACCESS_TOKEN saknas i taxitips-backend/.env."}
    started = time.monotonic()
    today = now.astimezone(timing.STOCKHOLM).date()
    raw_events, stats = predicthq.fetch_events(predicthq.Client(token), today, today + dt.timedelta(days=days))

    items = []
    for raw in raw_events:
        row = ingest.build_row(raw, ingest.PREDICTHQ)
        if row is None or (row["end_at"] and row["end_at"] <= now):
            continue
        items.append(SimpleNamespace(**row, source=ingest.PREDICTHQ))

    tickets = list(visible_upcoming(now, days))
    pairs = matching.pair(items, tickets)
    ticket_for = {i: (tickets[j], note) for j, (i, note) in pairs.items()}

    rows = []
    for index, item in enumerate(items):
        ticket, note = ticket_for.get(index, (None, ""))
        row = event_row(item, now, also=[ticket] if ticket else ())
        row["ticketmasterId"] = f"{ticket.source}:{ticket.external_id}" if ticket else None
        row["matchNote"] = note
        rows.append(row)
    rows.sort(key=lambda r: (r["startDate"], r["startAt"] or "~", r["name"]))

    return {
        "stored": False,
        "fetchedAt": now.isoformat(),
        "days": days,
        "durationMs": int((time.monotonic() - started) * 1000),
        "calls": stats["calls"],
        "pages": stats["pages"],
        "count": stats["count"],
        "overflow": stats["overflow"],
        "truncated": stats["truncated"],
        "rateLimitRemaining": stats["rateLimitRemaining"],
        "matchedTicketmaster": len(pairs),
        "events": rows,
        "attribution": timing.attribution({ingest.PREDICTHQ}),
    }


@require_GET
def pipeline_predicthq(request):
    """GET /api/pipeline/predicthq?days=14 -- bara med DEBUG, bara för pipeline-sidan."""
    if not settings.DEBUG:
        raise Http404("Finns bara lokalt.")
    try:
        days = int(request.GET.get("days") or DEFAULT_DAYS)
    except ValueError:
        days = DEFAULT_DAYS
    days = max(1, min(days, MAX_DAYS))
    try:
        payload = fetch(timezone.now(), days)
    except predicthq.PredictHQError as exc:
        payload = {"error": str(exc)}
    return JsonResponse(
        payload, status=502 if "error" in payload else 200, json_dumps_params={"ensure_ascii": False},
    )
