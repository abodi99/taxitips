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
from xml.sax.saxutils import quoteattr
from zoneinfo import ZoneInfo

import requests

from core.time_limits import reraise_time_limit

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

# Sidstorlek och tak för TrainAnnouncement. Dagtid ligger 14 000-15 000
# annonserade avgångar i åttatimmarsfönstret (mätt 2026-09-15). Den gamla frågan
# hämtade alla med limit 4000 och fick de första 4 000 i odefinierad ordning: en
# natt syntes 13 av 77 kommande inställda tåg.
PAGE_SIZE = 4000
MAX_PAGES = 10
# Stationer per fråga om avgångar vid drabbade stationer.
STATION_CHUNK = 40
LOCAL_TZ = ZoneInfo("Europe/Stockholm")

DEPARTURE_INCLUDES = "".join(
    f"<INCLUDE>{name}</INCLUDE>"
    for name in (
        "ActivityId", "AdvertisedTrainIdent", "LocationSignature", "AdvertisedTimeAtLocation",
        "ScheduledDepartureDateTime", "EstimatedTimeAtLocation", "Canceled", "ToLocation", "Deviation",
        # OtherInformation bär "Buss ers. Floda - Alingsås." på 11% av avgångarna.
        # TrackAtLocation och ProductInformation är 100% ifyllda även på inställda
        # avgångar -- "Pågatåg 1612 från Helsingborg C, spår 3" är mer värt för en
        # förare än "Skånetrafiken 1612". TypeOfTraffic skiljer bussavgångar från
        # tågavgångar i samma flöde. Se docs/api-field-inventory.md, förslag 6, 8 och 9.
        "OtherInformation", "TrackAtLocation", "ProductInformation", "TypeOfTraffic",
        "Operator", "InformationOwner", "WebLink", "WebLinkName",
    )
)

# Hur länge en strandsatt perrong räknas som en möjlighet.
PLATFORM_LIFETIME = timedelta(hours=1)

