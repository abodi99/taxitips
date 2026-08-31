const express = require("express");
const { pollOnce } = require("./poller");

const PORT = Number(process.env.PORT || 8787);
const INTERVAL = Number(process.env.POLL_INTERVAL_MS || 60_000);

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

async function loop() {
  try {
    await pollOnce();
  } catch (err) {
    console.error("[poll] failed", err.message || err);
  }
}

app.listen(PORT, () => {
  console.log(`[taxitips-worker] listening on :${PORT}`);
  loop();
  setInterval(loop, INTERVAL);
});
