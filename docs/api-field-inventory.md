# Fältinventering — vad datakällorna faktiskt innehåller

**Mätdatum: 2026-09-08, ca kl 09:30–10:30 lokal tid.** Alla ifyllnadsgrader
nedan är **ett stickprov från ett enda hämtningstillfälle**, inte statistik
över tid. Kvällstrafik, helg, snöstorm och sommartidtabell ger andra siffror.
Där jag inte kunnat mäta står det **"inte verifierat"** — det är inte samma
sak som "finns inte".

Adaptrarna som jämförs är `taxitips-backend/core/sources/*.py` som de såg ut
2026-09-08. Repot ändrades aktivt under mätningen (bl.a.
`trafikverket_rail.py`), så kontrollera radnummer innan du ändrar.

Kompletterar `docs/data-sources.md` (endpoints, nycklar, kvoter). Den här
filen handlar bara om **fälten**.

Stickprovsstorlekar:

| Källa | Poster i stickprovet |
|---|---|
| Trafiklab GTFS-RT ServiceAlerts | 538 alerts över 15 operatörskoder |
| Trafikverket `TrainAnnouncement` | 4 000 avgångar (8h-fönster, hela landet) |
| Trafikverket `ReplacementTraffic` | 1 000 poster |
| Trafikverket `OperativeEvent` (EventState=1) | 65 händelser |
| Trafikverket `TrainStation` | 718 stationer |
| Trafikverket `Situation` (väg) | 700 situationer → 1 177 `Deviation` (7 län) |
| SL deviations | 159 meddelanden |
| SL `/sites/{id}/departures` | 407 avgångar över 6 stationer |
| Västtrafik traffic-situations | 76 situationer |
| Västtrafik StopAreas | 11 182 hållplatsområden |
| SMHI snow1g punktprognos | 83 tidssteg för en punkt (Malmö) |

---

## Genomfört ur förslagslistan (uppdaterad 2026-09-08, huvudsessionen)

| # | Förslag | Status |
|---|---|---|
| 1 | Väg: `Deviation.StartTime` i stället för `PublicationTime` | **klart** |
| 2 | Väg: `Deviation.EndTime` med tak mot `ROAD_TTL` | **klart** |
| 3 | Väg: `MessageCode` + `IconId == roadClosed` styr allvarlighet | **klart** — koden når nu även poängsättningen via `cause` |
| 4 | SL: nästa avgång via `/v1/sites/{id}/departures` | **klart** — `enrich_next_departures()`, kräver både hållplats och linje |
| 6 | Järnväg: ersättning via `Deviation.Code ANA007` + `OtherInformation` | **klart** |
| 7 | Järnväg: beskriv `ReplacementTraffic` som den faktiskt beter sig | **klart** |
| 8 | Järnväg: `TrackAtLocation` + `ProductInformation` till föraren | **klart** — "x" filtreras som platshållare |
| 9 | Järnväg: flagga bussavgångar (`TypeOfTraffic`) | **klart** — räknas även som ersättningsindikator |
| 13 | SL: filtrera `FACILITY/LIFT` | **klart** |
| 14 | Ta bort/markera döda fältläsningar | **klart** — markerade, inte raderade |
| 5, 10, 11, 12, 15–19 | — | inte påbörjade |

Numren nedan är oförändrade; tabellen ovan säger bara vad som hunnit hända.

## 1. Trafiklab GTFS-RT ServiceAlerts

`https://opendata.samtrafiken.se/gtfs-rt-sweden/{operator}/ServiceAlertsSweden.pb`
Adapter: `core/sources/trafiklab.py`.

Operatörer som svarade med data: `skane 156, sl 193, varm 46, dt 21, otraf 20,
ul 19, vastmanland 17, jlt 16, dintur 14, orebro 13, klt 11, krono 3`.
`blekinge` och `gotland` svarade 200 med tom feed.

| Fält | Finns i spec | Ifyllnadsgrad (mätt) | Använder vi? | Värt att använda? |
|---|---|---|---|---|
| `header_text` | ja (required) | 538/538 (100%) | ja | ja — bär hela signalen |
| `description_text` | ja (required) | 538/538 (100%) | ja | ja |
| `active_period[0].start` | ja (optional) | 538/538 (100%) | ja | ja, men se fällan nedan |
| `active_period[0].end` | ja (optional) | 538/538 (100%) | ja | **nej som "störningen slutar"** — se fällan |
| `active_period` med >1 intervall | ja | 0/538 (0%) | nej | nej |
| `cause` | ja | 538/538 (100%) | byggs, används ej | nej — CONSTRUCTION 285, OTHER_CAUSE 196, TECHNICAL_PROBLEM 33, MAINTENANCE 22, POLICE_ACTIVITY 1, ACCIDENT 1. Texten bär redan detta |
| `effect` | ja | 538/538 men **alltid `UNKNOWN_EFFECT`** | byggs, används ej | nej |
| `severity_level` | ja (experimental) | **0/538 (0%)** | nej | nej — aldrig satt av någon svensk operatör i stickprovet |
| `url` | ja | **0/538 (0%)** | ja (blir alltid None) | nej — död läsning |
| `tts_header_text` / `tts_description_text` | ja | 0/538 (0%) | nej | nej |
| `cause_detail` / `effect_detail` / `image` | ja (experimental) | 0/538 (0%) | nej | nej |
| `informed_entity` (minst en) | ja (required) | 538/538 (100%) | ja | ja |
| `informed_entity.route_id` | ja | 186/538 (35%) | ja (till `routes`) | **ja, mer än idag** — se nedan |
| `informed_entity.stop_id` | ja | 416/538 (77%) | ja (till `stops`) | delvis — id-rymden går inte att joina |
| `informed_entity.agency_id` | ja | **0/538 (0%)** | ja (blir aldrig något) | nej — död läsning |
| `informed_entity.route_type` | ja | **0/538 (0%)** | nej | nej — hade annars gett färdsätt gratis |
| `informed_entity.trip.trip_id` | ja | 74/538 (14%) | nej | nej — id-rymden joinar inte |
| `informed_entity.trip.direction_id` | ja | 0/538 (0%) | nej | nej |
| `informed_entity.trip.start_time` / `start_date` | ja | **0/538 (0%)** | nej | nej — hade annars varit "vilken avgång" |
| `translation.language` | ja | 538/538 med **tom sträng** | ja (letar `sv`) | fungerar via fallback, men matchningen på `sv` träffar aldrig |

### Nytt som mätningen visar

**`route_id` bär länskoden.** Alla `route_id` är 16 tecken på formen
`9011` + tresiffrig SCB-länskod + linjenummer. Kontrollerat mot operatören:
`skane`→012 Skåne, `sl`→001 Stockholm, `klt`→008 Kalmar, `dt`→020 Dalarna,
`dintur`→022 Västernorrland, `xt`→021 Gävleborg, osv. 100% konsekvent i
stickprovet. Ett undantag: 21 skånska referenser har `9011110…`, alltså
länskod `110` som inte finns i SCB:s register — sannolikt dansk/Öresunds­trafik.
Inte verifierat.

Det här är värdefullt eftersom `extract_areas()` idag geografiskt placerar
larm med en **regexlista av ortnamn**. För 186 av 538 larm (35%) finns
länstillhörigheten strukturerat i `route_id` och behöver inte gissas ur text.

