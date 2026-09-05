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

**Everything still points to one action:** get a GTFS **Regional** Realtime
key. That unlocks correctly-scoped ServiceAlerts *and* TripUpdates whose ids
join our existing Regional static data.

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

## Trafikverket (road)

Endpoint: `https://api.trafikinfo.trafikverket.se/v2/data.json`, XML query
POSTed with an auth key. Used for road `Situation` records. Mockable via
`TRAFIKVERKET_MOCK=1`.

Road incidents are deliberately scored low for taxi demand — an accident
delays people already in a car, it doesn't strand pedestrians who need a
taxi. See `worker/src/scoring.js`.

---

## SMHI (weather)

Endpoint: `https://opendata-download-metfcst.smhi.se/api/category/pmp3g/version/2/geotype/point/lon/{lon}/lat/{lat}/data.json`.
No key, no quota. Fetched once per poll cycle for a small set of Skåne
points, then nearest-point matched per opportunity.

Weather is a **modifier only** — it boosts an existing transit/road
disruption's score, never creates a signal on its own.
