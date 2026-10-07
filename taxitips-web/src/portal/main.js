import { authErrorMessage, flagField, setBusy } from "../auth_form.js";
import { promptAndSetPassword, sendPasswordReset } from "../auth_password.js";
import { setupPasswordToggles } from "../password_toggle.js";
import { ApiError, api, countyName, offerableCountyEntries, supabase } from "./api.js";
import * as views from "./views.js";
import { quoteHtml } from "./views.js";
import { notifyBody } from "../notify_editor.js";

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
  tabs: document.querySelectorAll(".tabs-primary .tab"),
  moreToggle: document.getElementById("moreToggle"),
  moreMenu: document.getElementById("moreMenu"),
  whoami: document.getElementById("whoami"),
  logout: document.getElementById("logout"),
  globalError: document.getElementById("globalError"),
  globalNotice: document.getElementById("globalNotice"),
  codeDialog: document.getElementById("codeDialog"),
  codeValue: document.getElementById("codeValue"),
  codeFor: document.getElementById("codeFor"),
  loginSubmit: document.getElementById("loginSubmit"),
  magicSent: document.getElementById("magicSent"),
  // Lägg till medlemskap (ett län ur en lista + vem som håller platsen).
  addDialog: document.getElementById("addMembershipDialog"),
  addForm: document.getElementById("addMembershipForm"),
  addCounty: document.getElementById("addMembershipCounty"),
  addEmail: document.getElementById("addMembershipEmail"),
  addEmailField: document.querySelector(".add-email-field"),
  addQuote: document.getElementById("addMembershipQuote"),
  addError: document.getElementById("addMembershipError"),
  addBuy: document.getElementById("addMembershipBuy"),
};

/** Primärvyer i flikraden. Äldre fliknamn (bilar, lan) mappas till medlemskap. */
const ALL_VIEWS = new Set(["oversikt", "medlemskap", "abonnemang", "foretag"]);

function normalizeView(name) {
  if (name === "lan" || name === "bilar") return "medlemskap";
  return ALL_VIEWS.has(name) ? name : "oversikt";
}

function closeMoreMenu() {
  if (!el.moreMenu || !el.moreToggle) return;
  el.moreMenu.hidden = true;
  el.moreToggle.setAttribute("aria-expanded", "false");
  el.moreToggle.classList.toggle("is-active", state.view === "foretag");
}

function markActiveTab(view) {
  const active = normalizeView(view);
  for (const tab of el.tabs) {
    tab.setAttribute("aria-selected", tab.dataset.view === active ? "true" : "false");
  }
  if (el.moreToggle) {
    el.moreToggle.classList.toggle("is-active", active === "foretag");
    el.moreToggle.setAttribute("aria-current", active === "foretag" ? "page" : "false");
  }
}

async function showView(view) {
  state.view = normalizeView(view);
  markActiveTab(state.view);
  closeMoreMenu();
  if (state.view === "foretag") state.members = await api.members().catch(() => null);
  if (state.view === "medlemskap") state.notify = await api.notifySettings().catch(() => null);
  if (state.view === "abonnemang" && !state.orders) {
    try {
      state.orders = await api.orders();
    } catch (error) {
      showError(error);
    }
  }
  render();
  if (state.view === "abonnemang") loadPricing();
}

setupPasswordToggles(el.login ?? document);

let state = {
  view: "oversikt", data: null, orders: null, members: null, pricing: null,
  notify: null, userId: null,
  // Lägg till medlemskap: offerten vi visat (steg 1) och om ett köp pågår.
  addQuote: null, addBusy: false,
};

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
  // ApiError = serverns text. TypeError (Failed to fetch) = nät/CORS —
  // utan det syns bara den generiska raden och felet är omöjligt att felsöka.
  const message =
    error instanceof ApiError
      ? error.message
      : error?.name === "TypeError"
        ? "Kunde inte nå servern. Prova igen om en stund."
        : "Något gick fel. Prova igen.";
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
  state.userId = session.user?.id ?? null;
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
    if (state.view === "medlemskap") {
      // Samma sak med notiserna: medlemskapen visas även om de inte svarar.
      state.notify = await api.notifySettings().catch(() => null);
    }
  } catch (error) {
    showError(error);
    return;
  }
  render();
  // Antalet bilar kan ha ändrats: priset under Abonnemang hämtas om.
  if (state.view === "abonnemang") loadPricing();
}

