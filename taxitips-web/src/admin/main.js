import { promptAndSetPassword, sendPasswordReset } from "../auth_password.js";
import { ApiError, supabase } from "../portal/api.js";
import * as acc from "./accounts.js";
import * as activity from "./activity.js";
import { callsCell, followUpBody, nextCell, uppfoljning } from "./followup.js";
import { admin } from "./api.js";
import * as sales from "./sales.js";
import { LEVEL, statusBanner, statusView } from "./status.js";
import { appVersionCard, bindAppVersionForm, loadAppVersion } from "./app_version.js";
import * as support from "./support.js";
import * as tipReports from "./tip_reports.js";
import {
  EMPTY_PIPELINE_FILTERS,
  nextSort,
  pipelineNewLeadPrompt,
  pipelineTags,
  pipelineView,
  tasksView,
} from "./crm.js";
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

/** Rader per sida i CRM-tabellen; "Visa fler" hämtar nästa portion. */
const PIPELINE_PAGE = 200;

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
  codeTimer: document.getElementById("codeTimer"),
};

const state = {
  view: "oversikt",
  companyId: null,
  query: "",
  pushStatus: "",
  // Evenemangens filter, och en vald fil som väntar på att sparas.
  events: { q: "", hidden: false, days: 14, source: "", open: "" },
  eventImport: null,
  accountQuery: "",
  accountUserId: null,
  accountRecovery: null,
  // Kundens cykel: vilket steg som är öppet, och listans filter.
  companyTab: "",
  kundFilter: "alla",
  fuFilter: "ring",
  // En betald bils ändring som väntar på kundens godkännande: offerten visas
  // i bilens kort tills säljaren bekräftar eller avbryter.
  pending: null,
  // Säljflödet: län, prislista, Stripe-läge och vad den inloggade får göra.
  config: null,
  lookup: null,
  lookupOrg: "",
  // Den senaste offerten, så att beställningen skickar exakt det kunden hörde.
  quotedChange: null,
  // Inloggningslänk som personalen just skapat åt en av kundens inloggningar.
  companyLoginLink: null,
  // Supportchatten: en konversation att öppna direkt (från kundsidan).
  supportThread: null,
  // Senaste statusrapporten (menyns prick och Hems varning), och om nästa
  // hämtning ska köra om kontrollerna i stället för att ta serverns cache.
  status: null,
  statusFresh: false,
  companyCrm: null,
  pipelineLead: null,
  pipelineStageFilter: "",
  pipelineQuery: "",
  // Segment, län, tier, bolagsform, ort, ☎/@/TF — AND:as på servern.
  pipelineFilters: { ...EMPTY_PIPELINE_FILTERS },
  pipelineLimit: PIPELINE_PAGE,
  pipelineSort: "-updated",
  // CRM-underflik: "pipeline" eller "tasks" (uppgiftsöversikten).
  crmTab: "pipeline",
  taskFilters: { assignee: "me", status: "open" },
  // Sökning efter befintlig kontakt att koppla i affärsvyn: { q, hits }.
  crmPeople: null,
  crmDealId: null,
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
    if (tab.dataset.view === view) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
}

async function render() {
  const seq = ++renderSeq;
  clearError();
  el.view.innerHTML = '<p class="muted">Laddar …</p>';
  const note = state.flash;
  state.flash = null;
  try {
    await renderView(seq);
  } finally {
    if (note && seq === renderSeq) {
      el.view.insertAdjacentHTML("afterbegin", `<p class="ok flash" role="status">${sales.esc(note)}</p>`);
    }
  }
}

/**
 * Varje navigering får ett nummer, och bara den senaste får rita. Utan det
 * vann den som svarade SIST: Hem (tre anrop) laddade fortfarande när man
 * klickade på Support, och när Hem till slut svarade skrevs supportsidan över
 * -- menyn stod på Support men svarsrutan var borta (2026-09-26).
 */
let renderSeq = 0;

