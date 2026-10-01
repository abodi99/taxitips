import { setupConsent } from "./consent.js";
import { trackEvent } from "./analytics.js";
import { loadRuntimeConfig, portal } from "./config.js";
import { supabase } from "./portal/api.js";

/**
 * Registrering på webben (taxitips.se/registrera): samma väg som appens
 * (taxitips-app/lib/api_client.dart:signup), i samma ordning.
 *
 *   1. Bolagsverket-uppslag medan kunden skriver orgnr (GET /api/fleet/registry).
 *   2. Prövning före kontot (POST /api/fleet/register/check): fel mobilnummer
 *      eller ett orgnr som redan har ett konto ska synas INNAN e-posten
 *      bekräftats, inte efter.
 *   3. Konto i Supabase Auth.
 *   4. Bolaget och den kortfria provperioden (POST /api/fleet/register). Får
 *      kontot ingen session direkt (e-posten måste bekräftas) ligger bolagets
 *      uppgifter i användarens metadata, och kundportalen gör klart
 *      registreringen vid första inloggningen -- på vilken enhet som helst.
 *
 * Servern prövar allt igen; kontrollerna här finns bara för att säga det
 * direkt. Felen visas med serverns egna texter (fleet/signup_checks.py).
 */

loadRuntimeConfig().finally(() => setupConsent());

// På portal.taxitips.se är `/` portalen; logotypen ska leda till startsidan.
if (window.location.hostname.startsWith("portal.")) {
  document.querySelector(".brand-logo")?.setAttribute("href", "https://taxitips.se/");
}

const $ = (id) => document.getElementById(id);
const form = $("regForm");
const org = $("orgNumber");
const orgStatus = $("orgStatus");
const companyField = $("companyNameField");
const companyName = $("companyName");
const companyLabel = $("companyNameLabel");
const formError = $("formError");
const submitBtn = $("submitBtn");

/** Bekräftelselänken landar i portalen, som gör klart registreringen. */
const REDIRECT = `${window.location.origin}/portal`;

// ---------- Nummerregler (samma som appen och fleet/orgnr.py) ----------

function tenDigits(input) {
  let d = String(input).replace(/\D/g, "");
  if (d.length === 12) d = d.slice(2);
  return d;
}

export function orgLooksValid(input) {
  const d = tenDigits(input);
  if (d.length !== 10) return false;
  let sum = 0;
  for (let i = 0; i < 10; i++) {
    let x = Number(d[i]) * (i % 2 === 0 ? 2 : 1);
    if (x > 9) x -= 9;
    sum += x;
  }
  return sum % 10 === 0;
}

/** Personnummer (enskild firma) har månad 01–12 på plats tre och fyra. */
export function looksLikeSoleTrader(input) {
  const d = tenDigits(input);
  if (d.length !== 10) return false;
  const month = Number(d.slice(2, 4));
  return month >= 1 && month <= 12;
}

/** Svenskt mobilnummer: 07X och sju siffror, med eller utan +46. */
export function phoneLooksValid(input) {
  const raw = String(input).trim();
  let d = raw.replace(/\D/g, "");
  if (d.startsWith("0046")) d = d.slice(4);
  else if (raw.startsWith("+")) {
    if (!d.startsWith("46")) return false;
    d = d.slice(2);
  } else if (d.startsWith("46") && d.length === 11) d = d.slice(2);
  else if (d.startsWith("0")) d = d.slice(1);
  else return false;
  if (d.startsWith("0")) d = d.slice(1);
  return /^7[02369]\d{7}$/.test(d);
}

// ---------- Fältfel ----------

function setFieldError(field, message) {
  const wrap = form.querySelector(`[data-field="${field}"]`);
  if (!wrap) return;
  let p = wrap.querySelector(".rf-error-inline");
  const input = wrap.querySelector("input");
  if (!message) {
    p?.remove();
    wrap.classList.remove("has-error");
    input?.removeAttribute("aria-invalid");
    return;
  }
  if (!p) {
    p = document.createElement("p");
    p.className = "rf-error-inline";
    p.id = `${field}Error`;
    wrap.append(p);
  }
  p.textContent = message;
  wrap.classList.add("has-error");
  input?.setAttribute("aria-invalid", "true");
  if (input) {
    const ids = new Set((input.getAttribute("aria-describedby") || "").split(" ").filter(Boolean));
    ids.add(p.id);
    input.setAttribute("aria-describedby", [...ids].join(" "));
  }
}

function clearErrors() {
  form.querySelectorAll("[data-field]").forEach((w) => setFieldError(w.dataset.field, ""));
  formError.hidden = true;
  formError.textContent = "";
}

function showFormError(message) {
  formError.innerHTML = "";
  formError.append(message);
  formError.hidden = false;
}

// ---------- Bolagsverket-uppslag ----------

