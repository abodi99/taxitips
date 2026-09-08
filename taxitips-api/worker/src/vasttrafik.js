/**
 * Västtrafik (Göteborg) traffic situations -> the shared normalized alert shape.
 *
 * Göteborg is Sweden's second city (~1.7M in the region) and a hard gap in the
 * product: Trafiklab's own coverage tables list Västtrafik with static data but
 * NO realtime, so the operator's own portal is the only route to live
 * disruptions there.
 *
 * Unlike SL this needs credentials: OAuth2 client-credentials against
 * ext-api.vasttrafik.se, and the application must be *subscribed* to each API
 * separately in the developer portal. A key pair that is valid but unsubscribed
 * still mints a token -- it just returns 403 `900908 Resource forbidden` on
 * every call, with `scope: default` and no application name in the JWT. That is
 * the signature of a missing subscription, not a bad secret; see
 * fetchVasttrafikSituations' error handling.
 *
 * Credentials come from VASTTRAFIK_CLIENT_ID / VASTTRAFIK_CLIENT_SECRET.
 */

const TOKEN_URL = "https://ext-api.vasttrafik.se/token";
const SITUATIONS_URL = "https://ext-api.vasttrafik.se/ts/v1/traffic-situations";
// `includeGeometry=true` is required: without it every stop area comes back
// with `geometry: null` (verified against the live register -- 0 of 11,181
// carry a coordinate by default, all 11,181 do with the flag).
const STOPAREAS_URL =
  "https://ext-api.vasttrafik.se/geo/v3/StopAreas?includeGeometry=true";

/**
 * Västtrafik publishes coordinates in SWEREF99TM (EPSG:3006), Sweden's
 * national projected grid -- e.g. Brunnsparken is
 * `POINT (319346 6400119)`, metres from a false origin, NOT degrees.
 * Everything downstream (get_smart_alerts' Haversine, flutter_map, the
 * driver's distance) assumes WGS84 degrees, so these must be projected or a
 * Göteborg tip lands in the Gulf of Guinea.
 *
 * Implemented inline rather than pulling in proj4: this is one well-defined
 * transverse-Mercator inverse with fixed parameters (GRS80, central meridian
 * 15°E, scale 0.9996, false easting 500 km), and the formula is stable.
 * Accuracy is sub-metre over Sweden, far tighter than the ~100 m precision
 * that matters for "which street corner".
 */
function sweref99ToWgs84(easting, northing) {
  const axis = 6378137.0; // GRS80 semi-major
  const flat = 1 / 298.257222101; // GRS80 flattening
  const k0 = 0.9996, fe = 500000.0, lambdaZero = (15.0 * Math.PI) / 180;

  const e2 = flat * (2 - flat);
  const n = flat / (2 - flat);
  const aRoof = (axis / (1 + n)) * (1 + (n * n) / 4 + (n * n * n * n) / 64);

  const delta1 = n / 2 - (2 * n * n) / 3 + (37 * n ** 3) / 96 - (n ** 4) / 360;
  const delta2 = (n * n) / 48 + (n ** 3) / 15 - (437 * n ** 4) / 1440;
  const delta3 = (17 * n ** 3) / 480 - (37 * n ** 4) / 840;
  const delta4 = (4397 * n ** 4) / 161280;

  const Astar = e2, Bstar = (5 * e2 ** 2 - e2 ** 3) / 6;
  const Cstar = (104 * e2 ** 3 - 45 * e2 ** 4) / 120;
  const Dstar = (1237 * e2 ** 4) / 1260;

  const xi = (northing - 0) / (k0 * aRoof);
  const eta = (easting - fe) / (k0 * aRoof);

  const xiPrim =
    xi -
    delta1 * Math.sin(2 * xi) * Math.cosh(2 * eta) -
    delta2 * Math.sin(4 * xi) * Math.cosh(4 * eta) -
    delta3 * Math.sin(6 * xi) * Math.cosh(6 * eta) -
    delta4 * Math.sin(8 * xi) * Math.cosh(8 * eta);
  const etaPrim =
    eta -
    delta1 * Math.cos(2 * xi) * Math.sinh(2 * eta) -
    delta2 * Math.cos(4 * xi) * Math.sinh(4 * eta) -
    delta3 * Math.cos(6 * xi) * Math.sinh(6 * eta) -
    delta4 * Math.cos(8 * xi) * Math.sinh(8 * eta);

  const phiStar = Math.asin(Math.sin(xiPrim) / Math.cosh(etaPrim));
  const deltaLambda = Math.atan(Math.sinh(etaPrim) / Math.cos(xiPrim));
  const s = Math.sin(phiStar);
  const phi =
    phiStar +
    s * Math.cos(phiStar) *
      (Astar +
        Bstar * s ** 2 +
        Cstar * s ** 4 +
        Dstar * s ** 6);

  return {
    lat: (phi * 180) / Math.PI,
    lon: ((lambdaZero + deltaLambda) * 180) / Math.PI,
  };
}

