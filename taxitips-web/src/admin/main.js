import { ApiError, supabase } from "../portal/api.js";
import { admin } from "./api.js";
import * as sales from "./sales.js";
import * as views from "./views.js";

/**
 * Adminwebbens sammanhållning.
 *
 * Inloggningen är densamma som kundportalens (Supabase Auth). Vad inloggningen
 * GER avgörs av servern: utan en aktiv StaffRole svarar varje anrop
 * `not_staff`, och då visas bara det meddelandet. Ingen del av gränssnittet
 * "låtsas" att den som loggat in är admin.
 *
 * Varje ändring bekräftas först och loggas av servern med vem som gjorde den.
 */

const el = {
  login: document.getElementById("login"),
  loginForm: document.getElementById("loginForm"),
  loginError: document.getElementById("loginError"),
  app: document.getElementById("app"),
  view: document.getElementById("view"),
  tabs: document.querySelectorAll(".tab"),
  whoami: document.getElementById("whoami"),
  logout: document.getElementById("logout"),
  globalError: document.getElementById("globalError"),
  codeDialog: document.getElementById("codeDialog"),
  codeValue: document.getElementById("codeValue"),
  codeFor: document.getElementById("codeFor"),
  codeTimer: document.getElementById("codeTimer"),
};

const state = {
  view: "oversikt",
  companyId: null,
  query: "",
  pushStatus: "",
  eventQuery: "",
  eventHidden: false,
  // Säljflödet: län, prislista, Stripe-läge och vad den inloggade får göra.
  config: null,
  lookup: null,
  lookupOrg: "",
  // Den senaste offerten, så att beställningen skickar exakt det kunden hörde.
  quotedChange: null,
};

function showError(error) {
  const message = error instanceof ApiError ? error.message : "Något gick fel. Prova igen.";
  el.globalError.textContent = message;
  el.globalError.hidden = false;
}

function clearError() {
  el.globalError.hidden = true;
}

function setTab(view) {
  for (const tab of el.tabs) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === view));
  }
}

async function render() {
  clearError();
  el.view.innerHTML = '<p class="muted">Laddar …</p>';
  const note = state.flash;
  state.flash = null;
  try {
    await renderView();
  } finally {
    if (note) el.view.insertAdjacentHTML("afterbegin", `<p class="ok flash" role="status">${sales.esc(note)}</p>`);
  }
}

async function renderView() {
  try {
    if (!state.config) state.config = await admin.salesConfig();
    if (state.companyId) {
      el.view.innerHTML = views.kund(await admin.company(state.companyId), state.config);
      return;
    }
    switch (state.view) {
      case "oversikt":
        el.view.innerHTML = views.oversikt(await admin.overview());
        break;
      case "kunder":
        el.view.innerHTML = views.kunder(await admin.companies(state.query), state.query);
        break;
      case "abonnemang":
        el.view.innerHTML = views.abonnemang(await admin.companies());
        break;
      case "nykund":
        el.view.innerHTML = sales.nyKund(state.config, state.lookup, state.lookupOrg);
        break;
      case "kuponger":
        el.view.innerHTML = sales.kuponger(await admin.coupons(), state.config);
        break;
      case "notiser":
        el.view.innerHTML = views.notiser(await admin.notifications(state.pushStatus), state.pushStatus);
        break;
      case "evenemang":
        el.view.innerHTML = views.evenemang(
          await admin.events(state.eventQuery, state.eventHidden),
          state.eventQuery,
          state.eventHidden,
        );
        break;
      case "granskning":
        el.view.innerHTML = views.granskning(await admin.reviews("open"));
        break;
      default:
        el.view.innerHTML = "";
    }
  } catch (error) {
    el.view.innerHTML = "";
    if (error instanceof ApiError && error.reason === "not_staff") {
      el.view.innerHTML = `<div class="card"><h2>Ingen adminbehörighet</h2>
        <p>Kontot är inloggat men har ingen roll i plattformens personal.
        Kunder använder <a href="/portal">kundportalen</a>.</p></div>`;
      return;
    }
    showError(error);
  }
}

