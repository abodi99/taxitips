"""
Åtkomstkontrollen. Kontrolleras på servern, på varje skyddad begäran.

Sex frågor, i den här ordningen, och svaret bär alltid skälet:

1. Vilket företag? (credential -> enhet -> bolag, eller JWT -> medlemskap)
2. Får enheten det här? (aktivt `DeviceApproval`, inte spärrat)
3. Finns licensen och är den aktiv?
4. Är det den AKTUELLA aktiva sessionen? (en avslutad session ger ingenting)
5. Är tidsperioden giltig, mätt med serverns UTC-klocka?
6. Vilka län ger licensen rätt till?

**Varför inte JWT:n eller ett klientfilter räcker.** En giltig signatur säger
att token är utfärdad, inte att åtkomsten fortfarande gäller. Åtkomsträtten
hänger på billicensen och måste kunna spärras medan en gammal token lever
kvar -- en borttappad telefon ska sluta visa tips i samma sekund
administratören spärrar den, inte när token råkar gå ut. Därför läses
godkännandet och sessionen ur databasen vid varje anrop, aldrig ur token.

**Tre vägar in, med olika räckvidd:**

* `driver` -- förartelefon med credential, godkännande OCH aktiv bilsession.
  Ser tips i licensens län.
* `member` -- inloggad ägare/administratör via Supabase-JWT. Ser tips i de län
  företaget faktiskt betalar för, aldrig mer. Administrationsvyn är inte en
  gratis förarplats (§1), men att ta bort vägen helt hade låst ute varje ägare
  utan parad telefon -- se invariant 6 i AGENTS.md, buggen som 20260902000005
  en gång rättade.
* `legacy` -- företag som fanns före licensmodellen, under en uttrycklig,
  daterad övergång (`CompanyProfile.legacy_access_until`). Utan den hade
  utrullningen låst ute varje befintlig kund i samma sekund den deployades.

`counties` i svaret är en LISTA MED RÄTTIGHETER, inte ett filter. Förarens
egna länsval får bara smalna av den, aldrig vidga den.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from billing.models import Company, CompanyMember, Device
from core.entitlement import verify_supabase_jwt
from fleet.models import (
    CompanyProfile,
    DeviceApproval,
    DeviceCredential,
    License,
    LicenseCounty,
    StaffRole,
    Subscription,
    SubscriptionStatus,
    Trial,
    VehicleSession,
)
from fleet.pairing import hash_token
from fleet.roles import Principal, permissions_for, staff_permissions_for


@dataclass(frozen=True)
class Access:
    """Svaret. `reason` finns alltid -- ett tyst False går inte att felsöka."""

    ok: bool
    reason: str
    kind: str = ""
    company_id: str | None = None
    device_id: str | None = None
    license_id: str | None = None
    session_id: str | None = None
    vehicle_plate: str = ""
    counties: tuple[str, ...] = ()
    valid_until: object | None = None
    message: str = ""
    # Sätts när enheten är godkänd men saknar aktiv bilsession: appen ska då
    # visa bilvalet, inte ett fel.
    needs_session: bool = False
    available_licenses: tuple[dict, ...] = field(default_factory=tuple)
    # Skiljer "inga län" (ingen rättighet) från "ingen länsbegränsning"
    # (företag som ännu inte migrerats till licensmodellen). Utan fältet hade
    # en tom lista betytt båda, och ett omigrerat företag hade fått ett tomt
    # flöde som ser ut precis som "inga störningar just nu".
    unrestricted: bool = False

    def __bool__(self) -> bool:
        return self.ok

    def as_dict(self) -> dict:
        return {
            "entitled": self.ok,
            "reason": self.reason,
            "kind": self.kind,
            "companyId": self.company_id,
            "licenseId": self.license_id,
            "sessionId": self.session_id,
            "vehicle": self.vehicle_plate,
            "counties": list(self.counties),
            "validUntil": self.valid_until.isoformat() if self.valid_until else None,
            "message": self.message,
            "needsSession": self.needs_session,
            "availableLicenses": list(self.available_licenses),
            "unrestrictedCounties": self.unrestricted,
        }


# ---------------------------------------------------------------------------
# Tidsperioden
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    ok: bool
    reason: str
    valid_until: object | None = None


def enforce_licenses() -> bool:
    """
    Är licensmodellen den enda vägen in?

    `FLEET_ENFORCE_LICENSES` är False under utrullningen: ett företag som ännu
    inte har någon billicens kör vidare på den gamla regeln (bolagets status i
    Supabase) och får inget länsfilter. Att deploya den här koden låser
    alltså inte ute en enda befintlig kund.

    Efter `manage.py migrate_legacy_fleet` sätts flaggan till True, och då
    krävs licens, godkännande och session av alla. Rullar något fel är
    återställningen att sätta tillbaka den till False -- ingen data behöver
    rullas tillbaka, eftersom migreringen bara LÄGGER TILL rader.
    """
    return str(getattr(settings, "FLEET_ENFORCE_LICENSES", "")) in ("1", "True", "true")


def company_window(company_id, now=None) -> Window:
    """
    Har företaget en giltig period just nu?

    Provslut, betald period, uppsägningsdatum och betalningsfrist hålls isär
    (§9) -- de betyder olika saker för kunden och får olika svar här. Klockan
    är serverns UTC, läst vid anropet: ett cron-jobb som råkar stå stilla får
    inte förlänga en period.
    """
    now = now or timezone.now()
    subscription = Subscription.objects.filter(company_id=company_id).first()

    if subscription is None:
        # Inget abonnemang i den nya modellen: företaget är antingen helt nytt
        # eller ännu inte migrerat. Faller tillbaka på Supabases `companies`,
        # samma regel som core/entitlement.py.
        return _legacy_company_window(company_id, "legacy_company_status")

    if subscription.status in (SubscriptionStatus.TRIALING, SubscriptionStatus.NONE):
        # Ett pågående prov (eller en kupongs tillfälliga åtkomst) ger en
        # period även när abonnemanget inte har någon ännu. Inget sätter
        # abonnemanget till `trialing` när ett prov startar -- provet bor på
        # sin egen rad -- så att bara titta här vid TRIALING hade nekat varje
        # provföretag all data från första minuten.
        trial = (
            Trial.objects.filter(company_id=company_id, status=Trial.Status.ACTIVE)
            .order_by("-created_at")
            .first()
        )
        if trial and trial.ends_at and trial.ends_at > now:
            return Window(True, "trial", trial.ends_at)
        if subscription.status == SubscriptionStatus.TRIALING:
            # Stripes `trialing` utan eget prov: gratisdagar från en kupong har
            # flyttat nästa debitering (fleet/sales.py). Perioden är då betald
            # fram till dess.
            if subscription.current_period_end and subscription.current_period_end > now:
                return Window(True, "billing_deferred", subscription.current_period_end)
            return Window(False, "trial_ended")
        if Trial.objects.filter(company_id=company_id, status=Trial.Status.ENDED).exists():
            return Window(False, "trial_ended")
        return Window(False, "no_subscription")

    if subscription.status == SubscriptionStatus.ACTIVE:
        if subscription.current_period_end and subscription.current_period_end > now:
            return Window(True, "paid_period", subscription.current_period_end)
        if subscription.current_period_end is None:
            # Perioden är ännu inte känd. Det gäller ett nyss migrerat bolag,
            # vars period fylls av nästa Stripe-händelse eller av avstämningen.
            # "Vet inte" får inte betyda "utgången": det hade låst ute varje
            # befintlig kund i samma sekund migreringskommandot kördes, vilket
            # är precis den oannonserade utelåsning uppdraget förbjuder.
            # Bolagets status i Supabase gäller tills perioden är känd.
            return _legacy_company_window(company_id, "period_unknown")
        # Perioden har passerat utan att en förnyelse bokförts. Betalningsfristen
        # gäller bara den som betalat förut (§8).
        if subscription.grace_until and subscription.grace_until > now:
            return Window(True, "grace", subscription.grace_until)
        return Window(False, "period_expired")

    if subscription.status == SubscriptionStatus.PAST_DUE:
        if subscription.current_period_end and subscription.current_period_end > now:
            return Window(True, "paid_period", subscription.current_period_end)
        if subscription.grace_until and subscription.grace_until > now:
            return Window(True, "grace", subscription.grace_until)
        return Window(False, "past_due")

    if subscription.status == SubscriptionStatus.CANCELED:
        # Uppsagt: åtkomsten löper till den betalda periodens slut. Ingen
        # ytterligare frist (§8).
        until = subscription.access_until or subscription.current_period_end
        if until and until > now:
            return Window(True, "canceled_paid_period", until)
        return Window(False, "canceled")

    return Window(False, "no_subscription")


# ---------------------------------------------------------------------------
# Länsrättigheter
# ---------------------------------------------------------------------------


def _legacy_company_window(company_id, reason: str) -> Window:
    """
    Den gamla regeln: bolagets status i Supabase. Används när den nya modellen
    ännu inte vet något -- inget abonnemang alls, eller ett abonnemang utan
    känd period.
    """
    company = Company.objects.filter(id=company_id).first()
    if company is None:
        return Window(False, "unknown_company")
    if company.status in ("trial", "active") or company.subscription_status == "active":
        return Window(True, reason)
    return Window(False, f"company_{company.status}")


def license_counties(license_id, now=None) -> tuple[str, ...]:
    """Baslän + aktiva extra län. Schemalagda ändringar räknas inte förrän de gäller."""
    now = now or timezone.now()
    rows = LicenseCounty.objects.filter(
        license_id=license_id, active_from__lte=now
    ).exclude(active_to__lte=now)
    return tuple(sorted({row.county_code for row in rows}))


def company_counties(company_id, now=None) -> tuple[str, ...]:
    """
    Unionen av företagets alla licenser -- den räckvidd en inloggad
    administratör får. Företagets samlade län tillfaller INTE varje bil (§5);
    den här unionen används bara för administratörsvyn, aldrig för en förare.
    """
    now = now or timezone.now()
    license_ids = License.objects.filter(
        company_id=company_id,
        status__in=[License.Status.ACTIVE, License.Status.TRIAL, License.Status.PENDING_CANCEL],
    ).values_list("id", flat=True)
    rows = LicenseCounty.objects.filter(
        license_id__in=list(license_ids), active_from__lte=now
    ).exclude(active_to__lte=now)
    return tuple(sorted({row.county_code for row in rows}))


# ---------------------------------------------------------------------------
# Credential -> enhet
# ---------------------------------------------------------------------------


def device_for_token(token: str | None) -> tuple[Device | None, DeviceCredential | None, str]:
    """
    Slår upp enheten ur bärartoken. Två format, båda serververifierade:

    * `hashed_v1` -- nya parkopplingar. Servern har bara SHA-256-hashen.
    * klartext i `devices.token` -- telefoner som parkopplades före den här
      modellen. De fortsätter fungera; att dra den vägen ur väggen hade låst
      ute varje befintlig förare utan förvarning.
    """
    if not token:
        return None, None, "no_device_token"

    credential = DeviceCredential.objects.filter(
        token_hash=hash_token(token), revoked_at__isnull=True
    ).first()
    if credential is not None:
        device = Device.objects.filter(id=credential.device_id).first()
        if device is None:
            return None, credential, "credential_without_device"
        return device, credential, "credential"

    device = Device.objects.filter(token=token).first()
    if device is None:
        return None, None, "unknown_device_token"

    # Klartextvägen gäller BARA telefoner som aldrig fått en hashad hemlighet.
    # Sedan parkopplingen skriver installations-id:t till `devices.token` är
    # det fältet inte längre en hemlighet -- appen känner till det, det syns i
    # administratörsvyn, och att godta det hade gjort den nya hemligheten
    # meningslös. En telefon som HAR en hemlighet måste använda den.
    if DeviceCredential.objects.filter(
        device_id=device.id, scheme=DeviceCredential.Scheme.HASHED_V1, revoked_at__isnull=True
    ).exists():
        return None, None, "legacy_token_superseded"

    return device, None, "legacy_token"


# ---------------------------------------------------------------------------
# Huvudingången
# ---------------------------------------------------------------------------


def resolve(request, now=None) -> Access:
    """
    Åtkomsten för den här begäran. Förarvägen först -- den är den vanligaste
    och kostar minst, samma ordning som `current_entitlement`s coalesce.
    """
    now = now or timezone.now()

    device_result = None
    token = request.headers.get("X-Device-Token") or request.GET.get("device_token")
    if token:
        device_result = _driver_access(token, now)
        # En token som är okänd får ändå prövas mot JWT-vägen: en ägare kan ha
        # en gammal token liggande OCH vara inloggad. Men skälet sparas, så att
        # svaret blir "unknown_device_token" och inte "no_credentials" när det
        # inte finns någon JWT -- felsökningen börjar i det skälet.
        if device_result.ok or device_result.reason not in (
            "no_device_token", "unknown_device_token", "legacy_token_superseded"
        ):
            return device_result

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        payload = verify_supabase_jwt(auth[7:].strip())
        if payload:
            return _member_access(payload, now)
        # `is not None`, inte `or`: Access.__bool__ är False för ett nekat
        # svar, och `or` hade då kastat bort skälet och svarat "inga
        # credentials" på en token som faktiskt skickades.
        return device_result if device_result is not None else Access(False, "invalid_jwt")

    return device_result if device_result is not None else Access(False, "no_credentials")


def _driver_access(token: str, now) -> Access:
    device, credential, how = device_for_token(token)
    if device is None:
        return Access(False, how)

    window = company_window(device.company_id, now)

    approvals = list(
        DeviceApproval.objects.filter(device_id=device.id, status=DeviceApproval.Status.ACTIVE)
        .select_related("vehicle", "license")
    )
    if not approvals:
        legacy = _legacy_access(device, window, now)
        if legacy is not None:
            return legacy
        unmigrated = _unmigrated_access(device, window, now)
        if unmigrated is not None:
            return unmigrated
        return Access(
            False, "device_not_approved",
            company_id=str(device.company_id), device_id=str(device.id),
            message="Telefonen är inte godkänd för någon bil. Be din administratör om en kod.",
        )

    if not window.ok:
        return Access(
            False, window.reason, kind="driver",
            company_id=str(device.company_id), device_id=str(device.id),
            message=_window_message(window.reason),
        )

    session = (
        VehicleSession.objects.filter(device_id=device.id, ended_at__isnull=True)
        .select_related("vehicle", "license")
        .first()
    )
    if session is None:
        # Godkänd men inte i tjänst i någon bil. Inte ett fel -- appen ska visa
        # bilvalet. Ingen tipsdata lämnas ut förrän en session finns (§3).
        return Access(
            False, "no_active_session", kind="driver",
            company_id=str(device.company_id), device_id=str(device.id),
            needs_session=True,
            available_licenses=tuple(
                {
                    "licenseId": str(a.license_id),
                    "vehicleId": str(a.vehicle_id),
                    "plate": a.vehicle.plate,
                    "label": a.label or a.vehicle.label,
                }
                for a in approvals
            ),
            message="Välj vilken bil du kör.",
        )

    if session.approval.status != DeviceApproval.Status.ACTIVE:
        # Spärren tog effekt mellan sessionens start och nu.
        return Access(
            False, "device_blocked", kind="driver",
            company_id=str(device.company_id), device_id=str(device.id),
            message="Telefonen är spärrad av din administratör.",
        )

    if session.license.status not in (
        License.Status.ACTIVE, License.Status.TRIAL, License.Status.PENDING_CANCEL
    ):
        return Access(
            False, "license_inactive", kind="driver",
            company_id=str(device.company_id), device_id=str(device.id),
            message="Billicensen är avslutad.",
        )

    if credential is not None:
        DeviceCredential.objects.filter(id=credential.id).update(last_used_at=now)

    counties = license_counties(session.license_id, now)
    return Access(
        True, "driver", kind="driver",
        company_id=str(device.company_id), device_id=str(device.id),
        license_id=str(session.license_id), session_id=str(session.id),
        vehicle_plate=session.vehicle.plate, counties=counties,
        valid_until=window.valid_until,
    )


def _unmigrated_access(device: Device, window: Window, now) -> Access | None:
    """
    Företag som ännu inte har en enda billicens.

    Exakt den gamla regeln: bolagets status avgör, och inget länsfilter läggs
    på. Vägen stängs av `FLEET_ENFORCE_LICENSES=1`, och först då -- inte av
    att den här koden deployas.
    """
    if enforce_licenses():
        return None
    if License.objects.filter(company_id=device.company_id).exists():
        # Företaget ÄR migrerat. Då gäller licensmodellen, och den här
        # telefonen behöver parkopplas.
        return None
    if not window.ok:
        return Access(
            False, window.reason, kind="unmigrated",
            company_id=str(device.company_id), device_id=str(device.id),
            message=_window_message(window.reason),
        )
    return Access(
        True, "unmigrated_company", kind="unmigrated",
        company_id=str(device.company_id), device_id=str(device.id),
        valid_until=window.valid_until, unrestricted=True,
    )


def _legacy_access(device: Device, window: Window, now) -> Access | None:
    """
    Övergångsvägen för telefoner som parkopplades före licensmodellen.

    Gäller bara till och med `CompanyProfile.legacy_access_until` och bara med
    de län företaget hade då. Efter datumet får telefonen gå genom
    parkopplingen som alla andra -- men kunden har hunnit få veta det.
    """
    profile = CompanyProfile.objects.filter(company_id=device.company_id).first()
    if profile is None or not profile.legacy_access_until:
        return None
    if profile.legacy_access_until <= now:
        return None
    if not window.ok:
        return Access(
            False, window.reason, kind="legacy",
            company_id=str(device.company_id), device_id=str(device.id),
            message=_window_message(window.reason),
        )
    counties = tuple(sorted({str(c) for c in (profile.legacy_counties or [])}))
    return Access(
        True, "legacy_migration", kind="legacy",
        company_id=str(device.company_id), device_id=str(device.id),
        counties=counties,
        # Visste vi inte vilka län bolaget bevakade när övergången inleddes
        # gäller ingen länsbegränsning -- exakt som före licensmodellen. Att
        # låta en tom lista betyda "inga län" hade tagit bort ALL data från en
        # kund som aldrig satt ett körområde, mitt i övergångsfönstret.
        unrestricted=not counties,
        valid_until=min(
            profile.legacy_access_until,
            window.valid_until or profile.legacy_access_until,
        ),
        message="Övergångsåtkomst. Be din administratör parkoppla telefonen mot en bil.",
    )


def _member_access(payload: dict, now) -> Access:
    user_id = payload.get("sub")
    member = CompanyMember.objects.filter(user_id=user_id, status="active").first()
    if member is None:
        return Access(False, "no_active_membership")
    window = company_window(member.company_id, now)
    if not window.ok:
        return Access(
            False, window.reason, kind="member", company_id=str(member.company_id),
            message=_window_message(window.reason),
        )
    counties = company_counties(member.company_id, now)
    unrestricted = not enforce_licenses() and not License.objects.filter(
        company_id=member.company_id
    ).exists()
    return Access(
        True, "member", kind="member", company_id=str(member.company_id),
        counties=counties, valid_until=window.valid_until, unrestricted=unrestricted,
    )


def _window_message(reason: str) -> str:
    return {
        "trial_ended": "Provperioden är slut. Lägg en beställning för att fortsätta.",
        "period_expired": "Abonnemanget har gått ut.",
        "past_due": "Betalningen har inte gått igenom. Uppdatera betalmetoden.",
        "canceled": "Abonnemanget är avslutat.",
        "no_subscription": "Företaget har inget abonnemang.",
        "unknown_company": "Företaget finns inte.",
    }.get(reason, "Åtkomsten är inte aktiv.")


# ---------------------------------------------------------------------------
# Behörighet för administrativa anrop
# ---------------------------------------------------------------------------


def principal_for(request) -> Principal:
    """
    Vem som anropar en administrativ endpoint.

    Bara den inloggade vägen: en förartoken ger aldrig administrativ
    behörighet, oavsett vad klienten påstår. `aal` läses ur den VERIFIERADE
    token -- en klient som säger sig ha gjort tvåfaktor bevisar ingenting.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return Principal()
    payload = verify_supabase_jwt(auth[7:].strip())
    if not payload:
        return Principal()

    user_id = payload.get("sub")
    aal = str(payload.get("aal") or "")

    staff = StaffRole.objects.filter(user_id=user_id, is_active=True).first()
    if staff is not None:
        return Principal(
            user_id=user_id, staff_role=staff.role, aal=aal,
            permissions=staff_permissions_for(staff.role),
        )

    member = CompanyMember.objects.filter(user_id=user_id, status="active").first()
    if member is None:
        return Principal(user_id=user_id, aal=aal)
    return Principal(
        user_id=user_id, company_id=str(member.company_id), role=member.role or "",
        aal=aal, permissions=permissions_for(member.role),
    )


def allowed_counties(access: Access, requested: list[str] | None) -> list[str]:
    """
    Snittet mellan rättighet och förarens val.

    Förarens val får smalna av, aldrig vidga: ett filter som ber om ett län
    licensen inte betalar för ger ingenting därifrån. GPS-positionen ger
    heller ingen rättighet -- den finns inte i den här uträkningen (§5).
    """
    chosen = [str(c).strip() for c in (requested or []) if str(c).strip()]
    if access.unrestricted:
        # Företaget har ingen licensmodell ännu: förarens val gäller som förut.
        return sorted(set(chosen))
    entitled = set(access.counties)
    if not chosen:
        return sorted(entitled)
    return sorted(entitled & set(chosen))
