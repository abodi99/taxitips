"""
Normalisering och kontroll av svenska organisationsnummer.

Avtalsparten identifieras av land + normaliserat organisationsnummer (§1), så
formen måste vara EN: "556677-8899", "5566778899" och "165566778899" är samma
företag och får inte kunna bli tre konton med var sitt gratisprov.

Kontrollsiffran är Luhn, samma som för personnummer. Den bevisar bara att
numret är ett välformat organisationsnummer -- inte att den som skriver in det
företräder företaget. Det är hela skälet till att `verification_status` finns
vid sidan av det här fältet (§7).
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"\D+")


def normalize(value: str | None, country: str = "SE") -> str:
    """
    Bara siffror, utan sekelprefix. Tom sträng om det inte går att tolka.

    Andra länder än SE normaliseras bara till versaler utan skiljetecken: vi
    har ingen verifierad regel för deras format, och en påhittad sådan hade
    slagit ihop två olika företag eller delat upp ett.
    """
    if not value:
        return ""
    raw = str(value).strip()
    if (country or "SE").upper() != "SE":
        return re.sub(r"[^A-Za-z0-9]+", "", raw).upper()[:32]

    digits = _DIGITS.sub("", raw)
    # 12 siffror med sekelprefix (16 för juridiska personer) -> 10 siffror.
    if len(digits) == 12 and digits.startswith(("16", "18", "19", "20")):
        digits = digits[2:]
    if len(digits) != 10:
        return ""
    return digits


def is_valid(value: str | None, country: str = "SE") -> bool:
    """Luhn-kontroll. Utanför SE: bara att något återstår efter normalisering."""
    normalized = normalize(value, country)
    if not normalized:
        return False
    if (country or "SE").upper() != "SE":
        return True
    if len(normalized) != 10 or not normalized.isdigit():
        return False
    return _luhn(normalized)


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def org_key(country: str, org_number: str) -> str:
    """
    Nyckeln provspärren räknar på. Land + normaliserat nummer, så att ett nytt
    bolagskonto med samma organisationsnummer inte ger ett nytt gratisprov.
    """
    return f"{(country or 'SE').upper()}:{normalize(org_number, country)}"


def format_se(normalized: str) -> str:
    """Visningsform: 556677-8899. Bara för gränssnittet, aldrig för jämförelse."""
    if len(normalized) == 10 and normalized.isdigit():
        return f"{normalized[:6]}-{normalized[6:]}"
    return normalized
