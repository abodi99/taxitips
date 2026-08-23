const hotspotBar = document.getElementById("hotspotBar");
const cardList = document.getElementById("cardList");
const historyList = document.getElementById("historyList");
const summaryLine = document.getElementById("summaryLine");
const statusLabel = document.getElementById("statusLabel");
const statusMeta = document.getElementById("statusMeta");
const statusDot = document.getElementById("statusDot");
const refreshBtn = document.getElementById("refreshBtn");
const highOnlyToggle = document.getElementById("highOnlyToggle");
const nearMeToggle = document.getElementById("nearMeToggle");
const legendBtn = document.getElementById("legendBtn");
const legendDialog = document.getElementById("legendDialog");
const notifyBtn = document.getElementById("notifyBtn");
const notifyDialog = document.getElementById("notifyDialog");
const notifyError = document.getElementById("notifyError");
const notifyEnabled = document.getElementById("notifyEnabled");
const notifyEnabledHint = document.getElementById("notifyEnabledHint");
const notifyCities = document.getElementById("notifyCities");
const notifyCitiesHint = document.getElementById("notifyCitiesHint");
const notifyClearCities = document.getElementById("notifyClearCities");
const notifyTypes = document.getElementById("notifyTypes");
const notifyTips = document.getElementById("notifyTips");
const notifySaveHint = document.getElementById("notifySaveHint");

let allData = null;
let selectedPlace = null;
let kindFilter = "all"; // all | traffic (trafikfilter — events har egen flik)
let viewMode = "now"; // now | events
let apiQuery = "";
let notifyState = null;
let notifySaveTimer = null;
let userPos = null; // { lat, lon }
const NEAR_KM = 25;

let map = null;
let markerLayer = null;
let roadLayer = null;

const mapDetailDialog = document.getElementById("mapDetailDialog");
const mapDetailTitle = document.getElementById("mapDetailTitle");
const mapDetailLead = document.getElementById("mapDetailLead");
const mapDetailBody = document.getElementById("mapDetailBody");
const focusTitle = document.getElementById("focusTitle");
const focusSub = document.getElementById("focusSub");
const nearMeBtn = document.getElementById("nearMeBtn");
const highOnlyBtn = document.getElementById("highOnlyBtn");
const highOnlyCheck = document.getElementById("highOnlyCheck");
const menuDialog = document.getElementById("menuDialog");
const menuNotify = document.getElementById("menuNotify");
const menuFilter = document.getElementById("menuFilter");
const menuNearMe = document.getElementById("menuNearMe");
const historyPanel = document.getElementById("historyPanel");
const PHASE_ORDER = { approaching: 0, live: 1, after: 2, upcoming: 3 };

async function ensureAccess() {
  const params = new URLSearchParams(location.search);
  const invite = params.get("invite");
  if (invite) {
    const claim = await fetch("/api/devices/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: invite }),
    });
    if (claim.ok) {
      history.replaceState({}, "", "/app.html");
    } else {
      const err = await claim.json().catch(() => ({}));
      statusLabel.textContent = "Ingen access";
      statusDot.className = "dot err";
      statusMeta.textContent = err.error || "Ogiltig enhetslänk";
      cardList.innerHTML = `<div class="empty">${err.error || "Ogiltig enhetslänk"}. <a href="/signup.html">Skapa konto</a></div>`;
      return false;
    }
  }

  if (params.get("demo") === "1") {
    apiQuery = "?demo=1";
    return true;
  }

  const access = await fetch("/api/access");
  if (access.ok) {
    const info = await access.json().catch(() => ({}));
    if (info?.type === "device") {
      if (notifyBtn) notifyBtn.hidden = false;
      if (menuNotify) menuNotify.hidden = false;
    }
    return true;
  }

  statusLabel.textContent = "Saknar licens";
  statusDot.className = "dot warn";
  statusMeta.textContent = "Registrera med bolagskod";
  cardList.innerHTML = `<div class="empty">
    <strong>Registrera telefonen</strong>
    Ange bolagskoden från kontoret.<br/><br/>
    <a href="/join.html">Registrera med kod</a> ·
    <a href="/signup.html">Skapa företagskonto</a> ·
    <a href="/app.html?demo=1">Öppna demo</a>
  </div>`;
  return false;
}

