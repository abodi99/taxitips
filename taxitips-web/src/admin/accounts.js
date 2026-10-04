import { dateTime } from "../portal/api.js";
import { esc } from "./sales.js";

/**
 * Kontohantering: lista användare, öppna ett konto, spärra eller häva, och
 * plattformens personal.
 *
 * En spärr stänger ute på servern, på varje anrop (fleet/accounts.py) -- det
 * här är bara vyn. Knapparna som ändrar visas bara för den som får ändra; en
 * säljare eller supportperson ser listorna men inte knapparna.
 */

const KIND = { company: "Företag", email: "E-postadress", user: "Konto" };
const PLATFORM = { android: "Android", ios: "iOS", web: "Webb" };

/** Appen kontot senast använde (fleet/client_activity.py), eller ett streck. */
function clientCell(c) {
  if (!c) return '<span class="muted">—</span>';
  const version = c.appVersion ? `v${c.appVersion}${c.appBuild ? ` (${c.appBuild})` : ""}` : "";
  const line = [PLATFORM[c.platform] ?? c.platform, version, c.deviceModel].filter(Boolean).join(" · ");
  return `${esc(line || "Ingen appinfo")}${c.osVersion ? `<div class="muted">${esc(c.osVersion)}</div>` : ""}`;
}
const ROLE = { company_owner: "Ägare", fleet_admin: "Bilar och förare", finance: "Ekonomi", company_admin: "Administratör (äldre)" };

function accountRows(accounts, { manage = false, compact = false } = {}) {
  if (!accounts.length) {
    return `<p class="muted">Inget konto matchar. Katalogen innehåller konton som loggat in sedan den infördes.</p>`;
  }
  return `<table>
    <thead><tr><th>Konto</th><th>Företag</th><th>Senast sedd</th><th>App</th>${compact ? "" : "<th></th>"}</tr></thead>
    <tbody>${accounts.map((a) => `
      <tr class="clickable" data-action="open-account" data-user="${esc(a.userId)}">
        <td data-label="Konto"><b>${esc(a.email || a.userId)}</b>
          ${a.staffRole ? `<span class="pill">Personal: ${esc(a.staffRole)}</span>` : ""}
          ${a.blocked ? `<div class="muted">Spärrad</div>` : ""}</td>
        <td data-label="Företag">${a.memberships?.length ? a.memberships.map((m) => `
          <div>${esc(m.companyName || m.companyId)}
            <span class="muted">${esc(ROLE[m.role] ?? m.role)}${m.status === "active" ? "" : " · avstängd"}</span></div>`).join("")
          : '<span class="muted">Inget företag</span>'}</td>
        <td data-label="Senast sedd">${esc(dateTime(a.client?.lastSeenAt ?? a.lastSeenAt))}</td>
        <td data-label="App">${clientCell(a.client)}</td>
        ${compact ? "" : `<td data-label="">${manage && !a.blocked
          ? `<button class="btn btn-quiet btn-small" data-action="open-account" data-user="${esc(a.userId)}">Öppna</button>`
          : ""}</td>`}
      </tr>`).join("")}</tbody>
  </table>`;
}