# En ersättande avgång inom det här fönstret betyder att ingen är
# strandsatt -- de väntar en kvart, de tar inte taxi. Tröskeln tillämpas i
# core/scoring.py (ALTERNATIVE_SOON_MIN), som äger poängsättningen; här
# hämtas bara glappet fram. Konstanten låg kvar i en gren som räknade ut
# samma sak två gånger och alltid returnerade samma värde.


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
    # Den absoluta tidpunkten, inte bara avståndet i minuter. Minuterna
    # räknas vid pollning och åldras: ett tips som skrevs för 20 minuter
    # sedan påstår fortfarande "om 45 min" när det i själva verket är 25.
    # Klockslaget åldras aldrig, och är dessutom det en förare kan agera på
    # ("tåget går 14:35") utan att räkna i huvudet.
    next_departure_at: datetime | None = None
    # Är nästa avgång från stationen en BUSS? 50 av 4 000 avgångar i
    # flödet har TypeOfTraffic "Buss" -- det är ersättningstrafiken själv,
    # inte ett tåg. Att kalla den "nästa avgång" utan att säga det gör
    # beskedet fel på ett sätt som spelar roll: en resenär som ser en buss
    # där tåget skulle gå vet att tåget inte kommer.
    next_departure_is_bus: bool = False
    is_last_departure: bool = False
    station_departures_in_window: int = 0
    # Trafikverket anger själv när ersättningstrafik är insatt. Mätt: 35 av
    # 59 inställda avgångar har "Buss ersätter" -- de resenärerna är inte
    # strandsatta, de går på en buss. Att visa dem som toppnotering är
    # exakt den sortens falska tips som kostar en förare en bomresa.
    # Spår och produktnamn, båda 100% ifyllda även på inställda avgångar.
    # "Pågatåg 1612 från Helsingborg C, spår 3" säger en förare var på
    # stationen folk står; "Skånetrafiken 1612" gör det inte.
    track: str = ""
    product: str = ""
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
    # Stationens och slutstationens signatur -- nycklarna för ResRobot-uppslaget.
    station_signature: str = ""
    destination_signature: str = ""
    # Varifrån "nästa avgång" kommer: "station" (nästa tåg från samma station, oavsett
    # riktning) eller "resrobot" (nästa resa mot samma slutstation, se
    # core/sources/resrobot.py). `alternative` är ResRobot-svaret som sparas i rådatan.
    alternative_basis: str = "station"
    alternative_label: str = ""
    alternative: dict | None = None


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
        # Vad senaste hämtningen såg: unika inställda tåg, sidor, komplett. Se _departures.
        self.last_stats: dict = {}

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
        except Exception as exc:
            reraise_time_limit(exc)
            log.exception("trafikverket-rail: kunde inte hämta ReplacementTraffic, faller tillbaka på textmatchning")
            self._replacements = {}
        return self._replacements

    def _departures(self) -> list[dict]:
        """
        Störda avgångar i fönstret, plus alla avgångar vid de stationer där en
        störning blir ett tips.

        Hela avgångslistan behövs vid de stationerna: för att veta om ett inställt
        tåg har en ersättare om tio minuter måste man se de avgångar som INTE är
        inställda. Men bara där. Förut hämtades varje annonserad avgång i landet i
        en fråga med limit 4000 -- se PAGE_SIZE.

        Två frågor, båda sidindelade i stabil ordning (ActivityId):

        1. Inställda eller med beräknad tid (en försening har alltid
           EstimatedTimeAtLocation). En vardag 07-15: 272 inställda och 3 031
           beräknade rader.
        2. Alla avgångar vid stationerna där en störning blir ett tips, STATION_CHUNK
           stationer åt gången. Samma fönster: 3 014 rader vid 103 stationer.
        """
        disrupted, complete, pages = self._query_all(
            '<OR><EQ name="Canceled" value="true"/>'
            '<EXISTS name="EstimatedTimeAtLocation" value="true"/></OR>'
        )
        affected = sorted(tip_stations(disrupted))
        rows = list(disrupted)
        for start in range(0, len(affected), STATION_CHUNK):
            chunk = affected[start:start + STATION_CHUNK]
            station_rows, chunk_complete, chunk_pages = self._query_all(
                "<OR>" + "".join(f'<EQ name="LocationSignature" value={quoteattr(sig)}/>' for sig in chunk) + "</OR>"
            )
            rows.extend(station_rows)
            complete = complete and chunk_complete
            pages += chunk_pages
        rows = unique_announcements(rows)
        cancelled = [d for d in rows if d.get("Canceled") is True]
        self.last_stats = {
            "window_hours": WINDOW_HOURS,
            "cancelled_trains": len({train_key(d) for d in cancelled}),
            "cancelled_departures": len(cancelled),
            "delayed_departures": sum(
                1 for d in rows if d.get("Canceled") is not True and minutes_late(d) >= SERIOUS_DELAY_MIN
            ),
            "tip_stations": len(affected),
            "rows": len(rows),
            "pages": pages,
            "complete": complete,
        }
        if not complete:
            log.warning("trafikverket-rail: ofullständig hämtning, sidtaket nåddes efter %d sidor", pages)
        return rows

    def _query_all(self, condition: str) -> tuple[list[dict], bool, int]:
        """Avgångar i fönstret som uppfyller `condition`, sida för sida tills en sida är kort."""
        rows: list[dict] = []
        for page in range(MAX_PAGES):
            block = self._query(
                '<QUERY objecttype="TrainAnnouncement" namespace="rail.trafficinfo"'
                f' schemaversion="1.9" limit="{PAGE_SIZE}" skip="{page * PAGE_SIZE}" orderby="ActivityId">'
                "<FILTER><AND>"
                '<EQ name="ActivityType" value="Avgang"/>'
                '<EQ name="Advertised" value="true"/>'
                '<GT name="AdvertisedTimeAtLocation" value="$now"/>'
                f'<LT name="AdvertisedTimeAtLocation" value="$dateadd({WINDOW_HOURS}:00:00)"/>'
                f"{condition}"
                "</AND></FILTER>"
                f"{DEPARTURE_INCLUDES}"
                "</QUERY>"
            )
            batch = block.get("TrainAnnouncement", [])
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                return rows, True, page + 1
        return rows, False, MAX_PAGES

    # -- normalisering -----------------------------------------------------
    def fetch(self, now: datetime | None = None, alternative_for=None) -> list[RailAlert]:
        if not self.api_key or self.api_key == "mock":
            log.info("trafikverket-rail: ingen nyckel, hoppar över")
            return []

        now = now or datetime.now(dt_timezone.utc)
        stations = self.stations()
        replacements = self.replacement_traffic()
        departures = self._departures()
        alerts = build_alerts(
            departures, stations, now, replacement_index=replacements, alternative_for=alternative_for,
        )
        self.last_stats.update({"alerts": len(alerts), "cancelled_alerts": sum(1 for a in alerts if a.cancelled)})
        return alerts


