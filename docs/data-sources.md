# Data sources — endpoints, keys, quotas, and what combines with what

Cached research so ingestion work doesn't re-derive this every session (see
CLAUDE.md's token-efficiency rules). Everything here was verified against the
live APIs, not assumed from docs alone — where docs and observed behaviour
disagreed, the observed behaviour is noted.

Last verified: 2026-09-05.

---

## Trafiklab (public transport)

All feeds are served from `https://opendata.samtrafiken.se/`.

**Required header:** every endpoint returns `406` with
`{"errorMessage":"This API must be called with the HTTP-header 'Accept-Encoding' set to 'gzip' or 'deflate'"}`
unless `Accept-Encoding: gzip` is sent. `fetch()` in Node does this by
default; `curl` does not (use `--compressed`).

### Feed families and combinability

This is the part that matters most, and the part that's easy to get wrong.
Trafiklab runs **two separate data families with different id spaces**
([official doc](https://www.trafiklab.se/docs/using-trafiklab-data/combining-data/)):

| Family | Static | Realtime | Combinable? |
|---|---|---|---|
| **Sweden / Sverige** | `gtfs-sweden/sweden.zip` | `gtfs-rt-sweden/{op}/ServiceAlertsSweden.pb` | with each other, and with ResRobot APIs |
| **Regional** | `gtfs/{op}/{op}.zip` | `gtfs-rt/{op}/ServiceAlerts.pb` | with each other only |

**Cross-family joins do not work.** Trafiklab states plainly: *"GTFS Sverige 2
and GTFS Regional are not backed by the same data."* An aggregated feed
("GTFS Sverige 3") is on their roadmap but not shipped.

Regional realtime operator codes: `sl, ul, otraf, klt, skane, varm, dt, xt,
vastmanland, krono` (plus `jlt, orebro` for VehiclePositions only).
Regional realtime endpoints: `ServiceAlerts.pb`, `TripUpdates.pb`,
`VehiclePositions.pb`. Updates ≥15s (VehiclePositions ≥3s).

### What this project currently uses — and the resulting mismatch

- Realtime alerts: `gtfs-rt-sweden/skane/ServiceAlertsSweden.pb` (**Sweden family**)
- Static schedule: `gtfs/skane/skane.zip` (**Regional family**)

These are from different families, so **their `stop_id`s do not join**.
Verified against a real ingest:

- Sweden-family alert stop_ids: Skånetrafiken short numbers, e.g. `26515`
- Regional static stop_ids: NOPTIS format, e.g. `9022012093032001`
- `stop_code` (GTFS's normal bridge field for exactly this) is **empty for
  every stop** in the Regional feed
- Trafiklab support confirmed no public mapping table exists
  ("Stoppställenummer i GTFS Regional och GTFS Sverige 2")

**This is why `nextDeparture()` in `worker/src/gtfsStatic.js` is written,
tested, and not called** — the join silently matches nothing.

### The fix (blocked on access, not feasibility)

Switch the alert source to the **Regional** realtime feed
(`gtfs-rt/skane/ServiceAlerts.pb`) so both sides come from the same family.
Then stop_id joins work by construction and `nextDeparture()` can be wired
into scoring — which is what unlocks "is this the last train tonight?"
severity weighting.

Blocker: `TRAFIKLAB_API_KEY` returns **403 `{"errorMessage":"Key does not
have access to file"}`** for `/gtfs-rt/skane/*`. Each Trafiklab dataset needs
its own key/subscription; the current key is scoped to GTFS Sweden Realtime
only.

Access matrix for the current `TRAFIKLAB_API_KEY` (verified 2026-09-05):

| Endpoint | Status |
|---|---|
| `gtfs-rt-sweden/skane/ServiceAlertsSweden.pb` | **200** |
| `gtfs-rt/skane/ServiceAlerts.pb` | 403 |
| `gtfs-rt/skane/TripUpdates.pb` | 403 |
| `gtfs/skane/skane.zip` | 403 (uses separate `GTFS_STATIC_API_KEY`) |
| `gtfs-sweden/sweden.zip` | 403 |

**Action needed:** register a GTFS Regional Realtime key at trafiklab.se and
set it as its own env var. Do not assume one key covers multiple datasets.

### What the ServiceAlerts feed actually contains (measured, 123 live alerts)

Field population, decoded from a real Skåne response:

| Alert field | Populated | Useful? |
|---|---|---|
| `headerText`, `descriptionText` | 123/123 | **Yes** — the only real signal; `scoring.js` parses these |
| `activePeriod` | 123/123 | Yes — but `end` is the alert's *publishing validity*, not the disruption's duration (every cancellation in a batch shares one end time) |
| `cause` | 123/123 | Marginal — see below |
| `effect` | 123/123 but **always `UNKNOWN_EFFECT`** | **No** — Skånetrafiken never sets it |
| `url` | 0/123 | No |
| `informedEntity.stopId` | 256 refs | Wrong id space (see above) |
| `informedEntity.routeId` | 59 refs | Same |
| `informedEntity.trip.tripId` | 62 refs | Same |

**`cause` is not worth adding to scoring.** It looks promising (CONSTRUCTION 81,
OTHER_CAUSE 35, TECHNICAL_PROBLEM 4, MAINTENANCE 3) but cross-tabbing it
against our text-derived tiers shows the text already captures it: all 81
CONSTRUCTION and all 3 MAINTENANCE alerts are already scored `ignore`. And
`cause` is *not* a reliable planned/unplanned proxy — many `OTHER_CAUSE`
entries are long-running planned closures (e.g. "Stängd hållplats",
Aug 17 → Dec 11). Verified 2026-09-05; don't re-litigate without new evidence.

### TripUpdates / VehiclePositions on the Sweden feed — accessible but useless here

The current key **can** fetch these (200 OK, 377 KB / 82 KB):

```
gtfs-rt-sweden/skane/TripUpdatesSweden.pb       200
gtfs-rt-sweden/skane/VehiclePositionsSweden.pb  200
```

TripUpdates carries genuinely valuable data — 395 trips, 6778 stop-time
updates, 348 of them >5 min late, with real `delay` seconds per stop. That is
exactly the "is this train actually late / is this the last one" signal the
scoring engine lacks.

**But the `{operator}` path segment is ignored on this feed family.** Decoding
the stopIds returned by `/gtfs-rt-sweden/skane/TripUpdates…` gives **100%
Östergötland** stops (NOPTIS county digits `05`), zero Skåne. Our static feed
is county `12`. Sampled stopIds had **0/10 overlap** with our 10,703 ingested
Skåne stops.

So these feeds are accessible but describe the wrong region, and their ids
can't join our schedule. Same root cause as the ServiceAlerts mismatch: the
Sweden family is a different dataset, not a regional filter.

**Re-verified independently 2026-09-05 (second pass), and this section is
correct — do not "fix" it.** A later investigation measured a 50/148 stopId
overlap between ServiceAlerts and TripUpdates on the Sweden family and read
that as evidence the ids join. They do join *each other* — both feeds are the
same dataset — but that says nothing about which region they describe.
Decoding county digits settles it: `skane`, `otraf` and `sl` operator paths
all return **county 05 (Östergötland)** and nothing else, while the ingested
static feed is county 12. The DB confirms the join failure directly:

```sql
select count(*) from gtfs_stops
where stop_id in ('9022050028160001','9022050026651001','9022050026650001');
-- 0, against 10,703 ingested Skåne stops (prefixes 90220120 / 90210120)
```

Note also that the static feed is **not** stale: `gtfs_feed_versions` shows a
successful daily ingest (990,876 stop_times). A 403 when testing by hand means
the *local* `TRAFIKLAB_API_KEY` lacks static access — production uses a
separate `GTFS_STATIC_API_KEY`, which works. Don't infer "access lapsed" from
a local 403.

**Everything still points to one action:** get a GTFS **Regional** Realtime
key. That unlocks correctly-scoped ServiceAlerts *and* TripUpdates whose ids
join our existing Regional static data.

### SL (Stockholm) — open, no key, and already integrated

SL publishes its own realtime data with **no API key and no quota tier**:

```
deviations.integration.sl.se/v1/messages          200   158 deviations
transport.integration.sl.se/v1/sites?expand=true  200   6512 sites / 7214 stop areas
transport.integration.sl.se/v1/sites/{id}/departures  200
```

Two measured facts that shape `sl.js`:

1. **`publish` is a publication window, not a disruption duration.** 102 of
   158 run longer than 30 days; one live example was published 2024-01-03 and
   runs to 2026-12-31. Only ~19 of 152 are recent *and* bounded. `isActionable()`
   filters on that, because showing a two-year-old roadworks notice as a live
   opportunity is exactly the false tip that destroys driver trust.
2. **Stop-area ids and site ids are different id spaces** (only 14/104 collide,
   coincidentally). `?expand=true` carries each site's `stop_areas[]`, which
   bridges them for **104/104** referenced ids — hence `sl_sites` is keyed by
   stop_area, not site.

Known limit: the *actionable* deviations reference **lines, not stop areas**
(19/19 in a live sample named zero stop areas), so most Stockholm alerts carry
`lat/lon = null`. SL's open API exposes no line → stops mapping (`/lines`
returns no stop list; `/stop-points` carries no line reference). Inventing a
coordinate from a line would put drivers on a specific wrong corner of
Stockholm with false precision. GTFS Sweden 3 static's `stop_times` would
close this — one more reason it is the top subscription request.

### Quotas

Static feeds are tightly limited — Bronze **50 calls/month**, Silver 250,
Gold 2500. Realtime is far more generous but still quota'd (429 on exceed).
This is why `gtfsStatic.js` refreshes at most daily and guards startup
against re-fetching if a version <20h old exists.

### Efficiency notes worth adopting

- All endpoints support **HEAD** and **conditional GET**
  (`If-Modified-Since` / `If-None-Match`). The daily static refresh could
  HEAD first and skip the multi-MB download when unchanged — cheap win
  against the tiny static quota, not yet implemented.
- Route-planning/isochrone work belongs on local GTFS, never per-request API
  calls (Trafiklab's own guidance: 50k stops ⇒ 25M calls).

---

## Going national (MARKET_SCOPE=national)

Measured 2026-09-05. Short answer: **no new API keys are needed.** Both
existing keys already cover the whole country; the limits were in our code.

### What changes

| Env var | Skåne (default) | National |
|---|---|---|
| `MARKET_SCOPE` | unset / `skane` | `national` |
| `TRAFIKLAB_OPERATORS` | `skane` | `skane,sl,ul,otraf,klt,varm,dt,xt,vastmanland,krono,jlt,orebro` |
| `TRAFIKVERKET_COUNTIES` | `skane` | `all` |

`MARKET_SCOPE=national` disables the ingest-side region geofence entirely.
That is correct rather than lazy: once the market is the country, "is this
in region X" is meaningless — every alert is in *someone's* market — and
relevance becomes a per-driver distance question the client already answers
(`worth_it_score` folds in `distance_km`, plus the "Nära mig" filter).

### Measured national volume

- Transit: **464 alerts** across 12 operators (vs 121 Skåne-only)
- Road: **3,417 alerts** across 21 counties (vs 176 Skåne-only)
- After scoring: 2,242 non-ignore, of which **7 push-worthy**

The push gate holds at national scale without changes — road tiers are
score-capped and `vehicle_delayed` noise is filtered, so 3,881 raw alerts
still yield only 7 notifications.

### Coverage gaps (not fixable with keys)

`ServiceAlerts` **is** correctly region-scoped per operator (verified: the
`skane` feed returns 115 Skåne mentions, 0 Stockholm/Kalmar). But these
operator codes 404 on this feed family and simply aren't available:

```
vt (Västtrafik/Göteborg), sormland, ostgota, halland,
vasterbotten, norrbotten, jamtland, vasternorrland
```

**Västtrafik is the significant one** — Gothenburg is Sweden's second city
(~1.7M in the region) and has no transit alerts here. Road data via
Trafikverket covers those counties fine; only transit is missing. Getting
Västtrafik likely needs GTFS Regional Realtime (see above) or a direct
Västtrafik API — worth checking before promising national transit coverage.

**`blekinge` and `gotland` are NOT in the above 404 list — verified live
2026-09-06 on the Sweden-family endpoint (`gtfs-rt-sweden/{op}/
ServiceAlertsSweden.pb`): both return `200 OK`.** They were simply omitted
from the operator list that had been in use; added. Both currently return a
near-empty feed (~15 bytes, i.e. a header with zero entities) — that's
real-time sparseness at the moment of testing, not evidence the feed is
broken. Re-test if a Blekinge/Gotland driver reports the map never
populating there even during a known disruption.

### Correction 2026-09-08: Västernorrland IS available — as `dintur`

Re-probed all 25 candidate operator codes with the new GTFS Sweden 3
Realtime (Gold) key. `vasternorrland` 404s, as previously recorded — but the
operator code for that county is **`dintur`**, which returns `200 OK` with
14 alerts. It had never been tried: the earlier probe used the county name,
not the operator's own name, and the 404 was read as "the county isn't
covered" rather than "that string isn't the code". Added to
`TRAFIKLAB_OPERATORS`.

Fifteen codes verified working on `gtfs-rt-sweden/{op}/ServiceAlertsSweden.pb`:

```
sl 201   skane 159   varm 45   dt 21   otraf 19   ul 19   vastmanland 17
jlt 16   dintur 14   orebro 13   klt 11   xt 9   krono 3   gotland 1
blekinge 0 (200 OK, tom feed)
```

Still 404, i.e. genuinely not in the product: `halland, sormland, ostgota,
vt, vasterbotten, norrbotten, jamtland, vasternorrland, sj`. Västra
Götaland is covered anyway through its own Västtrafik adapter.

### Halland/far-north confirmed against the official spec, not just live probing (2026-09-06)

Cross-checked the 404 list above against Trafiklab's actual OpenAPI spec
([`gtfsSwedenRealtime.yaml`](https://github.com/trafiklab/openApi-docs/blob/master/gtfsSwedenRealtime.yaml)),
not just cached notes:

- **The documented operator enum for ServiceAlerts/TripUpdates is exactly**
  `dt, jlt, krono, orebro, skane, sl, ul, vastmanland, varm, xt, otraf`
  (11 operators). VehiclePositions has a *different* enum:
  `ul, otraf, klt, skane, varm, dt, xt, vastmanland`.
- **The spec's enum is not authoritative in practice** — `klt` (Kalmar) is
  absent from the ServiceAlerts enum yet returns real, working data (11
  opportunities in one poll); `blekinge`/`gotland` are absent entirely yet
  return `200`. Same conclusion this file already reaches elsewhere: measure
  against the live API, the docs undersell what actually works.
- **Halland, Västerbotten, Norrbotten, Jämtland are absent from the enum AND
  confirmed 404 live (re-tested 2026-09-08 with the new Gold key).** This is a
  genuine, structural gap in Trafiklab's realtime *ServiceAlerts* product
  specifically — not fixable by trying more operator codes, and not a gap
  in this project's polling logic.
- **GTFS Sweden 3's own product page claims broader *static* coverage**
  (Hallandstrafiken, Blekingetrafiken, Gotland, Din Tur/Västernorrland all
  listed as having schedule data; Västerbotten/Norrbotten/Jämtland "static
  only"). That's schedule data, not disruption alerts — it doesn't close
  this gap on its own.
- **A separate, newer product exists** — "Trafiklab Realtime APIs" (Stop
  Lookup / Timetables / Trips, launched 2025, built on GTFS Sweden 3),
  which does claim whole-of-Sweden coverage. It's a *timetable/departure*
  API, not a disruption-alerts API — using it here would mean inferring
  disruptions from scheduled-vs-actual departure deltas, the same
  technique `trafikverket_rail.py` already uses for rail. That is a real,
  buildable path to closing the Halland/north gap, but it is new
  engineering work (a new source module), not a config fix. Flagged as a
  candidate for a future phase, not attempted here.

### Trafiklab Realtime APIs — undersökt 2026-09-14 (för "nästa avgång", P1)

Läst ur Trafiklabs dokumentation. **Provat 2026-09-14 med `TRAFIKLAB_API_KEY`:** Realtime APIs svarar
HTTP 403 `error.key.invalid` ("Key … does not exist"), och GTFS Sweden 3 static svarar HTTP 403 på en
HEAD-förfrågan. Nyckeln gäller alltså bara GTFS Sweden Realtime; båda produkterna kräver egna nycklar.

- **Avgångar:** `https://realtime-api.trafiklab.se/v1/departures/{area id}[/{YYYY-MM-DDTHH:mm}]?key={key}`,
  samma form för `/arrivals/`. `area id` är rikshållplatsens id, **inte** hållplatslägets.
- **Hållplatser:** `/v1/stops/name/{sök}` och `/v1/stops/list`; `stop_groups[].id` är det id
  avgångarna tar, `stops[].id` barnen.
- **Fält per avgång:** `scheduled`, `realtime`, `delay` (s), `canceled`, `is_realtime`,
  `route.designation`/`direction`/`transport_mode`, `stop.id`, `trip.trip_id` + `start_date`
  (matchar GTFS Sweden 3), `agency`.
- **Kvot:** Bronze 25/min och 100 000/månad; Silver 150/min och 5 miljoner/månad.
- **Hela Sverige** enligt dokumentationen.

**Varför det inte är byggt:** Trafiklab-larmen (GTFS-RT ServiceAlerts) bär `route_id`
(t.ex. `9011001001300000`) och hållplatslägen (`9022050009836001`). Avgångssvaret har
ingen `route_id` -- bara `route.designation` och `trip_id`. En avgång kan därför bara
knytas till rätt linje via GTFS Sweden 3 static (`routes.txt`: `route_id` →
`route_short_name`; `stops.txt`: läge → `parent_station`). Utan linjen blir svaret
"något går härifrån", vilket SL-koden redan konstaterat är oanvändbart.

**Kräver beslut:** en nyckel till Trafiklab Realtime APIs, och tillgång till GTFS Sweden 3
static (Bronze tillåter 50 hämtningar/månad -- en om dygnet räcker). Budgeten måste
hållas i koden: 20 uppslag per 90-sekundersrunda vore ~580 000 anrop/månad, långt över
Bronze.

### Nya nycklar 2026-09-19: GTFS Sverige 3 statisk och GTFS Regional Realtime

Trafiklab har en nyckel per dataset. I `taxitips-backend/.env`:
- `TRAFIKLAB_API_KEY` gäller GTFS Sverige 3 Realtime (`gtfs-rt-sweden/...`).
- `GTFS_SWEDEN3_STATIC_KEY` gäller GTFS Sverige 3 statisk (`gtfs-sweden/sweden.zip`).
- `GTFS_REGIONAL_RT_KEY` gäller GTFS Regional Realtime (`gtfs-rt/{operator}/...`).

De två nya nycklarna syntes i chatten och ska roteras före drift. Kvot för statisk data: Bronze
10 anrop/min och 50/mån. Nyckeln delas mellan alla miljöer, så bara en miljö bör hämta dagligen.

Uppmätt 2026-09-19:

- **GTFS Regional Realtime, Skåne:** TripUpdates 200 (401 resor, alla hållplatser länskod 012),
  VehiclePositions 200 (1 089), ServiceAlerts 200 (203).
- **Sverige 3 statisk:** 650 MB zip på 15 s. `stop_times.txt` är 708 MB och `shapes.txt` 2,5 GB.
  `stop_id` är löpnummer ('1', '2' …), `trip_id` som `400000000000004936`.
- **Id:n matchar:** 371 av 404 `trip_id` i Regional Realtime Skåne finns i Sverige 3 `trips.txt`.
  Realtid och tidtabell går alltså att koppla ihop.
- **Färjor** (`route_type` 1000) finns på 74 linjer och 1 574 turer en lördag:
  Waxholmsbolaget (agency 114, 26 linjer), Västtrafik 15, Blekinge 7, SL 5, Trafikverket 4
  (vägfärjor), Destination Gotland 2, Ressel 2, Stavsnäs båttaxi 2, samt Ventrafiken
  (Landskrona–Ven), Skånetrafiken (Barum–Ivö), Visingsöfärjan, UL (Öregrund–Gräsö), Kalmar,
  Värmland, Kungälv, Roslagens sjötrafik, Strömma, Uddevalla och Sjöstadstrafiken.
  Utlandsfärjorna (Helsingborg–Helsingør, Stena, TT-Line, Finnlines, Tallink, Viking) finns inte.
- **Ingen realtid för färjorna:** 0 av 146 Ven-, Ivö- och Gotlandsturer den dagen fanns i Regional
  Realtime Skåne. Enligt Trafiklab har Destination Gotland, Ressel, Strömma, Stavsnäs båttaxi och
  Uddevalla bara statisk data. För färjorna ger GTFS alltså planerad tid och riktning, men ingen
  försening; läget kommer från AIS.
- **Bilväg vid färjeläget** (`stop_has_road`, räknat vid importen): 149 av 408 färjelägen har buss,
  spårvagn eller tåg inom 600 m enligt samma fil; 259 har det inte (3 790 av 12 621 anlöp). 400 m
  räckte inte: Nacka strands busshållplats ligger 470 m från bryggan. Rederiet med
  `agency_id` 500000000000000114 heter bara "114" i `agency.txt`; sidan skriver "rederi utan namn i
  tidtabellen (nr 114)" i stället för att gissa namnet.

### Known tuning issue at national scale (pre-existing, not caused by rollout)

`worth_it_score = demand_score - distance_km × 2` combined with the
deliberate road-score cap (~15–27) means **every road signal zeroes out past
roughly 8 km**. Measured: all 2,186 national non-ignore road signals score 0
for a Malmö driver — including roadwork in Malmö itself. Nationally this
"works" (no Norrbotten noise in Malmö) but for the wrong reason, and it also
suppresses genuinely local road incidents. Revisit the distance coefficient
for road tiers specifically before leaning on road data as a driver signal.

---

## Trafikverket (road)

Endpoint: `https://api.trafikinfo.trafikverket.se/v2/data.json`, XML query
POSTed with an auth key. Used for road `Situation` records. Mockable via
`TRAFIKVERKET_MOCK=1`.

Road incidents are deliberately scored low for taxi demand — an accident
delays people already in a car, it doesn't strand pedestrians who need a
taxi. See `worker/src/scoring.js`.

### Trafikverket rail — `TrainAnnouncement` vs `OperativeEvent` (candidate, not integrated)

Two different objecttypes exist on the same API, at two different levels.
Only the first is used today:

| Objecttype | Namespace | What it is | Used by |
|---|---|---|---|
| `TrainAnnouncement` | `rail.trafficinfo` v1.9 | The **symptom** — one departure, cancelled or delayed | `worker/src/trafikverketRail.js`, `taxitips-backend/core/sources/trafikverket_rail.py` |
| `OperativeEvent` | `ols.open` v1.0 | The **cause** — banarbete/tågfel/anläggningsfel on a rail section | Not wired in anywhere — verified live 2026-09-06 as a candidate, see below |

**Object type name is not obvious from Trafikverket's docs page** — the
field table (CountyNo, EventType, OperativeEventId, etc.) doesn't state the
`objecttype` attribute anywhere on the page. Verified by probing the live
API with `TRAFIKVERKET_API_KEY`; `OperativeEvent` is correct, `TrainMessage` /
`RailOperativeEvent` / `TrafficMessage` / `Event` all 400.

Measured live (2026-09-06, `EventState=1`, 59 events nationally):

- **`EventSection`** populated 100% — a from/to pair of `LocationSignature`
  codes, the same station-code register `fetchStations()` already builds.
  This is the join key if this source is ever ingested.
- **`EventType.Description`** gives a real named cause, embedded per-record
  (no separate lookup call needed): 42/59 "Banarbete/transport", the rest
  spread across track/switch/signal/catenary faults, one level-crossing
  accident, one police/medical stop.
- **`RoadDegreeOfImpact` and `RailRoadTimeForServiceResumption` are dead
  fields in practice** — 0/59 populated, including on the one
  level-crossing-accident record in the sample where road impact would be
  expected. Same shape as GTFS `cause`/`effect`: documented, not populated.
  `EventTrafficType` was 100% `0` (rail-only); the docs' `2` (rail+road)
  value was not observed live.
- **`EventState=1` ("active") is not "happening now"** — same publish-window
  trap already documented for SL above. 35/59 had a `StartDateTime` already
  in the past (one over a year old, still flagged active); one had a
  `StartDateTime` a month in the *future*. Worse: 7/59 had a nested
  `TrafficImpact[].EndDateTime` already passed while `EventState` stayed
  `1` — `TrafficImpact`'s own window, not the top-level state, is the
  trustworthy "is this still active" check.
- Volume is much smaller than `TrainAnnouncement`: 59 nationally active vs.
  thousands of departures per 8h window — this is one record per disrupted
  rail *section*, not per train.

**Why it might be worth adding:** it's the only source that would let a tip
say *why* — "Banarbete Mjölby–Motala, sedan igår" — instead of only
inferring cancelled/delayed from `TrainAnnouncement`. Needs a new
normalizer plus an expand-migrate-contract column addition on
`opportunities` for the cause text; no new API key required, same
`TRAFIKVERKET_API_KEY`.

A live read-only preview of this candidate source (counts, cause
breakdown, the `EventState` caveat above) is rendered in
`taxitips-pipeline-viz` — it calls Trafikverket directly, bypassing
`source_events`, so it proves nothing about production, only about what
the source contains.

---

### Trafikverket rail — kapad hämtning, rättad 2026-09-15

`poll_rail` frågade efter alla annonserade avgångar 8 h framåt med `limit="4000"`. Dagtid
ligger 14 000–15 000 i det fönstret (för 2026-09-15: 05–13 14 330, 07–15 14 372, 12–20
15 117; hela dygnet 33 597). Trafikverket gav de första 4 000 i odefinierad ordning. Natten
mot 2026-09-15 innehöll svaret 13 av 77 kommande inställda tåg. Hela dygnet hade 92 unika
inställda tåg; avbrott.se visade 87 samma dag.

Nu två frågor, sidindelade med `skip` och `orderby="ActivityId"`, och en komplett-flagga:

1. `Canceled=true` eller `EXISTS EstimatedTimeAtLocation` (en vardag 07–15: 272 + 3 031 rader).
2. Alla avgångar vid stationer där en störning blir ett tips, 40 signaturer per fråga
   (3 014 rader vid 103 stationer i samma fönster).

Live efter rättningen: 54 unika inställda tåg i fönstret, samma som en direkt fråga utan
sidor; 588 rader på 2 sidor, 2,4 s.

Tipsen blir ändå färre än "inställda tåg" på andra sajter: ett tips per tåg vid dess första
inställda stopp, en störning per station, bara 8 h framåt och synligt 90 min före avgång.
`source_status.detail` för `trafikverket_rail` bär `cancelled_trains` (unika tåg),
`cancelled_alerts` och `complete`, och pipeline-sidan visar dem bredvid varandra.

## SMHI (weather)

Endpoint: `https://opendata-download-metfcst.smhi.se/api/category/pmp3g/version/2/geotype/point/lon/{lon}/lat/{lat}/data.json`.
No key, no quota. Fetched once per poll cycle for a small set of Skåne
points, then nearest-point matched per opportunity.

Weather is a **modifier only** — it boosts an existing transit/road
disruption's score, never creates a signal on its own.

---

## Trafiklab ResRobot v2.1 (nästa resa) — added 2026-09-15

`https://api.resrobot.se/v2.1/` med `location.nearbystops`, `departureBoard` och `trip`.
Nyckel i `RESROBOT_API_KEY`, skickas som `accessId`. Licens CC0. Nivåer: Bronze 45 anrop/min
och 30 000/mån, Silver 60 och 200 000, Gold 200 och 1 000 000. Nyckeln skapades 2026-09-15
och syntes i chatten: rotera före drift.

Uppmätt 2026-09-15:

- Lindome 06:02, Västtågen 3022 mot Göteborg C inställt. Avgångstavlan saknade 3022 men
  hade 3023 åt andra hållet; `planRtTs` var 1970-01-01, alltså ingen realtidsplan.
  `trip` Lindome → Göteborg C gav 3174 06:13, 3024 06:28 och 3176 06:43.
- SL:s pendeltåg: `num` är linjenumret (43), inte tågnumret, och `trip` föreslog det
  inställda tåget självt "om 0 min". Därför räknas ett tåg inom 2 min från den inställda
  avgången som samma tåg.
- Ingen inställt-flagga syntes i svaren; `reachable` finns per delsträcka.

Användning, `core/sources/resrobot.py`: bara inställda tåg utan insatt ersättningstrafik som
går inom 2 h; högst 20 anrop per pollrunda (rälspollen går var 90:e sekund); månadsbudget
25 000; hållplats-id per station och räknaren i `source_status.detail["resrobot"]`; ett svar
återanvänds i 30 min. Första liverundan: 20 anrop, 7 svar, 13 kända hållplatser. Utan svar
gäller Trafikverkets nästa avgång från stationen.

Första rundan via beat (2026-09-15 22:02) fick `INT_HAFAS_CONNECTION_ERROR` på 8 av 11 anrop;
ett prov en minut senare svarade normalt. Efter 3 fel i en runda pausas anropen i 10 minuter,
även in i nästa runda, så att ett ihållande fel inte tömmer budgeten.

Kontroll mot Trafikverket 2026-09-15 22:10, Kallhäll: pendeltåg 2575 mot Nynäshamn inställt.
Trafikverkets avgångar därefter går 22:20 mot Bålsta, 22:25, 22:40 och 22:55 mot Västerhaninge,
och först 23:10 mot Nynäshamn. ResRobot svarade 23:10, alltså rätt: stationens nästa avgång
hade sagt tio minuter och menat ett tåg åt andra hållet.

## Swedavia FlightInfo v2 (flights) — added 2026-09-12

Portal: `https://apideveloper.swedavia.se` (product "FlightInfo Free").

```
GET https://api.swedavia.se/flightinfo/v2/{airportIATA}/arrivals/{YYYY-MM-DD}
  Ocp-Apim-Subscription-Key: <key>      # also accepted as ?subscription-key=
  Accept: application/json              # required by the spec
```

Other paths on the same product: `/{iata}/departures/{date}`, `/query` (OData
filter, max 1000 per page, continuation tokens), `/heartBeat`.

**Quota: 10,001 calls / 30 days.** No quota headers are returned — verified
against `/heartBeat`, which answers `200` with no `RateLimit-*`, `Retry-After`
or `x-ms-*` header of any kind. The budget is therefore counted client-side in
`SourceStatus.detail` for source `swedavia`; the cap and the per-airport
cadence both live in `core/thresholds.py`.

### Three things the OpenAPI spec does not tell you

**1. `DEL` means "Borttagen" / "Deleted", not "Delayed."** The
`locationAndStatus.flightLegStatus` enum is
`SCH, FPL, FLS, SEQ, ACT, CAN, LAN, RER, DIV, DEL` and contains **no delayed
status at all**. Measured on ARN 2026-09-12: all 29 `DEL` flights had neither
`estimatedUtc` nor `actualUtc` — they were pulled from the schedule, so they
carry zero arriving passengers. Reading `DEL` as "delayed" produces exactly the
inverse signal. Delay must be computed as
`(actualUtc ?? estimatedUtc) - scheduledUtc`; `DEL` and `CAN` are excluded from
every count.

**2. `{date}` is the local Swedish date, not UTC.** The ARN response for
`2026-09-12` spans 00:05–23:55 local, and a flight scheduled
`2026-09-11T22:35Z` (= 00:35 local on the 12th) appears in the 12th's payload.
A time window crossing midnight therefore needs two fetches.

**3. There is no aircraft type and no passenger count.** Fields are
`flightId`, `airlineOperator`, the three times, `locationAndStatus`, `baggage`,
`diIndicator` (D/S/I = domestic/Schengen/international) and
`flightLegIdentifier` (callsign, registration, ssrCode). A tip may state the
number of arrivals and nothing more — "500–600 people" would be invented.

### Measured volume (2026-09-12, full day, excluding DEL/CAN)

| Airport | Arrivals | Busiest 30-min window | Late windows (21:00–02:00) |
|---|---|---|---|
| ARN | 230 | 12 | 5, 2, 5, 5, 8, 12 |
| GOT | 59 | 4 | 2, 2, 2, 4 |
| MMX | 7 | 1 | 1, 1 |

Field fill rates on ARN's 260 rows: `scheduledUtc` 260/260, `estimatedUtc`
186/260, `actualUtc` 150/260. `remarksSwedish` present on 187 (mostly
"Sista bagage" and "Landat HH:MM" — FIDS text, not a machine-readable signal).

**Calibration note.** Delay clustering alone is too rare to carry the signal:
across the whole day only 10 flights were ≥40 min late and the fullest 30-min
window held **2** of them, so a "more than 3 delayed in one window" rule fires
approximately never. Arrival *volume* is the reliable trigger and delay is the
amplifier — and because the three airports differ by an order of magnitude, the
threshold is per airport (`thresholds.AIRPORTS[...]["wave_min"]`), not global.

## AISStream.io (fartyg, WebSocket) — added 2026-09-12

`wss://stream.aisstream.io/v0/stream`. Nyckel i `AISSTREAM_API_KEY`. Konsumeras av
`taxitips-backend/maritime/` (`manage.py run_ais_stream`), en långlivad process — inte Celery.

**Regler från dokumentationen:** prenumerationen måste skickas inom 3 s efter anslutning,
annars stängs den. Max 3 samtidiga anslutningar per konto (lokal körning räknas). Högst en
prenumerationsuppdatering per sekund; en uppdatering *ersätter* den förra. `BoundingBoxes`
är `[[lat, lon], [lat, lon]]` — latitud först. Ramarna är binära men innehållet är UTF-8-JSON.
Fel kommer som `{"error": "..."}`. Första meddelandet är `MessageType: "SubscriptionConfirmation"`.

### Fyra saker dokumentationen inte säger (uppmätt 2026-09-12, 76 s, åtta hamnrutor)

1. **`MetaData` använder gemener:** `latitude`, `longitude`, `time_utc`
   (`"2026-09-12 19:25:20.575040512 +0000 UTC"`, nanosekunder). Dokumentationen skriver
   `Latitude`. `MMSI_String` kom som heltal. Positionen finns även i `PositionReport.Latitude/Longitude`.
2. **`PositionReport` har ingen fartygstyp.** `ShipType` finns bara i `ShipStaticData.Type`, som
   sänds ungefär var 6:e minut: 9 statiska mot 85 positioner. Typen måste cachas per MMSI.
3. **ETA är ofta skräp.** `{"Hour": 24, "Minute": 60}` och nollor betyder "saknas"; en båt bar
   en ETA från juni i september. Inget år. ETA gäller fartygets *nästa* destination.
4. **ShipType 60–69 är mest småbåtar.** Alla nio passagerarfartyg i provet var 24–38 m
   (Waxholmsbolaget, Strömma, Styrsöbolaget). `Dimension.A + Dimension.B` = längd; tipsgränsen är
   100 m (`maritime/tips.py`).

Övrigt: `Sog` 102.3 = saknas. Positionen 91/181 = saknas. `NavigationalStatus` 5 = förtöjd,
1 = ankrad, 15 = odefinierad (vanligt på småbåtar). Namn och destination är utfyllda med `@`.

**Kvot:** ingen dokumenterad meddelandekvot. Volym i de åtta rutorna: ~70 positioner/minut en
lördagskväll, nästan allt Stockholms inre hamn.

### Rättelse samma dag: klass B, och hela schemat

Första versionen lyssnade bara på `PositionReport` och `ShipStaticData` (klass A). Det missade en
tredjedel av fartygen. Mätt utan typfilter, två minuter, samma åtta rutor:

| MessageType | Meddelanden | Unika MMSI |
|---|---|---|
| PositionReport (klass A) | 117 | 80 |
| StandardClassBPositionReport | 43 | 42 |
| ShipStaticData (klass A) | 21 | 21 |
| StaticDataReport (klass B) | 20 | 20 |

Inga andra av de 25 typerna kom på två minuter. Fullständigt schema: `type-definition.yaml` i
github.com/aisstream/ais-message-models (länkad från dokumentationssidan; sidans schemautforskare
bygger på den). Prenumerationen tar nu de sex typer som beskriver fartyg:
`PositionReport`, `StandardClassBPositionReport`, `ExtendedClassBPositionReport`,
`LongRangeAisBroadcastMessage`, `ShipStaticData`, `StaticDataReport`.

- **`StaticDataReport` kommer i två delar.** `PartNumber: false` = del A med bara `ReportA.Name`;
  `ReportB` är då `Valid: false` och nollad, inklusive `ShipType: 0`. Del B (`PartNumber: true`) bär
  `ShipType`, `CallSign`, `Dimension`. Tolkas del A som statisk data nollas fartygets typ.
- **Klass B saknar `NavigationalStatus`.** `Cog: 360` och `TrueHeading: 511` betyder "saknas".
- **`ExtendedClassBPositionReport`** bär `Name`, `Type` och `Dimension` i samma meddelande som läget.
- **`ShipType: 0`** = saknas, inte en typ.
- **`SubscriptionConfirmation.Message.CompressionEnabled`** ska vara `true`. Från september 2026 får
  okomprimerade anslutningar bandbreddstak och meddelanden över taket kastas utan fel.
- **Fler driftgränser:** 3 öppna anslutningar per IP-adress (före autentisering), och meddelanden
  kastas om klienten inte läser tillräckligt snabbt. En prenumeration som inte är giltig får ingen
  bekräftelse alls.

### Terminalregistret och inseglingsområdena, 2026-09-18

Urvalet följer Trafikanalys, Sjötrafik 2024: Stockholms hamnar (inklusive Kapellskär,
Nynäshamn och Norvik) hade 7,2 miljoner passagerare och Helsingborg 6,4 miljoner, med den
turtäta linjen Helsingborg–Helsingör. Därefter kommer i rangordning Visby, Ystad, Trelleborg,
Göteborg och Strömstad. Rapporten ger bara diagram för resten; siffrorna per hamn finns i
Trafikanalys tabeller.

`maritime/ports.py` har 17 hamnar: de åtta tidigare plus Helsingborg, Strömstad, Kapellskär,
Grisslehamn, Oskarshamn, Varberg, Karlshamn, Malmö och Umeå. De nya hamnarnas terminalpunkter
kommer från OpenStreetMap (`ferry_terminal` där en sådan finns; för Varberg, Malmö och Umeå bara
hamnområdet), hämtade 2026-09-18. Visbys punkt rättades efter OSM, ungefär en kilometer.
Karlskronas punkt låg 3,5 km fel och har använts för tips: STENA ESTELLE låg förtöjd
(AIS-status 5) vid 56,1658/15,6296, och OSM:s `ferry_terminal` "Karlskrona - Gdynia" ligger
25 m därifrån. Punkten är flyttad och hamnrutan utvidgad norrut. Umeås punkt flyttades 1,1 km
till där AURORA BOTNIA stannade (se nedan); ett enda anlöp.

Prenumerationen lyssnar nu på inseglingsområdena: 16 rektanglar, eftersom Stockholms två
terminaler delar område. Tidigare lyssnade den bara på hamnrutorna. Ankomsten avgörs
fortfarande i hamnrutan. De nya hamnarna ger inga tips förrän terminalpunkten stämts av mot
AIS-spår. Helsingborg ger aldrig tips: färjorna går i pendel.

Första anslutningen med de nya områdena 2026-09-18 18:51 bekräftades med komprimering. Efter
5 s hördes AURORA BOTNIA (151 m, destination "VAASA-UMEA-VAASA") i Umeås område.
Liveprovet 2026-09-18: efter 20 minuter visade kartan 19 stora passagerarfärjor i elva
hamnområden, bland dem VIKING GLORY vid kaj i Stadsgården, VISBY i Oskarshamn, GOTLAND i
Nynäshamn samt SILJA SYMPHONY och BALTIC QUEEN på väg genom Stockholms skärgård. AURORA BOTNIA
mot Umeå fick beräknad ankomst 19:19 (kl. 18:52, 10,3 km kvar), 19:17 (kl. 19:01) och 19:18
(kl. 19:11). Den stod still i hamnrutan 19:13:39, 1,1 km från den dåvarande terminalpunkten:
beräkningen var 4–6 minuter sen, främst för att punkten låg fel. Ett enda anlöp, ingen kalibrering.
Öresundsfärjornas typ och längd hördes först 23–25 minuter efter start (TYCHO BRAHE 110 m,
HAMLET 106 m). Ett separat prov mot bara Helsingborgs område visade att AISStream skickar dem;
det tar bara tid, och efter en omstart läses de in från databasen. Efter omstart med rättade
punkter kl. 19:20: STENA ESTELLE 0,0 km och AURORA BOTNIA 0,2 km från sina terminalpunkter,
HAMLET vid kaj i Helsingborg, COLOR HYBRID på väg in mot Strömstad. Kryssningsfartyg har också
AIS-typ 60 och räknas med (SKY PRINCESS, 330 m, i Stadsgården).

Livebilden: `maritime/approach.py`, `/api/pipeline/ferries` (bara med DEBUG), avsnitt 2c på
pipeline-sidan, och `/api/ferries` i appen. AISStream har inga publicerade villkor om visning eller
kommersiell användning (startsidan och dokumentationen lästa 2026-09-18): fråga före betald lansering.

### Piloten Visby/Värtahamnen live, 2026-09-14

En MMSI-filtrerad anslutning (`FiltersShipMMSI`, tre fartyg) 07:04–18:07 på en bärbar
dator: 24 positionsmeddelanden, 2 statiska, 0 anlöp. Anslutningen stängdes 14 gånger
utan close frame. Datorn sov i perioder (pmset: 44 insomningar), så siffrorna är ingen
täckningsmätning. Mät på en server innan AISStreams täckning vid färjelägena bedöms.

## Ticketmaster Discovery API v2 (evenemang) — added 2026-09-12

`https://app.ticketmaster.com/discovery/v2/events.json?apikey=…&countryCode=SE`. Bara **Consumer Key**
(`TICKETMASTER_API_KEY`); Consumer Secret används inte av Discovery. Konsumeras av
`taxitips-backend/events/` (`manage.py poll_events`, Beat var 6:e timme).

**Kvot:** 5000 anrop/dygn, 5/s. Headers `Rate-Limit`, `Rate-Limit-Available`, `Rate-Limit-Over`,
`Rate-Limit-Reset` (epoch ms). **Djup paginering:** "size * page < 1000" — fönstren delas därför.

### Uppmätt i Sverige

- **315 kommande evenemang**, 55 inom 30 dagar, 22 inom 14. Music 183, Arts & Theatre 103,
  Miscellaneous 22, **Sports 5**. Stockholm 133, Linköping 66, Skellefteå 44, Göteborg 25, **Malmö 4**.
- **Tunt för arenorna:** Avicii Arena 0 evenemang, Strawberry Arena 2, Malmö Arena 2 — arenorna finns i
  `venues.json` men har nästan inga evenemang. Källan räcker inte ensam för en rikstäckande kalender.
- Alla 315 har `venue.location`. 28 har `dates.end`, 11 har `timeTBA`, 3 `spanMultipleDays`.
- **`dates.end.localTime` är fel:** en kopia av startens localTime ("18:00" → "18:00") medan
  `dates.end.dateTime` stämmer (16:00Z → 17:00Z). Använd bara `dateTime`.
- **Arenanamn saknas ibland** (Ella Mai och A$AP Rocky på Globentorget 2 = Avicii Arena) — adressen finns.
- **Tilläggsprodukter säljs som evenemang:** "President | Early entry and merchandise experience",
  "Dryckeskuponger - Linköping Beer Expo", "… Platinum Tickets". Samma namn samma dag med olika tider
  (Mamma Mia! The Party 13:00 och 19:30) är däremot riktiga föreställningar.
- `classifications[].name == "Undefined"` förekommer och betyder ingenting.

### Villkor (developer.ticketmaster.com/support/terms-of-use, ordagrant)

- *"Sell, lease, or sublicense the Ticketmaster API or access thereto or derive revenues from the use or
  provision of the Ticketmaster API, whether for direct commercial or monetary gain or otherwise, except as
  set forth below."* — inget undantag följer. **TaxiTips är betalt: avtal krävs före produktion.**
- *"Cache or store any Event Content other than for reasonable periods in order to provide the service you
  are providing."* och *"Remove from your application within 24 hours any Event Content … that the owner
  asks you to remove."*
  24-timmarsregeln gäller alltså *borttagning när innehållsägaren begär det*, inte hur länge data får
  sparas i allmänhet -- där gäller "reasonable periods". Att `events/ingest.py` raderar passerade och
  försvunna evenemang efter 24 timmar är vårt eget val, inte ett villkor.
- *"we reserve the right to rate limit or block applications that make a large number of calls to the API
  that are not primarily in response to direct user actions."*
- Integritetspolicy i appen som beskriver hur data samlas in och används.

## PredictHQ Events API — undersökt 2026-09-13, visas live, sparas inte

`https://api.predicthq.com/v1/events/`, `Authorization: Bearer $PREDICTHQ_ACCESS_TOKEN`. Konsumeras av
`taxitips-backend/events/live.py` (`/api/pipeline/predicthq`, bara med DEBUG) och visas i
pipeline-sidans karta och kalender. **Inget sparas utan skriftligt avtal** — `events/rights.py` kräver både
`EVENTS_PREDICTHQ_STORE=1` och en rättighetsreferens (`EVENTS_PREDICTHQ_STORE_REFERENCE`) innan
`poll_events` gör ett enda anrop. Referensen ger ingen rätt i sig; den ska peka på avtalet. Se villkoren nedan.

**Täckning i Sverige, uppmätt:** ungefär tio gånger fler evenemang än Ticketmaster, med sport i en helt
annan skala (ishockey, fotboll, basket). De flesta har `phq_attendance` (förutsagt antal besökare); den
saknas främst för scenföreställningar. De flesta har `predicted_end`; en riktig `end` finns sällan.

**Fält som betyder något annat än de ser ut:**
- `end == start` betyder okänd sluttid. Använd `predicted_end` när den finns.
- Heldag skrivs `start_local` 00:00:00 och `end_local` 23:59:59. Flerdagars: `duration > 86400`.
- Många saknar `entities[type=venue]`, och en del saknar `geo.address.locality` — orten står då efter
  postnumret i `geo.address.formatted_address`.
- Ortnamn blandas: "Gothenburg" och "Göteborg", "Skelleftea" och "Skellefteå".
- Enstaka titlar är dubbelkodad UTF-8 ("GÃ¶teborg Book Fair").
- `performing-arts` blandar stå-upp, film, konsert, barnteater och cirkus — dela upp på `phq_labels`.
- `location` är utfasat; använd `geo.geometry.coordinates` (`[lon, lat]`).

**Anrop:** `limit` gav högst 50 per sida (planberoende). Svarshuvudet `x-ratelimit-limit: 200, 200;w=60`.
`overflow: true` betyder att abonnemanget kapade svaret — utan felkod. `next` bär alla parametrar.

**Överlapp med Ticketmaster:** de flesta Ticketmaster-evenemang finns också hos PredictHQ, oftast inom 30 m
och med samma namn. `events/matching.py` parar dem i minnet (400 m, 90 min, namnlikhet ≥ 0,5).

### Villkor (predicthq.com/legal/terms, ordagrant)

- **3.7 d) i)** Customer must not: *"cache, store, download, scrape, or retain a copy of or a method of
  accessing (other than via the API token that PredictHQ has issued to Customer) any PredictHQ Data in any
  form or format, unless otherwise agreed with us in writing"* — **ingen lagring utan skriftligt tillstånd.**
- **3.7 c)** *"For Customers that are on a 14-Day Trial or a complimentary or trial Starter or Premium Plan,
  Customer's right to use any PredictHQ Data is limited to internal use for the purposes of testing …
  provided that Customer will not use any PredictHQ Data … for Commercial Use unless and until Customer has
  subscribed to a (paid) Premium Plan or a (paid) Starter Plan."*
- **Lokal testlagring är inte undantagen.** 3.7 c) begränsar hur provdata får *användas* (internt, för
  test); den upphäver inte 3.7 d) i). De publicerade villkoren ger alltså inget generellt undantag för att
  spara PredictHQ-data lokalt eller i en testmiljö. Vad som är tillåtet avgörs av ett faktiskt skriftligt
  avtal med PredictHQ -- en miljövariabel eller inställning i koden ger ingen sådan rätt.
