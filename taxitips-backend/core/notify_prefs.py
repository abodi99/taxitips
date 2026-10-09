"""
Notisinställningarna som någon ÄNDRAR: färdiga lägen och valideringen.

Tre vägar skriver `devices.notify_prefs`: förarens app (/api/notify-prefs i
core/api.py), kundens administratör i portalen (fleet/notify_api.py) och
plattformens personal i adminwebben (fleet/admin_notify.py). Alla tre går genom
`apply_update`, så att en inställning inte kan vara giltig i portalen och okänd
för appen -- eller vidga länen bakom ryggen på licensen i en av dem.

Vad fälten BETYDER för notisbeslutet står i core/notify.py (decide); här står
bara vad som får sparas. Ett fält som saknas betyder alltid "som förut", så en
telefon som aldrig rört inställningarna beter sig som innan fälten fanns.

Färdiga lägen
-------------
De flesta förare vill välja ett läge, inte tolv reglage. Ett läge skriver
reglagen; ändrar föraren sedan ett reglage är läget "Eget" (`custom`).

**Rekommenderat** är det vi tror ger körningar utan att störa, och det är vad
en ny telefon redan har. Det följer poängsättningen rakt av, utan egna regler:

* Notis bara för **Starka** tips: poäng minst thresholds.NOTIFY_SCORE_FLOOR
  (60, samma gräns som Stark på kortet), en typ i NOTIFY_WORTHY_TIERS (hela
  linjen står still, inställd avgång, olycka) och ingen ersättningstrafik
  utskriven av källan. I praktiken: inställt tåg med en timme eller mer till
  nästa resa (68 p) och sista avgången (80 p), docs/betygsmetod.md §4.1.
  Vägtips är kapade till 15 p och når aldrig golvet; kategorin står ändå på,
  det finns inget att vinna på att gömma den.
* **Inga svaga notiser.** Utan golvet var ~64% av notiserna "en buss är sen"
  (thresholds.py) -- precis det som får en förare att stänga av notiserna
  helt och då missa de starka.
* **Inga tysta timmar.** Natten är när sista avgången strandar folk; de
  värdefullaste notiserna kommer mellan 23 och 02.
* **Inget tak per timme.** Starka tips är få; ett tak hade kunnat ta bort just
  den notis som var värd något.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from core import areas, notify, thresholds

# Ordningen är visningsordningen. `help` är EN mening, i förarens ord.
PRESETS: list[dict] = [
    {
        "id": "recommended",
        "label": "Rekommenderat",
        "help": "Bara starka tips: när en linje står still eller en avgång är inställd utan ersättning.",
    },
    {
        "id": "strongest",
        "label": "Bara de starkaste",
        "help": "Bara när hela linjen står still eller sista avgången är inställd. Färre notiser.",
    },
    {
        "id": "everything",
        "label": "Allt i mina län",
        "help": (
            "Starka och svaga tips i bilens alla län. "
            f"Högst {thresholds.NOTIFY_WEAK_MAX_PER_HOUR} svaga i timmen."
        ),
    },
    {
        "id": "silent",
        "label": "Tyst",
        "help": "Inga notiser. Tipsen finns kvar i listan.",
    },
]
PRESET_IDS = {p["id"] for p in PRESETS}
CUSTOM = "custom"

# Fält ett läge skriver. Län och paus rör ett läge inte (utom "Allt i mina län",
# som tar hela licensen): länen följer bilen och pausen är förarens stund.
_PRESET_FIELDS = ("enabled", "weak", "minLevel", "categories", "types", "quietHours", "maxPerHour")

# Det en företagsstandard får bära: reglerna, aldrig område eller paus. Området
# blir alltid bilens län när telefonen kopplas (fleet/pairing.py), och en paus
# hör till en förare i ett ögonblick, inte till ett företag.
DEFAULT_FIELDS = frozenset(_PRESET_FIELDS) | {"preset"}

_CATEGORY_IDS = [c["id"] for c in notify.CATEGORY_CATALOG]
_NOTIFIABLE_TYPES = [t["id"] for t in notify.TYPE_CATALOG if t["id"] in thresholds.NOTIFY_WORTHY_TIERS]
_WEAK_TYPES = [t["id"] for t in notify.TYPE_CATALOG if t.get("weak")]
_MAX_PER_HOUR_LIMIT = 30


def _all_categories_on() -> dict:
    return {c: True for c in _CATEGORY_IDS}


def preset_patch(preset: str) -> dict:
    """Reglagen ett läge sätter. Okänt läge = inget."""
    base = {
        "enabled": True,
        "weak": False,
        "minLevel": "all",
        "categories": _all_categories_on(),
        # Tom = katalogens standard för varje typ (notify.type_enabled).
        "types": {},
        "quietHours": None,
        "maxPerHour": None,
    }
    if preset == "recommended":
        return base
    if preset == "strongest":
        return {
            **base,
            "types": {t: t == "line_paused" for t in _NOTIFIABLE_TYPES},
        }
    if preset == "everything":
        return {**base, "weak": True}
    if preset == "silent":
        return {"enabled": False}
    return {}


def _set(out: dict, key: str, value) -> None:
    if value is None:
        out.pop(key, None)
    else:
        out[key] = value


def _quiet_value(raw):
    """{"from", "to"} som heltal, None för "inga", eller ... för ogiltigt."""
    if raw in (None, False, "", {}):
        return None
    probe = notify.quiet_hours({"quietHours": raw})
    if probe is None:
        return ...
    return {"from": probe[0], "to": probe[1]}


def _max_value(raw):
    if raw in (None, False, "", 0, "0"):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return ...
    if not 1 <= value <= _MAX_PER_HOUR_LIMIT:
        return ...
    return value


def apply_update(
    current: dict | None,
    body: dict,
    *,
    entitled=None,
    restricted: bool = False,
    now=None,
    allowed=None,
) -> dict:
    """
    Det klienten skickar, validerat och lagt ovanpå det sparade.

    `entitled`/`restricted`: länen bilens licens omfattar (fleet/access.py).
    Länsval utanför dem sparas aldrig -- de hade sett ut som ett val men aldrig
    gett en notis (fleet/push_gate.py släpper inte igenom dem). Är
    licensmodellen på men inget län känt rörs länen inte alls, hellre än att
    körområdet töms.

    `allowed`: fälten som får ändras (företagsstandarden tar bara reglerna).

    Okända nycklar och ogiltiga värden sparas inte. En okänd nyckel är ett
    stavfel eller en klient från framtiden, och båda ska synas som att den inte
    fastnade -- inte ligga kvar och se ut som en inställning.
    """
    now = now or timezone.now()
    out = dict(current) if isinstance(current, dict) else {}
    body = body if isinstance(body, dict) else {}
    if allowed is not None:
        body = {k: v for k, v in body.items() if k in allowed}
    entitled_set = {str(c) for c in (entitled or ()) if str(c).strip()}
    area_locked = restricted and not entitled_set

    preset = str(body.get("preset") or "")
    if preset in PRESET_IDS:
        for key, value in preset_patch(preset).items():
            _set(out, key, value)
        if preset == "everything" and (allowed is None or "counties" in allowed):
            # Hela licensen, inga kommuner: "allt i mina län" betyder alla län.
            if restricted and entitled_set:
                out["counties"] = sorted(entitled_set)
            out["municipalities"] = []
            out["regions"] = []
            out["cities"] = []

    if "enabled" in body:
        out["enabled"] = body["enabled"] is not False
    if isinstance(body.get("types"), dict):
        known = {t["id"] for t in notify.TYPE_CATALOG}
        out["types"] = {k: v is True for k, v in body["types"].items() if k in known}
    if isinstance(body.get("regions"), list):
        known = {r["key"] for r in notify.region_catalog()}
        out["regions"] = [str(r) for r in body["regions"] if str(r) in known]
    if isinstance(body.get("counties"), list) and not area_locked:
        counties = {str(c) for c in body["counties"] if str(c) in areas.COUNTY_NAMES}
        if restricted:
            counties &= entitled_set
            # Föraren har sett och valt bland just dessa län; ett som tillkommer
            # senare läggs till av fleet/device_prefs.align_prefs_to_entitlement.
            out["entitledCounties"] = sorted(entitled_set)
        out["counties"] = sorted(counties)
    if isinstance(body.get("categories"), dict):
        out["categories"] = {
            k: v is not False for k, v in body["categories"].items() if k in _CATEGORY_IDS
        }
    if "minLevel" in body:
        level = str(body.get("minLevel") or "all")
        out["minLevel"] = level if level in notify.LEVELS else "all"
    if "weak" in body:
        out["weak"] = body["weak"] is True
    if "quietHours" in body:
        value = _quiet_value(body.get("quietHours"))
        if value is not ...:
            _set(out, "quietHours", value)
    if "maxPerHour" in body:
        value = _max_value(body.get("maxPerHour"))
        if value is not ...:
            _set(out, "maxPerHour", value)
    if "pauseHours" in body:
        # Pausen räknas på servern, från serverns klocka: en telefon med fel tid
        # ska inte kunna pausa i ett år eller "pausa" bakåt i tiden.
        try:
            hours = float(body.get("pauseHours") or 0)
        except (TypeError, ValueError):
            hours = 0
        if hours > 0:
            hours = min(hours, notify.MAX_PAUSE_HOURS)
            out["pausedUntil"] = (now + timedelta(hours=hours)).isoformat()
        else:
            out.pop("pausedUntil", None)
    if isinstance(body.get("municipalities"), list) and not area_locked:
        chosen = areas.device_municipalities({"municipalities": body["municipalities"]})
        if restricted:
            chosen = [m for m in chosen if m[:2] in entitled_set]
        out["municipalities"] = chosen
    if isinstance(body.get("cities"), list):
        out["cities"] = [str(c) for c in body["cities"] if str(c).strip()][:50]

    # Kommuner utanför de valda länen har ingen mening; de hade legat kvar
    # osynliga och smalnat av notiserna utan att någon vetat om det.
    if isinstance(out.get("municipalities"), list) and out.get("counties"):
        out["municipalities"] = [m for m in out["municipalities"] if str(m)[:2] in set(out["counties"])]

    # Orter som inte hör till något valt län rensas bort. Annars kunde en
    # förare välja Skåne, kryssa Malmö, byta till Stockholm -- och fortfarande
    # ha Malmö kvar i prefs utan att UI:t visar det.
    allowed_cities = {
        c
        for key in out.get("regions") or []
        if key != "rail"
        for c in notify.cities_by_region().get(key, [])
    }
    if allowed_cities:
        out["cities"] = [c for c in (out.get("cities") or []) if c in allowed_cities][:50]
    elif out.get("regions"):
        # Bara "rail" valt, eller län utan orter -- ortfiltret har ingen mening.
        out["cities"] = []

    # Svaga notiser med "bara starka" hade betytt "inga svaga" -- ett val som
    # säger emot sig självt. Den som slår på svagare tips menar minst Medel.
    if out.get("weak") is True and out.get("minLevel") == "high":
        out["minLevel"] = "medium"
    return out


def _effective_types(prefs: dict, ids, weak=False) -> dict:
    return {t: notify.type_enabled(prefs.get("types"), t, weak=weak) for t in ids}


def preset_of(prefs: dict | None, *, entitled=None) -> str:
    """
    Vilket läge inställningarna motsvarar, eller "custom". Jämför det som
    GÄLLER (en typ som saknas = katalogens standard), inte det som råkar vara
    sparat, så att en ny telefon med tomma prefs är "Rekommenderat".
    """
    prefs = prefs if isinstance(prefs, dict) else {}
    if prefs.get("enabled") is False:
        return "silent"
    if notify.quiet_hours(prefs) is not None or notify.max_per_hour(prefs) is not None:
        return CUSTOM
    if not all(notify.category_enabled(prefs.get("categories"), c) for c in _CATEGORY_IDS):
        return CUSTOM
    types = _effective_types(prefs, _NOTIFIABLE_TYPES)
    if notify.weak_enabled(prefs):
        weak_types = _effective_types(prefs, _WEAK_TYPES, weak=True)
        if (
            all(types.values()) and all(weak_types.values())
            and (prefs.get("minLevel") or "all") == "all"
            and not (prefs.get("municipalities") or [])
        ):
            chosen = set(areas.device_counties(prefs))
            wanted = {str(c) for c in (entitled or ())}
            if not wanted or wanted <= chosen:
                return "everything"
        return CUSTOM
    if all(types.values()):
        return "recommended"
    if types == {t: t == "line_paused" for t in _NOTIFIABLE_TYPES}:
        return "strongest"
    return CUSTOM


def preset_label(preset: str) -> str:
    for p in PRESETS:
        if p["id"] == preset:
            return p["label"]
    return "Egna val"


def summary(prefs: dict | None, *, entitled=None, now=None) -> str:
    """En rad för tabellerna i portalen och adminwebben: läget plus det som avviker."""
    prefs = prefs if isinstance(prefs, dict) else {}
    now = now or timezone.now()
    preset = preset_of(prefs, entitled=entitled)
    bits = [preset_label(preset)]
    if preset == "silent":
        return bits[0]
    pause = notify.paused_until(prefs)
    if pause is not None and pause > now:
        local = pause.astimezone(notify._STOCKHOLM)
        bits.insert(0, f"Pausad till {local:%H:%M}")
    if preset == CUSTOM:
        if notify.weak_enabled(prefs):
            bits.append("svagare tips på")
        off = [
            c["label"] for c in notify.CATEGORY_CATALOG
            if not notify.category_enabled(prefs.get("categories"), c["id"])
        ]
        if off:
            bits.append("av: " + ", ".join(off))
        quiet = notify.quiet_hours(prefs)
        if quiet:
            bits.append(f"tyst {quiet[0]:02d}–{quiet[1]:02d}")
        cap = notify.max_per_hour(prefs)
        if cap:
            bits.append(f"högst {cap} i timmen")
    return " · ".join(bits)


def catalogs() -> dict:
    """Det ett formulär behöver för att visa valen, samma för app, portal och admin."""
    return {
        "presetCatalog": PRESETS,
        "categoryCatalog": notify.CATEGORY_CATALOG,
        "typeCatalog": notify.type_catalog(),
        "levels": list(notify.LEVELS),
        "maxPauseHours": notify.MAX_PAUSE_HOURS,
        "maxPerHourChoices": list(thresholds.NOTIFY_MAX_PER_HOUR_CHOICES),
        "weakMaxPerHour": thresholds.NOTIFY_WEAK_MAX_PER_HOUR,
        "notifyScoreFloor": thresholds.NOTIFY_SCORE_FLOOR,
    }
