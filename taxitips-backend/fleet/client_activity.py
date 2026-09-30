"""
Klientaktivitet och fel: vad supporten behöver för att felsöka en användare,
och inte mer.

Två saker bokförs:

1. **Senaste läget per konto och per telefon** (`ClientActivity`): senaste
   inloggning, senast sedd, appversion och byggnummer, plattform,
   OS-version, telefonmodell och ett grovt nät (/24) plus land om proxyn
   skickar det. Appen skickar metadatan som headers på varje anrop
   (taxitips-app/lib/client_info.dart); servern läser dem först när
   åtkomstkontrollen vet VEM som frågar -- `note_user()` från
   fleet/accounts.py:seen och `note_device()` från
   fleet/access.py:device_for_token. En header ensam skapar aldrig en rad.

2. **Fel** (`ClientError`): krascher och misslyckade kritiska flöden som
   appen rapporterar till POST /api/client-log (fleet/client_log_api.py), och
   5xx som servern själv svarat med (core/middleware.RequestContextMiddleware).

**Skrivspärr.** Varje verifierad begäran hade annars blivit en skrivning, och
flödet hämtas en gång i minuten per förare. En rad skrivs när något ändrats
(ny version, ny inloggning, annan telefon) eller när tio minuter gått -- samma
avvägning som `accounts.seen`. Spärren ligger i processen OCH i Djangos cache
(Redis i produktion), så att flera Gunicorn-arbetare inte skriver var sin gång.
"Senast sedd" är alltså exakt på tio minuter när, vilket räcker för frågan
"har telefonen varit igång i dag?".

**Tyst vid fel.** Allt här är en bekvämlighet för supporten. En misslyckad
skrivning får aldrig neka en förare tips eller ändra ett svar.

Vad som lagras och varför, och hur länge: docs/loggning.md.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from core import request_context
from core.log_filters import HIDDEN, redact

log = logging.getLogger(__name__)

# Hur ofta samma konto/telefon med oförändrad metadata skrivs.
SEEN_TTL_S = 600
# Felen rensas efter 30 dygn: längre än en supportfråga brukar ta att komma
# in, kortare än att listan blir en historik över användarna.
ERROR_RETENTION_DAYS = 30
# En telefon eller ett konto som inte hörts av på ett halvår är borta; raden
# har inget felsökningsvärde kvar.
ACTIVITY_RETENTION_DAYS = 180
# Samma fel från samma avsändare inom en timme räknas upp på samma rad.
ERROR_DEDUP_S = 3600
# Serverfel per sökväg: en trasig vy som svarar 500 tusen gånger i minuten
# ska inte skriva tusen rader i minuten.
SERVER_ERRORS_PER_PATH = 30
SERVER_ERRORS_WINDOW_S = 600

MESSAGE_MAX = 1000
STACK_MAX = 4000

PLATFORMS = ("android", "ios", "web", "macos", "windows", "linux", "fuchsia")

# ---------------------------------------------------------------------------
# Metadata ur headers
# ---------------------------------------------------------------------------

_PRINTABLE = re.compile(r"[^\x20-\x7e]")
_VERSION = re.compile(r"^[0-9A-Za-z.+\-_]{1,32}$")
_BUILD = re.compile(r"^[0-9A-Za-z.\-_]{1,16}$")


def _clean(value, max_len: int) -> str:
    """Bara skrivbar ASCII, inga radbrytningar, kapad. En header är klientens påstående."""
    text = _PRINTABLE.sub("", str(value or "")).strip()
    return text[:max_len]


def meta_from_request(request) -> dict:
    """
    Appens metadata ur headers, tvättad. Tomma fält för det som saknas eller
    inte ser ut som det ska -- aldrig ett fel.
    """
    headers = getattr(request, "headers", None) or {}
    version = _clean(headers.get("X-App-Version"), 32)
    build = _clean(headers.get("X-App-Build"), 16)
    platform = _clean(headers.get("X-App-Platform"), 16).lower()
    return {
        "app_version": version if _VERSION.match(version) else "",
        "app_build": build if _BUILD.match(build) else "",
        "platform": platform if platform in PLATFORMS else ("other" if platform else ""),
        "os_version": _clean(headers.get("X-OS-Version"), 64),
        "device_model": _clean(headers.get("X-Device-Model"), 64),
    }


def coarse_ip(ip: str) -> str:
    """
    Nätet, inte adressen: /24 för IPv4, /48 för IPv6. Räcker för att se
    "mobilnät eller företagets wifi", och pekar inte ut ett hushåll.
    """
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return ""
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))


def _client_ip(request) -> str:
    from fleet.bolagsverket import client_ip

    try:
        return client_ip(request)
    except Exception:  # noqa: BLE001
        return ""


def _country(request) -> str:
    # Bara om en proxy framför oss redan slagit upp landet (Cloudflare gör
    # det). Vi har ingen GeoIP-databas och ska inte skaffa en för detta.
    value = _clean(request.headers.get("CF-IPCountry"), 2).upper()
    return value if re.fullmatch(r"[A-Z]{2}", value) and value != "XX" else ""


def login_time(payload: dict | None) -> datetime | None:
    """
    När kontot senast faktiskt loggade in, ur den VERIFIERADE JWT:n.

    Supabase lägger inloggningens tidsstämpel i `amr` (`[{"method":
    "password", "timestamp": 1727…}]`) och behåller den när token förnyas.
    `iat` hade varit fel: den ändras varje timme när appen förnyar sessionen.
    """
    best = None
    for entry in (payload or {}).get("amr") or []:
        try:
            ts = int(entry.get("timestamp"))
        except (AttributeError, TypeError, ValueError):
            continue
        if best is None or ts > best:
            best = ts
    if best is None or best <= 0:
        return None
    return datetime.fromtimestamp(best, tz=dt_timezone.utc)


# ---------------------------------------------------------------------------
# Senast sedd
# ---------------------------------------------------------------------------

_local_seen: dict[str, float] = {}
_LOCAL_SEEN_MAX = 20_000


def _throttled(key: str) -> bool:
    """True om samma nyckel redan skrivits inom SEEN_TTL_S."""
    now_s = time.monotonic()
    stamp = _local_seen.get(key)
    if stamp is not None and now_s - stamp < SEEN_TTL_S:
        return True
    if len(_local_seen) > _LOCAL_SEEN_MAX:
        _local_seen.clear()
    _local_seen[key] = now_s
    try:
        # `add` sätter bara om nyckeln saknas: den första processen som ser
        # ändringen skriver, de andra hoppar över.
        return not cache.add(f"fleet:ca:{key}", 1, SEEN_TTL_S)
    except Exception:  # noqa: BLE001 -- utan cache skriver vi hellre än tappar
        return False


def reset_throttle() -> None:
    """För testerna: processens egen spärr (cachen tömmer de själva)."""
    _local_seen.clear()


def note_user(payload: dict | None) -> None:
    """Ett konto med verifierad JWT har anropat servern."""
    user_id = str((payload or {}).get("sub") or "")
    if not user_id:
        return
    request_context.note_user(user_id)
    _touch("user", user_id, last_login=login_time(payload))


def note_device(device) -> None:
    """En förartelefon har visat en giltig token."""
    if device is None:
        return
    request_context.note_device(device.id, getattr(device, "company_id", None))
    _touch("device", str(device.id), company_id=getattr(device, "company_id", None))


def _touch(kind: str, subject_id: str, *, company_id=None, last_login=None) -> None:
    ctx = request_context.current()
    request = getattr(ctx, "request", None)
    if request is None:
        # Utanför en begäran (kommandon, Celery): inget att bokföra.
        return
    try:
        meta = meta_from_request(request)
        fingerprint = hashlib.sha1(
            repr((sorted(meta.items()), last_login.isoformat() if last_login else "")).encode()
        ).hexdigest()[:16]
        if _throttled(f"{kind}:{subject_id}:{fingerprint}"):
            return
        _write_activity(kind, subject_id, meta, request, company_id=company_id, last_login=last_login)
    except Exception:  # noqa: BLE001 -- se modulens docstring
        log.debug("client_activity: kunde inte bokföra %s %s", kind, subject_id, exc_info=True)


def _company_for_user(user_id: str):
    from billing.models import CompanyMember

    return (
        CompanyMember.objects.filter(user_id=user_id, status="active")
        .order_by("created_at")
        .values_list("company_id", flat=True)
        .first()
    )


def _write_activity(kind, subject_id, meta, request, *, company_id=None, last_login=None) -> None:
    from fleet.models import ClientActivity

    now = timezone.now()
    if kind == "user" and company_id is None:
        company_id = _company_for_user(subject_id)
    ip_prefix = coarse_ip(_client_ip(request))
    country = _country(request)

    with transaction.atomic():
        row = ClientActivity.objects.select_for_update().filter(
            subject_kind=kind, subject_id=subject_id,
        ).first()
        if row is None:
            try:
                with transaction.atomic():
                    ClientActivity.objects.create(
                        subject_kind=kind, subject_id=subject_id, company_id=company_id,
                        last_seen_at=now, last_login_at=last_login,
                        ip_prefix=ip_prefix, country=country,
                        **{k: v for k, v in meta.items() if v},
                    )
                return
            except IntegrityError:
                # En annan process hann skapa raden; uppdatera den i stället.
                row = ClientActivity.objects.select_for_update().filter(
                    subject_kind=kind, subject_id=subject_id,
                ).first()
                if row is None:
                    return
        row.last_seen_at = now
        fields = ["last_seen_at"]
        # Bara det som faktiskt skickades skrivs över. Kundportalen och
        # adminwebben skickar inga X-App-*-headers, och ett anrop därifrån
        # får inte sudda ut vilken app ägaren har på telefonen.
        for name, value in meta.items():
            if value and getattr(row, name) != value:
                setattr(row, name, value)
                fields.append(name)
        if last_login and (row.last_login_at is None or last_login > row.last_login_at):
            row.last_login_at = last_login
            fields.append("last_login_at")
        if company_id and str(row.company_id or "") != str(company_id):
            row.company_id = company_id
            fields.append("company_id")
        for name, value in (("ip_prefix", ip_prefix), ("country", country)):
            if value and getattr(row, name) != value:
                setattr(row, name, value)
                fields.append(name)
        row.save(update_fields=fields)


# ---------------------------------------------------------------------------
# Tvätt av feltext
# ---------------------------------------------------------------------------

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

_SCRUB: list[tuple[re.Pattern, str]] = [
    # JWT (Supabase-sessionen): tre base64url-delar, den första alltid "eyJ".
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*"), HIDDEN),
    (re.compile(r"(?i)\bbearer\s+\S+"), f"Bearer {HIDDEN}"),
    # nyckel=värde / "nyckel": "värde" för allt som heter som en hemlighet.
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|device_token|push_token|access_token|"
            r"refresh_token|api_?key|authorization|pairing_?code|join_?code|otp)([\"']?\s*[:=]\s*[\"']?)[^\s\"',}&]+"
        ),
        rf"\1\2{HIDDEN}",
    ),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<e-post>"),
    # Personnummer (också enskild firmas organisationsnummer).
    (re.compile(r"(?<![\w.])(?:19|20)?\d{6}[-+]?\d{4}(?![\w.])"), "<nummer>"),
    # Svenska mobilnummer, med eller utan landsnummer och mellanrum.
    (re.compile(r"(?<![\w.])(?:\+46|0046|0)\s?7\d(?:[\s\-]?\d){7}(?![\w.])"), "<telefon>"),
    # Koordinatpar med minst tre decimaler (appens positioner), och
    # lat/lon-nycklar i alla former.
    (re.compile(r"-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}"), "<position>"),
    (re.compile(r"(?i)\b(lat|lon|lng|latitude|longitude)([\"']?\s*[:=]\s*)-?\d+(?:\.\d+)?"), r"\1\2<position>"),
]

# Långa slumpsträngar (enhetshemligheter, FCM-token, hashar): minst 32 tecken
# med både siffror och bokstäver. UUID:n släpps igenom -- de är id:n, inte
# hemligheter, och det är dem supporten söker på. Kravet på siffror håller
# långa klassnamn i en Dart-stack (RenderFlexOverflowIndicatorPainter) kvar.
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-:]{32,}")


def _long_token(match: re.Match) -> str:
    text = match.group(0)
    if _UUID.match(text):
        return text
    if any(c.isdigit() for c in text) and any(c.isalpha() for c in text):
        return HIDDEN
    return text


def scrub(text, max_len: int) -> str:
    """Feltext utan hemligheter, kontaktuppgifter eller position, kapad."""
    value = str(text or "")
    # Kapa först grovt, så att regexarna aldrig kör på en megabyte.
    value = value[: max_len * 2]
    value = redact(value)
    for pattern, replacement in _SCRUB:
        value = pattern.sub(replacement, value)
    value = _LONG_TOKEN.sub(_long_token, value)
    value = value.replace("\x00", "")
    return value[:max_len]


# ---------------------------------------------------------------------------
# Fel
# ---------------------------------------------------------------------------


def _dedup_key(parts) -> str:
    return "fleet:ce:" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def record_client_error(
    *, request, kind: str, flow: str, message: str, stack: str = "", error_type: str = "",
    fatal: bool = False, http_status=None, reason: str = "", request_id: str = "",
    user_id=None, device_id=None, company_id=None,
):
    """Ett fel från appen. Anroparen har redan kontrollerat avsändaren och gränserna."""
    from fleet.models import ClientError

    meta = meta_from_request(request)
    message = scrub(message, MESSAGE_MAX)
    stack = scrub(stack, STACK_MAX)
    subject = device_id or user_id or f"ip:{coarse_ip(_client_ip(request))}"
    key = _dedup_key(("app", subject, kind, flow, error_type, message[:300]))
    now = timezone.now()
    existing = None
    try:
        existing = cache.get(key)
    except Exception:  # noqa: BLE001
        existing = None
    if existing:
        updated = ClientError.objects.filter(id=existing).update(
            occurrences=F("occurrences") + 1, last_at=now,
        )
        if updated:
            return existing
    row = ClientError.objects.create(
        last_at=now, source=ClientError.Source.APP, kind=kind, flow=flow,
        error_type=error_type, message=message, stack=stack, fatal=bool(fatal),
        http_status=http_status, reason=reason, request_id=request_id,
        path="", company_id=company_id, user_id=user_id, device_id=device_id,
        **meta,
    )
    try:
        cache.set(key, str(row.id), ERROR_DEDUP_S)
    except Exception:  # noqa: BLE001
        pass
    return str(row.id)


def record_server_error(ctx, status: int) -> None:
    """
    Ett 5xx från /api/. Ingen feltext: den står i loggen under samma
    request-id, med stacken. Här räcker vem, var och när.
    """
    from fleet import ratelimit
    from fleet.models import ClientError

    path = (ctx.path or "")[:200]
    # Id:n i sökvägen (/api/opportunities/<uuid>) skulle ge en rad per tips.
    flow = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F\-]{27}", "<id>", path)[:64]
    allowed, _count = ratelimit.hit(
        ratelimit.Limit("server_error", SERVER_ERRORS_PER_PATH, SERVER_ERRORS_WINDOW_S), flow,
    )
    if not allowed:
        return
    request = ctx.request
    meta = meta_from_request(request) if request is not None else {}
    try:
        ClientError.objects.create(
            last_at=timezone.now(), source=ClientError.Source.SERVER, kind=ClientError.Kind.SERVER,
            flow=flow, message=f"HTTP {status} – se loggen under req={ctx.request_id}",
            http_status=status, request_id=ctx.request_id, path=path,
            company_id=ctx.company_id or None, user_id=ctx.user_id or None,
            device_id=ctx.device_id or None, **meta,
        )
    except Exception:  # noqa: BLE001 -- databasen kan vara själva felet
        log.warning("client_activity: kunde inte bokföra serverfel för %s", path, exc_info=True)


def purge(now=None) -> dict[str, int]:
    """Gallringen. Körs av `manage.py purge_old` (schemalagd varje timme)."""
    from fleet.models import ClientActivity, ClientError

    now = now or timezone.now()
    errors, _ = ClientError.objects.filter(
        last_at__lt=now - timedelta(days=ERROR_RETENTION_DAYS)
    ).delete()
    activity, _ = ClientActivity.objects.filter(
        last_seen_at__lt=now - timedelta(days=ACTIVITY_RETENTION_DAYS)
    ).delete()
    return {"client_errors": errors, "client_activity": activity}
