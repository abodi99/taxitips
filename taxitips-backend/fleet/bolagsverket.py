"""
Bolagsverkets API för värdefulla datamängder: namn, adress, form och status
för ett organisationsnummer.

**Varför.** Kunden ska ange så lite som möjligt. Med organisationsnumret hämtas
det registrerade namnet och postadressen härifrån, i stället för att någon
skriver av dem för hand -- och ett bolag som är avregistrerat eller i konkurs
syns innan det får ett prov.

**Vad det INTE bevisar.** Att bolaget finns säger ingenting om att personen som
registrerar sig får företräda det (§7). Profilen börjar fortfarande som
obekräftad; registret gör bara att uppgifterna stämmer.

**Aldrig ett hinder när tjänsten är nere.** Registreringen och säljflödet får
inte stå still för att Bolagsverket inte svarar. `lookup()` kastar
`RegistryUnavailable`, och anroparen faller tillbaka på det användaren skrev.

API:t: OAuth2 client credentials mot `BOLAGSVERKET_TOKEN_URL`, sedan
`POST {BOLAGSVERKET_API_URL}/organisationer` med organisationsnumret.
Gratis och utan avtal; se docs/data-sources.md.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 8
_TOKEN_CACHE_KEY = "bolagsverket:token"
SCOPES = "vardefulla-datamangder:read vardefulla-datamangder:ping"


class RegistryUnavailable(Exception):
    """Ingen konfiguration, eller Bolagsverket svarade inte som väntat."""


def configured() -> bool:
    return bool(
        getattr(settings, "BOLAGSVERKET_CLIENT_ID", "")
        and getattr(settings, "BOLAGSVERKET_CLIENT_SECRET", "")
    )


def _token() -> str:
    """Åtkomsttoken, cachad tills strax innan den går ut."""
    cached = cache.get(_TOKEN_CACHE_KEY)
    if cached:
        return cached
    if not configured():
        raise RegistryUnavailable("BOLAGSVERKET_CLIENT_ID/SECRET saknas.")
    try:
        response = requests.post(
            settings.BOLAGSVERKET_TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": SCOPES},
            auth=(settings.BOLAGSVERKET_CLIENT_ID, settings.BOLAGSVERKET_CLIENT_SECRET),
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RegistryUnavailable(f"Token: {exc.__class__.__name__}") from exc
    if response.status_code != 200:
        raise RegistryUnavailable(f"Token: HTTP {response.status_code}")
    body = response.json()
    token = body.get("access_token") or ""
    if not token:
        raise RegistryUnavailable("Token: inget access_token i svaret")
    ttl = max(60, int(body.get("expires_in") or 300) - 60)
    cache.set(_TOKEN_CACHE_KEY, token, ttl)
    return token


def fetch_raw(org_number: str) -> tuple[int, dict | list | str]:
    """Rått svar från /organisationer. För felsökning och kommandot."""
    token = _token()
    try:
        response = requests.post(
            f"{settings.BOLAGSVERKET_API_URL.rstrip('/')}/organisationer",
            json={"identitetsbeteckning": org_number},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RegistryUnavailable(f"Organisationer: {exc.__class__.__name__}") from exc
    if response.status_code == 401:
        cache.delete(_TOKEN_CACHE_KEY)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text[:2000]


# ---------------------------------------------------------------------------
# Tolkning
# ---------------------------------------------------------------------------

FOUND_TTL = 24 * 3600
# Kortare för "finns inte": ett nyregistrerat bolag ska synas samma dag.
NOT_FOUND_TTL = 3600


@dataclass(frozen=True)
class CompanyInfo:
    """Det registret säger om ett organisationsnummer, i vår form."""

    org_number: str
    found: bool
    name: str = ""
    legal_form: str = ""
    legal_form_code: str = ""
    # active | deregistered | winding_up | inactive
    status: str = ""
    status_text: str = ""
    registered_at: str = ""
    address: dict = field(default_factory=dict)
    sni: list = field(default_factory=list)
    fetched_at: str = ""

    @property
    def blocks_signup(self) -> bool:
        """Ett avregistrerat bolag kan inte teckna ett avtal."""
        return self.found and self.status == "deregistered"

    def as_dict(self) -> dict:
        return {
            "orgNumber": self.org_number, "found": self.found, "name": self.name,
            "legalForm": self.legal_form, "legalFormCode": self.legal_form_code,
            "status": self.status, "statusText": self.status_text,
            "registeredAt": self.registered_at, "address": dict(self.address),
            "sni": list(self.sni), "fetchedAt": self.fetched_at,
            "source": "Bolagsverket",
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CompanyInfo":
        return cls(
            org_number=data.get("orgNumber", ""), found=bool(data.get("found")),
            name=data.get("name", ""), legal_form=data.get("legalForm", ""),
            legal_form_code=data.get("legalFormCode", ""), status=data.get("status", ""),
            status_text=data.get("statusText", ""), registered_at=data.get("registeredAt", ""),
            address=dict(data.get("address") or {}), sni=list(data.get("sni") or []),
            fetched_at=data.get("fetchedAt", ""),
        )


def _has_error(block) -> bool:
    return isinstance(block, dict) and bool(block.get("fel"))


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _postal_code(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return f"{digits[:3]} {digits[3:]}" if len(digits) == 5 else _text(value)


def _city(value: str) -> str:
    """"UPPLANDS VÄSBY" -> "Upplands Väsby". Registret skriver orter i versaler."""
    text = _text(value)
    return text.title() if text.isupper() else text


def parse(org_number: str, body: dict, *, now: str = "") -> CompanyInfo:
    rows = (body or {}).get("organisationer") or []
    if not rows:
        return CompanyInfo(org_number=org_number, found=False, fetched_at=now)
    row = rows[0]

    names_block = row.get("organisationsnamn") or {}
    names = [n for n in (names_block.get("organisationsnamnLista") or []) if n.get("namn")]
    if not names:
        # Svaret har en rad även för ett nummer som inte finns; varje block bär
        # då felet ORGANISATION_FINNS_EJ i stället för data.
        return CompanyInfo(org_number=org_number, found=False, fetched_at=now)
    main = next(
        (n for n in names if (n.get("organisationsnamntyp") or {}).get("kod") == "FORETAGSNAMN"),
        names[0],
    )

    form = row.get("organisationsform") or {}
    if _has_error(form):
        form = row.get("juridiskForm") or {}

    status, status_text = _status(row)

    address = {}
    post_block = row.get("postadressOrganisation") or {}
    post = post_block.get("postadress") or {}
    if post and not _has_error(post_block):
        address = {
            "line1": _text(post.get("utdelningsadress")),
            "line2": f"c/o {_text(post['coAdress'])}" if post.get("coAdress") else "",
            "postal_code": _postal_code(post.get("postnummer")),
            "city": _city(post.get("postort")),
            "country": "SE" if not post.get("land") else _text(post.get("land")),
        }
        address = {k: v for k, v in address.items() if v}

    sni = [
        {"code": _text(s.get("kod")), "text": _text(s.get("klartext"))}
        for s in ((row.get("naringsgrenOrganisation") or {}).get("sni") or [])
        if _text(s.get("kod")) and _text(s.get("kod")) != "00000"
    ]
    dates = row.get("organisationsdatum") or {}
    return CompanyInfo(
        org_number=org_number, found=True, name=_text(main.get("namn")),
        legal_form=_text(form.get("klartext")), legal_form_code=_text(form.get("kod")),
        status=status, status_text=status_text,
        registered_at=_text(dates.get("registreringsdatum")) if not _has_error(dates) else "",
        address=address, sni=sni, fetched_at=now,
    )


def _status(row: dict) -> tuple[str, str]:
    """
    Avregistrerad, under avveckling (konkurs, likvidation, rekonstruktion),
    ej verksam enligt SCB, eller aktiv. I den ordningen -- det allvarligaste
    vinner.
    """
    dereg = row.get("avregistreradOrganisation")
    if isinstance(dereg, dict) and not _has_error(dereg) and dereg.get("avregistreringsdatum"):
        reason = row.get("avregistreringsorsak") or {}
        why = _text(reason.get("klartext")) if isinstance(reason, dict) else ""
        return "deregistered", f"Avregistrerad {dereg['avregistreringsdatum']}" + (f" ({why})" if why else "")

    ongoing = row.get("pagaendeAvvecklingsEllerOmstruktureringsforfarande")
    items = ongoing if isinstance(ongoing, list) else (
        (ongoing.get("pagaendeAvvecklingsEllerOmstruktureringsforfarandeLista") or [ongoing])
        if isinstance(ongoing, dict) and not _has_error(ongoing) else []
    )
    texts = [_text(i.get("klartext")) for i in items if isinstance(i, dict) and i.get("klartext")]
    if texts:
        return "winding_up", "Pågående: " + ", ".join(texts)

    active = row.get("verksamOrganisation") or {}
    if isinstance(active, dict) and not _has_error(active) and active.get("kod") == "NEJ":
        return "inactive", "Registrerat men inte verksamt enligt SCB"
    return "active", "Aktivt"


def _cache_key(org_number: str) -> str:
    # Enskilda firmor har personnumret som organisationsnummer: det ska inte
    # ligga i klartext i Redis.
    return "bolagsverket:org:" + hashlib.sha256(org_number.encode()).hexdigest()[:32]


def lookup(org_number: str, *, refresh: bool = False) -> CompanyInfo:
    """
    Registret för ett (normaliserat, giltigt) svenskt organisationsnummer.

    Cachas ett dygn (en timme för "finns inte"). Kastar `RegistryUnavailable`
    när Bolagsverket inte kan svara -- anroparen avgör vad det betyder.
    """
    key = _cache_key(org_number)
    if not refresh:
        cached = cache.get(key)
        if cached:
            return CompanyInfo.from_dict(cached)

    status, body = fetch_raw(org_number)
    now = timezone.now().isoformat()
    if status in (400, 404):
        info = CompanyInfo(org_number=org_number, found=False, fetched_at=now)
    elif status != 200 or not isinstance(body, dict):
        log.warning("bolagsverket: HTTP %s", status)
        raise RegistryUnavailable(f"Organisationer: HTTP {status}")
    else:
        info = parse(org_number, body, now=now)
    cache.set(key, info.as_dict(), FOUND_TTL if info.found else NOT_FOUND_TTL)
    return info


def try_lookup(org_number: str, *, refresh: bool = False) -> CompanyInfo | None:
    """Som `lookup`, men None när registret inte går att nå. Loggas."""
    if not configured():
        return None
    try:
        return lookup(org_number, refresh=refresh)
    except RegistryUnavailable as exc:
        log.warning("bolagsverket: uppslag misslyckades: %s", exc)
        return None


def client_ip(request) -> str:
    """
    Klientens adress bakom Traefik: den SISTA i X-Forwarded-For, som proxyn
    själv lade till. Den första kan klienten skriva vad den vill i.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


