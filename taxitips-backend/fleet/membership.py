"""
Kontobaserat medlemskap: en licens tilldelas ett KONTO, inte en bil.

Enheten som köps är fortfarande `License` (den bär länen i `LicenseCounty`).
Det nya är vem som håller den: i stället för att knytas till en registrerad bil
tilldelas medlemskapet ett konto -- `assignee_user_id`. Ägaren gör det på sig
själv (`assign_to_self`) eller tilldelar det till någon annan
(`assign_to_email`, som löses in när kontot med den adressen loggar in:
`claim_for_email`). Den som får platsen får ett mejl med en länk där hen
väljer lösenord (`send_invite`, samma väg som förarinbjudan), så att en person
utan konto kan logga in i appen utan att registrera ett eget företag. Länen väljs med `set_county` -- provet byter direkt, en
betald licens byter via en beställning (fleet/orders.py), samma regel som förut.

**En app-session per konto.** Att "ta" medlemskapet i appen är en rad i
`MembershipSession` (fleet/sessions.py). Det är där användarens regel bor:
samma konto på en andra telefon tar över, och portalen (som aldrig tar en
session) begränsas inte.

**Inga belopp rörs.** Ett medlemskap är en billicens; antal och pris är
oförändrade. Den här modulen rör aldrig fleet/pricing.py eller Stripe.
"""

from __future__ import annotations

import logging
import re

from django.db import transaction
from django.utils import timezone

from fleet import audit, licensing
from fleet.models import License, LicenseCounty, MembershipSession

log = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Status som fortfarande ger åtkomst (samma lista som fleet/access.py).
OPEN_STATUSES = (License.Status.ACTIVE, License.Status.TRIAL, License.Status.PENDING_CANCEL)


class MembershipError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail or {}


def normalize_email(value) -> str:
    from fleet import accounts

    email = accounts.normalize_email(value)
    if not email or len(email) > 254 or not _EMAIL.match(email):
        raise MembershipError("invalid_email", "E-postadressen ser inte rätt ut.")
    return email


# ---------------------------------------------------------------------------
# Läsa
# ---------------------------------------------------------------------------


def memberships_for_user(user_id, *, now=None) -> list[License]:
    """Aktiva medlemskap tilldelade det här kontot."""
    if not user_id:
        return []
    return list(
        License.objects.filter(assignee_user_id=user_id, status__in=OPEN_STATUSES)
        .order_by("created_at")
    )


def active_membership_for_user(user_id, *, now=None) -> License | None:
    """Kontots medlemskap, om det bara finns ett. Flera -> appen får välja."""
    memberships = memberships_for_user(user_id, now=now)
    return memberships[0] if len(memberships) == 1 else None


def memberships_for_company(company_id, *, now=None) -> list[License]:
    """Företagets alla öppna medlemskap, för portalen och admin."""
    return list(
        License.objects.filter(company_id=company_id, status__in=OPEN_STATUSES)
        .order_by("created_at")
    )


def county_codes(license: License, *, now=None) -> list[str]:
    """Länen medlemskapet ger rätt till just nu."""
    now = now or timezone.now()
    rows = LicenseCounty.objects.filter(
        license=license, active_from__lte=now
    ).exclude(active_to__lte=now)
    return sorted({row.county_code for row in rows})


# ---------------------------------------------------------------------------
# Tilldela
# ---------------------------------------------------------------------------


def _settle_previous_sessions(license: License, *, reason: str, now) -> None:
    """
    En tilldelning som ändras stänger app-sessionen. Annars fortsatte den förra
    innehavarens telefon att se data efter att kontot tagits bort från
    medlemskapet (samma resonemang som den gamla telefonens pass, invariant 17).
    """
    for row in MembershipSession.objects.filter(license=license, ended_at__isnull=True):
        MembershipSession.objects.filter(id=row.id, ended_at__isnull=True).update(
            ended_at=now, ended_reason=reason
        )


def _assign(*, license: License, user_id, email: str, actor_user_id, now, via: str) -> License:
    now = now or timezone.now()
    _settle_previous_sessions(license, reason=MembershipSession.EndReason.UNASSIGNED, now=now)
    License.objects.filter(id=license.id).update(
        assignee_user_id=user_id, assignee_email="", assigned_at=now, assigned_by=actor_user_id,
    )
    license.refresh_from_db()
    audit.record(
        "membership_assigned", company_id=license.company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="license", subject_id=license.id,
        detail={"assignee_user_id": str(user_id), "via": via},
    )
    return license


