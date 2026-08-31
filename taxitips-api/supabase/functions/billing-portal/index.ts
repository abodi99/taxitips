import { createClient } from 'npm:@supabase/supabase-js@2';
import Stripe from 'npm:stripe@16';

const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY')!);
const PRICE_ID = Deno.env.get('STRIPE_PRICE_ID') ?? 'price_1U7cJrP67HXLcerWkJ3vKy7I';
const SITE_URL = Deno.env.get('SITE_URL') ?? 'https://taxitips.se';

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

    const { data: member } = await supabase
      .from('company_members')
      .select('company_id')
      .eq('user_id', user.id)
      .eq('status', 'active')
      .single();
    if (!member) return json({ error: 'Inget bolag' }, 400);

    const { data: company } = await supabase
      .from('companies')
      .select('stripe_customer_id, stripe_subscription_id, seats')
      .eq('id', member.company_id)
      .single();

    // Not yet subscribed → hand the caller a checkout URL instead.
    if (!company?.stripe_customer_id || !company?.stripe_subscription_id) {
      let customerId = company?.stripe_customer_id;
      if (!customerId) {
        const customer = await stripe.customers.create({
          email: user.email,
          metadata: { company_id: member.company_id, user_id: user.id },
        });
        customerId = customer.id;
        await supabase
          .from('companies')
          .update({ stripe_customer_id: customerId })
          .eq('id', member.company_id);
      }
      const session = await stripe.checkout.sessions.create({
        customer: customerId,
        mode: 'subscription',
        line_items: [{ price: PRICE_ID, quantity: Number(company?.seats) || 1 }],
        success_url: `${SITE_URL}?paid=1`,
        cancel_url: `${SITE_URL}?canceled=1`,
        metadata: { company_id: member.company_id },
      });
      return json({ url: session.url, mode: 'checkout' });
    }

    const session = await stripe.billingPortal.sessions.create({
      customer: company.stripe_customer_id,
      return_url: SITE_URL,
    });
    return json({ url: session.url, mode: 'portal' });
  } catch (e) {
    return json({ error: e.message }, 500);
  }
});
