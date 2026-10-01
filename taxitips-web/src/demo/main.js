/**
 * Taxi Tips demo: 3D-karta över Sverige med exempeltips.
 *
 * Används på taxitips.se/demo och av säljare i möten. Listan, tipskortet
 * och turen fungerar även utan karta (om WebGL saknas eller kartplattorna
 * inte laddar), så demon går aldrig sönder mitt i ett möte.
 *
 * Länkar för säljare:
 *   /demo?tur=1          startar turen direkt, utan introt
 *   /demo#stockholm-c    öppnar ett visst tips
 *   /demo?intro=1        visar introt igen
 */
import { CATEGORIES, STRENGTHS, TIPS, TOUR, TOUR_END } from "./data.js";
import { CAT_ICONS, UI } from "./icons.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const desktopMq = matchMedia("(min-width: 960px)");
const isDesktop = () => desktopMq.matches;

const els = {
  stage: $("#stage"),
  map: $("#map"),
  loading: $("#mapLoading"),
  noMap: $("#noMap"),
  filters: $("#filters"),
  list: $("#listPanel"),
  items: $("#tipslista"),
  listCount: $("#listCount"),
  dockCount: $("#dockCount"),
  listBtn: $("#listBtn"),
  detail: $("#detailPanel"),
  detailBody: $("#detailBody"),
  detailNav: $("#detailNav"),
  tour: $("#tourPanel"),
  tourBar: $("#tourBar"),
  tourStep: $("#tourStep"),
  tourHead: $("#tourHead"),
  tourText: $("#tourText"),
  tourEnd: $("#tourEnd"),
  tourPlay: $("#tourPlay"),
  tourOpen: $("#tourOpen"),
  dock: $("#dock"),
  intro: $("#intro"),
  toast: $("#toast"),
};

const state = {
  filter: "alla",
  selected: null,
  listOpen: false,
  trigger: null,
  following: new Set(),
  tour: { active: false, index: 0, playing: false, timer: 0, started: 0, remaining: 0 },
};

let mapApi = null;

/* ---------- Ikoner i statisk HTML ---------- */

for (const el of $$("[data-icon]")) el.innerHTML = UI[el.dataset.icon] || "";
$("#overviewBtn").innerHTML = UI.sweden;
$$(".d-sheet-close").forEach((b) => (b.innerHTML = UI.close));
$("[data-step='-1']").innerHTML = UI.back;
$("[data-step='1']").innerHTML = UI.fwd;
$("#tourPrev").innerHTML = UI.back;
$("#tourNext").innerHTML = UI.fwd;

/* ---------- Tid ----------
   Allt räknas från när sidan öppnades, så klockslag och nedräkning alltid
   hänger ihop. När ett tips har räknat ned till noll börjar demon om från
   nu, så att sidan kan stå öppen under ett helt möte. */

let base = floorMinute(Date.now());
function floorMinute(ms) {
  return ms - (ms % 60000);
}
const elapsed = () => Math.floor((Date.now() - base) / 60000);
const pad2 = (n) => String(n).padStart(2, "0");
function t(offsetMin) {
  const d = new Date(base + offsetMin * 60000);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}
function left(tip) {
  return tip.minutes - elapsed();
}
function liveText(tip) {
  if (tip.ongoing) return "Pågår nu";
  const m = left(tip);
  if (m <= 0) return "Nu";
  if (m >= 60) return `om ${Math.floor(m / 60)} tim ${m % 60} min`;
  return `om ${m} min`;
}
function clockText(tip) {
  return tip.ongoing ? `Sedan ${t(tip.minutes)}` : t(tip.minutes);
}

/* ---------- Filter ---------- */

const visibleTips = () => TIPS.filter((x) => state.filter === "alla" || x.cat === state.filter);

