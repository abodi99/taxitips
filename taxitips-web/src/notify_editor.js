/**
 * Notisinställningar för en förartelefon eller för företagets standard --
 * samma formulär i kundportalen och i adminwebben.
 *
 * Servern äger reglerna (core/notify_prefs.py): vilka lägen som finns, vad
 * de betyder, vilka län bilen får ha. Formuläret visar bara katalogerna den
 * skickar och skickar tillbaka det som valts. Ett län utanför bilens licens
 * erbjuds inte -- och servern sparar det inte ens om det skickas.
 *
 * Två sparknappar i samma formulär: "Använd läget" skickar bara läget,
 * "Spara detaljerna" skickar varje reglage. Vilken som trycktes står i
 * `event.submitter` (se `notifyBody`).
 */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const LEVEL_TEXT = {
  all: "Alla som är värda en notis",
  medium: "Medel och starka",
  high: "Bara starka",
};

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const hh = (h) => String(h).padStart(2, "0");

function presetRadios(name, current, catalog, disabled) {
  const rows = (catalog.presetCatalog ?? []).map(
    (p) => `<label class="notify-choice">
      <input type="radio" name="preset" value="${esc(p.id)}" ${p.id === current ? "checked" : ""} ${disabled}>
      <span><b>${esc(p.label)}</b><span class="muted">${esc(p.help)}</span></span>
    </label>`,
  );
  if (current === "custom") {
    rows.push(`<p class="muted notify-custom">Nu: egna val (se Detaljerat).</p>`);
  }
  return `<fieldset class="notify-presets"><legend>${esc(name)}</legend>${rows.join("")}</fieldset>`;
}

function categoryChecks(prefs, catalog, locked, disabled) {
  const cats = prefs.categories ?? {};
  return (catalog.categoryCatalog ?? [])
    .map((c) => {
      const isLocked = locked.includes(c.id);
      const on = !isLocked && cats[c.id] !== false;
      return `<label class="notify-check">
        <input type="checkbox" name="cat" value="${esc(c.id)}" ${on ? "checked" : ""}
          ${isLocked ? "disabled" : disabled}>
        ${esc(c.label)}${isLocked ? ' <span class="muted">– ingår inte i provet</span>' : ""}
      </label>`;
    })
    .join("");
}

function countyChecks(prefs, entitled, countyNames, disabled) {
  if (!entitled.length) return "";
  const chosen = new Set((prefs.counties ?? []).map(String));
  const all = chosen.size === 0;
  return `<fieldset class="notify-group"><legend>Län (bara bilens)</legend>
    ${entitled
      .map(
        (code) => `<label class="notify-check">
          <input type="checkbox" name="county" value="${esc(code)}" ${all || chosen.has(String(code)) ? "checked" : ""} ${disabled}>
          ${esc(countyNames[code] ?? `Län ${code}`)}</label>`,
      )
      .join("")}
    <p class="muted">Inget kryssat betyder alla bilens län.</p>
  </fieldset>`;
}

/**
 * HTML för formuläret. `target`: { kind: "device", deviceId } eller { kind: "default" }.
 * `entitled`: bilens län (bara för en telefon). `canManage`: annars bara läsning.
 */
