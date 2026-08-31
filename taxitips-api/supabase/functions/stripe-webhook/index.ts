import { createClient } from 'npm:@supabase/supabase-js@2';
import Stripe from 'npm:stripe@16';

const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY')!);

Deno.serve(async (req) => {
  const signature = req.headers.get('stripe-signature') ?? '';
  const payload = await req.text();

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(
      payload,
      signature,
      Deno.env.get('STRIPE_WEBHOOK_SECRET')!,
    );
  } catch (e) {
    return new Response(`Webhook Error: ${e.message}`, { status: 400 });
  }

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  );

  // Idempotency: Stripe can and does redeliver events. Insert-then-check against
  // processed_webhook_events (unique on stripe_event_id) before doing anything else --
  // a duplicate delivery hits the unique violation and is treated as already handled.
  const { error: dupErr } = await supabase.from('processed_webhook_events').insert({
    stripe_event_id: event.id,
    event_type: event.type,
    status: 'processing',
  });
  if (dupErr) {
    return new Response(JSON.stringify({ received: true, duplicate: true }), { status: 200 });
  }

  const object = event.data.object as Record<string, unknown> & {
    metadata?: Record<string, string>;
  };

  try {
    if (event.type === 'checkout.session.completed') {
      const companyId = object.metadata?.company_id;
      const subscriptionId = object.subscription as string | undefined;
      if (companyId && subscriptionId) {
        await supabase
          .from('companies')
          .update({
            stripe_subscription_id: subscriptionId,
            subscription_status: 'active',
            status: 'active',
          })
          .eq('id', companyId);
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

      const { data: company } = await supabase
        .from('companies')
        .select('id')
        .eq('stripe_customer_id', customerId)
        .single();

      if (company) {
        const mapped =
          status === 'active'
            ? 'active'
            : status === 'past_due'
              ? 'past_due'
              : status === 'canceled' || status === 'unpaid' || status === 'incomplete_expired'
                ? 'canceled'
                : 'inactive';
        await supabase
          .from('companies')
          .update({
            subscription_status: status,
            status: mapped,
            ...(quantity ? { seats: quantity } : {}),
          })
          .eq('id', company.id);
      }
    }

    await supabase
      .from('processed_webhook_events')
      .update({ status: 'ok' })
      .eq('stripe_event_id', event.id);

    return new Response(JSON.stringify({ received: true }), { status: 200 });
  } catch (e) {
    await supabase
      .from('processed_webhook_events')
      .update({ status: 'error', error: String((e as Error)?.message ?? e) })
      .eq('stripe_event_id', event.id);
    return new Response(JSON.stringify({ error: 'handler_failed' }), { status: 500 });
  }
});
