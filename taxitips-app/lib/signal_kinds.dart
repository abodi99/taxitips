/// Vad något på kartan ÄR och hur viktigt det är -- en gång, för hela appen.
///
/// Kategorin (tåg och buss, väg, flyg, färja, event) bestämmer ikonen.
/// Styrkan bestämmer färgen och storleken. Samma par används på kartan, i
/// listan, i detaljvyn, i filtret och i förklaringen, så att en förare som
/// lärt sig en symbol på ett ställe känner igen den överallt -- utan att läsa.
///
/// **Enkla ord.** Många förare har inte svenska som förstaspråk. Etiketterna
/// är ett ord när det går ("Väg", "Flyg", "Färja", "Event") och bär alltid en
/// ikon. Färg är aldrig ensam bärare av betydelse (varumärkesguiden): styrkan
/// visas också med storlek och ett ord.
library;

import 'package:flutter/material.dart';

import 'severity_labels.dart';
import 'theme.dart';

enum SignalCategory { transit, road, flight, ferry, event }

/// Ordningen i kategoriraden: det som skapar körningar först.
const signalCategoryOrder = [
  SignalCategory.transit,
  SignalCategory.road,
  SignalCategory.flight,
  SignalCategory.ferry,
  SignalCategory.event,
];

extension SignalCategoryText on SignalCategory {
  /// Kort etikett för chips och kartförklaring.
  String get label => switch (this) {
    SignalCategory.transit => 'Tåg & buss',
    SignalCategory.road => 'Väg',
    SignalCategory.flight => 'Flyg',
    SignalCategory.ferry => 'Färja',
    SignalCategory.event => 'Event',
  };

  /// En mening i förklaringen: vad kategorin betyder för en taxiförare.
  String get explanation => switch (this) {
    SignalCategory.transit =>
      'Tåg, buss eller tunnelbana står still eller är sen. Folk behöver taxi.',
    SignalCategory.road =>
      'Olycka, avstängd väg, kö eller vägarbete (Trafikverket). Kör runt.',
    SignalCategory.flight =>
      'Många flyg landar, eller sista flyget. Folk behöver taxi från flygplatsen.',
    SignalCategory.ferry => 'Färja på väg in. Folk kliver av i hamnen.',
    SignalCategory.event =>
      'Match, konsert eller annat. Publiken går hem samtidigt.',
  };

  IconData get icon => switch (this) {
    SignalCategory.transit => Icons.train_rounded,
    SignalCategory.road => Icons.warning_rounded,
    SignalCategory.flight => Icons.flight_land_rounded,
    SignalCategory.ferry => Icons.directions_boat_rounded,
    SignalCategory.event => Icons.stadium_rounded,
  };

  /// Nyckeln i det sparade dolda-läget (filterModeOptions i severity_labels).
  String get key => switch (this) {
    SignalCategory.transit => 'transit',
    SignalCategory.road => 'road',
    SignalCategory.flight => 'flight',
    SignalCategory.ferry => 'ferry',
    SignalCategory.event => 'event',
  };
}

SignalCategory? signalCategoryFromKey(String? key) {
  for (final c in SignalCategory.values) {
    if (c.key == key) return c;
  }
  return null;
}

/// Vilken kategori ett tips hör till. `kind` först -- en färja från AIS har
/// `mode: boat` precis som Waxholmsbolagets båtar, men är något helt annat
/// för en taxiförare.
SignalCategory categoryOfAlert(Map alert) {
  switch (alert['kind']?.toString()) {
    case 'road':
      return SignalCategory.road;
    case 'flight':
      return SignalCategory.flight;
    case 'ferry':
      return SignalCategory.ferry;
  }
  switch (alert['mode']?.toString()) {
    case 'road':
      return SignalCategory.road;
    case 'flight':
      return SignalCategory.flight;
  }
  return SignalCategory.transit;
}

/// Hur viktigt något är, i tre steg. För tips: hur troligt det är att någon
/// behöver taxi. För väghinder: hur mycket det stör trafiken.
enum SignalStrength { high, medium, low }

SignalStrength _fromLikelihood(CustomerLikelihood l) => switch (l) {
  CustomerLikelihood.high => SignalStrength.high,
  CustomerLikelihood.medium => SignalStrength.medium,
  CustomerLikelihood.low => SignalStrength.low,
};

/// Väghinder har egen skala: en olycka är allvarlig för den som ska köra
/// förbi, men den skapar inga kunder (likelihood är alltid låg för väg).
SignalStrength roadStrength(String? tier) => switch (tier) {
  'road_accident_or_closure' => SignalStrength.high,
  'road_work_or_queue' => SignalStrength.medium,
  _ => SignalStrength.low,
};

SignalStrength strengthOfAlert(Map alert) {
  if (categoryOfAlert(alert) == SignalCategory.road) {
    return roadStrength(alert['severity_tier']?.toString());
  }
  return _fromLikelihood(likelihoodForAlert(alert));
}

/// Evenemangets storlek som styrka. Backendens `sizeLevel` (events/timing.py):
/// `stor` 5 000+, `medel` 1 000–4 999, `liten` och `okand`.
SignalStrength strengthOfEvent(Map event) =>
    switch (event['sizeLevel']?.toString()) {
      'stor' => SignalStrength.high,
      'medel' => SignalStrength.medium,
      _ => SignalStrength.low,
    };

