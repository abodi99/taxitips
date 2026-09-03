/**
 * GTFS-static schedule ingestion (Trafiklab GTFS Regional, Skåne operator scope).
 *
 * This closes the exact gap scoring.js's own header comment names: without a
 * real timetable, "single cancelled departure" vs "whole line paused" can only
 * be guessed from the alert's own wording. This feed gives the real answer --
 * when's the next scheduled departure at the affected stop, and is tonight's
 * service already over.
 *
 * Quota is tiny (Bronze 50/month, Silver 250/month per Trafiklab's published
 * limits) -- this must be fetched at most once or twice a day, NEVER per-alert
 * or per-request. See index.js's startup guard for how that's enforced.
 *
 * Only 6 of GTFS's files are parsed -- stops/trips/stop_times/calendar/
 * calendar_dates/routes -- everything else in the zip (shapes, frequencies,
 * transfers, fares) is irrelevant to "next departure at stop X" and is
 * skipped without error, so the zip can gain new optional files over time
 * without breaking ingestion.
 */

const yauzl = require("yauzl");
const { parse } = require("csv-parse/sync");

const GTFS_FILES = ["stops.txt", "trips.txt", "stop_times.txt", "calendar.txt", "calendar_dates.txt", "routes.txt"];
const BATCH_SIZE = 5000;
const DAY_KEYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];

async function fetchGtfsZip(apiKey, operator) {
  const url = `https://opendata.samtrafiken.se/gtfs/${encodeURIComponent(operator)}/${encodeURIComponent(operator)}.zip?key=${encodeURIComponent(apiKey)}`;
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`gtfs-static ${operator} ${res.status}: ${body.slice(0, 160)}`);
  }
  return Buffer.from(await res.arrayBuffer());
}

function parseGtfsZip(buffer) {
  return new Promise((resolve, reject) => {
    const out = {};
    yauzl.fromBuffer(buffer, { lazyEntries: true }, (err, zipfile) => {
      if (err) return reject(err);
      zipfile.readEntry();
      zipfile.on("entry", (entry) => {
        const name = entry.fileName.split("/").pop();
        if (!GTFS_FILES.includes(name)) {
          zipfile.readEntry();
          return;
        }
        zipfile.openReadStream(entry, (streamErr, stream) => {
          if (streamErr) return reject(streamErr);
          const chunks = [];
          stream.on("data", (chunk) => chunks.push(chunk));
          stream.on("end", () => {
            try {
              out[name] = parse(Buffer.concat(chunks), { columns: true, skip_empty_lines: true, bom: true });
            } catch (parseErr) {
              return reject(new Error(`gtfs-static parse ${name}: ${parseErr.message}`));
            }
            zipfile.readEntry();
          });
          stream.on("error", reject);
        });
      });
      zipfile.on("end", () => resolve(out));
      zipfile.on("error", reject);
    });
  });
}

// HH:MM:SS -> seconds, deliberately NOT wrapped at 86400 -- GTFS allows hours
// >23 for trips that run past midnight, and preserving that is what makes
// same-service-day ordering across midnight correct downstream.
function parseGtfsTime(hhmmss) {
  const parts = String(hhmmss || "").split(":").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
  const [h, m, s] = parts;
  return h * 3600 + m * 60 + s;
}

function daysOfWeekBitmask(calendarRow) {
  let mask = 0;
  DAY_KEYS.forEach((day, i) => {
    if (calendarRow[day] === "1") mask |= 1 << i;
  });
  return mask;
}

function parseGtfsDate(yyyymmdd) {
  const s = String(yyyymmdd || "");
  if (s.length !== 8) return null;
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
}

