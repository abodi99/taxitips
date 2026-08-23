/**
 * Trafikplatser / stationer där taxi-affär uppstår.
 * Koordinater (WGS84) för karta + “nära mig”.
 */

const HUBS = [
  {
    id: "malmo-c",
    name: "Malmö C",
    aliases: ["malmö c", "malmö central", "malmo c", "malmo central", "malmö centralstation"],
    city: "Malmö",
    lat: 55.6092,
    lon: 13.0007,
    radiusKm: 1.2,
    weight: 28,
  },
  {
    id: "triangeln",
    name: "Triangeln",
    aliases: ["triangeln", "triangelns", "malmö triangeln"],
    city: "Malmö",
    lat: 55.5915,
    lon: 13.0009,
    radiusKm: 0.9,
    weight: 22,
  },
  {
    id: "hyllie",
    name: "Hyllie",
    aliases: ["hyllie", "hyllie station", "malmö arena"],
    city: "Malmö",
    lat: 55.5627,
    lon: 12.9756,
    radiusKm: 1.5,
    weight: 26,
  },
  {
    id: "lund-c",
    name: "Lund C",
    aliases: ["lund c", "lund central", "lund centralstation"],
    city: "Lund",
    lat: 55.7058,
    lon: 13.187,
    radiusKm: 1.1,
    weight: 26,
  },
  {
    id: "helsingborg-c",
    name: "Helsingborg C",
    aliases: ["helsingborg c", "helsingborg central", "helsingborg centralstation", "knutpunkten"],
    city: "Helsingborg",
    lat: 56.0442,
    lon: 12.6945,
    radiusKm: 1.2,
    weight: 26,
  },
  {
    id: "kristianstad-c",
    name: "Kristianstad C",
    aliases: ["kristianstad c", "kristianstad central", "kristianstad"],
    city: "Kristianstad",
    lat: 56.0294,
    lon: 14.1567,
    radiusKm: 1.2,
    weight: 20,
  },
  {
    id: "hassleholm-c",
    name: "Hässleholm C",
    aliases: ["hässleholm c", "hässleholm central", "hässleholm", "hassleholm"],
    city: "Hässleholm",
    lat: 56.1578,
    lon: 13.7664,
    radiusKm: 1.1,
    weight: 20,
  },
  {
    id: "landskrona",
    name: "Landskrona",
    aliases: ["landskrona", "landskrona station"],
    city: "Landskrona",
    lat: 55.8705,
    lon: 12.8302,
    radiusKm: 1.2,
    weight: 18,
  },
  {
    id: "angelholm",
    name: "Ängelholm",
    aliases: ["ängelholm", "angelholm", "ängelholm station"],
    city: "Ängelholm",
    lat: 56.2465,
    lon: 12.8634,
    radiusKm: 1.1,
    weight: 16,
  },
  {
    id: "ystad",
    name: "Ystad",
    aliases: ["ystad", "ystad station"],
    city: "Ystad",
    lat: 55.4295,
    lon: 13.8204,
    radiusKm: 1.1,
    weight: 16,
  },
  {
    id: "trelleborg",
    name: "Trelleborg",
    aliases: ["trelleborg", "trelleborg central"],
    city: "Trelleborg",
    lat: 55.3752,
    lon: 13.1569,
    radiusKm: 1.1,
    weight: 16,
  },
  {
    id: "eslov",
    name: "Eslöv",
    aliases: ["eslöv", "eslov"],
    city: "Eslöv",
    lat: 55.8392,
    lon: 13.3039,
    radiusKm: 1.0,
    weight: 14,
  },
  {
    id: "cph-airport",
    name: "Köpenhamns flygplats",
    aliases: ["köpenhamns flygplats", "copenhagen airport", "cph airport", "kastrup", "cph"],
    city: "Kastrup",
    lat: 55.618,
    lon: 12.656,
    radiusKm: 2.5,
    weight: 24,
  },
];

