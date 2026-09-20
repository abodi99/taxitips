"""
Revisionsloggen. En rad per beslut som rör pengar, åtkomst eller behörighet.

Aldrig en hemlighet i `detail`: ingen token, ingen parkopplingskod, inget
lösenord. Loggen ska gå att läsa av support utan att den blir ett andra ställe
där credentials läcker (§2).
"""

from __future__ import annotations

import logging

from fleet.models import AuditEvent

log = logging.getLogger(__name__)

# Nycklar som aldrig får skrivas till loggen, oavsett vem som råkar skicka dem.
_FORBIDDEN = {
    "token", "device_token", "code", "pairing_code", "secret", "password",
    "code_hash", "token_hash", "api_key", "authorization",
}


def scrub(detail: dict | None) -> dict:
    """Tar bort hemligheter. Hellre en tom logg än en logg med en token i."""
    if not detail:
        return {}
    out = {}
    for key, value in detail.items():
        if str(key).lower() in _FORBIDDEN:
            out[key] = "[redacted]"
        elif isinstance(value, dict):
            out[key] = scrub(value)
        else:
            out[key] = value
    return out


def record(
    action: str,
    *,
    company_id=None,
    actor_user_id=None,
    actor_kind: str = "system",
    subject_type: str = "",
    subject_id="",
    detail: dict | None = None,
) -> AuditEvent | None:
    """
    Skriver en revisionsrad. Kastar aldrig: en trasig logg får inte fälla en
    lyckad uppsägning. Felet loggas i stället till applikationsloggen.
    """
    try:
        return AuditEvent.objects.create(
            company_id=company_id,
            actor_user_id=actor_user_id,
            actor_kind=actor_kind,
            action=action,
            subject_type=subject_type,
            subject_id=str(subject_id or "")[:64],
            detail=scrub(detail),
        )
    except Exception as exc:  # pragma: no cover - loggen får aldrig fälla flödet
        log.warning("fleet.audit: kunde inte skriva revisionsrad %s: %s", action, exc)
        return None
