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
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # setdefault hoppar över om nyckeln redan finns — även när den är
        # tom sträng (vanligt när skalet exporterat FIREBASE_…=). En tom
        # processmiljö ska inte vinna över en ifylld .env.
        if key not in os.environ or not os.environ.get(key):
            os.environ[key] = value


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
    # AISStream-lyssnaren (run_ais_stream). Egen app: den äger ferry_arrivals,
    # men skriver sina tips i core:s source_events/opportunities.
    "maritime",
    # Evenemangskalendern (Ticketmaster först, fler källor senare).
    "events",
    # Kundlivscykeln: bolag, roller, bilar, billicenser, län, godkända
    # telefoner, aktiva bilsessioner, prov, beställningar och revision.
    # Egen app och inte fler kolumner i Supabases `companies`/`devices` --
    # se fleet/models.py:s docstring.
    "fleet",
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
# Bara lokal docker-compose (appen i container, Postgres på host via
# `supabase start`). På Coolify ska DATABASE_URL peka på rätt hostnamn
# rakt av -- skriv inte om till host.docker.internal där (finns inte).
if (
    os.environ.get("DJANGO_DOCKER_HOST_GATEWAY") == "1"
    and Path("/.dockerenv").exists()
    and _database["HOST"] in ("127.0.0.1", "localhost")
):
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
# Trafiklab har en nyckel per dataset. TRAFIKLAB_API_KEY gäller GTFS Sverige 3 Realtime
# (gtfs-rt-sweden/...); de här två gäller GTFS Sverige 3 statisk och GTFS Regional Realtime.
GTFS_SWEDEN3_STATIC_KEY = os.environ.get("GTFS_SWEDEN3_STATIC_KEY", "")
GTFS_REGIONAL_RT_KEY = os.environ.get("GTFS_REGIONAL_RT_KEY", "")
VASTTRAFIK_CLIENT_ID = os.environ.get("VASTTRAFIK_CLIENT_ID", "")
VASTTRAFIK_CLIENT_SECRET = os.environ.get("VASTTRAFIK_CLIENT_SECRET", "")
# AISStream.io, fartygspositioner via WebSocket -- maritime/management/commands/run_ais_stream.py.
AISSTREAM_API_KEY = os.environ.get("AISSTREAM_API_KEY", "")
# Trafiklab ResRobot v2.1: tidtabell och reseplanerare, se core/sources/resrobot.py.
RESROBOT_API_KEY = os.environ.get("RESROBOT_API_KEY", "")
# Ticketmaster Discovery API v2 (https://developer.ticketmaster.com) -- poll_events
TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY", "")

# PredictHQ (https://docs.predicthq.com) -- poll_events
PREDICTHQ_ACCESS_TOKEN = os.environ.get("PREDICTHQ_ACCESS_TOKEN", "")

# TheSportsDB (https://www.thesportsdb.com) -- poll_events. "123" är deras öppna gratisnyckel för
# utveckling; en betald nyckel krävs för att publicera en app (events/sources/thesportsdb.py).
THESPORTSDB_API_KEY = os.environ.get("THESPORTSDB_API_KEY", "123")

# Evenemangskällor: vad som får lagras och vad som får visas i förarappen. Brytarna är
# teknik och ger ingen rätt. Varje handling kräver ÄVEN en referens till det som faktiskt
# tillåter den -- en villkorspunkt eller ett skriftligt avtal. Tom referens = inte
# tillåtet, oavsett brytare. Se events/rights.py och docs/data-sources.md.
# Förhandsvisning av evenemang i appen under utveckling, när ingen källa har rätt att visas
# där. Bara med DEBUG: ger ingen rättighet, når aldrig produktion och märks i svaret och i
# appen. Se events/api.py.
EVENTS_APP_PREVIEW = os.environ.get("EVENTS_APP_PREVIEW") == "1"

