"""
Django settings för TaxiTips backend.

Databearbetning -- hämta, klassificera, poängsätta, skriva -- plus admin
för att se resultatet, plus (sedan Spår B påbörjades) en egen Stripe-
webhook och FCM-push via Celery, se billing/-appen. "Ingen DRF" gäller
fortfarande: det finns inget publikt REST-API här, bara den ena
webhook-vyn och pipeline-vyn.
"""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    """
    Minimal .env-läsare. Inget beroende på python-dotenv för fyra rader
    konfiguration -- och den här varianten är läsbar utan att slå upp ett
    biblioteks beteende kring citattecken och kommentarer.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(BASE_DIR / ".env")

# Dev-standard. Sätts från miljön i Coolify.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-a-secret")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

# Ingen publik exponering ännu -- tjänsten pratar bara med databasen och
# externa API:er. Vidgas när/om Spår B (app-API) byggs.
ALLOWED_HOSTS = ["*"] if DEBUG else os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    # admin kräver auth + contenttypes + sessions. Det är inte en
    # säkerhetsdesign, bara admins beroenden -- inloggningen till appen
    # sköts fortfarande av Supabase.
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Före allt annat: en preflight ska besvaras, inte autentiseras eller
    # ruttas. Se core/middleware.py.
    "core.middleware.CorsPreflightMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


def database_from_url(url: str) -> dict:
    """
    postgresql://user:pass@host:port/name -> Djangos DATABASES-dict.

    Skrivet för hand i stället för dj-database-url: en URL-form, ingen
    anledning till ett beroende, och felmeddelandet blir vårt eget.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise ValueError(f"DATABASE_URL måste vara postgresql://, fick {parsed.scheme!r}")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/") or "postgres",
        "USER": parsed.username or "postgres",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "127.0.0.1",
        "PORT": str(parsed.port or 5432),
    }


# En databas: den Postgres `supabase start` kör. Django äger pipeline-tabellerna
# (source_events, opportunities, scoring_rule, ...) via sina egna migrationer;
# Supabases SQL-migrationer äger domäntabellerna (companies, devices, profiles,
# ...), som billing-appen når via managed=False-modeller. Ingen tabell beskrivs
# på två ställen.
#
# Tidigare fanns ett andra alias mot en egen Django-container. Det behövs inte
# längre -- och det var det som gjorde att allt pipelinen räknade ut hamnade i
# en databas ingen förare läste från.
_database = database_from_url(
    os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    )
)
if Path("/.dockerenv").exists() and _database["HOST"] in ("127.0.0.1", "localhost"):
    _database["HOST"] = "host.docker.internal"

DATABASES = {"default": _database}

LANGUAGE_CODE = "sv"
TIME_ZONE = "Europe/Stockholm"
USE_I18N = True
# Allt i pipelinen resonerar i UTC (källorna levererar tidszonade
# tidsstämplar); TIME_ZONE ovan styr bara hur admin visar dem.
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Datakällor -----------------------------------------------------------
# Samma nycklar som Node-workern använder. TRAFIKVERKET_API_KEY gäller både
# väg och järnväg -- ett konto, två produkter.
TRAFIKVERKET_API_KEY = os.environ.get("TRAFIKVERKET_API_KEY", "")
TRAFIKLAB_API_KEY = os.environ.get("TRAFIKLAB_API_KEY", "")
VASTTRAFIK_CLIENT_ID = os.environ.get("VASTTRAFIK_CLIENT_ID", "")
VASTTRAFIK_CLIENT_SECRET = os.environ.get("VASTTRAFIK_CLIENT_SECRET", "")
# Vilka Trafiklab-operatörer som pollas, och vilken marknad som räknas som
# "hemma" -- läses av core/market.py och core/sources/trafiklab.py. Samma
# namn och default som Node-workern, så en befintlig .env fungerar oförändrat.
TRAFIKLAB_OPERATORS = os.environ.get("TRAFIKLAB_OPERATORS", "skane")
# Vilka län Trafikverkets vägdata hämtas för. "all" = alla 21. Samma namn
# och default som Node-workern.
TRAFIKVERKET_COUNTIES = os.environ.get("TRAFIKVERKET_COUNTIES", "skane")
MARKET_SCOPE = os.environ.get("MARKET_SCOPE", "skane")

