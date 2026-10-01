import { dateTime } from "../portal/api.js";

/** Separat CRM-modul — tabell, sök och stegfilter. */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

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

const SEGMENTS = [
  { id: "segment:a", label: "Segment A", title: "A – Beställningscentral / stort" },
  { id: "segment:b", label: "Segment B", title: "B – Mellanstort (3–9 bilar)" },
  { id: "segment:c", label: "Segment C", title: "C – Litet (1–2 bilar)" },
  { id: "segment:d", label: "Segment D", title: "D – Storlek okänd" },
  { id: "segment:x", label: "Segment X", title: "X – Ring ej" },
];

/** Korta bolagsformer i tabellen. */
const FORM_SHORT = {
  Aktiebolag: "AB",
  "Enskild firma": "EF",
  Handelsbolag: "HB",
  Kommanditbolag: "KB",
  "Ekonomisk förening": "Ek. för.",
  "Ideell förening": "Ideell",
};

/** Sorterbara kolumner: nyckel → riktning vid första klick. */
const SORT_FIRST = { name: "asc", city: "asc", priority: "asc", stage: "asc", updated: "desc" };

/** Tomma filter — main.js håller samma form i state. */
export const EMPTY_PIPELINE_FILTERS = {
  segment: "",
  county: "",
  call: "",
  form: "",
  city: "",
  phone: false,
  email: false,
  tf: false,
};

export function pipelineTags(f) {
  return [f.segment, f.county, f.call, f.tf ? "medlem:taxiforbundet" : ""].filter(Boolean);
}

/** Nästa sortering när rubriken `key` klickas. */
export function nextSort(current, key) {
  const cur = current || "-updated";
  if (cur.replace(/^-/, "") === key) return cur.startsWith("-") ? key : `-${key}`;
  return SORT_FIRST[key] === "desc" ? `-${key}` : key;
}

const num = (n) => Number(n ?? 0).toLocaleString("sv-SE");

function shortDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const opts = { day: "numeric", month: "short" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString("sv-SE", opts);
}

function filterSelect(key, value, placeholder, options) {
  const opts = options.map((o) => `
    <option value="${esc(o.id)}"${value === o.id ? " selected" : ""}
      title="${esc(o.title || o.label)}">${esc(o.label)}</option>`).join("");
  return `
    <select class="crm-field${value ? " is-set" : ""}" data-crm-filter="${esc(key)}"
      aria-label="${esc(placeholder)}">
      <option value="">${esc(placeholder)}</option>${opts}
    </select>`;
}

function filterToggle(key, on, label, title) {
  return `
    <button type="button" class="crm-toggle${on ? " is-on" : ""}"
      data-action="pipeline-toggle" data-key="${esc(key)}"
      aria-pressed="${on ? "true" : "false"}" title="${esc(title)}">${label}</button>`;
}

function sortHeader(label, key, sort, extraClass = "") {
  const cur = sort || "-updated";
  const active = cur.replace(/^-/, "") === key;
  const desc = cur.startsWith("-");
  const aria = active ? (desc ? "descending" : "ascending") : "none";
  return `
    <th class="${extraClass}" aria-sort="${aria}">
      <button type="button" class="crm-sort${active ? " is-active" : ""}"
        data-action="pipeline-sort" data-sort="${esc(key)}">
        ${esc(label)}<span class="crm-sort-arrow" aria-hidden="true">${active ? (desc ? "↓" : "↑") : "↕"}</span>
      </button>
    </th>`;
}

function stageLabel(stage) {
  return STAGE_LABEL[String(stage || "")] || stage || "—";
}

/* ---- Uppgifter: gemensamma delar ------------------------------------- */

const TASK_STATUS = [
  { id: "todo", label: "Att göra" },
  { id: "doing", label: "Pågår" },
  { id: "done", label: "Klar" },
];

const BUCKETS = [
  { id: "overdue", label: "Försenade" },
  { id: "today", label: "Idag" },
  { id: "week", label: "Kommande 7 dagar" },
  { id: "later", label: "Senare" },
  { id: "nodate", label: "Utan datum" },
  { id: "done", label: "Klara" },
];

/** "2026-10-07" → lokalt datum utan tidszonsförskjutning. */
function localDate(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  return new Date(y, m - 1, d);
}

