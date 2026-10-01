"""
Adminwebbens statussida: fungerar varje koppling just nu?

`/health` svarar bara på om webbprocessen når databasen, och `/health/pipeline`
på om kärnkällorna hämtar. Ingen av dem säger om Stripe tar emot anrop, om
Bolagsverkets nyckel gått ut, om Firebase-kontot fortfarande kan skicka push
eller om SMTP-lösenordet bytts -- fel som annars syns först när en kund
klagar. Den här sidan samlar allt på ett ställe.

Tre sorters kontroller:

1. **Grunden** -- databas, cache, Celery-kön, beat-hjärtslaget och Supabase
   Auth. Läses eller anropas direkt.
2. **Datakällorna** -- LÄSES ur `SourceStatus`, anropas aldrig härifrån.
   Trafiklab och Swedavia har kvoter, och en statussida som bränner kvot varje
   gång någon tittar på den är själv ett driftfel. Senaste lyckade hämtning är
   dessutom det ärligare svaret: nyckeln kan svara på en testfråga och ändå
   misslyckas i den riktiga hämtningen.
3. **Externa tjänster** -- Stripe, Bolagsverket, Firebase och SMTP anropas
   live, men bara med ofarliga läsanrop: hämta en produkt, `isalive`, byta
   nyckeln mot en OAuth-token, logga in och ut. Ingenting skickas, debiteras
   eller skrivs. Anropen körs parallellt med egna tidsgränser, och svaret
   cachas kort så att en sida som laddas om inte hamrar tjänsterna.

Nivåerna: `ok`, `warn` (fungerar men något behöver tittas på), `down` (fungerar
inte) och `off` (inte konfigurerad -- ett medvetet läge, inget fel).

Inga hemligheter ut. Källornas felmeddelanden kan innehålla anrops-URL:er med
nyckeln i frågesträngen; de tvättas i `_redact` innan de lämnar servern.
"""

from __future__ import annotations

import re
import smtplib
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import timedelta

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.db.models import Count, Min
from django.utils import timezone
from django.views.decorators.http import require_GET

from core import thresholds
from core.api import _json
from fleet.admin_api import _staff, handle
from fleet.roles import Perm

OK, WARN, DOWN, OFF = "ok", "warn", "down", "off"
_RANK = {OK: 0, OFF: 0, WARN: 1, DOWN: 2}

CACHE_KEY = "admin:status"
CACHE_SECONDS = 30
HTTP_TIMEOUT = 6
# Hela sidan väntar aldrig längre än så här på en tjänst som hänger.
PROBE_DEADLINE = 12

SOURCE_LABEL = {
    "trafikverket_rail": "Trafikverket järnväg",
    "trafikverket": "Trafikverket väg",
    "trafiklab": "Trafiklab GTFS-RT",
    "sl": "SL",
    "vt": "Västtrafik",
    "smhi": "SMHI väder",
    "swedavia": "Swedavia flyg",
    "aisstream": "AISStream färjor",
    "ticketmaster": "Ticketmaster evenemang",
    "predicthq": "PredictHQ evenemang",
    "thesportsdb": "TheSportsDB sport",
    "api_sports": "API-Sports (fotboll, ishockey, handboll)",
    "aisstream_pilot": "AISStream färjepilot",
    "gtfs_sweden3_ferries": "Trafiklab GTFS Sverige 3 (färjor)",
}

# Källan hämtar ingenting utan den här inställningen. SL och SMHI är öppna.
SOURCE_SETTING = {
    "trafikverket_rail": "TRAFIKVERKET_API_KEY",
    "trafikverket": "TRAFIKVERKET_API_KEY",
    "trafiklab": "TRAFIKLAB_API_KEY",
    "vt": "VASTTRAFIK_CLIENT_ID",
    "swedavia": "SWEDAVIA_API_KEY",
    "aisstream": "AISSTREAM_API_KEY",
    "ticketmaster": "TICKETMASTER_API_KEY",
    "predicthq": "PREDICTHQ_ACCESS_TOKEN",
}

