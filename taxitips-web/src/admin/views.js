import { countyName, date, dateTime, money } from "../portal/api.js";
import {
  addCarsBlock, cancelBlock, discountBlock, ordersCard, ownerBlock, profileBlock,
  quoteBox, redemptionsCard, registryBlock, trialExtendBlock,
} from "./sales.js";
import { crmNotesCard } from "./crm.js";
import { notifyCard } from "../notify_editor.js";

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

/* --- Kundens cykel ----------------------------------------------------
 *
 * Fem steg, i den ordning en kund faktiskt går igenom dem. Samma regler
 * används för listan (vad är nästa steg för varje kund?) och för kundsidan
 * (vilket steg öppnas, vad är klart). En sanning, två vyer.
 */

export const STEPS = [
  { id: "foretag", title: "Företag", todo: "Kontrollera behörighet" },
  { id: "bilar", title: "Medlemskap", todo: "Lägg till medlemskap" },
  { id: "forare", title: "Förare", todo: "Tilldela konton" },
  { id: "konto", title: "Kundkonto", todo: "Bjud in kundens admin" },
  { id: "betalning", title: "Betalning", todo: "Ordna betalning" },
];

/** Vilka steg är klara, räknat ur listraden (GET /api/admin/companies). */
function doneFromRow(c) {
  const paying = ["active", "past_due"].includes(c.subscriptionStatus) && c.hadPayment;
  return {
    // Utan profil är det en kund från före självregistreringen: inget att kontrollera.
    foretag: c.verificationStatus === "verified" || !c.verificationStatus,
    bilar: (c.licenses ?? 0) > 0,
    // Kontobaserat: en plats räknas som bemannad när den är tilldelad ett konto.
    forare: (c.membershipsAssigned ?? c.phones ?? 0) > 0,
    konto: (c.members ?? 0) > 0,
    betalning: paying,
  };
}

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

function firstOpen(done) {
  return STEPS.find((st) => !done[st.id]) ?? null;
}

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

/** Status i ett ord, för listan och kundsidans rubrik. */
function customerStatus(c, { suspended, paused, trial, subscriptionStatus, accessOk }) {
  if (suspended) return ["pill-danger", "Avstängd"];
  if (paused) return ["pill-warn", "Pausad"];
  if (subscriptionStatus === "past_due") return ["pill-danger", "Obetald"];
  if (c.cancelAtPeriodEnd) return ["pill-warn", "Säger upp"];
  if (subscriptionStatus === "active") return ["pill-ok", "Betalande"];
  if (trial?.status === "active") return ["pill-warn", "Prov pågår"];
  if (trial?.status === "pending") return ["pill-warn", "Prov väntar"];
  if (subscriptionStatus === "canceled") return ["", "Avslutad"];
  return accessOk ? ["pill-ok", "Aktiv"] : ["", "Ny"];
}

