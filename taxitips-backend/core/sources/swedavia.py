"""
Swedavia FlightInfo v2 -- ankomster till svenska flygplatser.

Ren översättning: hämtar och normaliserar, filtrerar inte och poängsätter
inte. Reglerna bor i core/flight_scoring.py, trösklarna i core/thresholds.py.

Tre saker om API:t som inte syns i OpenAPI-specen och som kostade en
felaktig implementation att upptäcka (mätt mot ett riktigt ARN-svar):

1. **`DEL` betyder "Borttagen"/"Deleted", inte "Delayed".** Statusenum:t är
   SCH/FPL/FLS/SEQ/ACT/CAN/LAN/RER/DIV/DEL och innehåller ingen
   försenings-status över huvud taget. Alla 29 DEL-flyg i mätningen saknade
   både estimatedUtc och actualUtc -- de har tagits ur tidtabellen, alltså
   noll ankommande resenärer. Att läsa DEL som "försenad" hade gett exakt
   motsatt signal. Försening räknas i stället ur tiderna, se delay_minutes().

2. **`{date}` i sökvägen är LOKALT svenskt datum, inte UTC.** Svaret för
   2026-09-12 spänner 00:05-23:55 lokal tid, och ett plan schemalagt
   2026-09-11T22:35Z (= 00:35 lokal den 12:e) ligger i den 12:es svar. Ett
   fönster som korsar midnatt kräver därför två hämtningar.

3. **Det finns ingen flygplanstyp och inget passagerarantal.** Ett tips får
   aldrig påstå "500-600 personer" -- vi kan räkna ankomster, inget mer.
   Samma regel som för GTFS-beläggning: kategoriskt, aldrig påhittade tal.

Kvot: 10 001 anrop / 30 dagar på FlightInfo Free, och inga kvot-headers i
svaret (verifierat mot /heartBeat). Räkningen sköts av anroparen.
"""

from __future__ import annotations

import datetime as dt
import logging

import requests

log = logging.getLogger(__name__)

_URL = "https://api.swedavia.se/flightinfo/v2/{iata}/arrivals/{date}"

# Flyg som inte bär några resenärer till terminalen. Inte en tröskel utan en
# egenskap hos källan, därför här och inte i thresholds.py.
NON_ARRIVING_STATUSES = frozenset({"DEL", "CAN"})


def _parse_utc(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        log.warning("swedavia: obegriplig tidsstämpel %r", value)
        return None


def delay_minutes(flight: dict) -> int | None:
    """
    Försening i minuter, eller None när den inte går att räkna ut.

    None betyder "vet inte" och skiljer sig från 0 ("i tid") -- ett flyg utan
    estimat är inte ett flyg i tid.
    """
    scheduled = flight.get("scheduled")
    effective = flight.get("effective")
    if not scheduled or not effective or effective is scheduled:
        return None
    return round((effective - scheduled).total_seconds() / 60)


def normalize_flight(raw: dict, iata: str) -> dict | None:
    """Ett flyg ur svaret -> vår form. None när tiden saknas helt."""
    times = raw.get("arrivalTime") or {}
    scheduled = _parse_utc(times.get("scheduledUtc"))
    estimated = _parse_utc(times.get("estimatedUtc"))
    actual = _parse_utc(times.get("actualUtc"))

    # Faktisk tid slår estimat slår tidtabell. Utan någon av dem finns inget
    # att hinka in i ett tidsfönster och flyget är obrukbart för oss.
    effective = actual or estimated or scheduled
    if not effective:
        return None

    status = raw.get("locationAndStatus") or {}
    operator = raw.get("airlineOperator") or {}
    identifier = raw.get("flightLegIdentifier") or {}

    flight = {
        "airport": iata,
        "flight_id": raw.get("flightId") or identifier.get("flightId") or "",
        "airline": operator.get("name") or "",
        "airline_iata": operator.get("iata") or "",
        "origin": raw.get("departureAirportSwedish") or raw.get("departureAirportEnglish") or "",
        "origin_iata": identifier.get("departureAirportIata") or "",
        "scheduled": scheduled,
        "estimated": estimated,
        "actual": actual,
        "effective": effective,
        "status": status.get("flightLegStatus") or "",
        "status_text": status.get("flightLegStatusSwedish") or "",
        "terminal": status.get("terminal") or "",
        # D = inrikes, S = Schengen, I = internationellt. Säger inget om
        # planets storlek, bara vilken ankomsthall resenären kommer ut i.
        "di_indicator": raw.get("diIndicator") or "",
        # True när källan sagt något om den faktiska ankomsttiden. Skiljer ett
        # fönster byggt på live-data från ett byggt på ren tidtabell, vilket
        # är hela grunden för confidence i flight_scoring.
        "is_live": bool(actual or estimated),
    }
    flight["delay_minutes"] = delay_minutes(flight)
    return flight


def normalize_arrivals(payload: dict, iata: str) -> list[dict]:
    """
    Hela svaret -> lista av flyg.

    Borttagna och inställda flyg följer med hit: den här modulen översätter,
    den dömer inte. flight_scoring filtrerar dem med NON_ARRIVING_STATUSES så
    att torrkörningen kan rapportera hur många som sållades bort.
    """
    flights = (payload or {}).get("flights") or []
    out = []
    for raw in flights:
        flight = normalize_flight(raw, iata)
        if flight:
            out.append(flight)
    return out


def fetch_arrivals(key: str, iata: str, date: dt.date, timeout: int = 20) -> list[dict]:
    """
    En hämtning = ett anrop mot kvoten. `date` är lokalt svenskt datum.

    Höjer vid fel i stället för att svälja: en flygplats som slutat svara ska
    synas som trasig i pipelinevyn, inte som en lugn kväll utan ankomster.
    """
    res = requests.get(
        _URL.format(iata=iata, date=date.isoformat()),
        headers={"Ocp-Apim-Subscription-Key": key, "Accept": "application/json"},
        timeout=timeout,
    )
    if res.status_code == 401:
        raise RuntimeError("Swedavia 401 — SWEDAVIA_API_KEY avvisad")
    if res.status_code == 429:
        raise RuntimeError("Swedavia 429 — kvoten (10 001/30 dagar) är slut")
    if not res.ok:
        raise RuntimeError(f"Swedavia {res.status_code} för {iata} {date.isoformat()}")
    return normalize_arrivals(res.json(), iata)
