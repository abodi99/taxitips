/**
 * Webbstatistik: besök på taxitips.se och i appen ur Firebase/Google
 * Analytics 4 (core/web_analytics.py via /api/admin/web-analytics).
 *
 * Ren funktion från data till HTML, som dashboard.js, och samma diagram.
 * En källa som inte är inställd visar vad som saknas i stället för tomma
 * diagram.
 */

import { C1, C2, columns, dayLabel, esc, figure, legend, line, num, section, stat, table } from "./dashboard.js";

export const PERIODS = [[1, "I dag"], [7, "7 dagar"], [30, "30 dagar"], [90, "90 dagar"]];
const SOURCES = [["ga4", "Google Analytics"]];
const WEEKDAYS = ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag"];

// Händelserna sajten skickar (src/analytics.js trackEvent) med läsbara namn.
const EVENT_LABELS = {
  contact_submit: "Kontaktformulär skickat",
  early_access_subscribe: "Anmälan om tidig åtkomst",
  register_account: "Konto registrerat",
  register_company: "Bolag registrerat",
  page_view: "Sidvisning",
  session_start: "Besök startat",
  first_visit: "Första besöket",
  user_engagement: "Engagemang",
  scroll: "Scrollade till botten",
  click: "Utgående klick",
};

let last = null;

/** Källan som visas: den valda om den fungerar, annars den första som gör det. */
export function pickSource(data, wanted) {
  const ok = (id) => data?.sources?.[id]?.state === "ok";
  if (wanted && ok(wanted)) return wanted;
  return SOURCES.map(([id]) => id).find(ok) ?? wanted ?? "ga4";
}

function change(now, before) {
  if (now == null || !before) return "";
  const p = Math.round(((now - before) / before) * 100);
  const sign = p > 0 ? "+" : p < 0 ? "−" : "±";
  return `${sign}${Math.abs(p)} % mot förra perioden`;
}

function duration(sec) {
  if (sec == null) return "–";
  const m = Math.floor(sec / 60);
  return m ? `${m} min ${Math.round(sec % 60)} s` : `${Math.round(sec)} s`;
}

const pctOrDash = (v) => (v == null ? "–" : `${v.toLocaleString("sv-SE")} %`);

function hourRange(h) {
  return `kl ${String(h).padStart(2, "0")}–${String((h + 1) % 24).padStart(2, "0")}`;
}

/** Den mest besökta timmen och veckodagen, och den bästa dagen i perioden. */
function insights(s) {
  const heat = s.heat ?? [];
  let best = { v: 0, d: 0, h: 0 };
  heat.forEach((row, d) => row.forEach((v, h) => { if (v > best.v) best = { v, d, h }; }));
  const perDay = heat.map((row) => row.reduce((a, b) => a + b, 0));
  const dayMax = Math.max(...perDay, 0);
  const topDay = perDay.indexOf(dayMax);
  const hourTotals = Array.from({ length: 24 }, (_, h) => heat.reduce((a, row) => a + (row[h] ?? 0), 0));
  const topHour = hourTotals.indexOf(Math.max(...hourTotals, 0));
  const peak = [...(s.daily ?? [])].sort((a, b) => b.visitors - a.visitors)[0];
  const out = [];
  if (best.v) out.push(`Mest trafik: <b>${esc(WEEKDAYS[best.d].toLowerCase())}ar ${esc(hourRange(best.h))}</b>.`);
  if (dayMax) out.push(`Starkaste veckodagen är <b>${esc(WEEKDAYS[topDay].toLowerCase())}</b>, och timmen ${esc(hourRange(topHour))} över hela veckan.`);
  if (peak?.visitors && (s.daily?.length ?? 0) > 1) {
    out.push(`Bästa dagen i perioden: <b>${esc(dayLabel(peak.date))}</b> med ${num(peak.visitors)} besökare.`);
  }
  return out.length ? `<ul class="wa-insights">${out.map((t) => `<li>${t}</li>`).join("")}</ul>` : "";
}

