import { countyName, date, dateTime, money } from "../portal/api.js";

/**
 * Säljflödets vyer: ny kund, paket och start, förare, kundens administratör,
 * uppsägning och kuponger.
 *
 * Som resten av adminwebben: rena funktioner från data till HTML. Inga belopp
 * räknas här -- offerten kommer från backendens prismotor, och det som visas
 * är exakt det kunden sedan faktureras. Behörigheten avgörs av servern; att en
 * knapp döljs för en säljare är bara för att inte visa något som ändå nekas.
 */

export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const PAYMENT_LABEL = {
  stripe_card: "Kort via Stripe (betallänk)",
  stripe_invoice: "Faktura via Stripe (mejlas)",
  later: "Betalas senare / utanför Stripe",
};

const ORDER_STATUS = {
  pending_payment: ["pill-warn", "Väntar på betalning"],
  paid: ["pill-ok", "Betald"],
  applied: ["pill-ok", "Verkställd"],
  scheduled: ["pill-warn", "Vid förnyelse"],
  failed: ["pill-danger", "Misslyckad"],
  canceled: ["", "Avbruten"],
  draft: ["", "Utkast"],
};

const ORDER_KIND = {
  initial: "Första beställning",
  add_license: "Nya bilar",
  add_county: "Extra län",
  change_base_county: "Byte av baslän",
  reduce: "Minskning",
};