EVENT_SOURCES = {
    "ticketmaster": {
        "store": os.environ.get("EVENTS_TICKETMASTER_STORE", "1") == "1",
        "store_reference": os.environ.get(
            "EVENTS_TICKETMASTER_STORE_REFERENCE",
            'Ticketmaster Discovery API Terms of Use: lagring "for reasonable periods in order '
            'to provide the service" (hämtade 2026-09-12)',
        ),
        "show_in_app": os.environ.get("EVENTS_TICKETMASTER_SHOW_IN_APP", "0") == "1",
        # Tom med avsikt: villkoren förbjuder att "derive revenues" -- betald app kräver avtal.
        "app_reference": os.environ.get("EVENTS_TICKETMASTER_APP_REFERENCE", ""),
    },
    "predicthq": {
        "store": os.environ.get("EVENTS_PREDICTHQ_STORE", "0") == "1",
        # Tom med avsikt: villkor 3.7 d i förbjuder lagring utan skriftligt avtal, även lokalt.
        "store_reference": os.environ.get("EVENTS_PREDICTHQ_STORE_REFERENCE", ""),
        "show_in_app": os.environ.get("EVENTS_PREDICTHQ_SHOW_IN_APP", "0") == "1",
        "app_reference": os.environ.get("EVENTS_PREDICTHQ_APP_REFERENCE", ""),
    },
    "thesportsdb": {
        "store": os.environ.get("EVENTS_THESPORTSDB_STORE", "1") == "1",
        "store_reference": os.environ.get(
            "EVENTS_THESPORTSDB_STORE_REFERENCE",
            "TheSportsDB Terms of Use (hämtade 2026-09-19): lagring nämns inte; källan anges med länk",
        ),
        "show_in_app": os.environ.get("EVENTS_THESPORTSDB_SHOW_IN_APP", "0") == "1",
        # Tom med avsikt: "You cannot publish apps to an appstore unless you are a paid subscriber".
        # Fylls i med prenumerationen när den finns.
        "app_reference": os.environ.get("EVENTS_THESPORTSDB_APP_REFERENCE", ""),
    },
}
# Vilka Trafiklab-operatörer som pollas, och vilken marknad som räknas som
# "hemma" -- läses av core/market.py och core/sources/trafiklab.py. Samma
# namn och default som Node-workern, så en befintlig .env fungerar oförändrat.
TRAFIKLAB_OPERATORS = os.environ.get("TRAFIKLAB_OPERATORS", "skane")
# Vilka län Trafikverkets vägdata hämtas för. "all" = alla 21. Samma namn
# och default som Node-workern.
TRAFIKVERKET_COUNTIES = os.environ.get("TRAFIKVERKET_COUNTIES", "skane")
MARKET_SCOPE = os.environ.get("MARKET_SCOPE", "skane")
# Swedavia FlightInfo v2. Kvoten (10 001 anrop/30 dagar) exponeras inte i
# några svarsheaders, så den bevakas av core/thresholds.py:s budget i stället.
SWEDAVIA_API_KEY = os.environ.get("SWEDAVIA_API_KEY", "")

# --- Celery -----------------------------------------------------------
# CELERY_TASK_ALWAYS_EAGER: satt av testkörning (se Jenkinsfile och README)
# så `manage.py test` aldrig behöver en levande Redis/broker -- samma
# env-flagga-i-en-fil-mönster som DJANGO_DEBUG ovan, ingen ny settings-modul.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"
CELERY_TASK_EAGER_PROPAGATES = CELERY_TASK_ALWAYS_EAGER
# Ingen task får hänga för evigt: en hämtning som fastnar i ett anrop utan
# timeout håller annars en av två worker-processer tills containern startas
# om. Den mjuka gränsen kastar i kommandot (polling() skriver felet), den
# hårda dödar processen. Längre jobb sätter egna gränser i core/tasks.py.
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_TIME_LIMIT = 270