_SECRET_PARAM = re.compile(
    r"(?i)(?<![a-z])((?:api[_-]?key|key|token|access_token|secret|password|authenticationkey|subscription-key)"
    r"[=:]\s*)[^&\s\"',]+"
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")


def _redact(text) -> str:
    text = str(text or "")
    return _BEARER.sub(r"\1***", _SECRET_PARAM.sub(r"\1***", text))[:300]


def _check(key, label, status, summary, *, detail=None, latency_ms=None, since=None):
    return {
        "key": key,
        "label": label,
        "status": status,
        "summary": summary,
        "detail": detail or [],
        "latencyMs": latency_ms,
        "since": since.isoformat() if since else None,
    }


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _ago(minutes: int | None) -> str:
    if minutes is None:
        return "aldrig"
    if minutes < 1:
        return "nyss"
    if minutes < 90:
        return f"för {minutes} min sedan"
    if minutes < 48 * 60:
        return f"för {minutes // 60} h sedan"
    return f"för {minutes // (24 * 60)} dygn sedan"


# ---------------------------------------------------------------------------
# Grunden (läses i anropets egen tråd: databasen hör till den)
# ---------------------------------------------------------------------------


def _database():
    started = time.monotonic()
    try:
        with connection.cursor() as cur:
            cur.execute("select 1")
            cur.fetchone()
    except Exception as exc:
        return _check("database", "Databas (Postgres)", DOWN, f"Svarar inte: {type(exc).__name__}")
    ms = _ms(started)
    host = settings.DATABASES["default"].get("HOST") or "lokal"
    status = OK if ms < 500 else WARN
    return _check(
        "database", "Databas (Postgres)", status,
        f"Svarar på {ms} ms" + ("" if status == OK else " -- långsamt"),
        detail=[f"Värd: {host}"], latency_ms=ms,
    )


def _cache():
    backend = settings.CACHES["default"]["BACKEND"].rsplit(".", 1)[-1]
    name = "Redis" if "Redis" in backend else "processens minne"
    probe = f"admin:status:probe:{time.monotonic_ns()}"
    started = time.monotonic()
    try:
        cache.set(probe, "1", 10)
        got = cache.get(probe)
        cache.delete(probe)
    except Exception as exc:
        return _check("cache", "Cache", DOWN, f"{name}: {type(exc).__name__}")
    if got != "1":
        return _check("cache", "Cache", DOWN, f"{name}: skrev men kunde inte läsa tillbaka")
    return _check("cache", "Cache", OK, f"{name}, {_ms(started)} ms", latency_ms=_ms(started))


def _heartbeat(statuses, now):
    label = "Schemaläggaren (Celery beat + worker)"
    beat = statuses.get(thresholds.HEARTBEAT_SOURCE)
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return _check("beat", label, OFF, "Körs i webbprocessen (CELERY_TASK_ALWAYS_EAGER=1)")
    if beat is None:
        return _check("beat", label, DOWN, "Inget hjärtslag har registrerats -- beat eller worker körs inte")
    age = int((now - beat.checked_at).total_seconds())
    worker = (beat.detail or {}).get("worker") or ""
    detail = [f"Worker: {worker}"] if worker else []
    if age > thresholds.HEARTBEAT_MAX_AGE_SECONDS:
        return _check(
            "beat", label, DOWN,
            f"Senaste hjärtslag {_ago(age // 60)} -- inga källor uppdateras",
            detail=detail, since=beat.checked_at,
        )
    return _check("beat", label, OK, f"Hjärtslag för {age} s sedan", detail=detail, since=beat.checked_at)


def _broker():
    label = "Kön (Redis för Celery)"
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return _check("broker", label, OFF, "Ingen kö -- uppgifterna körs direkt (EAGER)")
    url = getattr(settings, "CELERY_BROKER_URL", "") or ""
    if not url.startswith(("redis://", "rediss://")):
        return _check("broker", label, OFF, "Ingen Redis-kö konfigurerad")
    import redis

    started = time.monotonic()
    try:
        client = redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
        client.ping()
        queued = client.llen("celery")
    except Exception as exc:
        return _check("broker", label, DOWN, f"Svarar inte: {type(exc).__name__}")
    ms = _ms(started)
    status = OK if queued < 500 else WARN
    return _check(
        "broker", label, status,
        f"{queued} uppgifter väntar i kön" + ("" if status == OK else " -- workern hinner inte med"),
        latency_ms=ms,
    )


def _supabase_auth():
    label = "Supabase Auth (inloggning)"
    url = str(getattr(settings, "SUPABASE_URL", "") or "").rstrip("/")
    if not url:
        return _check("supabase_auth", label, OFF, "SUPABASE_URL saknas")
    started = time.monotonic()
    try:
        res = requests.get(f"{url}/auth/v1/.well-known/jwks.json", timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        return _check("supabase_auth", label, DOWN, f"Svarar inte: {type(exc).__name__}")
    ms = _ms(started)
    if res.status_code != 200:
        return _check("supabase_auth", label, DOWN, f"HTTP {res.status_code} från JWKS", latency_ms=ms)
    try:
        keys = res.json().get("keys") or []
    except ValueError:
        keys = []
    if keys:
        return _check("supabase_auth", label, OK, f"Svarar, {len(keys)} signeringsnyckel(ar)", latency_ms=ms)
    if getattr(settings, "SUPABASE_JWT_SECRET", ""):
        return _check("supabase_auth", label, OK, "Svarar (HS256-hemligheten används)", latency_ms=ms)
    return _check(
        "supabase_auth", label, WARN,
        "Svarar, men varken nycklar eller SUPABASE_JWT_SECRET -- inloggade ägare nekas", latency_ms=ms,
    )


# ---------------------------------------------------------------------------
# Datakällorna (bara lästa ur SourceStatus -- se modulens docstring)
# ---------------------------------------------------------------------------


def _sources(statuses, now) -> list[dict]:
    names = list(thresholds.SOURCE_MAX_AGE_MINUTES)
    names += sorted(
        s for s in statuses if s not in thresholds.SOURCE_MAX_AGE_MINUTES and s != thresholds.HEARTBEAT_SOURCE
    )
    # Lokal/dev med EAGER: beat körs inte, så gamla SourceStatus-rader är
    # inte ett produktionshaveri -- visa Av i stället för Nere.
    polling_idle = bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False))
    out = []
    for source in names:
        label = SOURCE_LABEL.get(source, source)
        row = statuses.get(source)
        core = source in thresholds.CORE_SOURCES
        max_age = thresholds.SOURCE_MAX_AGE_MINUTES.get(source)
        setting = SOURCE_SETTING.get(source)
        if setting and not getattr(settings, setting, ""):
            out.append(_check(source, label, OFF, f"{setting} saknas -- hämtas inte"))
            continue
        if row is None:
            if polling_idle:
                out.append(_check(
                    source, label, OFF,
                    "Hämtas inte här (CELERY_TASK_ALWAYS_EAGER) -- kör poll_*/worker lokalt om du vill",
                ))
            else:
                out.append(_check(
                    source, label, DOWN if core else WARN, "Har aldrig hämtats i den här miljön",
                ))
            continue

        last = row.last_success_at
        age = int((now - last).total_seconds() // 60) if last else None
        stale = max_age is not None and (age is None or age > max_age)
        detail = []
        if max_age is not None:
            detail.append(f"Ska ha lyckats inom {max_age} min" + (" (kärnkälla)" if core else ""))
        else:
            detail.append("Ingen färskhetsgräns satt (core/thresholds.py) -- bedöms bara på senaste försöket")
        detail.append(f"Senaste försök {_ago(int((now - row.checked_at).total_seconds() // 60))}: "
                      f"{row.events} händelser, {row.written} tips, {row.duration_ms} ms")
        if row.consecutive_failures:
            detail.append(f"{row.consecutive_failures} misslyckade försök i rad")
        if not row.ok and row.message:
            detail.append(f"Fel: {_redact(row.message)}")
        parts = row.detail if isinstance(row.detail, dict) else {}
        failing = [
            f"{name}: {_redact(part.get('error') or 'fel')}"
            for name, part in parts.items() if isinstance(part, dict) and part.get("ok") is False
        ]
        if failing:
            detail.append(f"{len(failing)} av {len(parts)} delkällor fallerar")
            detail.extend(failing[:8])

        if polling_idle and stale:
            status = OFF
            summary = (
                f"Pollas inte här (EAGER) -- senaste lyckade {_ago(age)}"
                if age is not None else "Pollas inte här (CELERY_TASK_ALWAYS_EAGER)"
            )
            detail.append("I lokal utveckling räknas inte gamla hämtningar som haveri")
        elif last is None and max_age is None:
            status = OFF if row.ok else WARN
            summary = "Ingen lyckad hämtning ännu"
        elif stale:
            status = DOWN if core else WARN
            summary = f"Senaste lyckade hämtning {_ago(age)}"
        elif not row.ok:
            status = WARN
            summary = f"Senaste försöket misslyckades, senast lyckad {_ago(age)}"
        elif failing:
            status = WARN
            summary = f"Hämtar, men {len(failing)} delkälla(or) fallerar"
        else:
            status = OK
            summary = f"Hämtade {_ago(age)}"
        out.append(_check(source, label, status, summary, detail=detail, since=last))
    return out


# ---------------------------------------------------------------------------
# Externa tjänster (anropas live, parallellt)
# ---------------------------------------------------------------------------


def _stripe():
    label = "Stripe (betalning)"
    key = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    if not key:
        return _check("stripe", label, OFF, "STRIPE_SECRET_KEY saknas")
    import stripe

    live = key.startswith(("sk_live_", "rk_live_"))
    mode = "Livenyckel" if live else "Testnyckel"
    detail = [mode]
    if live and str(getattr(settings, "STRIPE_ALLOW_LIVE", "")) != "1":
        detail.append("STRIPE_ALLOW_LIVE är inte 1 -- appen vägrar röra abonnemang")
    if not getattr(settings, "STRIPE_WEBHOOK_SECRET", ""):
        detail.append("STRIPE_WEBHOOK_SECRET saknas -- webhooks kan inte verifieras")
    if not getattr(settings, "STRIPE_VAT_TAX_RATE_ID", ""):
        detail.append("STRIPE_VAT_TAX_RATE_ID saknas -- fakturor utan moms")

    client = stripe.StripeClient(
        key, http_client=stripe.RequestsClient(timeout=HTTP_TIMEOUT), max_network_retries=0
    )
    product_id = getattr(settings, "STRIPE_PRODUCT_ID", "") or ""
    started = time.monotonic()
    try:
        if product_id:
            product = client.products.retrieve(product_id)
            detail.append(f"Produkt: {product.name}" + ("" if product.active else " (INAKTIV)"))
            product_ok = bool(product.active)
        else:
            client.products.list(params={"limit": 1})
            detail.append("STRIPE_PRODUCT_ID saknas")
            product_ok = False
    except stripe.AuthenticationError:
        return _check("stripe", label, DOWN, "Nyckeln avvisas av Stripe", detail=detail)
    except stripe.InvalidRequestError as exc:
        return _check("stripe", label, DOWN, f"Anropet avvisades: {_redact(exc.user_message or exc)}", detail=detail)
    except Exception as exc:
        return _check("stripe", label, DOWN, f"Svarar inte: {type(exc).__name__}", detail=detail)
    ms = _ms(started)
    warn = not product_ok or len(detail) > 2
    return _check(
        "stripe", label, WARN if warn else OK,
        f"Svarar ({mode.lower()})" + (" -- se detaljer" if warn else ""),
        detail=detail, latency_ms=ms,
    )


def _bolagsverket():
    from fleet import bolagsverket

    label = "Bolagsverket (företagsregistret)"
    if not bolagsverket.configured():
        return _check("bolagsverket", label, OFF, "BOLAGSVERKET_CLIENT_ID/SECRET saknas")
    started = time.monotonic()
    try:
        token = bolagsverket._token()
    except bolagsverket.RegistryUnavailable as exc:
        return _check("bolagsverket", label, DOWN, f"Ingen token: {_redact(exc)}")
    try:
        res = requests.get(
            f"{settings.BOLAGSVERKET_API_URL.rstrip('/')}/isalive",
            headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        return _check("bolagsverket", label, DOWN, f"API:t svarar inte: {type(exc).__name__}")
    ms = _ms(started)
    if res.status_code == 200:
        return _check("bolagsverket", label, OK, f"Token och API svarar ({ms} ms)", latency_ms=ms)
    if res.status_code in (401, 403):
        cache.delete(bolagsverket._TOKEN_CACHE_KEY)
        return _check("bolagsverket", label, DOWN, f"API:t avvisar token (HTTP {res.status_code})", latency_ms=ms)
    return _check(
        "bolagsverket", label, WARN,
        f"Token fungerar, men isalive gav HTTP {res.status_code}", latency_ms=ms,
    )


def _firebase():
    from billing import fcm

    label = "Firebase (push-notiser)"
    raw = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "") or ""
    if not raw:
        return _check("firebase", label, OFF, "FIREBASE_SERVICE_ACCOUNT_JSON saknas -- ingen push skickas")
    info = fcm.load_service_account(raw)
    if not info:
        return _check("firebase", label, DOWN, "Tjänstekontot går inte att läsa (varken JSON eller base64)")
    started = time.monotonic()
    try:
        fcm.get_access_token(info)
    except Exception as exc:
        return _check(
            "firebase", label, DOWN, f"Google avvisar tjänstekontot: {type(exc).__name__}",
            detail=[f"Projekt: {info.get('project_id')}"],
        )
    ms = _ms(started)
    return _check(
        "firebase", label, OK, f"Tjänstekontot godkänt ({ms} ms)",
        detail=[f"Projekt: {info.get('project_id')}"], latency_ms=ms,
    )


def _smtp():
    from fleet import mailer

    label = "E-post (SMTP)"
    # `fleet.mailer.send` är SMTP-avsändaren uttryckligen utpekad (så står det i prod).
    sender = getattr(settings, "FLEET_OUTBOX_SENDER", "") or ""
    if sender and sender != "fleet.mailer.send":
        return _check("smtp", label, OFF, f"Annan avsändare: {sender}")
    if not mailer.configured():
        return _check("smtp", label, OFF, "FLEET_SMTP_USER/PASSWORD saknas -- utkorgen ligger kvar")
    host = settings.FLEET_SMTP_HOST
    port = int(settings.FLEET_SMTP_PORT or 465)
    started = time.monotonic()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=HTTP_TIMEOUT)
        else:
            server = smtplib.SMTP(host, port, timeout=HTTP_TIMEOUT)
            server.starttls()
        try:
            server.login(settings.FLEET_SMTP_USER, settings.FLEET_SMTP_PASSWORD)
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except smtplib.SMTPAuthenticationError:
        return _check("smtp", label, DOWN, "Inloggningen avvisas -- lösenordet stämmer inte")
    except Exception as exc:
        return _check("smtp", label, DOWN, f"{host}:{port} svarar inte: {type(exc).__name__}")
    ms = _ms(started)
    return _check(
        "smtp", label, OK, f"Inloggning godkänd ({ms} ms)",
        detail=[f"{host}:{port} som {settings.FLEET_SMTP_USER}"], latency_ms=ms,
    )


