"""
Tröskelvärdena, på ett ställe.

Det här är hela poängen med Spår B. Talet 50 fanns i fyra kopior över tre
språk -- `fcmPush.js`, `severity_labels.dart`, `api_client.dart`,
`viz/server.js` -- utan att något höll ihop dem (se schema/constants.md,
som `dump_truth` genererar). Marknadsradien 150 km och 24-timmarsfönstret
fanns dessutom bara inuti `get_smart_alerts`, en plpgsql-funktion som
omdefinierats sju gånger.

Härifrån bor de i Python, serveras av `/api/config` och läses av appen.
En förändring här ska synas i förarens telefon utan att någon rör Dart.
"""

from __future__ import annotations

from core.geo import REGION_ANCHOR, haversine_km, resolve_place_coords

# Poänggränsen där ett tips är värt att buzza en telefon. Samma tal som
# fcmPush.js NOTIFY_SCORE_FLOOR och samma tal som lyfter en inställd avgång
# till "hög" nedan -- avsiktligt EN konstant: det som väcker en förare mitt
# i natten och det som visas som starkt på kortet ska vara samma bedömning.
NOTIFY_SCORE_FLOOR = 50

# Marknadshorisont, inte en poängjustering. Avståndet påverkar aldrig
# poängen (se 20260905000006_drop_reachability_from_score.sql) -- men ett
# Göteborgståg 400 km bort är inte en Stockholmsförares affär över huvud
# taget, och ska därför inte nå listan alls.
MARKET_RADIUS_KM = 150

# Hur långt bakåt flödet visar. Störningen är över, men frågan "vad hände
# i natt?" är fortfarande relevant för en förare som börjar sitt pass.
FEED_LOOKBACK_HOURS = 24

# Vilka tiers som faktiskt strandar folk. Vägtiers är medvetet uteslutna:
# en olycka försenar dem som redan sitter i bil, den lämnar ingen
# fotgängare utan transport. Samma uppdelning som severity_labels.dart
# gjorde -- skillnaden är att den nu bara finns här.
HIGH_SEVERITY_TIERS = frozenset({"line_paused"})
MEDIUM_SEVERITY_TIERS = frozenset(
    {"line_delayed", "vehicle_cancelled", "arrival_wave", "last_arrival"}
)

# Vilka tiers som ÖVER HUVUD TAGET får väcka en telefon. Strängare än vad
# som får synas i listan, med avsikt: en push avbryter en förare som kan
# sitta mitt i en körning eller i trafiken, medan listan bara ligger där
# tills någon tittar.
#
# `severity_tier` ensam räcker inte som grind -- "vehicle_cancelled" spänner
# från ett inställt tåg med en perrong full av folk till en enstaka svag
# kvällsbuss -- därför gäller BÅDE den här mängden OCH NOTIFY_SCORE_FLOOR.
# Mätt i Node-versionen: utan poänggolvet hade ~64% av notiserna varit "en
# buss är sen", precis den signal poängsättningen kapar vid 25 för att
# hålla den i listans botten.
#
# Flyttad hit från fcmPush.js NOTIFY_WORTHY_TIERS: talet 50 hade fyra hem
# innan den här filen fanns, och den här mängden hade två (fcmPush.js och
# api_client.darts notifyTypeCatalog). Lägg inte till ett tredje.
# "arrival_wave" saknas här MED AVSIKT. Ankomstvågen syns i listan och i
# pipelinevyn, men väcker ingen förare förrän tröskeln per flygplats är
# kalibrerad mot fler än ett dygns mätning -- en push mitt i natten på en
# ojusterad signal är precis det golvet ovan finns för att förhindra. Att slå
# på den när volymerna sett rimliga ut i några dygn är den här raden.
NOTIFY_WORTHY_TIERS = frozenset(
    {"line_paused", "vehicle_cancelled", "road_accident_or_closure"}
)


# ---------------------------------------------------------------------------
# Flyg (Swedavia FlightInfo v2)
# ---------------------------------------------------------------------------
#
# Signalen är INTE "ett plan är försenat" utan "många landar samtidigt när
# kollektivtrafiken tunnats ut". Ett enskilt plan är ingen störning; klustret
# är hela poängen, och enheten är därför fönstret, inte flyget.
#
# Mätt mot riktiga svar 2026-09-12: den ursprungliga idén -- fler än tre flyg
# minst 40 min försenade i samma 30-minutersfönster -- utlöste noll gånger på
# ett dygn (som mest två i samma fönster, tio sena över hela dygnet). Samtidigt
# landade tolv plan i fönstret 23:30 och åtta i 23:00. Volymen bär signalen,
# förseningen förstärker den.

