/**
 * Rankar störningar efter nytta för taxiförare.
 *
 * Princip: visa bara när folk faktiskt kan behöva skjuts —
 * inställda tåg, stora störningar, ersättningsbuss, olycka, m.m.
 * Ignorera stationsservice (hiss, toalett, cykel, …).
 */

const { findHubsInText } = require("./hubs");
const { alertInSkane, placeLooksSkane } = require("./skane");

/** Station/info utan taxinytta — även om rubriken nämner en station. */
const NOISE_RE =
  /(hiss(en|ar|arna)?|rulltrapp|rullstol|toalett|cykel|cyklar|wifi|wi-?fi|biljettautomat|biljettmaskin|entr[eé]|assistans|assistent|ledsag|plattformsavvisare|platsbrist|kort tåg|nya spår)/i;

/** Allvarliga kollektivstörningar som brukar ge taxibehov. */
const SERIOUS_RE =
  /\b(inställd|inställda|ställs in|inga avgångar|ingen trafik|trafikstopp|stopp i (trafiken|tågtrafiken|busstrafiken)|totalt stopp|stora störningar|stora förseningar|ersättningsbuss|ersättningstrafik|strejk|nedrivning|strömavbrott|växelfel|signalproblem|tågtrafik (står|stoppad|inställd)|alla (pågatåg|öresundståg|tåg) (är )?inställda|avgång(ar)? inställd|inställd avgång|tåg(en)? (går|kör) inte|banan (är )?avstängd)\b/i;

/** Medel — kan ge efterfrågan men inte alltid “kör hit nu”. */
const MEDIUM_RE =
  /\b(försening|förseningar|minskad (service|trafik)|tågbyte|enkelspårsdrift|hastighetsnedsättning|banarbete som påverkar|förväntas bli (sen|försenad))\b/i;

const CITY_RE =
  /\b(Malmö|Lund|Helsingborg|Kristianstad|Landskrona|Trelleborg|Ystad|Eslöv|Höör|Hässleholm|Ängelholm|Simrishamn|Staffanstorp|Kävlinge|Hyllie|Triangeln|Lomma|Vellinge|Höganäs|Osby|Sjöbo|Svedala|Burlöv|Bromölla|Perstorp|Örkelljunga|Bjuv|Åstorp|Klippan)\b/gi;

const SKANE_ROAD_HINT =
  /\b(malmö|lund|helsingborg|kristianstad|landskrona|trelleborg|ystad|eslöv|hässleholm|ängelholm|simrishamn|kävlinge|hyllie|vellinge|höganäs|lomma|staffanstorp|bromölla|skåne|e22|e6|e65|väg 11|väg 108)\b/i;

function textOf(alert) {
  return `${alert.header || ""}\n${alert.description || ""}\n${alert.cause || ""}\n${alert.effect || ""}`;
}

function placesFrom(alert) {
  const text = `${alert.header || ""} ${alert.description || ""}`;
  const places = [];
  const hubs = findHubsInText(text);
  for (const hub of hubs) {
    if (!places.some((x) => x.toLowerCase() === hub.name.toLowerCase())) {
      places.push(hub.name);
    }
  }
  for (const m of text.matchAll(CITY_RE)) {
    const p = m[0];
    const coveredByHub = hubs.some(
      (h) => h.city.toLowerCase() === p.toLowerCase() || h.name.toLowerCase() === p.toLowerCase()
    );
    if (coveredByHub && hubs.length) continue;
    if (!places.some((x) => x.toLowerCase() === p.toLowerCase())) places.push(p);
  }
  return places.filter((p) => placeLooksSkane(p) || /köpenhamn|cph|kastrup/i.test(String(p)));
}

function ignoreResult(why, alert) {
  return {
    score: 0,
    level: "ignore",
    why,
    places: placesFrom(alert),
    driverHint: null,
    hubs: [],
  };
}

function isNoiseOnly(text) {
  if (!NOISE_RE.test(text)) return false;
  // Hiss + inställda tåg i samma text → behåll allvarliga delen
  return !SERIOUS_RE.test(text);
}

function hasSeriousEffect(alert) {
  const effect = String(alert.effect || "").toLowerCase();
  return (
    effect.includes("ingen service") ||
    effect.includes("inställd") ||
    effect.includes("stoppad") ||
    effect.includes("stora försening") ||
    effect.includes("minskad service")
  );
}

