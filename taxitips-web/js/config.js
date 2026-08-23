/**
 * TaxiTips web — Supabase config (production: api.taxitips.se).
 * Override via window.__TT_SUPABASE__ before this script, or ?sb= / ?anon= query params.
 */
(function () {
  const params = new URLSearchParams(location.search);
  const defaults = {
    url: params.get("sb") || "https://api.taxitips.se",
    anonKey:
      params.get("anon") ||
      "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJzdXBhYmFzZSIsImlhdCI6MTc4NzQ2Nzk4MCwiZXhwIjo0OTQzMTQxNTgwLCJyb2xlIjoiYW5vbiJ9.wxFoFcVxscjp0h4UlqltO-uBaH-EFiTIECWzyxovuzI",
  };
  window.__TT_SUPABASE__ = Object.assign({}, defaults, window.__TT_SUPABASE__ || {});
})();