async function renderView(seq) {
  const current = () => seq === renderSeq;
  const paint = (html) => {
    if (current()) el.view.innerHTML = html;
  };
  // Supportsidan hämtar i bakgrunden; den ska sluta när man går därifrån.
  support.stop();
  try {
    if (!state.config) state.config = await admin.salesConfig();
    if (state.companyId) {
      const [detail, crm] = await Promise.all([
        admin.company(state.companyId),
        admin.companyCrm(state.companyId).catch(() => null),
      ]);
      state.companyCrm = crm;
      paint(views.kund(
        detail, state.config, state.companyTab, state.pending, crm, state.companyLoginLink,
      ));
      // Under Historik: företagets appar och fel (activity.js), hämtas när rutan öppnas.
      if (views.kundTab(state.companyTab) === "historik") {
        activity.companyPanel(el.view, state.companyId, { isCurrent: current });
      }
      return;
    }
    switch (state.view) {
      case "oversikt": {
        const [overview, list, sup, tipRep] = await Promise.all([
          admin.overview(), admin.companies(),
          // Hem ska fungera även om supporten inte svarar.
          admin.supportSummary().catch(() => ({ waiting: 0 })),
          admin.tipReportsSummary().catch(() => ({ open: 0 })),
        ]);
        setSupportCount(sup.waiting ?? 0);
        setTipReportCount(tipRep.open ?? overview.tipReportsOpen ?? 0);
        paint(statusBanner(state.status) + views.oversikt(overview, list, sup.waiting ?? 0));
        break;
      }
      case "status": {
        const fresh = state.statusFresh;
        state.statusFresh = false;
        const [report, appVersion] = await Promise.all([admin.status(fresh), loadAppVersion()]);
        setStatus(report);
        paint(statusView(report) + appVersionCard(appVersion, !!state.config?.canManage));
        break;
      }
      case "support":
        if (!current()) return;
        support.mount(el.view, {
          threadId: state.supportThread,
          onOpenCompany: (id) => {
            state.companyId = id;
            state.companyTab = "";
            state.view = "kunder";
            setTab("kunder");
            render();
          },
          onError: showError,
          onWaiting: setSupportCount,
        });
        state.supportThread = null;
        break;
      case "kunder":
        paint(views.kunder(
          await admin.companies(state.query, state.kundFilter === "arkiverade"),
          state.query, state.kundFilter,
        ));
        break;
      case "uppfoljning":
        paint(uppfoljning(await admin.followUps(), state.fuFilter));
        break;
      case "pipeline": {
        if (state.crmDealId) {
          paint(pipelineView(
            {},
            state.config,
            { peopleQuery: state.crmPeople?.q, peopleHits: state.crmPeople?.hits },
            await admin.crmDeal(state.crmDealId),
          ));
        } else if (state.crmTab === "tasks") {
          paint(tasksView(await admin.crmTasks(state.taskFilters), state.config));
        } else {
          const f = state.pipelineFilters;
          paint(pipelineView(
            await admin.crmPipeline({
              stage: state.pipelineStageFilter,
              q: state.pipelineQuery,
              tags: pipelineTags(f),
              city: f.city,
              form: f.form,
              phone: f.phone,
              email: f.email,
              sort: state.pipelineSort,
              limit: state.pipelineLimit,
            }),
            state.config,
            {
              stage: state.pipelineStageFilter,
              q: state.pipelineQuery,
              filters: f,
              sort: state.pipelineSort,
            },
          ));
        }
        break;
      }
      case "nykund":
        paint(sales.nyKund(state.config, state.lookup, state.lookupOrg, state.pipelineLead));
        break;
      case "kuponger":
        paint(sales.kuponger(await admin.coupons(), state.config));
        break;
      case "notiser":
        paint(views.notiser(await admin.notifications(state.pushStatus), state.pushStatus));
        break;
      case "evenemang":
        paint(views.evenemang(
          await admin.events(state.events), state.events, state.config, state.eventImport,
        ));
        break;
      case "konton": {
        if (state.accountUserId) {
          const body = await admin.account(state.accountUserId);
          paint(acc.konto(body.account, state.config, state.accountRecovery, {
            devices: body.devices,
            deviceSwaps: body.deviceSwaps,
            notifications: body.notifications,
            favorites: body.favorites,
            feedback: body.feedback,
            tipReports: body.tipReports,
            feedbackSummary: body.feedbackSummary,
            errors: body.errors,
            audit: body.audit,
          }));
          break;
        }
        const q = state.accountQuery;
        const [found, blocks] = await Promise.all([admin.accounts(q), admin.blocks()]);
        paint(acc.konton(found, blocks, q, state.config));
        break;
      }
      case "personal":
        paint(acc.personal(await admin.staff(), state.config));
        break;
      case "aktivitet":
        // Egen vy med egna filter och händelser, se activity.js.
        await activity.mount(el.view, { isCurrent: current, onError: showError });
        break;
      case "granskning":
        paint(views.granskning(await admin.reviews("open")));
        break;
      case "tipprapporter":
        if (!current()) return;
        await tipReports.mount(el.view, {
          onError: showError,
          onOpenChange: setTipReportCount,
        });
        break;
      default:
        paint("");
    }
  } catch (error) {
    if (!current()) return;
    paint("");
    if (error instanceof ApiError && error.reason === "not_staff") {
      paint(`<div class="card"><h2>Ingen adminbehörighet</h2>
        <p>Kontot är inloggat men har ingen roll i plattformens personal.
        Kunder använder <a href="/portal">kundportalen</a>.</p></div>`);
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
  showAuthHashError();
}

// Inloggningen triggar både formulärets svar och `onAuthStateChange`; appen
// ska bara startas en gång, annars renderas allt två gånger i otakt.
let entered = false;

/**
 * Räknaren på Support i menyn: frågor som väntar på svar. Hämtas var 30:e
 * sekund medan fliken syns, så att en ny fråga märks utan att man står på
 * supportsidan.
 */
function setSupportCount(n) {
  const badge = document.getElementById("supportCount");
  if (!badge) return;
  badge.textContent = String(n);
  badge.hidden = !n;
}

function setTipReportCount(n) {
  const badge = document.getElementById("tipReportCount");
  if (!badge) return;
  badge.textContent = String(n);
  badge.hidden = !n;
}

async function refreshSupportCount() {
  if (document.hidden) return;
  try {
    setSupportCount((await admin.supportSummary()).waiting ?? 0);
  } catch {
    // Räknaren är en hjälp, inte ett felmeddelande.
  }
}

async function refreshTipReportCount() {
  if (document.hidden) return;
  try {
    setTipReportCount((await admin.tipReportsSummary()).open ?? 0);
  } catch {
    // Räknaren är en hjälp, inte ett felmeddelande.
  }
}

/**
 * Prick i menyn: grön, gul eller röd efter senaste statusrapporten. Hämtas i
 * bakgrunden varannan minut, så att ett fel syns var man än är i adminwebben
 * -- inte först när någon råkar öppna Status.
 */
function setStatus(report) {
  state.status = report;
  const dot = document.getElementById("statusDot");
  if (!dot || !report) return;
  dot.className = `st-dot st-nav st-${report.overall}`;
  dot.setAttribute("aria-label", LEVEL[report.overall]?.[0] ?? "");
  dot.hidden = false;
}

async function refreshStatus() {
  if (document.hidden) return;
  try {
    setStatus(await admin.status());
  } catch {
    // Prickens hämtning får aldrig visa ett fel ovanpå en annan vy.
  }
}

async function enterApp(session) {
  if (entered) return;
  entered = true;
  refreshSupportCount();
  setInterval(refreshSupportCount, 30_000);
  refreshTipReportCount();
  setInterval(refreshTipReportCount, 60_000);
  refreshStatus();
  setInterval(refreshStatus, 120_000);
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
 * Lokal debug-inloggning. Vite sätter `import.meta.env.DEV` bara under
 * `npm run dev` — hela blocket (knapp + lösenord) plockas bort i prod-bygget.
 * Kontot skapas lokalt: admin@taxitips.local / taxitips-admin-dev + StaffRole.
 */
if (import.meta.env.DEV) {
  const DEV_EMAIL = "admin@taxitips.local";
  const DEV_PASSWORD = "taxitips-admin-dev";
  const mount = document.getElementById("devLogin");
  if (mount) {
    mount.hidden = false;
    mount.innerHTML = `
      <p class="muted" style="margin:1rem 0 0.4rem">Lokal utveckling</p>
      <button id="devLoginBtn" class="btn btn-primary" type="button">
        Logga in som lokal admin
      </button>
      <p class="muted" style="margin-top:0.4rem;font-size:0.85rem">
        ${DEV_EMAIL} — syns bara i Vite-dev, inte i produktionsbygget.
      </p>`;
    document.getElementById("devLoginBtn")?.addEventListener("click", async () => {
      el.loginError.hidden = true;
      const emailInput = el.loginForm?.querySelector('[name="email"]');
      const passInput = el.loginForm?.querySelector('[name="password"]');
      if (emailInput) emailInput.value = DEV_EMAIL;
      if (passInput) passInput.value = DEV_PASSWORD;
      try {
        const { data, error } = await supabase().auth.signInWithPassword({
          email: DEV_EMAIL,
          password: DEV_PASSWORD,
        });
        if (error) throw error;
        await enterApp(data.session);
      } catch (error) {
        el.loginError.textContent =
          error?.message ??
          "Kunde inte logga in. Kör seed/StaffRole för admin@taxitips.local.";
        el.loginError.hidden = false;
      }
    });
  }
}

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

// Återställningsmejlet landar här med en engångssession. PASSWORD_RECOVERY
// betyder "sätt nytt lösenord nu" -- utan det ser det ut som vanlig inloggning.
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

document.getElementById("changePassword")?.addEventListener("click", async () => {
  try {
    await promptAndSetPassword(supabase());
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
    state.companyTab = "";
    if (state.view === "konton") {
      state.accountUserId = null;
      state.accountRecovery = null;
    }
    setTab(state.view);
    render();
  });
}

bindAppVersionForm(el.view);

el.view.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  clearError();
  if (form.dataset.crmForm) {
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try {
      if (await crmSubmit(form)) await render();
    } catch (error) {
      showError(error);
    } finally {
      if (button) button.disabled = false;
    }
    return;
  }
  if (form.dataset.form === "followup") {
    // Ingen omritning av hela listan: säljaren står mitt i den.
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try {
      const saved = await admin.updateFollowUp(form.dataset.fuCompany, followUpBody(form));
      // Uppdatera bara raden och fäll ihop den — listan ligger kvar.
      const tr = el.view.querySelector(`tr[data-fu-row="${form.dataset.fuCompany}"]`);
      if (tr) {
        const labels = new Map(JSON.parse(tr.closest("table")?.dataset.outcomes || "[]"));
        const cell = (k) => tr.querySelector(`[data-fu-cell="${k}"]`);
        if (cell("outcome")) cell("outcome").textContent = labels.get(saved.outcome) ?? saved.outcome;
        if (cell("next")) cell("next").innerHTML = nextCell(saved.nextContactAt);
        if (cell("calls")) cell("calls").innerHTML = callsCell(saved.attempts, new Date().toISOString());
        tr.classList.add("fu-saved");
        toggleFollowUp(form.dataset.fuCompany, false);
      }
      const box = form.querySelector('input[name="contacted"]');
      if (box) box.checked = true;
    } catch (error) {
      showError(error);
    } finally {
      if (button) button.disabled = false;
    }
    return;
  }
  try {
    switch (form.id) {
      case "searchForm":
        state.query = new FormData(form).get("q")?.toString().trim() ?? "";
        break;
      case "eventForm":
        state.events = {
          ...state.events,
          q: document.getElementById("eq")?.value.trim() ?? "",
          hidden: document.getElementById("ehidden")?.checked ?? false,
          source: document.getElementById("esource")?.value ?? "",
          days: Number(document.getElementById("edays")?.value || 14),
          open: "",
        };
        break;
      case "eventNewForm": {
        await admin.createEvent(eventBody(form));
        state.events = { ...state.events, source: "manual", open: "" };
        flash("Evenemanget är sparat och syns för förarna i det länet.");
        break;
      }
      case "accountSearch":
        state.accountQuery = new FormData(form).get("q")?.toString().trim() ?? "";
        break;
      case "blockEmailForm": {
        const data = new FormData(form);
        await admin.block("email", String(data.get("email") ?? ""), String(data.get("reason") ?? ""));
        flash("Adressen är spärrad.");
        break;
      }
      case "staffForm": {
        const data = new FormData(form);
        await admin.setStaff(String(data.get("email") ?? ""), String(data.get("role") ?? ""));
        flash("Rollen är sparad. Den gäller från personens nästa sidladdning.");
        break;
      }
      case "lookupForm":
        state.lookupOrg = new FormData(form).get("orgNumber")?.toString().trim() ?? "";
        state.lookup = await admin.lookup(state.lookupOrg);
        break;
      case "companyForm": {
        const created = await admin.createCompany(sales.companyBody(form));
        const lead = state.pipelineLead;
        if (lead?.leadId) {
          await admin.crmLinkLeadCompany(lead.leadId, {
            companyId: created.companyId,
            stage: "won",
          }).catch(() => null);
        }
        state.pipelineLead = null;
        state.lookup = null;
        state.lookupOrg = "";
        state.companyId = created.companyId;
        // Företaget är upplagt och kontrollerat av säljaren: nästa steg är bilarna.
        state.companyTab = "bilar";
        state.view = "kunder";
        setTab("kunder");
        flash("Företaget är upplagt. Lägg till bilarna.");
        break;
      }
      case "crmNoteForm": {
        const data = new FormData(form);
        await admin.crmNote(state.companyId, {
          title: String(data.get("title") ?? "Anteckning"),
          body: String(data.get("body") ?? ""),
        });
        flash("Anteckningen sparades.");
        break;
      }
      case "crmSearchForm": {
        const data = new FormData(form);
        state.pipelineQuery = String(data.get("q") ?? "").trim();
        state.pipelineLimit = PIPELINE_PAGE;
        state.crmDealId = null;
        break;
      }
      case "crmDealNoteForm": {
        const data = new FormData(form);
        const dealId = form.dataset.deal || state.crmDealId;
        await admin.crmDealNote(dealId, {
          title: String(data.get("title") ?? "Anteckning"),
          body: String(data.get("body") ?? ""),
        });
        flash("Anteckningen sparades.");
        break;
      }
      case "profileForm":
        await admin.updateProfile(state.companyId, sales.profileBody(form));
        flash("Uppgifterna är sparade.");
        break;
      case "couponForm": {
        const result = await admin.createCoupon(sales.couponBody(form));
        flash(`Kupongen ${result.coupon.code} är skapad.`);
        break;
      }
      case "discountForm": {
        await admin.setDiscount(state.companyId, sales.discountBody(form));
        flash("Prisrabatten är sparad.");
        break;
      }
      default:
        return;
    }
  } catch (error) {
    showError(error);
    return;
  }
  render();
});

/** Ett kort kvitto överst, som försvinner vid nästa åtgärd. */
function flash(message) {
  state.flash = message;
}

el.view.addEventListener("change", (event) => {
  if (event.target.id === "pushStatus") {
    state.pushStatus = event.target.value;
    render();
    return;
  }
  const taskId = event.target.dataset?.taskStatus;
  if (taskId) {
    admin.crmTaskUpdate(taskId, { status: event.target.value })
      .then(() => render())
      .catch(showError);
    return;
  }
  if (event.target.dataset?.crmTasks === "assignee") {
    state.taskFilters = { ...state.taskFilters, assignee: event.target.value };
    render();
    return;
  }
  const key = event.target.dataset?.crmFilter;
  if (key && key in state.pipelineFilters) {
    state.pipelineFilters = { ...state.pipelineFilters, [key]: event.target.value.trim() };
    state.pipelineLimit = PIPELINE_PAGE;
    render();
  }
});

el.view.addEventListener("click", async (event) => {
  const row = event.target.closest("[data-company]");
  if (row && !event.target.closest("button")) {
    state.companyId = row.dataset.company;
    state.quotedChange = null;
    return render();
  }
  // Ring/maila direkt från CRM-raden utan att raden öppnas.
  if (event.target.closest("a[href^='tel:'], a[href^='mailto:']")) return;
  const button = event.target.closest("[data-action]");
  if (!button) return;
  if (button.tagName === "A") event.preventDefault();
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

/**
 * CRM-formulär med data-crm-form (flera per sida, så inte id). Returnerar
 * true när vyn ska ritas om.
 */
async function crmSubmit(form) {
  const data = new FormData(form);
  const val = (k) => String(data.get(k) ?? "").trim();
  const ds = form.dataset;
  switch (ds.crmForm) {
    case "task-new":
      await admin.crmTaskCreate({
        title: val("title"),
        dueDate: val("dueDate"),
        assigneeUserId: val("assigneeUserId"),
        dealId: ds.deal || undefined,
        companyId: ds.customer || undefined,
      });
      flash("Uppgiften lades till.");
      return true;
    case "task-edit":
      await admin.crmTaskUpdate(ds.task, {
        title: val("title"),
        body: val("body"),
        dueDate: val("dueDate"),
        assigneeUserId: val("assigneeUserId"),
      });
      flash("Uppgiften sparades.");
      return true;
    case "note-edit":
      await admin.crmNoteUpdate(ds.note, { title: val("title"), body: val("body") });
      flash("Anteckningen ändrades.");
      return true;
    case "contact-new":
      await admin.crmContactAdd(ds.deal, {
        name: val("name"), title: val("title"), phone: val("phone"), email: val("email"),
      });
      flash("Kontakten sparades.");
      return true;
    case "contact-edit":
      await admin.crmPersonUpdate(ds.person, {
        name: val("name"), title: val("title"), phone: val("phone"), email: val("email"),
      });
      flash("Kontakten sparades.");
      return true;
    case "contact-search": {
      const q = val("q");
      const res = q.length >= 2 ? await admin.crmPeopleSearch(q, ds.account) : { rows: [] };
      state.crmPeople = { q, hits: res.rows ?? [] };
      return true;
    }
    default:
      return false;
  }
}

/** Fäll ut/ihop samtalsraden i uppföljningen utan omritning. */
function toggleFollowUp(companyId, open) {
  const detail = document.getElementById(`fu-detail-${companyId}`);
  const button = el.view.querySelector(`.fu-toggle[data-company="${companyId}"]`);
  if (!detail) return;
  const show = open ?? detail.hidden;
  detail.hidden = !show;
  button?.setAttribute("aria-expanded", String(show));
  if (button) button.textContent = show ? "Stäng" : "Logga samtal";
  detail.previousElementSibling?.classList.toggle("is-open", show);
  if (show) detail.querySelector("select, textarea")?.focus();
}

/* --- Åtgärder --------------------------------------------------------- */

async function act(action, ds) {
  switch (action) {
    case "back":
      state.companyId = null;
      state.companyTab = "";
      state.pending = null;
      state.companyLoginLink = null;
      return render();

    case "kund-tab":
      state.companyTab = ds.tab;
      state.pending = null;
      state.companyLoginLink = null;
      await render();
      window.scrollTo({ top: 0 });
      return;

    case "kund-filter":
      state.kundFilter = ds.filter;
      return render();

    case "fu-filter":
      state.fuFilter = ds.filter;
      return render();

    case "fu-toggle":
      toggleFollowUp(ds.company);
      return;

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

    case "code":
      return driverCode(ds.license, ds.plate);

    case "block": {
      if (!confirm(`Spärra ${ds.label || "telefonen"}? Den slutar visa tips direkt och lämnar bilen.\n\n` +
        "Föraren behöver en ny inbjudan för att köra igen.")) return;
      await admin.blockPhone(ds.approval, "admin_block");
      flash(`${ds.label || "Telefonen"} är spärrad.`);
      return render();
    }

    /* --- Supportåtgärder på kundsidan --- */

    case "car-release": {
      const reason = prompt(
        `Frigör ${ds.plate}? ${ds.holder} lämnar bilen, så att en annan förare kan ta den.\n\n` +
          "Telefonen får fortfarande köra bilen igen. Skäl (sparas i loggen):",
        "Föraren glömde lämna bilen",
      );
      if (reason === null) return;
      const result = await admin.releaseCar(ds.license, reason.trim());
      flash(result.released ? `${ds.plate} är frigjord.` : `Ingen körde ${ds.plate}.`);
      return render();
    }

    case "phone-rename": {
      const label = prompt("Nytt namn på telefonen (syns under bilen och i appen):", ds.label || "");
      if (!label?.trim()) return;
      await admin.renamePhone(ds.approval, label.trim());
      flash(`Telefonen heter nu ${label.trim()}.`);
      return render();
    }

    case "driver-invite": {
      const email = prompt(`Förarens e-post för ${ds.plate}?\n\nFöraren trycker "Jag är förare" i appen, skriver sin e-post och får en kod i mejlet. Inbjudan gäller i 7 dagar.`);
      if (!email?.trim()) return;
      const label = prompt("Förarens namn (visas som telefonens namn):", "") ?? "";
      await admin.inviteDriver(state.companyId, ds.license, email.trim(), label.trim());
      flash(`Inbjudan är skickad till ${email.trim()}.`);
      return render();
    }

    case "driver-invite-resend":
      await admin.resendDriverInvite(ds.invite);
      flash("Inbjudan är skickad igen och gäller sju nya dagar.");
      return render();

    case "driver-invite-revoke":
      if (!confirm(`Återkalla inbjudan till ${ds.email}?`)) return;
      await admin.revokeDriverInvite(ds.invite);
      flash("Inbjudan är återkallad.");
      return render();

    case "member-login-link": {
      const result = await admin.accountRecovery(ds.user, portalUrl());
      state.companyLoginLink = result;
      flash("Inloggningslänken är skapad. Kopiera och skicka den till personen.");
      return render();
    }

    case "copy-login-link": {
      const url = document.getElementById("loginLinkUrl")?.textContent?.trim();
      if (!url) return;
      await navigator.clipboard.writeText(url);
      flash("Länken är kopierad.");
      return;
    }

    case "member-role": {
      const what = {
        company_owner: "ägare. Ägaren kan beställa, säga upp och hantera inloggningar",
        fleet_admin: "Bilar och förare. Hen sköter bilar, län och förartelefoner men inte betalning",
        finance: "Ekonomi. Hen ser och betalar fakturor men ändrar inte bilar eller förare",
      }[ds.role];
      if (!confirm(`Ändra rollen till ${what}?`)) return;
      await admin.setMember(state.companyId, ds.user, { role: ds.role });
      flash(`Rollen är ändrad till ${views.MEMBER_ROLE[ds.role] ?? ds.role}.`);
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

    case "event-delete":
      if (!confirm(`Ta bort "${ds.name}"? Det försvinner för förarna direkt.`)) return;
      await admin.deleteEvent(Number(ds.event));
      flash("Evenemanget är borttaget.");
      return render();

    case "event-import": {
      const pending = state.eventImport;
      if (!pending?.content) return;
      const result = await admin.importEvents(pending.filename, pending.content, false);
      state.eventImport = null;
      state.events = { ...state.events, source: "manual" };
      flash(`${result.created} nya och ${result.updated} uppdaterade evenemang är sparade.`);
      return render();
    }

    case "event-import-cancel":
      state.eventImport = null;
      return render();

    case "event-template":
      return downloadTemplate();

    case "registry-refresh": {
      const overwrite = ds.overwrite === "1";
      if (overwrite && !confirm("Ersätta fakturaadressen med adressen hos Bolagsverket?")) return;
      const result = await admin.refreshRegistry(state.companyId, overwrite);
      const r = result.registry;
      flash(r.found
        ? `Hämtat från Bolagsverket: ${r.name} (${r.statusText}).`
        : "Bolagsverket har inget bolag med det numret.");
      return render();
    }

    case "support-start": {
      const started = await admin.supportStart(state.companyId);
      state.supportThread = started.thread.id;
      state.companyId = null;
      state.companyTab = "";
      state.view = "support";
      setTab("support");
      return render();
    }

    case "status-refresh":
      state.statusFresh = true;
      return render();

    case "goto":
      state.view = ds.view;
      state.companyId = null;
      state.companyTab = "";
      setTab(ds.view === "nykund" ? "kunder" : ds.view);
      return render();

    case "pipeline-filter":
      state.pipelineStageFilter = ds.stage ?? "";
      state.pipelineLimit = PIPELINE_PAGE;
      state.crmDealId = null;
      return render();

    case "pipeline-toggle":
      state.pipelineFilters = {
        ...state.pipelineFilters,
        [ds.key]: !state.pipelineFilters[ds.key],
      };
      state.pipelineLimit = PIPELINE_PAGE;
      return render();

    case "pipeline-clear":
      state.pipelineFilters = { ...EMPTY_PIPELINE_FILTERS };
      state.pipelineQuery = "";
      state.pipelineLimit = PIPELINE_PAGE;
      return render();

    case "pipeline-sort":
      state.pipelineSort = nextSort(state.pipelineSort, ds.sort);
      state.pipelineLimit = PIPELINE_PAGE;
      return render();

    case "pipeline-more":
      state.pipelineLimit += PIPELINE_PAGE;
      return render();

    case "crm-tab":
      state.crmTab = ds.tab === "tasks" ? "tasks" : "pipeline";
      state.crmDealId = null;
      return render();

    case "crm-tasks-status":
      state.taskFilters = { ...state.taskFilters, status: ds.status || "open" };
      return render();

    case "crm-tasks-assignee":
      state.taskFilters = { ...state.taskFilters, assignee: ds.assignee || "me" };
      return render();

    case "crm-task-toggle":
      await admin.crmTaskUpdate(ds.task, { status: ds.status });
      return render();

    case "crm-task-delete":
      if (!confirm("Ta bort uppgiften?")) return;
      await admin.crmTaskDelete(ds.task);
      flash("Uppgiften togs bort.");
      return render();

    case "crm-contact": {
      if (ds.op === "unlink" && !confirm("Ta bort kontakten från bolaget? Den finns kvar och kan kopplas igen.")) return;
      if (ds.op === "link") {
        await admin.crmContactAdd(ds.deal, { personId: ds.person });
        state.crmPeople = null;
        flash("Kontakten kopplades.");
      } else {
        await admin.crmContactAction(ds.deal, ds.person, ds.op);
      }
      return render();
    }

    case "crm-open-deal":
      state.crmPeople = null;
      state.crmDealId = ds.deal;
      state.view = "pipeline";
      state.companyId = null;
      setTab("pipeline");
      return render();

    case "crm-back":
      state.crmPeople = null;
      state.crmDealId = null;
      return render();

    case "pipeline-new-lead": {
      const body = pipelineNewLeadPrompt();
      if (!body?.contactName || !body.contactEmail) return;
      await admin.crmCreateLead(body);
      flash("Affären sparades i CRM.");
      return render();
    }

    case "pipeline-stage":
      await admin.crmUpdateLead(ds.deal || ds.lead, { stage: ds.stage });
      flash("Steget uppdaterades.");
      return render();

    case "pipeline-new-customer":
      state.pipelineLead = {
        leadId: ds.deal || ds.lead,
        contactName: ds.name || "",
        contactEmail: ds.email || "",
        companyName: ds.company || "",
        orgNumber: ds.org || "",
      };
      state.view = "nykund";
      state.lookup = null;
      state.lookupOrg = ds.org || "";
      setTab("kunder");
      return render();

    /* --- Konton och spärrar --- */

    case "open-account":
      // Från kundsidan: annars ritas kunden igen i stället för kontot.
      state.companyId = null;
      state.companyLoginLink = null;
      state.accountUserId = ds.user;
      state.accountRecovery = null;
      state.view = "konton";
      setTab("konton");
      return render();

    case "back-accounts":
      state.accountUserId = null;
      state.accountRecovery = null;
      return render();

    case "account-recovery": {
      const result = await admin.accountRecovery(ds.user);
      state.accountRecovery = result;
      flash("Lösenordslänk skapad — kopiera och skicka den till personen.");
      return render();
    }

    case "copy-recovery": {
      const url = document.getElementById("recoveryUrl")?.textContent?.trim();
      if (!url) return;
      await navigator.clipboard.writeText(url);
      flash("Länken är kopierad.");
      return;
    }

    case "account-delete": {
      const email = ds.email || "";
      const typed = prompt(
        `Radera kontot ${email}?\n\nTar bort inloggningen och medlemskapen. Supporttrådar och felrader behålls.\n\nSkriv e-postadressen för att bekräfta:`,
      );
      if (typed === null) return;
      await admin.deleteAccount(ds.user, typed.trim());
      state.accountUserId = null;
      state.accountRecovery = null;
      flash("Kontot är raderat.");
      return render();
    }

    case "account-test-push": {
      const body = await admin.accountTestPush(ds.user);
      const sent = (body.results || []).filter((r) => r.sent).length;
      const failed = (body.results || []).filter((r) => !r.sent);
      const why = failed.slice(0, 3).map((r) => `${r.device}: ${r.reason || "nej"}`).join("; ");
      flash(sent
        ? `Testnotis skickad till ${sent} telefon${sent === 1 ? "" : "er"}.${why ? ` Övriga: ${why}` : ""}`
        : `Ingen notis skickades.${why ? ` ${why}` : ""}`);
      return render();
    }

    case "county-change-allow": {
      const note = prompt(
        `Tillåt ett extra länbyte för ${ds.plate || "bilen"} den här månaden?\n\n` +
          "Anteckning (valfritt, syns i revisionen):",
      );
      if (note === null) return;
      const body = await admin.allowCountyChange(ds.license, note.trim());
      flash(`Extra länbyte beviljat. Kvar den här månaden: ${body.countyChanges?.remaining ?? "?"}.`);
      return render();
    }

    case "account-allow-device-swap": {
      const note = prompt(
        "Tillåt ett extra telefonbyte den här månaden?\n\nAnteckning (valfritt, syns i revisionen):",
      );
      if (note === null) return;
      const body = await admin.allowDeviceSwap(ds.user, note.trim());
      flash(`Extra byte beviljat. Kvar den här månaden: ${body.remaining ?? "?"}.`);
      return render();
    }

    case "account-member-status":
      await admin.setMember(ds.company, ds.user, { status: ds.status });
      flash(ds.status === "active" ? "Kontot är aktivt i företaget igen." : "Kontot är avstängt i företaget.");
      return render();

    case "block-user": {
      const reason = prompt(
        `Spärra kontot ${ds.email || ""}? Det får ingen data i något företag och inga adminrättigheter.\n\nSkäl (obligatoriskt):`,
      );
      if (!reason) return;
      await admin.block("user", ds.user, reason);
      flash("Kontot är spärrat.");
      return render();
    }

    case "block-email": {
      const reason = prompt(`Spärra adressen ${ds.email}? Den kan inte heller registrera nya företag.\n\nSkäl:`);
      if (!reason) return;
      await admin.block("email", ds.email, reason);
      flash("Adressen är spärrad.");
      return render();
    }

    case "block-lift": {
      const note = prompt("Häv spärren. Anteckning (sparas i loggen):");
      if (note === null) return;
      await admin.liftBlock(ds.block, note);
      flash("Spärren är hävd.");
      return render();
    }

    case "suspend": {
      const reason = prompt(
        "STÄNG AV FÖRETAGET: alla telefoner och inloggningar slutar få data direkt. Inget raderas.\n\nSkäl (obligatoriskt):",
      );
      if (!reason) return;
      await admin.block("company", state.companyId, reason);
      flash("Företaget är avstängt.");
      return render();
    }

    case "member-status":
      await admin.setMember(state.companyId, ds.user, { status: ds.status });
      flash(ds.status === "active" ? "Kontot är aktivt i företaget igen." : "Kontot är avstängt i företaget.");
      return render();

    case "verify": {
      const verified = ds.status === "verified";
      const note = prompt(
        verified
          ? "Hur kontrollerades att personen får företräda bolaget? (t.ex. ringde växeln, firmatecknare enligt Bolagsverket)"
          : "Varför avvisas företaget?",
      );
      if (!note) return;
      await admin.verifyCompany(state.companyId, ds.status, note);
      flash(verified ? "Behörigheten är markerad som kontrollerad." : "Företaget är avvisat.");
      return render();
    }

    case "staff-remove":
      if (!confirm(`Ta bort rollen för ${ds.email}?`)) return;
      await admin.setStaff(ds.email, "");
      flash("Rollen är borttagen.");
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
      return salesAction(action, ds);
  }
}

/* --- Evenemang: formulär, fil och arenasök ---------------------------- */

/** "55.58, 12.98" eller "55.58 12.98" ur fältet, som två tal. */
function eventBody(form) {
  const data = Object.fromEntries(new FormData(form));
  const parts = String(data.coords ?? "").split(/[,\s]+/).filter(Boolean);
  if (parts.length !== 2) {
    throw new ApiError(400, "Skriv koordinaten som lat, lon — till exempel 55.5838, 12.9884.", "coords");
  }
  delete data.coords;
  return { ...data, lat: parts[0], lon: parts[1] };
}

async function previewFile(file) {
  if (!file) return;
  clearError();
  const content = await file.text();
  try {
    const result = await admin.importEvents(file.name, content, true);
    state.eventImport = { filename: file.name, content, count: result.count, preview: result.preview };
  } catch (error) {
    if (!(error instanceof ApiError) || !error.detail?.errors) throw error;
    state.eventImport = { filename: file.name, message: error.message, errors: error.detail.errors };
  }
  render();
}

function downloadTemplate() {
  const csv =
    "namn;datum;tid;sluttid;arena;stad;lat;lon;kategori;besökare;länk\n" +
    "Malmö FF – AIK;2026-10-03;19:00;;Eleda Stadion;Malmö;55.5838;12.9884;sport;20000;\n";
  const url = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: "evenemang-mall.csv" });
  link.click();
  URL.revokeObjectURL(url);
}

el.view.addEventListener("change", (event) => {
  if (event.target.id === "eventFile") previewFile(event.target.files?.[0]).catch(showError);
});

el.view.addEventListener("dragover", (event) => {
  const drop = event.target.closest?.("#eventDrop");
  if (!drop) return;
  event.preventDefault();
  drop.classList.add("drag");
});
el.view.addEventListener("dragleave", (event) => {
  event.target.closest?.("#eventDrop")?.classList.remove("drag");
});
el.view.addEventListener("drop", (event) => {
  const drop = event.target.closest?.("#eventDrop");
  if (!drop) return;
  event.preventDefault();
  drop.classList.remove("drag");
  previewFile(event.dataTransfer?.files?.[0]).catch(showError);
});

let venueTimer = null;
el.view.addEventListener("input", (event) => {
  if (event.target.id !== "venueInput") return;
  clearTimeout(venueTimer);
  const q = event.target.value.trim();
  const hits = document.getElementById("venueHits");
  if (q.length < 2) {
    hits.hidden = true;
    return;
  }
  venueTimer = setTimeout(async () => {
    const { venues } = await admin.venues(q).catch(() => ({ venues: [] }));
    hits.innerHTML = venues
      .map((v, i) => `<li><button type="button" data-venue="${i}">${sales.esc(v.venue)}
        <span class="muted">${sales.esc(v.city)}</span></button></li>`)
      .join("");
    hits.hidden = !venues.length;
    hits.onclick = (e) => {
      const pick = venues[Number(e.target.closest("[data-venue]")?.dataset.venue)];
      if (!pick) return;
      const form = document.getElementById("eventNewForm");
      form.venue.value = pick.venue;
      form.city.value = pick.city;
      form.coords.value = `${pick.lat}, ${pick.lon}`;
      hits.hidden = true;
    };
  }, 250);
});

/* --- Förare ----------------------------------------------------------- */

let codeTimer = null;

/**
 * En kod per förare. Namnet blir telefonens etikett i listan över godkända
 * telefoner, så att rätt telefon kan spärras senare. Koden gäller i fem
 * minuter (§2) och bara en per bil i taget -- därför en i taget, med
 * nedräkning, och en knapp för nästa förare i samma bil.
 */
async function driverCode(licenseId, plate) {
  const name = prompt(`Förarens namn (visas som telefonens namn) för ${plate || "bilen"}:`);
  if (name === null) return;
  const result = await admin.pairingCode(state.companyId, licenseId, name.trim() || "Förare");
  el.codeFor.textContent = `${name.trim() || "Förare"} · ${plate || "bilen"}`;
  el.codeValue.textContent = result.code;
  const expires = new Date(result.expiresAt).getTime();
  const tick = () => {
    const left = Math.max(0, Math.round((expires - Date.now()) / 1000));
    el.codeTimer.textContent = left
      ? `Gäller i ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`
      : "Koden har gått ut. Skapa en ny.";
    if (!left) clearInterval(codeTimer);
  };
  clearInterval(codeTimer);
  tick();
  codeTimer = setInterval(tick, 1000);
  el.codeDialog.dataset.license = licenseId;
  el.codeDialog.dataset.plate = plate || "";
  el.codeDialog.showModal();
}

el.codeDialog?.addEventListener("close", () => {
  clearInterval(codeTimer);
  if (el.codeDialog.returnValue === "next") {
    driverCode(el.codeDialog.dataset.license, el.codeDialog.dataset.plate).catch(showError);
  } else {
    render();
  }
});

/* --- Säljflödet ------------------------------------------------------- */

function portalUrl() {
  // Kundportalen ligger på huvuddomänen, inte på admin-värden.
  const host = window.location.hostname.replace(/^admin\./, "");
  return `${window.location.protocol}//${host}${window.location.port ? `:${window.location.port}` : ""}/portal`;
}

function packageChange() {
  const panel = document.getElementById("salesPanel");
  const vehicles = panel ? sales.readVehicles(panel) : [];
  if (!vehicles.length) {
    throw new ApiError(400, "Fyll i minst ett registreringsnummer.", "vehicles_required");
  }
  return { vehicles, change: { addVehicles: vehicles } };
}

function showResult(html) {
  const box = document.getElementById("pkgResult");
  if (box) box.innerHTML = html;
}

function stripeWarning(result) {
  const stripe = result?.stripe;
  return stripe && stripe.synced === false ? `\n\nOBS: ${stripe.message}` : "";
}

let rowCounter = 0;

async function salesAction(action, ds) {
  const companyId = state.companyId;
  switch (action) {
    case "open-company":
      state.companyId = ds.id;
      state.companyTab = ds.tab || "";
      state.companyLoginLink = null;
      state.view = "kunder";
      setTab("kunder");
      return render();

    case "pkg-add-row": {
      const rows = document.getElementById("pkgRows");
      rowCounter += 1;
      rows.insertAdjacentHTML("beforeend", sales.vehicleRow(state.config.counties, rowCounter));
      return;
    }

    case "pkg-remove-row": {
      const rows = document.getElementById("pkgRows");
      if (rows.children.length > 1) rows.querySelector(`.pkg-row[data-row="${ds.row}"]`)?.remove();
      return;
    }

    case "pkg-quote": {
      const { change } = packageChange();
      const quote = await admin.quote(companyId, change);
      state.quotedChange = JSON.stringify(change);
      document.getElementById("pkgQuote").innerHTML = sales.quoteBox(quote);
      return;
    }

    case "pkg-trial": {
      const { vehicles } = packageChange();
      const daysRaw = document.getElementById("trialDays")?.value;
      const days = daysRaw ? Number(daysRaw) : undefined;
      const result = await admin.startTrial(companyId, vehicles, days);
      flash(
        `Provet omfattar nu ${result.vehicles} av högst ${result.vehicleLimit} bilar` +
          (result.plannedDays ? ` (${result.plannedDays} dagar)` : "") +
          ". " +
          (result.endsAt ? "" : "Det startar när första telefonen ansluts. ") +
          "Lägg till förare under Licenser och bilar.",
      );
      return render();
    }

    case "trial-extend": {
      const days = Number(document.getElementById("trialExtendDays")?.value || 0);
      const reason = prompt(`Förläng provet med ${days} dagar.\n\nSkriv varför (sparas i loggen):`);
      if (reason === null || !reason.trim()) return;
      await admin.extendTrial(state.companyId, days, reason.trim());
      flash("Provperioden är förlängd.");
      return render();
    }

    case "discount-clear": {
      const reason = prompt("Ta bort prisrabatten?\n\nSkäl (valfritt):");
      if (reason === null) return;
      await admin.clearDiscount(state.companyId, reason.trim());
      flash("Rabatten är borttagen.");
      return render();
    }

    case "pkg-coupon": {
      const code = document.getElementById("couponCode")?.value.trim();
      if (!code) throw new ApiError(400, "Skriv kupongkoden.", "code_required");
      const panel = document.getElementById("salesPanel");
      const vehicles = panel ? sales.readVehicles(panel) : [];
      const result = await admin.redeemCoupon(companyId, code, vehicles);
      const text = {
        temporary_access: `Tillfällig åtkomst i ${result.days} dagar, till ${result.detail.accessUntil?.slice(0, 10)}.`,
        billing_deferred: `Nästa debitering är flyttad till ${result.detail.nextBillingAt?.slice(0, 10)}.`,
        period_extended: `Perioden är förlängd till ${result.detail.periodEnd?.slice(0, 10)}.`,
      }[result.effect];
      flash(`Kupongen är inlöst. ${text ?? ""}`);
      return render();
    }

    case "pkg-order": {
      const { change } = packageChange();
      if (state.quotedChange !== JSON.stringify(change)) {
        throw new ApiError(
          400,
          "Räkna priset först, och läs upp det för kunden. Bilarna har ändrats sedan offerten.",
          "quote_required",
        );
      }
      if (!document.getElementById("pkgAccepted")?.checked) {
        throw new ApiError(
          400,
          "Bekräfta att kunden har godkänt antal, pris och betalningsdatum.",
          "acceptance_required",
        );
      }
      const payment = document.getElementById("pkgPayment").value;
      const result = await admin.order(companyId, {
        ...change,
        accepted: true,
        payment,
        daysUntilDue: Number(document.getElementById("pkgDue")?.value || 14),
      });
      state.quotedChange = null;
      return orderResult(result);
    }

    case "lic-add-county": {
      const county = document.querySelector(`[data-county-for="${ds.license}"]`)?.value;
      if (!county) return;
      return quotedOrder({ addCounties: [{ licenseId: ds.license, county }] });
    }

    /* --- Bilens län och borttagning (Bilar-steget) --- */

    case "county-add": {
      const county = document.querySelector(`[data-add-county="${ds.license}"]`)?.value;
      if (!county) throw new ApiError(400, "Välj ett län i listan först.", "county_required");
      if (ds.trial) {
        const extras = [...splitList(ds.extras), county];
        await admin.setTrialCounties(ds.license, ds.base, extras);
        flash(`${countyLabel(county)} är tillagt på ${ds.plate}. Gratis under provet.`);
        return render();
      }
      return prepareChange(ds.license, { addCounties: [{ licenseId: ds.license, county }] },
        `Lägg till ${countyLabel(county)} på ${ds.plate}`);
    }

    case "county-remove": {
      if (ds.trial) {
        if (!confirm(`Ta bort ${countyLabel(ds.county)} från ${ds.plate}?`)) return;
        const extras = splitList(ds.extras).filter((c) => c !== ds.county);
        await admin.setTrialCounties(ds.license, ds.base, extras);
        flash(`${countyLabel(ds.county)} är borttaget från ${ds.plate}.`);
        return render();
      }
      return prepareChange(ds.license, { removeCounties: [{ licenseId: ds.license, county: ds.county }] },
        `Ta bort ${countyLabel(ds.county)} från ${ds.plate} vid nästa förnyelse`);
    }

    case "base-change": {
      const county = document.querySelector(`[data-base-for="${ds.license}"]`)?.value;
      if (!county) throw new ApiError(400, "Välj det nya baslänet i listan först.", "county_required");
      if (ds.trial) {
        const extras = splitList(ds.extras).filter((c) => c !== county);
        await admin.setTrialCounties(ds.license, county, extras);
        flash(`${ds.plate} har nu ${countyLabel(county)} som baslän.`);
        return render();
      }
      return prepareChange(ds.license, { baseCountyChanges: [{ licenseId: ds.license, county }] },
        `Byt baslän på ${ds.plate} till ${countyLabel(county)} vid nästa förnyelse`);
    }

    case "base-change-now": {
      const county = document.querySelector(`[data-base-for="${ds.license}"]`)?.value;
      if (!county) throw new ApiError(400, "Välj det nya baslänet i listan först.", "county_required");
      const reason = prompt(
        `Byt baslän på ${ds.plate} till ${countyLabel(county)} DIREKT, i stället för vid förnyelsen.\n\n` +
          "Påverkar inte priset. Ange ett skäl (sparas i loggen):",
      );
      if (!reason) return;
      await admin.setBaseCountyNow(ds.license, county, reason);
      flash(`${ds.plate} har nu ${countyLabel(county)} som baslän.`);
      return render();
    }

    case "company-base-now": {
      const county = document.getElementById("companyBase")?.value;
      if (!county) throw new ApiError(400, "Välj det nya baslänet i listan först.", "county_required");
      const reason = prompt(
        `Byt baslän till ${countyLabel(county)} på ALLA företagets bilar, direkt.\n\n` +
          "Påverkar inte priset. Ange ett skäl (sparas i loggen):",
      );
      if (!reason) return;
      const result = await admin.setCompanyBaseCounty(state.companyId, county, reason);
      flash(`${result.changed} bil(ar) har nu ${countyLabel(county)} som baslän.`);
      return render();
    }

    case "pending-undo": {
      const reason = prompt(`Ångra "${ds.label}"? Det som skulle ändras vid förnyelsen ligger kvar som idag.\n\nAnge ett skäl (sparas i loggen):`);
      if (!reason) return;
      await admin.undoPendingChange(ds.change, reason);
      flash(`"${ds.label}" är ångrad.`);
      return render();
    }

    case "car-plate-ask": {
      const plate = prompt(`Nytt registreringsnummer för ${ds.plate}?\n\nLänen och perioden följer med. Förarna behöver en ny inbjudan.`);
      if (!plate) return;
      const result = await admin.changeVehicle(ds.license, plate.trim(), "permanent");
      flash(`Bilen är nu ${result.plate}. Förarna behöver en ny inbjudan.`);
      return render();
    }

    case "car-remove": {
      if (ds.trial) {
        const reason = prompt(`Ta bort provbilen ${ds.plate}? Förarna i bilen förlorar åtkomsten direkt.\n\nSkäl:`);
        if (!reason) return;
        await admin.removeLicense(ds.license, reason);
        flash(`${ds.plate} är borttagen.`);
        return render();
      }
      return prepareChange(ds.license, { cancelLicenseIds: [ds.license] },
        `Avsluta ${ds.plate} vid nästa förnyelse – ingen mer debitering för bilen`, { allowNow: true });
    }

    case "car-remove-now": {
      const reason = prompt(`Ta bort ${ds.plate} NU? Förarna förlorar åtkomsten direkt. Ingen återbetalning görs automatiskt.\n\nSkäl:`);
      if (!reason) return;
      await admin.removeLicense(ds.license, reason);
      state.pending = null;
      flash(`${ds.plate} är borttagen.`);
      return render();
    }

    case "pending-confirm": {
      const pending = state.pending;
      if (!pending) return;
      if (!document.getElementById("pendingAccepted")?.checked) {
        throw new ApiError(400, "Kryssa i att kunden har godkänt ändringen och priset.", "acceptance_required");
      }
      const result = await admin.order(companyId, {
        ...pending.change,
        accepted: true,
        payment: "stripe_card",
      });
      state.pending = null;
      return orderResult(result);
    }

    case "pending-cancel":
      state.pending = null;
      return render();

    case "lic-remove-county": {
      const county = document.querySelector(`[data-remove-county-for="${ds.license}"]`)?.value;
      if (!county) return;
      return quotedOrder({ removeCounties: [{ licenseId: ds.license, county }] });
    }

    case "lic-base": {
      const county = document.querySelector(`[data-base-for="${ds.license}"]`)?.value;
      if (!county) return;
      return quotedOrder({ baseCountyChanges: [{ licenseId: ds.license, county }] });
    }

    case "car-plate": {
      const plate = document.getElementById(`plate-${ds.license}`)?.value.trim();
      if (!plate) throw new ApiError(400, "Skriv det nya registreringsnumret.", "plate_required");
      const temporary = ds.mode === "temporary";
      if (!confirm(temporary
        ? `Ersättningsbil ${plate}? Länen följer med. Förarna behöver en ny inbjudan till ersättningsbilen.`
        : `Byt till ${plate}? Länen och perioden följer med. Förarna behöver en ny inbjudan.`)) return;
      const result = await admin.changeVehicle(ds.license, plate, ds.mode);
      flash(`Bilen är nu ${result.plate}. Bjud in förarna igen.`);
      return render();
    }

    case "car-return":
      await admin.changeVehicle(ds.license, "", "return");
      flash("Tillbaka till den ordinarie bilen.");
      return render();

    case "car-trial-counties": {
      const base = document.getElementById(`base-${ds.license}`)?.value;
      const extras = [...(document.getElementById(`extras-${ds.license}`)?.selectedOptions ?? [])].map((o) => o.value);
      await admin.setTrialCounties(ds.license, base, extras);
      flash("Länen är sparade.");
      return render();
    }

    case "lic-cancel": {
      if (!confirm(`Avsluta licensen för ${ds.plate} vid nästa förnyelse? Bilen fungerar perioden ut.`)) return;
      return quotedOrder({ cancelLicenseIds: [ds.license] });
    }

    case "owner-invite": {
      const email = document.getElementById("ownerEmail")?.value.trim();
      if (!email) throw new ApiError(400, "Skriv e-postadressen.", "email_required");
      const role = document.getElementById("ownerRole")?.value || "company_owner";
      const invite = await admin.inviteOwner(companyId, email, role);
      // Servern mejlar inbjudan med en inloggningslänk. Kontot knyts till
      // bolaget när personen loggar in med adressen (fleet/api.py:claim_invite).
      if (invite.mailSent) {
        flash(`Inbjudan är mejlad till ${invite.email}. Den gäller till ${invite.expiresAt.slice(0, 10)}.`);
        return render();
      }
      // Reserv utan service_role-nyckel på servern: en vanlig inloggningslänk.
      const { error } = await supabase().auth.signInWithOtp({
        email: invite.email,
        options: { shouldCreateUser: true, emailRedirectTo: portalUrl() },
      });
      flash(
        error
          ? `Inbjudan är sparad, men e-posten kunde inte skickas: ${error.message}. ` +
              `Be kunden gå till ${portalUrl()} och begära en inloggningslänk till ${invite.email}.`
          : `En inloggningslänk är skickad till ${invite.email}. Inbjudan gäller till ${invite.expiresAt.slice(0, 10)}.`,
      );
      return render();
    }

    case "cancel-period": {
      const reason = prompt("Säg upp till periodens slut. Varför slutar kunden? (sparas i loggen)");
      if (reason === null) return;
      const result = await admin.cancelSubscription(companyId, reason, false);
      alert(`Uppsagt till ${result.effectiveAt?.slice(0, 10)}. Kunden har åtkomst till dess.${stripeWarning(result)}`);
      return render();
    }

    case "undo-cancel": {
      const result = await admin.undoCancel(companyId);
      alert(`Uppsägningen är ångrad.${stripeWarning(result)}`);
      return render();
    }

    case "terminate-now": {
      const reason = prompt(
        "AVSLUTA DIREKT: åtkomsten upphör nu, alla licenser och förarpass avslutas och " +
          "Stripe slutar debitera. Ingen återbetalning görs automatiskt.\n\nSkäl (obligatoriskt):",
      );
      if (!reason) return;
      if (!confirm("Är du säker? Det går inte att ångra.")) return;
      const result = await admin.cancelSubscription(companyId, reason, true);
      alert(`Abonnemanget är avslutat.${stripeWarning(result)}`);
      if (confirm("Vill du också arkivera bolaget, så att det inte syns i listorna längre?")) {
        try {
          await admin.archiveCompany(companyId, true);
          flash("Bolaget är avslutat och arkiverat. Det finns under Kunder → Arkiverade.");
        } catch (error) {
          showError(error);
        }
      }
      return render();
    }

    case "archive":
      await admin.archiveCompany(companyId, true);
      flash("Bolaget är arkiverat. Det finns under Kunder → Arkiverade.");
      state.companyId = null;
      return render();

    case "unarchive":
      await admin.archiveCompany(companyId, false);
      flash("Bolaget är återställt och syns i listorna igen.");
      return render();

    case "delete-company": {
      const name = prompt(
        "RADERA PERMANENT: bolaget, bilarna, telefonerna, beställningarna och chatten tas bort " +
          "och går inte att få tillbaka.\n\nSkriv bolagets namn exakt för att bekräfta:",
      );
      if (!name) return;
      const result = await admin.deleteCompany(companyId, name);
      const total = Object.values(result.deleted ?? {}).reduce((a, b) => a + b, 0);
      flash(`Bolaget är raderat (${total} rader). Provhistoriken på organisationsnumret finns kvar.`);
      state.companyId = null;
      state.kundFilter = "alla";
      return render();
    }

    case "copy-link":
      await navigator.clipboard.writeText(ds.url);
      flash("Betallänken är kopierad. Skicka den till kunden.");
      return render();

    case "order-link": {
      const payment = confirm("Kort (OK) eller faktura via e-post (Avbryt)?") ? "stripe_card" : "stripe_invoice";
      await admin.paymentLink(ds.order, payment);
      flash("Betallänken är skapad.");
      return render();
    }

    case "order-refresh": {
      const result = await admin.refreshOrder(ds.order);
      flash(
        result.orderStatus === "applied"
          ? "Betalningen har gått igenom. Paketet är aktivt."
          : `Stripe: fakturan är ${result.invoiceStatus}. Ingenting är ändrat än.`,
      );
      return render();
    }

    case "order-cancel": {
      if (!confirm("Avbryta den obetalda ordern? En faktura i Stripe makuleras.")) return;
      await admin.cancelOrder(ds.order, "Avbruten av säljare");
      flash("Ordern är avbruten.");
      return render();
    }

    case "coupon-off": {
      if (!confirm("Stänga av kupongen? Redan inlösta påverkas inte.")) return;
      await admin.deactivateCoupon(ds.coupon);
      return render();
    }

    default:
      return;
  }
}

function splitList(value) {
  return String(value || "").split(",").filter(Boolean);
}

function countyLabel(code) {
  return (state.config?.counties ?? []).find((c) => c.code === code)?.name ?? code;
}

/**
 * En betald bils ändring: hämta offerten från servern och visa den i bilens
 * kort. Inget verkställs förrän säljaren bekräftat att kunden godkänt.
 */
async function prepareChange(licenseId, change, label, { allowNow = false } = {}) {
  const quote = await admin.quote(state.companyId, change);
  state.pending = { licenseId, change, label, quote, allowNow };
  return render();
}

/** Ändring på en befintlig licens: offert, bekräftelse, beställning. */
async function quotedOrder(change) {
  const quote = await admin.quote(state.companyId, change);
  const box = document.createElement("div");
  box.innerHTML = sales.quoteBox(quote);
  if (!confirm(`${box.innerText}\n\nHar kunden godkänt det här?`)) return;
  const result = await admin.order(state.companyId, {
    ...change,
    accepted: true,
    payment: "stripe_card",
  });
  return orderResult(result);
}

function orderResult(result) {
  const order = result.order;
  const pay = result.payment ?? {};
  if (order.status === "pending_payment") {
    if (pay.paymentUrl) {
      flash("Beställningen väntar på betalning. Betallänken finns under Beställningar — kopiera och skicka den till kunden.");
    } else if (pay.stripeError) {
      flash(`Beställningen är sparad men ingen betallänk skapades: ${pay.stripeError.message}`);
    } else {
      flash("Beställningen är sparad och väntar på betalning.");
    }
  } else if (order.status === "scheduled") {
    flash("Ändringen gäller från nästa förnyelse.");
  } else {
    flash("Beställningen är verkställd.");
  }
  return render();
}

boot().catch((error) => {
  el.login.hidden = false;
  showError(error);
});
