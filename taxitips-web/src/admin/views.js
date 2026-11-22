import { countyName, date, dateTime, money } from "../portal/api.js";
import {
  addCarsBlock, cancelBlock, discountBlock, ordersCard, ownerBlock, profileBlock,
  quoteBox, redemptionsCard, registryBlock, trialExtendBlock,
} from "./sales.js";
import { crmNotesCard } from "./crm.js";
import { notifyCard } from "../notify_editor.js";
import { icon } from "./nav.js";

/**
 * Adminwebbens vyer, som rena funktioner från data till HTML.
 *
 * Inga belopp räknas här. MRR och månadsbelopp kommer från backendens
 * prismotor (fleet/pricing.py) -- samma som fakturerar.
 */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const STATUS = {
  active: ["pill-ok", "Aktiv"],
  trialing: ["pill-warn", "Prov"],
  past_due: ["pill-danger", "Förfallen"],
  canceled: ["pill-danger", "Avslutad"],
  none: ["", "Inget"],
  trial: ["pill-warn", "Provplats"],
  pending_cancel: ["pill-warn", "Avslutas"],
  sent: ["pill-ok", "Skickad"],
  failed: ["pill-danger", "Misslyckad"],
  suppressed: ["pill-warn", "Undertryckt"],
  expired: ["", "Utgången"],
  pending: ["pill-warn", "Väntar"],
  sending: ["pill-warn", "Skickas"],
  open: ["pill-warn", "Öppen"],
  approved: ["pill-ok", "Godkänd"],
  rejected: ["pill-danger", "Avslagen"],
};

const TRIAL_SOURCE = {
  self_signup: "självregistrering",
  sales_invite: "säljarinbjudan",
  sales: "upplagt av säljare",
  coupon: "kupong",
};