export function konton(found, blocks, q = "", config = null) {
  const manage = !!config?.canManage;
  const accounts = found?.accounts ?? [];
  const active = (blocks?.blocks ?? []).filter((b) => !b.liftedAt);
  return `
    <div class="page-head">
      <div><h1>Konton</h1>
        <p class="muted">Användarnivå: öppna ett konto för medlemskap, loggar, lösenordslänk, spärr och radering.
          Spärrade konton och adresser får ingen data och kan inte registrera nya företag.</p></div>
    </div>

    <form class="toolbar" id="accountSearch">
      <input name="q" value="${esc(q)}" placeholder="E-post eller företagsnamn" />
      <button class="btn btn-primary" type="submit">Sök</button>
    </form>

    <div class="card table-scroll">
      <h2>${q ? "Träffar" : "Senast sedda"} <span class="muted">(${esc(accounts.length)})</span></h2>
      ${accountRows(accounts, { manage })}
    </div>

    ${manage ? `<div class="card">
      <h2>Spärra en e-postadress</h2>
      <p class="muted">Gäller även en adress som ännu inte har något konto.</p>
      <form id="blockEmailForm" class="form-grid">
        <label>E-postadress<input name="email" type="email" required placeholder="namn@exempel.se" /></label>
        <label>Skäl<input name="reason" required placeholder="Varför spärras adressen?" /></label>
        <div class="btn-row span-2"><button class="btn btn-quiet" type="submit">Spärra adressen</button></div>
      </form>
    </div>` : ""}

    <div class="card table-scroll">
      <h2>Aktiva spärrar <span class="muted">(${esc(active.length)})</span></h2>
      ${active.length ? `<table>
        <thead><tr><th>Vad</th><th>Skäl</th><th>Spärrad</th><th></th></tr></thead>
        <tbody>${active.map((b) => `
          <tr>
            <td data-label="Vad"><span class="pill">${esc(KIND[b.kind] ?? b.kind)}</span>
              ${b.kind === "company"
                ? `<a href="#" data-action="open-company" data-id="${esc(b.value)}">${esc(b.label)}</a>`
                : b.kind === "user"
                  ? `<a href="#" data-action="open-account" data-user="${esc(b.value)}">${esc(b.label)}</a>`
                  : `<b>${esc(b.label)}</b>`}</td>
            <td data-label="Skäl">${esc(b.reason)}</td>
            <td data-label="Spärrad">${esc(dateTime(b.createdAt))}<div class="muted">${esc(b.createdByEmail || "")}</div></td>
            <td data-label="">${manage ? `<button class="btn btn-quiet btn-small" data-action="block-lift" data-block="${esc(b.id)}">Häv</button>` : ""}</td>
          </tr>`).join("")}</tbody></table>`
        : '<p class="muted">Inga aktiva spärrar.</p>'}
    </div>
  `;
}

const ERR_KIND = { crash: "Krasch", flow: "Flöde", server: "Server" };
const ERR_SOURCE = { app: "App", server: "Server" };
const PUSH_STATUS = {
  sent: "Skickad", failed: "Misslyckad", suppressed: "Undertryckt",
  pending: "Väntar", sending: "Skickas", expired: "Utgången",
};
const KIND_LABEL = { driver: "Förare", owner_app: "Ägarapp" };
const LEVEL_LABEL = { all: "Alla", medium: "Medel+", high: "Bara starka" };

function prefsLine(p) {
  if (!p) return "";
  // Serverns rad (core/notify_prefs.summary): läget plus det som avviker.
  if (p.summary) {
    return p.counties?.length ? `${p.summary} · Län: ${p.counties.join(", ")}` : p.summary;
  }
  const bits = [];
  if (p.notificationsOff) bits.push("Notiser av");
  if (p.pausedUntil) bits.push(`Paus till ${dateTime(p.pausedUntil)}`);
  bits.push(LEVEL_LABEL[p.minLevel] ?? p.minLevel);
  if (p.counties?.length) bits.push(`Län: ${p.counties.join(", ")}`);
  if (p.categoriesOff?.length) bits.push(`Av: ${p.categoriesOff.join(", ")}`);
  return bits.filter(Boolean).join(" · ");
}

function deviceRows(devices) {
  if (!devices?.length) {
    return `<p class="muted">Ingen telefon kopplad till kontot (Firebase/push). Ägarappen eller
      en inlösen av förarinbjudan syns här.</p>`;
  }
  return `<table>
    <thead><tr><th>Telefon</th><th>Modell</th><th>Firebase</th><th>Notisinställning</th><th>Senast</th></tr></thead>
    <tbody>${devices.map((d) => `
      <tr>
        <td data-label="Telefon"><b>${esc(d.label || d.id.slice(0, 8))}</b>
          <div class="muted">${esc(KIND_LABEL[d.kind] ?? d.kind ?? "—")}
            ${d.companyName ? ` · ${esc(d.companyName)}` : ""}
            ${d.linkedToAccount ? "" : " · <span class=\"muted\">ej länkad till kontot</span>"}</div></td>
        <td data-label="Modell">${esc(d.deviceModel || d.client?.deviceModel || "—")}
          <div class="muted">${esc(PLATFORM[d.platform || d.client?.platform] ?? (d.platform || d.client?.platform || ""))}
            ${d.appVersion || d.client?.appVersion ? ` · v${esc(d.appVersion || d.client?.appVersion)}` : ""}
            ${d.osVersion || d.client?.osVersion ? ` · ${esc(d.osVersion || d.client?.osVersion)}` : ""}</div></td>
        <td data-label="Firebase">${d.hasPush
          ? '<span class="ok">Token registrerad</span>'
          : '<span class="muted">Ingen token</span>'}</td>
        <td data-label="Notisinställning">${esc(prefsLine(d.prefs) || "—")}</td>
        <td data-label="Senast">${esc(dateTime(d.lastSeenAt ?? d.client?.lastSeenAt))}</td>
      </tr>`).join("")}</tbody>
  </table>`;
}