/* --- Inloggning ------------------------------------------------------- */

const EMAIL_KEY = "tt_admin_email";

/**
 * Förifyller e-posten. Från `?email=` i adressen (en länk man kan spara som
 * bokmärke), annars den som senast loggade in i den här webbläsaren.
 *
 * Aldrig inskriven i själva sidan: admin.taxitips.se är publik, och en
 * förifylld adress i HTML:en hade talat om för vem som helst vilket
 * användarnamn som är administratörens.
 */
function prefillEmail() {
  const input = document.getElementById("email");
  if (!input || input.value) return;
  const fromUrl = new URLSearchParams(window.location.search).get("email");
  let remembered = "";
  try {
    remembered = window.localStorage.getItem(EMAIL_KEY) || "";
  } catch {
    /* privat läge eller blockerad lagring: inget att förifylla */
  }
  input.value = fromUrl || remembered;
  if (input.value) document.getElementById("password")?.focus();
}

function rememberEmail(email) {
  try {
    if (email) window.localStorage.setItem(EMAIL_KEY, email);
  } catch {
    /* bekvämlighet, inte funktion */
  }
}

async function boot() {
  prefillEmail();
  const { data } = await supabase().auth.getSession();
  if (data?.session) return enterApp(data.session);
  el.login.hidden = false;
}

// Inloggningen triggar både formulärets svar och `onAuthStateChange`; appen
// ska bara startas en gång, annars renderas allt två gånger i otakt.
let entered = false;

async function enterApp(session) {
  if (entered) return;
  entered = true;
  el.login.hidden = true;
  el.app.hidden = false;
  el.logout.hidden = false;
  document.getElementById("changePassword").hidden = false;
  el.whoami.textContent = session.user?.email ?? "";
  rememberEmail(session.user?.email);
  await render();
}

el.loginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  el.loginError.hidden = true;
  const form = new FormData(el.loginForm);
  try {
    const { data, error } = await supabase().auth.signInWithPassword({
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
    });
    if (error) throw error;
    await enterApp(data.session);
  } catch (error) {
    el.loginError.textContent = error?.message ?? "Kunde inte logga in.";
    el.loginError.hidden = false;
  }
});

/**
 * Inloggningslänk via e-post.
 *
 * Konton som skapats med Google har inget lösenord, och Google-inloggning är
 * inte konfigurerad i produktionens Supabase Auth. En länk till den verifierade
 * adressen loggar in samma konto -- GoTrue matchar på e-post -- utan att något
 * lösenord behöver sättas eller skickas någonstans.
 *
 * `shouldCreateUser: false`: adminwebben skapar aldrig konton. Att någon kan
 * begära en länk till en okänd adress får inte bli ett sätt att registrera sig.
 */
document.getElementById("magicLink")?.addEventListener("click", async () => {
  el.loginError.hidden = true;
  const email = String(new FormData(el.loginForm).get("email") ?? "").trim();
  const sent = document.getElementById("magicSent");
  if (!email) {
    el.loginError.textContent = "Skriv din e-post först.";
    el.loginError.hidden = false;
    return;
  }
  try {
    const { error } = await supabase().auth.signInWithOtp({
      email,
      options: {
        shouldCreateUser: false,
        emailRedirectTo: `${window.location.origin}${window.location.pathname}`,
      },
    });
    if (error) throw error;
    sent.textContent = `Om ${email} har ett konto kommer en inloggningslänk strax.`;
    sent.hidden = false;
  } catch (error) {
    el.loginError.textContent = error?.message ?? "Kunde inte skicka länken.";
    el.loginError.hidden = false;
  }
});

// Länken landar här med sessionen i URL:en. Supabase-klienten plockar upp den
// själv (detectSessionInUrl); det här ser bara till att appen visas direkt.
supabase().auth.onAuthStateChange((event, session) => {
  if (event === "SIGNED_IN" && session && el.app.hidden) {
    enterApp(session);
  }
});