- **3.7 b) ii)** betalda planer får *"use, display, frame, transmit and make available that PredictHQ Data
  solely in respect of Customer's own internal business use, products and services"*.
- **3.7 e)** API-token är konfidentiell och får inte delas utanför organisationen.
- **4.8** Evenemang som visas i webb eller app ska attribueras till PredictHQ enligt deras Attribution
  Policy. (Policysidan hittades inte via länkarna på villkorssidan.)

**Beslut 2026-09-13:** live i pipeline-sidan, ingen lagring, inte i förarappen förrän avtal finns.

## API-Sports (API-Football v3, API-Hockey v1) — undersökt 2026-09-13, inte integrerat

`https://v3.football.api-sports.io`, `https://v1.hockey.api-sports.io`, header `x-apisports-key`.
Gratisplan: 100 anrop/dygn per API, 10/minut (`x-ratelimit-requests-limit`, `x-ratelimit-limit`).

- Kontot svarade `{"access": "Your account is suspended, check on https://dashboard.api-football.com."}`
  på alla anrop, även `/status`.
- **Gratisplanen har inga aktuella säsonger:** hockey svarade `{"plan": "Free plans do not have access to
  this season, try from 2022 to 2024."}` för både 2025 och 2026. Kommande matcher kräver betald plan.