function renderFilters() {
  els.filters.innerHTML = CATEGORIES.map((c) => {
    const n = c.id === "alla" ? TIPS.length : TIPS.filter((x) => x.cat === c.id).length;
    const icon = c.id === "alla" ? "" : `<span class="d-chip-ico">${CAT_ICONS[c.id]}</span>`;
    return `<button type="button" class="d-chip" data-filter="${c.id}" aria-pressed="${state.filter === c.id}">${icon}${c.label}<span class="d-chip-n">${n}</span></button>`;
  }).join("");
}

els.filters.addEventListener("click", (e) => {
  const b = e.target.closest("[data-filter]");
  if (!b) return;
  setFilter(b.dataset.filter);
});

function setFilter(id) {
  state.filter = id;
  $$(".d-chip", els.filters).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === id)));
  const ids = visibleTips().map((x) => x.id);
  renderList();
  if (state.selected && !ids.includes(state.selected)) closeDetail({ restoreFocus: false });
  mapApi?.setVisible(ids);
  if (!state.tour.active) mapApi?.overview();
}

/* ---------- Lista ---------- */

const RANK = { stark: 0, medel: 1, svag: 2 };
function sorted(list) {
  return [...list].sort(
    (a, b) => RANK[a.strength] - RANK[b.strength] || (a.ongoing ? -1 : 0) - (b.ongoing ? -1 : 0) || a.minutes - b.minutes
  );
}

function renderList() {
  const list = sorted(visibleTips());
  els.listCount.textContent = list.length;
  els.dockCount.textContent = list.length;
  els.items.innerHTML = list
    .map(
      (x) => `
      <li>
        <button type="button" class="d-item s-${x.strength}" data-id="${x.id}" aria-current="${state.selected === x.id}">
          <span class="d-item-ico">${CAT_ICONS[x.cat]}</span>
          <span class="d-item-main">
            <span class="d-item-place">${x.place}</span>
            <span class="d-item-kind">${x.kind} · ${x.city}</span>
          </span>
          <span class="d-item-side">
            <span class="d-pill s-${x.strength}">${STRENGTHS[x.strength].label}</span>
            <span class="d-item-time" data-live="${x.id}">${liveText(x)}</span>
          </span>
        </button>
      </li>`
    )
    .join("");
}

els.items.addEventListener("click", (e) => {
  const b = e.target.closest("[data-id]");
  if (!b) return;
  if (state.tour.active) stopTour({ quiet: true });
  openDetail(b.dataset.id, b);
});

/* ---------- Bottenark (mobil) ---------- */

function openList() {
  if (isDesktop()) {
    els.items.focus({ preventScroll: true });
    return;
  }
  if (state.selected) closeDetail({ restoreFocus: false });
  state.listOpen = true;
  els.list.dataset.state = "open";
  els.listBtn.setAttribute("aria-expanded", "true");
  document.body.classList.add("is-list-open");
  requestAnimationFrame(() => $(".d-list-title", els.list).focus?.({ preventScroll: true }));
  mapApi?.setPadding();
}

function closeList({ restoreFocus = true } = {}) {
  if (!state.listOpen) return;
  state.listOpen = false;
  els.list.dataset.state = "closed";
  els.list.style.transform = "";
  els.listBtn.setAttribute("aria-expanded", "false");
  document.body.classList.remove("is-list-open");
  if (restoreFocus) els.listBtn.focus({ preventScroll: true });
  mapApi?.setPadding();
}

els.listBtn.addEventListener("click", () => (state.listOpen ? closeList() : openList()));
$("#noMapList").addEventListener("click", openList);