# Fönsterbredden. 30 minuter är ungefär så länge en ankomsthall håller ihop
# som en kö: kortare och samma våg splittras på två tips, längre och två
# orelaterade vågor slås ihop.
FLIGHT_WINDOW_MINUTES = 30

# Vad som räknas som försenat. Ditt tal, behållet: under 40 minuter hinner
# resenären fortfarande med sin planerade anslutning.
FLIGHT_DELAY_MINUTES = 40

# Timmar (lokal tid) då en ankomstvåg över huvud taget är taxirelevant. Mitt
# på dagen finns full kollektivtrafik och ingen står strandsatt, hur många
# plan som än landar. Halvöppet intervall som korsar midnatt.
FLIGHT_LATE_HOUR_FROM = 21
FLIGHT_LATE_HOUR_TO = 6

# Extra påslag för de timmar då tåg och buss faktiskt tunnats ut. Ett PÅSLAG,
# aldrig ett påstående: vi har ingen tidtabell för Arlanda Express eller
# flygbussarna, och får därför inte skriva "sista tåget har gått" i motiveringen
# (invariant 2 -- vi hittar aldrig på ett alternativ).
FLIGHT_NIGHT_HOUR_FROM = 23
FLIGHT_NIGHT_HOUR_TO = 3
FLIGHT_NIGHT_BONUS = 10

# Poängtrappan. Basen utgår från flygplatsens egen tröskel så att ett fullt
# fönster på Malmö Airport och ett fullt fönster på Arlanda blir jämförbara
# tal trots att volymerna skiljer en tiopotens.
FLIGHT_BASE_SCORE = 45
FLIGHT_SCORE_PER_EXTRA_ARRIVAL = 5
FLIGHT_SCORE_PER_DELAYED = 6
FLIGHT_DELAY_BONUS_CAP = 18

# Fönster längre fram än så bygger på ren tidtabell -- inga estimat har
# publicerats än -- och skrivs därför med confidence=low.
FLIGHT_HORIZON_HOURS = 6

# Kvotvakt. FlightInfo Free ger 10 001 anrop / 30 dagar och exponerar inga
# kvot-headers (verifierat mot /heartBeat), så räkningen måste ske här. Taket
# ligger med marginal under det riktiga: en pollare som slår i väggen mitt i
# månaden är värre än en som slutar lite för tidigt.
FLIGHT_MONTHLY_CALL_BUDGET = 9000

# Två regler, för att Sverige har två sorters flygplats
# ---------------------------------------------------------------------------
# Mätt mot riktiga svar för lördag 2026-09-12 och måndag 2026-09-14, alla tio
# Swedavia-flygplatser (de fyra icke-Swedavia -- Västerås, Örebro, Skavsta,
# Ängelholm -- svarar 400 och ingår inte i prenumerationen):
#
#     ARN  326 flyg/vardag, som mest 11 ankomster i ett sent fönster
#     GOT   68 flyg/vardag, som mest  3
#     övriga åtta: 3-15 flyg/dygn, ALDRIG mer än 2 i samma halvtimme
#
# På de åtta små existerar ingen ankomstvåg. Men sista planet till Kiruna
# 23:00 är ändå hela nattens taxiunderlag på den orten -- en annan signal, inte
# en svagare. Därför två regler:
#
#   RULE_WAVE          N ankomster i samma halvtimme (ARN, GOT)
#   RULE_LAST_ARRIVAL  en ankomst utan fler inom FLIGHT_ISOLATION_HOURS
#
# Den andra säger något vi faktiskt kan belägga ur tidtabellen: "inget mer
# plan landar här på minst två timmar". Den säger däremot ALDRIG att bussen
# slutat gå -- det vet vi inte (invariant 2).
RULE_WAVE = "wave"
RULE_LAST_ARRIVAL = "last_arrival"

