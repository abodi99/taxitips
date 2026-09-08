/**
 * Standalone read-only viewer for the TaxiTips data pipeline.
 *
 * Deliberately separate from taxitips-api/taxitips-app: this is a thinking
 * tool for understanding what data exists and how it's transformed, not part
 * of the product. No auth, localhost only, read-only queries.
 *
 * Run:  node server.js     (reads worker/.env.local for Supabase creds)
 */

const http = require("http");
const fs = require("fs");
const path = require("path");
const { createClient } = require("@supabase/supabase-js");

const PORT = Number(process.env.PORT || 4000);

// Credentials come from a local .env you control -- never committed, never
// passed on the command line. Falls back to the worker's .env.local, which
// points at a local Supabase rather than production.
function loadEnvFile(p) {
  if (!fs.existsSync(p)) return {};
  const out = {};
  for (const line of fs.readFileSync(p, "utf8").split("\n")) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m) out[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
  return out;
}
const env = {
  ...loadEnvFile(path.join(__dirname, "..", "taxitips-api", "worker", ".env.local")),
  ...loadEnvFile(path.join(__dirname, ".env")), // takes precedence
  ...process.env,
};

// Point at production by default -- the whole purpose is seeing REAL data.
const SUPABASE_URL = env.VIZ_SUPABASE_URL || "https://api.taxitips.se";
const SERVICE_KEY = env.VIZ_SERVICE_KEY || env.SUPABASE_SERVICE_ROLE_KEY;

const sb = SERVICE_KEY
  ? createClient(SUPABASE_URL, SERVICE_KEY, {
      auth: { persistSession: false, autoRefreshToken: false },
    })
  : null;

