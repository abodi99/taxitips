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
MEDIUM_SEVERITY_TIERS = frozenset({"line_delayed", "vehicle_cancelled"})


def customer_likelihood(
    severity_tier: str | None, demand_score: int, worth_it_score: int
) -> str:
    """
    "Hur troligt är det att det står folk här" -- high/medium/low.

    Port av severity_labels.darts customerLikelihood(). Flyttad hit av
    samma skäl som poängreglerna: bedömningen ska göras en gång, av den som
    har datan, inte räknas om i varje klient som råkar visa samma tips.
    """
    if worth_it_score <= 0:
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
    }
