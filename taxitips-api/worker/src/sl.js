/**
 * SL (Stockholm) deviations -> the shared normalized alert shape.
 *
 * SL publishes its own realtime data openly: no API key, no subscription,
 * no quota tier. That is why Stockholm ships before anything that needs a
 * Trafiklab subscription -- it is the single largest market (2.4M people)
 * and it costs nothing but the adapter below.
 *
 * Docs ask for at most one request per minute, which the 60s poll loop
 * already satisfies. https://www.trafiklab.se/api/trafiklab-apis/sl/
 */

const DEVIATIONS_URL = "https://deviations.integration.sl.se/v1/messages";
// `expand=true` is load-bearing, not an optimisation: deviations reference
// stop_areas, and a plain /sites response is keyed by SITE id -- a different
// id space (measured: only 14 of 104 referenced stop_area ids collide with a
// site id, and those collisions are coincidental, not meaningful). The
// expanded response carries each site's stop_areas[], which bridges the two
// spaces for 104/104 of the referenced ids.
const SITES_URL = "https://transport.integration.sl.se/v1/sites?expand=true";

/**
 * SL's `publish` window is NOT the disruption's duration -- it is how long
 * the *message* stays published, and the two differ by years.
 *
 * Measured against the live feed (158 deviations): 102 have a publish window
 * longer than 30 days, and 34 were first published over 90 days ago. One
 * real example is a roadworks notice published 2024-01-03 running to
 * 2026-12-31. Only 25 of 158 are both recent (<24h) and short (<7d).
 *
 * Feeding the other 133 into the pipeline would show a driver "Indragna
 * hållplatser — Södergården" as a live opportunity two years after it became
 * true. That is exactly the kind of false tip that destroys trust in the
 * product, and it is the same trap `end_time` turned out to be on the
 * Trafiklab side (see smart_alert_card.dart's comment on "Pågår i 7 timmar").
 *
 * So we filter on actionability, not on publication. A deviation is a taxi
 * opportunity only while it is BOTH recent and bounded: someone is standing
 * at that stop right now, unable to get home. A permanent stop closure is a
 * fact about the map, not an opportunity.
 */
const MAX_AGE_MS = 24 * 60 * 60 * 1000; // published within the last day
const MAX_WINDOW_MS = 7 * 24 * 60 * 60 * 1000; // and not an open-ended notice

function isActionable(deviation, now = Date.now()) {
  const from = Date.parse(deviation?.publish?.from || "");
  const upto = Date.parse(deviation?.publish?.upto || "");
  if (!Number.isFinite(from)) return false;
  // Not yet started. SL's publish.from is always in the past on live data, so
  // this never fires today -- but the Västtrafik feed proved the failure mode
  // is real (10 of 19 there were future-dated engineering works), and a
  // filter that only works by luck is not a filter.
  if (from > now) return false;
  if (now - from > MAX_AGE_MS) return false;
  // A missing `upto` is treated as open-ended (measured: 0/158 lack it, but
  // absence must not silently mean "short").
  if (!Number.isFinite(upto)) return false;
  if (upto - from > MAX_WINDOW_MS) return false;
  return upto > now; // already over = not an opportunity
}

/**
 * Swedish text, mirroring trafiklab.js's pickTranslation. Measured: 158/158
 * variants are `sv`, but the field is an array by design so don't assume.
 */
function pickVariant(variants) {
  const list = Array.isArray(variants) ? variants : [];
  return (
    list.find((v) => String(v?.language || "").toLowerCase().startsWith("sv")) ||
    list[0] ||
    null
  );
}

/**
 * SL's own transport_mode is structurally correct data, unlike mode.js's
 * keyword matching on Swedish prose. METRO/TRAM are reported as-is here and
 * folded into the "train" tiering branch by scoring.js -- a stopped metro
 * line strands people exactly like a stopped train does.
 */
function modeHintFrom(lines) {
  const modes = new Set(
    (Array.isArray(lines) ? lines : [])
      .map((l) => String(l?.transport_mode || "").toUpperCase())
      .filter(Boolean)
  );
  if (!modes.size) return null;
  if (modes.has("METRO")) return "metro";
  if (modes.has("TRAIN")) return "train";
  if (modes.has("TRAM")) return "tram";
  if (modes.has("BUS")) return "bus";
  return null;
}

