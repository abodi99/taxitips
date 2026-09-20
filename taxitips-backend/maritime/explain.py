"""
Färjekällan förklarad för pipeline-sidan: vad AIS gav, vad filtren släppte
igenom, och varför varje fartyg blir -- eller inte blir -- ett tips.

Läser bara. Använder samma konstanter som lyssnaren (maritime/ais.py,
maritime/tips.py), så sidan kan inte visa en annan regel än den som körs.

Två tidsramar blandas, och varje siffra säger vilken den tillhör:
"sedan start" kommer ur lyssnarens minne via source_status.detail och
nollställs vid omstart; "i databasen" och "just nu" kommer ur ferry_arrivals.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

from django.db import DatabaseError
from django.utils import timezone

from core.models import Opportunity, SourceStatus
from maritime import ais, tips
from maritime.models import AisVessel, FerryArrival
from maritime.ports import PORTS

# Samma fönster som lyssnarens "i hamn"-räkning.
IN_PORT_FRESH = dt.timedelta(minutes=15)
# Lyssnaren skriver status varje minut. Äldre än så här är den inte igång.
STATUS_STALE = dt.timedelta(minutes=3)
# Kartan visar fartyg med position inom det här fönstret.
MAP_WINDOW = dt.timedelta(minutes=60)

TYPE_GROUPS = (
    (20, 29, "Markeffektfarkost"),
    (30, 30, "Fiske"),
    (31, 32, "Bogsering"),
    (33, 34, "Muddring/dykning"),
    (35, 35, "Militär"),
    (36, 36, "Segelbåt"),
    (37, 37, "Fritidsbåt"),
    (40, 49, "Snabbgående (HSC)"),
    (50, 50, "Lotsbåt"),
    (51, 51, "Sjöräddning"),
    (52, 52, "Bogserbåt"),
    (53, 59, "Hamn/myndighet"),
    (60, 69, "Passagerarfartyg"),
    (70, 79, "Lastfartyg"),
    (80, 89, "Tankfartyg"),
    (90, 99, "Övrigt"),
)

# AISStreams alla 25 meddelandetyper, från type-definition.yaml i
# github.com/aisstream/ais-message-models. Kategorierna är dokumentationens.
MESSAGE_TYPE_DOCS = (
    ("PositionReport", "Position", "Klass A (större fartyg): läge, fart, kurs, riktning, navigationsstatus. Ankomstsignalen."),
    ("StandardClassBPositionReport", "Position", "Klass B (mindre fartyg, fritidsbåtar): läge, fart, kurs. Ingen navigationsstatus."),
    ("ExtendedClassBPositionReport", "Position", "Klass B med namn, typ och storlek i samma meddelande som läget."),
    ("LongRangeAisBroadcastMessage", "Position", "Klass A via satellit: grovt läge, fart, kurs och status, glest."),
    ("BaseStationReport", "Position", "Landbaserad AIS-station. Inget fartyg."),
    ("StandardSearchAndRescueAircraftReport", "Position", "Räddningsflyg och -helikoptrar. Inget fartyg."),
    ("ShipStaticData", "Statisk data och resa", "Klass A: namn, typ, storlek, anropssignal, IMO, djupgående, destination, ETA."),
    ("StaticDataReport", "Statisk data och resa", "Klass B i två delar: A = namn, B = typ, storlek, anropssignal."),
    ("AidsToNavigationReport", "Säkerhet", "Fyrar, bojar och sjömärken. Står still."),
    ("AddressedSafetyMessage", "Säkerhet", "Säkerhetsmeddelande i fritext till en mottagare. Ingen position."),
    ("SafetyBroadcastMessage", "Säkerhet", "Säkerhetsmeddelande i fritext till alla. Ingen position."),
    ("AddressedBinaryMessage", "Binärdata", "Applikationsdata till en mottagare (t.ex. hydrologi). Inte fartygsläge."),
    ("BinaryBroadcastMessage", "Binärdata", "Applikationsdata till alla (t.ex. väder). Inte fartygsläge."),
    ("GnssBroadcastBinaryMessage", "Binärdata", "GNSS-korrektioner från basstationer."),
    ("BinaryAcknowledge", "Binärdata", "Kvittens på ett binärmeddelande."),
    ("SingleSlotBinaryMessage", "Binärdata", "Kort binärmeddelande."),
    ("MultiSlotBinaryMessage", "Binärdata", "Längre binärmeddelande."),
    ("CoordinatedUTCInquiry", "Nät och styrning", "Förfrågan om UTC-tid mellan stationer."),
    ("Interrogation", "Nät och styrning", "En station ber ett fartyg sända en viss meddelandetyp."),
    ("AssignedModeCommand", "Nät och styrning", "Basstation tilldelar sändningsläge."),
    ("GroupAssignmentCommand", "Nät och styrning", "Basstation styr en grupp fartygs sändningsintervall."),
    ("DataLinkManagementMessage", "Nät och styrning", "Reservation av radiokanalens tidsluckor."),
    ("DataLinkManagementMessageData", "Nät och styrning", "Innehållet i DataLinkManagementMessage."),
    ("ChannelManagement", "Nät och styrning", "Byte av AIS-radiokanaler i ett område."),
    ("UnknownMessage", "Nät och styrning", "Meddelande som inte kunde avkodas."),
)

FIELDS_USED = (
    ("MessageType", "En av de sex fartygstyperna i prenumerationen. Allt annat ignoreras."),
    ("MetaData.MMSI", "Fartygets id, nyckeln i ferry_arrivals."),
    ("MetaData.time_utc", "Meddelandets tid (Go-format med nanosekunder)."),
    ("MetaData.ShipName", "Namnet, innan ShipStaticData hörts."),
    ("*Position*.Latitude / Longitude", "Vilken hamnruta fartyget är i, och punkten på kartan. 91/181 = saknas."),
    ("*Position*.Sog", "Fart i knop, själva ankomstsignalen. 102.3 = saknas."),
    ("*Position*.Cog / TrueHeading", "Kurs och riktning, visas på kartan. 360 respektive 511 = saknas."),
    ("PositionReport.NavigationalStatus", "5 = förtöjd, 1 = ankrad. Spärrar ETA-regeln. Klass B saknar fältet."),
    ("ShipStaticData.Type · StaticDataReport.ReportB.ShipType · ExtendedClassB.Type", "Fartygstyp, filter 2 (60-69). 0 = saknas."),
    ("…Dimension.A + B (C + D)", "Längd (bredd) över allt, filter 3."),
    ("StaticDataReport.PartNumber", "false = del A, bara ReportA.Name. true = del B med typ och storlek."),
    ("ShipStaticData.CallSign / ImoNumber / MaximumStaticDraught", "Anropssignal, IMO-nummer och djupgående, visas på kartan."),
    ("ShipStaticData.Eta", "Month/Day/Hour/Minute i UTC utan år. Används bara om den är rimlig."),
    ("ShipStaticData.Destination", "Visas, tolkas inte: fritext från besättningen."),
    ("…Valid", "false = meddelandet släpps."),
)


def type_label(code) -> tuple[str, str]:
    """(etikett, kodintervall) för en AIS-fartygstyp."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "Okänd typ", "saknas"
    for low, high, label in TYPE_GROUPS:
        if low <= code <= high:
            return label, str(low) if low == high else f"{low}–{high}"
    return "Okänd typ", "0/saknas"


