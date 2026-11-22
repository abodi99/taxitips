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

import logging
import smtplib
from email.utils import make_msgid

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

from fleet import email_layout

log = logging.getLogger(__name__)


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


class RecipientRefused(PermanentMailError):
    """Servern tog inte emot just den här mottagaren -- adressen finns inte."""


def _deliver(message) -> None:
    """Skickar och översätter SMTP-felen till "ta om" eller "ge upp"."""
    try:
        message.send(fail_silently=False)
    except smtplib.SMTPRecipientsRefused as exc:
        raise RecipientRefused(f"Mottagaren avvisades: {exc}") from exc
    except smtplib.SMTPResponseException as exc:
        if 500 <= int(exc.smtp_code) < 600 and exc.smtp_code not in (535, 530):
            # 5xx är permanent -- utom inloggningsfel, som är vår konfiguration
            # och ska tas om när lösenordet rättats.
            raise PermanentMailError(f"SMTP {exc.smtp_code}: {exc.smtp_error!r}") from exc
        raise


def send(row) -> None:
    """
    Skickar en rad ur utkorgen. Kastar `PermanentMailError` när ett nytt
    försök är meningslöst; andra fel (anslutning, tillfälligt 4xx) tas om vid
    nästa körning.
    """
    if not (row.to_address or "").strip() or "@" not in row.to_address:
        raise PermanentMailError("Ingen giltig mottagaradress.")
    if (row.category or "").startswith("outreach_"):
        return send_outreach(row)
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
    _deliver(message)


# --- Säljmejl (fleet/outreach.py) ------------------------------------------
#
# En egen brevlåda och en egen avsändare. Säljmejl och tjänstemejl ska inte
# dela rykte: ett klagomål på ett säljmejl får inte kosta en kund hennes
# inloggningskod.


def outreach_configured() -> bool:
    return bool(
        getattr(settings, "OUTREACH_SMTP_USER", "")
        and getattr(settings, "OUTREACH_SMTP_PASSWORD", "")
    )


def outreach_address() -> str:
    return (getattr(settings, "OUTREACH_SMTP_USER", "") or "").strip()


def outreach_from() -> str:
    name = (getattr(settings, "OUTREACH_FROM_NAME", "") or "").strip() or "Taxi Tips"
    # Django kodar å, ä och ö i namnet när mejlet byggs; här står det i klartext.
    name = name.replace('"', "").replace("<", "").replace(">", "").replace(",", " ")
    return f"{name} <{outreach_address()}>"


def _outreach_connection():
    port = int(getattr(settings, "FLEET_SMTP_PORT", 465) or 465)
    return get_connection(
        "django.core.mail.backends.smtp.EmailBackend",
        host=getattr(settings, "FLEET_SMTP_HOST", "smtp.hostinger.com"),
        port=port,
        username=settings.OUTREACH_SMTP_USER,
        password=settings.OUTREACH_SMTP_PASSWORD,
        use_ssl=port == 465,
        use_tls=port == 587,
        timeout=20,
    )


def build_outreach(row, *, connection=None) -> EmailMultiAlternatives:
    """
    Säljmejlet som det går ut. Egen funktion så att rubrikerna går att testa
    utan en SMTP-server.

    * `List-Unsubscribe` + `List-Unsubscribe-Post`: avregistrering med ett
      klick i mejlklienten (RFC 8058). Gmail och Yahoo kräver det av den som
      skickar i volym, och det är bättre att mottagaren trycker där än på
      "skräppost".
    * `Message-ID` sätts här och sparas, så att uppföljningen kan svara i
      samma tråd (`In-Reply-To`) och ett svar går att känna igen.
    """
    from fleet import outreach_templates

    payload = row.payload or {}
    message_id = payload.get("message_id") or make_msgid(domain=_domain(outreach_address()))
    headers = {
        "Message-ID": message_id,
        "X-TaxiTips-Category": row.category,
    }
    one_click = str(payload.get("one_click_url") or "").strip()
    if one_click:
        headers["List-Unsubscribe"] = (
            f"<{one_click}>, <mailto:{outreach_address()}?subject=Avregistrera>"
        )
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    thread = str(payload.get("thread") or "").strip()
    if thread:
        headers["In-Reply-To"] = thread
        headers["References"] = thread
    message = EmailMultiAlternatives(
        subject=row.subject,
        body=row.body,
        from_email=outreach_from(),
        to=[row.to_address.strip()],
        reply_to=[outreach_address()],
        headers=headers,
        connection=connection,
    )
    message.attach_alternative(outreach_templates.html_from_text(row.body), "text/html")
    return message


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1] if "@" in address else "taxitips.se"


def send_outreach(row) -> None:
    if not outreach_configured():
        # Inte permanent: raden ligger kvar tills brevlådan är inlagd.
        raise RuntimeError("Säljbrevlådan (OUTREACH_SMTP_USER) är inte konfigurerad.")
    message = build_outreach(row, connection=_outreach_connection())
    _deliver(message)
    payload = dict(row.payload or {})
    payload["message_id"] = message.extra_headers["Message-ID"]
    row.payload = payload
    type(row).objects.filter(id=row.id).update(payload=payload)
    # Kopia i brevlådans Skickat, så att utskicket syns där säljaren läser
    # sin post. Misslyckas kopian har mejlet ändå gått -- det får inte tas om.
    try:
        from fleet import outreach_inbox

        outreach_inbox.append_sent(message.message().as_bytes(linesep="\r\n"))
    except Exception as exc:  # pragma: no cover - nätverksfel
        log.warning("fleet.mailer: kunde inte spara kopia i Skickat: %s", exc)