- Villkorssidan (api-football.com/terms) gav 403 till automatisk hämtning; inte läst.

## Trafikverket färjor (vägfärjor) — undersökt 2026-09-13, inte integrerat som egen källa

Samma API och nyckel som väg och tåg (`api.trafikinfo.trafikverket.se/v2/data.json`). Gäller Trafikverket
Färjerederiets 40 **vägfärjeleder** (Hönöleden, Vaxholmsleden, Ljusteröleden, Gullmarsleden …) — gratis
bilfärjor, inte passagerarrederier. De passagerarfärjor som ger taxiresor fångas av AISStream (`maritime/`).

- `FerryRoute` (schema 1.2): 40 leder. `Name`, `Shortname`, `Type` (Vändande / Avg - Avg / Rutt),
  `Harbor[]`, `Timetable[]`, `Geometry.WGS84`, `DeviationId`.
- `FerryAnnouncement` (schema 1.2): varje avgång. `DepartureTime`, `FromHarbor`, `ToHarbor`, `Route`,
  `Deleted`, `Info[]`, `DeviationId`. Uppmätt: 2 292 avgångar på 24 h, **0 med `Deleted: true`** — och
  0 bland de 111 avgångar API:t hade kvar från senaste 7 dygnen. `Info` är driftinfo ("Kallelsetur …",
  "På färjan: Kör så nära framförvarande bil som möjligt", "Färja 1").
