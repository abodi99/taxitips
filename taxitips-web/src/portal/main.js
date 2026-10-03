import { promptAndSetPassword, sendPasswordReset } from "../auth_password.js";
import { ApiError, api, supabase } from "./api.js";
import * as views from "./views.js";
import { quoteHtml } from "./views.js";

/**
 * Portalens sammanhållning: inloggning, vyval och åtgärder.
 *
 * **Ingen åtgärd som rör pengar körs utan att kunden sett beloppet.** Köp går
 * alltid genom `api.quote()` först, och beställningen skickas först efter ett
 * uttryckligt ja på kostnad nu, nästa period, moms och datum.
 *
 * **Felen kommer från servern.** Portalen hittar inte på egna meddelanden om
 * behörighet, granskning eller betalning -- den visar backendens `message`,
 * som är skriven för kunden. Ett andra regelverk här hade kunnat säga något
 * annat än det som faktiskt gäller.
 */

const el = {
  login: document.getElementById("login"),
  loginForm: document.getElementById("loginForm"),
  loginError: document.getElementById("loginError"),
  app: document.getElementById("app"),
  view: document.getElementById("view"),
  tabs: document.querySelectorAll(".tab"),
  whoami: document.getElementById("whoami"),
  logout: document.getElementById("logout"),
  globalError: document.getElementById("globalError"),
  globalNotice: document.getElementById("globalNotice"),
  codeDialog: document.getElementById("codeDialog"),
  codeValue: document.getElementById("codeValue"),
  codeFor: document.getElementById("codeFor"),
};

let state = { view: "oversikt", data: null, orders: null, members: null };