def train_key(dep: dict) -> tuple[str, str]:
    """Ett tåg är tågnummer och avgångsdag: samma nummer går igen nästa dag."""
    return str(dep.get("AdvertisedTrainIdent") or ""), str(dep.get("ScheduledDepartureDateTime") or "")[:10]


def unique_announcements(rows: list[dict]) -> list[dict]:
    """En rad per annons, även när två frågor (eller två sidor) gav samma."""
    seen: set = set()
    out = []
    for row in rows:
        key = row.get("ActivityId") or (
            row.get("AdvertisedTrainIdent"), row.get("LocationSignature"), row.get("AdvertisedTimeAtLocation")
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def first_cancelled_stops(departures: list[dict]) -> dict[str, str]:
    """
    Tåg -> tidpunkten för dess första inställda stopp i fönstret.

    Ett inställt tåg annonseras vid varje stopp det skulle betjänat -- tåg 7182 gav
    fem nästan identiska tips ner för Norrbottensbanan. Behåll tågets FÖRSTA stopp:
    där står den fullaste perrongen, och passagerare längre ner på linjen klev
    oftast aldrig på.
    """
    first_stop: dict[str, str] = {}
    for dep in departures:
        if dep.get("Canceled") is not True:
            continue
        train = dep.get("AdvertisedTrainIdent")
        when = dep.get("AdvertisedTimeAtLocation")
        if not train or not when:
            continue
        if train not in first_stop or when < first_stop[train]:
            first_stop[train] = when
    return first_stop


def tip_stations(disrupted: list[dict]) -> set[str]:
    """Stationerna där en störning blir ett tips: ett inställt tågs första stopp, eller 30+ min försening."""
    first_stop = first_cancelled_stops(disrupted)
    out: set[str] = set()
    for dep in disrupted:
        sig = dep.get("LocationSignature")
        if not sig:
            continue
        if dep.get("Canceled") is True:
            if first_stop.get(dep.get("AdvertisedTrainIdent")) == dep.get("AdvertisedTimeAtLocation"):
                out.add(sig)
        elif minutes_late(dep) >= SERIOUS_DELAY_MIN:
            out.add(sig)
    return out


def build_alerts(
    departures: list[dict], stations: dict[str, Station], now: datetime,
    replacement_index: dict[tuple[str, str], dict] | None = None,
    alternative_for=None,
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

    first_stop = first_cancelled_stops(disrupted)

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

    cancelled_trains = {
        str(d.get("AdvertisedTrainIdent")) for d in departures
        if d.get("Canceled") is True and d.get("AdvertisedTrainIdent")
    }
    return [
        _normalize(
            dep, stations.get(sig), by_station.get(sig, []), now, stations, replacement_index,
            alternative_for, cancelled_trains,
        )
        for sig, dep in best.items()
    ]


def _normalize(
    dep: dict,
    station: Station | None,
    station_departures: list[dict],
    now: datetime,
    stations: dict[str, Station] | None = None,
    replacement_index: dict[tuple[str, str], dict] | None = None,
    alternative_for=None,
    cancelled_trains: set[str] | frozenset = frozenset(),
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
    next_minutes, is_last, next_at, next_is_bus = _next_departure(
        dep, station_departures, when
    )

    # Fjärde signalen, och den starkaste: operatören säger rakt ut om
    # ersättningstrafik är insatt.
    replacement, note, replacement_mode, replacement_coords = _replacement(dep, replacement_index)

    # Nästa resa mot samma slutstation (ResRobot) i stället för nästa tåg från
    # stationen oavsett riktning -- bara för ett inställt tåg utan insatt ersättning,
    # och bara när anroparen skickat med ett uppslag. Utan svar gäller stationens.
    basis, alternative_label, alternative = "station", "", None
    if cancelled and not replacement and alternative_for is not None and to_sig:
        alternative = alternative_for(
            f"tvr:{sig}:{train}:{dep.get('AdvertisedTimeAtLocation')}", sig, to_sig, when, cancelled_trains,
        )
        departs = _parse_time((alternative or {}).get("departs_at"))
        if departs is not None:
            next_minutes = max(0, round((departs - when).total_seconds() / 60))
            next_at, next_is_bus, is_last = departs, alternative.get("mode") == "buss", False
            basis, alternative_label = "resrobot", str(alternative.get("label") or "")
        else:
            alternative = None

    # Vilket bolag som kör, och vilket namn resenären känner igen. SJ,
    # Öresundståg, Snälltåget m.fl. är inte utbytbara för en förare -- olika
    # operatörer betyder olika resenärsprofil och olika stationsvana.
    operator = str(dep.get("Operator") or "")
    information_owner = str(dep.get("InformationOwner") or "")
    # Produktnamnet först: det är vad som står på tavlan resenären läser,
    # och InformationOwner kan tillskriva en Kalmar-avgång "Jönköpings
    # Länstrafik". Se docs/api-field-inventory.md, förslag 8.
    product = _product(dep)
    track = str(dep.get("TrackAtLocation") or "").strip()
    # "x" är Trafikverkets platshållare för stationer utan spårnumrering
    # (132 av 4 000 avgångar). "Spår x" är inte en anvisning, det är brus
    # på ett kort en förare läser i farten.
    if track.lower() in ("x", "-", "0"):
        track = ""
    brand = product or information_owner or operator
    train_label = f"{brand} {train}" if brand else f"Tåg {train}"

    time_text = when.astimezone().strftime("%H:%M")
    if cancelled:
        header = f"{train_label} {time_text} är inställt från {name}"
        description = (
            f"Avgången {time_text} från {name}"
            f"{f' mot {to}' if to else ''} är inställd."
        )
        if track:
            description += f" Spår {track}."
        if replacement:
            description += f" {note}."
        elif basis == "resrobot":
            description += (
                f" Nästa resa mot {to or 'slutstationen'}: {alternative_label} "
                f"{next_at.astimezone(LOCAL_TZ).strftime('%H:%M')}, om {_human_gap(next_minutes)}."
            )
        elif next_minutes is not None:
            what = "Nästa avgång är en buss och går" if next_is_bus else "Nästa avgång går"
            description += f" {what} om {_human_gap(next_minutes)}."
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
        station_signature=sig,
        destination_signature=to_sig or "",
        alternative_basis=basis,
        alternative_label=alternative_label,
        alternative=alternative,
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
        next_departure_at=next_at,
        next_departure_is_bus=next_is_bus,
        is_last_departure=is_last,
        track=track,
        product=product,
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

Tre källor, i fallande ordning efter hur ofta de svarar (mätt
    2026-09-08 på 82 inställda avgångar, se docs/api-field-inventory.md):

    1. **`Deviation.Code == ANA007`** ("Buss ersätter") -- 34 av 82. En kod
       är stabilare än en formulering: Trafikverket kan skriva om texten
       utan att koden ändras.
    2. **`OtherInformation`** -- 11% av alla avgångar, bär "Buss ers. Floda
       - Alingsås." Lästes inte alls tidigare.
    3. **`ReplacementTraffic`-registret** (JBS v1.0) -- teoretiskt bäst:
       verkligt fordonsläge och en GPS-spårad hållplats. Praktiskt **0
       träffar** på de 82 inställda avgångarna. Registret är ännu partiellt
       ("All ersättningstrafik finns inte med men det kommer att utökas
       löpande"). Det står kvar först i koden eftersom det ger mest när det
       väl träffar -- men kommentaren som kallade det "den starkaste
       signalen" var fel om verkligheten och är borttagen.

    Textmatchningen är sist, som reserv.
    """
    train = str(dep.get("AdvertisedTrainIdent") or "")
    date_key = _parse_date_local(dep.get("AdvertisedTimeAtLocation"))
    record = (replacement_index or {}).get((train, date_key)) if train and date_key else None
    if record:
        mode = record.get("VehicleMode")
        # Description finns inte i svaret (0 av 1000 poster i stickprovet).
        # Läsningen står kvar med .get() -- fältet är dokumenterat och kan
        # fyllas -- men koden ska inte antyda att den brukar ge något.
        detail = record.get("Description") or ""
        label = {"taxi": "Ersättningstaxi", "bus": "Ersättningsbuss"}.get(mode, "Ersättningstrafik")
        note = f"{label} redan insatt" + (f" ({detail})" if detail else "")
        return True, note, mode, _first_stop_coords(record)

    # Koden före orden. ANA007 = "Buss ersätter".
    for d in dep.get("Deviation") or []:
        if str(d.get("Code") or "").upper() == "ANA007":
            desc = str(d.get("Description") or "").strip() or "Buss ersätter"
            return True, desc, "bus", None

    for d in dep.get("Deviation") or []:
        desc = str(d.get("Description") or "")
        if any(w in desc.lower() for w in _REPLACEMENT_WORDS):
            return True, desc, None, None

    # "Buss ers. Floda - Alingsås." står här, inte i Deviation.
    for info in dep.get("OtherInformation") or []:
        desc = str(info.get("Description") or "")
        if any(w in desc.lower() for w in _REPLACEMENT_WORDS):
            return True, desc, None, None

    return False, "", None, None


def _is_bus(dep: dict) -> bool:
    """TypeOfTraffic YNA002 = "Buss". 50 av 4 000 avgångar i flödet."""
    return any(
        str(t.get("Code") or "").upper() == "YNA002"
        or str(t.get("Description") or "").lower() == "buss"
        for t in (dep.get("TypeOfTraffic") or [])
    )


def _product(dep: dict) -> str:
    """
    Produktnamnet resenären ser på tavlan -- "SJ Regional", "Pågatåg".

    Mer tillförlitligt än InformationOwner, som kan tillskriva en
    Kalmar-avgång "Jönköpings Länstrafik". 100% ifyllt.
    """
    for item in dep.get("ProductInformation") or []:
        name = str(item.get("Description") or "").strip()
        if name:
            return name
    return ""


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
) -> tuple[int | None, bool, datetime | None, bool]:
    """
    Finns en ersättande avgång, och hur snart?

    Detta är signalen hela fasen handlar om. Utan den kan systemet inte
    skilja ett verkligt strandsatt tåg från ett där nästa går om tio
    minuter -- båda fick 85 poäng.

    Returnerar (minuter till nästa avgång, är detta sista avgången,
    tidpunkten för nästa avgång, är nästa avgång en buss). Nästa avgång
    räknas bara om den inte själv är inställd.
    """
    later = []
    for other in station_departures:
        if other is dep or other.get("Canceled") is True:
            continue
        t = _parse_time(other.get("AdvertisedTimeAtLocation"))
        if t and t > when:
            later.append((t, other))

    if not later:
        # Inget senare tåg i fönstret. Med 8h framförhållning är det ett
        # rimligt "sista avgången", men bara om vi faktiskt såg avgångar
        # på stationen -- annars vet vi ingenting.
        return None, len(station_departures) > 1, None, False

    nxt, record = min(later, key=lambda pair: pair[0])
    gap = round((nxt - when).total_seconds() / 60)
    return gap, False, nxt, _is_bus(record)
