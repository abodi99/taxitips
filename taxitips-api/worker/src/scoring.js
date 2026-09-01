const { classifyMode } = require("./mode");

/**
 * A single cancelled train departure is NOT the same thing as a whole line being
 * down -- if another train runs a few minutes later, nobody is actually stranded.
 * Trafiklab's real alert text distinguishes these cases explicitly:
 *   - "Vi hänvisar till övriga avgångar" (other departures exist) -> one train
 *     cancelled, service otherwise continuing. Not a strong stranded-passenger signal.
 *   - "Ersättningsbuss" / "Buss ersätter" -> cancelled but a replacement is running.
 *     Some inconvenience, but not "no way to get anywhere."
 *   - "Stopp i tågtrafiken" / "ingen trafik" / "inga avgångar" with NO mention of an
 *     alternative -> genuinely no service on the line. This is the real
 *     stranded-passenger case a taxi driver should treat as high-value.
 * Without GTFS static timetable data (next scheduled departure), this is the best
 * available signal from the realtime feed's own text -- verified against real
 * alerts in this session, not guessed.
 */
function hasStatedAlternative(text) {
  return /(övriga avgångar|ersättningsbuss|ersättningstrafik|buss ersätter|tågbyte)/i.test(text);
}

function isWholeLineStop(text) {
  return /(stopp i tågtrafiken|ingen trafik|inga avgångar|trafikstopp)/i.test(text);
}

/**
 * Maps a scored alert (taxi.level/serious/mediumish, already computed by
 * taxiRelevance.js's scoreAlert/scoreRoadAlert) plus its transport mode into a
 * severity_tier -- the axis that distinguishes "a whole train line is paused" from
 * "one bus is running late," which today's flat serious/mediumish buckets do not.
 *
 * Reuses the existing tuned scoring (score/level) as the "how bad does this sound"
 * signal; classifyMode() is the new "which mode" signal. severity_tier is their
 * cross product, and adjusts the score band to reflect that a train line pause
 * strands categorically more people than a single delayed bus.
 */
function classifySeverity(alert, taxi) {
  const mode = classifyMode(alert);

  if (!taxi || taxi.level === "ignore") {
    return { mode, severityTier: "ignore", score: 0, confidence: "medium" };
  }

  if (mode === "road") {
    // Road severity is already well-tuned in scoreRoadAlert (accident/closure/
    // roadwork tiers) -- carry it through as-is, just labeled for the new column.
    const tierByLevel = { high: "road_accident_or_closure", medium: "road_work_or_queue", low: "road_work" };
    return {
      mode,
      severityTier: tierByLevel[taxi.level] || "road_unclassified",
      score: taxi.score,
      confidence: "medium",
    };
  }

  const serious = taxi.serious === true;
  const mediumish = taxi.mediumish === true;
  const text = `${alert.header || ""} ${alert.description || ""}`;

  if (mode === "train") {
    if (serious) {
      if (isWholeLineStop(text) && !hasStatedAlternative(text)) {
        // Genuinely no service on the line -- the real stranded-passenger case.
        return { mode, severityTier: "line_paused", score: Math.max(taxi.score, 85), confidence: "high" };
      }
      if (hasStatedAlternative(text)) {
        // One departure cancelled, but the alert itself names a next train or a
        // replacement bus -- treat as a single vehicle issue, not a line pause,
        // since most passengers just wait for the next departure.
        return { mode, severityTier: "vehicle_cancelled", score: Math.min(taxi.score, 55), confidence: "medium" };
      }
      // Serious language, but neither signal is explicit in the text -- can't
      // confidently tell whether this is a full stop or a single cancellation.
      // Score conservatively and flag the uncertainty rather than assuming the
      // worse (and more score-inflating) case.
      return { mode, severityTier: "line_paused", score: Math.max(taxi.score, 70), confidence: "low" };
    }
    if (mediumish) {
      return { mode, severityTier: "line_delayed", score: Math.min(taxi.score, 45), confidence: "high" };
    }
  }

  if (mode === "bus") {
    if (serious) {
      // Lower ceiling than a train line pause -- one bus route going down strands
      // far fewer people than a whole train line stopping.
      return { mode, severityTier: "vehicle_cancelled", score: Math.min(taxi.score, 60), confidence: "high" };
    }
    if (mediumish) {
      // Deliberately low -- this is the "bus running 5 min late" noise that should
      // rank near the bottom of what a driver sees, not alongside real disruptions.
      return { mode, severityTier: "vehicle_delayed", score: Math.min(taxi.score, 25), confidence: "high" };
    }
  }

  // mode === "unknown", or a shape that matched neither serious nor mediumish
  // (shouldn't normally reach here since scoreAlert would have returned "ignore"
  // first, but fall back honestly rather than mis-tiering).
  return { mode, severityTier: "disruption_unclassified", score: taxi.score, confidence: "low" };
}

module.exports = { classifySeverity };
