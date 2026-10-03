import "./password_toggle.css";

/**
 * Visa/dölj lösenord -- samma knapp i kundportalen, adminwebben och
 * registreringen.
 *
 * Markupen är en vanlig knapp bredvid fältet:
 *
 *   <div class="pw-field">
 *     <input id="password" type="password" … />
 *     <button type="button" class="pw-toggle" data-password-toggle="password"></button>
 *   </div>
 *
 * Hjälparen fyller i ikonen och sköter `type`, `aria-pressed` och
 * `aria-label`. Knappen är `type="button"` så att den aldrig skickar
 * formuläret, och etiketten byts i stället för att bara ikonen byts: en
 * skärmläsare ska höra vad ett tryck GÖR ("Dölj lösenord"), inte bara att
 * något är nedtryckt.
 */

// Samma streckstil som ikonerna i public/brand/icons (1.8, runda ändar).
const ICON = `<svg class="pw-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
  <g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/>
    <circle cx="12" cy="12" r="3"/>
    <path class="pw-slash" d="M4 4l16 16"/>
  </g>
</svg>`;

function sync(button, input) {
  const shown = input.type === "text";
  button.setAttribute("aria-pressed", String(shown));
  button.setAttribute("aria-label", shown ? "Dölj lösenord" : "Visa lösenord");
  button.title = shown ? "Dölj lösenord" : "Visa lösenord";
}

/** Koppla en knapp till sitt lösenordsfält. Returnerar en funktion som döljer igen. */
export function attachPasswordToggle(button) {
  const input = document.getElementById(button.dataset.passwordToggle || "");
  if (!input || button.dataset.pwReady) return () => {};
  button.dataset.pwReady = "1";
  button.type = "button";
  button.setAttribute("aria-controls", input.id);
  if (!button.querySelector("svg")) button.innerHTML = ICON;
  sync(button, input);

  button.addEventListener("click", () => {
    input.type = input.type === "password" ? "text" : "password";
    sync(button, input);
  });

  const hide = () => {
    input.type = "password";
    sync(button, input);
  };
  // Ett synligt lösenord ska inte följa med in i webbläsarens formulärminne
  // eller ligga kvar på skärmen efter inloggningen.
  input.form?.addEventListener("submit", hide);
  return hide;
}

/** Alla `[data-password-toggle]` under `root`. */
export function setupPasswordToggles(root = document) {
  root.querySelectorAll("[data-password-toggle]").forEach((b) => attachPasswordToggle(b));
}
