const crypto = require("crypto");
const { createClient } = require("@supabase/supabase-js");
const { fetchSkaneAlerts } = require("./trafiklab");
const { fetchRoadSituations } = require("./trafikverket");
const { enrichAlert, isTaxiNotifyWorthy, calculateDemandSignal } = require("./taxiRelevance");

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

  return {
    id: deterministicUuid(String(alert.id)),
    kind: alert.kind || alert.type || "traffic",
    level: taxi.level || alert.level || "medium",
    title: alert.title || alert.header || alert.summary || "Tips",
    summary: alert.summary || alert.description || null,
    lat: alert.lat ?? taxi.lat ?? null,
    lon: alert.lon ?? taxi.lon ?? null,
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

async function pollOnce() {
  const client = sb();
  const apiKey = process.env.TRAFIKLAB_API_KEY || "mock";
  const roadKey = process.env.TRAFIKVERKET_API_KEY || "";

  const transit = await fetchSkaneAlerts(apiKey);
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

  const enriched = [];
  let notifyWorthy = 0;
  for (const raw of [...(transit.alerts || []), ...(road.alerts || [])]) {
    const alert = enrichAlert(raw);
    if (isTaxiNotifyWorthy(alert) || alert.taxi?.level === "medium") {
      notifyWorthy += 1;
    }
    enriched.push(alert);
  }

  const result = await upsertAlerts(client, enriched);
  console.log(
    `[poll] upserted=${result.upserted} notifyWorthy=${notifyWorthy} transit=${(transit.alerts || []).length} road=${(road.alerts || []).length}`
  );
  return result;
}

module.exports = { pollOnce, upsertAlerts, mapAlert };
