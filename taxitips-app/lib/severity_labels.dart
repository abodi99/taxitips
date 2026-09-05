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

/// A reachable, strongly-scored cancellation is worth driving to, not just
/// "möjligt" -- vehicle_cancelled spans both a cancelled train that strands
/// a platform full of people (score ~72) and much weaker single-departure
/// cases, so let the tier's own score lift it. Matches the worker's push
/// gate (fcmPush.js NOTIFY_SCORE_FLOOR) so what buzzes the phone and what
/// reads "Troligt" on the card stay the same judgement.
const _highScoreFloor = 50;

CustomerLikelihood customerLikelihood({
  required String? severityTier,
  required num worthItScore,
  num demandScore = 0,
}) {
  if (worthItScore <= 0) return CustomerLikelihood.low;
  if (_highSeverityTiers.contains(severityTier)) {
    return CustomerLikelihood.high;
  }
  if (_mediumSeverityTiers.contains(severityTier)) {
    if (severityTier == 'vehicle_cancelled' && demandScore >= _highScoreFloor) {
      return CustomerLikelihood.high;
    }
    return CustomerLikelihood.medium;
  }
  return CustomerLikelihood.low;
}

const customerLikelihoodLabels = {
  CustomerLikelihood.high: 'Troligt att det finns kunder',
  CustomerLikelihood.medium: 'Möjligt att det finns kunder',
  CustomerLikelihood.low: 'Osannolikt just nu',
};

const _months = [
  'jan', 'feb', 'mar', 'apr', 'maj', 'jun',
  'jul', 'aug', 'sep', 'okt', 'nov', 'dec',
];

// Titles this generic carry no place/route info at all -- Trafiklab
// genuinely sends nothing more specific for these (verified against real
// payloads: e.g. "Försening" with description "Tåget är försenat. Orsaken
// är fordonsfel." and no place name anywhere). Prefixing the mode at least
// tells the driver "this is about a train" instead of a bare, contextless
// "Försening". Shared between the card and the detail sheet so both read
// the same title the same way.
const _genericTitles = {
  'försening',
  'förseningar',
  'inställd',
  'inställda avgångar',
  'trafikinformation',
  'ändrad körväg',
};

String displayTitle({required String? title, required String? mode}) {
  final t = title?.trim();
  if (t == null || t.isEmpty) return 'Tips';
  if (_genericTitles.contains(t.toLowerCase())) {
    final modeLabel = switch (mode) {
      'train' => 'Tåg',
      'bus' => 'Buss',
      'road' => 'Väg',
      _ => null,
    };
    if (modeLabel != null) return '$modeLabel: $t';
  }
  return t;
}

/// Local date+time, e.g. "2 sep 22:16" for a different day or just "22:16"
/// for today. Shared between the list card and the detail sheet so a driver
/// scanning "Senaste dygnet" can tell today's items from yesterday's at a
/// glance, not just on the disruption's own remaining/ended duration text.
String dateTimeLabel(String? iso) {
  if (iso == null) return '—';
  final dt = DateTime.tryParse(iso)?.toLocal();
  if (dt == null) return '—';
  final now = DateTime.now();
  final time =
      '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  if (dt.year == now.year && dt.month == now.month && dt.day == now.day) {
    return time;
  }
  return '${dt.day} ${_months[dt.month - 1]} $time';
}
