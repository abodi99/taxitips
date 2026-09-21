import { ApiError, supabase } from "../portal/api.js";
import { admin } from "./api.js";
import * as views from "./views.js";

/**
 * Adminwebbens sammanhållning.
 *
 * Inloggningen är densamma som kundportalens (Supabase Auth). Vad inloggningen
 * GER avgörs av servern: utan en aktiv StaffRole svarar varje anrop
 * `not_staff`, och då visas bara det meddelandet. Ingen del av gränssnittet
 * "låtsas" att den som loggat in är admin.
 *
 * Varje ändring bekräftas först och loggas av servern med vem som gjorde den.
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
  codeDialog: document.getElementById("codeDialog"),
  codeValue: document.getElementById("codeValue"),
  codeFor: document.getElementById("codeFor"),
};

const state = {
  view: "oversikt",
  companyId: null,
  query: "",
  pushStatus: "",
  eventQuery: "",
  eventHidden: false,
};

function showError(error) {
  const message = error instanceof ApiError ? error.message : "Något gick fel. Prova igen.";
  el.globalError.textContent = message;
  el.globalError.hidden = false;
}

function clearError() {
  el.globalError.hidden = true;
}

function setTab(view) {
  for (const tab of el.tabs) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === view));
  }
}

async function render() {
  clearError();
  el.view.innerHTML = '<p class="muted">Laddar …</p>';
  try {
    if (state.companyId) {
      el.view.innerHTML = views.kund(await admin.company(state.companyId));
      return;
    }
    switch (state.view) {
      case "oversikt":
        el.view.innerHTML = views.oversikt(await admin.overview());
        break;
      case "kunder":
        el.view.innerHTML = views.kunder(await admin.companies(state.query), state.query);
        break;
      case "abonnemang":
        el.view.innerHTML = views.abonnemang(await admin.companies());
        break;
      case "notiser":
        el.view.innerHTML = views.notiser(await admin.notifications(state.pushStatus), state.pushStatus);
        break;
      case "evenemang":
        el.view.innerHTML = views.evenemang(
          await admin.events(state.eventQuery, state.eventHidden),
          state.eventQuery,
          state.eventHidden,
        );
        break;
      case "granskning":
        el.view.innerHTML = views.granskning(await admin.reviews("open"));
        break;
      default:
        el.view.innerHTML = "";
    }
  } catch (error) {
    el.view.innerHTML = "";
    if (error instanceof ApiError && error.reason === "not_staff") {
      el.view.innerHTML = `<div class="card"><h2>Ingen adminbehörighet</h2>
        <p>Kontot är inloggat men har ingen roll i plattformens personal.
        Kunder använder <a href="/portal">kundportalen</a>.</p></div>`;
      return;
    }
    showError(error);
  }
}

/* --- Inloggning ------------------------------------------------------- */

const EMAIL_KEY = "tt_admin_email";

/**
 * Förifyller e-posten. Från `?email=` i adressen (en länk man kan spara som
 * bokmärke), annars den som senast loggade in i den här webbläsaren.
 *
 * Aldrig inskriven i själva sidan: admin.taxitips.se är publik, och en
 * förifylld adress i HTML:en hade talat om för vem som helst vilket
 * användarnamn som är administratörens.
 */
function prefillEmail() {
  const input = document.getElementById("email");
  if (!input || input.value) return;
  const fromUrl = new URLSearchParams(window.location.search).get("email");
  let remembered = "";
  try {
    remembered = window.localStorage.getItem(EMAIL_KEY) || "";
  } catch {
    /* privat läge eller blockerad lagring: inget att förifylla */
  }
  input.value = fromUrl || remembered;
  if (input.value) document.getElementById("password")?.focus();
}

function rememberEmail(email) {
  try {
    if (email) window.localStorage.setItem(EMAIL_KEY, email);
  } catch {
    /* bekvämlighet, inte funktion */
  }
}

async function boot() {
  prefillEmail();
  const { data } = await supabase().auth.getSession();
  if (data?.session) return enterApp(data.session);
  el.login.hidden = false;
}

async function enterApp(session) {
  el.login.hidden = true;
  el.app.hidden = false;
  el.logout.hidden = false;
  document.getElementById("changePassword").hidden = false;
  el.whoami.textContent = session.user?.email ?? "";
  rememberEmail(session.user?.email);
  await render();
}

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
    el.loginError.textContent = error?.message ?? "Kunde inte logga in.";
    el.loginError.hidden = false;
  }
});