const registry = { checked: false, data: null, seq: 0, pending: null };

function setOrgStatus(text, kind = "") {
  orgStatus.textContent = text;
  orgStatus.dataset.kind = kind;
}

function startsWithAlwaysRegistered(input) {
  // Aktiebolag, ekonomisk förening och handelsbolag (5/7/9) finns alltid hos
  // Bolagsverket. Saknas de där är numret fel.
  return /^[579]/.test(tenDigits(input));
}

function updateCompanyField() {
  const found = registry.data?.found === true;
  const needsName = registry.checked && !found && !registryRejects();
  companyField.hidden = !needsName;
  companyLabel.textContent = looksLikeSoleTrader(org.value) ? "Firmanamn" : "Företagets namn";
}

function registryRejects() {
  return registry.checked && registry.data && registry.data.found !== true &&
    !looksLikeSoleTrader(org.value) && startsWithAlwaysRegistered(org.value);
}

async function lookupOrg() {
  const value = org.value.trim();
  const seq = ++registry.seq;
  registry.checked = false;
  registry.data = null;
  setFieldError("orgNumber", "");
  updateCompanyField();

  const digits = value.replace(/\D/g, "");
  if (digits.length < 10) { setOrgStatus(""); return; }
  if (!orgLooksValid(value)) {
    setOrgStatus("");
    setFieldError("orgNumber", "Numret stämmer inte. Kolla siffrorna.");
    return;
  }

  setOrgStatus("Vi letar hos Bolagsverket …", "busy");
  let body = null;
  try {
    const res = await fetch(
      `${portal.apiBaseUrl}/api/fleet/registry?orgNumber=${encodeURIComponent(value)}`,
      { headers: { Accept: "application/json" } },
    );
    if (res.ok) body = await res.json();
  } catch {
    body = null;
  }
  if (seq !== registry.seq) return; // kunden har hunnit skriva vidare

  registry.checked = true;
  registry.data = body && body.available ? body.registry : null;
  const r = registry.data;

  if (r?.found && r.blocksSignup) {
    setOrgStatus("");
    setFieldError("orgNumber", `Bolaget går inte att registrera. Status hos Bolagsverket: ${r.statusText || r.status}.`);
  } else if (r?.found) {
    const place = r.city ? `, ${r.city}` : "";
    setOrgStatus(`✓ ${r.name}${place}`, "ok");
  } else if (registryRejects()) {
    setOrgStatus("");
    setFieldError("orgNumber", "Bolagsverket hittar inte numret. Kolla siffrorna.");
  } else if (looksLikeSoleTrader(value)) {
    setOrgStatus("Enskild firma. Skriv firmanamnet nedan.", "info");
  } else if (!r) {
    setOrgStatus("Vi når inte Bolagsverket just nu. Skriv namnet nedan, så kollar vi senare.", "info");
  } else {
    setOrgStatus("Skriv företagets namn nedan.", "info");
  }
  updateCompanyField();
}

let lookupTimer = null;
org.addEventListener("input", () => {
  window.clearTimeout(lookupTimer);
  registry.seq++;
  registry.checked = false;
  lookupTimer = window.setTimeout(() => { registry.pending = lookupOrg(); }, 450);
});

// Ett fel försvinner så fort kunden rättar fältet.
form.querySelectorAll("[data-field] input").forEach((input) => {
  input.addEventListener("input", () => {
    const field = input.closest("[data-field]").dataset.field;
    if (field !== "orgNumber") setFieldError(field, "");
  });
});

// ---------- Visa lösenord ----------

$("showPass").addEventListener("click", (e) => {
  const input = $("password");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  e.currentTarget.textContent = show ? "Dölj" : "Visa";
  e.currentTarget.setAttribute("aria-pressed", String(show));
});

// ---------- Skicka ----------

function values() {
  return {
    orgNumber: org.value.trim(),
    companyName: companyField.hidden ? "" : companyName.value.trim(),
    contactName: $("contactName").value.trim(),
    contactPhone: $("phone").value.trim(),
    email: $("email").value.trim(),
    password: $("password").value,
  };
}

function validate(v) {
  const errors = {};
  if (!orgLooksValid(v.orgNumber)) errors.orgNumber = "Skriv organisationsnumret med 10 siffror.";
  else if (registry.data?.blocksSignup) errors.orgNumber = "Bolaget går inte att registrera.";
  else if (registryRejects()) errors.orgNumber = "Bolagsverket hittar inte numret. Kolla siffrorna.";
  if (!companyField.hidden && !v.companyName) {
    errors.companyName = looksLikeSoleTrader(v.orgNumber) ? "Skriv firmanamnet." : "Skriv företagets namn.";
  }
  if (!v.contactName) errors.contactName = "Skriv ditt namn.";
  if (!phoneLooksValid(v.contactPhone)) errors.phone = "Skriv ett svenskt mobilnummer, till exempel 070-123 45 67.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.email)) errors.email = "Skriv en riktig e-postadress.";
  if (v.password.length < 8) errors.password = "Lösenordet behöver minst 8 tecken.";
  return errors;
}

