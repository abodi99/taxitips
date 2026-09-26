"""
Roller och behörigheter -- kontrollerade på servern, alltid.

Kundens roller bor kvar i Supabases `company_members.role`: att införa ett
andra rollsystem hade betytt två sanningar om vem som får köpa. Plattformens
egna roller (säljare, support) ligger i `fleet.StaffRole`, eftersom en säljare
inte är medlem i kundens företag och aldrig får ärva kundens behörigheter.

Enmansföretag: ägaren har samtliga kundbehörigheter, vilket följer av att
OWNER-rollen listar allihop -- inget särfall behövs.

**Tvåfaktor.** Känsliga behörigheter kräver `aal2` i Supabase-JWT:n, alltså en
session som passerat ett andra steg. Införandet är mjukt: `TWO_FACTOR_REQUIRED_FROM`
är NULL tills det sätts, och en befintlig kund låses aldrig ute utan att datumet
passerats (§2). Kravet kontrolleras på servern -- en klient som säger sig ha
gjort tvåfaktor bevisar ingenting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from fleet.models import StaffRole


class Perm:
    VIEW_COMPANY = "view_company"
    MANAGE_VEHICLES = "manage_vehicles"
    MANAGE_DEVICES = "manage_devices"
    MANAGE_COUNTIES = "manage_counties"
    PURCHASE = "purchase"
    CANCEL_SUBSCRIPTION = "cancel_subscription"
    VIEW_BILLING = "view_billing"
    MANAGE_MEMBERS = "manage_members"
    TRANSFER_OWNERSHIP = "transfer_ownership"
    CLOSE_ACCOUNT = "close_account"
    # Plattformen
    CREATE_SALES_INVITE = "create_sales_invite"
    REVIEW_CASES = "review_cases"
    # Adminwebben (admin.html). Läsa räcker för support; ändra kräver
    # plattformsadministratör -- och tvåfaktor när kravet är påslaget, för
    # att en kapad adminsession annars kan förlänga vilket abonnemang som
    # helst eller spärra vilken förare som helst.
    ADMIN_VIEW = "admin_view"
    ADMIN_MANAGE = "admin_manage"
    # Säljflödet i adminwebben: lägga upp företag, bilar, paket, prov,
    # kuponger (lösa in, inte skapa), förarkoder, betallänkar och uppsägning
    # till periodens slut. Det som flyttar pengar eller rättigheter UTAN
    # betalning -- markera betald utanför Stripe, avsluta direkt, skapa
    # kuponger, ändra status för hand -- kräver ADMIN_MANAGE.
    ADMIN_SELL = "admin_sell"
    # Supportchatten: svara användare och avsluta konversationer. Flyttar
    # varken pengar eller rättigheter, så den kräver inte tvåfaktor och ges
    # till alla personalroller -- supportrollen hade annars bara kunnat läsa.
    ADMIN_SUPPORT = "admin_support"


OWNER = "company_owner"
FLEET_ADMIN = "fleet_admin"
FINANCE = "finance"
DRIVER = "driver"

# Kundens roller. Ägaren har allt; de andra har sitt eget område och inget mer.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    OWNER: frozenset({
        Perm.VIEW_COMPANY, Perm.MANAGE_VEHICLES, Perm.MANAGE_DEVICES,
        Perm.MANAGE_COUNTIES, Perm.PURCHASE, Perm.CANCEL_SUBSCRIPTION,
        Perm.VIEW_BILLING, Perm.MANAGE_MEMBERS, Perm.TRANSFER_OWNERSHIP,
        Perm.CLOSE_ACCOUNT,
    }),
    FLEET_ADMIN: frozenset({
        Perm.VIEW_COMPANY, Perm.MANAGE_VEHICLES, Perm.MANAGE_DEVICES,
        # Får välja län som bilen REDAN har rätt till; att köpa ett nytt är
        # ett ekonomiskt åtagande och kräver PURCHASE.
        Perm.MANAGE_COUNTIES,
    }),
    FINANCE: frozenset({
        Perm.VIEW_COMPANY, Perm.VIEW_BILLING, Perm.PURCHASE,
        Perm.CANCEL_SUBSCRIPTION,
    }),
    DRIVER: frozenset(),
}

# Plattformens roller. Säljaren kan bjuda in till prov men aldrig återställa
# provhistorik (§7). Sedan säljflödet (2026-09-21) ser säljaren kundens paket
# och beställningar: att lägga upp och ändra ett abonnemang i telefon går inte
# utan att se vad det kostar. Säljaren kan däremot inte ge åtkomst utan
# betalning utöver prov och kuponger som administratören redan skapat.
STAFF_PERMISSIONS: dict[str, frozenset[str]] = {
    StaffRole.Role.SALES: frozenset({
        Perm.CREATE_SALES_INVITE, Perm.ADMIN_VIEW, Perm.ADMIN_SELL, Perm.ADMIN_SUPPORT,
    }),
    StaffRole.Role.SUPPORT: frozenset({Perm.VIEW_COMPANY, Perm.ADMIN_VIEW, Perm.ADMIN_SUPPORT}),
    StaffRole.Role.PLATFORM_ADMIN: frozenset({
        Perm.VIEW_COMPANY, Perm.REVIEW_CASES, Perm.CREATE_SALES_INVITE,
        Perm.ADMIN_VIEW, Perm.ADMIN_MANAGE, Perm.ADMIN_SELL, Perm.ADMIN_SUPPORT,
    }),
}

# Behörigheter som kräver en tvåfaktorssession när kravet är påslaget.
TWO_FACTOR_PERMISSIONS: frozenset[str] = frozenset({
    Perm.PURCHASE, Perm.CANCEL_SUBSCRIPTION, Perm.MANAGE_MEMBERS,
    Perm.TRANSFER_OWNERSHIP, Perm.CLOSE_ACCOUNT, Perm.ADMIN_MANAGE,
    Perm.ADMIN_SELL,
})


@dataclass(frozen=True)
class Principal:
    """Vem som anropar: kundmedlem, plattformspersonal eller ingen av dem."""

    user_id: str | None = None
    company_id: str | None = None
    role: str = ""
    staff_role: str = ""
    aal: str = ""
    permissions: frozenset[str] = frozenset()

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def has_two_factor(self) -> bool:
        return self.aal == "aal2"


def two_factor_required_from() -> datetime | None:
    """
    Datumet då tvåfaktor börjar krävas för känsliga behörigheter.

    NULL (standard) betyder att kravet inte är påslaget. Det finns för att
    införandet ska kunna annonseras innan det slår till -- en befintlig ägare
    ska inte upptäcka kravet genom att bli utelåst mitt i en uppsägning.
    """
    value = getattr(settings, "FLEET_TWO_FACTOR_REQUIRED_FROM", None)
    if not value:
        return None
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


def two_factor_enforced(now: datetime | None = None) -> bool:
    required_from = two_factor_required_from()
    if required_from is None:
        return False
    return (now or timezone.now()) >= required_from


def permissions_for(role: str | None) -> frozenset[str]:
    return ROLE_PERMISSIONS.get((role or "").strip(), frozenset())


def staff_permissions_for(role: str | None) -> frozenset[str]:
    return STAFF_PERMISSIONS.get((role or "").strip(), frozenset())


class PermissionDenied(Exception):
    """Nekad behörighet, med ett skäl klienten kan visa."""

    def __init__(self, reason: str, message: str = "", status: int = 403):
        super().__init__(reason)
        self.reason = reason
        self.message = message or "Du har inte behörighet till den här åtgärden."
        self.status = status


def require(principal: Principal, permission: str, *, now: datetime | None = None) -> None:
    """
    Kontrollen. Kastar PermissionDenied -- anroparen behöver aldrig komma ihåg
    att läsa ett returvärde.
    """
    if not principal.can(permission):
        raise PermissionDenied(
            "missing_permission",
            "Bara behöriga personer i företaget får göra det här.",
        )
    if permission in TWO_FACTOR_PERMISSIONS and two_factor_enforced(now):
        if not principal.has_two_factor:
            raise PermissionDenied(
                "two_factor_required",
                "Logga in med tvåfaktorsautentisering för att ändra "
                "ekonomiska åtaganden.",
            )