/**
 * Inloggningslänk via e-post.
 *
 * Konton som skapats med Google har inget lösenord, och Google-inloggning är
 * inte konfigurerad i produktionens Supabase Auth. En länk till den verifierade
 * adressen loggar in samma konto -- GoTrue matchar på e-post -- utan att något
 * lösenord behöver sättas eller skickas någonstans.
 *
 * `shouldCreateUser: false`: adminwebben skapar aldrig konton. Att någon kan
 * begära en länk till en okänd adress får inte bli ett sätt att registrera sig.
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

// Länken landar här med sessionen i URL:en. Supabase-klienten plockar upp den
// själv (detectSessionInUrl); det här ser bara till att appen visas direkt.
supabase().auth.onAuthStateChange((event, session) => {
  if (event === "SIGNED_IN" && session && el.app.hidden) {
    enterApp(session);
  }
});

document.getElementById("changePassword")?.addEventListener("click", async () => {
  const first = prompt("Nytt lösenord (minst 12 tecken):");
  if (first === null) return;
  if (first.length < 12) {
    alert("Lösenordet måste vara minst 12 tecken.");
    return;
  }
  const second = prompt("Skriv det nya lösenordet igen:");
  if (second === null) return;
  if (first !== second) {
    alert("Lösenorden stämmer inte överens. Inget ändrades.");
    return;
  }
  try {
    const { error } = await supabase().auth.updateUser({ password: first });
    if (error) throw error;
    alert("Lösenordet är bytt.");
  } catch (error) {
    alert(error?.message ?? "Kunde inte byta lösenord.");
  }
});

el.logout?.addEventListener("click", async () => {
  await supabase().auth.signOut();
  window.location.reload();
});

/* --- Navigering ------------------------------------------------------- */

for (const tab of el.tabs) {
  tab.addEventListener("click", () => {
    state.view = tab.dataset.view;
    state.companyId = null;
    setTab(state.view);
    render();
  });
}

el.view.addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.target.id === "searchForm") {
    state.query = new FormData(event.target).get("q")?.toString().trim() ?? "";
  } else if (event.target.id === "eventForm") {
    state.eventQuery = document.getElementById("eq")?.value.trim() ?? "";
    state.eventHidden = document.getElementById("ehidden")?.checked ?? false;
  }
  render();
});

el.view.addEventListener("change", (event) => {
  if (event.target.id === "pushStatus") {
    state.pushStatus = event.target.value;
    render();
  }
});

el.view.addEventListener("click", async (event) => {
  const row = event.target.closest("[data-company]");
  if (row && !event.target.closest("button")) {
    state.companyId = row.dataset.company;
    return render();
  }
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  clearError();
  button.disabled = true;
  try {
    await act(button.dataset.action, button.dataset);
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
  }
});

/* --- Åtgärder --------------------------------------------------------- */

async function act(action, ds) {
  switch (action) {
    case "back":
      state.companyId = null;
      return render();

    case "extend": {
      const days = Number(ds.days);
      const note = prompt(
        `Förläng perioden med ${days} dagar.\n\nÄndrar appens rättigheter, inte Stripe. ` +
          "Ange ett skäl (sparas i loggen):",
      );
      if (note === null) return;
      await admin.setSubscription(state.companyId, { extendDays: days, note });
      return render();
    }

    case "code": {
      const result = await admin.pairingCode(state.companyId, ds.license);
      el.codeFor.textContent = `För ${ds.plate || "bilen"}.`;
      el.codeValue.textContent = result.code;
      el.codeDialog.showModal();
      return;
    }

    case "block": {
      if (!confirm("Spärra telefonen? Den slutar visa tips direkt och lämnar bilen.")) return;
      await admin.blockPhone(ds.approval, "admin_block");
      return render();
    }

    case "test-push": {
      const result = await admin.testPush(state.companyId);
      const lines = (result.results ?? []).map(
        (r) => `${r.device}: ${r.sent ? "skickad" : `inte skickad (${r.reason})`}`,
      );
      alert(lines.length ? lines.join("\n") : "Bolaget har inga telefoner.");
      return;
    }

    case "event-hide": {
      const reason = prompt("Varför döljs evenemanget för förarna?");
      if (!reason) return;
      await admin.setEventVisibility(Number(ds.event), true, reason);
      return render();
    }

    case "event-show":
      await admin.setEventVisibility(Number(ds.event), false);
      return render();

    case "review-approve":
    case "review-reject": {
      const approved = action === "review-approve";
      const note = prompt(approved ? "Godkänn — anteckning:" : "Avslå — skäl:");
      if (note === null) return;
      await admin.resolveReview(ds.review, approved, note);
      return render();
    }

    default:
      return;
  }
}

boot().catch((error) => {
  el.login.hidden = false;
  showError(error);
});