function buildStopDepartures({ trips, stopTimes, calendar, routes }) {
  const tripById = new Map(trips.map((t) => [t.trip_id, t]));
  const routeById = new Map(routes.map((r) => [r.route_id, r]));
  const calendarByServiceId = new Map(calendar.map((c) => [c.service_id, c]));

  const rows = [];
  for (const st of stopTimes) {
    const trip = tripById.get(st.trip_id);
    if (!trip) continue;
    const departureSeconds = parseGtfsTime(st.departure_time);
    if (departureSeconds == null) continue;
    const route = routeById.get(trip.route_id);
    const cal = calendarByServiceId.get(trip.service_id);

    rows.push({
      stop_id: st.stop_id,
      trip_id: st.trip_id,
      route_id: trip.route_id || null,
      route_type: route ? Number(route.route_type) : null,
      service_id: trip.service_id,
      departure_seconds: departureSeconds,
      stop_sequence: st.stop_sequence != null ? Number(st.stop_sequence) : null,
      // No calendar.txt row (a calendar_dates-only service_id) -> mask 0, no
      // weekday validity of its own; buildServiceExceptions' rows are the
      // only thing that can make it valid on a given date.
      days_of_week: cal ? daysOfWeekBitmask(cal) : 0,
      start_date: cal ? parseGtfsDate(cal.start_date) : null,
      end_date: cal ? parseGtfsDate(cal.end_date) : null,
    });
  }
  return rows;
}

// stop_code is GTFS's field for "the identifier riders/other systems see" as
// opposed to stop_id (the feed's own internal key) -- stored specifically to
// test/bridge the mismatch between GTFS-RT alert stop_ids (Skånetrafiken's
// own short "hållplats" numbers) and this static feed's stop_id format
// (Samtrafiken's national VDV-style stop-point IDs).
function buildStops({ stops }) {
  return (stops || []).map((row) => ({
    stop_id: row.stop_id,
    stop_code: row.stop_code || null,
    stop_name: row.stop_name || null,
    parent_station: row.parent_station || null,
  }));
}

function buildServiceExceptions({ calendarDates }) {
  return (calendarDates || [])
    .map((row) => ({
      service_id: row.service_id,
      exception_date: parseGtfsDate(row.date),
      exception_type: Number(row.exception_type),
    }))
    .filter((row) => row.exception_date != null);
}

async function insertInBatches(client, table, rows, extraFields) {
  for (let i = 0; i < rows.length; i += BATCH_SIZE) {
    const batch = rows.slice(i, i + BATCH_SIZE).map((r) => ({ ...r, ...extraFields }));
    const { error } = await client.from(table).insert(batch);
    if (error) throw new Error(`gtfs-static insert ${table}: ${error.message}`);
  }
}

async function ingestGtfsStatic(client, apiKey, operator) {
  if (!apiKey || apiKey === "mock") {
    console.log(`[gtfs-static] no real API key configured, skipping ${operator} ingest`);
    return { skipped: true };
  }

  const zipBuffer = await fetchGtfsZip(apiKey, operator);
  const files = await parseGtfsZip(zipBuffer);
  const required = ["stops", "trips", "stop_times", "calendar", "routes"];
  for (const key of required) {
    const fileName = `${key}.txt`;
    if (!files[fileName]) throw new Error(`gtfs-static ${operator}: missing ${fileName} in zip`);
  }

  const departures = buildStopDepartures({
    trips: files["trips.txt"],
    stopTimes: files["stop_times.txt"],
    calendar: files["calendar.txt"],
    routes: files["routes.txt"],
  });
  const exceptions = buildServiceExceptions({ calendarDates: files["calendar_dates.txt"] || [] });
  const stops = buildStops({ stops: files["stops.txt"] });

  const { data: versionRow, error: versionErr } = await client
    .from("gtfs_feed_versions")
    .insert({
      operator,
      is_current: false,
      stop_count: files["stops.txt"].length,
      trip_count: files["trips.txt"].length,
      stop_time_count: departures.length,
    })
    .select("id")
    .single();
  if (versionErr) throw new Error(`gtfs-static insert feed_version: ${versionErr.message}`);

  await insertInBatches(client, "gtfs_stop_departures", departures, {
    feed_version_id: versionRow.id,
    operator,
  });
  await insertInBatches(client, "gtfs_service_exceptions", exceptions, {
    feed_version_id: versionRow.id,
  });
  await insertInBatches(client, "gtfs_stops", stops, {
    feed_version_id: versionRow.id,
  });

  const { error: promoteErr } = await client.rpc("gtfs_promote_feed_version", {
    p_new_id: versionRow.id,
    p_operator: operator,
  });
  if (promoteErr) throw new Error(`gtfs-static promote: ${promoteErr.message}`);

  return {
    feedVersionId: versionRow.id,
    stopCount: files["stops.txt"].length,
    tripCount: files["trips.txt"].length,
    departureCount: departures.length,
    exceptionCount: exceptions.length,
  };
}