function scoreAlert(alert) {
  const header = (alert.header || "").trim();
  const text = textOf(alert);
  const textLower = text.toLowerCase();

  if (isNoiseOnly(text)) {
    return ignoreResult("Stationsservice (hiss/toalett/cykel m.m.) — ingen taxinytta", alert);
  }

  if (/^stängd hållplats$/i.test(header) || /^hållplats /i.test(header)) {
    if (!SERIOUS_RE.test(text)) {
      return ignoreResult("Enstaka hållplatsinfo", alert);
    }
  }

  if (/^trafikinformation$/i.test(header) && !SERIOUS_RE.test(text) && !MEDIUM_RE.test(text)) {
    return ignoreResult("Allmän trafikinfo", alert);
  }

  // Tillfällig körväg / hållplatsflytt utan inställda tåg → inte “kör hit”
  if (
    /tillfällig (körväg|hållplats)|hänvisas till/i.test(text) &&
    !SERIOUS_RE.test(text) &&
    !/inställd/i.test(text)
  ) {
    return ignoreResult("Omledning/hållplatsflytt — låg taxinytta", alert);
  }

  const hubs = findHubsInText(text);
  const places = placesFrom(alert);
  const placeStr = places.length ? places.join(", ") : "Skåne";
  const hubName = hubs[0]?.name;

  const serious =
    SERIOUS_RE.test(text) ||
    (hasSeriousEffect(alert) &&
      (textLower.includes("tåg") ||
        textLower.includes("påga") ||
        textLower.includes("öresund") ||
        textLower.includes("buss") ||
        hubs.length > 0));

  const mediumish = MEDIUM_RE.test(text) || String(alert.effect || "").toLowerCase().includes("försening");

  // "Tekniskt fel" ensamt (t.ex. hiss) ska aldrig bli high
  const technicalOnly =
    /tekniskt fel/i.test(String(alert.cause || "")) && !serious && !mediumish;

  if (technicalOnly || (!serious && !mediumish && !hasSeriousEffect(alert))) {
    // Orsak/effekt utan allvarliga nyckelord → oftast brus
    if (!serious) {
      return ignoreResult("Ingen allvarlig trafikstörning", alert);
    }
  }

  let score = 0;
  const reasons = [];

  if (serious) {
    score = 70;
    reasons.push("allvarlig störning");
    if (/inställd|ställs in|inga avgångar|ingen trafik/i.test(text)) {
      score = 85;
      reasons.push("inställd/stopp");
    }
    if (/ersättningsbuss|ersättningstrafik/i.test(text)) {
      score += 5;
      reasons.push("ersättningsbuss");
    }
  } else if (mediumish) {
    score = 35;
    reasons.push("försening/påverkan");
  } else {
    return ignoreResult("Otillräcklig taxirelevans", alert);
  }

  if (hubs.length) {
    score += Math.min(12, Math.round((hubs[0].weight || 0) * 0.25));
    reasons.push(`station: ${hubs[0].name}`);
  }

  let level = "ignore";
  if (score >= 60 && serious) level = "high";
  else if (score >= 30) level = "medium";
  else if (score > 0) level = "low";

  // Hub-boost får aldrig ensamt lyfta till high utan allvarlig störning
  if (!serious && level === "high") level = "medium";

  let driverHint = null;
  if (level === "high") {
    driverHint = hubName
      ? `Station ${hubName}: resenärer behöver skjuts — kör hit. ${header}`
      : `Ökad taxieftefrågan trolig i ${placeStr}. Kollektivtrafik störd: ${header}`;
  } else if (level === "medium") {
    driverHint = hubName
      ? `Kolla ${hubName}: ${header}`
      : `Möjlig ökad efterfrågan i ${placeStr}: ${header}`;
  }

  return {
    score,
    level,
    why: reasons.slice(0, 4).join(", ") || "låg relevans",
    places,
    hubs: hubs.map((h) => h.name),
    driverHint,
    // Exposed so mode-aware severity tiering (scoring.js) can reuse the same
    // serious/mediumish signals instead of re-deriving them with a second regex pass.
    serious,
    mediumish,
  };
}

