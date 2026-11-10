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
  add_license: "Nya platser",
  add_county: "Fler län (äldre avtal)",
  change_base_county: "Byte av län",
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
  // All betalning går genom Stripe. Utan Stripe går det inte att beställa --
  // prov och kuponger fungerar som vanligt.
  return `<p class="error"><b>Stripe är inte kopplat.</b> Beställningar kan inte tas betalt för
    förrän det är det${stripe.reason ? ` (${esc(stripe.reason)})` : ""}. Prov och kuponger fungerar.</p>`;
}

/* --- Bolagsverket ------------------------------------------------------ */

const REGISTRY_PILL = {
  active: ["pill-ok", "Aktivt"],
  inactive: ["pill-warn", "Ej verksamt"],
  winding_up: ["pill-warn", "Avveckling pågår"],
  deregistered: ["pill-danger", "Avregistrerat"],
};

/** Vad Bolagsverket säger om bolaget: namn, form, status, adress och bransch. */
export function registryBlock(r, { checkedAt = "" } = {}) {
  if (!r) return "";
  if (!r.found) {
    return `<p class="muted">Bolagsverket har inget bolag med det numret
      (t.ex. en enskild firma). Fyll i uppgifterna för hand.</p>`;
  }
  const [cls, label] = REGISTRY_PILL[r.status] ?? ["", r.statusText || r.status];
  const a = r.address ?? {};
  const address = [a.line1, a.line2, [a.postal_code, a.city].filter(Boolean).join(" ")]
    .filter(Boolean).join(", ");
  return `
    <dl class="kv">
      <dt>Namn</dt><dd><b>${esc(r.name)}</b></dd>
      <dt>Status</dt><dd><span class="pill ${cls}">${esc(label)}</span>
        ${r.status !== "active" ? `<span class="muted">${esc(r.statusText)}</span>` : ""}</dd>
      <dt>Form</dt><dd>${esc(r.legalForm || "—")}</dd>
      <dt>Registrerat</dt><dd>${esc(r.registeredAt || "—")}</dd>
      <dt>Postadress</dt><dd>${esc(address || "—")}</dd>
      ${(r.sni ?? []).length ? `<dt>Bransch</dt><dd>${(r.sni ?? []).map((s) => esc(`${s.text} (${s.code})`)).join("<br>")}</dd>` : ""}
    </dl>
    <p class="muted">Från Bolagsverket${checkedAt ? `, hämtat ${esc(new Date(checkedAt).toLocaleString("sv-SE"))}` : ""}.</p>`;
}

/* --- Ny kund ---------------------------------------------------------- */

/**
 * Resultatet av ett org.nr-uppslag: finns bolaget redan, vad säger registret,
 * får det prov. Ritas i #orgLookupResult utan att resten av formuläret rörs.
 */
export function lookupResult(lookup) {
  if (!lookup) return "";
  const found = lookup.existingCompany;
  const trial = lookup.trial;
  if (!lookup.valid) return '<p class="error">Organisationsnumret går inte att tolka. Kontrollera siffrorna.</p>';
  if (found) {
    return `<div class="notice"><b>${esc(found.name)}</b> finns redan.
      <button class="btn btn-quiet" type="button" data-action="open-company" data-id="${esc(found.id)}">Öppna bolaget</button></div>`;
  }
  return `
    <p class="ok">${esc(lookup.orgNumber)} är giltigt och finns inte hos oss.</p>
    ${lookup.registry ? registryBlock(lookup.registry) : ""}
    ${lookup.registryError ? `<p class="muted">${esc(lookup.registryError)}</p>` : ""}
    ${lookup.registry?.status === "deregistered"
      ? '<p class="error">Bolaget är avregistrerat. Lägg bara upp det om du vet varför.</p>' : ""}
    <p>${trial?.eligible
      ? '<span class="pill pill-ok">Får provperiod</span>'
      : `<span class="pill pill-warn">Ingen provperiod</span> <span class="muted">${esc(trial?.message ?? "")}</span>`}</p>`;
}

/** Är en text i resultatet ett uppslag som kan fylla i formuläret? */
export function prefillFromLookup(form, lookup) {
  const reg = lookup?.registry?.found ? lookup.registry : null;
  if (!reg || !form) return;
  const set = (name, value) => {
    const input = form.elements[name];
    if (input && value && !input.value) input.value = value;
  };
  set("name", reg.name);
  set("legalName", reg.name);
  set("line1", reg.address?.line1);
  set("postalCode", reg.address?.postal_code);
  set("city", reg.address?.city);
}