/// Färgen för en styrka. Tips: grönt = värt att köra till. Väghinder: rött
/// = olycka eller avstängt, så att vägfaran aldrig förväxlas med en körning.
Color strengthColor(SignalStrength s, {SignalCategory? category}) {
  if (category == SignalCategory.road) {
    return switch (s) {
      SignalStrength.high => TbColors.danger,
      SignalStrength.medium => TbColors.guldDjup,
      SignalStrength.low => TbColors.skiffer,
    };
  }
  if (category == SignalCategory.event) {
    return switch (s) {
      SignalStrength.high => TbColors.midnatt,
      SignalStrength.medium => TbColors.midnattMjuk,
      SignalStrength.low => TbColors.skiffer,
    };
  }
  return switch (s) {
    SignalStrength.high => TbColors.likelihoodHigh,
    SignalStrength.medium => TbColors.likelihoodMedium,
    SignalStrength.low => TbColors.likelihoodLow,
  };
}

/// Ordet bredvid färgen. Kort, och samma ord i kort, detaljvy och förklaring.
String strengthWord(SignalStrength s, {SignalCategory? category}) {
  if (category == SignalCategory.road) {
    return switch (s) {
      SignalStrength.high => 'Stopp',
      SignalStrength.medium => 'Kö',
      SignalStrength.low => 'Arbete',
    };
  }
  if (category == SignalCategory.event) {
    return switch (s) {
      SignalStrength.high => 'Stort',
      SignalStrength.medium => 'Mellan',
      SignalStrength.low => 'Litet',
    };
  }
  return switch (s) {
    SignalStrength.high => 'Stark',
    SignalStrength.medium => 'Medel',
    SignalStrength.low => 'Svag',
  };
}

/// Ikonen för ett tips: färdsättet för kollektivtrafik, typen av hinder för väg.
IconData iconForAlert(Map alert) {
  final category = categoryOfAlert(alert);
  switch (category) {
    case SignalCategory.road:
      return switch (alert['severity_tier']?.toString()) {
        'road_accident_or_closure' => Icons.car_crash_rounded,
        'road_work_or_queue' => Icons.traffic_rounded,
        _ => Icons.construction_rounded,
      };
    case SignalCategory.flight:
      return Icons.flight_land_rounded;
    case SignalCategory.ferry:
      return Icons.directions_boat_rounded;
    case SignalCategory.event:
      return Icons.stadium_rounded;
    case SignalCategory.transit:
      return switch (alertFilterMode(Map<String, dynamic>.from(alert))) {
        'metro' => Icons.subway_rounded,
        'tram' => Icons.tram_rounded,
        'bus' => Icons.directions_bus_rounded,
        'boat' => Icons.directions_boat_filled_rounded,
        _ => Icons.train_rounded,
      };
  }
}

/// Ikonen för ett evenemang, efter sport eller kategori.
IconData iconForEvent(Map event) {
  final sport = event['sport']?.toString() ?? '';
  final category = event['category']?.toString() ?? '';
  return switch (sport.isNotEmpty ? sport : category) {
    'fotboll' => Icons.sports_soccer_rounded,
    'ishockey' => Icons.sports_hockey_rounded,
    'handboll' => Icons.sports_handball_rounded,
    'basket' => Icons.sports_basketball_rounded,
    'annan' || 'sport' => Icons.sports_rounded,
    'konsert' => Icons.music_note_rounded,
    'festival' => Icons.festival_rounded,
    'teater' || 'humor' => Icons.theater_comedy_rounded,
    'familj' => Icons.family_restroom_rounded,
    'film' => Icons.movie_rounded,
    'massa' || 'konferens' => Icons.groups_rounded,
    'flyg' => Icons.flight_land_rounded,
    'vader' => Icons.thunderstorm_rounded,
    'katastrof' || 'sakerhet' => Icons.report_rounded,
    _ => Icons.event_rounded,
  };
}

/// "Vad hände" i några få ord, för kortets andra rad.
String shortWhat(Map alert) {
  final tier = alert['severity_tier']?.toString();
  final short = severityTierShortLabels[tier];
  if (short != null) return short;
  return categoryOfAlert(alert).label;
}

/// "Västra Götalands län" -> "Västra Götaland", "Skåne län" -> "Skåne".
/// Grundformen är kortare och lättare att känna igen för den som inte har
/// svenska som förstaspråk. Inget län heter något som slutar på s i grundform.
String countyShort(String name) {
  var n = name.trim();
  if (n.endsWith(' län')) n = n.substring(0, n.length - 4);
  if (n.endsWith('s')) n = n.substring(0, n.length - 1);
  return n;
}

/// "3 km", "800 m" -- avstånd som en förare läser på en halv sekund.
String distanceText(num? km) {
  if (km == null) return '';
  if (km < 1) return '${(km * 1000 / 50).round() * 50} m';
  if (km < 10) return '${km.toStringAsFixed(1).replaceAll('.', ',')} km';
  return '${km.round()} km';
}

/// "Nu", "5 min", "2 tim" -- hur färskt något är.
String ageText(DateTime? start, {DateTime? now}) {
  if (start == null) return '';
  final diff = (now ?? DateTime.now()).difference(start);
  if (diff.isNegative) {
    final ahead = diff.abs();
    if (ahead.inMinutes < 60) return 'om ${ahead.inMinutes} min';
    return 'om ${ahead.inHours} tim';
  }
  if (diff.inMinutes < 1) return 'Nu';
  if (diff.inMinutes < 60) return '${diff.inMinutes} min';
  if (diff.inHours < 24) return '${diff.inHours} tim';
  return '${diff.inDays} d';
}
