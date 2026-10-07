"""
Manuellt beviljande: fullt medlemskap utan kostnad, till ett KONTO.

En människa i adminwebben har beslutat att den här personen ska ha allt,
gratis. Det är varken en rabatt (beloppet som ändå faktureras), en kupong
(gratisdagar någon måste lösa in) eller en beställning -- därför en egen rad
med aktör, skäl och tidsgräns (`MembershipGrant`), så att beslutet går att
läsa i efterhand: vem, när, till vem, varför, tills när.

**Ingen beställning, ingen faktura, ingen Stripe.** Den här modulen rör
aldrig `Order`, `Subscription` eller `fleet/pricing.py`. Beviljandet gör två
saker:

1. Öppnar företagets period. `fleet/access.py:company_window` svarar
   `free_grant` medan ett beviljande är aktivt, och `fleet/features.py` ger
   FULL när skälet inte är ett prov -- alla kategorier öppnas.
2. Ger personen en plats. Medlemskapet är en `License` utan bil
   (`licensing.create_membership_license`), tilldelad kontot -- samma väg som
   provet och portalen (fleet/membership.py). Alla län läggs på platsen, så
   både listan och notiserna når hela landet.

**Räckvidd.** Perioden är företagets (`company_window` är en fråga per bolag),
men platsen är personens: ett beviljande till person A ger inte person B tips,
eftersom B inte har någon plats tilldelad sig.

**E-post före konto.** Ett beviljande kan riktas till en adress som ännu inte
loggat in. Då väntar både platsen (`License.assignee_email`) och raden
(`MembershipGrant.email`) på inloggningen och binds när kontot med adressen
verifieras (`claim_for_email`, kallat från `access._maybe_claim_memberships`).

**Återkallelse.** `revoked_at` stänger fönstret direkt och den vanliga
periodprövningen gäller igen (abonnemang, prov, frist). En plats som SKAPADES
av beviljandet avslutas (`license_created`); en redan köpt plats röras aldrig
-- den är betald.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.utils import ProgrammingError
from django.utils import timezone

from core import areas
from fleet import audit, licensing, membership
from fleet.models import License, LicenseCounty, MembershipGrant, MembershipSession

log = logging.getLogger(__name__)

# Skälet i företagets periodfönster (fleet/access.py:company_window).
WINDOW_REASON = "free_grant"


class GrantError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# Läsa
# ---------------------------------------------------------------------------


def _is_active(grant: MembershipGrant, now) -> bool:
    if grant.revoked_at is not None:
        return False
    if grant.starts_at and grant.starts_at > now:
        return False
    if grant.ends_at and grant.ends_at <= now:
        return False
    return True


def _safe_grant_list(qs) -> list:
    """
    Beviljandetabellen lades till efter koden som läser den. Utan savepoint
    blir en saknad tabell ett avbrutet postgres-transaktionsfel, och admin
    Hem (som frågar per bolag) svarar då inte alls.
    """
    try:
        with transaction.atomic():
            return list(qs)
    except ProgrammingError:
        log.warning("fleet.grants: tabellen saknas, behandlar som inget beviljande")
        return []


def active_grants_for(company_ids, now=None) -> dict:
    """Aktiva beviljanden, ett per bolag, lästa i en fråga."""
    now = now or timezone.now()
    ids = [cid for cid in company_ids if cid]
    if not ids:
        return {}
    rows = _safe_grant_list(
        MembershipGrant.objects.filter(
            company_id__in=ids, revoked_at__isnull=True
        ).order_by("-starts_at", "-created_at")
    )
    out = {}
    for grant in rows:
        if grant.company_id in out:
            continue
        if _is_active(grant, now):
            out[grant.company_id] = grant
    return out


def active_grant(company_id, now=None) -> MembershipGrant | None:
    """
    Beviljandet som öppnar företagets period just nu, om något.

    Senast startade raden vinner (det kan bara finnas en öppen per bolag och
    person, men flera personer i samma bolag kan ha var sin). `ends_at` NULL
    = tills vidare.
    """
    if not company_id:
        return None
    return active_grants_for([company_id], now).get(company_id)


def open_grants(company_id) -> list[MembershipGrant]:
    """Alla öppna rader för bolaget, för adminvyn."""
    return list(
        MembershipGrant.objects.filter(company_id=company_id, revoked_at__isnull=True)
        .order_by("-created_at")
    )


def grants_for_company(company_id, limit: int = 20) -> list[MembershipGrant]:
    """Alla rader (även återkallade), nyast först -- historiken i adminvyn."""
    return list(
        MembershipGrant.objects.filter(company_id=company_id).order_by("-created_at")[:limit]
    )


def grant_license_ids(company_id) -> set[str]:
    """
    Id:n på de platser ett ÖPPET beviljande håller.

    Används av `licensing.billable_license_count` och `extra_county_count`:
    en plats som hålls av ett beviljande är gratis och får aldrig hamna på
    nästa faktura (`stripe_sync.sync_company_amount` räknar nästa belopp ur
    exakt de två funktionerna).
    """
    if not company_id:
        return set()
    return grant_license_ids_by_company([company_id]).get(company_id, set())


def grant_license_ids_by_company(company_ids) -> dict:
    """Samma som `grant_license_ids`, för många bolag."""
    ids = [cid for cid in company_ids if cid]
    if not ids:
        return {}
    rows = _safe_grant_list(
        MembershipGrant.objects.filter(
            company_id__in=ids, revoked_at__isnull=True
        ).values_list("company_id", "license_id")
    )
    out = {}
    for company_id, license_id in rows:
        if not license_id:
            continue
        out.setdefault(company_id, set()).add(str(license_id))
    return out


# ---------------------------------------------------------------------------
# Bevilja
# ---------------------------------------------------------------------------


def _resolve_target(*, user_id, email: str) -> tuple[str | None, str]:
    """
    Personen: ett konto-id eller en e-postadress som väntar på inloggning.

    Ett känt konto i katalogen (fleet/accounts.py) binder direkt, exakt som
    `membership.assign_to_email` gör -- annars väntar tilldelningen.
    """
    if user_id:
        return str(user_id), ""
    email = membership.normalize_email(email)
    from fleet.models import KnownAccount

    known = KnownAccount.objects.filter(email__iexact=email).first()
    if known is not None:
        return str(known.user_id), email
    return None, email


def _set_grant_counties(
    license: License, *, all_counties: bool, counties: list[str], now
) -> list[str]:
    """
    Länen på platsen. Stänger alla öppna rader och lägger upp de nya, så att
    rättigheten alltid är exakt det beviljandet sa -- aldrig en union med
    något gammalt.

    Alla rader blir EXTRA (baslänet är vad kort och listor visar, inte en
    rättighet vid sidan av de andra). De räknas ändå aldrig mot fakturan:
    `extra_county_count` hoppar över platser med ett öppet beviljande.
    """
    if all_counties:
        from core.coverage import offerable_county_codes

        codes = sorted(offerable_county_codes())
    else:
        codes = sorted({licensing.assert_county_available(str(c)) for c in counties})
        if not codes:
            raise GrantError("counties_required", "Välj minst ett län, eller bevilja alla.")
    with transaction.atomic():
        LicenseCounty.objects.filter(license=license).exclude(active_to__lte=now).update(
            active_to=now
        )
        for code in codes:
            LicenseCounty.objects.create(
                license=license, county_code=code,
                kind=LicenseCounty.Kind.EXTRA, active_from=now,
            )
        # `base_county` är vad kort och listor visar; rättigheten är raderna
        # ovan. Beviljandet har inget "baslän" -- alla län är lika mycket värda.
        License.objects.filter(id=license.id).update(
            base_county=codes[0], scheduled_base_county=""
        )
    license.refresh_from_db()
    return codes


def _seat_for(company_id, *, actor_user_id, now) -> tuple[License, bool]:
    """
    Platsen personen ska få: ALLTID en ny, utan bil.

    Ingen återanvändning av en ledig plats (provets `_adopt_or_create_trial`
    gör det, men här vore det farligt): en köpt plats som bara väntar på att
    tilldelas är betalad och bär sina köpta län. Ett beviljande som tog den
    skulle skriva över länen med "alla län", och när beviljandet gick ut hade
    platsen andra län än kunden betalat för -- utan någon order att härleda
    dem ur. Beviljandets plats är därför alltid sin egen, och återkallelsen
    avslutar exakt den (`license_created`).
    """
    return licensing.create_membership_license(
        company_id=company_id, base_county="", status=License.Status.ACTIVE,
        actor_user_id=actor_user_id, now=now,
    ), True


def _existing_open(company_id, *, user_id, email: str) -> MembershipGrant | None:
    """Ett öppet beviljande för samma person (konto eller adress)."""
    rows = MembershipGrant.objects.filter(company_id=company_id, revoked_at__isnull=True)
    if user_id:
        found = rows.filter(user_id=user_id).first()
        if found is not None:
            return found
    if email:
        return rows.filter(email__iexact=email).first()
    return None


@transaction.atomic
def grant_membership(
    *,
    company_id,
    user_id=None,
    email: str = "",
    reason: str,
    ends_at=None,
    all_counties: bool = True,
    counties: list[str] | None = None,
    actor_user_id=None,
    now=None,
) -> MembershipGrant:
    """
    Bevilja ett fullt medlemskap utan kostnad.

    Kräver ett skäl -- ett beslut utan skäl går inte att försvara i efterhand.
    `ends_at` NULL betyder tills vidare. Personen anges med `user_id` (känt
    konto) eller `email` (binder vid första inloggningen).
    """
    now = now or timezone.now()
    reason = str(reason or "").strip()
    if not reason:
        raise GrantError("reason_required", "Skriv varför medlemskapet beviljas utan kostnad.")
    if ends_at and ends_at <= now:
        raise GrantError("invalid_ends_at", "Slutdatumet måste vara i framtiden.")
    if not user_id and not str(email or "").strip():
        raise GrantError("person_required", "Ange kontots e-post eller användar-id.")

    resolved_user, resolved_email = _resolve_target(user_id=user_id, email=email)
    already = _existing_open(company_id, user_id=resolved_user, email=resolved_email)
    if already is not None:
        raise GrantError(
            "grant_exists", "Personen har redan ett beviljat medlemskap i det här bolaget.",
            status=409, detail={"grantId": str(already.id)},
        )

    license, license_created = _seat_for(company_id, actor_user_id=actor_user_id, now=now)
    # Tilldelningen går via medlemskapets egen väg, så att app-sessionen för en
    # eventuell förra innehavare stängs och revisionsloggen är densamma.
    if resolved_user:
        membership.assign_to_self(
            license=license, user_id=resolved_user,
            actor_user_id=actor_user_id, now=now,
        )
    else:
        membership.assign_to_email(
            license=license, email=resolved_email, actor_user_id=actor_user_id, now=now,
        )

    codes = _set_grant_counties(
        license, all_counties=all_counties, counties=counties or [], now=now,
    )
    grant = MembershipGrant.objects.create(
        company_id=company_id, license=license, license_created=license_created,
        user_id=resolved_user, email="" if resolved_user else resolved_email,
        counties=codes, all_counties=bool(all_counties),
        reason=reason, starts_at=now, ends_at=ends_at, granted_by=actor_user_id,
    )
    audit.record(
        "membership_granted", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="platform_admin", subject_type="membership_grant", subject_id=grant.id,
        detail={
            "license_id": str(license.id), "license_created": license_created,
            "assignee_user_id": resolved_user, "assignee_email": grant.email,
            "all_counties": grant.all_counties, "counties": codes,
            "reason": reason, "ends_at": ends_at.isoformat() if ends_at else None,
        },
    )
    return grant


# ---------------------------------------------------------------------------
# Lös in och återkalla
# ---------------------------------------------------------------------------


@transaction.atomic
def claim_for_email(*, email: str, user_id, now=None) -> list[MembershipGrant]:
    """
    Bind väntande beviljanden till kontot som just loggade in.

    Adressen kommer ur den VERIFIERADE token (samma bevis som
    `membership.claim_for_email`, som access-vägen redan anropar -- den löser
    också in platsen). Idempotent: inget att lösa in -> tom lista.
    """
    email = str(email or "").strip().lower()
    if not email or not user_id:
        return []
    claimed: list[MembershipGrant] = []
    pending = MembershipGrant.objects.filter(
        user_id__isnull=True, email__iexact=email, revoked_at__isnull=True,
    )
    for grant in pending:
        MembershipGrant.objects.filter(id=grant.id, user_id__isnull=True).update(
            user_id=user_id, email="",
        )
        grant.refresh_from_db()
        claimed.append(grant)
        audit.record(
            "membership_grant_claimed", company_id=grant.company_id, actor_user_id=user_id,
            actor_kind="customer", subject_type="membership_grant", subject_id=grant.id,
            detail={"email": email},
        )
    return claimed


@transaction.atomic
def revoke(grant: MembershipGrant, *, reason: str, actor_user_id=None, now=None) -> MembershipGrant:
    """
    Återkalla beviljandet. Fönstret stängs direkt; den vanliga periodprövningen
    (abonnemang, prov, frist) gäller igen.

    En plats som skapades AV beviljandet avslutas och avregistreras -- den var
    aldrig betald. En redan köpt plats röras inte (`license_created` skiljer
    dem). App-sessionen på platsen stängs i båda fallen: en avslutad session
    återupplivas aldrig, och nästa anrop prövar perioden på nytt.
    """
    now = now or timezone.now()
    reason = str(reason or "").strip()
    if not reason:
        raise GrantError("reason_required", "Skriv varför beviljandet återkallas.")
    if grant.revoked_at is not None:
        return grant

    MembershipGrant.objects.filter(id=grant.id, revoked_at__isnull=True).update(
        revoked_at=now, revoked_by=actor_user_id, revoke_reason=reason,
    )
    grant.refresh_from_db()

    license = grant.license
    for row in MembershipSession.objects.filter(license=license, ended_at__isnull=True):
        MembershipSession.objects.filter(id=row.id, ended_at__isnull=True).update(
            ended_at=now, ended_reason=MembershipSession.EndReason.UNASSIGNED,
        )
    if grant.license_created:
        LicenseCounty.objects.filter(license=license).exclude(active_to__lte=now).update(
            active_to=now
        )
        License.objects.filter(id=license.id).update(
            status=License.Status.CANCELED, canceled_at=now, ends_at=now,
            assignee_user_id=None, assignee_email="",
        )
    audit.record(
        "membership_grant_revoked", company_id=grant.company_id, actor_user_id=actor_user_id,
        actor_kind="platform_admin", subject_type="membership_grant", subject_id=grant.id,
        detail={
            "license_id": str(license.id), "license_created": grant.license_created,
            "reason": reason,
        },
    )
    return grant


# ---------------------------------------------------------------------------
# Visa
# ---------------------------------------------------------------------------


def view(grant: MembershipGrant, *, now=None) -> dict:
    """Beviljandet som JSON -- samma form adminvyn och revisionsloggen läser."""
    now = now or timezone.now()
    from fleet import accounts

    resolved = accounts.email_for(grant.user_id) if grant.user_id else ""
    return {
        "id": str(grant.id),
        "licenseId": str(grant.license_id),
        "licenseCreated": grant.license_created,
        "userId": str(grant.user_id) if grant.user_id else None,
        "resolvedEmail": resolved,
        "email": grant.email,
        "counties": grant.counties,
        "allCounties": grant.all_counties,
        "reason": grant.reason,
        "startsAt": grant.starts_at.isoformat() if grant.starts_at else None,
        "endsAt": grant.ends_at.isoformat() if grant.ends_at else None,
        "grantedBy": str(grant.granted_by) if grant.granted_by else None,
        "createdAt": grant.created_at.isoformat() if grant.created_at else None,
        "active": _is_active(grant, now),
        "revokedAt": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "revokedBy": str(grant.revoked_by) if grant.revoked_by else None,
        "revokeReason": grant.revoke_reason,
    }
