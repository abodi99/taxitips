"""
Lagstadgad förseningsersättning (lag 2015:953 om kollektivtrafik-
resenärers rättigheter) som en ny signal -- se docs/transit-compensation-
rules.md för research och källor bakom RegionCompensationRule-raderna.

Textkällorna (SL/Västtrafik/Trafiklab) prövas med `compensation_signal`,
Trafikverkets tåg med `rail_compensation_signal` -- men bara för regionala
tåg vi kan knyta till en huvudman (RAIL_PRODUCT_REGION nedan). Fjärrtåg (SJ
m.fl.) lyder under EU-förordning 1371/2007 med andra trösklar och belopp,
inte undersökta här; att applicera de regionala reglerna blint på ett
SJ-tåg vore en saklig felaktighet i en motivering som ska gå att lita på.

Ersättningen påverkar inte LÄGET (poäng/tier från källans regel), men den
är en omständighet i core/taxi_context.py: resenären som får taxin betald
tar den. Och den påstås bara när väntan säkert når regionens gräns.

"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from core.models import RegionCompensationRule
from core.taxi_relevance import _INSTALLD_STOPP_RE

# Undantag som gäller alla operatörer: en störning annonserad minst så här
# långt i förväg räknas som planerad (banarbete/ersättningstrafik), inte en
# oplanerad försening -- ingen operatör i researchen ersätter det.
ADVANCE_NOTICE_EXCLUSION = timedelta(days=3)


def compensation_signal(alert: dict, mode: str) -> dict | None:
    """
    alert (samma dict som når classify_transit_alert), färdsätt -> signal
    eller None om ingen av villkoren är uppfyllda.

    Utlöses bara av en ENTYDIG inställd-avgång-utsaga (_INSTALLD_STOPP_RE,
    samma regex som redan bevisat pålitlig för bus.serious-grenens
    konfidenssplit tidigare i den här sessionen) -- inte "allvarligt
    ordval" i stort, eftersom ingen textkälla bär faktisk
    försening-i-minuter att jämföra mot 20-minuterströskeln med. En
    inställd avgång utan omedelbart alternativ är i praktiken minst lika
    allvarlig som en 20-minutersförsening, så det är en verifierbar proxy,
    inte en gissning.
    """
    # Vägtrafik är utanför lagens tillämpning: lag 2015:953 gäller
    # kollektivtrafikRESENÄRER, inte den som sitter i egen bil i en kö.
    # Grenen nåddes aldrig så länge vägkällan skrev region=NULL och föll ur
    # på raden nedan -- en tyst beroendekedja, inte ett medvetet skydd.
    if mode == "road" or alert.get("source_kind") == "road":
        return None

    region = alert.get("region")
    if not region:
        return None

    text = f"{alert.get('header') or ''} {alert.get('description') or ''}"
    if not _INSTALLD_STOPP_RE.search(text):
        return None

    active_from = alert.get("active_from")
    if active_from and (active_from - timezone.now()) >= ADVANCE_NOTICE_EXCLUSION:
        # Annonserad minst tre dygn i förväg -- planerad störning, undantagen
        # hos samtliga undersökta operatörer.
        return None

    # SL:s larm kan bära nästa avgång (sl.enrich_next_departures). Går nästa
    # inom gränsen blir resenären inte försenad nog för ersättning -- att
    # påstå det vore fel mot både föraren och resenären.
    return _signal(region, mode, alert.get("next_departure_minutes"))


def _signal(region: str, mode: str, wait_minutes: int | None) -> dict | None:
    rule = RegionCompensationRule.objects.filter(region=region).first()
    if not rule:
        return None
    if mode in (rule.excluded_modes or []):
        return None
    if wait_minutes is not None and wait_minutes < rule.threshold_minutes:
        return None
    return {
        "eligible": True,
        "cap_kr": rule.taxi_cap_kr,
        "threshold_minutes": rule.threshold_minutes,
        # True/False/None -- None betyder att huvudmannen inte skriver ut
        # det, och då säger vi inget heller. Skillnaden är stor för en
        # förare: Skånetrafikens 2 960 kr gäller per betalande resenär,
        # medan SL uttryckligen skriver att beloppet inte blir högre om man
        # samåker. Fyra strandsatta resenärer är två olika affärer.
        "per_person": rule.cap_per_person,
    }


# --- Tåg (Trafikverket) ------------------------------------------------------
#
# Bara regional kollektivtrafik som lyder under lag 2015:953 och som vi kan
# knyta till EN huvudman. Nyckeln är ProductInformation -- det resenären ser på
# tavlan -- mätt i prod 2026-10-02. SJ, Snälltåget, Vy, VR, Norrtåg, Tåg i
# Bergslagen och Mälartåg saknas med avsikt: fjärrtåg lyder under EU-förordning
# 1371/2007 (andra regler, inte undersökta), och de regionala som korsar flera
# huvudmäns områden har vi inget säkert svar för. Inget svar är bättre än fel.
RAIL_PRODUCT_REGION: dict[str, str] = {
    "Pågatågen": "skane",
    "Pågatågen Exp": "skane",
    "Västtågen": "vt",
    "SL Pendeltåg": "sl",
    "VTAB": "varm",
}
# Tåg som kör åt flera huvudmän: stationens län avgör vems regler resenären
# reser på. Halland saknas (ingen regel undersökt), liksom Danmark.
RAIL_COUNTY_PRODUCTS = frozenset({"Öresundståg", "Krösatågen"})
COUNTY_REGION: dict[str, str] = {
    "12": "skane",
    "14": "vt",
    "06": "jlt",
    "07": "krono",
    "08": "klt",
    "10": "blekinge",
}


def rail_region(product: str, lat: float | None, lon: float | None) -> str | None:
    """Vilken huvudmans ersättningsregler en tågresenär reser på, eller None."""
    product = (product or "").strip()
    if product in RAIL_PRODUCT_REGION:
        return RAIL_PRODUCT_REGION[product]
    if product in RAIL_COUNTY_PRODUCTS:
        from core.areas import place_for

        county, _municipality, _codes = place_for(lat, lon)
        return COUNTY_REGION.get(county or "")
    return None


def rail_compensation_signal(
    *,
    product: str,
    lat: float | None,
    lon: float | None,
    cancelled: bool,
    wait_minutes: int | None,
    is_last_departure: bool,
    has_replacement: bool,
) -> dict | None:
    """
    Ersättningsrätt för en tågstörning. Kräver att vi VET att väntan blir
    minst regionens gräns: känt glapp eller försening över gränsen, eller
    sista avgången. Med ersättningstrafik insatt kommer resenären fram ändå.
    """
    if has_replacement:
        return None
    region = rail_region(product, lat, lon)
    if not region:
        return None
    if cancelled and is_last_departure:
        return _signal(region, "train", None)
    if wait_minutes is None:
        return None
    return _signal(region, "train", wait_minutes)
