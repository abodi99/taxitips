import { portal } from "../config.js";

/**
 * "Fortsätt här" (fortsatt.html): betalning i två tryck från mejlet/SMS:et
 * när provet tar slut. Ingen inloggning och ingen portal.
 *
 * **Biljetten.** Länken är `/fortsatt#t=<biljett>`. Biljetten ligger i
 * fragmentet så att den aldrig skickas till en server (inte heller i våra
 * åtkomstloggar). Sidan läser den, sparar den i `sessionStorage` -- Stripe tar
 * kunden bort från sidan och tillbaka (`?betalning=klar|avbruten`) utan
 * biljett i adressen -- och tar sedan bort fragmentet ur adressfältet. Den
 * skickas bara i kroppen på POST-anrop mot backenden, aldrig i en adress, och
 * loggas eller mäts aldrig.
 *
 * **Priset räknar servern.** Sidan formaterar bara det backenden svarar
 * (`/api/fleet/continue/offer`). Betalningen startas av `/continue/checkout`,
 * som själv bygger planen ur provets platser.
 */

const STORAGE_KEY = "taxitips.continue.token";
const POLL_TIMES = 8;
const POLL_EVERY_MS = 2500;

const root = document.getElementById("app");

/* --- Biljetten ---------------------------------------------------------- */

