"""
Evenemang sett med en taxiförares ögon: kategori, storlek, sluttid, och vad som
inte är ett evenemang alls.

En förare bryr sig inte om när dörrarna öppnar utan om när publiken går hem, och
hur många som gör det. Sluttiden tas i den här ordningen: källans riktiga sluttid,
PredictHQ:s förutsagda, och sist en uppskattning per kategori -- alltid märkt med
vilken, så att appen aldrig visar en gissning som ett faktum.

Allt här är rena funktioner utan databas.
"""

from __future__ import annotations

import datetime as dt
import re
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

STOCKHOLM = ZoneInfo("Europe/Stockholm")

SOURCE_LABELS = {"ticketmaster": "Ticketmaster", "predicthq": "PredictHQ", "thesportsdb": "TheSportsDB"}

CATEGORY_LABELS = {
    "konsert": "Konsert",
    "teater": "Teater och scen",
    "humor": "Humor",
    "sport": "Sport",
    "familj": "Familj",
    "massa": "Mässa och konferens",
    "festival": "Festival",
    "film": "Film",
    "flyg": "Flygförseningar",
    "vader": "Oväder",
    "katastrof": "Olyckor och katastrofer",
    "sakerhet": "Säkerhetshot",
    "ovrigt": "Övrigt",
}

# Minuter från start till att publiken strömmar ut. Okalibrerade startvärden --
# de ska ersättas av uppmätta längder när det finns data att mäta på, och
# märks därför "uppskattad" överallt där de syns.
TYPICAL_DURATION_MIN = {
    "konsert": 165,
    "teater": 150,
    "humor": 120,
    "sport": 135,
    "familj": 90,
    "massa": 300,
    "festival": 300,
    "film": 150,
    # PredictHQ ger egen sluttid för förseningar och oväder; det här gäller bara när den saknas.
    "flyg": 120,
    "vader": 360,
    "katastrof": 240,
    "sakerhet": 240,
    "ovrigt": 150,
}

# Utsläppsfönstret: från sluttiden och så här länge efter. En arena töms inte
# på en minut, och kön till tunnelbanan är längst i början.
LEAVE_WINDOW_MIN = 45

BASIS_SOURCE = "source"
BASIS_PREDICTED = "predicted"
BASIS_ESTIMATED = "estimated"
BASIS_UNKNOWN = "unknown"

# Storlek efter PredictHQ:s phq_attendance -- en förutsägelse, inte en räkning,
# och visas därför alltid avrundad (attendance_text). Mätt 2026-09-13 för Sverige,
# 120 dagar: median 1 106, 1 438 evenemang med minst 1 000 och 338 med minst 5 000.
# Under 1 000 är sällan en egen körning värd; det är standardgränsen i /api/events.
TAXI_MIN_ATTENDANCE = 1000
LARGE_ATTENDANCE = 5000
SIZE_LABELS = {
    "stor": "Stort, 5 000+",
    "medel": "Medel, 1 000–4 999",
    "liten": "Litet, under 1 000",
    "okand": "Storlek okänd",
}

STATUS_LABELS = {
    "onsale": "Planerat",
    "offsale": "Planerat",
    "active": "Planerat",
    "predicted": "Väntat, inte bekräftat",
    "cancelled": "Inställt",
    "canceled": "Inställt",
    "postponed": "Uppskjutet",
    "rescheduled": "Nytt datum",
}
# Här står ingen publik. "rescheduled" står inte med: evenemanget har fått ett
# nytt datum och blir av då.
NOT_HAPPENING = frozenset({"cancelled", "canceled", "postponed"})

# Produkter som säljs som egna "evenemang" men bara är tillägg till ett annat:
# de ger ingen egen publik och skulle dubblera evenemanget i kalendern. Mätt
# 2026-09-12: "President | Early entry and merchandise experience",
# "Dryckeskuponger - Linköping Beer Expo", "A$AP Rocky ... Platinum Tickets".
# Konservativ med avsikt -- "VIP" eller "Pass" ensamt kan vara riktiga evenemang.
# Mönstret DÖLJER inget på egen hand: events.ingest.resolve_addons döljer en
# träff bara när huvudevenemanget finns samma dag på samma plats.
ADDON_PATTERN = re.compile(
    r"early entry|merchandise|dryckeskupong|kupong|voucher|parkering|parking|platinum|"
    r"fast track|uppgradering|upgrade|vip[- ]?paket|garderob|lounge access",
    re.IGNORECASE,
)

PHQ_CATEGORY = {
    "concerts": "konsert",
    "sports": "sport",
    "festivals": "festival",
    # Flygförseningar i Sverige och på Kastrup (events/sources/predicthq.py), oväder och händelser.
    "airport-delays": "flyg",
    "severe-weather": "vader",
    "disasters": "katastrof",
    "terror": "sakerhet",
    "conferences": "massa",
    "expos": "massa",
    "community": "ovrigt",
    "performing-arts": "teater",
}


