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

/**
 * "Fortsätt med provbilarna": dit mejlen före och efter provslut länkar
 * (portal#fortsatt). Under pågående prov: spara kort för auto-förnyelse.
 * Efter prov utan kort: vanlig beställning (betala nu).
 */
/**
 * Var kunden står i fortsättningen efter provet. Översiktens kort och
 * medlemskapet under Abonnemang läser samma svar, så att de aldrig visar två
 * olika steg för samma bolag.
 *
 *   card_on_file -- kortet är sparat; första dragningen vid provets slut
 *   finish_card  -- bilarna är bekräftade men kortet inte sparat hos Stripe
 *   commit       -- pågående prov; bekräfta bilar och spara kort
 *   pay          -- provet är slut utan kort; vanlig beställning
 */
export function continueState(data) {
  const cars = data.continueVehicles ?? [];
  const canBuy = (data.permissions ?? []).includes("purchase");
  if (!cars.length || !canBuy) return null;
  const trial = data.trial;
  const activeTrial = trial && ["pending", "active"].includes(trial.status);
  if (activeTrial && trial.cardOnFile === true) return { kind: "card_on_file", cars, trial };
  if (activeTrial && trial.committed === true && trial.paymentUrl) {
    return { kind: "finish_card", cars, trial };
  }
  if (activeTrial) return { kind: "commit", cars, trial };
  return { kind: "pay", cars, trial };
}

