const express = require("express");
const { createClient } = require("@supabase/supabase-js");
const { pollOnce } = require("./poller");

const PORT = Number(process.env.PORT || 8787);
const INTERVAL = Number(process.env.POLL_INTERVAL_MS || 60_000);

function sb() {
  return createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

const app = express();

app.get("/health", (_req, res) => {
  res.json({ ok: true, service: "taxitips-worker" });
});

// Stripe needs raw body
app.post(
  "/webhooks/stripe",
  express.raw({ type: "application/json" }),
  async (req, res) => {
    const secret = process.env.STRIPE_WEBHOOK_SECRET;
    const key = process.env.STRIPE_SECRET_KEY;
    if (!secret || !key) {
      return res.status(503).json({ error: "stripe_not_configured" });
    }
    // eslint-disable-next-line global-require
    const Stripe = require("stripe");
    const stripe = new Stripe(key);
    let event;
    try {
      event = stripe.webhooks.constructEvent(
        req.body,
        req.headers["stripe-signature"],
        secret
      );
    } catch (err) {
      console.error("[stripe] signature", err.message);
      return res.status(400).send(`Webhook Error: ${err.message}`);
    }

    const client = sb();
    const { error: dupErr } = await client.from("processed_webhook_events").insert({
      stripe_event_id: event.id,
      event_type: event.type,
      status: "processing",
    });
    if (dupErr) {
      // already processed
      return res.json({ received: true, duplicate: true });
    }

    try {
      await handleStripeEvent(client, event);
      await client
        .from("processed_webhook_events")
        .update({ status: "ok" })
        .eq("stripe_event_id", event.id);
      res.json({ received: true });
    } catch (err) {
      console.error("[stripe] handler", err);
      await client
        .from("processed_webhook_events")
        .update({ status: "error", error: String(err.message || err) })
        .eq("stripe_event_id", event.id);
      res.status(500).json({ error: "handler_failed" });
    }
  }
);

app.use(express.json());

async function handleStripeEvent(client, event) {
  const obj = event.data?.object || {};
  if (event.type.startsWith("customer.subscription.")) {
    const customerId = obj.customer;
    if (!customerId) return;
    const status = obj.status || "none";
    const { data: companies } = await client
      .from("companies")
      .select("id, billing_account_id")
      .eq("stripe_customer_id", customerId);
    for (const c of companies || []) {
      await client
        .from("companies")
        .update({
          status: status === "active" || status === "trialing" ? "active" : status,
          stripe_subscription_id: obj.id || null,
        })
        .eq("id", c.id);
      if (c.billing_account_id) {
        await client.from("subscriptions").upsert(
          {
            billing_account_id: c.billing_account_id,
            stripe_subscription_id: obj.id,
            status,
            quantity: obj.items?.data?.[0]?.quantity || 1,
            raw_stripe_json: obj,
            updated_at: new Date().toISOString(),
          },
          { onConflict: "stripe_subscription_id" }
        );
      }
    }
  }
}

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
