"""
Förarbeskedet: en rad om tipset, i förarens ord.

Källornas text är skriven för resenärer ("Sök din resa i appen", "Resenärer
hänvisas till nästa avgång"), och kortets rubrik är ofta bara platsen. Beskedet
säger på en rad vad som hänt, var, när och varför det kan ge körningar --
skrivet av språkmodellen, men BARA ur tipsets egna fält.

Skyddet är mekaniskt, inte en uppmaning: varje siffra och varje klockslag i
beskedet måste finnas i underlaget, och raden får vara högst BRIEF_MAX_CHARS
tecken. Annars kastas den, och kortet visar det det alltid visat. Ett besked
som hittar på en avgångstid är värre än inget besked.

Skrivs i efterhand (beat "write-briefs") för tips på medel- och stark nivå.
`brief_key` är en hash av underlaget: ändras tipset blir beskedet inaktuellt
och skrivs om, och ett inaktuellt besked visas aldrig (current_brief).
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone
from pydantic import BaseModel

from core import ai_client, thresholds
from core.models import Opportunity

log = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Stockholm")
# Ryms på en rad i kortet och på låsskärmen.
BRIEF_MAX_CHARS = 90

_NUMBER_RE = re.compile(r"\d+(?:[:.]\d{2})?")


class BriefOut(BaseModel):
    text: str = ""


PROMPT = """Skriv EN rad på svenska till en taxiförare, högst 90 tecken: vad som hänt,
var och när, och varför det kan ge körningar.

Regler:
- Använd bara uppgifterna nedan. Varje siffra och klockslag du skriver måste stå i uppgifterna.
- Ingen hälsning, inga citattecken, ingen uppmaning som "kör dit".
- Hittar du inget säkert att säga, svara med en tom text.

## Uppgifter
{facts}
"""


def _clock(value) -> str:
    return value.astimezone(LOCAL_TZ).strftime("%H:%M") if value else ""


def source_text(o: Opportunity) -> str:
    """Underlaget, rad för rad: det modellen får läsa och det beskedet prövas mot."""
    lines = [
        f"Rubrik: {o.title or ''}",
        f"Text: {(o.summary or '')[:600]}",
        f"Plats: {', '.join(str(p) for p in (o.places or [])) or '(okänd)'}",
    ]
    if o.departure_at:
        lines.append(f"Drabbad avgång: {_clock(o.departure_at)}")
    if o.destination:
        lines.append(f"Mot: {o.destination}")
    if o.is_last_departure:
        lines.append("Sista avgången för dagen")
    elif o.next_departure_at:
        lines.append(f"Nästa avgång: {_clock(o.next_departure_at)}")
    if o.delay_minutes:
        lines.append(f"Försening: {o.delay_minutes} min")
    if o.has_alternative and o.alternative_note:
        lines.append(f"Alternativ: {o.alternative_note[:200]}")
    lines.append(f"Styrka: {'stark' if o.level == 'high' else 'medel'}")
    return "\n".join(lines)


def key_for(o: Opportunity) -> str:
    return hashlib.sha1(source_text(o).encode("utf-8")).hexdigest()[:40]


def valid(text: str | None, source: str) -> str | None:
    """Raden om den håller, annars None. Varje tal måste finnas i underlaget."""
    line = re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip().strip('"“”\'')
    if not line or len(line) > BRIEF_MAX_CHARS:
        return None
    for number in _NUMBER_RE.findall(line):
        if number not in source and number.replace(".", ":") not in source:
            return None
    return line


def current_brief(o: Opportunity) -> str | None:
    """Beskedet, bara om det skrevs från tipset som det ser ut nu."""
    brief = getattr(o, "brief", None)
    if not brief or getattr(o, "brief_key", None) != key_for(o):
        return None
    return brief


def due(now=None, limit: int | None = None) -> list[Opportunity]:
    now = now or timezone.now()
    limit = limit or thresholds.AI_BRIEF_MAX_PER_RUN
    rows = (
        Opportunity.objects.filter(
            end_time__gt=now, suppressed_at__isnull=True, level__in=("medium", "high"),
        )
        .exclude(severity_tier="ignore")
        .exclude(kind="road")
        .filter(Q(start_time__isnull=True) | Q(start_time__lte=now + timedelta(hours=thresholds.FEED_HORIZON_HOURS)))
        .order_by("-demand_score")[: limit * 4]
    )
    return [o for o in rows if o.brief_key != key_for(o)][:limit]


def run(now=None, limit: int | None = None) -> Counter:
    counts: Counter = Counter()
    blocked = ai_client.unavailable_reason(now)
    if blocked:
        counts["skipped"] = 1
        log.info("briefs: AI används inte just nu: %s", blocked)
        return counts
    for o in due(now, limit):
        source = source_text(o)
        try:
            out = ai_client.generate(
                "brief", PROMPT.format(facts=source), BriefOut,
                model=thresholds.AI_MODEL_EXTRACT, subject=o.external_id, timeout=15,
            )
        except ai_client.AiUnavailable:
            break
        except Exception as exc:  # ett tips fel stoppar aldrig de andra
            log.warning("briefs: %s misslyckades: %s", o.external_id, type(exc).__name__)
            counts["failed"] += 1
            continue
        text = valid(out.text, source)
        # Nyckeln sparas även när raden kastades: samma underlag ska inte kosta
        # ett nytt anrop varannan minut. Ändras tipset prövas det igen.
        Opportunity.objects.filter(pk=o.pk).update(brief=text, brief_key=key_for(o))
        counts["written" if text else "rejected"] += 1
    return counts
