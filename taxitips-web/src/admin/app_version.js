import { admin } from "./api.js";
import { dateTime } from "../portal/api.js";

/**
 * Appversionskortet på Status: vilken version förarna minst måste ha, och
 * vilken appen föreslår. Värdena bor i core/app_version.py och når appen via
 * /api/config -- ingen deploy, ingen Firebase-konsol.
 *
 * Kortet sköter sin egen sparning (bindAppVersionForm) och ritar bara om sig
 * självt: en statussida som laddar om alla kontroller för att en siffra
 * ändrats bränner tid och döljer ett fel i formuläret bakom omritningen.
 *
 * Behörigheten avgörs av servern (ADMIN_MANAGE för att ändra). `canManage`
 * här styr bara om formuläret visas alls.
 */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const PLATFORM = { android: "Android", ios: "iPhone" };

function current(entry) {
  if (!entry?.value) return '<span class="muted">Ingen gräns</span>';
  const from = entry.source === "env" ? ' <span class="muted">(miljövariabel)</span>' : "";
  return `<b>${esc(entry.value)}</b>${from}`;
}

function field(name, label, value, placeholder = "", type = "text") {
  return `<label>${esc(label)}<input name="${esc(name)}" type="${type}" value="${esc(value)}"
    placeholder="${esc(placeholder)}" autocomplete="off" spellcheck="false" /></label>`;
}

export function appVersionCard(data, canManage = false, error = "") {
  if (!data) {
    return `<div class="card" id="appVersionCard"><h2>Appversion</h2>
      <p class="muted">Kunde inte hämtas just nu.</p></div>`;
  }
  const p = data.platforms ?? {};
  const s = data.stored ?? {};
  const envOf = (platform, level) =>
    p[platform]?.[level]?.source === "env" ? p[platform][level].value : "";
  return `
    <div class="card" id="appVersionCard">
      <h2>Appversion</h2>
      <p class="muted">Under <b>minsta</b> version stängs appen tills föraren uppdaterat.
        Under <b>rekommenderad</b> visas en banderoll som går att stänga. Appen kontrollerar
        vid start och när den öppnas igen. Svarar inte servern släpps alla in.</p>
      <div class="table-scroll">
        <table>
          <thead><tr><th>Plattform</th><th>Minsta</th><th>Rekommenderad</th><th>Butik</th></tr></thead>
          <tbody>${Object.entries(PLATFORM).map(([key, label]) => `
            <tr>
              <td data-label="Plattform"><b>${label}</b></td>
              <td data-label="Minsta">${current(p[key]?.min)}</td>
              <td data-label="Rekommenderad">${current(p[key]?.recommended)}</td>
              <td data-label="Butik">${p[key]?.storeUrl?.value
                ? `<a href="${esc(p[key].storeUrl.value)}" target="_blank" rel="noopener">Öppna</a>`
                : '<span class="muted">Saknas</span>'}</td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
      ${data.message ? `<p>Meddelande till förarna: ${esc(data.message)}</p>` : ""}
      ${data.updatedAt ? `<p class="muted">Senast ändrad ${esc(dateTime(data.updatedAt))}</p>` : ""}
      ${canManage ? `
        <form id="appVersionForm" class="form-grid">
          ${field("android_min", "Android, minsta", s.android?.min, envOf("android", "min") || "t.ex. 1.0.2")}
          ${field("android_recommended", "Android, rekommenderad", s.android?.recommended, envOf("android", "recommended"))}
          ${field("ios_min", "iPhone, minsta", s.ios?.min, envOf("ios", "min"))}
          ${field("ios_recommended", "iPhone, rekommenderad", s.ios?.recommended, envOf("ios", "recommended"))}
          <label class="span-2">App Store-länk (krävs för en minsta iPhone-version)<input name="ios_store_url"
            type="url" value="${esc(s.ios?.storeUrl)}" placeholder="https://apps.apple.com/app/id…"
            autocomplete="off" /></label>
          <label class="span-2">Meddelande (valfritt, kort, visas i appen)<input name="message"
            maxlength="300" value="${esc(s.message)}" /></label>
          <p class="muted span-2">Formen är 1.2.3 eller 1.2.3+45 (byggnummer). Tomt fält = ingen gräns.
            Höj aldrig minsta version förrän den nya versionen syns i butiken.</p>
          ${error ? `<p class="error span-2" role="alert">${esc(error)}</p>` : ""}
          <div class="btn-row span-2"><button class="btn btn-primary" type="submit">Spara</button></div>
        </form>` : ""}
    </div>`;
}

function bodyOf(form) {
  const d = new FormData(form);
  const v = (name) => String(d.get(name) ?? "").trim();
  return {
    android: { min: v("android_min"), recommended: v("android_recommended") },
    ios: { min: v("ios_min"), recommended: v("ios_recommended"), storeUrl: v("ios_store_url") },
    message: v("message"),
  };
}

/**
 * Bekräftelsen säger vad som händer med förarna, inte bara vilka fält som
 * ändrats: en höjd minsta version stänger appen för alla som inte uppdaterat.
 */
function confirmText(before, body) {
  const lines = [];
  for (const [key, label] of Object.entries(PLATFORM)) {
    const was = before?.[key] ?? {};
    const now = body[key];
    if ((was.min ?? "") !== now.min) {
      lines.push(now.min
        ? `${label}: appen STÄNGS för alla med äldre version än ${now.min}.`
        : `${label}: ingen minsta version längre.`);
    }
    if ((was.recommended ?? "") !== now.recommended) {
      lines.push(now.recommended
        ? `${label}: banderoll för äldre version än ${now.recommended}.`
        : `${label}: ingen rekommenderad version längre.`);
    }
  }
  if ((before?.ios?.storeUrl ?? "") !== body.ios.storeUrl) lines.push("App Store-länken ändras.");
  if ((before?.message ?? "") !== body.message) lines.push("Meddelandet ändras.");
  if (!lines.length) return null;
  return `${lines.join("\n")}\n\nGäller direkt för alla förare. Spara?`;
}

let lastData = null;

/** Hämtar kortets data. Null om servern inte svarar -- Status ska ändå ritas. */
export async function loadAppVersion() {
  try {
    lastData = await admin.appVersion();
  } catch {
    lastData = null;
  }
  return lastData;
}

/** En gång, på vyns rot. Hanterar bara kortets eget formulär. */
export function bindAppVersionForm(root) {
  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (form.id !== "appVersionForm") return;
    event.preventDefault();
    const body = bodyOf(form);
    const text = confirmText(lastData?.stored, body);
    if (!text || !confirm(text)) return;
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    const card = document.getElementById("appVersionCard");
    try {
      lastData = await admin.setAppVersion(body);
      card?.insertAdjacentHTML("beforebegin", appVersionCard(lastData, true));
      card?.remove();
    } catch (error) {
      // Kortet ritas om med felet, och med det som skrevs -- inte det som var.
      const draft = { ...lastData, stored: { ...body } };
      card?.insertAdjacentHTML("beforebegin", appVersionCard(draft, true, error?.message ?? String(error)));
      card?.remove();
    }
  });
}