- `DeviationId` är **samma för alla avgångar på en led** och pekar på en permanent `Situation`-avvikelse
  (namespace `road.trafficinfo`, schema 1.6) med `MessageType: "Färjor"`, `MessageCode: "Färja"`. De flesta
  är tomma platshållare (öppna sedan 2025); riktiga störningar står som fritext i `Message`, t.ex.
  "14 september klockan 19:30 turen inställd på grund av en övning i färjetrafiken."
- **Delvis redan i pipelinen:** vägkällan (`poll_road`) hämtar `Situation` per län och får därmed
  färjeavvikelserna. Före P0-A3 bara så många som rymdes under taket `min(100 × län, 2000)`: oavgränsat
  svarade API:t med 3 496 situationer 2026-09-13 medan `poll_road` hämtade 2 000. Nu hämtas alla sida för
  sida (`limit=1000`, `skip`, `orderby="Id"`); mätt samma dag: 3 486 situationer på fyra sidor, inga
  dubbletter. `MessageType` i hela vägflödet:
  Vägarbete, Trafikmeddelande, Färjor, Hinder.
- Utan `namespace="road.trafficinfo"` svarar `Situation` med HTTP 400.

**Bedömning:** ingen taxiefterfrågan. En inställd vägfärjetur ersätts inte av taxi över vattnet; den gör
ett resmål svårt att nå, vilket är förarkontext av samma slag som en avstängd väg — och den texten når
redan pipelinen via vägavvikelserna.

