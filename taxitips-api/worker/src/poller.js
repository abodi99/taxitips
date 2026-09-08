const crypto = require("crypto");
const { createClient } = require("@supabase/supabase-js");
const { fetchSkaneAlerts } = require("./trafiklab");
const { fetchRoadSituations } = require("./trafikverket");
const { fetchRailDisruptions } = require("./trafikverketRail");
const { fetchSlDeviations, buildSiteIndex } = require("./sl");
const {
  fetchVasttrafikSituations,
  buildStopAreaIndex: buildVtIndex,
} = require("./vasttrafik");
const { enrichAlert, isTaxiNotifyWorthy, calculateDemandSignal, isRoadAlert } = require("./taxiRelevance");
const { classifySeverity } = require("./scoring");
const { fetchRegionWeather, nearestWeather, isAdverseWeather, describeWeather } = require("./smhi");
const { resolvePlaceCoords } = require("./hubs");
const { runPushCycle } = require("./fcmPush");

// Many Trafiklab transit alerts carry no lat/lon at all -- only a station/place name
// in the free text. Without a fallback, get_smart_alerts' distance math on a null
// coordinate silently zeroes worth_it_score, hiding even a 100-point cancelled train
// line from every driver. Resolve a known station/city name to real coordinates
// before falling back to null.
function resolveCoords(alert, taxi) {
  const lat = alert.lat ?? taxi.lat ?? null;
  const lon = alert.lon ?? taxi.lon ?? null;
  if (lat != null && lon != null) return { lat, lon };

  const placeNames = [...(taxi.hubs || []), ...(taxi.places || []), ...(alert.places || [])];
  for (const name of placeNames) {
    const geo = resolvePlaceCoords(name);
    if (geo) return { lat: geo.lat, lon: geo.lon };
  }

  // Last resort: the operators' own stop registers, matched by name in the
  // alert text. hubs.js only knows stations and city centres, but the alerts
  // that matter most name a LOCAL stop -- "Elektravägen", "Hässelby strand",
  // "Käppala" -- which no city list can ever cover. Measured on national
  // data: this lifts coordinate coverage from ~12% to ~59%.
  //
  // Longest match wins so "Hässelby strand" beats "Hässelby", and names
  // shorter than 5 characters are skipped -- short ones ("Ås", "Bro") match
  // inside unrelated words and would place a tip in the wrong town, which is
  // worse than having no coordinate at all.
  const gaz = stopNameGazetteer;
  if (gaz && gaz.size) {
    const text = `${alert.header || ""} ${alert.description || ""}`.toLowerCase();
    let best = null;
    for (const [name, coord] of gaz) {
      if (text.includes(name) && (!best || name.length > best.name.length)) {
        best = { name, coord };
      }
    }
    if (best) return { lat: best.coord.lat, lon: best.coord.lon };
  }

  return { lat: null, lon: null };
}

// name -> {lat, lon}, loaded once per process from sl_sites + vt_stop_areas.
// Held in memory because resolveCoords runs per alert (hundreds per cycle)
// and the registers change on a daily cadence at most.
let stopNameGazetteer = null;

async function loadStopNameGazetteer(client) {
  if (stopNameGazetteer) return stopNameGazetteer;
  const gaz = new Map();
  try {
    const [sl, vt] = await Promise.all([
      client.from("sl_sites").select("name, lat, lon"),
      client.from("vt_stop_areas").select("name, lat, lon"),
    ]);
    for (const rows of [sl.data || [], vt.data || []]) {
      for (const r of rows) {
        if (!r.name || r.name.length < 5) continue;
        const key = r.name.toLowerCase();
        if (!gaz.has(key)) gaz.set(key, { lat: r.lat, lon: r.lon });
      }
    }
  } catch (err) {
    console.error("[gazetteer] load failed", err.message);
  }
  stopNameGazetteer = gaz;
  if (!gaz.size) console.warn("[gazetteer] empty -- stop-name geocoding disabled");
  return gaz;
}

