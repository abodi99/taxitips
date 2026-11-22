import { authErrorMessage, flagField, setBusy } from "../auth_form.js";
import { promptAndSetPassword, sendPasswordReset } from "../auth_password.js";
import { setupPasswordToggles } from "../password_toggle.js";
import { ApiError, supabase } from "../portal/api.js";
import * as acc from "./accounts.js";
import * as activity from "./activity.js";
import { bindTooltips, dashboard } from "./dashboard.js";
import { downloadCsv, webAnalytics } from "./web_analytics.js";
import { callsCell, followUpBody, nextCell, uppfoljning } from "./followup.js";
import { admin } from "./api.js";
import { notifyBody } from "../notify_editor.js";
import * as sales from "./sales.js";
import { LEVEL, statusBanner, statusSummaryLine, statusView } from "./status.js";
import { appVersionCard, bindAppVersionForm, loadAppVersion } from "./app_version.js";
import * as support from "./support.js";
import * as tipReports from "./tip_reports.js";
import {
  EMPTY_PIPELINE_FILTERS,
  crmSubnav,
  nextSort,
  pipelineNewLeadPrompt,
  pipelineTags,
  pipelineView,
  tasksView,
} from "./crm.js";
import * as views from "./views.js";
import { mountNav, navItem } from "./nav.js";
import { setupPalette } from "./palette.js";
import { ask, choose, sure } from "./dialog.js";

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

// Menyn ritas ur nav.js innan knapparna letas upp nedan.
mountNav(document.getElementById("adminNav"), document.getElementById("adminNavFoot"));

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
  // Hem först: det som kräver åtgärd, inte dashboardens siffror.
  view: "oversikt",
  // Webbstatistiken: period och om appen räknas med.
  web: { days: 30, source: "", scope: "web", fresh: false },
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
  // Kundsidans hopfällda delar: { platser: true, ... }, och för vilken kund.
  secOpen: {},
  secOpenFor: null,
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
  // Överst på sidan syns felet inte om man har scrollat ner (i telefonen nästan alltid).
  if (window.scrollY > 120) showToast(message, "error");
}

function clearError() {
  el.globalError.hidden = true;
}

function setTab(view) {
  // Undervyer (Ny kund, Uppföljning) markerar sin menypunkt.
  const item = navItem(view);
  for (const tab of el.tabs) {
    if (tab.dataset.view === item?.view) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  // Raden ovanför rubriken: vilken del av adminwebben man är i.
  const crumb = document.getElementById("crumb");
  if (crumb) {
    crumb.textContent = item?.group ?? "";
    crumb.hidden = !item?.group;
  }
  closeNav();
}

/* --- Mobilmenyn ----------------------------------------------------------- */

const navOpenBtn = document.getElementById("navOpen");
const navBackdrop = document.getElementById("navBackdrop");

function openNav() {
  document.body.classList.add("nav-open");
  navBackdrop.hidden = false;
  navOpenBtn?.setAttribute("aria-expanded", "true");
  (document.querySelector('.admin-side .tab[aria-current="page"]') ?? document.querySelector(".admin-side .tab"))?.focus();
}

function closeNav() {
  if (!document.body.classList.contains("nav-open")) return;
  document.body.classList.remove("nav-open");
  if (navBackdrop) navBackdrop.hidden = true;
  navOpenBtn?.setAttribute("aria-expanded", "false");
}

navOpenBtn?.addEventListener("click", openNav);
navBackdrop?.addEventListener("click", closeNav);
document.getElementById("navClose")?.addEventListener("click", () => {
  closeNav();
  navOpenBtn?.focus();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeNav();
});

/* --- Adressen -------------------------------------------------------------
   Vyn, kunden och kontot står i adressen (?vy=kunder&kund=…), så att
   webbläsarens bakåtknapp fungerar, en sida kan laddas om utan att man
   hamnar på Hem, och en länk kan skickas till en kollega. */

const URL_KEYS = ["vy", "kund", "konto", "affar", "flik"];

function urlFromState() {
  const params = new URLSearchParams(window.location.search);
  for (const key of URL_KEYS) params.delete(key);
  if (state.companyId) {
    params.set("kund", state.companyId);
    const tab = views.kundTab(state.companyTab);
    if (tab !== "oversikt") params.set("flik", tab);
  } else {
    if (state.view && state.view !== "oversikt") params.set("vy", state.view);
    if (state.view === "konton" && state.accountUserId) params.set("konto", state.accountUserId);
    if (state.view === "pipeline") {
      if (state.crmDealId) params.set("affar", state.crmDealId);
      else if (state.crmTab && state.crmTab !== "pipeline") params.set("flik", state.crmTab);
    }
  }
  const qs = params.toString();
  return window.location.pathname + (qs ? `?${qs}` : "");
}

function stateFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get("vy");
  state.companyId = params.get("kund") || null;
  state.companyTab = state.companyId ? params.get("flik") || "" : "";
  state.view = state.companyId ? "kunder" : (view && (navItem(view) || view === "nykund") ? view : "oversikt");
  state.accountUserId = state.view === "konton" ? params.get("konto") || null : null;
  state.accountRecovery = null;
  state.crmDealId = state.view === "pipeline" ? params.get("affar") || null : null;
  const flik = params.get("flik");
  state.crmTab = state.view === "pipeline" && ["tasks", "uppfoljning"].includes(flik) ? flik : "pipeline";
}

let firstUrlSync = true;
function syncUrl() {
  const next = urlFromState();
  const current = window.location.pathname + window.location.search;
  if (next === current) return;
  // Första ritningen ersätter (inloggningen har redan lagt en rad i historiken).
  if (firstUrlSync) history.replaceState(null, "", next);
  else history.pushState(null, "", next);
}

window.addEventListener("popstate", () => {
  if (el.app.hidden) return;
  stateFromUrl();
  state.pending = null;
  state.companyLoginLink = null;
  setTab(state.view);
  render();
});

async function render() {
  const seq = ++renderSeq;
  syncUrl();
  firstUrlSync = false;
  clearError();
  // Samma kund ritas om efter en åtgärd: behåll sidan (och var man står) tills
  // den nya är klar, i stället för att hoppa till toppen via "Laddar …".
  const sameCompany = !!state.companyId && el.view.dataset.company === state.companyId;
  state.keepScroll = sameCompany ? window.scrollY : null;
  if (sameCompany) el.view.setAttribute("aria-busy", "true");
  else {
    delete el.view.dataset.company;
    el.view.innerHTML = '<p class="muted">Laddar …</p>';
  }
  const note = state.flash;
  state.flash = null;
  try {
    await renderView(seq);
  } finally {
    if (note && seq === renderSeq) showToast(note);
  }
}

