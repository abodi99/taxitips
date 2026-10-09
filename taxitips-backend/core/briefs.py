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

Skrivs för tips som ska notifieras -- inte för alla på medel- och stark nivå.
Mätt 2026-10-07: 7 854 anrop på fyra dygn för tips utan en enda mottagare, och
beskedet i pushen hann ändå sällan fram (beat varannan minut, push var 30:e
sekund). Nu två vägar till samma rad:

* `ensure()` i pushcykeln, efter grinden: beskedet skrivs för just de tips som
  är på väg ut, med kort tidsgräns och högst några anrop per cykel. Hinner det
  inte går notisen utan besked -- notisen väntar aldrig på modellen.
* `run()` (beat "write-briefs") förvärmer: notisvärdiga tips som ännu inte
  notifierats, så att pushcykeln oftast hittar raden färdig.

Underlaget är tipsets fält och, när granskningen läst ut fakta
(core/tip_facts.py, sparade i Opportunity.ai_facts), de faktaraderna -- men
bara fakta vars siffror står i källtexten, så att ett lästfel i faktan inte
blir en siffra i beskedet.

`brief_key` är en hash av underlaget: ändras tipset blir beskedet inaktuellt
och skrivs om, och ett inaktuellt besked visas aldrig (current_brief). Ett
misslyckat anrop lämnar sitt spår i `ai_call`, och `ai_client.retry_allowed`
håller tipset borta från nästa körning tills backoffen gått ut.
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
- Blanda aldrig färdsätt: en färja är inte ett flyg, ett flyg är inte en färja.
- Hittar du inget säkert att säga, svara med en tom text.

