"""
Avslutade bolag: arkivera (dölj) och radera (ta bort för gott).

**Arkivera** döljer ett bolag från Hem, Kunder och Uppföljning i adminwebben.
Ingenting tas bort, och "Återställ" tar tillbaka det. Kräver att bolaget
saknar åtkomst: ett bolag som fortfarande har en period eller ett pågående prov
ska avslutas först, annars försvinner en kund som kör ur listan.

**Radera** tar bort bolaget och allt som hör till det: bilar, licenser,
telefoner, förarpass, beställningar, supportchatten, notiser och kontakt-
uppgifterna. Två saker finns kvar med avsikt:

* **Provhistoriken** (`fleet_trial`, nycklad på land + organisationsnummer).
  Utan den kunde samma bolag registrera sig igen dagen efter och få ett nytt
  gratisprov (fleet/trials.py). Raden bär bara org-nyckeln och datum.
* **Revisionsloggen** (`fleet_audit_event`), plus en rad om själva raderingen:
  vem som raderade vad och när ska gå att svara på i efterhand.

Radering kräver plattformsadministratör, ett arkiverat bolag och att bolaget
**aldrig betalat**. Ett bolag som betalat har bokföringsunderlag
(beställningar, fakturareferenser) som ska sparas i sju år
(bokföringslagen 7 kap. 2 §); det arkiveras i stället.

**Medlemmarnas inloggningskonton i Supabase Auth raderas med bolaget.** Ett
konto som lämnades kvar utan bolag kunde fortfarande logga in, och samma
e-postadress gick inte att registrera på nytt ("adressen är redan
registrerad") -- en ny kund med samma adress blev utelåst. Kontot hör till
bolaget och ska bort med det (2026-10-07). Raderingen är bästa möjliga: en
Auth-tjänst som ligger nere får inte stoppa själva bolagsraderingen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import connection, transaction
from django.utils import timezone

from billing.models import Company, CompanyMember, Device
from fleet import audit, auth_admin
from fleet.access import company_window
from fleet.models import (
    AccountBlock,
    ChangeReview,
    CompanyProfile,
    CountyChange,
    CountyChangeGrant,
    CouponRedemption,
    DeviceApproval,
    DeviceCredential,
    DriverInvite,
    JoinRequest,
    License,
    LicenseCounty,
    Order,
    OutboxMessage,
    OwnerInvite,
    OwnershipTransfer,
    PairingCode,
    PendingChange,
    RiskSignal,
    SalesFollowUp,
    Subscription,
    SubscriptionStatus,
    SupportThread,
    Vehicle,
    VehicleAssignment,
    VehicleSession,
)


class ArchiveError(Exception):
    def __init__(self, reason: str, message: str, status: int = 409):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class State:
    archived_at: object | None
    can_archive: bool
    archive_blocker: str
    can_delete: bool
    delete_blocker: str

    def as_dict(self) -> dict:
        return {
            "archivedAt": self.archived_at.isoformat() if self.archived_at else None,
            "canArchive": self.can_archive,
            "archiveBlocker": self.archive_blocker,
            "canDelete": self.can_delete,
            "deleteBlocker": self.delete_blocker,
        }


def has_paid(company_id) -> bool:
    """Har bolaget någonsin betalat? Då finns bokföringsunderlag."""
    if Subscription.objects.filter(company_id=company_id, had_successful_payment=True).exists():
        return True
    return Order.objects.filter(company_id=company_id, status=Order.Status.PAID).exists()


def state(company_id, now=None) -> State:
    now = now or timezone.now()
    profile = CompanyProfile.objects.filter(company_id=company_id).first()
    archived_at = profile.archived_at if profile else None

    archive_blocker = ""
    if company_window(company_id, now).ok:
        archive_blocker = "Bolaget har fortfarande åtkomst. Avsluta abonnemanget eller provet först."
    elif License.objects.filter(
        company_id=company_id,
        status__in=[License.Status.ACTIVE, License.Status.TRIAL, License.Status.PENDING_CANCEL],
    ).exists():
        archive_blocker = "Bolaget har bilar som inte är avslutade."
    elif Order.objects.filter(company_id=company_id, status=Order.Status.PENDING_PAYMENT).exists():
        archive_blocker = "En beställning väntar på betalning. Avbryt den först."

    delete_blocker = ""
    if not archived_at:
        delete_blocker = "Arkivera bolaget först."
    elif has_paid(company_id):
        delete_blocker = (
            "Bolaget har betalat. Bokföringsunderlag sparas i sju år, så bolaget "
            "kan bara arkiveras."
        )
    elif Subscription.objects.filter(
        company_id=company_id,
        status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE],
    ).exists():
        delete_blocker = "Abonnemanget är inte avslutat."

    return State(
        archived_at=archived_at,
        can_archive=not archive_blocker and not archived_at,
        archive_blocker=archive_blocker,
        can_delete=not delete_blocker,
        delete_blocker=delete_blocker,
    )


def archived_ids() -> set:
    return set(
        CompanyProfile.objects.filter(archived_at__isnull=False).values_list("company_id", flat=True)
    )


def archive(company_id, *, actor_user_id, force: bool = False, now=None) -> None:
    now = now or timezone.now()
    current = state(company_id, now)
    if current.archived_at:
        return
    if not current.can_archive and not force:
        raise ArchiveError("cannot_archive", current.archive_blocker)
    profile, _ = CompanyProfile.objects.get_or_create(company_id=company_id)
    CompanyProfile.objects.filter(company_id=profile.company_id).update(
        archived_at=now, archived_by=actor_user_id,
    )
    audit.record(
        "company_archived", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="platform_admin", subject_type="company", subject_id=company_id,
    )


def unarchive(company_id, *, actor_user_id) -> None:
    CompanyProfile.objects.filter(company_id=company_id).update(archived_at=None, archived_by=None)
    audit.record(
        "company_unarchived", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="platform_admin", subject_type="company", subject_id=company_id,
    )


def _delete_auth_accounts(user_ids) -> int:
    """
    Raderar bolagets konton i Supabase Auth -- medlemmarna och förarna som
    bjudits in med e-post.

    Kontot hör till bolaget: lämnas det kvar kunde det fortsätta logga in, och
    e-postadressen gick inte att registrera på nytt -- nästa kund med samma
    adress blev utelåst. Bästa möjliga: en Auth-tjänst som ligger nere får inte
    stoppa bolagsraderingen (raden som tas bort är det som stänger åtkomsten,
    och ett konto utan medlemskap får ändå ingen företagsdata). Nyckeln saknas
    bara i lokal utveckling och i testerna; då loggas det och inget mer händer.
    """
    users = [str(u) for u in user_ids if u]
    if not users:
        return 0
    if not auth_admin.configured():
        log.warning(
            "archive.delete: SUPABASE_SERVICE_ROLE_KEY saknas -- %d Auth-konto(n) lämnas kvar",
            len(users),
        )
        return 0
    deleted = 0
    for user_id in users:
        try:
            auth_admin.delete_user(user_id)
            deleted += 1
        except auth_admin.AuthAdminError as exc:
            log.warning("archive.delete: Auth-raderingen misslyckades för %s: %s", user_id, exc)
    return deleted


@transaction.atomic
def delete(company_id, *, actor_user_id, confirm_name: str, now=None) -> dict:
    """Tar bort bolaget för gott. Se modulens docstring för vad som finns kvar."""
    now = now or timezone.now()
    company = Company.objects.select_for_update().filter(id=company_id).first()
    if company is None:
        raise ArchiveError("not_found", "Bolaget finns inte.", status=404)
    if (confirm_name or "").strip() != (company.name or "").strip():
        raise ArchiveError(
            "confirm_name_mismatch", "Skriv bolagets namn exakt som det står för att radera.",
            status=400,
        )
    current = state(company_id, now)
    if not current.can_delete:
        raise ArchiveError("cannot_delete", current.delete_blocker)

    device_ids = list(Device.objects.filter(company_id=company_id).values_list("id", flat=True))
    member_ids = list(
        CompanyMember.objects.filter(company_id=company_id).values_list("user_id", flat=True)
    )
    # Förarna som bjudits in med e-post är inte medlemmar i bolaget, men deras
    # Auth-konton hör ändå hit och ska bort med bolaget. consumed_by_user är
    # kontot som löste in inbjudan, auth_user_id kontot som länken skapade.
    driver_user_ids: set[str] = set()
    for field in ("consumed_by_user", "auth_user_id"):
        for uid in DriverInvite.objects.filter(company_id=company_id).values_list(field, flat=True):
            if uid:
                driver_user_ids.add(str(uid))
    counts: dict[str, int] = {}

    def gone(label, queryset):
        deleted, _ = queryset.delete()
        if deleted:
            counts[label] = counts.get(label, 0) + deleted

    # Barnen först; ordningen följer de främmande nycklarna mellan tabellerna.
    gone("förarpass", VehicleSession.objects.filter(company_id=company_id))
    gone("telefonnycklar", DeviceCredential.objects.filter(company_id=company_id))
    gone("godkända telefoner", DeviceApproval.objects.filter(company_id=company_id))
    gone("parkopplingskoder", PairingCode.objects.filter(company_id=company_id))
    gone("ansökningar", JoinRequest.objects.filter(company_id=company_id))
    gone("bilkopplingar", VehicleAssignment.objects.filter(license__company_id=company_id))
    gone("län", LicenseCounty.objects.filter(license__company_id=company_id))
    gone("länbyten", CountyChange.objects.filter(company_id=company_id))
    gone("extra länbyten", CountyChangeGrant.objects.filter(company_id=company_id))
    gone("licenser", License.objects.filter(company_id=company_id))
    gone("bilar", Vehicle.objects.filter(company_id=company_id))
    gone("väntande ändringar", PendingChange.objects.filter(company_id=company_id))
    gone("granskningar", ChangeReview.objects.filter(company_id=company_id))
    gone("risksignaler", RiskSignal.objects.filter(company_id=company_id))
    gone("beställningar", Order.objects.filter(company_id=company_id))
    gone("kupongförbrukning", CouponRedemption.objects.filter(company_id=company_id))
    gone("inbjudningar", OwnerInvite.objects.filter(company_id=company_id))
    gone("ägarbyten", OwnershipTransfer.objects.filter(company_id=company_id))
    gone("mejl", OutboxMessage.objects.filter(company_id=company_id))
    gone("supportchatt", SupportThread.objects.filter(company_id=company_id))
    gone("uppföljning", SalesFollowUp.objects.filter(company_id=company_id))
    gone("abonnemang", Subscription.objects.filter(company_id=company_id))
    gone("spärrar", AccountBlock.objects.filter(
        kind=AccountBlock.Kind.COMPANY, value=str(company_id),
    ))

    # Telefonernas spår i tipsdelen: notiser, favoriter och "i tjänst". Feedbacken
    # (🚕/👍/👎) behålls -- den är kalibreringsdata och bär ingen person.
    from core.models import DevicePresence, OpportunityFavorite, PushDelivery

    if device_ids:
        gone("notiser", PushDelivery.objects.filter(device_id__in=device_ids))
        gone("närvaro", DevicePresence.objects.filter(device_id__in=device_ids))
    owner_keys = [f"device:{d}" for d in device_ids] + [f"user:{u}" for u in member_ids]
    if owner_keys:
        gone("favoriter", OpportunityFavorite.objects.filter(owner_key__in=owner_keys))

    gone("företagsuppgifter", CompanyProfile.objects.filter(company_id=company_id))
    # Supabases tabeller: companies kaskaderar till devices och company_members
    # (och vidare till device_transfer_codes), men raderna tas bort uttryckligen
    # så att det inte beror på en främmande nyckel som kan saknas i en miljö.
    with connection.cursor() as cur:
        cur.execute("delete from company_members where company_id = %s", [str(company_id)])
        counts["medlemmar"] = cur.rowcount
        cur.execute("delete from devices where company_id = %s", [str(company_id)])
        counts["telefoner"] = cur.rowcount
        cur.execute("delete from companies where id = %s", [str(company_id)])

    # Kontona i Supabase Auth, sist i raden av raderingar: ett fel där rullar
    # inte tillbaka bolagsraderingen -- se _delete_auth_accounts.
    counts["inloggningar"] = _delete_auth_accounts(
        sorted({str(u) for u in member_ids if u} | driver_user_ids)
    )

    audit.record(
        "company_deleted", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="platform_admin", subject_type="company", subject_id=company_id,
        # Inget namn och inget organisationsnummer: raden ska finnas kvar när
        # uppgifterna inte längre får göra det.
        detail={"counts": counts},
    )
    return counts
