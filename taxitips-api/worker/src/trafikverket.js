/**
 * Trafikverket öppet API — Situation (väginfo för förare).
 * Gratis nyckel: https://api.trafikinfo.trafikverket.se/
 *
 * Deviation-typer som är relevanta för taxi:
 * Olycka, Vägarbete, Avstängning, Kövarning, Evenemang, Oförutsedda hinder, …
 */

// All 21 Swedish counties (SCB länskoder, which is what Trafikverket's
// Deviation.CountyNo uses). Only the six southern ones were mapped before,
// which silently capped road coverage no matter what TRAFIKVERKET_COUNTIES
// asked for. Verified against the live API: every code below returns real
// Situation data.
const COUNTY = {
  stockholm: "1",
  uppsala: "3",
  sodermanland: "4",
  ostergotland: "5",
  jonkoping: "6",
  kronoberg: "7",
  kalmar: "8",
  gotland: "9",
  blekinge: "10",
  skane: "12",
  halland: "13",
  vastragotaland: "14",
  varmland: "17",
  orebro: "18",
  vastmanland: "19",
  dalarna: "20",
  gavleborg: "21",
  vasternorrland: "22",
  jamtland: "23",
  vasterbotten: "24",
  norrbotten: "25",
};

/** Every county -- convenience for TRAFIKVERKET_COUNTIES=all. */
const ALL_COUNTIES = Object.keys(COUNTY).join(",");

const TAXI_TYPES = new Set([
  "olycka",
  "vägarbete",
  "vägarbete",
  "avstängning",
  "avstangning",
  "kövarning",
  "kovarning",
  "trafikmeddelande",
  "evenemang",
  "oförutsedda hinder",
  "oforutsedda hinder",
  "hinder",
  "viktig trafikinformation",
  "vägarbete, planerat",
]);

function configuredCounties() {
  const configured = process.env.TRAFIKVERKET_COUNTIES || "skane";
  const raw = configured.trim().toLowerCase() === "all" ? ALL_COUNTIES : configured;
  return [
    ...new Set(
      raw
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .map((name) => COUNTY[name])
        .filter(Boolean)
    ),
  ];
}

function levelForDeviation(dev) {
  const t = String(dev.MessageType || dev.IconId || "").toLowerCase();
  const sev = String(dev.SeverityText || dev.SeverityCode || "").toLowerCase();
  if (t.includes("olycka") || t.includes("avstäng") || t.includes("avstang") || sev.includes("mycket")) {
    return "high";
  }
  if (t.includes("kö") || t.includes("ko") || t.includes("hinder") || t.includes("arbete")) {
    return "medium";
  }
  return "low";
}

function placesFromDeviation(dev) {
  const places = [];
  const loc = `${dev.LocationDescriptor || ""} ${dev.Message || ""} ${dev.RoadNumber || ""} ${dev.CountyNo || ""}`;
  const known =
    loc.match(
      /\b(Malmö|Lund|Helsingborg|Kristianstad|Hässleholm|Landskrona|Halmstad|Karlskrona|Växjö|Älmhult|Ystad|Trelleborg|Ängelholm|Eslöv|Kävlinge|Bromölla|Hyllie|Markaryd|Höganäs|Vellinge)\b/gi
    ) || [];
  for (const p of known) {
    if (!places.some((x) => x.toLowerCase() === p.toLowerCase())) places.push(p);
  }
  // Vägnr bara om ingen ort hittades (annars drunknar kartan i E4/Väg…)
  if (!places.length && dev.RoadNumber) {
    places.push(String(dev.RoadNumber));
  }
  return places;
}

/** Parse Trafikverket WGS84 WKT → Leaflet-friendly path [[lat,lon],…] */
function parseWgs84Geometry(geometry) {
  if (!geometry) return null;
  const lineWkt = geometry.Line?.WGS84 || null;
  const pointWkt = geometry.Point?.WGS84 || geometry.WGS84 || null;
  const wkt = lineWkt || pointWkt;
  if (!wkt || typeof wkt !== "string") return null;

  const toLatLon = (pair) => {
    const parts = String(pair).trim().split(/\s+/).map(Number);
    if (parts.length < 2 || !Number.isFinite(parts[0]) || !Number.isFinite(parts[1])) return null;
    // WGS84 WKT is lon lat
    return [parts[1], parts[0]];
  };

  let path = [];
  if (/^LINESTRING/i.test(wkt)) {
    const inner = wkt.replace(/^LINESTRING\s*\(/i, "").replace(/\)\s*$/, "");
    path = inner.split(",").map(toLatLon).filter(Boolean);
  } else if (/^POINT/i.test(wkt)) {
    const m = wkt.match(/POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)/i);
    if (m) path = [[Number(m[2]), Number(m[1])]];
  }

  if (!path.length) return null;

  // Simplify very long stretches for map performance
  if (path.length > 80) {
    const step = Math.ceil(path.length / 60);
    const simplified = path.filter((_, i) => i % step === 0 || i === path.length - 1);
    path = simplified;
  }

  const mid = path[Math.floor(path.length / 2)];
  return {
    lat: mid[0],
    lon: mid[1],
    path,
  };
}