**Korrigering till `docs/data-sources.md`:** dokumentet slår fast att
Sweden-familjens flöden "beskriver fel region" eftersom stop_id har
"länssiffror 05 = Östergötland". Mätningen säger något annat: **varenda
16-teckens `stop_id` i hela stickprovet börjar på `902205`, oavsett
operatör** — `skane`, `sl`, `dintur`, `dt`, alla. `05` är alltså inte en
länssiffra i den här id-rymden utan en fast prefixdel. Slutsatsen att
id:na **inte joinar** mot GTFS Regional-statiken står kvar (formaten är
helt olika), men motiveringen "det är Östergötlandsdata" stämmer inte:
`route_id`-länskoderna följer operatören exakt. Skilj på "fel id-format"
och "fel region".

**Två id-rymder för `stop_id` inom samma feed.** 368 unika 16-teckens-id
och 296 unika korta id (2–5 siffror, t.ex. `26515`, `10741`). Hypotesen att
det korta id:t är kärnan i det långa håller inte: **1 av 296** korta id
återfinns som mittdelen i ett långt. De korta SL-id:na matchar inte heller
SL:s eget register särskilt väl (11/89 mot site-id, 10/89 mot stop_area-id,
22/89 mot stop_point-id — låga nog att vara sammanträffanden). De 175 långa
SL-id:na matchar **0** av SL:s egna `stop_point.gid` (som har formen
`9022001…`, alltså `9022` + länskod).

### Fällor

- **`active_period.end` är inte när störningen är över.** Median­varaktighet
  i stickprovet: **1 083 timmar (45 dygn)**. 330 av 538 (61%) sträcker sig
  över 30 dygn, 232 slutar mer än 30 dygn fram i tiden, en enda hade redan
  passerat. Bara 80 av 538 (15%) är kortare än ett dygn. Samma fälla som
  SL:s `publish`-fönster.
- **Varaktigheten varierar enormt per operatör.** `varm` (Värmland) har
  median **1,1 timme** och 31 av 46 under ett dygn — där ÄR fältet en
  störningslängd. `dintur`, `jlt`, `xt`, `dt` ligger på 1 500–1 900 timmars
  median. Ett globalt tröskelvärde behandlar de här operatörerna orättvist.
- **Språkfältet är tomt.** Alla 538 översättningar har `language: ""`.
  `pick_translation()` letar efter `sv` och faller alltid tillbaka på
  `items[0]`. Fungerar, men koden ser ut att göra något den inte gör.
- **Ersättningstrafik nämns nästan aldrig.** Bara 5 av 538 texter innehåller
  "ersättningsbuss"/"buss ersätter"/"ersättningstrafik". 2 nämner taxi.
  **0 av 538** nämner "nästa avgång". 159 (30%) nämner
  "alternativ"/"omled"/"hänvis".

---

## 2. Trafikverket järnväg — `TrainAnnouncement` (rail.trafficinfo 1.9)

Adapter: `core/sources/trafikverket_rail.py`. Stickprov: 4 000 annonserade
avgångar i ett 8-timmarsfönster, hela landet. 82 (2,1%) inställda.

| Fält | Finns i spec | Ifyllnadsgrad (mätt) | Använder vi? | Värt att använda? |
|---|---|---|---|---|
| `AdvertisedTimeAtLocation` | ja | 4000/4000 (100%) | ja | ja |
| `AdvertisedTrainIdent` | ja | 4000/4000 (100%) | ja | ja |
| `LocationSignature` | ja | 4000/4000 (100%) | ja | ja |
| `Canceled` | ja | 82 true / 3 918 false (100% satt) | ja | ja |
| `EstimatedTimeAtLocation` | ja | **127/4000 (3%)** | ja | ja, men se fällan |
| `TimeAtLocation` | ja | **0/4000 (0%)** | ja (fallback) | nej i framtidsfönster — sätts först när tåget passerat |
| `ToLocation` | ja | 4000/4000 (100%) | ja (destination) | ja |
| `ViaToLocation` | ja | 3 129/4000 (78%) | **nej** | ja — "via Ksus" ger resvägen |
| `Deviation[].Description` | ja | 287/4000 (7%); 82/82 på inställda | ja (`cause`, textmatchning) | ja |
| `Deviation[].Code` | ja | samma 7% | **nej** | **ja** — stabil kod (ANA027=Inställt, ANA007=Buss ersätter, ANA006=Buss) i stället för textmatchning |
| `Operator` | ja | 3 999/4000 (100%) | ja | ja |
| `InformationOwner` | ja | 3 999/4000 (100%) | ja | ja, men se fällan |
| `TrainOwner` | ja | 3 980/4000 (100%) | nej | marginellt |
| `ProductInformation[].Description` | ja | **4000/4000 (100%)** | **nej** | **ja** — varumärket resenären känner igen: "Pågatågen", "Mälartåg", "Öresundståg" |
| `TypeOfTraffic[].Description` | ja | **4000/4000 (100%)** | **nej** | **ja** — Tåg 2 498, Pendeltåg 1 433, **Buss 69** |
| `TrackAtLocation` | ja | **4000/4000 (100%)** | **nej** | **ja** — spårnumret. 82/82 även på inställda avgångar |
| `WebLink` / `WebLinkName` | ja | 4000/4000 (100%) | ja | ja |
| `MobileWebLink` | ja | 1 356/4000 (34%) | nej | marginellt |
| `ScheduledDepartureDateTime` | ja | 4000/4000 (100%) | nej (härleder datum ur `AdvertisedTimeAtLocation`) | ja — se nedan |
| `OtherInformation[].Description` | ja | 448/4000 (11%) | **nej** | **ja** — bär "Buss ers. Floda – Alingsås.", "Byte till buss vid Floda.", "Stannar ej vid …" |
| `Booking` | ja | 689/4000 (17%) | nej | nej |
| `Service` (Kiosk/Bistro) | ja | 272/4000 (7%) | nej | nej |
| `TrainComposition` | ja | 274/4000 (7%) | nej | nej |
| `OperationalTrainNumber` | ja | 3 930/4000 (98%) | nej | nej |
| `ModifiedTime` | ja | 4000/4000 (100%) | nej | marginellt (upptäck ändringar) |

**`Deviation`-koder i stickprovet (topp):** `ANA006 Buss` 69, `ANA031 Kort
tåg` 63, `ANA027 Inställt` 48, `ANA053 Spårfel` 36, `ANA007 Buss ersätter`
34, `ANA075 Invänta info` 25, `ANA274 Buss 22A/38N/38A` 35 tillsammans,
`ANA003 Banarbete` 14, `ANA055 Spårändrat` 8, `ANA078 Åter i trafik` 6.

### Fällor

- **`TypeOfTraffic = "Buss"` är 69 av 4 000 avgångar — det är
  ersättningsbussarna som annonseras som egna avgångar med stationssignatur.**
  Adaptern skiljer inte på dem: de räknas in i `station_departures_in_window`
  och kan bli "nästa avgång" i beskrivningstexten, som då säger "nästa
  avgång går om X min" om en buss. Det är delvis rätt men beskrivs fel.
  Alla 69 bär också `Deviation.Code = ANA006`.
- **`_REPLACEMENT_WORDS` missar bussarna.** Ordlistan matchar `"buss
  ersätter"` (34 träffar) men inte `"Buss"` (69) eller `"Buss 22A"`-familjen
  (35). Mätt på de 82 inställda: 34/82 (41%) matchar dagens ordlista.
