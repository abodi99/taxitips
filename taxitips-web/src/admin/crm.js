import { dateTime } from "../portal/api.js";

/** Separat CRM-modul — pipeline (deals) och valfri länk från kundkort. */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    10:  );

const STAGE_LABEL = {
  new: "Ny",
  screening: "Kvalificering",
  meeting: "Möte",
  proposal: "Offert",
  won: "Vunnen",
  lost: "Förlorad",
  churned: "Churnad",
};

const OPEN = ["new", "screening", "meeting", "proposal"];
const CLOSED = ["won", "lost", "churned"];

function stageLabel(stage) {
  return STAGE_LABEL[String(stage || "")] || stage || "—";
}

/** Valfri länk på kundsidan — ingen required CRM-widget. */
export function crmNotesCard(crm, config) {
  if (!crm) return "";
  const deal = crm.deal;
  if (!deal && !(crm.notes ?? []).length) {
    return `
      <div class="card muted-card" id="crmNotes">
        <p class="muted">Ingen CRM-affär kopplad. Öppna <button type="button" class="linklike" data-action="goto" data-view="pipeline">CRM</button> för att skapa eller länka.</p>
      </div>`;
  }
  const notes = crm.notes ?? [];
  const stageLine = deal?.stage
    ? `<p class="muted small">CRM: <strong>${esc(stageLabel(deal.stage))}</strong>
       ${deal.id ? ` · <button type="button" class="linklike" data-action="crm-open-deal" data-deal="${esc(deal.id)}">Öppna i CRM</button>` : ""}</p>`
    : "";
  const list = notes.length
    ? notes.slice(0, 5).map((n) => `
      <article class="crm-note">
        <h3>${esc(n.title)}</h3>
        <p class="crm-note-body">${esc(n.body).replace(/\n/g, "<br>")}</p>
        <p class="muted small">${esc(n.authorLabel || "")}${n.createdAt ? ` · ${esc(dateTime(n.createdAt))}` : ""}</p>
      </article>`).join("")
    : `<p class="muted">Inga anteckningar.</p>`;
  const form = config?.canSell ? `
    <form id="crmNoteForm" class="crm-note-form">
      <label for="crmNoteTitle">Rubrik</label>
      <input id="crmNoteTitle" name="title" maxlength="200" placeholder="Samtal, uppföljning …" />
      <label for="crmNoteBody">Anteckning</label>
      <textarea id="crmNoteBody" name="body" rows="3" required placeholder="Vad sa kunden?"></textarea>
      <button class="btn btn-primary btn-small" type="submit">Spara anteckning</button>
    </form>` : "";
  return `
    <div class="card" id="crmNotes">
      <div class="card-head"><h2>CRM</h2></div>
      ${stageLine}
      ${list}
      ${form}
    </div>`;
}

