// Firebase Analytics (GA4) + Umami + GlitchTip.
// All three only start after cookie consent (see consent.js).

import { firebase as firebaseConfig, umami as umamiConfig, glitchtip as glitchtipConfig } from "./config.js";

let analyticsInstance = null;
let initPromise = null;

function loadUmami() {
  if (document.querySelector(`script[data-website-id="${umamiConfig.websiteId}"]`)) {
    return;
  }
  const script = document.createElement("script");
  script.defer = true;
  script.src = umamiConfig.src;
  script.dataset.websiteId = umamiConfig.websiteId;
  document.head.appendChild(script);
}

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
    loadUmami();
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
  try {
    window.umami?.track(name, params);
  } catch {
    /* noop */
  }
}