# Hur länge det ska vara tomt efter ett plan för att det ska räknas som sista.
# Två timmar är ungefär när en ankomsthall verkligen töms: kortare och en
# normal lucka mellan två kvällsplan hade räknats som "sista", längre och
# kvällens verkliga sista plan hade missats på de flygplatser som stänger 23.
FLIGHT_ISOLATION_HOURS = 2

# Poängtrappan för sista-ankomsten. Lägre bas än en våg, med avsikt: ett plan
# är färre resenärer än åtta. Att den ändå är värd ett tips beror på att ingen
# annan lämnar flygplatsen efter den.
FLIGHT_LAST_ARRIVAL_BASE = 40
FLIGHT_LAST_ARRIVAL_PER_EXTRA = 6

# Flygplatserna. `rule` avgör vilken av de två som gäller, `cadence` hur ofta
# den hämtas (se CADENCE nedan).
#
# `region` knyter tipset till en marknad som finns i geo.REGION_ANCHOR, och
# `city` måste vara en ort i REGION_CITIES för den regionen -- annars filtrerar
# förarens ortsval bort tipset (core/notify.py matchar ortnamnet som delsträng
# mot opportunity.places).
#
# region=None för Luleå, Umeå, Kiruna och Östersund är inte en lucka utan ett
# svar: Norrbotten, Västerbotten och Jämtland har ingen kollektivtrafikoperatör
# i pipelinen (core/coverage.py listar dem med operator=None), så det finns
# ingen marknadsnyckel att sätta. NULL, aldrig tom sträng -- invariant 5. Tipset
# når ändå föraren, eftersom flygtips alltid har en koordinat och därmed
# stängslas av 150-kilometersgränsen i stället för av regionen.
AIRPORTS: dict[str, dict] = {
    "ARN": {
        "name": "Stockholm Arlanda", "region": "sl", "city": "Stockholm",
        "lat": 59.6519, "lon": 17.9186,
        "rule": RULE_WAVE, "wave_min": 8, "cadence": "major",
    },
    "GOT": {
        "name": "Göteborg Landvetter", "region": "vt", "city": "Göteborg",
        "lat": 57.6628, "lon": 12.2798,
        "rule": RULE_WAVE, "wave_min": 3, "cadence": "mid",
    },
    # Bromma hade 1 flyg på lördagen och 10 på måndagen, inget av dem sent.
    # Den ligger med ändå: den är Swedavias, den kostar tio anrop om dygnet,
    # och en flygplats som saknas i listan kan aldrig visa att den är tom.
    "BMA": {
        "name": "Stockholm Bromma", "region": "sl", "city": "Stockholm",
        "lat": 59.3544, "lon": 17.9416,
        "rule": RULE_LAST_ARRIVAL, "cadence": "minor",
    },
    "MMX": {
        "name": "Malmö Airport", "region": "skane", "city": "Malmö",
        "lat": 55.5363, "lon": 13.3762,
        "rule": RULE_LAST_ARRIVAL, "cadence": "minor",
    },
    "LLA": {
        "name": "Luleå Airport", "region": None, "city": "Luleå",
        "lat": 65.5438, "lon": 22.1220,
        "rule": RULE_LAST_ARRIVAL, "cadence": "minor",
    },
    "UME": {
        "name": "Umeå Airport", "region": None, "city": "Umeå",
        "lat": 63.7918, "lon": 20.2828,
        "rule": RULE_LAST_ARRIVAL, "cadence": "minor",
    },
    "VBY": {
        "name": "Visby Airport", "region": "gotland", "city": "Visby",
        "lat": 57.6627, "lon": 18.3462,
        "rule": RULE_LAST_ARRIVAL, "cadence": "minor",
    },
    "KRN": {
        "name": "Kiruna Airport", "region": None, "city": "Kiruna",
        "lat": 67.8221, "lon": 20.3368,
        "rule": RULE_LAST_ARRIVAL, "cadence": "minor",
    },
    "RNB": {
        "name": "Ronneby Airport", "region": "blekinge", "city": "Ronneby",
        "lat": 56.2567, "lon": 15.2650,
        "rule": RULE_LAST_ARRIVAL, "cadence": "minor",
    },
    "OSD": {
        "name": "Åre Östersund Airport", "region": None, "city": "Östersund",
        "lat": 63.1944, "lon": 14.5003,
        "rule": RULE_LAST_ARRIVAL, "cadence": "minor",
    },
}

