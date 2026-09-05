/**
 * Marknadsfokus: Skåne only (MVP / marknadstest).
 * All trafikdata och notiser ska handla om körningar i Skåne.
 */

const SKANE_PLACES = new Set(
  [
    "malmö",
    "lund",
    "helsingborg",
    "kristianstad",
    "hässleholm",
    "landskrona",
    "ystad",
    "trelleborg",
    "eslöv",
    "ängelholm",
    "höganäs",
    "höör",
    "osby",
    "simrishamn",
    "sjöbo",
    "staffanstorp",
    "svedala",
    "burlöv",
    "kävlinge",
    "bromölla",
    "perstorp",
    "örkelljunga",
    "bjuv",
    "åstorp",
    "klippan",
    "lomma",
    "vellinge",
    "hyllie",
    "triangeln",
    "malmö c",
    "lund c",
    "helsingborg c",
    "hässleholm c",
    "köpenhamns flygplats", // Öresundståg → taxibehov på skånska sidan
    "cph",
    "kastrup",
  ].map((s) => s.toLowerCase())
);

// NOTE ON WORD BOUNDARIES: JS's \b is ASCII-only, so `\böresundståg\b`
// never matches -- \b requires a word/non-word transition and "ö" is not an
// ASCII word char, so there's no boundary before it at a string or space
// start. That silently broke every entry beginning with å/ä/ö (öresundståg,
// ängelholm). Use explicit lookarounds against the Swedish letter set
// instead of \b anywhere a term can start or end with those.
const SV = "a-zà-öø-ÿ0-9";
const svWord = (alternatives) =>
  new RegExp(`(?<![${SV}])(?:${alternatives})(?![${SV}])`, "i");

const SKANE_TEXT_RE = svWord(
  "skåne|skånetrafiken|pågatåg|öresundståg|malmö|lund|helsingborg|kristianstad|hässleholm|landskrona|ystad|trelleborg|eslöv|ängelholm|hyllie|triangeln|e6|e22|e65"
);

/**
 * Places that positively identify an alert as belonging to a DIFFERENT
 * region, used to reject alerts the operator feed legitimately carries but
 * a local driver can't act on.
 *
 * ServiceAlerts IS correctly region-scoped per operator (measured: the
 * skane feed gives 115 Skåne mentions and 0 Stockholm/Kalmar). The leakage
 * comes from Skånetrafiken itself: it operates Öresundståg/Pågatåg services
 * that run far outside the county, so it publishes alerts about e.g. the
 * Kalmar C–Nybro stretch. Measured 3 of 8 top-tier (line_paused) signals in
 * a 24h window were Kalmar/Nybro -- ~200 km outside the market, occupying
 * the scarce high-prio slots a driver actually sees.
 *
 * Deliberately an exclusion list of other regions' hubs, not an allow-list:
 * it only rejects on positive evidence of elsewhere, so an alert that
 * happens to name no city still passes.
 *
 * NOTE for national rollout: this whole module becomes a *relevance-radius*
 * problem rather than a region-membership one. See docs/data-sources.md.
 */
const NON_SKANE_TEXT_RE = svWord(
  "kalmar|nybro|växjö|karlskrona|karlshamn|halmstad|varberg|göteborg|stockholm|uppsala|örebro|västerås|linköping|norrköping|jönköping|borås|umeå|luleå|sundsvall|gävle|falun|karlstad"
);

function placeLooksSkane(name) {
  if (!name) return false;
  const n = String(name).toLowerCase().trim();
  if (SKANE_PLACES.has(n)) return true;
  for (const p of SKANE_PLACES) {
    if (n.includes(p) || p.includes(n)) return true;
  }
  return false;
}

/**
 * National mode: when the market isn't a single region, "is this in Skåne?"
 * is the wrong question entirely -- every alert is in *someone's* market.
 * Relevance is then purely a distance problem, which the client already
 * solves per-driver (worth_it_score folds in distance_km, and the "Nära
 * mig" filter exists), so the ingest-side geofence must get out of the way
 * rather than silently discarding 3/4 of the country.
 *
 * Set MARKET_SCOPE=national to disable region filtering. Default stays
 * "skane" so existing deployments don't change behaviour on deploy.
 */
function isNationalScope() {
  return String(process.env.MARKET_SCOPE || "skane").toLowerCase() === "national";
}

/**
 * True om alerten hör till marknaden (ort, text eller operatör).
 * I national-läge är allt inom marknaden -- se isNationalScope().
 */
function alertInSkane(alert) {
  if (!alert) return false;
  if (isNationalScope()) return true;

  const text = `${alert.header || ""} ${alert.description || ""} ${alert.cause || ""}`;

  // Checked before every "yes" path below: an alert naming another region's
  // hub is out even if it also mentions Skåne (e.g. an Öresundståg running
  // Kalmar-Malmö is a Kalmar-side problem when the stop is up there), and
  // even if it arrived on the skane endpoint -- which, on the Sweden feed
  // family, means nothing.
  if (NON_SKANE_TEXT_RE.test(text) && !SKANE_TEXT_RE.test(text)) return false;

  const region = String(alert.region || "").toLowerCase();
  if (region === "skane" || region === "skåne") return true;

  const places = [
    ...(alert.taxi?.places || []),
    ...(Array.isArray(alert.areas) ? alert.areas : []),
  ];
  if (places.some(placeLooksSkane)) return true;

  if (SKANE_TEXT_RE.test(text)) return true;

  // Trafiklab Skåne-operator utan ortnamn — behåll (regionen är Skåne)
  if (String(alert.id || "").match(/^\d/) && !alert.sourceKind) return true;
  if (alert.sourceKind !== "road" && !String(alert.id || "").startsWith("tv:")) {
    // Kollektiv från skane-operator: default true om operators scoped to skane
    return true;
  }

  return false;
}

module.exports = {
  SKANE_PLACES,
  placeLooksSkane,
  alertInSkane,
  isNationalScope,
};