def category_for(segment: str | None, genre: str | None, sub_type: str | None = None) -> str:
    """Ticketmasters segment/genre som en av CATEGORY_LABELS nycklar."""
    seg = (segment or "").lower()
    gen = (genre or "").lower()
    sub = (sub_type or "").lower()
    if seg == "sports":
        return "sport"
    if gen == "comedy":
        return "humor"
    if gen in ("family", "children's theatre"):
        return "familj"
    if seg == "music":
        return "konsert"
    if seg == "arts & theatre":
        return "teater"
    if seg == "film":
        return "film"
    if sub == "festival":
        return "festival"
    if gen == "food & drink" or sub in ("expo", "convention"):
        return "massa"
    return "ovrigt"


def category_for_phq(category: str | None, labels: list[str] | None) -> str:
    """
    PredictHQ:s kategori och phq_labels som en av CATEGORY_LABELS nycklar.

    performing-arts rymmer allt från stå-upp till bio (mätt: general-theatre 314,
    comedy-club 174, concert 151, movie 61, family-theatre 34, circus 45), och de
    tömmer lokalen olika fort -- därför delas den upp på etiketterna.
    """
    tags = set(labels or [])
    if category == "performing-arts":
        if "comedy-club" in tags:
            return "humor"
        if tags & {"family-theatre", "circus"}:
            return "familj"
        if "movie" in tags:
            return "film"
        if "concert" in tags:
            return "konsert"
        return "teater"
    if category == "community" and "family-fun" in tags:
        return "familj"
    return PHQ_CATEGORY.get(category or "", "ovrigt")


def addon_reason(name: str | None) -> str:
    match = ADDON_PATTERN.search(name or "")
    if not match:
        return ""
    return f'Tilläggsprodukt, inte ett eget evenemang ("{match.group(0)}" i namnet).'


# Ticketmasters dynamiskt prissatta "Platinum"-biljetter listas som ett eget
# evenemang med suffix i namnet. För de stora arenakonserterna är det ofta den
# ENDA posten i Discovery API: 12 av 13 mätt 2026-09-12 (A$AP Rocky, J. Cole,
# Tove Lo, Benjamin Ingrosso ...). Suffixet tas bort i visningen; källans namn
# ligger kvar i raden.
_PLATINUM_SUFFIX = re.compile(r"[\s,|:–-]*platinum(?:\s+tickets?)?\s*$", re.IGNORECASE)


def display_name(name: str | None) -> str:
    cleaned = _PLATINUM_SUFFIX.sub("", name or "").strip()
    return cleaned or (name or "")


def fix_mojibake(text: str | None) -> str:
    """UTF-8 som lästs som Latin-1 ("GÃ¶teborg Book Fair", PredictHQ) tillbaka till text."""
    if not text or ("Ã" not in text and "Â" not in text):
        return text or ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


# PredictHQ blandar engelska och svenska ortnamn för samma ort (mätt: "Gothenburg"
# 99, "Göteborg" 80, "Skelleftea" 21, "Skellefteå" 61). Ortsfiltret i appen matchar
# på namn, så de måste bli ett.
_EXONYMS = {
    "gothenburg": "Göteborg", "goteborg": "Göteborg", "skelleftea": "Skellefteå", "malmo": "Malmö",
    "gavle": "Gävle", "vasteras": "Västerås", "jonkoping": "Jönköping", "norrkoping": "Norrköping",
    "linkoping": "Linköping", "umea": "Umeå", "lulea": "Luleå", "orebro": "Örebro", "vaxjo": "Växjö",
    "borlange": "Borlänge", "ostersund": "Östersund", "sodertalje": "Södertälje", "angelholm": "Ängelholm",
    "ornskoldsvik": "Örnsköldsvik", "pitea": "Piteå", "boras": "Borås", "trollhattan": "Trollhättan",
}
_POSTCODE_CITY = re.compile(r"\b\d{3} ?\d{2} ([^,\d][^,]*)")


def swedish_city(name: str | None) -> str:
    name = fix_mojibake(name or "").strip()
    return _EXONYMS.get(name.lower(), name)


def city_from_address(formatted: str | None) -> str:
    """Orten efter postnumret: "Rudbecksgatan 52E, 702 23 Örebro, Sweden" -> "Örebro"."""
    match = _POSTCODE_CITY.search(formatted or "")
    return match.group(1).strip() if match else ""


def size_level(attendance: int | None) -> str:
    if attendance is None:
        return "okand"
    if attendance >= LARGE_ATTENDANCE:
        return "stor"
    if attendance >= TAXI_MIN_ATTENDANCE:
        return "medel"
    return "liten"


def attendance_text(attendance: int | None) -> str:
    """Avrundat, aldrig exakt: det är en förutsägelse, inte en biljettsiffra."""
    if not attendance:
        return ""
    step = 50 if attendance < 1000 else 100 if attendance < 10000 else 1000
    rounded = max(step, round(attendance / step) * step)
    return f"≈ {rounded:,} besökare".replace(",", " ")


_NAME_STOP = frozenset({
    "the", "and", "at", "live", "tour", "world", "vs", "och", "med", "på", "presents",
    "tickets", "platinum", "konsert", "show",
})


