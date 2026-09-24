import { countyName, date, dateTime, money } from "../portal/api.js";
import { ordersCard, redemptionsCard, salesPanel } from "./sales.js";

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

export function oversikt(d) {
  const subs = d.subscriptions ?? {};
  const push = d.push24h ?? {};
  const pastDue = subs.past_due ?? 0;
  return `
    <div class="page-head">
      <div><h1>Översikt</h1><p class="muted">Uppdaterad ${esc(dateTime(d.generatedAt))}.</p></div>
      <button class="btn btn-primary" data-action="goto" data-view="nykund">+ Ny kund</button>
    </div>
    <div class="kpis">
      ${kpi("MRR (exkl. moms)", esc(money(d.mrrOre, d.currency)))}
      ${kpi("Bolag", esc(d.companies), { view: "kunder" })}
      ${kpi("Aktiva abonnemang", esc(subs.active ?? 0), { view: "abonnemang" })}
      ${kpi("Aktiva prov", esc(d.trialsActive), { view: "abonnemang" })}
      ${kpi("Aktiva licenser", esc(d.licensesActive))}
      ${kpi("I tjänst just nu", esc(d.sessionsActive))}
    </div>
    <div class="card">
      <h2>Behöver uppmärksamhet</h2>
      <div class="kpis" style="margin:0.5rem 0 0">
        ${kpi("Förfallna abonnemang", `${esc(pastDue)}<small class="muted"> (${esc(d.graceOpen)} i frist)</small>`,
          { alert: pastDue > 0, view: "abonnemang" })}
        ${kpi("Obekräftade företag", esc(d.unverifiedCompanies ?? 0),
          { alert: (d.unverifiedCompanies ?? 0) > 0, view: "kunder" })}
        ${kpi("Öppna granskningar", esc(d.reviewsOpen), { alert: d.reviewsOpen > 0, view: "granskning" })}
        ${kpi("Aktiva spärrar", esc(d.blocksActive ?? 0), { view: "konton" })}
        ${kpi("Väntar i utkorgen", esc(d.outboxPending))}
      </div>
    </div>
    <div class="card">
      <h2>Notiser senaste dygnet</h2>
      <p>${Object.keys(push).length
        ? Object.entries(push).map(([s, n]) => `${pill(s)} ${esc(n)}`).join(" &nbsp; ")
        : '<span class="muted">Inga notiser senaste dygnet.</span>'}</p>
    </div>
  `;
}

/* --- Kunder ----------------------------------------------------------- */

export function kunder(list, query = "") {
  const rows = list.companies ?? [];
  return `
    <div class="page-head">
      <h1>Kunder</h1>
      <button class="btn btn-primary" data-action="goto" data-view="nykund">+ Ny kund</button>
    </div>
    <form class="toolbar" id="searchForm">
      <label class="visually-hidden" for="q">Sök</label>
      <input id="q" name="q" value="${esc(query)}" placeholder="Namn, orgnr eller bolagskod" />
      <button class="btn btn-primary" type="submit">Sök</button>
    </form>
    ${list.truncated ? '<p class="muted">Visar de första 200. Sök för att smalna av.</p>' : ""}
    <div class="card">
      <table>
        <thead><tr>
          <th>Bolag</th><th>Abonnemang</th><th>Åtkomst</th>
          <th>Licenser</th><th>Telefoner</th><th>Period slut</th>
        </tr></thead>
        <tbody>${rows.map((c) => `
          <tr class="row-link" data-company="${esc(c.id)}">
            <td data-label="Bolag"><b>${esc(c.name)}</b><br />
              <span class="muted mono">${esc(c.orgNumber || "—")} · ${esc(c.joinCode)}</span></td>
            <td data-label="Abonnemang">${pill(c.subscriptionStatus)}
              ${c.cancelAtPeriodEnd ? '<br /><span class="pill pill-warn">Uppsagt</span>' : ""}</td>
            <td data-label="Åtkomst">${c.accessReason === "company_suspended"
              ? '<span class="pill pill-danger">Avstängt</span>'
              : c.accessOk ? '<span class="ok">Ja</span>' : '<span class="error">Nej</span>'}<br /><span class="muted mono">${esc(c.accessReason)}</span></td>
            <td data-label="Licenser">${esc(c.licenses)}</td>
            <td data-label="Telefoner">${esc(c.devices)}</td>
            <td data-label="Period slut">${esc(date(c.periodEnd))}</td>
          </tr>`).join("")}</tbody>
      </table>
      ${rows.length ? "" : '<p class="muted">Inga bolag hittades.</p>'}
    </div>
  `;
}

