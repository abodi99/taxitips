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

## SMHI (weather)

Endpoint: `https://opendata-download-metfcst.smhi.se/api/category/pmp3g/version/2/geotype/point/lon/{lon}/lat/{lat}/data.json`.
No key, no quota. Fetched once per poll cycle for a small set of Skåne
points, then nearest-point matched per opportunity.

Weather is a **modifier only** — it boosts an existing transit/road
disruption's score, never creates a signal on its own.