PROBES = {
    "supabase_auth": _supabase_auth,
    "broker": _broker,
    "stripe": _stripe,
    "bolagsverket": _bolagsverket,
    "firebase": _firebase,
    "smtp": _smtp,
}


def _run_probes(probes: dict) -> dict:
    """Alla nätverksanrop parallellt. En tjänst som hänger får bara sin egen rad röd."""
    pool = ThreadPoolExecutor(max_workers=len(probes) or 1, thread_name_prefix="admin-status")
    futures = {key: pool.submit(fn) for key, fn in probes.items()}
    wait(futures.values(), timeout=PROBE_DEADLINE)
    pool.shutdown(wait=False, cancel_futures=True)
    out = {}
    for key, future in futures.items():
        if not future.done():
            out[key] = _check(key, key, DOWN, f"Svarade inte inom {PROBE_DEADLINE} s")
            continue
        try:
            out[key] = future.result()
        except Exception as exc:  # en trasig kontroll ska inte fälla sidan
            out[key] = _check(key, key, DOWN, f"Kontrollen kraschade: {type(exc).__name__}")
    return out


# ---------------------------------------------------------------------------
# Flödena genom tjänsterna (databasen: vad har faktiskt hänt senaste dygnet?)
# ---------------------------------------------------------------------------