export function kund(d, config = null) {
  const c = d.company;
  const s = d.subscription;
  const access = d.access ?? {};
  return `
    <button class="back-link" data-action="back">← Alla kunder</button>
    <div class="page-head">
      <div><h1>${esc(c.name)}</h1>
        <p class="muted mono">${esc(c.orgNumber || "—")} · ${esc(c.id)}</p></div>
      ${d.profile ? verificationPill(d.profile.verificationStatus) : ""}
    </div>

    ${d.suspension ? `
      <div class="suspended-banner" role="alert">
        <b>Företaget är avstängt</b> sedan ${esc(dateTime(d.suspension.createdAt))}
        ${d.suspension.createdByEmail ? `av ${esc(d.suspension.createdByEmail)}` : ""}.
        Skäl: ${esc(d.suspension.reason)}. Inga telefoner eller inloggningar får data.
        ${config?.canManage ? `<div><button class="btn btn-quiet" data-action="block-lift"
          data-block="${esc(d.suspension.id)}">Häv avstängningen</button></div>` : ""}
      </div>` : ""}

    <div class="card">
      <h2>Kundens väg</h2>
      ${journey(d)}
    </div>

    ${verificationCard(d, config)}

    <div class="notice ${access.ok ? "" : "notice-danger"}">
      <b>Åtkomst: ${access.ok ? "Ja" : "Nej"}</b> — <span class="mono">${esc(access.reason)}</span>
      ${access.validUntil ? `, gäller till ${esc(dateTime(access.validUntil))}` : ""}
    </div>

    <div class="grid">
      <div class="card">
        <h2>Bolag</h2>
        <dl class="kv">
          <dt>Orgnr</dt><dd class="mono">${esc(c.orgNumber || "—")}</dd>
          <dt>Bolagskod</dt><dd class="mono">${esc(c.joinCode)}</dd>
          <dt>E-post</dt><dd>${esc(c.email || "—")}</dd>
          <dt>Gammal status</dt><dd class="mono">${esc(c.legacyStatus)} / ${esc(c.legacySubscriptionStatus)}</dd>
          <dt>Stripe-kund</dt><dd class="mono">${esc(c.stripeCustomerId || "—")}</dd>
          <dt>Skapad</dt><dd>${esc(date(c.createdAt))}</dd>
          ${d.profile ? `<dt>Verifiering</dt><dd>${esc(d.profile.verificationStatus)}</dd>` : ""}
          ${d.profile?.legacyAccessUntil ? `<dt>Övergång till</dt><dd>${esc(date(d.profile.legacyAccessUntil))}</dd>` : ""}
        </dl>
      </div>

      <div class="card">
        <h2>Abonnemang</h2>
        ${s ? `
          <dl class="kv">
            <dt>Status</dt><dd>${pill(s.status)}</dd>
            <dt>Period</dt><dd>${esc(date(s.periodStart))} – ${esc(date(s.periodEnd))}</dd>
            <dt>Månadsbelopp</dt><dd>${esc(money(s.monthlyOre))} exkl. moms</dd>
            <dt>Prisversion</dt><dd class="mono">${esc(s.priceVersion)}</dd>
            ${s.introEndsAt ? `<dt>Intro slutar</dt><dd>${esc(date(s.introEndsAt))}</dd>` : ""}
            ${s.graceUntil ? `<dt>Frist till</dt><dd>${esc(dateTime(s.graceUntil))}</dd>` : ""}
            ${s.cancelAtPeriodEnd ? `<dt>Uppsagt</dt><dd>till ${esc(date(s.accessUntil))}</dd>` : ""}
            <dt>Stripe</dt><dd class="mono">${esc(s.stripeSubscriptionId || "—")}</dd>
          </dl>` : '<p class="muted">Inget abonnemang i den nya modellen.</p>'}
        ${config?.canManage ? `
        <h3 style="margin-top:1rem">Supportåtgärd</h3>
        <p class="muted">Ändrar appens rättigheter, inte Stripe. Loggas.</p>
        <div class="btn-row">
          <button class="btn btn-quiet" data-action="extend" data-days="7">+7 dagar</button>
          <button class="btn btn-quiet" data-action="extend" data-days="30">+30 dagar</button>
          <button class="btn btn-quiet" data-action="test-push">Testnotis</button>
        </div>` : ""}
      </div>
    </div>

    ${d.trial ? `
      <div class="card">
        <h2>${d.trial.source === "coupon" ? "Tillfällig åtkomst" : "Prov"}</h2>
        <p>${pill(d.trial.status)} ${esc(TRIAL_SOURCE[d.trial.source] ?? d.trial.source)} ·
          ${d.trial.startedAt ? `${esc(dateTime(d.trial.startedAt))} – ${esc(dateTime(d.trial.endsAt))}` : "startar när första telefonen ansluts"}
          · ${esc(d.trial.vehicles ?? 0)} av högst ${esc(d.trial.vehicleLimit)} bilar</p>
      </div>` : ""}

    ${salesPanel(d, config)}

    <div class="card">
      <h2>Licenser och bilar</h2>
      ${d.licenses.length ? d.licenses.map((l) => `
        <div style="border-bottom:1px solid var(--line);padding:0.75rem 0">
          <b>${esc(l.vehicle || "—")}</b> ${pill(l.status)}
          ${l.assignmentKind === "temporary" ? '<span class="pill pill-warn">Ersättningsbil</span>' : ""}
          <div class="muted">Län: ${(l.counties ?? []).map((c) => esc(countyName(c))).join(", ") || "—"}
            ${l.scheduledBaseCounty ? ` · baslän byts till ${esc(countyName(l.scheduledBaseCounty))}` : ""}</div>
          <div>I tjänst: ${l.activePhone
            ? `${esc(l.activePhone.label)} sedan ${esc(dateTime(l.activePhone.since))}`
            : '<span class="muted">ingen</span>'}</div>
          ${(l.approvals ?? []).filter((a) => a.status === "active").map((a) => `
            <div class="btn-row">
              <span>${esc(a.label || "Telefon")} · godkänd ${esc(date(a.approvedAt))}</span>
              <button class="btn btn-danger" data-action="block" data-approval="${esc(a.id)}">Spärra</button>
            </div>`).join("")}
          ${["active", "trial", "pending_cancel"].includes(l.status) ? `<div class="btn-row">
            <button class="btn btn-primary" data-action="code" data-license="${esc(l.id)}"
              data-plate="${esc(l.vehicle)}">Lägg till förare</button>
            ${config?.canSell && l.status === "active" ? `
              <select data-county-for="${esc(l.id)}" aria-label="Län">${(config.counties ?? [])
                .filter((c) => !(l.counties ?? []).includes(c.code))
                .map((c) => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("")}</select>
              <button class="btn btn-quiet" data-action="lic-add-county" data-license="${esc(l.id)}">+ Län</button>
              <button class="btn btn-quiet" data-action="lic-cancel" data-license="${esc(l.id)}"
                data-plate="${esc(l.vehicle)}">Avsluta bilen vid förnyelse</button>` : ""}
          </div>` : ""}
        </div>`).join("") : '<p class="muted">Inga licenser.</p>'}
    </div>

    <div class="card">
      <h2>Telefoner</h2>
      <table><thead><tr><th>Telefon</th><th>Push</th><th>Körområde</th><th>Senast sedd</th></tr></thead>
      <tbody>${d.devices.map((dv) => `
        <tr>
          <td data-label="Telefon">${esc(dv.label)} <span class="muted mono">${esc(dv.kind)}</span></td>
          <td data-label="Push">${dv.hasPush ? '<span class="ok">Ja</span>' : '<span class="error">Nej</span>'}</td>
          <td data-label="Körområde">${(dv.counties ?? []).map((c) => esc(countyName(c))).join(", ") || "—"}</td>
          <td data-label="Senast sedd">${esc(dateTime(dv.lastSeenAt))}</td>
        </tr>`).join("")}</tbody></table>
    </div>

    ${membersCard(d, config)}
    ${ordersCard(d.orders, config)}
    ${redemptionsCard(d.couponRedemptions)}
    ${dangerZone(d, config)}

    <div class="card">
      <h2>Händelselogg</h2>
      <table><thead><tr><th>När</th><th>Vad</th><th>Av</th></tr></thead>
      <tbody>${d.audit.map((e) => `
        <tr><td data-label="När">${esc(dateTime(e.at))}</td>
          <td data-label="Vad"><span class="mono">${esc(e.action)}</span>
            <div class="audit-detail">${esc(JSON.stringify(e.detail))}</div></td>
          <td data-label="Av">${esc(e.actorKind)}</td></tr>`).join("")}</tbody></table>
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

/**
 * Kundens väg, steg för steg: det som gör en kund betalande och körande.
 * Räknas ur samma svar som resten av sidan -- inget eget tillstånd -- och
 * markerar första steget som inte är klart, så att säljaren ser vad som står
 * näst på tur.
 */
function journey(d) {
  const licenses = d.licenses ?? [];
  const members = (d.members ?? []).filter((m) => m.status === "active");
  const invites = (d.ownerInvites ?? []).filter((i) => i.status === "pending");
  const phones = licenses.some((l) => (l.approvals ?? []).some((a) => a.status === "active"));
  const s = d.subscription;
  const paid = s && ["active", "past_due"].includes(s.status) && s.hadSuccessfulPayment;
  const unpaid = (d.orders ?? []).some((o) => o.status === "pending_payment");
  const trialOn = d.trial && ["pending", "active"].includes(d.trial.status);
  const steps = [
    ["Företag", "Uppgifter och orgnr", !!d.profile, "Upplagt"],
    ["Behörighet", "Kontrollerad företrädare", d.profile?.verificationStatus === "verified", "Kontrollerad"],
    ["Bilar", `${licenses.length} bil(ar) med licens`, licenses.length > 0, `${licenses.length} bil(ar)`],
    ["Kundens admin", members.length ? "Loggar in i portalen" : invites.length ? "Inbjudan skickad" : "Ingen inbjuden",
      members.length > 0, "Inloggad"],
    ["Förare", "Telefon kopplad till bil", phones, "Kopplade"],
    ["Betalning", paid ? "Betalt" : unpaid ? "Väntar på betalning" : trialOn ? "Prov pågår" : "Ingen beställning",
      !!paid, "Betalar"],
  ];
  const next = steps.findIndex((step) => !step[2]);
  return `<ol class="journey">${steps.map(([title, hint, done, doneText], i) => `
    <li class="${done ? "done" : i === next ? "next" : ""}">
      <b>${i + 1}. ${esc(title)}</b>
      <span class="step-state">${done ? `✓ ${esc(doneText)}` : esc(hint)}</span>
    </li>`).join("")}</ol>`;
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

/* --- Abonnemang ------------------------------------------------------- */

export function abonnemang(list) {
  const rows = (list.companies ?? []).filter((c) => c.subscriptionStatus !== "none");
  const order = { past_due: 0, trialing: 1, active: 2, canceled: 3 };
  rows.sort((a, b) => (order[a.subscriptionStatus] ?? 9) - (order[b.subscriptionStatus] ?? 9));
  return `
    <p class="muted">Förfallna först. Klicka på ett bolag för detaljer och supportåtgärder.</p>
    <div class="card"><table>
      <thead><tr><th>Bolag</th><th>Status</th><th>Period slut</th><th>Licenser</th><th>Åtkomst</th></tr></thead>
      <tbody>${rows.map((c) => `
        <tr class="row-link" data-company="${esc(c.id)}">
          <td data-label="Bolag"><b>${esc(c.name)}</b></td>
          <td data-label="Status">${pill(c.subscriptionStatus)}
            ${c.cancelAtPeriodEnd ? '<span class="pill pill-warn">Uppsagt</span>' : ""}</td>
          <td data-label="Period slut">${esc(date(c.periodEnd))}</td>
          <td data-label="Licenser">${esc(c.licenses)}</td>
          <td data-label="Åtkomst">${c.accessOk ? '<span class="ok">Ja</span>' : '<span class="error">Nej</span>'}</td>
        </tr>`).join("")}</tbody>
    </table>
    ${rows.length ? "" : '<p class="muted">Inga abonnemang i den nya modellen än.</p>'}</div>
  `;
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