/** Provbilarna som en beställning: samma ändring som "Fortsätt efter provet". */
function continueChange() {
  const cars = state.data?.continueVehicles ?? [];
  if (!cars.length) return null;
  return {
    addVehicles: cars.map((c) => ({
      plate: c.plate, baseCounty: c.baseCounty, label: "", extraCounties: [],
    })),
  };
}

/**
 * Priset i medlemskapsvyn. Två offerter från servern, som inte ändrar något
 * (POST /api/fleet/quote): fortsättningen med bolagets egna medlemskap -- eller
 * nuläget, för den som redan betalar -- och ett medlemskap med ett extra län,
 * för länspriset. Portalen räknar inga belopp själv (fleet/pricing.py).
 *
 * Ett fel här är inget fel för kunden: vyn säger då bara att priset visas
 * innan något godkänns. En ekonomiroll utan rätt att se priser får samma text.
 */
let pricingRun = 0;
async function loadPricing() {
  const data = state.data;
  if (!data) return;
  const run = ++pricingRun;
  state.pricing = { loading: true };
  const cars = data.continueVehicles ?? [];
  const base = String(cars[0]?.baseCounty ?? data.licenses?.[0]?.baseCounty ?? "12");
  const extra = offerableCountyEntries().map(([code]) => code).find((code) => code !== base);
  const [own, probe] = await Promise.allSettled([
    api.quote(continueChange() ?? {}),
    api.quote({
      addVehicles: [{ plate: "", baseCounty: base, label: "", extraCounties: [extra] }],
    }),
  ]);
  if (run !== pricingRun) return; // en senare hämtning har redan tagit över
  state.pricing = {
    quote: own.status === "fulfilled" ? own.value : null,
    probe: probe.status === "fulfilled" ? probe.value : null,
  };
  if (state.view === "abonnemang") render();
}

function render() {
  const data = state.data;
  if (!data) return;
  state.view = normalizeView(state.view);
  markActiveTab(state.view);
  const html = {
    oversikt: () => views.oversikt(data),
    medlemskap: () => views.medlemskap(data, state.userId, state.notify),
    abonnemang: () => views.abonnemang(data, state.orders?.orders ?? [], state.pricing),
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
            "med e-post och lösenord. Annars: be den som sköter ert konto, eller Taxi Tips, " +
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

function showLoginError(message) {
  el.loginError.textContent = message;
  el.loginError.hidden = false;
}

/**
 * E-posten ur formuläret, eller tom sträng med felet visat vid fältet. Alla
 * tre vägarna (lösenord, inloggningslänk, glömt lösenord) börjar här, och ett
 * nytt försök tar bort förra försökets fel och kvitto.
 */
function loginEmail() {
  el.loginError.hidden = true;
  if (el.magicSent) el.magicSent.hidden = true;
  const email = String(new FormData(el.loginForm).get("email") ?? "").trim();
  if (!email) {
    showLoginError("Skriv din e-post först.");
    flagField(document.getElementById("email"));
  }
  return email;
}

/**
 * Inloggningslänk via e-post. `shouldCreateUser: false`: portalen skapar inga
 * konton på egen hand. Ett inbjudet konto skapas när säljaren skickar den
 * första länken; den här knappen ger en ny länk om den första hunnit gå ut.
 */
document.getElementById("magicLink")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const email = loginEmail();
  const sent = el.magicSent;
  if (!email) return;
  setBusy(button, true, "Skickar länken …");
  try {
    const { error } = await supabase().auth.signInWithOtp({
      email,
      options: {
        shouldCreateUser: false,
        emailRedirectTo: `${window.location.origin}${window.location.pathname}`,
      },
    });
    if (error) throw error;
    sent.textContent = `Om ${email} har ett konto kommer en inloggningslänk strax. Kolla inkorgen, och skräpposten.`;
    sent.hidden = false;
  } catch (error) {
    showLoginError(authErrorMessage(error, "Kunde inte skicka länken."));
  } finally {
    setBusy(button, false);
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

document.getElementById("forgotPassword")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const email = loginEmail();
  const sent = el.magicSent;
  if (!email) return;
  setBusy(button, true, "Skickar …");
  try {
    const { error } = await sendPasswordReset(
      supabase(),
      email,
      `${window.location.origin}${window.location.pathname}`,
    );
    if (error) throw error;
    sent.textContent = `Om ${email} har ett konto kommer en länk för att välja nytt lösenord strax.`;
    sent.hidden = false;
  } catch (error) {
    showLoginError(authErrorMessage(error, "Kunde inte skicka länken."));
  } finally {
    setBusy(button, false);
  }
});

el.loginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(el.loginForm);
  const email = loginEmail();
  if (!email) return;
  const password = String(form.get("password") ?? "");
  if (!password) {
    showLoginError("Skriv ditt lösenord.");
    flagField(document.getElementById("password"));
    return;
  }
  setBusy(el.loginSubmit, true, "Loggar in …");
  try {
    const { data, error } = await supabase().auth.signInWithPassword({ email, password });
    if (error) throw error;
    await enterApp(data.session);
  } catch (error) {
    showLoginError(
      authErrorMessage(error, "Kunde inte logga in. Kontrollera e-post och lösenord."),
    );
  } finally {
    setBusy(el.loginSubmit, false);
  }
});

