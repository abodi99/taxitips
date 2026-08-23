/* Cookie banner + Google Consent Mode v2 (GDPR / ePrivacy / Google EU requirements) */
(function () {
  const KEY = "tb_cookie_consent_v1";
  const cfg = window.__TB_FIREBASE__ || {};

  function readConsent() {
    try {
      return JSON.parse(localStorage.getItem(KEY) || "null");
    } catch (_) {
      return null;
    }
  }

  function writeConsent(value) {
    localStorage.setItem(KEY, JSON.stringify(value));
    window.dispatchEvent(new CustomEvent("tb-cookie-consent", { detail: value }));
  }

  /** Stub gtag + default DENY before any tags load (Consent Mode v2). */
  function ensureGtag() {
    window.dataLayer = window.dataLayer || [];
    window.gtag =
      window.gtag ||
      function () {
        window.dataLayer.push(arguments);
      };
    if (window.__TB_CONSENT_DEFAULT__) return;
    window.__TB_CONSENT_DEFAULT__ = true;
    window.gtag("consent", "default", {
      ad_storage: "denied",
      ad_user_data: "denied",
      ad_personalization: "denied",
      analytics_storage: "denied",
      functionality_storage: "granted",
      security_storage: "granted",
      wait_for_update: 500,
    });
    window.gtag("set", "ads_data_redaction", true);
    window.gtag("set", "url_passthrough", true);
  }

  function grantAnalytics() {
    window.gtag("consent", "update", { analytics_storage: "granted" });
  }

  function denyAnalytics() {
    window.gtag("consent", "update", { analytics_storage: "denied" });
  }

  function loadAnalytics() {
    if (window.__TB_ANALYTICS_LOADED__) return;
    const measurementId = (cfg.measurementId || "").trim();
    if (!measurementId) {
      console.warn("Taxi Tips: measurementId saknas — analytics laddas inte");
      return;
    }

    window.__TB_ANALYTICS_LOADED__ = true;
    grantAnalytics();

    const s = document.createElement("script");
    s.async = true;
    s.src =
      "https://www.googletagmanager.com/gtag/js?id=" +
      encodeURIComponent(measurementId);
    document.head.appendChild(s);

    window.gtag("js", new Date());
    window.gtag("config", measurementId, {
      anonymize_ip: true,
      send_page_view: true,
      cookie_flags: "SameSite=None;Secure",
    });
  }

  function hideBanner(el) {
    if (el) el.remove();
  }

  function showBanner() {
    if (document.getElementById("tb-cookie-banner")) return;
    const el = document.createElement("div");
    el.id = "tb-cookie-banner";
    el.className = "tb-cookie-banner";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-label", "Cookieinställningar");
    el.innerHTML = `
      <div class="tb-cookie-inner">
        <p><strong>Cookies &amp; analys</strong> Nödvändiga cookies behövs för inloggning och säkerhet.
        Med ditt godkännande mäter vi användning via Google Analytics (GA4) för att förbättra Taxi Tips.
        <a href="/privacy.html#cookies">Datapolicy</a>.</p>
        <div class="tb-cookie-actions">
          <button type="button" class="tb-cookie-btn tb-cookie-btn-ghost" data-choice="necessary">Endast nödvändiga</button>
          <button type="button" class="tb-cookie-btn tb-cookie-btn-primary" data-choice="all">Acceptera analys</button>
        </div>
      </div>
    `;
    el.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-choice]");
      if (!btn) return;
      const choice = btn.getAttribute("data-choice");
      const consent = {
        necessary: true,
        analytics: choice === "all",
        at: Date.now(),
      };
      writeConsent(consent);
      if (consent.analytics) loadAnalytics();
      else denyAnalytics();
      hideBanner(el);
    });
    document.body.appendChild(el);
  }

  function boot() {
    ensureGtag();
    const consent = readConsent();
    if (!consent) {
      showBanner();
      return;
    }
    if (consent.analytics) loadAnalytics();
    else denyAnalytics();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.tbOpenCookieSettings = function () {
    localStorage.removeItem(KEY);
    window.__TB_ANALYTICS_LOADED__ = false;
    showBanner();
  };

  window.tbGetCookieConsent = readConsent;
})();
