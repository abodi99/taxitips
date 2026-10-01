"""
Vilken appversion som krävs -- servern bestämmer, appen lyder.

Tidigare låg gränsen i Firebase Remote Config (`required_version`). Den gällde
båda plattformarna på en gång, syntes inte i adminwebben, och jämförelsen i
appen var den enda som fanns. Nu står gränsen i `app_version_policy` (en rad,
redigerbar i adminwebben utan deploy), serveras öppet i `/api/config`, och
appen jämför sin egen version mot den vid start och när den kommer tillbaka
från bakgrunden.

Två nivåer per plattform:

- **min** -- lägre än så blockeras appen helt, med en knapp till butiken. För
  en version som skickar fel data eller pratar med ett API som inte finns kvar.
- **recommended** -- lägre än så visas en banderoll som går att stänga. För
  allt annat: en förare mitt i ett pass ska inte tvingas uppdatera för en ny
  knappfärg.

Appen **blockerar aldrig när anropet misslyckas.** Ett avbrott på servern får
inte låsa ute varje förare samtidigt -- det kontrolleras i appen
(`lib/app_version.dart`), inte här.

Versionsformen är den Flutter skriver i pubspec: `1.2.3`, eventuellt med
byggnummer, `1.2.3+45`. Byggnumret jämförs bara när gränsen anger ett --
annars skulle varje ny byggning av samma version räknas som "nyare" och en
gräns på `1.2.3` aldrig gå att uppfylla med `1.2.3+1`.
"""

from __future__ import annotations

import logging
import re

from django.conf import settings

log = logging.getLogger(__name__)

PLATFORMS = ("android", "ios")
LEVELS = ("min", "recommended")

# Fältet i modellen och miljövariabeln som gäller när fältet är tomt.
_FIELDS = {
    ("android", "min"): ("android_min_version", "APP_ANDROID_MIN_VERSION"),
    ("android", "recommended"): ("android_recommended_version", "APP_ANDROID_RECOMMENDED_VERSION"),
    ("ios", "min"): ("ios_min_version", "APP_IOS_MIN_VERSION"),
    ("ios", "recommended"): ("ios_recommended_version", "APP_IOS_RECOMMENDED_VERSION"),
}

# Högst fyra led och rimliga längder: en gräns som "99999999999" är ett
# skrivfel, inte en version, och skulle stänga ute alla.
_VERSION = re.compile(r"^(\d{1,4})(?:\.(\d{1,4})){0,3}(?:\+(\d{1,9}))?$")

MESSAGE_MAX = 300


class AppVersionError(Exception):
    """Ett ogiltigt värde från adminwebben, med ett skäl som går att visa."""

    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


def parse(value: str) -> tuple[tuple[int, ...], int | None] | None:
    """`"1.0.10+7"` -> `((1, 0, 10), 7)`. None för allt som inte är en version."""
    value = (value or "").strip()
    if not _VERSION.match(value):
        return None
    core, _, build = value.partition("+")
    return tuple(int(p) for p in core.split(".")), (int(build) if build else None)


def compare(a: str, b: str) -> int:
    """
    -1, 0 eller 1. Leden jämförs som tal (1.0.10 > 1.0.9) och fylls ut med
    nollor (1.2 == 1.2.0). Byggnumret avgör bara när båda har ett.
    """
    pa, pb = parse(a), parse(b)
    if pa is None or pb is None:
        raise ValueError(f"ogiltig version: {a!r} / {b!r}")
    (ca, ba), (cb, bb) = pa, pb
    width = max(len(ca), len(cb))
    ca = ca + (0,) * (width - len(ca))
    cb = cb + (0,) * (width - len(cb))
    if ca != cb:
        return -1 if ca < cb else 1
    if ba is not None and bb is not None and ba != bb:
        return -1 if ba < bb else 1
    return 0


def _env(name: str, *, version: bool = True) -> str:
    value = str(getattr(settings, name, "") or "").strip()
    # En felskriven miljövariabel ska inte kunna låsa ute alla: den ignoreras
    # och loggas, precis som ett tomt värde.
    if value and version and parse(value) is None:
        log.warning("app_version: %s=%r är ingen version och ignoreras", name, value)
        return ""
    return value


def _policy_row():
    """
    Raden, eller None om tabellen inte går att läsa. /api/config bär också
    tröskelvärdena; en saknad migrering får inte ta ned dem.
    """
    from core.models import AppVersionPolicy

    try:
        # Läs, skapa inte: en öppen GET ska aldrig skriva i databasen.
        return AppVersionPolicy.objects.filter(id=1).first()
    except Exception as exc:  # t.ex. tabellen finns inte än (expand före migrate)
        log.warning("app_version: kunde inte läsa app_version_policy: %s", exc)
        return None


