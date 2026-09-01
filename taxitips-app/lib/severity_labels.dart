/// Driver-facing labels for the backend's severity_tier/confidence values.
/// Shared between the compact list card and the full explain panel so the
/// two never drift into saying different things about the same alert.
library;

const severityTierLabels = {
  'line_paused': 'Hela linjen är stoppad',
  'line_delayed': 'Försening på linjen',
  'vehicle_cancelled': 'En avgång inställd (andra avgångar/ersättning finns)',
  'vehicle_delayed': 'En avgång försenad',
  'road_accident_or_closure': 'Olycka eller avstängd väg',
  'road_work_or_queue': 'Vägarbete eller köbildning',
  'road_work': 'Mindre vägarbete',
  'disruption_unclassified': 'Störning (osäker klassificering)',
};

/// Short (card-width) version of the same tiers, for the compact list view.
const severityTierShortLabels = {
  'line_paused': 'Hela linjen stoppad',
  'line_delayed': 'Försening, linjen kör',
  'vehicle_cancelled': 'Enstaka avgång inställd',
  'vehicle_delayed': 'Enstaka avgång försenad',
  'road_accident_or_closure': 'Olycka/avstängning',
  'road_work_or_queue': 'Vägarbete/kö',
  'road_work': 'Vägarbete',
  'disruption_unclassified': 'Osäker bedömning',
};

const confidenceLabels = {
  'high': 'Hög — tydligt i källdatan',
  'medium': 'Medel',
  'low': 'Låg — osäker tolkning av källdatan',
};

/// Driver-facing "how likely are there customers here" read, replacing the
/// raw Worth-It number on the list card. worth_it_score is 0 both when a
/// disruption is genuinely weak AND when it's too far/too close to ending to
/// reach in time -- as a bare number those two cases are indistinguishable
/// and a legitimate 0 reads as "the app is broken". Splitting on severity_tier
/// (how strong the underlying signal is) crossed with whether worth_it_score
/// actually reached 0 (not reachable in time) says which case it is.
enum CustomerLikelihood { high, medium, low }

// Road tiers are deliberately excluded from both sets -- an accident or
// closure delays people already in a car, it doesn't strand pedestrians who'd
// need a taxi. Only transit disruptions (a stopped line, a cancelled vehicle)
// actually leave people without transport, so only those drive "likely
// customers" up. Road incidents fall through to `low` regardless of tier.
const _highSeverityTiers = {'line_paused'};
const _mediumSeverityTiers = {'line_delayed', 'vehicle_cancelled'};

CustomerLikelihood customerLikelihood({
  required String? severityTier,
  required num worthItScore,
}) {
  if (worthItScore <= 0) return CustomerLikelihood.low;
  if (_highSeverityTiers.contains(severityTier)) {
    return CustomerLikelihood.high;
  }
  if (_mediumSeverityTiers.contains(severityTier)) {
    return CustomerLikelihood.medium;
  }
  return CustomerLikelihood.low;
}

const customerLikelihoodLabels = {
  CustomerLikelihood.high: 'Troligt att det finns kunder',
  CustomerLikelihood.medium: 'Möjligt att det finns kunder',
  CustomerLikelihood.low: 'Osannolikt just nu',
};
