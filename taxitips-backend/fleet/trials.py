"""
Provperioden: 7 dagar, EN provbil vid självregistrering (tre när en säljare
lagt upp provet), högst en gratisperiod per företag under 24 månader.

**Varför en bil.** Provet ska ge en smak, inte driva en hel bilpark gratis i
två veckor. En säljare som pratat med kunden får ge fler -- det är en
människa som bedömt att bolaget är riktigt. Vad provet får SE står i
fleet/features.py (bara tåg och buss).

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

TRIAL_DAYS = 7
TRIAL_VEHICLE_LIMIT = 1
# Prov som en säljare lagt upp efter ett samtal (Trial.Source.SALES/SALES_INVITE).
# En bil, som alla andra prov (ägarens beslut 2026-10-03; var tre). Fler bilar
# är en beställning, eller en kupong som plattformsadministratören skapat.
SALES_TRIAL_VEHICLE_LIMIT = TRIAL_VEHICLE_LIMIT
# Karenstiden mellan två gratisperioder. Räknas på provets START, så att ett
# avbrutet prov inte kan användas för att korta ner den.
TRIAL_COOLDOWN_MONTHS = 24
INVITE_VALID_DAYS = 7
# Fler bilar i ett prov är ett manuellt beslut av personalen i admin (ägarens
# beslut 2026-10-04: ny registrering får 1 bil, 7 dagar, ett län och tåg & buss;
# mer delas ut för hand). Aldrig formulärets eller kundens val.
TRIAL_MANUAL_MAX_VEHICLES = 25
# Säljaren/admin kan förlänga eller sätta längre prov, men inte obegränsat.
TRIAL_MAX_PLANNED_DAYS = 365
TRIAL_EXTEND_MAX_DAYS = 366


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
def _validate_planned_days(days: int | None) -> None:
    """
    Provet är alltid TRIAL_DAYS långt när det startar -- samma för alla, vem
    som än lägger upp det (ägarens beslut 2026-10-03: ett säljarprov hade fått
    14 dagar). Behöver en kund mer tid är det en förlängning: en egen, loggad
    åtgärd med skäl (extend_trial), inte en annan startlängd.
    """
    if days is None:
        return
    if int(days) != TRIAL_DAYS:
        raise TrialError(
            "invalid_trial_days",
            f"Provet är {TRIAL_DAYS} dagar. Behöver kunden mer tid: förläng provet under Betalning.",
        )


def create_trial(
    *,
    company_id,
    country: str,
    org_number: str,
    source: str,
    invite: SalesInvite | None = None,
    requires_payment_method: bool = True,
    planned_days: int | None = None,
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
    _validate_planned_days(planned_days)

    trial = Trial.objects.create(
        company_id=company_id,
        org_key=orgnr.org_key(country, org_number),
        source=source,
        invite=invite,
        requires_payment_method=requires_payment_method,
        vehicle_limit=vehicle_limit_for(source),
        planned_days=planned_days,
        status=Trial.Status.PENDING,
    )
    audit.record(
        "trial_created", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="sales" if invite else "customer",
        subject_type="trial", subject_id=trial.id,
        detail={
            "source": source,
            "requires_payment_method": requires_payment_method,
            "planned_days": planned_days,
        },
    )
    return trial


def vehicle_limit_for(source: str) -> int:
    """En bil, vem som än lägger upp provet. Hålls som funktion om reglerna skiljer sig igen."""
    if source in (Trial.Source.SALES, Trial.Source.SALES_INVITE):
        return SALES_TRIAL_VEHICLE_LIMIT
    return TRIAL_VEHICLE_LIMIT


def start_trial(trial: Trial, *, now=None) -> Trial:
    """
    Startar klockan. Atomiskt, exakt en gång.

    Villkoret `started_at__isnull=True` ligger i UPDATE:n: två telefoner som
    aktiveras samtidigt ger ett startdatum, inte två. Alla provbilar delar
    slutdatum eftersom det bor på provet och inte på bilen (§7).
    """
    now = now or timezone.now()
    days = trial.planned_days or TRIAL_DAYS
    ends_at = now + timedelta(days=days)
    updated = Trial.objects.filter(
        id=trial.id, started_at__isnull=True, status=Trial.Status.PENDING
    ).update(started_at=now, ends_at=ends_at, status=Trial.Status.ACTIVE)
    trial.refresh_from_db()
    if updated:
        audit.record(
            "trial_started", company_id=trial.company_id, actor_kind="system",
            subject_type="trial", subject_id=trial.id,
            detail={
                "started_at": now.isoformat(),
                "ends_at": ends_at.isoformat(),
                "days": days,
            },
        )
    return trial


@transaction.atomic
def extend_trial(
    company_id,
    days: int,
    *,
    reason: str,
    actor_user_id,
    actor_kind: str = "sales",
    now=None,
) -> Trial:
    """Förlänger ett väntande eller pågående prov. Kräver skäl (audit)."""
    now = now or timezone.now()
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise TrialError("invalid_days", "Antal dagar ska vara ett heltal.")
    if not 1 <= days <= TRIAL_EXTEND_MAX_DAYS:
        raise TrialError("invalid_days", f"Förlängning: 1–{TRIAL_EXTEND_MAX_DAYS} dagar.")
    if not (reason or "").strip():
        raise TrialError("reason_required", "Skriv varför provet förlängs.")

    trial = active_trial(company_id)
    if trial is None:
        raise TrialError("no_trial", "Företaget har inget prov att förlänga.")
    if trial.status not in (Trial.Status.PENDING, Trial.Status.ACTIVE):
        raise TrialError("trial_not_open", "Provet är redan avslutat.")

    before = {
        "status": trial.status,
        "endsAt": trial.ends_at.isoformat() if trial.ends_at else None,
        "plannedDays": trial.planned_days,
    }
    if trial.status == Trial.Status.PENDING:
        base_days = trial.planned_days or TRIAL_DAYS
        new_planned = min(base_days + days, TRIAL_MAX_PLANNED_DAYS)
        Trial.objects.filter(id=trial.id).update(planned_days=new_planned)
    else:
        base = trial.ends_at if trial.ends_at and trial.ends_at > now else now
        Trial.objects.filter(id=trial.id).update(ends_at=base + timedelta(days=days))
    trial.refresh_from_db()
    audit.record(
        "trial_extended",
        company_id=company_id,
        actor_user_id=actor_user_id,
        actor_kind=actor_kind,
        subject_type="trial",
        subject_id=trial.id,
        detail={
            "before": before,
            "addedDays": days,
            "after": {
                "endsAt": trial.ends_at.isoformat() if trial.ends_at else None,
                "plannedDays": trial.planned_days,
            },
            "reason": reason.strip()[:300],
        },
    )
    return trial


def set_vehicle_limit(
    company_id,
    limit: int,
    *,
    reason: str,
    actor_user_id,
    actor_kind: str = "sales",
) -> Trial:
    """
    Sätter hur många bilar ett väntande eller pågående prov får ha. Manuellt
    av personal i admin, med skäl i loggen. Aldrig under antalet bilar provet
    redan har: bilar tas bort för sig, så att ingen förare tappar sin bil i tysthet.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise TrialError("invalid_vehicle_limit", "Antal bilar ska vara ett heltal.")
    if not 1 <= limit <= TRIAL_MANUAL_MAX_VEHICLES:
        raise TrialError("invalid_vehicle_limit", f"Bilar i provet: 1–{TRIAL_MANUAL_MAX_VEHICLES}.")
    if not (reason or "").strip():
        raise TrialError("reason_required", "Skriv varför provet får fler eller färre bilar.")

    trial = active_trial(company_id)
    if trial is None:
        raise TrialError("no_trial", "Företaget har inget prov.")
    current = trial_vehicle_count(trial)
    if limit < current:
        raise TrialError(
            "below_current",
            f"Provet har redan {current} bilar. Ta bort bilar först om gränsen ska sänkas.",
        )
    before = trial.vehicle_limit
    Trial.objects.filter(id=trial.id).update(vehicle_limit=limit)
    trial.refresh_from_db()
    audit.record(
        "trial_vehicle_limit_set",
        company_id=company_id,
        actor_user_id=actor_user_id,
        actor_kind=actor_kind,
        subject_type="trial",
        subject_id=trial.id,
        detail={"before": before, "after": limit, "vehicles": current, "reason": reason.strip()[:300]},
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
    # Provbilar som ingen beställt vidare avslutas -- både när provet tar slut
    # och när en beställning tagit över. Vid en övergång har de beställda redan
    # blivit aktiva (orders.apply_order); de som är kvar som `trial` valdes
    # bort. Att låta dem ligga kvar hade gett dem gratis åtkomst så länge
    # bolaget har en betald period, eftersom provlicenser släpps igenom.
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


def end_trial_now(
    company_id,
    *,
    reason: str,
    actor_user_id,
    actor_kind: str = "sales",
    now=None,
) -> tuple[Trial, bool]:
    """
    Personalen avslutar provet NU (adminwebben, "Avsluta provet").

    Provet blir `ended` med `ends_at = nu` och provbilarna avslutas -- samma
    väg som när provet löper ut (`end_trial`), så åtkomsten stängs i samma
    sekund: `access.company_window` svarar `trial_ended` och notisgrinden
    släpper inget mer. Ett betalt abonnemang rörs inte.

    Idempotent: ett prov som redan är slut returneras med `changed=False`.
    Ett prov där kunden sparat kort (trial commit) avslutas inte här -- där
    väntar ett Stripe-abonnemang på provslutet, och det är ett abonnemangs-
    beslut (avsluta abonnemanget), inte ett provbeslut.
    """
    now = now or timezone.now()
    reason = (reason or "").strip()
    if not reason:
        raise TrialError("reason_required", "Skriv varför provet avslutas.")

    with transaction.atomic():
        trial = (
            Trial.objects.select_for_update()
            .filter(company_id=company_id, status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE])
            .order_by("-created_at")
            .first()
        )
        if trial is None:
            latest = Trial.objects.filter(company_id=company_id).order_by("-created_at").first()
            if latest is None:
                raise TrialError("no_trial", "Företaget har inget prov.", status=404)
            return latest, False

        from fleet import commerce

        if commerce.has_active_trial_commit(company_id):
            raise TrialError(
                "trial_committed",
                "Kunden har sparat kort och provet går över i abonnemanget vid provslut. "
                "Avsluta abonnemanget i stället.",
                status=409,
            )

        before = {
            "status": trial.status,
            "endsAt": trial.ends_at.isoformat() if trial.ends_at else None,
        }
        Trial.objects.filter(id=trial.id).update(ends_at=now)
        trial.ends_at = now
        trial = end_trial(trial, reason="ended_by_staff", converted=False, now=now)
        audit.record(
            "trial_ended_by_staff",
            company_id=company_id,
            actor_user_id=actor_user_id,
            actor_kind=actor_kind,
            subject_type="trial",
            subject_id=trial.id,
            detail={"before": before, "endsAt": now.isoformat(), "reason": reason[:300]},
        )
    return trial, True


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


