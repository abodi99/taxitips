"""
Trafikverket järnväg: inställda och kraftigt försenade tågavgångar, nationellt.

Varför den här källan finns
---------------------------
Trafiklab publicerar realtid per regional huvudman, och INGEN av
fjärrtågsoperatörerna finns där -- SJ, Snälltåget, Öresundståg, Mälartåg,
Norrtåg, MTR och VR ger alla 404. Tågstörningar syntes därför bara i de tre
regioner som råkar köra egna tåg: Skåne, Stockholm, Göteborg. Överallt
annars var ett inställt tåg osynligt.

Trafikverket äger banan och täcker hela landet i en fråga. Mätt live: 63
inställda avgångar över 23 stationer -- Motala, Kungsbacka, Halmstad,
Mjölby, Katrineholm, Strängnäs och fler som inget regionalt flöde når.

Ett inställt tåg är den starkaste taxisignal som finns: folk står redan på
en perrong, med bagage, ofta utan alternativ på en timme.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.trafikinfo.trafikverket.se/v2/data.json"

# Hur långt fram vi letar.
#
# Tre timmar passar södra Sverige där tåg går var femte minut, men gör
# produkten tom norr om Gävle där banan bär en handfull avgångar per DYGN.
# Mätt kl 23:00: hela Norrland hade 11 avgångar på 8 timmar, varav en
# inställd (Boden 05:08). Med ett 3h-fönster är den osynlig.
WINDOW_HOURS = 8

# Ett tips blir relevant först när det går att agera på -- ingen står på
# perrongen sex timmar i förväg. Det är detta som gör det breda
# sökfönstret ärligt.
VISIBLE_BEFORE = timedelta(minutes=90)

# En försening av den här storleken strandsätter folk som en inställd
# avgång; under den väntar man på perrongen.
SERIOUS_DELAY_MIN = 30

# Hur länge en strandsatt perrong räknas som en möjlighet.
PLATFORM_LIFETIME = timedelta(hours=1)

# En ersättande avgång inom det här fönstret betyder att ingen är
# strandsatt -- de väntar en kvart, de tar inte taxi.
ALTERNATIVE_WITHIN = timedelta(minutes=30)


@dataclass
class Station:
    signature: str
    name: str
    lat: float | None = None
    lon: float | None = None


@dataclass
class RailAlert:
    """Normaliserad störning, redo för klassificering."""

    external_id: str
    header: str
    description: str
    station: str
    train: str
    cancelled: bool
    delay_minutes: int
    departure_at: datetime
    active_from: datetime
    active_to: datetime
    lat: float | None
    lon: float | None
    # Signalerna som gör poängsättningen möjlig. Utan dem får varje
    # inställt tåg identiska 97 poäng -- se scoring.py.
    next_departure_minutes: int | None = None
    is_last_departure: bool = False
    station_departures_in_window: int = 0
    # Trafikverket anger själv när ersättningstrafik är insatt. Mätt: 35 av
    # 59 inställda avgångar har "Buss ersätter" -- de resenärerna är inte
    # strandsatta, de går på en buss. Att visa dem som toppnotering är
    # exakt den sortens falska tips som kostar en förare en bomresa.
    has_replacement: bool = False
    replacement_note: str = ""
    # Populerade bara när has_replacement kom från en riktig ReplacementTraffic-
    # koppling, inte textmatchningens reservläge -- se _replacement().
    replacement_mode: str | None = None
    replacement_coords: tuple[float, float] | None = None
    # Vem kör tåget, och vilket namn resenären känner igen. Mätt live:
    # 100% populerade (SJ, ARRIVA, VY, TDEV, SLL, MTRX, SNÄLL, TÅGAB),
    # aldrig visade för föraren förut trots att fältet alltid finns.
    operator: str = ""
    information_owner: str = ""
    # Vart tåget var på väg -- redan uträknat för beskrivningstexten, men
    # inte förut sparat som eget fält, så en förare aldrig kunde se det
    # direkt (bara begravt i en löpande mening).
    destination: str = ""
    # Trafikverkets egen orsakstext (Deviation.Description), oavsett om den
    # råkar nämna ersättningstrafik eller inte -- t.ex. "Spårändrat",
    # "Signalfel", "Kort tåg". Skilt från replacement_note: en avvikelse
    # kan finnas utan att vara en ersättning, och tvärtom.
    cause: str = ""
    # 100% populerat live (128/128) -- en riktig "läs mer"-länk till
    # operatörens egen sida, tidigare aldrig sparad.
    web_link: str = ""
    web_link_name: str = ""
    routes: list[str] = field(default_factory=list)


def parse_point(wkt: str | None) -> tuple[float, float] | None:
    """
    WKT "POINT (lon lat)" -> (lat, lon).

    WKT är lon-först. Läses det lat-först hamnar Motala i Indiska oceanen,
    så konverteringen sker en gång, här.
    """
    if not wkt:
        return None
    m = re.search(r"POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", wkt, re.I)
    if not m:
        return None
    return float(m.group(2)), float(m.group(1))


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def minutes_late(announcement: dict) -> int:
    advertised = _parse_time(announcement.get("AdvertisedTimeAtLocation"))
    estimated = _parse_time(
        announcement.get("EstimatedTimeAtLocation") or announcement.get("TimeAtLocation")
    )
    if not advertised or not estimated:
        return 0
    return round((estimated - advertised).total_seconds() / 60)


class TrafikverketRail:
    """Hämtar och normaliserar järnvägsstörningar."""

    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self._stations: dict[str, Station] | None = None
        self._replacements: dict[tuple[str, str], dict] | None = None

    # -- API ---------------------------------------------------------------
    def _query(self, xml: str) -> dict:
        body = f'<REQUEST><LOGIN authenticationkey="{self.api_key}"/>{xml}</REQUEST>'
        res = self.session.post(
            API_URL, data=body.encode("utf-8"),
            headers={"Content-Type": "text/xml"}, timeout=60,
        )
        res.raise_for_status()
        block = (res.json().get("RESPONSE", {}).get("RESULT") or [{}])[0]
        if "ERROR" in block:
            raise RuntimeError(f"trafikverket-rail: {block['ERROR']}")
        return block

    def stations(self) -> dict[str, Station]:
        """Signatur -> station. ~1000 rader, hämtas en gång per process."""
        if self._stations is not None:
            return self._stations
        block = self._query(
            '<QUERY objecttype="TrainStation" namespace="rail.infrastructure"'
            ' schemaversion="1.5" limit="3000">'
            '<FILTER><EQ name="Advertised" value="true"/></FILTER>'
            "<INCLUDE>LocationSignature</INCLUDE>"
            "<INCLUDE>AdvertisedLocationName</INCLUDE>"
            "<INCLUDE>Geometry.WGS84</INCLUDE>"
            "</QUERY>"
        )
        out: dict[str, Station] = {}
        for s in block.get("TrainStation", []):
            sig = s.get("LocationSignature")
            if not sig:
                continue
            coord = parse_point((s.get("Geometry") or {}).get("WGS84"))
            out[sig] = Station(
                signature=sig,
                name=s.get("AdvertisedLocationName") or sig,
                lat=coord[0] if coord else None,
                lon=coord[1] if coord else None,
            )
        self._stations = out
        return out

    def replacement_traffic(self) -> dict[tuple[str, str], dict]:
        """
        (tågnummer, avgångsdatum) -> ReplacementTraffic-post. Hämtas en gång
        per process, precis som stations().

        Filtrerat till statusar som fortfarande betyder något just nu --
        mätt live (500 poster): 463 var finished/canceled (förbi, ovidkommande),
        bara running/confirmed/ordered var aktuella.

        Får aldrig stoppa hela pollningen om det strular -- det här är ett
        tillskott till järnvägens huvudsignal, inte en förutsättning för den.
        """
        if self._replacements is not None:
            return self._replacements
        try:
            block = self._query(
                '<QUERY objecttype="ReplacementTraffic" namespace="JBS"'
                ' schemaversion="1.0" limit="1000">'
                "<FILTER><OR>"
                '<EQ name="Status" value="running"/>'
                '<EQ name="Status" value="confirmed"/>'
                '<EQ name="Status" value="ordered"/>'
                "</OR></FILTER>"
                "</QUERY>"
            )
            self._replacements = build_replacement_index(block.get("ReplacementTraffic", []))
        except Exception:
            log.exception("trafikverket-rail: kunde inte hämta ReplacementTraffic, faller tillbaka på textmatchning")
            self._replacements = {}
        return self._replacements

    def _departures(self) -> list[dict]:
        """
        Alla annonserade avgångar i fönstret -- inte bara de störda.

        Hela listan behövs: för att veta om ett inställt tåg har en
        ersättare om 10 minuter måste man se de avgångar som INTE är
        inställda. Det är den signalen som saknas i Node-versionen.
        """
        block = self._query(
            '<QUERY objecttype="TrainAnnouncement" namespace="rail.trafficinfo"'
            ' schemaversion="1.9" limit="4000">'
            "<FILTER><AND>"
            '<EQ name="ActivityType" value="Avgang"/>'
            '<EQ name="Advertised" value="true"/>'
            '<GT name="AdvertisedTimeAtLocation" value="$now"/>'
            f'<LT name="AdvertisedTimeAtLocation" value="$dateadd({WINDOW_HOURS}:00:00)"/>'
            "</AND></FILTER>"
            "<INCLUDE>AdvertisedTrainIdent</INCLUDE>"
            "<INCLUDE>LocationSignature</INCLUDE>"
            "<INCLUDE>AdvertisedTimeAtLocation</INCLUDE>"
            "<INCLUDE>EstimatedTimeAtLocation</INCLUDE>"
            "<INCLUDE>Canceled</INCLUDE>"
            "<INCLUDE>ToLocation</INCLUDE>"
            "<INCLUDE>Deviation</INCLUDE>"
            "<INCLUDE>Operator</INCLUDE>"
            "<INCLUDE>InformationOwner</INCLUDE>"
            "<INCLUDE>WebLink</INCLUDE>"
            "<INCLUDE>WebLinkName</INCLUDE>"
            "</QUERY>"
        )
        return block.get("TrainAnnouncement", [])

    # -- normalisering -----------------------------------------------------
    def fetch(self, now: datetime | None = None) -> list[RailAlert]:
        if not self.api_key or self.api_key == "mock":
            log.info("trafikverket-rail: ingen nyckel, hoppar över")
            return []

        now = now or datetime.now(dt_timezone.utc)
        stations = self.stations()
        replacements = self.replacement_traffic()
        departures = self._departures()
        return build_alerts(departures, stations, now, replacement_index=replacements)


def build_alerts(
    departures: list[dict], stations: dict[str, Station], now: datetime,
    replacement_index: dict[tuple[str, str], dict] | None = None,
) -> list[RailAlert]:
    """
    Ren funktion: avgångar -> störningar. Testbar utan nätverk.
    """
    # Alla avgångar per station, för att kunna svara på "finns nästa tåg?"
    by_station: dict[str, list[dict]] = {}
    for dep in departures:
        sig = dep.get("LocationSignature")
        if sig:
            by_station.setdefault(sig, []).append(dep)
    for deps in by_station.values():
        deps.sort(key=lambda d: d.get("AdvertisedTimeAtLocation") or "")

    disrupted = [
        d for d in departures
        if d.get("Canceled") is True or minutes_late(d) >= SERIOUS_DELAY_MIN
    ]

    # Ett inställt tåg annonseras vid varje stopp det skulle betjänat -- tåg
    # 7182 gav fem nästan identiska tips ner för Norrbottensbanan. Behåll
    # tågets FÖRSTA stopp: där står den fullaste perrongen, och passagerare
    # längre ner på linjen klev oftast aldrig på.
    first_stop: dict[str, str] = {}
    for dep in disrupted:
        if dep.get("Canceled") is not True:
            continue
        train = dep.get("AdvertisedTrainIdent")
        when = dep.get("AdvertisedTimeAtLocation")
        if not train or not when:
            continue
        if train not in first_stop or when < first_stop[train]:
            first_stop[train] = when

    # En störning per station: inställd slår försenad, annars tidigast.
    best: dict[str, dict] = {}
    for dep in disrupted:
        sig = dep.get("LocationSignature")
        if not sig:
            continue
        cancelled = dep.get("Canceled") is True
        when = dep.get("AdvertisedTimeAtLocation")
        if cancelled and first_stop.get(dep.get("AdvertisedTrainIdent")) != when:
            continue
        prev = best.get(sig)
        if (
            prev is None
            or (cancelled and prev.get("Canceled") is not True)
            or (
                cancelled == (prev.get("Canceled") is True)
                and (when or "") < (prev.get("AdvertisedTimeAtLocation") or "")
            )
        ):
            best[sig] = dep

    return [
        _normalize(dep, stations.get(sig), by_station.get(sig, []), now, stations, replacement_index)
        for sig, dep in best.items()
    ]


def _normalize(
    dep: dict,
    station: Station | None,
    station_departures: list[dict],
    now: datetime,
    stations: dict[str, Station] | None = None,
    replacement_index: dict[tuple[str, str], dict] | None = None,
) -> RailAlert:
    sig = dep.get("LocationSignature", "")
    train = str(dep.get("AdvertisedTrainIdent") or "")
    when = _parse_time(dep.get("AdvertisedTimeAtLocation")) or now
    cancelled = dep.get("Canceled") is True
    delay = minutes_late(dep)
    name = station.name if station else sig
    # ToLocation ger en signatur ("Le"), inte ett namn. Registret vi redan
    # hämtat känner namnet -- en förare ska läsa "mot Luleå", inte "mot Le".
    to_sig = ((dep.get("ToLocation") or [{}])[0]).get("LocationName")
    to = None
    if to_sig:
        dest = (stations or {}).get(to_sig)
        to = dest.name if dest else to_sig

    # De tre signalerna som gör rangordning möjlig.
    next_minutes, is_last = _next_departure(dep, station_departures, when)

    # Fjärde signalen, och den starkaste: operatören säger rakt ut om
    # ersättningstrafik är insatt.
    replacement, note, replacement_mode, replacement_coords = _replacement(dep, replacement_index)

    # Vilket bolag som kör, och vilket namn resenären känner igen. SJ,
    # Öresundståg, Snälltåget m.fl. är inte utbytbara för en förare -- olika
    # operatörer betyder olika resenärsprofil och olika stationsvana.
    operator = str(dep.get("Operator") or "")
    information_owner = str(dep.get("InformationOwner") or "")
    brand = information_owner or operator
    train_label = f"{brand} {train}" if brand else f"Tåg {train}"

    time_text = when.astimezone().strftime("%H:%M")
    if cancelled:
        header = f"{train_label} {time_text} är inställt från {name}"
        description = (
            f"Avgången {time_text} från {name}"
            f"{f' mot {to}' if to else ''} är inställd."
        )
        if replacement:
            description += f" {note}."
        elif next_minutes is not None:
            description += f" Nästa avgång går om {_human_gap(next_minutes)}."
        elif is_last:
            description += " Det var sista avgången härifrån."
    else:
        header = f"{train_label} {time_text} är {delay} min försenat från {name}"
        description = (
            f"Avgången {time_text} från {name}"
            f"{f' mot {to}' if to else ''} är försenad {delay} minuter."
        )

    # En riktig ReplacementTraffic-koppling ger en GPS-spårad hållplats för
    # ersättningsfordonet -- närmare den strandsatta perrongen än stationens
    # egen plattformskoordinat, och verkligt spårad snarare än statisk.
    lat = replacement_coords[0] if replacement_coords else (station.lat if station else None)
    lon = replacement_coords[1] if replacement_coords else (station.lon if station else None)

    cause = _primary_cause(dep)

    return RailAlert(
        # Station + tåg + avgångstid är stabilt mellan pollningar, så
        # upserten uppdaterar samma rad i stället för att duplicera.
        external_id=f"tvr:{sig}:{train}:{dep.get('AdvertisedTimeAtLocation')}",
        header=header,
        description=description,
        station=name,
        train=train,
        cancelled=cancelled,
        delay_minutes=delay,
        departure_at=when,
        # Inte avgångstiden själv: tipset blir relevant strax innan, när
        # folk faktiskt kommer till perrongen. Aldrig tidigare än nu.
        active_from=max(now, when - VISIBLE_BEFORE),
        active_to=when + PLATFORM_LIFETIME,
        lat=lat,
        lon=lon,
        next_departure_minutes=next_minutes,
        is_last_departure=is_last,
        has_replacement=replacement,
        replacement_note=note,
        replacement_mode=replacement_mode,
        replacement_coords=replacement_coords,
        operator=operator,
        information_owner=information_owner,
        destination=to or "",
        cause=cause,
        web_link=str(dep.get("WebLink") or ""),
        web_link_name=str(dep.get("WebLinkName") or ""),
        station_departures_in_window=len(station_departures),
        routes=[train] if train else [],
    )


# Koder som betyder att resenärerna tas om hand -- de behöver ingen taxi.
# Reservläge när ReplacementTraffic-registret ännu inte känner till
# avgången -- se _replacement().
_REPLACEMENT_WORDS = ("buss ersätter", "ersättningsbuss", "ersättningstrafik",
                      "spårvagn", "taxi ersätter")


def _parse_date_local(value: str | None) -> str | None:
    """
    AdvertisedTimeAtLocation ("2026-09-06T09:24:00.000+02:00") -> "2026-09-06",
    i tidszonen tidsstämpeln själv bär -- inte konverterat till UTC först.
    En sen kvällsavgång kan annars hamna på fel kalenderdatum jämfört med
    vad ScheduledDepartureDate faktiskt menar.
    """
    dt = _parse_time(value)
    return dt.date().isoformat() if dt else None


def _first_stop_coords(record: dict) -> tuple[float, float] | None:
    """Hämtplatsen närmast den inställda stationen -- Sequence 1, annars första."""
    stops = (record.get("Stops") or {}).get("Stop") or []
    first = next((s for s in stops if s.get("Sequence") == 1), stops[0] if stops else None)
    if not first:
        return None
    location = ((first.get("StopPosition") or {}).get("Location")) or {}
    lat, lon = location.get("Latitude"), location.get("Longitude")
    return (lat, lon) if lat is not None and lon is not None else None


def build_replacement_index(records: list[dict]) -> dict[tuple[str, str], dict]:
    """
    (tågnummer, avgångsdatum) -> ReplacementTraffic-post.

    Ett ersättningsfordon kan täcka flera hopslagna inställda tåg samtidigt,
    så ReplacesTrains flattas till en post per (tåg, datum)-par.
    """
    index: dict[tuple[str, str], dict] = {}
    for r in records or []:
        replaces = (r.get("ReplacesTrains") or {}).get("ReplacesTrain") or []
        for t in replaces:
            ident = str(t.get("AdvertisedTrainIdent") or "")
            date = t.get("ScheduledDepartureDate")
            if ident and date:
                index.setdefault((ident, date), r)
    return index


def _replacement(
    dep: dict, replacement_index: dict[tuple[str, str], dict] | None = None
) -> tuple[bool, str, str | None, tuple[float, float] | None]:
    """
    Har avgången ersättningstrafik? Returnerar (har_ersättning, motivering,
    fordonsläge, koordinat).

    Kollar ReplacementTraffic-registret (JBS v1.0) först -- en riktig
    koppling till tåget, med verkligt fordonsläge (buss/taxi/...) och en
    GPS-spårad hållplats, inte en gissning. Trafikverkets täckning är dock
    ännu partiell ("All ersättningstrafik finns inte med men det kommer
    att utökas löpande"), så textmatchningen mot Deviation kvarstår som
    reservlösning -- mätt på live-data: 35 av 59 inställda avgångar bär
    "Buss ersätter" i sitt Deviation-fält, och utan den kontrollen rankas
    de som strandsatta perronger, den vanligaste falska högnoteringen i
    hela flödet.
    """
    train = str(dep.get("AdvertisedTrainIdent") or "")
    date_key = _parse_date_local(dep.get("AdvertisedTimeAtLocation"))
    record = (replacement_index or {}).get((train, date_key)) if train and date_key else None
    if record:
        mode = record.get("VehicleMode")
        detail = record.get("Description") or ""
        label = {"taxi": "Ersättningstaxi", "bus": "Ersättningsbuss"}.get(mode, "Ersättningstrafik")
        note = f"{label} redan insatt" + (f" ({detail})" if detail else "")
        return True, note, mode, _first_stop_coords(record)

    for d in dep.get("Deviation") or []:
        desc = str(d.get("Description") or "")
        if any(w in desc.lower() for w in _REPLACEMENT_WORDS):
            return True, desc, None, None
    return False, "", None, None


def _primary_cause(dep: dict) -> str:
    """
    Trafikverkets egen orsakstext, oavsett om den råkar handla om
    ersättningstrafik eller inte -- t.ex. "Spårändrat", "Signalfel", "Kort
    tåg". Första posten i Deviation räcker: mätt live, en enstaka avgång
    bär i praktiken aldrig mer än en verkligt relevant avvikelse åt gången.
    """
    deviations = dep.get("Deviation") or []
    if not deviations:
        return ""
    return str(deviations[0].get("Description") or "")


def _human_gap(minutes: int) -> str:
    """
    "360 minuter" är inget en förare räknar om i huvudet mitt i ett pass.
    """
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours} tim"
    return f"{hours} tim {rest} min"


def _next_departure(
    dep: dict, station_departures: list[dict], when: datetime
) -> tuple[int | None, bool]:
    """
    Finns en ersättande avgång, och hur snart?

    Detta är signalen hela fasen handlar om. Utan den kan systemet inte
    skilja ett verkligt strandsatt tåg från ett där nästa går om tio
    minuter -- båda fick 85 poäng.

    Returnerar (minuter till nästa avgång, är detta sista avgången).
    Nästa avgång räknas bara om den inte själv är inställd.
    """
    later = []
    for other in station_departures:
        if other is dep or other.get("Canceled") is True:
            continue
        t = _parse_time(other.get("AdvertisedTimeAtLocation"))
        if t and t > when:
            later.append(t)

    if not later:
        # Inget senare tåg i fönstret. Med 8h framförhållning är det ett
        # rimligt "sista avgången", men bara om vi faktiskt såg avgångar
        # på stationen -- annars vet vi ingenting.
        return None, len(station_departures) > 1

    gap = round((min(later) - when).total_seconds() / 60)
    if gap <= ALTERNATIVE_WITHIN.total_seconds() / 60:
        return gap, False
    return gap, False