function normalizeDeviation(deviation, siteIndex) {
  const variant = pickVariant(deviation.message_variants);
  if (!variant) return null;

  const stopAreas = Array.isArray(deviation.scope?.stop_areas)
    ? deviation.scope.stop_areas
    : [];
  const lines = Array.isArray(deviation.scope?.lines) ? deviation.scope.lines : [];

  const areas = stopAreas.map((s) => s.name).filter(Boolean);
  const routes = lines.map((l) => l.designation).filter(Boolean).map(String);
  const stops = stopAreas.map((s) => String(s.id)).filter(Boolean);

  // Coordinates come from the free sites endpoint, keyed by stop_area id.
  //
  // Measured reality, and a limit worth stating plainly: the deviations that
  // are ACTIONABLE (recent + bounded) reference lines, not stop areas --
  // 19/19 in a live sample named zero stop_areas. The ones that do name a
  // stop area are overwhelmingly the permanent notices this adapter filters
  // out. So in practice this lookup resolves rarely today, and most
  // Stockholm alerts carry lat/lon = null.
  //
  // That is not fatal: get_smart_alerts already handles coordinate-less
  // opportunities (migration 20260905000001 exists precisely for this), the
  // city filter falls back to place names, and fcmPush's placesMatchCities
  // treats unknown-location as "do not suppress". A line-level disruption
  // genuinely has no single location -- inventing one (say, the line's first
  // stop) would send drivers to a specific wrong corner of Stockholm with
  // false precision. Null is the honest answer.
  //
  // Closing this properly needs a line -> stops mapping, which SL's open API
  // does not expose (checked: /lines returns no stop list, /stop-points
  // carries no line reference). GTFS Sweden 3 static's routes+stop_times
  // does, which is one more reason that subscription is the top request.
  let lat = null;
  let lon = null;
  for (const area of stopAreas) {
    const site = siteIndex?.get(String(area.id));
    if (site) {
      lat = site.lat;
      lon = site.lon;
      break;
    }
  }

  const from = Date.parse(deviation.publish?.from || "");
  const upto = Date.parse(deviation.publish?.upto || "");

  return {
    id: `sl:${deviation.deviation_case_id}`,
    header: variant.header || "Störning",
    description: variant.details || "",
    // SL has no GTFS cause/effect enums. Left null rather than invented --
    // taxiRelevance.js reads these defensively and the Swedish text carries
    // the signal anyway (same conclusion as the Trafiklab path).
    cause: null,
    effect: null,
    areas,
    routes,
    stops,
    url: variant.weblink || null,
    active_from: Number.isFinite(from) ? from : Date.now(),
    active_to: Number.isFinite(upto) ? upto : null,
    source: "sl",
    region: "sl",
    lat,
    lon,
    modeHint: modeHintFrom(lines),
    // SL's editorial priority. Deliberately NOT mapped into demand_score --
    // it ranks messages for SL's own display surfaces, it does not measure
    // taxi demand. scoring.js uses it only to lift confidence.
    sl: {
      importanceLevel: Number(deviation.priority?.importance_level) || null,
      scopeAlias: variant.scope_alias || null,
    },
  };
}

/**
 * The site register: 6512 stops with coordinates, no key. Fetched on the
 * daily refresh loop rather than per poll -- it changes rarely and it is a
 * 330KB response.
 */
async function fetchSlSites() {
  const res = await fetch(SITES_URL, { headers: { "Accept-Encoding": "gzip" } });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`sl-sites ${res.status}: ${body.slice(0, 160)}`);
  }
  const sites = await res.json();
  // Deduplicated by stop_area_id: the register genuinely lists the same stop
  // area under more than one site (a station and its bus terminal reference
  // each other), and Postgres rejects an upsert batch that touches the same
  // key twice -- "ON CONFLICT DO UPDATE command cannot affect row a second
  // time". First writer wins; they carry the same coordinate anyway.
  const seen = new Set();
  const rows = [];
  for (const site of Array.isArray(sites) ? sites : []) {
    if (!site || site.lat == null || site.lon == null) continue;
    // One row per stop_area, because that is the id deviations actually
    // reference. A site with several stop areas (a station plus its bus
    // terminal) yields several rows pointing at the same coordinate, which
    // is correct -- they are the same place to a driver.
    const areas = Array.isArray(site.stop_areas) && site.stop_areas.length
      ? site.stop_areas
      : [site.id];
    for (const area of areas) {
      const stopAreaId = String(area?.id ?? area);
      if (!stopAreaId || seen.has(stopAreaId)) continue;
      seen.add(stopAreaId);
      rows.push({
        stop_area_id: stopAreaId,
        site_id: String(site.id),
        name: site.name || null,
        lat: Number(site.lat),
        lon: Number(site.lon),
      });
    }
  }
  return rows;
}

/** stop_area id -> {lat, lon, name}, the shape normalizeDeviation expects. */
function buildSiteIndex(rows) {
  return new Map((rows || []).map((r) => [String(r.stop_area_id), r]));
}

async function fetchSlDeviations({ siteIndex = null, now = Date.now() } = {}) {
  const res = await fetch(DEVIATIONS_URL, {
    headers: { "Accept-Encoding": "gzip" },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`sl-deviations ${res.status}: ${body.slice(0, 160)}`);
  }
  const raw = await res.json();
  const all = Array.isArray(raw) ? raw : [];

  const alerts = [];
  for (const deviation of all) {
    if (!isActionable(deviation, now)) continue;
    const alert = normalizeDeviation(deviation, siteIndex);
    if (alert) alerts.push(alert);
  }

  return { alerts, source: "sl", received: all.length, actionable: alerts.length };
}

module.exports = {
  fetchSlDeviations,
  fetchSlSites,
  buildSiteIndex,
  isActionable,
  pickVariant,
  modeHintFrom,
  normalizeDeviation,
};