function fmt(ts) {
  if (!ts) return "—";
  return new Intl.DateTimeFormat("sv-SE", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(ts));
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function primaryPlace(alert) {
  return (alert.taxi?.places || [])[0] || "Skåne";
}

function haversineKm(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const R = 6371;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function placeDistanceKm(place) {
  if (!userPos || place?.lat == null || place?.lon == null) return null;
  return Math.round(haversineKm(userPos.lat, userPos.lon, place.lat, place.lon) * 10) / 10;
}

function alertNearUser(alert) {
  if (!nearMeToggle?.checked || !userPos) return true;
  if (alert.lat != null && alert.lon != null) {
    return haversineKm(userPos.lat, userPos.lon, alert.lat, alert.lon) <= NEAR_KM;
  }
  const places = alert.taxi?.places || [];
  const stats = allData?.placeStats || [];
  for (const name of places) {
    const st = stats.find((p) => p.name === name);
    const d = placeDistanceKm(st);
    if (d != null && d <= NEAR_KM) return true;
  }
  return false;
}

function isEventAlert(alert) {
  return (
    alert?.sourceKind === "event" ||
    alert?.taxi?.reason === "event" ||
    String(alert?.id || "").startsWith("tm:") ||
    String(alert?.id || "").startsWith("demo:")
  );
}

function signalKind(alert) {
  if (isEventAlert(alert)) return "event";
  if (alert?.sourceKind === "road" || String(alert?.id || "").startsWith("tv:")) return "road";
  return "transit";
}

function phaseLabel(phase) {
  if (phase === "approaching") return "Folk dit";
  if (phase === "live") return "Pågår";
  if (phase === "after") return "Folk hem";
  if (phase === "upcoming") return "Kommande";
  return null;
}

function phaseNewsLabel(phase) {
  if (phase === "approaching") return "Folk på väg dit";
  if (phase === "live") return "Pågår nu";
  if (phase === "after") return "Folk vill hem";
  if (phase === "upcoming") return "Kommande";
  return "Evenemang";
}

/** Trafikfilter — events ingår aldrig (egen flik). */
function filterTrafficAlerts(alerts) {
  let list = (alerts || []).filter((a) => !isEventAlert(a));
  if (kindFilter === "traffic") {
    /* already traffic-only */
  }
  if (highOnlyToggle?.checked) {
    list = list.filter((a) => a.taxi?.level === "high");
  }
  if (selectedPlace) {
    list = list.filter((a) => (a.taxi?.places || []).includes(selectedPlace));
  }
  if (nearMeToggle?.checked && userPos) {
    list = list.filter(alertNearUser);
  }
  return list;
}

function filterEventsFeed(events) {
  let list = [...(events || [])];
  if (nearMeToggle?.checked && userPos) {
    list = list.filter((ev) => {
      if (ev.lat == null || ev.lon == null) return true;
      return haversineKm(userPos.lat, userPos.lon, ev.lat, ev.lon) <= NEAR_KM;
    });
  }
  list.sort((a, b) => {
    const pa = PHASE_ORDER[a.taxi?.phase] ?? 9;
    const pb = PHASE_ORDER[b.taxi?.phase] ?? 9;
    if (pa !== pb) return pa - pb;
    const ta = a.startsAt ? Date.parse(a.startsAt) : 0;
    const tb = b.startsAt ? Date.parse(b.startsAt) : 0;
    return ta - tb;
  });
  return list;
}

function syncChipButtons() {
  const high = Boolean(highOnlyToggle?.checked);
  const near = Boolean(nearMeToggle?.checked);
  if (highOnlyBtn) highOnlyBtn.setAttribute("aria-pressed", high ? "true" : "false");
  if (nearMeBtn) nearMeBtn.setAttribute("aria-pressed", near ? "true" : "false");
  if (highOnlyCheck) highOnlyCheck.checked = high;
  if (menuNearMe) {
    menuNearMe.textContent = near ? "Nära mig · på" : "Nära mig";
    menuNearMe.setAttribute("aria-pressed", near ? "true" : "false");
  }
}

function syncChromeForMode() {
  const eventsMode = viewMode === "events";
  document.body.classList.toggle("mode-events", eventsMode);
  document.body.classList.toggle("mode-now", !eventsMode);
  if (menuFilter) menuFilter.hidden = eventsMode;
  if (historyPanel) historyPanel.hidden = eventsMode;
}

function clearFilters() {
  selectedPlace = null;
  kindFilter = "all";
  if (highOnlyToggle) highOnlyToggle.checked = true;
  if (nearMeToggle) nearMeToggle.checked = false;
  document.querySelectorAll(".kind-chip").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.kind === "all");
  });
  userPos = null;
  syncChipButtons();
  render(allData);
}

function placesFromFiltered(alerts, placeStats) {
  const statsByName = Object.fromEntries((placeStats || []).map((p) => [p.name, p]));
  const map = new Map();
  const rank = (l) => (l === "high" ? 3 : l === "medium" ? 2 : 1);
  for (const a of alerts || []) {
    const level = a.taxi?.level || "low";
    for (const name of a.taxi?.places || []) {
      const base = statsByName[name] || {};
      const cur = map.get(name) || {
        name,
        count: 0,
        maxLevel: level,
        lat: base.lat,
        lon: base.lon,
        isHub: base.isHub,
      };
      cur.count += 1;
      if (rank(level) > rank(cur.maxLevel)) cur.maxLevel = level;
      map.set(name, cur);
    }
  }
  return [...map.values()].sort((a, b) => rank(b.maxLevel) - rank(a.maxLevel) || b.count - a.count);
}

