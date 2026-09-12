// Public client IDs only — never put API secrets here.
// Secrets for server-side CRM sync live in Coolify env (see server.mjs).

export const site = {
  name: "Taxi Tips",
  origin: "https://taxitips.se",
  contactEmail: "hej@taxitips.se",
};

/** Firebase / GA4 — project taxibehov, web app "Taxitips Web" */
export const firebase = {
  apiKey: "AIzaSyDoKaLhJptAWUpbw2vh1pJ61YRb7kau2zU",
  authDomain: "taxibehov.firebaseapp.com",
  projectId: "taxibehov",
  storageBucket: "taxibehov.firebasestorage.app",
  messagingSenderId: "963263574599",
  appId: "1:963263574599:web:f8fffff4809589607f7762",
  measurementId: "G-6ZWTCYKFKS",
};

/** Umami (A2M Central) — https://umami.a2m-tech.com */
export const umami = {
  src: "https://umami.a2m-tech.com/script.js",
  websiteId: "8287627e-d38d-45c4-87e5-5589e944cebd",
};

/**
 * GlitchTip (Sentry-compatible) — https://gt.a2m-tech.com
 * Prefer Coolify runtime env GLITCHTIP_DSN (served via /api/config).
 * VITE_GLITCHTIP_DSN works as a build-time fallback.
 */
export const glitchtip = {
  dsn: import.meta.env.VITE_GLITCHTIP_DSN || "",
  environment: import.meta.env.MODE || "production",
};

/**
 * Chatwoot website widget — https://chat.a2m-tech.com
 * Prefer Coolify runtime env CHATWOOT_WEBSITE_TOKEN (served via /api/config).
 */
export const chatwoot = {
  baseUrl: "https://chat.a2m-tech.com",
  // Website token is public by design (same as Umami websiteId).
  websiteToken:
    import.meta.env.VITE_CHATWOOT_WEBSITE_TOKEN || "LhpeRrGyqTJahHVfgmn4ErnF",
};

/** Fills chatwoot/glitchtip from the Node server's public runtime config. */
export async function loadRuntimeConfig() {
  try {
    const res = await fetch("/api/config", { headers: { Accept: "application/json" } });
    if (!res.ok) return;
    const data = await res.json();
    if (data.chatwootWebsiteToken) chatwoot.websiteToken = data.chatwootWebsiteToken;
    if (data.glitchtipDsn) glitchtip.dsn = data.glitchtipDsn;
  } catch {
    /* local vite without server.mjs — keep build-time fallbacks */
  }
}

/** Listmonk public launch list — proxied via /api/subscribe (CORS). */
export const listmonk = {
  listUuid: "e2f8a9bc-674d-47a0-8dd8-77d1272cbfa5",
  subscribePath: "/api/subscribe",
};

/** Twenty CRM workspace (leads land here via /api/lead when server env is set). */
export const twenty = {
  workspaceUrl: "https://taxitips.tw.a2m-tech.com",
  leadPath: "/api/lead",
};