function continueCard(data) {
  const state = continueState(data);
  if (!state) return "";
  const { cars, trial } = state;
  const n = cars.length;

  if (state.kind === "card_on_file") {
    return `<div class="card continue-card" id="fortsatt">
      <h2>Auto-förnyelse är klar</h2>
      <p>${cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ")}</p>
      <p class="muted">Kortet är sparat. Första dragningen sker
        ${esc(date(trial.firstChargeAt || trial.endsAt))} när provet tar slut,
        sedan varje månad tills ni säger upp.</p>
      <div class="btn-row">
        <button class="btn btn-quiet" data-action="cancel-trial-commit">Avbryt auto-förnyelse</button>
      </div>
    </div>`;
  }

  if (state.kind === "finish_card") {
    return `<div class="card continue-card" id="fortsatt">
      <h2>Slutför kortet</h2>
      <p>${cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ")}</p>
      <p class="muted">Ni har påbörjat fortsättningen. Öppna Stripes sida och
        spara kortet -- ingen dragning sker förrän provet tar slut.</p>
      <div class="btn-row">
        <a class="btn btn-primary" href="${esc(trial.paymentUrl)}" target="_blank" rel="noopener">Öppna betalsidan</a>
        <button class="btn btn-quiet" data-action="cancel-trial-commit">Avbryt</button>
      </div>
    </div>`;
  }

  if (state.kind === "commit") {
    return `<div class="card continue-card" id="fortsatt">
      <h2>Fortsätt med ${esc(n)} ${n === 1 ? "bil" : "bilar"}</h2>
      <p>${cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ")}</p>
      <p class="muted">Du ser månadspriset innan du godkänner. Kortet sparas i
        Stripe; första dragningen sker när provet tar slut
        (${esc(date(trial.endsAt))}), sedan automatiskt varje månad.</p>
      <div class="btn-row"><button class="btn btn-primary" data-action="continue-trial">Bekräfta bilar och spara kort</button></div>
    </div>`;
  }

  // Prov slut utan kort: betala nu (gamla flödet).
  return `<div class="card continue-card" id="fortsatt">
      <h2>Fortsätt med ${esc(n)} ${n === 1 ? "bil" : "bilar"}</h2>
      <p>${cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ")}</p>
      <p class="muted">Provet är slut. Du ser priset innan du godkänner.
        Betalningen sker på Stripes betalsida.</p>
      <div class="btn-row"><button class="btn btn-primary" data-action="continue-trial">Visa pris och betala</button></div>
    </div>`;
}

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

    ${continueCard(data)}

    ${
      trial
        ? `<div class="card">
             <h2>Provperiod</h2>
             <p>${esc(trial.vehiclesUsed)} av ${esc(trial.vehicleLimit)} provbilar.
             ${trial.endsAt ? `Provet slutar ${esc(dateTime(trial.endsAt))}.` : "Provet startar när den första telefonen ansluts."}</p>
             <p class="muted">${
               trial.cardOnFile
                 ? `Kort sparat — första dragningen ${esc(date(trial.firstChargeAt || trial.endsAt))}.`
                 : "Under provet kostar det ingenting. För auto-förnyelse bekräftar ni bilarna och sparar kort ovan. Utan kort stängs åtkomsten utan debitering."
             }</p>
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

/**
 * Förare som bjudits in med e-post men inte loggat in i appen än. "Skicka
 * igen" ger en ny länk och sju nya dagar; "Ta bort" gör att inbjudan inte
 * längre kan lösas in.
 */
function pendingInvites(row, canManage) {
  const invites = row.pendingInvites ?? [];
  if (!invites.length) return "";
  return `<h3>Inbjudna förare</h3>
    <ul class="invite-list">
      ${invites
        .map(
          (i) => `<li>
            <div>
              <strong>${esc(i.label || i.email)}</strong>
              ${i.label ? `<span class="muted">${esc(i.email)}</span>` : ""}
              <span class="muted">${
                i.expired
                  ? "Inbjudan har gått ut"
                  : `Väntar på att föraren loggar in · skickad ${esc(date(i.lastSentAt || i.createdAt))}`
              }</span>
            </div>
            ${
              canManage
                ? `<div class="btn-row">
                     <button class="btn btn-quiet" data-action="resend-invite" data-invite="${esc(i.inviteId)}">Skicka igen</button>
                     <button class="btn btn-quiet" data-action="revoke-invite" data-invite="${esc(i.inviteId)}">Ta bort</button>
                   </div>`
                : ""
            }
          </li>`,
        )
        .join("")}
    </ul>`;
}

/**
 * En ny förare bjuds in med e-post till den här bilen. Föraren skriver bara
 * sin e-post i appen och får en kod i mejlet (fleet/driver_login.py). Ingen
 * kod att läsa upp: bilen och länen bestäms här.
 */
function connectDriver(row) {
  const ids = `data-license="${esc(row.licenseId)}" data-vehicle="${esc(row.vehicleId)}"
    data-plate="${esc(row.vehicle)}"`;
  const key = esc(row.licenseId);
  return `<form class="invite-form" ${ids}>
      <h3>Bjud in förare med e-post</h3>
      <p class="muted">Föraren får ett mejl, öppnar appen, trycker <b>Jag är förare</b> och skriver
      sin e-post. Då kopplas telefonen till den här bilen, med bilens län. Inget lösenord behövs.</p>
      <label for="invite-email-${key}">Förarens e-post</label>
      <input id="invite-email-${key}" name="email" type="email" required
        autocomplete="off" inputmode="email" placeholder="namn@exempel.se" />
      <label for="invite-name-${key}">Förarens namn (valfritt)</label>
      <input id="invite-name-${key}" name="label" autocomplete="off" placeholder="Anna" />
      <div class="btn-row">
        <button class="btn btn-primary" type="submit">Skicka inbjudan</button>
        <button class="btn btn-quiet" type="button" data-action="change-vehicle"
          data-license="${esc(row.licenseId)}">Byt bil</button>
      </div>
    </form>`;
}

/**
 * Länbyten kvar den här månaden (fleet/county_changes.py). Två per bil och
 * kalendermånad, plus ett extra om support gett det. Servern räknar; vyn
 * visar bara svaret.
 */
export function countyChangesLeft(row) {
  const c = row.countyChanges;
  if (!c) return "";
  const total = (c.limit ?? 2) + (c.extra ?? 0);
  return c.remaining > 0
    ? `<p class="muted">Länbyten kvar den här månaden: <b>${esc(c.remaining)} av ${esc(total)}</b></p>`
    : `<p class="muted">Länbyten kvar den här månaden: <b>0 av ${esc(total)}</b>.
       Du kan byta igen nästa månad, eller kontakta support om det inte kan vänta.</p>`;
}

/**
 * Många förare på en gång: en rad per förare, `e-post;regnr;namn`. Regnumret
 * får utelämnas när bolaget bara har en bil. Varje rad får ett eget svar från
 * servern; en rad med fel stoppar inte de andra.
 */
function bulkInvite(rows, result) {
  const single = rows.length === 1;
  const plate = (i, fallback) => (single ? "" : rows[i]?.vehicle || fallback);
  // Radbrytning i platshållaren: &#10; efter att varje rad escapats.
  const example = [
    `anna@exempel.se;${plate(0, "ABC123")};Anna`,
    `bo@exempel.se;${plate(1, "DEF456")}`,
  ]
    .map(esc)
    .join("&#10;");
  return `<div class="card">
      <h2>Bjud in många förare</h2>
      <p class="muted">En rad per förare: <code>e-post;regnr;namn</code>. Namnet är valfritt.
      ${
        single
          ? "Ni har en bil, så regnumret kan lämnas tomt."
          : "Skriv bilens registreringsnummer på varje rad."
      } Högst 200 rader åt gången. Varje förare får ett eget mejl.</p>
      <form id="bulkInviteForm">
        <label for="bulkInviteRows">Förare</label>
        <textarea id="bulkInviteRows" name="rows" rows="6" required spellcheck="false"
          autocomplete="off" placeholder="${example}"></textarea>
        <div class="btn-row"><button class="btn btn-primary" type="submit">Skicka inbjudningar</button></div>
      </form>
      ${result ? bulkResult(result) : ""}
    </div>`;
}

function bulkResult(result) {
  const failed = result.results.filter((r) => !r.ok);
  return `<div class="bulk-result" role="status">
      <p><b>${esc(result.sent)} skickade</b>${
        failed.length ? `, <b>${esc(failed.length)} gick inte</b>` : ""
      }.</p>
      ${
        failed.length
          ? `<table><thead><tr><th>Rad</th><th>E-post</th><th>Varför</th></tr></thead><tbody>
              ${failed
                .map(
                  (r) => `<tr>
                    <td data-label="Rad">${esc(r.line)}</td>
                    <td data-label="E-post">${esc(r.email || "—")}</td>
                    <td data-label="Varför">${esc(r.message || "Något gick fel.")}</td>
                  </tr>`,
                )
                .join("")}
             </tbody></table>
             <p class="muted">Rätta raderna ovan och skicka bara dem igen.</p>`
          : ""
      }
    </div>`;
}

export function bilar(data, bulkInviteResult = null) {
  const canManage = (data.permissions ?? []).includes("manage_devices");
  const rows = data.licenses ?? [];

  return `
    ${canManage && rows.length ? bulkInvite(rows, bulkInviteResult) : ""}
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
        ${countyChangesLeft(row)}

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
        ${pendingInvites(row, canManage)}
        ${
          canManage
            ? `${connectDriver(row)}
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
      <p class="muted">Varje bil kan byta län två gånger per månad, även under
      provet. Att köpa ett extra län räknas inte som ett byte.</p>
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
        ${countyChangesLeft(row)}
        <div class="btn-row">
          <label class="visually-hidden" for="county-${esc(row.licenseId)}">Län</label>
          <select id="county-${esc(row.licenseId)}" data-county-for="${esc(row.licenseId)}">${options}</select>
          <button class="btn btn-primary" data-action="add-county" data-license="${esc(row.licenseId)}">Köp extra län</button>
          ${
            row.countyChanges && row.countyChanges.remaining <= 0
              ? ""
              : `<button class="btn btn-quiet" data-action="change-base" data-license="${esc(row.licenseId)}"
                   data-status="${esc(row.status)}">Byt baslän</button>`
          }
        </div>
      </div>`,
      )
      .join("")}
  `;
}

/* --- Abonnemang och fakturor -------------------------------------------- */

/**
 * Kategorierna i appen. Nycklarna är fleet/features.py:ALL_CATEGORIES;
 * texterna är desamma som i mejlen om provet
 * (fleet/notifications.py:_TRIAL_SCOPE), så att portalen inte lovar något
 * mejlet inte säger.
 */
const CATEGORY_TEXT = {
  transit: ["Tåg och buss", "Inställda tåg, sista avgången och ersättningstrafik"],
  flight: ["Flyg", "Ankomster till flygplatserna"],
  ferry: ["Färjor", ""],
  events: ["Evenemang", "När publiken går hem"],
  road: ["Trafikolyckor", ""],
};
const ALL_CATEGORIES = ["transit", "flight", "ferry", "events", "road"];
const TRIAL_CATEGORIES = ["transit"];

const inTrial = (trial) => Boolean(trial && ["pending", "active"].includes(trial.status));

/**
 * Vad bolaget ser i appen just nu. Servern avgör (fleet/features.py). Skickar
 * GET /api/fleet/company med `features` används det rakt av; annars läses det
 * ur provets läge med samma regel: ett pågående prov utan sparat kort ser tåg
 * och buss, allt annat ser allt.
 */
function membershipPlan(data) {
  const f = data.features;
  if (f && Array.isArray(f.categories)) {
    const on = ALL_CATEGORIES.filter((c) => f.categories.includes(c));
    return { plan: f.plan, on, locked: ALL_CATEGORIES.filter((c) => !on.includes(c)) };
  }
  const t = data.trial;
  if (inTrial(t) && !(t.committed && t.cardOnFile)) {
    return {
      plan: "trial",
      on: TRIAL_CATEGORIES,
      locked: ALL_CATEGORIES.filter((c) => !TRIAL_CATEGORIES.includes(c)),
    };
  }
  return { plan: "full", on: ALL_CATEGORIES, locked: [] };
}

/** Var bolaget står: prov, prov med sparat kort, medlem, prov slut, eller inget. */
function membershipStage(data) {
  const sub = data.subscription ?? {};
  const t = data.trial;
  if (inTrial(t)) return t.committed && t.cardOnFile ? "trial_committed" : "trial";
  if ((data.licenseCount ?? 0) > 0 || ["active", "trialing", "past_due"].includes(sub.status)) {
    return "member";
  }
  if ((data.continueVehicles ?? []).length) return "trial_ended";
  return "none";
}

function featureItem(key, state) {
  const [label, detail] = CATEGORY_TEXT[key] ?? [key, ""];
  return `<li class="feature is-${state}">
      <span class="feature-icon" aria-hidden="true"></span>
      <span class="feature-text"><b>${esc(label)}</b>${detail ? `<span>${esc(detail)}</span>` : ""}
        <span class="visually-hidden">${state === "on" ? "(ingår)" : "(låst)"}</span></span>
    </li>`;
}

function featuresSection(data, stage) {
  const { plan, on, locked } = membershipPlan(data);
  if (plan === "trial" && locked.length) {
    return `<div class="member-features">
      <div class="feature-col">
        <h3>Ingår i provet</h3>
        <ul class="feature-list">${on.map((k) => featureItem(k, "on")).join("")}</ul>
      </div>
      <div class="feature-col feature-col-plus">
        <h3>Låses upp med medlemskap</h3>
        <ul class="feature-list">${locked.map((k) => featureItem(k, "locked")).join("")}</ul>
      </div>
    </div>`;
  }
  const heading = {
    trial_committed: "Allt är upplåst redan nu",
    member: "Det här ingår",
  }[stage] ?? "Det här ingår i medlemskapet";
  return `<div class="member-features">
      <div class="feature-col feature-col-wide">
        <h3>${esc(heading)}</h3>
        <ul class="feature-list feature-list-grid">${on.map((k) => featureItem(k, "on")).join("")}</ul>
      </div>
    </div>`;
}

const findLine = (quote, prefix) =>
  (quote?.lines ?? []).find((line) => String(line.key ?? "").startsWith(prefix)) ?? null;

/**
 * Vad det kostar, ur serverns offert (POST /api/fleet/quote, som inte ändrar
 * något). Portalen räknar inget själv: styckpriset, anteckningen och summan
 * är serverns rader. `pricing.quote` är fortsättningen med bolagets egna bilar
 * (eller nuläget), `pricing.probe` en bil med ett extra län -- den enda vägen
 * till länspriset utan en prislista i klienten.
 */
function priceSection(stage, pricing) {
  if (!pricing || pricing.loading) {
    return `<div class="member-price" aria-busy="true">
      <h3>Vad det kostar</h3>
      <p class="muted">Hämtar priset …</p>
    </div>`;
  }
  const plan = pricing.quote?.nextPeriod ?? null;
  const probe = pricing.probe?.nextPeriod ?? null;
  const ownLicenses = findLine(plan, "licenses_");
  const licenseLine = ownLicenses ?? findLine(probe, "licenses_");
  const countyLine = findLine(plan, "extra_counties") ?? findLine(probe, "extra_counties");
  const discount = findLine(plan, "company_discount");
  const currency = plan?.currency ?? probe?.currency ?? "SEK";
  const vatBp = plan?.vatRateBp ?? probe?.vatRateBp;

  if (!licenseLine && !countyLine) {
    return `<div class="member-price">
      <h3>Vad det kostar</h3>
      <p class="muted">Du ser hela priset och godkänner det innan något köps.</p>
    </div>`;
  }

  const row = (label, line) =>
    line
      ? `<div class="price-row">
          <dt>${esc(label)}</dt>
          <dd>${esc(money(line.unit_price_ore, currency))}</dd>
          ${line.note ? `<p class="price-note">${esc(line.note)}</p>` : ""}
        </div>`
      : "";

  let total = "";
  if (ownLicenses && plan) {
    const n = ownLicenses.quantity;
    const who = `${n} ${n === 1 ? "bil" : "bilar"}`;
    const label = stage === "member" ? `Nästa period (${who})` : `Efter provet (${who})`;
    total = `<div class="price-total">
        <span>${esc(label)}</span>
        <b>${esc(money(plan.amountOre, currency))}</b>
        <span class="price-total-vat">${esc(money(plan.totalOre, currency))} inkl. moms</span>
      </div>`;
  }

  return `<div class="member-price">
      <h3>Vad det kostar</h3>
      <dl class="price-rows">
        ${row("Per bil och månad", licenseLine)}
        ${row("Extra län, per bil och månad", countyLine)}
        ${
          discount
            ? `<div class="price-row"><dt>${esc(discount.label)}</dt>
                <dd>${esc(money(discount.amount_ore, currency))}</dd>
                ${discount.note ? `<p class="price-note">${esc(discount.note)}</p>` : ""}</div>`
            : ""
        }
      </dl>
      ${total}
      <p class="price-fine">Priserna är exklusive moms${
        vatBp != null ? ` (${esc((vatBp / 100).toLocaleString("sv-SE"))} %)` : ""
      }. Du ser hela beloppet och godkänner det innan något köps.</p>
    </div>`;
}

/** "flyg, färjor och evenemang" */
function joinSv(words) {
  if (words.length < 2) return words.join("");
  return `${words.slice(0, -1).join(", ")} och ${words.at(-1)}`;
}

/** Nästa steg: starta medlemskapet, slutföra kortet, eller inget alls. */
function membershipAction(data, stage, plan) {
  const cs = continueState(data);
  const plates = cs ? cs.cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ") : "";
  const theCars = cs?.cars.length === 1 ? "bilen" : "bilarna";
  const trial = data.trial;
  const unlocked = joinSv(plan.locked.map((k) => (CATEGORY_TEXT[k] ?? [k])[0].toLowerCase()));
  const unlockText = unlocked
    ? ` ${unlocked.charAt(0).toUpperCase()}${unlocked.slice(1)} öppnas när kortet är sparat.`
    : "";

  switch (cs?.kind) {
    case "commit":
      return `<div class="member-cta">
          <div class="member-cta-text">
            <h3>Fortsätt efter provet</h3>
            <p>Bekräfta ${theCars} (${plates}) och spara kortet hos Stripe. Inget
              dras under provet. Första dragningen sker ${esc(date(trial?.endsAt))},
              sedan en gång i månaden.${esc(unlockText)}</p>
          </div>
          <div class="member-cta-act">
            <button class="btn btn-primary btn-lg" data-action="continue-trial">Fortsätt efter provet</button>
            <p class="member-fine">Du ser beloppet och godkänner det innan kortet sparas.</p>
          </div>
        </div>`;
    case "finish_card":
      return `<div class="member-cta">
          <div class="member-cta-text">
            <h3>Spara kortet</h3>
            <p>Ni har bekräftat ${theCars} (${plates}). Spara kortet på Stripes
              sida, så fortsätter appen efter provet. Inget dras förrän
              ${esc(date(trial?.endsAt))}.</p>
          </div>
          <div class="member-cta-act">
            <a class="btn btn-primary btn-lg" href="${esc(trial.paymentUrl)}" target="_blank" rel="noopener">Spara kortet hos Stripe</a>
            <button class="btn btn-quiet" data-action="cancel-trial-commit">Avbryt</button>
          </div>
        </div>`;
    case "card_on_file":
      return `<div class="member-cta is-done">
          <div class="member-cta-text">
            <h3>Klart. Medlemskapet tar vid efter provet.</h3>
            <p>Kortet är sparat för ${plates}. Första dragningen sker
              ${esc(date(trial?.firstChargeAt || trial?.endsAt))}, sedan varje
              månad tills ni säger upp.</p>
          </div>
          <div class="member-cta-act">
            <button class="btn btn-quiet" data-action="cancel-trial-commit">Avbryt auto-förnyelse</button>
          </div>
        </div>`;
    case "pay":
      return `<div class="member-cta">
          <div class="member-cta-text">
            <h3>Fortsätt med ${theCars}</h3>
            <p>Provet är slut för ${plates}. Du ser priset och godkänner det,
              sedan betalar du på Stripes betalsida. Appen öppnas när
              betalningen har gått igenom.</p>
          </div>
          <div class="member-cta-act">
            <button class="btn btn-primary btn-lg" data-action="continue-trial">Visa pris och betala</button>
          </div>
        </div>`;
    default:
      break;
  }

  if (stage === "trial" || stage === "trial_ended") {
    const canBuy = (data.permissions ?? []).includes("purchase");
    const text = !canBuy
      ? "Ägaren eller ekonomiansvarig startar medlemskapet här."
      : "Lägg upp bilen och anslut en telefon under <em>Bilar och telefoner</em>. Sedan kan ni fortsätta efter provet här.";
    return `<div class="member-cta is-quiet"><div class="member-cta-text"><p>${text}</p></div></div>`;
  }
  return "";
}

function membershipCard(data, pricing) {
  const sub = data.subscription ?? {};
  const t = data.trial;
  const stage = membershipStage(data);
  const plan = membershipPlan(data);

  const head = {
    trial: [
      "Ni provar Taxi Tips",
      t?.endsAt
        ? `Gratis till ${dateTime(t.endsAt)}. Inget kort behövs under provet.`
        : "Provet startar när den första telefonen ansluts och kostar ingenting.",
      '<span class="pill pill-warn">Provperiod</span>',
    ],
    trial_committed: [
      "Medlemskapet är klart",
      `Kortet är sparat och allt är upplåst. Medlemskapet tar vid ${date(t?.firstChargeAt || t?.endsAt)}.`,
      '<span class="pill pill-ok">Kort sparat</span>',
    ],
    member: [
      "Medlemskap",
      sub.cancelAtPeriodEnd
        ? `Uppsagt. Allt fungerar som vanligt till ${date(sub.accessUntil)}.`
        : "Allt ingår. Förnyas en gång i månaden tills ni säger upp.",
      statusPill(sub.status),
    ],
    trial_ended: [
      "Provet är slut",
      "Fortsätt med medlemskap, så öppnas appen igen för era bilar.",
      '<span class="pill pill-danger">Provet slut</span>',
    ],
    none: ["Medlemskap", "Lägg till en bil för att komma igång.", statusPill("none")],
  }[stage];

  const facts = {
    trial: t
      ? [
          ["Provet slutar", t.endsAt ? date(t.endsAt) : "Vid första telefonen"],
          ["Provbilar", `${t.vehiclesUsed ?? 0} av ${t.vehicleLimit ?? 0}`],
          ["Under provet", "0 kr"],
        ]
      : [],
    trial_committed: t
      ? [
          ["Första dragningen", date(t.firstChargeAt || t.endsAt)],
          ["Provbilar", `${t.vehiclesUsed ?? 0} av ${t.vehicleLimit ?? 0}`],
          ["Under provet", "0 kr"],
        ]
      : [],
    member: [
      ["Bilar", String(data.licenseCount ?? 0)],
      ["Extra län", String(data.extraCountyCount ?? 0)],
      sub.cancelAtPeriodEnd
        ? ["Gäller till", date(sub.accessUntil)]
        : ["Nästa betalning", date(sub.currentPeriodEnd)],
    ],
  }[stage] ?? [];

  return `<section class="card member" aria-labelledby="memberTitle">
      <div class="member-head">
        <div>
          <h2 id="memberTitle">${esc(head[0])}</h2>
          <p class="member-sub">${esc(head[1])}</p>
        </div>
        ${head[2]}
      </div>

      ${
        facts.length
          ? `<dl class="member-facts">${facts
              .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
              .join("")}</dl>`
          : ""
      }

      <div class="member-body">
        <div class="member-left">
          ${featuresSection(data, stage)}
          <ul class="member-terms">
            <li>En licens per bil. Förarna i bilen delar den och byter telefon utan extra kostnad.</li>
            <li>Månadsvis. Säg upp när ni vill, allt fungerar perioden ut.</li>
          </ul>
        </div>
        ${priceSection(stage, pricing)}
      </div>

      ${membershipAction(data, stage, plan)}
    </section>`;
}

export function abonnemang(data, orders, pricing = null) {
  const sub = data.subscription ?? {};
  const canBuy = (data.permissions ?? []).includes("purchase");
  const canCancel = (data.permissions ?? []).includes("cancel_subscription");
  const rows = [
    ["Status", statusPill(sub.status)],
    sub.currentPeriodStart
      ? ["Innevarande period", `${esc(date(sub.currentPeriodStart))} – ${esc(date(sub.currentPeriodEnd))}`]
      : null,
    sub.currentPeriodEnd ? ["Nästa betalning", esc(date(sub.currentPeriodEnd))] : null,
    sub.priceVersion ? ["Prisversion", esc(sub.priceVersion)] : null,
    sub.introEndsAt ? ["Introduktionen slutar", esc(date(sub.introEndsAt))] : null,
    sub.graceUntil ? ["Betalningsfrist", esc(dateTime(sub.graceUntil))] : null,
  ].filter(Boolean);

  return `
    ${membershipCard(data, pricing)}

    <div class="card">
      <h2>Hantera abonnemanget</h2>
      <table><tbody>
        ${rows.map(([k, v]) => `<tr><td class="kv-key">${esc(k)}</td><td>${v}</td></tr>`).join("")}
      </tbody></table>
      ${
        canBuy
          ? `<div class="btn-row">
               <button class="btn btn-primary" data-action="add-license">Lägg till en bil</button>
               <button class="btn btn-quiet" data-action="billing-portal">Uppdatera kort / fakturor</button>
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
                   <td data-label="Status">${esc(orderStatus(o.status))}
                     ${o.status === "pending_payment" && o.paymentUrl
                       ? `<br /><a href="${esc(o.paymentUrl)}" target="_blank" rel="noopener">Betala</a>`
                       : ""}</td>
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

/**
 * Vem som kan logga in i portalen och appens adminläge. Ägaren bjuder in en
 * kollega med e-post; servern mejlar en inloggningslänk (fleet/sales.py).
 * En ny ägare bjuds inte in här -- det är ägarbytet nedan.
 */
function membersCard(m) {
  if (!m) return "";
  const roleText = {
    fleet_admin: "Fordonsadministratör – bilar, län och förartelefoner",
    finance: "Ekonomiansvarig – betalning och fakturor",
  };
  return `
    <div class="card" id="inloggningar">
      <h2>Inloggningar</h2>
      <p class="muted">De som kan logga in här och i appens adminläge. Förare loggar in under Bilar.</p>
      <table><tbody>${(m.members ?? []).map((p) => `
        <tr><td>${esc(p.email || "Okänd e-post")}${p.isMe ? ' <span class="muted">(du)</span>' : ""}</td>
          <td>${esc(roleName(p.role))}</td>
          <td>${m.canManage && !p.isMe ? `<button class="btn btn-quiet" data-action="member-remove"
            data-user="${esc(p.userId)}" data-email="${esc(p.email)}">Ta bort</button>` : ""}</td></tr>`).join("")}
        ${(m.invites ?? []).map((i) => `
        <tr><td>${esc(i.email)} <span class="muted">${i.expired ? "inbjudan har gått ut" : `inbjuden, gäller till ${esc(date(i.expiresAt))}`}</span></td>
          <td>${esc(roleName(i.role))}</td>
          <td>${m.canManage ? `<button class="btn btn-quiet" data-action="member-invite-revoke"
            data-invite="${esc(i.id)}" data-email="${esc(i.email)}">Återkalla</button>` : ""}</td></tr>`).join("")}
      </tbody></table>
      ${m.canManage ? `
      <h3>Bjud in en kollega</h3>
      <form id="memberInviteForm" novalidate>
        <label for="mEmail">E-post</label>
        <input id="mEmail" name="email" type="email" autocomplete="off" required placeholder="namn@bolaget.se" />
        <label for="mRole">Roll</label>
        <select id="mRole" name="role">${(m.roles ?? []).map((r) =>
          `<option value="${esc(r)}">${esc(roleText[r] ?? roleName(r))}</option>`).join("")}</select>
        <div class="btn-row"><button class="btn btn-primary" type="submit">Skicka inbjudan</button></div>
        <p class="muted">Kollegan får ett mejl med en inloggningslänk som gäller i 14 dagar.</p>
      </form>` : '<p class="muted">Bara företagsägaren kan bjuda in fler.</p>'}
    </div>`;
}

export function foretag(data, members = null) {
  const company = data.company ?? {};
  const twoFactor = data.twoFactor ?? {};
  return `
    <div class="card">
      <h2>Företaget</h2>
      <table><tbody>
        <tr><td class="kv-key">Namn</td><td>${esc(company.name)}</td></tr>
        <tr><td class="kv-key">Organisationsnummer</td><td>${esc(company.orgNumber || "—")}</td></tr>
        <tr><td class="kv-key">Land</td><td>${esc(company.country)}</td></tr>
        <tr><td class="kv-key">Verifiering</td><td>${esc(verification(company.verificationStatus))}</td></tr>
        <tr><td class="kv-key">Din roll</td><td>${esc(roleName(data.role))}</td></tr>
      </tbody></table>
      <p class="muted">Ett organisationsnummer eller en verifierad e-post är
      inte i sig bevis på behörighet att företräda företaget. Byte av
      organisationsnummer är ett byte av avtalspart och granskas.</p>
    </div>

    ${membersCard(members)}

    ${detailsCards(data)}

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

/**
 * Kontaktperson och fakturering, som kunden ändrar själv
 * (POST /api/fleet/company/details). Fälten är låsta för den som saknar
 * behörigheten -- servern prövar den ändå.
 */
function detailsCards(data) {
  const d = data.company?.details ?? {};
  const a = d.billingAddress ?? {};
  const perms = data.permissions ?? [];
  const canContact = perms.includes("manage_members");
  const canBilling = perms.includes("purchase");
  const lock = (ok) => (ok ? "" : "disabled");
  return `
    <div class="card">
      <h2>Kontaktperson</h2>
      <p class="muted">Vi ringer det här numret om något behöver fixas.</p>
      <form id="contactForm" novalidate>
        <label for="cName">Namn</label>
        <input id="cName" name="contactName" autocomplete="name" value="${esc(d.contactName)}" ${lock(canContact)} required />
        <label for="cPhone">Mobilnummer</label>
        <input id="cPhone" name="contactPhone" type="tel" inputmode="tel" autocomplete="tel" value="${esc(d.contactPhone)}" ${lock(canContact)} required />
        ${d.contactEmail ? `<p class="muted">Inloggning: ${esc(d.contactEmail)}</p>` : ""}
        ${
          canContact
            ? '<div class="btn-row"><button class="btn btn-primary" type="submit">Spara</button></div><p class="ok" data-saved hidden>Sparat.</p>'
            : '<p class="muted">Bara ägaren kan ändra kontaktpersonen.</p>'
        }
      </form>
    </div>

    <div class="card">
      <h2>Fakturering</h2>
      <p class="muted">Hit skickar vi fakturor och kvitton.</p>
      <form id="billingForm" novalidate>
        <label for="bEmail">E-post för fakturor</label>
        <input id="bEmail" name="billingEmail" type="email" inputmode="email" autocomplete="email" value="${esc(d.billingEmail)}" ${lock(canBilling)} required />
        <label for="bRef">Er referens (valfritt)</label>
        <input id="bRef" name="billingReference" value="${esc(d.billingReference)}" ${lock(canBilling)} />
        <label for="bLine1">Gatuadress</label>
        <input id="bLine1" name="line1" autocomplete="address-line1" value="${esc(a.line1)}" ${lock(canBilling)} required />
        <label for="bLine2">c/o eller våning (valfritt)</label>
        <input id="bLine2" name="line2" autocomplete="address-line2" value="${esc(a.line2)}" ${lock(canBilling)} />
        <div class="form-pair">
          <div>
            <label for="bPostal">Postnummer</label>
            <input id="bPostal" name="postalCode" inputmode="numeric" autocomplete="postal-code" value="${esc(a.postalCode)}" ${lock(canBilling)} />
          </div>
          <div>
            <label for="bCity">Ort</label>
            <input id="bCity" name="city" autocomplete="address-level2" value="${esc(a.city)}" ${lock(canBilling)} required />
          </div>
        </div>
        ${
          canBilling
            ? '<div class="btn-row"><button class="btn btn-primary" type="submit">Spara</button></div><p class="ok" data-saved hidden>Sparat.</p>'
            : '<p class="muted">Bara ägaren eller ekonomiansvarig kan ändra faktureringen.</p>'
        }
      </form>
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