/** Kanban + lista. `data` från pipeline?board=1 eller vanlig lista. */
export function pipelineView(data, config, filterStage = "", dealDetail = null) {
  if (dealDetail?.deal) {
    return dealDetailView(dealDetail, config);
  }
  const stages = data.stages ?? [];
  const board = Array.isArray(data.columns) && data.columns.length;
  const newLead = config?.canSell
    ? `<button type="button" class="btn btn-primary btn-small" data-action="pipeline-new-lead">Ny affär</button>`
    : "";
  const filters = `
    <div class="btn-row pipeline-filters" role="tablist">
      <button type="button" class="btn btn-quiet btn-small${filterStage === "" && !board ? " btn-active" : ""}"
        data-action="pipeline-filter" data-stage="">Lista (öppna)</button>
      <button type="button" class="btn btn-quiet btn-small${filterStage === "__board__" ? " btn-active" : ""}"
        data-action="pipeline-filter" data-stage="__board__">Kanban</button>
      ${stages.filter((s) => OPEN.includes(s.id)).map((s) => `
        <button type="button" class="btn btn-quiet btn-small${filterStage === s.id ? " btn-active" : ""}"
          data-action="pipeline-filter" data-stage="${esc(s.id)}">${esc(s.label)}</button>`).join("")}
    </div>`;

  let body;
  if (board || filterStage === "__board__") {
    const cols = data.columns ?? [];
    body = `<div class="crm-board">${cols.map(boardColumn).join("")}</div>`;
  } else {
    const rows = data.rows ?? [];
    body = rows.length
      ? `<div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th>Steg</th><th>Affär</th><th>Kontakt</th><th>Bolag</th><th>Källa</th><th>Koppling</th><th></th>
          </tr></thead>
          <tbody>${rows.map((r) => pipelineRow(r, config)).join("")}</tbody>
        </table>
      </div>`
      : `<p class="muted">Inga affärer i filtret. Webleads från taxitips.se skapar en affär i steget Ny.</p>`;
  }

  return `
    <div class="page-head">
      <h1>CRM</h1>
      <p class="muted">Säljpipeline — separat från kunder, prov och Stripe. Koppla manuellt med «Gör till kund».</p>
      <div class="btn-row">${newLead}</div>
    </div>
    ${filters}
    ${body}`;
}

function boardColumn(col) {
  const rows = col.rows ?? [];
  return `
    <section class="crm-board-col" data-stage="${esc(col.id)}">
      <header><h2>${esc(col.label)}</h2><span class="muted">${rows.length}</span></header>
      <div class="crm-board-cards">
        ${rows.map((r) => boardCard(r)).join("") || `<p class="muted small">Tom</p>`}
      </div>
    </section>`;
}

function boardCard(r) {
  const contact = r.person?.name || r.person?.email || "";
  const company = r.account?.name || "";
  return `
    <button type="button" class="crm-board-card" data-action="crm-open-deal" data-deal="${esc(r.id)}">
      <strong>${esc(r.name || company || "Affär")}</strong>
      ${company ? `<span>${esc(company)}</span>` : ""}
      ${contact ? `<span class="muted">${esc(contact)}</span>` : ""}
    </button>`;
}

function pipelineRow(r, config) {
  const contact = [r.person?.name, r.person?.email].filter(Boolean).join(" · ") || "—";
  const company = r.account?.name || "—";
  const linked = r.companyId
    ? `<button class="linklike" data-action="open-company" data-id="${esc(r.companyId)}">Öppna kund</button>`
    : `<span class="muted">Ej kopplad</span>`;
  let actions = `<button class="btn btn-quiet btn-small" data-action="crm-open-deal" data-deal="${esc(r.id)}">Öppna</button>`;
  if (config?.canSell) {
    if (r.companyId) {
      actions += `<button class="btn btn-quiet btn-small" data-action="open-company" data-id="${esc(r.companyId)}" data-tab="betalning">Betalning</button>`;
    } else {
      actions += `<button class="btn btn-primary btn-small" data-action="pipeline-new-customer"
        data-deal="${esc(r.id)}"
        data-name="${esc(r.person?.name || "")}"
        data-email="${esc(r.person?.email || "")}"
        data-company="${esc(r.account?.name || "")}"
        data-org="${esc(r.account?.orgNumber || "")}">Gör till kund</button>`;
    }
    if (OPEN.includes(r.stage)) {
      actions += `<button class="btn btn-quiet btn-small" data-action="pipeline-stage"
        data-deal="${esc(r.id)}" data-stage="screening">Kvalificera</button>`;
    }
  }
  return `<tr>
    <td>${esc(stageLabel(r.stage))}</td>
    <td>${esc(r.name || "—")}</td>
    <td>${esc(contact)}</td>
    <td>${esc(company)}</td>
    <td class="muted">${esc(r.source || "—")}</td>
    <td>${linked}</td>
    <td class="btn-row">${actions}</td>
  </tr>`;
}