# Kadenserna, satta av kvoten snarare än av önskemål.
#
# 10 001 anrop / 30 dagar = 333 per dygn för ALLA flygplatser tillsammans.
# Fördelningen nedan ger ~228/dygn (~6 840 per 30 dagar, 76 % av budgeten) och
# lämnar plats för manuella --force-körningar:
#
#     ARN (major)   ~89/dygn      GOT (mid)  ~59/dygn
#     8 x minor     ~10/dygn var = ~80/dygn
#
# De små hämtas nästan bara i kvällsfönstret. Deras tidtabell rör sig inte --
# tre flyg om dygnet i Kiruna ändrar sig inte var tionde minut -- så dagtid
# räcker var sjätte timme för att veta när sista planet går.
CADENCE: dict[str, dict] = {
    "major": {"busy": (16, 2), "busy_minutes": 10, "quiet_minutes": 45},
    "mid": {"busy": (16, 2), "busy_minutes": 15, "quiet_minutes": 60},
    "minor": {"busy": (20, 1), "busy_minutes": 90, "quiet_minutes": 360},
}

# Från den här timmen hämtas även MORGONDAGENS datum. Sökvägens {date} är
# lokalt datum, så ett fönster efter midnatt ligger i nästa dags svar -- utan
# den här hämtningen hade natten 00:00-05:59 varit osynlig varje kväll.
# Morgondagen hämtas alltid med den glesa kadensen: tidtabellen för imorgon
# ändrar sig inte var tionde minut.
FLIGHT_TOMORROW_HOUR_FROM = 21


def in_hour_window(hour: int, start: int, end: int) -> bool:
    """
    Ligger `hour` i [start, end)? Hanterar intervall som korsar midnatt.

    Finns här och inte i tre kopior i flight_scoring/poll_flights: varje
    flygfönster i den här filen korsar midnatt, och en avrundning åt fel håll
    hade tyst flyttat hela kvällssignalen en timme.
    """
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def is_flight_late_hour(hour: int) -> bool:
    return in_hour_window(hour, FLIGHT_LATE_HOUR_FROM, FLIGHT_LATE_HOUR_TO)


def is_flight_night_hour(hour: int) -> bool:
    return in_hour_window(hour, FLIGHT_NIGHT_HOUR_FROM, FLIGHT_NIGHT_HOUR_TO)


def flight_poll_interval_minutes(iata: str, hour: int) -> int:
    """Hur ofta flygplatsen ska hämtas den här timmen."""
    cadence = CADENCE[AIRPORTS[iata]["cadence"]]
    if in_hour_window(hour, *cadence["busy"]):
        return cadence["busy_minutes"]
    return cadence["quiet_minutes"]


def flight_calls_per_day(iata: str) -> float:
    """
    Uppskattat antal anrop per dygn, inklusive morgondagens datum på kvällen.

    Finns för att budgeten ska gå att kontrollera i ett test i stället för i
    ett kommentarsfält som tyst blir fel när någon ändrar en kadens.
    """
    calls = sum(60 / flight_poll_interval_minutes(iata, h) for h in range(24))
    tomorrow_hours = 24 - FLIGHT_TOMORROW_HOUR_FROM
    quiet = CADENCE[AIRPORTS[iata]["cadence"]]["quiet_minutes"]
    return calls + tomorrow_hours * 60 / quiet


def is_notify_worthy(
    severity_tier: str | None,
    demand_score: int | None,
    has_alternative: bool = False,
) -> bool:
    """
    Får det här tipset väcka en telefon alls? (Före förarens egna val.)

    `has_alternative` stänger notisen men INTE tipset. Skillnaden är
    avsiktlig: kortet ligger kvar i listan med sin poäng och sin
    ersättningstrafik utskriven, så en förare som ändå tittar får se det och
    döma själv -- men ingen väcks för det.

    Mätt på de fjorton kandidaterna i den lokala databasen: **sex av dem bar
    `has_alternative=True`**, alltså återkommande ersättningsbusstrafik som
    källan själv skrivit ut ("Bussar ersätter spårvagnarna mellan Käppala och
    Gåshaga brygga på vardagar under rusningstid"). Ingen står strandsatt
    där. En förare som kör dit gör en bomresa -- exakt det invariant 2 i
    AGENTS.md är skriven för att förhindra.

    Signalen är stated data, inte en tolkning: den kommer från Trafikverkets
    ReplacementTraffic eller ur källans egen text (core/alternatives.py), och
    är tom när källan inte sagt något. Vi hittar aldrig på ett alternativ,
    och tystnad räknas därför aldrig som "det finns ersättning".
    """
    if severity_tier not in NOTIFY_WORTHY_TIERS:
        return False
    if has_alternative:
        return False
    return (demand_score or 0) >= NOTIFY_SCORE_FLOOR


