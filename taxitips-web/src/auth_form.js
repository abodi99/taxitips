/**
 * Det som kundportalens och adminwebbens inloggning delar: laddningsläget på
 * knapparna och felen från Supabase Auth på svenska.
 *
 * GoTrue svarar på engelska ("Invalid login credentials"). Texterna här säger
 * vad som gick fel och vad man gör åt det; okända fel visas som de kom, så att
 * inget felmeddelande försvinner bakom en gissning.
 */

const MESSAGES = [
  [/invalid login credentials/i,
    "Fel e-post eller lösenord. Kontrollera stavningen eller välj Glömt lösenord."],
  [/email not confirmed/i,
    "E-postadressen är inte bekräftad än. Öppna länken i mejlet från oss, eller be om en inloggningslänk."],
  [/rate limit|too many|for security purposes/i,
    "För många försök på kort tid. Vänta en minut och prova igen."],
  [/signups not allowed|user not found/i,
    "Vi hittar inget konto med den e-postadressen. Kontrollera adressen."],
  [/unable to validate email|invalid email|email address .* is invalid/i,
    "E-postadressen ser inte rätt ut."],
  [/failed to fetch|networkerror|load failed|network request failed/i,
    "Ingen kontakt med servern. Kontrollera uppkopplingen och prova igen."],
];

/** Felet som en svensk mening, eller `fallback` när det saknar text. */
export function authErrorMessage(error, fallback) {
  const raw = String(error?.message ?? "").trim();
  if (!raw) return fallback;
  for (const [pattern, text] of MESSAGES) {
    if (pattern.test(raw)) return text;
  }
  return raw;
}

/**
 * Knappen visar att något pågår och går inte att trycka två gånger.
 * Etiketten byts (inte bara en snurra), så att även en skärmläsare hör det.
 */
export function setBusy(button, busy, busyLabel) {
  if (!button) return;
  const label = button.querySelector(".btn-label") ?? button;
  if (busy) {
    if (!button.dataset.idleLabel) button.dataset.idleLabel = label.textContent;
    if (busyLabel) label.textContent = busyLabel;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.classList.add("is-busy");
  } else {
    if (button.dataset.idleLabel) label.textContent = button.dataset.idleLabel;
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.classList.remove("is-busy");
  }
}

/** Markera fältet som fel och flytta fokus dit. */
export function flagField(input) {
  if (!input) return;
  input.setAttribute("aria-invalid", "true");
  input.focus();
  input.addEventListener("input", () => input.removeAttribute("aria-invalid"), { once: true });
}