export function dealDetailView(data, config) {
  const d = data.deal;
  const notes = data.notes ?? [];
  const person = d.person || {};
  const account = d.account || {};
  const stageBtns = (config?.canSell ? OPEN.concat(["won", "lost"]) : [])
    .map((s) => `
      <button type="button" class="btn btn-quiet btn-small${d.stage === s ? " btn-active" : ""}"
        data-action="pipeline-stage" data-deal="${esc(d.id)}" data-stage="${esc(s)}">${esc(stageLabel(s))}</button>`)
    .join("");
  const linkActions = config?.canSell
    ? (d.companyId
      ? `<button class="btn btn-primary btn-small" data-action="open-company" data-id="${esc(d.companyId)}">Öppna TaxiTips-kund</button>`
      : `<button class="btn btn-primary btn-small" data-action="pipeline-new-customer"
          data-deal="${esc(d.id)}"
          data-name="${esc(person.name || "")}"
          data-email="${esc(person.email || "")}"
          data-company="${esc(account.name || "")}"
          data-org="${esc(account.orgNumber || "")}">Skapa TaxiTips-kund</button>`)
    : "";
  const noteForm = config?.canSell ? `
    <form id="crmDealNoteForm" class="crm-note-form" data-deal="${esc(d.id)}">
      <label>Ny anteckning</label>
      <input name="title" maxlength="200" placeholder="Rubrik" />
      <textarea name="body" rows="4" required placeholder="Anteckning …"></textarea>
      <button class="btn btn-primary btn-small" type="submit">Spara</button>
    </form>` : "";
  const noteList = notes.length
    ? notes.map((n) => `
      <article class="crm-note">
        <h3>${esc(n.title)}</h3>
        <p class="crm-note-body">${esc(n.body).replace(/\n/g, "<br>")}</p>
        <p class="muted small">${esc(n.authorLabel || "")}${n.createdAt ? ` · ${esc(dateTime(n.createdAt))}` : ""}</p>
      </article>`).join("")
    : `<p class="muted">Inga anteckningar.</p>`;

  return `
    <div class="page-head">
      <button type="button" class="btn btn-quiet btn-small" data-action="crm-back">← CRM</button>
      <h1>${esc(d.name || account.name || "Affär")}</h1>
      <p class="muted">${esc(stageLabel(d.stage))} · ${esc(d.source || "—")}</p>
      <div class="btn-row">${linkActions}</div>
    </div>
    <div class="crm-detail-grid">
      <div class="card">
        <h2>Kontakt</h2>
        <dl class="kv">
          <dt>Namn</dt><dd>${esc(person.name || "—")}</dd>
          <dt>E-post</dt><dd>${esc(person.email || "—")}</dd>
          <dt>Telefon</dt><dd>${esc(person.phone || "—")}</dd>
        </dl>
        <h2>Bolag</h2>
        <dl class="kv">
          <dt>Namn</dt><dd>${esc(account.name || "—")}</dd>
          <dt>Org.nr</dt><dd>${esc(account.orgNumber || "—")}</dd>
          <dt>Län</dt><dd>${esc(account.county || "—")}</dd>
        </dl>
        ${d.notesSummary ? `<p>${esc(d.notesSummary).replace(/\n/g, "<br>")}</p>` : ""}
        ${config?.canSell ? `<div class="btn-row" style="margin-top:1rem">${stageBtns}</div>` : ""}
      </div>
      <div class="card">
        <div class="card-head"><h2>Anteckningar</h2></div>
        ${noteList}
        ${noteForm}
      </div>
    </div>`;
}

export function pipelineNewLeadPrompt() {
  const contactName = prompt("Kontaktnamn:");
  if (contactName === null) return null;
  const contactEmail = prompt("E-post:");
  if (contactEmail === null) return null;
  const companyName = prompt("Bolagsnamn (valfritt):") ?? "";
  return {
    contactName: contactName.trim(),
    contactEmail: contactEmail.trim(),
    companyName: companyName.trim(),
    source: "admin",
  };
}