- **`InformationOwner` kan vara fel varumärke.** Ett inställt tåg från
  Kalmar C hade `InformationOwner = "Jönköpings Länstrafik"` (Krösatåg
  körs av JLT men avgår i Kalmar). Rubriken blir "Jönköpings Länstrafik
  28806 … från Kalmar C". `ProductInformation` hade gett rätt varumärke.
- **`EstimatedTimeAtLocation` finns bara på 3%** eftersom fönstret är
  framtiden — prognosen sätts sent. `minutes_late()` returnerar därför 0
  för nästan alla, och "kraftigt försenad" som signal fångar i praktiken
  bara de närmaste avgångarna. I stickprovet: 17 inställda mot 1 försenad
  bland de 18 byggda larmen.
- **`ScheduledDepartureDateTime` vs lokalt datum:** skiljer sig i **1 av
  4 000** poster. Adapterns `_parse_date_local()`-genväg är alltså nästan
  alltid rätt — men den enda avvikelsen är exakt den nattavgång som
  `ReplacementTraffic`-joinen behöver.

### `TrainStation` (rail.infrastructure 1.5) — 718 stationer

| Fält | Ifyllnadsgrad | Använder vi? | Värt att använda? |
|---|---|---|---|
| `LocationSignature` | 718/718 | ja | ja |
| `AdvertisedLocationName` | 718/718 | ja | ja |
| `Geometry.WGS84` | 718/718 | ja | ja |
| `AdvertisedShortLocationName` | 718/718 | nej | ja — kortnamn för trånga kort/pushar |
| `CountyNo` | 659/718 (92%) | **nej** | **ja** — geofence per län utan ortnamnsregex |
| `PlatformLine` | 588/718 (82%) | nej | marginellt |
| `LocationInformationText` | 469/718 (65%) | nej | inte verifierat vad det innehåller |
| `PrimaryLocationCode` | 699/718 (97%) | nej | ja — joinnyckel mot `ReplacementTraffic.Stops[].PrimaryLocationCode` |
| `Prognosticated` | 597/718 (83%) | nej | ja — säger om stationen alls har prognosdata |

### `ReplacementTraffic` (JBS 1.0) — och varför den inte fungerar idag

Stickprov: 1 000 poster.

| Fält | Ifyllnadsgrad | Använder vi? | Värt att använda? |
|---|---|---|---|
| `ReplacesTrains.ReplacesTrain[].AdvertisedTrainIdent` + `ScheduledDepartureDate` | 1000/1000 | ja (joinnyckel) | ja |
| `VehicleMode` | 1000/1000 (bus 991, taxi 9) | ja | ja |
| `Status` | 1000/1000 | ja (filter) | **se nedan — otillförlitligt** |
| `Stops.Stop[].StopPosition.Location.Latitude/Longitude` | 1000/1000 | ja (första stoppet) | ja |
| `Stops.Stop[].StopDescription` | 1000/1000 | **nej** | **ja** — "Luleå Central. Hpl. stationsplanen." är exakt var föraren ska köra |
| `Stops.Stop[].PlannedDepartureTime` / `PlannedArrivalTime` | 1000/1000 | **nej** | **ja** — när ersättningsbussen går |
| `Stops.Stop[].PlaceSignature` / `PrimaryLocationCode` | 1000/1000 | nej | ja — join mot `TrainStation` |
| `VehicleIdentifier` | 850/1000 (85%) | nej | nej |
| `Description` | **0/1000 (0%)** | **ja** (`record.get("Description")`) | **nej — fältet finns inte i svaret alls** |

**Den viktigaste mätningen i hela dokumentet:**

> Av 82 inställda avgångar i dagens 8-timmarsfönster joinade **0** mot
> `ReplacementTraffic` — varken med adapterns statusfilter (29 nycklar) eller
> helt ofiltrerat (636 nycklar).

Orsaken syns i datumfördelningen: av 1 000 poster ligger 813 i juni 2026,
60 i augusti, 76 i september. Bland de poster som har status
`running`/`confirmed`/`ordered` är avgångsdatumen `2026-06-10` (4st),
`2026-06-17` (1), `2026-06-23` (3) och sedan `2026-09-15` till `2026-09-25`
(21st). **Ingen enda för idag.** En post med status `running` avser ett tåg
som skulle gått 2026-06-17 — statusen städas alltså inte.

Slutsats: hela `ReplacementTraffic`-vägen i adaptern är idag effektivt död
kod. Textmatchningen mot `Deviation` gör 100% av arbetet (34/82), och
`replacement_mode`, `replacement_coords` och detaljtexten sätts aldrig.
Det är inte fel att behålla registret — Trafikverket säger själva att
täckningen byggs ut — men det bör inte beskrivas som "den starkaste
signalen" i koden när den ger noll träffar.

**Alternativ som faktiskt fungerar idag:** 16 av 82 inställda avgångar har
en `TypeOfTraffic = Buss`-avgång vid *samma* `LocationSignature` inom en
timme. Det är en svagare men verklig koppling. (Av de 34 med "Buss ersätter"
i `Deviation` var det bara 2 — bussen annonseras oftast från en annan
station än den där tåget ställdes in.)

### `OperativeEvent` (ols.open 1.0) — kandidat, inte inkopplad

Stickprov: 65 händelser med `EventState=1`.

| Fält | Ifyllnadsgrad | Använder vi? | Värt att använda? |
|---|---|---|---|
| `EventType.Description` + `EventTypeCode` | 65/65 (100%) | nej | ja — verklig orsakstext, "Banarbete/transport" 39, "Spår (solkurva…)" 8, "Kontaktledning" 3, "Polis/sjukdom" 1 |
| `EventSection[].FromLocation.Signature` | 65/65 (100%) | nej | ja — joinnyckel mot stationsregistret |
| `EventSection[].ToLocation.Signature` | 48/65 (74%) | nej | ja |
| `CountyNo` | 65/65 (100%) | nej | ja |
| `Geometry.WGS84` | 65/65 (100%) | nej | ja — **men se axelfällan** |
| `StartDateTime` | 65/65 (100%) | nej | ja, med förbehåll |
| `EndDateTime` (toppnivå) | **0/65 (0%)** | nej | nej |
| `TrafficImpact[].EndDateTime` | 68/68 poster, varav **14 redan passerade** | nej | ja — enda tillförlitliga "pågår till" |
| `TrafficImpact[].ForecastType` | 68/68, alltid `TRAFIKPÅVERKAN` | nej | nej |
| `TrafficImpact[].SelectedSection[].OperatingLevel` | 157 värden (1:148, 2:6, 4:2, 3:1) | nej | inte verifierat vad nivåerna betyder |
| `…SectionLocation[].PossibleTravelerExchange` | 3 257 värden (true 1 993, false 1 264) | nej | **ja** — säger per station om resenärsutbyte är möjligt, dvs. om folk faktiskt strandas där |
| `TrafficImpact[].PublicMessage.Header`/`Description` | **28/65 händelser (43%)** med icke-tom text | nej | ja — färdig svensk publiktext med egen start/sluttid |
| `RailRoadTimeForServiceResumption` | **0/65 (0%)** | nej | nej |
| `RoadDegreeOfImpact` | **0/65 (0%)** | nej | nej |
| `EventTrafficType` | 65/65, alltid `0` (endast järnväg) | nej | nej |

**Fällor:**

