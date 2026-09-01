/**
 * SMHI point-forecast weather data (SNOW1g, replaced the deprecated PMP3g API on
 * 2026-03-31 -- see https://opendata.smhi.se/apidocs/metfcst/). Free, keyless,
 * one HTTP call per (lon, lat) point rounded to a coarse grid.
 *
 * We do NOT fetch weather per-alert (a poll cycle can carry 100+ live alerts --
 * that would be 100+ SMHI calls every minute for no real gain, since weather
 * doesn't vary meaningfully across a few km). Instead we fetch a small, fixed
 * set of representative points covering the region actually being polled
 * (see REGION_POINTS) once per poll cycle, and each alert looks up the nearest
 * cached point by straight-line distance. This keeps SMHI load flat regardless
 * of how many disruptions are live.
 */

// One point per major Skåne population center. Coarse by design -- weather at
// this resolution is "is it raining in the Malmö area" not neighborhood-precise,
// which is all a taxi-demand signal needs.
const REGION_POINTS = [
  { name: "Malmö", lat: 55.605, lon: 13.0 },
  { name: "Lund", lat: 55.7047, lon: 13.191 },
  { name: "Helsingborg", lat: 56.0465, lon: 12.6945 },
  { name: "Kristianstad", lat: 56.0294, lon: 14.1567 },
  { name: "Hässleholm", lat: 56.1589, lon: 13.7668 },
  { name: "Ystad", lat: 55.4295, lon: 13.82 },
  { name: "Trelleborg", lat: 55.3753, lon: 13.1569 },
];

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

async function fetchPointForecast(lat, lon) {
  const url = `https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point/lon/${lon}/lat/${lat}/data.json`;
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`SMHI ${res.status} for (${lat},${lon})`);
  }
  return res.json();
}

/**
 * Reduce a raw SMHI response to just the current hour's reading (index 0 of
 * timeSeries is always the nearest upcoming/current hour) and the handful of
 * fields the scoring layer actually uses. We don't need historical/forecast
 * hours for a live demand signal, and don't need the ~20 other SMHI fields
 * (cloud layers, pressure, etc.) at all.
 */
function summarize(raw, point) {
  const entry = raw?.timeSeries?.[0];
  if (!entry) return null;
  const d = entry.data || {};
  return {
    point: point.name,
    lat: point.lat,
    lon: point.lon,
    observedAt: entry.time,
    temperatureC: d.air_temperature ?? null,
    windSpeedMs: d.wind_speed ?? null,
    windGustMs: d.wind_speed_of_gust ?? null,
    precipitationMmPerH: d.precipitation_amount_mean ?? null,
    precipitationProbabilityPct: d.probability_of_precipitation ?? null,
    thunderstormProbabilityPct: d.thunderstorm_probability ?? null,
    frozenPrecipitationProbabilityPct: d.probability_of_frozen_precipitation ?? null,
    symbolCode: d.symbol_code ?? null,
  };
}

/** Fetches all region points. Failures on individual points are logged and
 * skipped rather than failing the whole batch -- weather is an enhancement
 * signal, not a required one; a driver still gets the traffic disruption
 * itself even if SMHI is briefly unreachable. */
async function fetchRegionWeather() {
  const results = [];
  for (const point of REGION_POINTS) {
    try {
      const raw = await fetchPointForecast(point.lat, point.lon);
      const summary = summarize(raw, point);
      if (summary) results.push(summary);
    } catch (err) {
      console.error("[smhi]", point.name, err.message);
    }
  }
  return results;
}

/** Given a location and the batch fetched by fetchRegionWeather, returns the
 * nearest point's summary, or null if the batch is empty (e.g. SMHI was fully
 * unreachable this cycle). */
function nearestWeather(lat, lon, regionWeather) {
  if (!lat || !lon || !regionWeather.length) return null;
  let best = null;
  let bestDist = Infinity;
  for (const w of regionWeather) {
    const dist = haversineKm(lat, lon, w.lat, w.lon);
    if (dist < bestDist) {
      bestDist = dist;
      best = w;
    }
  }
  return best;
}

/** True if conditions at a point plausibly push people toward taxis instead of
 * walking/cycling/waiting outside for transit: real rain/snow, high wind, or a
 * thunderstorm risk. Deliberately conservative thresholds -- light drizzle or
 * a light breeze isn't a taxi-demand signal, only weather someone would
 * actively avoid being outside in. */
function isAdverseWeather(weather) {
  if (!weather) return false;
  const heavyPrecip = (weather.precipitationMmPerH ?? 0) >= 1.0 && (weather.precipitationProbabilityPct ?? 0) >= 40;
  const highWind = (weather.windGustMs ?? weather.windSpeedMs ?? 0) >= 12;
  const thunder = (weather.thunderstormProbabilityPct ?? 0) >= 30;
  const freezing = (weather.temperatureC ?? 99) <= 0 && (weather.frozenPrecipitationProbabilityPct ?? 0) >= 40;
  return heavyPrecip || highWind || thunder || freezing;
}

function describeWeather(weather) {
  if (!weather) return null;
  const bits = [];
  if ((weather.precipitationMmPerH ?? 0) >= 1.0 && (weather.precipitationProbabilityPct ?? 0) >= 40) {
    bits.push((weather.frozenPrecipitationProbabilityPct ?? 0) >= 40 ? "snöfall" : "regn");
  }
  if ((weather.windGustMs ?? weather.windSpeedMs ?? 0) >= 12) bits.push("hård vind");
  if ((weather.thunderstormProbabilityPct ?? 0) >= 30) bits.push("åska");
  if ((weather.temperatureC ?? 99) <= 0 && (weather.frozenPrecipitationProbabilityPct ?? 0) >= 40) {
    bits.push("halka/kyla");
  }
  return bits.length ? bits.join(", ") : null;
}

module.exports = {
  REGION_POINTS,
  fetchPointForecast,
  fetchRegionWeather,
  nearestWeather,
  isAdverseWeather,
  describeWeather,
  haversineKm,
};