/* Dra nedåt i greppet för att stänga arket. */
function enableDrag(panel, onClose) {
  const grabs = $$("[data-grab], .d-detail-bar, .d-list-head", panel);
  let y0 = 0;
  let dy = 0;
  let t0 = 0;
  let dragging = false;
  for (const g of grabs) {
    g.addEventListener("pointerdown", (e) => {
      if (isDesktop() || e.button > 0 || e.target.closest("button, a")) return;
      dragging = true;
      y0 = e.clientY;
      dy = 0;
      t0 = performance.now();
      panel.classList.add("is-dragging");
      g.setPointerCapture(e.pointerId);
    });
    g.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      dy = Math.max(0, e.clientY - y0);
      panel.style.transform = `translateY(${dy}px)`;
    });
    const end = () => {
      if (!dragging) return;
      dragging = false;
      panel.classList.remove("is-dragging");
      const fast = dy / Math.max(1, performance.now() - t0) > 0.6;
      if (dy > 90 || (fast && dy > 30)) {
        onClose();
      } else {
        panel.style.transform = "";
      }
    };
    g.addEventListener("pointerup", end);
    g.addEventListener("pointercancel", end);
  }
}
enableDrag(els.list, () => closeList());
enableDrag(els.detail, () => closeDetail());

/* ---------- Tipskortet ---------- */

function cardHtml(x) {
  const s = STRENGTHS[x.strength];
  const following = state.following.has(x.id);
  return `
    <article class="tc s-${x.strength}">
      <div class="tc-head">
        <span class="tc-icon">${CAT_ICONS[x.cat]}</span>
        <div>
          <p class="tc-cat">${x.kind}</p>
          <span class="tc-lvl">${s.label}</span>
        </div>
      </div>
      <h2 class="tc-place" id="detailPlace" tabindex="-1">${x.place}</h2>
      <p class="tc-city">${x.city}</p>
      <div class="tc-actions">
        <button type="button" class="tc-btn tc-go" data-act="go">${UI.go}Kör dit</button>
        <button type="button" class="tc-btn tc-follow" data-act="follow" aria-pressed="${following}">${UI.star}${following ? "Följer" : "Följ"}</button>
      </div>
      <div class="tc-chips">
        <span class="tc-chip">${UI.clock}<span data-clock="${x.id}">${clockText(x)}</span></span>
        <span class="tc-chip tc-live${x.ongoing ? " is-ongoing" : ""}" data-live="${x.id}">${liveText(x)}</span>
      </div>
      <p class="tc-what">${x.what(t)}</p>
      <p class="tc-next">${UI.next}<span>${x.next(t)}</span></p>
      <div class="tc-why">
        <p class="tc-why-t">Varför visas detta?</p>
        <p class="tc-why-k">Bedömning</p>
        <p class="tc-why-v">${x.why}</p>
        <p class="tc-why-k">Det bygger på</p>
        <ul class="tc-signals">${x.signals.map((g) => `<li>${UI.check}${g}</li>`).join("")}</ul>
        <p class="tc-why-k">Styrka</p>
        <p class="tc-why-s"><b>${s.label}.</b> ${s.note}</p>
      </div>
      <div class="tc-fb">
        <p>Var tipset bra? Tryck efter resan.</p>
        <div class="tc-fb-row">
          <button type="button" class="tc-btn tc-fb-btn" data-act="fb-yes">${UI.up}Fick körning</button>
          <button type="button" class="tc-btn tc-fb-btn" data-act="fb-no">${UI.down}Ingen kund</button>
        </div>
      </div>
    </article>
    <div class="d-sell">
      <p><b>Vill ni ha det här i bolagets bilar?</b> Provet är gratis och du behöver inget kort.</p>
      <div class="d-sell-row">
        <a class="d-btn d-btn-gold" href="/registrera" data-track="demo_card_signup">Prova gratis</a>
        <a class="d-btn d-btn-ghost" href="/#kontakt" data-track="demo_card_book">Boka demo</a>
      </div>
    </div>
    <p class="d-fineprint">Exempeldata. Platsen är riktig, händelsen är påhittad för demon.</p>`;
}

