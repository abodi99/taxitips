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
/// raw Worth-It number on the list card.
///
/// worth_it_score used to fold in reachability -- it subtracted distance and
/// zeroed out anything judged unreachable "in time" -- which meant a strong
/// disruption 90 km away scored the same 0 as a genuinely weak one. That
/// conflation is gone: the backend no longer scores distance at all, because
/// whether a drive is worth making is the driver's call, not a formula's.
/// Distance is shown separately on the card; this read is now purely about
/// how strong the underlying signal is.
enum CustomerLikelihood { high, medium, low }

// Road tiers are deliberately excluded from both sets -- an accident or
// closure delays people already in a car, it doesn't strand pedestrians who'd
// need a taxi. Only transit disruptions (a stopped line, a cancelled vehicle)
// actually leave people without transport, so only those drive "likely
// customers" up. Road incidents fall through to `low` regardless of tier.
const _highSeverityTiers = {'line_paused'};
const _mediumSeverityTiers = {'line_delayed', 'vehicle_cancelled'};

/// Fallback-golvet, inte källan.
///
/// Bedömningen görs numera i backend (core/thresholds.py, som serverar den
/// som `level` på varje tips och som `notifyScoreFloor` på /api/config).
/// Talet 50 stod tidigare i fyra kopior över tre språk utan att något höll
/// ihop dem -- se taxitips-backend/schema/constants.md. Kopian här lever
/// kvar av ett skäl: appen ska kunna rendera en cachead eller
/// Supabase-hämtad lista som saknar `level` utan att visa fel färg. Den
/// speglar backend och får aldrig avvika på egen hand.
const _highScoreFloor = 50;

/// Bedömningen som backend redan gjort, när den finns med.
///
/// `level` kommer från Django-API:t (core/api.py). Saknas fältet -- äldre
/// Supabase-RPC-svar, cachead data -- räknas det ut lokalt av reglerna
/// nedan, som är en spegling av samma Python-kod.
CustomerLikelihood likelihoodForAlert(Map alert) => customerLikelihood(
  severityTier: alert['severity_tier']?.toString(),
  worthItScore: (alert['worth_it_score'] as num?) ?? 0,
  demandScore: (alert['demand_score'] as num?) ?? 0,
  backendLevel: alert['level']?.toString(),
  // travel_options.has_alternative speglar samma fält; flat has_alternative
  // kommer från Django. Båda behövs så cachead/Supabase-data inte
  // återuppväcker ersättningstrafik som "high".
  hasAlternative:
      alert['has_alternative'] == true ||
      TravelOptions.of(alert)?.hasAlternative == true,
);

CustomerLikelihood customerLikelihood({
  required String? severityTier,
  required num worthItScore,
  num demandScore = 0,
  String? backendLevel,
  bool hasAlternative = false,
}) {
  // Ersättningstrafik först -- även om en cachead backendLevel säger
  // "high" (äldre svar innan thresholds.py sänkte dem).
  if (hasAlternative) return CustomerLikelihood.low;
  switch (backendLevel) {
    case 'high':
      return CustomerLikelihood.high;
    case 'medium':
      return CustomerLikelihood.medium;
    case 'low':
      return CustomerLikelihood.low;
  }
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

// The "Troligt/Möjligt/Osannolikt att det finns kunder" labels lived here.
// Removed deliberately: they stated a probability the data can't actually
// support (we know severity, distance and age -- not whether anyone is
// standing at that stop), and they occupied the badge slot that now carries
// distance, which a driver can act on. CustomerLikelihood itself is kept and
// still drives the badge colour and the "Bara hög prio" filter.

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
      // SL reports metro and tram distinctly, and the backend keeps them
      // distinct rather than flattening both into "Tåg" -- a Stockholm driver
      // reads "Tunnelbana" and knows immediately which kind of stop to head
      // for. They are scored on the same tiers as train (a stopped metro
      // line strands people identically); only the label differs.
      'metro' => 'Tunnelbana',
      'tram' => 'Spårvagn',
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

/// Etiketten för lagstadgad förseningsersättning, delad mellan kortet och
/// detaljvyn så att de aldrig säger olika saker om samma tips.
///
/// Beloppet kommer från backendens RegionCompensationRule (en rad per
/// län/operatör, källbelagd i docs/transit-compensation-rules.md) -- appen
/// räknar inte ut det och ska inte gissa när det saknas.
/// [perPerson] är avsiktligt trelägad: null betyder att huvudmannen inte
/// skriver ut om taket gäller per resenär eller per resa, och då påstår
/// kortet inget. Skillnaden är stor — Skånetrafikens 2 960 kr gäller per
/// betalande resenär, medan SL skriver att beloppet inte blir högre vid
/// samåkning. Fyra strandsatta resenärer är två olika affärer.
String compensationLabel(num? amountKr, {bool? perPerson}) {
  if (amountKr == null) return 'Taxi kan ersättas';
  final per = switch (perPerson) {
    true => ' per resenär',
    false => ' per resa',
    null => '',
  };
  return 'Taxi ersätts · upp till ${amountKr.round()} kr$per';
}


/// "Vad gör resenären i stället?" — nästa avgång och ersättningstrafik.
///
/// Meningen kommer färdigformulerad från backend (core/alternatives.py);
/// appen väljer bara hur den ska se ut. Att formulera om den här hade
/// betytt att kortet och detaljvyn förr eller senare sa olika saker om
/// samma tips.
class TravelOptions {
  const TravelOptions({
    required this.summary,
    required this.isLastDeparture,
    required this.hasAlternative,
    required this.minutes,
  });

  final String? summary;
  final bool isLastDeparture;
  final bool hasAlternative;
  final int? minutes;

  static TravelOptions? of(Map alert) {
    final raw = alert['travel_options'];
    if (raw is! Map) return null;
    final summary = raw['summary']?.toString();
    if (summary == null || summary.isEmpty) return null;
    return TravelOptions(
      summary: summary,
      isLastDeparture: raw['is_last_departure'] == true,
      hasAlternative: raw['has_alternative'] == true,
      minutes: (raw['next_departure_minutes'] as num?)?.toInt(),
    );
  }

  /// Sista avgången betyder att ingen tar sig hem själv — det är den
  /// starkaste signalen ett tips kan bära. En angiven ersättningsbuss
  /// betyder tvärtom att resenären sannolikt inte behöver taxi. Samma rad,
  /// motsatt innebörd, så de får inte se likadana ut.
  bool get isStrong => isLastDeparture || (minutes != null && minutes! >= 60);
  bool get isWeak => hasAlternative && !isLastDeparture;
}
