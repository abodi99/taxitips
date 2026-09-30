"""
Kontrollerna vid självregistreringen: telefon, organisationsnummer,
personnummer (enskild firma) och e-post -- och flaggorna säljaren ser efteråt.

**Varför.** Provet är kortfritt, så det enda som står mellan en påhittad
registrering och fjorton gratisdagar är det här. Mätt i produktion
2026-09-29: av tre självregistrerade prov hade ett företagsnamnet "jsjjdd",
två inget telefonnummer, och ett var Aktiebolaget Volvos organisationsnummer.
Säljaren som ringer efter provet behöver ett nummer som går att ringa och ett
bolag som finns.

**Vad som stoppas och vad som bara flaggas.** Stoppas: det som med säkerhet
är fel -- ett nummer som inte är ett svenskt mobilnummer, ett personnummer
med ett datum som inte finns eller som tillhör någon under 18, ett bolag som
Bolagsverket inte känner till, en engångsadress. Flaggas (adminwebben,
Uppföljning): det som kan vara rätt men behöver en människa -- en enskild
firma vars namn inget register bekräftar, en branschkod som inte är
persontransport, ett register som inte svarade. En regel som stoppar en
riktig taxiägare kostar mer än en flagga som säljaren läser.

**Vad som INTE bevisas.** Att numret går att ringa, eller att personen får
företräda bolaget (§7). Det bekräftar säljarens samtal, inte formuläret.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.utils import timezone

# Svenska mobilnummer: 07X följt av sju siffror. 071 är maskin-till-maskin
# (larm, mätare) och ges inte till personer; 074/075/077/078 är inte
# tilldelade för mobiltelefoni (PTS nummerplan).
MOBILE_PREFIXES = ("70", "72", "73", "76", "79")

# Organisationsnumrets första siffra är gruppen (Skatteverket, SKV 709).
# Dödsbon, myndigheter/kommuner och ideella föreningar kör inte taxi.
_ORG_GROUP_BLOCKED = {
    "1": "ett dödsbo",
    "2": "en myndighet, region eller kommun",
    "8": "en ideell förening eller stiftelse",
}
# Grupper som alltid finns hos Bolagsverket: aktiebolag, ekonomiska
# föreningar, handels- och kommanditbolag. "Finns inte" betyder då fel nummer.
_ORG_GROUP_IN_REGISTRY = {"5", "7", "9"}

# Engångsadresser. Inte en fullständig lista -- bara de vanligaste, och
# adressen måste ändå bekräftas med en länk innan kontot finns.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "sharklasers.com",
    "10minutemail.com", "10minutemail.net", "temp-mail.org", "tempmail.com",
    "tempmailo.com", "yopmail.com", "yopmail.fr", "trashmail.com", "getnada.com",
    "dispostable.com", "maildrop.cc", "throwawaymail.com", "fakeinbox.com",
    "mohmal.com", "emailondeck.com", "mintemail.com", "mailnesia.com",
    "tempr.email", "discard.email", "spamgourmet.com", "burnermail.io",
    "moakt.com", "tmail.ws", "inboxkitten.com", "1secmail.com", "emltmp.com",
})

# SNI 49 är landtransport; 49.320 är taxi, 49.390 övrig persontransport.
TAXI_SNI_PREFIX = "49"


class CheckError(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(reason)
        self.reason = reason
        self.message = message


# ---------------------------------------------------------------------------
# Telefon
# ---------------------------------------------------------------------------


def normalize_phone(value: str | None) -> str:
    """Svenskt mobilnummer i E.164 (+46701234567), annars tom sträng."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        if not digits.startswith("46"):
            return ""
        national = digits[2:]
    elif digits.startswith("0046"):
        national = digits[4:]
    elif digits.startswith("46") and len(digits) == 11:
        national = digits[2:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        return ""
    national = national.lstrip("0") if national.startswith("0") else national
    if len(national) != 9 or not national.startswith(MOBILE_PREFIXES):
        return ""
    return "+46" + national


def _looks_made_up(e164: str) -> bool:
    """0700000000, 0701111111, 0701234567 -- nummer som skrivs för att komma förbi."""
    subscriber = e164[-7:]
    if len(set(subscriber)) <= 2:
        return True
    return subscriber in "01234567890123456789" or subscriber in "98765432109876543210"


def check_phone(value: str | None) -> str:
    """Normaliserat mobilnummer, eller CheckError med vad som är fel."""
    if not str(value or "").strip():
        raise CheckError(
            "phone_required",
            "Skriv ditt mobilnummer. Vi ringer och hjälper dig i gång under provet.",
        )
    e164 = normalize_phone(value)
    if not e164:
        raise CheckError(
            "invalid_phone", "Skriv ett svenskt mobilnummer, till exempel 070-123 45 67.",
        )
    if _looks_made_up(e164):
        raise CheckError("invalid_phone", "Mobilnumret ser inte ut att vara riktigt.")
    return e164


def phone_variants(e164: str) -> list[str]:
    """Formerna numret kan vara sparat i (äldre profiler sparade det som det skrevs)."""
    national = "0" + e164[3:]
    return [e164, national, e164[1:], f"{national[:3]}-{national[3:]}"]


def phone_used_by_other_trial(e164: str, *, exclude_company_id=None, now=None) -> bool:
    """
    Har numret redan använts för ett prov i ett annat bolag de senaste 24
    månaderna? Samma skäl som provspärren på organisationsnumret: en person
    med flera vilande bolag ska inte kunna ta ett prov per bolag.
    """
    from fleet.models import CompanyProfile, Trial
    from fleet.trials import TRIAL_COOLDOWN_MONTHS

    now = now or timezone.now()
    companies = CompanyProfile.objects.filter(contact_phone__in=phone_variants(e164))
    if exclude_company_id:
        companies = companies.exclude(company_id=exclude_company_id)
    ids = list(companies.values_list("company_id", flat=True))
    if not ids:
        return False
    return Trial.objects.filter(
        company_id__in=ids, created_at__gte=now - timedelta(days=TRIAL_COOLDOWN_MONTHS * 30),
    ).exclude(status=Trial.Status.CANCELED).exists()


# ---------------------------------------------------------------------------
# Organisationsnummer och personnummer
# ---------------------------------------------------------------------------


def org_kind(normalized: str) -> str:
    """
    "organisation" eller "person". Ett organisationsnummer har 20 eller mer i
    "månaden" (tredje och fjärde siffran), så att det aldrig kan förväxlas
    med ett personnummer -- det är hela skälet till regeln.
    """
    if len(normalized) == 10 and normalized.isdigit() and int(normalized[2]) >= 2:
        return "organisation"
    return "person"


def birthdate(normalized: str, *, today: date | None = None) -> date | None:
    """
    Födelsedatumet i ett tiosiffrigt personnummer, eller None om det inte
    finns. Samordningsnummer har dag + 60. Seklet väljs så att personen är
    högst 100 år, som Skatteverket gör för tiosiffriga nummer.
    """
    today = today or timezone.localdate()
    try:
        yy, mm, dd = int(normalized[0:2]), int(normalized[2:4]), int(normalized[4:6])
    except (ValueError, IndexError):
        return None
    if dd > 60:
        dd -= 60
    century = (today.year // 100) * 100
    year = century + yy if century + yy <= today.year else century - 100 + yy
    try:
        born = date(year, mm, dd)
    except ValueError:
        return None
    if born > today:
        return None
    return born


def check_identity(normalized: str, *, today: date | None = None) -> str:
    """Kontrollerar numrets form. Returnerar org_kind, eller CheckError."""
    today = today or timezone.localdate()
    kind = org_kind(normalized)
    if kind == "person":
        born = birthdate(normalized, today=today)
        if born is None:
            raise CheckError(
                "invalid_personal_number",
                "Personnumret har ett datum som inte finns. Kontrollera numret.",
            )
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if age < 18:
            raise CheckError(
                "personal_number_minor",
                "En enskild firma registreras av någon som fyllt 18. Kontrollera numret.",
            )
        return kind
    blocked = _ORG_GROUP_BLOCKED.get(normalized[0])
    if blocked:
        raise CheckError(
            "org_group_not_allowed",
            f"Organisationsnumret hör till {blocked}. Kontakta TaxiTips om det är fel.",
        )
    return kind


def check_registry(normalized: str, kind: str, registry) -> None:
    """
    Ett aktiebolag, en ekonomisk förening eller ett handelsbolag som
    Bolagsverket säger inte finns är ett felskrivet eller påhittat nummer.
    `registry` None = registret svarade inte; då släpps registreringen igenom
    och flaggas i stället (bolagsverket.py: aldrig ett hinder när tjänsten är nere).
    """
    if registry is None or registry.found or kind != "organisation":
        return
    if normalized[0] in _ORG_GROUP_IN_REGISTRY:
        raise CheckError(
            "org_not_in_registry",
            "Vi hittar inte organisationsnumret hos Bolagsverket. Kontrollera numret.",
        )


# ---------------------------------------------------------------------------
# E-post
# ---------------------------------------------------------------------------


def check_email(email: str, payload: dict | None = None) -> None:
    domain = (email or "").rsplit("@", 1)[-1].lower()
    if domain in DISPOSABLE_DOMAINS:
        raise CheckError(
            "disposable_email",
            "Använd företagets eller din vanliga e-postadress, inte en tillfällig.",
        )
    meta = (payload or {}).get("user_metadata") or {}
    if (payload or {}).get("is_anonymous") or meta.get("email_verified") is False:
        # Produktionens Supabase utfärdar ingen session förrän länken i
        # mejlet klickats; det här fångar en framtida autoconfirm.
        raise CheckError(
            "email_unverified", "Bekräfta e-postadressen med länken vi skickade först.",
        )


# ---------------------------------------------------------------------------
# Flaggor för säljaren
# ---------------------------------------------------------------------------


def is_taxi_industry(registry: dict | None) -> bool | None:
    """True/False ur SNI-koderna, None när registret inte har några."""
    sni = (registry or {}).get("sni") or []
    codes = [str(s.get("code") or "") for s in sni if s.get("code")]
    if not codes:
        return None
    return any(code.startswith(TAXI_SNI_PREFIX) for code in codes)


def flags(profile) -> list[dict]:
    """
    Det säljaren ska veta innan samtalet. Räknas fram ur profilen varje gång,
    så att en ny registerhämtning syns direkt.
    """
    out: list[dict] = []
    if profile is None:
        return out
    registry = profile.registry or {}
    kind = org_kind(profile.org_number) if profile.country == "SE" else "organisation"
    if kind == "person":
        out.append({
            "code": "sole_trader",
            "level": "warn",
            "text": "Enskild firma: namnet är inte kontrollerat mot något register.",
        })
    elif not registry:
        out.append({
            "code": "registry_missing",
            "level": "warn",
            "text": "Bolagsverket svarade inte vid registreringen. Hämta registret.",
        })
    elif not registry.get("found"):
        out.append({
            "code": "registry_not_found",
            "level": "danger",
            "text": "Bolagsverket hittar inte organisationsnumret.",
        })
    elif registry.get("status") not in ("active", ""):
        out.append({
            "code": "registry_status",
            "level": "danger",
            "text": f"Bolagsverket: {registry.get('statusText') or registry.get('status')}.",
        })
    taxi = is_taxi_industry(registry)
    if taxi is False:
        text = ", ".join(
            f"{s.get('code')} {s.get('text')}".strip() for s in (registry.get("sni") or [])[:2]
        )
        out.append({
            "code": "not_taxi_industry",
            "level": "danger",
            "text": f"Branschkoden är inte persontransport ({text}).",
        })
    if not profile.contact_phone:
        out.append({"code": "phone_missing", "level": "danger", "text": "Inget telefonnummer."})
    elif not normalize_phone(profile.contact_phone):
        out.append({
            "code": "phone_invalid", "level": "warn",
            "text": "Telefonnumret är inte ett svenskt mobilnummer.",
        })
    if not profile.email_verified_at:
        out.append({
            "code": "email_unverified", "level": "info",
            "text": "E-postadressen är inte bekräftad hos oss.",
        })
    return out