def _webhook_detail(now) -> tuple[list[str], bool]:
    from billing.models import ProcessedWebhookEvent

    last = ProcessedWebhookEvent.objects.order_by("-processed_at").first()
    errors = ProcessedWebhookEvent.objects.filter(
        processed_at__gte=now - timedelta(hours=24)
    ).filter(status="error").count()
    lines = [f"Senaste webhook: {_ago(int((now - last.processed_at).total_seconds() // 60)) if last else 'aldrig'}"]
    if errors:
        lines.append(f"{errors} webhook(s) misslyckades senaste dygnet")
    return lines, errors > 0


def _push_detail(now) -> tuple[list[str], bool]:
    from core.models import PushDelivery

    rows = dict(
        PushDelivery.objects.filter(created_at__gte=now - timedelta(hours=24))
        .values_list("status").annotate(n=Count("id"))
    )
    sent, failed = rows.get("sent", 0), rows.get("failed", 0)
    lines = [f"Senaste dygnet: {sent} skickade, {failed} misslyckade, "
             f"{rows.get('suppressed', 0)} undertryckta"]
    return lines, failed >= 5 and failed > sent / 4


def _outbox_detail(now) -> tuple[list[str], bool]:
    from fleet.models import OutboxMessage

    pending = OutboxMessage.objects.filter(status=OutboxMessage.Status.PENDING)
    oldest = pending.aggregate(m=Min("created_at"))["m"]
    failed = OutboxMessage.objects.filter(
        status=OutboxMessage.Status.FAILED, created_at__gte=now - timedelta(hours=24)
    ).count()
    lines = [f"Utkorgen: {pending.count()} väntar, {failed} misslyckade senaste dygnet"]
    stuck = bool(oldest and now - oldest > timedelta(minutes=30))
    if stuck:
        lines.append(f"Äldsta väntande mejl köades {_ago(int((now - oldest).total_seconds() // 60))}")
    return lines, stuck or failed > 0