function openDetail(id, trigger, { fly = true, focus = true } = {}) {
  const x = TIPS.find((v) => v.id === id);
  if (!x) return;
  if (state.listOpen) closeList({ restoreFocus: false });
  state.selected = id;
  state.trigger = trigger || state.trigger;
  els.detailBody.innerHTML = cardHtml(x);
  els.detailNav.hidden = state.tour.active || visibleTips().length < 2;
  els.detail.style.transform = "";
  els.detail.hidden = false;
  els.detailBody.scrollTop = 0; // först nu, när panelen syns
  document.body.classList.add("is-detail-open");
  // En bildruta senare, så att CSS-övergången syns.
  requestAnimationFrame(() => {
    els.detail.dataset.state = "open";
    if (focus) $("#detailPlace").focus({ preventScroll: true });
    mapApi?.select(id);
    if (fly) mapApi?.focusTip(id);
  });
  $$(".d-item", els.items).forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === id)));
  try {
    history.replaceState(null, "", `${location.pathname}${location.search}#${id}`);
  } catch {}
}

function closeDetail({ restoreFocus = true } = {}) {
  if (!state.selected) return;
  state.selected = null;
  els.detail.dataset.state = "closed";
  document.body.classList.remove("is-detail-open");
  mapApi?.select(null);
  mapApi?.setPadding();
  $$(".d-item", els.items).forEach((b) => b.setAttribute("aria-current", "false"));
  const done = () => {
    if (!state.selected) els.detail.hidden = true;
    els.detail.style.transform = "";
  };
  setTimeout(done, reducedMotion ? 0 : 320);
  try {
    history.replaceState(null, "", `${location.pathname}${location.search}`);
  } catch {}
  if (restoreFocus) {
    const back = state.trigger && document.contains(state.trigger) && !state.trigger.hidden ? state.trigger : null;
    (back || (state.tour.active ? els.tourPlay : els.listBtn.offsetParent ? els.listBtn : els.items)).focus({
      preventScroll: true,
    });
  }
  state.trigger = null;
}

els.detail.addEventListener("click", (e) => {
  if (e.target.closest("[data-close]")) return closeDetail();
  const step = e.target.closest("[data-step]");
  if (step) {
    const list = sorted(visibleTips());
    const i = list.findIndex((v) => v.id === state.selected);
    const next = list[(i + Number(step.dataset.step) + list.length) % list.length];
    openDetail(next.id, null, { focus: false });
    return;
  }
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (!act) return;
  const x = TIPS.find((v) => v.id === state.selected);
  if (act === "go") toast(`I appen öppnas vägen till ${x.place} i din kartapp.`);
  if (act === "follow") {
    const b = e.target.closest("[data-act]");
    const on = !state.following.has(x.id);
    on ? state.following.add(x.id) : state.following.delete(x.id);
    b.setAttribute("aria-pressed", String(on));
    b.innerHTML = `${UI.star}${on ? "Följer" : "Följ"}`;
    toast(on ? `Du följer ${x.place}. Då får du fler notiser därifrån.` : `Du följer inte ${x.place} längre.`);
  }
  if (act === "fb-yes" || act === "fb-no") {
    $$(".tc-fb-btn", els.detail).forEach((b) => b.classList.toggle("is-on", b === e.target.closest("[data-act]")));
    toast("Tack! Så blir tipsen bättre. I demon sparas inget.");
  }
});

$("[data-close='list']").addEventListener("click", () => closeList());

/* ---------- Turen ---------- */

const STEP_MS = 9000;

function startTour() {
  if (els.intro.open) els.intro.close();
  closeList({ restoreFocus: false });
  if (state.filter !== "alla") setFilter("alla");
  Object.assign(state.tour, { active: true, index: 0, playing: true });
  document.body.classList.add("is-touring");
  els.tour.hidden = false;
  showStep(0);
  els.tourPlay.focus({ preventScroll: true });
}