@transaction.atomic
def assign_to_self(*, license: License, user_id, email: str = "", actor_user_id=None, now=None) -> License:
    """Registrera medlemskapet på sitt eget konto."""
    if not user_id:
        raise MembershipError("login_required", "Logga in för att registrera medlemskapet.", status=401)
    return _assign(license=license, user_id=user_id, email=email, actor_user_id=actor_user_id, now=now, via="self")


@transaction.atomic
def assign_to_email(
    *, license: License, email: str, actor_user_id=None, now=None, notify: bool = True,
) -> License:
    """
    Tilldela medlemskapet till någon annans e-post. Kontot kan redan finnas --
    då binds det direkt om vi känner igen adressen -- annars väntar det tills
    personen loggar in (`claim_for_email`).

    Personen får ett mejl i båda fallen (`send_invite`): utan det visste ingen
    att platsen väntade, och den som saknade konto kom inte in utan att
    registrera ett nytt företag. `notify=False` bara när platsen flyttas utan
    att någon ny bjuds in (en fortsättning efter provet).
    """
    email = normalize_email(email)
    now = now or timezone.now()
    known = _known_user_for_email(email)
    if known is not None:
        license = _assign(license=license, user_id=known, email=email, actor_user_id=actor_user_id, now=now, via="email_known")
    else:
        _settle_previous_sessions(license, reason=MembershipSession.EndReason.UNASSIGNED, now=now)
        License.objects.filter(id=license.id).update(
            assignee_user_id=None, assignee_email=email, assigned_at=now, assigned_by=actor_user_id,
        )
        license.refresh_from_db()
        audit.record(
            "membership_assigned", company_id=license.company_id, actor_user_id=actor_user_id,
            actor_kind="admin", subject_type="license", subject_id=license.id,
            detail={"assignee_email": email, "pending": True},
        )
    if notify:
        send_invite(license, email=email, actor_user_id=actor_user_id, now=now)
    return license


# ---------------------------------------------------------------------------
# Inbjudan: mejlet till den som fått platsen
# ---------------------------------------------------------------------------


def _password_link(email: str) -> str:
    """
    Länken där personen väljer lösenord -- samma Supabase-länk som
    förarinbjudan (fleet/driver_invites.py): `invite` skapar kontot, ett konto
    som redan finns får `recovery`. Landar på taxitips.se/forare. Tom sträng
    utan Supabase Auth (lokalt) eller om anropet fallerar; mejlet hänvisar då
    till "Glömt lösenord?" i appen, som ger en likadan länk.
    """
    from fleet import auth_admin, driver_invites

    if not auth_admin.configured():
        return ""
    try:
        return auth_admin.invite_link(email, driver_invites._redirect_url()).url
    except auth_admin.AuthAdminError as exc:
        log.warning("membership: ingen lösenordslänk för %s: %s", email, exc)
        return ""


def send_invite(license: License, *, email: str, actor_user_id=None, now=None):
    """
    Köar inbjudningsmejlet till den som fått platsen (fleet/notifications.py:
    `membership_invite`). Inga priser och inga köplänkar -- mejlet går till en
    förare. Varje utskick är ett eget mejl med en ny länk ("Skicka igen").
    En spärrad adress får inget mejl.
    """
    from billing.models import Company
    from fleet import accounts, notifications
    from fleet.models import OutboxMessage

    now = now or timezone.now()
    if accounts.account_block(email=email) is not None:
        return None
    send_no = OutboxMessage.objects.filter(
        category="membership_invite", payload__licenseId=str(license.id), to_address__iexact=email,
    ).count() + 1
    company = Company.objects.filter(id=license.company_id).first()
    row = notifications.membership_invite(
        license, email=email, company_name=company.name if company else "",
        counties=county_codes(license, now=now), link=_password_link(email), send_no=send_no,
    )
    audit.record(
        "membership_invite_sent", company_id=license.company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="license", subject_id=license.id,
        detail={"email": email, "send_no": send_no},
    )
    return row