const VIA_LABEL = {
  owner_app: "Ägarapp",
  device_session: "Session",
  email_invite: "Förarinbjudan",
  email_relogin: "Förarinloggning",
};

function deviceSwapCard(swaps, userId, manage) {
  const s = swaps || {};
  const used = s.used ?? 0;
  const limit = s.limit ?? 2;
  const grants = s.grants ?? 0;
  const remaining = s.remaining ?? 0;
  const history = s.history || [];
  return `<div class="card table-scroll">
    <h2>Telefonbyten <span class="muted">${esc(used)}/${esc(limit)}${grants ? ` (+${esc(grants)} extra)` : ""} · ${esc(s.month || "")}</span></h2>
    <p class="muted">Högst två byten per kalendermånad (Stockholm). Första kopplingen och samma telefon igen räknas inte.
      Kvar: <b>${esc(remaining)}</b>.</p>
    ${manage ? `<div class="btn-row" style="margin-bottom:1rem">
      <button class="btn btn-quiet" data-action="account-allow-device-swap" data-user="${esc(userId)}">Tillåt ett extra byte</button>
    </div>` : ""}
    ${history.length ? `<table>
      <thead><tr><th>När</th><th>Vad</th><th>Telefon</th><th>Från</th></tr></thead>
      <tbody>${history.map((h) => `
        <tr>
          <td data-label="När">${esc(dateTime(h.at))}</td>
          <td data-label="Vad">${h.isSwap
            ? (h.adminOverride ? '<span class="pill">Byte (admin)</span>' : '<span class="pill pill-warn">Byte</span>')
            : '<span class="muted">Första / samma</span>'}
            <div class="muted">${esc(VIA_LABEL[h.via] ?? h.via ?? "")}</div></td>
          <td data-label="Telefon">${esc(h.deviceLabel || (h.deviceId || "").slice(0, 8))}</td>
          <td data-label="Från">${h.previousDeviceId
            ? esc(h.previousLabel || h.previousDeviceId.slice(0, 8))
            : "—"}</td>
        </tr>`).join("")}</tbody>
    </table>` : '<p class="muted">Inga kopplingar bokförda ännu.</p>'}
  </div>`;
}

function notificationRows(rows) {
  if (!rows?.length) return '<p class="muted">Inga notiser skickade till kontots telefoner.</p>';
  return `<table>
    <thead><tr><th>När</th><th>Notis</th><th>Till</th><th>Status</th></tr></thead>
    <tbody>${rows.map((n) => `
      <tr>
        <td data-label="När">${esc(dateTime(n.createdAt))}</td>
        <td data-label="Notis"><b>${esc(n.title)}</b><div class="muted">${esc(n.body)}</div>
          ${n.error ? `<div class="error mono">${esc(n.error)}</div>` : ""}</td>
        <td data-label="Till">${esc(n.device || "")}</td>
        <td data-label="Status">${esc(PUSH_STATUS[n.status] ?? n.status)}
          ${n.attempts > 1 ? `<div class="muted">${esc(n.attempts)} försök</div>` : ""}</td>
      </tr>`).join("")}</tbody>
  </table>`;
}

const FEEDBACK_CLASS = {
  fare: "pill-ok",
  empty: "pill-danger",
  heading: "pill-warn",
};

function feedbackRows(rows) {
  if (!rows?.length) {
    return '<p class="muted">Ingen feedback än (fick körning / ingen kund / kör dit).</p>';
  }
  return `<table>
    <thead><tr><th>När</th><th>Svar</th><th>Tips</th></tr></thead>
    <tbody>${rows.map((f) => `
      <tr>
        <td data-label="När">${esc(dateTime(f.createdAt))}</td>
        <td data-label="Svar"><span class="pill ${FEEDBACK_CLASS[f.verdict] || ""}">${esc(f.verdictLabel || f.verdict)}</span></td>
        <td data-label="Tips"><b>${esc(f.title || "—")}</b>
          <div class="muted">${[f.kind, f.region, f.demandScore != null ? `${f.demandScore} p` : ""]
            .filter(Boolean).map(esc).join(" · ")}</div></td>
      </tr>`).join("")}</tbody>
  </table>`;
}

