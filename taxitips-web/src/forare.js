import { createClient } from "@supabase/supabase-js";

import { portal } from "./config.js";

/**
 * forare.html: föraren väljer lösenord efter inbjudan eller "Glömt lösenord?".
 *
 * Länken i mejlet går till Supabase Auth, som verifierar den och skickar hit
 * med en session i adressens hash (#access_token=…&type=invite|recovery).
 * Klienten läser den, `updateUser` sätter lösenordet, och sedan loggas
 * webbsessionen ut igen: kontot används i APPEN, där inloggningen löser in
 * inbjudan och kopplar telefonen (fleet/driver_invites.py). Sidan rör inte
 * backenden alls.
 *
 * Sessionen sparas inte (`persistSession: false`): en förare på en lånad dator
 * ska inte lämna en inloggning efter sig.
 */

const MIN_LENGTH = 8;

const el = {
  loading: document.getElementById("loading"),
  setPassword: document.getElementById("setPassword"),
  done: document.getElementById("done"),
  failed: document.getElementById("failed"),
  failedDetail: document.getElementById("failedDetail"),
  form: document.getElementById("passwordForm"),
  error: document.getElementById("passwordError"),
  save: document.getElementById("passwordSave"),
  emailShown: document.getElementById("emailShown"),
  emailDone: document.getElementById("emailDone"),
};

function show(section) {
  for (const s of [el.loading, el.setPassword, el.done, el.failed]) s.hidden = s !== section;
}

function hashError() {
  const params = new URLSearchParams(
    window.location.search.slice(1) + "&" + window.location.hash.replace(/^#/, ""),
  );
  const error = params.get("error") || params.get("error_code");
  if (!error) return null;
  return (params.get("error_description") || "").replace(/\+/g, " ");
}

function clearAddress() {
  // Token ska inte ligga kvar i adressfältet eller historiken.
  if (window.location.search || window.location.hash) {
    history.replaceState(null, "", window.location.pathname);
  }
}

async function boot() {
  const linkError = hashError();
  if (linkError !== null || !portal.supabaseAnonKey) {
    el.failedDetail.textContent = linkError || "";
    clearAddress();
    show(el.failed);
    return;
  }
  const client = createClient(portal.supabaseUrl, portal.supabaseAnonKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: true,
      flowType: "implicit",
    },
  });
  const { data } = await client.auth.getSession();
  clearAddress();
  const session = data?.session;
  if (!session) {
    show(el.failed);
    return;
  }
  const email = session.user?.email ?? "";
  el.emailShown.textContent = email;
  el.emailDone.textContent = email;
  show(el.setPassword);
  el.form.querySelector("input")?.focus();

  el.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    el.error.hidden = true;
    const form = new FormData(el.form);
    const first = String(form.get("password") ?? "");
    const second = String(form.get("password2") ?? "");
    let problem = "";
    if (first.length < MIN_LENGTH) problem = `Lösenordet behöver minst ${MIN_LENGTH} tecken.`;
    else if (first !== second) problem = "Lösenorden är inte lika. Skriv dem igen.";
    if (problem) {
      el.error.textContent = problem;
      el.error.hidden = false;
      return;
    }
    el.save.disabled = true;
    try {
      const { error } = await client.auth.updateUser({ password: first });
      if (error) throw error;
      await client.auth.signOut({ scope: "local" }).catch(() => {});
      show(el.done);
    } catch (error) {
      el.error.textContent = /weak|short|least/i.test(error?.message ?? "")
        ? "Lösenordet är för enkelt. Välj ett längre."
        : "Det gick inte att spara lösenordet. Försök igen.";
      el.error.hidden = false;
    } finally {
      el.save.disabled = false;
    }
  });
}

boot().catch(() => show(el.failed));