export function nyKund(config, lookup = null, orgValue = "", pipelineLead = null) {
  if (!config?.canSell) {
    return `<div class="card"><h2>Ny kund</h2>
      <p class="muted">Din roll kan läsa men inte lägga upp kunder.</p></div>`;
  }
  const counties = config.counties ?? [];
  const trialSeats = Number(config.trial?.vehicleLimit ?? 3);
  return `
    <form id="companyForm" class="card form-grid">
      <h2 class="span-2">Ny kund</h2>
      <label class="span-2">Företagsnamn<input name="name" required autocomplete="off"
        value="${esc(pipelineLead?.companyName ?? "")}" /></label>
      <label>Kontaktperson<input name="contactName" required autocomplete="off"
        value="${esc(pipelineLead?.contactName ?? "")}" /></label>
      <label>E-post<input name="contactEmail" type="email" required
        value="${esc(pipelineLead?.contactEmail ?? "")}" /></label>
      <label>Mobil<input name="contactPhone" type="tel" /></label>
      <label>Antal platser<input name="seats" type="number" min="1" max="50" value="1" required /></label>
      <label class="span-2">Län<select name="county" required>
        <option value="">Välj län …</option>
        ${countyOptions(counties, "")}
      </select></label>

      <div class="span-2 org-field">
        <label>Organisationsnummer <span class="muted">(valfritt – krävs först när kunden köper)</span>
          <input id="orgLookup" name="orgNumber" value="${esc(orgValue)}" placeholder="556677-8899" inputmode="numeric" /></label>
        <button class="btn btn-quiet" type="button" data-action="org-lookup">Slå upp</button>
      </div>
      <div id="orgLookupResult" class="span-2">${lookupResult(lookup)}</div>

      <details class="span-2 pkg-extras">
        <summary>Fler uppgifter (valfritt)</summary>
        <div class="form-grid">
          <label>Juridiskt namn <span class="muted">(om annat)</span><input name="legalName" /></label>
          <label>Roll<input name="contactRole" placeholder="t.ex. VD, trafikledare" /></label>
          <label>Fakturamejl <span class="muted">(tomt = kontaktpersonens)</span><input name="billingEmail" type="email" /></label>
          <label>Er referens<input name="billingReference" /></label>
          <label>Gatuadress<input name="line1" autocomplete="off" /></label>
          <label>Postnummer<input name="postalCode" inputmode="numeric" /></label>
          <label>Ort<input name="city" /></label>
          <label class="span-2">Hur kontrollerade du att personen får företräda bolaget?
            <textarea name="verificationNote" rows="2"
              placeholder="t.ex. Ringde numret i Bolagsverket, kopplades till VD Anna Andersson."></textarea></label>
        </div>
      </details>

      <p class="muted span-2">Kunden får ${esc(config.trial?.days ?? 7)} dagars gratis prov på platserna du anger.
        Provet startar när första kontot loggar in i appen.</p>
      <div class="btn-row span-2"><button class="btn btn-primary" type="submit">Lägg upp kunden</button></div>
    </form>
  `;
}

/** Svaret som backenden får (POST /api/admin/companies/new). */
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
    // Backenden kräver en anteckning (fleet/sales.create_company). Formuläret
    // gör den valfri; utan text skickas en ärlig standard i stället.
    verificationNote: get("verificationNote")
      || "Upplagd av personal i admin. Behörigheten är inte kontrollerad.",
  };
}

/** Platserna som formuläret ber om: startas som prov direkt efter upplägget. */
export function companySeats(form) {
  const data = new FormData(form);
  return {
    seats: Math.max(1, Number(data.get("seats") || 1)),
    county: String(data.get("county") ?? ""),
  };
}

/* --- Säljpanelen på ett bolag ----------------------------------------- */

