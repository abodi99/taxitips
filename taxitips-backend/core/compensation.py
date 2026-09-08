"""
Lagstadgad förseningsersättning (lag 2015:953 om kollektivtrafik-
resenärers rättigheter) som en ny signal -- se docs/transit-compensation-
rules.md för research och källor bakom RegionCompensationRule-raderna.

Medvetet begränsad till textkällorna (SL/Västtrafik/Trafiklab), INTE
Trafikverkets järnvägsdata: RailAlert saknar helt ett regionfält (skrivs
hårdkodat som "rail"), och Trafikverkets tågdata blandar regionala korttåg
(som lyder under lag 2015:953, samma lag som textkällorna) med fjärrtåg
(SJ m.fl., som lyder under EU-förordning 1371/2007 -- andra trösklar och
belopp, inte undersökta här). Att applicera de regionala reglerna blint på
ett SJ-fjärrtåg vore en saklig felaktighet i en motivering som ska gå att
lita på.

Av samma skäl som SL/VT:s redaktionella prioritet i text_scoring.pys
_editorial_confidence() bara får flytta konfidens: en juridisk
ersättningsrätt mäter något annat än hur allvarlig störningen är för en
taxiförare, och ska aldrig tävla med poängsystemet. Den här modulen rör
varken poäng eller severity_tier -- bara ett separat, spårbart fält plus
en motiveringsrad.
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

    rule = RegionCompensationRule.objects.filter(region=region).first()
    if not rule:
        return None
    if mode in (rule.excluded_modes or []):
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