# --- Celery -----------------------------------------------------------
# CELERY_TASK_ALWAYS_EAGER: satt av testkörning (se Jenkinsfile och README)
# så `manage.py test` aldrig behöver en levande Redis/broker -- samma
# env-flagga-i-en-fil-mönster som DJANGO_DEBUG ovan, ingen ny settings-modul.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"
CELERY_TASK_EAGER_PROPAGATES = CELERY_TASK_ALWAYS_EAGER

# Mappad 1:1 från run_pipeline.pys POLL_INTERVAL_SECONDS/SITES_REFRESH_SECONDS/
# REVIEW_INTERVAL_SECONDS -- se core/tasks.py. Heltalsintervall, inte crontab,
# för att matcha time.monotonic()s "N sekunder sedan senaste körning" exakt.
CELERY_BEAT_SCHEDULE = {
    "poll-rail": {"task": "core.tasks.poll_rail_task", "schedule": 90},
    "poll-road": {"task": "core.tasks.poll_road_task", "schedule": 90},
    "poll-trafiklab": {"task": "core.tasks.poll_trafiklab_task", "schedule": 90},
    "poll-sl": {"task": "core.tasks.poll_sl_task", "schedule": 90},
    "poll-vasttrafik": {"task": "core.tasks.poll_vasttrafik_task", "schedule": 90},
    "refresh-sites": {"task": "core.tasks.refresh_sites_task", "schedule": 24 * 60 * 60},
    "review-uncertain": {"task": "core.tasks.review_uncertain_task", "schedule": 5 * 60},
    # Tätare än pollningen med avsikt: en notis som väntar in nästa pollvarv
    # lägger upp till 90 sekunder till den fördröjning källan redan har, och
    # en störning är som mest värd att köra till i sin första kvart.
    # Cykeln är billig när det inte finns något att skicka -- en indexerad
    # fråga på notified_at is null som normalt ger noll rader.
    "push-cycle": {"task": "core.tasks.push_cycle_task", "schedule": 30},
}

# --- Förar-API (Spår B, core/api.py) -----------------------------------
# Supabases JWT-hemlighet: används BARA för att verifiera en inloggad
# ägares access token (core/entitlement.py). Utan den fungerar förarens
# token-väg som vanligt, men en inloggad ägare utan parad enhet får tomt
# flöde -- samma bugg som 20260902000005 rättade i SQL-versionen.
# Varifrån JWKS hämtas när Supabase signerar asymmetriskt (ES256), vilket
# moderna projekt och en lokal `supabase start` gör som standard.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "http://127.0.0.1:54321")
if Path("/.dockerenv").exists():
    SUPABASE_URL = SUPABASE_URL.replace(
        "127.0.0.1", "host.docker.internal"
    ).replace("localhost", "host.docker.internal")
SUPABASE_JWT_SECRET = os.environ.get(
    "SUPABASE_JWT_SECRET", "super-secret-jwt-token-with-at-least-32-characters-long"
) if DEBUG else os.environ.get("SUPABASE_JWT_SECRET", "")
# Inget "*": svaren är entitlement-gated data. Flutter web och
# visualiseraren listas explicit.
APP_API_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "APP_API_ALLOWED_ORIGINS",
        # 4000 = pipeline-visualiseraren, 5173 = `flutter run -d chrome
        # --web-port 5173`. Inte 5000: macOS AirPlay Receiver sitter där.
        # Flutter web är den enda klienten som omfattas av CORS alls --
        # mobilappen skickar ingen Origin.
        "http://localhost:4000,http://127.0.0.1:4000,"
        "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]

# --- Stripe / FCM (billing-appen) --------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
# Samma variabelnamn som taxitips-api/worker/src/fcmPush.js, för kontinuitet
# -- samma Firebase-projekt backar båda tjänsterna.
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