function stopTour({ quiet = false } = {}) {
  if (!state.tour.active) return;
  clearTimeout(state.tour.timer);
  state.tour.active = false;
  state.tour.playing = false;
  document.body.classList.remove("is-touring");
  els.tour.hidden = true;
  if (!quiet) {
    closeDetail({ restoreFocus: false });
    $("[data-tour-start]", isDesktop() ? els.list : els.dock)?.focus({ preventScroll: true });
    mapApi?.overview();
  }
  mapApi?.setPadding();
}

function showStep(i) {
  const tour = state.tour;
  clearTimeout(tour.timer);
  tour.index = i;
  const n = TOUR.length;
  const end = i >= n;
  els.tour.classList.toggle("is-end", end);
  els.tourEnd.hidden = !end;
  els.tourOpen.hidden = end;
  $("#tourNext").disabled = end;
  $("#tourPrev").disabled = i === 0;

  if (end) {
    els.tourStep.textContent = "Klart";
    els.tourHead.innerHTML = "Så funkar Taxi Tips";
    els.tourText.textContent = TOUR_END;
    tour.playing = false;
    updatePlay();
    closeDetail({ restoreFocus: false });
    resetBar(0, true);
    mapApi?.overview();
    return;
  }

  const x = TIPS.find((v) => v.id === TOUR[i]);
  els.tourStep.textContent = `${i + 1} av ${n}`;
  els.tourHead.innerHTML = `<span class="d-tour-ico s-${x.strength}">${CAT_ICONS[x.cat]}</span><span class="d-tour-place">${x.place}</span><span class="d-pill s-${x.strength}">${STRENGTHS[x.strength].label}</span>`;
  els.tourText.textContent = x.tour;

  if (isDesktop()) {
    openDetail(x.id, null, { focus: false });
  } else {
    if (state.selected) closeDetail({ restoreFocus: false });
    mapApi?.select(x.id);
    requestAnimationFrame(() => mapApi?.focusTip(x.id));
  }
  tour.remaining = STEP_MS;
  if (tour.playing) runTimer();
  else resetBar(0, true);
  updatePlay();
}

function runTimer() {
  const tour = state.tour;
  tour.started = performance.now();
  const done = 1 - tour.remaining / STEP_MS;
  resetBar(done, true);
  requestAnimationFrame(() => {
    els.tourBar.style.transition = `transform ${tour.remaining}ms linear`;
    els.tourBar.style.transform = "scaleX(1)";
  });
  tour.timer = setTimeout(() => showStep(tour.index + 1), tour.remaining);
}

function resetBar(fraction, instant) {
  if (instant) els.tourBar.style.transition = "none";
  els.tourBar.style.transform = `scaleX(${fraction})`;
}

function pauseTour() {
  const tour = state.tour;
  if (!tour.playing) return;
  tour.playing = false;
  clearTimeout(tour.timer);
  tour.remaining = Math.max(0, tour.remaining - (performance.now() - tour.started));
  resetBar(1 - tour.remaining / STEP_MS, true);
  updatePlay();
}

function playTour() {
  const tour = state.tour;
  if (tour.index >= TOUR.length) return showStep(0), playTour();
  if (tour.playing) return;
  tour.playing = true;
  if (!tour.remaining) tour.remaining = STEP_MS;
  runTimer();
  updatePlay();
}

function updatePlay() {
  const end = state.tour.index >= TOUR.length;
  const playing = state.tour.playing;
  els.tourPlay.innerHTML = end ? UI.play : playing ? UI.pause : UI.play;
  els.tourPlay.setAttribute("aria-label", end ? "Börja om" : playing ? "Pausa" : "Spela");
}

$$("[data-tour-start]").forEach((b) => b.addEventListener("click", startTour));
$("#tourStop").addEventListener("click", () => stopTour());
// Bläddra utan att pausa: spelar turen, fortsätter den från det nya steget.
$("#tourNext").addEventListener("click", () => showStep(state.tour.index + 1));
$("#tourPrev").addEventListener("click", () => showStep(Math.max(0, state.tour.index - 1)));
els.tourPlay.addEventListener("click", () => (state.tour.playing ? pauseTour() : playTour()));
els.tourOpen.addEventListener("click", () => {
  pauseTour();
  openDetail(TOUR[state.tour.index], els.tourOpen, { fly: false });
});