// Inbjudningsmejlet (fleet/notifications.py:member_invite) loggar in direkt
// via #...&type=invite. Läses innan Supabase-klienten tömmer adressraden, så
// att personen får välja ett lösenord och kan logga in igen utan mejl.
let arrivedByInvite = /(^|[#&])type=invite(&|$)/.test(window.location.hash);

/**
 * Länken i mejlen om provslut (portal#fortsatt). Ankaret försvinner när
 * kunden loggar in med e-postlänk -- den skickar tillbaka till sidan utan
 * det -- så önskan sparas här och läses efter inloggningen.
 */
const CONTINUE_KEY = "tt_portal_continue";
try {
  if (window.location.hash === "#fortsatt") sessionStorage.setItem(CONTINUE_KEY, "1");
  const params = new URLSearchParams(window.location.search);
  if (params.get("trial_commit") === "ok") sessionStorage.setItem(CONTINUE_KEY, "1");
} catch {
  // Utan sessionStorage fungerar länken bara när kunden redan är inloggad.
}

function takeContinueWish() {
  try {
    const wanted = sessionStorage.getItem(CONTINUE_KEY) === "1" || window.location.hash === "#fortsatt";
    sessionStorage.removeItem(CONTINUE_KEY);
    return wanted;
  } catch {
    return window.location.hash === "#fortsatt";
  }
}

function showError(error) {
  const message =
    error instanceof ApiError ? error.message : "Något gick fel. Prova igen.";
  el.globalError.textContent = message;
  el.globalError.hidden = false;
}

function clearError() {
  el.globalError.hidden = true;
  el.globalError.textContent = "";
  if (el.globalNotice) {
    el.globalNotice.hidden = true;
    el.globalNotice.textContent = "";
  }
}

/** En bekräftelse som ligger kvar efter omritningen (t.ex. "Inbjudan skickad"). */
function showNotice(message) {
  if (!el.globalNotice) return;
  el.globalNotice.textContent = message;
  el.globalNotice.hidden = false;
}

async function boot() {
  const { data } = await supabase().auth.getSession();
  if (data?.session) {
    await enterApp(data.session);
  } else {
    el.login.hidden = false;
    showAuthHashError();
  }
}

/** Visa GoTrue-fel från hash (#error=otp_expired …) efter en förbrukad mejllänk. */
function showAuthHashError() {
  const raw = window.location.hash.replace(/^#/, "");
  if (!raw.includes("error=")) return;
  const params = new URLSearchParams(raw);
  const code = params.get("error_code") || params.get("error") || "";
  const desc = params.get("error_description") || "";
  let message = "Inloggningslänken fungerar inte längre.";
  if (code === "otp_expired" || /expired|invalid/i.test(desc)) {
    message =
      "Länken är redan använd eller har gått ut. Begär en ny under Glömt lösenord.";
  }
  el.loginError.textContent = message;
  el.loginError.hidden = false;
  history.replaceState(null, "", window.location.pathname + window.location.search);
}

// Inloggningen triggar både formulärets svar och `onAuthStateChange`; appen
// ska bara startas en gång, annars renderas allt två gånger i otakt.
let entered = false;

async function enterApp(session) {
  if (entered) return;
  entered = true;
  el.login.hidden = true;
  el.app.hidden = false;
  el.logout.hidden = false;
  el.whoami.textContent = session.user?.email ?? "";
  const wantsContinue = takeContinueWish();
  if (wantsContinue) state.view = "oversikt";
  await refresh();
  if (wantsContinue) {
    const card = document.getElementById("fortsatt");
    card?.scrollIntoView({ behavior: "smooth", block: "center" });
    card?.classList.add("is-highlighted");
    card?.querySelector("button")?.focus({ preventScroll: true });
  }
}

async function refresh() {
  clearError();
  try {
    state.data = await companyOrClaim();
    if (state.view === "abonnemang" && !state.orders) {
      state.orders = await api.orders();
    }
    if (state.view === "foretag") {
      // Listan är en extra: företagssidan ska visas även om den inte svarar.
      state.members = await api.members().catch(() => null);
    }
  } catch (error) {
    showError(error);
    return;
  }
  render();
}

function render() {
  const data = state.data;
  if (!data) return;
  const html = {
    oversikt: () => views.oversikt(data),
    bilar: () => views.bilar(data),
    lan: () => views.lan(data),
    abonnemang: () => views.abonnemang(data, state.orders?.orders ?? []),
    foretag: () => views.foretag(data, state.members),
  }[state.view];
  el.view.innerHTML = html ? html() : "";
}

/**
 * Första inloggningen efter en inbjudan: kontot hör inte till något företag
 * än. Servern knyter det till företaget som bjöd in e-postadressen -- och bara
 * då; adressen läses ur den verifierade inloggningen, inte ur något vi skickar.
 */
async function companyOrClaim() {
  try {
    return await api.company();
  } catch (error) {
    if (!(error instanceof ApiError) || error.reason !== "missing_permission") throw error;
    try {
      await api.claimInvite();
    } catch (claimError) {
      if (claimError instanceof ApiError && claimError.reason === "no_invite") {
        if (await completePendingRegistration()) return api.company();
        throw new ApiError(
          403,
          "Kontot är inte kopplat till något företag. Är du förare? Logga in i appen " +
            "under Jag är förare. Annars: be den som sköter ert konto, eller Taxi Tips, " +
            "att bjuda in din e-postadress.",
          "no_company",
        );
      }
      throw claimError;
    }
    return api.company();
  }
}

/**
 * Registreringen från taxitips.se/registrera, när e-posten först måste
 * bekräftas: bolagets uppgifter sparades i kontots metadata, och görs klart
 * här vid första inloggningen (samma POST /api/fleet/register som appen).
 * Servern prövar allt igen och tar e-posten ur den verifierade inloggningen.
 * Ett fel (t.ex. att bolaget redan har ett konto) visas med serverns text.
 */
async function completePendingRegistration() {
  const { data } = await supabase().auth.getUser();
  const pending = data?.user?.user_metadata?.pending_company;
  if (!pending || typeof pending !== "object") return false;
  await api.register(pending);
  await supabase().auth.updateUser({ data: { pending_company: null } }).catch(() => {});
  return true;
}

/* --- Inloggning --------------------------------------------------------- */

/**
 * Inloggningslänk via e-post. `shouldCreateUser: false`: portalen skapar inga
 * konton på egen hand. Ett inbjudet konto skapas när säljaren skickar den
 * första länken; den här knappen ger en ny länk om den första hunnit gå ut.
 */
document.getElementById("magicLink")?.addEventListener("click", async () => {
  el.loginError.hidden = true;
  const email = String(new FormData(el.loginForm).get("email") ?? "").trim();
  const sent = document.getElementById("magicSent");
  if (!email) {
    el.loginError.textContent = "Skriv din e-post först.";
    el.loginError.hidden = false;
    return;
  }
  try {
    const { error } = await supabase().auth.signInWithOtp({
      email,
      options: {
        shouldCreateUser: false,
        emailRedirectTo: `${window.location.origin}${window.location.pathname}`,
      },
    });
    if (error) throw error;
    sent.textContent = `Om ${email} har ett konto kommer en inloggningslänk strax.`;
    sent.hidden = false;
  } catch (error) {
    el.loginError.textContent = error?.message ?? "Kunde inte skicka länken.";
    el.loginError.hidden = false;
  }
});

// Återställningsmejlet landar här. Utan PASSWORD_RECOVERY-steget ser det ut
// som vanlig inloggning och användaren blir ombedd om det gamla lösenordet.
supabase().auth.onAuthStateChange(async (event, session) => {
  if (event === "PASSWORD_RECOVERY" && session) {
    try {
      await promptAndSetPassword(supabase());
    } catch (error) {
      alert(error?.message ?? "Kunde inte spara lösenordet.");
      return;
    }
    if (el.app.hidden) await enterApp(session);
    return;
  }
  if (event === "SIGNED_IN" && session && el.app.hidden) {
    await enterApp(session);
  }
  if (event === "SIGNED_IN" && session && arrivedByInvite) {
    arrivedByInvite = false;
    alert("Välkommen till Taxi Tips! Välj ett lösenord, så kan du logga in igen här och i appen.");
    await promptAndSetPassword(supabase()).catch((error) => alert(error?.message ?? "Kunde inte spara lösenordet."));
  }
});

document.getElementById("forgotPassword")?.addEventListener("click", async () => {
  el.loginError.hidden = true;
  const email = String(new FormData(el.loginForm).get("email") ?? "").trim();
  const sent = document.getElementById("magicSent");
  if (!email) {
    el.loginError.textContent = "Skriv din e-post först.";
    el.loginError.hidden = false;
    return;
  }
  try {
    const { error } = await sendPasswordReset(
      supabase(),
      email,
      `${window.location.origin}${window.location.pathname}`,
    );
    if (error) throw error;
    sent.textContent = `Om ${email} har ett konto kommer en återställningslänk strax.`;
    sent.hidden = false;
  } catch (error) {
    el.loginError.textContent = error?.message ?? "Kunde inte skicka länken.";
    el.loginError.hidden = false;
  }
});

el.loginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  el.loginError.hidden = true;
  const form = new FormData(el.loginForm);
  try {
    const { data, error } = await supabase().auth.signInWithPassword({
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
    });
    if (error) throw error;
    await enterApp(data.session);
  } catch (error) {
    el.loginError.textContent =
      error?.message ?? "Kunde inte logga in. Kontrollera e-post och lösenord.";
    el.loginError.hidden = false;
  }
});

el.logout?.addEventListener("click", async () => {
  await supabase().auth.signOut();
  window.location.reload();
});

/* --- Vyval -------------------------------------------------------------- */

for (const tab of el.tabs) {
  tab.addEventListener("click", async () => {
    for (const other of el.tabs) other.setAttribute("aria-selected", "false");
    tab.setAttribute("aria-selected", "true");
    state.view = tab.dataset.view;
    if (state.view === "foretag") state.members = await api.members().catch(() => null);
    if (state.view === "abonnemang" && !state.orders) {
      try {
        state.orders = await api.orders();
      } catch (error) {
        showError(error);
      }
    }
    render();
  });
}

/* --- Åtgärder ----------------------------------------------------------- */

el.view.addEventListener("submit", async (event) => {
  const form = event.target;
  if (form.id === "contactForm" || form.id === "billingForm") {
    event.preventDefault();
    await saveDetails(form);
    return;
  }
  if (form.id === "memberInviteForm") {
    event.preventDefault();
    clearError();
    const data = new FormData(form);
    const email = String(data.get("email") ?? "").trim();
    try {
      await api.inviteMember(email, String(data.get("role") ?? "fleet_admin"));
      await refresh();
      showNotice(`Inbjudan är skickad till ${email}.`);
    } catch (error) {
      showError(error);
    }
    return;
  }
  if (form.classList.contains("invite-form")) {
    event.preventDefault();
    await inviteDriver(form);
    return;
  }
  if (form.id !== "vehicleForm") return;
  event.preventDefault();
  clearError();
  const data = new FormData(form);
  try {
    await api.createVehicle(
      String(data.get("plate") ?? ""),
      String(data.get("label") ?? ""),
    );
    await refresh();
  } catch (error) {
    showError(error);
  }
});

/** Bjud in en förare med e-post. Servern skapar kontot och skickar mejlet. */
async function inviteDriver(form) {
  clearError();
  const data = new FormData(form);
  const email = String(data.get("email") ?? "").trim();
  const button = form.querySelector('button[type="submit"]');
  if (!email) {
    showError(new ApiError(400, "Skriv förarens e-post.", "email_required"));
    form.querySelector('[name="email"]')?.focus();
    return;
  }
  button.disabled = true;
  try {
    await api.inviteDriver({
      email,
      label: String(data.get("label") ?? "").trim(),
      licenseId: form.dataset.license,
      vehicleId: form.dataset.vehicle,
    });
    await refresh();
    showNotice(
      `Inbjudan skickad till ${email}. Föraren väljer lösenord via mejlet och loggar sedan in i appen.`,
    );
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
  }
}

/** Kontaktperson eller fakturering. Felet visas vid fältet servern pekar ut. */
async function saveDetails(form) {
  clearError();
  const data = new FormData(form);
  const value = (k) => String(data.get(k) ?? "").trim();
  const body =
    form.id === "contactForm"
      ? { contactName: value("contactName"), contactPhone: value("contactPhone") }
      : {
          billingEmail: value("billingEmail"),
          billingReference: value("billingReference"),
          billingAddress: {
            line1: value("line1"), line2: value("line2"),
            postalCode: value("postalCode"), city: value("city"),
          },
        };
  const button = form.querySelector('button[type="submit"]');
  const saved = form.querySelector("[data-saved]");
  form.querySelectorAll("[aria-invalid]").forEach((i) => i.removeAttribute("aria-invalid"));
  form.querySelector(".field-error")?.remove();
  button.disabled = true;
  try {
    const result = await api.updateDetails(body);
    if (state.data?.company) state.data.company.details = result.details;
    if (saved) {
      saved.hidden = false;
      window.setTimeout(() => { saved.hidden = true; }, 3000);
    }
  } catch (error) {
    const field = error instanceof ApiError ? error.detail?.field : null;
    const input = field && form.querySelector(
      field === "billingAddress" ? '[name="line1"]' : `[name="${field}"]`,
    );
    if (input) {
      input.setAttribute("aria-invalid", "true");
      const p = document.createElement("p");
      p.className = "error field-error";
      p.setAttribute("role", "alert");
      p.textContent = error.message;
      input.after(p);
      input.focus();
    } else {
      showError(error);
    }
  } finally {
    button.disabled = false;
  }
}

el.view.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  clearError();
  const { action, license, vehicle, plate, approval, invite, user, email } = button.dataset;
  button.disabled = true;
  try {
    await handle(action, { license, vehicle, plate, approval, invite, user, email });
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
  }
});

