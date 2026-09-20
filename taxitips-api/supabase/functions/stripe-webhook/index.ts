import { createClient } from 'npm:@supabase/supabase-js@2';
import Stripe from 'npm:stripe@16';

const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY')!);

// Deno har ingen synkron HMAC. constructEvent kastade "SubtleCryptoProvider cannot
// be used in a synchronous context" för VARJE händelse, även korrekt signerade --
// provat lokalt i edge-runtime v1.74.3 2026-09-13 -- så ingen händelse tillämpades.
// Verifieringen görs därför asynkront med Web Crypto.
const cryptoProvider = Stripe.createSubtleCryptoProvider();

// En rad som stått i 'processing' längre än så räknas som ett avbrutet försök.
const STALE_PROCESSING_MS = 5 * 60 * 1000;

Deno.serve(async (req) => {
  const signature = req.headers.get('stripe-signature') ?? '';
  const payload = await req.text();

  let event: Stripe.Event;
  try {
    event = await stripe.webhooks.constructEventAsync(
      payload,
      signature,
      Deno.env.get('STRIPE_WEBHOOK_SECRET')!,
      undefined,
      cryptoProvider,
    );
  } catch (e) {
    return new Response(`Webhook Error: ${(e as Error).message}`, { status: 400 });
  }

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  );

  // Idempotens: stripe_event_id är unik. En ny händelse får en rad i 'processing'.
  // Finns raden redan betyder 'ok' att den är klar, och en färsk 'processing' att
  // ett annat försök pågår. 'error' eller en gammal 'processing' betyder att förra
  // försöket inte gick igenom, och då tas händelsen om. Tidigare svarade varje
  // omleverans 200 "duplicate", även efter ett fel -- och händelsen tillämpades aldrig.
  const { error: insertError } = await supabase.from('processed_webhook_events').insert({
    stripe_event_id: event.id,
    event_type: event.type,
    status: 'processing',
  });
  if (insertError) {
    const { data: existing } = await supabase
      .from('processed_webhook_events')
      .select('status, processed_at')
      .eq('stripe_event_id', event.id)
      .maybeSingle();
    if (!existing || existing.status === 'ok') {
      return json({ received: true, duplicate: true }, 200);
    }
    const stale = Date.now() - new Date(existing.processed_at).getTime() > STALE_PROCESSING_MS;
    if (existing.status === 'processing' && !stale) {
      // Inte 200: går det pågående försöket fel ska Stripe försöka igen.
      return json({ received: false, in_progress: true }, 409);
    }
    // Ta över raden bara om ingen annan hunnit före.
    const { data: claimed } = await supabase
      .from('processed_webhook_events')
      .update({ status: 'processing', processed_at: new Date().toISOString(), error: null })
      .eq('stripe_event_id', event.id)
      .eq('status', existing.status)
      .select('stripe_event_id');
    if (!claimed || claimed.length === 0) {
      return json({ received: false, in_progress: true }, 409);
    }
  }

  const object = event.data.object as Record<string, unknown> & {
    metadata?: Record<string, string>;
  };
  const eventAt = new Date(event.created * 1000).toISOString();

  try {
    if (
      event.type === 'checkout.session.completed' ||
      event.type === 'checkout.session.async_payment_succeeded'
    ) {
      const companyId = object.metadata?.company_id;
      const subscriptionId = object.subscription as string | undefined;
      // Kort är betalt direkt. Fördröjda betalsätt är 'unpaid' tills
      // async_payment_succeeded; tidigare aktiverades bolaget ändå.
      const paid = object.payment_status === 'paid' || object.payment_status === 'no_payment_required';
      if (companyId && subscriptionId && paid) {
        await check(
          supabase
            .from('companies')
            .update({
              stripe_subscription_id: subscriptionId,
              subscription_status: 'active',
              status: 'active',
            })
            .eq('id', companyId),
        );
      }
    } else if (
      event.type === 'customer.subscription.updated' ||
      event.type === 'customer.subscription.deleted'
    ) {
      const customerId = object.customer as string;
      const status =
        event.type === 'customer.subscription.deleted'
          ? 'canceled'
          : (object.status as string);
      const items = object.items as { data?: Array<{ quantity?: number }> };
      const quantity = items?.data?.[0]?.quantity;

      const { data: company } = await check(
        supabase
          .from('companies')
          .select('id, last_subscription_event_at')
          .eq('stripe_customer_id', customerId)
          .maybeSingle(),
      );

      // Stripe lovar ingen ordning. En äldre händelse som kommer efter en nyare
      // (past_due efter active) får inte skriva över den.
      const newer =
        !company?.last_subscription_event_at ||
        new Date(company.last_subscription_event_at).getTime() <= new Date(eventAt).getTime();

      if (company && newer) {
        const mapped =
          status === 'active'
            ? 'active'
            : status === 'past_due'
              ? 'past_due'
              : status === 'canceled' || status === 'unpaid' || status === 'incomplete_expired'
                ? 'canceled'
                : 'inactive';
        await check(
          supabase
            .from('companies')
            .update({
              subscription_status: status,
              status: mapped,
              last_subscription_event_at: eventAt,
              ...(quantity ? { seats: quantity } : {}),
            })
            .eq('id', company.id),
        );
      }
    }

    await check(
      supabase
        .from('processed_webhook_events')
        .update({ status: 'ok' })
        .eq('stripe_event_id', event.id),
    );
    return json({ received: true }, 200);
  } catch (e) {
    await supabase
      .from('processed_webhook_events')
      .update({ status: 'error', error: String((e as Error)?.message ?? e) })
      .eq('stripe_event_id', event.id);
    return json({ error: 'handler_failed' }, 500);
  }
});

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

// supabase-js kastar inte vid databasfel utan returnerar { error }. Utan den här
// kontrollen markerades en misslyckad uppdatering som 'ok'.
async function check<T extends { error: unknown }>(query: PromiseLike<T>): Promise<T> {
  const result = await query;
  if (result.error) throw result.error;
  return result;
}
