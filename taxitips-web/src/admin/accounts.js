import { dateTime } from "../portal/api.js";
import { esc } from "./sales.js";

/**
 * Kontohantering: hitta ett konto, spärra eller häva, och plattformens personal.
 *
 * En spärr stänger ute på servern, på varje anrop (fleet/accounts.py) -- det
 * här är bara vyn. Knapparna som ändrar visas bara för den som får ändra; en
 * säljare eller supportperson ser listorna men inte knapparna.
 */

const KIND = { company: "Företag", email: "E-postadress", user: "Konto" };
const ROLE = { company_owner: "Ägare", company_admin: "Administratör" };

export function konton(found, blocks, q = "", config = null) {
  const manage = !!config?.canManage;
  const accounts = found?.accounts ?? [];
  const active = (blocks?.blocks ?? []).filter((b) => !b.liftedAt);
  return `
    <div class="page-head">
      <div><h1>Konton och spärrar</h1>
        <p class="muted">Sök efter en e-postadress eller ett företag. Ett spärrat konto eller en spärrad
          adress får ingen data och kan inte registrera ett nytt företag.</p></div>
    </div>

    <form class="toolbar" id="accountSearch">
      <input name="q" value="${esc(q)}" placeholder="E-post eller företagsnamn" />
      <button class="btn btn-primary" type="submit">Sök</button>
    </form>

    ${q ? `<div class="card table-scroll">
      <h2>Träffar</h2>
      ${accounts.length ? `<table>
        <thead><tr><th>Konto</th><th>Företag</th><th>Senast inloggad</th><th></th></tr></thead>
        <tbody>${accounts.map((a) => `
          <tr>
            <td data-label="Konto"><b>${esc(a.email)}</b>
              ${a.staffRole ? `<span class="pill pill-warn">Personal: ${esc(a.staffRole)}</span>` : ""}
              ${a.blocked ? `<div class="error">Spärrad: ${esc(a.blocked.reason)}</div>` : ""}</td>
            <td data-label="Företag">${a.memberships.length ? a.memberships.map((m) => `
              <div><a href="#" data-action="open-company" data-id="${esc(m.companyId)}">${esc(m.companyName || m.companyId)}</a>
                <span class="muted">${esc(ROLE[m.role] ?? m.role)}${m.status === "active" ? "" : " · avstängd"}</span></div>`).join("")
              : '<span class="muted">Inget företag</span>'}</td>
            <td data-label="Senast inloggad">${esc(dateTime(a.lastSeenAt))}</td>
            <td data-label="">${manage && !a.blocked ? `<div class="btn-row">
              <button class="btn btn-danger" data-action="block-user" data-user="${esc(a.userId)}" data-email="${esc(a.email)}">Spärra kontot</button>
              <button class="btn btn-quiet" data-action="block-email" data-email="${esc(a.email)}">Spärra adressen</button>
            </div>` : ""}</td>
          </tr>`).join("")}</tbody></table>`
        : `<p class="muted">Inget konto matchar. Katalogen innehåller konton som loggat in sedan den infördes;
            en adress som aldrig loggat in kan ändå spärras nedan.</p>`}
    </div>` : ""}

    ${manage ? `<div class="card">
      <h2>Spärra en e-postadress</h2>
      <p class="muted">Gäller även en adress som ännu inte har något konto: den kan då inte registrera sig.</p>
      <form id="blockEmailForm" class="form-grid">
        <label>E-postadress<input name="email" type="email" required placeholder="namn@exempel.se" /></label>
        <label>Skäl<input name="reason" required placeholder="Varför spärras adressen?" /></label>
        <div class="btn-row span-2"><button class="btn btn-danger" type="submit">Spärra adressen</button></div>
      </form>
    </div>` : ""}

    <div class="card table-scroll">
      <h2>Aktiva spärrar <span class="muted">(${esc(active.length)})</span></h2>
      ${active.length ? `<table>
        <thead><tr><th>Vad</th><th>Skäl</th><th>Spärrad</th><th></th></tr></thead>
        <tbody>${active.map((b) => `
          <tr>
            <td data-label="Vad"><span class="pill pill-danger">${esc(KIND[b.kind] ?? b.kind)}</span>
              ${b.kind === "company"
                ? `<a href="#" data-action="open-company" data-id="${esc(b.value)}">${esc(b.label)}</a>`
                : `<b>${esc(b.label)}</b>`}</td>
            <td data-label="Skäl">${esc(b.reason)}</td>
            <td data-label="Spärrad">${esc(dateTime(b.createdAt))}<div class="muted">${esc(b.createdByEmail || "")}</div></td>
            <td data-label="">${manage ? `<button class="btn btn-quiet" data-action="block-lift" data-block="${esc(b.id)}">Häv</button>` : ""}</td>
          </tr>`).join("")}</tbody></table>`
        : '<p class="muted">Inga aktiva spärrar.</p>'}
    </div>
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
          <b>Plattformsadministratör</b> gör allt, även spärrar, avstängning och betalt utanför Stripe.</p></div>
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