# Mappad 1:1 från run_pipeline.pys POLL_INTERVAL_SECONDS/SITES_REFRESH_SECONDS/
# REVIEW_INTERVAL_SECONDS -- se core/tasks.py. Heltalsintervall, inte crontab,
# för att matcha time.monotonic()s "N sekunder sedan senaste körning" exakt.
CELERY_BEAT_SCHEDULE = {
    "poll-rail": {"task": "core.tasks.poll_rail_task", "schedule": 90},
    "poll-road": {"task": "core.tasks.poll_road_task", "schedule": 90},
    "poll-trafiklab": {"task": "core.tasks.poll_trafiklab_task", "schedule": 90},
    "poll-sl": {"task": "core.tasks.poll_sl_task", "schedule": 90},
    "poll-vasttrafik": {"task": "core.tasks.poll_vasttrafik_task", "schedule": 90},
    # Glesare än de andra pollarna med avsikt: kommandot avgör själv vilka
    # flygplatser som är mogna (ARN var 10:e minut, MMX var 30:e), så beat
    # behöver bara knacka på tillräckligt ofta för att den tätaste kadensen
    # ska hållas. En tidtabell rör sig inte som ett inställt tåg gör.
    "poll-flights": {"task": "core.tasks.poll_flights_task", "schedule": 5 * 60},
    # Evenemang ändras på dagar, inte minuter, och Ticketmasters villkor tillåter
    # att appar som gör många anrop utan användare bakom stryps. Se events/ingest.py.
    "poll-events": {"task": "core.tasks.poll_events_task", "schedule": 6 * 60 * 60},
    "refresh-sites": {"task": "core.tasks.refresh_sites_task", "schedule": 24 * 60 * 60},
    "review-uncertain": {"task": "core.tasks.review_uncertain_task", "schedule": 5 * 60},
    # Tätare än pollningen med avsikt: en notis som väntar in nästa pollvarv
    # lägger upp till 90 sekunder till den fördröjning källan redan har, och
    # en störning är som mest värd att köra till i sin första kvart.
    # Cykeln är billig när det inte finns något att skicka -- en indexerad
    # fråga på notified_at is null som normalt ger noll rader.
    "push-cycle": {"task": "core.tasks.push_cycle_task", "schedule": 30},
    # Signaler från olika källor som delar plats och tid -- se core/combine.py.
    "combine-signals": {"task": "core.tasks.combine_signals_task", "schedule": 60},
    # "I tjänst"-rutor som gått ut -- se core/presence.py.
    "purge-presence": {"task": "core.tasks.purge_presence_task", "schedule": 5 * 60},
    # Gällande sjudygnsregel för tips och källhändelser, i batchar (se
    # core/repository.purge_old). Var tidigare inte schemalagd alls.
    "purge-old": {"task": "core.tasks.purge_old_task", "schedule": 60 * 60},
    # Bevisar att beat och en worker lever -- se core/pipeline_health.py.
    "heartbeat": {"task": "core.tasks.heartbeat_task", "schedule": 60},
    # Kundlivscykelns tidsstyrda del: väntande ändringar, provslut,
    # betalningsfrist, utkorg. En gång i timmen räcker -- åtkomsten avgörs av
    # serverns klocka vid varje anrop, inte av att tasken har kört, så ett
    # uteblivet tick kan aldrig ge extra åtkomst (se fleet/management/commands/
    # fleet_tick.py).
    "fleet-tick": {"task": "fleet.tasks.fleet_tick", "schedule": 60 * 60},
    # Avstämning mot Stripe. Rapporterar avvikelser, rättar inget.
    "fleet-reconcile-stripe": {
        "task": "fleet.tasks.reconcile_stripe", "schedule": 6 * 60 * 60
    },
}

