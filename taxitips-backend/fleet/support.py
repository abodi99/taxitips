"""
Supportchatten: användare skriver i appen, personalen svarar i adminwebben.

**Vem som skriver.** Två sorters användare, med olika bevis:

* ett inloggat konto (`Authorization: Bearer <supabase-jwt>`) -- ägare och
  administratörer, även ett konto vars registrering inte är klar,
* en förartelefon (`X-Device-Token`) -- förare har inget konto.

Skickar appen båda (en ägare som också kör med telefonen) gäller kontot: det är
en person, och den ska se samma konversation vilken telefon den än använder.

**Varken betalning eller godkännande krävs.** En förare vars telefon spärrats,
eller ett bolag vars prov gått ut, är precis de som behöver fråga något. Ett
SPÄRRAT KONTO (fleet/accounts.py) får däremot inte skriva: spärren gäller
plattformen, och chatten är en del av den.

**Bara text.** Inga filer, inga bilder (beslut 2026-09-26). Längden är begränsad
så att ett meddelande alltid ryms i en notis och i adminwebbens lista.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from billing.models import Company, CompanyMember, Device
from fleet import audit, ratelimit
from fleet.models import SupportMessage, SupportThread
from fleet.roles import PermissionDenied

MAX_BODY = 2000
# Hur många meddelanden en konversation visar. Äldre finns kvar i databasen;
# en supportchatt som behöver mer historik än så är ett ärende för mejl.
HISTORY = 200
STAFF_NAME = "TaxiTips support"


class SupportError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Requester:
    """Den som skriver från appen."""

    kind: str
    user_id: str | None = None
    device_id: str | None = None
    company_id: str | None = None
    label: str = ""

    @property
    def identity(self) -> str:
        return f"{self.kind}:{self.user_id or self.device_id}"


def requester_for(request) -> Requester:
    """Kontot först, annars telefonen. Kastar om ingen av dem är giltig."""
    from core.entitlement import verify_supabase_jwt
    from fleet import access, accounts

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        payload = verify_supabase_jwt(auth[7:].strip())
        if payload and payload.get("sub"):
            user_id = str(payload["sub"])
            email = str(payload.get("email") or "")
            if accounts.account_block(user_id=user_id, email=email) is not None:
                raise PermissionDenied(
                    "account_blocked", "Kontot är spärrat. Mejla hej@taxitips.se.",
                )
            member = CompanyMember.objects.filter(user_id=user_id, status="active").first()
            return Requester(
                kind=SupportThread.Requester.MEMBER, user_id=user_id,
                company_id=str(member.company_id) if member else None,
                label=email or "Konto",
            )

    token = request.headers.get("X-Device-Token") or ""
    if token:
        device, _credential, _how = access.device_for_token(token)
        if device is not None:
            return Requester(
                kind=SupportThread.Requester.DEVICE, device_id=str(device.id),
                company_id=str(device.company_id) if device.company_id else None,
                label=device.label or "Förartelefon",
            )

    raise PermissionDenied("login_required", "Logga in eller anslut telefonen först.", status=401)


def thread_for(requester: Requester) -> SupportThread | None:
    if requester.kind == SupportThread.Requester.MEMBER:
        return SupportThread.objects.filter(user_id=requester.user_id).first()
    return SupportThread.objects.filter(device_id=requester.device_id).first()


def _clean(body) -> str:
    text = str(body or "").strip()
    if not text:
        raise SupportError("empty_message", "Skriv ett meddelande först.")
    if len(text) > MAX_BODY:
        raise SupportError(
            "message_too_long", f"Meddelandet får vara högst {MAX_BODY} tecken.",
        )
    return text


def _get_or_create_thread(requester: Requester) -> SupportThread:
    """
    Tråden för användaren, skapad vid första meddelandet.

    Två samtidiga första meddelanden krockar på det unika indexet; den som
    förlorar läser den som vann i stället för att få ett fel.
    """
    existing = thread_for(requester)
    if existing is not None:
        return existing
    fields = {
        "requester_kind": requester.kind,
        "company_id": requester.company_id,
        "requester_label": requester.label[:200],
    }
    if requester.kind == SupportThread.Requester.MEMBER:
        fields["user_id"] = requester.user_id
    else:
        fields["device_id"] = requester.device_id
    try:
        with transaction.atomic():
            return SupportThread.objects.create(**fields)
    except IntegrityError:
        found = thread_for(requester)
        if found is None:
            raise
        return found


def post_customer_message(requester: Requester, body, *, now=None) -> tuple[SupportThread, SupportMessage]:
    """Användarens meddelande. Öppnar en avslutad konversation igen."""
    text = _clean(body)
    ratelimit.enforce(ratelimit.SUPPORT_MESSAGE, requester.identity)
    now = now or timezone.now()
    with transaction.atomic():
        thread = _get_or_create_thread(requester)
        thread = SupportThread.objects.select_for_update().get(id=thread.id)
        message = SupportMessage.objects.create(
            thread=thread, sender=SupportMessage.Sender.CUSTOMER, body=text,
            author_user_id=requester.user_id, author_device_id=requester.device_id,
        )
        reopened = thread.status == SupportThread.Status.CLOSED
        # Bolag och namn följer användaren: en telefon som flyttats till ett
        # nytt bolag ska synas under det nya i supportens lista.
        SupportThread.objects.filter(id=thread.id).update(
            status=SupportThread.Status.OPEN, closed_at=None, closed_by=None,
            last_message_at=message.created_at, last_customer_message_at=message.created_at,
            customer_read_at=message.created_at,
            company_id=requester.company_id or thread.company_id,
            requester_label=(requester.label or thread.requester_label)[:200],
        )
    if reopened:
        audit.record(
            "support_thread_reopened", company_id=thread.company_id, actor_kind="customer",
            subject_type="support_thread", subject_id=thread.id,
        )
    thread.refresh_from_db()
    return thread, message


def post_staff_message(thread: SupportThread, *, staff_user_id, body, now=None) -> SupportMessage:
    """Supportens svar. Notisen till användaren skickas efter commit."""
    text = _clean(body)
    with transaction.atomic():
        locked = SupportThread.objects.select_for_update().get(id=thread.id)
        message = SupportMessage.objects.create(
            thread=locked, sender=SupportMessage.Sender.STAFF, body=text,
            author_user_id=staff_user_id,
        )
        SupportThread.objects.filter(id=locked.id).update(
            status=SupportThread.Status.OPEN, closed_at=None, closed_by=None,
            last_message_at=message.created_at, last_staff_message_at=message.created_at,
            staff_read_at=message.created_at,
        )
        transaction.on_commit(lambda: _enqueue_reply_push(str(locked.id), str(message.id)))
    audit.record(
        "support_reply", company_id=locked.company_id, actor_user_id=staff_user_id,
        actor_kind="staff", subject_type="support_thread", subject_id=locked.id,
        detail={"message_id": str(message.id), "length": len(text)},
    )
    thread.refresh_from_db()
    return message


def _enqueue_reply_push(thread_id: str, message_id: str) -> None:
    from fleet.tasks import send_support_reply_push

    try:
        send_support_reply_push.delay(thread_id, message_id)
    except Exception:  # pragma: no cover - en nere kö får inte fälla svaret
        import logging

        logging.getLogger(__name__).exception("support: notisen kunde inte köas")


def set_status(thread: SupportThread, status: str, *, staff_user_id, now=None) -> SupportThread:
    if status not in SupportThread.Status.values:
        raise SupportError("invalid_status", "Okänd status.")
    now = now or timezone.now()
    closed = status == SupportThread.Status.CLOSED
    SupportThread.objects.filter(id=thread.id).update(
        status=status, closed_at=now if closed else None,
        closed_by=staff_user_id if closed else None,
        # Att avsluta är att ha läst: en avslutad tråd ska inte ligga kvar
        # som "väntar på svar".
        **({"staff_read_at": now} if closed else {}),
    )
    audit.record(
        "support_thread_closed" if closed else "support_thread_reopened",
        company_id=thread.company_id, actor_user_id=staff_user_id, actor_kind="staff",
        subject_type="support_thread", subject_id=thread.id,
    )
    thread.refresh_from_db()
    return thread


def mark_read_by_customer(thread: SupportThread, now=None) -> None:
    now = now or timezone.now()
    SupportThread.objects.filter(id=thread.id).update(customer_read_at=now)


def mark_read_by_staff(thread: SupportThread, now=None) -> None:
    now = now or timezone.now()
    SupportThread.objects.filter(id=thread.id).update(staff_read_at=now)


def thread_for_company_owner(company_id, *, staff_user_id) -> SupportThread:
    """
    Personalen startar en konversation med ett bolag: den går till ägarens
    konto, eftersom det är ägaren som har ett konto att läsa den med.
    """
    from fleet import roles

    active = CompanyMember.objects.filter(company_id=company_id, status="active")
    owner = active.filter(role=roles.OWNER).first() or active.first()
    if owner is None or owner.user_id is None:
        raise SupportError(
            "no_account", "Företaget har inget konto att skriva till. Ring eller mejla kunden.",
            status=409,
        )
    company = Company.objects.filter(id=company_id).first()
    requester = Requester(
        kind=SupportThread.Requester.MEMBER, user_id=str(owner.user_id),
        company_id=str(company_id), label=(company.email if company else "") or "Ägaren",
    )
    thread = _get_or_create_thread(requester)
    audit.record(
        "support_thread_started", company_id=company_id, actor_user_id=staff_user_id,
        actor_kind="staff", subject_type="support_thread", subject_id=thread.id,
    )
    return thread


# ---------------------------------------------------------------------------
# Läsning
# ---------------------------------------------------------------------------


def unread_for_customer(thread: SupportThread | None) -> int:
    if thread is None:
        return 0
    rows = thread.messages.filter(sender=SupportMessage.Sender.STAFF)
    if thread.customer_read_at:
        rows = rows.filter(created_at__gt=thread.customer_read_at)
    return rows.count()


def waiting_for_staff(thread: SupportThread) -> bool:
    """Användaren har skrivit något supporten inte läst."""
    if thread.status != SupportThread.Status.OPEN or not thread.last_customer_message_at:
        return False
    return not thread.staff_read_at or thread.last_customer_message_at > thread.staff_read_at


def waiting_threads():
    """Öppna trådar med ett oläst meddelande från användaren."""
    return SupportThread.objects.filter(
        status=SupportThread.Status.OPEN, last_customer_message_at__isnull=False,
    ).filter(
        Q(staff_read_at__isnull=True) | Q(last_customer_message_at__gt=F("staff_read_at"))
    )


def message_row(message: SupportMessage) -> dict:
    return {
        "id": str(message.id),
        "sender": message.sender,
        "body": message.body,
        "createdAt": message.created_at.isoformat(),
        "author": STAFF_NAME if message.sender == SupportMessage.Sender.STAFF else "",
    }


def messages_for(thread: SupportThread) -> list[dict]:
    rows = list(thread.messages.order_by("-created_at")[:HISTORY])
    rows.reverse()
    return [message_row(m) for m in rows]


def thread_row(thread: SupportThread, *, company_names: dict | None = None) -> dict:
    names = company_names or {}
    return {
        "id": str(thread.id),
        "status": thread.status,
        "requesterKind": thread.requester_kind,
        "requesterLabel": thread.requester_label,
        "companyId": str(thread.company_id) if thread.company_id else None,
        "companyName": names.get(str(thread.company_id)) if thread.company_id else None,
        "lastMessageAt": thread.last_message_at.isoformat() if thread.last_message_at else None,
        "waiting": waiting_for_staff(thread),
        "createdAt": thread.created_at.isoformat(),
    }


def company_names(threads) -> dict:
    ids = {t.company_id for t in threads if t.company_id}
    return {str(c.id): c.name for c in Company.objects.filter(id__in=ids)}


def device_push_targets(thread: SupportThread) -> list[Device]:
    """
    Vart notisen om ett svar ska. Förartelefonen själv, eller -- för ett konto
    -- varje telefon där kontot är inloggat (`devices.user_id`).
    """
    if thread.requester_kind == SupportThread.Requester.DEVICE:
        rows = Device.objects.filter(id=thread.device_id)
    else:
        rows = Device.objects.filter(user_id=thread.user_id)
    return [d for d in rows.exclude(push_token__isnull=True) if (d.push_token or "").strip()]
