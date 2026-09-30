import { date, dateTime } from "../portal/api.js";

/**
 * Uppföljning: listan säljaren ringer från (fleet/admin_followup.py).
 *
 * Servern bestämmer ordningen (utlovade samtal först, sedan prov som tar slut,
 * sedan de som redan slutat) och flaggorna (fleet/signup_checks.py). Den här
 * filen ritar bara -- ingen regel om vem som ska ringas bor här.
 */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const FILTERS = [
  ["ring", "Att ringa"],
  ["pagar", "Pågår"],
  ["slut", "Slutade"],
  ["alla", "Alla"],
];

const CLOSED = ["not_interested", "customer", "wrong_details"];

function due(row) {
  const next = row.followUp.nextContactAt;
  return !!next && new Date(next) <= new Date();
}

function matches(row, filter) {
  const closed = CLOSED.includes(row.followUp.outcome);
  switch (filter) {
    case "ring":
      return !closed && !row.cardOnFile && (
        due(row) || row.stage === "ending" || row.stage === "ended"
        || row.followUp.outcome === "not_contacted"
      );
    case "pagar":
      return row.stage === "active" || row.stage === "ending" || row.stage === "not_started";
    case "slut":
      return row.stage === "ended";
    default:
      return true;
  }
}

function stagePill(row) {
  if (row.cardOnFile) return ["pill-ok", "Kort sparat – blir kund vid provslut"];
  const days = row.daysLeft;
  switch (row.stage) {
    case "not_started":
      return ["pill-warn", "Väntar på första telefonen"];
    case "ending":
      return ["pill-danger", days <= 1 ? "Slutar inom ett dygn" : `Slutar om ${Math.ceil(days)} dagar`];
    case "active":
      return ["pill-warn", `Pågår – ${Math.ceil(days)} dagar kvar`];
    default:
      return ["pill-danger", `Slutade ${date(row.endsAt)}`];
  }
}

/** "+46708123491" -> "070-812 34 91". Bara för visning; länken bär E.164. */
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

function flagList(flags) {
  if (!flags?.length) return "";
  return `<ul class="fu-flags">${flags.map((f) =>
    `<li class="fu-flag fu-${esc(f.level)}">${esc(f.text)}</li>`).join("")}</ul>`;
}

function row(r, outcomes) {
  const [cls, label] = stagePill(r);
  const f = r.followUp;
  const phone = r.phone
    ? `<a class="fu-phone" href="tel:${esc(r.phone)}">${esc(phoneText(r.phone))}</a>`
    : '<span class="fu-flag fu-danger">Inget telefonnummer</span>';
  const mails = r.mails?.length
    ? `<p class="muted fu-mails">Mejl: ${r.mails.map((m) =>
      `${esc(m.subject)} (${esc(date(m.sentAt))})`).join(" · ")}</p>`
    : '<p class="muted fu-mails">Inga mejl skickade än.</p>';
  return `
    <article class="card fu-card">
      <header class="fu-head">
        <div>
          <h2 class="fu-name">${esc(r.legalName || r.name)}</h2>
          <p class="muted mono">${esc(r.orgNumber)}${r.kind === "person" ? " · enskild firma" : ""}
            ${r.registryCity ? ` · ${esc(r.registryCity)}` : ""}</p>
        </div>
        <span class="pill ${cls}">${esc(label)}</span>
      </header>

      <p class="fu-contact">
        <b>${esc(r.contactName || "Kontakt saknas")}</b> · ${phone}
        ${r.email ? ` · <a href="mailto:${esc(r.email)}">${esc(r.email)}</a>` : ""}
      </p>
      <p class="muted">
        ${esc(r.cars)} av ${esc(r.vehicleLimit)} ${r.vehicleLimit === 1 ? "bil" : "bilar"} ·
        ${esc(r.phonesConnected)} ${r.phonesConnected === 1 ? "telefon kopplad" : "telefoner kopplade"} ·
        registrerad ${esc(date(r.createdAt))}
      </p>
      ${flagList(r.flags)}
      ${mails}

      <form class="fu-form" data-form="followup" data-company="${esc(r.companyId)}">
        <label>Utfall
          <select name="outcome">
            ${outcomes.map((o) => `<option value="${esc(o.id)}" ${o.id === f.outcome ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
          </select>
        </label>
        <label>Ring igen
          <input type="date" name="nextContactAt" value="${esc(localDateInput(f.nextContactAt))}" />
        </label>
        <label class="fu-note">Anteckning
          <textarea name="note" rows="2" placeholder="Vad sa de?">${esc(f.note)}</textarea>
        </label>
        <label class="fu-check"><input type="checkbox" name="contacted" /> Jag ringde nu</label>
        <div class="fu-actions">
          <button class="btn btn-primary btn-small" type="submit">Spara</button>
          <button class="btn btn-quiet btn-small" type="button" data-action="open-company"
            data-id="${esc(r.companyId)}" data-tab="betalning">Öppna kunden →</button>
        </div>
        <p class="muted fu-meta">${f.attempts ? `${esc(f.attempts)} samtal · senast ${esc(dateTime(f.lastContactAt))}` : "Inte kontaktad än"}</p>
      </form>
    </article>`;
}

export function uppfoljning(data, filter = "ring") {
  const all = data.followUps ?? [];
  const rows = all.filter((r) => matches(r, filter));
  const outcomes = data.outcomes ?? [];
  return `
    <div class="page-head">
      <div><h1>Uppföljning</h1>
        <p class="muted">Prov som pågår eller slutat de senaste 60 dagarna, i den ordning de ska ringas.
        Mejlen med betalningslänken går ut automatiskt – samtalet är det som avgör.</p></div>
    </div>
    <div class="chips" role="tablist" aria-label="Filter">
      ${FILTERS.map(([id, label]) => `<button class="chip" role="tab" data-action="fu-filter" data-filter="${id}"
        aria-selected="${id === filter}">${esc(label)} <span class="muted">${esc(all.filter((r) => matches(r, id)).length)}</span></button>`).join("")}
    </div>
    ${rows.length ? rows.map((r) => row(r, outcomes)).join("") : '<div class="card"><p class="muted">Ingen att ringa här just nu.</p></div>'}
  `;
}

/** Formulärets värden i den form servern tar emot. */
export function followUpBody(form) {
  const data = new FormData(form);
  return {
    outcome: String(data.get("outcome") ?? ""),
    note: String(data.get("note") ?? ""),
    nextContactAt: String(data.get("nextContactAt") ?? ""),
    contacted: data.get("contacted") === "on",
  };
}