def resend_invite(license: License, *, actor_user_id=None, now=None):
    """"Skicka igen": nytt mejl och ny länk till en tilldelning som inte lösts in än."""
    if license.assignee_user_id or not license.assignee_email:
        raise MembershipError(
            "nothing_to_resend", "Platsen väntar inte på någon inbjudan.", status=409,
        )
    if license.status not in OPEN_STATUSES:
        raise MembershipError("membership_closed", "Medlemskapet är avslutat.", status=409)
    return send_invite(license, email=license.assignee_email, actor_user_id=actor_user_id, now=now)


def carry_over_assignee(*, source: License, target: License, actor_user_id=None, now=None) -> License:
    """
    Den nya platsen får samma innehavare som den gamla (provplatsen som
    fortsätter efter provslut, fleet/orders.py). Inget mejl: ingen ny bjuds in.
    """
    now = now or timezone.now()
    if source.assignee_user_id:
        return _assign(
            license=target, user_id=source.assignee_user_id, email="",
            actor_user_id=actor_user_id, now=now, via="continued",
        )
    if source.assignee_email:
        return assign_to_email(
            license=target, email=source.assignee_email, actor_user_id=actor_user_id,
            now=now, notify=False,
        )
    return target


@transaction.atomic
def unassign(*, license: License, actor_user_id=None, now=None) -> License:
    """Ta bort medlemskapet från sitt konto. Platsen är kvar, men otilldelad."""
    now = now or timezone.now()
    _settle_previous_sessions(license, reason=MembershipSession.EndReason.UNASSIGNED, now=now)
    License.objects.filter(id=license.id).update(
        assignee_user_id=None, assignee_email="", assigned_at=None, assigned_by=None,
    )
    license.refresh_from_db()
    audit.record(
        "membership_unassigned", company_id=license.company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="license", subject_id=license.id,
    )
    return license


@transaction.atomic
def create_trial_membership(
    *,
    company_id,
    trial,
    assignee_user_id,
    base_county: str = "",
    actor_user_id=None,
    now=None,
) -> License:
    """
    Provets medlemskap: en plats utan bil, tilldelad ägarens konto med en gång.

    Under provet ska ingen behöva tilldela någon annan -- kunden får sin egen
    plats. Baslänet kan vara tomt här: länen väljs efter att e-posten bekräftats,
    i appen (`set_county`), och först då har tipset ett område. Kräver ingen bil
    och ingen `CompanyMember`-rad, bara en titel (ägaren).
    """
    now = now or timezone.now()
    license = licensing.create_membership_license(
        company_id=company_id, base_county=base_county, status=License.Status.TRIAL,
        trial=trial, actor_user_id=actor_user_id, now=now,
    )
    if assignee_user_id:
        assign_to_self(
            license=license, user_id=assignee_user_id, actor_user_id=actor_user_id, now=now,
        )
    return license


def _adopt_or_create_trial(*, company_id, user_id, now) -> License:
    """
    Ägarens provplats. En ledig plats (t.ex. skapad med en bil från
    webbformuläret eller av en säljare) tas i stället för att en andra skapas --
    provet har en plats. Saknas en skapas en utan bil.
    """
    from fleet import trials

    trial = trials.active_trial(company_id)
    if trial is None:
        raise MembershipError(
            "no_trial", "Provet är inte aktivt. Kontakta TaxiTips.", status=409,
        )
    orphan = (
        License.objects.filter(
            company_id=company_id, trial=trial, status=License.Status.TRIAL,
            assignee_user_id__isnull=True, assignee_email="",
        )
        .order_by("created_at")
        .first()
    )
    if orphan is not None:
        return assign_to_self(license=orphan, user_id=user_id, now=now)
    return create_trial_membership(
        company_id=company_id, trial=trial, assignee_user_id=user_id, now=now,
    )


def ensure_trial_membership(*, user_id, base_county: str, now=None) -> License:
    """
    Appens steg efter att e-posten bekräftats: ägaren tar sin provplats och
    väljer län. Skapar platsen första gången (utan bil, tilldelad kontot) och
    sätter länen. Idempotent -- en andra gång bara byter län.
    """
    from billing.models import CompanyMember

    now = now or timezone.now()
    if not user_id:
        raise MembershipError("login_required", "Logga in för att välja län.", status=401)
    member = CompanyMember.objects.filter(user_id=user_id, status="active").first()
    if member is None:
        raise MembershipError("no_company", "Kontot hör inte till något företag.", status=403)
    mine = memberships_for_user(user_id, now=now)
    license = mine[0] if mine else _adopt_or_create_trial(
        company_id=member.company_id, user_id=user_id, now=now,
    )
    set_county(license=license, base=base_county, actor_user_id=user_id, now=now)
    return license