function dueLabel(t) {
  if (!t.dueDate) return "";
  if (t.status !== "done" && t.bucket === "today") return "Idag";
  const d = localDate(t.dueDate);
  const opts = { weekday: "short", day: "numeric", month: "short" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString("sv-SE", opts);
}

/** Kort namn på den ansvariga: "Jag" eller e-postens förled. */
function who(userId, label, me) {
  if (!userId) return "Ingen ansvarig";
  if (userId === me) return "Jag";
  return (label || "").split("@")[0] || "Okänd";
}

function staffSelect(name, staff, selected, me, { allowNone = true } = {}) {
  const opts = (staff ?? []).map((s) => `
    <option value="${esc(s.userId)}"${selected === s.userId ? " selected" : ""}>
      ${esc(s.userId === me ? (s.email ? `Jag (${s.email})` : "Jag") : s.email || s.userId)}</option>`).join("");
  return `
    <select name="${esc(name)}" aria-label="Ansvarig">
      ${allowNone ? `<option value=""${!selected ? " selected" : ""}>Ingen ansvarig</option>` : ""}
      ${opts}
    </select>`;
}

/** Formulär för ny uppgift. target: { dealId?, companyId? } */
export function taskNewForm(target, staff, me, placeholder = "Ny uppgift, t.ex. Ring och boka demo") {
  return `
    <form class="crm-task-new" data-crm-form="task-new"
      data-deal="${esc(target.dealId || "")}" data-customer="${esc(target.companyId || "")}">
      <input name="title" maxlength="200" required placeholder="${esc(placeholder)}" aria-label="Uppgift" />
      <input name="dueDate" type="date" aria-label="Senast" title="Senast" />
      ${staffSelect("assigneeUserId", staff, me, me)}
      <button class="btn btn-primary btn-small" type="submit">Lägg till</button>
    </form>`;
}

function taskRow(t, { staff, me, showDeal = false, canEdit = true }) {
  const done = t.status === "done";
  const due = dueLabel(t);
  const meta = [
    due ? `<span class="crm-due crm-due-${esc(t.bucket)}">${esc(t.bucket === "overdue" ? `Försenad · ${due}` : due)}</span>` : "",
    `<span title="${esc(t.assigneeLabel || "")}">${esc(who(t.assigneeUserId, t.assigneeLabel, me))}</span>`,
    showDeal && t.dealId
      ? `<button type="button" class="linklike" data-action="crm-open-deal" data-deal="${esc(t.dealId)}">${esc(t.dealName || "Affär")}</button>`
      : "",
    done && t.completedAt ? `<span>Klar ${esc(new Date(t.completedAt).toLocaleDateString("sv-SE", { day: "numeric", month: "short" }))}</span>` : "",
  ].filter(Boolean).join(`<span class="crm-dot" aria-hidden="true">·</span>`);

  const statusSelect = canEdit ? `
    <select class="crm-task-status crm-task-status-${esc(t.status)}" data-task-status="${esc(t.id)}" aria-label="Status">
      ${TASK_STATUS.map((s) => `<option value="${s.id}"${t.status === s.id ? " selected" : ""}>${s.label}</option>`).join("")}
    </select>` : `<span class="crm-task-status crm-task-status-${esc(t.status)}">${esc(TASK_STATUS.find((s) => s.id === t.status)?.label ?? t.status)}</span>`;

  const edit = canEdit ? `
    <details class="crm-more">
      <summary>Ändra</summary>
      <form class="crm-inline-form" data-crm-form="task-edit" data-task="${esc(t.id)}">
        <label>Uppgift<input name="title" maxlength="200" required value="${esc(t.title)}" /></label>
        <label>Detaljer<textarea name="body" rows="2">${esc(t.body)}</textarea></label>
        <div class="crm-form-row">
          <label>Senast<input name="dueDate" type="date" value="${esc(t.dueDate || "")}" /></label>
          <label>Ansvarig${staffSelect("assigneeUserId", staff, t.assigneeUserId, me)}</label>
        </div>
        <div class="crm-form-actions">
          <button class="btn btn-primary btn-small" type="submit">Spara</button>
          <button class="crm-danger-link" type="button" data-action="crm-task-delete" data-task="${esc(t.id)}">Ta bort</button>
        </div>
      </form>
    </details>` : "";

  return `
    <li class="crm-task${done ? " is-done" : ""}">
      ${canEdit
        ? `<button type="button" class="crm-task-check" data-action="crm-task-toggle"
            data-task="${esc(t.id)}" data-status="${done ? "todo" : "done"}"
            aria-label="${done ? "Markera som ej klar" : "Markera som klar"}" aria-pressed="${done}">✓</button>`
        : `<span class="crm-task-check" aria-hidden="true">${done ? "✓" : ""}</span>`}
      <div class="crm-task-main">
        <span class="crm-task-title">${esc(t.title)}</span>
        ${t.body ? `<span class="crm-task-body">${esc(t.body)}</span>` : ""}
        <span class="crm-task-meta">${meta}</span>
      </div>
      <div class="crm-task-side">${statusSelect}${edit}</div>
    </li>`;
}

export function taskList(tasks, opts) {
  if (!tasks?.length) return `<p class="muted crm-empty-inline">${esc(opts.empty || "Inga uppgifter.")}</p>`;
  return `<ul class="crm-tasks">${tasks.map((t) => taskRow(t, opts)).join("")}</ul>`;
}

/** Underflikar i CRM: pipeline och uppgifter. */
function crmSubnav(active) {
  const tab = (id, label) => `
    <button type="button" role="tab" class="crm-subtab" aria-selected="${active === id}"
      data-action="crm-tab" data-tab="${id}">${label}</button>`;
  return `<div class="crm-subnav" role="tablist" aria-label="CRM">${tab("pipeline", "Pipeline")}${tab("tasks", "Uppgifter")}</div>`;
}

/**
 * Uppgiftsöversikten. data = GET /crm/tasks; opts: { assignee, status }
 */
export function tasksView(data, config) {
  const me = data.me;
  const staff = data.staff ?? [];
  const s = data.summary ?? {};
  const assignee = data.assignee || "me";
  const status = data.status || "open";
  const rows = data.rows ?? [];
  const canEdit = !!config?.canSell;

  const whoOptions = [
    { id: "me", label: "Mina uppgifter" },
    { id: "all", label: "Alla säljare" },
    { id: "none", label: "Utan ansvarig" },
    ...staff.filter((p) => p.userId !== me).map((p) => ({ id: p.userId, label: p.email || p.userId })),
  ].map((o) => `<option value="${esc(o.id)}"${assignee === o.id ? " selected" : ""}>${esc(o.label)}</option>`).join("");

  const statusTabs = [
    { id: "open", label: "Öppna" },
    { id: "todo", label: "Att göra" },
    { id: "doing", label: "Pågår" },
    { id: "done", label: "Klara" },
  ].map((t) => `
    <button type="button" role="tab" class="crm-tab" aria-selected="${status === t.id}"
      data-action="crm-tasks-status" data-status="${t.id}">${t.label}</button>`).join("");

  const tile = (label, n, tone = "", hint = "") => `
    <div class="crm-tile${tone && n ? ` crm-tile-${tone}` : ""}">
      <span class="crm-tile-n">${num(n)}</span>
      <span class="crm-tile-label">${esc(label)}</span>
      ${hint ? `<span class="crm-tile-hint">${esc(hint)}</span>` : ""}
    </div>`;
  const tiles = `
    <div class="crm-tiles">
      ${tile("Försenade", s.overdue, "danger")}
      ${tile("Idag", s.today, "warn")}
      ${tile("Kommande 7 dagar", s.week)}
      ${tile("Utan datum", s.nodate)}
      ${tile("Pågår", s.doing)}
      ${tile("Klara", s.doneWeek, "ok", "senaste 7 dagarna")}
    </div>`;

  let list;
  if (status === "done") {
    list = taskList(rows, { staff, me, showDeal: true, canEdit, empty: "Inga klara uppgifter." });
  } else {
    const groups = BUCKETS.filter((b) => b.id !== "done")
      .map((b) => ({ ...b, rows: rows.filter((r) => r.bucket === b.id) }))
      .filter((g) => g.rows.length);
    list = groups.length
      ? groups.map((g) => `
          <section class="crm-task-group crm-task-group-${g.id}">
            <h3>${esc(g.label)} <span class="crm-tab-n">${num(g.rows.length)}</span></h3>
            ${taskList(g.rows, { staff, me, showDeal: true, canEdit })}
          </section>`).join("")
      : `<div class="crm-empty"><p>Inga öppna uppgifter${assignee === "me" ? " för dig" : ""}. 🎉</p></div>`;
  }

  const perSeller = (data.perSeller ?? []).map((p) => {
    const id = p.userId === me ? "me" : p.userId;
    const name = p.userId === "none" ? "Utan ansvarig" : p.userId === me ? "Jag" : (p.email || p.userId);
    const active = assignee === id;
    return `
      <tr class="row-link${active ? " is-active" : ""}" data-action="crm-tasks-assignee" data-assignee="${esc(id)}">
        <td>${esc(name)}</td>
        <td class="num">${num(p.open)}</td>
        <td class="num${p.overdue ? " crm-num-danger" : ""}">${num(p.overdue)}</td>
        <td class="num">${num(p.doing)}</td>
        <td class="num">${num(p.doneWeek)}</td>
      </tr>`;
  }).join("");

  return `
    <div class="page-head">
      <div>
        <h1>CRM</h1>
        ${crmSubnav("tasks")}
      </div>
    </div>
    <div class="crm-toolbar">
      <select class="crm-field crm-who${assignee !== "me" ? " is-set" : ""}" data-crm-tasks="assignee" aria-label="Vems uppgifter">${whoOptions}</select>
      <div class="crm-tabs" role="tablist" aria-label="Status">${statusTabs}</div>
    </div>
    ${tiles}
    <div class="crm-tasks-grid">
      <div class="card crm-tasks-card">
        ${canEdit ? taskNewForm({}, staff, me, "Ny uppgift utan kund, t.ex. Ring alla A-bolag i Skåne") : ""}
        ${list}
      </div>
      <aside class="card crm-seller-card">
        <h2>Per säljare</h2>
        <table class="crm-seller-table">
          <thead><tr><th>Säljare</th><th class="num">Öppna</th><th class="num" title="Försenade">Sena</th><th class="num">Pågår</th><th class="num" title="Klara senaste 7 dagarna">Klara</th></tr></thead>
          <tbody>${perSeller || `<tr><td colspan="5" class="muted">Ingen personal med säljroll.</td></tr>`}</tbody>
        </table>
        <p class="muted crm-table-note">Klara = senaste 7 dagarna. Klicka på en rad för att se säljarens lista.</p>
      </aside>
    </div>`;
}

function noteItem(n, canEdit) {
  const edited = n.editedAt
    ? ` · <span title="${esc(dateTime(n.editedAt))}">redigerad${n.editedByLabel ? ` av ${esc(n.editedByLabel.split("@")[0])}` : ""}</span>`
    : "";
  const form = canEdit ? `
    <details class="crm-more">
      <summary>Ändra</summary>
      <form class="crm-inline-form" data-crm-form="note-edit" data-note="${esc(n.id)}">
        <label>Rubrik<input name="title" maxlength="200" value="${esc(n.title)}" /></label>
        <label>Anteckning<textarea name="body" rows="5" required>${esc(n.body)}</textarea></label>
        <div class="crm-form-actions"><button class="btn btn-primary btn-small" type="submit">Spara ändringen</button></div>
      </form>
    </details>` : "";
  return `
    <article class="crm-note">
      <div class="crm-note-head">
        <h3>${esc(n.title)}</h3>
        ${form}
      </div>
      <p class="crm-note-body">${esc(n.body).replace(/\n/g, "<br>")}</p>
      <p class="muted small">${esc(n.authorLabel || "")}${n.createdAt ? ` · ${esc(dateTime(n.createdAt))}` : ""}${edited}</p>
    </article>`;
}

/** Valfri CRM-ruta på kundsidan: uppgifter och anteckningar. */
export function crmNotesCard(crm, config) {
  if (!crm) return "";
  const deal = crm.deal;
  const canSell = !!config?.canSell;
  const notes = crm.notes ?? [];
  const tasks = crm.tasks ?? [];
  const companyId = crm.companyId || "";
  const stageLine = deal?.stage
    ? `<p class="muted small">CRM: <strong>${esc(stageLabel(deal.stage))}</strong>
       ${deal.id ? ` · <button type="button" class="linklike" data-action="crm-open-deal" data-deal="${esc(deal.id)}">Öppna i CRM</button>` : ""}</p>`
    : `<p class="muted small">Ingen CRM-affär kopplad. Öppna <button type="button" class="linklike" data-action="goto" data-view="pipeline">CRM</button> för att skapa eller länka.</p>`;
  const noteForm = canSell ? `
    <details class="crm-more crm-add">
      <summary>+ Ny anteckning</summary>
      <form id="crmNoteForm" class="crm-note-form">
        <label for="crmNoteTitle">Rubrik</label>
        <input id="crmNoteTitle" name="title" maxlength="200" placeholder="Samtal, uppföljning …" />
        <label for="crmNoteBody">Anteckning</label>
        <textarea id="crmNoteBody" name="body" rows="3" required placeholder="Vad sa kunden?"></textarea>
        <button class="btn btn-primary btn-small" type="submit">Spara anteckning</button>
      </form>
    </details>` : "";
  return `
    <div class="card" id="crmNotes">
      <div class="card-head"><h2>CRM</h2></div>
      ${stageLine}
      <h3 class="crm-card-sub">Uppgifter</h3>
      ${canSell && companyId ? taskNewForm({ companyId, dealId: deal?.id }, crm.staff ?? [], crm.me) : ""}
      ${taskList(tasks, { staff: crm.staff ?? [], me: crm.me, canEdit: canSell, empty: "Inga uppgifter för kunden." })}
      <h3 class="crm-card-sub">Anteckningar</h3>
      ${noteForm}
      ${notes.length ? notes.slice(0, 8).map((n) => noteItem(n, canSell)).join("") : `<p class="muted">Inga anteckningar.</p>`}
    </div>`;
}

/**
 * Tabellvy. opts: { stage, q, filters, sort }
 */
export function pipelineView(data, config, opts = {}, dealDetail = null) {
  if (dealDetail?.deal) {
    return dealDetailView(dealDetail, config, opts);
  }
  const filterStage = opts.stage ?? "";
  const q = opts.q ?? "";
  const sort = opts.sort || data.sort || "-updated";
  const f = { ...EMPTY_PIPELINE_FILTERS, ...(opts.filters ?? {}) };
  const stages = data.stages ?? [];
  const counts = data.stageCounts ?? {};
  const rows = data.rows ?? [];
  const total = data.total ?? rows.length;
  const facets = data.facets ?? {};
  const anyFilter = Object.values(f).some(Boolean) || Boolean(q);

  const tab = (id, label) => `
    <button type="button" role="tab" class="crm-tab"
      aria-selected="${filterStage === id ? "true" : "false"}"
      data-action="pipeline-filter" data-stage="${esc(id)}">
      ${esc(label)}<span class="crm-tab-n">${num(counts[id])}</span>
    </button>`;
  const openTabs = [tab("", "Öppna"), ...stages.filter((s) => OPEN.includes(s.id)).map((s) => tab(s.id, s.label))];
  const closedTabs = stages.filter((s) => !OPEN.includes(s.id)).map((s) => tab(s.id, s.label));

  const counties = (facets.counties ?? []).map((t) => ({
    id: t.slug,
    label: t.label.replace(/ län$/, ""),
    title: t.label,
  }));
  const tiers = (facets.callTiers ?? []).map((t) => ({
    id: t.slug,
    label: t.label.replace(/^Tier (\d) – /, "T$1 · "),
    title: t.label,
  }));
  const forms = (facets.legalForms ?? []).map((name) => ({ id: name, label: name }));
  const cityList = (facets.cities ?? [])
    .map((c) => `<option value="${esc(c)}"></option>`).join("");

  const toolbar = `
    <div class="crm-toolbar">
      <form id="crmSearchForm" class="crm-search" role="search">
        <input type="search" name="q" value="${esc(q)}" class="crm-field"
          placeholder="Sök bolag, org.nr, kontakt, ort …" aria-label="Sök" autocomplete="off" />
      </form>
      ${filterSelect("segment", f.segment, "Segment", SEGMENTS)}
      ${filterSelect("county", f.county, "Län", counties)}
      ${filterSelect("call", f.call, "Ringordning", tiers)}
      ${filterSelect("form", f.form, "Bolagsform", forms)}
      <input class="crm-field crm-city${f.city ? " is-set" : ""}" type="search"
        data-crm-filter="city" list="crmCityList" value="${esc(f.city)}"
        placeholder="Ort" aria-label="Ort" autocomplete="off" />
      <datalist id="crmCityList">${cityList}</datalist>
      <div class="crm-toggles" role="group" aria-label="Måste ha">
        ${filterToggle("phone", f.phone, "Telefon", "Bara bolag med telefonnummer")}
        ${filterToggle("email", f.email, "E-post", "Bara bolag med e-post")}
        ${filterToggle("tf", f.tf, "TF-medlem", "Bara medlemmar i Taxiförbundet")}
      </div>
      ${anyFilter
        ? `<button type="button" class="crm-clear" data-action="pipeline-clear">Rensa</button>`
        : ""}
    </div>
    <div class="crm-tabs-row">
      <div class="crm-tabs" role="tablist" aria-label="Steg">
        ${openTabs.join("")}<span class="crm-tabs-sep" aria-hidden="true"></span>${closedTabs.join("")}
      </div>
      <p class="crm-count">${rows.length < total ? `Visar ${num(rows.length)} av ` : ""}${num(total)} ${total === 1 ? "affär" : "affärer"}</p>
    </div>`;

  const body = rows.length
    ? `<div class="table-scroll">
      <table class="crm-table">
        <thead><tr>
          ${sortHeader("Bolag", "name", sort)}
          ${sortHeader("Ort", "city", sort)}
          ${sortHeader("Prio", "priority", sort)}
          <th>Kontakt</th>
          ${sortHeader("Steg", "stage", sort)}
          ${sortHeader("Ändrad", "updated", sort, "crm-col-date")}
          <th class="crm-col-actions"><span class="sr">Åtgärder</span></th>
        </tr></thead>
        <tbody>${rows.map((r) => pipelineRow(r, config)).join("")}</tbody>
      </table>
    </div>`
    : `<div class="crm-empty">
        <p>Inga affärer matchar ${anyFilter ? "filtren" : "steget"}.</p>
        ${anyFilter ? `<button type="button" class="crm-clear" data-action="pipeline-clear">Rensa filter och sök</button>` : ""}
      </div>`;

  const more = rows.length < total
    ? `<p class="crm-more"><button type="button" class="btn btn-quiet btn-small" data-action="pipeline-more">Visa ${num(Math.min(200, total - rows.length))} till</button></p>`
    : "";

  return `
    <div class="page-head">
      <div>
        <h1>CRM</h1>
        ${crmSubnav("pipeline")}
      </div>
      ${config?.canSell
        ? `<button type="button" class="btn btn-primary btn-small crm-new" data-action="pipeline-new-lead">+ Ny affär</button>`
        : ""}
    </div>
    ${toolbar}
    ${body}
    ${more}`;
}

function rowBadges(tags) {
  const seg = tags.find((t) => t.slug.startsWith("segment:"));
  const call = tags.find((t) => t.category === "call");
  const tf = tags.some((t) => t.slug === "medlem:taxiforbundet");
  const out = [];
  if (seg) {
    const letter = seg.slug.split(":")[1];
    out.push(`<span class="crm-seg crm-seg-${esc(letter)}" title="${esc(seg.label)}">${esc(letter.toUpperCase())}</span>`);
  }
  if (call) {
    out.push(`<span class="crm-badge" title="${esc(call.label)}">T${esc(call.slug.split(":")[1])}</span>`);
  }
  if (tf) out.push(`<span class="crm-badge crm-badge-tf" title="Medlem i Taxiförbundet">TF</span>`);
  return out.join("") || `<span class="muted">—</span>`;
}

function pipelineRow(r, config) {
  const acc = r.account || {};
  const per = r.person || {};
  const company = acc.name || r.name || "—";
  const contactName = per.name && per.name !== company ? per.name : "";
  const phone = per.phone || "";
  const email = per.email || "";
  const form = FORM_SHORT[acc.legalForm] || acc.legalForm || "";
  const meta = [acc.orgNumber, form].filter(Boolean).map(esc).join(" · ");
  const county = (acc.county || "").replace(/ län$/, "");

  let actions = "";
  if (config?.canSell) {
    actions = r.companyId
      ? `<button type="button" class="crm-icon-btn" data-action="open-company" data-id="${esc(r.companyId)}" title="Öppna TaxiTips-kund">👤</button>`
      : `<button type="button" class="crm-icon-btn" data-action="pipeline-new-customer"
          data-deal="${esc(r.id)}"
          data-name="${esc(per.name || "")}"
          data-email="${esc(email)}"
          data-company="${esc(acc.name || "")}"
          data-org="${esc(acc.orgNumber || "")}"
          title="Gör till TaxiTips-kund">+</button>`;
  }
  return `<tr class="row-link" data-action="crm-open-deal" data-deal="${esc(r.id)}">
    <td class="crm-col-company">
      <span class="crm-company">${esc(company)}</span>
      ${r.name && r.name !== company ? `<span class="crm-sub">Affär: ${esc(r.name)}</span>` : ""}
      ${meta ? `<span class="crm-sub crm-mono">${meta}</span>` : ""}
    </td>
    <td>${esc(acc.city || "—")}${acc.county && county !== acc.city ? `<span class="crm-sub">${esc(acc.county)}</span>` : ""}</td>
    <td class="crm-col-prio">${rowBadges(r.tags ?? [])}</td>
    <td class="crm-col-contact">
      ${contactName ? `<span>${esc(contactName)}</span>` : ""}
      ${phone ? `<a class="crm-contact-link" href="tel:${esc(phone.replace(/[^\d+]/g, ""))}">${esc(phone)}</a>` : ""}
      ${email ? `<a class="crm-contact-link crm-email" href="mailto:${esc(email)}" title="${esc(email)}">${esc(email)}</a>` : ""}
      ${!contactName && !phone && !email ? `<span class="muted">—</span>` : ""}
    </td>
    <td><span class="crm-stage crm-stage-${esc(r.stage)}">${esc(stageLabel(r.stage))}</span></td>
    <td class="crm-col-date muted">${esc(shortDate(r.updatedAt))}</td>
    <td class="crm-col-actions">${actions}</td>
  </tr>`;
}

function contactItem(c, dealId, canEdit) {
  const lines = [
    c.title ? `<span class="crm-sub">${esc(c.title)}</span>` : "",
    c.phone ? `<a class="crm-contact-link" href="tel:${esc(c.phone.replace(/[^\d+]/g, ""))}">${esc(c.phone)}</a>` : "",
    c.email ? `<a class="crm-contact-link crm-email" href="mailto:${esc(c.email)}">${esc(c.email)}</a>` : "",
  ].filter(Boolean).join("");
  const actions = canEdit ? `
    <div class="crm-contact-actions">
      ${c.isPrimary ? "" : `<button type="button" class="linklike" data-action="crm-contact" data-op="primary" data-deal="${esc(dealId)}" data-person="${esc(c.id)}">Gör till huvudkontakt</button>`}
      <details class="crm-more">
        <summary>Ändra</summary>
        <form class="crm-inline-form" data-crm-form="contact-edit" data-person="${esc(c.id)}">
          <div class="crm-form-row">
            <label>Namn<input name="name" maxlength="200" value="${esc(c.name)}" /></label>
            <label>Roll<input name="title" maxlength="200" value="${esc(c.title)}" placeholder="VD, trafikledare …" /></label>
          </div>
          <div class="crm-form-row">
            <label>Telefon<input name="phone" type="tel" maxlength="80" value="${esc(c.phone)}" /></label>
            <label>E-post<input name="email" type="email" maxlength="320" value="${esc(c.email)}" /></label>
          </div>
          <div class="crm-form-actions">
            <button class="btn btn-primary btn-small" type="submit">Spara</button>
            <button type="button" class="crm-danger-link" data-action="crm-contact" data-op="unlink"
              data-deal="${esc(dealId)}" data-person="${esc(c.id)}">Ta bort från bolaget</button>
          </div>
        </form>
      </details>
    </div>` : "";
  return `
    <li class="crm-contact">
      <div>
        <span class="crm-contact-name">${esc(c.name || "Namnlös")}</span>
        ${c.isPrimary ? `<span class="crm-badge crm-badge-primary">Huvudkontakt</span>` : ""}
        ${lines}
      </div>
      ${actions}
    </li>`;
}

/** opts: { peopleQuery, peopleHits } — sökträffar för att koppla befintlig kontakt. */
export function dealDetailView(data, config, opts = {}) {
  const d = data.deal;
  const notes = data.notes ?? [];
  const contacts = data.contacts ?? [];
  const tasks = data.tasks ?? [];
  const staff = data.staff ?? [];
  const me = data.me;
  const account = d.account || {};
  const canSell = !!config?.canSell;

  const stageBtns = canSell
    ? OPEN.concat(["won", "lost"]).map((s) => `
      <button type="button" class="crm-chip${d.stage === s ? " crm-chip-active" : ""}"
        data-action="pipeline-stage" data-deal="${esc(d.id)}" data-stage="${esc(s)}">${esc(stageLabel(s))}</button>`).join("")
    : "";
  const linkActions = canSell
    ? (d.companyId
      ? `<button class="btn btn-quiet btn-small" data-action="open-company" data-id="${esc(d.companyId)}">Öppna TaxiTips-kund</button>`
      : `<button class="btn btn-quiet btn-small" data-action="pipeline-new-customer"
          data-deal="${esc(d.id)}"
          data-name="${esc(d.person?.name || "")}"
          data-email="${esc(d.person?.email || "")}"
          data-company="${esc(account.name || "")}"
          data-org="${esc(account.orgNumber || "")}">Skapa TaxiTips-kund</button>`)
    : "";

  const hits = opts.peopleHits;
  const hitList = hits
    ? (hits.length
      ? `<ul class="crm-hits">${hits.map((p) => `
          <li><span>${esc(p.name || "Namnlös")}<span class="crm-sub">${esc([p.phone, p.email, p.accountName && `hos ${p.accountName}`].filter(Boolean).join(" · "))}</span></span>
            <button type="button" class="btn btn-quiet btn-small" data-action="crm-contact" data-op="link"
              data-deal="${esc(d.id)}" data-person="${esc(p.id)}">Koppla</button></li>`).join("")}</ul>`
      : `<p class="muted small">Inga träffar för «${esc(opts.peopleQuery || "")}».</p>`)
    : "";
  const contactForms = canSell ? `
    <details class="crm-more crm-add"${hits ? " open" : ""}>
      <summary>+ Lägg till kontakt</summary>
      <form class="crm-inline-form" data-crm-form="contact-new" data-deal="${esc(d.id)}">
        <div class="crm-form-row">
          <label>Namn<input name="name" maxlength="200" /></label>
          <label>Roll<input name="title" maxlength="200" placeholder="VD, trafikledare …" /></label>
        </div>
        <div class="crm-form-row">
          <label>Telefon<input name="phone" type="tel" maxlength="80" /></label>
          <label>E-post<input name="email" type="email" maxlength="320" /></label>
        </div>
        <div class="crm-form-actions"><button class="btn btn-primary btn-small" type="submit">Spara kontakt</button></div>
      </form>
      <form class="crm-inline-form crm-link-search" data-crm-form="contact-search" data-account="${esc(d.accountId || "")}">
        <label>…eller koppla en befintlig kontakt
          <input name="q" type="search" minlength="2" value="${esc(opts.peopleQuery || "")}" placeholder="Sök namn, telefon eller e-post" /></label>
      </form>
      ${hitList}
    </details>` : "";

  const noteForm = canSell ? `
    <details class="crm-more crm-add">
      <summary>+ Ny anteckning</summary>
      <form id="crmDealNoteForm" class="crm-inline-form" data-deal="${esc(d.id)}">
        <label>Rubrik<input name="title" maxlength="200" placeholder="Samtal, möte …" /></label>
        <label>Anteckning<textarea name="body" rows="4" required placeholder="Vad sa de?"></textarea></label>
        <div class="crm-form-actions"><button class="btn btn-primary btn-small" type="submit">Spara anteckning</button></div>
      </form>
    </details>` : "";

  const openTasks = tasks.filter((t) => t.status !== "done").length;
  const where = [account.city, account.county].filter(Boolean).join(", ");

  return `
    <div class="page-head crm-detail-head">
      <div>
        <button type="button" class="crm-back" data-action="crm-back">← Pipeline</button>
        <h1>${esc(account.name || d.name || "Affär")}</h1>
        <p class="muted">${esc([stageLabel(d.stage), where, d.source].filter(Boolean).join(" · "))}</p>
      </div>
      <div class="btn-row">${linkActions}</div>
    </div>
    ${canSell ? `<div class="crm-chips crm-stage-row" role="group" aria-label="Steg">${stageBtns}</div>` : ""}
    <div class="crm-detail-grid">
      <div class="crm-detail-col">
        <div class="card">
          <h2>Bolag</h2>
          <dl class="kv">
            <dt>Org.nr</dt><dd>${esc(account.orgNumber || "—")}</dd>
            <dt>Bolagsform</dt><dd>${esc(account.legalForm || "—")}</dd>
            <dt>Ort</dt><dd>${esc(account.city || "—")}</dd>
            <dt>Län</dt><dd>${esc(account.county || "—")}</dd>
            ${account.domain ? `<dt>Webb</dt><dd>${esc(account.domain)}</dd>` : ""}
          </dl>
          ${d.notesSummary ? `<h3 class="crm-card-sub">Inför samtalet</h3><p class="crm-brief">${esc(d.notesSummary).replace(/\n/g, "<br>")}</p>` : ""}
        </div>
        <div class="card">
          <div class="card-head"><h2>Kontakter <span class="crm-tab-n">${num(contacts.length)}</span></h2></div>
          ${contacts.length
            ? `<ul class="crm-contacts">${contacts.map((c) => contactItem(c, d.id, canSell)).join("")}</ul>`
            : `<p class="muted">Inga kontakter ännu.</p>`}
          ${contactForms}
        </div>
      </div>
      <div class="crm-detail-col">
        <div class="card">
          <div class="card-head"><h2>Uppgifter <span class="crm-tab-n">${num(openTasks)}</span></h2></div>
          ${canSell ? taskNewForm({ dealId: d.id, companyId: d.companyId }, staff, me) : ""}
          ${taskList(tasks, { staff, me, canEdit: canSell, empty: "Inga uppgifter på affären." })}
        </div>
        <div class="card">
          <div class="card-head"><h2>Anteckningar <span class="crm-tab-n">${num(notes.length)}</span></h2></div>
          ${noteForm}
          ${notes.length ? notes.map((n) => noteItem(n, canSell)).join("") : `<p class="muted">Inga anteckningar.</p>`}
        </div>
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