def _verdict(stage: str, text: str, *, candidate: bool = False) -> dict:
    return {"stage": stage, "text": text, "candidate": candidate}


def verdict(vessel, now: dt.datetime) -> dict:
    """
    Var i filterkedjan fartyget står, i den ordning filtren slår till.

    Storleken prövas före ankomstspärren, så att en skärgårdsbåt som
    faktiskt lade till visar varför den inte blev tips, inte bara "hanterad".
    """
    if vessel.timestamp is None or vessel.latitude is None:
        return _verdict("no_position", "Typen är hörd men ingen position ännu.")
    if not vessel.port_name:
        return _verdict("outside", "Senast hörd utanför hamnrutorna.")
    silent = now - vessel.timestamp
    if silent > IN_PORT_FRESH:
        minutes = int(silent.total_seconds() // 60)
        return _verdict("silent", f"Tyst i {minutes} min, har troligen lämnat rutan.")
    if not vessel.length_m:
        return _verdict("unknown_length", "Längden saknas i AIS, så storleken går inte att bedöma. Inget tips.")
    if vessel.length_m < tips.MIN_TIP_LENGTH_M:
        return _verdict(
            "too_short",
            f"{vessel.length_m} m, under färjegränsen på {tips.MIN_TIP_LENGTH_M} m. Inget tips.",
        )
    if vessel.is_processed:
        when = timezone.localtime(vessel.triggered_at).strftime("%H:%M") if vessel.triggered_at else "?"
        return _verdict("handled", f"Ankomsten hanterades kl {when}. Spärrad tills färjan avgår.", candidate=True)
    if vessel.speed_knots is None:
        return _verdict("no_speed", "Farten saknas i AIS, så en inbromsning syns inte.")
    if vessel.speed_knots >= ais.UNDERWAY_KNOTS:
        return _verdict(
            "underway",
            f"I fart ({vessel.speed_knots:.1f} kn). Blir tips om den saktar in under "
            f"{ais.SLOW_KNOTS:g} kn i hamnrutan.",
            candidate=True,
        )
    if not vessel.was_underway:
        return _verdict(
            "still",
            "Ligger still och har inte setts i fart sedan lyssnaren började höra den. Det är ingen ankomst.",
        )
    return _verdict("slowing", f"{vessel.speed_knots:.1f} kn, mellan gränserna.", candidate=True)


def _map(now: dt.datetime, ferries: dict[int, FerryArrival]) -> dict:
    """Alla fartyg med färsk position, för karta 8a på pipeline-sidan."""
    since = now - MAP_WINDOW
    rows = []
    fresh = AisVessel.objects.filter(latitude__isnull=False, position_at__gte=since).order_by("-position_at")
    for s in fresh:
        label, _ = type_label(s.ship_type)
        ferry = ferries.get(s.mmsi)
        rows.append({
            "mmsi": s.mmsi, "name": s.name, "type": s.ship_type, "typeLabel": label,
            "passenger": ais.is_passenger(s.ship_type), "aisClass": s.ais_class,
            "lengthM": s.length_m, "widthM": s.width_m, "draught": s.draught_m,
            "callSign": s.call_sign, "imo": s.imo, "destination": s.destination,
            "lat": s.latitude, "lon": s.longitude, "sog": s.speed_knots, "cog": s.course,
            "heading": s.heading, "navStatus": s.nav_status, "port": s.port_name,
            "positionAt": _iso(s.position_at), "lastMessageType": s.last_message_type,
            "messages": s.messages,
            "ferryText": verdict(ferry, now)["text"] if ferry else "",
        })
    return {
        "map": rows,
        "mapSummary": {
            "windowMinutes": int(MAP_WINDOW.total_seconds() // 60),
            "shown": len(rows),
            "stale": AisVessel.objects.filter(position_at__lt=since).count(),
            "classA": sum(1 for r in rows if r["aisClass"] == "A"),
            "classB": sum(1 for r in rows if r["aisClass"] == "B"),
            "passenger": sum(1 for r in rows if r["passenger"]),
        },
    }


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


_STAGE_ORDER = {
    "underway": 0, "slowing": 0, "handled": 1, "still": 2, "no_speed": 3,
    "too_short": 4, "unknown_length": 5, "no_position": 6, "outside": 7, "silent": 8,
}


def build(now: dt.datetime | None = None) -> dict:
    now = now or timezone.now()
    try:
        return _build(now)
    except DatabaseError as exc:
        # Tabellen saknas hellre synligt än att hela pipeline-sidan faller.
        return {"error": f"{type(exc).__name__}: {exc}. Har `manage.py migrate maritime` körts?"}


def _build(now: dt.datetime) -> dict:
    status = SourceStatus.objects.filter(source=tips.SOURCE).first()
    detail = dict((status.detail if status else None) or {})
    total = detail.get("total") or {}
    fresh = bool(status and now - status.checked_at <= STATUS_STALE)

    vessels = list(FerryArrival.objects.all())
    rows = []
    for v in vessels:
        rows.append({
            "mmsi": v.mmsi, "name": v.ship_name, "type": v.ship_type, "lengthM": v.length_m,
            "destination": v.destination, "port": v.port_name, "knots": v.speed_knots,
            "navStatus": v.nav_status, "timestamp": _iso(v.timestamp), "eta": _iso(v.eta),
            "verdict": verdict(v, now),
        })
    rows.sort(key=lambda r: (_STAGE_ORDER.get(r["verdict"]["stage"], 9), -(r["lengthM"] or 0)))

    in_port = [v for v in vessels if v.port_name and v.timestamp and now - v.timestamp <= IN_PORT_FRESH]
    ships_now = Counter(v.port_name for v in in_port)

    groups: dict[str, dict] = {}
    for code, n in (detail.get("shipTypes") or {}).items():
        label, code_range = type_label(code)
        group = groups.setdefault(
            label, {"label": label, "range": code_range, "n": 0, "passenger": label == "Passagerarfartyg"},
        )
        group["n"] += n

    ship_types_known = sum((detail.get("shipTypes") or {}).values())
    funnel = [
        {"label": "AIS-meddelanden mottagna", "scope": "sedan start",
         "n": total.get("position", 0) + total.get("static", 0),
         "note": "Allt AISStream skickat inifrån hamnrutorna. Rutfiltret görs hos AISStream, inte här."},
        {"label": "Unika fartyg hörda", "scope": "sedan start",
         "n": detail.get("uniqueShips", 0),
         "note": "Olika MMSI, oavsett typ."},
        {"label": "varav klass B (mindre fartyg)", "scope": "sedan start",
         "n": detail.get("classBShips", 0),
         "note": "StandardClassBPositionReport och StaticDataReport. Ingen navigationsstatus."},
        {"label": "Fartygstypen känd", "scope": "sedan start",
         "n": ship_types_known,
         "note": f"Typen kommer bara i ShipStaticData, ungefär var 6:e minut. "
                 f"{detail.get('unknownTypeShips', 0)} fartyg väntar på sin."},
        {"label": "Passagerarfartyg (typ 60–69)", "scope": "i databasen",
         "n": len(vessels),
         "note": "Filter 2. Last- och tankfartyg, bogserbåtar och lotsar sorteras bort och sparas inte."},
        {"label": "I en hamnruta nu", "scope": "just nu",
         "n": len(in_port),
         "note": "Passagerarfartyg med position de senaste 15 minuterna."},
        {"label": f"Minst {tips.MIN_TIP_LENGTH_M} m långa", "scope": "just nu",
         "n": sum(1 for v in in_port if (v.length_m or 0) >= tips.MIN_TIP_LENGTH_M),
         "note": "Filter 3. Skiljer färjor från skärgårdsbåtar."},
        {"label": "Ankomster", "scope": "sedan start",
         "n": total.get("arrivals", 0),
         "note": f"Saktade in under {ais.SLOW_KNOTS:g} kn efter att ha varit i fart. Alla storlekar."},
        {"label": "Tips skrivna", "scope": "sedan start",
         "n": total.get("tips_written", 0),
         "note": "Ankomster som också klarade längdgränsen."},
    ]

    active_tips = list(
        Opportunity.objects.filter(kind="ferry", end_time__gt=now)
        .order_by("-demand_score")
        .values("title", "demand_score", "confidence", "reasons", "rule_id", "end_time", "places")
    )
    for tip in active_tips:
        tip["end_time"] = _iso(tip["end_time"])

    return {
        "status": {
            "connected": bool(detail.get("connected")) and fresh,
            "fresh": fresh,
            "checkedAt": _iso(status.checked_at) if status else None,
            "connectedSince": detail.get("connectedSince"),
            "reconnects": detail.get("reconnects", 0),
            "lastError": detail.get("lastError") or (
                "" if fresh else "Ingen färsk statusrad. Kör `manage.py run_ais_stream`."
            ),
            "dryRun": detail.get("dryRun", False),
            "compressionEnabled": detail.get("compressionEnabled"),
        },
        "funnel": funnel,
        "config": {
            "passengerTypes": "60–69",
            "slowKnots": ais.SLOW_KNOTS,
            "underwayKnots": ais.UNDERWAY_KNOTS,
            "minTipLengthM": tips.MIN_TIP_LENGTH_M,
            "rearmGapHours": int(ais.REARM_GAP.total_seconds() // 3600),
            "rearmAfterTriggerMin": int(ais.REARM_AFTER_TRIGGER.total_seconds() // 60),
            "etaAheadMin": int(ais.ETA_TRIGGER_AHEAD.total_seconds() // 60),
            "etaBehindMin": int(ais.ETA_TRIGGER_BEHIND.total_seconds() // 60),
            "tailMinutes": tips.TAIL_MINUTES,
            "sizeBands": [
                {"minLengthM": floor, "score": score, "label": label}
                for floor, score, label in tips.SIZE_BANDS
            ],
            "lateBonus": tips.LATE_BONUS,
            "lateFrom": tips.LATE_FROM_HOUR,
            "lateUntil": tips.LATE_UNTIL_HOUR,
            "scoreCap": tips.SCORE_CAP,
            "ruleId": tips.RULE_ID,
        },
        "ports": [
            {"key": p.key, "name": p.name, "region": p.region, "city": p.city,
             "lat": p.lat, "lon": p.lon, "box": p.bounding_box, "approach": p.approach_box,
             "tips": p.tips, "shipsNow": ships_now.get(p.name, 0)}
            for p in PORTS
        ],
        "shipTypes": sorted(groups.values(), key=lambda g: -g["n"]),
        "vessels": rows,
        "decisions": detail.get("decisions") or [],
        "samples": detail.get("samples") or {},
        "fieldsUsed": [{"field": f, "use": u} for f, u in FIELDS_USED],
        "messageTypes": [
            {"type": t, "category": c, "use": u, "subscribed": t in ais.MESSAGE_TYPES,
             "received": (detail.get("messageTypes") or {}).get(t, 0)}
            for t, c, u in MESSAGE_TYPE_DOCS
        ],
        "compressionEnabled": detail.get("compressionEnabled"),
        **_map(now, {v.mmsi: v for v in vessels}),
        "tips": active_tips,
    }