function tipReportRows(rows) {
  if (!rows?.length) {
    return '<p class="muted">Inga rapporter om felaktiga tips från kontot.</p>';
  }
  return `<table>
    <thead><tr><th>När</th><th>Status</th><th>Tips</th><th>Skäl</th></tr></thead>
    <tbody>${rows.map((r) => `
      <tr>
        <td data-label="När">${esc(dateTime(r.createdAt))}</td>
        <td data-label="Status">${r.status === "open"
          ? '<span class="pill pill-warn">Öppen</span>'
          : '<span class="pill">Avslutad</span>'}</td>
        <td data-label="Tips"><b>${esc(r.title || "—")}</b>
          <div class="muted">${[r.kind, r.region].filter(Boolean).map(esc).join(" · ")}</div></td>
        <td data-label="Skäl">${esc((r.reason || "").slice(0, 160) || "—")}
          ${r.resolutionNote ? `<div class="muted">${esc(r.resolutionNote.slice(0, 120))}</div>` : ""}</td>
      </tr>`).join("")}</tbody>
  </table>`;
}

function favoriteRows(rows) {
  if (!rows?.length) {
    return '<p class="muted">Inga sparade tips (favoriter) på kontots telefoner.</p>';
  }
  return `<table>
    <thead><tr><th>När</th><th>Tips</th><th>Var</th></tr></thead>
    <tbody>${rows.map((f) => `
      <tr>
        <td data-label="När">${esc(dateTime(f.createdAt))}</td>
        <td data-label="Tips"><b>${esc(f.title || "—")}</b>
          <div class="muted">${[f.kind, f.region, f.demandScore != null ? `${f.demandScore} p` : ""]
            .filter(Boolean).map(esc).join(" · ")}
            ${f.purged ? " · tipset gallrat" : ""}</div>
          ${f.note ? `<div class="muted">${esc(f.note.slice(0, 120))}</div>` : ""}</td>
        <td data-label="Var">${esc(f.ownerLabel || "—")}</td>
      </tr>`).join("")}</tbody>
  </table>`;
}

function errorRows(errors) {
  if (!errors?.length) return '<p class="muted">Inga fel rapporterade för det här kontot.</p>';
  return `<table>
    <thead><tr><th>När</th><th>Vad</th><th>Meddelande</th><th></th></tr></thead>
    <tbody>${errors.map((e) => `
      <tr>
        <td data-label="När">${esc(dateTime(e.lastAt))}
          ${e.occurrences > 1 ? `<div class="muted">×${esc(e.occurrences)}</div>` : ""}</td>
        <td data-label="Vad"><span class="pill">${esc(ERR_SOURCE[e.source] ?? e.source)}</span>
          ${esc(ERR_KIND[e.kind] ?? e.kind)}
          ${e.flow ? `<div class="muted">${esc(e.flow)}</div>` : ""}</td>
        <td data-label="Meddelande">${esc((e.message || e.errorType || "").slice(0, 160))}
          ${e.httpStatus ? `<div class="muted">HTTP ${esc(e.httpStatus)}</div>` : ""}</td>
        <td data-label="">${e.appVersion ? `v${esc(e.appVersion)}` : ""}
          ${e.platform ? `<div class="muted">${esc(PLATFORM[e.platform] ?? e.platform)}</div>` : ""}</td>
      </tr>`).join("")}</tbody>
  </table>`;
}

function auditRows(audit) {
  if (!audit?.length) return '<p class="muted">Inga revisionhändelser knutna till kontot.</p>';
  return `<table>
    <thead><tr><th>När</th><th>Händelse</th><th>Detalj</th></tr></thead>
    <tbody>${audit.map((r) => `
      <tr>
        <td data-label="När">${esc(dateTime(r.at))}</td>
        <td data-label="Händelse"><code>${esc(r.action)}</code>
          ${r.subjectType ? `<div class="muted">${esc(r.subjectType)}</div>` : ""}</td>
        <td data-label="Detalj"><span class="muted">${esc(JSON.stringify(r.detail || {}).slice(0, 180))}</span></td>
      </tr>`).join("")}</tbody>
  </table>`;
}

