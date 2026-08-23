const { createClient } = require("@supabase/supabase-js");
const { fetchSkaneAlerts } = require("./trafiklab");
const { fetchRoadSituations } = require("./trafikverket");
const { enrichAlert, isTaxiNotifyWorthy } = require("./taxiRelevance");

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
  return {
    id: String(alert.id),
    kind: alert.kind || alert.type || "traffic",
    level: taxi.level || alert.level || "medium",
    title: alert.title || alert.summary || "Tips",
    summary: alert.summary || alert.description || null,
    lat: alert.lat ?? taxi.lat ?? null,
    lon: alert.lon ?? taxi.lon ?? null,
    places: taxi.places || alert.places || [],
    payload: alert,
    starts_at: alert.startsAt ? new Date(alert.startsAt).toISOString() : null,
    ends_at: alert.endsAt ? new Date(alert.endsAt).toISOString() : null,
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