## Län och kommuner — SCB Digitala gränser (2026-02-25), CC0

`https://www.scb.se/contentassets/3443fea3fa6640f7a57ea15d9a372d33/shape_svenska_260225.zip` innehåller
`LanSweref99TM.zip` (21 län, fält `LnKod`, `LnNamn`) och `Kommun_Sweref99TM.zip` (290 kommuner, `KnKod`,
`KnNamn`), polygoner i SWEREF 99 TM. Licens CC0 enligt SCB; källangivelse "Källa: SCB" rekommenderas men
krävs inte. SCB kallar gränserna förenklade för tematisk presentation, inte för analys.

`ops/geo/build_areas_scb.py` räknar om till WGS84 (Lantmäteriets Gauss–Krüger-formler) och skriver
`taxitips-backend/core/data/se_counties.geojson` (77 kB) och `se_municipalities.geojson` (226 kB).
Kontrollerat 2026-09-14: Stockholm, Göteborg, Malmö, Kiruna, Visby, Umeå, Uppsala och Arlanda hamnar i rätt
kommun. Ersatte Natural Earth admin-1 (ungefär en kilometer, bara län).

Kommunkoden börjar med länskoden, så `core/areas.py` låter länet följa kommunen och de två hamnar aldrig på
olika sidor om samma gräns.

