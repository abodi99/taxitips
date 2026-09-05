const GtfsRealtimeBindings = require("gtfs-realtime-bindings");

const CAUSE = {
  1: "Okänd orsak",
  2: "Övrigt",
  3: "Tekniskt fel",
  4: "Strejk",
  5: "Demonstration",
  6: "Olycka",
  7: "Semester",
  8: "Väder",
  9: "Underhåll",
  10: "Byggarbete",
  11: "Polisinsats",
  12: "Medicinsk nödsituation",
};

const EFFECT = {
  1: "Ingen service",
  2: "Minskad service",
  3: "Stora förseningar",
  4: "Förseningar",
  5: "Omledning",
  6: "Ytterligare avgångar",
  7: "Modifierad service",
  8: "Annat",
  9: "Okänd effekt",
  10: "Stoppad avgång",
  11: "Inställd avgång",
};

function pickTranslation(translated) {
  if (!translated || !translated.translation) return "";
  const list = translated.translation;
  const sv = list.find((t) => (t.language || "").toLowerCase().startsWith("sv"));
  return (sv || list[0] || {}).text || "";
}

function extractAreas(header, description, entities) {
  const areas = new Set();
  const routes = new Set();
  const stops = new Set();

  for (const entity of entities || []) {
    if (entity.routeId) routes.add(String(entity.routeId));
    if (entity.stopId) stops.add(String(entity.stopId));
    if (entity.agencyId) areas.add(`Operatör ${entity.agencyId}`);
    if (entity.trip?.routeId) routes.add(String(entity.trip.routeId));
  }

  const text = `${header}\n${description}`;
  const placePatterns = [
    /\b(Malmö|Lund|Helsingborg|Kristianstad|Landskrona|Trelleborg|Ystad|Eslöv|Höör|Hässleholm|Ängelholm|Simrishamn|Staffanstorp|Burlöv|Kävlinge|Svedala|Vellinge|Höganäs|Bjuv|Åstorp|Örkelljunga|Perstorp|Osby|Bromölla|Östra Göinge|Skurup|Sjöbo|Hörby|Tomelilla|Båstad|Klippan|Svalöv|Lomma)\b/gi,
    /\b(Halmstad|Falkenberg|Varberg|Laholm|Kungsbacka|Hyltebruk)\b/gi,
    /\b(Karlskrona|Karlshamn|Ronneby|Sölvesborg|Olofström)\b/gi,
    /\b(Växjö|Ljungby|Älmhult|Alvesta|Markaryd|Värnamo|Nässjö|Jönköping|Eksjö)\b/gi,
    /\b(Pågatåg|Öresundståg|Krösatåg|Kustpilen|Pendeln|Citybuss|Regionbuss)\b/gi,
  ];
  for (const pattern of placePatterns) {
    for (const match of text.matchAll(pattern)) {
      areas.add(match[0]);
    }
  }

  if (routes.size) areas.add(`Linjer: ${[...routes].slice(0, 8).join(", ")}`);
  if (stops.size) areas.add(`Hållplatser: ${[...stops].slice(0, 6).join(", ")}`);

  return {
    areas: [...areas],
    routes: [...routes],
    stops: [...stops],
  };
}

function parseFeed(buffer) {
  const feed = GtfsRealtimeBindings.transit_realtime.FeedMessage.decode(buffer);
  const alerts = [];

  for (const entity of feed.entity || []) {
    if (!entity.alert) continue;
    const alert = entity.alert;
    const header = pickTranslation(alert.headerText) || "Störning";
    const description = pickTranslation(alert.descriptionText);
    const url = pickTranslation(alert.url);
    const { areas, routes, stops } = extractAreas(header, description, alert.informedEntity);

    let activeFrom = null;
    let activeTo = null;
    const period = (alert.activePeriod || [])[0];
    if (period) {
      if (period.start) activeFrom = Number(period.start) * 1000;
      if (period.end) activeTo = Number(period.end) * 1000;
    }

    alerts.push({
      id: entity.id || `alert-${header.slice(0, 40)}-${activeFrom || "na"}`,
      header,
      description,
      // Kept for shape-compatibility with road alerts (trafikverket.js sets
      // real values here, and taxiRelevance.js reads it for both sources),
      // but measured against live Skåne data: `effect` is UNKNOWN_EFFECT on
      // 100% of alerts and `cause` never adds signal the Swedish text
      // doesn't already carry -- all CONSTRUCTION/MAINTENANCE alerts are
      // already scored `ignore` from text alone. Don't build scoring rules
      // on these two for the transit path. See docs/data-sources.md.
      cause: CAUSE[alert.cause] || "Okänd orsak",
      effect: EFFECT[alert.effect] || "Okänd effekt",
      areas,
      routes,
      stops,
      url: url || null,
      active_from: activeFrom,
      active_to: activeTo,
    });
  }

  return alerts;
}