// public.alerts.id is uuid in production, but source alerts have stable text ids
// (e.g. "tv:mock-e22") used to make repeated polls upsert the same row instead of
// duplicating it. Derive a deterministic UUID (v5-style, namespace + name hash) from
// the stable source id so upserts stay idempotent across poll cycles.
const ALERT_ID_NAMESPACE = "6f0a7b1e-4b1f-4b3a-9c0e-2a1d7c9f5e2a";
function deterministicUuid(name) {
  const namespaceBytes = Buffer.from(ALERT_ID_NAMESPACE.replace(/-/g, ""), "hex");
  const hash = crypto.createHash("sha1").update(namespaceBytes).update(String(name)).digest();
  const bytes = Buffer.from(hash.subarray(0, 16));
  bytes[6] = (bytes[6] & 0x0f) | 0x50; // version 5
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function requireEnv(name) {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env ${name}`);
  return v;
}

function sb() {
  return createClient(
    requireEnv("SUPABASE_URL"),
    requireEnv("SUPABASE_SERVICE_ROLE_KEY"),
    { auth: { persistSession: false, autoRefreshToken: false } }
  );
}

function mapAlert(alert) {
  const taxi = alert.taxi || {};
  const signal = calculateDemandSignal(alert);
  const start_time = alert.active_from ? new Date(alert.active_from).toISOString() : null;
  // Sources (esp. Trafikverket road situations) often omit an end time for ongoing
  // events (e.g. an accident with no announced clearance time). get_smart_alerts filters
  // on end_time > now(), so a null end_time makes the alert permanently invisible to
  // drivers -- fall back to a 3h window from start (or now) instead of leaving it null.
  // The next poll cycle naturally refreshes/removes it once the source resolves the event.
  const FALLBACK_DURATION_MS = 3 * 60 * 60 * 1000;
  const end_time = alert.active_to
    ? new Date(alert.active_to).toISOString()
    : new Date((alert.active_from || Date.now()) + FALLBACK_DURATION_MS).toISOString();

  const coords = resolveCoords(alert, taxi);

  return {
    id: deterministicUuid(String(alert.id)),
    kind: isRoadAlert(alert) ? "road" : "transit",
    level: taxi.level || alert.level || "medium",
    title: alert.title || alert.header || alert.summary || "Tips",
    summary: alert.summary || alert.description || null,
    lat: coords.lat,
    lon: coords.lon,
    places: taxi.places || alert.places || [],
    payload: alert,
    start_time: start_time,
    end_time: end_time,
    h3_index: signal.h3_index,
    demand_score: signal.demand_score,
    reasons: signal.reasons,
    updated_at: new Date().toISOString(),
  };
}

async function upsertAlerts(client, alerts) {
  if (!alerts.length) return { upserted: 0 };
  const rows = alerts.map(mapAlert);
  const { error } = await client.from("alerts").upsert(rows, { onConflict: "id" });
  if (error) throw error;
  return { upserted: rows.length };
}

// source_events: the raw fact, untouched. Kept as latest-known-state (upsert on
// external_id) rather than an append-only log -- see architecture notes; this is
// enough to answer "which source event" for explainability without unbounded growth.
function mapSourceEvent(alert) {
  const start_time = alert.active_from ? new Date(alert.active_from).toISOString() : null;
  const end_time = alert.active_to ? new Date(alert.active_to).toISOString() : null;
  const coords = resolveCoords(alert, alert.taxi || {});
  return {
    // Each fetcher declares its own source. The road/transit ternary is kept
    // only as a fallback for alerts constructed before that field existed
    // (mocks, tests) -- it cannot distinguish a third source, and silently
    // labelling SL data "trafiklab" is a trust bug, not a cosmetic one:
    // get_opportunity_detail shows this string to the driver, so a Stockholm
    // tip would claim a Skåne feed produced it.
    source: alert.source || (isRoadAlert(alert) ? "trafikverket" : "trafiklab"),
    external_id: String(alert.id),
    active_from: start_time,
    active_to: end_time,
    raw: alert,
    lat: coords.lat,
    lon: coords.lon,
  };
}

async function upsertSourceEvents(client, alerts) {
  if (!alerts.length) return { upserted: 0 };
  const rows = alerts.map(mapSourceEvent);
  const { data, error } = await client
    .from("source_events")
    .upsert(rows, { onConflict: "external_id" })
    .select("id, external_id");
  if (error) throw error;
  return { upserted: rows.length, rows: data || [] };
}

// Flat bonus applied when adverse weather (real rain/snow/high wind/thunder) coincides
// with a transit or road disruption at the same location -- a cancelled train in a
// downpour strands people who now also can't comfortably wait/walk for an alternative,
// which is a stronger taxi-demand signal than the same cancellation on a clear day.
// Deliberately modest and additive (not a multiplier) so it nudges rather than
// dominates the underlying disruption severity classifySeverity already computed.
const WEATHER_BONUS = 12;

// opportunities: the derived, scored thing shown to a driver. Reuses the same
// demand/h3 signal and taxi-relevance scoring as mapAlert, plus the new mode-aware
// severity tier and explicit provenance (source_event_ids/rule_id/confidence).
//
// weatherIdByPoint maps region point name -> that weather source_event's real DB
// id, so that when the bonus applies we can cite it in source_event_ids the same
// way the underlying disruption's own source_event is cited -- get_opportunity_detail
// joins source_events strictly via that array, so a weather event stored but not
// referenced there would never actually surface in the explain panel.
function mapOpportunity(alert, sourceEventId, regionWeather, weatherIdByPoint) {
  const taxi = alert.taxi || {};
  const signal = calculateDemandSignal(alert);
  const severity = classifySeverity(alert, taxi);
  const start_time = alert.active_from ? new Date(alert.active_from).toISOString() : null;
  const FALLBACK_DURATION_MS = 3 * 60 * 60 * 1000;
  const end_time = alert.active_to
    ? new Date(alert.active_to).toISOString()
    : new Date((alert.active_from || Date.now()) + FALLBACK_DURATION_MS).toISOString();

  const coords = resolveCoords(alert, taxi);

  // Only apply the weather bonus to disruptions that are already genuinely
  // relevant (not "ignore" tier) -- weather shouldn't be what turns a
  // non-signal into a signal on its own, only sharpen a real one.
  const weather = severity.severityTier !== "ignore" ? nearestWeather(coords.lat, coords.lon, regionWeather || []) : null;
  const weatherAdverse = isAdverseWeather(weather);
  const weatherReason = weatherAdverse ? describeWeather(weather) : null;
  const score = weatherAdverse ? Math.min(100, severity.score + WEATHER_BONUS) : severity.score;
  const reasons = weatherReason ? [...signal.reasons, `väder: ${weatherReason}`] : signal.reasons;

  const sourceEventIds = sourceEventId ? [sourceEventId] : [];
  const weatherId = weatherAdverse ? weatherIdByPoint?.get(weather.point) : null;
  if (weatherId) sourceEventIds.push(weatherId);

  return {
    external_id: String(alert.id),
    kind: isRoadAlert(alert) ? "road" : "transit",
    mode: severity.mode,
    severity_tier: severity.severityTier,
    level: taxi.level || alert.level || "medium",
    title: alert.title || alert.header || alert.summary || "Tips",
    summary: alert.summary || alert.description || null,
    lat: coords.lat,
    lon: coords.lon,
    h3_index: signal.h3_index,
    places: taxi.places || alert.places || [],
    start_time,
    end_time,
    // classifySeverity's score IS the score -- it caps signal.demand_score down
    // for severity tiers where the raw text-severity heuristic (plus the flat
    // Last Train Risk boost) overstates real driver value, e.g. a single
    // cancelled departure with a stated alternative (vehicle_cancelled, capped
    // at 55) shouldn't reach the same score as a genuine whole-line stop
    // (line_paused, floor of 85). Using signal.demand_score directly here was
    // a bug -- classifySeverity's cap was computed but never actually stored.
    // The weather bonus (see WEATHER_BONUS) is applied on top of that capped
    // score, not the raw uncapped one.
    demand_score: score,
    confidence: severity.confidence,
    reasons,
    // Phase 1 stub: derived from the existing short reason tag until Phase 2's
    // richer rule_id naming (e.g. "transit.train.line_paused") is wired through.
    rule_id: `${severity.mode || "unknown"}.${severity.severityTier}`,
    // Which market this belongs to. Load-bearing for opportunities with no
    // coordinate: get_smart_alerts can only distance-fence located ones, so
    // without a region a placeless Stockholm tip reached a Malmö driver at
    // full score. Falls back to the id prefix each source already uses.
    region:
      alert.region ||
      (String(alert.id || "").includes(":")
        ? String(alert.id).split(":")[0]
        : "skane"),
    source_event_ids: sourceEventIds,
    computed_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

async function upsertOpportunities(client, alerts, sourceEventIdByExternalId, regionWeather, weatherIdByPoint) {
  if (!alerts.length) return { upserted: 0 };
  const rows = alerts.map((a) =>
    mapOpportunity(a, sourceEventIdByExternalId.get(String(a.id)), regionWeather, weatherIdByPoint)
  );
  const { error } = await client.from("opportunities").upsert(rows, { onConflict: "external_id" });
  if (error) throw error;
  return { upserted: rows.length };
}

// weather is its own source_event too (source='smhi'), one row per region point,
// upserted on external_id so it doesn't grow unbounded -- same pattern as the
// transit/road source_events, and gives the explain panel a real citation
// ("SMHI, Malmö, 21:00") instead of just a bare "väder: regn" reason string.
// Returns the point-name -> db-id map mapOpportunity needs to actually cite a
// weather event in source_event_ids when its bonus applied.
async function upsertWeatherSourceEvents(client, regionWeather) {
  if (!regionWeather.length) return { upserted: 0, idByPoint: new Map() };
  const rows = regionWeather.map((w) => ({
    source: "smhi",
    external_id: `smhi:${w.point}`,
    mode: "weather",
    active_from: w.observedAt,
    active_to: null,
    raw: w,
    lat: w.lat,
    lon: w.lon,
  }));
  const { data, error } = await client
    .from("source_events")
    .upsert(rows, { onConflict: "external_id" })
    .select("id, external_id");
  if (error) throw error;
  const idByPoint = new Map(
    (data || []).map((r) => [r.external_id.replace(/^smhi:/, ""), r.id])
  );
  return { upserted: rows.length, idByPoint };
}

/**
 * stop_area -> coordinate lookup, read from Postgres and cached in memory for
 * the process. ~7200 rows that change on a daily refresh cadence, so re-reading
 * them every 60s poll would be pure waste. A failed read yields an empty index
 * rather than throwing: alerts then carry lat/lon = null, which the pipeline
 * already handles, instead of losing the whole cycle.
 */
let slSiteIndexCache = null;
let slSiteIndexLoadedAt = 0;
const SL_SITE_CACHE_MS = 60 * 60 * 1000;

async function getSlSiteIndex(client) {
  if (slSiteIndexCache && Date.now() - slSiteIndexLoadedAt < SL_SITE_CACHE_MS) {
    return slSiteIndexCache;
  }
  try {
    const { data, error } = await client
      .from("sl_sites")
      .select("stop_area_id, site_id, name, lat, lon");
    if (error) throw new Error(error.message);
    slSiteIndexCache = buildSiteIndex(data || []);
    slSiteIndexLoadedAt = Date.now();
    if (!slSiteIndexCache.size) {
      console.warn("[sl] site index is empty -- Stockholm alerts will have no coordinates");
    }
  } catch (err) {
    console.error("[sl] site index load failed", err.message);
    return slSiteIndexCache || new Map();
  }
  return slSiteIndexCache;
}

/** Same caching rationale as getSlSiteIndex -- ~11k rows, daily refresh. */
let vtIndexCache = null;
let vtIndexLoadedAt = 0;

async function getVtStopAreaIndex(client) {
  if (vtIndexCache && Date.now() - vtIndexLoadedAt < SL_SITE_CACHE_MS) return vtIndexCache;
  try {
    const { data, error } = await client
      .from("vt_stop_areas")
      .select("gid, name, lat, lon");
    if (error) throw new Error(error.message);
    vtIndexCache = buildVtIndex(data || []);
    vtIndexLoadedAt = Date.now();
    if (!vtIndexCache.size) {
      console.warn("[vasttrafik] stop-area index empty -- Göteborg alerts will have no coordinates");
    }
  } catch (err) {
    console.error("[vasttrafik] stop-area index load failed", err.message);
    return vtIndexCache || new Map();
  }
  return vtIndexCache;
}

async function pollOnce() {
  const client = sb();
  await loadStopNameGazetteer(client);
  const apiKey = process.env.TRAFIKLAB_API_KEY || "mock";
  const roadKey = process.env.TRAFIKVERKET_API_KEY || "";

  let transit = { alerts: [] };
  try {
    transit = await fetchSkaneAlerts(apiKey);
  } catch (err) {
    console.error("[trafiklab]", err.message);
  }
  let road = { alerts: [] };
  if (roadKey) {
    try {
      road = await fetchRoadSituations(roadKey);
    } catch (err) {
      console.error("[trafikverket]", err.message);
    }
  } else if (apiKey === "mock" || process.env.TRAFIKVERKET_MOCK === "1") {
    road = await fetchRoadSituations("mock");
  }

  // Stockholm. SL publishes openly -- no key, no quota -- so this is gated
  // only by a feature flag, off by default until verified against a live
  // client (CLAUDE.md: no feature ships half-visible). Its own try/catch
  // means an SL outage can never affect Skåne ingestion.
  let sl = { alerts: [] };
  if (process.env.SL_ENABLED === "1") {
    try {
      sl = await fetchSlDeviations({ siteIndex: await getSlSiteIndex(client) });
    } catch (err) {
      console.error("[sl]", err.message);
    }
  }

  // Göteborg. Needs OAuth credentials (unlike SL), so it is gated on those
  // being present as well as the flag -- a missing key is a silent no-op,
  // not an error every cycle.
  let vt = { alerts: [] };
  if (process.env.VT_ENABLED === "1" && process.env.VASTTRAFIK_CLIENT_ID) {
    try {
      vt = await fetchVasttrafikSituations({
        stopAreaIndex: await getVtStopAreaIndex(client),
      });
    } catch (err) {
      console.error("[vasttrafik]", err.message);
    }
  }

  // National rail. Trafiklab publishes realtime per regional authority, and
  // the long-distance train operators (SJ, Öresundståg, Mälartåg, Norrtåg,
  // MTR, VR) publish nothing there at all -- so before this, a cancelled
  // train only ever appeared in the three regions that run their own trains.
  // Trafikverket owns the network and covers the whole country in one query.
  let rail = { alerts: [] };
  if (roadKey) {
    try {
      rail = await fetchRailDisruptions({ apiKey: roadKey });
    } catch (err) {
      console.error("[trafikverket-rail]", err.message);
    }
  }

  // Fetched once per poll cycle (not per-alert -- see smhi.js), and failures here
  // never block the traffic-disruption pipeline: weather only sharpens an
  // existing signal, a driver still gets the disruption itself without it.
  let regionWeather = [];
  try {
    regionWeather = await fetchRegionWeather();
  } catch (err) {
    console.error("[smhi]", err.message);
  }

  const enriched = [];
  let notifyWorthy = 0;
  let skipped = 0;
  for (const raw of [
    ...(transit.alerts || []),
    ...(sl.alerts || []),
    ...(vt.alerts || []),
    ...(rail.alerts || []),
    ...(road.alerts || []),
  ]) {
    // Per-alert isolation: every fetch above is already wrapped, but this
    // loop was not -- so one unexpected payload shape (a missing text
    // variant, a malformed date) threw straight out of pollOnce and lost the
    // entire cycle: no opportunities written, no push sent, for every source
    // at once. One source's bad row must not silence the others.
    try {
      const alert = enrichAlert(raw);
      if (isTaxiNotifyWorthy(alert) || alert.taxi?.level === "medium") {
        notifyWorthy += 1;
      }
      enriched.push(alert);
    } catch (err) {
      skipped += 1;
      console.error("[enrich]", raw?.id, err.message);
    }
  }

  const result = await upsertAlerts(client, enriched);

  // Dual-write during the source_events/opportunities cutover: alerts stays
  // authoritative for reads until get_smart_alerts is verified against
  // opportunities and cut over (see architecture notes). Failures here are
  // logged but never block the existing alerts write path above.
  try {
    const seResult = await upsertSourceEvents(client, enriched);
    const sourceEventIdByExternalId = new Map(
      (seResult.rows || []).map((r) => [r.external_id, r.id])
    );
    const { idByPoint: weatherIdByPoint } = await upsertWeatherSourceEvents(client, regionWeather);
    await upsertOpportunities(client, enriched, sourceEventIdByExternalId, regionWeather, weatherIdByPoint);
  } catch (err) {
    console.error("[opportunities] dual-write failed", err.message || err);
  }

  // Push-send is a separate, non-critical step -- a failure here (bad
  // credential, FCM outage, a single device's send erroring) must never take
  // down alert/road ingestion. runPushCycle itself never throws, but wrap it
  // anyway to match the isolation pattern already used for every other
  // optional enrichment step above.
  let pushResult = { sent: 0 };
  try {
    pushResult = await runPushCycle(client);
  } catch (err) {
    console.error("[fcm] push cycle failed", err.message || err);
  }

  console.log(
    `[poll] upserted=${result.upserted} notifyWorthy=${notifyWorthy} transit=${(transit.alerts || []).length} sl=${(sl.alerts || []).length} vt=${(vt.alerts || []).length} rail=${(rail.alerts || []).length} road=${(road.alerts || []).length} weather=${regionWeather.length} pushed=${pushResult.sent || 0}${skipped ? ` skipped=${skipped}` : ""}`
  );
  return result;
}

module.exports = {
  pollOnce,
  upsertAlerts,
  mapAlert,
  mapSourceEvent,
  upsertSourceEvents,
  mapOpportunity,
  upsertOpportunities,
};