// Convert a Date to "YYYY-MM-DD" using its LOCAL calendar date, not UTC --
// service-day boundaries are wall-clock/local, and callers pass real local
// instants (a driver's "now", an alert's active_to).
function localDateString(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function addDays(date, n) {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

async function getCurrentFeedVersionId(client, operator) {
  const { data, error } = await client
    .from("gtfs_feed_versions")
    .select("id")
    .eq("operator", operator)
    .eq("is_current", true)
    .maybeSingle();
  if (error) throw new Error(`gtfs-static current version lookup: ${error.message}`);
  return data?.id || null;
}

// Which service_ids run on a given local calendar date, folding in
// calendar_dates.txt overrides (added/removed) on top of the weekday+range
// base validity from calendar.txt (already precomputed into days_of_week/
// start_date/end_date on gtfs_stop_departures at ingest time).
async function validServiceIdsForDate(client, feedVersionId, dateObj, candidateServiceIds) {
  if (!candidateServiceIds.length) return new Set();
  const dateStr = localDateString(dateObj);
  const weekdayBit = 1 << dateObj.getDay(); // matches DAY_KEYS' Sunday=0 order

  const { data: baseRows, error: baseErr } = await client
    .from("gtfs_stop_departures")
    .select("service_id, days_of_week, start_date, end_date")
    .eq("feed_version_id", feedVersionId)
    .in("service_id", candidateServiceIds);
  if (baseErr) throw new Error(`gtfs-static service validity lookup: ${baseErr.message}`);

  const byServiceId = new Map();
  for (const row of baseRows || []) {
    if (byServiceId.has(row.service_id)) continue;
    byServiceId.set(row.service_id, row);
  }

  const valid = new Set();
  for (const serviceId of candidateServiceIds) {
    const row = byServiceId.get(serviceId);
    if (!row) continue;
    const weekdayOk = (row.days_of_week & weekdayBit) !== 0;
    const inRange =
      (!row.start_date || row.start_date <= dateStr) && (!row.end_date || dateStr <= row.end_date);
    if (weekdayOk && inRange) valid.add(serviceId);
  }

  const { data: exceptions, error: excErr } = await client
    .from("gtfs_service_exceptions")
    .select("service_id, exception_type")
    .eq("feed_version_id", feedVersionId)
    .eq("exception_date", dateStr)
    .in("service_id", candidateServiceIds);
  if (excErr) throw new Error(`gtfs-static exceptions lookup: ${excErr.message}`);
  for (const exc of exceptions || []) {
    if (exc.exception_type === 1) valid.add(exc.service_id);
    else if (exc.exception_type === 2) valid.delete(exc.service_id);
  }

  return valid;
}

// Bounded window (in seconds) to search per candidate date -- avoids pulling
// a full day's schedule for a stop just to find the single next departure.
const LOOKUP_WINDOW_SECONDS = 6 * 3600;

async function candidateDepartures(client, feedVersionId, stopId, minSeconds, maxSeconds) {
  const { data, error } = await client
    .from("gtfs_stop_departures")
    .select("service_id, departure_seconds, trip_id, route_id, route_type")
    .eq("feed_version_id", feedVersionId)
    .eq("stop_id", stopId)
    .gte("departure_seconds", minSeconds)
    .lte("departure_seconds", maxSeconds)
    .order("departure_seconds", { ascending: true });
  if (error) throw new Error(`gtfs-static departures lookup: ${error.message}`);
  return data || [];
}

/**
 * Find the next scheduled departure at stopId after afterTimestamp (a real
 * Date/instant). Checks two candidate service dates -- today and yesterday,
 * by local calendar date -- because a late-night trip (e.g. departing 00:40)
 * is filed under the PREVIOUS date's service_id with departure_seconds >
 * 86400, per GTFS's documented after-midnight convention.
 *
 * Returns { departureAt: Date, gapMinutes: number, tripId, routeId, routeType }
 * or null if nothing resolves (unknown stop_id, no current feed, or
 * genuinely no more service in the lookup window) -- callers must treat null
 * as "no answer available", never as "no more trains tonight".
 */
async function nextDeparture(client, { stopId, afterTimestamp, operator }) {
  const feedVersionId = await getCurrentFeedVersionId(client, operator);
  if (!feedVersionId || !stopId) return null;

  let best = null;
  for (const dayOffset of [0, -1]) {
    const candidateDate = addDays(afterTimestamp, dayOffset);
    const midnight = new Date(candidateDate.getFullYear(), candidateDate.getMonth(), candidateDate.getDate());
    // secondsSinceMidnight is relative to THIS candidate's own midnight, and
    // can be >86400 for the yesterday candidate (afterTimestamp is a full day
    // ahead of it) -- that's correct and exactly what we want to search from,
    // since a departure_seconds value must be >= this to be at or after
    // afterTimestamp. There is no separate hardcoded floor: searching only
    // from the real elapsed time (not a fixed 86400) is what prevents
    // matching yesterday's already-past late-night trips as if they were
    // still upcoming.
    const secondsSinceMidnight = Math.floor((afterTimestamp.getTime() - midnight.getTime()) / 1000);
    if (secondsSinceMidnight > 86400 + LOOKUP_WINDOW_SECONDS) continue;

    // Gather every distinct service_id present in the search window first,
    // so validity is checked only for service_ids that could actually matter.
    const rows = await candidateDepartures(
      client,
      feedVersionId,
      stopId,
      secondsSinceMidnight,
      secondsSinceMidnight + LOOKUP_WINDOW_SECONDS
    );
    if (!rows.length) continue;

    const candidateServiceIds = [...new Set(rows.map((r) => r.service_id))];
    const validIds = await validServiceIdsForDate(client, feedVersionId, midnight, candidateServiceIds);
    const match = rows.find((r) => validIds.has(r.service_id));
    if (!match) continue;

    const departureAt = new Date(midnight.getTime() + match.departure_seconds * 1000);
    if (!best || departureAt < best.departureAt) {
      best = {
        departureAt,
        tripId: match.trip_id,
        routeId: match.route_id,
        routeType: match.route_type,
      };
    }
  }

  if (!best) return null;
  const gapMinutes = Math.round((best.departureAt.getTime() - afterTimestamp.getTime()) / 60000);
  return { ...best, gapMinutes };
}

/**
 * Count scheduled departures at stopId remaining today (from fromTimestamp
 * through the end of the current service day, including after-midnight
 * trips filed under today's service_id). Used to detect "this is the last
 * departure tonight" -- remainingCount <= 1 means the one just cancelled/
 * disrupted (or the one being checked) is the last of the night.
 */
async function remainingDeparturesToday(client, { stopId, fromTimestamp, operator }) {
  const feedVersionId = await getCurrentFeedVersionId(client, operator);
  if (!feedVersionId || !stopId) return null;

  const midnight = new Date(fromTimestamp.getFullYear(), fromTimestamp.getMonth(), fromTimestamp.getDate());
  const secondsSinceMidnight = Math.floor((fromTimestamp.getTime() - midnight.getTime()) / 1000);

  // Today's service day can run well past 24:00:00 for late-night trips --
  // search the full remainder, not just to 86400.
  const rows = await candidateDepartures(client, feedVersionId, stopId, secondsSinceMidnight, 30 * 3600);
  if (!rows.length) return 0;

  const candidateServiceIds = [...new Set(rows.map((r) => r.service_id))];
  const validIds = await validServiceIdsForDate(client, feedVersionId, midnight, candidateServiceIds);
  return rows.filter((r) => validIds.has(r.service_id)).length;
}

module.exports = {
  fetchGtfsZip,
  parseGtfsZip,
  parseGtfsTime,
  daysOfWeekBitmask,
  nextDeparture,
  remainingDeparturesToday,
  buildStopDepartures,
  buildServiceExceptions,
  buildStops,
  ingestGtfsStatic,
};
