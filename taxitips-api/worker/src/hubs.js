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

  // National rollout. Trafiklab's alerts carry stop_ids we cannot resolve
  // (different id space -- see docs/data-sources.md), so a place name in the
  // free text is the ONLY way most alerts get a coordinate. With only Skåne
  // towns listed, every alert from the other 14 operators scored a real
  // severity but landed with lat/lon = null: invisible on the map, and
  // reachable by a driver only through the region fallback.
  //
  // City centres, not stations: precise enough to tell a driver which town,
  // honest about not knowing which platform.
  Stockholm: { lat: 59.3293, lon: 18.0686 },
  Solna: { lat: 59.36, lon: 18.0 },
  Södertälje: { lat: 59.1955, lon: 17.6252 },
  Nacka: { lat: 59.3105, lon: 18.1637 },
  Sundbyberg: { lat: 59.3612, lon: 17.9713 },
  Täby: { lat: 59.4439, lon: 18.0687 },
  Norrtälje: { lat: 59.7574, lon: 18.7053 },
  Uppsala: { lat: 59.8586, lon: 17.6389 },
  Enköping: { lat: 59.6358, lon: 17.0776 },
  Göteborg: { lat: 57.7089, lon: 11.9746 },
  Mölndal: { lat: 57.6554, lon: 12.0134 },
  Kungsbacka: { lat: 57.4874, lon: 12.0761 },
  Borås: { lat: 57.721, lon: 12.9401 },
  Trollhättan: { lat: 58.2837, lon: 12.2886 },
  Uddevalla: { lat: 58.3498, lon: 11.9424 },
  Skövde: { lat: 58.3912, lon: 13.8452 },
  Linköping: { lat: 58.4109, lon: 15.6216 },
  Norrköping: { lat: 58.5877, lon: 16.1924 },
  Motala: { lat: 58.5371, lon: 15.0364 },
  Jönköping: { lat: 57.7826, lon: 14.1618 },
  Nässjö: { lat: 57.6531, lon: 14.6963 },
  Värnamo: { lat: 57.1866, lon: 14.0416 },
  Kalmar: { lat: 56.6634, lon: 16.3566 },
  Oskarshamn: { lat: 57.2646, lon: 16.4487 },
  Västervik: { lat: 57.7577, lon: 16.6373 },
  Nybro: { lat: 56.7444, lon: 15.9083 },
  Karlstad: { lat: 59.3793, lon: 13.5036 },
  Kristinehamn: { lat: 59.3097, lon: 14.1073 },
  Arvika: { lat: 59.6547, lon: 12.5911 },
  Örebro: { lat: 59.2741, lon: 15.2066 },
  Karlskoga: { lat: 59.3266, lon: 14.5241 },
  Västerås: { lat: 59.6099, lon: 16.5448 },
  Köping: { lat: 59.5133, lon: 15.9927 },
  Eskilstuna: { lat: 59.3717, lon: 16.5098 },
  Nyköping: { lat: 58.7531, lon: 17.0086 },
  Falun: { lat: 60.6065, lon: 15.6355 },
  Borlänge: { lat: 60.4858, lon: 15.4371 },
  Mora: { lat: 61.0055, lon: 14.5378 },
  Gävle: { lat: 60.6749, lon: 17.1413 },
  Sandviken: { lat: 60.6172, lon: 16.7759 },
  Hudiksvall: { lat: 61.7288, lon: 17.1058 },
  Sundsvall: { lat: 62.3908, lon: 17.3069 },
  Härnösand: { lat: 62.6323, lon: 17.9379 },
  Örnsköldsvik: { lat: 63.29, lon: 18.7156 },
  Östersund: { lat: 63.1792, lon: 14.6357 },
  Umeå: { lat: 63.8258, lon: 20.263 },
  Skellefteå: { lat: 64.7507, lon: 20.9528 },
  Luleå: { lat: 65.5848, lon: 22.1547 },
  Piteå: { lat: 65.3172, lon: 21.4794 },
  Kiruna: { lat: 67.8558, lon: 20.2253 },
  Visby: { lat: 57.6348, lon: 18.2948 },
  Karlshamn: { lat: 56.1706, lon: 14.8626 },
  Varberg: { lat: 57.1057, lon: 12.2508 },
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
