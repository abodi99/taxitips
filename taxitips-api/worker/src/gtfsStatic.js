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

module.exports = {
  fetchGtfsZip,
  parseGtfsZip,
  parseGtfsTime,
  daysOfWeekBitmask,
  buildStopDepartures,
  buildServiceExceptions,
  ingestGtfsStatic,
};