def _normalize_name(name: str | None) -> str:
    text = display_name(fix_mojibake(name or "")).lower()
    return re.sub(r"[^0-9a-zåäöéüæø]+", " ", text).strip()


def name_similarity(a: str | None, b: str | None) -> float:
    """
    0-1: hur troligt två källors namn avser samma evenemang.

    Två mått, det högsta vinner. Ordöverlapp fångar "Stevie Wonder at 3Arena" mot
    "Stevie Wonder: Songs In The Key of Life ..."; teckenlikhet fångar översättningar
    som "Piteå stråkkvartett" mot "Piteå String Quartet".
    """
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return 0.0
    ta = {w for w in na.split() if len(w) > 2 and w not in _NAME_STOP}
    tb = {w for w in nb.split() if len(w) > 2 and w not in _NAME_STOP}
    overlap = len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0
    return max(overlap, SequenceMatcher(None, na, nb).ratio())


def attribution(sources) -> str:
    present = set(sources)
    labels = [SOURCE_LABELS[s] for s in ("predicthq", "ticketmaster") if s in present]
    return "Evenemangsdata från " + " och ".join(labels) if labels else ""


def status_label(code: str | None) -> str:
    return STATUS_LABELS.get((code or "").lower(), "Planerat")


def is_happening(code: str | None) -> bool:
    return (code or "").lower() not in NOT_HAPPENING


def _duration_text(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min"


def finish(
    start_at: dt.datetime | None,
    source_end: dt.datetime | None,
    time_known: bool,
    category: str,
    multi_day: bool,
    predicted_end: dt.datetime | None = None,
    sport: str = "",
) -> tuple[dt.datetime | None, str, str]:
    """(sluttid, grund, förklaring). Källans sluttid, sedan PredictHQ:s förutsagda, sedan uppskattning."""
    if source_end and start_at and source_end > start_at:
        return source_end, BASIS_SOURCE, "Sluttid från källan."
    if not time_known or start_at is None:
        return None, BASIS_UNKNOWN, "Starttiden är inte satt, så sluttiden går inte att uppskatta."
    if multi_day:
        return None, BASIS_UNKNOWN, "Pågår flera dagar: ingen enskild sluttid."
    if predicted_end and predicted_end > start_at:
        return predicted_end, BASIS_PREDICTED, "Förutsagd av PredictHQ."
    minutes = TYPICAL_DURATION_MIN.get(category, TYPICAL_DURATION_MIN["ovrigt"])
    label = CATEGORY_LABELS.get(category, "evenemang").lower()
    if category == "sport" and sport in SPORT_DURATION_MIN:
        minutes, label = SPORT_DURATION_MIN[sport], SPORT_MATCH_LABEL[sport]
    return (
        start_at + dt.timedelta(minutes=minutes),
        BASIS_ESTIMATED,
        f"Uppskattad: {_duration_text(minutes)} efter start, standardlängd för {label}. Inte kalibrerad.",
    )


# -- Sport ----------------------------------------------------------------------
#
# Vilken sport ett sportevenemang är, så att föraren kan välja fotboll, ishockey eller
# handboll. Läses per källa: hos Ticketmaster är "Football" amerikansk fotboll och fotboll
# heter "Soccer"; PredictHQ har etiketter (soccer, ice-hockey, handball); TheSportsDB sätter
# strSport (Soccer, Ice Hockey, Handball; events/sources/thesportsdb.py).
SPORT_LABELS = {"fotboll": "Fotboll", "ishockey": "Ishockey", "handboll": "Handboll", "annan": "Annan sport"}
# Från avspark/nedsläpp till slutsignal, med paus: fotboll 2 x 45 + 15 + tillägg, ishockey 3 x 20
# + två pauser på 18 och stopptid, handboll 2 x 30 + 15 + timeouts. Okalibrerat, som resten.
SPORT_DURATION_MIN = {"fotboll": 115, "ishockey": 150, "handboll": 95}
SPORT_MATCH_LABEL = {"fotboll": "en fotbollsmatch med paus", "ishockey": "en hockeymatch med pauser",
                     "handboll": "en handbollsmatch med paus"}
_SPORT_WORDS = {
    "fotboll": re.compile(r"\b(soccer|fotboll|allsvenskan|superettan|damallsvenskan)\b"),
    "ishockey": re.compile(r"\b(ice[- ]hockey|hockey|ishockey|shl|sdhl|hockeyallsvenskan)\b"),
    "handboll": re.compile(r"\b(handball|handboll|handbollsligan)\b"),
}


def sport_for(source: str, category: str, genre: str = "", sub_genre: str = "", name: str = "") -> str:
    """Sportens nyckel i SPORT_LABELS, eller "" när evenemanget inte är sport."""
    if category != "sport":
        return ""
    tags = f"{genre} {sub_genre}".lower()
    for key, words in _SPORT_WORDS.items():
        if words.search(tags):
            return key
    # Namnet sist: "Allsvenskan - Hammarby vs Brommapojkarna" när etiketterna bara säger "sport".
    title = (name or "").lower()
    for key, words in _SPORT_WORDS.items():
        if words.search(title):
            return key
    return "annan"