## Uppgifter
{facts}
"""

_KIND_SV = {
    "ferry": "färja",
    "flight": "flyg",
    "road": "väg",
    "transit": "kollektivtrafik",
}


def _clock(value) -> str:
    return value.astimezone(LOCAL_TZ).strftime("%H:%M") if value else ""


def source_text(o: Opportunity) -> str:
    """Underlaget, rad för rad: det modellen får läsa och det beskedet prövas mot."""
    kind = _KIND_SV.get(o.kind or "", o.kind or "okänd")
    lines = [
        f"Typ: {kind}",
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
    lines.extend(_fact_lines(o))
    lines.append(f"Styrka: {'stark' if o.level == 'high' else 'medel'}")
    return "\n".join(lines)


_FACT_LABELS = (
    ("line", "Linje"),
    ("train_no", "Tåg"),
    ("from_station", "Från"),
    ("to_station", "Till"),
    ("departure_clock", "Drabbad avgång enligt texten"),
    ("next_departure_clock", "Nästa avgång enligt texten"),
    ("cause", "Orsak"),
    ("why", "Vad som hänt"),
)


def _fact_lines(o: Opportunity) -> list[str]:
    """
    Det granskningen redan läst ut (core/tip_facts.TipFacts), som rader.

    Varje siffra i en faktarad måste stå i tipsets egen text: faktan är
    modellens läsning, och ett klockslag den läst fel får inte bli en
    "verifierad" siffra i beskedet bara för att den står i underlaget.
    """
    facts = getattr(o, "ai_facts", None)
    if not isinstance(facts, dict):
        return []
    # Läsningen gäller texten den gjordes på: har texten ändrats sedan dess
    # (ny rule_key) är faktan en annan störnings.
    rule_key, ai_rule_key = getattr(o, "rule_key", None), getattr(o, "ai_rule_key", None)
    if rule_key and ai_rule_key and rule_key != ai_rule_key:
        return []
    raw = f"{o.title or ''} {o.summary or ''}"
    out = []
    for key, label in _FACT_LABELS:
        value = str(facts.get(key) or "").strip()
        if not value:
            continue
        if any(n not in raw and n.replace(".", ":") not in raw for n in _NUMBER_RE.findall(value)):
            continue
        out.append(f"{label}: {value[:120]}")
    delay = facts.get("delay_minutes")
    if isinstance(delay, int) and delay > 0 and str(delay) in raw and not o.delay_minutes:
        out.append(f"Försening enligt texten: {delay} min")
    return out


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
    lowered = line.lower()
    if "typ: färja" in source.lower() and re.search(r"flyg", lowered):
        return None
    if "typ: flyg" in source.lower() and re.search(r"färj", lowered):
        return None
    return line


def current_brief(o: Opportunity) -> str | None:
    """Beskedet, bara om det skrevs från tipset som det ser ut nu."""
    brief = getattr(o, "brief", None)
    if not brief or getattr(o, "brief_key", None) != key_for(o):
        return None
    return brief


def wants_brief(o: Opportunity) -> bool:
    """
    Ska det här tipset ha ett besked alls? Bara det som kan väcka en telefon
    (thresholds.is_notify_worthy, samma grind som pushcykeln). Allt annat
    visar kortet som det alltid gjort.
    """
    if o.kind == "road" or o.severity_tier == "ignore" or o.suppressed_at is not None:
        return False
    return thresholds.is_notify_worthy(
        o.severity_tier, o.demand_score, o.has_alternative, level=thresholds.effective_level(o),
    )


def due(now=None, limit: int | None = None) -> list[Opportunity]:
    """Förvärmningen: notisvärdiga tips som ännu inte notifierats och saknar besked."""
    now = now or timezone.now()
    limit = limit or thresholds.AI_BRIEF_MAX_PER_RUN
    rows = (
        Opportunity.objects.filter(
            end_time__gt=now, suppressed_at__isnull=True, notified_at__isnull=True,
            level="high", has_alternative=False,
            severity_tier__in=sorted(thresholds.NOTIFY_WORTHY_TIERS),
            demand_score__gte=thresholds.NOTIFY_SCORE_FLOOR,
        )
        .exclude(kind="road")
        .filter(Q(start_time__isnull=True) | Q(start_time__lte=now + timedelta(hours=thresholds.FEED_HORIZON_HOURS)))
        .order_by("-demand_score")[: limit * 4]
    )
    pending = [o for o in rows if wants_brief(o) and o.brief_key != key_for(o)]
    allowed = ai_client.retry_allowed("brief", [o.external_id for o in pending], now)
    return [o for o in pending if o.external_id in allowed][:limit]


def _write_one(o: Opportunity, *, timeout: float) -> str | None:
    """
    Ett anrop för ett tips. Returnerar raden ("" när modellen inte hade något
    säkert att säga eller raden kastades). Kastar AiUnavailable rakt igenom;
    övriga fel loggas i ai_call av klienten och kastas vidare.
    """
    source = source_text(o)
    out = ai_client.generate(
        "brief", PROMPT.format(facts=source), BriefOut,
        model=thresholds.AI_MODEL_EXTRACT, subject=o.external_id, timeout=timeout,
    )
    text = valid(out.text, source)
    key = key_for(o)
    # Nyckeln sparas även när raden kastades: samma underlag ska inte kosta
    # ett nytt anrop i nästa körning. Ändras tipset prövas det igen.
    Opportunity.objects.filter(pk=o.pk).update(brief=text, brief_key=key)
    o.brief, o.brief_key = text, key
    return text


def run(now=None, limit: int | None = None) -> Counter:
    counts: Counter = Counter()
    blocked = ai_client.unavailable_reason(now)
    if blocked:
        counts["skipped"] = 1
        log.info("briefs: AI används inte just nu: %s", blocked)
        return counts
    for o in due(now, limit):
        try:
            text = _write_one(o, timeout=15)
        except ai_client.AiUnavailable:
            break
        except Exception as exc:  # ett tips fel stoppar aldrig de andra
            log.warning("briefs: %s misslyckades: %s", o.external_id, type(exc).__name__)
            counts["failed"] += 1
            continue
        counts["written" if text else "rejected"] += 1
    return counts


def ensure(rows: list, now=None, *, max_calls: int | None = None, timeout: float | None = None) -> Counter:
    """
    Beskeden för tipsen som är på väg ut i pushcykeln, strax efter grinden.

    Fail-open i varje led: avstängd AI, backoff, fullt tak eller ett fel
    betyder att notisen går med kortets vanliga text. Räknarna följer med i
    pushsvaret så att "inget besked" går att skilja från "beskedet skrevs".
    """
    now = now or timezone.now()
    max_calls = thresholds.AI_BRIEF_MAX_PER_CYCLE if max_calls is None else max_calls
    timeout = thresholds.AI_BRIEF_TIMEOUT_S if timeout is None else timeout
    counts: Counter = Counter()
    # Nyckeln, inte texten: ett tips vars rad kastades har sin nyckel och ska
    # inte kosta ett nytt anrop förrän underlaget ändrats.
    pending = [o for o in rows if wants_brief(o) and o.brief_key != key_for(o)]
    if not pending:
        return counts
    if ai_client.unavailable_reason(now, purpose="brief"):
        counts["unavailable"] = len(pending)
        return counts
    allowed = ai_client.retry_allowed("brief", [o.external_id for o in pending], now)
    asked = 0
    for o in pending:
        if o.external_id not in allowed:
            counts["backoff"] += 1
            continue
        if asked >= max_calls:
            counts["deferred"] += 1
            continue
        asked += 1
        try:
            text = _write_one(o, timeout=timeout)
        except ai_client.AiUnavailable:
            counts["unavailable"] += 1
            break
        except Exception as exc:
            log.warning("briefs: %s misslyckades i pushcykeln: %s", o.external_id, type(exc).__name__)
            counts["failed"] += 1
            continue
        counts["written" if text else "rejected"] += 1
    return counts