- **Axelordningen är omvänd mot `TrainStation`.** `TrainStation.Geometry.WGS84`
  är `POINT (11.97 57.71)` = **lon lat** (Göteborg C). `OperativeEvent.Geometry.WGS84`
  är `POINT (60.47 14.84)` = **lat lon** (Dalarna). Samma API, samma fältnamn,
  motsatt ordning. `parse_point()` i `trafikverket_rail.py` är skriven för
  stationsformatet — återanvänds den rakt av för `OperativeEvent` hamnar varje
  händelse fel. Kontrollvärde: 55,96/12,78 är Helsingborgstrakten; läst
  lon-först blir det Somalias kust.
- **`EventState = 1` betyder inte "pågår nu".** 44 av 65 har `StartDateTime`
  i det förflutna (äldsta 367 dygn), och en ligger 32 dygn i framtiden.
- Utan `EventState`-filter dominerar avslutade händelser: i ett ofiltrerat
  urval om 500 hade **497** `EventState = 0`.

---

## 3. Trafikverket väg — `Situation` (road.trafficinfo 1.6)

Adapter: `core/sources/trafikverket_road.py`. Stickprov: 7 län (Stockholm,
Skåne, V Götaland, Halland, Östergötland, Dalarna, Norrbotten), 700
situationer → 1 177 `Deviation`.

| Fält | Ifyllnadsgrad (mätt) | Använder vi? | Värt att använda? |
|---|---|---|---|
| `Deviation.Id` | 1177/1177 (100%) | ja | ja |
| `Deviation.MessageType` | 1177/1177 (100%) | ja | ja — men bara 3 värden: Vägarbete 672, Trafikmeddelande 478, Färjor 27 |
| `Deviation.MessageCode` | **1177/1177 (100%)** | **nej** | **ja** — Vägarbete 603, Körfältsavstängningar 323, Hastighetsbegränsning 113, Beläggningsarbete 65, **Vägen avstängd 33**, Färja 27, Sprängningsarbete 4, Vägskada 1, Djur på vägen 1 |
| `Deviation.IconId` | 1177/1177 (100%) | ja | ja — roadwork 672, trafficMessage 445, roadClosed 33, ferry* 27 |
| `Deviation.SeverityText` / `SeverityCode` | 1 049/1177 (89%) | ja | ja — Liten 491, Stor 420, Mycket stor 98, Ingen 40 |
| `Deviation.StartTime` | **1177/1177 (100%)** | **nej** | **ja** — se fällan om `PublicationTime` |
| `Deviation.EndTime` | **1 153/1177 (98%)** | **nej** (`active_to` sätts alltid till `None` och skrivs över med `now + 4h` i `poll_road.py`) | **ja, med tak** — se fällan |
| `Deviation.CreationTime` / `VersionTime` | 1177/1177 (100%) | nej | marginellt |
| `Deviation.Message` | 1 024/1177 (87%) | ja | ja |
| `Deviation.LocationDescriptor` | 1 050/1177 (89%) | ja | ja |
| `Deviation.RoadNumber` / `RoadNumberNumeric` | 938/1177 (80%) | ja | ja |
| `Deviation.RoadName` | 552/1177 (47%) | **nej** | ja — gatunamn där vägnummer saknas |
| `Deviation.Header` | **28/1177 (2%)** | ja (första valet) | fungerar via fallback till `MessageType` |
| `Deviation.AffectedDirectionValue` | **1177/1177 (100%)** | nej | ja — BothDirections 829, OneDirection 348 |
| `Deviation.TrafficRestrictionType` | 722/1177 (61%) | nej | ja — alltid "Körfält blockerade" i stickprovet |
| `Deviation.NumberOfLanesRestricted` | 722/1177 (61%) | nej | ja — hur många körfält |
| `Deviation.Suspended` | **763/1177 (65%) = true** | **nej** | **ja** — se fällan |
| `Deviation.ManagedCause` | 701/1177 (60%) = true | nej | inte verifierat vad det betyder |
| `Deviation.TemporaryLimit` | 124/1177 (11%) | nej | marginellt (tillfällig hastighet) |
| `Deviation.CountyNo` | 1 175/1177 (100%) | bara som filter | ja — spara den i stället för att regex:a ortnamn |
| `Deviation.Geometry.Line.WGS84` | 1 128/1177 (96%) | ja | ja |
| `Deviation.Geometry.Point.WGS84` | 1 175/1177 (100%) | ja (fallback) | ja |
| `Deviation.WebLink` | 28/1177 (2%) | nej (`url` hårdkodas till None) | nej |
| `Deviation.ValidUntilFurtherNotice` | 24/1177 (2%) | nej | ja — säger uttryckligen "inget slut känt" |
| `Deviation.PositionalDescription` | 24/1177 (2%) | nej | nej |
| `Situation.PublicationTime` | 700/700 (100%) | ja (som `active_from`) | **nej — se fällan** |

### Fällor

- **`PublicationTime` är inte när händelsen började.** Mätt:
  `StartTime − PublicationTime` har **median −862 timmar** (spann −68 955 h
  till +4 049 h). `PublicationTime` är alltså i regel *långt efter* att
  avvikelsen började — den uppdateras när posten republiceras. Adaptern
  sätter `active_from = PublicationTime`, vilket får ett år gammalt vägarbete
  att se ut som brandfärskt. `Deviation.StartTime` finns på 100% och är rätt fält.
- **`EndTime` finns (98%) — men är oftast ett års planeringsfönster.**
  Medianvaraktighet `EndTime − StartTime` är **8 379 timmar (≈349 dygn)**.
  Bara 12 av 1 177 (1%) är kortare än ett dygn. Att bara byta in `EndTime`
  som `active_to` skulle låta vägtips ligga kvar i ett år. Rätt användning är
  `min(EndTime, now + ROAD_TTL)` — och att visa "pågår till …" för föraren
  bara när `EndTime` ligger inom något dygn.
- **65% av avvikelserna är `Suspended = true`.** Fördelning: Vägarbete
  522 av 672 suspended, Trafikmeddelande 241 av 478. Om fältet betyder
  "tillfälligt vilande" (t.ex. helguppehåll i vägarbetet) visar vi idag
  hundratals händelser som pausade. Betydelsen är **inte verifierad** mot
  spec — Trafikverkets dokumentationsportal är en SPA och gick inte att läsa
  maskinellt. Detta bör verifieras innan fältet används, men fördelningen är
  för stor för att ignoreras.
- **`level_for_deviation()` missar avstängda vägar.** Funktionen letar efter
  "olycka"/"avstäng" i `MessageType` + `IconId`. `MessageType` har bara tre
  värden (inget av dem innehåller de orden) och `IconId` är engelskt
  (`roadClosed`). Mätt: av 33 avvikelser med `MessageCode = "Vägen avstängd"`
  får **25 nivån `low`** — bara de 8 som råkar ha "Mycket stor påverkan" blir
  `high`. Ordet "avstäng" finns i `MessageCode`, som funktionen inte läser.
  Samma sak för "olycka": **0 träffar i hela stickprovet** — värdet
  förekommer inte i `MessageType`/`IconId` alls.
- **Feeden innehåller passerade poster.** 10 av 1 177 har `EndTime` i det
  förflutna (äldsta 2025-06-02). Antalet aktiva just nu
  (`StartTime ≤ now < EndTime`) var 1 138 av 1 177.

---

## 4. SL — deviations

`https://deviations.integration.sl.se/v1/messages`. Adapter: `core/sources/sl.py`.
Stickprov: 159 meddelanden, varav **25 agerbara** enligt `is_actionable()`.