function normalizeSituation(situation) {
  const deviations = situation.Deviation || [];
  const list = Array.isArray(deviations) ? deviations : deviations ? [deviations] : [];
  return list.map((dev, i) => {
    const header = dev.Header || dev.MessageType || "Väghändelse";
    const description = [dev.Message, dev.LocationDescriptor, dev.RoadNumber ? `Väg ${dev.RoadNumber}` : null]
      .filter(Boolean)
      .join(" · ");
    const places = placesFromDeviation(dev);
    const level = levelForDeviation(dev);
    const type = String(dev.MessageType || "Situation");
    const geometry = parseWgs84Geometry(dev.Geometry);
    return {
      id: `tv:${situation.Id || "sit"}:${dev.Id || i}`,
      header,
      description,
      cause: type,
      effect: dev.SeverityText || "Vägpåverkan",
      areas: places,
      routes: dev.RoadNumber ? [String(dev.RoadNumber)] : [],
      stops: [],
      url: null,
      active_from: situation.PublicationTime ? Date.parse(situation.PublicationTime) : Date.now(),
      active_to: null,
      sourceKind: "road",
      region: "trafikverket",
      lat: geometry?.lat ?? null,
      lon: geometry?.lon ?? null,
      geometry: geometry || null,
      taxi: {
        level,
        score: level === "high" ? 70 : level === "medium" ? 45 : 20,
        places,
        driverHint:
          level === "high"
            ? `${type}: undvik / räkna med omväg — ${places[0] || "området"}.`
            : `${type} i ${places[0] || "området"} — bra att känna till.`,
        reason: "trafikverket_situation",
      },
    };
  });
}

function mockRoadAlerts() {
  const now = Date.now();
  // Approximate E22 stretch north of Lund (for map polyline demo)
  const e22Path = [
    [55.74, 13.22],
    [55.755, 13.235],
    [55.77, 13.25],
    [55.785, 13.265],
    [55.8, 13.28],
  ];
  const malmoPath = [
    [55.606, 13.0],
    [55.6055, 13.002],
    [55.605, 13.004],
    [55.6045, 13.006],
  ];
  return [
    {
      id: "tv:mock-e22",
      header: "Olycka E22 norr om Lund",
      description: "Ett körfält avstängt. Köbildning mot Lund. Räkna med 15–25 min extra.",
      cause: "Olycka",
      effect: "Kövarning",
      areas: ["Lund", "E22"],
      routes: ["E22"],
      stops: [],
      url: null,
      active_from: now - 20 * 60 * 1000,
      active_to: null,
      sourceKind: "road",
      region: "trafikverket",
      lat: 55.77,
      lon: 13.25,
      geometry: { lat: 55.77, lon: 13.25, path: e22Path },
      taxi: {
        level: "high",
        score: 72,
        places: ["Lund", "E22"],
        driverHint: "Olycka E22 — undvik / räkna med omväg kring Lund.",
        reason: "trafikverket_situation",
      },
    },
    {
      id: "tv:mock-malmo",
      header: "Vägarbete Malmö centrum",
      description: "Stängd gata vid Stortorget kvällstid. Evenemang i området.",
      cause: "Vägarbete",
      effect: "Avstängning",
      areas: ["Malmö"],
      routes: [],
      stops: [],
      url: null,
      active_from: now - 60 * 60 * 1000,
      active_to: now + 4 * 60 * 60 * 1000,
      sourceKind: "road",
      region: "trafikverket",
      lat: 55.605,
      lon: 13.003,
      geometry: { lat: 55.605, lon: 13.003, path: malmoPath },
      taxi: {
        level: "medium",
        score: 48,
        places: ["Malmö"],
        driverHint: "Vägarbete i Malmö centrum — bra att känna till.",
        reason: "trafikverket_situation",
      },
    },
  ];
}

async function fetchRoadSituations(apiKey) {
  if (!apiKey || apiKey === "mock") {
    return { alerts: mockRoadAlerts(), source: "mock", counties: ["mock"] };
  }

  const counties = configuredCounties();
  const countyFilter = counties
    .map((c) => `<EQ name="Deviation.CountyNo" value="${c}" />`)
    .join("");

  // The county filter is an OR across all configured counties, so `limit`
  // caps the WHOLE country's results, not per-county -- and which rows
  // survive is undefined. At limit=100 across 21 counties that silently
  // returned FEWER national alerts than Skåne alone (measured: 127 vs 176).
  // Scale the cap with the number of counties so national coverage is
  // actually national.
  const limit = Math.min(100 * Math.max(counties.length, 1), 2000);

  // Situation ligger under namespace road.trafficinfo (krävs i API v2).
  const body = `
<REQUEST>
  <LOGIN authenticationkey="${apiKey}" />
  <QUERY objecttype="Situation" namespace="road.trafficinfo" schemaversion="1.6" limit="${limit}">
    <FILTER>
      <OR>
        ${countyFilter || '<EQ name="Deviation.CountyNo" value="12" />'}
      </OR>
    </FILTER>
  </QUERY>
</REQUEST>`.trim();

  const res = await fetch("https://api.trafikinfo.trafikverket.se/v2/data.json", {
    method: "POST",
    headers: { "Content-Type": "text/xml", Accept: "application/json" },
    body,
  });

  const data = await res.json().catch(() => ({}));
  const block = data?.RESPONSE?.RESULT?.[0] || {};
  if (!res.ok || block.ERROR) {
    const msg = block.ERROR?.MESSAGE || JSON.stringify(data).slice(0, 200);
    throw new Error(`Trafikverket ${res.status}: ${msg}`);
  }

  const sits = block.Situation || [];
  const list = Array.isArray(sits) ? sits : sits ? [sits] : [];
  const situations = [];
  for (const sit of list) situations.push(...normalizeSituation(sit));

  const filtered = situations.filter((a) => {
    const t = String(a.cause || "").toLowerCase();
    return [...TAXI_TYPES].some((k) => t.includes(k)) || a.taxi?.level !== "low";
  });

  return {
    alerts: filtered.length ? filtered : situations.slice(0, 40),
    source: "trafikverket",
    counties,
  };
}

module.exports = {
  fetchRoadSituations,
  mockRoadAlerts,
  configuredCounties,
  COUNTY,
};
