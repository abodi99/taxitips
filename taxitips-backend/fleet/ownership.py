"""
Ägarroll, medlemmar, kontostängning och byte av avtalspart.

**Sista ägaren kan inte tas bort.** Ett aktivt betalabonnemang utan ägare har
ingen som får säga upp det, ingen som får uppdatera betalmetoden och ingen som
kan svara på en betalningsfråga -- kunden blir inlåst i en avgift ingen kan
avsluta. Kontrollen ligger på servern, i `remove_member`, och inte bara som en
gråad knapp (§10).

**Överföring kräver två steg.** Avsändaren måste ha en färsk, tvåfaktorsäkrad
session; mottagaren måste uttryckligen acceptera. Ett ensidigt byte hade gjort
en kapad session till ett sätt att låsa ut den riktiga ägaren.

**Byte av organisationsnummer är inte en profiländring.** Det är ett byte av
avtalspart och kräver granskning. Det ger heller inget nytt gratisprov:
provhistoriken är nyckelad på organisationsnumret, och den gamla raden ligger
kvar (§10).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from billing.models import CompanyMember
from fleet import audit, orgnr, roles
from fleet.models import (
    ChangeReview,
    CompanyProfile,
    OwnershipTransfer,
    Subscription,
    SubscriptionStatus,
    Trial,
)

TRANSFER_VALID_DAYS = 7


class OwnershipError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


def owners(company_id) -> list[CompanyMember]:
    return list(
        CompanyMember.objects.filter(
            company_id=company_id, role=roles.OWNER, status="active"
        )
    )


def has_active_paid_subscription(company_id, now=None) -> bool:
    now = now or timezone.now()
    subscription = Subscription.objects.filter(company_id=company_id).first()
    if subscription is None:
        return False
    if subscription.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE):
        return True
    if subscription.status == SubscriptionStatus.CANCELED:
        until = subscription.access_until or subscription.current_period_end
        return bool(until and until > now)
    return False


@transaction.atomic
def remove_member(*, company_id, user_id, actor_user_id, now=None) -> None:
    """
    Tar bort en medlem. Vägrar om det skulle lämna ett aktivt betalabonnemang
    ägarlöst.
    """
    now = now or timezone.now()
    member = CompanyMember.objects.filter(
        company_id=company_id, user_id=user_id, status="active"
    ).first()
    if member is None:
        raise OwnershipError("unknown_member", "Personen är inte medlem i företaget.", 404)

    if member.role == roles.OWNER:
        remaining = [o for o in owners(company_id) if str(o.user_id) != str(user_id)]
        if not remaining and has_active_paid_subscription(company_id, now):
            raise OwnershipError(
                "last_owner",
                "Företaget skulle bli utan ägare med ett aktivt abonnemang. "
                "Överför ägarrollen först, eller avsluta abonnemanget.",
                409,
            )

    CompanyMember.objects.filter(id=member.id).update(status="removed")
    audit.record(
        "member_removed", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="member", subject_id=member.id,
        detail={"user_id": str(user_id), "role": member.role},
    )


@transaction.atomic
def request_transfer(*, company_id, from_principal: roles.Principal, to_user_id, now=None):
    """
    Startar överföringen av ägarrollen. Kräver TRANSFER_OWNERSHIP och -- när
    kravet är påslaget -- en tvåfaktorsäkrad session (ny autentisering).
    """
    now = now or timezone.now()
    roles.require(from_principal, roles.Perm.TRANSFER_OWNERSHIP, now=now)

    if str(to_user_id) == str(from_principal.user_id):
        raise OwnershipError("same_user", "Mottagaren är redan ägare.")
    recipient = CompanyMember.objects.filter(
        company_id=company_id, user_id=to_user_id, status="active"
    ).first()
    if recipient is None:
        raise OwnershipError(
            "recipient_not_member",
            "Mottagaren måste vara medlem i företaget innan ägarrollen överförs.",
        )

    OwnershipTransfer.objects.filter(
        company_id=company_id, status=OwnershipTransfer.Status.PENDING
    ).update(status=OwnershipTransfer.Status.CANCELED, resolved_at=now)

    transfer = OwnershipTransfer.objects.create(
        company_id=company_id, from_user_id=from_principal.user_id, to_user_id=to_user_id,
        expires_at=now + timedelta(days=TRANSFER_VALID_DAYS),
    )
    audit.record(
        "ownership_transfer_requested", company_id=company_id,
        actor_user_id=from_principal.user_id, actor_kind="owner",
        subject_type="transfer", subject_id=transfer.id,
        detail={"to_user_id": str(to_user_id)},
    )
    return transfer


@transaction.atomic
def accept_transfer(*, transfer: OwnershipTransfer, by_user_id, now=None) -> OwnershipTransfer:
    """
    Mottagarens acceptans. Först här byter rollerna plats.

    Avsändaren blir fordonsadministratör i stället för att tas bort: företaget
    ska aldrig passera ett läge utan ägare, och den gamla ägaren ska inte
    tappa åtkomsten mitt i ett skift.
    """
    now = now or timezone.now()
    if str(transfer.to_user_id) != str(by_user_id):
        raise OwnershipError("not_recipient", "Bara mottagaren kan acceptera.", 403)
    if transfer.status != OwnershipTransfer.Status.PENDING:
        raise OwnershipError("transfer_closed", "Överföringen är inte längre öppen.", 409)
    if transfer.expires_at <= now:
        OwnershipTransfer.objects.filter(id=transfer.id).update(
            status=OwnershipTransfer.Status.EXPIRED, resolved_at=now
        )
        raise OwnershipError("transfer_expired", "Överföringen har gått ut.", 409)

    CompanyMember.objects.filter(
        company_id=transfer.company_id, user_id=transfer.to_user_id, status="active"
    ).update(role=roles.OWNER)
    CompanyMember.objects.filter(
        company_id=transfer.company_id, user_id=transfer.from_user_id, status="active"
    ).update(role=roles.FLEET_ADMIN)
    OwnershipTransfer.objects.filter(id=transfer.id).update(
        status=OwnershipTransfer.Status.ACCEPTED, resolved_at=now
    )
    transfer.refresh_from_db()
    audit.record(
        "ownership_transfer_accepted", company_id=transfer.company_id,
        actor_user_id=by_user_id, actor_kind="owner",
        subject_type="transfer", subject_id=transfer.id,
        detail={"from_user_id": str(transfer.from_user_id)},
    )
    return transfer


@transaction.atomic
def close_account(*, company_id, actor_user_id, now=None) -> dict:
    """
    Avslutar företagskontot: stoppar framtida förnyelse och förklarar vad som
    händer med kvarvarande data och åtkomst (§8).

    Att ta bort förare eller avinstallera appen gör INTE det här -- det är två
    olika saker, och att blanda ihop dem är hur ett abonnemang fortsätter
    debitera ett företag som tror att det slutat.
    """
    from fleet import orders

    now = now or timezone.now()
    change = orders.cancel_subscription(
        company_id, actor_user_id=actor_user_id, reason="account_closed", now=now
    )
    subscription = orders.get_or_create_subscription(company_id)
    Subscription.objects.filter(id=subscription.id).update(renewal_stopped_at=now)
    subscription.refresh_from_db()

    audit.record(
        "account_closed", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="owner", subject_type="company", subject_id=company_id,
        detail={"access_until": change.effective_at.isoformat()},
    )
    return {
        "accessUntil": change.effective_at.isoformat(),
        "renewalStopped": True,
        "explanation": (
            "Abonnemanget förnyas inte. Åtkomsten gäller till "
            f"{change.effective_at:%Y-%m-%d}. Fakturor och beställningar finns "
            "kvar för behörig kund enligt bokföringsreglerna; detaljerade "
            "sessionsloggar gallras enligt gallringsregeln. Provhistoriken "
            "behålls -- ett nytt konto med samma organisationsnummer ger inte "
            "en ny gratisperiod."
        ),
    }


@transaction.atomic
def change_contracting_party(
    *, company_id, country: str, org_number: str, actor_user_id, note: str = "", now=None
) -> ChangeReview:
    """
    Byte av organisationsnummer = byte av avtalspart. Öppnar ett
    granskningsärende i stället för att skriva om profilen.

    Provhistoriken flyttas inte och nollas inte: det gamla numret behåller sin
    rad, och det nya prövas mot sin egen historik. Ett byte av avtalspart är
    inget sätt att få ett nytt gratisprov (§10).
    """
    now = now or timezone.now()
    normalized = orgnr.normalize(org_number, country)
    if not orgnr.is_valid(org_number, country):
        raise OwnershipError("invalid_org_number", "Organisationsnumret går inte att tolka.")

    profile = CompanyProfile.objects.filter(company_id=company_id).first()
    if profile is None:
        raise OwnershipError("no_profile", "Företagsprofilen saknas.", 404)
    if profile.org_number == normalized and profile.country == (country or "SE").upper():
        raise OwnershipError("unchanged", "Organisationsnumret är redan det.")

    previous_trials = Trial.objects.filter(
        org_key=orgnr.org_key(country, org_number)
    ).count()

    review = ChangeReview.objects.create(
        company_id=company_id, kind=ChangeReview.Kind.OWNERSHIP_TRANSFER,
        customer_message=(
            "Byte av avtalspart granskas. Nuvarande abonnemang och åtkomst "
            "fortsätter som vanligt under tiden."
        ),
        detail={
            "from": {"country": profile.country, "org_number": profile.org_number},
            "to": {"country": (country or "SE").upper(), "org_number": normalized},
            "note": note[:500],
            "trials_on_target_org": previous_trials,
        },
    )
    audit.record(
        "contracting_party_change_requested", company_id=company_id,
        actor_user_id=actor_user_id, actor_kind="owner",
        subject_type="review", subject_id=review.id,
        detail={"to_org_number": normalized},
    )
    return review
