"""
Taxiläget: läge + omständigheter -> poäng, styrka och skälen föraren läser.

Frågan är förarens, inte trafikbolagets: står det folk som behöver taxi, och
hur troligt är det att de tar en? Två delar:

* **Läget** -- hur strandsatta är resenärerna? Räknas av källans regel
  (core/scoring.py för tåg, core/text_scoring.py för fritext) och kommer hit
  som ett `Situation`.
* **Omständigheterna** -- tid på dygnet och veckodag, rätt till ersättning,
  väder, stationens storlek. De gör en strandsatt resenär mer eller mindre
  benägen att ta taxi. De skapar aldrig ett läge.

Två hårda regler, båda skrivna för att föraren inte ska göra en bomresa:

1. **Stark kräver strandsättning** (`Situation.stranded`): inget alternativ
   inom en halvtimme. Omständigheter kan aldrig ensamma göra ett tips Starkt.
2. **Omständigheter räknas inte** när resenären har ett alternativ inom
   tio minuter eller ersättningstrafik står insatt, eller när läget är så
   svagt (under OMSTANDIGHET_MIN_BASE) att det inte finns något att förstärka.

Skälen (`Factor`) är det föraren ser i appen: korta meningar på enkel
svenska, både det som talar för och det som talar emot. Inga poäng, inga
källnamn. Föraren avgör.

Rena funktioner, inga databasanrop: testas i core/test_taxi_context.py.
Ändras en siffra här ska docs/betygsmetod.md ändras i samma commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Stockholm")

# --- Styrkan -----------------------------------------------------------------

# Samma gränser för alla källor. Stark kräver dessutom strandsättning.
STRONG_SCORE = 60
MEDIUM_SCORE = 35

# Omständigheterna får tillsammans höja högst så här mycket: de förstärker ett
# läge, de ersätter det inte.
CONTEXT_CAP = 20

# Under den här lägespoängen finns inget att förstärka. En enstaka inställd
# buss (20) blir inte en körning för att det råkar vara rusning.
CONTEXT_MIN_BASE = 25

# --- Omständigheterna --------------------------------------------------------

# (från, till) i lokal tid, halvöppet. Vardag = måndag-fredag; röda dagar
# räknas inte än (se docs/betygsmetod.md).
MORNING_RUSH = (6, 9)
MORNING_RUSH_BONUS = 8
AFTERNOON_RUSH = (15, 18)
AFTERNOON_RUSH_BONUS = 5
LATE_EVENING = (21, 24)
LATE_EVENING_BONUS = 6
NIGHT = (0, 5)
NIGHT_BONUS = 10

# Resenären får taxin betald (lag 2015:953). Den starkaste viljan att ta taxi
# som finns: det kostar dem ingenting.
COMPENSATION_BONUS = 8

# Väder. "Dåligt" är SMHI-gränserna i core/sources/smhi.py; "kraftigt" är
# det som får folk att låta bli att gå eller vänta ute.
WEATHER_BONUS = 4
SEVERE_WEATHER_BONUS = 10
SEVERE_PRECIP_MM_H = 3.0
SEVERE_PRECIP_PROBABILITY_PCT = 50
SEVERE_GUST_MS = 18
SEVERE_THUNDER_PCT = 50
SNOW_PRECIP_MM_H = 1.0
SNOW_FROZEN_PCT = 40

# Många resenärer på samma perrong.
BUSY_STATION_BONUS = 5


@dataclass(frozen=True)
class Factor:
    """En rad föraren läser. `sign`: "+" talar för, "-" talar emot."""

    text: str
    sign: str = "+"
    weight: int = 0
    # Vilken omständighet ("tid", "väder", "ersättning", "station"); tomt för
    # lägets egna skäl. Står först i motiveringen: "väder: Snöfall (+10)".
    kind: str = ""

    def as_dict(self) -> dict:
        return {"text": self.text, "sign": self.sign}


@dataclass
class Situation:
    """Läget, som källans regel såg det."""

    base: int
    stranded: bool
    confidence: str = "high"
    # Alternativ inom tio minuter, eller ersättningstrafik insatt: ingen
    # omständighet gör att de tar taxi.
    quick_alternative: bool = False
    # Hur länge resenären blir stående (glapp till nästa resa eller
    # försening), i minuter. Avgör rätten till ersättning. None = okänt.
    wait_minutes: int | None = None
    # Lägets egna skäl, i den ordning de ska läsas.
    factors: list[Factor] = field(default_factory=list)


@dataclass
class Outcome:
    score: int
    level: str
    factors: list[dict]
    reasons: list[str]


# --- Lägets skäl, formulerade på ett ställe ----------------------------------


def human_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} tim" if rest == 0 else f"{hours} tim {rest} min"


def wait_factor(minutes: int, what: str = "Nästa resa") -> Factor:
    """Glappet som det låter för någon som står på perrongen."""
    if minutes <= 10:
        return Factor(f"{what} går {human_minutes(minutes)} senare", "-", 30)
    if minutes <= 30:
        return Factor(f"{what} går {human_minutes(minutes)} senare", "-", 15)
    return Factor(f"{what} går först {human_minutes(minutes)} senare", "+", 30)


LAST_DEPARTURE = Factor("Sista avgången härifrån", "+", 40)
WHOLE_LINE_STOPPED = Factor("Hela linjen står still", "+", 35)
REPLACEMENT = Factor("Ersättningstrafik är insatt", "-", 30)
STATED_ALTERNATIVE = Factor("Trafikbolaget anvisar ett annat sätt att resa", "-", 20)
SINGLE_DEPARTURE = Factor("En enstaka avgång – nästa brukar gå snart", "-", 15)
UNCERTAIN = Factor("Oklart läge – bygger på trafikbolagets text", "-", 5)
UNKNOWN_NEXT = Factor("Okänt när nästa resa går", "-", 5)


def delay_factor(minutes: int) -> Factor:
    return Factor(f"Försenat {human_minutes(minutes)}", "+" if minutes >= 30 else "-", 20)


# --- Omständigheterna --------------------------------------------------------


def _in_window(hour: int, window: tuple[int, int]) -> bool:
    start, end = window
    return start <= hour < end


def time_factor(when: datetime | None) -> Factor | None:
    """Tid på dygnet och veckodag för den drabbade avgången."""
    if when is None:
        return None
    local = when.astimezone(LOCAL_TZ)
    hour, weekday = local.hour, local.weekday() < 5
    if _in_window(hour, NIGHT):
        return Factor("Natt – nästan inga andra sätt att ta sig hem", "+", NIGHT_BONUS, "tid")
    if _in_window(hour, LATE_EVENING):
        return Factor("Sent på kvällen – färre alternativ", "+", LATE_EVENING_BONUS, "tid")
    if weekday and _in_window(hour, MORNING_RUSH):
        return Factor("Morgon en vardag – folk ska till jobbet", "+", MORNING_RUSH_BONUS, "tid")
    if weekday and _in_window(hour, AFTERNOON_RUSH):
        return Factor("Eftermiddag en vardag – folk ska hem", "+", AFTERNOON_RUSH_BONUS, "tid")
    return None


def weather_factor(weather: dict | None) -> Factor | None:
    """Vädret där resenären står. Kraftigt väder väger mer än dåligt."""
    if not weather:
        return None
    precip = weather.get("precipitation_mm_h") or 0
    precip_pct = weather.get("precipitation_probability_pct") or 0
    frozen = weather.get("frozen_probability_pct") or 0
    gust = weather.get("wind_gust_ms")
    gust = gust if gust is not None else (weather.get("wind_speed_ms") or 0)
    thunder = weather.get("thunderstorm_probability_pct") or 0

    if precip >= SNOW_PRECIP_MM_H and frozen >= SNOW_FROZEN_PCT and precip_pct >= 40:
        return Factor("Snöfall", "+", SEVERE_WEATHER_BONUS, "väder")
    if precip >= SEVERE_PRECIP_MM_H and precip_pct >= SEVERE_PRECIP_PROBABILITY_PCT:
        return Factor("Kraftigt regn", "+", SEVERE_WEATHER_BONUS, "väder")
    if gust >= SEVERE_GUST_MS:
        return Factor("Hård blåst", "+", SEVERE_WEATHER_BONUS, "väder")
    if thunder >= SEVERE_THUNDER_PCT:
        return Factor("Åska", "+", SEVERE_WEATHER_BONUS, "väder")

    from core.sources.smhi import describe_weather, is_adverse_weather

    if is_adverse_weather(weather):
        text = describe_weather(weather) or "Dåligt väder"
        return Factor(text[:1].upper() + text[1:], "+", WEATHER_BONUS, "väder")
    return None


def compensation_factor(compensation: dict | None) -> Factor | None:
    if not compensation:
        return None
    cap = compensation.get("cap_kr")
    amount = f" (upp till {format_kr(cap)})" if cap else ""
    return Factor(f"Resenären kan få taxin betald{amount}", "+", COMPENSATION_BONUS, "ersättning")


def format_kr(amount: int) -> str:
    digits = f"{int(amount):,}".replace(",", " ")
    return f"{digits} kr"


def busy_station_factor(busy: bool) -> Factor | None:
    return Factor("Stor station – många resenärer", "+", BUSY_STATION_BONUS, "station") if busy else None


# --- Helheten ----------------------------------------------------------------


def final_level(
    score: int,
    stranded: bool,
    has_alternative: bool = False,
    confidence: str | None = None,
) -> str:
    """
    Stark / Medel / Svag, samma regel för alla källor.

    Stark kräver poäng OCH strandsättning OCH att vi är säkra. En osäker
    fritext ("allvarligt ordval, men otydligt") blir högst Medel tills
    någon (AI-granskningen eller föraren) bekräftat den.
    """
    if score <= 0 or has_alternative:
        return "low"
    if score >= STRONG_SCORE and stranded and confidence != "low":
        return "high"
    if score >= MEDIUM_SCORE:
        return "medium"
    return "low"


def assess(
    situation: Situation,
    *,
    when: datetime | None = None,
    weather: dict | None = None,
    compensation: dict | None = None,
    busy_station: bool = False,
    has_alternative: bool = False,
) -> Outcome:
    """
    Läge + omständigheter -> poäng, styrka och skäl.

    `compensation` ska redan vara prövad mot väntetiden (core/compensation.py);
    här avgörs bara om den får räknas som omständighet.
    """
    context: list[Factor] = []
    applies = (
        not situation.quick_alternative
        and not has_alternative
        and situation.base >= CONTEXT_MIN_BASE
    )
    for factor in (
        compensation_factor(compensation),
        time_factor(when),
        weather_factor(weather),
        busy_station_factor(busy_station),
    ):
        if factor is not None:
            context.append(factor)

    bonus = min(CONTEXT_CAP, sum(f.weight for f in context)) if applies else 0
    score = max(0, min(100, situation.base + bonus))
    level = final_level(score, situation.stranded, has_alternative, situation.confidence)

    # Det föraren läser: lägets egna skäl först (de avgör), sedan de
    # omständigheter som faktiskt räknades. Omständigheter som inte räknades
    # visas inte -- "Morgonrusning" på ett tips där nästa tåg går om fem
    # minuter vore att antyda något vi inte menar. Ersättningsrätten visas
    # däremot alltid när den finns: den är ett faktum för resenären.
    shown = list(situation.factors)
    if applies:
        shown += sorted(context, key=lambda f: -f.weight)
    else:
        shown += [f for f in context if f.kind == "ersättning"]
    factors = [f.as_dict() for f in _dedupe(shown)[:4]]

    reasons = [f"{f.sign} {f.text}" for f in situation.factors]
    if applies and context:
        reasons += [f"{f.kind}: {f.text} (+{f.weight})" for f in context]
        if bonus < sum(f.weight for f in context):
            reasons.append(f"omständigheter kapade till +{CONTEXT_CAP}")
    elif context:
        reasons.append("omständigheter räknas inte: alternativ finns eller läget är svagt")
    return Outcome(score=score, level=level, factors=factors, reasons=reasons)


def _dedupe(factors: list[Factor]) -> list[Factor]:
    seen: set[str] = set()
    out = []
    for f in factors:
        if f.text in seen:
            continue
        seen.add(f.text)
        out.append(f)
    return out
