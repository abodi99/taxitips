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

const SKANE_TEXT_RE =
  /\b(skåne|skånetrafiken|pågatåg|öresundståg|malmö|lund|helsingborg|kristianstad|hässleholm|landskrona|ystad|trelleborg|eslöv|ängelholm|hyllie|triangeln|e6|e22|e65)\b/i;

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
 * True om alerten hör till Skåne-marknaden (ort, text eller Skånetrafiken).
 */
function alertInSkane(alert) {
  if (!alert) return false;
  const region = String(alert.region || "").toLowerCase();
  if (region === "skane" || region === "skåne") return true;

  const places = [
    ...(alert.taxi?.places || []),
    ...(Array.isArray(alert.areas) ? alert.areas : []),
  ];
  if (places.some(placeLooksSkane)) return true;

  const text = `${alert.header || ""} ${alert.description || ""} ${alert.cause || ""}`;
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
};