document.getElementById("changePassword")?.addEventListener("click", async () => {
  const first = prompt("Nytt lösenord (minst 12 tecken):");
  if (first === null) return;
  if (first.length < 12) {
    alert("Lösenordet måste vara minst 12 tecken.");
    return;
  }
  const second = prompt("Skriv det nya lösenordet igen:");
  if (second === null) return;
  if (first !== second) {
    alert("Lösenorden stämmer inte överens. Inget ändrades.");
    return;
  }
  try {
    const { error } = await supabase().auth.updateUser({ password: first });
    if (error) throw error;
    alert("Lösenordet är bytt.");
  } catch (error) {
    alert(error?.message ?? "Kunde inte byta lösenord.");
  }
});

el.logout?.addEventListener("click", async () => {
  await supabase().auth.signOut();
  window.location.reload();
});

/* --- Navigering ------------------------------------------------------- */

for (const tab of el.tabs) {
  tab.addEventListener("click", () => {
    state.view = tab.dataset.view;
    state.companyId = null;
    setTab(state.view);
    render();
  });
}

el.view.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  clearError();
  try {
    switch (form.id) {
      case "searchForm":
        state.query = new FormData(form).get("q")?.toString().trim() ?? "";
        break;
      case "eventForm":
        state.eventQuery = document.getElementById("eq")?.value.trim() ?? "";
        state.eventHidden = document.getElementById("ehidden")?.checked ?? false;
        break;
      case "lookupForm":
        state.lookupOrg = new FormData(form).get("orgNumber")?.toString().trim() ?? "";
        state.lookup = await admin.lookup(state.lookupOrg);
        break;
      case "companyForm": {
        const created = await admin.createCompany(sales.companyBody(form));
        state.lookup = null;
        state.lookupOrg = "";
        state.companyId = created.companyId;
        break;
      }
      case "profileForm":
        await admin.updateProfile(state.companyId, sales.profileBody(form));
        flash("Uppgifterna är sparade.");
        break;
      case "couponForm": {
        const result = await admin.createCoupon(sales.couponBody(form));
        flash(`Kupongen ${result.coupon.code} är skapad.`);
        break;
      }
      default:
        return;
    }
  } catch (error) {
    showError(error);
    return;
  }
  render();
});

/** Ett kort kvitto överst, som försvinner vid nästa åtgärd. */
function flash(message) {
  state.flash = message;
}

el.view.addEventListener("change", (event) => {
  if (event.target.id === "pushStatus") {
    state.pushStatus = event.target.value;
    render();
  }
});

el.view.addEventListener("click", async (event) => {
  const row = event.target.closest("[data-company]");
  if (row && !event.target.closest("button")) {
    state.companyId = row.dataset.company;
    state.quotedChange = null;
    return render();
  }
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  clearError();
  button.disabled = true;
  try {
    await act(button.dataset.action, button.dataset);
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
  }
});

/* --- Åtgärder --------------------------------------------------------- */

async function act(action, ds) {
  switch (action) {
    case "back":
      state.companyId = null;
      return render();

    case "extend": {
      const days = Number(ds.days);
      const note = prompt(
        `Förläng perioden med ${days} dagar.\n\nÄndrar appens rättigheter, inte Stripe. ` +
          "Ange ett skäl (sparas i loggen):",
      );
      if (note === null) return;
      await admin.setSubscription(state.companyId, { extendDays: days, note });
      return render();
    }

    case "code":
      return driverCode(ds.license, ds.plate);

    case "block": {
      if (!confirm("Spärra telefonen? Den slutar visa tips direkt och lämnar bilen.")) return;
      await admin.blockPhone(ds.approval, "admin_block");
      return render();
    }

    case "test-push": {
      const result = await admin.testPush(state.companyId);
      const lines = (result.results ?? []).map(
        (r) => `${r.device}: ${r.sent ? "skickad" : `inte skickad (${r.reason})`}`,
      );
      alert(lines.length ? lines.join("\n") : "Bolaget har inga telefoner.");
      return;
    }

    case "event-hide": {
      const reason = prompt("Varför döljs evenemanget för förarna?");
      if (!reason) return;
      await admin.setEventVisibility(Number(ds.event), true, reason);
      return render();
    }

    case "event-show":
      await admin.setEventVisibility(Number(ds.event), false);
      return render();

    case "review-approve":
    case "review-reject": {
      const approved = action === "review-approve";
      const note = prompt(approved ? "Godkänn — anteckning:" : "Avslå — skäl:");
      if (note === null) return;
      await admin.resolveReview(ds.review, approved, note);
      return render();
    }

    default:
      return salesAction(action, ds);
  }
}