el.logout?.addEventListener("click", async () => {
  await supabase().auth.signOut();
  window.location.reload();
});

/* --- Vyval -------------------------------------------------------------- */

for (const tab of el.tabs) {
  tab.addEventListener("click", () => {
    showView(tab.dataset.view);
  });
}

el.moreToggle?.addEventListener("click", (event) => {
  event.stopPropagation();
  if (!el.moreMenu) return;
  const open = el.moreMenu.hidden;
  el.moreMenu.hidden = !open;
  el.moreToggle.setAttribute("aria-expanded", open ? "true" : "false");
});

el.moreMenu?.addEventListener("click", (event) => {
  const item = event.target.closest("[data-view]");
  if (!item) return;
  showView(item.dataset.view);
});

document.addEventListener("click", (event) => {
  if (!el.moreMenu || el.moreMenu.hidden) return;
  if (event.target.closest(".tab-more")) return;
  closeMoreMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMoreMenu();
});

/* --- Åtgärder ----------------------------------------------------------- */

el.view.addEventListener("submit", async (event) => {
  const form = event.target;
  if (form.classList.contains("notify-form")) {
    event.preventDefault();
    await saveNotify(form, event.submitter);
    return;
  }
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
  if (form.id === "membershipInviteForm") {
    event.preventDefault();
    await inviteAccount(form);
    return;
  }
});

/** Notiserna för en telefon eller företagets standard (src/notify_editor.js). */
async function saveNotify(form, submitter) {
  clearError();
  const body = notifyBody(form, submitter);
  if (!body) {
    showError(new ApiError(400, "Välj ett läge först.", "preset_required"));
    return;
  }
  const buttons = form.querySelectorAll('button[type="submit"]');
  for (const b of buttons) b.disabled = true;
  try {
    if (form.dataset.target === "default") {
      const result = await api.setNotifyDefault(body);
      showNotice(
        result.phonesChanged
          ? `Standarden är sparad och gäller nu ${result.phonesChanged} telefon(er).`
          : "Standarden är sparad. Nya telefoner får den när de kopplas till en bil.",
      );
    } else {
      await api.setDeviceNotify(form.dataset.device, body);
      showNotice("Notiserna är ändrade på telefonen.");
    }
    state.notify = await api.notifySettings().catch(() => state.notify);
    render();
  } catch (error) {
    showError(error);
  } finally {
    for (const b of buttons) b.disabled = false;
  }
}

/**
 * Bjud in ett konto: tilldela ett medlemskap till en e-postadress. Kontot
 * binds när personen loggar in (fleet/membership.py:claim_for_email) -- adressen
 * läses ur den verifierade inloggningen, inte ur det här formuläret.
 */
