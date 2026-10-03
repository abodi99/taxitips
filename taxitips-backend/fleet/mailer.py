"""
Utkorgens avsändare: SMTP, för taxitips.se Hostingers server.

Domänen har redan SPF (`include:_spf.mail.hostinger.com`), DKIM
(`hostingermail-a._domainkey`) och DMARC, så mejl som skickas genom Hostinger
från en adress på taxitips.se går igenom kontrollerna hos mottagaren. Att
skicka från en annan server med samma avsändare hade hamnat i skräpposten.

Konfiguration (taxitips-backend och -worker):

    FLEET_SMTP_USER=hej@taxitips.se        # brevlådan i Hostinger
    FLEET_SMTP_PASSWORD=...                 # brevlådans lösenord
    FLEET_SMTP_HOST=smtp.hostinger.com      # standard
    FLEET_SMTP_PORT=465                     # SSL; 587 = STARTTLS

Utan användare och lösenord är avsändaren avstängd och utkorgen ligger kvar
som `pending` -- samma säkra läge som i utveckling (fleet/notifications.py).
"""

from __future__ import annotations

import smtplib

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

from fleet import email_layout


class PermanentMailError(Exception):
    """Ett fel som inte blir bättre av ett nytt försök: fel adress, avvisat innehåll."""


def configured() -> bool:
    return bool(
        getattr(settings, "FLEET_SMTP_USER", "") and getattr(settings, "FLEET_SMTP_PASSWORD", "")
    )


def _connection():
    port = int(getattr(settings, "FLEET_SMTP_PORT", 465) or 465)
    return get_connection(
        "django.core.mail.backends.smtp.EmailBackend",
        host=getattr(settings, "FLEET_SMTP_HOST", "smtp.hostinger.com"),
        port=port,
        username=settings.FLEET_SMTP_USER,
        password=settings.FLEET_SMTP_PASSWORD,
        use_ssl=port == 465,
        use_tls=port == 587,
        timeout=20,
    )


def from_address() -> str:
    configured_from = getattr(settings, "FLEET_MAIL_FROM", "") or ""
    return configured_from or f"TaxiTips <{settings.FLEET_SMTP_USER}>"


def send(row) -> None:
    """
    Skickar en rad ur utkorgen. Kastar `PermanentMailError` när ett nytt
    försök är meningslöst; andra fel (anslutning, tillfälligt 4xx) tas om vid
    nästa körning.
    """
    if not (row.to_address or "").strip() or "@" not in row.to_address:
        raise PermanentMailError("Ingen giltig mottagaradress.")
    message = EmailMultiAlternatives(
        subject=row.subject,
        body=row.body,
        from_email=from_address(),
        to=[row.to_address.strip()],
        reply_to=[getattr(settings, "FLEET_MAIL_REPLY_TO", "") or "hej@taxitips.se"],
        headers={"X-TaxiTips-Category": row.category},
        connection=_connection(),
    )
    # Samma innehåll med logga och färger. Texten ovan är reserven för
    # klienter som inte visar HTML (fleet/email_layout.py).
    message.attach_alternative(
        email_layout.from_text(row.subject, row.body, row.payload), "text/html"
    )
    try:
        message.send(fail_silently=False)
    except smtplib.SMTPRecipientsRefused as exc:
        raise PermanentMailError(f"Mottagaren avvisades: {exc}") from exc
    except smtplib.SMTPResponseException as exc:
        if 500 <= int(exc.smtp_code) < 600 and exc.smtp_code not in (535, 530):
            # 5xx är permanent -- utom inloggningsfel, som är vår konfiguration
            # och ska tas om när lösenordet rättats.
            raise PermanentMailError(f"SMTP {exc.smtp_code}: {exc.smtp_error!r}") from exc
        raise
