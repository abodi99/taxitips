import { countyName, date, dateTime, money } from "../portal/api.js";
import { addCarsBlock, cancelBlock, ordersCard, ownerBlock, profileBlock, quoteBox, redemptionsCard } from "./sales.js";

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
  trial: ["pill-warn", "Provbil"],
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
  { id: "bilar", title: "Bilar", todo: "Lägg till bilar" },
  { id: "forare", title: "Förare", todo: "Koppla förare" },
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
    forare: (c.phones ?? 0) > 0,
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
    forare: open.some((l) => (l.approvals ?? []).some((a) => a.status === "active")),
    konto: (d.members ?? []).some((m) => m.status === "active"),
    betalning: !!(s && ["active", "past_due"].includes(s.status) && s.hadSuccessfulPayment),
  };
}

function firstOpen(done) {
  return STEPS.find((st) => !done[st.id]) ?? null;
}

const ACCESS_TEXT = {
  trial_not_started: "provet startar när första telefonen kopplas",
  trial_ended: "provet är slut",
  company_suspended: "avstängt",
  past_due: "betalningen saknas",
  period_expired: "perioden har gått ut",
  canceled: "uppsagt",
  no_subscription: "inget abonnemang",
  company_inactive: "inget prov eller abonnemang än",
  unknown_company: "företaget saknas",
};

/** Status i ett ord, för listan och kundsidans rubrik. */
function customerStatus(c, { suspended, trial, subscriptionStatus, accessOk }) {
  if (suspended) return ["pill-danger", "Avstängd"];
  if (subscriptionStatus === "past_due") return ["pill-danger", "Obetald"];
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
  if (c.suspended) return null;
  if (c.subscriptionStatus === "past_due") return { why: "Betalningen har inte kommit in", step: "betalning", level: 3 };
  if (c.unpaidOrders) return { why: "Beställning väntar på betalning", step: "betalning", level: 2 };
  if (c.verificationStatus === "unverified") return { why: "Registrerade sig själv – kontrollera behörigheten", step: "foretag", level: 2 };
  if (c.trial?.status === "active" && days !== null && days <= 3) return { why: `Provet slutar om ${Math.max(days, 0)} dag(ar) – dags att sälja`, step: "betalning", level: 2 };
  if (c.trial && !c.phones && c.licenses) return { why: "Har bilar men ingen förare kopplad", step: "forare", level: 1 };
  if (c.trial && !c.licenses) return { why: "Har inga bilar än", step: "bilar", level: 1 };
  return null;
}

/* --- Hem ---------------------------------------------------------------- */

export function oversikt(d, list = { companies: [] }) {
  const subs = d.subscriptions ?? {};
  const todo = (list.companies ?? [])
    .map((c) => ({ c, a: attention(c) }))
    .filter((x) => x.a)
    .sort((x, y) => y.a.level - x.a.level);
  return `
    <div class="page-head">
      <div><h1>Hem</h1><p class="muted">Det här behöver göras. Tryck på en rad för att gå direkt till rätt steg.</p></div>
      <button class="btn btn-primary" data-action="goto" data-view="nykund">+ Ny kund</button>
    </div>

    <div class="card">
      <h2>Att göra <span class="muted">(${esc(todo.length)})</span></h2>
      ${todo.length ? `<ul class="todo">${todo.map(({ c, a }) => `
        <li><button class="todo-row" data-action="open-company" data-id="${esc(c.id)}" data-tab="${esc(a.step)}">
          <span class="todo-dot lvl-${a.level}" aria-hidden="true"></span>
          <span class="todo-main"><b>${esc(c.name)}</b><span class="muted">${esc(a.why)}</span></span>
          <span class="todo-go">${esc(STEPS.find((st) => st.id === a.step)?.title ?? "")} →</span>
        </button></li>`).join("")}</ul>`
        : '<p class="muted">Inget att göra just nu. 🎉</p>'}
      ${d.reviewsOpen ? `<p><button class="btn btn-quiet" data-action="goto" data-view="granskning">
        ${esc(d.reviewsOpen)} riskgranskning(ar) väntar →</button></p>` : ""}
    </div>

    <div class="kpis">
      ${kpi("Kunder", esc(d.companies), { view: "kunder" })}
      ${kpi("Betalande", esc(subs.active ?? 0), { view: "kunder" })}
      ${kpi("Prov", esc(d.trialsActive), { view: "kunder" })}
      ${kpi("MRR exkl. moms", esc(money(d.mrrOre, d.currency)))}
      ${kpi("Förare i tjänst nu", esc(d.sessionsActive))}
    </div>
  `;
}