export function notifyForm({ target, prefs = {}, preset = "recommended", catalog = {},
  entitled = [], countyNames = {}, canManage = false, locked = [] }) {
  const disabled = canManage ? "" : "disabled";
  const quiet = prefs.quietHours ?? null;
  const max = prefs.maxPerHour ?? "";
  const level = prefs.minLevel ?? "all";
  const weakMax = catalog.weakMaxPerHour ?? 3;
  const choices = catalog.maxPerHourChoices ?? [2, 4, 6];
  const isDefault = target.kind === "default";
  const dataAttrs = isDefault
    ? 'data-target="default"'
    : `data-target="device" data-device="${esc(target.deviceId)}"`;

  return `<form class="notify-form" ${dataAttrs}>
    ${presetRadios(isDefault ? "Läge för nya telefoner" : "Läge", preset, catalog, disabled)}
    ${canManage ? `<div class="btn-row"><button class="btn btn-primary btn-small" type="submit" value="preset">Använd läget</button></div>` : ""}
    <details class="notify-details">
      <summary>Detaljerat</summary>
      <label class="notify-check"><input type="checkbox" name="enabled" ${prefs.enabled === false ? "" : "checked"} ${disabled}>
        Notiser på</label>
      <fieldset class="notify-group"><legend>Kategorier</legend>${categoryChecks(prefs, catalog, locked, disabled)}</fieldset>
      <label for="lvl-${esc(target.deviceId ?? "default")}">Styrka</label>
      <select id="lvl-${esc(target.deviceId ?? "default")}" name="minLevel" ${disabled}>
        ${(catalog.levels ?? ["all", "medium", "high"])
          .map((l) => `<option value="${esc(l)}" ${l === level ? "selected" : ""}>${esc(LEVEL_TEXT[l] ?? l)}</option>`)
          .join("")}
      </select>
      <label class="notify-check"><input type="checkbox" name="weak" ${prefs.weak === true ? "checked" : ""} ${disabled}>
        Även svagare tips <span class="muted">– högst ${esc(weakMax)} i timmen, av som standard</span></label>
      <fieldset class="notify-group"><legend>Tysta timmar</legend>
        <div class="notify-hours">
          <select name="quietFrom" aria-label="Tyst från" ${disabled}>
            <option value="">Inga</option>
            ${HOURS.map((h) => `<option value="${h}" ${quiet && quiet.from === h ? "selected" : ""}>från ${hh(h)}:00</option>`).join("")}
          </select>
          <select name="quietTo" aria-label="Tyst till" ${disabled}>
            <option value="">–</option>
            ${HOURS.map((h) => `<option value="${h}" ${quiet && quiet.to === h ? "selected" : ""}>till ${hh(h)}:00</option>`).join("")}
          </select>
        </div>
      </fieldset>
      <label for="max-${esc(target.deviceId ?? "default")}">Högst antal notiser i timmen</label>
      <select id="max-${esc(target.deviceId ?? "default")}" name="maxPerHour" ${disabled}>
        <option value="">Inget tak</option>
        ${choices.map((n) => `<option value="${n}" ${Number(max) === n ? "selected" : ""}>${n}</option>`).join("")}
      </select>
      ${isDefault ? "" : countyChecks(prefs, entitled, countyNames, disabled)}
      ${isDefault && canManage ? `<label class="notify-check"><input type="checkbox" name="applyToPhones">
        Gäller också alla telefoner som redan finns <span class="muted">– län och paus ändras inte</span></label>` : ""}
      ${canManage ? `<div class="btn-row"><button class="btn btn-quiet btn-small" type="submit" value="details">Spara detaljerna</button></div>` : ""}
    </details>
  </form>`;
}

/** Det som ska skickas, ur formuläret och knappen som trycktes. */
export function notifyBody(form, submitter) {
  const data = new FormData(form);
  const applyToPhones = data.get("applyToPhones") === "on";
  if (submitter?.value === "preset") {
    const preset = String(data.get("preset") ?? "");
    return preset ? { preset, ...(applyToPhones ? { applyToPhones } : {}) } : null;
  }
  const categories = {};
  for (const box of form.querySelectorAll('input[name="cat"]:not(:disabled)')) {
    categories[box.value] = box.checked;
  }
  const from = String(data.get("quietFrom") ?? "");
  const to = String(data.get("quietTo") ?? "");
  const body = {
    enabled: data.get("enabled") === "on",
    categories,
    minLevel: String(data.get("minLevel") ?? "all"),
    weak: data.get("weak") === "on",
    quietHours: from !== "" && to !== "" && from !== to ? { from: Number(from), to: Number(to) } : null,
    maxPerHour: data.get("maxPerHour") ? Number(data.get("maxPerHour")) : null,
  };
  const counties = form.querySelectorAll('input[name="county"]');
  if (counties.length) {
    body.counties = [...counties].filter((c) => c.checked).map((c) => c.value);
  }
  if (applyToPhones) body.applyToPhones = true;
  return body;
}

/** Kortet med standarden och en rad per telefon. `notify` = svaret från servern. */
export function notifyCard(notify, { countyNames = {}, title = "Notiser för förarna" } = {}) {
  if (!notify) return "";
  const canManage = !!notify.canManage;
  const locked = notify.features?.locked ?? [];
  const phones = notify.phones ?? [];
  return `<div class="card notify-card">
    <h2>${esc(title)}</h2>
    <p class="muted">Rekommenderat ger notis bara för starka tips, där folk sannolikt står utan
      transport. Ändringar gäller direkt på förarens telefon. Föraren kan också ändra själv i appen.</p>
    <details class="notify-default">
      <summary><b>Standard för nya telefoner:</b> ${esc(notify.defaultSummary || "Rekommenderat")}</summary>
      ${notifyForm({
        target: { kind: "default" }, prefs: notify.default ?? {}, preset: notify.defaultPreset,
        catalog: notify, canManage, locked,
      })}
    </details>
    ${
      phones.length
        ? phones
            .map(
              (p) => `<details class="notify-phone">
            <summary><b>${esc(p.label || "Telefon")}</b>${p.plates?.length ? ` <span class="muted">${esc(p.plates.join(", "))}</span>` : ""}
              · ${esc(p.summary)}</summary>
            ${
              p.areaLocked
                ? '<p class="muted">Telefonen är inte kopplad till någon bil just nu, så den får inga notiser.</p>'
                : ""
            }
            ${notifyForm({
              target: { kind: "device", deviceId: p.deviceId }, prefs: p.prefs ?? {}, preset: p.preset,
              catalog: notify, entitled: p.entitledCounties ?? [], countyNames, canManage, locked,
            })}
          </details>`,
            )
            .join("")
        : '<p class="muted">Ingen telefon är kopplad än.</p>'
    }
  </div>`;
}
