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
from datetime import datetime

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


def alternative_from_text(*parts: str | None) -> tuple[bool, str]:
    """
    Fritext -> (finns alternativ, kort etikett + källans egen mening).

    Returnerar (False, "") när texten inte nämner något alternativ. Att
    gissa vore värre än att tiga: en förare som kör till en perrong där
    ersättningsbussen redan står gör en bomresa.
    """
    text = " ".join(p for p in parts if p).strip()
    if not text:
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
    alternative_note: str,
    now: datetime,
) -> dict:
    """
    Det appen visar under tipset: när går nästa, och finns det något annat?

    Minuterna räknas om från den absoluta tidpunkten när vi har en --
    `next_departure_minutes` mättes när tipset skrevs och åldras med det.
    Ett tips som skrevs för 20 minuter sedan påstod annars "om 45 min" när
    det i verkligheten var 25.
    """
    minutes = next_departure_minutes
    clock = None
    departed = False
    if next_departure_at:
        minutes = round((next_departure_at - now).total_seconds() / 60)
        clock = next_departure_at.astimezone().strftime("%H:%M")
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
    if is_last_departure:
        parts.append("Sista avgången härifrån")
    elif departed:
        parts.append(f"Nästa avgång gick {clock}")
    elif minutes is not None and route:
        parts.append(f"{route} (om {human_gap(minutes)})")
    elif minutes is not None:
        gap = human_gap(minutes)
        parts.append(f"Nästa avgång {clock} (om {gap})" if clock else f"Nästa avgång om {gap}")
    elif route:
        parts.append(route)

    if has_alternative and alternative_note and alternative_note != route:
        parts.append(alternative_note)
    elif has_alternative and not alternative_note:
        parts.append("Ersättningstrafik finns")

    return {
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