async function inviteAccount(form) {
  clearError();
  const data = new FormData(form);
  const email = String(data.get("email") ?? "").trim();
  const licenseId = String(data.get("licenseId") ?? "").trim();
  const button = form.querySelector('button[type="submit"]');
  if (!email) {
    showError(new ApiError(400, "Skriv e-postadressen till kontot.", "email_required"));
    form.querySelector('[name="email"]')?.focus();
    return;
  }
  if (!licenseId) {
    showError(new ApiError(400, "Välj vilket medlemskap kontot ska få.", "license_required"));
    return;
  }
  button.disabled = true;
  try {
    await api.assignMembership(licenseId, { mode: "email", email });
    await refresh();
    showNotice(`Medlemskapet väntar nu på ${email}. Personen loggar in i appen och tar platsen.`);
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
  const goto = event.target.closest("[data-goto]");
  if (goto) {
    event.preventDefault();
    await showView(goto.dataset.goto);
    return;
  }
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  clearError();
  const { action, license, vehicle, plate, approval, invite, user, email, status } = button.dataset;
  button.disabled = true;
  try {
    await handle(action, { license, vehicle, plate, approval, invite, user, email, status });
  } catch (error) {
    // Gränsen för länbyten: hämta om, så att "Länbyten kvar" visar rätt,
    // och visa sedan serverns förklaring.
    if (error instanceof ApiError && error.reason === "county_change_limit") await refresh();
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
    case "add-county": {
      const select = document.querySelector(`[data-county-for="${ctx.license}"]`);
      const county = select?.value;
      if (!county) return;
      return buy({ addCounties: [{ licenseId: ctx.license, county }] });
    }
    case "assign-membership-self": {
      await api.assignMembership(ctx.license, { mode: "self" });
      await refresh();
      showNotice("Platsen ligger på ditt konto.");
      return;
    }
    case "unassign-membership": {
      if (
        !confirm(
          "Ta bort tilldelningen? Platsen är kvar men inget konto använder den.",
        )
      )
        return;
      await api.unassignMembership(ctx.license);
      return refresh();
    }
    case "change-base": {
      const select = document.querySelector(`[data-county-for="${ctx.license}"]`);
      const county = select?.value;
      if (!county) return;
      if (ctx.status === "trial") {
        // Provplatsen byter direkt och utan kostnad -- ingen beställning, men
        // bytet räknas mot medlemskapets två i månaden.
        if (
          !confirm(
            `Byta baslän till ${countyName(county)}? Det gäller direkt. ` +
              "Varje medlemskap kan byta län två gånger per månad.",
          )
        )
          return;
        await api.setMembershipCounty(ctx.license, county);
        await refresh();
        showNotice(`Baslänet är nu ${countyName(county)}.`);
        return;
      }
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
      const change = continueChange();
      if (!change) return;
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
      // Ett län ur en lista och vem som håller platsen -- inget
      // registreringsnummer, inga webbläsar-popupper (se openAddMembership).
      openAddMembership();
      return;
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
 *
 * Ett enda godkännande räcker: beloppet, moms, totalsumma och datum visas i
 * bekräftelsen ovan (§6). Frågan "Öppna betalsidan nu?" togs bort -- den kom
 * efter ett ja och läste som att något gått fel. Navigeringen sker i samma flik
 * (`location.assign`), för ett `window.open` efter ett await blockeras av
 * mobilwebbläsaren. Avbryts navigeringen ligger betalsidan kvar som länk i
 * vyn efter omritningen (views.js, "Öppna betalsidan").
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
    state.orders = null;
    // Omritningen först: navigeringen lämnar sidan.
    await refresh();
    window.location.assign(result.paymentUrl);
    return;
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
 *
 * Efter godkännandet går färden rakt till betalsidan i samma flik. Den gamla
 * frågan "Öppna betalsidan nu?" låg efter ett ja och läste som att något gått
 * fel, och `window.open` efter ett await blockeras av mobilwebbläsaren.
 * Rättigheterna ges när Stripe bekräftat betalningen, inte när kunden kommer
 * tillbaka hit.
 */
/* --- Lägg till medlemskap: ett län ur en lista, inga webbläsar-popupper ----- */

/** Länen i bokstavsordning, från samma källa som resten av portalen. */
const COUNTY_OPTIONS = offerableCountyEntries()
  .map(([code, name]) => ({ code, name }))
  .sort((a, b) => a.name.localeCompare(b.name, "sv"));

function escAttr(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

function labelBuy(text) {
  el.addBuy?.querySelector(".btn-label")?.replaceChildren(text);
}

function setAddBusy(busy) {
  if (!el.addBuy) return;
  el.addBuy.disabled = busy;
  el.addBuy.classList.toggle("is-busy", busy);
  el.addBuy.setAttribute("aria-busy", busy ? "true" : "false");
}

/** Rutan för "Lägg till medlemskap": ett län och vem som håller platsen. */
function openAddMembership() {
  if (el.addCounty && !el.addCounty.options.length) {
    el.addCounty.innerHTML = COUNTY_OPTIONS.map(
      (c) => `<option value="${escAttr(c.code)}">${escAttr(c.name)}</option>`,
    ).join("");
  }
  el.addForm?.reset();
  if (el.addEmailField) el.addEmailField.hidden = true;
  if (el.addQuote) {
    el.addQuote.hidden = true;
    el.addQuote.replaceChildren();
  }
  if (el.addError) el.addError.hidden = true;
  labelBuy("Visa pris");
  state.addQuote = null;
  el.addDialog?.showModal?.();
}

/** Ändringen att köpa: ett medlemskap i ett län, kopplat till ett konto. */
function addMembershipChange() {
  const byEmail = el.addForm.elements.holder.value === "email";
  const email = el.addEmail.value.trim();
  const spec = { baseCounty: el.addCounty.value, label: "", extraCounties: [] };
  // En plats per konto: antingen kontot som köper, eller en annan e-post.
  if (byEmail && email) spec.assigneeEmail = email;
  else spec.assignSelf = true;
  return { addVehicles: [spec] };
}

/**
 * Visar resultatet av en beställning i sidan -- inte i en webbläsar-popup.
 * Väntar beställningen på betalning skickas kunden vidare till betalsidan i
 * samma flik, och länken ligger kvar i rutan som reservväg.
 *
 * Beloppet visades i steget före (offerten), så ytterligare ett klick mellan
 * godkännandet och betalsidan läste som att något gått fel. Ett `window.open`
 * efter ett await blockeras dessutom av mobilwebbläsaren -- `location.assign`
 * gör det inte.
 */
async function finishOrder(order, container) {
  state.orders = null;
  if (order.status === "pending_payment" && order.paymentUrl) {
    container.hidden = false;
    container.innerHTML =
      "<p>Beställningen väntar på betalning. Länen aktiveras när betalningen " +
      "har gått igenom. Du skickas vidare till betalsidan — öppnas den inte, " +
      "använd knappen.</p>" +
      `<a class="btn btn-primary btn-block" href="${escAttr(order.paymentUrl)}">` +
      "Öppna betalsidan</a>";
    // Omritningen först: navigeringen lämnar sidan, så rutan med reservlänken
    // måste vara ritad innan vi går vidare -- annars ser flödet ut att hänga sig.
    await refresh();
    window.location.assign(order.paymentUrl);
    return;
  }
  el.addDialog?.close();
  if (order.status === "pending_payment") {
    showNotice(
      "Beställningen är registrerad och väntar på betalning." +
        (order.paymentError?.message ? ` ${order.paymentError.message}` : ""),
    );
  } else if (order.status === "scheduled") {
    showNotice("Ändringen är schemalagd till nästa förnyelse.");
  } else {
    showNotice("Medlemskapet är beställt.");
  }
  await refresh();
}

el.addForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.addBusy) return;
  if (el.addError) el.addError.hidden = true;

  const byEmail = el.addForm.elements.holder.value === "email";
  const email = el.addEmail.value.trim();
  if (!el.addCounty.value) return;
  if (byEmail && !email) {
    el.addError.textContent = "Skriv e-postadressen till personen.";
    el.addError.hidden = false;
    return;
  }
  const change = addMembershipChange();

  state.addBusy = true;
  setAddBusy(true);
  try {
    if (!state.addQuote) {
      // Steg 1: visa beloppet i rutan. Inget beställs förrän kunden sett det.
      state.addQuote = await api.quote(change);
      el.addQuote.innerHTML = quoteHtml(state.addQuote);
      el.addQuote.hidden = false;
      labelBuy("Godkänn och skapa");
      return;
    }
    // Steg 2: beloppet är visat. Lägg beställningen.
    const order = await api.order(change);
    state.addQuote = null;
    await finishOrder(order, el.addQuote);
  } catch (error) {
    el.addError.textContent =
      error instanceof ApiError ? error.message : "Kunde inte hämta priset. Prova igen.";
    el.addError.hidden = false;
  } finally {
    state.addBusy = false;
    setAddBusy(false);
  }
});

for (const radio of el.addForm?.elements.holder ?? []) {
  radio.addEventListener("change", () => {
    if (el.addEmailField) el.addEmailField.hidden = el.addForm.elements.holder.value !== "email";
  });
}

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-dialog]")) el.addDialog?.close();
});

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
    // Beställningen är lagd och beloppet är godkänt. Rakt till betalsidan i
    // samma flik -- reservlänken ligger kvar i rutan bakom.
    state.orders = null;
    await refresh();
    window.location.assign(order.paymentUrl);
    return;
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
