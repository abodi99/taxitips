import { dateTime, request } from "../portal/api.js";
import { esc } from "./sales.js";

/**
 * "Appar och fel": vad supporten behöver när en kund ringer och säger att
 * appen inte fungerar.
 *
 * * **Fel** -- appens krascher och misslyckade inloggningar, registreringar,
 *   parkopplingar och flöden, plus serverns egna 5xx. Serverfelen bär ett
 *   request-id som står på samma rad i serverloggen.
 * * **Appar** -- per konto och telefon: senaste inloggning, senast sedd,
 *   appversion, plattform, OS och modell. Och hur många som kör varje version.
 *
 * Servern bestämmer vem som får läsa (fleet/admin_activity.py, ADMIN_VIEW) och
 * vad som finns att läsa (fleet/client_activity.py -- inga tokens, ingen
 * position, texten tvättad). Den här filen ritar bara.
 *
 * Egen fil med egen händelsehantering (data-activity-attribut), så att den
 * inte behöver flätas in i main.js: main anropar bara `mount` och
 * `companyPanel`.
 */

const KIND = {
  crash: ["Krasch", "pill-danger"],
  flow: ["Flöde", "pill-warn"],
  server: ["Server", "pill-danger"],
};

const FLOW = {
  login: "Inloggning",
  me: "Profil vid start",
  signup: "Registrering (konto)",
  register: "Registrering (företag)",
  pairing: "Parkoppling",
  feed: "Tipsflödet",
  flutter: "Krasch i gränssnittet",
  uncaught: "Ofångat fel",
  unknown: "Okänt",
};

const PLATFORM = { android: "Android", ios: "iOS", web: "Webb" };

const view = {
  tab: "fel",
  errors: { days: 7, kind: "", platform: "", flow: "", q: "" },
  clients: { q: "", platform: "", kind: "", days: "" },
};

let host = null;
let hooks = { isCurrent: () => true, onError: () => {} };
const wired = new WeakSet();

/* --- Anrop ------------------------------------------------------------ */

