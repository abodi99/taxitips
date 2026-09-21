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

function stat(label, value) {
  return `<div class="stat"><span class="muted">${esc(label)}</span><b>${value}</b></div>`;
}

/* --- Översikt --------------------------------------------------------- */

export function oversikt(d) {
  const subs = d.subscriptions ?? {};
  const push = d.push24h ?? {};
  return `
    <div class="grid">
      ${stat("MRR (exkl. moms)", esc(money(d.mrrOre, d.currency)))}
      ${stat("Bolag", esc(d.companies))}
      ${stat("Aktiva abonnemang", esc(subs.active ?? 0))}
      ${stat("Aktiva prov", esc(d.trialsActive))}
    </div>
    <div class="grid" style="margin-top:1rem">
      ${stat("Aktiva licenser", esc(d.licensesActive))}
      ${stat("Telefoner", esc(d.devices))}
      ${stat("I tjänst just nu", esc(d.sessionsActive))}
      ${stat("Öppna granskningar", esc(d.reviewsOpen))}
    </div>
    <div class="card" style="margin-top:1rem">
      <h2>Behöver uppmärksamhet</h2>
      <ul>
        <li>Förfallna abonnemang: <b>${esc(subs.past_due ?? 0)}</b>
          (varav i betalningsfrist: ${esc(d.graceOpen)})</li>
        <li>Öppna riskgranskningar: <b>${esc(d.reviewsOpen)}</b></li>
        <li>Utskick som väntar i utkorgen: <b>${esc(d.outboxPending)}</b></li>
      </ul>
    </div>
    <div class="card">
      <h2>Notiser senaste dygnet</h2>
      <p>${Object.keys(push).length
        ? Object.entries(push).map(([s, n]) => `${pill(s)} ${esc(n)}`).join(" &nbsp; ")
        : '<span class="muted">Inga notiser senaste dygnet.</span>'}</p>
    </div>
    <p class="muted">Uppdaterad ${esc(dateTime(d.generatedAt))}.</p>
  `;
}

/* --- Kunder ----------------------------------------------------------- */

export function kunder(list, query = "") {
  const rows = list.companies ?? [];
  return `
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
            <td data-label="Åtkomst">${c.accessOk
              ? '<span class="ok">Ja</span>'
              : `<span class="error">Nej</span>`}<br /><span class="muted mono">${esc(c.accessReason)}</span></td>
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
    <h1>${esc(c.name)}</h1>
    <p class="muted mono">${esc(c.id)}</p>

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

    ${ordersCard(d.orders, config)}
    ${redemptionsCard(d.couponRedemptions)}

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

export function evenemang(list, q = "", hidden = false) {
  const rows = list.events ?? [];
  return `
    <form class="toolbar" id="eventForm">
      <input id="eq" name="q" value="${esc(q)}" placeholder="Namn, arena eller stad" />
      <label><input type="checkbox" id="ehidden" ${hidden ? "checked" : ""} style="width:auto" /> Bara dolda</label>
      <button class="btn btn-primary" type="submit">Sök</button>
    </form>
    <p class="muted">Kommande 14 dagar. Ett dolt evenemang syns inte för förarna.</p>
    <div class="card"><table>
      <thead><tr><th>Datum</th><th>Evenemang</th><th>Plats</th><th>Besökare</th><th></th></tr></thead>
      <tbody>${rows.map((e) => `
        <tr><td data-label="Datum">${esc(date(e.startDate))}${e.startAt ? `<div class="muted">${esc(new Date(e.startAt).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" }))}</div>` : ""}</td>
          <td data-label="Evenemang"><b>${esc(e.name)}</b><div class="muted">${esc(e.category)} · ${esc(e.source)}</div>
            ${e.hidden ? `<div class="error">Dold: ${esc(e.hiddenReason)}</div>` : ""}</td>
          <td data-label="Plats">${esc(e.venue)}<div class="muted">${esc(e.city)}</div></td>
          <td data-label="Besökare">${e.attendance ? esc(e.attendance.toLocaleString("sv-SE")) : "—"}</td>
          <td data-label="">${e.hidden
            ? `<button class="btn btn-quiet" data-action="event-show" data-event="${esc(e.id)}">Visa</button>`
            : `<button class="btn btn-danger" data-action="event-hide" data-event="${esc(e.id)}">Dölj</button>`}</td>
        </tr>`).join("")}</tbody>
    </table>
    ${rows.length ? "" : '<p class="muted">Inga evenemang.</p>'}</div>
  `;
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
