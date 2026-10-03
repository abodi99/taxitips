/**
 * Dashboarden: hela tjänsten på en sida, ett avsnitt per perspektiv
 * (fleet/admin_dashboard.py).
 *
 * Ren funktion från data till HTML, som views.js. Ingenting räknas om här:
 * beloppen kommer från prismotorn och risklägena från Uppföljningen. Varje
 * siffra som har en lista bakom sig är en knapp till den listan
 * (`data-action="goto"` med `data-filter`, eller `open-company`).
 *
 * Diagrammen är inline SVG utan bibliotek. Färgerna är validerade med
 * dataviz-skillens validator mot vit yta: serie 1 #3a5a9a (midnattsblå i
 * markbandet), serie 2 #e08f00 (guld-djup, under 3:1 -- därför direktetikett
 * och tabellvy), trattens tre steg som en ordinal ramp i samma blå, och
 * skickat/misslyckat i status-färgerna (--ok/--danger, staplade med mellanrum
 * och förklaring eftersom rött/grönt ligger nära under deuteranopi).
 * Varje diagram har en tabell bredvid sig; verktygstipset är en genväg, aldrig
 * enda vägen till en siffra.
 */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const num = (n) => (n ?? 0).toLocaleString("sv-SE");
const pct = (p) => (p == null ? "–" : `${p.toLocaleString("sv-SE")} %`);

/** Hela kronor, för nyckeltal och axlar. Fakturorna visar ören; det gör inte en översikt. */
function kr(ore) {
  return new Intl.NumberFormat("sv-SE", {
    style: "currency", currency: "SEK", maximumFractionDigits: 0,
  }).format((ore ?? 0) / 100);
}

function shortDate(iso) {
  if (!iso) return "–";
  return new Intl.DateTimeFormat("sv-SE", { day: "numeric", month: "short" }).format(new Date(iso));
}