function orderPill(status) {
  const [cls, label] = ORDER_STATUS[status] ?? ["", status];
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

function countyOptions(counties, selected = "") {
  return counties
    .map((c) => `<option value="${esc(c.code)}" ${c.code === selected ? "selected" : ""}>${esc(c.name)}</option>`)
    .join("");
}

/* --- Stripe-läget ----------------------------------------------------- */

export function stripeNotice(config) {
  const stripe = config?.stripe ?? {};
  if (stripe.available) {
    const problems = stripe.problems ?? [];
    return problems.length
      ? `<p class="error">Stripe: ${problems.map((p) => esc(p)).join(" · ")}</p>`
      : `<p class="muted">Stripe (${stripe.mode === "live" ? "skarpt" : "test"}): betallänk och faktura skapas automatiskt.</p>`;
  }
  // En rad, inte en röd ruta: det är ett känt läge, inte ett fel just nu.
  return `<p class="muted"><b>Stripe är inte kopplat.</b> Välj <em>Betalas senare</em>, fakturera kunden
    själv och tryck <em>Markera betald</em> under Betalning när pengarna kommit.</p>`;
}

/* --- Ny kund ---------------------------------------------------------- */

export function nyKund(config, lookup = null, orgValue = "") {
  if (!config?.canSell) {
    return `<div class="card"><h2>Ny kund</h2>
      <p class="muted">Din roll kan läsa men inte lägga upp kunder.</p></div>`;
  }
  const found = lookup?.existingCompany;
  const trial = lookup?.trial;
  return `
    <div class="card">
      <h2>Ny kund</h2>
      <p class="muted">Börja med organisationsnumret. Finns bolaget redan öppnar
        du det i stället; ett bolag får bara finnas en gång.</p>
      <form id="lookupForm" class="toolbar">
        <label class="visually-hidden" for="orgLookup">Organisationsnummer</label>
        <input id="orgLookup" name="orgNumber" value="${esc(orgValue)}" placeholder="556677-8899" inputmode="numeric" required />
        <button class="btn btn-primary" type="submit">Kontrollera</button>
      </form>
      ${lookup ? `
        ${!lookup.valid ? '<p class="error">Organisationsnumret går inte att tolka. Kontrollera siffrorna.</p>' : ""}
        ${found ? `<div class="notice">
            <b>${esc(found.name)}</b> finns redan.
            <button class="btn btn-quiet" data-action="open-company" data-id="${esc(found.id)}">Öppna bolaget</button>
          </div>` : ""}
        ${lookup.valid && !found ? `
          <p class="ok">${esc(lookup.orgNumber)} är giltigt och finns inte hos oss.</p>
          <p>${trial?.eligible
            ? '<span class="pill pill-ok">Får provperiod</span>'
            : `<span class="pill pill-warn">Ingen provperiod</span> <span class="muted">${esc(trial?.message ?? "")}</span>`}</p>` : ""}
      ` : ""}
    </div>

    ${lookup?.valid && !found ? `
    <form id="companyForm" class="card form-grid">
      <h2 class="span-2">Företaget</h2>
      <input type="hidden" name="orgNumber" value="${esc(lookup.normalized)}" />
      <label>Företagsnamn (som kunden kallar det)<input name="name" required /></label>
      <label>Juridiskt namn <span class="muted">(om annat)</span><input name="legalName" /></label>

      <h3 class="span-2">Kontaktperson</h3>
      <label>Namn<input name="contactName" required autocomplete="off" /></label>
      <label>Roll<input name="contactRole" placeholder="t.ex. VD, trafikledare" /></label>
      <label>E-post<input name="contactEmail" type="email" required /></label>
      <label>Telefon<input name="contactPhone" type="tel" /></label>

      <h3 class="span-2">Fakturering</h3>
      <label>Fakturamejl <span class="muted">(tomt = kontaktpersonens)</span><input name="billingEmail" type="email" /></label>
      <label>Er referens<input name="billingReference" /></label>
      <label>Gatuadress<input name="line1" autocomplete="off" /></label>
      <label>Postnummer<input name="postalCode" inputmode="numeric" /></label>
      <label>Ort<input name="city" /></label>

      <label class="span-2">Hur kontrollerade du att personen får företräda bolaget?
        <textarea name="verificationNote" rows="2" required
          placeholder="t.ex. Ringde numret i Bolagsverket, kopplades till VD Anna Andersson."></textarea></label>
      <p class="muted span-2">Obligatoriskt. Det är det enda spåret när någon senare frågar
        varför bolaget fick ett avtal eller en provperiod.</p>
      <div class="btn-row span-2"><button class="btn btn-primary" type="submit">Lägg upp företaget</button></div>
    </form>` : ""}
  `;
}

export function companyBody(form) {
  const data = new FormData(form);
  const get = (k) => String(data.get(k) ?? "").trim();
  return {
    orgNumber: get("orgNumber"),
    name: get("name"),
    legalName: get("legalName"),
    contactName: get("contactName"),
    contactRole: get("contactRole"),
    contactEmail: get("contactEmail"),
    contactPhone: get("contactPhone"),
    billingEmail: get("billingEmail"),
    billingReference: get("billingReference"),
    billingAddress: { line1: get("line1"), postalCode: get("postalCode"), city: get("city") },
    verificationNote: get("verificationNote"),
  };
}

/* --- Säljpanelen på ett bolag ----------------------------------------- */

function isPaying(d) {
  const s = d.subscription;
  return s && ["active", "trialing", "past_due"].includes(s.status) && !!s.periodEnd;
}

export function vehicleRow(counties, index = 0) {
  return `
    <div class="pkg-row" data-row="${index}">
      <label>Regnr<input name="plate" placeholder="ABC123" autocomplete="off" /></label>
      <label>Etikett <span class="muted">(valfri)</span><input name="label" placeholder="Bil 12" /></label>
      <label>Baslän <span class="muted">(ingår)</span><select name="baseCounty">${countyOptions(counties, "14")}</select></label>
      <button class="btn btn-quiet" type="button" data-action="pkg-remove-row" data-row="${index}" title="Ta bort raden">✕</button>
      <details class="pkg-extras">
        <summary>+ Extra län <span class="muted">(valfritt)</span></summary>
        <div class="county-grid">${counties.map((c) => `
          <label class="check"><input type="checkbox" name="extraCounties" value="${esc(c.code)}" /> ${esc(c.name)}</label>`).join("")}</div>
      </details>
    </div>`;
}

export function readVehicles(root) {
  return [...root.querySelectorAll(".pkg-row")]
    .map((row) => {
      const base = row.querySelector('[name="baseCounty"]').value;
      return {
        plate: row.querySelector('[name="plate"]').value.trim(),
        label: row.querySelector('[name="label"]').value.trim(),
        baseCounty: base,
        extraCounties: [...row.querySelectorAll('[name="extraCounties"]:checked')]
          .map((o) => o.value)
          .filter((c) => c !== base),
      };
    })
    .filter((v) => v.plate);
}

export function quoteBox(q) {
  if (!q) return "";
  const lines = (q.now?.lines ?? []).map(
    (l) => `<div class="quote-line"><span>${esc(l.label)}${l.note ? ` <span class="muted">${esc(l.note)}</span>` : ""}</span><b>${esc(money(l.amount_ore))}</b></div>`,
  );
  return `
    <div class="quote">
      <div class="quote-lines">${lines.join("") || '<p class="muted">Inget att betala nu.</p>'}</div>
      <div class="quote-line"><span>Moms</span><b>${esc(money(q.now?.vatOre))}</b></div>
      <div class="quote-line quote-total"><span>Att betala nu</span><b>${esc(money(q.now?.totalOre))}</b></div>
      <p class="muted">Därefter <b>${esc(money(q.nextPeriod?.totalOre))}</b> per månad inkl. moms
        (${esc(money(q.nextPeriod?.amountOre))} exkl.)${q.effectiveAt ? `, från ${esc(date(q.effectiveAt))}` : ""}.
        ${q.licenses ? `Bilar: ${esc(q.licenses.before)} → ${esc(q.licenses.after)}.` : ""}</p>
    </div>`;
}

/**
 * Kundsidans byggstenar. Varje steg i kundens cykel (views.js:kund) visar en
 * av dem -- tidigare låg alla på samma sida och det gick att gå vilse.
 */

/** Steg Bilar: lägg till bilar som prov, med kupong eller som beställning. */
export function addCarsBlock(d, config) {
  if (!config?.canSell) return "";
  const counties = config.counties ?? [];
  const stripeOk = !!config.stripe?.available;
  const paying = isPaying(d);
  const trialOpen = d.trial && ["pending", "active"].includes(d.trial.status);
  const defaultPayment = stripeOk ? "stripe_card" : "later";
  const payOption = (value) =>
    `<option value="${value}" ${value === defaultPayment ? "selected" : ""}
      ${value !== "later" && !stripeOk ? "disabled" : ""}>${esc(PAYMENT_LABEL[value])}</option>`;
  return `
    <div class="card" id="salesPanel">
      <h2>Lägg till bilar</h2>
      <p class="muted">Pris per bil ${esc(money(config.price?.baseOre))}
        (${esc(money(config.price?.volumeOre))} från ${esc(config.price?.volumeThreshold)} bilar),
        extra län ${esc(money(config.price?.extraCountyOre))} per bil och månad, exkl. moms.</p>
      <div id="pkgRows">${vehicleRow(counties, 0)}</div>
      <div class="btn-row">
        <button class="btn btn-quiet" type="button" data-action="pkg-add-row">+ En bil till</button>
      </div>

      <div class="start-grid">
        ${!paying ? `
        <div class="start-option">
          <h4>${trialOpen ? "Lägg till i provet" : "Starta gratis prov"}</h4>
          <p class="muted">${esc(config.trial?.days)} dagar, högst ${esc(config.trial?.vehicleLimit)} bilar.
            Startar när första telefonen kopplas. Kostar inget.</p>
          <button class="btn btn-primary" type="button" data-action="pkg-trial">
            ${trialOpen ? "Lägg till provbilar" : "Starta prov"}</button>
        </div>` : ""}

        <div class="start-option">
          <h4>Beställ</h4>
          ${stripeNotice(config)}
          <button class="btn btn-quiet" type="button" data-action="pkg-quote">1. Räkna pris</button>
          <div id="pkgQuote"></div>
          <label>Betalning<select id="pkgPayment">
            ${payOption("stripe_card")}${payOption("stripe_invoice")}${payOption("later")}
          </select></label>
          <label>Förfallodagar (faktura)<input id="pkgDue" type="number" min="1" max="60" value="14" /></label>
          <label class="check"><input id="pkgAccepted" type="checkbox" />
            Kunden har godkänt antal, pris och betalningsdatum</label>
          <button class="btn btn-primary" type="button" data-action="pkg-order">2. Lägg beställning</button>
        </div>

        <div class="start-option">
          <h4>Kupong</h4>
          <p class="muted">${paying
            ? "Gratisdagar: nästa debitering flyttas eller perioden förlängs."
            : "Tillfällig åtkomst i kupongens antal dagar, för bilarna ovan."}</p>
          <div class="inline-field">
            <input id="couponCode" placeholder="KUPONGKOD" autocomplete="off" />
            <button class="btn btn-quiet" type="button" data-action="pkg-coupon">Lös in</button>
          </div>
        </div>
      </div>
      <div id="pkgResult"></div>
    </div>`;
}

/** Steg Kundkonto: bjud in den som sköter kontot i kundportalen och appen. */
export function ownerBlock(d) {
  const profile = d.profile ?? {};
  return `
    <div class="card">
      <h2>Bjud in kundens administratör</h2>
      <p class="muted">Personen får en inloggningslänk och kopplas till företaget när hen loggar in.
        Sedan kan hen själv koppla förare i appen.</p>
      <div class="inline-field">
        <input id="ownerEmail" type="email" value="${esc(profile.contactEmail ?? "")}" placeholder="namn@bolaget.se" />
        <button class="btn btn-primary" type="button" data-action="owner-invite">Skicka inbjudan</button>
      </div>
      ${(d.ownerInvites ?? []).length ? `<ul class="plain">${d.ownerInvites.map((i) => `
        <li>${esc(i.email)} ${i.status === "consumed"
          ? '<span class="pill pill-ok">Inloggad</span>'
          : i.status === "pending" ? `<span class="pill pill-warn">Väntar</span> <span class="muted">till ${esc(date(i.expiresAt))}</span>`
          : '<span class="pill">Återkallad</span>'}</li>`).join("")}</ul>` : ""}
    </div>`;
}

/** Steg Betalning: säga upp, ångra, avsluta direkt. */
export function cancelBlock(d, config) {
  if (!config?.canSell) return "";
  const s = d.subscription;
  return `
    <div class="card">
      <h2>Uppsägning</h2>
      ${s?.cancelAtPeriodEnd ? `
        <p><span class="pill pill-warn">Uppsagt</span> Åtkomsten gäller till ${esc(date(s.accessUntil))}.</p>
        <div class="btn-row"><button class="btn btn-quiet" type="button" data-action="undo-cancel">Ångra uppsägningen</button></div>
      ` : s && ["active", "trialing", "past_due"].includes(s.status) ? `
        <p class="muted">Kunden behåller åtkomsten den betalda perioden ut, sedan debiteras inget mer.</p>
        <div class="btn-row"><button class="btn btn-quiet" type="button" data-action="cancel-period">Säg upp till periodens slut</button></div>
      ` : '<p class="muted">Inget löpande abonnemang att säga upp.</p>'}
    </div>`;
}

/** Steg Företag: kund- och fakturauppgifter. */
export function profileBlock(d) {
  const profile = d.profile ?? {};
  const address = profile.billingAddress ?? {};
  return `
    <form id="profileForm" class="card form-grid">
      <h2 class="span-2">Uppgifter</h2>
      <label>Företagsnamn<input name="name" value="${esc(d.company.name)}" /></label>
      <label>Juridiskt namn<input name="legalName" value="${esc(profile.legalName ?? "")}" /></label>
      <label>Kontaktperson<input name="contactName" value="${esc(profile.contactName ?? "")}" /></label>
      <label>Roll<input name="contactRole" value="${esc(profile.contactRole ?? "")}" /></label>
      <label>E-post<input name="contactEmail" type="email" value="${esc(profile.contactEmail ?? "")}" /></label>
      <label>Telefon<input name="contactPhone" value="${esc(profile.contactPhone ?? "")}" /></label>
      <label>Fakturamejl<input name="billingEmail" type="email" value="${esc(profile.billingEmail ?? "")}" /></label>
      <label>Er referens<input name="billingReference" value="${esc(profile.billingReference ?? "")}" /></label>
      <label>Gatuadress<input name="line1" value="${esc(address.line1 ?? "")}" /></label>
      <label>Postnummer<input name="postalCode" value="${esc(address.postal_code ?? "")}" /></label>
      <label>Ort<input name="city" value="${esc(address.city ?? "")}" /></label>
      <p class="muted span-2">Orgnr ${esc(profile.orgNumber ?? d.company.orgNumber ?? "")} ändras inte här:
        ett nytt orgnr är en ny avtalspart.</p>
      <div class="btn-row span-2"><button class="btn btn-primary" type="submit">Spara</button></div>
    </form>`;
}

export function profileBody(form) {
  const data = new FormData(form);
  const get = (k) => String(data.get(k) ?? "").trim();
  return {
    name: get("name"),
    legalName: get("legalName"),
    contactName: get("contactName"),
    contactRole: get("contactRole"),
    contactEmail: get("contactEmail"),
    contactPhone: get("contactPhone"),
    billingEmail: get("billingEmail"),
    billingReference: get("billingReference"),
    billingAddress: { line1: get("line1"), postalCode: get("postalCode"), city: get("city") },
  };
}

/* --- Beställningar ----------------------------------------------------- */

export function ordersCard(orders, config) {
  const canSell = !!config?.canSell;
  const canManage = !!config?.canManage;
  const stripeOk = !!config?.stripe?.available;
  if (!orders?.length) return `<div class="card"><h2>Beställningar</h2><p class="muted">Inga beställningar.</p></div>`;
  return `
    <div class="card">
      <h2>Beställningar</h2>
      <table><thead><tr><th>Datum</th><th>Vad</th><th>Status</th><th>Nu</th><th>Per månad</th><th></th></tr></thead>
      <tbody>${orders.map((o) => `
        <tr>
          <td data-label="Datum">${esc(date(o.createdAt))}</td>
          <td data-label="Vad">${esc(ORDER_KIND[o.kind] ?? o.kind)}
            ${o.quantityAfter ? `<div class="muted">${esc(o.quantityAfter)} bilar efter</div>` : ""}
            ${o.failureReason ? `<div class="muted mono">${esc(o.failureReason)}</div>` : ""}</td>
          <td data-label="Status">${orderPill(o.status)}
            ${o.paidAt ? `<div class="muted">${esc(dateTime(o.paidAt))}</div>` : ""}</td>
          <td data-label="Nu">${esc(money(o.totalNowOre))}</td>
          <td data-label="Per månad">${esc(money(o.nextPeriodTotalOre))}</td>
          <td data-label="">
            ${o.paymentUrl ? `<div class="btn-row">
                <a class="btn btn-quiet" href="${esc(o.paymentUrl)}" target="_blank" rel="noopener">Betalsida</a>
                <button class="btn btn-quiet" data-action="copy-link" data-url="${esc(o.paymentUrl)}">Kopiera länk</button></div>` : ""}
            ${canSell && o.status === "pending_payment" ? `<div class="btn-row">
              ${o.stripeInvoiceId ? `<button class="btn btn-quiet" data-action="order-refresh" data-order="${esc(o.id)}">Kontrollera betalning</button>` : ""}
              ${!o.stripeInvoiceId && stripeOk ? `<button class="btn btn-quiet" data-action="order-link" data-order="${esc(o.id)}">Skapa betallänk</button>` : ""}
              ${!o.stripeInvoiceId && canManage ? `<button class="btn btn-quiet" data-action="order-paid" data-order="${esc(o.id)}">Markera betald</button>` : ""}
              <button class="btn btn-danger" data-action="order-cancel" data-order="${esc(o.id)}">Avbryt</button>
            </div>` : ""}
          </td>
        </tr>`).join("")}</tbody></table>
    </div>`;
}

export function redemptionsCard(list) {
  if (!list?.length) return "";
  const effect = {
    temporary_access: "Tillfällig åtkomst",
    billing_deferred: "Nästa debitering flyttad",
    period_extended: "Perioden förlängd",
  };
  return `<div class="card"><h2>Kuponger</h2><ul class="plain">${list.map((r) => `
    <li><span class="mono">${esc(r.code)}</span> · ${esc(effect[r.effect] ?? r.effect)} ·
      ${esc(r.days)} dagar · ${esc(date(r.at))}</li>`).join("")}</ul></div>`;
}

/* --- Kuponger ---------------------------------------------------------- */

export function kuponger(list, config) {
  const rows = list.coupons ?? [];
  const canManage = !!config?.canManage;
  return `
    ${canManage ? `
    <form id="couponForm" class="card form-grid">
      <h2 class="span-2">Ny kupong</h2>
      <label>Kod <span class="muted">(tom = slumpas)</span><input name="code" placeholder="SOMMAR30" autocomplete="off" /></label>
      <label>Beskrivning<input name="description" placeholder="Mässan i Göteborg" /></label>
      <label>Gratisdagar<input name="days" type="number" min="1" max="365" value="30" required /></label>
      <label>Högst antal bilar <span class="muted">(tillfällig åtkomst)</span><input name="vehicleLimit" type="number" min="1" max="50" value="3" /></label>
      <label>Högst antal inlösen <span class="muted">(tom = obegränsat)</span><input name="maxRedemptions" type="number" min="1" /></label>
      <label>Giltig till och med<input name="validUntil" type="date" /></label>
      <p class="muted span-2">Utan betalande abonnemang ger kupongen tillfällig åtkomst som slutar utan
        kostnad. Med abonnemang i Stripe flyttas nästa debitering. Med abonnemang som betalas
        utanför Stripe förlängs perioden. Ett bolag kan använda samma kupong en gång.</p>
      <div class="btn-row span-2"><button class="btn btn-primary" type="submit">Skapa kupong</button></div>
    </form>` : '<p class="muted">Kuponger skapas av en plattformsadministratör. Säljare löser in dem på kundens sida.</p>'}
    <div class="card"><table>
      <thead><tr><th>Kod</th><th>Dagar</th><th>Bilar</th><th>Inlösta</th><th>Giltig till</th><th>Status</th><th></th></tr></thead>
      <tbody>${rows.map((c) => `
        <tr><td data-label="Kod"><b class="mono">${esc(c.code)}</b><div class="muted">${esc(c.description)}</div></td>
          <td data-label="Dagar">${esc(c.days)}</td>
          <td data-label="Bilar">${esc(c.vehicleLimit)}</td>
          <td data-label="Inlösta">${esc(c.redemptions)}${c.maxRedemptions ? ` / ${esc(c.maxRedemptions)}` : ""}</td>
          <td data-label="Giltig till">${esc(c.validUntil ? date(c.validUntil) : "—")}</td>
          <td data-label="Status">${c.active ? '<span class="pill pill-ok">Aktiv</span>' : '<span class="pill">Avstängd</span>'}</td>
          <td data-label="">${canManage && c.active
            ? `<button class="btn btn-danger" data-action="coupon-off" data-coupon="${esc(c.id)}">Stäng av</button>` : ""}</td>
        </tr>`).join("")}</tbody>
    </table>
    ${rows.length ? "" : '<p class="muted">Inga kuponger än.</p>'}</div>
  `;
}

export function couponBody(form) {
  const data = new FormData(form);
  const get = (k) => String(data.get(k) ?? "").trim();
  return {
    code: get("code"),
    description: get("description"),
    days: Number(get("days")),
    vehicleLimit: Number(get("vehicleLimit") || 3),
    maxRedemptions: get("maxRedemptions") ? Number(get("maxRedemptions")) : null,
    validUntil: get("validUntil") || null,
  };
}

export { countyName };
