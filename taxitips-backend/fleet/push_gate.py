"""
Kontrollen av mottagaren i samma ögonblick notisen ska skickas.

**Varför urvalet vid köandet inte räcker.** En notis köas när tipset räknas
fram och skickas en stund senare. Däremellan kan administratören ha spärrat
telefonen, en annan förare ha tagit över bilen, eller perioden ha löpt ut. Den
kön bär en titel och en text som beskriver ett skyddat tips -- skickas den
ändå har åtkomstkontrollen kringgåtts av tidsfördröjningen (§3).

Redan LEVERERAT innehåll går inte att återkalla. Det här steget handlar om det
som ännu inte lämnat servern.

Länsprövningen är avsiktligt generös på en punkt: ett tips utan länskoder
släpps igenom, samma undantag som listan gör. Trafikverkets tågdata saknar
länsfält (invariant 14 i AGENTS.md), och avståndsgrinden i `within_reach()` är
det som håller dem -- inte länsfiltret.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from fleet.access import company_window, enforce_licenses, license_counties
from fleet.models import DeviceApproval, License, VehicleSession


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str


def can_receive(device, snapshot: dict | None = None, *, now=None) -> Verdict:
    """
    Får den här telefonen ta emot den här notisen just nu?

    Anropas strax före sändningen, per leverans. Håll den billig: den körs en
    gång per notis och per cykel.
    """
    now = now or timezone.now()

    company_id = getattr(device, "company_id", None)
    if company_id is None:
        # Varje rad i `devices` har ett bolag (kolumnen är NOT NULL). Saknas
        # det är objektet inte en enhet, och då finns inget att kontrollera
        # mot -- vilket aldrig får betyda "skicka ändå".
        return Verdict(False, "device_without_company")

    window = company_window(company_id, now)
    if not window.ok:
        return Verdict(False, f"company_{window.reason}")

    approvals = DeviceApproval.objects.filter(
        device_id=device.id, status=DeviceApproval.Status.ACTIVE
    ).exists()
    if not approvals:
        if enforce_licenses() or License.objects.filter(company_id=company_id).exists():
            # Företaget är migrerat men telefonen är spärrad eller inte
            # parkopplad. Ingen notis.
            return Verdict(False, "device_not_approved")
        # Omigrerat företag: samma regel som förut, ingen länsprövning.
        return Verdict(True, "unmigrated_company")

    session = VehicleSession.objects.filter(
        device_id=device.id, ended_at__isnull=True
    ).select_related("license", "approval").first()
    if session is None:
        # Telefonen är inte i tjänst i någon bil. Att väcka den vore att
        # skicka ut ett skyddat tips till någon som inte kan öppna det.
        return Verdict(False, "no_active_session")
    if session.approval.status != DeviceApproval.Status.ACTIVE:
        # Samma prövning som förarvyn (access._driver_access): ett pass på ett
        # utbytt eller spärrat godkännande ger ingen data, och då inte heller
        # en notis om data föraren inte kan öppna.
        return Verdict(False, "session_approval_inactive")
    if session.license.status not in (
        License.Status.ACTIVE, License.Status.TRIAL, License.Status.PENDING_CANCEL
    ):
        return Verdict(False, "license_inactive")

    snapshot = snapshot or {}
    if "area_codes" in snapshot:
        codes = [str(c) for c in (snapshot.get("area_codes") or [])]
    else:
        # Leveranser köade innan ögonblicksbilden bar länskoder. Slå upp tipset;
        # är det gallrat finns inget län att pröva mot och notisen släpps
        # igenom, samma undantag som för ett tips utan koordinat.
        codes = _codes_from_opportunity(snapshot.get("id"))
    if not codes:
        return Verdict(True, "unplaced_tip")
    entitled = set(license_counties(session.license_id, now))
    if any(code in entitled or code[:2] in entitled for code in codes):
        return Verdict(True, "entitled")
    return Verdict(False, "outside_licensed_county")


def _codes_from_opportunity(opportunity_id) -> list[str]:
    if not opportunity_id:
        return []
    from core.models import Opportunity

    row = Opportunity.objects.filter(id=opportunity_id).values_list("area_codes", flat=True).first()
    return [str(c) for c in (row or [])]