def claim_for_email(*, email: str, user_id, now=None) -> list[License]:
    """
    Bind väntande tilldelningar till kontot som just loggade in.

    Adressen kommer ur den VERIFIERADE token (samma bevis som förarinbjudan),
    aldrig ur ett anrop klienten kan styra. Idempotent: inget att lösa in ->
    tom lista.
    """
    email = (email or "").strip().lower()
    if not email or not user_id:
        return []
    now = now or timezone.now()
    claimed: list[License] = []
    pending = License.objects.filter(
        assignee_user_id__isnull=True, assignee_email__iexact=email, status__in=OPEN_STATUSES
    )
    for license in pending:
        License.objects.filter(id=license.id, assignee_user_id__isnull=True).update(
            assignee_user_id=user_id, assignee_email="", assigned_at=now,
        )
        license.refresh_from_db()
        claimed.append(license)
        audit.record(
            "membership_claimed", company_id=license.company_id, actor_user_id=user_id,
            actor_kind="customer", subject_type="license", subject_id=license.id,
            detail={"email": email},
        )
    return claimed


def _known_user_for_email(email: str):
    """Ett känt konto för adressen, om katalogen har ett (fleet/accounts.py)."""
    from fleet.models import KnownAccount

    row = KnownAccount.objects.filter(email__iexact=email).first()
    return row.user_id if row else None


# ---------------------------------------------------------------------------
# Län
# ---------------------------------------------------------------------------


def set_county(*, license: License, base: str, extras: list[str] | None = None, actor_user_id=None, now=None):
    """
    Välj län för medlemskapet.

    Provet byter direkt och kostnadsfritt (`licensing.set_trial_counties`). En
    betald licens byter via en beställning, så att fakturan stämmer -- samma
    regel som förut (fleet/licensing.py), och därför nekas det här.
    """
    if license.status != License.Status.TRIAL:
        raise MembershipError(
            "paid_license",
            "Medlemskapet är betalt. Län ändras via en beställning.",
        )
    if license.base_county:
        # Ett byte: samma regler som provbilens länbyte (fleet/county_changes.py)
        # -- inte fler län än platsen har (§7: självregistrerat prov = ett län)
        # och två byten per kalendermånad (§8). Förut gick den här vägen förbi
        # båda, och en provplats kunde få alla län gratis.
        from fleet import county_changes

        result = county_changes.change_trial_counties(
            license, base=base, extras=extras, actor_user_id=actor_user_id, now=now,
        )
        base, extra_codes = result["base"], result["extras"]
    else:
        # Första valet efter registreringen är inget byte, men ger inga extra län.
        chosen = licensing.assert_county_available(str(base or ""))
        if {str(c) for c in (extras or [])} - {chosen}:
            raise licensing.LicensingError(
                "trial_extra_county",
                "Under provet ingår ett län per plats. Fler län ordnar en säljare hos TaxiTips.",
            )
        base, extra_codes = licensing.set_trial_counties(license, base=chosen, extras=[], now=now)
    license.refresh_from_db()
    audit.record(
        "membership_county_set", company_id=license.company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="license", subject_id=license.id,
        detail={"base": base, "extras": extra_codes},
    )
    return base, extra_codes


def view(license: License, *, now=None) -> dict:
    """Medlemskapet som JSON -- samma form appen, portalen och admin läser."""
    now = now or timezone.now()
    return {
        "licenseId": str(license.id),
        "status": license.status,
        "baseCounty": license.base_county,
        "counties": county_codes(license, now=now),
        "assigneeUserId": str(license.assignee_user_id) if license.assignee_user_id else None,
        "assigneeEmail": license.assignee_email,
        "assignedAt": license.assigned_at.isoformat() if license.assigned_at else None,
        "assigned": bool(license.assignee_user_id or license.assignee_email),
        "trial": license.status == License.Status.TRIAL,
    }
