/**
 * Gemensam hantering av återställning och byte av lösenord.
 *
 * GoTrue-mejlens verify-länk måste ha redirect_to till en sida som kör
 * Supabase-klienten (admin eller portal). Annars landar användaren på
 * api.taxitips.se utan UI och ser bara ett inloggningsformulär (eller inget).
 */

/**
 * Fråga efter nytt lösenord och spara via den redan öppna recovery-sessionen.
 * Returnerar true om bytet lyckades.
 */
export async function promptAndSetPassword(supabaseClient, { minLength = 12 } = {}) {
  const first = prompt(`Välj ett nytt lösenord (minst ${minLength} tecken):`);
  if (first === null) return false;
  if (first.length < minLength) {
    alert(`Lösenordet måste vara minst ${minLength} tecken.`);
    return false;
  }
  const second = prompt("Skriv det nya lösenordet igen:");
  if (second === null) return false;
  if (first !== second) {
    alert("Lösenorden stämmer inte överens. Inget ändrades.");
    return false;
  }
  const { error } = await supabaseClient.auth.updateUser({ password: first });
  if (error) throw error;
  alert("Lösenordet är sparat. Du är inloggad.");
  return true;
}

/** Skicka återställningsmejl. redirectTo måste ligga i Auth allow-list. */
export async function sendPasswordReset(supabaseClient, email, redirectTo) {
  return supabaseClient.auth.resetPasswordForEmail(email, { redirectTo });
}
