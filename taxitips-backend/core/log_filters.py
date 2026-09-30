"""
Tar bort positioner, tokens och nycklar ur loggposter innan de skrivs.

Första bältet är att de aldrig står i en URL (core/api.position_from). Det här
är det andra: Django loggar sökvägen vid fel, runserver loggar hela anropsraden,
och källornas undantag bär ibland anrops-URL:en med API-nyckeln. En proxy,
loggtjänst eller APM som läser samma ström får annars med dem.
"""

from __future__ import annotations

import logging
import re

HIDDEN = "<dold>"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Koordinater i en query: lat=55.60&lon=13.00
    (re.compile(r"(?i)\b(lat|lon|lng|latitude|longitude)=-?\d+(?:\.\d+)?"), rf"\1={HIDDEN}"),
    # Positionsheadern i en utskrift av headers
    (
        re.compile(r"(?i)(x-tt-position['\"]?\s*[:=]\s*['\"]?)-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?"),
        rf"\1{HIDDEN}",
    ),
    # Tokens och nycklar i en query
    (
        re.compile(r"(?i)\b(token|device_token|push_token|access_token|key|api_key|apikey|authenticationkey)=[^&\s'\"]+"),
        rf"\1={HIDDEN}",
    ),
    # Trafikverkets XML-inloggning
    (re.compile(r"(?i)(authenticationkey\s*=\s*['\"])[^'\"]+(['\"])"), rf"\1{HIDDEN}\2"),
    # Headers
    (re.compile(r"(?i)(x-device-token['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"), rf"\1{HIDDEN}"),
    (re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?bearer\s+)[^\s'\",}]+"), rf"\1{HIDDEN}"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # en trasig formatsträng ska inte fälla loggningen
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True


class ContextFormatter(logging.Formatter):
    """
    Lägger begärans id, sökväg och konto/telefon på varje rad som skrivs
    under en begäran (core/request_context.py).

    Utan det stod ett oväntat fel i `handle()` som "oväntat fel i pair" -- utan
    någon väg från föraren som ringde till raden i loggen. Id:t skickas också
    tillbaka i svaret (`X-Request-Id`), så att ett fel som en användare ser går
    att matcha mot exakt en rad här. Formatteraren och inte ett filter: ett
    filter hade krävt att varje handler som använder formatet också har
    filtret, annars kastar `%(ctx)s` KeyError mitt i en loggning.
    """

    def format(self, record: logging.LogRecord) -> str:
        from core.request_context import log_suffix

        try:
            record.ctx = log_suffix()
        except Exception:  # loggningen får aldrig fällas av sin egen kontext
            record.ctx = ""
        return super().format(record)
