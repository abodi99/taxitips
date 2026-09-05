/**
 * FCM (Firebase Cloud Messaging) push-send pipeline, HTTP v1 API.
 *
 * Client-side token registration already existed (push_service.dart) --
 * this closes the other half: actually notifying a driver's device when a
 * new high-value opportunity appears, filtered by that device's own
 * notify_prefs (enabled/cities/types, written by NotifyPrefsSheet in the
 * Flutter app).
 *
 * No firebase-admin dependency -- that pulls in gRPC/protobuf for a single
 * HTTP call this worker doesn't need elsewhere. Hand-rolled OAuth2 service-
 * account JWT signing via Node's built-in crypto, matching this project's
 * existing preference for small dependencies over heavy SDKs (see
 * gtfsStatic.js's plain zip/CSV parsing instead of node-gtfs).
 */

const crypto = require("crypto");

const TOKEN_URL = "https://oauth2.googleapis.com/token";
const SCOPE = "https://www.googleapis.com/auth/firebase.messaging";

function base64url(input) {
  return Buffer.from(input)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

// Accepts either raw JSON or base64-encoded JSON for
// FIREBASE_SERVICE_ACCOUNT_JSON -- a service account key's private_key field
// is itself multiline PEM, and some env-var storage layers (Coolify's env
// file included) can mangle a raw multiline JSON secret in ways that are
// hard to diagnose after the fact. Base64 sidesteps that entirely; raw JSON
// is still accepted so a value already stored/pasted as plain JSON keeps
// working.
function loadServiceAccount() {
  const raw = process.env.FIREBASE_SERVICE_ACCOUNT_JSON;
  if (!raw) return null;
  const candidates = [raw];
  try {
    candidates.push(Buffer.from(raw, "base64").toString("utf8"));
  } catch {
    // not valid base64, raw JSON is still tried below
  }
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate);
      if (parsed.client_email && parsed.private_key && parsed.project_id) {
        return parsed;
      }
    } catch {
      // try the next candidate
    }
  }
  return null;
}

// Short-lived in-memory cache -- Google access tokens last ~1h, and this
// worker polls every ~60s, so minting a fresh one every cycle would be both
// wasteful and (at high poll frequency) a real rate-limit risk.
let cachedToken = null;
let cachedTokenExpiresAt = 0;

async function getAccessToken(serviceAccount) {
  if (cachedToken && Date.now() < cachedTokenExpiresAt - 60_000) {
    return cachedToken;
  }

  const now = Math.floor(Date.now() / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const claims = {
    iss: serviceAccount.client_email,
    scope: SCOPE,
    aud: TOKEN_URL,
    iat: now,
    exp: now + 3600,
  };
  const unsigned = `${base64url(JSON.stringify(header))}.${base64url(JSON.stringify(claims))}`;
  const signature = crypto
    .createSign("RSA-SHA256")
    .update(unsigned)
    .sign(serviceAccount.private_key);
  const jwt = `${unsigned}.${base64url(signature)}`;

  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: jwt,
    }),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`fcm oauth token ${res.status}: ${body.slice(0, 200)}`);
  }
  const data = await res.json();
  cachedToken = data.access_token;
  cachedTokenExpiresAt = Date.now() + (data.expires_in || 3600) * 1000;
  return cachedToken;
}

async function sendPush(serviceAccount, accessToken, { token, title, body, opportunityId }) {
  const url = `https://fcm.googleapis.com/v1/projects/${serviceAccount.project_id}/messages:send`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message: {
        token,
        notification: { title, body },
        data: { opportunity_id: opportunityId },
      },
    }),
  });
  if (!res.ok) {
    const errBody = await res.text().catch(() => "");
    return { ok: false, status: res.status, body: errBody.slice(0, 200) };
  }
  return { ok: true };
}

// A notify_prefs type absent from the saved map falls back to the catalog's
// own default rather than reading as opted-out -- matches the same
// unset-means-default semantics the Flutter client's NotifyPrefsSheet uses
// (see api_client.dart's notifyTypeCatalog), so a brand-new device isn't
// silently notified for nothing just because it's never touched a toggle.
const DEFAULT_ON_TYPES = new Set(["line_paused", "vehicle_cancelled", "road_accident_or_closure"]);

function typeEnabled(types, severityTier) {
  if (types && Object.prototype.hasOwnProperty.call(types, severityTier)) {
    return types[severityTier] === true;
  }
  return DEFAULT_ON_TYPES.has(severityTier);
}

// Loose substring match, not exact equality -- notify_prefs.cities holds
// plain city names ("Malmö") a driver picked from the company's watched
// areas, while opportunities.places can carry more specific station names
// ("Malmö C"). Exact equality would silently never match.
//
// The unlocatable case matters more than it looks: ~57% of live Skåne
// opportunities carry no places at all (Trafiklab often sends only stop_id
// numbers, and those don't resolve -- see gtfs_stops' own note about the
// realtime/static ID spaces not overlapping). Treating "we don't know where
// this is" as "doesn't match your cities" silently suppressed the majority
// of real disruptions for any driver who picked cities, which is the exact
// opposite of what picking a city is for. A city filter is meant to remove
// signals known to be elsewhere -- not to hide everything we can't place.
function placesMatchCities(places, cities) {
  if (!cities || !cities.length) return true; // no city filter set = all cities
  if (!places || !places.length) return true; // location unknown -> don't suppress
  return places.some((place) =>
    cities.some(
      (city) =>
        place.toLowerCase().includes(city.toLowerCase()) ||
        city.toLowerCase().includes(place.toLowerCase())
    )
  );
}