async function handle(action, ctx) {
  switch (action) {
    case "member-invite-revoke": {
      if (!confirm(`Återkalla inbjudan till ${ctx.email}?`)) return;
      await api.revokeMemberInvite(ctx.invite);
      return refresh();
    }
    case "member-remove": {
      if (!confirm(`Ta bort ${ctx.email || "personen"}? Hen kan inte längre logga in i företaget.`)) return;
      await api.removeMember(ctx.user);
      await refresh();
      showNotice(`${ctx.email || "Personen"} är borttagen.`);
      return;
    }
    case "resend-invite": {
      await api.resendInvite(ctx.invite);
      await refresh();
      showNotice("Inbjudan skickad igen. Den nya länken gäller i sju dagar.");
      return;
    }
    case "revoke-invite": {
      if (!confirm("Ta bort inbjudan? Föraren kan inte längre använda den för att logga in.")) return;
      await api.revokeInvite(ctx.invite);
      return refresh();
    }
    case "block": {
      if (
        !confirm(
          "Spärra telefonen? Den slutar visa tips direkt och lämnar bilen. " +
            "Telefonen behöver anslutas på nytt för att användas igen.",
        )
      )
        return;
      await api.blockPhone(ctx.approval, "lost_phone");
      return refresh();
    }
    case "change-vehicle": {
      const plate = prompt(
        "Registreringsnummer för den nya bilen. Licensens betalperiod, län och " +
          "provhistorik följer med; den gamla bilens telefoner måste godkännas på nytt.",
      );
      if (!plate) return;
      const created = await api.createVehicle(plate, "");
      await api.changeVehicle(ctx.license, {
        mode: "permanent",
        vehicle_id: created.vehicleId,
      });
      return refresh();
    }
    case "add-county": {
      const select = document.querySelector(`[data-county-for="${ctx.license}"]`);
      const county = select?.value;
      if (!county) return;
      return buy({ addCounties: [{ licenseId: ctx.license, county }] });
    }
    case "change-base": {
      const select = document.querySelector(`[data-county-for="${ctx.license}"]`);
      const county = select?.value;
      if (!county) return;
      const now = confirm(
        "Behöver du det nya länet direkt?\n\n" +
          "OK: vi köper länet som tillägg nu (proportionellt för resten av " +
          "perioden) och byter baslän vid nästa förnyelse. Tillägget tas bort " +
          "automatiskt vid bytet.\n\n" +
          "Avbryt: bytet sker vid nästa förnyelse och kostar inget nu.",
      );
      return buy({
        baseCountyChanges: [{ licenseId: ctx.license, county, immediate: now }],
      });
    }
    case "continue-trial": {
      const cars = state.data?.continueVehicles ?? [];
      if (!cars.length) return;
      const change = {
        addVehicles: cars.map((c) => ({
          plate: c.plate, baseCounty: c.baseCounty, label: "", extraCounties: [],
        })),
      };
      const trial = state.data?.trial;
      const activeTrial = trial && ["pending", "active"].includes(trial.status);
      if (activeTrial) {
        return commitTrial(change);
      }
      return buy(change);
    }
    case "cancel-trial-commit": {
      if (
        !confirm(
          "Avbryta auto-förnyelse?\n\nKortet tas bort från fortsättningen. " +
            "Provet gäller ut, sedan stängs åtkomsten utan debitering om ni " +
            "inte sparar kort igen.",
        )
      )
        return;
      await api.trialCommitCancel();
      state.orders = null;
      return refresh();
    }
    case "billing-portal": {
      const result = await api.billingPortal();
      if (result.url) window.open(result.url, "_blank", "noopener");
      return;
    }
    case "add-license": {
      const plate = prompt("Registreringsnummer för bilen:");
      if (!plate) return;
      const county = prompt("Baslän (SCB-kod, t.ex. 12 för Skåne):");
      if (!county) return;
      return buy({
        addVehicles: [{ plate, baseCounty: county, label: "", extraCounties: [] }],
      });
    }
    case "cancel": {
      if (
        !confirm(
          "Säga upp abonnemanget?\n\nNästa period stoppas. Du behåller " +
            "åtkomsten den betalda perioden ut och kan ångra dig fram till " +
            "slutdatumet.",
        )
      )
        return;
      const result = await api.cancel("");
      alert(result.message);
      state.orders = null;
      return refresh();
    }
    case "undo-cancel": {
      await api.undoCancel();
      state.orders = null;
      return refresh();
    }
    case "close-account": {
      if (
        !confirm(
          "Avsluta företagskontot? Förnyelsen stoppas. Åtkomsten gäller den " +
            "betalda perioden ut.",
        )
      )
        return;
      const result = await api.closeAccount();
      alert(result.explanation);
      return refresh();
    }
    default:
      return;
  }
}

