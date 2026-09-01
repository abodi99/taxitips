const { isRoadAlert } = require("./taxiRelevance");

/**
 * Classifies which transport mode a disruption concerns. This is an explicit,
 * first-class field -- not a side effect buried in scoring -- because a paused
 * train LINE is a categorically different severity than one delayed bus, and both
 * need to be distinguishable before scoring, not folded into the same bucket.
 *
 * Route type (GTFS static route_type: tram/subway/rail/bus/...) would be the
 * structurally correct signal here, but the worker only consumes the GTFS-RT
 * realtime feed (see trafiklab.js), which does not carry route_type -- that field
 * only exists in a separate static GTFS dataset, joined by route_id. Until that
 * static feed is ingested (a real follow-up, not done here), fall back to keyword
 * matching on the alert text/route ids. Returns "unknown" rather than guessing when
 * neither train nor bus keywords match -- honest uncertainty over fake precision.
 */
function classifyMode(alert) {
  if (isRoadAlert(alert)) return "road";

  const text = `${alert.header || ""} ${alert.description || ""} ${(alert.routes || []).join(" ")}`.toLowerCase();

  // Swedish word forms (tåget/tågen/tågets, bussen/bussar/...) attach suffixes
  // directly to the stem, so match on a leading word-boundary only, not a
  // trailing one -- \btåg\b would miss "Tåget är inställt" entirely.
  if (/\b(tåg|påga|pågatåg|öresundståg|krösatåg|kustpilen|pendeltåg|spårvagn|spårfel|spårarbete)/.test(text)) {
    return "train";
  }
  if (/\b(buss|regionbuss|citybuss|stadsbuss|ersättningsbuss)/.test(text)) {
    return "bus";
  }
  return "unknown";
}

module.exports = { classifyMode };
