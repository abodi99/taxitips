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
