"""
Passagerarhamnarna AISStream-prenumerationen lyssnar på.

Varje hamn är en rektangel (BoundingBox) plus en terminalpunkt. Rektangeln
måste rymma inseglingen, inte bara kajen: AISStream skickar BARA meddelanden
inifrån rutorna, så ett fartyg vi aldrig sett i fart kan inte heller ses
sakta in -- och "saktar in efter att ha varit i fart" är hela ankomstsignalen
(se maritime/ais.py).

Varje hamn har också ett inseglingsområde (`approach`). Prenumerationen lyssnar på
inseglingsområdena, så att en färja syns på väg in och inte först i hamnrutan; ankomsten
avgörs fortfarande i hamnrutan. Livekartan (maritime/approach.py) använder områdena och
farledsfaktorn.

`tips=False`: hamnen visas på kartan men en ankomst ger inget tips. Helsingborg för att
färjorna går i pendel dygnet runt -- varje ankomst är ingen händelse. Hamnarna som lades
till 2026-09-18 tills deras terminalpunkt stämts av mot AIS-spår. `note` säger varför
hamnen finns med och varifrån punkten kommer.

Urvalet följer Trafikanalys, Sjötrafik 2024: Stockholms hamnar (inklusive Kapellskär,
Nynäshamn och Norvik) hade 7,2 miljoner passagerare, Helsingborg 6,4 miljoner, och därefter
i rangordning Visby, Ystad, Trelleborg, Göteborg och Strömstad. Terminalpunkterna för de
nya hamnarna är OpenStreetMaps `ferry_terminal`, hämtade 2026-09-18, där en sådan fanns.

Koordinaterna är avlästa från karta, inte kalibrerade mot uppmätta AIS-spår.
Kör `run_ais_stream -v 2` ett dygn och jämför var färjorna faktiskt passerar
5 knop innan rutorna krymps eller flyttas.

`region` och `city` följer samma regel som flygplatserna i core/thresholds.py:
regionen måste finnas i geo.REGION_ANCHOR och orten i REGION_CITIES för
regionen, annars filtrerar förarens ortsval bort tipset (core/notify.py
matchar ortnamnet som delsträng mot opportunity.places).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Port:
    key: str
    # places[0] och push-prefixet.
    name: str
    city: str
    region: str
    # Terminalen -- tipsets koordinat, det föraren kör mot.
    lat: float
    lon: float
    south: float
    west: float
    north: float
    east: float
    # Inseglingsområdet (syd, väst, nord, öst). None = bara hamnrutan.
    approach: tuple[float, float, float, float] | None = None
    # Farleden är längre än fågelvägen. Okalibrerat; används för beräknad ankomst på kartan.
    route_factor: float = 1.15
    tips: bool = True
    note: str = ""

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east

    @property
    def bounding_box(self) -> list[list[float]]:
        # AISStreams ordning är [[lat, lon], [lat, lon]] -- latitud FÖRST,
        # tvärtemot GeoJSON. Byter man plats hamnar rutan i Arabiska havet
        # och strömmen blir tyst utan felmeddelande.
        return [[self.south, self.west], [self.north, self.east]]

    @property
    def approach_bounds(self) -> tuple[float, float, float, float]:
        return self.approach or (self.south, self.west, self.north, self.east)

    def in_approach(self, lat: float, lon: float) -> bool:
        south, west, north, east = self.approach_bounds
        return south <= lat <= north and west <= lon <= east

    @property
    def approach_box(self) -> list[list[float]]:
        """Inseglingsområdet i AISStreams ordning, latitud först."""
        south, west, north, east = self.approach_bounds
        return [[south, west], [north, east]]


PORTS: tuple[Port, ...] = (
    # Tallink Silja (Helsingfors, Åbo, Tallinn, Riga). Rutan slutar söder om
    # Lidingöbron och norr om Stadsgårdens ruta -- de får inte överlappa,
    # annars byter ett fartyg hamn mitt i inseglingen. Inseglingen genom
    # skärgården delas med Stadsgården.
    Port(
        key="vartahamnen", name="Stockholm Värtahamnen", city="Stockholm", region="sl",
        lat=59.3510, lon=18.1080,
        south=59.336, west=18.080, north=59.372, east=18.160,
        approach=(59.250, 18.040, 59.700, 19.300), route_factor=1.35,
        note="Stockholms hamnar (inklusive Kapellskär, Nynäshamn och Norvik) hade flest passagerare 2024, 7,2 miljoner (Trafikanalys).",
    ),
    # Viking Line och Birka. Samma ruta fångar Skeppsbron, Nybroplan och
    # Waxholmsbolagets kajer -- längdgränsen i tips.py håller dem borta.
    Port(
        key="stadsgarden", name="Stockholm Stadsgården", city="Stockholm", region="sl",
        lat=59.3160, lon=18.0860,
        south=59.305, west=18.050, north=59.332, east=18.130,
        approach=(59.250, 18.040, 59.700, 19.300), route_factor=1.35,
        note="Stockholms hamnar (inklusive Kapellskär, Nynäshamn och Norvik) hade flest passagerare 2024, 7,2 miljoner (Trafikanalys).",
    ),
    # Gotlandsbåtarna, samt linjerna till Polen och Lettland.
    Port(
        key="nynashamn", name="Nynäshamn", city="Stockholm", region="sl",
        lat=58.9030, lon=17.9530,
        south=58.880, west=17.920, north=58.930, east=17.995,
        approach=(58.650, 17.850, 58.935, 18.350), route_factor=1.15,
        note="Stockholms hamnar (inklusive Kapellskär, Nynäshamn och Norvik) hade flest passagerare 2024, 7,2 miljoner (Trafikanalys).",
    ),
    # Stena Line: Frederikshavn (Masthugget) och Kiel (Majnabbe). En ruta
    # för båda terminalerna; de ligger två kilometer isär på samma älv.
    Port(
        key="goteborg", name="Göteborg Stena Line", city="Göteborg", region="vt",
        lat=57.6980, lon=11.9250,
        south=57.680, west=11.870, north=57.715, east=11.970,
        approach=(57.550, 11.450, 57.750, 11.970), route_factor=1.2,
        note="Bland de sju största passagerarhamnarna 2024 (Trafikanalys).",
    ),
    # Tysklands- och Polenfärjorna.
    Port(
        key="trelleborg", name="Trelleborg", city="Trelleborg", region="skane",
        lat=55.3690, lon=13.1520,
        south=55.340, west=13.100, north=55.385, east=13.200,
        approach=(55.100, 12.950, 55.385, 13.450), route_factor=1.05,
        note="Bland de sju största passagerarhamnarna 2024 (Trafikanalys).",
    ),
    # Bornholm och Polen.
    Port(
        key="ystad", name="Ystad", city="Ystad", region="skane",
        lat=55.4270, lon=13.8230,
        south=55.400, west=13.780, north=55.440, east=13.870,
        approach=(55.150, 13.550, 55.440, 14.250), route_factor=1.05,
        note="Bland de sju största passagerarhamnarna 2024 (Trafikanalys).",
    ),
    # Stena Line till Gdynia, från Verkö -- inte centrala Karlskrona. Terminalpunkten
    # rättad 2026-09-18: den gamla låg 3,5 km söderut. STENA ESTELLE låg förtöjd
    # (AIS-status 5) vid 56,1658/15,6296, och OpenStreetMaps ferry_terminal
    # "Karlskrona - Gdynia" ligger 25 m därifrån. Rutan utvidgad norrut så att kajen
    # inte ligger vid kanten.
    Port(
        key="karlskrona", name="Karlskrona Verkö", city="Karlskrona", region="blekinge",
        lat=56.1660, lon=15.6298,
        south=56.100, west=15.570, north=56.185, east=15.700,
        approach=(55.900, 15.450, 56.200, 15.950), route_factor=1.25,
    ),
    # Terminalpunkten rättad 2026-09-18 till OpenStreetMaps ferry_terminal "Visby - Nynäshamn";
    # den gamla låg en kilometer norrut.
    Port(
        key="visby", name="Visby", city="Visby", region="gotland",
        lat=57.6347, lon=18.2794,
        south=57.620, west=18.240, north=57.670, east=18.310,
        approach=(57.400, 17.700, 57.900, 18.310), route_factor=1.05,
        note="Bland de sju största passagerarhamnarna 2024 (Trafikanalys).",
    ),
    # --- Tillagda 2026-09-18: visas på kartan, ger inga tips än (se modulens docstring). ---
    Port(
        key="helsingborg", name="Helsingborg Knutpunkten", city="Helsingborg", region="skane",
        lat=56.0436, lon=12.6941,
        south=56.030, west=12.670, north=56.055, east=12.700,
        approach=(55.990, 12.560, 56.110, 12.720), route_factor=1.05, tips=False,
        note="Näst största passagerarhamnen, 6,4 miljoner 2024, med den turtäta linjen Helsingborg–Helsingör "
             "(Trafikanalys). Färjorna går i pendel, så en enskild ankomst ger ingen notis. "
             "Terminalpunkt: OpenStreetMap, Knutpunkten.",
    ),
    Port(
        key="stromstad", name="Strömstad", city="Strömstad", region="vt",
        lat=58.9335, lon=11.1697,
        south=58.920, west=11.140, north=58.950, east=11.190,
        approach=(58.850, 10.950, 59.000, 11.200), route_factor=1.25, tips=False,
        note="Bland de sju största passagerarhamnarna 2024 (Trafikanalys). Terminalpunkt: OpenStreetMap ferry_terminal Strömstad–Sandefjord.",
    ),
    Port(
        key="kapellskar", name="Kapellskär", city="Norrtälje", region="sl",
        lat=59.7207, lon=19.0615,
        south=59.705, west=19.030, north=59.735, east=19.090,
        approach=(59.550, 18.900, 60.050, 19.700), route_factor=1.2, tips=False,
        note="Stockholms hamnar (inklusive Kapellskär, Nynäshamn och Norvik) hade flest passagerare 2024, 7,2 miljoner (Trafikanalys). Terminalpunkt: OpenStreetMap, Kapellskärs hamn.",
    ),
    Port(
        key="grisslehamn", name="Grisslehamn", city="Norrtälje", region="sl",
        lat=60.0986, lon=18.8151,
        south=60.085, west=18.790, north=60.115, east=18.840,
        approach=(59.950, 18.750, 60.300, 19.700), route_factor=1.1, tips=False,
        note="Ålandsfärjan. Terminalpunkt: OpenStreetMap ferry_terminal.",
    ),
    Port(
        key="oskarshamn", name="Oskarshamn", city="Oskarshamn", region="klt",
        lat=57.2639, lon=16.4582,
        south=57.250, west=16.430, north=57.280, east=16.500,
        approach=(57.150, 16.430, 57.450, 17.100), route_factor=1.1, tips=False,
        note="Gotlandsfärjan. Terminalpunkt: OpenStreetMap ferry_terminal Oskarshamn–Visby.",
    ),
    Port(
        key="varberg", name="Varberg", city="Varberg", region="",
        lat=57.1110, lon=12.2420,
        south=57.095, west=12.200, north=57.130, east=12.260,
        approach=(56.950, 11.800, 57.250, 12.260), route_factor=1.05, tips=False,
        note="Danmarksfärjan. Terminalpunkten är uppskattad från hamnområdet i OpenStreetMap, "
             "inte en terminal: stäms av mot AIS.",
    ),
    Port(
        key="karlshamn", name="Karlshamn Stilleryd", city="Karlshamn", region="blekinge",
        lat=56.1600, lon=14.8168,
        south=56.140, west=14.790, north=56.175, east=14.850,
        approach=(55.950, 14.700, 56.175, 15.100), route_factor=1.15, tips=False,
        note="Litauenfärjan. Terminalpunkt: OpenStreetMap ferry_terminal Stillerydshamnen.",
    ),
    Port(
        key="malmo", name="Malmö Norra hamnen", city="Malmö", region="skane",
        lat=55.6264, lon=12.9947,
        south=55.615, west=12.960, north=55.645, east=13.010,
        approach=(55.450, 12.600, 55.700, 13.010), route_factor=1.1, tips=False,
        note="Tysklandsfärjan. Terminalpunkten är hamnområdet i OpenStreetMap, inte en terminal: "
             "stäms av mot AIS.",
    ),
    Port(
        key="umea", name="Umeå Holmsund", city="Umeå", region="",
        lat=63.6810, lon=20.3477,
        south=63.675, west=20.300, north=63.710, east=20.380,
        approach=(63.450, 20.300, 63.720, 21.100), route_factor=1.2, tips=False,
        note="Finlandsfärjan. Terminalpunkten är där AURORA BOTNIA stannade 2026-09-18 19:13 "
             "(0,9 knop), 1,1 km från hamnområdets mitt i OpenStreetMap. Ett enda anlöp: stäms av igen.",
    ),
)

_BY_KEY = {p.key: p for p in PORTS}
_BY_NAME = {p.name: p for p in PORTS}


def by_key(key: str) -> Port:
    return _BY_KEY[key]


def by_name(name: str) -> Port | None:
    return _BY_NAME.get(name)


def port_for(lat: float | None, lon: float | None) -> Port | None:
    if lat is None or lon is None:
        return None
    for port in PORTS:
        if port.contains(lat, lon):
            return port
    return None