/**
 * Under pågående prov: offert → commit (spara kort, debitering vid ends_at).
 */
async function commitTrial(change) {
  const quote = await api.quote(change);
  const summary = document.createElement("div");
  summary.innerHTML = quoteHtml(quote);
  const ends = state.data?.trial?.endsAt
    ? new Date(state.data.trial.endsAt).toLocaleDateString("sv-SE")
    : "provets slut";
  const accepted = confirm(
    `${summary.textContent}\n\n` +
      `Godkänner du? Kortet sparas nu. Första dragningen sker ${ends} — ` +
      `inget debiteras under provet.`,
  );
  if (!accepted) return;

  const result = await api.trialCommit(change);
  if (result.cardOnFile) {
    alert(
      "Kortet är redan sparat. Första dragningen sker när provet tar slut.",
    );
  } else if (result.paymentUrl) {
    const go = confirm(
      "Öppna Stripes sida och spara kortet nu?\n\n" +
        "Ingen dragning sker förrän provperioden tar slut.",
    );
    if (go) window.open(result.paymentUrl, "_blank", "noopener");
  } else {
    alert(
      "Kunde inte öppna betalsidan." +
        (result.paymentError ? `\n\n${result.paymentError.message}` : ""),
    );
  }
  state.orders = null;
  return refresh();
}