| Fält | Finns i spec | Ifyllnadsgrad (mätt) | Använder vi? | Värt att använda? |
|---|---|---|---|---|
| `deviation_case_id` | ja | 159/159 (100%) | ja | ja |
| `version`, `created` | ja | 159/159 (100%) | **nej** | ja — `created` är när ärendet uppstod, oberoende av republiceringar |
| `modified` | dokumenterad | **0/159 (0%)** | nej | nej — finns inte i svaret |
| `publish.from` / `publish.upto` | ja | 159/159 (100%) | ja | ja, men se fällan |
| `message_variants[].header` | ja | 159/159 (100%) | ja | ja |
| `message_variants[].details` | ja | 159/159 (100%) | ja | **ja, mer än idag** — se nedan |
| `message_variants[].scope_alias` | ja | 159/159 (100%) | ja (`route_label`) | ja |
| `message_variants[].language` | ja | 159/159, alltid `sv` | ja | ja |
| `message_variants[].weblink` | — | **0/159 (0%)** | **ja** (blir alltid None) | nej — **död läsning, fältet finns inte** |
| `priority.importance_level` | ja | 159/159 (5:80, 7:62, 2:17) | ja (konfidens) | ja |
| `priority.influence_level` | ja | 159/159 (5:131, 3:27, 7:1) | ja | ja |
| `priority.urgency_level` | ja | 159/159, **alltid `1`** | ja | nej — konstant, bär ingen information |
| `scope.lines[].designation` | ja | 159/159 (100%) | ja | ja |
| `scope.lines[].transport_mode` | ja | 159/159 (BUS 255, METRO 21, TRAIN 12, TRAM 8, SHIP 5) | ja (`mode_hint`) | ja |
| `scope.lines[].group_of_lines` | ja | 38/159 (24%) | nej | marginellt |
| `scope.lines[].id` | ja | 159/159 (100%) | nej | ja — server-side filter, se nedan |
| `scope.stop_areas[].id` / `.name` | ja | 97/159 (61%) **men bara 2/25 bland de agerbara** | ja (geokodning) | ja när den finns |
| `scope.stop_areas[].stop_points[]` | ja | 27/159 (17%), 1/25 agerbara | nej | marginellt |
| `categories[].group` / `.type` | ja | **10/159 (6%), samtliga `FACILITY/LIFT`** | nej | ja — som **uteslutningsfilter**: hissfel är ingen taxisignal |

### Det här är den viktigaste SL-mätningen

`details`-texten är **starkt mallad**. Av de 25 agerbara innehåller **21
(84%)** mönstret `"… från|mellan <hållplatsnamn> [kl] HH:MM …"`:

```
Inställd avgång för buss linje 4 mellan Varvsgatan kl 6:45 och Fridhemsplan pga tekniskt fel.
Förseningar upp till 15 minuter för buss linje 865 från Skärholmen 08:52 mot Rudsjöterrassen …
```

Av de 21 utvunna hållplatsnamnen gick **19 (90%)** att slå upp direkt mot
`sites`-registret (5 980 namn med koordinat). Det ger både **koordinat** och
**avgångstid** för Stockholmslarm som idag har `lat/lon = null`, utan att
hitta på något: namnet står i SL:s egen text.

De två som föll: en falsk träff ("kl.") och `"Sollentuna station"` (registret
har ett annat namn för den).

### Fällor

- **`publish` är publiceringsfönstret, inte störningen.** Median 52,8 dygn;
  103 av 159 längre än 30 dygn, längsta 4 210 dygn. Median ålder sedan
  `publish.from`: 472 timmar; 35 av 159 är äldre än 90 dygn. Bara 33 är
  yngre än ett dygn. (Redan dokumenterat i `data-sources.md` — bekräftas här.)
- **Hisslarm ligger i flödet.** 10 poster är `FACILITY/LIFT`. De filtreras
  idag bort av åldersfiltret, inte av något som förstår vad de är.

### Oanvänd endpoint: `/v1/sites/{siteId}/departures`

Ingen nyckel, ingen kvot. Stickprov 407 avgångar över 6 stationer.

| Fält | Ifyllnadsgrad | Använder vi? | Värt att använda? |
|---|---|---|---|
| `scheduled` | 407/407 (100%) | nej | **ja** |
| `expected` | 407/407 (100%) | nej | **ja** |
| `state` | 407/407 — EXPECTED 369, ATSTOP 26, **CANCELLED 12 (3%)** | nej | **ja** |
| `destination`, `direction`, `direction_code` | 407/407 (100%) | nej | **ja** |
| `line.designation`, `line.transport_mode` | 407/407 (100%) | nej | **ja** |
| `stop_area.id` / `.name` / `.type` | 407/407 (100%) | nej | **ja** — geokodbart |
| `stop_point.id` / `.name` | 407/407 (100%) | nej | ja |
| `stop_point.designation` (läge) | 397/407 (98%) | nej | ja — "läge C" |
| `deviations[]` med `consequence` | 18/407 (4%) — CANCELLED 12, INFORMATION 6 | nej | ja |
| `journey.prediction_state` | 250/407 (61%) | nej | marginellt |
| `via` | 28/407 (7%) | nej | marginellt |
| `stop_deviations` | 0 i stickprovet | nej | inte verifierat |

**Detta är den enda källa som kan svara "när går nästa" för Stockholm.**
Fälla: `scheduled`/`expected` saknar tidszonssuffix
(`"2026-09-08T10:13:00"`) medan `publish.from` i deviations-API:t **har**
det (`"…+02:00"`). Två endpoints i samma API, olika konvention. Naiva
strängar måste lokaliseras till Europe/Stockholm innan de jämförs, annars
blir felet 2 timmar på sommaren och 1 på vintern.

**Serverside-filter fungerar** (verifierat live): `?transport_mode=METRO`
→ 9 poster, `?line=40` → 4, `?future=true` → 173 (mot 156 utan). Vi hämtar
idag alltid hela listan och filtrerar i Python.

---

## 5. Västtrafik — traffic-situations (Störning v1)

Adapter: `core/sources/vasttrafik.py`. Stickprov: 76 situationer, varav
**6 agerbara**. Plus 11 182 hållplatsområden.

| Fält | Ifyllnadsgrad (mätt) | Använder vi? | Värt att använda? |
|---|---|---|---|
| `situationNumber` | 76/76 (100%) | ja | ja |
| `title` | 76/76 (100%) | ja | **ja, mer än idag** — se nedan |
| `description` | 74/76 (97%) | ja | ja |
| `startTime` / `endTime` | 76/76 (100%) | ja | ja — **äkta störningsfönster**, inte publiceringsfönster |
| `creationTime` | 76/76 (100%) | nej | marginellt |
| `severity` | 76/76 — `slight` 64, `normal` 12 | ja (bärs vidare) | ja, men `high`/`veryHigh` sågs aldrig i stickprovet |
| `affectedLines[].designation` | 70/76 (92%) | ja | ja |
| `affectedLines[].defaultTransportModeCode` | 70/76 (92%) | ja (`mode_hint`) | ja |
| `affectedLines[].directions[].name` | **70/76 (92%)** | **nej** (riktning läses bara ur `affectedJourneys`, 7%) | **ja** — "Munkedal - Uddevalla" |
| `affectedLines[].municipalities[].municipalityName` | 70/76 (92%) | nej | ja — kommunnamn utan regex |
| `affectedLines[].affectedStopPointGids` | **64/76 (84%)** | **nej** | **ja** — geokodar linjelarm som saknar `affectedStopPoints` |
| `affectedLines[].backgroundColor` / `textColor` | 70/76 (92%) | nej | ja för UI-paritet med Västtrafiks egen färgsättning |
| `affectedStopPoints[].stopAreaGid` | 69/76 (91%) | ja (geokodning) | ja |
| `affectedStopPoints[].stopAreaName` / `.name` | 69/76 (91%) | ja | ja |
| `affectedStopPoints[].municipalityName` | 69/76 (91%) | ja (till `areas`) | ja |
| `affectedJourneys[]` | **5/76 (7%)** | ja | marginellt |
| `affectedJourneys[].departureDateTime` | **4/76 (5%)** | ja (`journey_departure_at`) | ja när den finns — men se fällan |