### TheSportsDB: fotboll, ishockey och handboll (2026-09-19)

Ersatte API-SPORTS samma dag (det kontot var avstängt; koden är borttagen). `events/sources/thesportsdb.py`.

- **Nyckel:** den öppna gratisnyckeln `123` (`THESPORTSDB_API_KEY`, tom = 123). 30 anrop/minut;
  klienten håller 2,5 s mellan anrop och väntar en minut vid 429.
- **Gratisnyckelns gränser:** `eventsnextleague` 1 match, `eventsseason` 5, `eventsday` 3. Hela omgångar
  (`eventsround`) ges fullt ut (Allsvenskan 8, SHL 7). Hämtning: ligans aktuella säsong (`lookupleague`),
  nästa match ger omgången, sedan upp till 8 omgångar framåt. Hockey Allsvenskan saknar omgångsnummer:
  omgång 0 ger alla (50).
- **Ligor med stor publik** (id enligt `search_all_leagues.php?c=Sweden`): Allsvenskan 4347, SHL 4419,
  Hockey Allsvenskan 5162, Handbollsligan 5136. Superettan finns inte hos TheSportsDB. Handbollsligan
  hade bara säsongen 2025-2026 (0 kommande matcher).
- **Arena:** `lookupvenue` ger `strMap` (koordinater) och `intCapacity`; saknas koordinater används ortens
  centrum (`core/geo.py` CITY_COORDS) eller kommunens mitt (`core/areas.py` municipality_point); saknas
  arenan helt, orten i hemmalagets namn. Uppmätt: 157 matcher, alla med plats efter reserverna.