function busy(on, label = "Skapa konto") {
  submitBtn.disabled = on;
  submitBtn.textContent = on ? "Vänta …" : label;
  form.setAttribute("aria-busy", String(on));
}

async function postJson(path, body, token) {
  const res = await fetch(`${portal.apiBaseUrl}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* tomt svar */ }
  return { ok: res.ok && data.ok !== false, status: res.status, data };
}

function loginLink(text) {
  const frag = document.createDocumentFragment();
  frag.append(`${text} `);
  const a = document.createElement("a");
  a.href = "/portal";
  a.textContent = "Logga in här.";
  frag.append(a);
  return frag;
}

function show(id) {
  form.hidden = true;
  const panel = $(id);
  panel.hidden = false;
  panel.querySelector("h2")?.focus();
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearErrors();

  // Ett uppslag som pågår (eller väntar på att kunden slutat skriva) ska
  // vara klart innan vi bedömer numret.
  if (!registry.checked && orgLooksValid(org.value)) {
    window.clearTimeout(lookupTimer);
    await (registry.pending = lookupOrg());
  }

  const v = values();
  const errors = validate(v);
  const fields = Object.keys(errors);
  if (fields.length) {
    fields.forEach((f) => setFieldError(f, errors[f]));
    form.querySelector(`[data-field="${fields[0]}"] input`)?.focus();
    return;
  }

  const company = {
    orgNumber: v.orgNumber,
    companyName: v.companyName,
    contactName: v.contactName,
    contactPhone: v.contactPhone,
  };

  busy(true);
  try {
    // 2. Prövning före kontot.
    const check = await postJson("/api/fleet/register/check", { ...company, email: v.email });
    if (!check.ok) {
      const d = check.data;
      if (d.reason === "company_exists") {
        showFormError(loginLink(d.message || "Bolaget har redan ett konto."));
      } else if (d.field && d.message) {
        setFieldError(d.field === "phone" ? "phone" : d.field, d.message);
        form.querySelector(`[data-field="${d.field}"] input`)?.focus();
      } else {
        showFormError(d.message || "Något gick fel. Prova igen om en stund.");
      }
      return;
    }

    // 3. Kontot.
    const sb = supabase();
    const { data: auth, error } = await sb.auth.signUp({
      email: v.email,
      password: v.password,
      options: {
        data: { name: v.contactName, pending_company: company },
        emailRedirectTo: REDIRECT,
      },
    });
    if (error) {
      if (/already (been )?registered/i.test(error.message)) {
        showFormError(loginLink("Det finns redan ett konto med den e-posten."));
      } else if (/password/i.test(error.message)) {
        setFieldError("password", "Lösenordet är för svagt. Välj ett längre.");
      } else {
        showFormError("Kontot kunde inte skapas. Prova igen om en stund.");
      }
      return;
    }
    trackEvent("register_account");

    // Supabase säger inte alltid ifrån om e-posten redan finns: då kommer en
    // användare utan identiteter tillbaka och inget mejl skickas.
    if (auth?.user && Array.isArray(auth.user.identities) && auth.user.identities.length === 0) {
      showFormError(loginLink("Det finns redan ett konto med den e-posten."));
      return;
    }

    // 4a. E-posten måste bekräftas först: portalen gör klart resten.
    if (!auth?.session) {
      $("mailTo").textContent = v.email;
      show("regMail");
      return;
    }

    // 4b. Session direkt: bolaget registreras nu.
    const reg = await postJson("/api/fleet/register", company, auth.session.access_token);
    if (!reg.ok) {
      showFormError(reg.data.message || "Kontot är skapat, men bolaget blev inte klart. Logga in så gör vi klart det.");
      return;
    }
    await sb.auth.updateUser({ data: { pending_company: null } }).catch(() => {});
    trackEvent("register_company");
    if (reg.data.message) $("doneText").textContent = reg.data.message;
    show("regDone");
  } catch {
    showFormError("Vi når inte servern. Kolla internet och prova igen.");
  } finally {
    busy(false);
  }
});

// ---------- Skicka bekräftelsen igen ----------

$("resendBtn").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  const status = $("resendStatus");
  btn.disabled = true;
  try {
    const { error } = await supabase().auth.resend({
      type: "signup",
      email: $("email").value.trim(),
      options: { emailRedirectTo: REDIRECT },
    });
    status.textContent = error ? "Det gick inte. Vänta en minut och prova igen." : "Skickat. Kolla din e-post.";
  } catch {
    status.textContent = "Det gick inte. Kolla internet.";
  } finally {
    window.setTimeout(() => { btn.disabled = false; }, 30000);
  }
});