/**
 * Token caching mirrors fcmPush.js's getAccessToken: tokens are valid for
 * ~24h, so minting one per 60s poll would be pure waste (and rate-limit
 * bait). Refresh a minute early to avoid using one that expires mid-request.
 */
let cachedToken = null;
let cachedTokenExpiresAt = 0;

async function getAccessToken(clientId, clientSecret) {
  if (cachedToken && Date.now() < cachedTokenExpiresAt - 60_000) return cachedToken;

  const basic = Buffer.from(`${clientId}:${clientSecret}`).toString("base64");
  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: {
      Authorization: `Basic ${basic}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: "grant_type=client_credentials",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`vasttrafik token ${res.status}: ${body.slice(0, 160)}`);
  }
  const json = await res.json();
  if (!json.access_token) throw new Error("vasttrafik token: no access_token in response");
  cachedToken = json.access_token;
  cachedTokenExpiresAt = Date.now() + Number(json.expires_in || 3600) * 1000;
  return cachedToken;
}

async function authedGet(url, clientId, clientSecret) {
  const token = await getAccessToken(clientId, clientSecret);
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}`, "Accept-Encoding": "gzip" },
  });
  if (res.status === 403) {
    // Distinguish "not subscribed" from "bad credentials": a token was minted
    // successfully above, so the key pair is valid -- the application just
    // isn't subscribed to this API in the developer portal. Saying so plainly
    // saves re-testing the secret.
    throw new Error(
      `vasttrafik 403 on ${new URL(url).pathname} -- token minted OK, so the ` +
        `application is likely not subscribed to this API. Subscribe it in ` +
        `developer.vasttrafik.se (Störning v1 / Geografi v3) and retry.`
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`vasttrafik ${res.status}: ${body.slice(0, 160)}`);
  }
  return res.json();
}

/**
 * Västtrafik states start/end times for the situation itself (startTime /
 * endTime), which is a genuine improvement over SL's publish window -- it
 * describes the disruption rather than the message. The same actionability
 * rule still applies though: a months-long planned closure is a fact about
 * the map, not a taxi opportunity.
 */
const MAX_AGE_MS = 24 * 60 * 60 * 1000;
const MAX_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;

function isActionable(situation, now = Date.now()) {
  const from = Date.parse(situation?.startTime || "");
  const to = Date.parse(situation?.endTime || "");
  if (!Number.isFinite(from)) return false;
  if (!Number.isFinite(to)) return false;
  // Must have STARTED. Västtrafik publishes planned engineering work well in
  // advance -- measured: 17 of 87 situations, and 10 of the 19 that passed
  // the age/duration test alone, had not begun yet (night-time track work
  // scheduled up to three weeks out). A tram line that goes down next
  // Saturday is not a taxi opportunity tonight, and showing it as one is the
  // same false-tip failure the SL publish-window filter guards against.
  if (from > now) return false;
  if (now - from > MAX_AGE_MS) return false;
  if (to - from > MAX_WINDOW_MS) return false;
  return to > now;
}

/**
 * Västtrafik's `severity` is the operator's own judgement (documented values
 * include normal/high/veryHigh). Like SL's importance_level it is carried
 * through as evidence, never mapped into demand_score -- it ranks messages
 * for Västtrafik's display surfaces, it does not measure taxi demand.
 */
function normalizeSeverity(severity) {
  // Measured on the live feed: only `normal` (14) and `slight` (73) appear,
  // but the model documents higher levels too. Kept as reported.
  const v = String(severity || "").toLowerCase();
  if (v === "veryhigh" || v === "very_high") return "veryHigh";
  if (v === "high") return "high";
  if (v === "normal") return "normal";
  if (v === "slight") return "slight";
  return null;
}

function modeHintFrom(lines) {
  const modes = new Set(
    (Array.isArray(lines) ? lines : [])
      .map((l) =>
        String(l?.defaultTransportModeCode || l?.transportMode || "").toLowerCase()
      )
      .filter(Boolean)
  );
  if (!modes.size) return null;
  if (modes.has("tram")) return "tram";
  if (modes.has("train") || modes.has("rail")) return "train";
  if (modes.has("bus")) return "bus";
  if (modes.has("ferry") || modes.has("boat")) return "boat";
  return null;
}

