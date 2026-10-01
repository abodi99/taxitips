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

function stagePill(row) {
  const seg = row.segment || "trial";
  if (seg === "past_due") return ["pill-danger", "Förfallen betalning"];
  if (seg === "pending_cancel") {
    return ["pill-warn", row.accessUntil
      ? `Uppsagt – åtkomst till ${date(row.accessUntil)}`
      : "Uppsagt – väntar på slutdatum"];
  }
  if (seg === "churn") {
    return ["pill-danger", row.accessUntil
      ? `Avslutad ${date(row.accessUntil)}`
      : "Avslutad kund"];
  }
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

function row(r, outcomes, churnReasons) {
  const [cls, label] = stagePill(r);
  const f = r.followUp;
  const seg = r.segment || "trial";
  const showChurn = seg !== "trial";
  const phone = r.phone
    ? `<a class="fu-phone" href="tel:${esc(r.phone)}">${esc(phoneText(r.phone))}</a>`
    : '<span class="fu-flag fu-danger">Inget telefonnummer</span>';
  const mails = r.mails?.length
    ? `<p class="muted fu-mails">Mejl: ${r.mails.map((m) =>
      `${esc(m.subject)} (${esc(date(m.sentAt))})`).join(" · ")}</p>`
    : seg === "trial"
      ? '<p class="muted fu-mails">Inga mejl skickade än.</p>'
      : "";
  const stated = r.statedCancelReason
    ? `<p class="muted fu-stated">Kundens angivna orsak vid uppsägning: <em>${esc(r.statedCancelReason)}</em></p>`
    : "";
  const trialMeta = seg === "trial"
    ? `<p class="muted">
        ${esc(r.cars)} av ${esc(r.vehicleLimit)} ${r.vehicleLimit === 1 ? "bil" : "bilar"} ·
        ${esc(r.phonesConnected)} ${r.phonesConnected === 1 ? "telefon kopplad" : "telefoner kopplade"} ·
        registrerad ${esc(date(r.createdAt))}
      </p>`
    : `<p class="muted">Registrerad ${esc(date(r.createdAt))}</p>`;
  // Rabatt och förlängt prov bor på kundkortet (Betalning) — här bara tipset.
  const offerHint = seg === "trial" && (r.stage === "ending" || r.stage === "ended")
    ? `<p class="muted fu-hint">Tips: förläng provet eller sätt en prisrabatt under Betalning innan du ringer.</p>`
    : (seg === "pending_cancel" || seg === "churn" || seg === "past_due")
      ? `<p class="muted fu-hint">Tips: erbjud rabatt eller paus via Betalning om orsaken är pris eller säsong.</p>`
      : "";
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
      ${trialMeta}
      ${offerHint}
      ${stated}
      ${flagList(r.flags)}
      ${mails}

      <form class="fu-form" data-form="followup" data-company="${esc(r.companyId)}">
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
  const churnReasons = data.churnReasons ?? [];
  return `
    <div class="page-head">
      <div><h1>Uppföljning</h1>
        <p class="muted">Prov som tar slut, kunder som sagt upp eller slutat betala, och avslutade abonnemang
        — inte friska betalande kunder. Mejlen med betalningslänken går ut automatiskt; samtalet avgör provet,
        avhoppsorsaken dokumenteras här.</p></div>
    </div>
    <div class="chips" role="tablist" aria-label="Filter">
      ${FILTERS.map(([id, label]) => `<button class="chip" role="tab" data-action="fu-filter" data-filter="${id}"
        aria-selected="${id === filter}">${esc(label)} <span class="muted">${esc(all.filter((r) => matches(r, id)).length)}</span></button>`).join("")}
    </div>
    ${rows.length ? rows.map((r) => row(r, outcomes, churnReasons)).join("") : '<div class="card"><p class="muted">Ingen att ringa här just nu.</p></div>'}
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
