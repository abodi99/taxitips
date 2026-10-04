"""
"Vad gör resenären i stället?" -- nästa avgång och ersättningstrafik,
sammanfattat för en förare.

Det här är den fråga som avgör om en störning är värd att köra till.
Signalerna fanns redan i pipelinen men nådde aldrig fram: järnvägen räknade
ut nästa avgång och läste Trafikverkets ReplacementTraffic, textkällorna
matchade "buss ersätter" för att sätta rätt tier -- och sedan förblev allt
det bara ett tal i en poängformel. En förare fick se poängen, inte skälet.

Modulen gör två saker:

1. Läser ut ersättningstrafik ur en fritextkälla (SL, Västtrafik,
   Trafiklab), som inte har något strukturerat fält för det.
2. Formulerar den mening som appen visar. Formuleringen bor här, på ETT
   ställe, av samma skäl som poängtrösklarna flyttade till thresholds.py:
   en klient som skriver om samma sak själv börjar förr eller senare säga
   något annat än en annan klient.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Stockholm")

# Vad källorna faktiskt skriver. Ordningen betyder något: den första
# träffen blir etiketten, och "ersättningsbuss" är mer informativt än det
# generella "ersättningstrafik".
_ALTERNATIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"ersättningsbuss(?:ar|arna|en)?", re.IGNORECASE), "Ersättningsbuss"),
    (re.compile(r"buss(?:ar)? ersätter", re.IGNORECASE), "Buss ersätter"),
    (re.compile(r"ersättningstrafik", re.IGNORECASE), "Ersättningstrafik"),
    (re.compile(r"ersättningsfordon", re.IGNORECASE), "Ersättningsfordon"),
    (re.compile(r"taxi ersätter|ersättningstaxi", re.IGNORECASE), "Taxi ersätter"),
    (re.compile(r"tågbyte", re.IGNORECASE), "Tågbyte"),
    (re.compile(r"övriga avgångar", re.IGNORECASE), "Övriga avgångar går"),
    (re.compile(r"hänvisas till linje\s*\w+", re.IGNORECASE), "Hänvisas till annan linje"),
    (re.compile(r"res med linje\s*\w+", re.IGNORECASE), "Alternativ linje anvisad"),
]

# Meningen som bär beskedet, för att kunna citera källan i stället för att
# bara påstå att det finns ett alternativ.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NO_ALTERNATIVE_YET_RE = re.compile(
    r"(invänta info|inga ersättningsbuss|ingen ersättningsbuss|ingen ersättningstrafik|saknas ersättningsbuss)",
    re.IGNORECASE,
)


def alternative_from_text(*parts: str | None) -> tuple[bool, str]:
    """
    Fritext -> (finns alternativ, kort etikett + källans egen mening).

    Returnerar (False, "") när texten inte nämner något alternativ. Att
    gissa vore värre än att tiga: en förare som kör till en perrong där
    ersättningsbussen redan står gör en bomresa.
    """
    text = " ".join(p for p in parts if p).strip()
    if not text or _NO_ALTERNATIVE_YET_RE.search(text):
        return False, ""

    for pattern, label in _ALTERNATIVE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        sentence = next(
            (s.strip() for s in _SENTENCE_SPLIT.split(text) if pattern.search(s)), ""
        )
        # Källans mening kan vara hur lång som helst; etiketten är det som
        # ryms på ett kort. Meningen läggs bara till när den säger något
        # UTÖVER etiketten -- "Buss ersätter — Buss ersätter." är brus, och
        # källorna skriver ofta precis så kort.
        restates_label = sentence.strip().rstrip(".!?").lower() == label.lower()
        if sentence and len(sentence) <= 140 and not restates_label:
            return True, f"{label} — {sentence}"
        return True, label
    return False, ""


def human_gap(minutes: int) -> str:
    """"360 minuter" räknar ingen om i huvudet mitt i ett pass."""
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} tim" if rest == 0 else f"{hours} tim {rest} min"


ROUTE_PREFIX = "Nästa resa mot "


def route_note(destination: str, label: str, departs_local: str, changes: int = 0) -> str:
    """
    ResRobots resa som en rad: "Nästa resa mot Nässjö C: Länstrafik tåg 3493 22:58, 1 byte".
    Bytena står med: utan dem såg samma första tåg ut att gå mot två olika mål.
    """
    text = f"{ROUTE_PREFIX}{destination or 'slutstationen'}: {label} {departs_local}"
    if changes:
        text += f", {changes} {'byte' if changes == 1 else 'byten'}"
    return text


def travel_options(
    *,
    next_departure_at: datetime | None,
    next_departure_minutes: int | None,
    is_last_departure: bool,
    has_alternative: bool,
    alternative_note: str | None,
    now: datetime,
    departure_at: datetime | None = None,
    destination: str = "",
    delay_minutes: int | None = None,
) -> dict:
    """
    Det appen visar under tipset: när går nästa, och finns det något annat?

    Minuterna räknas om från den absoluta tidpunkten när vi har en --
    `next_departure_minutes` mättes när tipset skrevs och åldras med det.
    Ett tips som skrevs för 20 minuter sedan påstod annars "om 45 min" när
    det i verkligheten var 25.
    """
    # Kolumnen är nullable; en NULL-rad kraschade hela /api/alerts och appen
    # visade "Inloggningen fungerar inte" (den mappar varje "Ogiltig…" dit).
    alternative_note = alternative_note or ""
    minutes = next_departure_minutes
    clock = None
    departed = False
    if next_departure_at:
        minutes = round((next_departure_at - now).total_seconds() / 60)
        clock = next_departure_at.astimezone(LOCAL_TZ).strftime("%H:%M")
        if minutes <= 0:
            # Avgången har redan gått. "om 0 min" hade låtit som att den
            # står kvar på perrongen; det gör den inte, och skillnaden
            # avgör om det är någon idé att åka dit.
            departed, minutes = True, 0

    # ResRobots resa mot samma slutstation (core/sources/resrobot.py) står i anteckningen som
    # "Nästa resa mot X: Regional tåg 178 14:09" -- oavsett om den räknas som ett alternativ.
    # Förut syntes den bara när has_alternative var sant, så en förare med en timmes glapp
    # såg "Nästa avgång 14:09" utan att veta vart eller med vad.
    route = alternative_note if alternative_note.startswith(ROUTE_PREFIX) else ""
    parts: list[str] = []
    # Raden delad i ett huvud som aldrig åldras och ett "om X" som gör det.
    # Appen sätter ihop dem med sin egen klocka (travelRelative i
    # severity_labels.dart), så en sparad eller cachad rad inte fryser avståndet.
    head_upcoming = head_departed = None
    if is_last_departure:
        parts.append("Sista avgången härifrån")
    elif departed:
        parts.append(f"Nästa avgång gick {clock}")
        head_departed = parts[-1]
    elif minutes is not None and route:
        parts.append(f"{route} (om {human_gap(minutes)})")
        head_upcoming = route
    elif minutes is not None:
        gap = human_gap(minutes)
        parts.append(f"Nästa avgång {clock} (om {gap})" if clock else f"Nästa avgång om {gap}")
        head_upcoming = f"Nästa avgång {clock}" if clock else None
    elif route:
        parts.append(route)

    if has_alternative and alternative_note and alternative_note != route:
        parts.append(alternative_note)
    elif has_alternative and not alternative_note:
        parts.append("Ersättningstrafik finns")
    tail = " · ".join(parts[1:]) if parts else ""
    if next_departure_at and not is_last_departure:
        # Avgången har gått: det gäller även om anropet skedde före, appen avgör själv.
        head_departed = head_departed or f"Nästa avgång gick {clock}"

    # Den drabbade avgången och hur länge resenären blir stående efter den.
    # Glappet räknas från den inställda avgången och åldras inte -- "om 1 tim"
    # räknat från nu (Landskrona 2026-10-02: inställt 20:39, nästa 20:50, appen
    # sa "om 1 tim" kl 19:50) svarar på fel fråga. Appen räknar "om X" mot den
    # inställda avgången i stället, med sin egen klocka.
    departure = None
    if departure_at:
        local = departure_at.astimezone(LOCAL_TZ)
        departure = {
            "at": departure_at.isoformat(),
            "clock": local.strftime("%H:%M"),
            "destination": destination or None,
            "status": "delayed" if delay_minutes else "cancelled",
            "delay_minutes": delay_minutes,
            "new_clock": (
                (local + timedelta(minutes=delay_minutes)).strftime("%H:%M") if delay_minutes else None
            ),
        }
    gap = next_departure_minutes if departure_at and not delay_minutes else None

    return {
        "departure": departure,
        "gap_minutes": gap,
        "next_clock": next_departure_at.astimezone(LOCAL_TZ).strftime("%H:%M") if next_departure_at else None,
        "summary_head_upcoming": head_upcoming,
        "summary_head_departed": head_departed if next_departure_at else None,
        "summary_tail": tail or None,
        "next_departure_at": next_departure_at.isoformat() if next_departure_at else None,
        "next_departure_minutes": minutes,
        "next_departure_clock": clock,
        "next_departure_departed": departed,
        "is_last_departure": is_last_departure,
        "has_alternative": has_alternative,
        "alternative": alternative_note or None,
        # Resan mot samma mål, och vem som svarade: reseplaneraren, inte stationens tavla.
        "route": route or None,
        "planner": "ResRobot" if route else None,
        # None, inte tom sträng: appen ska kunna skilja "vi vet inget" från
        # "vi vet att det inte finns något", och de två fallen ser olika ut
        # på ett kort.
        "summary": " · ".join(parts) or None,
    }
