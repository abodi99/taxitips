"""
Provperioden: 14 dagar, högst tre provbilar, högst en gratisperiod per företag
under 24 månader.

**Vad spärren räknar på.** `Trial.org_key` = land + normaliserat
organisationsnummer. Inte company_id: ett nytt bolagskonto med samma
organisationsnummer ska inte ge ett nytt gratisprov. Inte e-post, inte telefon,
inte Stripe-kund, inte administratör -- alla fyra går att byta på en eftermiddag
(§7). Raden ligger kvar efter provets slut; den ÄR provhistoriken.

**Varför provet startar vid första telefonaktiveringen och inte vid
registreringen.** Ett prov som börjar när formuläret skickas brinner medan
kunden väntar på att få telefonerna utdelade, och supportärendet blir
"förlänga provet", vilket är just den sortens ärende som ska bort. Starten
skrivs atomiskt EN gång (ett villkorat UPDATE): två telefoner som aktiveras i
samma sekund ger inte två startdatum.

**Provbilar är inte beställda licenser.** Tre provbilar blir aldrig tre
debiterade licenser utan en uttrycklig beställning av vilka bilar som
fortsätter (§7). Det följer av att `Trial.vehicle_limit` och `Order.
quantity_after` är olika fält som skrivs av olika flöden.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from fleet import audit, orgnr
from fleet.models import License, SalesInvite, Trial

TRIAL_DAYS = 14
TRIAL_VEHICLE_LIMIT = 3
# Karenstiden mellan två gratisperioder. Räknas på provets START, så att ett
# avbrutet prov inte kan användas för att korta ner den.
TRIAL_COOLDOWN_MONTHS = 24
INVITE_VALID_DAYS = 7


class TrialError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reason: str
    message: str = ""
    previous_started_at: object | None = None

    def as_dict(self) -> dict:
        return {
            "eligible": self.ok,
            "reason": self.reason,
            "message": self.message,
            "previousTrialStartedAt": (
                self.previous_started_at.isoformat() if self.previous_started_at else None
            ),
        }


def eligibility(*, country: str, org_number: str, now=None) -> Eligibility:
    """Får det här organisationsnumret ett gratisprov just nu?"""
    now = now or timezone.now()
    key = orgnr.org_key(country, org_number)
    if not orgnr.normalize(org_number, country):
        return Eligibility(False, "invalid_org_number", "Organisationsnumret går inte att tolka.")

    cutoff = now - timedelta(days=TRIAL_COOLDOWN_MONTHS * 30)
    previous = (
        Trial.objects.filter(org_key=key)
        .exclude(status=Trial.Status.CANCELED)
        .order_by("-created_at")
        .first()
    )
    if previous is None:
        return Eligibility(True, "no_previous_trial")

    # Ett pågående prov är inte ett skäl att ge ett till.
    if previous.status in (Trial.Status.PENDING, Trial.Status.ACTIVE):
        return Eligibility(
            False, "trial_in_progress", "Företaget har redan en provperiod.",
            previous.started_at,
        )
    reference = previous.started_at or previous.created_at
    if reference and reference > cutoff:
        return Eligibility(
            False, "trial_used_recently",
            f"Företaget har haft en provperiod de senaste {TRIAL_COOLDOWN_MONTHS} månaderna.",
            previous.started_at,
        )
    return Eligibility(True, "cooldown_passed", previous_started_at=previous.started_at)


@transaction.atomic
def create_trial(
    *,
    company_id,
    country: str,
    org_number: str,
    source: str,
    invite: SalesInvite | None = None,
    requires_payment_method: bool = True,
    actor_user_id=None,
    now=None,
) -> Trial:
    """
    Skapar provet i läget `pending`. Klockan startar inte här -- den startar
    vid första telefonaktiveringen, se `start_trial`.
    """
    now = now or timezone.now()
    check = eligibility(country=country, org_number=org_number, now=now)
    if not check.ok:
        raise TrialError(check.reason, check.message)

    trial = Trial.objects.create(
        company_id=company_id,
        org_key=orgnr.org_key(country, org_number),
        source=source,
        invite=invite,
        requires_payment_method=requires_payment_method,
        vehicle_limit=TRIAL_VEHICLE_LIMIT,
        status=Trial.Status.PENDING,
    )
    audit.record(
        "trial_created", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="sales" if invite else "customer",
        subject_type="trial", subject_id=trial.id,
        detail={"source": source, "requires_payment_method": requires_payment_method},
    )
    return trial


def start_trial(trial: Trial, *, now=None) -> Trial:
    """
    Startar klockan. Atomiskt, exakt en gång.

    Villkoret `started_at__isnull=True` ligger i UPDATE:n: två telefoner som
    aktiveras samtidigt ger ett startdatum, inte två. Alla provbilar delar
    slutdatum eftersom det bor på provet och inte på bilen (§7).
    """
    now = now or timezone.now()
    ends_at = now + timedelta(days=TRIAL_DAYS)
    updated = Trial.objects.filter(
        id=trial.id, started_at__isnull=True, status=Trial.Status.PENDING
    ).update(started_at=now, ends_at=ends_at, status=Trial.Status.ACTIVE)
    trial.refresh_from_db()
    if updated:
        audit.record(
            "trial_started", company_id=trial.company_id, actor_kind="system",
            subject_type="trial", subject_id=trial.id,
            detail={"started_at": now.isoformat(), "ends_at": ends_at.isoformat()},
        )
    return trial


def active_trial(company_id) -> Trial | None:
    return (
        Trial.objects.filter(
            company_id=company_id, status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE]
        )
        .order_by("-created_at")
        .first()
    )


def trial_vehicle_count(trial: Trial) -> int:
    return License.objects.filter(trial=trial).exclude(status=License.Status.CANCELED).count()


def assert_can_add_trial_vehicle(trial: Trial) -> None:
    if trial_vehicle_count(trial) >= trial.vehicle_limit:
        raise TrialError(
            "trial_vehicle_limit",
            f"Provperioden omfattar högst {trial.vehicle_limit} bilar.",
        )


@transaction.atomic
def end_trial(trial: Trial, *, reason: str, converted: bool = False, now=None) -> Trial:
    """
    Avslutar provet.

    `converted=True` betyder att en betald beställning tagit över. Utan order
    slutar provet UTAN debitering -- en kortfri provperiod övergår aldrig till
    betalning av sig själv (§8), och ett uppsagt prov med tidigare
    betalningsgodkännande debiterar inte heller när det tar slut.
    """
    now = now or timezone.now()
    status = Trial.Status.CONVERTED if converted else Trial.Status.ENDED
    Trial.objects.filter(id=trial.id).update(
        status=status, ended_reason=reason[:200], ends_at=trial.ends_at or now
    )
    if not converted:
        # Provbilar som ingen beställt vidare avslutas. Antalet provbilar blir
        # aldrig ett debiterat antal av sig självt.
        License.objects.filter(trial=trial, status=License.Status.TRIAL).update(
            status=License.Status.CANCELED, canceled_at=now, ends_at=now
        )
    trial.refresh_from_db()
    audit.record(
        "trial_ended", company_id=trial.company_id, actor_kind="system",
        subject_type="trial", subject_id=trial.id,
        detail={"reason": reason[:200], "converted": converted},
    )
    return trial


# ---------------------------------------------------------------------------
# Säljarinbjudan
# ---------------------------------------------------------------------------


def create_invite(
    *,
    created_by,
    country: str,
    org_number: str,
    company_name: str,
    contact_name: str,
    contact_email: str,
    contact_phone: str,
    verification_note: str,
    now=None,
) -> tuple[SalesInvite, str]:
    """
    Personlig engångsinbjudan till kortfritt prov, giltig sju dagar.

    `verification_note` är obligatorisk: säljaren måste dokumentera den
    verifierade företagskontakten innan inbjudan skickas (§7). Utan text,
    ingen inbjudan -- det är inte en formalitet, det är det enda spår som
    finns när någon i efterhand frågar varför ett företag fick kortfritt prov.
    """
    import hashlib
    import secrets

    now = now or timezone.now()
    if not (verification_note or "").strip():
        raise TrialError(
            "verification_note_required",
            "Dokumentera den verifierade företagskontakten innan inbjudan skickas.",
        )
    normalized = orgnr.normalize(org_number, country)
    if not normalized:
        raise TrialError("invalid_org_number", "Organisationsnumret går inte att tolka.")

    code = secrets.token_urlsafe(18)
    invite = SalesInvite.objects.create(
        # Inbjudningskoden är en URL-säker slumpsträng, inte en inknappad
        # kod: den klistras in ur ett mejl. Därför sha256 rakt av, utan
        # parkopplingskodens normalisering av tvetydiga tecken.
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        created_by=created_by,
        country=(country or "SE").upper(),
        org_number=normalized,
        company_name=company_name,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        verification_note=verification_note.strip(),
        expires_at=now + timedelta(days=INVITE_VALID_DAYS),
    )
    audit.record(
        "sales_invite_created", actor_user_id=created_by, actor_kind="sales",
        subject_type="invite", subject_id=invite.id,
        detail={"org_number": normalized, "company_name": company_name},
    )
    return invite, code


def find_invite(code: str, *, now=None) -> SalesInvite:
    import hashlib

    from fleet import ratelimit

    now = now or timezone.now()
    digest = hashlib.sha256((code or "").encode()).hexdigest()
    ratelimit.enforce(ratelimit.INVITE_REDEEM, digest[:32])

    invite = SalesInvite.objects.filter(code_hash=digest).first()
    if invite is None or invite.status != SalesInvite.Status.PENDING:
        raise TrialError("invalid_invite", "Inbjudan är ogiltig eller redan använd.")
    if invite.expires_at <= now:
        SalesInvite.objects.filter(id=invite.id).update(status=SalesInvite.Status.REVOKED)
        raise TrialError("invite_expired", "Inbjudan har gått ut.")
    return invite


def consume_invite(invite: SalesInvite, *, company_id, now=None) -> SalesInvite:
    now = now or timezone.now()
    consumed = SalesInvite.objects.filter(
        id=invite.id, status=SalesInvite.Status.PENDING
    ).update(status=SalesInvite.Status.CONSUMED, consumed_at=now, consumed_by_company=company_id)
    if consumed != 1:
        raise TrialError("invalid_invite", "Inbjudan är ogiltig eller redan använd.")
    invite.refresh_from_db()
    return invite