function isPaying(d) {
  const s = d.subscription;
  return s && ["active", "trialing", "past_due"].includes(s.status) && !!s.periodEnd;
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
        ${q.licenses ? `Platser: ${esc(q.licenses.before)} → ${esc(q.licenses.after)}.` : ""}</p>
    </div>`;
}

/**
 * Kundsidans byggstenar. Varje steg i kundens cykel (views.js:kund) visar en
 * av dem -- tidigare låg alla på samma sida och det gick att gå vilse.
 */

/**
 * Säljsteget på kundsidan: lägg till platser, räkna pris och ta betalt. Inga
 * regnr -- platsen hör till ett konto, precis som i appen. Ett län per plats;
 * extra län säljs inte längre. Priset kommer från servern (config.price).
 */
export function addCarsBlock(d, config) {
  if (!config?.canSell) return "";
  const counties = config.counties ?? [];
  const stripeOk = !!config.stripe?.available;
  const paying = isPaying(d);
  const trialOpen = d.trial && ["pending", "active"].includes(d.trial.status);
  const payOption = (value) =>
    `<option value="${value}" ${value === "stripe_card" ? "selected" : ""}>${esc(PAYMENT_LABEL[value])}</option>`;
  const maxTrial = Number(config.trial?.vehicleLimit ?? 3);
  return `
    <div class="card" id="salesPanel">
      <h2>Lägg till plats</h2>
      ${config.price?.baseOre != null ? `<p class="muted">${esc(money(config.price.baseOre))} per plats och månad exkl. moms.</p>` : ""}
      <div class="pack-seats">
        <label>Antal<input id="pkgCount" type="number" min="1" max="50" value="1" /></label>
        <label>Län<select id="pkgCounty">
          <option value="">Välj län …</option>
          ${countyOptions(counties, "")}
        </select></label>
      </div>

      ${!paying ? `
      <div class="pack-path">
        <p><b>${trialOpen ? "Lägg till i provet" : "Starta prov"}</b>
          <span class="muted"> — ${esc(config.trial?.days ?? 7)} dagar, högst ${esc(maxTrial)} platser.
            Startar när första kontot loggar in i appen. Kostar inget.</span></p>
        <button class="btn ${paying ? "btn-quiet" : "btn-primary"}" type="button" data-action="pkg-trial">
          ${trialOpen ? "Lägg till i provet" : "Starta prov"}</button>
      </div>` : ""}

      <div class="pack-path pack-charge">
        <p><b>Ta betalt</b> <span class="muted">— kortlänk eller Stripe-faktura. Samma belopp som kunden ser.</span></p>
        ${stripeNotice(config)}
        ${stripeOk ? `
        <div class="btn-row">
          <button class="btn btn-quiet" type="button" data-action="pkg-quote">Räkna pris</button>
        </div>
        <div id="pkgQuote"></div>
        <div class="pack-pay">
          <label>Betalning<select id="pkgPayment">
            ${payOption("stripe_card")}${payOption("stripe_invoice")}
          </select></label>
          <label>Förfallodagar (faktura)<input id="pkgDue" type="number" min="1" max="60" value="14" /></label>
        </div>
        <label class="check"><input id="pkgAccepted" type="checkbox" />
          Kunden har godkänt antal, pris och betalningsdatum</label>
        <button class="btn ${paying ? "btn-primary" : "btn-quiet"}" type="button" data-action="pkg-order">Skicka betallänk</button>` : ""}
      </div>

      <details class="pack-extras">
        <summary>Kupong</summary>
        <p class="muted">${paying
          ? "Gratisdagar: nästa debitering flyttas eller perioden förlängs."
          : "Tillfällig åtkomst i kupongens antal dagar, för platserna ovan."}</p>
        <div class="inline-field">
          <input id="couponCode" placeholder="KUPONGKOD" autocomplete="off" />
          <button class="btn btn-quiet" type="button" data-action="pkg-coupon">Lös in</button>
        </div>
      </details>
      <div id="pkgResult"></div>
    </div>`;
}

/** Steg Kundkonto: bjud in den som sköter kontot i kundportalen och appen. */
export function ownerBlock(d) {
  const profile = d.profile ?? {};
  const members = (d.members ?? []).some((m) => m.status === "active");
  return `
    <div class="card" id="ownerCard">
      <h2>Bjud in en inloggning</h2>
      <p class="muted">Personen får ett mejl från Taxi Tips med en inloggningslänk och kopplas till företaget
        när hen loggar in. Gäller i 14 dagar.</p>
      <div class="inline-field">
        <input id="ownerEmail" type="email" value="${esc(members ? "" : profile.contactEmail ?? "")}" placeholder="namn@bolaget.se" />
        <select id="ownerRole" aria-label="Roll">
          <option value="company_owner">Ägare</option>
          <option value="fleet_admin">Bilar och förare</option>
          <option value="finance">Ekonomi</option>
        </select>
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
  if (!s?.cancelAtPeriodEnd && !["active", "trialing", "past_due"].includes(s?.status)) return "";
  return `
    <div class="card">
      <h2>Uppsägning</h2>
      ${s?.cancelAtPeriodEnd ? `
        <p><span class="pill pill-warn">Uppsagt</span> Åtkomsten gäller till ${esc(date(s.accessUntil))}.</p>
        <div class="btn-row"><button class="btn btn-quiet" type="button" data-action="undo-cancel">Ångra uppsägningen</button></div>
      ` : `
        <p class="muted">Kunden behåller åtkomsten den betalda perioden ut, sedan debiteras inget mer.</p>
        <div class="btn-row"><button class="btn btn-quiet" type="button" data-action="cancel-period">Säg upp till periodens slut</button></div>
      `}
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
      <p class="muted span-2">${(profile.orgNumber || d.company.orgNumber)
        ? `Org.nr ${esc(profile.orgNumber || d.company.orgNumber)} ändras inte här: ett nytt org.nr är en ny avtalspart.`
        : "Org.nr saknas – behövs vid köp. Kunden anger det i portalen när hen beställer."}</p>
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
  const stripeOk = !!config?.stripe?.available;
  const visible = (orders ?? []).filter((o) => !["canceled", "failed", "draft"].includes(o.status));
  if (!visible.length) return "";
  return `
    <div class="card">
      <h2>Beställningar</h2>
      <table><thead><tr><th>Datum</th><th>Vad</th><th>Status</th><th>Nu</th><th>Per månad</th><th></th></tr></thead>
      <tbody>${visible.map((o) => `
        <tr>
          <td data-label="Datum">${esc(date(o.createdAt))}</td>
          <td data-label="Vad">${esc(ORDER_KIND[o.kind] ?? o.kind)}
            ${o.quantityAfter ? `<div class="muted">${esc(o.quantityAfter)} platser efter</div>` : ""}
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
              ${o.stripeInvoiceId || o.stripeCheckoutSessionId ? `<button class="btn btn-quiet" data-action="order-refresh" data-order="${esc(o.id)}">Kontrollera betalning</button>` : ""}
              ${!o.stripeInvoiceId && !o.stripeCheckoutSessionId && stripeOk ? `<button class="btn btn-quiet" data-action="order-link" data-order="${esc(o.id)}">Skapa betallänk</button>` : ""}
              <button class="btn btn-danger" data-action="order-cancel" data-order="${esc(o.id)}">Avbryt</button>
            </div>` : ""}
            ${canSell && o.status === "paid" ? `<div class="btn-row">
              <button class="btn btn-primary" data-action="order-refresh" data-order="${esc(o.id)}">Verkställ betald order</button>
            </div>` : ""}
          </td>
        </tr>`).join("")}</tbody></table>
    </div>`;
}

/** Steg Betalning: förläng pågående prov (säljare). */
export function trialExtendBlock(d, config) {
  if (!config?.canSell) return "";
  const t = d.trial;
  if (!t || !["pending", "active"].includes(t.status)) return "";
  const pending = t.status === "pending";
  return `
    <div class="card">
      <h2>Provperiod</h2>
      <p class="muted">${pending
        ? `Provet startar när första kontot loggar in i appen. Planerad längd: ${esc(t.plannedDays ?? config.trial?.days ?? 7)} dagar.`
        : `Provet pågår till ${esc(date(t.endsAt))}.`}</p>
      <div class="inline-field">
        <input id="trialExtendDays" type="number" min="1" max="366" value="7" />
        <button class="btn btn-quiet" type="button" data-action="trial-extend">Förläng med dagar</button>
      </div>
      <p>Platser i provet: <b>${esc(t.vehicles ?? 0)}</b> av högst <b>${esc(t.vehicleLimit ?? 1)}</b>.
        <span class="muted">Ett nytt prov har en plats, ett län och tåg &amp; buss.</span></p>
      <div class="inline-field">
        <label class="visually-hidden" for="trialVehicleLimit">Högst antal platser i provet</label>
        <input id="trialVehicleLimit" type="number" min="${esc(Math.max(1, t.vehicles ?? 1))}" max="25"
          value="${esc(t.vehicleLimit ?? 1)}" />
        <button class="btn btn-quiet" type="button" data-action="trial-vehicles">Ändra antal platser</button>
      </div>
      <p class="muted">Skälet sparas i händelseloggen. Bjud in kontona under Platser.</p>
      <h3>Avsluta provet</h3>
      <p class="muted">Provet slutar nu: inga tips och inga notiser. Kunden får samma mejl som när provet
        löper ut. Ett betalt abonnemang påverkas inte.</p>
      <div class="btn-row"><button class="btn btn-danger" type="button" data-action="trial-end">Avsluta provet</button></div>
    </div>`;
}

/** Steg Betalning: månadsrabatt på platser (plattformsadmin). */
export function discountBlock(d, config) {
  if (!config?.canManage) return "";
  const active = d.discount;
  const label = active
    ? (active.kind === "percent_bp"
      ? `${(active.value / 100).toFixed(2)} % på platserna`
      : `${money(active.value)} / mån exkl. moms`)
    : null;
  return `
    <details class="card" id="discountCard"${active ? " open" : ""}>
      <summary>Prisrabatt${active ? ` · ${esc(label)}` : ""}</summary>
      ${active ? `<p><span class="pill pill-ok">Aktiv</span> ${esc(label)}
        ${active.validUntil ? `<span class="muted"> till ${esc(date(active.validUntil))}</span>` : ""}
        ${active.description ? `<span class="muted"> — ${esc(active.description)}</span>` : ""}</p>
        <button class="btn btn-danger" type="button" data-action="discount-clear">Ta bort rabatt</button>` : `
      <p class="muted">Procent eller fast belopp dras av platserna i prismotorn.
        Syns i offerter och MRR.</p>
      <form id="discountForm" class="form-grid">
        <label>Typ<select name="kind">
          <option value="percent_bp">Procent</option>
          <option value="fixed_ore">Fast belopp (kr/mån exkl. moms)</option>
        </select></label>
        <label>Värde<input name="value" type="number" min="1" required placeholder="10 eller 50000" /></label>
        <label>Giltig till <span class="muted">(valfritt)</span><input name="validUntil" type="date" /></label>
        <label class="span-2">Anteckning<input name="description" placeholder="Avtal med VD 2026-10-01" /></label>
        <div class="btn-row span-2"><button class="btn btn-primary" type="submit">Spara rabatt</button></div>
      </form>`}
    </details>`;
}

export function discountBody(form) {
  const data = new FormData(form);
  const kind = String(data.get("kind") ?? "percent_bp");
  let value = Number(data.get("value"));
  if (kind === "fixed_ore") {
    value = Math.round(value * 100);
  } else {
    value = Math.round(value * 100);
  }
  return {
    kind,
    value,
    description: String(data.get("description") ?? "").trim(),
    validUntil: String(data.get("validUntil") ?? "").trim() || null,
  };
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
      <label>Högst antal platser <span class="muted">(tillfällig åtkomst)</span><input name="vehicleLimit" type="number" min="1" max="50" value="3" /></label>
      <label>Högst antal inlösen <span class="muted">(tom = obegränsat)</span><input name="maxRedemptions" type="number" min="1" /></label>
      <label>Giltig till och med<input name="validUntil" type="date" /></label>
      <p class="muted span-2">Utan betalande abonnemang ger kupongen tillfällig åtkomst som slutar utan
        kostnad. Med abonnemang i Stripe flyttas nästa debitering. Med abonnemang som betalas
        utanför Stripe förlängs perioden. Ett bolag kan använda samma kupong en gång.</p>
      <div class="btn-row span-2"><button class="btn btn-primary" type="submit">Skapa kupong</button></div>
    </form>` : '<p class="muted">Kuponger skapas av en plattformsadministratör. Säljare löser in dem på kundens sida.</p>'}
    <div class="card"><table>
      <thead><tr><th>Kod</th><th>Dagar</th><th>Platser</th><th>Inlösta</th><th>Giltig till</th><th>Status</th><th></th></tr></thead>
      <tbody>${rows.map((c) => `
        <tr><td data-label="Kod"><b class="mono">${esc(c.code)}</b><div class="muted">${esc(c.description)}</div></td>
          <td data-label="Dagar">${esc(c.days)}</td>
          <td data-label="Platser">${esc(c.vehicleLimit)}</td>
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