/* ---------- Intro ---------- */

const params = new URLSearchParams(location.search);
const hashTip = TIPS.find((x) => `#${x.id}` === location.hash);

function introSeen() {
  try {
    return localStorage.getItem("tt-demo-intro") === "1";
  } catch {
    return false;
  }
}
function markIntroSeen() {
  try {
    localStorage.setItem("tt-demo-intro", "1");
  } catch {}
}

function showIntro() {
  if (typeof els.intro.showModal === "function") {
    els.intro.showModal();
  } else {
    els.intro.setAttribute("open", "");
  }
}
els.intro.addEventListener("click", (e) => {
  if (e.target.closest("[data-intro-close]") || e.target === els.intro) {
    if (els.intro.open) els.intro.close();
  }
});
els.intro.addEventListener("close", markIntroSeen);
$("#helpBtn").addEventListener("click", showIntro);
$("#overviewBtn").addEventListener("click", () => {
  if (state.tour.active) stopTour({ quiet: true });
  closeDetail({ restoreFocus: false });
  mapApi?.overview();
});

/* ---------- Tangentbord ---------- */

document.addEventListener("keydown", (e) => {
  if (els.intro.open) return; // dialogen sköter Esc själv
  if (e.key === "Escape") {
    if (state.selected && !(isDesktop() && state.tour.active)) return closeDetail();
    if (state.listOpen) return closeList();
    if (state.tour.active) return stopTour();
  }
  if (!state.tour.active || e.target.closest("input, textarea")) return;
  if (e.key === "ArrowRight") $("#tourNext").click();
  if (e.key === "ArrowLeft") $("#tourPrev").click();
});

/* ---------- Toast ---------- */

let toastTimer = 0;
function toast(msg) {
  els.toast.textContent = msg;
  els.toast.classList.add("is-on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.remove("is-on"), 3200);
}

/* ---------- Nedräkning ---------- */

function tick() {
  if (TIPS.some((x) => !x.ongoing && left(x) <= 0)) {
    base = floorMinute(Date.now());
    renderList();
    if (state.selected) {
      const scroll = els.detailBody.scrollTop;
      els.detailBody.innerHTML = cardHtml(TIPS.find((v) => v.id === state.selected));
      els.detailBody.scrollTop = scroll;
    }
    return;
  }
  for (const el of $$("[data-live]")) {
    const x = TIPS.find((v) => v.id === el.dataset.live);
    const txt = liveText(x);
    if (el.textContent !== txt) {
      el.textContent = txt;
      el.classList.remove("tick");
      void el.offsetWidth;
      el.classList.add("tick");
    }
  }
}
setInterval(tick, 10000);

/* ---------- Kartans synliga yta ---------- */

/** Var börjar det som täcker kartan nerifrån på mobil (knapprad, tur, ark)? */
function bottomCover() {
  const stage = els.stage.getBoundingClientRect();
  let cover = stage.bottom;
  if (els.dock.offsetParent) cover = els.dock.getBoundingClientRect().top;
  if (state.tour.active && !els.tour.hidden && !(state.selected && !isDesktop())) {
    cover = Math.min(cover, els.tour.getBoundingClientRect().top);
  }
  if (state.selected) cover = Math.min(cover, stage.bottom - els.detail.offsetHeight);
  if (state.listOpen) cover = Math.min(cover, stage.bottom - els.list.offsetHeight);
  return Math.max(0, stage.bottom - cover);
}

function updateCover() {
  els.stage.style.setProperty("--cover-b", `${isDesktop() ? 0 : bottomCover() + 4}px`);
}

function getPadding() {
  const stage = els.stage.getBoundingClientRect();
  const filtersShown = isDesktop() || !(state.selected || state.listOpen);
  const top = filtersShown ? Math.max(0, els.filters.getBoundingClientRect().bottom - stage.top) + 8 : 12;
  updateCover();
  if (isDesktop()) {
    // Mått utan transform: panelerna kan vara mitt i en glidning.
    const gap = 16;
    const leftPad = els.list.offsetWidth + gap * 2;
    const rightPad = state.selected ? els.detail.offsetWidth + gap * 2 : 8;
    const bottom = state.tour.active && !els.tour.hidden ? els.tour.offsetHeight + gap * 2 : 8;
    return { top, left: leftPad, right: rightPad, bottom };
  }
  const bottom = bottomCover() + 8;
  // Lämna alltid minst 140 px karta.
  const room = stage.height - top - bottom;
  return { top, left: 8, right: 8, bottom: Math.max(0, room < 140 ? bottom - (140 - room) : bottom) };
}

if ("ResizeObserver" in window) {
  const ro = new ResizeObserver(() => updateCover());
  [els.dock, els.tour, els.detail, els.list].forEach((el) => ro.observe(el));
}
addEventListener("resize", updateCover);

/* ---------- Kartan ---------- */

function hasWebGL() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGL2RenderingContext && c.getContext("webgl2")) || !!c.getContext("webgl");
  } catch {
    return false;
  }
}