/** Veckodag x timme. Mörkare = fler besökare; varje ruta har sitt tal i verktygstipset. */
function heatmap(heat) {
  const max = Math.max(...heat.flat(), 0);
  if (!max) return `<p class="muted dash-empty">Inga besök med tid i perioden.</p>`;
  const cell = (v, d, h) => {
    const share = v / max;
    const tip = esc(JSON.stringify({
      title: `${WEEKDAYS[d]} ${hourRange(h)}`, lines: [["var(--dv-1)", num(v), "besökare"]],
    }));
    return `<td class="wa-cell" style="--a:${(share * 100).toFixed(0)}%" tabindex="0"
      data-tip="${tip}" aria-label="${esc(`${WEEKDAYS[d]} ${hourRange(h)}: ${v} besökare`)}"></td>`;
  };
  return `<div class="wa-heat-wrap"><table class="wa-heat">
    <caption class="visually-hidden">Besökare per veckodag och timme</caption>
    <thead><tr><th></th>${Array.from({ length: 24 }, (_, h) =>
      `<th scope="col">${h % 3 === 0 ? String(h).padStart(2, "0") : ""}</th>`).join("")}</tr></thead>
    <tbody>${heat.map((row, d) => `<tr><th scope="row">${esc(WEEKDAYS[d].slice(0, 3))}</th>${
      row.map((v, h) => cell(v, d, h)).join("")}</tr>`).join("")}</tbody>
  </table>
  <p class="wa-heat-key muted"><span>Färre</span><i></i><span>Fler (högst ${num(max)})</span></p></div>`;
}

/** En topplista med andel som stapel. */
function top(title, items, { labels = null, empty = "Inget i perioden." } = {}) {
  const max = Math.max(...(items ?? []).map((i) => i.count), 0);
  const body = items?.length
    ? `<ol class="wa-top">${items.map((i) => `<li>
        <span class="wa-top-name" title="${esc(i.name)}">${esc(labels?.[i.name] ?? i.name)}</span>
        <b class="num">${num(i.count)}</b>
        <span class="wa-top-bar"><i style="width:${max ? (i.count / max) * 100 : 0}%"></i></span>
      </li>`).join("")}</ol>`
    : `<p class="muted dash-empty">${esc(empty)}</p>`;
  return `<div><h3>${esc(title)}</h3>${body}</div>`;
}

function setupHelp(src) {
  const msg = src?.message ? `<p class="${src.state === "error" ? "error" : "muted"}">${esc(src.message)}</p>` : "";
  const steps = `<ol class="wa-steps">
      <li>Firebase-konsolen → Projektinställningar → <b>Integrationer</b> → Google Analytics → Aktivera.
        Då börjar sajten (och appen) skicka data – webbkoden är redan på plats.</li>
      <li>Analytics → Admin → Egenskapsåtkomst: lägg till
        <code>firebase-adminsdk-fbsvc@taxitips-se.iam.gserviceaccount.com</code> som <b>Läsare</b>.</li>
      <li>Slå på <b>Google Analytics Data API</b> i Google Cloud-projektet taxitips-se.</li>
      <li>Sätt <code>GA4_PROPERTY_ID</code> (egenskapens nummer) på backenden i Coolify och driftsätt.</li>
    </ol>`;
  return `<div class="wa-setup">${msg}${steps}</div>`;
}

function chips(action, options, current, label) {
  return `<div class="chips" role="tablist" aria-label="${esc(label)}">${options.map(([id, text, note]) =>
    `<button class="chip" type="button" role="tab" data-action="${action}" data-value="${esc(id)}"
      aria-selected="${String(id) === String(current)}">${esc(text)}${note ? ` <span class="muted">${note}</span>` : ""}</button>`).join("")}</div>`;
}