/**
 * Kvittot efter en åtgärd ("Uppgifterna är sparade."): en ruta längst ner på
 * skärmen i stället för överst på sidan, så att den syns även när man har
 * scrollat ner -- i telefonen nästan alltid. Försvinner efter en stund.
 */
let toastTimer = null;
function showToast(message, kind = "ok") {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.querySelector("[data-toast-text]").textContent = message;
  toast.hidden = false;
  toast.classList.remove("is-leaving");
  toast.classList.toggle("is-error", kind === "error");
  toast.setAttribute("role", kind === "error" ? "alert" : "status");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, Math.min(14000, 5000 + message.length * 40));
}
function hideToast() {
  const toast = document.getElementById("toast");
  if (!toast || toast.hidden) return;
  toast.classList.add("is-leaving");
  setTimeout(() => {
    if (toast.classList.contains("is-leaving")) toast.hidden = true;
  }, 200);
}
document.getElementById("toastClose")?.addEventListener("click", hideToast);

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
      // Delarnas öppet/stängt hör till kunden: byter man kund börjar det om.
      if (state.secOpenFor !== state.companyId) {
        state.secOpen = {};
        state.secOpenFor = state.companyId;
      }
      // Kundsidan har egen "← Alla kunder"; gruppraden ovanför blir dubbel.
      if (current()) document.getElementById("crumb").hidden = true;
      paint(views.kund(
        detail, state.config, state.companyTab, state.pending, crm, state.companyLoginLink,
        state.secOpen,
      ));
      if (current()) {
        el.view.dataset.company = state.companyId;
        el.view.removeAttribute("aria-busy");
        if (state.keepScroll != null) window.scrollTo({ top: state.keepScroll });
        autoQuote();
      }
      // Vald flik synlig i flikraden (i telefonen kan den ligga utanför kanten).
      const bar = current() ? el.view.querySelector(".kt-bar") : null;
      const sel = bar?.querySelector('.kt-tab[aria-selected="true"]');
      if (bar && sel && sel.offsetLeft + sel.offsetWidth > bar.clientWidth) {
        bar.scrollLeft = sel.offsetLeft - 12;
      }
      // Under Historik: företagets appar och fel (activity.js), hämtas när rutan öppnas.
      if (current()) {
        activity.companyPanel(
          el.view.querySelector('[data-sec-mount="activity"]'), state.companyId, { isCurrent: current },
        );
      }
      return;
    }
    switch (state.view) {
      case "dashboard":
        paint(dashboard(await admin.dashboard()));
        break;
      case "webbstatistik": {
        const { days, scope, fresh } = state.web;
        state.web.fresh = false;
        paint(webAnalytics(await admin.webAnalytics({ days, scope, fresh }), state.web));
        break;
      }
      case "oversikt": {
        const [overview, list, sup, tipRep, crmTasks] = await Promise.all([
          admin.overview(), admin.companies(),
          // Hem ska fungera även om supporten/CRM inte svarar. Statuspricken
          // (Stripe-produkt, SMTP, Firebase) hämtas i bakgrunden av
          // refreshStatus -- den får inte blockera den här sidan.
          admin.supportSummary().catch(() => ({ waiting: 0 })),
          admin.tipReportsSummary().catch(() => ({ open: 0 })),
          admin.crmTasks({ assignee: "all", status: "open" }).catch(() => null),
        ]);
        const waiting = sup.waiting ?? 0;
        const tipOpen = tipRep.open ?? overview.tipReportsOpen ?? 0;
        const reviewsOpen = overview.reviewsOpen ?? 0;
        const crmOverdue = crmTasks?.summary?.overdue ?? 0;
        setSupportCount(waiting);
        setTipReportCount(tipOpen);
        setReviewsCount(reviewsOpen);
        paint(statusBanner(state.status) + views.oversikt(overview, list, {
          supportWaiting: waiting,
          tipReportsOpen: tipOpen,
          crmTasksOverdue: crmOverdue,
          statusReport: state.status,
          statusLine: statusSummaryLine(state.status),
        }));
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
        // Bakåtkompatibelt: Dashboard och gamla länkar → CRM-underflik.
        state.view = "pipeline";
        state.crmTab = "uppfoljning";
        setTab("pipeline");
        paint(uppfoljning(await admin.followUps(), state.fuFilter, {
          crmNav: crmSubnav("uppfoljning"),
        }));
        break;
      case "pipeline": {
        if (state.crmDealId) {
          paint(pipelineView(
            {},
            state.config,
            { peopleQuery: state.crmPeople?.q, peopleHits: state.crmPeople?.hits },
            await admin.crmDeal(state.crmDealId),
          ));
        } else if (state.crmTab === "uppfoljning") {
          paint(uppfoljning(await admin.followUps(), state.fuFilter, {
            crmNav: crmSubnav("uppfoljning"),
          }));
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
    el.view.removeAttribute("aria-busy");
    delete el.view.dataset.company;
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
  refreshNavDot();
}

function setTipReportCount(n) {
  const badge = document.getElementById("tipReportCount");
  if (badge) {
    badge.textContent = String(n);
    badge.hidden = !n;
  }
  refreshNavDot();
}

function setReviewsCount(n) {
  const badge = document.getElementById("granskningCount");
  if (badge) {
    badge.textContent = String(n);
    badge.hidden = !n;
  }
  refreshNavDot();
}

/** Mobil: en prick på menyknappen när något i menyn väntar. */
function refreshNavDot() {
  const waiting = ["supportCount", "tipReportCount", "granskningCount"].some((id) => {
    const node = document.getElementById(id);
    return node && !node.hidden;
  });
  const dot = document.getElementById("navOpenBadge");
  if (dot) dot.hidden = !waiting;
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
  document.body.classList.add("in-app");
  stateFromUrl();
  el.logout.hidden = false;
  document.getElementById("changePassword").hidden = false;
  el.whoami.textContent = session.user?.email ?? "";
  rememberEmail(session.user?.email);
  setTab(state.view);
  await render();
}

setupPasswordToggles(el.login ?? document);

function showLoginError(message) {
  el.loginError.textContent = message;
  el.loginError.hidden = false;
}

/**
 * E-posten ur formuläret, eller tom sträng med felet visat vid fältet. Ett
 * nytt försök tar bort förra försökets fel och kvitto.
 */
function loginEmail() {
  el.loginError.hidden = true;
  const sent = document.getElementById("magicSent");
  if (sent) sent.hidden = true;
  const email = String(new FormData(el.loginForm).get("email") ?? "").trim();
  if (!email) {
    showLoginError("Skriv din e-post först.");
    flagField(document.getElementById("email"));
  }
  return email;
}

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
  const submit = document.getElementById("loginSubmit");
  setBusy(submit, true, "Loggar in …");
  try {
    const { data, error } = await supabase().auth.signInWithPassword({ email, password });
    if (error) throw error;
    await enterApp(data.session);
  } catch (error) {
    showLoginError(authErrorMessage(error, "Kunde inte logga in."));
  } finally {
    setBusy(submit, false);
  }
});

/**
 * Lokal debug-inloggning. Vite sätter `import.meta.env.DEV` bara under
 * `npm run dev` — hela blocket (knapp + lösenord) plockas bort i prod-bygget,
 * och platsen för knappen skapas här i stället för att stå i admin.html, så att
 * produktionens HTML inte ens har ett tomt `#devLogin`.
 * Kontot skapas lokalt: admin@taxitips.local / taxitips-admin-dev + StaffRole.
 */
if (import.meta.env.DEV) {
  const DEV_EMAIL = "admin@taxitips.local";
  const DEV_PASSWORD = "taxitips-admin-dev";
  const anchor = document.getElementById("magicSent");
  const mount = document.createElement("div");
  mount.id = "devLogin";
  mount.className = "dev-login";
  anchor?.after(mount);
  if (anchor) {
    mount.innerHTML = `
      <p class="muted"><b>Lokal utveckling</b></p>
      <button id="devLoginBtn" class="btn btn-outline btn-block" type="button">
        Logga in som lokal admin
      </button>
      <p class="muted">
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
document.getElementById("magicLink")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const email = loginEmail();
  const sent = document.getElementById("magicSent");
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
    sent.textContent = `Om ${email} har ett konto kommer en inloggningslänk strax.`;
    sent.hidden = false;
  } catch (error) {
    showLoginError(authErrorMessage(error, "Kunde inte skicka länken."));
  } finally {
    setBusy(button, false);
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

document.getElementById("forgotPassword")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const email = loginEmail();
  const sent = document.getElementById("magicSent");
  if (!email) return;
  setBusy(button, true, "Skickar …");
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
    showLoginError(authErrorMessage(error, "Kunde inte skicka länken."));
  } finally {
    setBusy(button, false);
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

function gotoView(view) {
  state.view = view;
  state.companyId = null;
  state.companyTab = "";
  state.pending = null;
  state.companyLoginLink = null;
  if (view === "konton") {
    state.accountUserId = null;
    state.accountRecovery = null;
  }
  if (view === "pipeline") state.crmDealId = null;
  setTab(view);
  render();
  window.scrollTo({ top: 0 });
}

for (const tab of el.tabs) {
  tab.addEventListener("click", () => gotoView(tab.dataset.view));
}

const palette = setupPalette({
  onView: gotoView,
  onCompany: (id) => act("open-company", { id }).catch(showError),
  onAccount: (user) => act("open-account", { user }).catch(showError),
  searchCompanies: (q) => admin.companies(q),
  searchAccounts: (q) => admin.accounts(q),
});

bindAppVersionForm(el.view);
bindTooltips(el.view);

// "toggle" bubblar inte: fånga det på vägen ner för att minnas vilka delar av
// kundsidan som är öppna när sidan ritas om efter en åtgärd.
el.view.addEventListener("toggle", (event) => {
  const node = event.target;
  const sec = node instanceof HTMLDetailsElement ? node.dataset.sec : "";
  if (sec && state.companyId) state.secOpen[sec] = node.open;
}, true);

el.view.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  clearError();
  if (form.classList.contains("notify-form")) {
    // Notiserna för kundens telefoner (src/notify_editor.js, fleet/admin_notify.py).
    const body = notifyBody(form, event.submitter);
    if (!body) return showError(new ApiError(400, "Välj ett läge först.", "preset_required"));
    const buttons = form.querySelectorAll('button[type="submit"]');
    for (const b of buttons) b.disabled = true;
    try {
      if (form.dataset.target === "default") {
        const result = await admin.setNotifyDefault(state.companyId, body);
        flash(result.phonesChanged
          ? `Standarden är sparad och gäller nu ${result.phonesChanged} telefon(er).`
          : "Standarden är sparad. Nya telefoner får den när de kopplas till en bil.");
      } else {
        await admin.setDeviceNotify(state.companyId, form.dataset.device, body);
        flash("Notiserna är ändrade på telefonen. Ändringen är loggad.");
      }
      await render();
    } catch (error) {
      showError(error);
    } finally {
      for (const b of buttons) b.disabled = false;
    }
    return;
  }
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
      case "companyForm": {
        const created = await admin.createCompany(sales.companyBody(form));
        const { seats, county } = sales.companySeats(form);
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
        // Företaget är upplagt: nästa steg är platser och betalning, samma som i portalen.
        state.companyTab = "betalning";
        state.view = "kunder";
        setTab("kunder");
        // Platserna startas som prov direkt. Går det inte (för många platser,
        // eller bolaget har haft prov) hamnar säljaren på Betalning med skälet.
        try {
          const vehicles = Array.from({ length: seats }, () => ({
            plate: "", label: "", baseCounty: county, extraCounties: [],
          }));
          await admin.startTrial(created.companyId, vehicles);
          state.companyTab = "";
          flash(`Kunden är upplagd med ${seats === 1 ? "1 plats" : `${seats} platser`} i prov. `
            + "Provet startar när första kontot loggar in. Bjud in kontona under Platser.");
        } catch (error) {
          flash(`Kunden är upplagd. Provet kunde inte startas: ${error?.message ?? "okänt fel"} `
            + "Lägg till plats eller skicka betallänk under Betalning.");
        }
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
        const stripe = result.stripe ?? {};
        flash(
          stripe.synced && stripe.published !== false
            ? `Kupongen ${result.coupon.code} är skapad och fungerar som kampanjkod i Stripe-kassan.`
            : `Kupongen ${result.coupon.code} är skapad, men inte i Stripe-kassan: ${stripe.message || stripe.reason || "okänt fel"}. Säljaren kan fortfarande lösa in den.`,
        );
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

el.view.addEventListener("change", async (event) => {
  if (event.target.id === "pkgCounty" || event.target.id === "pkgCount") {
    autoQuote();
    return;
  }
  if (event.target.id === "pushStatus") {
    state.pushStatus = event.target.value;
    render();
    return;
  }
  if (event.target.matches?.("[data-seat-county]")) {
    // Länet byts direkt i platsens rad. Avbryter man ställs listan tillbaka.
    const select = event.target;
    const ds = select.dataset;
    const county = select.value;
    if (!county || county === ds.base) return;
    if (!await sure(`Byta län på ${ds.plate} till ${countyLabel(county)}? Gäller direkt.`)) {
      select.value = ds.base;
      return;
    }
    const extras = splitList(ds.extras).filter((c) => c !== county);
    select.disabled = true;
    admin.setTrialCounties(ds.license, county, extras)
      .then(() => {
        flash(`${ds.plate} har nu ${countyLabel(county)}.`);
        return render();
      })
      .catch((error) => {
        select.disabled = false;
        select.value = ds.base;
        showError(error);
      });
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

/**
 * Visa en flik på kundsidan utan att hämta om kunden. Fliken minns i
 * `state.companyTab` (så att den står kvar när sidan ritas om efter en
 * åtgärd) och i adressen. Returnerar panelen, eller null.
 */
function showKundTab(name) {
  const tab = views.kundTab(name);
  const panel = el.view.querySelector(`[data-tab-panel="${tab}"]`);
  if (!panel) return null;
  for (const node of el.view.querySelectorAll("[data-tab-panel]")) node.hidden = node !== panel;
  for (const btn of el.view.querySelectorAll(".kt-tab")) {
    btn.setAttribute("aria-selected", String(btn.dataset.tab === tab));
  }
  const bar = el.view.querySelector(".kt-bar");
  const btn = el.view.querySelector(`.kt-tab[data-tab="${tab}"]`);
  if (bar && btn) {
    if (btn.offsetLeft < bar.scrollLeft) bar.scrollLeft = btn.offsetLeft - 12;
    else if (btn.offsetLeft + btn.offsetWidth > bar.scrollLeft + bar.clientWidth) {
      bar.scrollLeft = btn.offsetLeft + btn.offsetWidth - bar.clientWidth + 12;
    }
  }
  state.companyTab = tab;
  history.replaceState(null, "", urlFromState());
  return panel;
}

// En meny ("Fler åtgärder", "Mer") stängs när man valt något i den eller klickar utanför.
document.addEventListener("click", (event) => {
  const inMenu = event.target.closest?.(".more-menu");
  for (const menu of document.querySelectorAll(".more-menu[open]")) {
    if (menu !== inMenu || event.target.closest('[role="menuitem"]')) menu.open = false;
  }
});

// Flikraden i mobilen: tona inte ut kanten när man redan svept till slutet.
el.view.addEventListener("scroll", (event) => {
  const bar = event.target;
  if (!(bar instanceof HTMLElement) || !bar.classList.contains("kt-bar")) return;
  bar.classList.toggle("is-end", bar.scrollLeft + bar.clientWidth >= bar.scrollWidth - 4);
}, true);

/**
 * Efter ett flikbyte: har man scrollat förbi flikraden, rulla så att den nya
 * panelen börjar precis under raden (som står kvar överst). Annars hamnar man
 * mitt i den nya fliken på samma höjd som man var i den förra.
 */
function scrollToKundTabs() {
  const wrap = el.view.querySelector(".kt-bar-wrap");
  const panel = el.view.querySelector("[data-tab-panel]:not([hidden])");
  if (!wrap || !panel) return;
  const topbar = document.querySelector(".admin-topbar");
  const offset = (topbar && topbar.offsetParent ? topbar.offsetHeight : 0) + wrap.offsetHeight;
  const y = panel.getBoundingClientRect().top + window.scrollY - offset;
  if (window.scrollY > y) window.scrollTo({ top: y });
}

/** Dashboardens siffror öppnar listan bakom sig med samma urval (dashboard.js). */
function gotoFilter(view, filter) {
  if (view === "kunder") state.kundFilter = filter;
  else if (view === "uppfoljning") {
    state.view = "pipeline";
    state.crmTab = "uppfoljning";
    state.fuFilter = filter;
  } else if (view === "notiser") state.pushStatus = filter;
  else if (view === "pipeline" && filter === "tasks") {
    state.crmDealId = null;
    state.crmTab = "tasks";
    state.taskFilters = { assignee: "all", status: "open" };
  } else if (view === "pipeline" && filter === "uppfoljning") {
    state.crmDealId = null;
    state.crmTab = "uppfoljning";
  } else if (view === "pipeline" && filter === "prov") {
    // Hem: "prov slutar" → kunder/prov, redan hanterat via view=kunder.
  }
}

async function act(action, ds) {
  switch (action) {
    case "back":
      state.companyId = null;
      state.companyTab = "";
      state.pending = null;
      state.companyLoginLink = null;
      return render();

    case "sec-open": {
      // Byt till fliken där delen bor, öppna det som är hopfällt och rulla dit.
      const panel = showKundTab(ds.sec);
      if (!panel) return;
      const target = (ds.target && document.getElementById(ds.target)) || null;
      if (!target) {
        scrollToKundTabs();
        return;
      }
      for (let node = target.parentElement?.closest("details"); node; node = node.parentElement?.closest("details")) {
        node.open = true;
      }
      if (target instanceof HTMLDetailsElement) target.open = true;
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }

    case "kund-tab":
      // Flikarna ritas alla på en gång; att byta är bara att visa en annan.
      if (showKundTab(ds.tab)) scrollToKundTabs();
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
      const note = await ask(
        `Ge ${days} extra dagar?\n\nÄndrar inte Stripe.\n\nSkäl:`,
      );
      if (note === null) return;
      await admin.setSubscription(state.companyId, { extendDays: days, note });
      return render();
    }

    case "code":
      return driverCode(ds.license, ds.plate);

    case "block": {
      if (!await sure(`Spärra ${ds.label || "telefonen"}? Den slutar visa tips direkt och lämnar bilen.\n\n` +
        "Föraren behöver en ny inbjudan för att köra igen.")) return;
      await admin.blockPhone(ds.approval, "admin_block");
      flash(`${ds.label || "Telefonen"} är spärrad.`);
      return render();
    }

    /* --- Supportåtgärder på kundsidan --- */

    case "car-release": {
      const reason = await ask(
        `Frigör ${ds.plate}?\n\n${ds.holder} lämnar bilen så att någon annan kan ta den.\n\nSkäl:`,
        "Föraren glömde lämna bilen",
      );
      if (reason === null) return;
      const result = await admin.releaseCar(ds.license, reason.trim());
      flash(result.released ? `${ds.plate} är frigjord.` : `Ingen körde ${ds.plate}.`);
      return render();
    }

    case "seat-assign": {
      const input = el.view.querySelector(`[data-seat-email="${ds.license}"]`);
      const email = input?.value.trim() ?? "";
      if (!email || !input.checkValidity()) {
        throw new ApiError(400, "Skriv förarens e-post först.", "email_required");
      }
      await admin.assignMembership(ds.license, { email });
      flash(`${ds.plate} är tilldelad ${email}.`);
      return render();
    }

    case "membership-assign": {
      const email = await ask(
        `Vem ska ha ${memberLabel(ds)}?\n\nPlatsen kopplas när personen loggar in i appen.\n\nE-post:`,
      );
      if (!email?.trim()) return;
      await admin.assignMembership(ds.license, { email: email.trim() });
      flash(`${memberLabel(ds)} tilldelas ${email.trim()}.`);
      return render();
    }

    case "membership-unassign": {
      if (
        !await sure(
          `Ta bort tilldelningen på ${memberLabel(ds)}? Platsen är kvar men inget konto använder den.`,
        )
      )
        return;
      await admin.unassignMembership(ds.license);
      flash(`Tilldelningen på ${memberLabel(ds)} är borttagen.`);
      return render();
    }

    /* --- Plats utan bil, och beviljanden --- */

    case "membership-invite-free": {
      const licenseId = document.getElementById("inviteLicense")?.value;
      const email = document.getElementById("inviteEmail")?.value.trim();
      if (!licenseId) {
        flash("Välj en ledig plats först.");
        return;
      }
      if (!email) {
        flash("Skriv kontots e-post först.");
        return;
      }
      await admin.assignMembership(licenseId, { email });
      flash(`Platsen tilldelas ${email}.`);
      return render();
    }

    case "membership-create": {
      const email = document.getElementById("newMemberEmail")?.value.trim();
      if (!email) {
        flash("Skriv kontots e-post först.");
        return;
      }
      const baseCounty = document.getElementById("newMemberCounty")?.value ?? "";
      await admin.createMembership(state.companyId, { email, baseCounty });
      flash(`Platsen skapas och tilldelas ${email}.`);
      return render();
    }

    case "grant-membership": {
      const email = document.getElementById("grantEmail")?.value.trim();
      const reason = document.getElementById("grantReason")?.value.trim();
      const endsAt = document.getElementById("grantEnds")?.value ?? "";
      if (!email) {
        flash("Skriv kontots e-post först.");
        return;
      }
      if (!reason) {
        flash("Skriv varför platsen beviljas utan kostnad -- skälet loggas.");
        return;
      }
      const choice = readGrantChoice("grantCategory", "grantCounty");
      if (!choice.categories.length) {
        flash("Välj minst en kategori.");
        return;
      }
      if (
        !await sure(
          `Tilldela ${email} plats utan kostnad?\n\n` +
            `Kategorier: ${choice.categoryText}.\nLän: ${choice.countyText}.\n` +
            (endsAt ? `Gäller till ${endsAt}. ` : "Gäller tills vidare. ") +
            "Ingen order eller faktura skapas, och platsen räknas inte mot nästa betalning.",
        )
      )
        return;
      await admin.grantMembership(state.companyId, {
        email,
        reason,
        ...(endsAt ? { endsAt } : {}),
        ...choice.body,
      });
      flash(`${email} har fått en plats utan kostnad (${choice.categoryText}).`);
      return render();
    }

    case "grant-update": {
      const choice = readGrantChoice(`grantEditCat-${ds.grant}`, `grantEditCounty-${ds.grant}`);
      if (!choice.categories.length) {
        flash("Välj minst en kategori.");
        return;
      }
      if (
        !await sure(
          `Ändra beviljandet för ${ds.who}?\n\n` +
            `Kategorier: ${choice.categoryText}.\nLän: ${choice.countyText}.\n` +
            "Ändringen gäller direkt och loggas.",
        )
      )
        return;
      await admin.updateGrant(ds.grant, choice.body);
      flash(`Beviljandet för ${ds.who} är ändrat (${choice.categoryText}).`);
      return render();
    }

    case "grant-revoke": {
      const reason = await ask(
        `Återkalla gratisplatsen för ${ds.who}?\n\nÅtkomsten stängs direkt.\n\nSkäl:`,
      );
      if (!reason?.trim()) return;
      await admin.revokeGrant(ds.grant, reason.trim());
      flash("Beviljandet är återkallat.");
      return render();
    }

    case "phone-rename": {
      const label = await ask("Byt namn på telefonen\n\nNamn:", ds.label || "");
      if (!label?.trim()) return;
      await admin.renamePhone(ds.approval, label.trim());
      flash(`Telefonen heter nu ${label.trim()}.`);
      return render();
    }

    case "driver-invite": {
      const email = await ask(`Bjud in förare till ${ds.plate}\n\nFöraren får ett mejl och väljer lösenord. Gäller i 7 dagar.\n\nE-post:`);
      if (!email?.trim()) return;
      const label = await ask("Förarens namn\n\nVisas som telefonens namn.\n\nNamn:", "") ?? "";
      await admin.inviteDriver(state.companyId, ds.license, email.trim(), label.trim());
      flash(`Inbjudan är skickad till ${email.trim()}.`);
      return render();
    }

    case "driver-invite-resend":
      await admin.resendDriverInvite(ds.invite);
      flash("Inbjudan är skickad igen och gäller sju nya dagar.");
      return render();

    case "driver-invite-revoke":
      if (!await sure(`Återkalla inbjudan till ${ds.email}?`)) return;
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
        fleet_admin: "Bilar och förare. Hen sköter platser, län och konton men inte betalning",
        finance: "Ekonomi. Hen ser och betalar fakturor men ändrar inte bilar eller förare",
      }[ds.role];
      if (!await sure(`Ändra rollen till ${what}?`)) return;
      await admin.setMember(state.companyId, ds.user, { role: ds.role });
      flash(`Rollen är ändrad till ${views.MEMBER_ROLE[ds.role] ?? ds.role}.`);
      return render();
    }

    case "test-push": {
      const result = await admin.testPush(state.companyId);
      const lines = (result.results ?? []).map(
        (r) => `${r.device}: ${r.sent ? "skickad" : `inte skickad (${r.reason})`}`,
      );
      await sure(`Testnotis\n\n${lines.length ? lines.join("\n") : "Bolaget har inga telefoner."}`, { ok: "OK", danger: false });
      return;
    }

    case "event-hide": {
      const reason = await ask("Dölj evenemanget för förarna?\n\nSkäl (obligatoriskt):");
      if (!reason) return;
      await admin.setEventVisibility(Number(ds.event), true, reason);
      return render();
    }

    case "event-show":
      await admin.setEventVisibility(Number(ds.event), false);
      return render();

    case "event-delete":
      if (!await sure(`Ta bort "${ds.name}"? Det försvinner för förarna direkt.`)) return;
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
      if (overwrite && !await sure("Ersätta fakturaadressen med adressen hos Bolagsverket?")) return;
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

    case "wa-days":
      state.web.days = Number(ds.value);
      return render();
    case "wa-scope":
      state.web.scope = ds.value;
      return render();
    case "wa-refresh":
      state.web.fresh = true;
      return render();
    case "wa-csv":
      return downloadCsv(state.web.source);

    case "palette":
      palette.open();
      return;

    case "goto":
      state.view = ds.view;
      state.companyId = null;
      state.companyTab = "";
      if (ds.filter) gotoFilter(ds.view, ds.filter);
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
      state.crmTab = ["tasks", "uppfoljning"].includes(ds.tab) ? ds.tab : "pipeline";
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
      if (!await sure("Ta bort uppgiften?")) return;
      await admin.crmTaskDelete(ds.task);
      flash("Uppgiften togs bort.");
      return render();

    case "crm-contact": {
      if (ds.op === "unlink" && !await sure("Ta bort kontakten från bolaget? Den finns kvar och kan kopplas igen.")) return;
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
      const body = await pipelineNewLeadPrompt();
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
      const typed = await ask(
        `Radera kontot ${email}?\n\nInloggningen och platserna tas bort.\n\nSkriv e-postadressen för att bekräfta:`,
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
      const note = await ask(
        `Ge ${memberLabel(ds)} ett extra länbyte?\n\nGäller den här månaden.\n\nAnteckning (valfritt):`,
      );
      if (note === null) return;
      const body = await admin.allowCountyChange(ds.license, note.trim());
      flash(`Extra länbyte beviljat. Kvar den här månaden: ${body.countyChanges?.remaining ?? "?"}.`);
      return render();
    }

    case "account-allow-device-swap": {
      const note = await ask(
        "Ge ett extra telefonbyte?\n\nGäller den här månaden.\n\nAnteckning (valfritt):",
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
      const reason = await ask(
        `Spärra kontot ${ds.email || ""}?\n\nKontot får ingen data i något företag.\n\nSkäl (obligatoriskt):`,
      );
      if (!reason) return;
      await admin.block("user", ds.user, reason);
      flash("Kontot är spärrat.");
      return render();
    }

    case "block-email": {
      const reason = await ask(`Spärra adressen ${ds.email}?\n\nDen kan inte registrera nya företag.\n\nSkäl (obligatoriskt):`);
      if (!reason) return;
      await admin.block("email", ds.email, reason);
      flash("Adressen är spärrad.");
      return render();
    }

    case "block-lift": {
      const note = await ask("Häv spärren?\n\nAnteckning:");
      if (note === null) return;
      await admin.liftBlock(ds.block, note);
      flash("Spärren är hävd.");
      return render();
    }

    case "suspend": {
      const reason = await ask(
        "Stäng av företaget?\n\nIngen får data förrän du häver det. Inget raderas.\n\nSkäl (obligatoriskt):",
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
      const note = await ask(
        verified
          ? "Markera som kontrollerat\n\nT.ex. ringde växeln eller firmatecknare enligt Bolagsverket.\n\nHur kontrollerades det?:"
          : "Avvisa företaget?\n\nSkäl (obligatoriskt):",
      );
      if (!note) return;
      await admin.verifyCompany(state.companyId, ds.status, note);
      flash(verified ? "Behörigheten är markerad som kontrollerad." : "Företaget är avvisat.");
      return render();
    }

    case "staff-remove":
      if (!await sure(`Ta bort rollen för ${ds.email}?`)) return;
      await admin.setStaff(ds.email, "");
      flash("Rollen är borttagen.");
      return render();

    case "review-approve":
    case "review-reject": {
      const approved = action === "review-approve";
      const note = await ask(approved ? "Godkänn granskningen\n\nAnteckning:" : "Avslå granskningen\n\nSkäl:");
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
  if (event.target.id === "pkgCount") autoQuote();
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
  const name = await ask(`Förarkod för ${plate || "bilen"}\n\nNamnet visas som telefonens namn.\n\nFörarens namn:`);
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

/**
 * Priset för "Lägg till plats" räknas av sig självt när antal och län är
 * valda (serverns prismotor, samma som offerten alltid använt) -- inget
 * "Räkna pris"-steg. Beställningen kräver fortfarande att det som skickas är
 * exakt det som visades (`state.quotedChange`).
 */
let quoteTimer = null;
function autoQuote() {
  clearTimeout(quoteTimer);
  const box = document.getElementById("pkgQuote");
  if (!box) return;
  state.quotedChange = null;
  const count = Number(document.getElementById("pkgCount")?.value || 0);
  const county = document.getElementById("pkgCounty")?.value || "";
  if (count < 1 || !county) {
    box.innerHTML = '<p class="muted small">Priset räknas när antal och län är valda.</p>';
    return;
  }
  box.innerHTML = '<p class="muted small">Räknar priset …</p>';
  const companyId = state.companyId;
  quoteTimer = setTimeout(async () => {
    try {
      const { change } = packageChange();
      const quote = await admin.quote(companyId, change);
      if (!box.isConnected || state.companyId !== companyId) return;
      state.quotedChange = JSON.stringify(change);
      box.innerHTML = sales.quoteBox(quote);
    } catch (error) {
      if (box.isConnected) box.innerHTML = `<p class="error small">${sales.esc(error?.message ?? "Kunde inte räkna priset.")}</p>`;
    }
  }, 300);
}

function packageChange() {
  const count = Math.max(0, Number(document.getElementById("pkgCount")?.value || 0));
  const county = document.getElementById("pkgCounty")?.value || "";
  if (count < 1) {
    throw new ApiError(400, "Ange hur många platser.", "vehicles_required");
  }
  if (!county) {
    throw new ApiError(400, "Välj län.", "county_required");
  }
  // Ett län per plats; extra län säljs inte längre.
  const vehicles = Array.from({ length: count }, () => ({
    plate: "",
    label: "",
    baseCounty: county,
    extraCounties: [],
  }));
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

    case "org-lookup": {
      const form = document.getElementById("companyForm");
      const org = document.getElementById("orgLookup")?.value.trim();
      if (!org) throw new ApiError(400, "Skriv ett organisationsnummer att slå upp.", "org_required");
      state.lookupOrg = org;
      state.lookup = await admin.lookup(org);
      const box = document.getElementById("orgLookupResult");
      if (box) box.innerHTML = sales.lookupResult(state.lookup);
      sales.prefillFromLookup(form, state.lookup);
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
      // Provet är alltid 7 dagar (fleet/trials.py); mer tid är en förlängning.
      const result = await admin.startTrial(companyId, vehicles);
      flash(
        `Provet omfattar nu ${result.vehicles} av högst ${result.vehicleLimit} platser` +
          (result.plannedDays ? ` (${result.plannedDays} dagar)` : "") +
          ". " +
          (result.endsAt ? "" : "Det startar när första kontot loggar in i appen. ") +
          "Bjud in kontona under Platser.",
      );
      return render();
    }

    case "trial-vehicles": {
      const limit = Number(document.getElementById("trialVehicleLimit")?.value || 0);
      const reason = await ask(`Provet får högst ${limit} ${limit === 1 ? "plats" : "platser"}?\n\nSkäl (obligatoriskt):`);
      if (reason === null || !reason.trim()) return;
      const result = await admin.setTrialVehicleLimit(state.companyId, limit, reason.trim());
      flash(`Provet får nu ha högst ${result.vehicleLimit} ${result.vehicleLimit === 1 ? "plats" : "platser"}.`);
      return render();
    }

    case "trial-extend": {
      const days = Number(ds.days || document.getElementById("trialExtendDays")?.value || 0);
      const reason = await ask(`Förläng provet med ${days} dagar?\n\nSkäl (obligatoriskt):`);
      if (reason === null || !reason.trim()) return;
      await admin.extendTrial(state.companyId, days, reason.trim());
      flash("Provperioden är förlängd.");
      return render();
    }

    case "trial-end": {
      const reason = await ask("Avsluta provet nu?\n\nKunden får inga fler tips. Ett betalt abonnemang påverkas inte.\n\nSkäl (obligatoriskt):");
      if (reason === null || !reason.trim()) return;
      const result = await admin.endTrial(state.companyId, reason.trim());
      flash(result.changed ? "Provet är avslutat." : "Provet var redan avslutat.");
      return render();
    }

    case "company-pause": {
      const reason = await ask(
        "Pausa tipsen för hela företaget?\n\nInga tips eller notiser tills du återupptar. Inget raderas.\n\nSkäl (obligatoriskt):",
      );
      if (reason === null || !reason.trim()) return;
      await admin.pauseCompany(state.companyId, reason.trim());
      flash("Tipsen är pausade.");
      return render();
    }

    case "company-resume": {
      const note = await ask("Återuppta tipsen?\n\nAnteckning:", "", { ok: "Återuppta" });
      if (note === null) return;
      await admin.resumeCompany(state.companyId, note.trim());
      flash("Tipsen är återupptagna.");
      return render();
    }

    case "member-pause": {
      const reason = await ask(
        `Pausa tipsen för ${ds.email || "kontot"}?\n\nKontot kan fortfarande logga in i kundportalen.\n\nSkäl (obligatoriskt):`,
      );
      if (reason === null || !reason.trim()) return;
      await admin.pauseAccount(ds.user, state.companyId, reason.trim());
      flash("Tipsen är pausade för kontot.");
      return render();
    }

    case "member-resume": {
      const note = await ask("Återuppta tipsen för kontot?\n\nAnteckning:", "", { ok: "Återuppta" });
      if (note === null) return;
      await admin.resumeAccount(ds.user, state.companyId, note.trim());
      flash("Tipsen är återupptagna för kontot.");
      return render();
    }

    case "discount-clear": {
      const reason = await ask("Ta bort prisrabatten?\n\nSkäl (valfritt):", "", { ok: "Ta bort" });
      if (reason === null) return;
      await admin.clearDiscount(state.companyId, reason.trim());
      flash("Rabatten är borttagen.");
      return render();
    }

    case "pkg-coupon": {
      const code = document.getElementById("couponCode")?.value.trim();
      if (!code) throw new ApiError(400, "Skriv kupongkoden.", "code_required");
      const panel = document.getElementById("salesPanel");
      let vehicles = [];
      try {
        vehicles = packageChange().vehicles;
      } catch {
        // Betalande kund: kupongen flyttar debiteringen. Utan platser
        // svarar servern om de ändå behövs.
      }
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
          "Vänta tills priset har räknats, och läs upp det för kunden.",
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

    /* --- Platsens län (direkt, högst 2 byten per månad) --- */

    case "base-change": {
      const county = document.querySelector(`[data-base-for="${ds.license}"]`)?.value;
      if (!county) throw new ApiError(400, "Välj det nya länet i listan först.", "county_required");
      if (!await sure(`Byta län till ${countyLabel(county)}? Gäller direkt. Högst 2 byten per månad.`)) return;
      // Fler län från äldre avtal behålls; själva länet byts direkt för alla platser.
      const extras = splitList(ds.extras).filter((c) => c !== county);
      await admin.setTrialCounties(ds.license, county, extras);
      flash(`${memberLabel(ds)} har nu ${countyLabel(county)} som län.`);
      return render();
    }

    case "pending-undo": {
      const reason = await ask(`Ångra "${ds.label}"?\n\nInget ändras vid förnyelsen.\n\nSkäl (obligatoriskt):`);
      if (!reason) return;
      await admin.undoPendingChange(ds.change, reason);
      flash(`"${ds.label}" är ångrad.`);
      return render();
    }

    case "car-plate-ask": {
      const plate = await ask(`Nytt registreringsnummer för ${ds.plate}?\n\nLänen och perioden följer med. Förarna behöver en ny inbjudan.`);
      if (!plate) return;
      const result = await admin.changeVehicle(ds.license, plate.trim(), "permanent");
      flash(`Bilen är nu ${result.plate}. Förarna behöver en ny inbjudan.`);
      return render();
    }

    case "car-remove": {
      if (ds.trial) {
        const reason = await ask(`Ta bort provplatsen ${memberLabel(ds)}?\n\nKontot förlorar åtkomsten direkt.\n\nSkäl (obligatoriskt):`);
        if (!reason) return;
        await admin.removeLicense(ds.license, reason);
        flash(`${memberLabel(ds)} är borttagen.`);
        return render();
      }
      return prepareChange(ds.license, { cancelLicenseIds: [ds.license] },
        `Avsluta ${memberLabel(ds)} vid nästa förnyelse – ingen mer debitering för platsen`, { allowNow: true });
    }

    case "car-remove-now": {
      const reason = await ask(`Ta bort ${memberLabel(ds)} nu?\n\nKontot förlorar åtkomsten direkt. Ingen återbetalning.\n\nSkäl (obligatoriskt):`);
      if (!reason) return;
      await admin.removeLicense(ds.license, reason);
      state.pending = null;
      flash(`${memberLabel(ds)} är borttagen.`);
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

    case "car-plate": {
      const plate = document.getElementById(`plate-${ds.license}`)?.value.trim();
      if (!plate) throw new ApiError(400, "Skriv det nya registreringsnumret.", "plate_required");
      const temporary = ds.mode === "temporary";
      if (!await sure(temporary
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

    case "lic-cancel": {
      if (!await sure(`Avsluta platsen ${ds.plate} vid nästa förnyelse? Bilen fungerar perioden ut.`)) return;
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
      const reason = await ask("Säg upp till periodens slut?\n\nKunden har åtkomst perioden ut, sedan debiteras inget mer.\n\nVarför slutar kunden?:");
      if (reason === null) return;
      const result = await admin.cancelSubscription(companyId, reason, false);
      flash(`Uppsagt till ${result.effectiveAt?.slice(0, 10)}. Kunden har åtkomst till dess.${stripeWarning(result)}`);
      return render();
    }

    case "undo-cancel": {
      const result = await admin.undoCancel(companyId);
      flash(`Uppsägningen är ångrad.${stripeWarning(result)}`);
      return render();
    }

    case "terminate-now": {
      const reason = await ask(
        "Avsluta allt direkt?\n\nÅtkomst, platser och prov stängs nu och Stripe slutar debitera. Ingen återbetalning.\n\nSkäl (obligatoriskt):",
      );
      if (!reason) return;
      if (!await sure("Är du säker?\n\nDet går inte att ångra.", { ok: "Avsluta direkt" })) return;
      const result = await admin.cancelSubscription(companyId, reason, true);
      flash(`Abonnemanget är avslutat.${stripeWarning(result)}`);
      if (await sure("Arkivera bolaget också?\n\nDet döljs i listorna men kan återställas.", { ok: "Arkivera", danger: false })) {
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
      const name = await ask(
        "Radera bolaget permanent?\n\nPlatser, telefoner, beställningar, chatt och inloggningar tas bort och går inte att få tillbaka.\n\n" +
          "Skriv bolagets namn för att bekräfta:",
      );
      if (!name) return;
      const result = await admin.deleteCompany(companyId, name);
      const deleted = result.deleted ?? {};
      const left = deleted["inloggningar kvar"] ?? 0;
      const total = Object.entries(deleted)
        .filter(([key]) => key !== "inloggningar kvar")
        .reduce((sum, [, n]) => sum + n, 0);
      flash(
        `Bolaget är raderat (${total} rader, ${deleted.inloggningar ?? 0} inloggningar). ` +
          (left ? `${left} inloggning(ar) kunde inte raderas -- se Konton.` : "Bolaget kan registrera sig och prova igen."),
      );
      state.companyId = null;
      state.kundFilter = "alla";
      return render();
    }

    case "copy-link":
      await navigator.clipboard.writeText(ds.url);
      flash("Betallänken är kopierad. Skicka den till kunden.");
      return render();

    case "order-link": {
      const payment = await choose("Hur ska kunden betala?", [
        ["stripe_card", "Kort (betallänk)"], ["stripe_invoice", "Faktura via e-post"],
      ]);
      if (!payment) return;
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
      if (!await sure("Avbryta den obetalda ordern? En faktura i Stripe makuleras.")) return;
      await admin.cancelOrder(ds.order, "Avbruten av säljare");
      flash("Ordern är avbruten.");
      return render();
    }

    case "coupon-off": {
      if (!await sure("Stänga av kupongen? Kampanjkoden i Stripe-kassan stängs också. Redan inlösta påverkas inte.")) return;
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
 * Kategorier och län ur beviljandeformuläret (eller redigeringsraden).
 * Alla kategorier = `allCategories` (NULL på servern: följer med om en
 * kategori läggs till). Inga län ikryssade = alla län.
 */
function readGrantChoice(categoryField, countyField) {
  const checked = (name) =>
    [...document.querySelectorAll(`input[name="${CSS.escape(name)}"]:checked`)].map((el) => el.value);
  const categories = checked(categoryField);
  const counties = checked(countyField);
  const all = categories.length === views.GRANT_CATEGORIES.length;
  const labels = Object.fromEntries(views.GRANT_CATEGORIES);
  return {
    categories,
    categoryText: all ? "alla" : categories.map((c) => labels[c] ?? c).join(", "),
    countyText: counties.length ? counties.map(countyLabel).join(", ") : "alla",
    body: {
      ...(all ? { allCategories: true } : { categories }),
      ...(counties.length ? { allCounties: false, counties } : { allCounties: true }),
    },
  };
}

/** Kortets rubrik i bekräftelser: regnr när det finns, annars "platsen". */
function memberLabel(ds) {
  return ds.plate || "platsen";
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

/** Ändring på en befintlig plats: offert, bekräftelse, beställning. */
async function quotedOrder(change) {
  const quote = await admin.quote(state.companyId, change);
  const box = document.createElement("div");
  box.innerHTML = sales.quoteBox(quote);
  if (!await sure(`${box.innerText}\n\nHar kunden godkänt det här?`)) return;
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
