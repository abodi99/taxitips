// Firebase Analytics (GA4) + GlitchTip.
// Both only start after cookie consent (see consent.js). Umami är bortkopplat:
// servern är nere. Statistiken läses i adminwebben (Webbstatistik).

import { firebase as firebaseConfig, glitchtip as glitchtipConfig } from "./config.js";

let analyticsInstance = null;
let initPromise = null;

async function loadGlitchtip() {
  if (!glitchtipConfig.dsn) return;
  try {
    const Sentry = await import("https://cdn.jsdelivr.net/npm/@sentry/browser@8/+esm");
    Sentry.init({
      dsn: glitchtipConfig.dsn,
      environment: glitchtipConfig.environment,
      tracesSampleRate: 0.1,
      // GlitchTip speaks the Sentry protocol.
    });
  } catch (err) {
    console.warn("[glitchtip] init failed", err);
  }
}

export function initAnalytics() {
  if (initPromise) return initPromise;
  initPromise = (async () => {
    await loadGlitchtip();

    const [{ initializeApp }, { getAnalytics, logEvent }] = await Promise.all([
      import("firebase/app"),
      import("firebase/analytics"),
    ]);
    const app = initializeApp(firebaseConfig);
    analyticsInstance = getAnalytics(app);
    logEvent(analyticsInstance, "page_view");
    return { logEvent };
  })();
  return initPromise;
}

export async function trackEvent(name, params) {
  if (!initPromise) return;
  try {
    const { logEvent } = await initPromise;
    if (analyticsInstance) logEvent(analyticsInstance, name, params);
  } catch {
    /* analytics must never break the page */
  }
}