function normalizeSituation(situation, stopAreaIndex) {
  const stopPoints = Array.isArray(situation.affectedStopPoints)
    ? situation.affectedStopPoints
    : [];
  // Train/coach situations carry no `affectedLines` at all -- the line sits
  // under `affectedJourneys[].line` instead (verified: every "Öresundståg
  // NNNN är inställt" situation has affectedLines: [] and a populated
  // affectedJourneys). Missing this drops cancelled trains, which are the
  // single most valuable tip type there is, to mode "unknown" and therefore
  // to severity_tier "ignore".
  const journeys = Array.isArray(situation.affectedJourneys)
    ? situation.affectedJourneys
    : [];
  const lines = (
    Array.isArray(situation.affectedLines) && situation.affectedLines.length
      ? situation.affectedLines
      : journeys.map((j) => j?.line).filter(Boolean)
  );

  const areas = [
    ...new Set(
      stopPoints
        .map((s) => s.stopAreaName || s.name)
        .filter(Boolean)
        .concat(stopPoints.map((s) => s.municipalityName).filter(Boolean))
    ),
  ];
  const routes = [
    ...new Set(lines.map((l) => l.designation || l.name).filter(Boolean).map(String)),
  ];
  const stops = [
    ...new Set(stopPoints.map((s) => String(s.stopAreaGid || s.gid)).filter(Boolean)),
  ];

  // Stop points in the situations feed carry NO coordinates -- only a
  // `stopAreaGid`, which joins the geo register (measured: 268/268 of the
  // referenced gids resolve). The register's own coordinates are SWEREF99TM
  // and are projected to WGS84 when the index is built.
  let lat = null;
  let lon = null;
  for (const sp of stopPoints) {
    const hit =
      stopAreaIndex?.get(String(sp.stopAreaGid)) ||
      stopAreaIndex?.get(String(sp.gid));
    if (hit) {
      lat = hit.lat;
      lon = hit.lon;
      break;
    }
  }

  const from = Date.parse(situation.startTime || "");
  const to = Date.parse(situation.endTime || "");

  return {
    id: `vt:${situation.situationNumber}`,
    header: situation.title || "Störning",
    description: situation.description || "",
    cause: null,
    effect: null,
    areas,
    routes,
    stops,
    url: null,
    active_from: Number.isFinite(from) ? from : Date.now(),
    active_to: Number.isFinite(to) ? to : null,
    source: "vt",
    region: "vt",
    lat,
    lon,
    modeHint: modeHintFrom(lines),
    vt: { severity: normalizeSeverity(situation.severity) },
    // Västtrafik states the disruption's own start/end, unlike SL's publish
    // window -- so active_from/active_to above are the real thing.
  };
}

/** gid -> {lat, lon, name} for the Göteborg stop-area register. */
function buildStopAreaIndex(rows) {
  return new Map((rows || []).map((r) => [String(r.gid), r]));
}

async function fetchVasttrafikStopAreas(clientId, clientSecret) {
  const json = await authedGet(STOPAREAS_URL, clientId, clientSecret);
  const areas = json?.stopAreas || (Array.isArray(json) ? json : []);
  // Deduplicated for the same reason as sl.js: an upsert batch may not touch
  // the same key twice.
  const seen = new Set();
  const rows = [];
  for (const a of areas) {
    if (a?.gid && seen.has(String(a.gid))) continue;
    if (a?.gid) seen.add(String(a.gid));
    const g = a?.geometry;
    if (!a?.gid || !g || g.eastingCoordinate == null || g.northingCoordinate == null) continue;
    const { lat, lon } = sweref99ToWgs84(
      Number(g.eastingCoordinate),
      Number(g.northingCoordinate)
    );
    rows.push({ gid: String(a.gid), name: a.name || null, lat, lon });
  }
  return rows;
}

async function fetchVasttrafikSituations({
  clientId = process.env.VASTTRAFIK_CLIENT_ID,
  clientSecret = process.env.VASTTRAFIK_CLIENT_SECRET,
  stopAreaIndex = null,
  now = Date.now(),
} = {}) {
  if (!clientId || !clientSecret) {
    return { alerts: [], source: "vt", skipped: "no credentials" };
  }
  const json = await authedGet(SITUATIONS_URL, clientId, clientSecret);
  const all = Array.isArray(json) ? json : json?.results || [];

  const alerts = [];
  for (const situation of all) {
    if (!isActionable(situation, now)) continue;
    const alert = normalizeSituation(situation, stopAreaIndex);
    if (alert) alerts.push(alert);
  }
  return { alerts, source: "vt", received: all.length, actionable: alerts.length };
}

module.exports = {
  fetchVasttrafikSituations,
  fetchVasttrafikStopAreas,
  buildStopAreaIndex,
  isActionable,
  modeHintFrom,
  normalizeSituation,
  normalizeSeverity,
};
