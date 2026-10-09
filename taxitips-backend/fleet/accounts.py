"""
Konton och spärrar: plattformens sätt att stänga av ett företag, en
e-postadress eller ett enskilt konto.

**Var spärren biter.** I fleet/access.py, på varje begäran:

* ett spärrat FÖRETAG ger `company_suspended` i `company_window` -- samma
  punkt som förartelefoner, inloggade ägare och övergångsvägen passerar, så
  alla tre stängs i samma sekund;
* ett spärrat KONTO eller en spärrad E-POSTADRESS ger `account_blocked` för den
  inloggade vägen och tar bort alla administrativa behörigheter i
  `principal_for`. Förartelefoner bär ingen e-post och påverkas bara av
  företagsspärren.

**Pausade tips** (`pause`/`resume`, kinds `pause` och `user_pause`) är samma
rad men ett annat beslut: kunden betalar inte, inget fusk. De ger
`company_paused` respektive `account_paused` -- ett neutralt skäl som appen
visar utan pris eller länk -- och stoppar tips och notiser. Pausen rör aldrig
portalen (`principal_for`): ägaren ska kunna ordna medlemskapet på webben.
Säljare och plattformsadministratör pausar; spärrar är bara plattformens.

Registrering och inbjudningar prövas också mot e-postspärren, så att en
avstängd adress inte kan skapa ett nytt företag och börja om.

**Inget raderas.** En spärr är en rad; en hävning skriver `lifted_at`. Bilar,
licenser och historik ligger kvar, och vem som gjorde vad står i
revisionsloggen (`fleet_audit_event`).
"""

from __future__ import annotations

import time

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from fleet import audit
from fleet.models import AccountBlock, KnownAccount


class AccountError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.status = status


def normalize_email(value) -> str:
    return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Kontokatalogen
# ---------------------------------------------------------------------------

# Varje verifierad begäran skulle annars bli en skrivning. Tio minuter räcker
# för en katalog som bara används för att hitta ett konto i adminwebben.
_SEEN_TTL_S = 600
_seen_cache: dict[str, tuple[str, float]] = {}


def seen(payload: dict | None) -> None:
    """
    Bokför kontot ur en VERIFIERAD Supabase-token. Aldrig ur anropets kropp.

    Tyst vid fel: katalogen är en bekvämlighet för adminwebben, och en
    misslyckad skrivning här får aldrig neka en förare tips.
    """
    if not payload:
        return
    # Senaste inloggning, appversion och telefon (fleet/client_activity.py).
    # Före e-postkontrollen: ett konto utan e-post i token är fortfarande ett
    # konto som supporten kan behöva felsöka. Har egen skrivspärr och är tyst.
    from fleet import client_activity

    client_activity.note_user(payload)
    user_id = str(payload.get("sub") or "")
    email = normalize_email(payload.get("email"))
    if not user_id or not email:
        return
    cached = _seen_cache.get(user_id)
    now_s = time.monotonic()
    if cached and cached[0] == email and now_s - cached[1] < _SEEN_TTL_S:
        return
    try:
        with transaction.atomic():
            KnownAccount.objects.update_or_create(
                user_id=user_id,
                defaults={"email": email, "last_seen_at": timezone.now()},
            )
        _seen_cache[user_id] = (email, now_s)
    except Exception:  # noqa: BLE001 -- se docstring
        pass


def email_for(user_id) -> str:
    row = KnownAccount.objects.filter(user_id=user_id).first()
    return row.email if row else ""


def user_ids_for_email(email: str) -> list:
    """Konton som senast setts med adressen (katalogen, inte Supabase Auth)."""
    email = normalize_email(email)
    if not email:
        return []
    return list(KnownAccount.objects.filter(email=email).values_list("user_id", flat=True))


def emails_for(user_ids) -> dict[str, str]:
    return {
        str(row.user_id): row.email
        for row in KnownAccount.objects.filter(user_id__in=[u for u in user_ids if u])
    }


# ---------------------------------------------------------------------------
# Spärrar
# ---------------------------------------------------------------------------


def _active():
    return AccountBlock.objects.filter(lifted_at__isnull=True)


def company_block(company_id) -> AccountBlock | None:
    if not company_id:
        return None
    return _active().filter(kind=AccountBlock.Kind.COMPANY, value=str(company_id)).first()


def company_pause(company_id) -> AccountBlock | None:
    if not company_id:
        return None
    return _active().filter(kind=AccountBlock.Kind.PAUSE, value=str(company_id)).first()


def account_pause(user_id) -> AccountBlock | None:
    if not user_id:
        return None
    return _active().filter(kind=AccountBlock.Kind.USER_PAUSE, value=str(user_id)).first()


_COMPANY_KINDS = (AccountBlock.Kind.COMPANY, AccountBlock.Kind.PAUSE)


def account_block(*, user_id=None, email: str = "") -> AccountBlock | None:
    """Spärren som gäller ett konto, via dess id eller dess e-postadress."""
    email = normalize_email(email)
    if not user_id and not email:
        return None
    if not email and user_id:
        email = email_for(user_id)
    q = Q()
    if user_id:
        q |= Q(kind=AccountBlock.Kind.USER, value=str(user_id))
    if email:
        q |= Q(kind=AccountBlock.Kind.EMAIL, value=email)
    return _active().filter(q).first()


def assert_email_allowed(email: str) -> None:
    """För registrering och inbjudningar: en spärrad adress börjar inte om."""
    if account_block(email=email) is not None:
        raise AccountError(
            "account_blocked",
            "E-postadressen är spärrad. Kontakta TaxiTips support.",
            status=403,
        )