async function collect() {
  if (!sb) {
    return { error: "No Supabase credentials found. Set VIZ_SERVICE_KEY or SUPABASE_SERVICE_ROLE_KEY." };
  }

  const nowIso = new Date().toISOString();

  // Fail loudly on a bad/mismatched key. Supabase answers count queries with
  // an empty result rather than an error when auth fails, so without this
  // check the page would render a confident-looking dashboard full of
  // zeroes -- worse than an error, because it looks like real data.
  const probe = await sb.from("opportunities").select("id").limit(1);
  if (probe.error) {
    return {
      error:
        `Kunde inte läsa från ${SUPABASE_URL}: ${probe.error.message}. ` +
        `Kontrollera VIZ_SERVICE_KEY i .env (hämtas från Coolify -> taxitips-worker -> Environment Variables).`,
    };
  }

  const [sourceEvents, opportunities, stops, departures] = await Promise.all([
    sb.from("source_events").select("source", { count: "exact", head: true }),
    sb.from("opportunities").select("id", { count: "exact", head: true }),
    sb.from("gtfs_stops").select("id", { count: "exact", head: true }),
    sb.from("gtfs_stop_departures").select("id", { count: "exact", head: true }),
  ]);

  // Per-source counts (small number of sources, so individual counts are cheap).
  const bySource = {};
  for (const src of ["trafiklab", "trafikverket", "smhi"]) {
    const { count } = await sb
      .from("source_events")
      .select("id", { count: "exact", head: true })
      .eq("source", src);
    bySource[src] = count || 0;
  }

  // Active opportunities, full rows -- this is the interesting set.
  const { data: active } = await sb
    .from("opportunities")
    .select(
      "id,title,summary,severity_tier,mode,confidence,demand_score,reasons,rule_id,lat,lon,start_time,end_time,places,source_event_ids,region"
    )
    .gt("end_time", nowIso)
    .order("demand_score", { ascending: false })
    .limit(500);

  // Per-region rollup: this is the multi-market picture, and the whole point
  // of adding SL. Counts are computed from the `active` rows we already have
  // rather than as extra round-trips.
  const byRegion = {};
  for (const o of active || []) {
    const region = o.region || "skane";
    const r = (byRegion[region] ||= {
      total: 0, scorable: 0, pushWorthy: 0, withCoords: 0, tiers: {}, modes: {},
    });
    r.total += 1;
    if (o.severity_tier !== "ignore" && (o.demand_score || 0) > 0) r.scorable += 1;
    if ((o.demand_score || 0) >= 50) r.pushWorthy += 1;
    if (o.lat != null) r.withCoords += 1;
    r.tiers[o.severity_tier] = (r.tiers[o.severity_tier] || 0) + 1;
    if (o.mode) r.modes[o.mode] = (r.modes[o.mode] || 0) + 1;
  }

  // What a driver actually sees, per market -- the real RPC, not a proxy for
  // it. This is the only query here that proves the end-to-end behaviour,
  // including the region fence on placeless opportunities.
  const driverViews = {};
  const probes = {
    "Malmö": [55.605, 13.0038],
    "Stockholm": [59.3196, 18.0725],
    "Göteborg": [57.7089, 11.9746],
  };
  const deviceToken = env.VIZ_DEVICE_TOKEN || null;
  if (deviceToken) {
    for (const [city, [lat, lon]] of Object.entries(probes)) {
      const { data, error } = await sb.rpc("get_smart_alerts", {
        p_lat: lat, p_lon: lon, p_device_token: deviceToken,
      });
      if (error) { driverViews[city] = { error: error.message }; continue; }
      const rows = Array.isArray(data) ? data : [];
      driverViews[city] = {
        total: rows.length,
        top: rows
          .slice()
          .sort((a, b) => (b.worth_it_score || 0) - (a.worth_it_score || 0))
          .slice(0, 5)
          .map((r) => ({
            title: r.title, mode: r.mode, tier: r.severity_tier,
            score: r.demand_score, worthIt: r.worth_it_score,
            km: r.distance_km == null ? null : Math.round(r.distance_km * 10) / 10,
          })),
        foreignModes: rows.filter((r) => ["tram", "metro"].includes(r.mode)).length,
      };
    }
  }

  // One fully traced example: opportunity + the raw source event behind it.
  let traced = null;
  const example = (active || []).find(
    (o) => o.severity_tier !== "ignore" && (o.source_event_ids || []).length
  );
  if (example) {
    const { data: se } = await sb
      .from("source_events")
      .select("source,external_id,mode,raw,active_from,active_to,lat,lon")
      .eq("id", example.source_event_ids[0])
      .maybeSingle();
    traced = { opportunity: example, sourceEvent: se || null };
  }

  // Same lookup, but for every active opportunity -- this is what lets the
  // map popup show "which source, and the actual raw response" per point,
  // not just the one traced example. One batched query keyed by the first
  // source_event_id on each opportunity (an opportunity can span several;
  // the first is the one that anchored the tip).
  const firstSeId = (o) => (o.source_event_ids || [])[0] || null;
  const seIds = [...new Set((active || []).map(firstSeId).filter(Boolean))];
  if (seIds.length) {
    const { data: seRows } = await sb
      .from("source_events")
      .select("id,source,external_id,raw,active_from,active_to")
      .in("id", seIds);
    const byId = new Map((seRows || []).map((r) => [r.id, r]));
    for (const o of active || []) {
      const id = firstSeId(o);
      o.sourceEvent = id ? byId.get(id) || null : null;
    }
  }

  return {
    generatedAt: nowIso,
    supabaseUrl: SUPABASE_URL,
    totals: {
      sourceEvents: sourceEvents.count || 0,
      opportunities: opportunities.count || 0,
      gtfsStops: stops.count || 0,
      gtfsDepartures: departures.count || 0,
      bySource,
    },
    active: active || [],
    byRegion,
    driverViews,
    traced,
  };
}

// Peka mot Django (VIZ_BACKEND=http://127.0.0.1:8000) i stället för
// Supabase. Django äger tågpipelinen sedan Fas 2 och serverar samma
// JSON-form på /api/pipeline.
const BACKEND = env.VIZ_BACKEND || null;

// Kandidatkälla, inte ansluten till pipelinen: Trafikverkets OperativeEvent
// (namespace ols.open v1.0) -- orsaksnivån (banarbete/tågfel/anläggningsfel)
// bakom en inställd avgång, till skillnad från TrainAnnouncement som bara
// visar SYMPTOMET (den enskilda avgången). Hämtas direkt från Trafikverket,
// förbi source_events, så den här panelen bevisar ingenting om vad som
// faktiskt är ansluten till poängsättningen -- bara vad källan innehåller.
const TRAFIKVERKET_API_KEY = env.TRAFIKVERKET_API_KEY || null;
const TV_URL = "https://api.trafikinfo.trafikverket.se/v2/data.json";