/** En användares sida: medlemskap, Firebase, notiser, loggar, åtgärder. */
export function konto(account, config = null, recovery = null, logs = null) {
  const manage = !!config?.canManage;
  const a = account || {};
  const memberships = a.memberships || [];
  const devices = logs?.devices ?? [];
  const deviceSwaps = logs?.deviceSwaps ?? null;
  const notifications = logs?.notifications ?? [];
  const favorites = logs?.favorites ?? [];
  const feedback = logs?.feedback ?? [];
  const tipReports = logs?.tipReports ?? [];
  const summary = logs?.feedbackSummary ?? {};
  const errors = logs?.errors ?? [];
  const audit = logs?.audit ?? [];
  const hasPush = devices.some((d) => d.hasPush);
  return `
    <div class="page-head">
      <div>
        <p class="muted"><a href="#" data-action="back-accounts">← Konton</a></p>
        <h1>${esc(a.email || a.userId || "Konto")}</h1>
        <p class="muted">${a.staffRole ? `Personalroll: ${esc(a.staffRole)} · ` : ""}id ${esc(a.userId || "")}</p>
      </div>
    </div>

    ${a.blocked ? `<div class="card">
      <p>Spärrad: ${esc(a.blocked.reason || "")}</p>
      ${manage ? `<button class="btn btn-quiet" data-action="block-lift" data-block="${esc(a.blocked.id)}">Häv spärren</button>` : ""}
    </div>` : ""}

    <div class="card">
      <h2>Aktivitet</h2>
      <dl class="kv">
        <dt>Senast inloggad</dt><dd>${esc(dateTime(a.client?.lastLoginAt))}</dd>
        <dt>Senast sedd</dt><dd>${esc(dateTime(a.client?.lastSeenAt ?? a.lastSeenAt))}</dd>
        <dt>App</dt><dd>${clientCell(a.client)}</dd>
        <dt>Feedback</dt><dd>${esc(summary.fare || 0)} fick körning · ${esc(summary.empty || 0)} ingen kund
          ${summary.heading ? ` · ${esc(summary.heading)} kör dit` : ""}
          ${summary.reportsTotal ? ` · ${esc(summary.reportsOpen || 0)}/${esc(summary.reportsTotal)} tipprapporter öppna` : ""}
          ${summary.favorites ? ` · ${esc(summary.favorites)} sparade` : ""}</dd>
      </dl>
    </div>

    <div class="card table-scroll">
      <h2>Företag</h2>
      ${memberships.length ? `<table>
        <thead><tr><th>Företag</th><th>Roll</th><th>Status</th><th></th></tr></thead>
        <tbody>${memberships.map((m) => `
          <tr>
            <td data-label="Företag"><a href="#" data-action="open-company" data-id="${esc(m.companyId)}">${esc(m.companyName || m.companyId)}</a></td>
            <td data-label="Roll">${esc(ROLE[m.role] ?? m.role)}</td>
            <td data-label="Status">${m.status === "active" ? "Aktiv" : "Avstängd i företaget"}</td>
            <td data-label="">${manage ? `<div class="btn-row">
              ${m.status === "active"
                ? `<button class="btn btn-quiet btn-small" data-action="account-member-status" data-company="${esc(m.companyId)}" data-user="${esc(a.userId)}" data-status="disabled">Stäng av här</button>`
                : `<button class="btn btn-quiet btn-small" data-action="account-member-status" data-company="${esc(m.companyId)}" data-user="${esc(a.userId)}" data-status="active">Aktivera här</button>`}
            </div>` : ""}</td>
          </tr>`).join("")}</tbody>
      </table>` : '<p class="muted">Hör inte till något företag.</p>'}
    </div>

    <div class="card table-scroll">
      <h2>Firebase / telefoner <span class="muted">(${esc(devices.length)})</span></h2>
      ${deviceRows(devices)}
      ${manage && devices.length ? `<div class="btn-row" style="margin-top:1rem">
        <button class="btn btn-quiet" data-action="account-test-push" data-user="${esc(a.userId)}"
          ${hasPush ? "" : "disabled"}>Skicka testnotis</button>
      </div>
      <p class="muted">Testnotisen går bara till telefoner med Firebase-token som klarar mottagargrinden.</p>` : ""}
    </div>

    ${deviceSwapCard(deviceSwaps, a.userId, manage)}

    <div class="card table-scroll">
      <h2>Notiser <span class="muted">(${esc(notifications.length)})</span></h2>
      ${notificationRows(notifications)}
    </div>

    <div class="card table-scroll">
      <h2>Sparade tips <span class="muted">(${esc(favorites.length)})</span></h2>
      <p class="muted">Favoriter från kontots telefoner och inloggning. Gallras efter sju dagar.</p>
      ${favoriteRows(favorites)}
    </div>

    <div class="card table-scroll">
      <h2>Feedback <span class="muted">(${esc(feedback.length)})</span></h2>
      <p class="muted">Fick körning / ingen kund från kontots telefoner.</p>
      ${feedbackRows(feedback)}
    </div>

    <div class="card table-scroll">
      <h2>Felaktiga tips <span class="muted">(${esc(tipReports.length)})</span></h2>
      ${tipReportRows(tipReports)}
    </div>

    <div class="card table-scroll">
      <h2>Loggar — fel <span class="muted">(${esc(errors.length)})</span></h2>
      ${errorRows(errors)}
    </div>

    <div class="card table-scroll">
      <h2>Loggar — revision <span class="muted">(${esc(audit.length)})</span></h2>
      ${auditRows(audit)}
    </div>

    ${manage ? `<div class="card">
      <h2>Åtgärder</h2>
      <div class="btn-row">
        <button class="btn btn-quiet" data-action="account-recovery" data-user="${esc(a.userId)}">Skapa lösenordslänk</button>
        ${a.blocked ? "" : `<button class="btn btn-quiet" data-action="block-user" data-user="${esc(a.userId)}" data-email="${esc(a.email)}">Spärra kontot</button>
        <button class="btn btn-quiet" data-action="block-email" data-email="${esc(a.email)}">Spärra adressen</button>`}
        <button class="btn btn-quiet" data-action="account-delete" data-user="${esc(a.userId)}" data-email="${esc(a.email)}">Radera kontot</button>
      </div>
      ${recovery?.url ? `<p class="muted" style="margin-top:1rem">Länk (${esc(recovery.kind)}):</p>
        <p><code id="recoveryUrl">${esc(recovery.url)}</code></p>
        <button class="btn btn-quiet btn-small" data-action="copy-recovery">Kopiera</button>` : ""}
      <p class="muted" style="margin-top:1rem">Radering tar bort inloggningen. Enda ägare i ett företag går inte — överlåt först.</p>
    </div>` : ""}
  `;
}