function query(params) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== "" && value != null) qs.set(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

function fetchErrors(params) {
  return request(`/api/admin/activity/errors${query(params)}`);
}

function fetchClients(params) {
  return request(`/api/admin/activity/clients${query(params)}`);
}

/* --- Bitar ------------------------------------------------------------ */

function flowLabel(flow) {
  if (!flow) return "—";
  return FLOW[flow] ?? flow;
}

function appLine(r) {
  const version = r.appVersion ? `${r.appVersion}${r.appBuild ? ` (${r.appBuild})` : ""}` : "";
  const parts = [
    PLATFORM[r.platform] ?? r.platform,
    version && `v${version}`,
    r.deviceModel,
    r.osVersion,
  ].filter(Boolean);
  return parts.length ? esc(parts.join(" · ")) : '<span class="muted">Ingen appinfo</span>';
}

function who(r) {
  const bits = [];
  if (r.companyId) {
    bits.push(`<a href="#" data-action="open-company" data-id="${esc(r.companyId)}">${esc(r.companyName || "Företaget")}</a>`);
  }
  if (r.deviceId) bits.push(`<span>Telefon: ${esc(r.deviceLabel || r.deviceId.slice(0, 8))}</span>`);
  if (r.userId) bits.push(`<span>${esc(r.userEmail || `Konto ${r.userId.slice(0, 8)}`)}</span>`);
  if (!bits.length) bits.push('<span class="muted">Inte inloggad</span>');
  return bits.join("<br />");
}

function errorRow(e) {
  const [label, cls] = KIND[e.kind] ?? [e.kind, ""];
  const status = e.httpStatus ? ` · HTTP ${esc(e.httpStatus)}` : "";
  const reason = e.reason ? ` · ${esc(e.reason)}` : "";
  const detail = [
    e.errorType && `<dt>Typ</dt><dd class="mono">${esc(e.errorType)}</dd>`,
    e.requestId && `<dt>Request-id</dt><dd class="mono">${esc(e.requestId)}</dd>`,
    e.path && `<dt>Sökväg</dt><dd class="mono">${esc(e.path)}</dd>`,
    `<dt>Första gången</dt><dd>${esc(dateTime(e.createdAt))}</dd>`,
  ].filter(Boolean).join("");
  return `
    <tr>
      <td data-label="Senast">${esc(dateTime(e.lastAt))}
        ${e.occurrences > 1 ? `<div class="muted">${esc(e.occurrences)} gånger</div>` : ""}</td>
      <td data-label="Vad"><span class="pill ${cls}">${esc(label)}</span>${e.fatal ? ' <span class="pill pill-danger">Fatal</span>' : ""}
        <div><b>${esc(flowLabel(e.flow))}</b><span class="muted">${status}${reason}</span></div></td>
      <td data-label="Fel">
        <details><summary>${esc((e.message || "—").slice(0, 160))}</summary>
          <dl class="kv">${detail}</dl>
          ${e.message && e.message.length > 160 ? `<p>${esc(e.message)}</p>` : ""}
          ${e.stack ? `<pre class="mono" style="white-space: pre-wrap; font-size: 0.8rem; max-height: 20rem; overflow: auto">${esc(e.stack)}</pre>` : ""}
        </details></td>
      <td data-label="Vem">${who(e)}</td>
      <td data-label="App">${appLine(e)}</td>
    </tr>`;
}

export function errorsTable(errors, { empty = "Inga fel i perioden." } = {}) {
  if (!errors.length) return `<p class="muted">${esc(empty)}</p>`;
  return `<table>
    <thead><tr><th>Senast</th><th>Vad</th><th>Fel</th><th>Vem</th><th>App</th></tr></thead>
    <tbody>${errors.map(errorRow).join("")}</tbody></table>`;
}

function clientRow(c) {
  const kind = c.kind === "user" ? "Konto" : "Telefon";
  const place = [c.ipPrefix, c.country].filter(Boolean).join(" · ");
  return `
    <tr>
      <td data-label="Vem"><b>${esc(c.label || c.id.slice(0, 8))}</b>
        <div class="muted">${esc(kind)}${c.deviceKind === "owner_app" ? " (ägarens app)" : ""}</div></td>
      <td data-label="Företag">${c.companyId
        ? `<a href="#" data-action="open-company" data-id="${esc(c.companyId)}">${esc(c.companyName || "Företaget")}</a>`
        : '<span class="muted">—</span>'}</td>
      <td data-label="Senast inloggad">${c.kind === "user" ? esc(dateTime(c.lastLoginAt)) : '<span class="muted">Loggar inte in</span>'}</td>
      <td data-label="Senast sedd">${esc(dateTime(c.lastSeenAt))}</td>
      <td data-label="App">${appLine(c)}</td>
      <td data-label="Nät"><span class="mono">${esc(place || "—")}</span></td>
    </tr>`;
}

export function clientsTable(clients, { empty = "Ingen app har hörts av än." } = {}) {
  if (!clients.length) return `<p class="muted">${esc(empty)}</p>`;
  return `<table>
    <thead><tr><th>Vem</th><th>Företag</th><th>Senast inloggad</th><th>Senast sedd</th><th>App</th><th>Nät</th></tr></thead>
    <tbody>${clients.map(clientRow).join("")}</tbody></table>`;
}

function versionChips(versions) {
  if (!versions?.length) return "";
  return `<ul class="chips" style="list-style: none; padding: 0" aria-label="Versioner senaste 30 dygnen">${versions.map((v) => `
    <li class="pill">${esc(PLATFORM[v.platform] ?? v.platform ?? "?")} v${esc(v.appVersion)}:
      <b>${esc(v.count)}</b></li>`).join("")}</ul>`;
}

function select(name, value, options) {
  return `<select name="${name}">${options.map(([v, label]) =>
    `<option value="${esc(v)}"${String(v) === String(value) ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
}

/* --- Sidan ------------------------------------------------------------ */

function errorsPage(data) {
  const f = view.errors;
  const flows = data.flows ?? [];
  return `
    <form class="toolbar" data-activity-form="errors">
      <input name="q" value="${esc(f.q)}" placeholder="Feltext, request-id, version eller modell" />
      ${select("kind", f.kind, [["", "Alla sorter"], ["crash", "Krascher"], ["flow", "Flöden"], ["server", "Serverfel"]])}
      ${select("platform", f.platform, [["", "Alla plattformar"], ["android", "Android"], ["ios", "iOS"], ["web", "Webb"]])}
      ${select("days", f.days, [[1, "Senaste dygnet"], [7, "Senaste 7 dygnen"], [30, "Senaste 30 dygnen"]])}
      <button class="btn btn-primary" type="submit">Filtrera</button>
    </form>
    ${flows.length ? `<div class="chips" role="tablist" aria-label="Flöde">
      <button class="chip" role="tab" data-activity="flow" data-flow="" aria-selected="${!f.flow}">Alla</button>
      ${flows.map((x) => `<button class="chip" role="tab" data-activity="flow" data-flow="${esc(x.flow)}"
        aria-selected="${x.flow === f.flow}">${esc(flowLabel(x.flow))} <span class="muted">${esc(x.count)}</span></button>`).join("")}
    </div>` : ""}
    <div class="card table-scroll">
      <h2>Fel <span class="muted">(${esc(data.total ?? 0)}${(data.total ?? 0) > (data.limit ?? 200) ? `, visar ${esc(data.limit)} senaste` : ""})</span></h2>
      ${errorsTable(data.errors ?? [])}
    </div>`;
}

function clientsPage(data) {
  const f = view.clients;
  return `
    <form class="toolbar" data-activity-form="clients">
      <input name="q" value="${esc(f.q)}" placeholder="E-post, telefon, företag, version eller modell" />
      ${select("kind", f.kind, [["", "Konton och telefoner"], ["user", "Konton"], ["device", "Telefoner"]])}
      ${select("platform", f.platform, [["", "Alla plattformar"], ["android", "Android"], ["ios", "iOS"], ["web", "Webb"]])}
      ${select("days", f.days, [["", "Alla"], [1, "Sedda senaste dygnet"], [7, "Sedda senaste 7 dygnen"], [30, "Sedda senaste 30 dygnen"]])}
      <button class="btn btn-primary" type="submit">Filtrera</button>
    </form>
    <div class="card">
      <h2>Versioner</h2>
      <p class="muted">Appar som hörts av de senaste 30 dygnen, per plattform och version.</p>
      ${versionChips(data.versions) || '<p class="muted">Ingen app med version har hörts av.</p>'}
    </div>
    <div class="card table-scroll">
      <h2>Konton och telefoner <span class="muted">(${esc((data.clients ?? []).length)})</span></h2>
      ${clientsTable(data.clients ?? [])}
    </div>`;
}

function page(inner) {
  return `
    <div class="page-head">
      <div><h1>Appar och fel</h1>
        <p class="muted">Appens krascher och misslyckade inloggningar, registreringar, parkopplingar och
          tipsflöden, serverns egna fel, och vilken app varje konto och telefon kör. Feltexter är
          tvättade från tokens, e-post, telefonnummer och positioner. Fel sparas i 30 dygn.</p></div>
    </div>
    <div class="chips" role="tablist" aria-label="Vy">
      <button class="chip" role="tab" data-activity="tab" data-tab="fel" aria-selected="${view.tab === "fel"}">Fel</button>
      <button class="chip" role="tab" data-activity="tab" data-tab="appar" aria-selected="${view.tab === "appar"}">Appar</button>
    </div>
    ${inner}`;
}

async function paint() {
  if (!host) return;
  const target = host;
  try {
    const inner = view.tab === "fel"
      ? errorsPage(await fetchErrors(view.errors))
      : clientsPage(await fetchClients(view.clients));
    if (hooks.isCurrent() && target === host) target.innerHTML = page(inner);
  } catch (error) {
    if (hooks.isCurrent()) {
      target.innerHTML = page("");
      hooks.onError(error);
    }
  }
}

/** Ritar vyn i `el`. `isCurrent` från main.js: sluta rita när man gått vidare. */
export function mount(el, { isCurrent = () => true, onError = () => {} } = {}) {
  host = el;
  hooks = { isCurrent, onError };
  wire(el);
  return paint();
}

/* --- Kundsidan ------------------------------------------------------- */

/**
 * En hopfälld ruta sist på kundsidan: företagets appar och fel. Hämtas först
 * när den öppnas -- kundsidan ska inte bli långsammare för att någon kanske
 * vill felsöka.
 */
export function companyPanel(el, companyId, { isCurrent = () => true } = {}) {
  if (!el || !companyId || !isCurrent()) return;
  wire(el);
  el.insertAdjacentHTML("beforeend", `
    <details class="card" data-activity-panel="${esc(companyId)}">
      <summary><h2>Appar och fel</h2></summary>
      <p class="muted">Vilken app varje konto och telefon kör, och fel de senaste 30 dygnen.</p>
      <div data-activity-body><p class="muted">Laddar …</p></div>
    </details>`);
}

async function loadPanel(panel) {
  const body = panel.querySelector("[data-activity-body]");
  const companyId = panel.dataset.activityPanel;
  if (!body || panel.dataset.loaded) return;
  panel.dataset.loaded = "1";
  try {
    const [clients, errors] = await Promise.all([
      fetchClients({ company: companyId }),
      fetchErrors({ company: companyId, days: 30 }),
    ]);
    body.innerHTML = `
      <h3>Konton och telefoner</h3>
      <div class="table-scroll">${clientsTable(clients.clients ?? [], {
        empty: "Ingen av företagets appar har hörts av sedan loggningen infördes.",
      })}</div>
      <h3>Fel <span class="muted">(${esc(errors.total ?? 0)})</span></h3>
      <div class="table-scroll">${errorsTable(errors.errors ?? [], { empty: "Inga fel de senaste 30 dygnen." })}</div>`;
  } catch (error) {
    panel.dataset.loaded = "";
    body.innerHTML = `<p class="error">${esc(error?.message ?? "Kunde inte hämta.")}</p>`;
  }
}

/* --- Händelser --------------------------------------------------------- */

function wire(el) {
  if (wired.has(el)) return;
  wired.add(el);
  el.addEventListener("click", (event) => {
    const button = event.target.closest("[data-activity]");
    if (!button || !el.contains(button)) return;
    if (button.dataset.activity === "tab") {
      view.tab = button.dataset.tab === "appar" ? "appar" : "fel";
      paint();
    } else if (button.dataset.activity === "flow") {
      view.errors = { ...view.errors, flow: button.dataset.flow ?? "" };
      paint();
    }
  });
  // main.js lyssnar också på submit i samma behållare, men gör ingenting med
  // formulär den inte känner igen. preventDefault där eller här -- båda är ok.
  el.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-activity-form]");
    if (!form) return;
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    if (form.dataset.activityForm === "errors") {
      view.errors = { ...view.errors, ...data, days: Number(data.days || 7), flow: "" };
    } else {
      view.clients = { ...view.clients, ...data };
    }
    paint();
  });
  el.addEventListener("toggle", (event) => {
    const panel = event.target;
    if (panel?.dataset?.activityPanel && panel.open) loadPanel(panel);
  }, true);
}