async function fetchOperativeEvents() {
  if (!TRAFIKVERKET_API_KEY || TRAFIKVERKET_API_KEY === "mock") {
    return { error: "Ingen TRAFIKVERKET_API_KEY hittad -- kan inte hämta kandidatkällan live." };
  }
  const xml = `<REQUEST><LOGIN authenticationkey="${TRAFIKVERKET_API_KEY}"/>` +
    `<QUERY objecttype="OperativeEvent" namespace="ols.open" schemaversion="1.0" limit="500">` +
    `<FILTER><EQ name="EventState" value="1"/></FILTER>` +
    `</QUERY></REQUEST>`;

  const res = await fetch(TV_URL, {
    method: "POST",
    headers: { "Content-Type": "text/xml", "Accept-Encoding": "gzip" },
    body: xml,
  });
  const json = await res.json().catch(() => null);
  const block = json?.RESPONSE?.RESULT?.[0];
  if (!res.ok || block?.ERROR) {
    return { error: `Trafikverket ${res.status}: ${JSON.stringify(block?.ERROR || {}).slice(0, 200)}` };
  }

  const events = block?.OperativeEvent || [];
  const now = Date.now();

  // EventState=1 betyder "inte avslutad", inte "pågår nu" -- samma fälla
  // som SL:s publish-fönster (se avsnitt 6 i huvudvyn). Räkna hur ofta det
  // slår fel: StartDateTime redan passerat säger inget om NU, men om
  // TrafficImpact-fönstret redan stängt är eventet med säkerhet inte
  // längre aktivt trots EventState=1.
  const byType = {};
  let roadBridged = 0, withResumption = 0, withRelated = 0;
  let startInPast = 0, impactWindowClosed = 0;
  for (const e of events) {
    const code = e.EventType?.EventTypeCode || "?";
    const desc = e.EventType?.Description || "(okänd typ)";
    (byType[code] ??= { desc, n: 0 }).n++;
    if (e.EventTrafficType === 2) roadBridged++;
    if (e.RailRoadTimeForServiceResumption) withResumption++;
    if ((e.RelatedEvent || []).length) withRelated++;
    if (Date.parse(e.StartDateTime) <= now) startInPast++;
    const impacts = e.TrafficImpact || [];
    if (impacts.length && impacts.every((i) => Date.parse(i.EndDateTime) < now)) impactWindowClosed++;
  }

  return {
    fetchedAt: new Date(now).toISOString(),
    total: events.length,
    byType: Object.entries(byType)
      .sort((a, b) => b[1].n - a[1].n)
      .map(([code, v]) => ({ code, desc: v.desc, n: v.n })),
    roadBridged,
    withResumption,
    withRelated,
    startInPast,
    impactWindowClosed,
    sample: events.find((e) => e.EventType?.EventTypeCode === "16") || events[0] || null,
  };
}

const server = http.createServer(async (req, res) => {
  if (req.url === "/api/pipeline" && BACKEND) {
    try {
      const upstream = await fetch(`${BACKEND}/api/pipeline`);
      const body = await upstream.text();
      res.writeHead(upstream.status, {
        "Content-Type": "application/json; charset=utf-8",
      });
      return res.end(body);
    } catch (err) {
      res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
      return res.end(JSON.stringify({
        error: `Nådde inte backend på ${BACKEND}: ${err.message}. ` +
               `Kör Django med: manage.py runserver 8000`,
      }));
    }
  }

  if (req.url === "/api/pipeline") {
    try {
      const data = await collect();
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify(data));
    } catch (err) {
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: String(err.message || err) }));
    }
    return;
  }

  // Analysdokumenten, serverade som de ligger på disk. Vitlistade med
  // avsikt: det här är en läsvy utan auth, och en fri sökväg hade gjort
  // den till en filbläddrare över hela repot.
  const DOCS = {
    "api-field-inventory": "api-field-inventory.md",
    "transit-compensation-rules": "transit-compensation-rules.md",
    "data-sources": "data-sources.md",
  };
  const docMatch = req.url.match(/^\/api\/doc\/([a-z0-9-]+)$/);
  if (docMatch) {
    const file = DOCS[docMatch[1]];
    if (!file) {
      res.writeHead(404, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ error: `Okänt dokument: ${docMatch[1]}` }));
    }
    try {
      const md = fs.readFileSync(path.join(__dirname, "..", "docs", file), "utf8");
      res.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" });
      return res.end(md);
    } catch (err) {
      res.writeHead(404, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ error: `Kunde inte läsa docs/${file}: ${err.message}` }));
    }
  }

  if (req.url === "/api/operative-events") {
    try {
      const data = await fetchOperativeEvents();
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify(data));
    } catch (err) {
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: String(err.message || err) }));
    }
    return;
  }

  const file = path.join(__dirname, "index.html");
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(fs.readFileSync(file));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`\n  TaxiTips pipeline viewer\n  http://localhost:${PORT}\n`);
  console.log(`  Reading from: ${SUPABASE_URL}`);
  console.log(`  Credentials:  ${SERVICE_KEY ? "found" : "MISSING -- set VIZ_SERVICE_KEY"}\n`);
});
