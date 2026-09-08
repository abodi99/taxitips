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

  // A source that states the mode outright beats any amount of guessing at
  // Swedish prose. SL publishes transport_mode per affected line (BUS/METRO/
  // TRAIN/TRAM/SHIP), which is exactly the structural signal the comment
  // above wishes for -- so use it when present. `metro` and `tram` are new
  // values the keyword path could never produce; scoring.js folds them into
  // the train branch, since a stopped metro line strands people the same way.
  if (alert.modeHint) return alert.modeHint;

  // Operators append boilerplate that names OTHER modes in passing.
  // Dalatrafik ends every message with "Har ni tider att passa, anslutande
  // tåg eller bussar..." -- that single word made 7 of 7 bus disruptions
  // classify as train, which then let them reach the train severity branch
  // and score up to 70 ("line_paused") for a delayed bus. Strip the known
  // boilerplate before any keyword vote.
  const boilerplate =
    /(anslutande tåg eller buss\w*|se .{0,20}app(en)? eller reseplanerare|för beräknad avgångstid[^.]*\.|läs mer på \S+)/gi;
  const header = String(alert.header || "").toLowerCase();
  const body = String(alert.description || "")
    .toLowerCase()
    .replace(boilerplate, " ");
  const text = `${header} ${body} ${(alert.routes || []).join(" ")}`.toLowerCase();

  // Swedish word forms (tåget/tågen/tågets, bussen/bussar/...) attach suffixes
  // directly to the stem, so match on a leading word-boundary only, not a
  // trailing one -- \btåg\b would miss "Tåget är inställt" entirely.
  const TRAIN_RE =
    /(?<![a-zà-öø-ÿ0-9])(tåg|påga|pågatåg|öresundståg|krösatåg|kustpilen|pendeltåg|spårvagn|spårfel|spårarbete)/;
  const BUS_RE =
    /(?<![a-zà-öø-ÿ0-9])(buss|regionbuss|citybuss|stadsbuss|ersättningsbuss)/;

  // A bus mentioned as REPLACEMENT means the broken thing is rail: "Inställd
  // - Buss ersätter" is a cancelled train, and calling it a bus would drop it
  // out of the rail severity branch that exists precisely for stranded
  // passengers. Check this before the header-wins rule below.
  const REPLACEMENT_RE =
    /(ersättningsbuss|buss(ar)? ersätter|ersätter (spårvagn|tåg)|ersättningstrafik)/;
  if (REPLACEMENT_RE.test(`${header} ${body}`)) return "train";

  // The header is what the disruption is ABOUT; the body often mentions the
  // replacement or a connecting service. When the two disagree, trust the
  // header -- "Buss linje 210 ..." is a bus story even if the body says tåg.
  if (BUS_RE.test(header) && !TRAIN_RE.test(header)) return "bus";
  if (TRAIN_RE.test(header) && !BUS_RE.test(header)) return "train";

  if (TRAIN_RE.test(text)) {
    return "train";
  }
  if (BUS_RE.test(text)) {
    return "bus";
  }
  return "unknown";
}

module.exports = { classifyMode };
