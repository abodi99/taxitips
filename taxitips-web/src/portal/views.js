import { COUNTIES, countyName, date, dateTime, money } from "./api.js";

/**
 * Portalens fem vyer, som rena funktioner från data till HTML.
 *
 * Ingen vy räknar ut ett belopp. Allt som ser ut som pengar kommer från
 * backendens uträkning (fleet/pricing.py) -- en andra prismotor i webbläsaren
 * hade kunnat visa rätt när fakturan blev fel, vilket är värre än att inte
 * visa något alls.
 */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

function statusPill(status) {
  const map = {
    active: ["pill-ok", "Aktiv"],
    trialing: ["pill-warn", "Provperiod"],
    trial: ["pill-warn", "Provbil"],
    past_due: ["pill-danger", "Förfallen"],
    canceled: ["pill-danger", "Avslutad"],
    pending_cancel: ["pill-warn", "Avslutas"],
    none: ["", "Inget abonnemang"],
  };
  const [cls, label] = map[status] ?? ["", status ?? "—"];
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

/* --- Översikt ---------------------------------------------------------- */

export function oversikt(data) {
  const sub = data.subscription ?? {};
  const trial = data.trial;
  const reviews = (data.reviews ?? []).filter((r) => r.status === "open");

  const notices = [];
  if (sub.cancelAtPeriodEnd) {
    notices.push(`<div class="notice notice-danger">
      <b>Abonnemanget är uppsagt.</b> Allt fungerar som vanligt till
      ${esc(date(sub.accessUntil))}. Du kan ångra uppsägningen fram till dess.
      <div class="btn-row"><button class="btn btn-quiet" data-action="undo-cancel">Ångra uppsägningen</button></div>
    </div>`);
  }
  if (sub.status === "past_due") {
    notices.push(`<div class="notice notice-danger">
      <b>Betalningen har inte gått igenom.</b>
      ${sub.graceUntil ? `Åtkomsten gäller till ${esc(dateTime(sub.graceUntil))}.` : "Ingen betalningsfrist gäller för den här betalningen."}
      Uppdatera betalmetoden under <em>Abonnemang och fakturor</em>.
    </div>`);
  }
  if (sub.renewalStopped) {
    notices.push(`<div class="notice notice-danger">
      <b>Förnyelsen är stoppad.</b> Inga nya månadsavgifter tillkommer.
      En obetald faktura hanteras separat -- kontakta oss så reder vi ut den.
    </div>`);
  }
  for (const review of reviews) {
    notices.push(
      `<div class="notice"><b>Under granskning.</b> ${esc(review.message)}</div>`,
    );
  }
  if (data.company?.legacyAccessUntil) {
    notices.push(`<div class="notice">
      <b>Övergång pågår.</b> Era telefoner fungerar som förut till
      ${esc(date(data.company.legacyAccessUntil))}. Lägg upp bilarna och anslut
      telefonerna under <em>Bilar och telefoner</em> före dess.
    </div>`);
  }

  return `
    ${notices.join("")}
    <div class="grid">
      <div class="stat"><span class="muted">Abonnemang</span><b>${statusPill(sub.status)}</b></div>
      <div class="stat"><span class="muted">Köpta billicenser</span><b>${esc(data.licenseCount ?? 0)}</b></div>
      <div class="stat"><span class="muted">Extra län</span><b>${esc(data.extraCountyCount ?? 0)}</b></div>
      <div class="stat"><span class="muted">Nästa betalning</span><b>${esc(date(sub.currentPeriodEnd))}</b></div>
    </div>

    ${
      trial
        ? `<div class="card">
             <h2>Provperiod</h2>
             <p>${esc(trial.vehiclesUsed)} av ${esc(trial.vehicleLimit)} provbilar.
             ${trial.endsAt ? `Provet slutar ${esc(dateTime(trial.endsAt))}.` : "Provet startar när den första telefonen ansluts."}</p>
             <p class="muted">Utan en beställning avslutas provet utan debitering.
             Provbilar blir aldrig debiterade licenser av sig själva -- du väljer
             vilka bilar som fortsätter.</p>
           </div>`
        : ""
    }

    ${
      sub.introEndsAt
        ? `<div class="card"><h2>Introduktionspris</h2>
             <p>Gäller till ${esc(date(sub.introEndsAt))}. Bilar som läggs till
             senare får den tid som är kvar.</p></div>`
        : ""
    }

    <div class="card">
      <h2>Bilar just nu</h2>
      ${licensTabell(data)}
    </div>

    ${vantandeAndringar(data)}
  `;
}

function licensTabell(data) {
  const rows = data.licenses ?? [];
  if (!rows.length) {
    return `<p class="muted">Inga bilar upplagda än.</p>`;
  }
  return `<table>
    <thead><tr>
      <th>Bil</th><th>Status</th><th>Aktiv telefon</th><th>Län</th>
    </tr></thead>
    <tbody>${rows
      .map(
        (row) => `<tr>
          <td data-label="Bil"><b>${esc(row.vehicle || "—")}</b>
            ${row.assignmentKind === "temporary" ? '<br /><span class="pill pill-warn">Ersättningsbil</span>' : ""}</td>
          <td data-label="Status">${statusPill(row.status)}</td>
          <td data-label="Aktiv telefon">${
            row.activePhone
              ? `${esc(row.activePhone.label)}<br /><span class="muted">sedan ${esc(dateTime(row.activePhone.since))}</span>`
              : '<span class="muted">Ingen i tjänst</span>'
          }</td>
          <td data-label="Län">${(row.counties ?? []).map((c) => esc(countyName(c))).join(", ") || "—"}</td>
        </tr>`,
      )
      .join("")}</tbody>
  </table>`;
}

function vantandeAndringar(data) {
  const pending = data.pendingChanges ?? [];
  if (!pending.length) return "";
  const label = {
    reduce_licenses: "Billicenser avslutas",
    remove_county: "Extra län tas bort",
    change_base_county: "Baslänet byts",
    cancel_subscription: "Abonnemanget avslutas",
  };
  return `<div class="card">
    <h2>Väntande ändringar</h2>
    <p class="muted">Träder i kraft vid nästa förnyelse. Fram till dess gäller
    det du har nu.</p>
    <table><thead><tr><th>Ändring</th><th>Gäller från</th></tr></thead>
    <tbody>${pending
      .map(
        (p) =>
          `<tr><td data-label="Ändring">${esc(label[p.kind] ?? p.kind)}</td>
               <td data-label="Gäller från">${esc(date(p.effectiveAt))}</td></tr>`,
      )
      .join("")}</tbody></table>
  </div>`;
}

/* --- Bilar och telefoner ------------------------------------------------ */

export function bilar(data) {
  const canManage = (data.permissions ?? []).includes("manage_devices");
  const rows = data.licenses ?? [];

  return `
    <div class="card">
      <h2>Lägg till en bil</h2>
      <p class="muted">Registreringsnumret identifierar bilen. En billicens
      gäller en registrerad bil -- inte en plats som roterar mellan bilar.</p>
      <form id="vehicleForm">
        <label for="plate">Registreringsnummer</label>
        <input id="plate" name="plate" required autocomplete="off" />
        <label for="vlabel">Namn (valfritt)</label>
        <input id="vlabel" name="label" autocomplete="off" placeholder="Nattbil, Bil 3 …" />
        <div class="btn-row"><button class="btn btn-primary" type="submit">Lägg till bil</button></div>
      </form>
    </div>

    ${rows
      .map(
        (row) => `<div class="card">
        <h2>${esc(row.vehicle || "Bil utan registreringsnummer")} ${statusPill(row.status)}</h2>
        <p class="muted">Baslän: ${esc(countyName(row.baseCounty))}${
          row.scheduledBaseCounty
            ? ` → byts till ${esc(countyName(row.scheduledBaseCounty))} vid nästa förnyelse`
            : ""
        }</p>

        <h3>Godkända telefoner</h3>
        ${
          (row.approvedPhones ?? []).length
            ? `<table><thead><tr><th>Telefon</th><th>Godkänd</th><th></th></tr></thead><tbody>
                ${row.approvedPhones
                  .map(
                    (p) => `<tr>
                      <td data-label="Telefon">${esc(p.label || "Telefon")}
                        ${
                          row.activePhone && row.activePhone.deviceId === p.deviceId
                            ? ' <span class="pill pill-ok">I tjänst</span>'
                            : ""
                        }</td>
                      <td data-label="Godkänd">${esc(date(p.approvedAt))}</td>
                      <td data-label="">${
                        canManage
                          ? `<button class="btn btn-danger" data-action="block" data-approval="${esc(p.approvalId)}">Spärra</button>`
                          : ""
                      }</td>
                    </tr>`,
                  )
                  .join("")}
               </tbody></table>`
            : '<p class="muted">Ingen telefon godkänd för den här bilen än.</p>'
        }
        ${
          canManage
            ? `<div class="btn-row">
                 <button class="btn btn-primary" data-action="pair"
                   data-license="${esc(row.licenseId)}" data-vehicle="${esc(row.vehicleId)}"
                   data-plate="${esc(row.vehicle)}">Anslut en telefon</button>
                 <button class="btn btn-quiet" data-action="change-vehicle"
                   data-license="${esc(row.licenseId)}">Byt bil</button>
               </div>
               <p class="muted">En spärr gäller direkt, även om telefonen är
               borta. Byten mellan godkända skifttelefoner är avgiftsfria och
               har ingen kvot.</p>`
            : ""
        }
      </div>`,
      )
      .join("")}
  `;
}

/* --- Län och filter ----------------------------------------------------- */

export function lan(data) {
  const rows = data.licenses ?? [];
  const options = Object.entries(COUNTIES)
    .map(([code, name]) => `<option value="${esc(code)}">${esc(name)}</option>`)
    .join("");

  return `
    <div class="card">
      <h2>Så fungerar länen</h2>
      <p>Länsrättigheterna hör till <b>bilen</b>, inte till företaget. Alla
      utlovade datakategorier ingår i bilens köpta län -- kategorier och
      kommuner är filter i appen, inte separata paket.</p>
      <p class="muted">Extra län börjar gälla när tilläggsbetalningen har
      lyckats, och kostar en andel av återstående period. Att ta bort ett län
      eller byta baslän gäller vid nästa förnyelse. Behöver du ett nytt län
      direkt: köp det som tillägg nu och schemalägg baslänsbytet -- tillägget
      tas bort automatiskt vid bytet, så ingen betalar två gånger.</p>
    </div>

    ${rows
      .map(
        (row) => `<div class="card">
        <h2>${esc(row.vehicle || "Bil")}</h2>
        <p>Baslän: <b>${esc(countyName(row.baseCounty))}</b>${
          row.scheduledBaseCounty
            ? ` <span class="pill pill-warn">Byts till ${esc(countyName(row.scheduledBaseCounty))}</span>`
            : ""
        }</p>
        <p>Extra län: ${
          (row.extraCounties ?? []).length
            ? row.extraCounties.map((c) => esc(countyName(c))).join(", ")
            : '<span class="muted">inga</span>'
        }</p>
        <div class="btn-row">
          <label class="visually-hidden" for="county-${esc(row.licenseId)}">Län</label>
          <select id="county-${esc(row.licenseId)}" data-county-for="${esc(row.licenseId)}">${options}</select>
          <button class="btn btn-primary" data-action="add-county" data-license="${esc(row.licenseId)}">Köp extra län</button>
          <button class="btn btn-quiet" data-action="change-base" data-license="${esc(row.licenseId)}">Byt baslän</button>
        </div>
      </div>`,
      )
      .join("")}
  `;
}

/* --- Abonnemang och fakturor -------------------------------------------- */

export function abonnemang(data, orders) {
  const sub = data.subscription ?? {};
  const canBuy = (data.permissions ?? []).includes("purchase");
  const canCancel = (data.permissions ?? []).includes("cancel_subscription");

  return `
    <div class="card">
      <h2>Abonnemang</h2>
      <table><tbody>
        <tr><td data-label="Status">Status</td><td data-label="">${statusPill(sub.status)}</td></tr>
        <tr><td data-label="Period">Innevarande period</td><td data-label="">${esc(date(sub.currentPeriodStart))} – ${esc(date(sub.currentPeriodEnd))}</td></tr>
        <tr><td data-label="Nästa betalning">Nästa betalning</td><td data-label="">${esc(date(sub.currentPeriodEnd))}</td></tr>
        <tr><td data-label="Prisversion">Prisversion</td><td data-label="">${esc(sub.priceVersion ?? "—")}</td></tr>
        ${sub.introEndsAt ? `<tr><td data-label="Introduktion">Introduktionen slutar</td><td data-label="">${esc(date(sub.introEndsAt))}</td></tr>` : ""}
        ${sub.graceUntil ? `<tr><td data-label="Betalningsfrist">Betalningsfrist</td><td data-label="">${esc(dateTime(sub.graceUntil))}</td></tr>` : ""}
      </tbody></table>
      ${
        canBuy
          ? `<div class="btn-row">
               <button class="btn btn-primary" data-action="add-license">Lägg till en bil</button>
             </div>`
          : ""
      }
      ${
        canCancel
          ? sub.cancelAtPeriodEnd
            ? `<div class="btn-row"><button class="btn btn-quiet" data-action="undo-cancel">Ångra uppsägningen</button></div>`
            : `<div class="btn-row"><button class="btn btn-danger" data-action="cancel">Säg upp abonnemanget</button></div>
               <p class="muted">Uppsägningen stoppar nästa period. Du behåller
               åtkomsten den betalda perioden ut -- ingen extra frist, inget
               samtal som krävs, och du kan ångra dig fram till slutdatumet.</p>`
          : ""
      }
    </div>

    <div class="card">
      <h2>Beställningar och fakturor</h2>
      ${
        (orders ?? []).length
          ? `<table><thead><tr>
               <th>Datum</th><th>Ändring</th><th>Status</th><th>Betalt nu</th><th>Nästa period</th>
             </tr></thead><tbody>
             ${orders
               .map(
                 (o) => `<tr>
                   <td data-label="Datum">${esc(date(o.createdAt))}</td>
                   <td data-label="Ändring">${esc(orderKind(o.kind))}</td>
                   <td data-label="Status">${esc(orderStatus(o.status))}</td>
                   <td data-label="Betalt nu">${esc(money(o.totalNowOre, o.currency))}</td>
                   <td data-label="Nästa period">${esc(money(o.nextPeriodTotalOre, o.currency))}</td>
                 </tr>`,
               )
               .join("")}
             </tbody></table>
             <p class="muted">Beloppen är inklusive moms. Fakturorna finns kvar
             här även om liveinformationen är spärrad.</p>`
          : '<p class="muted">Inga beställningar än.</p>'
      }
    </div>
  `;
}

function orderKind(kind) {
  return (
    {
      initial: "Första beställningen",
      add_license: "Fler billicenser",
      add_county: "Extra län",
      reduce: "Minskning",
      change_base_county: "Byte av baslän",
      renewal: "Förnyelse",
    }[kind] ?? kind
  );
}

function orderStatus(status) {
  return (
    {
      draft: "Utkast",
      pending_payment: "Väntar på betalning",
      paid: "Betald",
      applied: "Verkställd",
      failed: "Misslyckad",
      canceled: "Avbruten",
      scheduled: "Schemalagd",
    }[status] ?? status
  );
}

/* --- Företag och behörigheter ------------------------------------------- */

export function foretag(data) {
  const company = data.company ?? {};
  const twoFactor = data.twoFactor ?? {};
  return `
    <div class="card">
      <h2>Företaget</h2>
      <table><tbody>
        <tr><td data-label="Namn">Namn</td><td data-label="">${esc(company.name)}</td></tr>
        <tr><td data-label="Organisationsnummer">Organisationsnummer</td><td data-label="">${esc(company.orgNumber || "—")}</td></tr>
        <tr><td data-label="Land">Land</td><td data-label="">${esc(company.country)}</td></tr>
        <tr><td data-label="Verifiering">Verifiering</td><td data-label="">${esc(verification(company.verificationStatus))}</td></tr>
        <tr><td data-label="Din roll">Din roll</td><td data-label="">${esc(roleName(data.role))}</td></tr>
      </tbody></table>
      <p class="muted">Ett organisationsnummer eller en verifierad e-post är
      inte i sig bevis på behörighet att företräda företaget. Byte av
      organisationsnummer är ett byte av avtalspart och granskas.</p>
    </div>

    <div class="card">
      <h2>Tvåfaktorsautentisering</h2>
      <p>${
        twoFactor.enforced
          ? twoFactor.satisfied
            ? '<span class="ok">Din session är tvåfaktorsäkrad.</span>'
            : '<span class="error">Krävs för köp, uppsägning och ägarbyte. Logga in med tvåfaktor.</span>'
          : "Inte påslaget än. Vi meddelar i god tid innan det börjar krävas."
      }</p>
    </div>

    <div class="card">
      <h2>Ägarroll</h2>
      <p class="muted">Ägarrollen överförs i två steg: du begär bytet med en
      ny inloggning, och mottagaren accepterar. Den sista ägaren går inte att
      ta bort medan ett aktivt abonnemang löper.</p>
    </div>

    <div class="card">
      <h2>Avsluta företagskontot</h2>
      <p class="muted">Stoppar framtida förnyelse. Att ta bort förare eller
      avinstallera appen avslutar inte abonnemanget -- det här gör det.</p>
      ${
        (data.permissions ?? []).includes("close_account")
          ? '<div class="btn-row"><button class="btn btn-danger" data-action="close-account">Avsluta kontot</button></div>'
          : '<p class="muted">Bara företagsägaren kan avsluta kontot.</p>'
      }
    </div>
  `;
}

function verification(status) {
  return (
    {
      unverified: "Inte verifierad",
      pending_review: "Under granskning",
      verified: "Verifierad",
      rejected: "Avvisad",
    }[status] ?? status
  );
}

function roleName(role) {
  return (
    {
      company_owner: "Företagsägare",
      fleet_admin: "Fordonsadministratör",
      finance: "Ekonomiansvarig",
      driver: "Förare",
      // `??` och `||` får inte blandas utan parenteser -- det är ett syntaxfel,
      // inte en stilfråga.
    }[role] ?? (role || "—")
  );
}

/* --- Prisunderlaget kunden godkänner ------------------------------------ */

export function quoteHtml(quote) {
  const now = quote.now ?? {};
  const next = quote.nextPeriod ?? {};
  const lines = (now.lines ?? []).length ? now.lines : (next.lines ?? []);
  return `
    <div class="quote-lines">
      ${lines
        .map(
          (l) => `<div>${esc(l.label)} × ${esc(l.quantity)} —
            ${esc(money(l.amount_ore, now.currency))}
            ${l.note ? `<br /><span class="muted">${esc(l.note)}</span>` : ""}</div>`,
        )
        .join("")}
    </div>
    <div>Att betala nu (exkl. moms): ${esc(money(now.amountOre, now.currency))}</div>
    <div>Moms: ${esc(money(now.vatOre, now.currency))}</div>
    <div class="quote-total">Att betala nu: ${esc(money(now.totalOre, now.currency))}</div>
    <div class="muted">Nästa period (${esc(date(quote.nextPeriodStart))}):
      ${esc(money(next.totalOre, next.currency))} inkl. moms</div>
  `;
}