/* --- Förare ----------------------------------------------------------- */

let codeTimer = null;

/**
 * En kod per förare. Namnet blir telefonens etikett i listan över godkända
 * telefoner, så att rätt telefon kan spärras senare. Koden gäller i fem
 * minuter (§2) och bara en per bil i taget -- därför en i taget, med
 * nedräkning, och en knapp för nästa förare i samma bil.
 */
async function driverCode(licenseId, plate) {
  const name = prompt(`Förarens namn (visas som telefonens namn) för ${plate || "bilen"}:`);
  if (name === null) return;
  const result = await admin.pairingCode(state.companyId, licenseId, name.trim() || "Förare");
  el.codeFor.textContent = `${name.trim() || "Förare"} · ${plate || "bilen"}`;
  el.codeValue.textContent = result.code;
  const expires = new Date(result.expiresAt).getTime();
  const tick = () => {
    const left = Math.max(0, Math.round((expires - Date.now()) / 1000));
    el.codeTimer.textContent = left
      ? `Gäller i ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`
      : "Koden har gått ut. Skapa en ny.";
    if (!left) clearInterval(codeTimer);
  };
  clearInterval(codeTimer);
  tick();
  codeTimer = setInterval(tick, 1000);
  el.codeDialog.dataset.license = licenseId;
  el.codeDialog.dataset.plate = plate || "";
  el.codeDialog.showModal();
}

el.codeDialog?.addEventListener("close", () => {
  clearInterval(codeTimer);
  if (el.codeDialog.returnValue === "next") {
    driverCode(el.codeDialog.dataset.license, el.codeDialog.dataset.plate).catch(showError);
  } else {
    render();
  }
});

/* --- Säljflödet ------------------------------------------------------- */

function portalUrl() {
  // Kundportalen ligger på huvuddomänen, inte på admin-värden.
  const host = window.location.hostname.replace(/^admin\./, "");
  return `${window.location.protocol}//${host}${window.location.port ? `:${window.location.port}` : ""}/portal`;
}

function packageChange() {
  const panel = document.getElementById("salesPanel");
  const vehicles = panel ? sales.readVehicles(panel) : [];
  if (!vehicles.length) {
    throw new ApiError(400, "Fyll i minst ett registreringsnummer.", "vehicles_required");
  }
  return { vehicles, change: { addVehicles: vehicles } };
}

function showResult(html) {
  const box = document.getElementById("pkgResult");
  if (box) box.innerHTML = html;
}

function stripeWarning(result) {
  const stripe = result?.stripe;
  return stripe && stripe.synced === false ? `\n\nOBS: ${stripe.message}` : "";
}

let rowCounter = 0;

