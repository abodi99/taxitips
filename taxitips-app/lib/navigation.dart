import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:url_launcher/url_launcher.dart';

/// "Kör dit": öppnar telefonens egen navigering med vägbeskrivning dit.
///
/// Appen bygger ingen egen ruttplanering. Telefonens navigering (Google Maps
/// på Android, Apple Kartor på iPhone) har trafikdata i realtid, röststyrning
/// och omledning vid köer -- det föraren redan kör med. På Android startar
/// `google.navigation:` turn-by-turn direkt, utan ett extra steg i en
/// webbsida. Finns ingen sådan app faller vi tillbaka på Google Maps på webben.
Future<bool> openNavigation(double lat, double lon) async {
  final destination = '${lat.toStringAsFixed(6)},${lon.toStringAsFixed(6)}';
  final candidates = <Uri>[
    if (!kIsWeb && Platform.isAndroid)
      Uri.parse('google.navigation:q=$destination&mode=d'),
    if (!kIsWeb && Platform.isIOS)
      Uri.parse('maps://?daddr=$destination&dirflg=d'),
    Uri.parse(
      'https://www.google.com/maps/dir/?api=1&destination=$destination&travelmode=driving',
    ),
  ];
  for (final uri in candidates) {
    try {
      if (await launchUrl(uri, mode: LaunchMode.externalApplication)) {
        return true;
      }
    } catch (_) {
      // Ingen app för den adressen -- prova nästa.
    }
  }
  return false;
}