- **Tider** (`strTimestamp`) i UTC. Sluttid uppskattas per sport: fotboll 115 min, ishockey 150,
  handboll 95 (okalibrerat).
- **Villkor** (docs_terms_of_use): "You cannot publish apps to an appstore unless you are a paid
  subscriber", källan ska anges med länk. Visning i förarappen är av tills betald plan och referens
  (`EVENTS_THESPORTSDB_APP_REFERENCE`) finns.

### PredictHQ: flygförseningar (airport-delays), uppmätt 2026-09-19

- Hämtas för `country=SE` och `country=DK`; från Danmark behålls bara Köpenhamn (CPH).
  Visas live på pipelinevyns Flyg-sida (`/api/pipeline/airport-delays`), cachat 10 min, sparas inte.
- **Nivån är PHQ Rank** (dokumentationen): 20 minimal, 40 måttlig, 70 betydande, 90 svår. Titeln
  säger "Moderate Delays" även vid rank 20 och används därför inte.
- Varje försening har start och slut (UTC plus `start_local`/`end_local`), position på flygplatsen och
  en venue-entitet. `phq_labels` var tom trots att dokumentationen lovar etiketterna airport och delay.
- Oplanerade: inga framtida förseningar i svaret. `first_seen` låg 60-75 min efter starten för CPH.
- 90 dagar bakåt: 667 förseningar i Sverige och på CPH (17 anrop). CPH 25 (6 svåra), oftast 01-04.