function mockAlerts() {
  const now = Date.now();
  return [
    {
      id: "mock-pagatag-lund-malmo",
      header: "Inställda avgångar Pågatåg Lund–Malmö",
      description:
        "På grund av signalproblem är flera Pågatåg mellan Lund C och Malmö C inställda. Ersättningsbussar sätts in. Räkna med längre restider under eftermiddagen.",
      cause: "Tekniskt fel",
      effect: "Inställd avgång",
      areas: ["Lund", "Malmö", "Pågatåg", "Linjer: PA"],
      routes: ["PA"],
      stops: ["82000", "80000"],
      url: "https://www.skanetrafiken.se/",
      active_from: now - 30 * 60 * 1000,
      active_to: now + 3 * 60 * 60 * 1000,
    },
    {
      id: "mock-buss-helsingborg",
      header: "Trafikstörning stadsbuss Helsingborg",
      description:
        "Linje 1 och 2 påverkas av vägarbete i centrum. Bussarna kör alternativ sträckning via Hälsovägen.",
      cause: "Byggarbete",
      effect: "Omledning",
      areas: ["Helsingborg", "Linjer: 1, 2"],
      routes: ["1", "2"],
      stops: [],
      url: null,
      active_from: now - 2 * 60 * 60 * 1000,
      active_to: now + 6 * 60 * 60 * 1000,
    },
  ];
}

async function fetchOperatorAlerts(apiKey, operator) {
  const url = `https://opendata.samtrafiken.se/gtfs-rt-sweden/${encodeURIComponent(operator)}/ServiceAlertsSweden.pb?key=${encodeURIComponent(apiKey)}`;
  const res = await fetch(url, {
    headers: {
      Accept: "application/x-protobuf",
      "Accept-Encoding": "gzip",
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${operator} ${res.status}: ${body.slice(0, 160)}`);
  }

  const buffer = Buffer.from(await res.arrayBuffer());
  return parseFeed(buffer).map((a) => ({
    ...a,
    id: `${operator}:${a.id}`,
    region: operator,
  }));
}

/**
 * Hämta ServiceAlerts för en eller flera regioner nära Skåne.
 * TRAFIKLAB_OPERATORS=skane,blekinge,krono,jlt,halland
 */
function configuredOperators() {
  const raw = process.env.TRAFIKLAB_OPERATORS || "skane";
  return [
    ...new Set(
      raw
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean)
    ),
  ];
}

async function fetchSkaneAlerts(apiKey) {
  if (!apiKey || apiKey === "mock") {
    return { alerts: mockAlerts(), source: "mock", operators: ["mock"] };
  }

  const operators = configuredOperators();
  const merged = [];
  const ok = [];
  const errors = [];

  for (const operator of operators) {
    try {
      const alerts = await fetchOperatorAlerts(apiKey, operator);
      merged.push(...alerts);
      ok.push(operator);
    } catch (err) {
      errors.push({ operator, error: err.message });
      console.error(`[trafiklab] ${operator}:`, err.message);
    }
  }

  if (!ok.length) {
    throw new Error(errors.map((e) => e.error).join(" | ") || "Inga regioner svarade");
  }

  return {
    alerts: merged,
    source: "trafiklab",
    operators: ok,
    errors: errors.length ? errors : undefined,
  };
}

module.exports = {
  fetchSkaneAlerts,
  fetchOperatorAlerts,
  configuredOperators,
  parseFeed,
  mockAlerts,
};