def _normalize_value(kind: str, value) -> str:
    value = str(value or "").strip()
    if kind == AccountBlock.Kind.EMAIL:
        value = normalize_email(value)
        if "@" not in value or len(value) > 320:
            raise AccountError("invalid_email", "Ange en giltig e-postadress.")
        return value
    import uuid

    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise AccountError("invalid_id", "Id:t går inte att tolka.") from exc


def block(
    *, kind: str, value, reason: str, actor_user_id, company_id=None,
    action: str = "", actor_kind: str = "platform_admin",
) -> AccountBlock:
    if kind not in AccountBlock.Kind.values:
        raise AccountError("invalid_kind", "Okänd sorts spärr.")
    reason = str(reason or "").strip()[:500]
    if not reason:
        raise AccountError("reason_required", "Skriv varför spärren läggs.")
    value = _normalize_value(kind, value)
    # Den som spärrar sig själv låser ute den enda som kan häva spärren.
    if kind in (AccountBlock.Kind.USER, AccountBlock.Kind.USER_PAUSE) and value == str(actor_user_id):
        raise AccountError("self_block", "Du kan inte spärra ditt eget konto.")
    if kind == AccountBlock.Kind.EMAIL and value == email_for(actor_user_id):
        raise AccountError("self_block", "Du kan inte spärra din egen e-postadress.")
    try:
        with transaction.atomic():
            row = AccountBlock.objects.create(
                kind=kind, value=value, reason=reason, created_by=actor_user_id,
            )
    except IntegrityError as exc:
        raise AccountError("already_blocked", "Det finns redan en aktiv spärr.", status=409) from exc
    audit.record(
        action or f"admin_block_{kind}",
        # Företagets spärr/paus, eller kontots paus lagd från en kundsida.
        company_id=company_id,
        actor_user_id=actor_user_id, actor_kind=actor_kind,
        subject_type="account_block", subject_id=row.id,
        detail={"kind": kind, "value": value, "reason": reason},
    )
    return row


def lift(
    block_id, *, actor_user_id, note: str = "", action: str = "",
    actor_kind: str = "platform_admin", company_id=None,
) -> AccountBlock:
    row = _active().filter(id=block_id).first()
    if row is None:
        raise AccountError("unknown_block", "Spärren finns inte eller är redan hävd.", status=404)
    AccountBlock.objects.filter(id=row.id, lifted_at__isnull=True).update(
        lifted_at=timezone.now(), lifted_by=actor_user_id, lift_note=str(note or "")[:500],
    )
    row.refresh_from_db()
    audit.record(
        action or f"admin_unblock_{row.kind}",
        company_id=row.value if row.kind in _COMPANY_KINDS else company_id,
        actor_user_id=actor_user_id, actor_kind=actor_kind,
        subject_type="account_block", subject_id=row.id,
        detail={"kind": row.kind, "value": row.value, "note": row.lift_note},
    )
    return row


def block_row(row: AccountBlock) -> dict:
    return {
        "id": str(row.id), "kind": row.kind, "value": row.value, "reason": row.reason,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "createdBy": str(row.created_by) if row.created_by else None,
        "createdByEmail": email_for(row.created_by) if row.created_by else "",
        "liftedAt": row.lifted_at.isoformat() if row.lifted_at else None,
        "liftNote": row.lift_note,
    }


# ---------------------------------------------------------------------------
# Pausade tips (kunden betalar inte -- inte en spärr)
# ---------------------------------------------------------------------------


def _pause_kind(scope: str) -> str:
    if scope == "company":
        return AccountBlock.Kind.PAUSE
    if scope == "user":
        return AccountBlock.Kind.USER_PAUSE
    raise AccountError("invalid_kind", "Okänd sorts paus.")


def pause(*, scope: str, value, reason: str, actor_user_id, actor_kind: str,
          company_id=None) -> tuple[AccountBlock, bool]:
    """
    Pausar tipsen för ett företag (`scope="company"`) eller ett konto
    (`scope="user"`). Idempotent: en redan pausad sak returneras som den är,
    med `created=False`. Kräver skäl; skrivs i revisionsloggen.
    """
    kind = _pause_kind(scope)
    if not str(reason or "").strip():
        raise AccountError("reason_required", "Skriv varför tipsen pausas.")
    existing = _active().filter(kind=kind, value=_normalize_value(kind, value)).first()
    if existing is not None:
        return existing, False
    try:
        row = block(
            kind=kind, value=value, reason=reason, actor_user_id=actor_user_id,
            company_id=company_id, action=f"{scope}_tips_paused", actor_kind=actor_kind,
        )
    except AccountError as exc:
        if exc.reason != "already_blocked":
            raise
        # Två samtidiga klick: den andra läser den första radens paus.
        return _active().filter(kind=kind, value=_normalize_value(kind, value)).first(), False
    return row, True


def resume(*, scope: str, value, actor_user_id, actor_kind: str, note: str = "",
           company_id=None) -> AccountBlock | None:
    """Häver pausen. Idempotent: None när inget var pausat."""
    kind = _pause_kind(scope)
    row = _active().filter(kind=kind, value=_normalize_value(kind, value)).first()
    if row is None:
        return None
    try:
        return lift(
            row.id, actor_user_id=actor_user_id, note=note,
            action=f"{scope}_tips_resumed", actor_kind=actor_kind, company_id=company_id,
        )
    except AccountError as exc:
        if exc.reason != "unknown_block":
            raise
        return None