**StopAreas-registret:** 11 182 av 11 182 (100%) har
`geometry.eastingCoordinate`/`northingCoordinate` när `includeGeometry=true`
skickas. Bekräftar adapterns kommentar.

Med dagens adapter fick de 6 agerbara: **4/6 koordinat**, 4/6 riktning,
6/6 `route_label`.

### Titlarna bär redan svaret

Västtrafiks titlar är maskingenererade och innehåller ofta tid, riktning
och ersättning:

```
Västtågen 3334 klockan 13:33 är inställt från Herrljunga station till …
Linje 200 klockan 10:12 är inställd från Borså resecentrum till Östra …
Västtågen 3349 klockan 11:22 är inställt och ersätts med buss linje 35…
Linje 35A klockan 07:15 är försenad från Laxå station mot Alingsås.
```

Mätt: `"klockan HH:MM"` finns i **4 av 6 agerbara** (5 av 76 totalt — de
mallade titlarna är just de akuta). `"ersätts med"`/`"ersättningsbuss"`/
`"ersättningstrafik"` finns i **11 av 76** titlar/beskrivningar.

### Fällor

- **`affectedJourneys[].departureDateTime` kan vara veckogammal.** Två av
  de fyra i stickprovet pekade på `2026-08-18` i en situation som var aktiv
  i september. Använd den aldrig som "nästa avgång" utan att kontrollera att
  den ligger nära `startTime`.
- **`is_actionable()` slår hårt:** 6 av 76 (8%) passerar. 44 av 76 har
  `endTime − startTime > 30 dygn` och 10 har `startTime` i framtiden
  (planerat nattarbete), så filtret gör rätt sak — men Göteborg producerar
  bara en handfull tips per hämtning.
- **`affectedStopPoints[].gid` är ett hållplats*punkts*-gid, inte ett
  områdes-gid.** Adapterns fallback `stop_area_index[gid]` träffar därför
  inte; det är `stopAreaGid` som gör jobbet.
- Koordinaterna i registret är **SWEREF99TM (EPSG:3006), meter**, inte
  grader — redan hanterat i adaptern, men värt att upprepa: rådata är
  `POINT (319346 6400119)`.

---

## 6. SMHI — punktprognos (snow1g v1)

`https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/...`
Adapter: `core/sources/smhi.py`. Stickprov: en punkt (Malmö), 83 tidssteg
(nu → +10 dygn, timupplösning första dygnen).

Verifierat: **`pmp3g` version 2 ger 404** (avvecklad 2026-03-31).
`docs/data-sources.md` anger fortfarande pmp3g-URL:en — den är död.
Koden är redan bytt; dokumentet har inte hunnit ikapp.

| Parameter | Ifyllnadsgrad | Använder vi? | Värt att använda? |
|---|---|---|---|
| `air_temperature` | 83/83 (100%) | ja | ja |
| `wind_speed` | 83/83 | ja | ja |
| `wind_speed_of_gust` | 83/83 | ja | ja |
| `precipitation_amount_mean` | 83/83 | ja | ja |
| `probability_of_precipitation` | 83/83 | ja | ja |
| `thunderstorm_probability` | 83/83 | ja | ja |
| `probability_of_frozen_precipitation` | 83/83 | ja | ja |
| `symbol_code` | 83/83 | hämtas, används ej | ja för ikon i appen |
| `visibility_in_air` | **83/83 (100%)** | **nej** | **ja** — dimma/snöyra. Låg sikt är en klassisk taxisignal |
| `precipitation_frozen_part` | 83/83 | nej | ja — snö vs regn, mer direkt än `probability_of_frozen_precipitation` |
| `predominant_precipitation_type_at_surface` | 83/83 | nej | ja |
| `relative_humidity` | 83/83 | nej | marginellt |
| `wind_from_direction` | 83/83 | nej | nej |
| `cloud_area_fraction` + low/medium/high | 83/83 | nej | nej |
| `air_pressure_at_mean_sea_level` | 83/83 | nej | nej |
| `precipitation_amount_min` / `_max` / `_median` / `_mean_deterministic` | 83/83 | nej | ja — `_max` ger ett värstafall att larma på |
| `cloud_base_altitude` / `cloud_top_altitude` | 83/83 | nej | nej |

### Fällor och outnyttjat

- **Vi läser bara `timeSeries[0]`.** 82 tidssteg framåt kastas. Det som
  saknas är "kommer det ösregna när tåget skulle ha kommit fram" — dvs.
  vädret vid `next_departure_at`, inte vädret nu.
- **Tider är UTC med `Z`.** `referenceTime` var `07:45Z` medan första
  tidssteget var `08:00Z` — `timeSeries[0]` är alltså den *påbörjade*
  timmen, inte exakt "nu". Vid kvartsprecision kan den vara upp till en
  timme gammal.
- Toppnivåfältet heter `createdTime` i snow1g (inte `approvedTime` som i
  pmp3g). Vi läser ingetdera.
- Alla parametrar var 100% ifyllda över hela horisonten i stickprovet —
  inga hål att designa runt.
- `precipitation_amount_*` är mm/h och gäller ett **intervall** fram till
  `time`; övriga parametrar är momentanvärden vid `time`. Blandar man dem
  rakt av jämför man ett medelvärde bakåt med ett ögonblicksvärde.
  `visibility_in_air` är i **km**, inte meter.

---

## 7. Nästa avgång och ersättningstrafik — vad varje källa faktiskt kan svara på

Detta är avsnittet för det huvudsessionen bygger. Sammanfattningen först:

| Källa | "När går nästa?" | "Finns ersättningstrafik?" | "När är störningen över?" |
|---|---|---|---|
| **Trafikverket rail** | **Ja, härlett** — hela tidtabellen i 8h-fönstret finns, `_next_departure()` räknar gapet | **Delvis** — `Deviation.Code ANA007` (34/82) fungerar; `ReplacementTraffic` joinar 0/82 idag | Nej — vi hittar på `departure_at + 1h` |
| **SL** | **Ja, men inte inkopplat** — `/sites/{id}/departures` ger `scheduled`/`expected`/`state=CANCELLED` | **Bara i fritext** — 1 av 25 agerbara nämner ersättning | Nej — `publish.upto` är publiceringsfönster (median 53 dygn) |
| **Västtrafik** | **Nästan** — `affectedJourneys.departureDateTime` (5%) eller ur titeln "klockan HH:MM" (4/6 agerbara) | **Ur titeln** — "ersätts med buss linje 35", 11/76 | **Ja** — `endTime` är störningens eget slut, inte publiceringens |
| **Trafiklab GTFS-RT** | **Nej** — 0/538 nämner nästa avgång; `trip.start_time` 0% | **Nästan aldrig** — 5/538 texter | Nej — `active_period.end` median 45 dygn |
| **Trafikverket väg** | Ej tillämpligt | Ej tillämpligt | **Ja, men grovt** — `EndTime` 98% men median ≈349 dygn |
| **SMHI** | Ej tillämpligt | Ej tillämpligt | Ej tillämpligt |

