"""
SMS via 46elks, avstängt som standard.

Används bara för "Fortsätt här"-länken kring provslutet (fleet/notifications.py,
fleet/continue_link.py). Utkorgen (`OutboxMessage`) har ett `channel`-fält men
sändaren (`notifications.send_pending`) skickar allt som e-post, så SMS går
direkt vid samma tillfälle som mejlet köas, med dubblettskydd i cachen. Det
undviker att ändra utkorgens sändare för ett enda utskick.

Konfiguration (env):

    FORTYSIXELKS_USERNAME=...     # API-användare hos 46elks
    FORTYSIXELKS_PASSWORD=...
    FLEET_SMS_SENDER=TaxiTips     # avsändarnamn, högst 11 tecken

Utan användare och lösenord är allt avstängt: inget skickas och inget fallerar.

`send` kastar aldrig till anroparen. Ett misslyckat SMS får inte fälla provslutets
mejl eller fleet_tick. Fel loggas utan meddelandetext: länken i texten är ett
bevis för bolaget och ska inte ligga i loggarna.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)

API_URL = "https://api.46elks.com/a1/sms"
TIMEOUT = 10


def configured() -> bool:
    return bool(
        (getattr(settings, "FORTYSIXELKS_USERNAME", "") or "").strip()
        and (getattr(settings, "FORTYSIXELKS_PASSWORD", "") or "").strip()
    )


def send(to_e164: str, text: str) -> bool:
    """True när 46elks tog emot meddelandet. Aldrig ett undantag."""
    if not configured() or not to_e164 or not text:
        return False
    try:
        response = requests.post(
            API_URL,
            auth=(settings.FORTYSIXELKS_USERNAME, settings.FORTYSIXELKS_PASSWORD),
            data={
                "from": (getattr(settings, "FLEET_SMS_SENDER", "") or "TaxiTips")[:11],
                "to": to_e164,
                "message": text,
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        log.warning("fleet.sms: anropet till 46elks fallerade: %s", type(exc).__name__)
        return False
    if response.status_code >= 300:
        log.warning("fleet.sms: 46elks svarade %s", response.status_code)
        return False
    return True