def _safely(fn, now, what: str):
    """
    En egen savepoint per fråga: en saknad tabell (webhookloggen finns bara där
    Supabase-migrationerna körts) ska bli en rad text, inte avbryta transaktionen
    för resten av sidan.
    """
    try:
        with transaction.atomic():
            return fn(now)
    except Exception as exc:
        return [f"{what} gick inte att läsa: {type(exc).__name__}"], False


def _worsen(check: dict, lines: list[str], problem: bool, why: str) -> None:
    check["detail"] = check["detail"] + lines
    if problem and check["status"] == OK:
        check["status"] = WARN
        check["summary"] = f"{check['summary']} -- {why}"


# ---------------------------------------------------------------------------
# Endpointen
# ---------------------------------------------------------------------------


def build_report(now=None) -> dict:
    from core.models import SourceStatus

    now = now or timezone.now()
    live = _run_probes(PROBES)

    db = _database()
    statuses = {}
    sources = []
    if db["status"] != DOWN:
        statuses = {s.source: s for s in SourceStatus.objects.all()}
        sources = _sources(statuses, now)

    stripe_check, firebase_check, smtp_check = live["stripe"], live["firebase"], live["smtp"]
    if db["status"] != DOWN:
        _worsen(stripe_check, *_safely(_webhook_detail, now, "Webhookloggen"), "webhooks misslyckas")
        _worsen(firebase_check, *_safely(_push_detail, now, "Notisloggen"), "många misslyckade notiser")
        _worsen(smtp_check, *_safely(_outbox_detail, now, "Utkorgen"), "utkorgen har problem")

    groups = [
        {"key": "grund", "title": "Grunden", "checks": [
            _check("web", "Backend (Django)", OK, "Svarar -- annars hade sidan inte laddat"),
            db, _cache(), live["broker"],
            _heartbeat(statuses, now) if db["status"] != DOWN
            else _check("beat", "Schemaläggaren (Celery beat + worker)", DOWN, "Okänt -- databasen svarar inte"),
            live["supabase_auth"],
        ]},
        {"key": "tjanster", "title": "Externa tjänster", "checks": [
            stripe_check, live["bolagsverket"], firebase_check, smtp_check,
        ]},
        {"key": "kallor", "title": "Datakällor", "checks": sources},
    ]
    worst = max((_RANK[c["status"]] for g in groups for c in g["checks"]), default=0)
    counts = {}
    for g in groups:
        for c in g["checks"]:
            counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {
        "ok": True,
        "overall": {0: OK, 1: WARN, 2: DOWN}[worst],
        "counts": counts,
        "groups": groups,
        "environment": "utveckling" if settings.DEBUG else "produktion",
        "checkedAt": now.isoformat(),
    }


@require_GET
@handle
def status(request):
    """
    GET /api/admin/status -- varje koppling, grön/gul/röd. `?fresh=1` kör om
    kontrollerna direkt; annars återanvänds ett svar som är högst 30 s gammalt.
    """
    _staff(request, Perm.ADMIN_VIEW)
    report = None
    if request.GET.get("fresh") != "1":
        try:
            report = cache.get(CACHE_KEY)
        except Exception:  # en trasig cache visas som en röd rad, inte som ett 500
            report = None
    if report is None:
        report = build_report()
        try:
            cache.set(CACHE_KEY, report, CACHE_SECONDS)
        except Exception:
            pass
    response = _json(request, report)
    response["Cache-Control"] = "no-store"
    return response
