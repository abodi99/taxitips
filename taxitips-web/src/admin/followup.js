import { date, dateTime } from "../portal/api.js";

/**
 * Uppföljning: prov, uppsägning och churn (fleet/admin_followup.py).
 */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const FILTERS = [
  ["ring", "Att ringa"],
  ["prov", "Prov"],
  ["risk", "Avgår / betalning"],
  ["churn", "Avslutade"],
  ["alla", "Alla"],
];

const CLOSED = ["not_interested", "customer", "wrong_details"];

function due(row) {
  const next = row.followUp.nextContactAt;
  return !!next && new Date(next) <= new Date();
}

function hasSignupFlags(row) {
  return row.flags?.some((f) => f.level === "warn" || f.level === "danger");
}

function matches(row, filter) {
  const closed = CLOSED.includes(row.followUp.outcome);
  const seg = row.segment || "trial";
  switch (filter) {
    case "ring":
      if (closed) return false;
      if (seg === "past_due" || seg === "pending_cancel") return true;
      if (seg === "churn") {
        // Orsak saknas, eller uppföljning fortfarande öppen (ring igen / vill tillbaka).
        return (
          row.followUp.churnReason === "not_asked"
          || due(row)
          || ["call_back", "interested", "win_back", "no_answer"].includes(row.followUp.outcome)
        );
      }
      if (row.cardOnFile) return false;
      return (
        due(row)
        || row.stage === "ending"
        || row.stage === "ended"
        || row.stage === "not_started"
        || (row.followUp.outcome === "not_contacted" && hasSignupFlags(row))
      );
    case "prov":
      return seg === "trial";
    case "risk":
      return seg === "pending_cancel" || seg === "past_due";
    case "churn":
      return seg === "churn";
    default:
      return true;
  }
}

/** Kort status för tabellen: [ton, text, förklaring]. */
function stagePill(row) {
  const seg = row.segment || "trial";
  if (seg === "past_due") return ["pill-danger", "Förfallen betalning", "Kunden har slutat betala."];
  if (seg === "pending_cancel") {
    return ["pill-warn", "Uppsagt", row.accessUntil
      ? `Uppsagt – åtkomst till ${date(row.accessUntil)}`
      : "Uppsagt – väntar på slutdatum"];
  }
  if (seg === "churn") {
    return ["pill-danger", "Avslutad", row.accessUntil ? `Avslutad ${date(row.accessUntil)}` : "Avslutad kund"];
  }
  if (row.cardOnFile) return ["pill-ok", "Kort sparat", "Blir kund när provet slutar."];
  const days = Math.ceil(row.daysLeft ?? 0);
  switch (row.stage) {
    case "not_started":
      return ["pill-warn", "Ej startat", "Väntar på första telefonen."];
    case "ending":
      return ["pill-danger", days <= 1 ? "Slutar idag" : `Slutar om ${days} d`, `Provet slutar ${date(row.endsAt)}.`];
    case "active":
      return ["", `Prov · ${days} d kvar`, `Provet slutar ${date(row.endsAt)}.`];
    default:
      return ["pill-danger", "Provet slut", `Slutade ${date(row.endsAt)}.`];
  }
}

function phoneText(value) {
  const m = /^\+46(7\d)(\d{3})(\d{2})(\d{2})$/.exec(value ?? "");
  return m ? `0${m[1]}-${m[2]} ${m[3]} ${m[4]}` : (value ?? "");
}

function localDateInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function shortDay(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("sv-SE", { day: "numeric", month: "short" });
}

/** "Ring igen"-cellen: datum, rött när det är dags. */
export function nextCell(iso) {
  if (!iso) return '<span class="muted">—</span>';
  const isDue = new Date(iso) <= new Date();
  return `<span class="${isDue ? "fu-due" : ""}">${esc(isDue ? `Idag/sen · ${shortDay(iso)}` : shortDay(iso))}</span>`;
}