def continue_vehicles(company_id) -> list[dict]:
    """
    Bilarna kunden fortsätter med i kundportalen ("Fortsätt med provbilarna"):
    det pågående provets bilar, eller -- när provet löpt ut utan beställning --
    bilarna i det senaste provet. Mejlen före och efter provslut länkar hit,
    så båda fallen måste ge en lista. Tomt när bolaget redan betalar.
    """
    from fleet import licensing, sessions

    if licensing.active_licenses(company_id).exists():
        return []
    trial = active_trial(company_id) or (
        Trial.objects.filter(company_id=company_id, status=Trial.Status.ENDED)
        .order_by("-created_at").first()
    )
    if trial is None:
        return []
    wanted = (
        [License.Status.TRIAL] if trial.status in (Trial.Status.PENDING, Trial.Status.ACTIVE)
        else [License.Status.CANCELED]
    )
    out, seen = [], set()
    for license in License.objects.filter(trial=trial, status__in=wanted).order_by("created_at"):
        vehicle = sessions.current_vehicle(license) or (
            license.assignments.order_by("-started_at").first().vehicle
            if license.assignments.exists() else None
        )
        if vehicle is None or vehicle.plate in seen:
            continue
        seen.add(vehicle.plate)
        out.append({"plate": vehicle.plate, "baseCounty": license.base_county})
    return out
