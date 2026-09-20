"""
Bekräftelser och påminnelser: aktivering, provslut, prissteg, betalningsfel,
uppsägning.

**Utkorg, inte direktsändning.** Meddelandet skrivs som en rad och skickas av
ett separat steg. Två skäl: en webhook som kommer två gånger får inte skicka
två mejl (`dedupe_key` är unik), och ett utskick som misslyckas ska kunna tas
om utan att flödet som skapade det körs igen.

**Tjänstemeddelanden är inte marknadsföring.** `category` skiljer dem åt, och
avregistrering från marknadsföring tystar aldrig en faktura som misslyckats
(§10). Det är inte en artighet -- ett företag som inte får veta att betalningen
föll förlorar åtkomsten utan förvarning.

**Testutskick går till sandbox.** Utan `FLEET_OUTBOX_SENDER` konfigurerad
skrivs raden men skickas inte, och statusen blir `pending`. Ingen riktig
mottagare kan nås av misstag från en utvecklingsmiljö.
"""

from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.utils import timezone

from fleet.models import OutboxMessage

log = logging.getLogger(__name__)

# Tjänstemeddelanden. Ingen av dem får kunna tystas av ett marknadsföringsval.
SERVICE_CATEGORIES = frozenset({
    "activation", "trial_started", "trial_ending", "trial_ended",
    "order_confirmed", "payment_failed", "grace_started", "renewal_reminder",
    "price_step", "cancellation_confirmed", "cancellation_applied",
    "device_blocked", "review_opened",
})


def dedupe_key(category: str, *parts) -> str:
    raw = ":".join([category, *[str(p) for p in parts]])
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def queue(
    *,
    category: str,
    company_id=None,
    to_address: str = "",
    subject: str = "",
    body: str = "",
    payload: dict | None = None,
    key_parts: tuple = (),
) -> OutboxMessage | None:
    """
    Lägger ett meddelande i utkorgen. Dubbletter tas tyst: samma `dedupe_key`
    betyder att meddelandet redan finns, och det är rätt svar, inte ett fel.
    """
    key = dedupe_key(category, *key_parts)
    existing = OutboxMessage.objects.filter(dedupe_key=key).first()
    if existing is not None:
        return existing
    return OutboxMessage.objects.create(
        company_id=company_id, category=category, to_address=to_address,
        subject=subject, body=body, payload=payload or {}, dedupe_key=key,
    )


def send_pending(limit: int = 50, sender=None) -> dict:
    """
    Skickar det som ligger i utkorgen.

    Utan konfigurerad sändare skickas ingenting och raderna ligger kvar som
    `pending`. Det är avsiktligt: en utvecklingsmiljö ska inte kunna nå en
    riktig kund.
    """
    sender = sender or _configured_sender()
    if sender is None:
        return {"sent": 0, "skipped": "no_sender"}

    sent = failed = 0
    rows = OutboxMessage.objects.filter(status=OutboxMessage.Status.PENDING).order_by(
        "created_at"
    )[:limit]
    for row in rows:
        try:
            sender(row)
        except Exception as exc:
            failed += 1
            OutboxMessage.objects.filter(id=row.id).update(
                status=OutboxMessage.Status.FAILED, error=str(exc)[:500]
            )
            continue
        sent += 1
        OutboxMessage.objects.filter(id=row.id).update(
            status=OutboxMessage.Status.SENT, sent_at=timezone.now(), error=""
        )
    return {"sent": sent, "failed": failed}


def _configured_sender():
    path = getattr(settings, "FLEET_OUTBOX_SENDER", "") or ""
    if not path:
        return None
    module_name, _, attr = path.rpartition(".")
    try:
        module = __import__(module_name, fromlist=[attr])
        return getattr(module, attr)
    except Exception as exc:  # pragma: no cover - konfigurationsfel
        log.warning("fleet.notifications: kan inte ladda sändaren %s: %s", path, exc)
        return None


# --- Färdiga meddelanden --------------------------------------------------


def _money(ore: int) -> str:
    return f"{ore // 100:,}".replace(",", " ") + f",{ore % 100:02d} kr"


def trial_started(company_id, to_address: str, trial) -> OutboxMessage | None:
    return queue(
        category="trial_started", company_id=company_id, to_address=to_address,
        subject="Provperioden har börjat",
        body=(
            f"Provperioden gäller till {trial.ends_at:%Y-%m-%d %H:%M}. "
            f"Den omfattar högst {trial.vehicle_limit} bilar. "
            "Utan en beställning avslutas provet utan debitering."
        ),
        key_parts=(company_id, trial.id),
    )


def trial_ending(company_id, to_address: str, trial) -> OutboxMessage | None:
    return queue(
        category="trial_ending", company_id=company_id, to_address=to_address,
        subject="Provperioden tar snart slut",
        body=(
            f"Provet avslutas {trial.ends_at:%Y-%m-%d}. Beställ de bilar som ska "
            "fortsätta, annars avslutas provet utan debitering."
        ),
        key_parts=(company_id, trial.id),
    )


def order_confirmed(order) -> OutboxMessage | None:
    return queue(
        category="order_confirmed", company_id=order.company_id,
        subject="Beställningen är bekräftad",
        body=(
            f"Att betala nu: {_money(order.total_now_ore)} inkl. moms. "
            f"Nästa period: {_money(order.next_period_total_ore)} inkl. moms."
        ),
        payload={"orderId": str(order.id), "kind": order.kind},
        key_parts=(order.id,),
    )


def payment_failed(subscription, *, grace_until=None) -> OutboxMessage | None:
    body = "Betalningen gick inte igenom. Uppdatera betalmetoden."
    if grace_until:
        body += f" Åtkomsten gäller till {grace_until:%Y-%m-%d %H:%M}."
    else:
        body += " Ingen betalningsfrist gäller för den här betalningen."
    return queue(
        category="payment_failed", company_id=subscription.company_id,
        subject="Betalningen misslyckades", body=body,
        key_parts=(subscription.company_id, subscription.current_period_end),
    )


def cancellation_confirmed(company_id, effective_at) -> OutboxMessage | None:
    return queue(
        category="cancellation_confirmed", company_id=company_id,
        subject="Uppsägningen är registrerad",
        body=(
            f"Abonnemanget avslutas {effective_at:%Y-%m-%d}. Fram till dess "
            "fungerar allt som vanligt. Du kan ångra uppsägningen fram till det "
            "datumet."
        ),
        key_parts=(company_id, effective_at),
    )


def device_blocked(company_id, approval) -> OutboxMessage | None:
    return queue(
        category="device_blocked", company_id=company_id,
        subject="En telefon har spärrats",
        body="Telefonen kan inte längre se tips eller ta bilen i anspråk.",
        payload={"approvalId": str(approval.id)},
        key_parts=(approval.id,),
    )
