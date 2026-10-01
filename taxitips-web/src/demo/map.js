/**
 * 3D-kartan. Laddas först när sidan är uppe (dynamisk import), så att
 * listan och knapparna fungerar direkt och kartbiblioteket inte hamnar
 * på någon annan sida.
 */
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { navyStyle } from "./mapstyle.js";
import { CAT_ICONS } from "./icons.js";

const SWEDEN = [
  [10.6, 55.25],
  [24.2, 69.1],
];

const PILLAR_HEIGHT = { stark: 240, medel: 150, svag: 80 };
const PILLAR_COLOR = { stark: "#fca311", medel: "#ffd08a", svag: "#8e9ab0" };

/** En liten månghörning runt punkten, för ljuspelaren i 3D. */
function circlePolygon([lng, lat], meters, steps = 28) {
  const coords = [];
  const dLat = meters / 111320;
  const dLng = meters / (111320 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    coords.push([lng + Math.cos(a) * dLng, lat + Math.sin(a) * dLat]);
  }
  return [coords];
}

export function createMap({ container, tips, reducedMotion, onSelect, getPadding, onReady, onFail }) {
  let map;
  try {
    map = new maplibregl.Map({
      container,
      style: navyStyle(),
      center: [15.5, 58.5],
      zoom: reducedMotion ? 3.6 : 1.6,
      pitch: 0,
      bearing: 0,
      maxPitch: 70,
      attributionControl: false,
      dragRotate: true,
      pitchWithRotate: true,
      cooperativeGestures: false,
      fadeDuration: 150,
    });
  } catch (err) {
    onFail?.(err);
    return null;
  }

  map.addControl(
    new maplibregl.AttributionControl({
      compact: true,
    }),
    "bottom-right"
  );
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  map.touchZoomRotate.enableRotation();

  /* ---------- Markörer ---------- */

  const markers = new Map(); // id -> { marker, el, tip }
  let visible = new Set(tips.map((t) => t.id));
  let selectedId = null;

  for (const tip of tips) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = `mk mk-${tip.strength} mk-${tip.cat}`;
    el.dataset.id = tip.id;
    el.setAttribute("aria-label", `${tip.place}, ${tip.kind}, ${labelFor(tip.strength)}. Visa tipset.`);
    el.innerHTML = `
      <span class="mk-ring" aria-hidden="true"></span>
      <span class="mk-head" aria-hidden="true">${CAT_ICONS[tip.cat]}</span>
      <span class="mk-count" aria-hidden="true"></span>
      <span class="mk-label" aria-hidden="true">${tip.place}</span>
      <span class="mk-stem" aria-hidden="true"></span>`;
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const group = el._group;
      if (group && group.length > 1) {
        zoomToGroup(group);
      } else {
        onSelect(tip.id, el);
      }
    });
    const marker = new maplibregl.Marker({ element: el, anchor: "bottom", subpixelPositioning: true })
      .setLngLat(tip.lngLat)
      .addTo(map);
    markers.set(tip.id, { marker, el, tip });
  }

  function labelFor(s) {
    return s === "stark" ? "Stark" : s === "medel" ? "Medel" : "Svag";
  }

  /* Enkel gruppering i skärmen: prickar som ligger på varandra slås ihop
     till en med ett antal. Tryck på den så zoomar kartan in. Bara 13
     punkter, så det räcker att räkna om varje bildruta. */
  const RANK = { stark: 0, medel: 1, svag: 2 };
  let raf = 0;
  function regroup() {
    raf = 0;
    const items = tips
      .filter((t) => visible.has(t.id))
      .map((t) => ({ t, p: map.project(t.lngLat) }))
      .sort((a, b) => RANK[a.t.strength] - RANK[b.t.strength] || a.t.minutes - b.t.minutes);
    const used = new Set();
    const groups = [];
    for (const a of items) {
      if (used.has(a.t.id)) continue;
      used.add(a.t.id);
      const g = [a.t];
      for (const b of items) {
        if (used.has(b.t.id)) continue;
        if (Math.hypot(a.p.x - b.p.x, a.p.y - b.p.y) < 46) {
          used.add(b.t.id);
          g.push(b.t);
        }
      }
      groups.push(g);
    }
    const lead = new Map();
    for (const g of groups) for (const t of g) lead.set(t.id, g);

    for (const [id, { el }] of markers) {
      const g = lead.get(id);
      const show = visible.has(id) && g && g[0].id === id;
      el.hidden = !show;
      el.tabIndex = show ? 0 : -1;
      if (!show) continue;
      el._group = g;
      const n = g.length;
      el.classList.toggle("is-group", n > 1);
      el.querySelector(".mk-count").textContent = n > 1 ? String(n) : "";
      el.setAttribute(
        "aria-label",
        n > 1
          ? `${n} tips nära ${g[0].city}. Zooma in.`
          : `${g[0].place}, ${g[0].kind}, ${labelFor(g[0].strength)}. Visa tipset.`
      );
    }
  }
  const scheduleRegroup = () => {
    if (!raf) raf = requestAnimationFrame(regroup);
  };
  map.on("move", scheduleRegroup);
  map.on("resize", scheduleRegroup);

  function zoomToGroup(group) {
    const lngs = group.map((t) => t.lngLat[0]);
    const lats = group.map((t) => t.lngLat[1]);
    const box = [
      [Math.min(...lngs), Math.min(...lats)],
      [Math.max(...lngs), Math.max(...lats)],
    ];
    const zoom = Math.min(14.5, fitZoom(box, 70));
    move({ center: centerOf(box), zoom, pitch: 45, bearing: map.getBearing(), padding: getPadding() }, "fly");
  }

  /* ---------- 3D-lager: ljuspelare och glöd på marken ---------- */

  function pillarData() {
    return {
      type: "FeatureCollection",
      features: tips
        .filter((t) => visible.has(t.id))
        .map((t) => ({
          type: "Feature",
          properties: {
            h: PILLAR_HEIGHT[t.strength],
            c: PILLAR_COLOR[t.strength],
            sel: t.id === selectedId ? 1 : 0,
          },
          geometry: { type: "Polygon", coordinates: circlePolygon(t.lngLat, t.strength === "stark" ? 28 : 22) },
        })),
    };
  }
  function glowData() {
    return {
      type: "FeatureCollection",
      features: tips
        .filter((t) => visible.has(t.id))
        .map((t) => ({
          type: "Feature",
          properties: { c: PILLAR_COLOR[t.strength], sel: t.id === selectedId ? 1 : 0 },
          geometry: { type: "Point", coordinates: t.lngLat },
        })),
    };
  }

  let ready = false;
  map.on("load", () => {
    map.addSource("glow", { type: "geojson", data: glowData() });
    map.addSource("pillars", { type: "geojson", data: pillarData() });
    map.addLayer(
      {
        id: "glow",
        type: "circle",
        source: "glow",
        minzoom: 9,
        paint: {
          "circle-color": ["get", "c"],
          "circle-radius": ["interpolate", ["exponential", 2], ["zoom"], 9, 6, 13, 40, 16, 230],
          "circle-blur": 1,
          "circle-opacity": ["case", ["==", ["get", "sel"], 1], 0.55, 0.28],
          "circle-pitch-alignment": "map",
        },
      },
      "building-3d"
    );
    map.addLayer({
      id: "pillars",
      type: "fill-extrusion",
      source: "pillars",
      minzoom: 11,
      paint: {
        "fill-extrusion-color": ["get", "c"],
        "fill-extrusion-height": ["interpolate", ["linear"], ["zoom"], 11, 0, 13, ["get", "h"]],
        "fill-extrusion-base": 0,
        "fill-extrusion-opacity": 0.55,
        "fill-extrusion-vertical-gradient": true,
      },
    });
    ready = true;
    regroup();
    onReady?.();
  });

  function refreshLayers() {
    if (!ready) return;
    map.getSource("pillars")?.setData(pillarData());
    map.getSource("glow")?.setData(glowData());
  }

  /* ---------- Kamera ---------- */


  function move(cam, duration) {
    if (reducedMotion) {
      map.jumpTo(cam);
    } else if (duration === "fly") {
      map.flyTo({ ...cam, speed: 0.9, curve: 1.5, maxDuration: 6500, essential: false });
    } else {
      map.easeTo({ ...cam, duration, essential: false });
    }
  }

  const mercY = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

  /** Zoom som får plats med en lng/lat-ruta i den synliga delen av kartan. */
  function fitZoom([[w, s], [e, n]], marginPx) {
    const p = getPadding();
    const c = map.getContainer();
    const availW = Math.max(80, c.clientWidth - p.left - p.right - marginPx * 2);
    const availH = Math.max(80, c.clientHeight - p.top - p.bottom - marginPx * 2);
    const fracW = Math.max((e - w) / 360, 1e-6);
    const fracH = Math.max((mercY(n) - mercY(s)) / (2 * Math.PI), 1e-6);
    return Math.min(Math.log2(availW / (512 * fracW)), Math.log2(availH / (512 * fracH)));
  }
  const centerOf = ([[w, s], [e, n]]) => {
    const y = (mercY(n) + mercY(s)) / 2;
    return [(w + e) / 2, (360 / Math.PI) * Math.atan(Math.exp(y)) - 90];
  };

  function overview(animate = true) {
    let box = SWEDEN;
    let maxZoom = 6;
    if (visible.size && visible.size < tips.length) {
      const pts = tips.filter((t) => visible.has(t.id)).map((t) => t.lngLat);
      const lngs = pts.map((q) => q[0]);
      const lats = pts.map((q) => q[1]);
      box = [
        [Math.min(...lngs), Math.min(...lats)],
        [Math.max(...lngs), Math.max(...lats)],
      ];
      maxZoom = 11;
    }
    const zoom = Math.min(maxZoom, fitZoom(box, box === SWEDEN ? 6 : 50));
    // Lätt lutning ger djup utan att södra Sverige hamnar utanför.
    const narrow = map.getContainer().clientWidth < 600;
    move({ center: centerOf(box), zoom: zoom - (narrow ? 0.25 : 0.05), pitch: 20, bearing: 0, padding: getPadding() }, animate ? "fly" : 0);
  }

  function focusTip(id) {
    const t = tips.find((x) => x.id === id);
    if (!t) return;
    move(
      { center: t.lngLat, zoom: 15.2, pitch: 60, bearing: t.bearing || 0, padding: getPadding() },
      "fly"
    );
  }

  function select(id) {
    selectedId = id;
    for (const [mid, { el }] of markers) el.classList.toggle("is-selected", mid === id);
    refreshLayers();
  }

  function setVisible(ids) {
    visible = new Set(ids);
    refreshLayers();
    regroup();
  }

  function setPadding() {
    // Kameran håller sig till den synliga delen av kartan.
    map.easeTo({ padding: getPadding(), duration: reducedMotion ? 0 : 400 });
  }

  function markerEl(id) {
    return markers.get(id)?.el;
  }

  return { map, overview, focusTip, select, setVisible, setPadding, markerEl, regroup };
}
