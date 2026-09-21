import { ApiError, api, supabase } from "./api.js";
import * as views from "./views.js";
import { quoteHtml } from "./views.js";

/**
 * Portalens sammanhållning: inloggning, vyval och åtgärder.
 *
 * **Ingen åtgärd som rör pengar körs utan att kunden sett beloppet.** Köp går
 * alltid genom `api.quote()` först, och beställningen skickas först efter ett
 * uttryckligt ja på kostnad nu, nästa period, moms och datum.
 *
 * **Felen kommer från servern.** Portalen hittar inte på egna meddelanden om
 * behörighet, granskning eller betalning -- den visar backendens `message`,
 * som är skriven för kunden. Ett andra regelverk här hade kunnat säga något
 * annat än det som faktiskt gäller.
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
};

let state = { view: "oversikt", data: null, orders: null };

function showError(error) {
  const message =
    error instanceof ApiError ? error.message : "Något gick fel. Prova igen.";
  el.globalError.textContent = message;
  el.globalError.hidden = false;
}

function clearError() {
  el.globalError.hidden = true;
  el.globalError.textContent = "";
}

async function boot() {
  const { data } = await supabase().auth.getSession();
  if (data?.session) {
    await enterApp(data.session);
  } else {
    el.login.hidden = false;
  }
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
  el.whoami.textContent = session.user?.email ?? "";
  await refresh();
}

async function refresh() {
  clearError();
  try {
    state.data = await companyOrClaim();
    if (state.view === "abonnemang" && !state.orders) {
      state.orders = await api.orders();
    }
  } catch (error) {
    showError(error);
    return;
  }
  render();
}

function render() {
  const data = state.data;
  if (!data) return;
  const html = {
    oversikt: () => views.oversikt(data),
    bilar: () => views.bilar(data),
    lan: () => views.lan(data),
    abonnemang: () => views.abonnemang(data, state.orders?.orders ?? []),
    foretag: () => views.foretag(data),
  }[state.view];
  el.view.innerHTML = html ? html() : "";
}

/**
 * Första inloggningen efter en inbjudan: kontot hör inte till något företag
 * än. Servern knyter det till företaget som bjöd in e-postadressen -- och bara
 * då; adressen läses ur den verifierade inloggningen, inte ur något vi skickar.
 */
async function companyOrClaim() {
  try {
    return await api.company();
  } catch (error) {
    if (!(error instanceof ApiError) || error.reason !== "missing_permission") throw error;
    try {
      await api.claimInvite();
    } catch (claimError) {
      if (claimError instanceof ApiError && claimError.reason === "no_invite") {
        throw new ApiError(
          403,
          "Kontot är inte kopplat till något företag. Be den som sköter ert konto, " +
            "eller Taxi Tips, att bjuda in din e-postadress.",
          "no_company",
        );
      }
      throw claimError;
    }
    return api.company();
  }
}

/* --- Inloggning --------------------------------------------------------- */

/**
 * Inloggningslänk via e-post. `shouldCreateUser: false`: portalen skapar inga
 * konton på egen hand. Ett inbjudet konto skapas när säljaren skickar den
 * första länken; den här knappen ger en ny länk om den första hunnit gå ut.
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

// Länken landar här med sessionen i URL:en; klienten plockar upp den själv.
supabase().auth.onAuthStateChange((event, session) => {
  if (event === "SIGNED_IN" && session && el.app.hidden) {
    enterApp(session);
  }
});

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
    el.loginError.textContent =
      error?.message ?? "Kunde inte logga in. Kontrollera e-post och lösenord.";
    el.loginError.hidden = false;
  }
});

el.logout?.addEventListener("click", async () => {
  await supabase().auth.signOut();
  window.location.reload();
});

/* --- Vyval -------------------------------------------------------------- */

for (const tab of el.tabs) {
  tab.addEventListener("click", async () => {
    for (const other of el.tabs) other.setAttribute("aria-selected", "false");
    tab.setAttribute("aria-selected", "true");
    state.view = tab.dataset.view;
    if (state.view === "abonnemang" && !state.orders) {
      try {
        state.orders = await api.orders();
      } catch (error) {
        showError(error);
      }
    }
    render();
  });
}

/* --- Åtgärder ----------------------------------------------------------- */

el.view.addEventListener("submit", async (event) => {
  const form = event.target;
  if (form.id !== "vehicleForm") return;
  event.preventDefault();
  clearError();
  const data = new FormData(form);
  try {
    await api.createVehicle(
      String(data.get("plate") ?? ""),
      String(data.get("label") ?? ""),
    );
    await refresh();
  } catch (error) {
    showError(error);
  }
});

el.view.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  clearError();
  const { action, license, vehicle, plate, approval } = button.dataset;
  button.disabled = true;
  try {
    await handle(action, { license, vehicle, plate, approval });
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
  }
});

