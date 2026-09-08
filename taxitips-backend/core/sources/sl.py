"""
SL (Stockholm) deviations -> den delade normaliserade alert-formen.

Port av worker/src/sl.js. SL publicerar sin realtidsdata öppet -- ingen
nyckel, ingen kvot -- vilket är varför Stockholm (2,4 miljoner invånare)
kostar bara den här adaptern, ingen prenumeration.

Docs ber om högst ett anrop per minut; relevant först när ett schema för
återkommande polling finns (se planens "Explicitly out of scope").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import requests

DEVIATIONS_URL = "https://deviations.integration.sl.se/v1/messages"
# expand=true är bärande, inte en optimering: deviations refererar
# stop_areas, men en vanlig /sites-respons är nyckad på SITE-id -- ett annat
# id-rum (mätt: bara 14 av 104 refererade stop_area-id:n råkar kollidera med
# ett site-id). Den utökade responsen bär varje sites stop_areas[], vilket
# bygger bron för 104/104 av de refererade id:na.
SITES_URL = "https://transport.integration.sl.se/v1/sites?expand=true"

# SL:s `publish`-fönster är INTE störningens varaktighet -- det är hur länge
# MEDDELANDET är publicerat, och de två skiljer sig med år. Mätt mot
# live-flödet (158 deviations): 102 har ett publiceringsfönster längre än 30
# dagar, 34 publicerades första gången för över 90 dagar sedan. Bara 25 av
# 158 är både nya (<24h) och korta (<7d).
MAX_AGE = timedelta(hours=24)
MAX_WINDOW = timedelta(days=7)

# Kategorier som aldrig skapar taxibehov. En trasig hiss är ett verkligt
# tillgänglighetsproblem, men den strandar ingen -- resenären tar trappan
# eller nästa station. Mätt: 9 av 179 deviations är FACILITY/LIFT.
#
# De föll tidigare bort på åldersfiltret, alltså av tur snarare än av
# förståelse: ett FÄRSKT hissfel passerade rakt igenom och blev ett tips
# (verifierat -- "Avstängd hiss vid Skanstull" nådde flödet 2026-09-08).
IGNORED_CATEGORY_GROUPS = {"FACILITY"}


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_actionable(deviation: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(dt_timezone.utc)
    for category in deviation.get("categories") or []:
        group = str((category or {}).get("group") or "").upper()
        if group in IGNORED_CATEGORY_GROUPS:
            return False
    publish = deviation.get("publish") or {}
    start = _parse(publish.get("from"))
    upto = _parse(publish.get("upto"))
    if start is None:
        return False
    # Inte påbörjad än. SL:s publish.from ligger alltid i det förflutna på
    # live-data, så detta slår aldrig till idag -- men Västtrafik-flödet
    # bevisade att felläget är verkligt (10 av 19 där var framtidsdaterade),
    # och ett filter som bara fungerar av tur är inget filter.
    if start > now:
        return False
    if now - start > MAX_AGE:
        return False
    # Ett saknat `upto` tolkas som öppet slut (mätt: 0/158 saknar det, men
    # frånvaro får inte tyst betyda "kort").
    if upto is None:
        return False
    if upto - start > MAX_WINDOW:
        return False
    return upto > now


def pick_variant(variants: list[dict] | None) -> dict | None:
    items = variants or []
    sv = next((v for v in items if str(v.get("language") or "").lower().startswith("sv")), None)
    return sv or (items[0] if items else None)


def mode_hint_from(lines: list[dict] | None) -> str | None:
    """
    SL:s egen transport_mode är strukturell data, till skillnad från
    mode.py:s nyckelordsgissning. METRO/TRAM rapporteras som de är och
    fälls in i "train"-grenen av text_scoring.py -- en stoppad tunnelbana
    strandsätter folk precis som ett stoppat tåg.
    """
    modes = {str(l.get("transport_mode") or "").upper() for l in (lines or [])}
    modes.discard("")
    if not modes:
        return None
    if "METRO" in modes:
        return "metro"
    if "TRAIN" in modes:
        return "train"
    if "TRAM" in modes:
        return "tram"
    if "BUS" in modes:
        return "bus"
    return None


def normalize_deviation(deviation: dict, site_index: dict | None) -> dict | None:
    variant = pick_variant(deviation.get("message_variants"))
    if not variant:
        return None

    scope = deviation.get("scope") or {}
    stop_areas = scope.get("stop_areas") or []
    lines = scope.get("lines") or []

    areas = [s.get("name") for s in stop_areas if s.get("name")]
    routes = [str(l.get("designation")) for l in lines if l.get("designation")]
    stops = [str(s.get("id")) for s in stop_areas if s.get("id") is not None]

    # Mätt verklighet: de AGERBARA deviations (nya + tidsbegränsade)
    # refererar linjer, inte stop_areas -- 19/19 i ett live-urval namngav
    # noll stop_areas. De som namnger en stop_area är nästan uteslutande de
    # permanenta meddelanden den här filtreringen redan sållat bort. Så i
    # praktiken slår uppslaget sällan till idag, och de flesta Stockholms-
    # larm bär lat/lon = null -- det är det ärliga svaret, inte ett fel att
    # fixa här (en påhittad koordinat, t.ex. linjens första hållplats,
    # skulle skicka en förare till ett specifikt FEL gathörn).
    lat = None
    lon = None
    for area in stop_areas:
        site = (site_index or {}).get(str(area.get("id")))
        if site:
            lat, lon = site["lat"], site["lon"]
            break

    start = _parse(deviation.get("publish", {}).get("from"))
    upto = _parse(deviation.get("publish", {}).get("upto"))

    return {
        "id": f"sl:{deviation.get('deviation_case_id')}",
        "header": variant.get("header") or "Störning",
        "description": variant.get("details") or "",
        # SL har inga GTFS cause/effect-enum. Lämnas None hellre än
        # påhittat -- taxi_relevance.py läser dessa defensivt, och den
        # svenska texten bär signalen ändå (samma slutsats som Trafiklab).
        "cause": None,
        "effect": None,
        "areas": areas, "routes": routes, "stops": stops,
        # weblink finns inte i SL:s svar (0 av 159 i mätningen 2026-09-08,
        # fältet saknas helt i schemat). Läsningen står kvar för att den är
        # ofarlig och fältet är dokumenterat -- men den ger aldrig något
        # idag, och det ska inte se ut som om den gör det.
        "url": variant.get("weblink") or None,
        "active_from": start or datetime.now(dt_timezone.utc),
        "active_to": upto,
        "source": "sl",
        "region": "sl",
        "lat": lat, "lon": lon,
        "mode_hint": mode_hint_from(lines),
        # scope_alias ("Buss 803") är den enda linje-etiketten SL ger --
        # tidigare bara sparad i sl-bagaget nedan, aldrig visad. Samma
        # gemensamma fältnamn som Västtrafik använder, så popupen kan
        # rendera "linje" oavsett källa utan källspecifik kod.
        "route_label": variant.get("scope_alias"),
        # SL:s redaktionella prioritet. Medvetet INTE inmappad i
        # demand_score -- den rangordnar SL:s egna visningsytor, den mäter
        # inte taxiefterfrågan. text_scoring.py använder den bara för att
        # höja konfidens.
        "sl": {
            "importance_level": (deviation.get("priority") or {}).get("importance_level"),
            "influence_level": (deviation.get("priority") or {}).get("influence_level"),
            "urgency_level": (deviation.get("priority") or {}).get("urgency_level"),
            "scope_alias": variant.get("scope_alias"),
        },
    }


def fetch_sl_sites() -> list[dict]:
    """
    Hållplatsregistret: ~6500 hållplatser med koordinat, ingen nyckel.
    """
    res = requests.get(SITES_URL, headers={"Accept-Encoding": "gzip"}, timeout=30)
    if not res.ok:
        raise RuntimeError(f"sl-sites {res.status_code}: {res.text[:160]}")
    sites = res.json()

    # Deduplicerat på stop_area_id: registret listar genuint samma
    # hållplatsområde under fler än en site (en station och dess
    # bussterminal refererar varandra). Första skrivning vinner; de bär
    # samma koordinat ändå.
    seen: set[str] = set()
    rows = []
    for site in sites if isinstance(sites, list) else []:
        if not site or site.get("lat") is None or site.get("lon") is None:
            continue
        areas = site.get("stop_areas") or [site.get("id")]
        for area in areas:
            stop_area_id = str(area.get("id") if isinstance(area, dict) else area)
            if not stop_area_id or stop_area_id in seen:
                continue
            seen.add(stop_area_id)
            rows.append({
                "gid": stop_area_id,
                "operator": "sl",
                "name": site.get("name"),
                "lat": float(site["lat"]),
                "lon": float(site["lon"]),
                # Site-id:t, inte stop_area-id:t: departures-endpointen
                # nycklas på det förra, och de två id-rymderna kolliderar
                # bara i 14 av 104 fall (se SITES_URL-kommentaren).
                "site_id": str(site.get("id") or ""),
            })
    return rows


def build_site_index(rows: list[dict] | None) -> dict[str, dict]:
    """stop_area id -> {lat, lon, name, site_id}, formen normalize_deviation förväntar sig."""
    return {str(r["gid"]): r for r in (rows or [])}


DEPARTURES_URL = "https://transport.integration.sl.se/v1/sites/{site_id}/departures"

# Hur långt fram departures-endpointen tillfrågas. Två timmar räcker för
# frågan "går det något härifrån snart?" och håller svaret litet.
DEPARTURE_FORECAST_MINUTES = 120

# Stockholm är CET/CEST och SL:s departures-endpoint svarar med NAKNA
# tidsstämplar ("2026-09-08T18:42:00") medan deviations-endpointen svarar
# med tidszon. Jämförs de rakt av blir felet en eller två timmar -- alltid
# åt hållet som får en avgång att se närmare ut än den är.
STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _parse_naive_local(value: str | None) -> datetime | None:
    dt = _parse(value)
    if dt is None:
        return None
    return dt.replace(tzinfo=STOCKHOLM) if dt.tzinfo is None else dt


def fetch_site_departures(site_id: str, forecast_minutes: int | None = None) -> list[dict]:
    """Kommande avgångar från en hållplats. Ingen nyckel, ingen kvot."""
    res = requests.get(
        DEPARTURES_URL.format(site_id=site_id),
        params={"forecast": forecast_minutes or DEPARTURE_FORECAST_MINUTES},
        headers={"Accept-Encoding": "gzip"},
        timeout=20,
    )
    if not res.ok:
        raise RuntimeError(f"sl-departures {res.status_code}: {res.text[:120]}")
    payload = res.json()
    return payload.get("departures") or []


def next_departure(
    departures: list[dict],
    *,
    stop_area_id: str | None = None,
    line: str | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """
    Nästa avgång som faktiskt går, på samma linje och hållplats.

    Inställda avgångar räknas inte -- det är hela poängen: en resenär vars
    buss ställts in hjälps inte av att nästa också är inställd.

    Returnerar bara tidpunkten. `is_last_departure` sätts medvetet ALDRIG
    härifrån: endpointen svarar bara för ett fönster framåt, så "inga fler
    avgångar" betyder "inga inom två timmar", inte "sista turen idag". Att
    blanda ihop dem hade gett det starkaste beskedet vi har på svagast
    grund.
    """
    now = now or datetime.now(dt_timezone.utc)
    best: datetime | None = None
    for d in departures:
        if str(d.get("state") or "").upper() == "CANCELLED":
            continue
        if stop_area_id and str((d.get("stop_area") or {}).get("id")) != str(stop_area_id):
            continue
        if line and str((d.get("line") or {}).get("designation") or "") != str(line):
            continue
        when = _parse_naive_local(d.get("expected") or d.get("scheduled"))
        if when and when > now and (best is None or when < best):
            best = when
    return best


def fetch_sl_deviations(site_index: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(dt_timezone.utc)
    res = requests.get(DEVIATIONS_URL, headers={"Accept-Encoding": "gzip"}, timeout=30)
    if not res.ok:
        raise RuntimeError(f"sl-deviations {res.status_code}: {res.text[:160]}")
    raw = res.json()
    all_deviations = raw if isinstance(raw, list) else []

    alerts = []
    for deviation in all_deviations:
        if not is_actionable(deviation, now):
            continue
        alert = normalize_deviation(deviation, site_index)
        if alert:
            alerts.append(alert)

    return {"alerts": alerts, "source": "sl", "received": len(all_deviations), "actionable": len(alerts)}


# Hur många hållplatser som frågas per cykel. SL:s dokumentation ber om
# högst ett anrop per minut mot deviations; departures är en annan
# endpoint, men måtta är ändå rätt: de agerbara larmen är sällan fler än
# ett tjugotal, och ett tak gör att en dålig dag inte blir en skur av anrop.
MAX_DEPARTURE_LOOKUPS = 20


def enrich_next_departures(
    alerts: list[dict],
    site_index: dict | None,
    now: datetime | None = None,
    fetch=fetch_site_departures,
) -> int:
    """
    Fyller `next_departure_at` på de SL-larm där frågan går att besvara.

    Stockholm hade tidigare inget svar alls på "när går nästa?" -- SL:s
    avvikelsetext bär ingen tidtabell. Det gör däremot
    /v1/sites/{id}/departures, utan nyckel och utan kvot, och kombinationen
    "larmet säger att linje 4 är inställd vid Slussen" + "endpointen säger
    när nästa 4:a går därifrån" ger exakt den signal järnvägen redan har.

    Kräver BÅDE hållplats och linje. Utan linjen vore svaret "något går
    härifrån om 3 minuter", vilket är sant och oanvändbart: det kan vara en
    buss åt fel håll. Returnerar antalet larm som fick ett svar.
    """
    now = now or datetime.now(dt_timezone.utc)
    filled = 0
    cache: dict[str, list[dict]] = {}

    for alert in alerts:
        stops = alert.get("stops") or []
        routes = alert.get("routes") or []
        if not stops or not routes:
            continue

        for stop_area_id in stops:
            site = (site_index or {}).get(str(stop_area_id)) or {}
            site_id = str(site.get("site_id") or "")
            if not site_id:
                continue
            if site_id not in cache:
                if len(cache) >= MAX_DEPARTURE_LOOKUPS:
                    return filled
                try:
                    cache[site_id] = fetch(site_id)
                except Exception:
                    # En hållplats som inte svarar får inte stoppa cykeln --
                    # tipset skrivs ändå, bara utan avgångsbesked.
                    cache[site_id] = []
            when = next_departure(
                cache[site_id], stop_area_id=stop_area_id, line=routes[0], now=now
            )
            if when:
                alert["next_departure_at"] = when
                alert["next_departure_minutes"] = round((when - now).total_seconds() / 60)
                filled += 1
                break
    return filled