def _effective(row) -> dict:
    """Gällande gränser med var varje värde kommer ifrån (db, env eller inget)."""
    out: dict = {}
    for platform in PLATFORMS:
        out[platform] = {}
        for level in LEVELS:
            field, env_name = _FIELDS[(platform, level)]
            db_value = (getattr(row, field, "") or "").strip() if row is not None else ""
            if db_value:
                out[platform][level] = {"value": db_value, "source": "db"}
            elif _env(env_name):
                out[platform][level] = {"value": _env(env_name), "source": "env"}
            else:
                out[platform][level] = {"value": None, "source": None}
    ios_url = ((row.ios_store_url if row is not None else "") or "").strip()
    if ios_url:
        out["ios"]["storeUrl"] = {"value": ios_url, "source": "db"}
    elif _env("APP_IOS_STORE_URL", version=False):
        out["ios"]["storeUrl"] = {"value": _env("APP_IOS_STORE_URL", version=False), "source": "env"}
    else:
        out["ios"]["storeUrl"] = {"value": None, "source": None}
    package = getattr(settings, "APP_ANDROID_PACKAGE", "") or "se.taxitips.app"
    out["android"]["storeUrl"] = {
        "value": f"https://play.google.com/store/apps/details?id={package}",
        "source": "env",
    }
    out["android"]["package"] = package
    out["message"] = ((row.message if row is not None else "") or "").strip() or None
    return out


def public_config() -> dict:
    """
    Det `/api/config` bär under `appVersion`. Öppet med avsikt: en gammal app
    som inte kan logga in måste ändå kunna få veta att den är för gammal.
    """
    eff = _effective(_policy_row())
    return {
        platform: {
            "min": eff[platform]["min"]["value"],
            "recommended": eff[platform]["recommended"]["value"],
            "storeUrl": eff[platform]["storeUrl"]["value"],
        }
        for platform in PLATFORMS
    } | {"message": eff["message"]}


def admin_state() -> dict:
    """Samma sak för adminwebben, plus varifrån varje värde kommer."""
    row = _policy_row()
    eff = _effective(row)
    return {
        "platforms": {
            platform: {
                level: eff[platform][level] for level in (*LEVELS, "storeUrl")
            }
            for platform in PLATFORMS
        },
        "message": eff["message"],
        "stored": {
            "android": {
                "min": row.android_min_version if row else "",
                "recommended": row.android_recommended_version if row else "",
            },
            "ios": {
                "min": row.ios_min_version if row else "",
                "recommended": row.ios_recommended_version if row else "",
                "storeUrl": row.ios_store_url if row else "",
            },
            "message": row.message if row else "",
        },
        "updatedAt": row.updated_at.isoformat() if row and row.updated_at else None,
    }


def _clean_version(value, label: str) -> str:
    value = str(value if value is not None else "").strip()
    if value and parse(value) is None:
        raise AppVersionError(
            "invalid_version",
            f"{label}: \"{value}\" är ingen version. Skriv t.ex. 1.2.3 eller 1.2.3+45.",
        )
    return value


def update(body: dict, *, user_id=None) -> tuple[dict, dict]:
    """
    Sparar det som skickats; en nyckel som saknas lämnas orörd. Returnerar
    (före, efter) som de lagrade värdena, för revisionsloggen.

    Kontrollerna finns för att ett skrivfel här slår mot varje förare på en
    gång -- därför hellre ett nej i adminwebben än en gräns som inte går att
    uppfylla.
    """
    from core.models import AppVersionPolicy

    row = AppVersionPolicy.current()
    before = {
        "android_min_version": row.android_min_version,
        "android_recommended_version": row.android_recommended_version,
        "ios_min_version": row.ios_min_version,
        "ios_recommended_version": row.ios_recommended_version,
        "ios_store_url": row.ios_store_url,
        "message": row.message,
    }
    labels = {"android": "Android", "ios": "iPhone"}
    for platform in PLATFORMS:
        part = body.get(platform)
        if part is None:
            continue
        if not isinstance(part, dict):
            raise AppVersionError("invalid_body", "Ogiltigt format.")
        for level in LEVELS:
            if level in part:
                field, _ = _FIELDS[(platform, level)]
                word = "minsta version" if level == "min" else "rekommenderad version"
                setattr(row, field, _clean_version(part[level], f"{labels[platform]}, {word}"))
        if platform == "ios" and "storeUrl" in part:
            url = str(part["storeUrl"] or "").strip()
            # En länk som inte öppnar App Store lämnar en blockerad förare
            # utan väg ut. https räcker; iOS öppnar apps.apple.com i butiken.
            if url and not url.startswith("https://"):
                raise AppVersionError(
                    "invalid_store_url", "App Store-länken måste börja med https://."
                )
            row.ios_store_url = url[:300]
    if "message" in body:
        message = str(body.get("message") or "").strip()
        if len(message) > MESSAGE_MAX:
            raise AppVersionError(
                "message_too_long", f"Meddelandet får vara högst {MESSAGE_MAX} tecken."
            )
        row.message = message

    eff = _effective(row)
    for platform in PLATFORMS:
        low = eff[platform]["min"]["value"]
        rec = eff[platform]["recommended"]["value"]
        if low and rec and compare(rec, low) < 0:
            raise AppVersionError(
                "recommended_below_min",
                f"{labels[platform]}: rekommenderad version kan inte vara lägre än minsta.",
            )
    # iPhone-appen öppnar butiken via länken ovan. Utan den blir en blockerad
    # förare stående framför en knapp som inte gör något.
    if eff["ios"]["min"]["value"] and not eff["ios"]["storeUrl"]["value"]:
        raise AppVersionError(
            "ios_store_url_required",
            "Lägg in App Store-länken innan du sätter en minsta iPhone-version.",
        )

    row.updated_by = user_id
    row.save()
    after = {key: getattr(row, key) for key in before}
    return before, after
