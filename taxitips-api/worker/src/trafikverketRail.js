/**
 * Trafikverket rail: cancelled and heavily delayed train departures, nationally.
 *
 * This closes the gap that made the product look regional. Trafiklab's
 * realtime feeds are published per regional authority, and the long-distance
 * train operators -- SJ, Snälltåget, Öresundståg, Mälartåg, Norrtåg, MTR, VR
 * -- publish no realtime feed there at all (verified: every one of those
 * operator paths returns 404). So train disruptions only ever surfaced where
 * a regional authority happened to run its own trains: Skåne, Stockholm and
 * Göteborg. Everywhere else, a cancelled train was invisible.
 *
 * Trafikverket owns the national rail network and publishes every advertised
 * departure, so a single query covers the whole country. Measured live: 63
 * cancelled departures across 23 stations -- Motala, Kungsbacka, Halmstad,
 * Mjölby, Katrineholm, Strängnäs and others no Trafiklab feed reaches.
 *
 * Coverage is genuinely uneven by geography, and that is the data, not a bug:
 * south of Gävle trains run every few minutes, while all of Norrland had 11
 * departures in an 8-hour window (measured at 23:00). An empty map in Luleå
 * at night is correct -- there is no train to be cancelled.
 *
 * A cancelled train is the strongest taxi signal there is: people are already
 * standing on a platform, with luggage, and often no alternative for an hour.
 */

const API_URL = "https://api.trafikinfo.trafikverket.se/v2/data.json";

// How far ahead to look for cancellations.
//
// Three hours suits the south, where trains run every few minutes -- but it
// makes the product look empty north of Gävle, where the line carries a
// handful of departures per DAY. Measured at 23:00: all of Norrland had 11
// departures in the next 8 hours, one of them cancelled (Boden 05:08). At a
// 3h window that cancellation is invisible, and a Luleå driver sees nothing
// at all -- not because the pipeline missed it, but because it hadn't looked
// far enough for a timetable that sparse.
//
// 8 hours covers a night shift. The tip itself is still short-lived: each one
// only becomes visible near its own departure (see VISIBLE_BEFORE_MS), so a
// wider search window does not mean stale tips at the top of the list.
const WINDOW_HOURS = 8;

// A cancellation is only worth showing once it is close enough to act on --
// nobody is standing on the platform six hours early. Tips start when the
// departure is this near, which is what keeps the wider search window honest.
const VISIBLE_BEFORE_MS = 90 * 60 * 1000;

// A delay this size strands people the same way a cancellation does; below it
// they wait on the platform.
const SERIOUS_DELAY_MIN = 30;

async function query(apiKey, xml) {
  const res = await fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "text/xml", "Accept-Encoding": "gzip" },
    body: `<REQUEST><LOGIN authenticationkey="${apiKey}"/>${xml}</REQUEST>`,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`trafikverket-rail ${res.status}: ${body.slice(0, 160)}`);
  }
  const json = await res.json();
  const block = json?.RESPONSE?.RESULT?.[0];
  if (block?.ERROR) {
    throw new Error(`trafikverket-rail: ${JSON.stringify(block.ERROR).slice(0, 160)}`);
  }
  return block || {};
}

/** WKT "POINT (lon lat)" -> {lat, lon}. Note WKT is lon-first. */
function parsePoint(wkt) {
  const m = /POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)/i.exec(String(wkt || ""));
  if (!m) return null;
  const lon = Number(m[1]);
  const lat = Number(m[2]);
  return Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null;
}

/**
 * Station signature ("Cst", "G", "M") -> {name, lat, lon}. ~1000 rows that
 * change when a station is built, so fetched once per process.
 */
let stationCache = null;

async function fetchStations(apiKey) {
  if (stationCache) return stationCache;
  const block = await query(
    apiKey,
    `<QUERY objecttype="TrainStation" namespace="rail.infrastructure" schemaversion="1.5" limit="3000">
       <FILTER><EQ name="Advertised" value="true"/></FILTER>
       <INCLUDE>LocationSignature</INCLUDE>
       <INCLUDE>AdvertisedLocationName</INCLUDE>
       <INCLUDE>Geometry.WGS84</INCLUDE>
     </QUERY>`
  );
  const map = new Map();
  for (const s of block.TrainStation || []) {
    const p = parsePoint(s?.Geometry?.WGS84);
    if (!s?.LocationSignature) continue;
    map.set(s.LocationSignature, {
      name: s.AdvertisedLocationName || s.LocationSignature,
      lat: p?.lat ?? null,
      lon: p?.lon ?? null,
    });
  }
  stationCache = map;
  return map;
}

function minutesLate(announcement) {
  const adv = Date.parse(announcement?.AdvertisedTimeAtLocation || "");
  const est = Date.parse(
    announcement?.EstimatedTimeAtLocation || announcement?.TimeAtLocation || ""
  );
  if (!Number.isFinite(adv) || !Number.isFinite(est)) return 0;
  return Math.round((est - adv) / 60000);
}

/**
 * One departure -> the shared normalized alert shape.
 *
 * Deliberately NOT one alert per train per station: a train cancelled along
 * its whole route would otherwise produce a dozen near-identical tips. The
 * caller groups by station and keeps the earliest departure, so a driver sees
 * "Tåg inställt från Västerås C", once.
 */
