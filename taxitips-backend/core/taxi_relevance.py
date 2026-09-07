"""
Rankar störningar efter nytta för taxiförare.

Port av worker/src/taxiRelevance.js -- bara den logik som faktiskt matas av
en källa som finns i Django-portens Fas 1 (Trafiklab, textbaserade
transitlarm). Medvetet UTELÄMNAT mot originalet:

- scoreRoadAlert: ingen vägkälla är portad än, inget matar den.
- calculateDemandSignal (h3/"Last Train Risk"): dött kod i originalet --
  bifogad EFTER modulens egna module.exports, läser ett fält
  ("Last Train Risk") som filens egen kommentar säger aldrig triggade.
  poll_rail.py satte redan precedenset att inte porta detta (h3_index="").
- filterForTaxi/isTaxiNotifyWorthy: konsumeras av ett push/notis-steg som
  inte finns i Django än.

Princip: visa bara när folk faktiskt kan behöva skjuts -- inställda tåg,
stora störningar, ersättningsbuss, olycka, m.m. Ignorera stationsservice
(hiss, toalett, cykel, ...).
"""

from __future__ import annotations

import re

from core.geo import find_hubs_in_text, resolve_place_coords
from core.market import alert_in_market, is_national_scope, place_looks_skane

# Station/info utan taxinytta -- även om rubriken nämner en station.
NOISE_RE = re.compile(
    r"(hiss(en|ar|arna)?|rulltrapp|rullstol|toalett|cykel|cyklar|wifi|wi-?fi|"
    r"biljettautomat|biljettmaskin|entr[eé]|assistans|assistent|ledsag|"
    r"plattformsavvisare|platsbrist|kort tåg|nya spår)",
    re.IGNORECASE,
)

_SV = "a-zà-öø-ÿ0-9"

# Allvarliga kollektivstörningar som brukar ge taxibehov.
SERIOUS_RE = re.compile(
    rf"(?<![{_SV}])(inställd|inställt|inställda|ställs in|inga avgångar|"
    r"ingen trafik|trafikstopp|stopp i (trafiken|tågtrafiken|busstrafiken)|"
    r"totalt stopp|stora störningar|stora förseningar|ersättningsbuss|"
    r"ersättningstrafik|strejk|nedrivning|strömavbrott|växelfel|"
    r"signalproblem|tågtrafik (står|stoppad|inställd)|"
    r"alla (pågatåg|öresundståg|tåg) (är )?inställda|avgång(ar)? inställd|"
    r"inställd avgång|tåg(en)? (går|kör) inte|banan (är )?avstängd)"
    rf"(?![{_SV}])",
    re.IGNORECASE,
)

# Medel -- kan ge efterfrågan men inte alltid "kör hit nu".
MEDIUM_RE = re.compile(
    r"\b(försening|förseningar|minskad (service|trafik)|tågbyte|"
    r"enkelspårsdrift|hastighetsnedsättning|banarbete som påverkar|"
    r"förväntas bli (sen|försenad))\b",
    re.IGNORECASE,
)

CITY_RE = re.compile(
    rf"(?<![{_SV}])(Malmö|Lund|Helsingborg|Kristianstad|Landskrona|Trelleborg|"
    r"Ystad|Eslöv|Höör|Hässleholm|Ängelholm|Simrishamn|Staffanstorp|"
    r"Kävlinge|Hyllie|Triangeln|Lomma|Vellinge|Höganäs|Osby|Sjöbo|Svedala|"
    r"Burlöv|Bromölla|Perstorp|Örkelljunga|Bjuv|Åstorp|Klippan|Stockholm|"
    r"Solna|Södertälje|Nacka|Sundbyberg|Täby|Norrtälje|Uppsala|Enköping|"
    r"Göteborg|Mölndal|Kungsbacka|Borås|Trollhättan|Uddevalla|Skövde|"
    r"Linköping|Norrköping|Motala|Jönköping|Nässjö|Värnamo|Kalmar|"
    r"Oskarshamn|Västervik|Nybro|Karlstad|Kristinehamn|Arvika|Örebro|"
    r"Karlskoga|Västerås|Köping|Eskilstuna|Nyköping|Falun|Borlänge|Mora|"
    r"Gävle|Sandviken|Hudiksvall|Sundsvall|Härnösand|Örnsköldsvik|"
    r"Östersund|Umeå|Skellefteå|Luleå|Piteå|Kiruna|Visby|Karlskrona|"
    r"Karlshamn|Varberg|Halmstad|Växjö|Älmhult)"
    rf"(?![{_SV}])",
    re.IGNORECASE,
)