function stored() {
  try {
    return sessionStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function store(token) {
  try {
    sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    /* privat läge: biljetten finns då bara kvar i minnet */
  }
}

/** Läser #t= (och sparar den), annars sparad biljett från före Stripe. */
function takeToken() {
  const match = /(?:^#|&)t=([^&]+)/.exec(location.hash);
  let token = "";
  if (match) {
    try {
      token = decodeURIComponent(match[1]);
    } catch {
      token = "";
    }
    if (token) store(token);
  }
  // Adressfältet ska inte bära biljetten (historik, delning, skärmdump).
  const outcome = new URLSearchParams(location.search).get("betalning");
  if (location.hash || location.search) {
    history.replaceState(null, "", location.pathname);
  }
  return { token: token || stored(), outcome };
}

/* --- Anropen ------------------------------------------------------------ */

class ApiError extends Error {
  constructor(status, data) {
    super(data?.message || "Något gick fel. Försök igen.");
    this.status = status;
    this.reason = data?.reason || "error";
    this.detail = data?.detail || null;
  }
}

async function call(path, token, extra = {}) {
  let res;
  try {
    res = await fetch(`${portal.apiBaseUrl}/api/fleet/continue/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ token, ...extra }),
    });
  } catch {
    throw new ApiError(0, { message: "Ingen kontakt med Taxi Tips. Kontrollera nätet och försök igen.", reason: "network" });
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* tomt svar */
  }
  if (!res.ok || !data?.ok) throw new ApiError(res.status, data);
  return data;
}

/* --- Små hjälpare ------------------------------------------------------- */

/** Bygger element utan innerHTML: texter från servern tolkas aldrig som HTML. */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

function money(ore, currency = "SEK") {
  return new Intl.NumberFormat("sv-SE", {
    style: "currency",
    currency,
    minimumFractionDigits: ore % 100 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(ore / 100);
}

function longDate(iso) {
  try {
    return new Intl.DateTimeFormat("sv-SE", { day: "numeric", month: "long" }).format(new Date(iso));
  } catch {
    return "";
  }
}

function show(...nodes) {
  root.replaceChildren(...nodes.flat().filter(Boolean));
  root.focus?.();
}

const PORTAL_LINK = () => h("a", { class: "btn btn-outline btn-block", href: "/portal" }, "Till kundportalen");

/* --- Vyerna ------------------------------------------------------------- */

function viewLoading(text = "Laddar …") {
  show(h("p", { class: "muted center" }, text));
}

function viewProblem(message) {
  show(
    h("div", { class: "card center" },
      h("div", { class: "mark warn", "aria-hidden": "true" }, "!"),
      h("h1", {}, "Länken fungerar inte"),
      h("p", { class: "muted" }, message),
      PORTAL_LINK(),
    ),
  );
}

function viewNothing() {
  show(
    h("div", { class: "card center" },
      h("h1", {}, "Det finns inget att betala."),
      h("p", { class: "muted" }, "Har du frågor? Skriv till oss i appens chatt."),
      PORTAL_LINK(),
    ),
  );
}

function viewPaid(title = "Klart! Öppna appen.") {
  show(
    h("div", { class: "card center" },
      h("div", { class: "mark", "aria-hidden": "true" }, "✓"),
      h("h1", {}, title),
      h("p", { class: "muted" }, "Förarna får tipsen som vanligt. Du kan stänga den här sidan."),
    ),
  );
}

function viewProcessing(text = "Betalningen behandlas …") {
  show(
    h("div", { class: "card center" },
      h("div", { class: "mark wait", "aria-hidden": "true" }, "…"),
      h("h1", {}, text),
      h("p", { class: "muted" }, "Det tar bara en liten stund."),
    ),
  );
}

/**
 * Erbjudandet. `note` är ett lugnt meddelande överst (till exempel att
 * betalningen avbröts). Fälten för organisationsnummer visas bara när
 * servern säger att numret saknas, och namnet bara när registret inte
 * hittade bolaget -- samma beteende som portalens "Företagets uppgifter".
 */
function viewOffer(token, offer, { note = "" } = {}) {
  let askName = false;
  const orgInput = h("input", {
    id: "orgNumber", name: "orgNumber", inputmode: "numeric", autocomplete: "off",
    autocapitalize: "off", "aria-describedby": "orgHelp orgError",
  });
  const orgError = h("p", { class: "error field-error", id: "orgError", role: "alert", hidden: true });
  const nameInput = h("input", { id: "legalName", name: "legalName", autocomplete: "organization", "aria-describedby": "nameError" });
  const nameError = h("p", { class: "error field-error", id: "nameError", role: "alert", hidden: true });
  const nameField = h("div", { hidden: true },
    h("label", { for: "legalName" }, "Företagets namn"),
    nameInput,
    nameError,
  );
  const accept = h("input", { type: "checkbox", id: "accept" });
  const acceptError = h("p", { class: "error field-error", role: "alert", hidden: true });
  const formError = h("p", { class: "error", role: "alert", hidden: true });
  const pay = h("button", { class: "btn btn-primary btn-block btn-lg", type: "button" }, "Betala");

  const orgBlock = offer.needsOrgNumber
    ? h("div", { id: "orgBlock" },
        h("label", { for: "orgNumber" }, "Organisationsnummer"),
        orgInput,
        h("p", { class: "muted hint", id: "orgHelp" }, "Enskild firma: ditt personnummer"),
        orgError,
        nameField,
      )
    : null;

  function setError(el, message) {
    el.textContent = message || "";
    el.hidden = !message;
  }
  function clearErrors() {
    [orgError, nameError, acceptError, formError].forEach((el) => setError(el, ""));
    orgInput.removeAttribute("aria-invalid");
    nameInput.removeAttribute("aria-invalid");
  }
  function busy(on) {
    pay.disabled = on;
    pay.textContent = on ? "Ett ögonblick …" : "Betala";
  }
  function showOrgField(message) {
    // Servern kan kräva numret även om sidan trodde att det fanns: då saknas
    // fältet här, och felet visas som ett vanligt meddelande.
    if (!orgBlock) return setError(formError, message);
    orgInput.setAttribute("aria-invalid", "true");
    setError(orgError, message);
    orgInput.focus();
  }

  async function submit() {
    clearErrors();
    if (!accept.checked) {
      setError(acceptError, "Godkänn priset och villkoren för att betala.");
      accept.focus();
      return;
    }
    busy(true);
    try {
      if (offer.needsOrgNumber) {
        try {
          await call("org-number", token, {
            orgNumber: orgInput.value.trim(),
            ...(askName ? { legalName: nameInput.value.trim() } : {}),
          });
          offer.needsOrgNumber = false;
        } catch (error) {
          const field = error.detail?.field;
          if (error.reason === "org_number_set") {
            offer.needsOrgNumber = false; // numret fanns redan: gå vidare
          } else if (field === "legalName" || error.reason === "name_required") {
            askName = true;
            nameField.hidden = false;
            nameInput.setAttribute("aria-invalid", "true");
            setError(nameError, error.message);
            nameInput.focus();
            busy(false);
            return;
          } else if (field === "orgNumber") {
            orgInput.setAttribute("aria-invalid", "true");
            setError(orgError, error.message);
            orgInput.focus();
            busy(false);
            return;
          } else {
            throw error;
          }
        }
      }
      const result = await call("checkout", token, { accepted: true });
      if (result.paymentUrl) {
        // Samma flik: en ny flik efter ett await blockeras av mobilwebbläsaren.
        location.assign(result.paymentUrl);
        return;
      }
      if (result.alreadyCommitted) {
        viewPaid("Klart! Ni fortsätter.");
        return;
      }
      throw new ApiError(0, { message: "Kunde inte öppna betalsidan. Försök igen om en stund." });
    } catch (error) {
      if (error.detail?.field === "orgNumber") {
        showOrgField(error.message);
      } else if (["invalid_link", "expired_link"].includes(error.reason)) {
        viewProblem(error.message);
        return;
      } else {
        setError(formError, error.message);
      }
      busy(false);
    }
  }
  pay.addEventListener("click", submit);

  const vat = offer.vatPercent ? ` (${money(offer.monthlyTotalOre, offer.currency)} inkl. moms)` : "";
  show(
    h("h1", {}, "Fortsätt med Taxi Tips"),
    h("p", { class: "muted company" }, offer.companyName),
    note ? h("p", { class: "notice", role: "status" }, note) : null,
    h("div", { class: "card" },
      h("ul", { class: "items" }, offer.items.map((item) => h("li", {}, item.label))),
      h("p", { class: "price" }, money(offer.monthlyOre, offer.currency), h("small", {}, " /mån")),
      h("p", { class: "muted vat" }, `exkl. moms${vat}`),
      offer.state === "trial" && offer.trialEndsAt
        ? h("p", { class: "muted terms" }, `Provet gäller till ${longDate(offer.trialEndsAt)}. Du betalar första månaden nu.`)
        : null,
      // Samma löfte som kundportalens medlemskapsvy (src/portal/views.js).
      h("p", { class: "muted terms" }, "Månadsvis. Säg upp när ni vill, allt fungerar perioden ut."),
    ),
    orgBlock,
    h("label", { class: "accept", for: "accept" }, accept, h("span", {}, "Jag godkänner priset och villkoren")),
    acceptError,
    formError,
    pay,
  );
}

/* --- Start -------------------------------------------------------------- */

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Efter Stripe: webhooken kan landa en stund efter att kunden kommit tillbaka. */
async function afterPayment(token) {
  viewProcessing();
  for (let i = 0; i < POLL_TIMES; i += 1) {
    try {
      const offer = await call("offer", token);
      if (offer.state === "paid") {
        viewPaid();
        return;
      }
    } catch (error) {
      if (["invalid_link", "expired_link"].includes(error.reason)) {
        viewProblem(error.message);
        return;
      }
    }
    await delay(POLL_EVERY_MS);
  }
  show(
    h("div", { class: "card center" },
      h("div", { class: "mark wait", "aria-hidden": "true" }, "…"),
      h("h1", {}, "Betalningen är mottagen"),
      h("p", { class: "muted" }, "Det kan ta någon minut innan allt är klart. Öppna appen om en stund."),
      h("button", { class: "btn btn-outline btn-block", type: "button", onclick: () => afterPayment(token) }, "Kontrollera igen"),
    ),
  );
}

async function start() {
  const { token, outcome } = takeToken();
  if (!token) {
    viewProblem("Länken fungerar inte längre. Be om en ny i appens chatt eller logga in i kundportalen.");
    return;
  }
  if (outcome === "klar") {
    await afterPayment(token);
    return;
  }
  viewLoading();
  try {
    const offer = await call("offer", token);
    if (offer.state === "paid") return viewPaid();
    if (offer.state === "nothing") return viewNothing();
    viewOffer(token, offer, { note: outcome === "avbruten" ? "Betalningen avbröts." : "" });
  } catch (error) {
    viewProblem(error.message);
  }
}

start();