function scoreRoadAlert(alert) {
  const type = String(alert.cause || alert.header || "").toLowerCase();
  const text = `${alert.header || ""} ${alert.description || ""} ${alert.effect || ""}`.toLowerCase();
  let places = Array.isArray(alert.areas)
    ? alert.areas.filter((p) => p && !String(p).startsWith("Linjer") && !String(p).startsWith("Hållplatser"))
    : [];
  const hubs = findHubsInText(text);
  for (const hub of hubs) {
    if (!places.some((x) => x.toLowerCase() === hub.name.toLowerCase())) {
      places = [hub.name, ...places];
    }
  }

  const inSkaneSphere = SKANE_ROAD_HINT.test(text) || places.some((p) => SKANE_ROAD_HINT.test(String(p)));
  const isAccident = type.includes("olycka") || text.includes("olycka");
  const isFullClosure =
    text.includes("vägen avstäng") ||
    text.includes("helt avstäng") ||
    type.includes("avstängning") ||
    type.includes("avstangning");
  const isRoadwork = type.includes("vägarbete") || text.includes("beläggningsarbete") || text.includes("vägarbete");
  const isQueue = type.includes("kö") || text.includes("kövarning") || text.includes("köbildning");

  // Planerat nattarbete / beläggning långt bort → ingen taxisignal
  if (isRoadwork && !isAccident && !inSkaneSphere) {
    return {
      score: 0,
      level: "ignore",
      why: "Vägarbete utanför relevant område",
      places,
      hubs: hubs.map((h) => h.name),
      driverHint: null,
    };
  }

  if (isRoadwork && !isAccident && text.includes("kl 19") && text.includes("05:00")) {
    return {
      score: 0,
      level: "ignore",
      why: "Nattligt vägarbete — låg taxinytta",
      places,
      hubs: hubs.map((h) => h.name),
      driverHint: null,
    };
  }

  let level = "ignore";
  let score = 0;

  if (isAccident && inSkaneSphere) {
    level = "high";
    score = 75;
  } else if (isAccident) {
    level = "medium";
    score = 40;
  } else if (isFullClosure && inSkaneSphere && !isRoadwork) {
    level = "high";
    score = 65;
  } else if (isQueue && inSkaneSphere) {
    level = "medium";
    score = 40;
  } else if (isFullClosure && inSkaneSphere && isRoadwork) {
    // Avstängd väg i Skåne p.g.a. arbete — bevaka, inte “kör hit”
    level = "medium";
    score = 32;
  } else if (isRoadwork && inSkaneSphere) {
    level = "low";
    score = 15;
  } else {
    return {
      score: 0,
      level: "ignore",
      why: "Väginfo utan taxirelevans",
      places,
      hubs: hubs.map((h) => h.name),
      driverHint: null,
    };
  }

  // Vägarbete får aldrig bli high
  if (isRoadwork && !isAccident && level === "high") {
    level = "medium";
    score = Math.min(score, 40);
  }

  const place = places[0] || hubs[0]?.name || "vägen";
  return {
    score,
    level,
    why: isAccident ? "olycka" : isRoadwork ? "vägarbete" : "väg",
    places,
    hubs: hubs.map((h) => h.name),
    driverHint:
      level === "high"
        ? `${alert.cause || "Väg"} nära ${place}: omväg + mer efterfrågan.`
        : level === "medium"
          ? `${alert.cause || "Väginfo"} i ${place} — bra att känna till.`
          : null,
  };
}

function isRoadAlert(alert) {
  return (
    alert?.sourceKind === "road" ||
    alert?.source_kind === "road" ||
    String(alert?.id || "").startsWith("tv:")
  );
}

function enrichAlert(alert) {
  if (isRoadAlert(alert)) {
    const scored = { ...alert, sourceKind: "road", taxi: scoreRoadAlert(alert) };
    if (!alertInSkane(scored) && scored.taxi.level !== "ignore") {
      return {
        ...scored,
        taxi: {
          ...scored.taxi,
          score: 0,
          level: "ignore",
          why: "Utanför Skåne",
          driverHint: null,
        },
      };
    }
    return scored;
  }
  const taxi = scoreAlert(alert);
  const enriched = { ...alert, taxi };
  if (!alertInSkane(enriched) && taxi.level !== "ignore") {
    return {
      ...enriched,
      taxi: {
        ...taxi,
        score: 0,
        level: "ignore",
        why: "Utanför Skåne",
        driverHint: null,
      },
    };
  }
  return enriched;
}

function filterForTaxi(alerts, { minLevel = "medium" } = {}) {
  const order = { high: 3, medium: 2, low: 1, ignore: 0 };
  const min = order[minLevel] ?? 2;
  return alerts
    .map(enrichAlert)
    .filter((a) => (order[a.taxi.level] || 0) >= min)
    .sort((a, b) => b.taxi.score - a.taxi.score || b.lastSeenAt - a.lastSeenAt);
}

function isTaxiNotifyWorthy(alert) {
  const taxi = alert.taxi || (isRoadAlert(alert) ? scoreRoadAlert(alert) : scoreAlert(alert));
  return taxi.level === "high";
}

module.exports = {
  scoreAlert,
  scoreRoadAlert,
  enrichAlert,
  filterForTaxi,
  isTaxiNotifyWorthy,
  isRoadAlert,
};

const h3 = require("h3-js");

function calculateDemandSignal(alert) {
  let h3_index = null;
  // Get lat/lon from alert (from raw payload or parsed)
  const lat = alert.lat || alert.payload?.lat;
  const lon = alert.lon || alert.payload?.lon;
  
  if (lat && lon) {
    h3_index = h3.latLngToCell(lat, lon, 8);
  }

  let demand_score = alert.taxi?.score || 0;
  let reasons = alert.taxi?.why ? alert.taxi.why.split(',').map(s => s.trim()) : [];
  
  const text = (alert.header + " " + alert.description).toLowerCase();
  const isTrain = text.includes("tåg") || text.includes("påga") || text.includes("öresund");
  
  // Last train risk: late night check
  // NOTE: raw source alerts carry active_to (ms epoch), not endsAt -- this never matched
  // before, so the +30 "Last Train Risk" boost has never actually applied.
  const end = alert.active_to ? new Date(alert.active_to) : null;
  if (isTrain && end) {
    const hours = end.getHours();
    // Late night / early morning (e.g. 22:00 - 04:00)
    if (hours >= 22 || hours <= 4) {
      demand_score = Math.min(100, demand_score + 30);
      reasons.push("Last Train Risk");
    }
  }

  return { h3_index, demand_score, reasons };
}

module.exports.calculateDemandSignal = calculateDemandSignal;