export function personal(list, config = null) {
  const manage = !!config?.canManage;
  const rows = list?.staff ?? [];
  const roles = list?.roles ?? [];
  const label = Object.fromEntries(roles.map((r) => [r.value, r.label]));
  return `
    <div class="page-head">
      <div><h1>Personal</h1>
        <p class="muted"><b>Support</b> läser. <b>Säljare</b> lägger upp kunder, paket, prov och kuponger.
          <b>Plattformsadministratör</b> gör allt, även spärrar och avstängning.</p></div>
    </div>
    <div class="card table-scroll">
      <table>
        <thead><tr><th>Konto</th><th>Roll</th><th>Sedan</th><th></th></tr></thead>
        <tbody>${rows.map((r) => `
          <tr>
            <td data-label="Konto"><b>${esc(r.email || r.userId)}</b></td>
            <td data-label="Roll">${r.active ? esc(label[r.role] ?? r.role) : '<span class="muted">Borttagen</span>'}</td>
            <td data-label="Sedan">${esc(dateTime(r.createdAt))}</td>
            <td data-label="">${manage && r.active && r.email ? `<button class="btn btn-quiet" data-action="staff-remove"
              data-email="${esc(r.email)}">Ta bort rollen</button>` : ""}</td>
          </tr>`).join("")}</tbody>
      </table>
    </div>
    ${manage ? `<div class="card">
      <h2>Ge en roll</h2>
      <p class="muted">Personen loggar först in i adminwebben en gång (hen ser då "Ingen adminbehörighet"),
        så att kontot finns. Sedan ger du rollen här.</p>
      <form id="staffForm" class="form-grid">
        <label>E-postadress<input name="email" type="email" required /></label>
        <label>Roll<select name="role">${roles.map((r) => `<option value="${esc(r.value)}">${esc(r.label)}</option>`).join("")}</select></label>
        <div class="btn-row span-2"><button class="btn btn-primary" type="submit">Spara</button></div>
      </form>
    </div>` : ""}
  `;
}