function mapUnavailable() {
  els.loading.hidden = true;
  els.noMap.hidden = false;
  document.body.classList.add("no-map");
}

async function loadMap() {
  if (!hasWebGL()) return mapUnavailable();
  let mod;
  try {
    mod = await import("./map.js");
  } catch (err) {
    console.warn("[demo] kartan kunde inte laddas", err);
    return mapUnavailable();
  }
  let loaded = false;
  const slow = setTimeout(() => {
    if (!loaded) mapUnavailable();
  }, 20000);
  mapApi = mod.createMap({
    container: els.map,
    tips: TIPS,
    reducedMotion,
    getPadding,
    onFail: () => {
      clearTimeout(slow);
      mapUnavailable();
    },
    onSelect: (id, el) => {
      if (state.tour.active) stopTour({ quiet: true });
      openDetail(id, el);
    },
    onReady: () => {
      loaded = true;
      clearTimeout(slow);
      els.loading.hidden = true;
      els.noMap.hidden = true;
      document.body.classList.remove("no-map");
      document.body.classList.add("map-ready");
      afterMapReady();
    },
  });
  if (!mapApi) return;
  if (import.meta.env.DEV) window.__demoMap = mapApi.map;
  mapApi.map.on("click", (e) => {
    if (!isDesktop() && state.selected && !e.originalEvent.target.closest(".mk")) closeDetail({ restoreFocus: false });
  });
  // Om man själv tar tag i kartan under turen pausas den.
  const userMove = (e) => {
    if (e.originalEvent && state.tour.active) pauseTour();
  };
  mapApi.map.on("dragstart", userMove);
  mapApi.map.on("zoomstart", userMove);
  mapApi.map.on("rotatestart", userMove);
}

function afterMapReady() {
  mapApi.setVisible(visibleTips().map((x) => x.id));
  if (state.selected) {
    mapApi.select(state.selected);
    mapApi.focusTip(state.selected);
  } else if (state.tour.active) {
    const id = TOUR[state.tour.index];
    if (id) {
      mapApi.select(id);
      mapApi.focusTip(id);
    } else mapApi.overview();
  } else {
    mapApi.overview();
  }
}

desktopMq.addEventListener("change", () => {
  if (isDesktop()) closeList({ restoreFocus: false });
  mapApi?.setPadding();
});

/* ---------- Start ---------- */

renderFilters();
renderList();
loadMap();

if (params.get("tur") === "1") {
  startTour();
} else if (hashTip) {
  openDetail(hashTip.id, null, { focus: false });
} else if (params.get("intro") === "1" || !introSeen()) {
  showIntro();
}