// A push interrupts a driver who may be mid-fare or mid-traffic, so the bar
// is deliberately higher than the bar for appearing in the in-app list.
// severity_tier alone isn't enough: "vehicle_cancelled" spans both a
// cancelled train (real stranded passengers) and a single late-evening bus,
// so require the tier to be one worth interrupting for AND the tuned
// demand_score to clear a floor. Without this, ~64% of pushes would be
// "one bus running late" -- exactly the noise scoring.js caps at 25 to keep
// it at the bottom of the list, never something to buzz a phone over.
const NOTIFY_WORTHY_TIERS = new Set([
  "line_paused",
  "vehicle_cancelled",
  "road_accident_or_closure",
]);
const NOTIFY_SCORE_FLOOR = 50;

function isNotifyWorthy(opportunity) {
  if (!NOTIFY_WORTHY_TIERS.has(opportunity.severity_tier)) return false;
  return (opportunity.demand_score || 0) >= NOTIFY_SCORE_FLOOR;
}

// A lock-screen line a driver reads in about one second, at a red light.
// The raw title is often a bare "Inställd"/"Försening" with no context
// (Trafiklab genuinely sends nothing more for many alerts), so lead with
// what the driver actually needs: where, and what kind of disruption.
// Mirrors the Flutter client's displayTitle()/severityTierShortLabels so a
// push and the card it opens don't describe the same thing differently.
const TIER_PUSH_LABEL = {
  line_paused: "Hela linjen stoppad",
  vehicle_cancelled: "Avgång inställd",
  road_accident_or_closure: "Olycka/avstängning",
};
const MODE_PUSH_LABEL = { train: "Tåg", bus: "Buss", road: "Väg" };

function pushTitle(opportunity) {
  const place = (opportunity.places || [])[0];
  const tier = TIER_PUSH_LABEL[opportunity.severity_tier];
  const mode = MODE_PUSH_LABEL[opportunity.mode];
  const what = tier || opportunity.title || "Ny taxisignal";
  const prefix = place || mode;
  return prefix ? `${prefix}: ${what}` : what;
}

/**
 * Notify devices for one newly-notify-worthy opportunity. Never throws --
 * callers (pollOnce) must not have a push failure break the main ingestion
 * loop, mirroring the existing per-source error isolation for SMHI/
 * Trafikverket fetches.
 */
async function notifyOpportunity(client, serviceAccount, accessToken, opportunity) {
  const { data: devices, error } = await client
    .from("devices")
    .select("id, push_token, notify_prefs")
    .not("push_token", "is", null);
  if (error) {
    console.error("[fcm] device lookup failed", error.message);
    return { sent: 0 };
  }

  let sent = 0;
  for (const device of devices || []) {
    const prefs = device.notify_prefs || {};
    if (prefs.enabled === false) continue;
    if (!typeEnabled(prefs.types, opportunity.severity_tier)) continue;
    if (!placesMatchCities(opportunity.places, prefs.cities)) continue;

    const result = await sendPush(serviceAccount, accessToken, {
      token: device.push_token,
      title: pushTitle(opportunity),
      body: opportunity.summary || "",
      opportunityId: opportunity.id,
    });
    if (result.ok) {
      sent += 1;
    } else if (result.status === 404 || result.status === 400) {
      // Token no longer valid (app uninstalled, token rotated without a
      // registerPushToken call landing yet) -- clear it so this device
      // stops being queried every cycle for a send that will never work.
      await client.from("devices").update({ push_token: null }).eq("id", device.id);
    } else {
      console.error(`[fcm] send failed for device ${device.id}: ${result.status} ${result.body}`);
    }
  }
  return { sent };
}

/**
 * Entry point called once per poll cycle from pollOnce(). Finds opportunities
 * that just became notify-worthy (severity_tier warrants it, not yet
 * notified, still active) and sends pushes, marking notified_at so the same
 * opportunity is never notified twice while it stays live.
 */
async function runPushCycle(client) {
  const serviceAccount = loadServiceAccount();
  if (!serviceAccount) {
    return { skipped: true, reason: "no FIREBASE_SERVICE_ACCOUNT_JSON configured" };
  }

  const { data: rows, error } = await client
    .from("opportunities")
    .select("id, title, summary, severity_tier, mode, places, demand_score")
    .is("notified_at", null)
    .gte("demand_score", NOTIFY_SCORE_FLOOR)
    .in("severity_tier", [...NOTIFY_WORTHY_TIERS])
    .gt("end_time", new Date().toISOString());
  if (error) {
    console.error("[fcm] candidate lookup failed", error.message);
    return { sent: 0, error: error.message };
  }
  // Belt-and-braces: the query already encodes the gate, but re-checking in
  // JS keeps isNotifyWorthy the single readable source of truth if either
  // side is ever tuned independently.
  const candidates = (rows || []).filter(isNotifyWorthy);
  if (!candidates.length) return { sent: 0 };

  let accessToken;
  try {
    accessToken = await getAccessToken(serviceAccount);
  } catch (err) {
    console.error("[fcm] auth failed", err.message || err);
    return { sent: 0, error: "auth_failed" };
  }

  let totalSent = 0;
  for (const opportunity of candidates) {
    try {
      const { sent } = await notifyOpportunity(client, serviceAccount, accessToken, opportunity);
      totalSent += sent;
    } catch (err) {
      // Never let one opportunity's failure block the rest, or the caller's
      // poll cycle.
      console.error(`[fcm] notify failed for ${opportunity.id}`, err.message || err);
      continue;
    }
    await client
      .from("opportunities")
      .update({ notified_at: new Date().toISOString() })
      .eq("id", opportunity.id);
  }
  return { sent: totalSent, candidates: candidates.length };
}

module.exports = {
  loadServiceAccount,
  typeEnabled,
  placesMatchCities,
  isNotifyWorthy,
  pushTitle,
  runPushCycle,
  NOTIFY_SCORE_FLOOR,
};
