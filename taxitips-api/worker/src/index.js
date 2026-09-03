const express = require("express");
const { createClient } = require("@supabase/supabase-js");
const { pollOnce } = require("./poller");
const { ingestGtfsStatic } = require("./gtfsStatic");

const PORT = Number(process.env.PORT || 8787);
const INTERVAL = Number(process.env.POLL_INTERVAL_MS || 60_000);
const GTFS_OPERATOR = process.env.GTFS_STATIC_OPERATOR || "skane";
const GTFS_REFRESH_INTERVAL = Number(process.env.GTFS_STATIC_REFRESH_INTERVAL_MS || 24 * 60 * 60 * 1000);
// Trafiklab's GTFS Regional static quota is tiny (Bronze 50/month, Silver
// 250/month) -- fetching it on every container start (e.g. repeated Coolify
// redeploys in a day) would burn a meaningful chunk of a month's quota for no
// benefit, since the feed itself only changes once a day anyway. Skip the
// startup fetch if a version was already pulled recently.
const GTFS_STARTUP_SKIP_IF_FRESHER_THAN_MS = 20 * 60 * 60 * 1000;

const app = express();

app.get("/health", (_req, res) => {
  res.json({ ok: true, service: "taxitips-worker" });
});

// Stripe webhooks are handled by the taxitips-api/supabase/functions/stripe-webhook
// edge function, not here -- this worker is ingestion/scoring only. Having two live
// webhook handlers was a real bug (only one can be canonical, and they used different
// linking strategies -- client_reference_id here vs. metadata.company_id there); the
// edge function version has fuller Stripe event coverage and is the one Stripe's
// dashboard should point at.

function sb() {
  return createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

async function loop() {
  try {
    await pollOnce();
  } catch (err) {
    console.error("[poll] failed", err.message || err);
  }
}

// Runs independently of the 60s realtime poll loop -- a slow zip download/
// parse must never delay pollOnce()'s own setInterval timer, and a failure
// here should never take down alert/road ingestion.
async function gtfsRefreshLoop({ skipIfFresh } = {}) {
  const client = sb();
  try {
    if (skipIfFresh) {
      const { data, error } = await client
        .from("gtfs_feed_versions")
        .select("fetched_at")
        .eq("operator", GTFS_OPERATOR)
        .order("fetched_at", { ascending: false })
        .limit(1)
        .maybeSingle();
      if (!error && data?.fetched_at) {
        const ageMs = Date.now() - new Date(data.fetched_at).getTime();
        if (ageMs < GTFS_STARTUP_SKIP_IF_FRESHER_THAN_MS) {
          console.log(`[gtfs-static] skipping startup fetch, current version is ${Math.round(ageMs / 60000)}min old`);
          return;
        }
      }
    }
    const result = await ingestGtfsStatic(client, process.env.TRAFIKLAB_API_KEY, GTFS_OPERATOR);
    if (!result.skipped) {
      console.log(
        `[gtfs-static] ingested ${GTFS_OPERATOR}: stops=${result.stopCount} trips=${result.tripCount} departures=${result.departureCount} exceptions=${result.exceptionCount}`
      );
    }
  } catch (err) {
    console.error("[gtfs-static] failed", err.message || err);
  }
}

app.listen(PORT, () => {
  console.log(`[taxitips-worker] listening on :${PORT}`);
  loop();
  setInterval(loop, INTERVAL);
  gtfsRefreshLoop({ skipIfFresh: true });
  setInterval(() => gtfsRefreshLoop({ skipIfFresh: false }), GTFS_REFRESH_INTERVAL);
});