_COPENHAGEN_RE = re.compile(r"köpenhamn|cph|kastrup", re.IGNORECASE)
_TILLFALLIG_RE = re.compile(r"tillfällig (körväg|hållplats)|hänvisas till", re.IGNORECASE)
_INSTALLD_STOPP_RE = re.compile(r"inställd|ställs in|inga avgångar|ingen trafik", re.IGNORECASE)
_ERSATTNING_RE = re.compile(r"ersättningsbuss|ersättningstrafik", re.IGNORECASE)
_TEKNISKT_FEL_RE = re.compile(r"tekniskt fel", re.IGNORECASE)
_STANGD_HALLPLATS_RE = re.compile(r"^stängd hållplats$", re.IGNORECASE)
_HALLPLATS_RE = re.compile(r"^hållplats ", re.IGNORECASE)
_TRAFIKINFO_RE = re.compile(r"^trafikinformation$", re.IGNORECASE)
_INSTALLD_RE = re.compile(r"inställd", re.IGNORECASE)


def _text_of(alert: dict) -> str:
    return "\n".join([
        alert.get("header") or "", alert.get("description") or "",
        alert.get("cause") or "", alert.get("effect") or "",
    ])


def places_from(alert: dict) -> list[str]:
    text = f"{alert.get('header') or ''} {alert.get('description') or ''}"
    places: list[str] = []
    hubs = find_hubs_in_text(text)
    for hub in hubs:
        if not any(x.lower() == hub["name"].lower() for x in places):
            places.append(hub["name"])

    for m in CITY_RE.finditer(text):
        p = m.group(0)
        covered_by_hub = any(
            h["city"].lower() == p.lower() or h["name"].lower() == p.lower() for h in hubs
        )
        if covered_by_hub and hubs:
            continue
        if not any(x.lower() == p.lower() for x in places):
            places.append(p)

    return [
        p for p in places
        if resolve_place_coords(p) is not None or place_looks_skane(p) or _COPENHAGEN_RE.search(str(p))
    ]


def _ignore_result(why: str, alert: dict) -> dict:
    return {
        "score": 0, "level": "ignore", "why": why,
        "places": places_from(alert), "driver_hint": None, "hubs": [],
    }


def is_noise_only(text: str) -> bool:
    if not NOISE_RE.search(text):
        return False
    return not SERIOUS_RE.search(text)


def has_serious_effect(alert: dict) -> bool:
    effect = str(alert.get("effect") or "").lower()
    return any(
        s in effect
        for s in ("ingen service", "inställd", "stoppad", "stora försening", "minskad service")
    )