# ---------------------------------------------------------------------------
# Profilen
# ---------------------------------------------------------------------------


def has_address(address: dict | None) -> bool:
    address = address or {}
    return bool(address.get("line1") or address.get("postal_code") or address.get("city"))


def apply_to_profile(profile, info: CompanyInfo, *, overwrite_address: bool = False, now=None) -> list[str]:
    """
    Skriver registrets uppgifter på företagsprofilen. Returnerar vilka fält
    som ändrades, för revisionsloggen.

    * Ögonblicksbilden sparas alltid, även "finns inte" -- då syns det i admin
      att registret faktiskt frågades.
    * Det juridiska namnet är registrets när bolaget finns: det är det som ska
      stå på en faktura.
    * Postadressen fylls bara i om profilen saknar en (eller på begäran): en
      kund kan vilja ha fakturan någon annanstans än till registrerad adress.
    """
    from fleet.models import CompanyProfile

    now = now or timezone.now()
    changed = ["registry"]
    fields = {"registry": info.as_dict(), "registry_checked_at": now}
    if info.found:
        if info.name and info.name != profile.legal_name:
            fields["legal_name"] = info.name
            changed.append("legal_name")
        if info.address and (overwrite_address or not has_address(profile.billing_address)):
            fields["billing_address"] = {"country": "SE", **info.address}
            changed.append("billing_address")
    CompanyProfile.objects.filter(company_id=profile.company_id).update(**fields)
    profile.refresh_from_db()
    return changed


def public_view(info: CompanyInfo) -> dict:
    """
    Det som visas för någon som inte är inloggad: namn, postadress, form och
    status. Samma uppgifter som Bolagsverket själv visar öppet -- inget om
    huruvida bolaget är kund hos TaxiTips. Adressen ingår så att kunden slipper
    skriva av den (enskild firma saknas i registret och får bara skriva namnet).
    """
    address = info.address or {}
    return {
        "found": info.found,
        "name": info.name,
        "city": address.get("city", ""),
        "line1": address.get("line1", ""),
        "line2": address.get("line2", ""),
        "postalCode": address.get("postal_code", ""),
        "legalForm": info.legal_form,
        "status": info.status,
        "statusText": info.status_text,
        "blocksSignup": info.blocks_signup,
    }