# Stäng av enskilda beat-poster, t.ex. lokalt:
#   TAXITIPS_BEAT_DISABLE=push-cycle,review-uncertain
# så att en lokal worker inte skickar riktiga notiser till testtelefoner
# eller anropar Genkit. Inte CELERY_-prefix: Celery läser de nycklarna själv.
for _entry in filter(None, (e.strip() for e in os.environ.get("TAXITIPS_BEAT_DISABLE", "").split(","))):
    CELERY_BEAT_SCHEDULE.pop(_entry, None)

# En task som legat i kön längre än sitt eget intervall är redan ersatt av
# nästa. Utan utgångstid kör en worker som varit nere hela kön i ett svep.
for _entry in CELERY_BEAT_SCHEDULE.values():
    _entry.setdefault("options", {}).setdefault("expires", _entry["schedule"])

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
# Produkten och momssatsen som prenumerationsposterna i Stripe skrivs mot.
# Båda tomma i utveckling; `fleet.stripe_sync.check_billing_config()` listar
# vad som fattas innan modellen får gå i produktion.
STRIPE_PRODUCT_ID = os.environ.get("STRIPE_PRODUCT_ID", "")
STRIPE_VAT_TAX_RATE_ID = os.environ.get("STRIPE_VAT_TAX_RATE_ID", "")
# Spärr mot att den här koden rör riktiga abonnemang. Måste sättas till "1"
# uttryckligen innan en livenyckel används -- se fleet/stripe_sync.py.
STRIPE_ALLOW_LIVE = os.environ.get("STRIPE_ALLOW_LIVE", "")

# --- Kundlivscykeln (fleet-appen) --------------------------------------
# Kräv billicens, godkänd telefon och aktiv bilsession av ALLA. False under
# utrullningen: ett företag utan licenser kör vidare på den gamla regeln, så
# att en deploy inte låser ute befintliga kunder. Sätts till 1 när
# `manage.py migrate_legacy_fleet` har körts och kunderna är informerade.
# Återställning är att sätta tillbaka den till 0; ingen data behöver rullas
# tillbaka, eftersom migreringen bara lägger till rader.
FLEET_ENFORCE_LICENSES = os.environ.get("FLEET_ENFORCE_LICENSES", "")
# Datum då tvåfaktor börjar krävas för köp, uppsägning, medlemshantering och
# ägarbyte. Tom = kravet är inte påslaget. Finns för att införandet ska kunna
# annonseras innan det slår till (§2: ingen oannonserad utelåsning).
FLEET_TWO_FACTOR_REQUIRED_FROM = os.environ.get("FLEET_TWO_FACTOR_REQUIRED_FROM", "")
# Sändaren för utkorgen (bekräftelser, påminnelser). Tom = raderna skrivs men
# skickas inte, så en utvecklingsmiljö aldrig kan nå en riktig mottagare.
FLEET_OUTBOX_SENDER = os.environ.get("FLEET_OUTBOX_SENDER", "")

# Samma variabelnamn som taxitips-api/worker/src/fcmPush.js, för kontinuitet
# -- samma Firebase-projekt backar båda tjänsterna.
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")

# Alla loggposter går genom RedactFilter: positioner, enhets- och push-tokens och
# API-nycklar i URL:er tas bort innan raden skrivs (core/log_filters.py).
# `django` och `django.server` pekas om hit; annars skriver Django (i DEBUG) och
# runserver ofiltrerat genom sina egna handlers.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "core.log_filters.RedactFilter"}},
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "filters": ["redact"], "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
# Celery byter annars ut rotloggern mot sin egen, och filtret ovan försvinner i
# worker och beat -- där källornas felmeddelanden med anrops-URL:er skrivs.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# Delad cache för uträknade flöden (core/api.shared_feed). Utan CACHE_REDIS_URL har
# varje process sin egen minnescache, vilket räcker för en instans; med flera
# repliker delar Redis resultatet mellan dem.
if os.environ.get("CACHE_REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.environ["CACHE_REDIS_URL"],
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "taxitips"}}