function statusPill([cls, label]) {
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

/** Det som faktiskt kräver någon: en rad per kund, med skälet först. */
function attention(c) {
  const days = c.trial?.endsAt ? Math.ceil((new Date(c.trial.endsAt) - Date.now()) / 86400000) : null;
  const healthyPaid = c.subscriptionStatus === "active" && !c.cancelAtPeriodEnd;
  if (c.suspended) return null;
  if (c.subscriptionStatus === "past_due") return { why: "Betalningen har inte kommit in", step: "betalning", level: 3 };
  if (c.cancelAtPeriodEnd) return { why: "Säger upp vid periodens slut – ring och fråga varför", step: "betalning", level: 2 };
  if (c.unpaidOrders) return { why: "Beställning väntar på betalning", step: "betalning", level: 2 };
  // Friska betalande utan öppen faktura: inget brus — Uppföljning tar risklägen.
  if (healthyPaid) return null;
  if (c.verificationStatus === "unverified") return { why: "Registrerade sig själv – kontrollera behörigheten", step: "foretag", level: 2 };
  if (c.trial?.status === "active" && days !== null && days <= 3) return { why: `Provet slutar om ${Math.max(days, 0)} dag(ar) – dags att sälja`, step: "betalning", level: 2 };
  if (c.trial && !(c.membershipsAssigned ?? c.phones) && c.licenses) return { why: "Har medlemskap men inget konto tilldelat", step: "forare", level: 1 };
  if (c.trial && !c.licenses) return { why: "Har inga medlemskap än", step: "betalning", level: 1 };
  return null;
}

/* --- Hem ---------------------------------------------------------------- */

/**
 * Att-göra-läge: inkorg (support, tipprapporter, granskningar, CRM) överst
 * med ett klick, sedan kundrader, statusrad och nyckeltal.
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
  const todo = companies
    .map((c) => ({ c, a: attention(c) }))
    .filter((x) => x.a)
    .sort((x, y) => y.a.level - x.a.level);
  const trialsEnding = companies.filter((c) => {
    if (c.trial?.status !== "active" || !c.trial.endsAt) return false;
    const days = Math.ceil((new Date(c.trial.endsAt) - Date.now()) / 86400000);
    return days >= 0 && days <= 3;
  }).length;

  const inboxItems = [
    supportWaiting ? {
      view: "support",
      label: supportWaiting === 1 ? "1 fråga väntar i supporten" : `${supportWaiting} frågor väntar i supporten`,
      go: "Öppna support",
      level: 3,
      danger: true,
    } : null,
    tipReportsOpen ? {
      view: "tipprapporter",
      label: tipReportsOpen === 1 ? "1 tipprapport att granska" : `${tipReportsOpen} tipprapporter att granska`,
      go: "Granska",
      level: 3,
      danger: true,
    } : null,
    reviewsOpen ? {
      view: "granskning",
      label: reviewsOpen === 1 ? "1 riskgranskning väntar" : `${reviewsOpen} riskgranskningar väntar`,
      go: "Öppna",
      level: 3,
      danger: true,
    } : null,
    crmOverdue ? {
      view: "pipeline",
      filter: "tasks",
      label: crmOverdue === 1 ? "1 försenad CRM-uppgift" : `${crmOverdue} försenade CRM-uppgifter`,
      go: "Öppna uppgifter",
      level: 2,
    } : null,
    trialsEnding ? {
      view: "kunder",
      filter: "prov",
      label: trialsEnding === 1
        ? "1 prov slutar inom 3 dagar"
        : `${trialsEnding} prov slutar inom 3 dagar`,
      go: "Visa prov",
      level: 2,
    } : null,
  ].filter(Boolean);

  return `
    <div class="page-head">
      <div><h1>Hem</h1><p class="muted">Det som behöver dig just nu. Ett klick tar dig dit.</p></div>
      <button class="btn btn-primary" data-action="goto" data-view="nykund">+ Ny kund</button>
    </div>

    ${inboxItems.length ? `
    <div class="card attn-inbox">
      <h2>Inkorg</h2>
      <ul class="todo">${inboxItems.map((item) => `
        <li><button class="todo-row${item.danger ? " is-danger" : ""}" data-action="goto"
          data-view="${esc(item.view)}"${item.filter ? ` data-filter="${esc(item.filter)}"` : ""}>
          <span class="todo-dot lvl-${item.level}" aria-hidden="true"></span>
          <span class="todo-main"><b>${esc(item.label)}</b></span>
          <span class="todo-go">${esc(item.go)} →</span>
        </button></li>`).join("")}</ul>
    </div>` : ""}

    <div class="card">
      <h2>Kunder som behöver åtgärd <span class="muted">(${esc(todo.length)})</span></h2>
      ${todo.length ? `<ul class="todo">${todo.map(({ c, a }) => `
        <li><button class="todo-row" data-action="open-company" data-id="${esc(c.id)}" data-tab="${esc(a.step)}">
          <span class="todo-dot lvl-${a.level}" aria-hidden="true"></span>
          <span class="todo-main"><b>${esc(c.name)}</b><span class="muted">${esc(a.why)}</span></span>
          <span class="todo-go">${esc(STEPS.find((st) => st.id === a.step)?.title ?? "")} →</span>
        </button></li>`).join("")}</ul>`
        : `<p class="muted">${inboxItems.length
          ? "Inga kunder kräver åtgärd just nu."
          : "Inget att göra just nu."}</p>`}
    </div>

    ${statusReport ? `
    <button type="button" class="status-inline st-${esc(statusReport.overall ?? "ok")}"
      data-action="goto" data-view="status">
      <span class="st-dot st-${esc(statusReport.overall ?? "ok")}" aria-hidden="true"></span>
      <span>Datakällor: ${esc(statusLine || "okänt")}</span>
      <span class="todo-go">Status →</span>
    </button>` : ""}

    <details class="card attn-kpis">
      <summary>Nyckeltal</summary>
      <div class="kpis">
        ${kpi("Kunder", esc(d.companies), { view: "kunder" })}
        ${kpi("Betalande", esc(subs.active ?? 0), { view: "kunder" })}
        ${kpi("Prov", esc(d.trialsActive), { view: "kunder" })}
        ${kpi("MRR exkl. moms", esc(money(d.mrrOre, d.currency)))}
        ${kpi("Förare i tjänst nu", esc(d.sessionsActive))}
      </div>
    </details>
  `;
}

/* --- Kunder ------------------------------------------------------------- */

const FILTERS = [
  ["alla", "Alla"],
  ["atgard", "Behöver åtgärd"],
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

export function kunder(list, query = "", filter = "alla") {
  const all = list.companies ?? [];
  const rows = all.filter((c) => matchesFilter(c, filter));
  return `
    <div class="page-head">
      <h1>Kunder</h1>
      <button class="btn btn-primary" data-action="goto" data-view="nykund">+ Ny kund</button>
    </div>
    <form class="toolbar" id="searchForm">
      <label class="visually-hidden" for="q">Sök</label>
      <input id="q" name="q" value="${esc(query)}" placeholder="Sök namn eller orgnr" />
      <button class="btn btn-quiet" type="submit">Sök</button>
    </form>
    <div class="chips" role="tablist" aria-label="Filter">
      ${FILTERS.map(([id, label]) => `<button class="chip" role="tab" data-action="kund-filter" data-filter="${id}"
        aria-selected="${id === filter}">${esc(label)} <span class="muted">${esc(
          id === "arkiverade" ? (list.archivedCount ?? 0)
            : filter === "arkiverade" ? "" : all.filter((c) => matchesFilter(c, id)).length,
        )}</span></button>`).join("")}
    </div>
    <div class="card list-card">
      ${rows.length ? rows.map((c) => {
        const done = doneFromRow(c);
        const next = firstOpen(done);
        const a = attention(c);
        return `
        <button class="cust-row" data-action="open-company" data-id="${esc(c.id)}" data-tab="${esc(a?.step ?? "")}">
          <span class="cust-main"><b>${esc(c.name)}</b>
            <span class="muted mono">${esc(c.orgNumber || "—")}</span></span>
          <span class="cust-steps" aria-label="Steg klara">${STEPS.map((st) =>
            `<i class="${done[st.id] ? "on" : ""}" title="${esc(st.title)}"></i>`).join("")}</span>
          <span class="cust-status">${statusPill(customerStatus(c, c))}</span>
          <span class="cust-next muted">${esc(a?.why ?? (next ? next.todo : "Klar"))}</span>
        </button>`;
      }).join("") : '<p class="muted">Inga kunder här.</p>'}
    </div>
  `;
}

/* --- En kund ------------------------------------------------------------
 *
 * Fyra flikar, samma ord som i portalen och appen: översikt, medlemskap
 * (platser och konton), inloggning till portalen, betalning (sälj och
 * debitering). Manuella undantag ligger under Betalning eller ihopfällda.
 */

export const KUND_TABS = [
  { id: "oversikt", title: "Översikt" },
  { id: "bilar", title: "Medlemskap" },
  { id: "konton", title: "Inloggningar" },
  { id: "betalning", title: "Betalning" },
];

/** Sällan använda flikar — under Mer på kundkortet. */
export const KUND_TABS_MORE = [
  { id: "foretag", title: "Företag" },
  { id: "historik", title: "Historik" },
];

const ALL_KUND_TABS = [...KUND_TABS, ...KUND_TABS_MORE];

/** Ett steg i cykeln (Hem, Kunder) till fliken där det görs. */
const TAB_FOR = { foretag: "foretag", bilar: "bilar", forare: "bilar", konto: "konton", betalning: "betalning" };

export function kundTab(tab) {
  if (ALL_KUND_TABS.some((t) => t.id === tab)) return tab;
  return TAB_FOR[tab] ?? "oversikt";
}

/** Det som är fel eller saknas, i den ordning det brådskar. */
function issues(d) {
  const s = d.subscription;
  const t = d.trial;
  const done = doneFromDetail(d);
  const list = [];
  const add = (level, text, tab, label) => list.push({ level, text, tab, label });
  if (s?.status === "past_due") add(3, "Betalningen har inte kommit in.", "betalning", "Betalning");
  const unpaid = (d.orders ?? []).filter((o) => o.status === "pending_payment" && !["canceled", "failed"].includes(o.status)).length;
  if (unpaid) add(2, `${unpaid} beställning(ar) väntar på betalning.`, "betalning", "Betalning");
  if (s?.cancelAtPeriodEnd) add(2, `Har sagt upp. Åtkomsten slutar ${date(s.accessUntil)}.`, "betalning", "Betalning");
  if (d.profile?.verificationStatus && d.profile.verificationStatus !== "verified") {
    add(2, "Registrerade sig själv – behörigheten är inte kontrollerad.", "foretag", "Kontrollera");
  }
  if (t?.status === "active" && t.endsAt) {
    const days = Math.ceil((new Date(t.endsAt) - Date.now()) / 86400000);
    if (days <= 3) add(2, `Provet slutar om ${Math.max(days, 0)} dag(ar).`, "betalning", "Betalning");
  }
  if (!done.bilar) add(1, "Har inga medlemskap.", "betalning", "Lägg till medlemskap");
  else if (!done.forare) add(1, "Inget konto är tilldelat något medlemskap.", "bilar", "Tilldela konton");
  if (!done.konto) add(1, "Ingen kan logga in i kundportalen.", "konton", "Bjud in");
  if (!d.suspension && !d.pause && d.access && !d.access.ok && !list.some((i) => i.level === 3)) {
    add(2, `Får inga tips: ${ACCESS_TEXT[d.access.reason] ?? d.access.reason}.`, "betalning", "Betalning");
  }
  const reviews = (d.reviews ?? []).filter((r) => r.status === "open").length;
  if (reviews) add(1, `${reviews} riskgranskning(ar) väntar.`, "", "");
  return list.sort((a, b) => b.level - a.level);
}

export function kund(d, config = null, tab = "", pending = null, crm = null, loginLink = null) {
  const c = d.company;
  const p = d.profile ?? {};
  const active = kundTab(tab);
  const status = customerStatus(c, {
    suspended: !!d.suspension, paused: !!d.pause, trial: d.trial, subscriptionStatus: d.subscription?.status,
    accessOk: d.access?.ok,
  });
  const open = (d.licenses ?? []).filter((l) => LICENSE_OPEN.includes(l.status));
  const found = issues(d);
  const badge = {
    bilar: open.length,
    konton: (d.members ?? []).filter((m) => m.status === "active").length,
  };
  const alertTabs = new Set(found.filter((i) => i.level >= 2).map((i) => i.tab));
  const moreActive = KUND_TABS_MORE.some((t) => t.id === active);
  const panel = {
    oversikt: () => tabOversikt(d, config, crm, found),
    bilar: () => tabBilar(d, config, pending),
    konton: () => tabKonton(d, config, loginLink),
    betalning: () => tabBetalning(d, config),
    foretag: () => tabForetag(d, config, crm),
    historik: () => tabHistorik(d),
  }[active]();
  const contact = [
    p.contactName ? esc(p.contactName) : "",
    p.contactPhone ? `<a href="tel:${esc(p.contactPhone.replace(/\s/g, ""))}">${esc(p.contactPhone)}</a>` : "",
    p.contactEmail ? `<a href="mailto:${esc(p.contactEmail)}">${esc(p.contactEmail)}</a>` : "",
  ].filter(Boolean).join(" · ");
  const next = found[0];

  return `
    <button class="back-link" data-action="back">← Alla kunder</button>
    <div class="page-head">
      <div><h1>${esc(c.name)} ${statusPill(status)}</h1>
        <p class="muted"><span class="mono">${esc(c.orgNumber || "—")}</span>${contact ? ` · ${contact}` : ""}</p></div>
      <div class="btn-row">
        <button class="btn btn-quiet" data-action="support-start">Chatta med kunden</button>
        ${config?.canSell && !d.suspension && !d.pause
          ? '<button class="btn btn-quiet" data-action="company-pause">Pausa tipsen</button>' : ""}
      </div>
    </div>

    ${d.suspension ? `
      <div class="suspended-banner" role="alert">
        <b>Företaget är avstängt.</b> ${esc(d.suspension.reason)}
        ${config?.canManage ? `<button class="btn btn-quiet" data-action="block-lift" data-block="${esc(d.suspension.id)}">Häv avstängningen</button>` : ""}
      </div>` : d.pause ? `
      <div class="paused-banner" role="status">
        <b>Tipsen är pausade.</b> ${esc(d.pause.reason)}
        <span class="muted">Ingen tips och inga notiser. Kunden ser ett neutralt besked i appen och kan
          ordna medlemskapet i kundportalen.</span>
        ${config?.canSell ? '<button class="btn btn-quiet" data-action="company-resume">Återuppta tipsen</button>' : ""}
      </div>` : `
      <p class="access-line ${d.access?.ok ? "ok" : "bad"}">${d.access?.ok
        ? `Förarna får tips${d.access.validUntil ? ` till ${esc(date(d.access.validUntil))}` : ""}.`
        : `Förarna får inga tips: ${esc(ACCESS_TEXT[d.access?.reason] ?? d.access?.reason ?? "okänt skäl")}.`}</p>`}

    ${next && active === "oversikt" ? `
      <div class="next-action">
        <p><b>Nästa steg:</b> ${esc(next.text)}</p>
        ${next.tab
          ? `<button class="btn btn-primary" data-action="kund-tab" data-tab="${esc(next.tab)}">${esc(next.label || "Öppna")} →</button>`
          : `<button class="btn btn-primary" data-action="goto" data-view="granskning">${esc(next.label || "Granskning")} →</button>`}
      </div>` : ""}

    <div class="ktabs-wrap">
    <nav class="ktabs" aria-label="Kundens sidor">
      ${KUND_TABS.map((t) => `
        <button class="ktab" data-action="kund-tab" data-tab="${t.id}" aria-current="${t.id === active ? "page" : "false"}">
          ${esc(t.title)}${badge[t.id] != null ? ` <span class="ktab-n">${esc(badge[t.id])}</span>` : ""}${alertTabs.has(t.id) ? '<span class="ktab-dot" aria-label="behöver åtgärd"></span>' : ""}
        </button>`).join("")}
      <details class="ktab-more"${moreActive ? " open" : ""}>
        <summary class="ktab ktab-more-toggle${moreActive ? " is-on" : ""}">Mer${
          KUND_TABS_MORE.some((t) => alertTabs.has(t.id))
            ? '<span class="ktab-dot" aria-label="behöver åtgärd"></span>' : ""
        }</summary>
        <div class="ktab-more-menu" role="menu">
          ${KUND_TABS_MORE.map((t) => `
            <button type="button" role="menuitem" class="ktab-more-item" data-action="kund-tab" data-tab="${t.id}"
              aria-current="${t.id === active ? "page" : "false"}">${esc(t.title)}${
                alertTabs.has(t.id) ? '<span class="ktab-dot" aria-label="behöver åtgärd"></span>' : ""
              }</button>`).join("")}
        </div>
      </details>
    </nav>
    </div>

    <section class="step-panel">${panel}</section>
  `;
}

/* --- Översikt ----------------------------------------------------------- */

function tile(tab, label, value, sub = "") {
  return `<button type="button" class="ktile" data-action="kund-tab" data-tab="${esc(tab)}">
    <span class="ktile-label">${esc(label)}</span><b>${value}</b>${sub ? `<span class="muted">${sub}</span>` : ""}</button>`;
}

function tabOversikt(d, config, crm, found) {
  const s = d.subscription;
  const t = d.trial;
  const open = (d.licenses ?? []).filter((l) => LICENSE_OPEN.includes(l.status));
  const assigned = open.filter((l) => l.assigned).length;
  const members = (d.members ?? []).filter((m) => m.status === "active" && !m.blocked).length;
  const plan = s && ["active", "past_due"].includes(s.status)
    ? pill(s.status)
    : t && ["pending", "active"].includes(t.status) ? '<span class="pill pill-warn">Prov</span>' : pill(s?.status ?? "none");
  const planSub = s?.monthlyOre && ["active", "past_due"].includes(s.status)
    ? `${esc(money(s.monthlyOre))}/mån exkl. moms${s.periodEnd ? ` · betalt till ${esc(date(s.periodEnd))}` : ""}`
    : t?.status === "active" ? `till ${esc(date(t.endsAt))}`
      : t?.status === "pending" ? "startar när första kontot loggar in" : "";
  return `
    <div class="card">
      <h2>Att åtgärda</h2>
      ${found.length ? `<ul class="todo">${found.map((i) => `
        <li><button class="todo-row" ${i.tab ? `data-action="kund-tab" data-tab="${esc(i.tab)}"` : 'data-action="goto" data-view="granskning"'}>
          <span class="todo-dot lvl-${i.level}" aria-hidden="true"></span>
          <span class="todo-main"><b>${esc(i.text)}</b></span>
          <span class="todo-go">${esc(i.label || "Granskning")} →</span>
        </button></li>`).join("")}</ul>`
        : '<p class="ok">Inget att åtgärda. Kunden har medlemskap, konton, inloggning och betalning på plats.</p>'}
    </div>

    <div class="ktiles">
      ${tile("betalning", "Abonnemang", plan, planSub)}
      ${tile("bilar", "Medlemskap", esc(open.length), `${esc(assigned)} tilldelade konton`)}
      ${tile("konton", "Inloggningar", esc(members), members ? "ägare och administratörer" : "ingen kan logga in")}
      ${tile("foretag", "Behörighet", d.profile?.verificationStatus ? verificationPill(d.profile.verificationStatus) : '<span class="pill">Äldre kund</span>')}
    </div>

    ${crmNotesCard(crm, config)}
  `;
}

/* --- Medlemskap --------------------------------------------------------- */

/**
 * Bjud in till en ledig plats — samma som i kundportalen. Nya platser köps
 * under Betalning, de skapas inte gratis här.
 */
function membershipLabel(l) {
  if (l.vehicle) return l.vehicle;
  return `Medlemskap · ${l.baseCounty ? countyName(l.baseCounty) : "utan län"}`;
}

function inviteUnassignedBlock(d, config) {
  if (!config?.canSell) return "";
  const open = (d.licenses ?? []).filter((l) => LICENSE_OPEN.includes(l.status));
  const free = open.filter((l) => !l.assigned);
  if (!free.length) return "";
  return `
    <div class="card">
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
  return `
    <details class="card">
      <summary>Manuellt: skapa plats utan beställning</summary>
      <p class="muted">Bara när Stripe inte ska in. Platsen räknas mot nästa faktura om den inte
        beviljas utan kostnad nedan. Vanliga sälj skapar platser under Betalning.</p>
      <div class="county-add">
        <input id="newMemberEmail" type="email" placeholder="namn@bolaget.se" autocomplete="off" />
        <select id="newMemberCounty" aria-label="Baslän för den nya platsen">
          <option value="">Baslän (valfritt)</option>
          ${counties.map((c) => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("")}
        </select>
        <button class="btn btn-quiet btn-small" data-action="membership-create">Skapa plats</button>
      </div>
    </details>`;
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
 * Manuellt beviljande (fleet/grants.py): medlemskap utan kostnad till en
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
  return `
    <details class="card"${active ? " open" : ""}>
      <summary>Beviljat utan kostnad <span class="muted">(${esc(active)})</span></summary>
      <p class="muted">Medlemskap utan betalning, till en person, med de kategorier och län du väljer.
        Ingen order, ingen faktura och ingen ändring i Stripe — platsen räknas inte mot nästa faktura.
        Skälet loggas. Ett bolag som redan betalar behåller alla kategorier.</p>
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
        <button class="btn btn-quiet" data-action="grant-membership">Tilldela utan kostnad</button>
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
        </tbody></table>` : '<p class="muted">Inga beviljanden.</p>'}
    </details>`;
}

function tabBilar(d, config, pending) {
  const devices = d.devices ?? [];
  const notifyHtml = d.notify ? notifyCard({ ...d.notify, canManage: !!config?.canSell }, {
    countyNames: Object.fromEntries((d.notify.countyCatalog ?? []).map((c) => [c.code, c.name])),
    title: "Notiser per telefon",
  }) : "";
  return `
    ${inviteUnassignedBlock(d, config)}
    ${membershipsCard(d, config, pending)}
    ${addMembershipBlock(d, config)}
    ${companyChangesCard(d, config)}
    <details class="support-fold">
      <summary>Telefoner och notiser <span class="muted">(${esc(devices.length)})</span></summary>
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
      <p class="muted">Utan notistoken kan telefonen inte få notiser – be föraren öppna appen och tillåta notiser.
        Ett extra telefonbyte behövs när föraren har bytt telefon en gång den här månaden.</p>
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
  change_base_county: "Byt baslän",
  remove_county: "Ta bort extra län",
  reduce_licenses: "Avsluta medlemskap",
  cancel_subscription: "Uppsägning",
};

/** Baslän för alla medlemskap på en gång, och det som väntar på förnyelsen. */
function companyChangesCard(d, config) {
  if (!config?.canSell) return "";
  const open = (d.licenses ?? []).filter((l) => LICENSE_OPEN.includes(l.status));
  const pending = d.pendingChanges ?? [];
  const anyPaid = open.some((l) => l.status !== "trial");
  const canBase = open.length > 1 && (!anyPaid || config.canManage);
  if (!canBase && !pending.length) return "";
  const counties = config?.counties ?? [];
  const subject = (id) => open.find((l) => l.id === id)?.vehicle || "medlemskap";
  const describe = (p) => {
    const pl = p.payload ?? {};
    if (p.kind === "change_base_county") return `${subject(pl.licenseId)} → ${countyName(pl.county)}`;
    if (p.kind === "remove_county") return `${countyName(pl.county)} på ${subject(pl.licenseId)}`;
    if (p.kind === "reduce_licenses") return (pl.licenseIds ?? []).map(subject).filter(Boolean).join(", ");
    return pl.reason ? `Orsak: ${pl.reason}` : "";
  };
  const body = `
      ${canBase ? `
      <h3>Byt baslän på alla medlemskap direkt</h3>
      <p class="muted">Påverkar inte priset. Ett extra län som blir baslän tas bort. Skälet loggas.</p>
      <div class="county-add">
        <select id="companyBase" aria-label="Nytt baslän för alla medlemskap">
          <option value="">Välj län …</option>
          ${counties.map((c) => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("")}
        </select>
        <button class="btn btn-quiet btn-small" data-action="company-base-now">Byt för alla medlemskap</button>
      </div>` : ""}
      ${pending.length ? `<h3>Väntar på förnyelsen</h3><table><thead><tr><th>Ändring</th><th>Gäller från</th><th></th></tr></thead>
        <tbody>${pending.map((p) => `
          <tr><td data-label="Ändring"><b>${esc(PENDING_KIND[p.kind] ?? p.kind)}</b>
              <div class="muted">${esc(describe(p))}</div></td>
            <td data-label="Gäller från">${esc(date(p.effectiveAt))}</td>
            <td>${config.canManage && p.kind !== "cancel_subscription"
              ? `<button class="btn btn-quiet btn-small" data-action="pending-undo" data-change="${esc(p.id)}"
                  data-label="${esc(PENDING_KIND[p.kind] ?? p.kind)}">Ångra</button>`
              : p.kind === "cancel_subscription" ? '<span class="muted">Ångras under Betalning</span>' : ""}</td></tr>`).join("")}
        </tbody></table>` : ""}`;
  return pending.length
    ? `<div class="card"><h2>Ändringar för hela företaget</h2>${body}</div>`
    : `<details class="card"><summary>Byt baslän på alla medlemskap</summary>${body}</details>`;
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
  const t = d.trial;
  return `
    ${addCarsBlock(d, config)}
    <div class="card">
      <h2>Just nu</h2>
      <dl class="kv">
        <dt>Läge</dt><dd>${s ? pill(s.status) : "—"}
          ${t && ["pending", "active"].includes(t.status) ? `<span class="pill pill-warn">Prov ${t.startedAt ? `till ${esc(date(t.endsAt))}` : "startar när första kontot loggar in"}</span>` : ""}
          ${s?.cancelAtPeriodEnd ? '<span class="pill pill-warn">Uppsagt</span>' : ""}</dd>
        ${s?.periodEnd ? `<dt>Betalt till</dt><dd>${esc(date(s.periodEnd))}</dd>` : ""}
        ${s?.monthlyOre ? `<dt>Per månad</dt><dd>${esc(money(s.monthlyOre))} exkl. moms</dd>` : ""}
        ${s?.licenseCount != null ? `<dt>Platser</dt><dd>${esc(s.licenseCount)}</dd>` : ""}
        ${s?.extraCountyCount != null ? `<dt>Extra län</dt><dd>${esc(s.extraCountyCount)}</dd>` : ""}
        ${s?.packageSummary ? `<dt>Paket</dt><dd>${esc(s.packageSummary)}</dd>` : ""}
        ${d.discount ? `<dt>Rabatt</dt><dd>${d.discount.kind === "percent_bp"
          ? `${esc((d.discount.value / 100).toFixed(2))} %` : `${esc(money(d.discount.value))}/mån`}</dd>` : ""}
      </dl>
    </div>
    ${ordersCard(d.orders, config)}
    ${trialExtendBlock(d, config)}
    ${grantsCard(d, config)}
    ${config?.canManage ? `
    <details class="card">
      <summary>Ge åtkomst utan Stripe</summary>
      <p class="muted">När kunden behöver några dagar till medan en betalning går igenom.
        Ändrar appens rättigheter, inte Stripe. Skälet loggas.</p>
      <div class="btn-row">
        <button class="btn btn-quiet" data-action="extend" data-days="7">+7 dagar</button>
        <button class="btn btn-quiet" data-action="extend" data-days="30">+30 dagar</button>
      </div>
    </details>` : ""}
    ${discountBlock(d, config)}
    ${redemptionsCard(d.couponRedemptions)}
    ${cancelBlock(d, config)}
    ${config?.canManage && !["canceled"].includes(d.subscription?.status) ? `
    <details class="card danger-zone">
      <summary>Avsluta direkt</summary>
      <p class="muted">Åtkomsten upphör nu, alla medlemskap och förarpass avslutas och Stripe slutar debitera.
        Ingen återbetalning görs automatiskt.</p>
      <div class="btn-row"><button class="btn btn-danger" data-action="terminate-now">Avsluta direkt</button></div>
    </details>` : ""}
  `;
}

/* --- Företag ------------------------------------------------------------ */

function tabForetag(d, config, crm) {
  const p = d.profile ?? {};
  const deal = crm?.deal;
  return `
    ${verificationCard(d, config)}
    ${config?.canSell ? profileBlock(d) : `
    <div class="card">
      <h2>Uppgifter</h2>
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
        ${config?.canSell && (p.country ?? "SE") === "SE" ? `<div class="btn-row">
          <button class="btn btn-quiet btn-small" data-action="registry-refresh">Hämta igen</button>
          ${p.registry?.found ? `<button class="btn btn-quiet btn-small" data-action="registry-refresh" data-overwrite="1">Använd registrets adress</button>` : ""}
        </div>` : ""}
      </div>
      ${p.registry ? registryBlock(p.registry, { checkedAt: p.registryCheckedAt })
        : '<p class="muted">Inte uppslaget än. Tryck på <b>Hämta igen</b>.</p>'}
      ${deal?.id ? `<p class="muted small"><button type="button" class="linklike" data-action="crm-open-deal" data-deal="${esc(deal.id)}">Öppna i CRM</button></p>` : ""}
    </div>
    ${config?.canManage || d.archive ? `
    <details class="card danger-zone">
      <summary><h2>Stäng av, arkivera eller radera</h2></summary>
      ${dangerZone(d, config)}
      ${archiveCard(d, config)}
    </details>` : ""}
  `;
}

/* --- Historik ----------------------------------------------------------- */

const ACTOR = {
  platform_admin: "Personal", customer: "Kunden", admin: "Kunden", owner: "Kunden",
  driver: "Förare", system: "Systemet", stripe: "Stripe",
};

const AUDIT = {
  account_closed: "Kontot avslutades",
  admin_base_county_set: "Baslän bytt direkt",
  admin_company_base_county_set: "Baslän bytt på alla medlemskap",
  admin_company_verification: "Behörighet bedömd",
  admin_device_blocked: "Telefon spärrad",
  admin_driver_invite_resent: "Förarinbjudan skickad igen",
  admin_driver_invite_revoked: "Förarinbjudan återkallad",
  admin_driver_invited: "Förare inbjuden med e-post",
  admin_license_removed: "Bil borttagen",
  admin_member_changed: "Inloggning ändrad",
  admin_pairing_code_issued: "Förarkod skapad",
  admin_pending_change_undone: "Väntande ändring ångrad",
  admin_subscription_changed: "Åtkomst ändrad för hand",
  admin_test_push: "Testnotis skickad",
  admin_device_notify_prefs_changed: "Notiser ändrade på telefon (support)",
  admin_company_notify_default_changed: "Standard för notiser ändrad (support)",
  admin_trial_counties_set: "Provbilens län ändrade",
  admin_vehicle_changed: "Regnr bytt",
  admin_vehicle_released: "Bilen frigjord",
  base_county_changed: "Baslän bytt",
  company_archived: "Arkiverat",
  company_details_updated: "Uppgifter ändrade",
  company_discount_cleared: "Rabatt borttagen",
  company_discount_set: "Rabatt satt",
  company_unarchived: "Återställt från arkivet",
  contracting_party_change_requested: "Byte av avtalspart begärt",
  county_activated: "Län tillagt",
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
  license_created: "Bil tillagd",
  licenses_reduced: "Bilar avslutade",
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
  trial_vehicle_removed: "Provbil borttagen",
  vehicle_created: "Bil skapad",
};

/** Detaljen som läsbar text: bara enkla värden, nycklar på svenska där det går. */
function auditDetail(detail) {
  if (!detail || typeof detail !== "object") return "";
  const skip = new Set(["license_id", "vehicle_id", "licenseId", "vehicleId", "device_id", "approval_id"]);
  return Object.entries(detail)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== "" && typeof v !== "object")
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ")
    .slice(0, 200);
}

function tabHistorik(d) {
  const rows = d.audit ?? [];
  return `
    <div class="card table-scroll">
      <h2>Händelser <span class="muted">(senaste ${esc(rows.length)})</span></h2>
      ${rows.length ? `<table><thead><tr><th>När</th><th>Vad</th><th>Vem</th></tr></thead>
      <tbody>${rows.map((e) => `
        <tr><td data-label="När">${esc(dateTime(e.at))}</td>
          <td data-label="Vad"><b>${esc(AUDIT[e.action] ?? e.action)}</b>
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
      <p class="muted">Företaget registrerade sig själv. En e-post och ett orgnr bevisar
        inte att personen får företräda bolaget. Ring växeln eller kontrollera firmatecknare,
        och skriv hur det gjordes.</p>
      <p class="muted">Nuvarande anteckning: ${esc(p.verificationNote || "—")}</p>
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
      <h2>Vem kan logga in</h2>
      <p class="muted">Ägare och administratörer i kundportalen och appens adminläge. Förarplatser bjuds in
        under <button class="linklike" data-action="kund-tab" data-tab="bilar">Medlemskap</button>.</p>
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
        : '<p class="muted">Ingen kan logga in än. Bjud in kundens ägare nedan.</p>'}
      <p class="muted small"><b>Ägare</b> gör allt. <b>Bilar och förare</b> sköter medlemskap, län och konton.
        <b>Ekonomi</b> ser och betalar fakturor.</p>
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
  const extraPrice = money(config?.price?.extraCountyOre);
  const name = (code) => countyName(code);
  return `
    <div class="card">
      <h2>Medlemskap <span class="muted">(${esc(open.length)})</span></h2>
      <p class="muted">En plats gäller ett konto i ett län, samma som i appen och portalen.
        Bjud in med e-post — personen loggar in i appen och tar platsen där.</p>
      ${open.length ? open.map((l) => {
        const trial = l.status === "trial";
        const extras = l.extraCounties ?? [];
        const free = counties.filter((c) => !(l.counties ?? []).includes(c.code) && c.code !== l.baseCounty);
        const mine = pending?.licenseId === l.id ? pending : null;
        const data = `data-license="${esc(l.id)}" data-base="${esc(l.baseCounty)}" data-extras="${esc(extras.join(","))}" data-plate="${esc(l.vehicle)}" data-trial="${trial ? "1" : ""}"`;
        const title = membershipLabel(l);
        return `
        <div class="car ${mine ? "car-pending" : ""}">
          <div class="car-head">
            <b class="${l.vehicle ? "plate" : "seat-title"}">${esc(title)}</b> ${pill(l.status)}
            ${l.assignmentKind === "temporary" && l.vehicle ? '<span class="pill pill-warn">Ersättningsbil</span>' : ""}
          </div>
          <div class="county-chips" aria-label="Län">
            <span class="county-chip base" title="Ingår i medlemskapets pris">${esc(name(l.baseCounty))} <small>baslän</small></span>
            ${extras.map((c) => `<span class="county-chip">${esc(name(c))}
              ${sell ? `<button class="chip-x" data-action="county-remove" data-county="${esc(c)}" ${data}
                aria-label="Ta bort ${esc(name(c))}" title="Ta bort ${esc(name(c))}">✕</button>` : ""}</span>`).join("")}
            ${l.scheduledBaseCounty ? `<span class="muted">baslän byts till ${esc(name(l.scheduledBaseCounty))} vid förnyelse</span>` : ""}
          </div>
          ${countyChangesRow(l, sell)}
          ${membershipRow(l, sell)}
          ${l.status === "pending_cancel" ? `<p class="muted">Medlemskapet avslutas vid nästa förnyelse${l.endsAt ? ` (${esc(date(l.endsAt))})` : ""}.</p>` : ""}

          ${sell ? `
          <details class="car-edit" ${mine ? "open" : ""}>
            <summary>Ändra medlemskapets län</summary>
            <div class="car-actions">
              ${l.status !== "pending_cancel" ? `
              <div class="county-add">
                <select data-add-county="${esc(l.id)}" aria-label="Välj län att lägga till">
                  <option value="">+ Lägg till län …</option>
                  ${free.map((c) => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("")}
                </select>
                <button class="btn btn-quiet btn-small" data-action="county-add" ${data}>Lägg till</button>
                <span class="muted">${trial ? "gratis under provet" : `+${esc(extraPrice)}/mån`}</span>
              </div>
              <div class="county-add">
                <select data-base-for="${esc(l.id)}" aria-label="Byt baslän">
                  <option value="">Byt baslän …</option>
                  ${counties.filter((c) => c.code !== l.baseCounty).map((c) => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("")}
                </select>
                <button class="btn btn-quiet btn-small" data-action="base-change" ${data}>${trial ? "Byt" : "Byt vid förnyelse"}</button>
                ${!trial && manage ? `<button class="btn btn-quiet btn-small" data-action="base-change-now" ${data}
                  title="Byter direkt i stället för vid förnyelsen. Påverkar inte priset.">Byt nu</button>` : ""}
              </div>` : ""}
              <div class="btn-row">
                ${l.status !== "pending_cancel" ? `<button class="btn btn-danger btn-small" data-action="car-remove" ${data}>Ta bort medlemskapet</button>` : ""}
              </div>
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
      }).join("") : '<p class="muted">Inga medlemskap än. Lägg till under Betalning.</p>'}
      ${closed ? `<p class="muted">${esc(closed)} avslutat medlemskap visas inte.</p>` : ""}
    </div>`;
}

function dangerZone(d, config) {
  if (!config?.canManage || d.suspension) return "";
  return `
    <h3>Stäng av företaget</h3>
    <p class="muted">Alla förartelefoner och inloggningar slutar få data direkt. Inget raderas, och när
      avstängningen hävs fungerar allt som förut. Stripe påverkas inte — säg upp under Betalning om
      debiteringen också ska sluta.</p>
    <div class="btn-row"><button class="btn btn-danger" data-action="suspend">Stäng av företaget</button></div>`;
}

/* --- Notiser ---------------------------------------------------------- */

export function notiser(list, status = "") {
  const rows = list.notifications ?? [];
  const opt = (v, l) => `<option value="${v}" ${v === status ? "selected" : ""}>${l}</option>`;
  return `
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
        <p class="muted">Det förarna ser under Evenemang i appen, i sina län. Dolda syns inte för någon förare.</p></div>
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
    <p class="muted">Riskärenden blockerar kundens NÄSTA ändring, aldrig åtkomsten
      som redan gäller. Godkänn för att släppa spärren.</p>
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
    <p class="muted">Döljer bolaget från Hem, Kunder och Uppföljning. Inget tas bort, och det går att
      återställa under Kunder → Arkiverade.</p>
    ${a.canArchive
      ? '<div class="btn-row"><button class="btn btn-quiet" data-action="archive">Arkivera bolaget</button></div>'
      : `<p class="muted">${esc(a.archiveBlocker)}</p>`}`;
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
      ? `<p class="muted">Radera tar bort bilar, telefoner, beställningar, chatt och kontaktuppgifter.
          Provhistoriken på organisationsnumret sparas, så att bolaget inte kan få ett nytt gratisprov.
          ${config?.canManage ? "" : "Bara plattformsadministratören kan radera."}</p>`
      : `<p class="muted">${esc(a.deleteBlocker)}</p>`}`;
}