def score_alert(alert: dict) -> dict:
    header = (alert.get("header") or "").strip()
    text = _text_of(alert)
    text_lower = text.lower()

    if is_noise_only(text):
        return _ignore_result("Stationsservice (hiss/toalett/cykel m.m.) — ingen taxinytta", alert)

    if _STANGD_HALLPLATS_RE.match(header) or _HALLPLATS_RE.match(header):
        if not SERIOUS_RE.search(text):
            return _ignore_result("Enstaka hållplatsinfo", alert)

    if _TRAFIKINFO_RE.match(header) and not SERIOUS_RE.search(text) and not MEDIUM_RE.search(text):
        return _ignore_result("Allmän trafikinfo", alert)

    if _TILLFALLIG_RE.search(text) and not SERIOUS_RE.search(text) and not _INSTALLD_RE.search(text):
        return _ignore_result("Omledning/hållplatsflytt — låg taxinytta", alert)

    hubs = find_hubs_in_text(text)
    places = places_from(alert)
    place_str = ", ".join(places) if places else ("Okänd plats" if is_national_scope() else "Skåne")
    hub_name = hubs[0]["name"] if hubs else None

    serious = bool(SERIOUS_RE.search(text)) or (
        has_serious_effect(alert)
        and (
            "tåg" in text_lower or "påga" in text_lower or "öresund" in text_lower
            or "buss" in text_lower or bool(hubs)
        )
    )

    mediumish = bool(MEDIUM_RE.search(text)) or "försening" in str(alert.get("effect") or "").lower()

    # "Tekniskt fel" ensamt (t.ex. hiss) ska aldrig bli high.
    technical_only = bool(_TEKNISKT_FEL_RE.search(str(alert.get("cause") or ""))) and not serious and not mediumish

    if technical_only or (not serious and not mediumish and not has_serious_effect(alert)):
        if not serious:
            return _ignore_result("Ingen allvarlig trafikstörning", alert)

    score = 0
    reasons: list[str] = []

    if serious:
        score = 70
        reasons.append("allvarlig störning")
        if _INSTALLD_STOPP_RE.search(text):
            score = 85
            reasons.append("inställd/stopp")
        if _ERSATTNING_RE.search(text):
            score += 5
            reasons.append("ersättningsbuss")
    elif mediumish:
        score = 35
        reasons.append("försening/påverkan")
    else:
        return _ignore_result("Otillräcklig taxirelevans", alert)

    if hubs:
        score += min(12, round((hubs[0].get("weight") or 0) * 0.25))
        reasons.append(f"station: {hubs[0]['name']}")

    level = "ignore"
    if score >= 60 and serious:
        level = "high"
    elif score >= 30:
        level = "medium"
    elif score > 0:
        level = "low"

    # Hub-boost får aldrig ensamt lyfta till high utan allvarlig störning.
    if not serious and level == "high":
        level = "medium"

    driver_hint = None
    if level == "high":
        driver_hint = (
            f"Station {hub_name}: resenärer behöver skjuts — kör hit. {header}"
            if hub_name else
            f"Ökad taxieftefrågan trolig i {place_str}. Kollektivtrafik störd: {header}"
        )
    elif level == "medium":
        driver_hint = f"Kolla {hub_name}: {header}" if hub_name else f"Möjlig ökad efterfrågan i {place_str}: {header}"

    return {
        "score": score,
        "level": level,
        "why": ", ".join(reasons[:4]) or "låg relevans",
        "places": places,
        "hubs": [h["name"] for h in hubs],
        "driver_hint": driver_hint,
        # Exponerat så mode-medveten allvarlighetsgradering (text_scoring.py)
        # kan återanvända samma serious/mediumish-signaler i stället för att
        # räkna om dem med ett andra regexpass.
        "serious": serious,
        "mediumish": mediumish,
    }


def is_road_alert(alert: dict | None) -> bool:
    if not alert:
        return False
    return (
        alert.get("source_kind") == "road"
        or str(alert.get("id") or "").startswith("tv:")
    )


def enrich_alert(alert: dict) -> dict:
    """
    Port of taxiRelevance.js's enrichAlert: scores the alert, then re-checks
    alert_in_market() and force-zeroes to "ignore" if the alert names
    another region -- the out-of-market suppression must run AFTER
    scoring (it needs taxi["places"]), not folded into score_alert itself.

    Returns the (possibly force-ignored) taxi dict -- not merged with
    `alert`, unlike the JS original's object-spread style; callers already
    have `alert` and pass both to classify_transit_alert().
    """
    if is_road_alert(alert):
        # scoreRoadAlert isn't ported (Phase 1 is Trafiklab-only, no road
        # source exists to feed this branch) -- see core/text_scoring.py's
        # matching stub for the tier-classification side.
        raise NotImplementedError("scoreRoadAlert not ported yet (no road source in Django)")

    taxi = score_alert(alert)
    if not alert_in_market(alert, taxi) and taxi["level"] != "ignore":
        return {**taxi, "score": 0, "level": "ignore", "why": "Utanför marknaden", "driver_hint": None}
    return taxi