async function salesAction(action, ds) {
  const companyId = state.companyId;
  switch (action) {
    case "open-company":
      state.companyId = ds.id;
      state.view = "kunder";
      setTab("kunder");
      return render();

    case "pkg-add-row": {
      const rows = document.getElementById("pkgRows");
      rowCounter += 1;
      rows.insertAdjacentHTML("beforeend", sales.vehicleRow(state.config.counties, rowCounter));
      return;
    }

    case "pkg-remove-row": {
      const rows = document.getElementById("pkgRows");
      if (rows.children.length > 1) rows.querySelector(`.pkg-row[data-row="${ds.row}"]`)?.remove();
      return;
    }

    case "pkg-quote": {
      const { change } = packageChange();
      const quote = await admin.quote(companyId, change);
      state.quotedChange = JSON.stringify(change);
      document.getElementById("pkgQuote").innerHTML = sales.quoteBox(quote);
      return;
    }

    case "pkg-trial": {
      const { vehicles } = packageChange();
      const result = await admin.startTrial(companyId, vehicles);
      flash(
        `Provet omfattar nu ${result.vehicles} av högst ${result.vehicleLimit} bilar. ` +
          (result.endsAt ? "" : "Det startar när första telefonen ansluts. ") +
          "Lägg till förare under Licenser och bilar.",
      );
      return render();
    }

    case "pkg-coupon": {
      const code = document.getElementById("couponCode")?.value.trim();
      if (!code) throw new ApiError(400, "Skriv kupongkoden.", "code_required");
      const panel = document.getElementById("salesPanel");
      const vehicles = panel ? sales.readVehicles(panel) : [];
      const result = await admin.redeemCoupon(companyId, code, vehicles);
      const text = {
        temporary_access: `Tillfällig åtkomst i ${result.days} dagar, till ${result.detail.accessUntil?.slice(0, 10)}.`,
        billing_deferred: `Nästa debitering är flyttad till ${result.detail.nextBillingAt?.slice(0, 10)}.`,
        period_extended: `Perioden är förlängd till ${result.detail.periodEnd?.slice(0, 10)}.`,
      }[result.effect];
      flash(`Kupongen är inlöst. ${text ?? ""}`);
      return render();
    }

    case "pkg-order": {
      const { change } = packageChange();
      if (state.quotedChange !== JSON.stringify(change)) {
        throw new ApiError(
          400,
          "Räkna priset först, och läs upp det för kunden. Bilarna har ändrats sedan offerten.",
          "quote_required",
        );
      }
      if (!document.getElementById("pkgAccepted")?.checked) {
        throw new ApiError(
          400,
          "Bekräfta att kunden har godkänt antal, pris och betalningsdatum.",
          "acceptance_required",
        );
      }
      const payment = document.getElementById("pkgPayment").value;
      const result = await admin.order(companyId, {
        ...change,
        accepted: true,
        payment,
        daysUntilDue: Number(document.getElementById("pkgDue")?.value || 14),
      });
      state.quotedChange = null;
      return orderResult(result);
    }

    case "lic-add-county": {
      const county = document.querySelector(`[data-county-for="${ds.license}"]`)?.value;
      if (!county) return;
      return quotedOrder({ addCounties: [{ licenseId: ds.license, county }] });
    }

    case "lic-cancel": {
      if (!confirm(`Avsluta licensen för ${ds.plate} vid nästa förnyelse? Bilen fungerar perioden ut.`)) return;
      return quotedOrder({ cancelLicenseIds: [ds.license] });
    }

    case "owner-invite": {
      const email = document.getElementById("ownerEmail")?.value.trim();
      if (!email) throw new ApiError(400, "Skriv e-postadressen.", "email_required");
      const invite = await admin.inviteOwner(companyId, email);
      // Länken skickas av Supabase Auth, som också skapar kontot om det inte
      // finns. Kontot knyts till bolaget först när personen loggar in med den
      // här adressen (fleet/api.py:claim_invite).
      const { error } = await supabase().auth.signInWithOtp({
        email: invite.email,
        options: { shouldCreateUser: true, emailRedirectTo: portalUrl() },
      });
      flash(
        error
          ? `Inbjudan är sparad, men e-posten kunde inte skickas: ${error.message}. ` +
              `Be kunden gå till ${portalUrl()} och begära en inloggningslänk till ${invite.email}.`
          : `En inloggningslänk är skickad till ${invite.email}. Inbjudan gäller till ${invite.expiresAt.slice(0, 10)}.`,
      );
      return render();
    }

    case "cancel-period": {
      const reason = prompt("Säg upp till periodens slut. Varför slutar kunden? (sparas i loggen)");
      if (reason === null) return;
      const result = await admin.cancelSubscription(companyId, reason, false);
      alert(`Uppsagt till ${result.effectiveAt?.slice(0, 10)}. Kunden har åtkomst till dess.${stripeWarning(result)}`);
      return render();
    }

    case "undo-cancel": {
      const result = await admin.undoCancel(companyId);
      alert(`Uppsägningen är ångrad.${stripeWarning(result)}`);
      return render();
    }

    case "terminate-now": {
      const reason = prompt(
        "AVSLUTA DIREKT: åtkomsten upphör nu, alla licenser och förarpass avslutas och " +
          "Stripe slutar debitera. Ingen återbetalning görs automatiskt.\n\nSkäl (obligatoriskt):",
      );
      if (!reason) return;
      if (!confirm("Är du säker? Det går inte att ångra.")) return;
      const result = await admin.cancelSubscription(companyId, reason, true);
      alert(`Abonnemanget är avslutat.${stripeWarning(result)}`);
      return render();
    }

    case "copy-link":
      await navigator.clipboard.writeText(ds.url);
      flash("Betallänken är kopierad. Skicka den till kunden.");
      return render();

    case "order-link": {
      const payment = confirm("Kort (OK) eller faktura via e-post (Avbryt)?") ? "stripe_card" : "stripe_invoice";
      await admin.paymentLink(ds.order, payment);
      flash("Betallänken är skapad.");
      return render();
    }

    case "order-refresh": {
      const result = await admin.refreshOrder(ds.order);
      flash(
        result.orderStatus === "applied"
          ? "Betalningen har gått igenom. Paketet är aktivt."
          : `Stripe: fakturan är ${result.invoiceStatus}. Ingenting är ändrat än.`,
      );
      return render();
    }

    case "order-paid": {
      const note = prompt(
        "Markera betald utanför Stripe. Paketet aktiveras direkt.\n\nHur betalade kunden? (t.ex. fakturanummer)",
      );
      if (!note) return;
      await admin.markPaid(ds.order, note);
      flash("Ordern är markerad som betald och paketet är aktivt.");
      return render();
    }

    case "order-cancel": {
      if (!confirm("Avbryta den obetalda ordern? En faktura i Stripe makuleras.")) return;
      await admin.cancelOrder(ds.order, "Avbruten av säljare");
      flash("Ordern är avbruten.");
      return render();
    }

    case "coupon-off": {
      if (!confirm("Stänga av kupongen? Redan inlösta påverkas inte.")) return;
      await admin.deactivateCoupon(ds.coupon);
      return render();
    }

    default:
      return;
  }
}