/** "Samtal"-cellen: antal och senaste. */
export function callsCell(attempts, lastIso) {
  if (!attempts) return '<span class="muted">—</span>';
  return `${esc(attempts)} st${lastIso ? ` <span class="muted">· ${esc(shortDay(lastIso))}</span>` : ""}`;
}

function flagList(flags) {
  if (!flags?.length) return "";
  return `<ul class="fu-flags">${flags.map((f) =>
    `<li class="fu-flag fu-${esc(f.level)}">${esc(f.text)}</li>`).join("")}</ul>`;
}

function warnCount(flags) {
  const n = (flags ?? []).filter((f) => f.level === "warn" || f.level === "danger").length;
  if (!n) return "";
  const title = flags.map((f) => f.text).join("\n");
  return ` <span class="fu-warnmark" title="${esc(title)}">⚠ ${n}</span>`;
}

function row(r, outcomes, churnReasons) {
  const [tone, label, title] = stagePill(r);
  const f = r.followUp;
  const seg = r.segment || "trial";
  const showChurn = seg !== "trial";
  const id = esc(r.companyId);
  const outcomeLabel = outcomes.find((o) => o.id === f.outcome)?.label ?? f.outcome;
  const phone = r.phone
    ? `<a class="fu-phone" href="tel:${esc(r.phone)}">${esc(phoneText(r.phone))}</a>`
    : '<span class="fu-nophone">Inget nummer</span>';

  // Detaljer som tidigare stod öppet på kortet — nu bara när raden fälls ut.
  const facts = [
    seg === "trial"
      ? `${esc(r.cars)} av ${esc(r.vehicleLimit)} ${r.vehicleLimit === 1 ? "bil" : "bilar"} · ${esc(r.phonesConnected)} ${r.phonesConnected === 1 ? "telefon kopplad" : "telefoner kopplade"}`
      : "",
    `Registrerad ${esc(date(r.createdAt))}`,
    r.email ? `<a href="mailto:${esc(r.email)}">${esc(r.email)}</a>` : "",
  ].filter(Boolean).join(" · ");
  const mails = r.mails?.length
    ? `<p class="muted">Mejl: ${r.mails.map((m) => `${esc(m.subject)} (${esc(date(m.sentAt))})`).join(" · ")}</p>`
    : seg === "trial" ? '<p class="muted">Inga mejl skickade än.</p>' : "";
  const hint = seg === "trial" && (r.stage === "ending" || r.stage === "ended")
    ? "Tips: förläng provet eller sätt en prisrabatt under Betalning innan du ringer."
    : showChurn ? "Tips: erbjud rabatt eller paus via Betalning om orsaken är pris eller säsong." : "";

  return `
    <tr class="fu-row" data-fu-row="${id}">
      <td>
        <span class="fu-name">${esc(r.legalName || r.name)}</span>${warnCount(r.flags)}
        <span class="fu-sub">${esc([r.orgNumber, r.kind === "person" ? "EF" : "", r.registryCity].filter(Boolean).join(" · "))}</span>
      </td>
      <td><span class="pill ${tone}" title="${esc(title)}">${esc(label)}</span></td>
      <td>
        <span class="fu-contact-name">${esc(r.contactName || "—")}</span>
        <span class="fu-sub">${phone}</span>
      </td>
      <td data-label="Utfall" data-fu-cell="outcome">${esc(outcomeLabel)}</td>
      <td data-label="Ring igen" data-fu-cell="next">${nextCell(f.nextContactAt)}</td>
      <td data-label="Samtal" data-fu-cell="calls">${callsCell(f.attempts, f.lastContactAt)}</td>
      <td class="fu-col-actions">
        <button type="button" class="btn btn-quiet btn-small fu-toggle" data-action="fu-toggle"
          data-company="${id}" aria-expanded="false" aria-controls="fu-detail-${id}">Logga samtal</button>
      </td>
    </tr>
    <tr class="fu-detail" id="fu-detail-${id}" hidden>
      <td colspan="7">
        <div class="fu-detail-grid">
          <div class="fu-info-col">
            <p>${facts}</p>
            ${r.statedCancelReason ? `<p>Kundens orsak vid uppsägning: <em>${esc(r.statedCancelReason)}</em></p>` : ""}
            ${flagList(r.flags)}
            ${mails}
            ${hint ? `<p class="muted fu-hint">${esc(hint)}</p>` : ""}
            <button class="linklike" type="button" data-action="open-company"
              data-id="${id}" data-tab="betalning">Öppna kunden →</button>
          </div>
          <form class="fu-form" data-form="followup" data-fu-company="${id}">
            <label>Utfall
              <select name="outcome">
                ${outcomes.map((o) => `<option value="${esc(o.id)}" ${o.id === f.outcome ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
              </select>
            </label>
            ${showChurn ? `<label>Avhoppsorsak
              <select name="churnReason">
                ${churnReasons.map((o) => `<option value="${esc(o.id)}" ${o.id === (f.churnReason || "not_asked") ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
              </select>
            </label>` : ""}
            <label>Ring igen
              <input type="date" name="nextContactAt" value="${esc(localDateInput(f.nextContactAt))}" />
            </label>
            <label class="fu-note">Anteckning
              <textarea name="note" rows="2" placeholder="${showChurn ? "Vad sa de om varför de lämnar?" : "Vad sa de?"}">${esc(f.note)}</textarea>
            </label>
            <div class="fu-actions">
              <label class="fu-check"><input type="checkbox" name="contacted" checked /> Jag ringde nu</label>
              <button class="btn btn-primary btn-small" type="submit">Spara</button>
            </div>
            <p class="muted fu-meta"></p>
          </form>
        </div>
      </td>
    </tr>`;
}

export function uppfoljning(data, filter = "ring") {
  const all = data.followUps ?? [];
  const rows = all.filter((r) => matches(r, filter));
  const outcomes = data.outcomes ?? [];
  const churnReasons = data.churnReasons ?? [];
  const tabs = FILTERS.map(([id, label]) => `
    <button type="button" role="tab" class="crm-tab" data-action="fu-filter" data-filter="${id}"
      aria-selected="${id === filter}">${esc(label)}<span class="crm-tab-n">${esc(all.filter((r) => matches(r, id)).length)}</span></button>`).join("");
  const table = rows.length
    ? `<div class="table-scroll">
        <table class="fu-table" data-outcomes="${esc(JSON.stringify(outcomes.map((o) => [o.id, o.label])))}">
          <thead><tr>
            <th>Kund</th><th>Status</th><th>Kontakt</th><th>Senaste utfall</th><th>Ring igen</th><th>Samtal</th><th></th>
          </tr></thead>
          <tbody>${rows.map((r) => row(r, outcomes, churnReasons)).join("")}</tbody>
        </table>
      </div>`
    : '<div class="crm-empty"><p>Ingen att ringa här just nu.</p></div>';
  return `
    <div class="page-head">
      <div><h1>Uppföljning</h1>
        <p class="muted">Prov som tar slut, uppsägningar, missade betalningar och avslutade kunder.</p></div>
    </div>
    <div class="crm-tabs-row">
      <div class="crm-tabs" role="tablist" aria-label="Filter">${tabs}</div>
    </div>
    ${table}
  `;
}

export function followUpBody(form) {
  const data = new FormData(form);
  const body = {
    outcome: String(data.get("outcome") ?? ""),
    note: String(data.get("note") ?? ""),
    nextContactAt: String(data.get("nextContactAt") ?? ""),
    contacted: data.get("contacted") === "on",
  };
  const churn = data.get("churnReason");
  if (churn != null) body.churnReason = String(churn);
  return body;
}
