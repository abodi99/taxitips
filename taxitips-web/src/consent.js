import { initAnalytics } from "./analytics.js";

const STORAGE_KEY = "tt-consent";

function getStoredConsent() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function setStoredConsent(value) {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    /* private browsing / storage disabled — banner just reappears next visit */
  }
}

function showBanner() {
  const banner = document.createElement("div");
  banner.className = "consent-banner";
  banner.setAttribute("role", "dialog");
  banner.setAttribute("aria-label", "Cookies");
  banner.innerHTML = `
    <p>Vi använder nödvändiga cookies för att sidan ska fungera. Med ditt godkännande mäter vi besök via Umami och Google Analytics (Firebase), och fångar tekniska fel via GlitchTip.</p>
    <div class="consent-actions">
      <button type="button" class="btn-ghost-sm" data-consent="necessary">Endast nödvändiga</button>
      <button type="button" class="btn btn-primary btn-sm" data-consent="accepted">Acceptera analys</button>
    </div>
  `;
  document.body.appendChild(banner);
  requestAnimationFrame(() => banner.classList.add("is-visible"));

  banner.addEventListener("click", (e) => {
    const choice = e.target.closest("[data-consent]")?.dataset.consent;
    if (!choice) return;
    setStoredConsent(choice);
    if (choice === "accepted") initAnalytics();
    banner.classList.remove("is-visible");
    window.setTimeout(() => banner.remove(), 300);
  });
}

export function setupConsent() {
  const stored = getStoredConsent();
  if (stored === "accepted") {
    initAnalytics();
  } else if (stored !== "necessary") {
    showBanner();
  }

  const reopenLink = document.querySelector("[data-reopen-consent]");
  if (reopenLink) {
    reopenLink.addEventListener("click", (e) => {
      e.preventDefault();
      if (!document.querySelector(".consent-banner")) showBanner();
    });
  }
}