function normalizeDeparture(dep, station, delayMin) {
  const stationName = station?.name || dep.LocationSignature;
  const to = (dep.ToLocation || [])[0]?.LocationName || null;
  const train = dep.AdvertisedTrainIdent || "";
  const when = dep.AdvertisedTimeAtLocation;
  const cancelled = dep.Canceled === true;

  const time = when
    ? new Date(when).toLocaleTimeString("sv-SE", {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

  const header = cancelled
    ? `Tåg ${train} ${time} är inställt från ${stationName}`
    : `Tåg ${train} ${time} är ${delayMin} min försenat från ${stationName}`;

  const description = cancelled
    ? `Avgången ${time} från ${stationName}${to ? ` mot ${to}` : ""} är inställd. ` +
      `Resenärer står kvar på perrongen.`
    : `Avgången ${time} från ${stationName}${to ? ` mot ${to}` : ""} är försenad ` +
      `${delayMin} minuter.`;

  return {
    // Station + train + departure time is stable across polls, so re-polling
    // updates the same row instead of duplicating it.
    id: `tvr:${dep.LocationSignature}:${train}:${when}`,
    header,
    description,
    cause: null,
    effect: null,
    areas: [stationName],
    routes: train ? [String(train)] : [],
    stops: [dep.LocationSignature],
    url: null,
    // Not the departure time itself: the tip becomes relevant shortly before
    // it, when people are actually arriving at the platform. Never earlier
    // than now, so a cancellation found mid-window doesn't appear backdated.
    active_from: Math.max(
      Date.now(),
      (Date.parse(when) || Date.now()) - VISIBLE_BEFORE_MS
    ),
    // A stranded platform clears within about an hour, whether or not the
    // operator says so. Without an end time these would sit at the top of the
    // list all day.
    active_to: (Date.parse(when) || Date.now()) + 60 * 60 * 1000,
    // Kept so the card can say when the cancelled train was due, distinct
    // from when the tip is worth acting on.
    departure_at: Date.parse(when) || null,
    source: "trafikverket_rail",
    region: "rail",
    lat: station?.lat ?? null,
    lon: station?.lon ?? null,
    // Trafikverket states cancellation structurally -- no regex needed, and
    // no chance of the "inställt vs inställd" gap that hid these before.
    modeHint: "train",
  };
}

async function fetchRailDisruptions({
  apiKey = process.env.TRAFIKVERKET_API_KEY,
  now = Date.now(),
} = {}) {
  if (!apiKey || apiKey === "mock") {
    return { alerts: [], source: "trafikverket_rail", skipped: "no api key" };
  }

  const stations = await fetchStations(apiKey);

  const block = await query(
    apiKey,
    `<QUERY objecttype="TrainAnnouncement" namespace="rail.trafficinfo" schemaversion="1.9" limit="800">
       <FILTER>
         <AND>
           <EQ name="ActivityType" value="Avgang"/>
           <EQ name="Advertised" value="true"/>
           <GT name="AdvertisedTimeAtLocation" value="$now"/>
           <LT name="AdvertisedTimeAtLocation" value="$dateadd(${WINDOW_HOURS}:00:00)"/>
           <OR>
             <EQ name="Canceled" value="true"/>
             <EXISTS name="EstimatedTimeAtLocation" value="true"/>
           </OR>
         </AND>
       </FILTER>
       <INCLUDE>AdvertisedTrainIdent</INCLUDE>
       <INCLUDE>LocationSignature</INCLUDE>
       <INCLUDE>AdvertisedTimeAtLocation</INCLUDE>
       <INCLUDE>EstimatedTimeAtLocation</INCLUDE>
       <INCLUDE>Canceled</INCLUDE>
       <INCLUDE>ToLocation</INCLUDE>
     </QUERY>`
  );

  const departures = block.TrainAnnouncement || [];

  // One tip per station AND one per train.
  //
  // A cancelled train is announced at every stop it would have served, so
  // train 7182 alone produced five near-identical tips down the Norrbotten
  // line -- Luleå, Notviken, Sunderby sjukhus, Boden, Kalix. That is one
  // event, and five cards for it buries everything else in the list.
  //
  // Keep the FIRST station on each train's route: that is where the fullest
  // platform is, and where a taxi is most likely to be wanted. Passengers
  // further down the line mostly never boarded.
  const firstStopByTrain = new Map();
  for (const dep of departures) {
    if (dep.Canceled !== true) continue;
    const train = dep.AdvertisedTrainIdent;
    const t = Date.parse(dep.AdvertisedTimeAtLocation);
    if (!train || !Number.isFinite(t)) continue;
    const prev = firstStopByTrain.get(train);
    if (!prev || t < prev) firstStopByTrain.set(train, t);
  }

  const bestByStation = new Map();
  for (const dep of departures) {
    const cancelled = dep.Canceled === true;
    const delay = minutesLate(dep);
    if (!cancelled && delay < SERIOUS_DELAY_MIN) continue;

    // Only the train's first cancelled stop; the rest are the same event.
    if (cancelled) {
      const first = firstStopByTrain.get(dep.AdvertisedTrainIdent);
      if (first != null && Date.parse(dep.AdvertisedTimeAtLocation) !== first) continue;
    }

    const sig = dep.LocationSignature;
    if (!sig) continue;
    const prev = bestByStation.get(sig);
    // A cancellation outranks a delay; otherwise the earliest departure wins,
    // because that is the platform with people on it right now.
    const better =
      !prev ||
      (cancelled && !prev.cancelled) ||
      (cancelled === prev.cancelled &&
        Date.parse(dep.AdvertisedTimeAtLocation) < Date.parse(prev.dep.AdvertisedTimeAtLocation));
    if (better) bestByStation.set(sig, { dep, cancelled, delay });
  }

  const alerts = [];
  for (const [sig, { dep, delay }] of bestByStation) {
    alerts.push(normalizeDeparture(dep, stations.get(sig), delay));
  }

  return {
    alerts,
    source: "trafikverket_rail",
    received: departures.length,
    stations: alerts.length,
  };
}

module.exports = {
  fetchRailDisruptions,
  fetchStations,
  normalizeDeparture,
  parsePoint,
  minutesLate,
};
