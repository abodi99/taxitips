import { createClient } from 'npm:@supabase/supabase-js@2';
import Stripe from 'npm:stripe@16';

const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY')!);
const PRICE_ID = Deno.env.get('STRIPE_PRICE_ID') ?? 'price_1U7cJrP67HXLcerWkJ3vKy7I';

const cors = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers':
    'authorization, x-client-info, apikey, content-type',
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, 'Content-Type': 'application/json' },
  });

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  try {
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
      { auth: { persistSession: false } },
    );

    const auth = req.headers.get('Authorization') ?? '';
    const {
      data: { user },
      error: authErr,
    } = await supabase.auth.getUser(auth.replace('Bearer ', ''));
    if (authErr || !user) return json({ error: 'Unauthorized' }, 401);

    const { seats } = await req.json();
    const quantity = Math.max(1, Number(seats) || 1);

    const { data: member } = await supabase
      .from('company_members')
      .select('company_id')
      .eq('user_id', user.id)
      .eq('status', 'active')
      .eq('role', 'company_owner')
      .single();
    if (!member) return json({ error: 'Inget bolag' }, 400);

    const { data: company } = await supabase
      .from('companies')
      .select('stripe_subscription_id')
      .eq('id', member.company_id)
      .single();

    const { count: deviceCount } = await supabase
      .from('devices')
      .select('id', { count: 'exact', head: true })
      .eq('company_id', member.company_id);
    if ((deviceCount ?? 0) > quantity) {
      return json(
        { error: `Ta bort ${deviceCount! - quantity} telefon först.` },
        400,
      );
    }

    await supabase
      .from('companies')
      .update({ seats: quantity })
      .eq('id', member.company_id);

    const subscriptionId = company?.stripe_subscription_id;
    if (!subscriptionId) {
      return json({ quantity, synced: false });
    }

    const subscription = await stripe.subscriptions.retrieve(subscriptionId);
    const itemId = subscription.items.data[0]?.id;
    if (itemId) {
      await stripe.subscriptions.update(subscriptionId, {
        items: [{ id: itemId, price: PRICE_ID, quantity }],
      });
    }

    return json({ quantity, synced: true });
  } catch (e) {
    return json({ error: e.message }, 500);
  }
});
