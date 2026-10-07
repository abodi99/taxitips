import { dateTime } from "../portal/api.js";

/**
 * Statussidan: fungerar varje koppling just nu? Svaret kommer från
 * fleet/admin_status.py -- den här filen bedömer ingenting själv, den ritar
 * bara nivån servern satte.
 *
 * Datakällorna (Trafiklab, Trafikverket …) anropas inte av sidan: de läses ur
 * senaste hämtningen, så att en titt här aldrig bränner kvot.
 */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

export const LEVEL = {
  ok: ["Fungerar", "pill-ok"],
  warn: ["Varning", "pill-warn"],
  down: ["Nere", "pill-danger"],
  off: ["Av", ""],
};

const HEADLINE = {
  ok: "Allt fungerar",
  warn: "Något behöver tittas på",
  down: "Något är nere",
};

function row(c) {
  const [label, cls] = LEVEL[c.status] ?? [c.status, ""];
  const detail = c.detail ?? [];
  const body = `
    <span class="st-dot st-${esc(c.status)}" aria-hidden="true"></span>
    <span class="st-main"><b>${esc(c.label)}</b><span class="muted">${esc(c.summary)}</span></span>
    <span class="pill ${cls}">${esc(label)}</span>`;
  if (!detail.length) return `<li class="st-row">${body}</li>`;
  // Det som inte fungerar öppnas direkt; det som fungerar går att fälla ut.
  const open = c.status === "down" || c.status === "warn" ? " open" : "";
  return `<li><details class="st-row st-more"${open}>
    <summary>${body}</summary>
    <ul class="st-detail">${detail.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>
  </details></li>`;
}

export function statusView(report) {
  const counts = report.counts ?? {};
  const overall = report.overall ?? "ok";
  return `
    <div class="page-head">
      <div>
        <h1>Status</h1>
        <p class="muted">Backend, databas, kö, datakällor och externa tjänster. Kontrollerad
          ${esc(dateTime(report.checkedAt))} · ${esc(report.environment ?? "")}</p>
      </div>
      <button class="btn btn-primary" data-action="status-refresh">Kontrollera igen</button>
    </div>

    <div class="card st-summary st-summary-${esc(overall)}">
      <span class="st-dot st-${esc(overall)}" aria-hidden="true"></span>
      <div>
        <h2>${esc(HEADLINE[overall] ?? overall)}</h2>
        <p class="muted">${esc(counts.ok ?? 0)} fungerar · ${esc(counts.warn ?? 0)} varningar ·
          ${esc(counts.down ?? 0)} nere · ${esc(counts.off ?? 0)} avstängda</p>
      </div>
    </div>

    ${(report.groups ?? []).map((g) => `
      <div class="card">
        <h2>${esc(g.title)}</h2>
        ${g.key === "kallor" ? `<p class="muted">Läses ur senaste hämtningen – sidan anropar inte källorna själv,
          så att kvoten inte går åt. Röd betyder en kärnkälla som slutat hämta.</p>` : ""}
        <ul class="st-list">${(g.checks ?? []).map(row).join("")}</ul>
      </div>`).join("")}
  `;
}

/** En rad överst på Hem när något inte fungerar. Tom sträng när allt är grönt. */
export function statusBanner(report) {
  if (!report || !["warn", "down"].includes(report.overall)) return "";
  const bad = (report.groups ?? [])
    .flatMap((g) => g.checks ?? [])
    .filter((c) => c.status === report.overall)
    .map((c) => c.label);
  return `<button class="st-banner st-banner-${esc(report.overall)}" data-action="goto" data-view="status">
    <span class="st-dot st-${esc(report.overall)}" aria-hidden="true"></span>
    <span><b>${esc(HEADLINE[report.overall])}:</b> ${esc(bad.slice(0, 4).join(", "))}${bad.length > 4 ? " …" : ""}</span>
    <span class="todo-go">Status →</span>
  </button>`;
}

/** Kort rad för Hem: "2 nere · 1 varning · 12 ok". */
export function statusSummaryLine(report) {
  if (!report) return "";
  const c = report.counts ?? {};
  const parts = [];
  if (c.down) parts.push(`${c.down} nere`);
  if (c.warn) parts.push(`${c.warn} varning${c.warn === 1 ? "" : "ar"}`);
  parts.push(`${c.ok ?? 0} ok`);
  if (c.off) parts.push(`${c.off} av`);
  return parts.join(" · ");
}