def customer_likelihood(
    severity_tier: str | None,
    demand_score: int,
    worth_it_score: int,
    has_alternative: bool = False,
) -> str:
    """
    "Hur troligt är det att det står folk här" -- high/medium/low.

    Port av severity_labels.darts customerLikelihood(). Flyttad hit av
    samma skäl som poängreglerna: bedömningen ska göras en gång, av den som
    har datan, inte räknas om i varje klient som råkar visa samma tips.

    `has_alternative` sänker till low: källan har själv skrivit ut
    ersättningstrafik, så resenären har redan ett alternativ. Utan den
    här grinden fylldes "Bara hög prio" av planerade ombyggnader ("bussar
    ersätter spårvagnarna … till oktober") där ingen står strandsatt.
    Kortet ligger kvar i listan -- det är bara färgen/filtret som ska
    spegla verkligheten (samma resonemang som is_notify_worthy).
    """
    if worth_it_score <= 0:
        return "low"
    if has_alternative:
        return "low"
    if severity_tier in HIGH_SEVERITY_TIERS:
        return "high"
    if severity_tier in MEDIUM_SEVERITY_TIERS:
        # En inställd avgång spänner från ett strandsatt tågperrong-fullt
        # med folk till en enstaka svag avgång. Låt poängen lyfta den, med
        # samma golv som pushen använder.
        if severity_tier == "vehicle_cancelled" and demand_score >= NOTIFY_SCORE_FLOOR:
            return "high"
        return "medium"
    return "low"


def market_region(lat: float | None, lon: float | None) -> str | None:
    """
    Vilken marknad föraren står i, som regionnyckel (skane/sl/vt/ul/...).

    Används BARA för att placera tips som saknar egen koordinat -- allt som
    har en koordinat stängslas av avståndet i stället.

    `get_smart_alerts` hade tre hårdkodade lat/lon-rutor (Skåne, Stockholm,
    Göteborg). Det betydde att en förare i Falun eller Umeå aldrig såg ett
    enda koordinatlöst tips, tyst, oavsett MARKET_SCOPE=national. Här
    härleds marknaden i stället ur REGION_ANCHOR -- samma nycklar som
    pipelinen redan skriver i `region` -- så alla femton regioner fungerar.
    """
    if lat is None or lon is None:
        return None

    best: tuple[float, str] | None = None
    for region, city in REGION_ANCHOR.items():
        geo = resolve_place_coords(city)
        if not geo:
            continue
        km = haversine_km(lat, lon, geo["lat"], geo["lon"])
        if km <= MARKET_RADIUS_KM and (best is None or km < best[0]):
            best = (km, region)
    return best[1] if best else None


def as_config() -> dict:
    """Det appen och visualiseraren läser i stället för egna kopior."""
    return {
        "notifyScoreFloor": NOTIFY_SCORE_FLOOR,
        "marketRadiusKm": MARKET_RADIUS_KM,
        "feedLookbackHours": FEED_LOOKBACK_HOURS,
        "highSeverityTiers": sorted(HIGH_SEVERITY_TIERS),
        "mediumSeverityTiers": sorted(MEDIUM_SEVERITY_TIERS),
        "notifyWorthyTiers": sorted(NOTIFY_WORTHY_TIERS),
        "flightWindowMinutes": FLIGHT_WINDOW_MINUTES,
        "flightDelayMinutes": FLIGHT_DELAY_MINUTES,
        "flightAirports": {
            iata: {
                "name": a["name"], "region": a["region"],
                "rule": a["rule"], "waveMin": a.get("wave_min"),
            }
            for iata, a in AIRPORTS.items()
        },
    }


