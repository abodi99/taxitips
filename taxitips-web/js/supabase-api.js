/**
 * Shared Supabase client + thin API helpers for taxitips-web.
 * Requires: config.js, then @supabase/supabase-js from CDN.
 */
(function () {
  const cfg = window.__TT_SUPABASE__ || {};
  if (!window.supabase || !cfg.url || !cfg.anonKey || cfg.anonKey.startsWith("REPLACE_")) {
    console.warn("[taxitips] Supabase not configured — set window.__TT_SUPABASE__ or js/config.js");
  }

  const client =
    window.supabase && cfg.url && cfg.anonKey
      ? window.supabase.createClient(cfg.url, cfg.anonKey, {
          auth: {
            persistSession: true,
            autoRefreshToken: true,
            detectSessionInUrl: true,
            storageKey: "tt-auth",
          },
        })
      : null;

  window.tt = window.tt || {};
  window.tt.sb = client;

  async function session() {
    if (!client) return null;
    const { data } = await client.auth.getSession();
    return data.session;
  }

  window.tt.api = {
    async login(email, password) {
      const { data, error } = await client.auth.signInWithPassword({ email, password });
      if (error) throw error;
      return data;
    },
    async signup(email, password, meta = {}) {
      const { data, error } = await client.auth.signUp({
        email,
        password,
        options: { data: meta },
      });
      if (error) throw error;
      return data;
    },
    async logout() {
      await client.auth.signOut();
    },
    async me() {
      const s = await session();
      if (!s) throw new Error("not_authenticated");
      const { data: profile } = await client
        .from("profiles")
        .select("*")
        .eq("id", s.user.id)
        .maybeSingle();
      const { data: memberships } = await client
        .from("company_members")
        .select("role, status, company:companies(*)")
        .eq("user_id", s.user.id)
        .eq("status", "active");
      return { user: s.user, profile, memberships: memberships || [] };
    },
    async alerts() {
      const { data, error } = await client
        .from("alerts")
        .select("*")
        .order("updated_at", { ascending: false })
        .limit(200);
      if (error) throw error;
      return data || [];
    },
    async joinDevice(code, label) {
      const { data, error } = await client.rpc("join_device", {
        p_join_code: code,
        p_label: label || "Förare",
      });
      if (error) throw error;
      return data;
    },
    async deviceByToken(token) {
      const { data, error } = await client.rpc("device_by_token", { p_token: token });
      if (error) throw error;
      return data;
    },
  };
})();