/** Ändring på en befintlig licens: offert, bekräftelse, beställning. */
async function quotedOrder(change) {
  const quote = await admin.quote(state.companyId, change);
  const box = document.createElement("div");
  box.innerHTML = sales.quoteBox(quote);
  if (!confirm(`${box.innerText}\n\nHar kunden godkänt det här?`)) return;
  const stripeOk = !!state.config?.stripe?.available;
  const result = await admin.order(state.companyId, {
    ...change,
    accepted: true,
    payment: stripeOk ? "stripe_card" : "later",
  });
  return orderResult(result);
}

function orderResult(result) {
  const order = result.order;
  const pay = result.payment ?? {};
  if (order.status === "pending_payment") {
    if (pay.paymentUrl) {
      flash("Beställningen väntar på betalning. Betallänken finns under Beställningar — kopiera och skicka den till kunden.");
    } else if (pay.stripeError) {
      flash(`Beställningen är sparad men ingen betallänk skapades: ${pay.stripeError.message}`);
    } else {
      flash("Beställningen är sparad och väntar på betalning.");
    }
  } else if (order.status === "scheduled") {
    flash("Ändringen gäller från nästa förnyelse.");
  } else {
    flash("Beställningen är verkställd.");
  }
  return render();
}

boot().catch((error) => {
  el.login.hidden = false;
  showError(error);
});
