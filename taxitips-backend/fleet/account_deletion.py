"""
Radera mitt konto -- självbetjäning i appen (Apple 5.1.1(v), Google Play User Data).

Apple kräver att ett konto som kan skapas i appen också kan raderas i appen, och
"Avsluta företagskontot" (fleet/ownership.py:close_account) gör inte det: den
stoppar förnyelsen men lämnar inloggningen kvar. Här tas själva kontot bort.

Två sorters bevis, samma som resten av fleet-API:t:

* **Inloggat konto** (`Authorization: Bearer`, ägare, kontor, ekonomi). Kontot i
  Supabase Auth, medlemskapen, katalograden och telefonerna kontot använt.
* **Förarens telefon** (`X-Device-Token`, föraren har ingen Supabase-session i
  appen). Telefonens koppling till bilen och förarkontot som löste in
  inbjudan. Ett konto som också är medlem i ett företag raderas INTE den vägen:
  en telefon bevisar att man håller i telefonen, inte att man äger
  ägarkontot -- då kopplas bara telefonen loss och appen säger hur ägaren
  raderar sitt konto (logga in och radera där).

**Vägrar** när kontot är ENDA ägaren i ett företag vars medlemskap förnyas.
Annars försvann den enda som kan säga upp abonnemanget medan det fortsatte
debitera företaget -- samma skäl som `ownership.remove_member` vägrar. Svaret
säger vad hen gör i stället: avsluta företagskontot först (då förnyas inget),
eller låt en kollega ta över ägarrollen. Ett kortfritt prov stoppar inte
raderingen: provet avslutas, det debiterar aldrig av sig självt.

Personalkonton (adminwebben) raderas inte härifrån: en plattformsadministratör
som av misstag raderar sig själv i appen låser ute plattformen.

**Kvar efter raderingen**, med avsikt och samma som adminwebbens radering
(fleet/admin_accounts.py:delete_account): revisionsloggen (vem gjorde vad),
supporttrådar och felrader utan inloggning, feedback på tips (knuten till
telefonens installations-id, inte till en person), företagets egna uppgifter
om bilar och inbjudningar, och bokföringsunderlag. Telefonens rad i `devices`
finns kvar för de raderna, men utan push-token, konto, inställningar och namn.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from billing.models import Company, CompanyMember, Device
from fleet import audit, auth_admin, roles, sessions
from fleet.models import (
    ClientActivity,
    DeviceApproval,
    DeviceCredential,
    DriverInvite,
    KnownAccount,
    StaffRole,
    Subscription,
    SubscriptionStatus,
    Trial,
    VehicleSession,
)

log = logging.getLogger(__name__)

# Bekräftelsen i anropet. Appen skickar den först när användaren tryckt
# "Radera" i bekräftelsedialogen; ett anrop utan den gör ingenting.
CONFIRM_WORD = "radera"

# Raderade telefoner får det här namnet: adminwebben och portalen ska kunna
# visa raden i historiken utan förarens namn.
DELETED_LABEL = "Raderad"


class AccountDeletionError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail


def confirmed(body: dict) -> bool:
    return str((body or {}).get("confirm") or "").strip().lower() == CONFIRM_WORD


def _require_confirm(body: dict) -> None:
    if not confirmed(body):
        raise AccountDeletionError(
            "confirm_required",
            "Bekräfta att du vill radera kontot.",
        )


def _renews(subscription: Subscription | None) -> bool:
    """
    Förnyas medlemskapet, dvs. kommer företaget att debiteras igen?

    En uppsagd period som löper ut (`cancel_at_period_end`, `renewal_stopped_at`)
    förnyas inte. Ett kortfritt prov finns inte här alls (fleet_trial); ett prov
    där kunden sparat kort i portalen är ett Stripe-abonnemang i `trialing` som
    debiterar vid provets slut, och räknas därför som förnyande.
    """
    if subscription is None:
        return False
    if subscription.cancel_at_period_end or subscription.renewal_stopped_at:
        return False
    if subscription.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE):
        return True
    return subscription.status == SubscriptionStatus.TRIALING and bool(
        subscription.stripe_subscription_id
    )


def sole_owned_companies(user_id) -> list[dict]:
    """Företag där kontot är enda aktiva ägaren, och om medlemskapet förnyas."""
    out = []
    for member in CompanyMember.objects.filter(
        user_id=user_id, role=roles.OWNER, status="active",
    ):
        others = CompanyMember.objects.filter(
            company_id=member.company_id, role=roles.OWNER, status="active",
        ).exclude(user_id=user_id).exists()
        if others:
            continue
        company = Company.objects.filter(id=member.company_id).first()
        out.append({
            "companyId": str(member.company_id),
            "companyName": company.name if company else "",
            "renews": _renews(Subscription.objects.filter(company_id=member.company_id).first()),
        })
    return out


def _device_ids_for_users(user_ids) -> set[str]:
    """Telefoner kontona använt: `devices.user_id` och inlösta förarinbjudningar."""
    user_ids = [str(u) for u in user_ids if u]
    if not user_ids:
        return set()
    ids = {str(d) for d in Device.objects.filter(user_id__in=user_ids).values_list("id", flat=True)}
    ids.update(
        str(d) for d in DriverInvite.objects.filter(
            Q(consumed_by_user__in=user_ids) | Q(auth_user_id__in=user_ids),
            consumed_by_device__isnull=False,
        ).values_list("consumed_by_device", flat=True) if d
    )
    return ids


def _release_device(device_id, *, now) -> str | None:
    """
    Kopplar loss telefonen och tar bort det som pekar på föraren.

    Godkännandena ersätts (inte spärras: företaget ska inte se en spärr det
    inte gjort), hemligheterna återkallas, passet stängs, push-token, konto,
    namn och notisinställningar nollas. Sparade tips, notishistorik, "i tjänst"
    och senaste-sedd-raden tas bort. Returnerar företaget telefonen hörde till.
    """
    from core.models import DevicePresence, OpportunityFavorite, PushDelivery

    device = Device.objects.filter(id=device_id).first()
    if device is None:
        return None
    DeviceApproval.objects.filter(
        device_id=device.id, status=DeviceApproval.Status.ACTIVE,
    ).update(
        status=DeviceApproval.Status.REPLACED, revoked_at=now, revoke_reason="account_deleted",
    )
    DeviceCredential.objects.filter(device_id=device.id, revoked_at__isnull=True).update(
        revoked_at=now, revoke_reason="account_deleted",
    )
    sessions.end_sessions_for_device(
        device.id, reason=VehicleSession.EndReason.DRIVER_END, now=now,
    )
    Device.objects.filter(id=device.id).update(
        push_token=None, user_id=None, notify_prefs={}, label=DELETED_LABEL,
    )
    OpportunityFavorite.objects.filter(
        owner_key__in=[f"device:{device.id}", device.token],
    ).delete()
    PushDelivery.objects.filter(device_id=device.id).delete()
    DevicePresence.objects.filter(device_id=device.id).delete()
    ClientActivity.objects.filter(
        subject_kind=ClientActivity.Kind.DEVICE, subject_id=device.id,
    ).delete()
    return str(device.company_id) if device.company_id else None


def _forget_user(user_id) -> None:
    """Katalograden, senaste-sedd och sparade tips för det inloggade kontot."""
    from core.models import OpportunityFavorite

    KnownAccount.objects.filter(user_id=user_id).delete()
    ClientActivity.objects.filter(
        subject_kind=ClientActivity.Kind.USER, subject_id=user_id,
    ).delete()
    OpportunityFavorite.objects.filter(owner_key=f"user:{user_id}").delete()


def _require_auth_admin() -> None:
    if not auth_admin.configured():
        raise AccountDeletionError(
            "auth_not_configured",
            "Det går inte att radera kontot just nu. Försök igen senare, eller "
            "skriv till hej@taxitips.se så hjälper vi dig.",
            status=503,
        )


def _delete_auth_user(user_id) -> None:
    """
    Kontot i Supabase Auth. Körs SIST i transaktionen: misslyckas det rullas
    allt tillbaka och användaren kan försöka igen med samma inloggning.
    """
    try:
        auth_admin.delete_user(str(user_id))
    except auth_admin.AuthAdminError as exc:
        log.warning("account_deletion: Auth-raderingen misslyckades för %s: %s", user_id, exc)
        raise AccountDeletionError(
            "auth_delete_failed",
            "Det gick inte att radera kontot just nu. Försök igen om en stund.",
            status=502,
        ) from exc


def delete_signed_in_account(*, user_id, email: str = "", device: Device | None = None,
                             body: dict | None = None, now=None) -> dict:
    """
    Raderar det inloggade kontot. `device` är telefonen anropet kom från, om
    appen också bär en förartoken (en ägare som kör bilen själv).
    """
    now = now or timezone.now()
    _require_confirm(body or {})
    if not user_id:
        raise AccountDeletionError("login_required", "Logga in för att fortsätta.", status=401)

    if StaffRole.objects.filter(user_id=user_id, is_active=True).exists():
        raise AccountDeletionError(
            "staff_account",
            "Det här är ett personalkonto. Det raderas av TaxiTips plattformsadministratör, "
            "inte i appen.",
            status=409,
        )

    sole = sole_owned_companies(user_id)
    _require_auth_admin()

    device_ids = _device_ids_for_users([user_id])
    if device is not None:
        device_ids.add(str(device.id))

    with transaction.atomic():
        trials_ended = 0
        for company in sole:
            # Ingen kvar som kan sköta provet: det avslutas, utan kostnad.
            trial = Trial.objects.filter(
                company_id=company["companyId"],
                status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE],
            ).first()
            if trial is not None:
                from fleet import trials

                trials.end_trial(trial, reason="owner_account_deleted", now=now)
                trials_ended += 1
            # Förnyas medlemskapet pausas det och företaget arkiveras, så att
            # ägaren slipper "avsluta först" och företaget inte lämnas med ett
            # debiterande abonnemang utan ägare (ägarens beslut 2026-10-07).
            if company["renews"]:
                from fleet import archive, ownership

                ownership.close_account(
                    company_id=company["companyId"], actor_user_id=user_id, now=now,
                )
                archive.archive(
                    company_id=company["companyId"], actor_user_id=user_id,
                    force=True, now=now,
                )

        memberships = list(CompanyMember.objects.filter(user_id=user_id))
        companies = sorted({str(m.company_id) for m in memberships})
        CompanyMember.objects.filter(user_id=user_id).delete()

        released = []
        for device_id in sorted(device_ids):
            company_id = _release_device(device_id, now=now)
            released.append(device_id)
            if company_id and company_id not in companies:
                companies.append(company_id)
        _forget_user(user_id)

        for company_id in companies or [None]:
            audit.record(
                "account_deleted_by_user",
                company_id=company_id,
                actor_user_id=user_id,
                actor_kind="owner" if memberships else "user",
                subject_type="account",
                subject_id=user_id,
                detail={
                    "via": "app",
                    "membershipsRemoved": len(memberships),
                    "phonesReleased": len(released),
                    "trialsEnded": trials_ended,
                },
            )
        _delete_auth_user(user_id)

    return {
        "deleted": True,
        "accountsDeleted": 1,
        "phonesReleased": len(released),
        "trialsEnded": trials_ended,
        "message": "Ditt konto är raderat.",
    }


def delete_driver_by_device(*, device: Device, body: dict | None = None, now=None) -> dict:
    """
    Föraren raderar sitt konto från telefonen (ingen Supabase-session i appen).

    Telefonens koppling tas bort, och förarkontot som löste in inbjudan
    raderas -- om det bara är ett förarkonto. Ett konto som är medlem i ett
    företag (eller personal) lämnas orört; telefonen kopplas loss ändå.
    """
    now = now or timezone.now()
    _require_confirm(body or {})

    user_ids = set()
    if device.user_id:
        user_ids.add(str(device.user_id))
    for consumed, auth_user in DriverInvite.objects.filter(
        consumed_by_device=device.id,
    ).values_list("consumed_by_user", "auth_user_id"):
        for uid in (consumed, auth_user):
            if uid:
                user_ids.add(str(uid))

    kept = sorted(
        uid for uid in user_ids
        if CompanyMember.objects.filter(user_id=uid, status="active").exists()
        or StaffRole.objects.filter(user_id=uid, is_active=True).exists()
    )
    to_delete = sorted(user_ids - set(kept))
    if to_delete:
        _require_auth_admin()

    device_ids = _device_ids_for_users(to_delete) | {str(device.id)}

    with transaction.atomic():
        companies = []
        for device_id in sorted(device_ids):
            company_id = _release_device(device_id, now=now)
            if company_id and company_id not in companies:
                companies.append(company_id)
        for uid in to_delete:
            # Ett förarkonto har inga medlemskap; en inaktiv rad (borttagen,
            # avstängd) följer med kontot.
            CompanyMember.objects.filter(user_id=uid).delete()
            _forget_user(uid)

        for company_id in companies or [None]:
            audit.record(
                "account_deleted_by_user",
                company_id=company_id,
                actor_kind="driver",
                subject_type="device",
                subject_id=device.id,
                detail={
                    "via": "app",
                    "accountsDeleted": len(to_delete),
                    "accountsKept": len(kept),
                    "phonesReleased": len(device_ids),
                },
            )
        for uid in to_delete:
            _delete_auth_user(uid)

    message = "Ditt förarkonto är raderat och telefonen är bortkopplad."
    if kept:
        message = (
            "Telefonen är bortkopplad. Ditt inloggningskonto hör till ett företag och "
            "finns kvar: logga in med e-post och lösenord och radera det under "
            "Inställningar."
        )
    return {
        "deleted": True,
        "accountsDeleted": len(to_delete),
        "accountsKept": len(kept),
        "phonesReleased": len(device_ids),
        "message": message,
    }
