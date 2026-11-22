/**
 * Adminwebbens egna frågerutor i stället för webbläsarens prompt()/confirm().
 *
 * Webbläsarens rutor är små, visar all text som en klump och ser olika ut i
 * varje telefon -- och "OK" säger inte vad som händer. Här får varje fråga en
 * rubrik, en kort förklaring, ett fält med etikett och en knapp som säger vad
 * den gör. Farliga åtgärder (ta bort, avsluta, spärra) får en röd knapp.
 *
 * Samma signatur som originalen, men asynkrona:
 *   await ask("Rubrik\n\nFörklaring\n\nSkäl:", "förval")  -> text | null
 *   await sure("Rubrik?\n\nFörklaring")                    -> true | false
 *   await choose("Rubrik", [["kort", "Kort"], ...])         -> värde | null
 * Meddelandet delas på tomma rader: första stycket blir rubrik, sista stycket
 * i ask() blir fältets etikett (om det slutar med ":"), resten förklaring.
 */

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[ch]);

const DANGER = /^(ta bort|radera|spärra|avsluta|avbryta|stäng av|stänga av|är du säker|säg upp)/i;

/** Knappen säger vad den gör: verbet ur en fråga ("Pausa tipsen …?" -> "Pausa"). */
function verbOf(title) {
  if (!/\?\s*$/.test(title)) return "";
  const m = title.match(/^(Ta bort|Säg upp|Stäng av|Bjud in|Häv|[A-ZÅÄÖ][a-zåäö]+)\b/);
  if (!m || /^(Vem|Vad|Hur|Varför|Vilken|Vilka|Är|Vill|Ska|Kan)$/.test(m[1])) return "";
  return m[1];
}

let dialog = null;

function ensureDialog() {
  if (dialog) return dialog;
  dialog = document.createElement("dialog");
  dialog.className = "ask";
  dialog.setAttribute("aria-labelledby", "askTitle");
  document.body.append(dialog);
  return dialog;
}

function split(message) {
  const parts = String(message ?? "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  return parts.length ? parts : [""];
}

/** Rubrik av första stycket: en lång första mening blir rubrik + resten text. */
function titleAndBody(parts) {
  let [title, ...body] = parts;
  if (title.length > 90) {
    const cut = title.search(/[.?!:]\s/);
    if (cut > 0 && cut < 90) {
      body = [title.slice(cut + 1).trim(), ...body];
      title = title.slice(0, cut + 1);
    }
  }
  return { title: title.replace(/:$/, ""), body };
}

function open(html, { onSubmit, focus }) {
  const d = ensureDialog();
  d.innerHTML = html;
  return new Promise((resolve) => {
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      d.close();
      resolve(value);
    };
    d.onclose = () => finish(null);
    d.onclick = (event) => {
      if (event.target === d) finish(null);
      const btn = event.target.closest("[data-ask]");
      if (!btn) return;
      if (btn.dataset.ask === "cancel") finish(null);
      else if (btn.dataset.ask === "choice") finish(btn.dataset.value);
    };
    const form = d.querySelector("form");
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      finish(onSubmit ? onSubmit(form) : true);
    });
    d.showModal();
    (focus ? d.querySelector(focus) : null)?.focus();
  });
}

/** Ersätter prompt(). Avbryt ger null, precis som originalet. */
export function ask(message, defaultValue = "", { ok = "", required: mustFill = false } = {}) {
  let required = mustFill;
  const parts = split(message);
  let label = "";
  if (parts.length > 1 && /:\s*$/.test(parts[parts.length - 1])) label = parts.pop().replace(/:\s*$/, "");
  const { title, body } = titleAndBody(parts);
  const long = /skäl|varför|anteckning|kommentar/i.test(`${label} ${title}`);
  // "Skriv varför …" / "(obligatoriskt …)": tomt svar går inte att skicka.
  required = required || /skriv varför|obligatorisk/i.test(message);
  const danger = DANGER.test(title);
  const okLabel = ok || verbOf(title) || (danger ? "Ja, fortsätt" : "Spara");
  const field = long
    ? `<textarea id="askInput" rows="3" ${required ? "required" : ""}>${esc(defaultValue)}</textarea>`
    : `<input id="askInput" value="${esc(defaultValue)}" autocomplete="off" ${required ? "required" : ""} />`;
  return open(`
    <form method="dialog" class="ask-form">
      <h2 id="askTitle">${esc(title)}</h2>
      ${body.map((p) => `<p class="ask-text">${esc(p)}</p>`).join("")}
      <label class="ask-field">${label ? `<span>${esc(label)}</span>` : ""}${field}</label>
      <div class="ask-buttons">
        <button type="button" class="btn btn-quiet" data-ask="cancel">Avbryt</button>
        <button type="submit" class="btn ${danger ? "btn-danger" : "btn-primary"}">${esc(okLabel)}</button>
      </div>
    </form>`, {
    focus: "#askInput",
    onSubmit: (form) => form.querySelector("#askInput").value,
  });
}

/** Ersätter confirm(). */
export async function sure(message, { ok = "", danger = null } = {}) {
  const { title, body } = titleAndBody(split(message));
  const red = danger ?? DANGER.test(title);
  const result = await open(`
    <form method="dialog" class="ask-form">
      <h2 id="askTitle">${esc(title)}</h2>
      ${body.map((p) => `<p class="ask-text">${esc(p)}</p>`).join("")}
      <div class="ask-buttons">
        <button type="button" class="btn btn-quiet" data-ask="cancel">Avbryt</button>
        <button type="submit" class="btn ${red ? "btn-danger" : "btn-primary"}">${esc(ok || verbOf(title) || (red ? "Ja, gör det" : "Ja"))}</button>
      </div>
    </form>`, { focus: 'button[type="submit"]' });
  return result === true;
}

/** Ett val bland flera knappar. Avbryt ger null. */
export function choose(message, options) {
  const { title, body } = titleAndBody(split(message));
  return open(`
    <div class="ask-form">
      <h2 id="askTitle">${esc(title)}</h2>
      ${body.map((p) => `<p class="ask-text">${esc(p)}</p>`).join("")}
      <div class="ask-choices">
        ${options.map(([value, label]) => `<button type="button" class="btn btn-quiet" data-ask="choice" data-value="${esc(value)}">${esc(label)}</button>`).join("")}
      </div>
      <div class="ask-buttons"><button type="button" class="btn btn-quiet" data-ask="cancel">Avbryt</button></div>
    </div>`, { focus: ".ask-choices button" });
}