### Detaljer per fråga

**"När går nästa avgång?"**

Bara järnvägen svarar strukturerat idag, och den gör det genom att hämta
*alla* avgångar i fönstret, inte bara de störda. Mätt på dagens 18 byggda
larm: 13 hade `next_departure_minutes` (median 25 min, spann 1–84), 3 var
markerade som sista avgången.

Stockholm kan få samma sak utan ny nyckel: `/v1/sites/{siteId}/departures`
returnerar `scheduled` + `expected` + `state` på 100% av 407 avgångar, med
`CANCELLED` som eget tillstånd (12/407). Kombinationen "SL-deviation säger
inställd avgång kl 6:45 från Varvsgatan" + "departures-endpointen säger när
nästa buss på linje 4 går från samma hållplats" ger exakt det järnvägen
redan har.

Göteborg kan inte svara strukturerat: Västtrafiks Störning-API har ingen
tidtabell, och Trafiklab har ingen realtid för `vt`. Det bästa som går är
att läsa avgångstiden ur titeln ("klockan 11:22") och redovisa den som
*den inställda* avgången, inte som nästa.

Trafiklab kan inte svara alls. `trip.start_time`/`start_date` är 0% ifyllda
och stop_id-rymden joinar inte mot vår GTFS-statik.

**"Finns ersättningstrafik?"**

Rangordnat efter hur ofta det faktiskt går att svara:

1. **Trafikverket `Deviation.Code`** — `ANA007 "Buss ersätter"` på 34 av 82
   inställda (41%). Koden är stabilare än textmatchning. Utöka gärna med
   `ANA006 "Buss"` (69 poster — men de är själva ersättningsbussarna, inte
   inställda tåg) och `ANA274` (linjenummer för ersättningsbuss: "Buss 22A",
   "Buss 38N").
2. **`OtherInformation`** — 448/4000 (11%), innehåller "Buss ers. Floda –
   Alingsås." och "Byte till buss vid Floda." Läses inte alls idag.
3. **Västtrafiks titel/beskrivning** — 11 av 76 (14%).
4. **`ReplacementTraffic`** — teoretiskt bäst (fordonsläge, GPS-hållplats,
   `PlannedDepartureTime`, `StopDescription`), praktiskt **0 träffar idag**.
5. **Trafiklab** — 5 av 538 (1%). Räkna inte med det.
6. **SL** — 1 av 25 agerbara. Räkna inte med det.

**"När är störningen över?"**

Bara Västtrafik har ett fält som ärligt betyder detta (`endTime`, 100%).
Trafikverket väg har `EndTime` (98%) men som planeringsfönster.
Trafikverkets `OperativeEvent.TrafficImpact[].EndDateTime` finns på 100% av
`TrafficImpact`-posterna men 14 av 68 hade redan passerat medan
`EventState` fortfarande stod på 1.

SL och Trafiklab har **inget** sådant fält — deras "sluttider" är
publiceringsfönster med median 53 respektive 45 dygn. Att visa dem som
"pågår till" vore direkt vilseledande.

---

## 8. Konkreta förslag

Sorterade efter nytta per arbetsinsats. Inget av detta är implementerat —
det är förslag, inte ändringar.

**1. Sluta använda `PublicationTime` som starttid för väghändelser.**
`core/sources/trafikverket_road.py`, `normalize_situation()`:
byt `"active_from": _parse_time(situation.get("PublicationTime"))` mot
`Deviation.StartTime` (100% ifylld). Ger: väghändelser slutar se
nyskapade ut varje gång Trafikverket republicerar posten. Mätt medianfel
idag: 862 timmar.

**2. Läs `Deviation.EndTime` för väg, med tak.**
Samma fil + `core/management/commands/poll_road.py`. `EndTime` finns på
98% men har median ≈349 dygn, så: `active_to = min(EndTime, now + ROAD_TTL)`.
Visa "pågår till …" för föraren bara när `EndTime − now < 24h`. Ger: en
avstängning som faktiskt slutar kl 16 kan sluta visas kl 16 i stället för
att hänga kvar i 4h-fönstret, och en ettårig vägarbetsplats slutar hävda
ett falskt slut.

**3. Låt `level_for_deviation()` läsa `MessageCode`.**
`core/sources/trafikverket_road.py`. Idag läses bara `MessageType`
(3 möjliga värden) och `IconId` (engelskt). Mätt konsekvens: 25 av 33
avvikelser med `MessageCode = "Vägen avstängd"` klassas `low`. Lägg till
`MessageCode` i strängen som matchas, och lägg till `IconId == "roadClosed"`
som egen `high`-regel. Ger: avstängda vägar blir `high` i stället för `low`.

**4. Bygg SL:s "nästa avgång" på `/v1/sites/{siteId}/departures`.**
Ny funktion i `core/sources/sl.py` + anrop från
`core/management/commands/poll_sl.py`. `Opportunity` har redan kolumnerna
(`next_departure_minutes`, `next_departure_at`, `is_last_departure`).
Ingen nyckel, ingen kvot; hämta bara för de site-id som faktiskt förekommer
i agerbara deviations. **Kritiskt:** `scheduled`/`expected` saknar
tidszonssuffix — lokalisera till Europe/Stockholm innan jämförelse.
Ger: Stockholm får samma signal som järnvägen redan har, för landets största
marknad.

**5. Extrahera hållplats + tid ur SL:s `details`-text.**
`core/sources/sl.py`, `normalize_deviation()`. Mönstret
`(från|mellan) <namn> [kl] HH:MM` fanns i 21 av 25 agerbara, och 19 av 21
namn slog upp direkt mot `sl_sites`. Ger: koordinat för
Stockholmslarm som idag har `lat/lon = null`, plus den inställda avgångens
klockslag. Detta är inte en påhittad koordinat — namnet står i SL:s egen
text, vilket är precis den invändning kommentaren i adaptern reser mot att
gissa från linjens första hållplats.

**6. Matcha ersättningstrafik på `Deviation.Code`, inte på ord.**
`core/sources/trafikverket_rail.py`, `_replacement()`. Använd
`ANA007` ("Buss ersätter") som primär signal och behåll textmatchningen som
reserv. Lägg till `OtherInformation[].Description` (11% ifylld) i sökningen —
den bär "Buss ers. Floda – Alingsås." Ger: robusthet mot att Trafikverket
formulerar om texten, plus några procent extra träffar.

**7. Beskriv `ReplacementTraffic` som det den är.**
`core/sources/trafikverket_rail.py`. Tre konkreta punkter: (a) `Description`
finns inte i svaret (0/1000) — ta bort läsningen eller notera att den alltid
är tom; (b) `Status = "running"` kan avse ett tåg från juni — filtrera på
`ScheduledDepartureDate` mot dagens datum i stället för/utöver `Status`;
(c) uppdatera kommentaren som kallar den "den starkaste signalen" — den gav
0 träffar på 82 inställda avgångar 2026-09-08. Ger: koden slutar ljuga om
var signalen kommer ifrån.

**8. Visa `TrackAtLocation` och `ProductInformation` för föraren.**
`core/sources/trafikverket_rail.py`, `_normalize()`. Båda 100% ifyllda,
även på inställda avgångar. "Pågatåg 1612 från Helsingborg C, spår 3" är
mer användbart än "Skånetrafiken 1612". `ProductInformation` fixar också
fallet där `InformationOwner` ger fel varumärke (Kalmar C-avgången som
tillskrevs "Jönköpings Länstrafik"). Ger: konkretare kort, rätt varumärke.