async function handle(action, ctx) {
  switch (action) {
    case "pair": {
      const result = await api.pairingCode(ctx.license, ctx.vehicle, "");
      el.codeFor.textContent = `För ${ctx.plate || "bilen"}.`;
      el.codeValue.textContent = result.code;
      el.codeDialog.showModal();
      return;
    }
    case "block": {
      if (
        !confirm(
          "Spärra telefonen? Den slutar visa tips direkt och lämnar bilen. " +
            "Telefonen behöver anslutas på nytt för att användas igen.",
        )
      )
        return;
      await api.blockPhone(ctx.approval, "lost_phone");
      return refresh();
    }
    case "change-vehicle": {
      const plate = prompt(
        "Registreringsnummer för den nya bilen. Licensens betalperiod, län och " +
          "provhistorik följer med; den gamla bilens telefoner måste godkännas på nytt.",
      );
      if (!plate) return;
      const created = await api.createVehicle(plate, "");
      await api.changeVehicle(ctx.license, {
        mode: "permanent",
        vehicle_id: created.vehicleId,
      });
      return refresh();
    }
    case "add-county": {
      const select = document.querySelector(`[data-county-for="${ctx.license}"]`);
      const county = select?.value;
      if (!county) return;
      return buy({ addCounties: [{ licenseId: ctx.license, county }] });
    }
    case "change-base": {
      const select = document.querySelector(`[data-county-for="${ctx.license}"]`);
      const county = select?.value;
      if (!county) return;
      const now = confirm(
        "Behöver du det nya länet direkt?\n\n" +
          "OK: vi köper länet som tillägg nu (proportionellt för resten av " +
          "perioden) och byter baslän vid nästa förnyelse. Tillägget tas bort " +
          "automatiskt vid bytet.\n\n" +
          "Avbryt: bytet sker vid nästa förnyelse och kostar inget nu.",
      );
      return buy({
        baseCountyChanges: [{ licenseId: ctx.license, county, immediate: now }],
      });
    }
    case "add-license": {
      const plate = prompt("Registreringsnummer för bilen:");
      if (!plate) return;
      const county = prompt("Baslän (SCB-kod, t.ex. 12 för Skåne):");
      if (!county) return;
      return buy({
        addVehicles: [{ plate, baseCounty: county, label: "", extraCounties: [] }],
      });
    }
    case "cancel": {
      if (
        !confirm(
          "Säga upp abonnemanget?\n\nNästa period stoppas. Du behåller " +
            "åtkomsten den betalda perioden ut och kan ångra dig fram till " +
            "slutdatumet.",
        )
      )
        return;
      const result = await api.cancel("");
      alert(result.message);
      state.orders = null;
      return refresh();
    }
    case "undo-cancel": {
      await api.undoCancel();
      state.orders = null;
      return refresh();
    }
    case "close-account": {
      if (
        !confirm(
          "Avsluta företagskontot? Förnyelsen stoppas. Åtkomsten gäller den " +
            "betalda perioden ut.",
        )
      )
        return;
      const result = await api.closeAccount();
      alert(result.explanation);
      return refresh();
    }
    default:
      return;
  }
}

/**
 * Köp: offert först, godkännande sedan, beställning sist.
 *
 * Ordningen är regeln, inte en artighet -- §6 kräver att kunden ser kostnad nu,
 * nästa period, moms, totalsumma och datum innan beställningen godkänns.
 */
async function buy(change) {
  const quote = await api.quote(change);
  const summary = document.createElement("div");
  summary.innerHTML = quoteHtml(quote);

  const accepted = confirm(
    `${summary.textContent}\n\nGodkänner du beställningen?`,
  );
  if (!accepted) return;

  const order = await api.order(change);
  if (order.status === "pending_payment" && order.paymentUrl) {
    // Stripes betalsida. Rättigheterna ges när Stripe bekräftat betalningen,
    // inte när kunden kommer tillbaka hit.
    const go = confirm(
      "Beställningen väntar på betalning. Öppna betalsidan nu?\n\n" +
        "Bilarna och länen aktiveras när betalningen har gått igenom.",
    );
    if (go) window.open(order.paymentUrl, "_blank", "noopener");
  } else if (order.status === "pending_payment") {
    alert(
      "Beställningen är registrerad och väntar på betalning. Rättigheterna " +
        "träder i kraft när betalningen har gått igenom." +
        (order.paymentError ? `\n\n${order.paymentError.message}` : ""),
    );
  } else if (order.status === "scheduled") {
    alert(
      "Ändringen är schemalagd till nästa förnyelse. Fram till dess gäller " +
        "det du har nu.",
    );
  }
  state.orders = null;
  return refresh();
}

boot().catch((error) => {
  el.login.hidden = false;
  showError(error);
});
