"""
Tipsets två korta rader: vad som hänt och det som avgör om det är värt att köra.

Förare med lite svenska ska förstå ett tips på en sekund. Källornas text är
skriven för resenärer och AI-raden (core/briefs.py) kan hitta på, så raderna
här skrivs av servern, deterministiskt ur tipsets egna fält och regel-id:
samma indata ger alltid samma rader, och inget hittas på. Kortet, detaljvyn
och notisen (core/notify.py) visar samma rader, så att de aldrig säger emot
varandra.

* `headline`  -- vad (högst 4 ord): "Tåg inställt".
* `decision`  -- det som avgör (högst 5 ord): "Nästa tåg 23:48".
* `decision_tone` -- `go` (tomt på alternativ, kör), `wait` (osäkert eller
  alternativ snart), `no` (resenärerna klarar sig själva).

Ordlistan hålls liten med flit: varje nytt ord är ett ord till som någon ska
slå upp. core/test_tip_lines.py vaktar ordgränserna.

Tomma rader betyder "visa källans egen rubrik" (tier `ignore`) -- raden får
aldrig fyllas med gissningar för att något ska stå där.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.scoring import ALTERNATIVE_SOON_MIN, QUICK_ALTERNATIVE_MIN
from core.taxi_context import human_minutes

LOCAL_TZ = ZoneInfo("Europe/Stockholm")

GO, WAIT, NO = "go", "wait", "no"

# Färdsätt -> (substantiv, bestämd form, "inställd" i rätt genus, "sen" i rätt genus).
# Tåg är neutrum ("inställt", "sent"); övriga är utrum.
_NOUNS = {
    "train": ("Tåg", "tåget", "inställt", "sent"),
    "bus": ("Buss", "bussen", "inställd", "sen"),
    "metro": ("Tunnelbana", "tunnelbanan", "inställd", "sen"),
    "tram": ("Spårvagn", "spårvagnen", "inställd", "sen"),
    "boat": ("Båt", "båten", "inställd", "sen"),
}
_UNKNOWN_NOUN = ("Avgång", "avgången", "inställd", "sen")

_WAVE_COUNT_RE = re.compile(r"^\s*(\d+)\s+plan\b")
_WAVE_SPAN_RE = re.compile(r"mellan (\d{2}:\d{2}) och (\d{2}:\d{2})")
_CLOCK_AFTER_KL_RE = re.compile(r"\bkl\.?\s*(\d{2}:\d{2})")


def _clock(value: datetime | None) -> str:
    if value is None:
        return ""
    if timezone.is_naive(value):
        value = timezone.make_aware(value, LOCAL_TZ)
    return value.astimezone(LOCAL_TZ).strftime("%H:%M")


def _mode(o) -> str:
    mode = (getattr(o, "mode", None) or "").lower()
    if mode in _NOUNS or mode in ("flight", "road"):
        return mode
    prefix = (getattr(o, "rule_id", None) or "").split(".", 1)[0]
    return prefix if prefix in _NOUNS or prefix in ("flight", "road") else "unknown"


def _hours_or_minutes(minutes: int) -> str:
    """Högst "2 tim": 1 tim 20 min blir för långt för en rad som ska läsas på en sekund."""
    if minutes < 60:
        return human_minutes(minutes)
    return human_minutes(max(1, round(minutes / 60)) * 60)


def _gap_minutes(o) -> int | None:
    """
    Glappet från den inställda avgången till nästa, i minuter.

    Räknas mot den inställda avgången, inte mot nu: ett tips visas upp till
    två timmar i förväg, och "nästa om 2 tim 40 min" om ett tåg som går tio
    minuter efter det inställda vore fel besked.
    """
    at, departure = getattr(o, "next_departure_at", None), getattr(o, "departure_at", None)
    if at is not None and departure is not None:
        return max(0, round((at - departure).total_seconds() / 60))
    return getattr(o, "next_departure_minutes", None)


def _vehicle(o, mode: str) -> tuple[str, str, str]:
    """
    (benämning, "inställd/inställt", "sen/sent") för det drabbade fordonet.

    Linjen när den är känd och kort ("Buss 190", "Pendeltåg 41"): fyra kort
    som alla säger "Centralen · Buss sen" går inte att skilja åt (mätt i
    Stockholm 2026-11-10). Längre benämningar ("SJ Snabbtåg 451") och
    ersättningsbussar faller tillbaka på färdsättet -- raden ska rymmas.
    """
    noun, _definite, cancelled, late = _NOUNS.get(mode, _UNKNOWN_NOUN)
    line = " ".join(str(getattr(o, "line", None) or "").split())
    words = line.split()
    if not line or len(words) > 2 or len(line) > 18 or words[0].lower().startswith("ersättning"):
        return noun, cancelled, late
    # Genus följer ordet: "…tåg" är neutrum, buss/linje/spårvagn är utrum.
    # "Lidingöbanan inställd", "Roslagsbanan sen": banor är utrum fast de går på räls.
    neuter = words[0].lower().endswith("tåg")
    return line, ("inställt" if neuter else "inställd"), ("sent" if neuter else "sen")


def _text_delay(o) -> str:
    """"Cirka 10 min" ur trafikbolagets egen text, när fältet saknas. "" annars."""
    from core import tip_text

    found = tip_text.delay(f"{getattr(o, 'title', None) or ''}. {getattr(o, 'summary', None) or ''}")
    if not found:
        return ""
    minutes, qualifier = found
    text = f"{qualifier} {human_minutes(minutes)}".strip()
    return text[:1].upper() + text[1:]


def _lines(headline: str = "", decision: str = "", tone: str = WAIT) -> dict:
    return {"headline": headline, "decision": decision, "decision_tone": tone}


def _flight(o, condition: str) -> dict:
    summary = getattr(o, "summary", None) or ""
    if condition == "last_arrival":
        start = _clock(getattr(o, "start_time", None))
        return _lines("Sista planet", f"Landar {start}" if start else "", GO)
    count = _WAVE_COUNT_RE.match(summary)
    headline = f"{count.group(1)} plan landar" if count else "Många plan landar"
    span = _WAVE_SPAN_RE.search(summary)
    if span:
        decision = f"{span.group(1)}–{span.group(2)}"
    else:
        decision = _clock(getattr(o, "start_time", None))
    return _lines(headline, decision, WAIT)


def _ferry(o) -> dict:
    match = _CLOCK_AFTER_KL_RE.search(getattr(o, "summary", None) or "")
    decision = match.group(1) if match else _clock(getattr(o, "start_time", None))
    return _lines("Färja kommer", decision, WAIT)


def _road(o, rule_id: str) -> dict:
    # Vägtips är sammanhang, aldrig underlag för en körning: ingen beslutsrad.
    if "accident" in rule_id:
        return _lines("Olycka", "", NO)
    if "closed" in rule_id:
        return _lines("Väg avstängd", "", NO)
    if "queue" in rule_id:
        return _lines("Kö på vägen", "", NO)
    if "work" in rule_id or "minor" in rule_id:
        return _lines("Vägarbete", "", NO)
    return _lines("Trafikstörning", "", NO)


def _delay(o, mode: str) -> dict:
    noun, _cancelled, late = _vehicle(o, mode)
    known_line = noun != _NOUNS.get(mode, _UNKNOWN_NOUN)[0]
    minutes = getattr(o, "delay_minutes", None)
    departure = getattr(o, "departure_at", None)
    if mode not in _NOUNS and not known_line:
        headline = f"Försening {minutes} min" if minutes else "Försening"
    elif minutes and not known_line:
        headline = f"{noun} {minutes} min {late}"
    else:
        headline = f"{noun} {late}"
    if minutes and departure is not None:
        return _lines(headline, f"Kommer {_clock(departure + timedelta(minutes=minutes))}", WAIT)
    if minutes and known_line:
        return _lines(headline, human_minutes(minutes), WAIT)
    # Hur länge står oftast i texten ("cirka 10 minuter"): det är det enda
    # som skiljer en kort försening från en lång.
    return _lines(headline, _text_delay(o), WAIT)


def lines_for(o, now: datetime | None = None) -> dict:
    """
    {"headline", "decision", "decision_tone"} för ett tips (eller något som
    liknar ett: getattr används genomgående så att ögonblicksbilder och
    SimpleNamespace i tester fungerar).
    """
    now = now or timezone.now()
    tier = getattr(o, "severity_tier", None) or ""
    if tier == "ignore":
        return _lines("", "", WAIT)

    rule_id = getattr(o, "rule_id", None) or ""
    parts = rule_id.split(".")
    condition = parts[-1] if len(parts) > 1 else ""
    kind = getattr(o, "kind", None) or ""
    mode = _mode(o)

    # Flyg och färja har egna regler och inga avgångsfält.
    if mode == "flight" or kind == "flight" or rule_id.startswith("flight."):
        return _flight(o, condition if condition == "last_arrival" else "arrival_wave")
    if kind == "ferry" or rule_id == "boat.arrival_wave":
        return _ferry(o)
    if mode == "road" or kind == "road" or rule_id.startswith("road."):
        return _road(o, rule_id)

    _plain, definite, _c, _late = _NOUNS.get(mode, _UNKNOWN_NOUN)
    noun, cancelled, _late = _vehicle(o, mode)
    headline = f"{noun} {cancelled}"
    has_alternative = bool(getattr(o, "has_alternative", False))
    is_last = bool(getattr(o, "is_last_departure", False)) or condition == "last_departure"
    delayed = (
        tier in ("line_delayed", "vehicle_delayed")
        or condition in ("mediumish", "watched_line_notice")
        or rule_id.endswith("line_delayed")
    )

    if delayed and condition != "last_departure":
        return _delay(o, mode)

    # Finns ett annat sätt att ta sig fram ligger resenärerna inte kvar.
    if condition == "stated_alternative":
        return _lines(headline, "Annan resa finns", NO)
    if condition == "replacement" or has_alternative:
        return _lines(headline, "Buss ersätter", NO)

    if is_last:
        return _lines(f"Sista {definite} {_c}", "Inget mer i kväll", GO)
    if condition == "whole_line_stop":
        return _lines("Linjen står still", "Ingen trafik", GO)

    # Två klockslag säger allt och kräver ingen svenska: "Tåg 22:48 inställt",
    # "Nästa tåg 23:48". Färgen (tone) bär bedömningen av glappet.
    departure_clock = _clock(getattr(o, "departure_at", None))
    if departure_clock:
        headline = f"{noun} {departure_clock} {cancelled}"
    next_at = getattr(o, "next_departure_at", None)
    next_noun = _plain.lower() if mode in _NOUNS else "avgång"
    minutes = _gap_minutes(o)
    if condition in ("alternative_soon", "known_gap", "long_gap"):
        if condition == "long_gap" or (minutes is not None and minutes > ALTERNATIVE_SOON_MIN):
            tone = GO
        elif minutes is not None and minutes > QUICK_ALTERNATIVE_MIN:
            tone = WAIT
        else:
            tone = NO
        if next_at is not None:
            return _lines(headline, f"Nästa {next_noun} {_clock(next_at)}", tone)
        if minutes is not None:
            return _lines(headline, f"Nästa {_hours_or_minutes(minutes)} senare", tone)
        return _lines(headline, "Nästa går senare" if tone == GO else "Nästa går snart", tone)

    if condition == "single_departure":
        return _lines(headline, "Nästa går snart", NO)

    # Det reglerna inte kunde läsa ut mer ur (unknown, ambiguous, serious,
    # partial_route, unclassified). Rubriken följer tiern, så att en enstaka
    # inställd buss inte heter "Stopp i trafiken" (mätt 2026-11-10: 59 sådana
    # på en vecka). Beslutsraden säger som det är: vi vet inte.
    if tier == "vehicle_cancelled":
        return _lines(headline, "Oklart läge", WAIT)
    if tier == "line_paused" or not tier:
        return _lines("Stopp i trafiken", "Oklart läge", WAIT)
    return _lines("Störning", "Oklart läge", WAIT)