/** Städer utan specifik station — centrum för karta. */
const CITY_COORDS = {
  Malmö: { lat: 55.605, lon: 13.0038 },
  Lund: { lat: 55.7047, lon: 13.191 },
  Helsingborg: { lat: 56.0465, lon: 12.6945 },
  Kristianstad: { lat: 56.0294, lon: 14.1567 },
  Hässleholm: { lat: 56.1589, lon: 13.7664 },
  Landskrona: { lat: 55.8705, lon: 12.8302 },
  Trelleborg: { lat: 55.3752, lon: 13.1569 },
  Ystad: { lat: 55.4295, lon: 13.8204 },
  Eslöv: { lat: 55.8392, lon: 13.3039 },
  Höör: { lat: 55.9344, lon: 13.5422 },
  Ängelholm: { lat: 56.2428, lon: 12.8622 },
  Simrishamn: { lat: 55.5566, lon: 14.3503 },
  Staffanstorp: { lat: 55.6425, lon: 13.2075 },
  Kävlinge: { lat: 55.792, lon: 13.1102 },
  Lomma: { lat: 55.6726, lon: 13.069 },
  Vellinge: { lat: 55.4636, lon: 13.0197 },
  Markaryd: { lat: 56.4615, lon: 13.5964 },
  Bromölla: { lat: 56.0754, lon: 14.4695 },
  Höganäs: { lat: 56.1997, lon: 12.557 },
  Halmstad: { lat: 56.6745, lon: 12.857 },
  Karlskrona: { lat: 56.1612, lon: 15.5869 },
  Växjö: { lat: 56.8777, lon: 14.8091 },
  Älmhult: { lat: 56.5515, lon: 14.1362 },
};

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

function findHubsInText(text) {
  const t = String(text || "").toLowerCase();
  const hits = [];
  for (const hub of HUBS) {
    if (hub.aliases.some((a) => t.includes(a))) hits.push(hub);
  }
  return hits;
}

function resolvePlaceCoords(name) {
  if (!name) return null;
  const key = String(name).trim();
  const lower = key.toLowerCase();
  const hub = HUBS.find(
    (h) =>
      h.name.toLowerCase() === lower ||
      h.aliases.includes(lower) ||
      h.city.toLowerCase() === lower
  );
  if (hub) {
    return {
      name: hub.name,
      lat: hub.lat,
      lon: hub.lon,
      hubId: hub.id,
      isHub: true,
      city: hub.city,
      radiusKm: hub.radiusKm,
    };
  }
  const city = CITY_COORDS[key] || CITY_COORDS[Object.keys(CITY_COORDS).find((c) => c.toLowerCase() === lower)];
  if (city) {
    return {
      name: key,
      lat: city.lat,
      lon: city.lon,
      hubId: null,
      isHub: false,
      city: key,
      radiusKm: 3,
    };
  }
  return null;
}

function enrichPlaceStats(placeStats = []) {
  return placeStats
    .filter((p) => {
      const n = String(p.name || "");
      // Kartan ska visa orter/stationer — inte vägnr som E4 / Väg 123
      if (/^E\d/i.test(n)) return false;
      if (/^väg\s/i.test(n)) return false;
      if (/^rv\s?\d/i.test(n)) return false;
      return true;
    })
    .map((p) => {
      const geo = resolvePlaceCoords(p.name);
      return {
        ...p,
        lat: geo?.lat ?? null,
        lon: geo?.lon ?? null,
        isHub: Boolean(geo?.isHub),
        hubId: geo?.hubId || null,
        radiusKm: geo?.radiusKm ?? 3,
      };
    });
}

function distanceToPlaceKm(lat, lon, placeName) {
  const geo = resolvePlaceCoords(placeName);
  if (!geo || lat == null || lon == null) return null;
  return haversineKm(lat, lon, geo.lat, geo.lon);
}

function filterPlacesByDistance(placeStats, { lat, lon, maxKm = 25 } = {}) {
  if (lat == null || lon == null) return placeStats;
  return placeStats
    .map((p) => {
      const d = p.lat != null ? haversineKm(lat, lon, p.lat, p.lon) : distanceToPlaceKm(lat, lon, p.name);
      return { ...p, distanceKm: d == null ? null : Math.round(d * 10) / 10 };
    })
    .filter((p) => p.distanceKm == null || p.distanceKm <= maxKm)
    .sort((a, b) => (a.distanceKm ?? 999) - (b.distanceKm ?? 999));
}

module.exports = {
  HUBS,
  CITY_COORDS,
  haversineKm,
  findHubsInText,
  resolvePlaceCoords,
  enrichPlaceStats,
  distanceToPlaceKm,
  filterPlacesByDistance,
};