/* --- Kunder ------------------------------------------------------------- */

const FILTERS = [
  ["alla", "Alla"],
  ["atgard", "Behöver åtgärd"],
  ["prov", "Prov"],
  ["betalande", "Betalande"],
  ["avstangda", "Avstängda"],
];

function matchesFilter(c, filter) {
  switch (filter) {
    case "atgard": return !!attention(c);
    case "prov": return !!c.trial;
    case "betalande": return ["active", "past_due"].includes(c.subscriptionStatus);
    case "avstangda": return !!c.suspended;
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
        aria-selected="${id === filter}">${esc(label)} <span class="muted">${esc(all.filter((c) => matchesFilter(c, id)).length)}</span></button>`).join("")}
    </div>
    <div class="card list-card">
      ${rows.length ? rows.map((c) => {
        const done = doneFromRow(c);
        const next = firstOpen(done);
        const a = attention(c);
        return `
        <button class="cust-row" data-action="open-company" data-id="${esc(c.id)}" data-tab="${esc(a?.step ?? next?.id ?? "foretag")}">
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

/* --- En kund ------------------------------------------------------------ */

export function kund(d, config = null, tab = "", pending = null) {
  const c = d.company;
  const done = doneFromDetail(d);
  const next = firstOpen(done);
  const active = STEPS.some((st) => st.id === tab) || tab === "mer" ? tab : (next?.id ?? "betalning");
  const idx = STEPS.findIndex((st) => st.id === active);
  let after = idx >= 0 ? STEPS.slice(idx + 1).find((st) => !done[st.id]) ?? STEPS[idx + 1] : null;
  // Förare utan bil går inte: då är nästa steg Bilar, inte framåt.
  if (active === "forare" && !done.bilar) after = STEPS[1];
  const status = customerStatus(c, {
    suspended: !!d.suspension, trial: d.trial, subscriptionStatus: d.subscription?.status,
    accessOk: d.access?.ok,
  });
  const panel = {
    foretag: () => stepForetag(d, config),
    bilar: () => stepBilar(d, config, pending),
    forare: () => stepForare(d),
    konto: () => stepKonto(d, config),
    betalning: () => stepBetalning(d, config),
    mer: () => stepMer(d, config),
  }[active]();

  return `
    <button class="back-link" data-action="back">← Alla kunder</button>
    <div class="page-head">
      <div><h1>${esc(c.name)} ${statusPill(status)}</h1>
        <p class="muted"><span class="mono">${esc(c.orgNumber || "—")}</span>${d.access?.ok
          ? (d.access.validUntil ? ` · tips på till ${esc(date(d.access.validUntil))}` : " · tips på")
          : ` · inga tips: ${esc(ACCESS_TEXT[d.access?.reason] ?? d.access?.reason ?? "")}`}</p></div>
      ${next && next.id !== active ? `<button class="btn btn-primary" data-action="kund-tab" data-tab="${esc(next.id)}">
        Nästa steg: ${esc(next.todo)} →</button>` : ""}
    </div>

    ${d.suspension ? `
      <div class="suspended-banner" role="alert">
        <b>Företaget är avstängt.</b> ${esc(d.suspension.reason)}
        ${config?.canManage ? `<button class="btn btn-quiet" data-action="block-lift" data-block="${esc(d.suspension.id)}">Häv avstängningen</button>` : ""}
      </div>` : ""}

    <nav class="steps" aria-label="Kundens steg">
      ${STEPS.map((st, i) => `
        <button class="step ${done[st.id] ? "done" : ""} ${st.id === active ? "current" : ""}"
          data-action="kund-tab" data-tab="${st.id}" aria-current="${st.id === active ? "step" : "false"}">
          <span class="step-num">${done[st.id] ? "✓" : i + 1}</span>
          <span class="step-title">${esc(st.title)}</span>
        </button>`).join("")}
      <button class="step step-more ${active === "mer" ? "current" : ""}" data-action="kund-tab" data-tab="mer">Mer</button>
    </nav>

    <section class="step-panel">
      ${panel}
      ${after ? `<div class="step-next"><button class="btn btn-quiet" data-action="kund-tab" data-tab="${esc(after.id)}">
        Nästa: ${esc(after.title)} →</button></div>` : ""}
    </section>
  `;
}

function stepForetag(d, config) {
  const p = d.profile ?? {};
  return `
    ${verificationCard(d, config)}
    <div class="card">
      <h2>Företaget</h2>
      <dl class="kv">
        <dt>Kontakt</dt><dd>${esc(p.contactName || "—")} ${p.contactRole ? `<span class="muted">(${esc(p.contactRole)})</span>` : ""}</dd>
        <dt>E-post</dt><dd>${esc(p.contactEmail || "—")}</dd>
        <dt>Telefon</dt><dd>${esc(p.contactPhone || "—")}</dd>
        <dt>Behörighet</dt><dd>${p.verificationStatus ? verificationPill(p.verificationStatus) : "—"}</dd>
      </dl>
    </div>
    ${config?.canSell ? `<details class="card"><summary><h2 style="display:inline">Ändra uppgifter</h2></summary>${profileBlock(d)}</details>` : ""}
  `;
}

function stepBilar(d, config, pending) {
  return `${carsCard(d, config, pending)}${addCarsBlock(d, config)}`;
}

function stepForare(d) {
  const open = (d.licenses ?? []).filter((l) => LICENSE_OPEN.includes(l.status));
  if (!open.length) {
    return `<div class="card"><h2>Förare</h2><p class="muted">Lägg till en bil först.</p>
      <button class="btn btn-primary" data-action="kund-tab" data-tab="bilar">Till Bilar →</button></div>`;
  }
  return `
    <div class="card">
      <h2>Förare</h2>
      <p class="muted">Ge föraren en kod. Föraren öppnar appen, trycker <b>Jag är förare</b> och skriver in koden.
        Koden gäller i 5 minuter.</p>
      ${open.map((l) => {
        const phones = (l.approvals ?? []).filter((a) => a.status === "active");
        return `
        <div class="car">
          <div class="car-head"><b class="plate">${esc(l.vehicle || "—")}</b>
            <span class="muted">${l.activePhone ? `kör nu: ${esc(l.activePhone.label)}` : "ingen kör just nu"}</span></div>
          ${phones.map((a) => `
            <div class="driver-row"><span>📱 ${esc(a.label || "Telefon")} <span class="muted">· ${esc(date(a.approvedAt))}</span></span>
              <button class="btn btn-quiet btn-small" data-action="block" data-approval="${esc(a.id)}">Spärra</button></div>`).join("")}
          <button class="btn btn-primary btn-small" data-action="code" data-license="${esc(l.id)}"
            data-plate="${esc(l.vehicle)}">+ Förare (ge kod)</button>
        </div>`;
      }).join("")}
    </div>`;
}

function stepKonto(d, config) {
  return `${ownerBlock(d)}${membersCard(d, config)}`;
}

function stepBetalning(d, config) {
  const s = d.subscription;
  const t = d.trial;
  return `
    <div class="card">
      <h2>Betalning</h2>
      <dl class="kv">
        <dt>Läge</dt><dd>${s ? pill(s.status) : "—"}
          ${t && ["pending", "active"].includes(t.status) ? `<span class="pill pill-warn">Prov ${t.startedAt ? `till ${esc(date(t.endsAt))}` : "startar vid första telefonen"}</span>` : ""}</dd>
        ${s?.periodEnd ? `<dt>Betalt till</dt><dd>${esc(date(s.periodEnd))}</dd>` : ""}
        ${s?.monthlyOre ? `<dt>Per månad</dt><dd>${esc(money(s.monthlyOre))} exkl. moms</dd>` : ""}
      </dl>
      <p class="muted">Ny beställning (fler bilar eller län) görs under <button class="linklike" data-action="kund-tab" data-tab="bilar">Bilar</button>.</p>
    </div>
    ${ordersCard(d.orders, config)}
    ${redemptionsCard(d.couponRedemptions)}
    ${cancelBlock(d, config)}
  `;
}

function stepMer(d, config) {
  return `
    ${config?.canManage ? `
    <div class="card">
      <h2>Supportåtgärder</h2>
      <p class="muted">Ändrar appens rättigheter, inte Stripe. Loggas.</p>
      <div class="btn-row">
        <button class="btn btn-quiet" data-action="extend" data-days="7">+7 dagar</button>
        <button class="btn btn-quiet" data-action="extend" data-days="30">+30 dagar</button>
        <button class="btn btn-quiet" data-action="test-push">Skicka testnotis</button>
      </div>
    </div>` : ""}
    <div class="card">
      <h2>Telefoner</h2>
      <table><thead><tr><th>Telefon</th><th>Notiser</th><th>Senast sedd</th></tr></thead>
      <tbody>${(d.devices ?? []).map((dv) => `
        <tr><td data-label="Telefon">${esc(dv.label)}</td>
          <td data-label="Notiser">${dv.hasPush ? '<span class="ok">Ja</span>' : '<span class="muted">Nej</span>'}</td>
          <td data-label="Senast sedd">${esc(dateTime(dv.lastSeenAt))}</td></tr>`).join("")}</tbody></table>
    </div>
    ${dangerZone(d, config)}
    ${config?.canManage && !["canceled"].includes(d.subscription?.status) ? `
    <div class="card danger-zone">
      <h2>Avsluta direkt</h2>
      <p class="muted">Åtkomsten upphör nu, alla bilar och förarpass avslutas och Stripe slutar debitera.
        Ingen återbetalning görs automatiskt.</p>
      <div class="btn-row"><button class="btn btn-danger" data-action="terminate-now">Avsluta direkt</button></div>
    </div>` : ""}
    <details class="card"><summary><h2 style="display:inline">Händelselogg</h2></summary>
      <table><thead><tr><th>När</th><th>Vad</th><th>Av</th></tr></thead>
      <tbody>${(d.audit ?? []).map((e) => `
        <tr><td data-label="När">${esc(dateTime(e.at))}</td>
          <td data-label="Vad"><span class="mono">${esc(e.action)}</span>
            <div class="audit-detail">${esc(JSON.stringify(e.detail))}</div></td>
          <td data-label="Av">${esc(e.actorKind)}</td></tr>`).join("")}</tbody></table>
    </details>
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

function membersCard(d, config) {
  const members = d.members ?? [];
  const manage = !!config?.canManage;
  const ROLE = { company_owner: "Ägare", company_admin: "Administratör" };
  return `
    <div class="card">
      <h2>Inloggade konton</h2>
      <p class="muted">Ägare och administratörer som loggar in i kundportalen eller appens adminläge.
        Förarnas telefoner syns under Licenser och bilar.</p>
      ${members.length ? `<div class="table-scroll"><table>
        <thead><tr><th>Konto</th><th>Roll</th><th>Status</th><th></th></tr></thead>
        <tbody>${members.map((m) => `
          <tr>
            <td data-label="Konto">${m.email ? esc(m.email) : '<span class="muted">E-post okänd (inte inloggad sedan katalogen infördes)</span>'}
              <div class="muted mono">${esc(m.userId)}</div></td>
            <td data-label="Roll">${esc(ROLE[m.role] ?? m.role)}</td>
            <td data-label="Status">${m.blocked
              ? `<span class="pill pill-danger">Spärrad</span><div class="muted">${esc(m.blocked.reason)}</div>`
              : m.status === "active" ? '<span class="pill pill-ok">Aktiv</span>' : '<span class="pill">Avstängd</span>'}</td>
            <td data-label="">${manage ? `<div class="btn-row">
              ${m.status === "active"
                ? `<button class="btn btn-quiet" data-action="member-status" data-user="${esc(m.userId)}" data-status="disabled">Stäng av här</button>`
                : `<button class="btn btn-quiet" data-action="member-status" data-user="${esc(m.userId)}" data-status="active">Aktivera</button>`}
              ${m.blocked ? "" : `<button class="btn btn-danger" data-action="block-user" data-user="${esc(m.userId)}"
                data-email="${esc(m.email)}">Spärra kontot</button>`}
            </div>` : ""}</td>
          </tr>`).join("")}</tbody></table></div>`
        : '<p class="muted">Inga inloggade konton än. Bjud in kundens administratör ovan.</p>'}
    </div>`;
}

const LICENSE_OPEN = ["active", "trial", "pending_cancel"];

/**
 * Bilarna, en kort per bil: regnr, län som chips och vad man kan göra.
 *
 * Provbilar kostar inget och ändras direkt. En betald bils ändring visas
 * först som en offert i kortet -- beloppet räknas av serverns prismotor
 * (fleet/pricing.py), aldrig här -- och verkställs när säljaren bekräftat att
 * kunden godkänt. Samma regel som i fleet/admin_vehicles.py.
 */
function carsCard(d, config, pending = null) {
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
      <h2>Bilar <span class="muted">(${esc(open.length)})</span></h2>
      <p class="muted">Varje bil har ett <b>baslän</b> som ingår i priset. <b>Extra län</b> kostar
        ${esc(extraPrice)} per bil och månad exkl. moms (gratis under provet).</p>
      ${open.length ? open.map((l) => {
        const trial = l.status === "trial";
        const extras = l.extraCounties ?? [];
        const free = counties.filter((c) => !(l.counties ?? []).includes(c.code) && c.code !== l.baseCounty);
        const mine = pending?.licenseId === l.id ? pending : null;
        const data = `data-license="${esc(l.id)}" data-base="${esc(l.baseCounty)}" data-extras="${esc(extras.join(","))}" data-plate="${esc(l.vehicle)}" data-trial="${trial ? "1" : ""}"`;
        return `
        <div class="car ${mine ? "car-pending" : ""}">
          <div class="car-head">
            <b class="plate">${esc(l.vehicle || "—")}</b> ${pill(l.status)}
            ${l.assignmentKind === "temporary" ? '<span class="pill pill-warn">Ersättningsbil</span>' : ""}
            ${sell ? `<span class="car-tools">
              <button class="btn btn-quiet btn-small" data-action="car-plate-ask" ${data}>Byt regnr</button>
              ${l.status !== "pending_cancel" ? `<button class="btn btn-danger btn-small" data-action="car-remove" ${data}>Ta bort bil</button>` : ""}
            </span>` : ""}
          </div>

          <div class="county-chips" aria-label="Län för ${esc(l.vehicle)}">
            <span class="county-chip base" title="Ingår i bilens pris">${esc(name(l.baseCounty))} <small>baslän</small></span>
            ${extras.map((c) => `<span class="county-chip">${esc(name(c))}
              ${sell ? `<button class="chip-x" data-action="county-remove" data-county="${esc(c)}" ${data}
                aria-label="Ta bort ${esc(name(c))}" title="Ta bort ${esc(name(c))}">✕</button>` : ""}</span>`).join("")}
            ${l.scheduledBaseCounty ? `<span class="muted">baslän byts till ${esc(name(l.scheduledBaseCounty))} vid förnyelse</span>` : ""}
          </div>

          ${sell && l.status !== "pending_cancel" ? `
          <div class="county-add">
            <select data-add-county="${esc(l.id)}" aria-label="Välj län att lägga till">
              <option value="">+ Lägg till län …</option>
              ${free.map((c) => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("")}
            </select>
            <button class="btn btn-quiet btn-small" data-action="county-add" ${data}>Lägg till</button>
            <span class="muted">${trial ? "gratis under provet" : `+${esc(extraPrice)}/mån`}</span>
            <select data-base-for="${esc(l.id)}" aria-label="Byt baslän">
              <option value="">Byt baslän …</option>
              ${counties.filter((c) => c.code !== l.baseCounty).map((c) => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("")}
            </select>
            <button class="btn btn-quiet btn-small" data-action="base-change" ${data}>Byt</button>
          </div>` : ""}

          ${l.status === "pending_cancel" ? `<p class="muted">Bilen avslutas vid nästa förnyelse${l.endsAt ? ` (${esc(date(l.endsAt))})` : ""}.</p>` : ""}

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
      }).join("") : '<p class="muted">Inga bilar än. Lägg till nedan.</p>'}
      ${closed ? `<p class="muted">${esc(closed)} borttagen/borttagna bil(ar) visas inte.</p>` : ""}
    </div>`;
}

function dangerZone(d, config) {
  if (!config?.canManage || d.suspension) return "";
  return `
    <div class="card danger-zone">
      <h2>Stäng av företaget</h2>
      <p class="muted">Alla förartelefoner och inloggningar slutar få data direkt. Inget raderas:
        bilar, licenser, abonnemang och historik ligger kvar, och när avstängningen hävs fungerar
        allt som förut. Stripe påverkas inte — säg upp abonnemanget ovan om debiteringen också ska sluta.</p>
      <div class="btn-row"><button class="btn btn-danger" data-action="suspend">Stäng av företaget</button></div>
    </div>`;
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