# --- Källhälsa (core/pipeline_health.py) ------------------------------------
#
# Hur gammal den senaste LYCKADE hämtningen får vara innan källan räknas som
# inaktuell. Ungefär tre missade rundor: en enstaka timeout är vardag, tre i
# rad är ett avbrott. SMHI saknas med avsikt -- den hämtas inuti de andra
# pollarna och har ingen egen rad.
SOURCE_MAX_AGE_MINUTES: dict[str, int] = {
    # Beat var 90:e sekund; en Trafiklab-runda över femton operatörer tar upp
    # mot en minut.
    "trafikverket_rail": 6,
    "trafiklab": 6,
    "sl": 6,
    "vt": 6,
    "trafikverket": 6,
    # Beat var femte minut. En runda där ingen flygplats är mogen räknas som
    # lyckad: kadensen är avsiktlig, inte ett avbrott.
    "swedavia": 20,
    # Lyssnaren skriver status varje minut medan den tar emot meddelanden.
    "aisstream": 5,
    # Var sjätte timme; en missad runda tolereras.
    "ticketmaster": 13 * 60,
}

# Kärnkällorna: utan dem finns ingen produkt, och bara de gör /health/pipeline
# röd. Flyg, väg, evenemang och fartyg är tillägg -- ingen valfri källa får
# blockera kärnappen.
CORE_SOURCES = frozenset({"trafikverket_rail", "trafiklab", "sl", "vt"})

# Beat schemalägger hjärtslaget varje minut; tre missade betyder att beat,
# Redis eller alla workers står still.
HEARTBEAT_SOURCE = "pipeline_heartbeat"
HEARTBEAT_INTERVAL_SECONDS = 60
HEARTBEAT_MAX_AGE_SECONDS = 180


# Vilka väghändelser föraren ser -- i Väg-läget, på kartan och i antalen.
#
# Bara trafikolyckor (beslut 2026-09-21). Mätt samma dag i Skåne, Halland och
# Västra Götaland: 1 570 aktiva väghändelser, varav 546 körfältsavstängningar och
# ~900 vägarbeten, de flesta planerade och veckor gamla. Ett första urval med
# avstängda vägar, köer och stora störningar på huvudled gav 98 -- fortfarande
# mest planerade avstängningar. En olycka är det föraren inte kan veta om i
# förväg. Klassningen i core/text_scoring.road_tier är kvar (villkoret står i
# rule_id, road.<nivå>.<villkor>), så varje dold händelse går att förklara.
ROAD_SHOWN_CONDITIONS = frozenset({"accident"})


def road_shown(rule_id: str | None) -> bool:
    """Visas väghändelsen för föraren? Avgörs av villkoret i rule_id."""
    parts = (rule_id or "").split(".")
    return len(parts) == 3 and parts[0] == "road" and parts[2] in ROAD_SHOWN_CONDITIONS


# Huvudled: E-vägar, riksvägar (1-99) och primära länsvägar (100-499) -- samma
# gräns som Trafikverkets numrering drar. Sekundära länsvägar (500+) räknas inte.
ROAD_MAIN_ROAD_MAX_NUMBER = 499
# Akuta hinder (Trafikverkets MessageCode, gemener) som visas på huvudled. Kort
# livslängd och ofta oannonserade -- därför värda en blick även utan olycka.
ROAD_HAZARD_CAUSES = frozenset({
    "fordonshaveri", "fordonsfel", "bärgning", "djur på vägen", "föremål på vägen",
    "nedfallet träd", "faror på vägen", "hinder på vägbanan", "olja på vägen",
    "människor på vägen", "långsamtgående fordon", "evenemang",
})

# Hur många väghändelser förarflödet skickar som sammanhang. Mätt 2026-09-13: med
# alla situationer hämtade var `context` 400-1 200 rader och 0,4-1,3 MB per svar.
# Sedan bara olyckorna skickas (ROAD_SHOWN_CONDITIONS ovan) är de en handfull, så
# taket rymmer dem alla: tipslistan och Väg-läget visar då samma väghändelser och
# samma antal. Taket skyddar bara mot en förare med hela landet.
FEED_CONTEXT_LIMIT = 300
# Taket när appen ber om alla väghändelser (`road=all`, Väg-läget). Mätt
# 2026-09-21: 1 800 samtidiga i Skåne, Halland och Västra Götaland. Taket
# skyddar telefonen om Trafikverket skulle skicka ett helt land på en gång.
FEED_CONTEXT_FULL_LIMIT = 3000