**9. Flagga bussavgångar i järnvägsflödet.**
`core/sources/trafikverket_rail.py`. 69 av 4 000 avgångar har
`TypeOfTraffic = "Buss"` (identiskt med `Deviation.Code = ANA006`).
De räknas idag in i `station_departures_in_window` och kan bli "nästa
avgång". Två saker följer: skriv "nästa ersättningsbuss går om X" i stället
för "nästa avgång", och använd dem som en andra ersättningsindikator
(16 av 82 inställda hade en bussavgång vid samma station inom en timme).

**10. Använd `route_id`-länskoden i Trafiklab i stället för ortnamnsregex.**
`core/sources/trafiklab.py`, `extract_areas()`. `route_id` är
`9011` + SCB-länskod + linje, och stämde med operatören i 100% av
stickprovet (186 av 538 larm har minst ett `route_id`). Ger: strukturerad
länstillhörighet för en tredjedel av larmen utan att underhålla en
ortnamnslista — särskilt för de nordliga operatörer regexen inte täcker.
Behåll regexen som reserv.

**11. Läs `affectedLines[].directions[].name` i Västtrafik.**
`core/sources/vasttrafik.py`, `normalize_situation()`. Riktning hämtas idag
bara ur `affectedJourneys` (7% ifylld); `affectedLines[].directions` finns
på 92%. Ger: "mot Uddevalla" på nästan alla Göteborgstips i stället för
på en handfull.

**12. Geokoda Västtrafik-linjelarm via `affectedLines[].affectedStopPointGids`.**
Samma fil. 84% ifylld, mot 91% för `affectedStopPoints`. Ger: en reserv
för de linjelarm som saknar `affectedStopPoints` helt (2 av 6 agerbara i
stickprovet saknade koordinat).

**13. Filtrera bort SL:s hisslarm på `categories`.**
`core/sources/sl.py`. 10 av 159 är `FACILITY/LIFT`. De faller idag bort
genom åldersfiltret, inte genom att någon förstått vad de är — ett färskt
hissfel skulle passera. Ger: en explicit regel i stället för tur.

**14. Ta bort de döda läsningarna.**
Tre stycken, alla verifierat 0% i stickprovet:
`core/sources/sl.py` → `variant.get("weblink")` (0/159, fältet finns inte);
`core/sources/trafiklab.py` → `entity.agency_id` (0/538) och `alert.url`
(0/538); `core/sources/trafikverket_rail.py` → `record.get("Description")`
i `_replacement()` (0/1000). Ger: koden slutar antyda att data finns.
Kommentera hellre än att radera om ni tror att fälten fylls i framtiden.

**15. Använd `visibility_in_air` som vädersignal.**
`core/sources/smhi.py`, `_PARAMS` + en ny tröskel. 100% ifylld, i **km**.
Dimma och snöyra driver taxiefterfrågan och fångas inte av dagens
nederbörd/vind/åska/halka-trösklar. Ger: en signal ingen av de fyra
befintliga täcker. Rör inte de befintliga trösklarna — de är avsiktligt
identiska med Nodes.

**16. Hämta väder för rätt tidpunkt, inte bara `timeSeries[0]`.**
Samma fil. Prognosen har 83 tidssteg (10 dygn). När ett tips har
`next_departure_at` eller `active_to` är vädret *då* mer relevant än vädret
nu. Ger: "det börjar regna 16:30, tåget går inte förrän 17:10" blir möjligt
att säga.

**17. Kandidat, större arbete: koppla in `OperativeEvent` för orsakstext.**
Ny modul. `EventType.Description` är 100% ifylld och ger den enda riktiga
*varför*-texten i hela flödet ("Banarbete/transport", "Kontaktledning",
"Polis/sjukdom"), och `TrafficImpact[].PublicMessage` ger färdig svensk
publiktext på 28 av 65 händelser. `EventSection[].FromLocation.Signature`
joinar mot stationsregistret vi redan har. **Två varningar:** (a)
`Geometry.WGS84` är **lat-först** här, tvärtemot `TrainStation` — återanvänd
inte `parse_point()` utan att vända på det; (b) `EventState = 1` betyder
inte "pågår nu" (44/65 startade i det förflutna, en 367 dygn sedan) —
använd `TrafficImpact[].EndDateTime`, och kom ihåg att 14 av 68 av dem
redan passerat.

**18. Verifiera vad `Suspended` betyder innan ni litar på flödet.**
`Deviation.Suspended = true` på 763 av 1 177 väghändelser (65%). Om det
betyder "tillfälligt vilande" visar vi idag hundratals pausade vägarbeten
som pågående. Trafikverkets dokumentationsportal går inte att läsa
maskinellt (SPA), så detta kunde **inte verifieras** här. Kolla mot en känd
vägarbetsplats en helg, eller fråga Trafikverkets support. Det här är den
enskilt största outnyttjade filtreringsmöjligheten i vägflödet.

**19. Använd SL:s serverside-filter.**
`core/sources/sl.py`. Verifierat live: `?transport_mode=`, `?line=`,
`?future=true` fungerar. Vi hämtar idag hela listan (202 KB) varje cykel
och filtrerar i Python. Ger: mindre trafik mot ett API vars egen
dokumentation ber om högst ett anrop per minut.

---

## 9. Sammanfattade fällor (checklista)

| Fälla | Var | Kontrollvärde |
|---|---|---|
| WGS84 lon-först | `TrainStation`, `Situation` (väg), Trafiklab-inget | Göteborg C = `POINT (11.97 57.71)` |
| WGS84 **lat-först** | `OperativeEvent` | Helsingborg = `POINT (55.96 12.78)` |
| SWEREF99TM i meter | Västtrafik StopAreas | Brunnsparken = `POINT (319346 6400119)` |
| Publiceringsfönster ≠ störningslängd | SL `publish`, Trafiklab `active_period`, Trafikverket väg `PublicationTime` | SL median 53 dygn; Trafiklab median 45 dygn |
| Naiv tid utan tidszon | SL `/departures` `scheduled`/`expected` | `"2026-09-08T10:13:00"` mot deviations `"…+02:00"` |
| UTC med `Z` | SMHI `time`, Trafikverket `ModifiedTime` | `"2026-09-08T08:00:00Z"` |
| Fält som alltid är tomt | GTFS `effect` (UNKNOWN), `severity_level`, `agency_id`, `route_type`, `url`; SL `weblink`, `urgency_level` (konstant 1); `ReplacementTraffic.Description`; `RoadDegreeOfImpact`; `RailRoadTimeForServiceResumption` | alla 0% i stickprovet |
| Status som inte städas | `ReplacementTraffic.Status`, `OperativeEvent.EventState` | "running" för ett tåg 2026-06-17 |
| Enhet: km, inte meter | SMHI `visibility_in_air` | 8.7 |
| Enhet: mm/h över intervall, inte momentanvärde | SMHI `precipitation_amount_*` | jämför inte rakt av med momentanparametrar |
| Två id-rymder i samma feed | Trafiklab `stop_id` (16 tecken vs 2–5 siffror) | 1 av 296 korta id matchar ett långt |
| Länskod finns strukturerat | Trafiklab `route_id[4:7]`, Trafikverket `CountyNo` | `9011012…` = Skåne |