/** "45 min", "3 h", "2 dygn" -- räknat mot svarets egen tid, så att funktionen förblir ren. */
function age(iso, now) {
  if (!iso) return "–";
  const minutes = Math.max(0, Math.round((new Date(now) - new Date(iso)) / 60000));
  if (minutes < 90) return `${minutes} min`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h`;
  return `${Math.round(minutes / 1440)} dygn`;
}

/** ISO-veckonummer för en måndag (YYYY-MM-DD). */
function isoWeek(day) {
  const d = new Date(`${day}T12:00:00Z`);
  const thursday = new Date(d);
  thursday.setUTCDate(d.getUTCDate() + 3 - ((d.getUTCDay() + 6) % 7));
  const jan4 = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((thursday - jan4) / 86400000 - 3 + ((jan4.getUTCDay() + 6) % 7)) / 7);
}

function dayLabel(day) {
  const d = new Date(`${day}T12:00:00Z`);
  const wd = new Intl.DateTimeFormat("sv-SE", { weekday: "short", timeZone: "UTC" }).format(d);
  return `${wd.replace(".", "")} ${d.getUTCDate()}/${d.getUTCMonth() + 1}`;
}

/* --- Byggklossar --------------------------------------------------------- */

/**
 * Ett nyckeltal. Med `go` blir det en knapp till listan bakom siffran:
 * `{ view, filter }` eller `{ company, tab }`.
 */
function stat(label, value, { note = "", go = null, alert = false, hero = false } = {}) {
  const cls = `dash-stat${alert ? " is-alert" : ""}${hero ? " is-hero" : ""}`;
  const body = `<span class="dash-stat-label">${esc(label)}</span>
    <b class="dash-stat-value">${value}</b>
    ${note ? `<span class="dash-stat-note">${note}</span>` : ""}`;
  if (!go) return `<div class="${cls}">${body}</div>`;
  return `<button type="button" class="${cls} is-link" ${goAttrs(go)}>${body}
    <span class="dash-go" aria-hidden="true">→</span></button>`;
}

function goAttrs(go) {
  if (go.company) {
    return `data-action="open-company" data-id="${esc(go.company)}" data-tab="${esc(go.tab ?? "")}"`;
  }
  if (go.user) return `data-action="open-account" data-user="${esc(go.user)}"`;
  return `data-action="goto" data-view="${esc(go.view)}"${go.filter ? ` data-filter="${esc(go.filter)}"` : ""}`;
}

/** En lista med rader som öppnar kunden eller kontot. */
function rows(items, empty) {
  if (!items.length) return `<p class="muted dash-empty">${esc(empty)}</p>`;
  return `<ul class="dash-list">${items.map((r) => `
    <li><button type="button" class="dash-row" ${goAttrs(r.go)}>
      <b>${esc(r.title)}</b><span class="muted">${esc(r.why)}</span>
      <span class="dash-go" aria-hidden="true">→</span>
    </button></li>`).join("")}</ul>`;
}

function section(id, title, lead, body, data) {
  const inner = data?.unavailable
    ? `<p class="error">${esc(data.message || "Avsnittet gick inte att räkna.")}</p>`
    : body();
  return `
    <section class="card dash-sec" id="dash-${id}" aria-labelledby="dash-${id}-h">
      <div class="dash-sec-head">
        <h2 id="dash-${id}-h">${esc(title)}</h2>
        <p class="muted">${esc(lead)}</p>
      </div>
      ${inner}
    </section>`;
}

function table(caption, head, body) {
  return `<details class="dv-table"><summary>Visa som tabell</summary>
    <table><caption class="visually-hidden">${esc(caption)}</caption>
      <thead><tr>${head.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead>
      <tbody>${body.map((r) => `<tr>${r.map((c, i) => (i
        ? `<td class="num" data-label="${esc(head[i])}">${esc(c)}</td>`
        : `<th scope="row">${esc(c)}</th>`)).join("")}</tr>`).join("")}</tbody>
    </table></details>`;
}

/* --- Diagram ------------------------------------------------------------- */

const W = 480;
const PAD = { top: 16, right: 10, bottom: 26, left: 44 };
const PLOT_H = 140;
const H = PAD.top + PLOT_H + PAD.bottom;

/** Jämna steg på y-axeln: 1, 2 eller 5 gånger en tiopotens. */
function scale(max, ticks = 4) {
  if (!max || max <= 0) return { top: ticks, step: 1 };
  const raw = max / ticks;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw);
  return { top: Math.ceil(max / step) * step, step };
}

const yOf = (v, top) => PAD.top + PLOT_H - (v / top) * PLOT_H;

function grid(top, step, fmt) {
  let out = "";
  for (let v = 0; v <= top + 1e-9; v += step) {
    const y = yOf(v, top).toFixed(1);
    out += `<line class="${v === 0 ? "dv-base" : "dv-grid"}" x1="${PAD.left}" x2="${W - PAD.right}" y1="${y}" y2="${y}"/>
      <text class="dv-tick" x="${PAD.left - 6}" y="${y}" text-anchor="end" dy="0.32em">${esc(fmt(v))}</text>`;
  }
  return out;
}

/** Stapel som växer från baslinjen, rundad 4 px i dataänden och rak mot baslinjen. */
function bar(x, y, w, h, cls, style = "") {
  if (h <= 0) return "";
  const r = Math.min(4, h, w / 2);
  const y0 = y + h;
  return `<path class="${cls}"${style} d="M${x},${y0}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y0}Z"/>`;
}

function tipAttr(title, lines) {
  const label = `${title}: ${lines.map(([, v, l]) => `${l} ${v}`).join(", ")}`;
  return `tabindex="0" role="img" aria-label="${esc(label)}" data-tip="${esc(JSON.stringify({ title, lines }))}"`;
}

function legend(series, kind = "rect") {
  return `<ul class="dv-legend">${series.map((s) =>
    `<li><i class="dv-key dv-key-${kind}" style="--c:${s.color}"></i>${esc(s.label)}</li>`).join("")}</ul>`;
}

/**
 * Staplar per kategori, grupperade eller staplade. `values[i][j]` är serie j
 * i kategori i. Senaste kategorin får sina värden utskrivna -- inte alla:
 * ett tal på varje stapel läses inte.
 */
function columns({ title, cats, series, values, stacked = false, fmt = num }) {
  const n = cats.length;
  const totals = values.map((v) => (stacked ? v.reduce((a, b) => a + b, 0) : Math.max(...v)));
  const { top, step } = scale(Math.max(...totals, 0));
  const band = (W - PAD.left - PAD.right) / n;
  const k = stacked ? 1 : series.length;
  const bw = Math.min(24, (band - 10 - 2 * (k - 1)) / k);
  const groupW = bw * k + 2 * (k - 1);

  let marks = "";
  cats.forEach((cat, i) => {
    const x0 = PAD.left + band * i + (band - groupW) / 2;
    let inner = "";
    let base = 0;
    series.forEach((s, j) => {
      const v = values[i][j] ?? 0;
      const style = ` style="fill:${s.color}"`;
      if (stacked) {
        const yTop = yOf(base + v, top);
        // 2 px yta mellan segmenten: avståndet, inte en kantlinje, skiljer dem åt.
        const yBottom = yOf(base, top) - (base > 0 ? 2 : 0);
        const last = j === series.length - 1 || values[i].slice(j + 1).every((x) => !x);
        inner += last
          ? bar(x0, yTop, bw, yBottom - yTop, "dv-bar", style)
          : (yBottom - yTop > 0 ? `<rect class="dv-bar"${style} x="${x0}" y="${yTop}" width="${bw}" height="${yBottom - yTop}"/>` : "");
        base += v;
      } else {
        const x = x0 + j * (bw + 2);
        const y = yOf(v, top);
        inner += bar(x, y, bw, PAD.top + PLOT_H - y, "dv-bar", style);
        if (i === n - 1) {
          inner += `<text class="dv-label" x="${x + bw / 2}" y="${y - 5}" text-anchor="middle">${esc(fmt(v))}</text>`;
        }
      }
    });
    if (stacked && i === n - 1) {
      inner += `<text class="dv-label" x="${x0 + bw / 2}" y="${yOf(base, top) - 5}" text-anchor="middle">${esc(fmt(base))}</text>`;
    }
    const lines = series.map((s, j) => [s.color, fmt(values[i][j] ?? 0), s.label]);
    marks += `<g class="dv-hit" ${tipAttr(cat.long ?? cat.label, lines)}>
      <rect class="dv-hit-area" x="${PAD.left + band * i}" y="${PAD.top}" width="${band}" height="${PLOT_H}"/>
      ${inner}
      <text class="dv-tick" x="${PAD.left + band * i + band / 2}" y="${H - 8}" text-anchor="middle">${esc(cat.label)}</text>
    </g>`;
  });

  return `<svg class="dv" viewBox="0 0 ${W} ${H}" role="group" aria-label="${esc(title)}">
    ${grid(top, step, fmt)}${marks}</svg>`;
}

/** En linje över tid, med en tunn yta under och värdet utskrivet vid sista punkten. */
function line({ title, cats, values, color, fmt, valueFmt = fmt, tipLabel }) {
  const n = cats.length;
  const { top, step } = scale(Math.max(...values, 0));
  const band = (W - PAD.left - PAD.right) / n;
  const xs = cats.map((_, i) => PAD.left + band * i + band / 2);
  const ys = values.map((v) => yOf(v, top));
  const path = xs.map((x, i) => `${i ? "L" : "M"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join("");
  const area = `${path}L${xs[n - 1].toFixed(1)},${PAD.top + PLOT_H}L${xs[0].toFixed(1)},${PAD.top + PLOT_H}Z`;
  const hits = cats.map((cat, i) => `<g class="dv-hit" ${tipAttr(cat.long ?? cat.label, [[color, valueFmt(values[i]), tipLabel]])}>
      <rect class="dv-hit-area" x="${PAD.left + band * i}" y="${PAD.top}" width="${band}" height="${PLOT_H}"/>
      <line class="dv-cross" x1="${xs[i]}" x2="${xs[i]}" y1="${PAD.top}" y2="${PAD.top + PLOT_H}"/>
      <circle class="dv-dot dv-dot-hover" cx="${xs[i]}" cy="${ys[i]}" r="4" style="fill:${color}"/>
      <text class="dv-tick" x="${xs[i]}" y="${H - 8}" text-anchor="middle">${esc(cat.label)}</text>
    </g>`).join("");
  const last = n - 1;
  return `<svg class="dv" viewBox="0 0 ${W} ${H}" role="group" aria-label="${esc(title)}">
    ${grid(top, step, fmt)}
    <path class="dv-area" d="${area}" style="fill:${color}"/>
    <path class="dv-line" d="${path}" style="stroke:${color}"/>
    ${hits}
    <circle class="dv-dot" cx="${xs[last]}" cy="${ys[last]}" r="4" style="fill:${color}"/>
    <text class="dv-label" x="${xs[last]}" y="${ys[last] - 10}" text-anchor="end">${esc(valueFmt(values[last]))}</text>
  </svg>`;
}

function figure(title, note, chart, legendHtml, tableHtml) {
  return `<figure class="dv-fig">
    <figcaption><b>${esc(title)}</b>${note ? `<span class="muted">${note}</span>` : ""}</figcaption>
    ${legendHtml}${chart}${tableHtml}
  </figure>`;
}

const C1 = "var(--dv-1)";
const C2 = "var(--dv-2)";

/* --- Avsnitten ----------------------------------------------------------- */

function ledning(d) {
  const weeks = d.weeks ?? [];
  const cats = weeks.map((w) => ({
    label: `v${isoWeek(w.weekStart)}`,
    long: `Vecka ${isoWeek(w.weekStart)} (från ${shortDate(w.weekStart)})`,
  }));
  const series = [{ label: "Nya bolag", color: C1 }, { label: "Nya betalande", color: C2 }];
  const lastMrr = weeks.at(-1)?.mrrOre ?? 0;
  const mrrNote = lastMrr === d.mrrOre
    ? "Månadsbeloppet ur bolagens senaste betalda beställning, vid veckans slut."
    : `Månadsbeloppet ur bolagens senaste betalda beställning, vid veckans slut. Skiljer sig från
       dagens ${esc(kr(d.mrrOre))} ovan när ett abonnemang lagts upp utan beställning.`;
  return `
    <div class="dash-stats dash-stats-lead">
      ${stat("MRR exkl. moms", esc(kr(d.mrrOre)), { hero: true, note: "Räknat live av prismotorn, som på Hem" })}
      ${stat("Betalande bolag", num(d.payingCompanies), {
        go: { view: "kunder", filter: "betalande" },
        note: d.pastDue ? `varav ${num(d.pastDue)} obetald` : "",
      })}
      ${stat("Kunder", num(d.companies), { go: { view: "kunder" }, note: "utan arkiverade" })}
      ${stat("Bilar", num(d.carsPaid), { note: `betalda · ${num(d.carsTrial)} provbilar` })}
      ${stat("Aktiva förare", num(d.activeDrivers), { note: `körde senaste ${num(d.activeDriverDays)} dygnen` })}
      ${stat("I tjänst nu", num(d.driversOnDuty), { note: "förarpass som pågår just nu" })}
      ${stat("Kopplade telefoner", num(d.phonesApproved), { note: "godkända för en bil" })}
    </div>
    <div class="dash-charts">
      ${figure("Nya bolag och nya betalande per vecka", "Ny betalande = veckan bolagets första betalning kom in.",
        columns({ title: "Nya bolag och nya betalande per vecka", cats, series,
          values: weeks.map((w) => [w.newCompanies, w.newPaying]) }),
        legend(series),
        table("Nya bolag och nya betalande per vecka", ["Vecka", "Nya bolag", "Nya betalande"],
          weeks.map((w, i) => [cats[i].long, num(w.newCompanies), num(w.newPaying)])))}
      ${figure("MRR per vecka, kr exkl. moms", mrrNote,
        line({ title: "MRR per vecka", cats, values: weeks.map((w) => w.mrrOre), color: C1,
          fmt: (v) => kr(v).replace(/\s?kr$/, ""), valueFmt: kr, tipLabel: "MRR" }),
        "",
        table("MRR per vecka", ["Vecka", "MRR exkl. moms"],
          weeks.map((w, i) => [cats[i].long, kr(w.mrrOre)])))}
    </div>`;
}

function funnel(f) {
  const steps = [
    ["Registrerade", f.registered, "var(--dv-o1)", ""],
    ["Startade prov", f.trialStarted, "var(--dv-o2)",
      f.boughtWithoutTrial ? `inkl. ${num(f.boughtWithoutTrial)} som köpte utan prov` : ""],
    ["Blev betalande", f.paying, "var(--dv-o3)", ""],
  ];
  const max = Math.max(f.registered, 1);
  const conv = [
    `${pct(f.rates?.trialOfRegistered)} gick vidare`,
    `${pct(f.rates?.payingOfTrial)} av dem betalar`,
  ];
  return `<figure class="dv-fig dash-funnel">
    <figcaption><b>Tratten, bolag registrerade senaste ${num(f.windowDays)} dagarna</b>
      <span class="muted">${pct(f.rates?.payingOfRegistered)} av alla registrerade blev betalande${
        f.archived ? ` · inkl. ${num(f.archived)} arkiverade` : ""}</span></figcaption>
    <ol class="funnel">${steps.map(([label, n, color, note], i) => `
      <li>
        <span class="funnel-label">${esc(label)}${note ? `<small class="muted">${esc(note)}</small>` : ""}</span>
        <span class="funnel-track"><i style="width:${Math.max((n / max) * 100, n ? 1.5 : 0)}%;background:${color}"></i></span>
        <b class="funnel-n">${num(n)}</b>
        ${i < conv.length ? `<span class="funnel-conv muted">↓ ${esc(conv[i])}</span>` : ""}
      </li>`).join("")}
    </ol>
  </figure>`;
}

function salj(d) {
  const ending = d.trialsEnding ?? { rows: [] };
  const missing = d.missingSetup ?? { rows: [] };
  const crm = d.crmOverdue ?? { perAssignee: [] };
  return `
    ${funnel(d.funnel ?? {})}
    <div class="dash-cols">
      <div>
        ${stat(`Prov som slutar inom ${num(ending.days)} dagar`, num(ending.count), {
          go: { view: "uppfoljning", filter: "prov" } })}
        ${rows(ending.rows.map((r) => ({
          title: r.name, why: `slutar ${shortDate(r.endsAt)} (${r.daysLeft.toLocaleString("sv-SE")} d kvar)`,
          go: { company: r.companyId, tab: "betalning" },
        })), "Inget prov slutar den närmaste veckan.")}
      </div>
      <div>
        ${stat("Saknar bil eller förare", num(missing.noCar + missing.noDriver), {
          note: `${num(missing.noCar)} utan bil · ${num(missing.noDriver)} utan förare` })}
        ${rows(missing.rows.map((r) => ({
          title: r.name,
          why: `${r.missing === "car" ? "ingen bil" : "bil men ingen förare"} · registrerad ${shortDate(r.createdAt)}`,
          go: { company: r.companyId, tab: r.missing === "car" ? "bilar" : "forare" },
        })), "Alla nya bolag har bil och förare.")}
      </div>
      <div>
        ${stat("Försenade CRM-uppgifter", num(crm.count), {
          go: { view: "pipeline", filter: "tasks" }, alert: crm.count > 0,
          note: crm.oldestDue ? `äldsta skulle göras ${shortDate(crm.oldestDue)}` : "" })}
        ${crm.perAssignee.length ? `<ul class="dash-mini">${crm.perAssignee.map((p) =>
          `<li><span>${esc(p.assignee || "Ingen ansvarig")}</span><b>${num(p.count)}</b></li>`).join("")}</ul>`
          : '<p class="muted dash-empty">Inget försenat.</p>'}
      </div>
    </div>`;
}

function supportSec(d, now) {
  const e = d.errors ?? { h24: {}, d7: {} };
  const swap = d.swapLimit ?? {};
  return `
    <div class="dash-stats">
      ${stat("Väntar på svar", num(d.threadsWaiting), {
        go: { view: "support" }, alert: d.threadsWaiting > 0,
        note: d.oldestWaitingSince ? `äldsta har väntat ${age(d.oldestWaitingSince, now)}` : `${num(d.threadsOpen)} öppna trådar` })}
      ${stat("Öppna tipprapporter", num(d.tipReportsOpen), {
        go: { view: "tipprapporter" }, alert: d.tipReportsOpen > 0,
        note: d.oldestTipReportAt ? `äldsta ${age(d.oldestTipReportAt, now)}` : "" })}
      ${stat("Appfel senaste 24 h", num((e.h24.app ?? 0) + (e.h24.server ?? 0)), {
        go: { view: "aktivitet" }, note: `${num(e.h24.app)} i appen · ${num(e.h24.server)} på servern` })}
      ${stat("Appfel senaste 7 dygn", num((e.d7.app ?? 0) + (e.d7.server ?? 0)), {
        go: { view: "aktivitet" }, note: `varav ${num(e.d7.crashes)} ${e.d7.crashes === 1 ? "krasch" : "krascher"}` })}
    </div>
    <div class="dash-cols">
      <div>
        <h3>Hur länge frågorna väntat</h3>
        <ul class="dash-mini">${(d.waitBuckets ?? []).map((b) =>
          `<li><span>${esc(b.label)}</span><b>${num(b.count)}</b></li>`).join("")}</ul>
      </div>
      <div>
        ${swap.unavailable ? `<p class="error">Telefonbytena: ${esc(swap.message)}</p>` : `
        ${stat(`Slagit i telefonbytesgränsen (${swap.month ?? ""})`, num(swap.count), {
          note: `${num(swap.limit)} byten per månad, sedan behövs support` })}
        ${rows((swap.rows ?? []).map((r) => ({
          title: r.email || "Okänt konto", why: `${num(r.used)} av ${num(r.allowed)} byten`,
          go: { user: r.userId },
        })), "Ingen förare har slagit i gränsen den här månaden.")}`}
      </div>
    </div>`;
}

function uppfoljning(d) {
  const inactive = d.inactiveTrials ?? { rows: [] };
  return `
    <div class="dash-stats">
      ${stat("Obetald betalning", num(d.pastDue), { go: { view: "uppfoljning", filter: "betala" }, alert: d.pastDue > 0 })}
      ${stat("Obetalda beställningar", num(d.unpaidOrders?.companies), {
        go: { view: "uppfoljning", filter: "betala" }, note: `${esc(kr(d.unpaidOrders?.ore))} öppet` })}
      ${stat("Uppsagda till periodens slut", num(d.pendingCancel), { go: { view: "uppfoljning", filter: "risk" } })}
      ${stat(`Avslutade senaste ${num(d.churnWindowDays)} dagarna`, num(d.churned), {
        go: { view: "uppfoljning", filter: "churn" } })}
      ${stat("Prov utan aktivitet", num(inactive.count), {
        go: { view: "uppfoljning", filter: "prov" },
        note: `ingen förare har kört på ${num(inactive.days)} dygn` })}
    </div>
    <div class="dash-cols dash-cols-2">
      <div>
        <h3>Churnrisk</h3>
        ${rows((d.atRisk ?? []).map((r) => ({
          title: r.name,
          why: r.segment === "past_due" ? "betalningen har inte kommit in"
            : `har sagt upp${r.accessUntil ? ` – åtkomst till ${shortDate(r.accessUntil)}` : ""}`,
          go: { company: r.companyId, tab: "betalning" },
        })), "Ingen kund med obetald betalning eller uppsägning.")}
      </div>
      <div>
        <h3>Prov utan aktivitet</h3>
        ${rows(inactive.rows.map((r) => ({
          title: r.name,
          why: r.status === "pending" ? "väntar på första telefonen" : `startade ${shortDate(r.startedAt)}, ingen har kört sedan`,
          go: { company: r.companyId, tab: "forare" },
        })), "Alla pågående prov har förare som kör.")}
      </div>
    </div>`;
}

const OUTBOX_LABEL = {
  trial_started: "Provet startat",
  trial_ending: "Provet slutar snart",
  trial_ended: "Provet slut",
  order_confirmed: "Beställning bekräftad",
  payment_failed: "Betalningen misslyckades",
  cancellation_confirmed: "Uppsägning bekräftad",
  driver_invite: "Förarinbjudan",
  driver_login_code: "Förarens inloggningskod",
  member_invite: "Inbjudan till portalen",
  device_blocked: "Telefon spärrad",
};

const LEVEL_TEXT = { ok: "fungerar", warn: "varning", down: "nere", off: "av" };

function drift(d) {
  const counts = d.sourceCounts ?? {};
  const out = d.outbox ?? { categories: [] };
  const push = d.push ?? { perDay: [], byStatus: {} };
  const pushSeries = [
    { label: "Skickade", color: "var(--ok)" },
    { label: "Misslyckade", color: "var(--danger)" },
  ];
  const cats = push.perDay.map((p) => ({ label: dayLabel(p.date), long: dayLabel(p.date) }));
  const failed = push.byStatus?.failed ?? 0;
  return `
    <div class="dash-cols dash-cols-2">
      <div>
        <div class="dash-subhead"><h3>Datakällor</h3>
          <button type="button" class="btn btn-quiet btn-small" data-action="goto" data-view="status">Status →</button></div>
        <p class="muted dash-counts">${["down", "warn", "ok", "off"].filter((k) => counts[k]).map((k) =>
          `${num(counts[k])} ${LEVEL_TEXT[k]}`).join(" · ") || "Inga källor"}</p>
        <ul class="dash-sources">${(d.sources ?? []).map((s) => `
          <li><span class="st-dot st-${esc(s.status)}" aria-hidden="true"></span>
            <span><b>${esc(s.label)}</b> <span class="visually-hidden">(${esc(LEVEL_TEXT[s.status] ?? s.status)})</span>
            <span class="muted">${esc(s.summary)}</span></span></li>`).join("")}
        </ul>
      </div>
      <div>
        ${figure(`Notiser per dag, senaste ${num(push.days)} dygnen`,
          `${num(push.byStatus?.suppressed)} undertryckta (mottagaren saknade åtkomst) · ${num(push.byStatus?.expired)} utgångna`,
          columns({ title: "Notiser per dag", cats, series: pushSeries, stacked: true,
            values: push.perDay.map((p) => [p.sent, p.failed]) }),
          legend(pushSeries),
          table("Notiser per dag", ["Dag", "Skickade", "Misslyckade"],
            push.perDay.map((p) => [dayLabel(p.date), num(p.sent), num(p.failed)])))}
        ${stat("Misslyckade notiser", num(failed), { go: { view: "notiser", filter: "failed" }, alert: failed > 0 })}
      </div>
    </div>
    <h3>Utkorgen, senaste ${num(out.days)} dygnen</h3>
    <p class="muted">${num(out.pendingNow)} mejl väntar just nu${out.oldestPendingAt ? `, äldsta köat ${shortDate(out.oldestPendingAt)}` : ""}.</p>
    ${out.categories.length ? `<div class="table-scroll"><table class="dash-outbox">
      <thead><tr><th scope="col">Sort</th><th scope="col" class="num">Skickade</th>
        <th scope="col" class="num">Misslyckade</th><th scope="col" class="num">Väntar</th>
        <th scope="col" class="num">Undertryckta</th></tr></thead>
      <tbody>${out.categories.map((c) => `<tr>
        <th scope="row">${esc(OUTBOX_LABEL[c.category] ?? c.category)}</th>
        <td class="num" data-label="Skickade">${num(c.sent)}</td>
        <td class="num${c.failed ? " is-bad" : ""}" data-label="Misslyckade">${num(c.failed)}</td>
        <td class="num" data-label="Väntar">${num(c.pending)}</td>
        <td class="num" data-label="Undertryckta">${num(c.suppressed)}</td></tr>`).join("")}</tbody>
    </table></div>` : '<p class="muted dash-empty">Inga mejl den senaste veckan.</p>'}`;
}

function anvandning(d) {
  const f7 = d.feedback?.d7 ?? {};
  const f30 = d.feedback?.d30 ?? {};
  const days = d.tipsPerDay ?? [];
  const cats = days.map((p) => ({ label: dayLabel(p.date), long: dayLabel(p.date) }));
  const road = days.reduce((a, p) => a + (p.road ?? 0), 0);
  return `<div class="dash-charts">
    <div class="dash-stats dash-stats-2">
      ${stat("Fick körning", num(f7.fare), { note: `senaste 7 dygnen · ${num(f30.fare)} på 30` })}
      ${stat("Ingen kund", num(f7.empty), { note: `senaste 7 dygnen · ${num(f30.empty)} på 30` })}
      ${stat("Kör dit", num(f7.heading), { note: `senaste 7 dygnen · ${num(f30.heading)} på 30` })}
      ${stat("Träffsäkerhet", pct(f30.fareRate), { note: "fick körning av alla svar, 30 dygn" })}
    </div>
    ${figure(`Nya tips per dag, senaste ${num(d.tipsRetentionDays)} dygnen`,
      `Tipsen gallras efter ${num(d.tipsRetentionDays)} dygn, så längre bakåt går det inte att räkna. Vägolyckor räknas för sig: ${num(road)} st.`,
      columns({ title: "Nya tips per dag", cats, series: [{ label: "Tips", color: C1 }],
        values: days.map((p) => [p.tips]) }),
      "",
      table("Nya tips per dag", ["Dag", "Tips", "Vägolyckor"],
        days.map((p) => [dayLabel(p.date), num(p.tips), num(p.road)])))}
  </div>`;
}

/* --- Sidan --------------------------------------------------------------- */

const SECTIONS = [
  ["ledning", "Ledning"], ["salj", "Sälj"], ["support", "Support"],
  ["uppfoljning", "Uppföljning"], ["drift", "Drift"], ["anvandning", "Användning"],
];

export function dashboard(d) {
  const now = d.generatedAt;
  return `
    <div class="page-head">
      <div><h1>Dashboard</h1>
        <p class="muted">Hela tjänsten på en sida. Tryck på en siffra för att öppna listan bakom den.</p></div>
      <button class="btn btn-quiet" type="button" data-action="goto" data-view="dashboard">Uppdatera</button>
    </div>
    <nav class="chips dash-jump" aria-label="Avsnitt">
      ${SECTIONS.map(([id, label]) => `<a class="chip" href="#dash-${id}">${esc(label)}</a>`).join("")}
      <span class="muted dash-stamp">Räknat ${esc(new Intl.DateTimeFormat("sv-SE", { timeStyle: "short" }).format(new Date(now)))}</span>
    </nav>
    <div class="dash">
      ${section("ledning", "Ledning", "Intäkt, kunder och förare – och hur det rört sig de senaste tolv veckorna.",
        () => ledning(d.ledning), d.ledning)}
      ${section("salj", "Sälj", "Från registrering till betalande kund, och det som ska göras nu.",
        () => salj(d.salj), d.salj)}
      ${section("support", "Support", "Frågor som väntar, rapporter från förarna och fel i appen.",
        () => supportSec(d.support, now), d.support)}
      ${section("uppfoljning", "Uppföljning", "Kunder som riskerar att lämna. Samma lägen som under Uppföljning.",
        () => uppfoljning(d.uppfoljning), d.uppfoljning)}
      ${section("drift", "Drift", "Datakällorna, mejlen och notiserna.", () => drift(d.drift), d.drift)}
      ${section("anvandning", "Användning", "Vad förarna svarar på tipsen, och hur många tips som skapas.",
        () => anvandning(d.anvandning), d.anvandning)}
    </div>`;
}

/* --- Verktygstips ---------------------------------------------------------
 *
 * Ett enda tips för hela vyn, bundet en gång. Samma innehåll vid hovring och
 * tangentbordsfokus. Texten sätts med textContent: kategorinamn är data.
 */

export function bindTooltips(root) {
  let tip = null;
  const hide = () => { if (tip) tip.hidden = true; };
  const show = (target) => {
    let data;
    try { data = JSON.parse(target.dataset.tip); } catch { return; }
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "dv-tip";
      tip.setAttribute("role", "presentation");
      document.body.append(tip);
    }
    tip.replaceChildren();
    const head = document.createElement("div");
    head.className = "dv-tip-head";
    head.textContent = data.title;
    tip.append(head);
    for (const [color, value, label] of data.lines ?? []) {
      const row = document.createElement("div");
      row.className = "dv-tip-row";
      const key = document.createElement("i");
      key.style.setProperty("--c", color);
      const v = document.createElement("b");
      v.textContent = value;
      const l = document.createElement("span");
      l.textContent = label;
      row.append(key, v, l);
      tip.append(row);
    }
    tip.hidden = false;
    const box = target.getBoundingClientRect();
    const w = tip.offsetWidth;
    const left = Math.min(Math.max(8, box.left + box.width / 2 - w / 2), window.innerWidth - w - 8);
    const top = box.top - tip.offsetHeight - 8;
    tip.style.left = `${left}px`;
    tip.style.top = `${top < 8 ? box.bottom + 8 : top}px`;
  };
  const target = (event) => event.target.closest?.("[data-tip]");
  root.addEventListener("pointerover", (e) => { const t = target(e); if (t) show(t); });
  root.addEventListener("pointerout", (e) => { if (!e.relatedTarget?.closest?.("[data-tip]")) hide(); });
  root.addEventListener("focusin", (e) => { const t = target(e); if (t) show(t); else hide(); });
  root.addEventListener("focusout", hide);
  window.addEventListener("scroll", hide, { passive: true });
}
