const { classifyMode } = require("./mode");

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

  if (mode === "train") {
    if (serious) {
      return { mode, severityTier: "line_paused", score: Math.max(taxi.score, 85), confidence: "high" };
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