function initMap() {
  if (map || !window.L) return;
  const el = document.getElementById("hotspotMap");
  if (!el) return;
  map = L.map(el, { zoomControl: true, attributionControl: true }).setView([55.85, 13.5], 9);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
  roadLayer = L.layerGroup().addTo(map);
  markerLayer = L.layerGroup().addTo(map);
  setTimeout(() => map.invalidateSize(), 80);
  window.addEventListener("resize", () => {
    if (map) setTimeout(() => map.invalidateSize(), 80);
  });
}

function markerHtml(level, label, kind) {
  const size = level === "high" ? 44 : level === "medium" ? 36 : 30;
  const cls = kind === "event" ? "event" : level || "low";
  return L.divIcon({
    className: "",
    html: `<div class="hot-marker ${cls}" style="width:${size}px;height:${size}px">${escapeHtml(label)}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function roadStyle(level) {
  if (level === "high") {
    return {
      casing: { color: "#3b120c", weight: 9, opacity: 0.9, lineCap: "round", lineJoin: "round" },
      line: { color: "#e03b2f", weight: 5, opacity: 0.95, lineCap: "round", lineJoin: "round" },
    };
  }
  if (level === "medium") {
    return {
      casing: { color: "#4a2c0a", weight: 8, opacity: 0.85, lineCap: "round", lineJoin: "round" },
      line: { color: "#e08a1a", weight: 4.5, opacity: 0.95, lineCap: "round", lineJoin: "round" },
    };
  }
  return {
    casing: { color: "#2a2620", weight: 7, opacity: 0.7, lineCap: "round", lineJoin: "round" },
    line: { color: "#8a7f70", weight: 3.5, opacity: 0.9, lineCap: "round", lineJoin: "round" },
  };
}

function alertsForPlace(placeName) {
  if (!allData || !placeName) return [];
  return (allData.active || []).filter(
    (a) => !isEventAlert(a) && ((a.taxi?.places || []).includes(placeName) || a.place === placeName)
  );
}

function openMapDetail({ title, lead, items, focusLatLng = null }) {
  if (!mapDetailDialog) return;
  mapDetailTitle.textContent = title || "Vad händer?";
  mapDetailLead.textContent = lead || "";
  mapDetailBody.innerHTML = "";

  if (!items?.length) {
    mapDetailBody.innerHTML = `<div class="empty"><strong>Inget just nu</strong>Ingen detaljerad signal här.</div>`;
  } else {
    for (const alert of items) {
      const kind = signalKind(alert);
      const kindLabel =
        kind === "event" ? "Evenemang" : kind === "road" ? "Väg" : "Kollektiv";
      const el = document.createElement("article");
      el.className = "map-detail-item";
      const phase = phaseLabel(alert.taxi?.phase);
      el.innerHTML = `
        <div class="kind-row">
          <span class="kind-tag ${kind === "event" ? "event" : kind === "road" ? "road" : "transit"}">${kindLabel}</span>
          ${alert.taxi?.level === "high" ? `<span class="kind-tag">Kör hit</span>` : ""}
        </div>
        <h3>${escapeHtml(alert.header || alert.name || "Signal")}</h3>
        <p class="hint">${escapeHtml(alert.taxi?.driverHint || alert.description || "")}</p>
        ${phase ? `<p>${escapeHtml(phase)}</p>` : ""}
        ${
          alert.description && alert.description !== alert.taxi?.driverHint
            ? `<p>${escapeHtml(alert.description)}</p>`
            : ""
        }
        ${alert.routes?.length ? `<p>Väg: ${escapeHtml(alert.routes.join(", "))}</p>` : ""}
      `;
      mapDetailBody.appendChild(el);
    }
  }

  if (focusLatLng && map) {
    map.panTo(focusLatLng, { animate: true });
  }
  if (typeof mapDetailDialog.showModal === "function") {
    mapDetailDialog.showModal();
  }
}

function openPlaceDetail(place) {
  const items = alertsForPlace(place.name);
  selectedPlace = place.name;
  render(allData);
  openMapDetail({
    title: place.name,
    lead: `${items.length} signal${items.length === 1 ? "" : "er"} · ${place.maxLevel || "—"}${
      place.isHub ? " · station" : ""
    }`,
    items,
    focusLatLng: place.lat != null ? [place.lat, place.lon] : null,
  });
}

function openAlertDetail(alert) {
  const place = primaryPlace(alert);
  selectedPlace = place;
  render(allData);
  openMapDetail({
    title: place,
    lead: alert.routes?.length ? `Väg ${alert.routes.join(", ")}` : alert.cause || "Trafik",
    items: [alert],
    focusLatLng: alert.lat != null ? [alert.lat, alert.lon] : alert.geometry?.path?.[0] || null,
  });
}

function openEventDetail(ev) {
  openMapDetail({
    title: ev.name || ev.place || ev.city || "Evenemang",
    lead: [ev.venue, ev.city].filter(Boolean).join(" · "),
    items: [{ ...ev, sourceKind: "event", header: ev.name }],
    focusLatLng: ev.lat != null ? [ev.lat, ev.lon] : null,
  });
}

function drawRoadAlert(alert) {
  if (!roadLayer || !window.L) return;
  const path = alert.geometry?.path;
  if (!path?.length) return;
  if (viewMode === "events") return;
  if (nearMeToggle?.checked && userPos && alert.lat != null) {
    if (haversineKm(userPos.lat, userPos.lon, alert.lat, alert.lon) > NEAR_KM) return;
  }
  if (highOnlyToggle?.checked && alert.taxi?.level !== "high") return;

  const level = alert.taxi?.level || "medium";
  const style = roadStyle(level);
  const latlngs = path;

  const casing = L.polyline(latlngs, { ...style.casing, className: "road-line-hit", interactive: true });
  const line = L.polyline(latlngs, { ...style.line, className: "road-line-hit", interactive: true });

  const open = () => openAlertDetail(alert);
  casing.on("click", open);
  line.on("click", open);
  casing.bindTooltip(`${alert.header || "Väghändelse"} — klicka`, { sticky: true });
  line.bindTooltip(`${alert.header || "Väghändelse"} — klicka`, { sticky: true });

  casing.addTo(roadLayer);
  line.addTo(roadLayer);
  return latlngs;
}

function renderMap(data) {
  initMap();
  if (!map || !markerLayer) return;
  markerLayer.clearLayers();
  if (roadLayer) roadLayer.clearLayers();

  const bounds = [];
  const eventsMode = viewMode === "events";

  if (!eventsMode) {
    let places = data.placeStats || [];
    if (highOnlyToggle?.checked) {
      places = places.filter((p) => p.maxLevel === "high");
    }
    if (nearMeToggle?.checked && userPos) {
      places = places.filter((p) => {
        const d = placeDistanceKm(p);
        return d == null || d <= NEAR_KM;
      });
    }

    for (const alert of data.active || []) {
      if (signalKind(alert) !== "road") continue;
      const latlngs = drawRoadAlert(alert);
      if (latlngs?.length) {
        for (const ll of latlngs) bounds.push(ll);
      } else if (alert.lat != null && alert.lon != null) {
        if (highOnlyToggle?.checked && alert.taxi?.level !== "high") continue;
        if (nearMeToggle?.checked && userPos) {
          if (haversineKm(userPos.lat, userPos.lon, alert.lat, alert.lon) > NEAR_KM) continue;
        }
        const m = L.circleMarker([alert.lat, alert.lon], {
          radius: alert.taxi?.level === "high" ? 9 : 7,
          color: "#fff",
          weight: 2,
          fillColor: alert.taxi?.level === "high" ? "#e03b2f" : "#e08a1a",
          fillOpacity: 0.95,
        });
        m.on("click", () => openAlertDetail(alert));
        m.bindTooltip(alert.header || "Väg", { direction: "top" });
        m.addTo(markerLayer);
        bounds.push([alert.lat, alert.lon]);
      }
    }

    for (const p of places) {
      if (p.lat == null || p.lon == null) continue;
      const m = L.marker([p.lat, p.lon], {
        icon: markerHtml(p.maxLevel, String(p.count || ""), "place"),
      });
      const dist = placeDistanceKm(p);
      m.bindTooltip(
        `${p.name} · ${p.count} signal${p.count === 1 ? "" : "er"}${dist != null ? ` · ${dist} km` : ""}`,
        { direction: "top" }
      );
      m.on("click", () => openPlaceDetail(p));
      m.addTo(markerLayer);
      bounds.push([p.lat, p.lon]);
    }
  } else {
    for (const ev of filterEventsFeed(data.events || [])) {
      if (ev.lat == null || ev.lon == null) continue;
      const m = L.marker([ev.lat, ev.lon], {
        icon: markerHtml(ev.taxi?.level || "medium", "E", "event"),
      });
      m.bindTooltip(`${ev.name || "Evenemang"} — klicka`, { direction: "top" });
      m.on("click", () => openEventDetail(ev));
      m.addTo(markerLayer);
      bounds.push([ev.lat, ev.lon]);
    }
  }

  if (userPos) {
    L.circleMarker([userPos.lat, userPos.lon], {
      radius: 7,
      color: "#08254c",
      fillColor: "#ffc400",
      fillOpacity: 1,
      weight: 2,
    })
      .bindTooltip("Du är här")
      .addTo(markerLayer);
    bounds.push([userPos.lat, userPos.lon]);
  }

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [28, 28], maxZoom: eventsMode ? 12 : 11 });
  } else {
    map.setView([55.85, 13.5], 9);
  }
  setTimeout(() => map.invalidateSize(), 50);
}

function renderHotspots(placeStats, activeCount) {
  hotspotBar.innerHTML = "";

  let places = placeStats || [];
  if (nearMeToggle?.checked && userPos) {
    places = places
      .map((p) => ({ ...p, distanceKm: placeDistanceKm(p) }))
      .filter((p) => p.distanceKm == null || p.distanceKm <= NEAR_KM)
      .sort((a, b) => (a.distanceKm ?? 999) - (b.distanceKm ?? 999));
  }

  places = places.slice(0, 5);

  // No place chips → hide bar (less noise)
  if (!places.length) {
    hotspotBar.hidden = true;
    return;
  }
  hotspotBar.hidden = false;

  const allBtn = document.createElement("button");
  allBtn.type = "button";
  allBtn.className = `hotspot${selectedPlace ? "" : " active"}`;
  allBtn.textContent = "Alla";
  allBtn.addEventListener("click", () => {
    selectedPlace = null;
    render(allData);
  });
  hotspotBar.appendChild(allBtn);

  for (const place of places) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `hotspot ${place.maxLevel}${selectedPlace === place.name ? " active" : ""}`;
    const dist = place.distanceKm ?? placeDistanceKm(place);
    btn.innerHTML = `${escapeHtml(place.name)} <span class="count">${place.count}${
      dist != null ? ` · ${dist}km` : ""
    }</span>`;
    btn.addEventListener("click", () => {
      selectedPlace = selectedPlace === place.name ? null : place.name;
      render(allData);
    });
    hotspotBar.appendChild(btn);
  }
}

function renderCard(alert, { compact = false } = {}) {
  const level = alert.taxi?.level || "medium";
  const place = primaryPlace(alert);
  const hint = alert.taxi?.driverHint || alert.header;
  const kind = signalKind(alert);
  const el = document.createElement("article");
  el.className = `card ${level}`;

  const badge =
    level === "high"
      ? `<span class="badge go">Kör hit</span>`
      : `<span class="badge">Bevaka</span>`;

  const kindMeta = kind === "road" ? "Väg" : "Tåg / kollektiv";

  const details = [];
  if (alert.description) details.push(alert.description);

  el.innerHTML = `
    <div class="card-top">
      <h2 class="place">${escapeHtml(place)}</h2>
      ${badge}
    </div>
    <p class="why">${escapeHtml(hint)}</p>
    <p class="meta">${escapeHtml(kindMeta)}${alert.routes?.length ? ` · ${escapeHtml(alert.routes.join(", "))}` : ""}</p>
    ${
      !compact && details.length
        ? `<details class="more">
            <summary>Mer</summary>
            <p class="meta">${details.map((d) => escapeHtml(d)).join("<br/>")}</p>
          </details>`
        : ""
    }
  `;
  return el;
}

function formatEventWhen(ev) {
  const opts = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" };
  const start = ev.startsAt
    ? new Intl.DateTimeFormat("sv-SE", opts).format(new Date(ev.startsAt))
    : null;
  const end = ev.endsAt
    ? new Intl.DateTimeFormat("sv-SE", { hour: "2-digit", minute: "2-digit" }).format(
        new Date(ev.endsAt)
      )
    : null;
  if (start && end) return `${start} – ${end}`;
  if (start) return start;
  return null;
}

function renderEventCard(ev) {
  const el = document.createElement("article");
  const phase = ev.taxi?.phase || "upcoming";
  el.className = `card event-news phase-${phase}`;
  el.setAttribute("role", "button");
  el.tabIndex = 0;

  const city = ev.city || ev.place || "";
  const venue = ev.venue || "";
  const when = formatEventWhen(ev);
  const phaseText = phaseNewsLabel(phase);
  const hint = ev.taxi?.driverHint || "";

  el.innerHTML = `
    <div class="card-top">
      <h2 class="place">${escapeHtml(ev.name || city || "Evenemang")}</h2>
      <span class="badge phase">${escapeHtml(phaseText)}</span>
    </div>
    <p class="why">${escapeHtml([venue, city].filter(Boolean).join(" · ") || "Skåne")}</p>
    <p class="meta">${when ? escapeHtml(when) : "Tid saknas"}${hint ? ` · ${escapeHtml(hint)}` : ""}</p>
  `;

  if (ev.url) {
    const a = document.createElement("a");
    a.className = "more-link";
    a.href = ev.url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = "Öppna evenemang";
    a.addEventListener("click", (e) => e.stopPropagation());
    el.appendChild(a);
  }

  const open = () => openEventDetail(ev);
  el.addEventListener("click", open);
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open();
    }
  });
  return el;
}

function renderEventsFeed(events) {
  cardList.innerHTML = "";
  const list = filterEventsFeed(events);

  if (!list.length) {
    const near = nearMeToggle?.checked && userPos;
    cardList.innerHTML = near
      ? `<div class="empty"><strong>Inga evenemang nära dig</strong>Slå av “Nära mig” för att se hela Skåne.</div>`
      : `<div class="empty"><strong>Inga evenemang i fönstret just nu</strong>När arena/evenemang dyker upp syns de här som nyhetsflöde.</div>`;
    return list;
  }

  const h = document.createElement("h3");
  h.className = "list-section-title";
  h.textContent = "Evenemang — tips";
  cardList.appendChild(h);
  for (const ev of list) cardList.appendChild(renderEventCard(ev));
  return list;
}

function renderHistory(week) {
  historyList.innerHTML = "";
  const items = filterTrafficAlerts(week).slice(0, 12);
  if (!items.length) {
    historyList.innerHTML = `<div class="empty">Ingen taxi-relevant historik ännu.</div>`;
    return;
  }
  for (const alert of items) {
    historyList.appendChild(renderCard(alert, { compact: true }));
  }
}

function updateFocus(mode, driveNow, places, eventsFeed) {
  if (mode === "events") {
    const n = eventsFeed?.length || 0;
    if (focusTitle) {
      focusTitle.textContent = n === 0 ? "Inga evenemang just nu" : `${n} evenemangstips`;
    }
    if (focusSub) {
      focusSub.hidden = true;
    }
    return;
  }

  const top = places?.find((p) => p.maxLevel === "high") || places?.[0];
  const n = driveNow.length;
  if (focusTitle) {
    if (n === 0) focusTitle.textContent = "Inga tips just nu";
    else if (top) focusTitle.textContent = `Tips: ${top.name}`;
    else focusTitle.textContent = `${n} tips i Skåne`;
  }
  if (focusSub) {
    focusSub.hidden = true;
  }
}

function render(data) {
  if (!data) return;
  allData = data;
  syncChipButtons();
  syncChromeForMode();

  const eventsMode = viewMode === "events";

  if (eventsMode) {
    if (hotspotBar) hotspotBar.hidden = true;
    const feed = renderEventsFeed(data.events || []);
    updateFocus("events", [], [], feed);
    renderMap(data);
    if (summaryLine) summaryLine.textContent = `${feed.length} evenemang`;
  } else {
    const savedPlace = selectedPlace;
    selectedPlace = null;
    const chipSource = filterTrafficAlerts(data.active || []);
    selectedPlace = savedPlace;
    const placeStats = placesFromFiltered(chipSource, data.placeStats || []);

    const driveNow = filterTrafficAlerts(data.active || []).sort(
      (a, b) => (b.taxi?.score || 0) - (a.taxi?.score || 0)
    );

    renderHotspots(placeStats, driveNow.length);
    renderMap(data);
    updateFocus("now", driveNow, placeStats, []);

    if (summaryLine) summaryLine.textContent = `${driveNow.length} signaler`;

    cardList.innerHTML = "";
    const list = driveNow.slice(0, 12);

    if (!list.length) {
      const filtered =
        selectedPlace ||
        kindFilter !== "all" ||
        highOnlyToggle?.checked ||
        (nearMeToggle?.checked && userPos);
      cardList.innerHTML = filtered
        ? `<div class="empty"><strong>Inget i filtret</strong>Slå av “Bara starka” eller nollställ filter.<br/><button type="button" class="btn btn-primary" id="clearFiltersBtn">Visa mer</button></div>`
        : `<div class="empty"><strong>Lugnt läge</strong>Inga tips som brukar ge taxikunder just nu.</div>`;
      document.getElementById("clearFiltersBtn")?.addEventListener("click", () => {
        selectedPlace = null;
        kindFilter = "all";
        if (highOnlyToggle) highOnlyToggle.checked = false;
        if (nearMeToggle) nearMeToggle.checked = false;
        document.querySelectorAll(".kind-chip").forEach((btn) => {
          btn.classList.toggle("on", btn.dataset.kind === "all");
        });
        syncChipButtons();
        render(allData);
      });
    } else {
      const h = document.createElement("h3");
      h.className = "list-section-title";
      h.textContent = "Tips — tåg/väg i Skåne";
      cardList.appendChild(h);
      for (const alert of list) cardList.appendChild(renderCard(alert));
    }

    renderHistory(data.week || []);
  }

  const updated = data.updatedAt ? fmt(data.updatedAt) : "—";
  if (statusMeta) {
    statusMeta.hidden = true;
    statusMeta.textContent = `Uppdaterad ${updated}`;
  }

  if (data.error) {
    statusLabel.textContent = "Fel";
    statusDot.className = "dot err";
  } else {
    statusLabel.textContent = data.source === "mock" ? "Demo" : "Live";
    statusDot.className = data.source === "mock" ? "dot warn" : "dot live";
  }
}

async function load() {
  const res = await fetch(`/api/taxi${apiQuery}`);
  if (res.status === 401) {
    await ensureAccess();
    return;
  }
  const data = await res.json();
  render(data);
}

function requestNearMe() {
  if (!navigator.geolocation) {
    statusMeta.hidden = false;
    statusMeta.textContent = "GPS saknas i den här webbläsaren";
    nearMeToggle.checked = false;
    return;
  }
  statusMeta.hidden = false;
  statusMeta.textContent = "Hämtar position…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      userPos = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      statusMeta.textContent = "Position OK — visar inom 25 km";
      render(allData);
    },
    (err) => {
      nearMeToggle.checked = false;
      statusMeta.textContent = err.message || "Kunde inte hämta position";
    },
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
  );
}

function scheduleNotifySave() {
  clearTimeout(notifySaveTimer);
  notifySaveTimer = setTimeout(saveNotifyPrefs, 280);
}

async function saveNotifyPrefs() {
  if (!notifyState?.prefs) return;
  notifySaveHint.hidden = true;
  notifyError.hidden = true;
  try {
    const res = await fetch("/api/devices/me/notify-prefs", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: notifyState.prefs.enabled,
        cities: notifyState.prefs.cities,
        types: notifyState.prefs.types,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Kunde inte spara");
    notifyState.prefs = data.prefs;
    notifySaveHint.hidden = false;
    setTimeout(() => {
      notifySaveHint.hidden = true;
    }, 1600);
  } catch (err) {
    notifyError.textContent = err.message;
    notifyError.hidden = false;
  }
}

function renderNotifyUi() {
  if (!notifyState) return;
  const { prefs, meta, companyAreas, areaCatalog } = notifyState;
  const enabled = prefs.enabled !== false;
  notifyEnabled.checked = enabled;
  notifyEnabledHint.textContent = enabled ? "På — filtreras enligt nedan" : "Av — ingen push";

  const choices = (companyAreas?.length ? companyAreas : areaCatalog) || [];
  const selected = new Set(prefs.cities || []);
  notifyCitiesHint.textContent = selected.size
    ? "Notiser bara när signalen träffar valda orter."
    : "Inga valda = bolagets bevakade orter (eller hela området).";
  notifyCities.innerHTML = "";
  for (const city of choices) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `city-chip${selected.has(city) ? " on" : ""}`;
    btn.textContent = city;
    btn.disabled = !enabled;
    btn.addEventListener("click", () => {
      const set = new Set(notifyState.prefs.cities || []);
      if (set.has(city)) set.delete(city);
      else set.add(city);
      notifyState.prefs.cities = [...set];
      renderNotifyUi();
      scheduleNotifySave();
    });
    notifyCities.appendChild(btn);
  }

  notifyTypes.innerHTML = "";
  for (const t of meta?.catalog || []) {
    const row = document.createElement("label");
    row.className = "notify-type";
    const checked = prefs.types?.[t.id] === true;
    row.innerHTML = `
      <input type="checkbox" data-type="${escapeHtml(t.id)}" ${checked ? "checked" : ""} ${enabled ? "" : "disabled"} />
      <span>
        <strong>${escapeHtml(t.label)}</strong>
        <p class="short">${escapeHtml(t.short || "")}</p>
        <p class="help">${escapeHtml(t.help || "")}</p>
      </span>
    `;
    const input = row.querySelector("input");
    input.addEventListener("change", () => {
      notifyState.prefs.types[t.id] = input.checked;
      scheduleNotifySave();
    });
    notifyTypes.appendChild(row);
  }

  const tips = meta?.tips || [];
  notifyTips.innerHTML = tips.length
    ? `<strong>Tips</strong><ul>${tips.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`
    : "";
}

async function openNotifySettings() {
  notifyError.hidden = true;
  notifySaveHint.hidden = true;
  try {
    const res = await fetch("/api/devices/me/notify-prefs");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Kunde inte hämta inställningar");
    notifyState = {
      prefs: data.prefs,
      meta: data.meta,
      companyAreas: data.companyAreas || [],
      areaCatalog: data.areaCatalog || [],
    };
    renderNotifyUi();
    notifyDialog.showModal();
  } catch (err) {
    statusMeta.hidden = false;
    statusMeta.textContent = err.message;
  }
}

notifyEnabled?.addEventListener("change", () => {
  if (!notifyState) return;
  notifyState.prefs.enabled = notifyEnabled.checked;
  renderNotifyUi();
  scheduleNotifySave();
});

notifyClearCities?.addEventListener("click", () => {
  if (!notifyState) return;
  notifyState.prefs.cities = [];
  renderNotifyUi();
  scheduleNotifySave();
});

notifyBtn?.addEventListener("click", () => openNotifySettings());
menuNotify?.addEventListener("click", () => {
  menuDialog?.close();
  openNotifySettings();
});

document.getElementById("menuBtn")?.addEventListener("click", () => menuDialog?.showModal());
document.getElementById("menuRefresh")?.addEventListener("click", async () => {
  menuDialog?.close();
  refreshBtn?.click();
});
document.getElementById("menuLegend")?.addEventListener("click", () => {
  menuDialog?.close();
  legendDialog?.showModal();
});
menuFilter?.addEventListener("click", () => {
  menuDialog?.close();
  document.getElementById("filterDialog")?.showModal();
});
menuNearMe?.addEventListener("click", () => {
  menuDialog?.close();
  if (!nearMeToggle) return;
  nearMeToggle.checked = !nearMeToggle.checked;
  syncChipButtons();
  if (nearMeToggle.checked) requestNearMe();
  else render(allData);
});

document.getElementById("filterBtn")?.addEventListener("click", () => {
  document.getElementById("filterDialog")?.showModal();
});
document.getElementById("clearFiltersInDialog")?.addEventListener("click", () => {
  clearFilters();
});

nearMeBtn?.addEventListener("click", () => {
  if (!nearMeToggle) return;
  nearMeToggle.checked = !nearMeToggle.checked;
  syncChipButtons();
  if (nearMeToggle.checked) requestNearMe();
  else render(allData);
});

highOnlyBtn?.addEventListener("click", () => {
  if (!highOnlyToggle) return;
  highOnlyToggle.checked = !highOnlyToggle.checked;
  syncChipButtons();
  render(allData);
});

highOnlyCheck?.addEventListener("change", () => {
  if (!highOnlyToggle) return;
  highOnlyToggle.checked = highOnlyCheck.checked;
  syncChipButtons();
  render(allData);
});

document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    viewMode = btn.getAttribute("data-mode") || "now";
    document.querySelectorAll(".mode-btn").forEach((b) => {
      const on = b === btn;
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    render(allData);
  });
});

refreshBtn.addEventListener("click", async () => {
  refreshBtn.disabled = true;
  try {
    await fetch(`/api/poll${apiQuery}`, { method: "POST" });
    await load();
  } finally {
    refreshBtn.disabled = false;
  }
});

highOnlyToggle?.addEventListener("change", () => {
  syncChipButtons();
  render(allData);
});
nearMeToggle?.addEventListener("change", () => {
  syncChipButtons();
  if (nearMeToggle.checked) requestNearMe();
  else render(allData);
});

document.querySelectorAll(".kind-chip").forEach((btn) => {
  btn.addEventListener("click", () => {
    kindFilter = btn.getAttribute("data-kind") || "all";
    document.querySelectorAll(".kind-chip").forEach((b) => b.classList.toggle("on", b === btn));
    render(allData);
  });
});

legendBtn?.addEventListener("click", () => legendDialog?.showModal());

syncChipButtons();

function connectEvents() {
  const es = new EventSource(`/api/events${apiQuery}`);
  es.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      if (event.type === "hello" || event.type === "poll" || event.type === "alert") {
        load();
      }
      if (event.type === "error") {
        statusLabel.textContent = "Fel";
        statusDot.className = "dot err";
        statusMeta.textContent = event.message;
      }
    } catch {
      /* ignore */
    }
  };
  es.onerror = () => {
    statusLabel.textContent = "Återansluter";
    statusDot.className = "dot warn";
  };
}

(async () => {
  const ok = await ensureAccess();
  if (!ok) return;
  const tabDriver = document.getElementById("tabDriver");
  const tabOffice = document.getElementById("tabOffice");
  if (tabDriver) {
    tabDriver.href = apiQuery.includes("demo=1") ? "/app.html?demo=1" : "/app.html";
  }
  if (tabOffice) tabOffice.href = "/";
  if (!apiQuery && notifyBtn) {
    const probe = await fetch("/api/devices/me/notify-prefs");
    if (probe.ok) notifyBtn.hidden = false;
  }
  initMap();
  load().catch((err) => {
    statusLabel.textContent = "Fel";
    statusDot.className = "dot err";
    statusMeta.textContent = err.message;
  });
  connectEvents();
})();