function body(s, days) {
  const t = s.totals ?? {};
  const p = s.previous ?? {};
  const daily = s.daily ?? [];
  const cats = daily.map((d) => ({ label: days > 31 ? d.date.slice(8) : dayLabel(d.date).split(" ")[1], long: dayLabel(d.date) }));
  // Med 90 punkter läses inte varje etikett; varannan vecka räcker.
  if (days > 31) cats.forEach((c, i) => { if (i % 14) c.label = ""; });
  else if (days > 14) cats.forEach((c, i) => { if (i % 3) c.label = ""; });
  const series = [{ label: "Besök", color: C1 }, { label: "Sidvisningar", color: C2 }];

  const charts = daily.length > 1 ? `<div class="dash-charts">
      ${figure("Besökare per dag", "Svensk tid.",
        line({ title: "Besökare per dag", cats, values: daily.map((d) => d.visitors), color: C1, fmt: num, tipLabel: "besökare" }),
        "",
        table("Besökare per dag", ["Dag", "Besökare", "Besök", "Sidvisningar"],
          daily.map((d) => [dayLabel(d.date), num(d.visitors), num(d.sessions), num(d.pageviews)])))}
      ${figure("Besök och sidvisningar per dag", "",
        columns({ title: "Besök och sidvisningar per dag", cats, series,
          values: daily.map((d) => [d.sessions, d.pageviews]) }),
        legend(series), "")}
    </div>` : "";

  return `
    <div class="dash-stats dash-stats-lead">
      ${stat("Besökare", num(t.visitors), { hero: true, note: change(t.visitors, p.visitors) })}
      ${stat("Besök", num(t.sessions), { note: change(t.sessions, p.sessions) })}
      ${stat("Sidvisningar", num(t.pageviews), { note: change(t.pageviews, p.pageviews) })}
      ${stat("Avvisningsfrekvens", pctOrDash(t.bounceRate), { note: "lämnade efter en sida" })}
      ${stat("Snittid per besök", duration(t.avgSessionSec))}
      ${stat("Just nu", s.activeNow == null ? "–" : num(s.activeNow), { note: `besökare senaste ${esc(s.activeWindow ?? "")}` })}
    </div>
    ${insights(s)}
    ${charts}
    <div class="dv-fig">
      <h3>När kommer besökarna?</h3>
      <p class="muted">Besökare per veckodag och timme, hela perioden.</p>
      ${heatmap(s.heat ?? [])}
    </div>
    <div class="dash-cols dash-cols-2">
      ${top("Mest besökta sidor", s.pages)}
      ${top("Varifrån de kommer", s.referrers, { empty: "Bara direkttrafik." })}
      ${top("Länder", s.countries)}
      ${top("Enheter", s.devices, { labels: { mobile: "Mobil", desktop: "Dator", tablet: "Surfplatta", laptop: "Laptop" } })}
      ${s.platforms?.length ? top("Plattform", s.platforms, { labels: { web: "Webb", iOS: "iPhone-appen", Android: "Android-appen" } }) : ""}
      ${top("Händelser och konverteringar", s.events, { labels: EVENT_LABELS, empty: "Inga händelser ännu." })}
    </div>`;
}

export function webAnalytics(data, { source, days, scope }) {
  last = data;
  const shown = pickSource(data, source);
  const src = data.sources?.[shown];
  const stamp = new Intl.DateTimeFormat("sv-SE", { timeStyle: "short" }).format(new Date(data.generatedAt));
  const lead = scope === "all"
    ? "Webben och appen tillsammans, ur Firebase/Google Analytics."
    : "Bara taxitips.se, ur Firebase/Google Analytics. Räknas för besökare som godkänt kakor.";
  return `
    <div class="page-head">
      <div><h1>Webbstatistik</h1>
        <p class="muted">Hur många som besöker taxitips.se, när, varifrån och vad de gör.</p></div>
      <div class="btn-row">
        ${src?.state === "ok" ? `<button class="btn btn-quiet" type="button" data-action="wa-csv">Ladda ner CSV</button>` : ""}
        ${src?.dashboardUrl ? `<a class="btn btn-quiet" href="${esc(src.dashboardUrl)}" target="_blank" rel="noopener">Öppna Analytics ↗</a>` : ""}
        <button class="btn btn-quiet" type="button" data-action="wa-refresh">Uppdatera</button>
      </div>
    </div>
    <div class="wa-controls">
      ${chips("wa-days", PERIODS, data.days, "Period")}
      ${src?.state === "ok"
        ? chips("wa-scope", [["web", "Bara webben"], ["all", "Webb + app"]], scope, "Omfång") : ""}
      <span class="muted dash-stamp">Hämtat ${esc(stamp)}</span>
    </div>
    <div class="dash">
      ${section("webb", SOURCES.find(([id]) => id === shown)[1], src?.state === "ok" ? lead : "Källan är inte igång än.",
        () => (src?.state === "ok" ? body(src, data.days) : setupHelp(src)))}
    </div>`;
}

/** Perioden per dag som CSV (semikolon, för svensk Excel). */
export function downloadCsv(source) {
  const s = last?.sources?.[pickSource(last, source)];
  if (!s?.daily) return;
  const rows = [["Datum", "Besökare", "Besök", "Sidvisningar"], ...s.daily.map((d) => [d.date, d.visitors, d.sessions, d.pageviews])];
  const blob = new Blob([`﻿${rows.map((r) => r.join(";")).join("\n")}`], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `taxitips-webbstatistik-${pickSource(last, source)}-${last.days}d.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