function pill(status) {
  const [cls, label] = STATUS[status] ?? ["", status ?? "—"];
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

/* --- Översikt --------------------------------------------------------- */

function kpi(label, value, { alert = false, view = "" } = {}) {
  const tag = view ? "button" : "div";
  const attrs = view ? ` type="button" data-action="goto" data-view="${esc(view)}"` : "";
  return `<${tag} class="kpi${alert ? " kpi-alert" : ""}"${attrs}><span>${esc(label)}</span><b>${value}</b></${tag}>`;
}

/* --- Kundens läge, ur samma fält som kundsidan visar ------------------- */

/** Samma sak ur kundsidans svar (GET /api/admin/companies/<id>). */
function doneFromDetail(d) {
  const open = (d.licenses ?? []).filter((l) => LICENSE_OPEN.includes(l.status));
  const s = d.subscription;
  return {
    foretag: !d.profile || d.profile.verificationStatus === "verified",
    bilar: open.length > 0,
    forare: open.some((l) => l.assigned),
    konto: (d.members ?? []).some((m) => m.status === "active"),
    betalning: !!(s && ["active", "past_due"].includes(s.status) && s.hadSuccessfulPayment),
  };
}

const DAY_MS = 86400000;
const daysTo = (iso) => (iso ? Math.ceil((new Date(iso) - Date.now()) / DAY_MS) : null);
const ENDED_REASONS = ["trial_ended", "canceled", "period_expired"];
const ORG_MISSING = "Org.nr saknas – behövs vid köp";
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const inDays = (n) => (n <= 0 ? "idag" : n === 1 ? "imorgon" : `om ${n} dagar`);

const ACCESS_TEXT = {
  trial_not_started: "provet startar när första kontot loggar in i appen",
  trial_ended: "provet är slut",
  company_suspended: "avstängt",
  company_paused: "tipsen är pausade",
  past_due: "betalningen saknas",
  period_expired: "perioden har gått ut",
  canceled: "uppsagt",
  no_subscription: "inget abonnemang",
  company_inactive: "inget prov eller abonnemang än",
  unknown_company: "företaget saknas",
};

/** Status i ett ord: samma ord i listan och på kundsidan. */
function customerStatus({ suspended, paused, trial, subscriptionStatus, cancelAtPeriodEnd, endedReason }) {
  if (suspended) return ["pill-danger", "Avstängd"];
  if (subscriptionStatus === "past_due") return ["pill-danger", "Obetald"];
  if (subscriptionStatus === "active") {
    return cancelAtPeriodEnd ? ["pill-warn", "Uppsagd"] : ["pill-ok", "Betalar"];
  }
  if (trial && ["active", "pending"].includes(trial.status)) return ["pill-warn", "Prov"];
  if (paused) return ["pill-warn", "Pausad"];
  if (subscriptionStatus === "canceled" || endedReason) return ["", "Slut"];
  return ["", "Ny"];
}

/** Listraden (GET /api/admin/companies) till customerStatus. */
const statusOfRow = (c) => ({
  suspended: c.suspended,
  trial: c.trial,
  subscriptionStatus: c.subscriptionStatus,
  cancelAtPeriodEnd: c.cancelAtPeriodEnd,
  endedReason: ENDED_REASONS.includes(c.accessReason),
});

/** Kundsidans svar (GET /api/admin/companies/<id>) till customerStatus. */
const statusOfDetail = (d) => ({
  suspended: !!d.suspension,
  paused: !!d.pause,
  trial: d.trial,
  subscriptionStatus: d.subscription?.status,
  cancelAtPeriodEnd: d.subscription?.cancelAtPeriodEnd,
  endedReason: ENDED_REASONS.includes(d.access?.reason) || ["ended", "canceled"].includes(d.trial?.status),
});

function statusPill([cls, label]) {
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

/**
 * Det som faktiskt kräver någon: en rad per kund, med skälet först. `sec` är
 * delen av kundsidan som öppnas, `go` texten på knappen.
 */
function attention(c) {
  const days = daysTo(c.trial?.endsAt);
  const healthyPaid = c.subscriptionStatus === "active" && !c.cancelAtPeriodEnd;
  if (c.suspended) return null;
  if (c.subscriptionStatus === "past_due") {
    return { why: "Betalningen har inte gått igenom", sec: "betalning", level: 5, go: "Se betalning" };
  }
  if (c.trial?.status === "active" && days !== null && days <= 3 && c.subscriptionStatus !== "active") {
    return { why: `Provet slutar ${inDays(days)} – inget köp än`, sec: "betalning", level: 4, go: "Skicka betallänk" };
  }
  if (c.cancelAtPeriodEnd) {
    return { why: "Har sagt upp – ring och fråga varför", sec: "betalning", level: 2, go: "Öppna kunden" };
  }
  if (c.unpaidOrders) {
    return { why: "Beställning väntar på betalning", sec: "betalning", level: 3, go: "Se betalning" };
  }
  // Friska betalande utan öppen faktura: inget brus — Uppföljning tar risklägen.
  if (healthyPaid) return null;
  if (c.verificationStatus === "unverified") {
    return { why: "Ny registrering – ring och kontrollera", sec: "uppgifter", level: 3, go: "Öppna kunden" };
  }
  if (c.trial && !(c.membershipsAssigned ?? c.phones) && c.licenses) {
    return { why: "Har platser men inget konto tilldelat", sec: "platser", level: 1, go: "Tilldela" };
  }
  if (c.trial && !c.licenses) {
    return { why: "Har inga platser än", sec: "betalning", level: 1, go: "Lägg till plats" };
  }
  return null;
}

/* --- Hem ---------------------------------------------------------------- */

/**
 * Hem: en lista, viktigast först. Varje rad är vem, vad och en knapp. Inkorgen
 * (support, tipprapporter, granskningar, CRM) och kunderna som behöver något
 * ligger i samma lista; nyckeltal och datakällor är hopfällda under.
 */
export function oversikt(d, list = { companies: [] }, inbox = {}) {
  const supportWaiting = inbox.supportWaiting ?? 0;
  const tipReportsOpen = inbox.tipReportsOpen ?? d.tipReportsOpen ?? 0;
  const reviewsOpen = d.reviewsOpen ?? 0;
  const crmOverdue = inbox.crmTasksOverdue ?? d.crmTasksOverdue ?? 0;
  const statusReport = inbox.statusReport ?? null;
  const statusLine = inbox.statusLine ?? "";
  const subs = d.subscriptions ?? {};
  const companies = list.companies ?? [];

  const goto = (view, filter = "") =>
    `data-action="goto" data-view="${esc(view)}"${filter ? ` data-filter="${esc(filter)}"` : ""}`;
  const items = [
    supportWaiting ? {
      level: 6, who: "Support", go: "Öppna support", attrs: goto("support"),
      what: supportWaiting === 1 ? "1 fråga väntar på svar" : `${supportWaiting} frågor väntar på svar`,
    } : null,
    ...companies.map((c) => {
      const a = attention(c);
      return a ? {
        level: a.level, who: c.name, what: a.why, go: a.go,
        attrs: `data-action="open-company" data-id="${esc(c.id)}" data-tab="${esc(a.sec)}"`,
      } : null;
    }),
    reviewsOpen ? {
      level: 3, who: "Riskgranskning", go: "Granska", attrs: goto("granskning"),
      what: reviewsOpen === 1 ? "1 granskning väntar" : `${reviewsOpen} granskningar väntar`,
    } : null,
    tipReportsOpen ? {
      level: 3, who: "Tipprapporter", go: "Granska", attrs: goto("tipprapporter"),
      what: tipReportsOpen === 1 ? "1 rapport att granska" : `${tipReportsOpen} rapporter att granska`,
    } : null,
    crmOverdue ? {
      level: 2, who: "CRM", go: "Öppna uppgifter", attrs: goto("pipeline", "tasks"),
      what: crmOverdue === 1 ? "1 försenad uppgift" : `${crmOverdue} försenade uppgifter`,
    } : null,
  ].filter(Boolean).sort((a, b) => b.level - a.level);

  const today = new Date().toLocaleDateString("sv-SE", { weekday: "long", day: "numeric", month: "long" });
  const lead = items.length
    ? `${items.length === 1 ? "En sak väntar" : `${items.length} saker väntar`} – viktigast först.`
    : "Inget väntar just nu.";
  // Genvägar till det man gör oftast; samma mål som menyn, bara närmare.
  const shortcut = (ico, label, attrs, extra = "") => `
    <li><button type="button" class="shortcut" ${attrs}>
      ${icon(ico, "shortcut-icon")}<span>${esc(label)}</span>${extra}
    </button></li>`;
  const count = (n) => (n ? `<span class="nav-count">${esc(n)}</span>` : "");
  const overall = statusReport?.overall ?? "";

  return `
    <div class="page-head">
      <div><h1>Hem</h1>
        <p class="muted"><span class="home-date">${esc(today)}</span> · ${esc(lead)}</p></div>
      <div class="btn-row">
        <button class="btn btn-quiet" type="button" data-action="palette">${icon("search", "btn-icon")}Sök kund</button>
        <button class="btn btn-primary" type="button" data-action="goto" data-view="nykund">+ Ny kund</button>
      </div>
    </div>

    <div class="home-grid">
      <div class="card home-todo">
        <h2>Att göra${items.length ? ` <span class="muted">(${esc(items.length)})</span>` : ""}</h2>
        ${items.length ? `<ul class="todo">${items.map((item) => `
          <li><button class="todo-row${item.level >= 5 ? " is-danger" : ""}" ${item.attrs}>
            <span class="todo-dot lvl-${Math.min(item.level, 3)}" aria-hidden="true"></span>
            <span class="todo-main"><b>${esc(item.who)}</b><span class="muted">${esc(item.what)}</span></span>
            <span class="todo-cta">${esc(item.go)}</span>
          </button></li>`).join("")}</ul>`
          : `<p class="home-empty">${icon("shield", "home-empty-icon")}<span>Allt är omhändertaget. Nya
              registreringar, supportfrågor och prov som tar slut dyker upp här.</span></p>`}
      </div>

      <nav class="card home-shortcuts" aria-label="Genvägar">
        <h2>Genvägar</h2>
        <ul>
          ${shortcut("plus", "Lägg upp en kund", goto("nykund"))}
          ${shortcut("chat", "Svara på supportfrågor", goto("support"), count(supportWaiting))}
          ${shortcut("funnel", "Mina CRM-uppgifter", goto("pipeline", "tasks"), count(crmOverdue))}
          ${shortcut("ticket", "Skapa en kupong", goto("kuponger"))}
          ${shortcut("calendar", "Lägg till evenemang", goto("evenemang"))}
          ${shortcut("pulse", statusReport ? `Status: ${statusLine || "okänt"}` : "Status", goto("status"),
            overall ? `<span class="st-dot st-${esc(overall)}" aria-hidden="true"></span>` : "")}
        </ul>
      </nav>
    </div>

    <section class="home-kpis" aria-labelledby="kpiTitle">
      <div class="section-head">
        <h2 id="kpiTitle">Nyckeltal</h2>
        <button type="button" class="link-btn" data-action="goto" data-view="dashboard">Hela rapporten →</button>
      </div>
      <div class="kpis">
        ${kpi("Kunder", esc(d.companies), { view: "kunder" })}
        ${kpi("Betalande", esc(subs.active ?? 0), { view: "kunder" })}
        ${kpi("Prov", esc(d.trialsActive), { view: "kunder" })}
        ${kpi("MRR exkl. moms", esc(money(d.mrrOre, d.currency)))}
        ${kpi("Förare i tjänst nu", esc(d.sessionsActive))}
      </div>
    </section>
  `;
}

/* --- Kunder ------------------------------------------------------------- */

/** Synliga direkt, och de som ligger bakom knappen Filter. */
const FILTERS_MAIN = [
  ["alla", "Alla"],
  ["atgard", "Behöver åtgärd"],
];
const FILTERS_MORE = [
  ["prov", "Prov"],
  ["betalande", "Betalande"],
  ["avstangda", "Avstängda"],
  // Hämtas för sig (fleet/archive.py): arkiverade bolag syns inte i de andra.
  ["arkiverade", "Arkiverade"],
];

function matchesFilter(c, filter) {
  switch (filter) {
    case "atgard": return !!attention(c);
    case "prov": return !!c.trial;
    case "betalande": return ["active", "past_due"].includes(c.subscriptionStatus);
    case "avstangda": return !!c.suspended;
    case "arkiverade": return !!c.archived;
    default: return true;
  }
}

/** "BankID ✓" och/eller org.nr-saknas: en lugn upplysning, inget fel. */
function identityHints(orgNumber, bankId) {
  return [
    bankId ? '<span class="id-chip">BankID ✓</span>' : "",
    orgNumber ? "" : `<span class="muted">${esc(ORG_MISSING)}</span>`,
  ].filter(Boolean).join(" ");
}

/** Nästa händelse i kundens liv, ur listraden. */
function nextEvent(c) {
  if (c.suspended) return "";
  if (c.subscriptionStatus === "past_due") return "betalningen saknas";
  if (c.subscriptionStatus === "active") {
    if (!c.periodEnd) return "";
    return c.cancelAtPeriodEnd ? `åtkomsten slutar ${date(c.periodEnd)}` : `förnyelse ${date(c.periodEnd)}`;
  }
  if (c.trial?.status === "active" && c.trial.endsAt) return `provet slutar ${date(c.trial.endsAt)}`;
  if (c.trial?.status === "pending") return "provet startar vid första inloggningen";
  return "";
}

export function kunder(list, query = "", filter = "alla") {
  const all = list.companies ?? [];
  const rows = all.filter((c) => matchesFilter(c, filter));
  const chip = ([id, label]) => `<button class="chip" role="tab" data-action="kund-filter" data-filter="${id}"
    aria-selected="${id === filter}">${esc(label)} <span class="muted">${esc(
      id === "arkiverade" ? (list.archivedCount ?? 0)
        : filter === "arkiverade" ? "" : all.filter((c) => matchesFilter(c, id)).length,
    )}</span></button>`;
  const moreActive = FILTERS_MORE.find(([id]) => id === filter);
  return `
    <div class="page-head">
      <h1>Alla kunder</h1>
      <button class="btn btn-primary" data-action="goto" data-view="nykund">+ Ny kund</button>
    </div>
    <form class="toolbar" id="searchForm">
      <label class="visually-hidden" for="q">Sök</label>
      <input id="q" name="q" value="${esc(query)}" placeholder="Sök namn eller org.nr" />
      <button class="btn btn-quiet" type="submit">Sök</button>
    </form>
    <div class="chips" role="tablist" aria-label="Filter">
      ${FILTERS_MAIN.map(chip).join("")}
      <details class="filter-more"${moreActive ? " open" : ""}>
        <summary class="btn btn-quiet btn-small">Filter${moreActive ? `: ${esc(moreActive[1])}` : ""}</summary>
        <div class="filter-more-items">${FILTERS_MORE.map(chip).join("")}</div>
      </details>
    </div>
    <div class="card list-card">
      ${rows.length ? rows.map((c) => {
        const next = nextEvent(c);
        const hints = identityHints(c.orgNumber, c.bankId === true);
        return `
        <button class="cust-row" data-action="open-company" data-id="${esc(c.id)}" data-tab="${esc(attention(c)?.sec ?? "")}">
          <span class="cust-main"><b>${esc(c.name)}</b>
            ${c.orgNumber ? `<span class="muted mono">${esc(c.orgNumber)}</span>` : ""}
            ${hints ? `<span class="cust-hints">${hints}</span>` : ""}</span>
          <span class="cust-status">${statusPill(customerStatus(statusOfRow(c)))}</span>
          <span class="cust-seats muted">${esc(plural(c.licenses ?? 0, "plats", "platser"))}</span>
          <span class="cust-next muted">${next ? `Nästa: ${esc(next)}` : "—"}</span>
        </button>`;
      }).join("") : '<p class="muted">Inga kunder här.</p>'}
    </div>
  `;
}

/* --- En kund ------------------------------------------------------------
 *
 * Uppifrån: rubrik, en tidslinje (Registrerad → Prov → Betalar → Uppsagd),
 * ETT kort med nästa steg och knapparna för det, och sedan fyra hopfällda
 * delar: Platser, Betalning, Uppgifter, Historik. Farliga saker sist.
 */

/** Kundsidans flikar, i den ordning man oftast behöver dem. */
export const KUND_TABS = [
  ["oversikt", "Översikt"],
  ["platser", "Platser"],
  ["betalning", "Betalning"],
  ["inloggningar", "Inloggningar"],
  ["foretag", "Företaget"],
  ["historik", "Historik"],
];

const SECTION_FOR = {
  oversikt: "oversikt",
  platser: "platser", bilar: "platser", forare: "platser",
  betalning: "betalning",
  inloggningar: "inloggningar", konton: "inloggningar", konto: "inloggningar",
  uppgifter: "foretag", foretag: "foretag",
  historik: "historik",
};

/** Ett flik-, steg- eller gammalt delnamn till fliken på kundsidan. */
export function kundTab(tab) {
  return SECTION_FOR[tab] ?? "oversikt";
}

/** Det som är fel eller saknas, i den ordning det brådskar. */
function issues(d) {
  const s = d.subscription;
  const done = doneFromDetail(d);
  const list = [];
  const add = (level, text, sec, label, target = "") => list.push({ level, text, sec, label, target });
  if (s?.status === "past_due") add(3, "Betalningen har inte kommit in.", "betalning", "Betalning");
  const unpaid = (d.orders ?? []).filter((o) => o.status === "pending_payment").length;
  if (unpaid) add(2, `${plural(unpaid, "beställning väntar", "beställningar väntar")} på betalning.`, "betalning", "Se beställningar");
  if (d.profile?.verificationStatus && d.profile.verificationStatus !== "verified") {
    add(2, "Behörigheten är inte kontrollerad.", "foretag", "Kontrollera");
  }
  if (!done.bilar) add(1, "Har inga platser.", "betalning", "Lägg till plats", "salesPanel");
  else if (!done.forare) add(1, "Inget konto är tilldelat någon plats.", "platser", "Tilldela");
  if (!done.konto) add(1, "Ingen kan logga in i kundportalen.", "inloggningar", "Bjud in", "ownerCard");
  const reviews = (d.reviews ?? []).filter((r) => r.status === "open").length;
  if (reviews) add(1, `${plural(reviews, "riskgranskning väntar", "riskgranskningar väntar")}.`, "", "Granskning");
  return list.sort((a, b) => b.level - a.level);
}

/* --- Tidslinjen ------------------------------------------------------- */

/** "dag X av Y" för ett pågående prov, ur startat/slutdatum. */
function trialDayText(t) {
  if (t?.status !== "active" || !t.startedAt || !t.endsAt) return "";
  const total = Math.max(1, Math.round((new Date(t.endsAt) - new Date(t.startedAt)) / DAY_MS));
  const day = Math.min(total, Math.max(1, Math.floor((Date.now() - new Date(t.startedAt)) / DAY_MS) + 1));
  return `dag ${day} av ${total}`;
}

/** Fyra steg i den ordning en kund går dem. Allt ur kundsidans svar. */
function timeline(d) {
  const s = d.subscription;
  const t = d.trial;
  const cancelled = !!(s?.cancelAtPeriodEnd || s?.status === "canceled");
  const paying = !!(s && (["active", "past_due"].includes(s.status)
    || (s.status === "canceled" && s.hadSuccessfulPayment)));
  const trialReached = !!(t && t.status !== "canceled") || (t?.status === "canceled" && !!t.startedAt);
  const trialOpen = !!(t && ["pending", "active"].includes(t.status));
  const steps = [
    { id: "reg", label: "Registrerad", reached: true, note: date(d.company.createdAt) },
    {
      id: "prov", label: "Prov", reached: trialReached,
      note: !trialReached ? "" : trialOpen
        ? (t.status === "pending" ? "väntar på första inloggning" : trialDayText(t))
        : t.endsAt ? `slutade ${date(t.endsAt)}` : "slut",
    },
    {
      id: "betalar", label: "Betalar", reached: paying,
      note: !paying ? "" : s.status === "past_due" ? "betalning saknas"
        : s.periodEnd ? `betalt till ${date(s.periodEnd)}` : "",
    },
    {
      id: "uppsagd", label: "Uppsagd", reached: cancelled,
      note: !cancelled ? "" : s.status === "canceled"
        ? `avslutad ${date(s.periodEnd)}`
        : `slutar ${date(s.accessUntil || s.periodEnd)}`,
    },
  ];
  const last = steps.reduce((acc, st, i) => (st.reached ? i : acc), 0);
  const endedTrial = last === 1 && !trialOpen;
  return `
    <ol class="tl" aria-label="Kundens väg">
      ${steps.map((st, i) => {
        const cls = i === last ? (endedTrial ? "is-current is-ended" : "is-current")
          : st.reached ? "is-done" : i < last ? "is-skipped" : "";
        return `<li class="tl-step ${cls}"${i === last ? ' aria-current="step"' : ""}>
          <span class="tl-dot" aria-hidden="true"></span>
          <b>${esc(st.label)}</b>
          <span class="tl-note">${esc(st.note || "")}</span>
        </li>`;
      }).join("")}
    </ol>`;
}

/* --- Nästa steg ------------------------------------------------------- */

/** Dagar före provslut då systemet skickar påminnelse (fleet_tick: 3 och 1). */
function trialMailDates(t) {
  if (t?.status !== "active" || !t.endsAt) return [];
  const end = new Date(t.endsAt).getTime();
  return [3, 1].map((n) => end - n * DAY_MS).filter((ts) => ts > Date.now()).map((ts) => date(new Date(ts).toISOString()));
}

/**
 * Vad som händer härnäst och vad systemet gör självt. Allt räknas ur fälten i
 * kundsidans svar -- inget påstås som inte går att läsa ur datat.
 */
function nextStep(d, config) {
  const s = d.subscription;
  const t = d.trial;
  const sell = !!config?.canSell;
  const manage = !!config?.canManage;
  const auto = [];
  let text = "";
  const btn = (label, attrs, primary = false) =>
    `<button class="btn btn-small ${primary ? "btn-primary" : "btn-quiet"}" type="button" ${attrs}>${esc(label)}</button>`;
  const sec = (label, section, target = "", primary = false) =>
    btn(label, `data-action="sec-open" data-sec="${section}"${target ? ` data-target="${target}"` : ""}`, primary);
  const buttons = [];

  const trialOpen = t && ["pending", "active"].includes(t.status);
  const days = daysTo(t?.endsAt);

  if (d.suspension) {
    text = "Företaget är avstängt. Förarna får inga tips och ingen kan logga in.";
    if (manage) buttons.push(btn("Häv avstängningen", `data-action="block-lift" data-block="${esc(d.suspension.id)}"`, true));
  } else if (s?.status === "past_due") {
    text = "Betalningen har inte gått igenom.";
    if (s.graceUntil) {
      auto.push(`betalningsfrist till ${date(s.graceUntil)}`);
      if (!s.renewalStopped) auto.push(`förnyelsen stoppas ${date(s.graceUntil)} om betalningen uteblir`);
    } else {
      auto.push("ingen betalningsfrist gäller");
    }
    if (s.renewalStopped) auto.push("förnyelsen är redan stoppad");
    if (sell) buttons.push(sec("Skicka betallänk", "betalning", "salesPanel", true));
    if (manage) buttons.push(btn("Ge 7 dagar till", 'data-action="extend" data-days="7"'));
  } else if (s?.status === "active" && s.cancelAtPeriodEnd) {
    text = `Kunden har sagt upp. Åtkomsten slutar ${date(s.accessUntil || s.periodEnd)}.`;
    auto.push(`ingen mer debitering efter ${date(s.accessUntil || s.periodEnd)}`);
    if (sell) buttons.push(btn("Ångra uppsägningen", 'data-action="undo-cancel"', true));
  } else if (s?.status === "active") {
    text = s.periodEnd
      ? `Nästa förnyelse ${date(s.periodEnd)}${s.monthlyOre ? ` (${money(s.monthlyOre)} exkl. moms)` : ""}.`
      : "Abonnemanget är aktivt.";
    if (s.renewalStopped) auto.push("förnyelsen är stoppad – ingen ny period dras");
    else if (s.periodEnd) auto.push(`förnyas automatiskt ${date(s.periodEnd)}`);
    if (s.graceUntil) auto.push(`betalningsfrist vid missad betalning: till ${date(s.graceUntil)}`);
    if (sell) buttons.push(sec("Lägg till plats", "betalning", "salesPanel", true));
  } else if (trialOpen && t.status === "pending") {
    text = `Bjud in föraren. Provet (${t.plannedDays ?? config?.trial?.days ?? 7} dagar) startar när första kontot loggar in i appen.`;
    auto.push("provet startar vid första inloggningen");
    buttons.push(sec("Bjud in förare", "platser", "inviteCard", true));
  } else if (trialOpen) {
    const mails = trialMailDates(t);
    text = `Provet slutar ${date(t.endsAt)}${trialDayText(t) ? ` (${trialDayText(t)})` : ""}.`;
    if (mails.length) auto.push(`påminnelsemejl ${mails.join(" och ")}`);
    auto.push(`provet slutar av sig självt ${date(t.endsAt)}`);
    // Fälten finns först när servern skickar dem: påstå inget annars.
    if (t.committed === true) auto.push("första debiteringen sker när provet slutar");
    else if (t.committed === false) auto.push("ingen debitering sker eftersom ingen beställning är gjord");
    if (sell) {
      buttons.push(sec("Skicka betallänk", "betalning", "salesPanel", days !== null && days <= 3));
      buttons.push(btn("Förläng prov 7 dagar", 'data-action="trial-extend" data-days="7"', !(days !== null && days <= 3)));
    }
  } else if (t || ENDED_REASONS.includes(d.access?.reason)) {
    text = t?.endsAt && t.status !== "pending"
      ? `Provet tog slut ${date(t.endsAt)}. Kunden har inte köpt.`
      : "Kunden har inget aktivt abonnemang.";
    auto.push("inget sker automatiskt");
    if (sell) buttons.push(sec("Lägg beställning", "betalning", "salesPanel", true));
  } else {
    text = "Kunden har registrerat sig men har inget prov eller abonnemang än.";
    auto.push("inget sker automatiskt förrän ett prov eller en beställning finns");
    if (sell) {
      buttons.push(sec("Starta prov", "betalning", "salesPanel", true));
      buttons.push(sec("Skicka betallänk", "betalning", "salesPanel"));
    }
  }

  // Allt annat man kan göra här: i en meny, så att huvudsteget syns.
  const more = [];
  const item = (label, attrs) =>
    `<button type="button" class="btn btn-quiet btn-small" role="menuitem" ${attrs}>${esc(label)}</button>`;
  const secItem = (label, section, target = "") =>
    item(label, `data-action="sec-open" data-sec="${section}"${target ? ` data-target="${target}"` : ""}`);
  if (!d.suspension) {
    // Ett prov som väntar på första inloggningen säger redan varför ingen får tips.
    if (d.access && !d.access.ok && !d.pause && s?.status !== "past_due" && !(trialOpen && t.status === "pending")) {
      text += ` Förarna får inga tips: ${ACCESS_TEXT[d.access.reason] ?? d.access.reason}.`;
    }
    if (sell && !(trialOpen && t.status === "pending") && (s || t)) more.push(secItem("Lägg till plats", "betalning", "salesPanel"));
    if (sell && !(d.members ?? []).some((m) => m.status === "active")) {
      more.push(secItem("Bjud in till kundportalen", "inloggningar", "ownerCard"));
    }
    if (manage) more.push(secItem("Ge rabatt", "betalning", "discountCard"));
    if (sell) more.push(secItem("Undantag", "betalning", "undantag"));
    if (sell && !d.pause) more.push(item("Pausa tipsen", 'data-action="company-pause"'));
  }
  // Det som inte syns i rutorna under (riskgranskningar) får en egen rad.
  const reviews = (d.reviews ?? []).filter((r) => r.status === "open").length;

  return `
    <div class="next-card">
      <h2>Nästa steg</h2>
      <p class="next-text">${esc(text)}</p>
      ${auto.length ? `<p class="next-auto">Automatiskt: ${esc(auto.join(" · "))}.</p>` : ""}
      ${buttons.length || more.length ? `<div class="btn-row next-buttons">${buttons.join("")}
        ${more.length ? `<details class="more-menu">
          <summary class="btn btn-small btn-more">Fler åtgärder</summary>
          <div class="more-items" role="menu">${more.join("")}</div>
        </details>` : ""}</div>` : ""}
      ${reviews ? `<p class="next-also"><span>${esc(plural(reviews, "riskgranskning väntar", "riskgranskningar väntar"))}.</span>
        <button class="linklike" type="button" data-action="goto" data-view="granskning">Granska →</button></p>` : ""}
    </div>`;
}

/* --- Sidan -------------------------------------------------------------- */

/** Platser i rubriken: "3 platser · Västra Götalands län · 1 197,00 kr/mån". */
function headerFacts(d, open) {
  const s = d.subscription;
  const counties = [...new Set(open.map((l) => l.baseCounty).filter(Boolean))].map(countyName);
  const where = counties.length <= 2 ? counties.join(", ") : `${counties.length} län`;
  const amount = s && ["active", "past_due"].includes(s.status) && s.monthlyOre
    ? `${money(s.monthlyOre)}/mån` : "";
  return [plural(open.length, "plats", "platser"), where, amount].filter(Boolean).join(" · ");
}

/** En ruta i Översiktens "Läget": rubrik, värde, en rad till, och fliken den öppnar. */
function stateTile(tab, label, value, note, level = "") {
  return `<button type="button" class="kt-tile${level ? ` is-${level}` : ""}" data-action="kund-tab" data-tab="${tab}">
      <span class="kt-tile-label">${esc(label)}</span>
      <b class="kt-tile-value">${esc(value)}</b>
      ${note ? `<span class="kt-tile-note">${esc(note)}</span>` : ""}
      <span class="kt-tile-go" aria-hidden="true">→</span>
    </button>`;
}

/** Läget i fyra rutor: platser, betalning, inloggningar och företaget. */
function stateTiles(d, open) {
  const s = d.subscription;
  const t = d.trial;
  const assigned = open.filter((l) => l.assigned).length;
  const devices = d.devices ?? [];
  const noPush = devices.filter((dv) => !dv.hasPush).length;
  const members = (d.members ?? []).filter((m) => m.status === "active").length;
  const unpaid = (d.orders ?? []).filter((o) => o.status === "pending_payment").length;
  const verification = d.profile?.verificationStatus;

  let pay = ["Inget abonnemang", "", ""];
  if (s?.status === "past_due") pay = ["Betalning saknas", "", "danger"];
  else if (s?.status === "active" && s.cancelAtPeriodEnd) pay = ["Uppsagd", `slutar ${date(s.accessUntil || s.periodEnd)}`, "warn"];
  else if (s?.status === "active") pay = ["Betalar", s.monthlyOre ? `${money(s.monthlyOre)}/mån exkl. moms` : "", "ok"];
  else if (t?.status === "active") pay = ["Prov", `slutar ${date(t.endsAt)}`, ""];
  else if (t?.status === "pending") pay = ["Prov", "startar vid första inloggningen", ""];
  if (unpaid) pay[1] = `${plural(unpaid, "beställning väntar", "beställningar väntar")} på betalning`;

  return `
    <div class="kt-tiles">
      ${stateTile("platser", "Platser",
        open.length ? `${assigned} av ${open.length} har förare` : "Inga platser",
        devices.length ? `${plural(devices.length, "telefon", "telefoner")}${noPush ? ` · ${noPush} utan notiser` : ""}` : "ingen telefon kopplad",
        !open.length || assigned < open.length ? "warn" : "")}
      ${stateTile("betalning", "Betalning", pay[0], pay[1], unpaid ? "warn" : pay[2])}
      ${stateTile("inloggningar", "Inloggningar",
        members ? plural(members, "person", "personer") : "Ingen",
        members ? "kan logga in i kundportalen" : "kan logga in i kundportalen",
        members ? "" : "warn")}
      ${stateTile("foretag", "Företaget",
        verification === "verified" ? "Kontrollerat" : verification === "rejected" ? "Avvisat" : "Inte kontrollerat",
        (d.company.orgNumber || d.profile?.orgNumber) ? `org.nr ${d.company.orgNumber || d.profile.orgNumber}` : "org.nr saknas",
        verification === "verified" ? "" : verification === "rejected" ? "danger" : "warn")}
    </div>`;
}

export function kund(d, config = null, tab = "", pending = null, crm = null, loginLink = null) {
  const c = d.company;
  const p = d.profile ?? {};
  const status = customerStatus(statusOfDetail(d));
  const open = (d.licenses ?? []).filter((l) => LICENSE_OPEN.includes(l.status));
  const found = issues(d);
  const active = kundTab(tab);
  const flagged = new Set(found.filter((i) => i.level >= 2).map((i) => i.sec));
  const orgNumber = c.orgNumber || p.orgNumber || "";
  const bankId = c.bankId === true;
  const hints = identityHints(orgNumber, bankId);
  const members = (d.members ?? []).filter((m) => m.status === "active").length;
  const unpaid = (d.orders ?? []).filter((o) => o.status === "pending_payment").length;
  const phone = (p.contactPhone ?? "").replace(/\s/g, "");

  const counts = { platser: open.length, betalning: unpaid || "", inloggningar: members || "" };
  const tabButton = ([id, label]) => `
    <button type="button" class="kt-tab" role="tab" id="kt-${id}" aria-controls="kp-${id}"
      aria-selected="${id === active}" data-action="kund-tab" data-tab="${id}">
      ${esc(label)}${counts[id] ? ` <span class="kt-n">${esc(counts[id])}</span>` : ""}${
        flagged.has(id) ? '<span class="kt-dot" aria-label="behöver åtgärd"></span>' : ""}
    </button>`;
  const panel = (id, body) => `
    <div class="kt-panel" role="tabpanel" id="kp-${id}" aria-labelledby="kt-${id}" data-tab-panel="${id}"${id === active ? "" : " hidden"}>
      ${body}
    </div>`;

  const danger = config?.canManage || d.archive ? `
    <div class="card danger-zone">
      <h2>Stäng av, arkivera eller radera</h2>
      ${dangerZone(d, config)}
      ${archiveCard(d, config)}
    </div>` : "";

  return `
    <button class="back-link" data-action="back">← Alla kunder</button>
    <div class="kund-head">
      <div class="kund-title">
        <h1>${esc(c.name)}</h1> ${statusPill(status)}
      </div>
      <p class="kund-facts">${esc(headerFacts(d, open))}</p>
      <p class="muted kund-id">${orgNumber ? `<span class="mono">${esc(orgNumber)}</span>` : ""}${
        hints ? `${orgNumber ? " · " : ""}${hints}` : ""}</p>
      <div class="kund-contact">
        ${p.contactName ? `<span class="kund-person">${icon("user", "kund-person-icon")}<span><b>${esc(p.contactName)}</b>${
          p.contactRole ? ` <span class="muted">${esc(p.contactRole)}</span>` : ""}</span></span>` : ""}
        <div class="kund-actions">
          ${phone ? `<a class="btn btn-quiet btn-small" href="tel:${esc(phone)}" title="${esc(p.contactPhone)}">Ring</a>` : ""}
          ${p.contactEmail ? `<a class="btn btn-quiet btn-small" href="mailto:${esc(p.contactEmail)}" title="${esc(p.contactEmail)}">Mejla</a>` : ""}
          <button class="btn btn-quiet btn-small" type="button" data-action="support-start">Chatta</button>
        </div>
      </div>
    </div>

    ${d.suspension ? `
      <div class="suspended-banner" role="alert">
        <b>Företaget är avstängt.</b> ${esc(d.suspension.reason)}
      </div>` : d.pause ? `
      <div class="paused-banner" role="status">
        <b>Tipsen är pausade.</b> ${esc(d.pause.reason)}
        ${config?.canSell ? '<button class="btn btn-quiet" data-action="company-resume">Återuppta tipsen</button>' : ""}
      </div>` : ""}

    <div class="kt-bar-wrap">
      <div class="kt-bar" role="tablist" aria-label="Kundens delar">
        ${KUND_TABS.map(tabButton).join("")}
      </div>
    </div>

    ${panel("oversikt", `
      ${timeline(d)}
      ${nextStep(d, config)}
      <h2 class="kt-sub">Läget</h2>
      ${stateTiles(d, open)}
      ${crmNotesCard(crm, config)}
    `)}
    ${panel("platser", tabPlatser(d, config, pending))}
    ${panel("betalning", tabBetalning(d, config))}
    ${panel("inloggningar", tabKonton(d, config, loginLink))}
    ${panel("foretag", `${tabUppgifter(d, config)}${danger}`)}
    ${panel("historik", `${tabHistorik(d)}<div data-sec-mount="activity"></div>`)}
  `;
}

/* --- Platser --------------------------------------------------------- */

/**
 * Bjud in till en ledig plats — samma som i kundportalen. Nya platser köps
 * under Betalning, de skapas inte gratis här.
 */
function membershipLabel(l) {
  if (l.vehicle) return l.vehicle;
  return `Plats · ${l.baseCounty ? countyName(l.baseCounty) : "utan län"}`;
}

function inviteUnassignedBlock(d, config) {
  if (!config?.canSell) return "";
  const open = (d.licenses ?? []).filter((l) => LICENSE_OPEN.includes(l.status));
  const free = open.filter((l) => !l.assigned);
  if (!free.length) return "";
  return `
    <div class="card" id="inviteCard">
      <h2>Bjud in ett konto</h2>
      <p class="muted">Personen får platsen på e-posten. När hen loggar in i appen binds kontot
        — samma väg som i kundportalen.</p>
      <div class="county-add">
        <select id="inviteLicense" aria-label="Ledig plats">
          ${free.map((l) => `<option value="${esc(l.id)}">${esc(membershipLabel(l))}</option>`).join("")}
        </select>
        <input id="inviteEmail" type="email" placeholder="namn@bolaget.se" autocomplete="off" />
        <button class="btn btn-primary btn-small" data-action="membership-invite-free">Bjud in</button>
      </div>
    </div>`;
}

function addMembershipBlock(d, config) {
  if (!config?.canManage) return "";
  const counties = config?.counties ?? [];
  return exceptionRow("Plats utan betallänk", "Läggs på nästa faktura.", `
      <div class="county-add">
        <input id="newMemberEmail" type="email" placeholder="förarens e-post" autocomplete="off" />
        <select id="newMemberCounty" aria-label="Län för den nya platsen">
          <option value="">Län (valfritt)</option>
          ${counties.map((c) => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("")}
        </select>
        <button class="btn btn-quiet btn-small" data-action="membership-create">Skapa plats</button>
      </div>`);
}

/**
 * Tipskategorierna ett beviljande kan öppna -- samma nycklar och ordning som
 * fleet/features.py ALL_CATEGORIES. Etiketterna är appens kategorirad.
 */
export const GRANT_CATEGORIES = [
  ["transit", "Tåg & buss"],
  ["road", "Trafik/väg"],
  ["flight", "Flyg"],
  ["ferry", "Färja"],
  ["events", "Evenemang"],
];

function grantCategoryText(g) {
  if (g.allCategories !== false) return "alla kategorier";
  const labels = Object.fromEntries(GRANT_CATEGORIES);
  return (g.categories ?? []).map((c) => labels[c] ?? c).join(", ");
}

/** Kryssrutor för kategorier; `checked` = nycklarna som är ikryssade. */
function grantCategoryChecks(name, checked) {
  return GRANT_CATEGORIES.map(([key, label]) => `
    <label class="check"><input type="checkbox" name="${esc(name)}" value="${esc(key)}"
      ${checked.includes(key) ? "checked" : ""} /> ${esc(label)}</label>`).join("");
}

/** Kryssrutor för län; inga ikryssade = alla län. */
function grantCountyChecks(name, counties, checked) {
  return counties.map((c) => `
    <label class="check"><input type="checkbox" name="${esc(name)}" value="${esc(c.code)}"
      ${checked.includes(c.code) ? "checked" : ""} /> ${esc(c.name)}</label>`).join("");
}

/** Redigeringen av ett öppet beviljande: en egen rad under beviljandet. */
function grantEditRow(g, config) {
  const counties = config?.counties ?? [];
  const cats = g.allCategories !== false ? GRANT_CATEGORIES.map(([k]) => k) : (g.categories ?? []);
  const chosenCounties = g.allCounties ? [] : (g.counties ?? []);
  const id = esc(g.id);
  return `
    <tr class="grant-edit-row"><td colspan="4" data-label="">
      <details class="grant-edit">
        <summary>Ändra kategorier och län</summary>
        <fieldset class="grant-fieldset">
          <legend>Kategorier</legend>
          <div class="county-grid">${grantCategoryChecks(`grantEditCat-${g.id}`, cats)}</div>
        </fieldset>
        ${counties.length ? `
        <fieldset class="grant-fieldset">
          <legend>Län <span class="muted">(inga ikryssade = alla län)</span></legend>
          <div class="county-grid">${grantCountyChecks(`grantEditCounty-${g.id}`, counties, chosenCounties)}</div>
        </fieldset>` : ""}
        <button class="btn btn-quiet btn-small" data-action="grant-update" data-grant="${id}"
          data-who="${esc(g.resolvedEmail || g.email || g.userId)}">Spara ändringen</button>
      </details>
    </td></tr>`;
}

/**
 * Manuellt beviljande (fleet/grants.py): plats utan kostnad till en
 * person, med valda tipskategorier och län. Kräver canManage -- det flyttar
 * rättigheter utan betalning, samma gräns som kuponger. Skäl och tidsgräns
 * är obligatoriska att ta ställning till; beslutet loggas och visas här i
 * efterhand.
 */
function grantsCard(d, config) {
  const grants = d.grants ?? [];
  if (!config?.canManage && !grants.length) return "";
  const active = grants.filter((g) => g.active).length;
  const counties = config?.counties ?? [];
  const who = (g) =>
    g.email
      ? `väntar på ${esc(g.email)} (loggar in i appen)`
      : g.resolvedEmail
        ? esc(g.resolvedEmail)
        : g.userId
          ? "ett konto"
          : "—";
  return exceptionRow(`Gratis plats${active ? ` (${active} aktiva)` : ""}`,
    "Till en person, utan faktura och utan Stripe.", `
      ${config?.canManage ? `
      <div class="start-option">
        <label>Kontots e-post<input id="grantEmail" type="email" placeholder="namn@bolaget.se" autocomplete="off" /></label>
        <label>Skäl (loggas)<input id="grantReason" placeholder="T.ex. goodwill efter driftstörning" autocomplete="off" /></label>
        <label>Gäller till <span class="muted">(valfritt, tomt = tills vidare)</span>
          <input id="grantEnds" type="date" /></label>
        <fieldset class="grant-fieldset">
          <legend>Kategorier</legend>
          <div class="county-grid">${grantCategoryChecks("grantCategory", GRANT_CATEGORIES.map(([k]) => k))}</div>
        </fieldset>
        ${counties.length ? `
        <details class="pkg-extras">
          <summary>Begränsa till vissa län <span class="muted">(annars alla län)</span></summary>
          <div class="county-grid">${grantCountyChecks("grantCounty", counties, [])}</div>
        </details>` : ""}
        <button class="btn btn-primary" data-action="grant-membership">Ge gratis plats</button>
      </div>` : ""}
      ${grants.length ? `<table><thead><tr><th>Konto</th><th>Skäl</th><th>Gäller</th><th></th></tr></thead>
        <tbody>${grants.map((g) => `
          <tr><td data-label="Konto"><b>${who(g)}</b>
              <div class="muted">${g.allCounties ? "alla län" : esc((g.counties ?? []).map(countyName).join(", "))}</div>
              <div class="muted">${esc(grantCategoryText(g))}</div></td>
            <td data-label="Skäl">${esc(g.reason)}
              ${g.revokeReason ? `<div class="muted">återkallat: ${esc(g.revokeReason)}</div>` : ""}</td>
            <td data-label="Gäller">${g.revokedAt
              ? `<span class="pill pill-danger">Återkallat ${esc(date(g.revokedAt))}</span>`
              : g.active
                ? `<span class="pill pill-ok">Aktivt</span> ${g.endsAt ? `till ${esc(date(g.endsAt))}` : "tills vidare"}`
                : `<span class="pill">Utgånget</span> ${g.endsAt ? esc(date(g.endsAt)) : ""}`}</td>
            <td data-label="">${config?.canManage && !g.revokedAt
              ? `<button class="btn btn-danger btn-small" data-action="grant-revoke"
                  data-grant="${esc(g.id)}" data-who="${esc(g.resolvedEmail || g.email || g.userId)}">Återkalla</button>`
              : ""}</td></tr>
          ${config?.canManage && !g.revokedAt ? grantEditRow(g, config) : ""}`).join("")}
        </tbody></table>` : ""}`, { open: active > 0 });
}

function tabPlatser(d, config, pending) {
  const devices = d.devices ?? [];
  const notifyHtml = d.notify ? notifyCard({ ...d.notify, canManage: !!config?.canSell }, {
    countyNames: Object.fromEntries((d.notify.countyCatalog ?? []).map((c) => [c.code, c.name])),
    title: "Notiser per telefon",
  }) : "";
  return `
    ${membershipsCard(d, config, pending)}
    ${companyChangesCard(d, config)}
    <details class="card kt-fold">
      <summary><h2>Telefoner och notiser <span class="muted">(${esc(devices.length)})</span></h2></summary>
      ${phonesCard(d, config)}
      ${notifyHtml}
    </details>
  `;
}

const PUSH_REASON = { no_push_token: "ingen notistoken" };

/** Alla telefoner i bolaget: vem, notiser, senast sedd -- för "får inga notiser". */
function phonesCard(d, config) {
  const devices = d.devices ?? [];
  const manage = !!config?.canManage;
  return `
    <div class="card table-scroll">
      <div class="card-head"><h2>Telefoner <span class="muted">(${esc(devices.length)})</span></h2>
        ${manage && devices.length ? '<button class="btn btn-quiet btn-small" data-action="test-push">Skicka testnotis till alla</button>' : ""}</div>
      <p class="muted small">"Ingen token": föraren ska öppna appen och tillåta notiser.</p>
      ${devices.length ? `<table><thead><tr><th>Telefon</th><th>Notiser</th><th>Senast sedd</th><th></th></tr></thead>
      <tbody>${devices.map((dv) => `
        <tr><td data-label="Telefon"><b>${esc(dv.label || "Telefon")}</b>
            <div class="muted">${dv.kind === "owner_app" ? "Ägarapp" : "Förare"}${dv.userId
              ? ` · <a href="#" data-action="open-account" data-user="${esc(dv.userId)}">konto</a>` : ""}</div></td>
          <td data-label="Notiser">${dv.hasPush ? '<span class="ok">Påslagna</span>' : '<span class="error">Ingen token</span>'}</td>
          <td data-label="Senast sedd">${esc(dateTime(dv.lastSeenAt))}</td>
          <td data-label="">${manage && dv.userId
            ? `<button class="btn btn-quiet btn-small" data-action="account-allow-device-swap" data-user="${esc(dv.userId)}">Tillåt extra telefonbyte</button>`
            : ""}</td></tr>`).join("")}</tbody></table>`
        : '<p class="muted">Ingen telefon har kopplats än.</p>'}
    </div>`;
}

const PENDING_KIND = {
  reduce_licenses: "Avsluta platser",
  cancel_subscription: "Uppsägning",
};

/**
 * Det som väntar på förnyelsen. Länbyten är direkta nu och visas inte här;
 * en gammal väntande länändring ligger kvar i databasen men göms.
 */
function companyChangesCard(d, config) {
  if (!config?.canSell) return "";
  const open = (d.licenses ?? []).filter((l) => LICENSE_OPEN.includes(l.status));
  const pending = (d.pendingChanges ?? []).filter((p) => PENDING_KIND[p.kind]);
  if (!pending.length) return "";
  const subject = (id) => open.find((l) => l.id === id)?.vehicle || "plats";
  const describe = (p) => {
    const pl = p.payload ?? {};
    if (p.kind === "reduce_licenses") return (pl.licenseIds ?? []).map(subject).filter(Boolean).join(", ");
    return pl.reason ? `Orsak: ${pl.reason}` : "";
  };
  return `
    <div class="card">
      <h2>Väntar på förnyelsen</h2>
      <table><thead><tr><th>Ändring</th><th>Gäller från</th><th></th></tr></thead>
        <tbody>${pending.map((p) => `
          <tr><td data-label="Ändring"><b>${esc(PENDING_KIND[p.kind])}</b>
              <div class="muted">${esc(describe(p))}</div></td>
            <td data-label="Gäller från">${esc(date(p.effectiveAt))}</td>
            <td>${config.canManage && p.kind !== "cancel_subscription"
              ? `<button class="btn btn-quiet btn-small" data-action="pending-undo" data-change="${esc(p.id)}"
                  data-label="${esc(PENDING_KIND[p.kind])}">Ångra</button>`
              : p.kind === "cancel_subscription" ? '<span class="muted">Ångras under Betalning</span>' : ""}</td></tr>`).join("")}
        </tbody></table>
    </div>`;
}

/* --- Inloggningar ------------------------------------------------------- */

function tabKonton(d, config, loginLink) {
  return `
    ${loginLink?.url ? `
    <div class="notice" role="status">
      <b>Inloggningslänk till ${esc(loginLink.email)}</b>
      <p class="muted">Gäller en gång. Kopiera och skicka den i chatten eller med e-post – den är för lång att läsa upp.</p>
      <p><code id="loginLinkUrl" class="break">${esc(loginLink.url)}</code></p>
      <button class="btn btn-quiet btn-small" data-action="copy-login-link">Kopiera länken</button>
    </div>` : ""}
    ${membersCard(d, config)}
    ${ownerBlock(d)}
  `;
}

/* --- Betalning ---------------------------------------------------------- */

function tabBetalning(d, config) {
  const s = d.subscription;
  return `
    ${s?.packageSummary ? `<p class="muted kt-lead">Paket: ${esc(s.packageSummary)}${
      s.priceVersion ? ` · prislista ${esc(s.priceVersion)}` : ""}</p>` : ""}
    ${ordersCard(d.orders, config)}
    ${addCarsBlock(d, config)}
    ${trialExtendBlock(d, config)}
    ${redemptionsCard(d.couponRedemptions)}
    ${cancelBlock(d, config)}
    ${exceptionsBlock(d, config)}
  `;
}

/** En rad bland undantagen: rubrik, en mening och innehållet när den fälls ut. */
function exceptionRow(title, line, body, { open = false, danger = false, id = "" } = {}) {
  return `
    <details class="card exc${danger ? " exc-danger" : ""}"${id ? ` id="${id}"` : ""}${open ? " open" : ""}>
      <summary><span class="exc-head"><b>${esc(title)}</b><span class="muted">${esc(line)}</span></span></summary>
      <div class="exc-body">${body}</div>
    </details>`;
}

/**
 * Undantagen: allt som går förbi det vanliga flödet (prov -> betallänk ->
 * Stripe). Samlade på ett ställe, sist på Betalning, så att de inte blandas
 * med det man gör varje dag men alltid går att hitta. Allt loggas.
 */
function exceptionsBlock(d, config) {
  const sell = !!config?.canSell;
  const manage = !!config?.canManage;
  const s = d.subscription;
  const t = d.trial;
  const trialOpen = t && ["pending", "active"].includes(t.status);
  const rows = [
    manage ? discountBlock(d, config) : "",
    grantsCard(d, config),
    manage ? exceptionRow("Extra dagar utan Stripe", "När en betalning dröjer. Stripe ändras inte.", `
      <div class="btn-row">
        <button class="btn btn-quiet" data-action="extend" data-days="7">+7 dagar</button>
        <button class="btn btn-quiet" data-action="extend" data-days="30">+30 dagar</button>
      </div>`) : "",
    addMembershipBlock(d, config),
    sell && trialOpen ? exceptionRow("Avsluta provet nu", "Inga fler tips. Kunden får samma mejl som vid provslut.", `
      <div class="btn-row"><button class="btn btn-danger" type="button" data-action="trial-end">Avsluta provet</button></div>`,
    { danger: true }) : "",
    manage && !["canceled"].includes(s?.status) && (s || trialOpen) ? exceptionRow("Avsluta allt direkt",
      "Åtkomst, platser och debitering stoppas nu. Ingen återbetalning.", `
      <div class="btn-row"><button class="btn btn-danger" data-action="terminate-now">Avsluta direkt</button></div>`,
    { danger: true }) : "",
  ].filter(Boolean);
  if (!rows.length) return "";
  return `
    <section id="undantag" class="exceptions" aria-labelledby="undantagTitle">
      <h2 class="kt-sub" id="undantagTitle">Undantag</h2>
      <p class="muted small exc-lead">Utanför det vanliga flödet. Allt loggas med vem och varför.</p>
      ${rows.join("")}
    </section>`;
}

/* --- Uppgifter ----------------------------------------------------------- */

function tabUppgifter(d, config) {
  const p = d.profile ?? {};
  return `
    ${verificationCard(d, config)}
    ${config?.canSell ? profileBlock(d) : `
    <div class="card">
      <h2>Kontakt</h2>
      <dl class="kv">
        <dt>Kontakt</dt><dd>${esc(p.contactName || "—")} ${p.contactRole ? `<span class="muted">(${esc(p.contactRole)})</span>` : ""}</dd>
        <dt>E-post</dt><dd>${esc(p.contactEmail || "—")}</dd>
        <dt>Telefon</dt><dd>${esc(p.contactPhone || "—")}</dd>
        <dt>Fakturamejl</dt><dd>${esc(p.billingEmail || "—")}</dd>
      </dl>
    </div>`}
    <div class="card">
      <div class="card-head">
        <h2>Bolagsverket</h2>
        ${config?.canSell && (p.country ?? "SE") === "SE" && (p.orgNumber || d.company.orgNumber) ? `<div class="btn-row">
          <button class="btn btn-quiet btn-small" data-action="registry-refresh">Hämta igen</button>
          ${p.registry?.found ? `<button class="btn btn-quiet btn-small" data-action="registry-refresh" data-overwrite="1">Använd registrets adress</button>` : ""}
        </div>` : ""}
      </div>
      ${p.registry ? registryBlock(p.registry, { checkedAt: p.registryCheckedAt })
        : (p.orgNumber || d.company.orgNumber)
          ? '<p class="muted">Inte uppslaget än.</p>'
          : '<p class="muted">Slås upp när kunden anger org.nr.</p>'}
    </div>
  `;
}

/* --- Historik ----------------------------------------------------------- */

const ACTOR = {
  platform_admin: "Personal", customer: "Kunden", admin: "Kunden", owner: "Kunden",
  driver: "Förare", system: "Systemet", stripe: "Stripe",
};

const AUDIT = {
  account_closed: "Kontot avslutades",
  admin_base_county_set: "Län bytt direkt",
  admin_company_base_county_set: "Län bytt på alla platser",
  admin_company_verification: "Behörighet bedömd",
  admin_device_blocked: "Telefon spärrad",
  admin_driver_invite_resent: "Förarinbjudan skickad igen",
  admin_driver_invite_revoked: "Förarinbjudan återkallad",
  admin_driver_invited: "Förare inbjuden med e-post",
  admin_license_removed: "Plats borttagen",
  admin_member_changed: "Inloggning ändrad",
  admin_pairing_code_issued: "Förarkod skapad",
  admin_pending_change_undone: "Väntande ändring ångrad",
  admin_subscription_changed: "Åtkomst ändrad för hand",
  admin_test_push: "Testnotis skickad",
  admin_device_notify_prefs_changed: "Notiser ändrade på telefon (support)",
  admin_company_notify_default_changed: "Standard för notiser ändrad (support)",
  admin_trial_counties_set: "Län ändrat på plats",
  admin_vehicle_changed: "Regnr bytt",
  admin_vehicle_released: "Bilen frigjord",
  base_county_changed: "Län bytt",
  company_archived: "Arkiverat",
  company_details_updated: "Uppgifter ändrade",
  company_discount_cleared: "Rabatt borttagen",
  company_discount_set: "Rabatt satt",
  company_unarchived: "Återställt från arkivet",
  contracting_party_change_requested: "Byte av avtalspart begärt",
  county_activated: "Län tillagt (äldre avtal)",
  county_removal_scheduled: "Län tas bort vid förnyelse",
  coupon_redeemed: "Kupong inlöst",
  device_approved: "Telefon godkänd",
  device_blocked: "Telefon spärrad",
  device_renamed: "Telefon omdöpt",
  device_notify_prefs_changed: "Notiser ändrade på telefon",
  company_notify_default_changed: "Standard för notiser ändrad",
  driver_invite_claimed: "Förarinbjudan använd",
  driver_invite_resent: "Förarinbjudan skickad igen",
  driver_invite_revoked: "Förarinbjudan återkallad",
  driver_invited: "Förare inbjuden med e-post",
  driver_relogin: "Förare loggade in igen",
  join_request_created: "Telefon bad om att få gå med",
  license_created: "Plats tillagd",
  licenses_reduced: "Platser avslutade",
  member_removed: "Inloggning borttagen",
  order_applied: "Beställning genomförd",
  order_canceled: "Beställning avbruten",
  order_created: "Beställning skapad",
  order_failed: "Beställning misslyckades",
  order_payment_requested: "Betallänk skapad",
  owner_invite_claimed: "Inbjudan till portalen använd",
  owner_invited: "Inbjuden till portalen",
  ownership_transfer_accepted: "Ägarskap överlåtet",
  ownership_transfer_requested: "Överlåtelse begärd",
  pairing_code_issued: "Förarkod skapad",
  registry_refreshed: "Hämtat från Bolagsverket",
  renewal_stopped: "Förnyelsen stoppad",
  review_resolved: "Granskning avgjord",
  sales_company_created: "Kund upplagd av säljare",
  sales_company_updated: "Uppgifter ändrade",
  sales_trial_started: "Prov startat av säljare",
  self_registered: "Registrerade sig själv",
  session_ended: "Förare lämnade bilen",
  session_started: "Förare tog bilen",
  stripe_subscription_synced: "Stripe uppdaterat",
  subscription_canceled: "Uppsagt",
  subscription_cancellation_applied: "Uppsägningen trädde i kraft",
  subscription_cancellation_undone: "Uppsägningen ångrad",
  subscription_terminated_now: "Avslutat direkt",
  support_thread_started: "Supportchatt startad",
  trial_created: "Prov skapat",
  trial_ended: "Provet slutade",
  trial_extended: "Provet förlängt",
  trial_started: "Provet startade",
  trial_vehicle_removed: "Provplats borttagen",
  vehicle_created: "Bil skapad",
  account_deleted_by_user: "Kontot raderat av användaren",
  admin_account_deleted: "Kontot raderat (personal)",
  admin_account_recovery_link: "Lösenordslänk skapad",
  admin_account_test_push: "Testnotis till kontot",
  admin_block_company: "Företaget avstängt",
  admin_unblock_company: "Avstängningen hävd",
  admin_county_change_grant: "Extra länbyte beviljat",
  bankid_login: "Inloggning med BankID",
  bankid_recovered: "Konto återställt med BankID",
  company_deleted: "Företaget raderat",
  company_tips_paused: "Tipsen pausade",
  consumer_start_now_accepted: "Godkände start direkt",
  crm_note_edited: "CRM-anteckning ändrad",
  crm_task_deleted: "CRM-uppgift borttagen",
  duplicate_signup_attempt: "Försökte registrera sig igen",
  membership_assigned: "Plats tilldelad",
  membership_claimed: "Plats tagen i appen",
  membership_closed: "Plats avslutad",
  membership_county_set: "Län satt på plats",
  membership_created: "Plats skapad",
  membership_grant_claimed: "Beviljad plats tagen",
  membership_grant_revoked: "Beviljande återkallat",
  membership_grant_updated: "Beviljande ändrat",
  membership_granted: "Plats beviljad utan kostnad",
  membership_invite_sent: "Inbjudan till plats skickad",
  membership_license_created: "Plats skapad",
  membership_session_started: "Förare började köra",
  membership_unassigned: "Tilldelning borttagen",
  order_supersede_failed: "Ersättande beställning misslyckades",
  owner_invite_revoked: "Inbjudan till portalen återkallad",
  promotion_code_used: "Rabattkod använd",
  seat_county_changed: "Län bytt på plats",
  stripe_not_updated: "Stripe kunde inte uppdateras",
  trial_commit_canceled: "Beställning efter provet avbruten",
  trial_commit_card_saved: "Kort sparat för efter provet",
  trial_committed: "Beställde efter provet",
  trial_counties_set: "Län satt i provet",
  trial_ended_by_staff: "Provet avslutat av personal",
  trial_seat_continued: "Provplats fortsätter",
  trial_vehicle_limit_set: "Antal provplatser ändrat",
  user_tips_paused: "Tipsen pausade för en person",
  user_tips_resumed: "Tipsen återupptagna för en person",
};

/** Okänd händelsekod: läsbar text i stället för snake_case. */
function auditLabel(action) {
  if (AUDIT[action]) return AUDIT[action];
  const text = String(action ?? "").replace(/^admin_/, "").replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Detaljen som läsbar text: bara enkla värden, nycklar på svenska där det går. */
/** Detaljnycklar på svenska; län visas med namn. Okända nycklar visas som de är. */
const DETAIL_KEY = {
  email: "e-post", assignee_email: "e-post", mode: "sätt", send_no: "utskick nr",
  base: "län", base_county: "län", county: "län", from: "från", to: "till",
  before: "före", after: "efter", reason: "skäl", status: "status", days: "dagar",
  pending: "väntar", role: "roll", seats: "platser", count: "antal",
};
const COUNTY_KEYS = new Set(["base", "base_county", "county", "from_county", "to_county"]);

function auditDetail(detail) {
  if (!detail || typeof detail !== "object") return "";
  const skip = new Set(["license_id", "vehicle_id", "licenseId", "vehicleId", "device_id", "approval_id"]);
  const value = (k, v) => {
    if (COUNTY_KEYS.has(k)) return countyName(String(v)) || v;
    if (v === true) return "ja";
    if (v === false) return "nej";
    return v;
  };
  return Object.entries(detail)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== "" && typeof v !== "object")
    .map(([k, v]) => `${DETAIL_KEY[k] ?? k.replace(/_/g, " ")}: ${value(k, v)}`)
    .join(" · ")
    .slice(0, 200);
}

function tabHistorik(d) {
  const rows = d.audit ?? [];
  return `
    <div class="card table-scroll">
      <h2>Händelser <span class="muted">(senaste ${esc(rows.length)})</span></h2>
      ${rows.length ? `<table class="audit-table"><thead><tr><th>När</th><th>Vad</th><th>Vem</th></tr></thead>
      <tbody>${rows.map((e) => `
        <tr><td data-label="När">${esc(dateTime(e.at))}</td>
          <td data-label="Vad"><b>${esc(auditLabel(e.action))}</b>
            ${auditDetail(e.detail) ? `<div class="muted">${esc(auditDetail(e.detail))}</div>` : ""}</td>
          <td data-label="Vem">${esc(ACTOR[e.actorKind] ?? e.actorKind)}</td></tr>`).join("")}</tbody></table>`
        : '<p class="muted">Inga händelser.</p>'}
    </div>
  `;
}

const VERIFICATION = {
  verified: ["pill-ok", "Behörighet kontrollerad"],
  unverified: ["pill-warn", "Obekräftad"],
  pending_review: ["pill-warn", "Under granskning"],
  rejected: ["pill-danger", "Avvisad"],
};

function verificationPill(status) {
  const [cls, label] = VERIFICATION[status] ?? ["", status];
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

function verificationCard(d, config) {
  const p = d.profile;
  if (!p || p.verificationStatus === "verified" || !config?.canSell) return "";
  return `
    <div class="card">
      <h2>Kontrollera behörigheten</h2>
      <p class="muted">Ring växeln eller kolla firmatecknare: får personen företräda bolaget?</p>
      <div class="btn-row">
        <button class="btn btn-primary" data-action="verify" data-status="verified">Markera som kontrollerad</button>
        <button class="btn btn-danger" data-action="verify" data-status="rejected">Avvisa</button>
      </div>
    </div>`;
}

/** Kundens roller (fleet/roles.py). "company_admin" är en äldre roll utan behörigheter. */
export const MEMBER_ROLE = {
  company_owner: "Ägare",
  fleet_admin: "Bilar och förare",
  finance: "Ekonomi",
  company_admin: "Administratör (äldre, utan behörighet)",
};
const ROLE_CHOICES = { company_owner: "Ägare", fleet_admin: "Bilar och förare", finance: "Ekonomi" };

function membersCard(d, config) {
  const members = d.members ?? [];
  const manage = !!config?.canManage;
  const sell = !!config?.canSell;
  return `
    <div class="card">
      <h2>Kan logga in i kundportalen</h2>
      ${members.length ? `<div class="table-scroll"><table>
        <thead><tr><th>Konto</th><th>Roll</th><th>Status</th><th></th></tr></thead>
        <tbody>${members.map((m) => `
          <tr>
            <td data-label="Konto">${m.email
              ? `<a href="#" data-action="open-account" data-user="${esc(m.userId)}">${esc(m.email)}</a>`
              : '<span class="muted">E-post okänd (inte inloggad sedan katalogen infördes)</span>'}</td>
            <td data-label="Roll">${esc(MEMBER_ROLE[m.role] ?? m.role)}</td>
            <td data-label="Status">${m.blocked
              ? `<span class="pill pill-danger">Spärrad</span><div class="muted">${esc(m.blocked.reason)}</div>`
              : m.status === "active" ? '<span class="pill pill-ok">Aktiv</span>' : '<span class="pill">Avstängd här</span>'}${m.paused
              ? `<div><span class="pill pill-warn">Tipsen pausade</span><div class="muted">${esc(m.paused.reason)}</div></div>` : ""}</td>
            <td data-label="" class="actions-cell">${sell && !m.blocked ? (m.paused
              ? `<button class="btn btn-quiet btn-small" data-action="member-resume" data-user="${esc(m.userId)}">Återuppta tipsen</button>`
              : `<button class="btn btn-quiet btn-small" data-action="member-pause" data-user="${esc(m.userId)}" data-email="${esc(m.email)}">Pausa tipsen</button>`) : ""}${manage ? `<div class="btn-row">
              ${m.email && !m.blocked ? `<button class="btn btn-primary btn-small" data-action="member-login-link" data-user="${esc(m.userId)}">Skapa inloggningslänk</button>` : ""}
              <details class="more-menu">
                <summary class="btn btn-small btn-more" aria-label="Mer åtgärder">Mer</summary>
                <div class="more-items" role="menu">
                ${Object.entries(ROLE_CHOICES).filter(([r]) => r !== m.role).map(([r, label]) =>
                  `<button type="button" class="btn btn-quiet btn-small" role="menuitem" data-action="member-role" data-user="${esc(m.userId)}" data-role="${r}">Byt roll: ${esc(label)}</button>`).join("")}
                ${m.status === "active"
                  ? `<button type="button" class="btn btn-quiet btn-small" role="menuitem" data-action="member-status" data-user="${esc(m.userId)}" data-status="disabled">Stäng av i företaget</button>`
                  : `<button type="button" class="btn btn-quiet btn-small" role="menuitem" data-action="member-status" data-user="${esc(m.userId)}" data-status="active">Aktivera i företaget</button>`}
                ${m.blocked ? "" : `<button type="button" class="btn btn-danger btn-small" role="menuitem" data-action="block-user" data-user="${esc(m.userId)}"
                  data-email="${esc(m.email)}">Spärra kontot överallt</button>`}
              </div></details>
            </div>` : ""}</td>
          </tr>`).join("")}</tbody></table></div>`
        : '<p class="muted">Ingen än. Bjud in ägaren nedan.</p>'}
      <p class="muted small">Ägare: allt · Bilar och förare: platser och konton · Ekonomi: fakturor.
        Förare bjuds in under <button class="linklike" data-action="sec-open" data-sec="platser">Platser</button>.</p>
    </div>`;
}

const LICENSE_OPEN = ["active", "trial", "pending_cancel"];

/**
 * Ett kort per medlemskap: vilket konto platsen är tilldelad, vilka län som
 * hör till platsen och vad som går att ändra. Det man gör i ett samtal syns
 * direkt; ändringar av medlemskapet själv (län, ta bort) ligger under
 * "Ändra medlemskapets län".
 *
 * Provet kostar inget och ändras direkt. Ett betalt medlemskaps ändring visas
 * först som en offert i kortet -- beloppet räknas av serverns prismotor
 * (fleet/pricing.py), aldrig här -- och verkställs när säljaren bekräftat att
 * kunden godkänt. Samma regel som i fleet/admin_vehicles.py.
 */
/**
 * Kundens länbyten den här månaden (fleet/county_changes.py): två per
 * medlemskap och kalendermånad, även under provet. Personalens egna ändringar
 * räknas inte. När kunden ringer för att hen "inte får byta län" är det här
 * svaret, och knappen ger ett extra byte som kunden sedan gör själv.
 */
function countyChangesRow(l, sell) {
  const c = l.countyChanges;
  if (!c || !LICENSE_OPEN.includes(l.status)) return "";
  const total = (c.limit ?? 2) + (c.extra ?? 0);
  return `<div class="driving ${c.remaining > 0 ? "" : "warn"}">
      <span>Länbyten kvar den här månaden: <b>${esc(c.remaining)} av ${esc(total)}</b>
        ${c.extra ? `<span class="muted">(varav ${esc(c.extra)} extra från support)</span>` : ""}</span>
      ${sell ? `<button class="btn btn-quiet btn-small" data-action="county-change-allow"
        data-license="${esc(l.id)}" data-plate="${esc(l.vehicle)}"
        title="Kunden byter sedan själv. Gäller bara den här månaden.">Tillåt ett extra länbyte</button>` : ""}
    </div>`;
}

/**
 * Medlemskapet (2026-10): platsen tilldelas ett KONTO, inte en bil. I appen får
 * kunden sin plats själv; här tilldelar personalen fler platser åt kunden,
 * t.ex. till en kollegas konto. Portalen tar aldrig en app-session.
 */
function membershipRow(l, sell) {
  if (!LICENSE_OPEN.includes(l.status)) return "";
  const who = l.assigneeEmail
    ? `väntar på ${esc(l.assigneeEmail)}`
    : l.assigneeResolvedEmail
      ? esc(l.assigneeResolvedEmail)
      : l.assigneeUserId || l.assigned
        ? "ett konto"
        : "ingen än";
  return `<div class="driving ${l.assigned ? "on" : ""}">
      <span><b>Konto:</b> ${who}</span>
      ${
        sell
          ? `<button class="btn btn-primary btn-small" data-action="membership-assign"
               data-license="${esc(l.id)}" data-plate="${esc(l.vehicle)}">${l.assigned ? "Byt konto" : "Bjud in konto"}</button>
             ${
               l.assigned
                 ? `<button class="btn btn-quiet btn-small" data-action="membership-unassign"
                      data-license="${esc(l.id)}" data-plate="${esc(l.vehicle)}">Ta bort tilldelning</button>`
                 : ""
             }`
          : ""
      }
    </div>`;
}

function membershipsCard(d, config, pending = null) {
  const all = d.licenses ?? [];
  const open = all.filter((l) => LICENSE_OPEN.includes(l.status));
  const closed = all.length - open.length;
  const sell = !!config?.canSell;
  const manage = !!config?.canManage;
  const counties = config?.counties ?? [];
  const name = (code) => countyName(code);
  return `
    <div class="seats" id="inviteCard">
      ${open.length ? open.map((l, i) => {
        const trial = l.status === "trial";
        const extras = l.extraCounties ?? [];
        const mine = pending?.licenseId === l.id ? pending : null;
        const title = l.vehicle || `Plats ${i + 1}`;
        const data = `data-license="${esc(l.id)}" data-base="${esc(l.baseCounty)}" data-extras="${esc(extras.join(","))}" data-plate="${esc(title)}" data-trial="${trial ? "1" : ""}"`;
        const email = l.assigneeEmail || l.assigneeResolvedEmail || "";
        const who = l.assigneeEmail
          ? "Väntar på att föraren loggar in i appen"
          : l.assigned
            ? `Inloggad${l.activePhone ? ` · ${l.activePhone.label || "telefon ansluten"}` : ""}`
            : "Ingen förare än";
        const c = l.countyChanges;
        const editable = sell && l.status !== "pending_cancel";
        return `
        <div class="seat ${mine ? "car-pending" : ""}">
          <div class="seat-head">
            <b class="seat-title">${esc(title)}</b> ${pill(l.status)}
            ${l.assignmentKind === "temporary" && l.vehicle ? '<span class="pill pill-warn">Ersättningsbil</span>' : ""}
          </div>
          <div class="seat-fields">
            <label class="seat-field">Län
              ${editable ? `
              <select data-seat-county ${data}>
                ${counties.some((x) => x.code === l.baseCounty) ? "" : `<option value="${esc(l.baseCounty)}" selected>${esc(name(l.baseCounty) || "Välj län")}</option>`}
                ${counties.map((x) => `<option value="${esc(x.code)}" ${x.code === l.baseCounty ? "selected" : ""}>${esc(x.name)}</option>`).join("")}
              </select>` : `<span class="seat-value">${esc(name(l.baseCounty))}</span>`}
            </label>
            <label class="seat-field">Förare
              ${editable ? `
              <span class="seat-inline">
                <input type="email" data-seat-email="${esc(l.id)}" value="${esc(email)}"
                  placeholder="förarens e-post" autocomplete="off" inputmode="email" />
                <button class="btn btn-primary btn-small" type="button" data-action="seat-assign" ${data}>Spara</button>
              </span>` : `<span class="seat-value">${esc(email || "—")}</span>`}
            </label>
          </div>
          <p class="seat-note ${l.assigned && !l.assigneeEmail ? "ok" : "muted"}">${esc(who)}</p>
          ${extras.length ? `<p class="muted small">Fler län (äldre avtal): ${esc(extras.map(name).join(", "))}</p>` : ""}
          ${l.scheduledBaseCounty ? `<p class="muted small">Byts till ${esc(name(l.scheduledBaseCounty))} vid förnyelse.</p>` : ""}
          ${l.status === "pending_cancel" ? `<p class="muted small">Platsen avslutas vid nästa förnyelse${l.endsAt ? ` (${esc(date(l.endsAt))})` : ""}.</p>` : ""}
          ${editable ? `
          <details class="seat-more">
            <summary>Mer</summary>
            <div class="seat-more-body">
              ${c ? `<span class="muted">Förarens egna länbyten kvar i månaden: <b>${esc(c.remaining)} av ${esc((c.limit ?? 2) + (c.extra ?? 0))}</b></span>
                <button class="btn btn-quiet btn-small" type="button" data-action="county-change-allow" ${data}>Ge ett extra byte</button>` : ""}
              ${l.assigned ? `<button class="btn btn-quiet btn-small" type="button" data-action="membership-unassign" ${data}>Ta bort föraren</button>` : ""}
              <button class="btn btn-danger btn-small" type="button" data-action="car-remove" ${data}>Ta bort platsen</button>
            </div>
          </details>` : ""}

          ${mine ? `
          <div class="pending-change" role="region" aria-label="Offert">
            <h4>${esc(mine.label)}</h4>
            ${quoteBox(mine.quote)}
            <label class="check"><input id="pendingAccepted" type="checkbox" />
              Kunden har godkänt ändringen och priset</label>
            <div class="btn-row">
              <button class="btn btn-primary" data-action="pending-confirm">Bekräfta</button>
              <button class="btn btn-quiet" data-action="pending-cancel">Avbryt</button>
              ${mine.allowNow && manage ? `<button class="btn btn-danger" data-action="car-remove-now" ${data}>Ta bort nu i stället (ingen återbetalning)</button>` : ""}
            </div>
          </div>` : ""}
        </div>`;
      }).join("") : `<p class="muted">Inga platser än. Lägg till under <button type="button" class="linklike" data-action="sec-open" data-sec="betalning" data-target="salesPanel">Betalning</button>.</p>`}
      ${closed ? `<p class="muted small">${esc(plural(closed, "avslutad plats visas", "avslutade platser visas"))} inte.</p>` : ""}
    </div>`;
}

function dangerZone(d, config) {
  if (!config?.canManage || d.suspension) return "";
  return `
    <h3>Stäng av</h3>
    <p class="muted">Ingen får data. Inget raderas, och allt fungerar igen när du häver det. Stripe debiterar som vanligt.</p>
    <div class="btn-row"><button class="btn btn-danger" data-action="suspend">Stäng av företaget</button></div>`;
}

/* --- Notiser ---------------------------------------------------------- */

export function notiser(list, status = "") {
  const rows = list.notifications ?? [];
  const opt = (v, l) => `<option value="${v}" ${v === status ? "selected" : ""}>${l}</option>`;
  return `
    <div class="page-head">
      <div><h1>Notiser</h1>
        <p class="muted">Skickade pushnotiser, senaste först.</p></div>
    </div>
    <div class="toolbar">
      <label for="pushStatus">Status</label>
      <select id="pushStatus">
        ${opt("", "Alla")}${opt("sent", "Skickade")}${opt("failed", "Misslyckade")}
        ${opt("suppressed", "Undertryckta")}${opt("pending", "Väntar")}${opt("expired", "Utgångna")}
      </select>
    </div>
    <p class="muted"><b>Undertryckt</b> = mottagaren tappade åtkomsten mellan köandet och
      sändningen (spärrad telefon, övertagen bil, utgången period, län utanför licensen).</p>
    <div class="card"><table>
      <thead><tr><th>När</th><th>Notis</th><th>Till</th><th>Status</th></tr></thead>
      <tbody>${rows.map((n) => `
        <tr><td data-label="När">${esc(dateTime(n.createdAt))}</td>
          <td data-label="Notis"><b>${esc(n.title)}</b><div class="muted">${esc(n.body)}</div>
            ${n.error ? `<div class="error mono">${esc(n.error)}</div>` : ""}</td>
          <td data-label="Till">${esc(n.company)}<div class="muted">${esc(n.device)}</div></td>
          <td data-label="Status">${pill(n.status)}${n.attempts > 1 ? ` <span class="muted">${esc(n.attempts)} försök</span>` : ""}</td>
        </tr>`).join("")}</tbody>
    </table>
    ${rows.length ? "" : '<p class="muted">Inga notiser.</p>'}</div>
  `;
}

/* --- Evenemang -------------------------------------------------------- */

const CATEGORIES = [
  ["konsert", "Konsert"], ["sport", "Sport"], ["teater", "Teater och scen"], ["humor", "Humor"],
  ["familj", "Familj"], ["massa", "Mässa och konferens"], ["festival", "Festival"],
  ["film", "Film"], ["ovrigt", "Övrigt"],
];

const SOURCE_LABEL = { manual: "TaxiTips (eget)", predicthq: "PredictHQ", ticketmaster: "Ticketmaster", thesportsdb: "TheSportsDB" };

function time(iso) {
  return iso ? new Date(iso).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" }) : "";
}

export function evenemang(list, f = {}, config = null, importState = null) {
  const rows = list.events ?? [];
  const manage = !!config?.canManage;
  const opt = (v, l, cur) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`;
  return `
    <div class="page-head">
      <div><h1>Evenemang</h1>
        <p class="muted">Det förarna ser under Evenemang i appen.</p></div>
    </div>

    ${manage ? `
    <div class="grid grid-top">
      <details class="card" ${f.open === "new" ? "open" : ""}>
        <summary><h2 style="display:inline">+ Lägg till evenemang</h2></summary>
        <form id="eventNewForm" class="form-grid" autocomplete="off">
          <label class="span-2">Namn<input name="name" required placeholder="Malmö FF – AIK" /></label>
          <label>Datum<input name="date" type="date" required /></label>
          <label>Kategori<select name="category">${CATEGORIES.map(([v, l]) => opt(v, l, "ovrigt")).join("")}</select></label>
          <label>Starttid<input name="time" type="time" /></label>
          <label>Sluttid (tomt = uppskattas)<input name="endTime" type="time" /></label>
          <label class="span-2">Arena eller plats
            <input name="venue" id="venueInput" placeholder="Börja skriva, t.ex. Eleda" />
            <ul class="venue-hits" id="venueHits" hidden></ul></label>
          <label>Stad<input name="city" /></label>
          <label>Förväntade besökare<input name="attendance" inputmode="numeric" /></label>
          <label class="span-2">Koordinat (lat, lon)
            <input name="coords" id="coordsInput" required placeholder="55.5838, 12.9884 — högerklicka i Google Maps och kopiera" /></label>
          <label class="span-2">Länk (valfri)<input name="url" type="url" placeholder="https://" /></label>
          <p class="muted span-2">Koordinaten krävs: appen visar evenemang efter förarens län, och en gissad
            plats skickar föraren fel. Välj en känd arena så fylls den i.</p>
          <div class="btn-row span-2"><button class="btn btn-primary" type="submit">Spara evenemang</button></div>
        </form>
      </details>

      <details class="card" ${f.open === "import" || importState ? "open" : ""}>
        <summary><h2 style="display:inline">Importera från fil</h2></summary>
        <p class="muted">CSV (komma eller semikolon) eller JSON. Kolumner: <span class="mono">namn, datum, tid,
          sluttid, arena, stad, lat, lon, kategori, besökare, länk</span>. Samma fil kan importeras igen — den
          uppdaterar i stället för att dubblera.</p>
        <div class="drop" id="eventDrop">
          <input type="file" id="eventFile" accept=".csv,.json,text/csv,application/json" />
          <p class="muted">eller dra filen hit</p>
        </div>
        <p><a href="#" data-action="event-template">Ladda ner mall (CSV)</a></p>
        ${importPanel(importState)}
      </details>
    </div>` : ""}

    <form class="toolbar" id="eventForm">
      <input id="eq" name="q" value="${esc(f.q ?? "")}" placeholder="Namn, arena eller stad" />
      <select id="esource" aria-label="Källa">
        ${opt("", "Alla källor", f.source ?? "")}${Object.entries(SOURCE_LABEL).map(([v, l]) => opt(v, l, f.source ?? "")).join("")}
      </select>
      <select id="edays" aria-label="Period">
        ${opt("14", "14 dagar", String(f.days ?? 14))}${opt("30", "30 dagar", String(f.days ?? 14))}${opt("90", "90 dagar", String(f.days ?? 14))}
      </select>
      <label class="check" style="margin:0"><input type="checkbox" id="ehidden" ${f.hidden ? "checked" : ""} /> Bara dolda</label>
      <button class="btn btn-primary" type="submit">Sök</button>
    </form>

    <div class="card table-scroll"><table>
      <thead><tr><th>Datum</th><th>Evenemang</th><th>Plats</th><th>Besökare</th><th></th></tr></thead>
      <tbody>${rows.map((e) => `
        <tr><td data-label="Datum">${esc(date(e.startDate))}${e.startAt ? `<div class="muted">${esc(time(e.startAt))}</div>` : ""}</td>
          <td data-label="Evenemang"><b>${esc(e.name)}</b>
            <div class="muted">${esc(e.category)} · ${esc(SOURCE_LABEL[e.source] ?? e.source)}</div>
            ${e.hidden ? `<div class="error">Dold: ${esc(e.hiddenReason)}</div>` : ""}</td>
          <td data-label="Plats">${esc(e.venue)}<div class="muted">${esc(e.city)}</div></td>
          <td data-label="Besökare">${e.attendance ? esc(e.attendance.toLocaleString("sv-SE")) : "—"}</td>
          <td data-label="">${manage ? `<div class="btn-row">${e.hidden
            ? `<button class="btn btn-quiet" data-action="event-show" data-event="${esc(e.id)}">Visa</button>`
            : `<button class="btn btn-quiet" data-action="event-hide" data-event="${esc(e.id)}">Dölj</button>`}
            ${e.source === "manual" ? `<button class="btn btn-danger" data-action="event-delete" data-event="${esc(e.id)}"
              data-name="${esc(e.name)}">Ta bort</button>` : ""}</div>` : ""}</td>
        </tr>`).join("")}</tbody>
    </table>
    ${rows.length ? "" : '<p class="muted">Inga evenemang i perioden.</p>'}</div>
  `;
}

/** Förhandsgranskningen efter att en fil valts: vad som sparas, eller vilka rader som är fel. */
function importPanel(st) {
  if (!st) return "";
  if (st.errors) {
    return `<div class="notice notice-danger"><b>${esc(st.message)}</b>
      <ul>${st.errors.map((e) => `<li>Rad ${esc(e.row)}: ${esc(e.error)}</li>`).join("")}</ul>
      <p class="muted">Rätta filen och välj den igen.</p></div>`;
  }
  return `<div class="notice"><b>${esc(st.count)} evenemang i ${esc(st.filename)} är redo att sparas.</b>
    <div class="table-scroll"><table><thead><tr><th>Datum</th><th>Namn</th><th>Plats</th><th>Sluttid</th></tr></thead>
    <tbody>${(st.preview ?? []).slice(0, 50).map((r) => `<tr>
      <td>${esc(r.date)} ${esc(r.time)}</td><td>${esc(r.name)}<div class="muted">${esc(r.category)}</div></td>
      <td>${esc(r.venue)}<div class="muted">${esc(r.city)}</div></td><td class="muted">${esc(r.endNote)}</td></tr>`).join("")}
    </tbody></table></div>
    ${st.count > 50 ? `<p class="muted">… och ${esc(st.count - 50)} till.</p>` : ""}
    <div class="btn-row"><button class="btn btn-primary" data-action="event-import">Spara ${esc(st.count)} evenemang</button>
      <button class="btn btn-quiet" data-action="event-import-cancel">Avbryt</button></div></div>`;
}

/* --- Granskningar ----------------------------------------------------- */

export function granskning(list) {
  const rows = list.reviews ?? [];
  return `
    <div class="page-head">
      <div><h1>Granskningar</h1>
        <p class="muted">Spärrar kundens nästa ändring tills du godkänner. Åtkomsten påverkas inte.</p></div>
    </div>
    ${rows.length ? rows.map((r) => `
      <div class="card">
        <h2>${esc(r.company)} ${pill(r.status)}</h2>
        <p class="mono">${esc(r.kind)} · ${esc(dateTime(r.createdAt))}</p>
        <p>${esc(r.message)}</p>
        <p class="audit-detail">${esc(JSON.stringify(r.detail))}</p>
        ${r.status === "open" ? `
          <div class="btn-row">
            <button class="btn btn-primary" data-action="review-approve" data-review="${esc(r.id)}">Godkänn</button>
            <button class="btn btn-danger" data-action="review-reject" data-review="${esc(r.id)}">Avslå</button>
          </div>` : ""}
      </div>`).join("") : '<div class="card"><p class="muted">Inga öppna granskningar.</p></div>'}
  `;
}


/**
 * Arkivera och radera (fleet/archive.py). Servern säger vad som går och varför
 * inte; knapparna visas bara när det går, annars skälet.
 */
function archiveCard(d, config) {
  const a = d.archive;
  if (!a) return "";
  if (!a.archivedAt) {
    return `
    <h3>Arkivera</h3>
    <p class="muted">Döljs i listorna. Kan återställas under Kunder → Arkiverade.</p>
    ${a.canArchive
      ? '<div class="btn-row"><button class="btn btn-quiet" data-action="archive">Arkivera bolaget</button></div>'
      : `<p class="muted">${esc(a.archiveBlocker)}</p>
        ${config?.canManage && ["access", "licenses"].includes(a.archiveBlockedBy)
          ? '<div class="btn-row"><button class="btn btn-danger" data-action="terminate-now">Avsluta direkt och arkivera</button></div>'
          : ""}`}`;
  }
  return `
    <h3>Arkiverat ${esc(date(a.archivedAt))}</h3>
    <p class="muted">Bolaget syns bara under Kunder → Arkiverade.</p>
    <div class="btn-row">
      <button class="btn btn-quiet" data-action="unarchive">Återställ</button>
      ${config?.canManage && a.canDelete
        ? '<button class="btn btn-danger" data-action="delete-company">Radera permanent</button>' : ""}
    </div>
    ${a.canDelete
      ? `<p class="muted">Radera tar bort bilar, telefoner, beställningar, chatt, kontaktuppgifter,
          bolagets inloggningar och provhistoriken. Betalda belopp och fakturareferenser sparas
          för bokföringen. Bolaget kan sedan registrera sig och prova igen.
          Så länge det bara är arkiverat får det inget nytt gratisprov, och kontona är pausade.
          ${config?.canManage ? "" : "Bara plattformsadministratören kan radera."}</p>`
      : `<p class="muted">${esc(a.deleteBlocker)}</p>`}`;
}