/**
 * Köp: offert först, godkännande sedan, beställning sist.
 *
 * Ordningen är regeln, inte en artighet -- §6 kräver att kunden ser kostnad nu,
 * nästa period, moms, totalsumma och datum innan beställningen godkänns.
 */
async function buy(change) {
  const quote = await api.quote(change);
  const summary = document.createElement("div");
  summary.innerHTML = quoteHtml(quote);

  const accepted = confirm(
    `${summary.textContent}\n\nGodkänner du beställningen?`,
  );
  if (!accepted) return;

  const order = await api.order(change);
  if (order.status === "pending_payment" && order.paymentUrl) {
    // Stripes betalsida. Rättigheterna ges när Stripe bekräftat betalningen,
    // inte när kunden kommer tillbaka hit.
    const go = confirm(
      "Beställningen väntar på betalning. Öppna betalsidan nu?\n\n" +
        "Bilarna och länen aktiveras när betalningen har gått igenom.",
    );
    if (go) window.open(order.paymentUrl, "_blank", "noopener");
  } else if (order.status === "pending_payment") {
    alert(
      "Beställningen är registrerad och väntar på betalning. Rättigheterna " +
        "träder i kraft när betalningen har gått igenom." +
        (order.paymentError ? `\n\n${order.paymentError.message}` : ""),
    );
  } else if (order.status === "scheduled") {
    alert(
      "Ändringen är schemalagd till nästa förnyelse. Fram till dess gäller " +
        "det du har nu.",
    );
  }
  state.orders = null;
  return refresh();
}

boot().catch((error) => {
  el.login.hidden = false;
  showError(error);
});
