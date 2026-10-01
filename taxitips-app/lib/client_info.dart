import 'dart:async';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:package_info_plus/package_info_plus.dart';

/// Vilken app på vilken telefon -- som headers på varje anrop till backenden.
///
/// Supporten ska kunna se "Samsung S23, Android 14, version 1.0.1 bygge 2"
/// utan att be föraren leta i inställningarna. Backenden sparar det senaste
/// värdet per konto och telefon (fleet/client_activity.py) och visar det i
/// adminwebben under "Appar och fel".
///
/// Bara det: version, bygge, plattform, OS-version och modell. Inget
/// enhets-id, inget namn på telefonen ("Kalles iPhone"), ingen position.
/// Se docs/loggning.md.
class ClientInfo {
  ClientInfo._();

  static final Map<String, String> _headers = {
    'X-App-Platform': platformName(),
  };

  /// Headrarna som går med i varje anrop (BackendApi._headers). Tom på
  /// version och modell tills [load] hunnit svara -- aldrig ett fel.
  static Map<String, String> get headers => Map.unmodifiable(_headers);

  static Future<void>? _loading;

  /// Läser version och telefon en gång. Säker att anropa flera gånger.
  static Future<void> load() => _loading ??= _load();

  static Future<void> _load() async {
    try {
      final info = await PackageInfo.fromPlatform();
      _put('X-App-Version', info.version, max: 32);
      _put('X-App-Build', info.buildNumber, max: 16);
    } catch (e) {
      debugPrint('ClientInfo: version saknas: $e');
    }
    try {
      final plugin = DeviceInfoPlugin();
      if (kIsWeb) {
        final web = await plugin.webBrowserInfo;
        // Webbläsarens namn räcker; hela user-agent-strängen skickar
        // webbläsaren redan själv.
        _put('X-Device-Model', web.browserName.name);
      } else if (defaultTargetPlatform == TargetPlatform.android) {
        final a = await plugin.androidInfo;
        _put('X-Device-Model', '${a.manufacturer} ${a.model}');
        _put(
          'X-OS-Version',
          'Android ${a.version.release} (SDK ${a.version.sdkInt})',
        );
      } else if (defaultTargetPlatform == TargetPlatform.iOS) {
        final i = await plugin.iosInfo;
        _put(
          'X-Device-Model',
          i.modelName.isNotEmpty ? i.modelName : i.utsname.machine,
        );
        _put('X-OS-Version', '${i.systemName} ${i.systemVersion}');
      }
    } catch (e) {
      debugPrint('ClientInfo: telefonuppgifter saknas: $e');
    }
  }

  static void _put(String key, String value, {int max = 64}) {
    final cleaned = clean(value, max: max);
    if (cleaned.isNotEmpty) _headers[key] = cleaned;
  }

  /// Bara skrivbar ASCII, kapad. En HTTP-header med "é" eller en radbrytning
  /// kastar i http-paketet -- och då hade själva anropet fallerat.
  @visibleForTesting
  static String clean(String value, {int max = 64}) {
    final ascii = value.replaceAll(RegExp(r'[^\x20-\x7E]'), '').trim();
    return ascii.length > max ? ascii.substring(0, max) : ascii;
  }

  @visibleForTesting
  static String platformName() {
    if (kIsWeb) return 'web';
    return switch (defaultTargetPlatform) {
      TargetPlatform.android => 'android',
      TargetPlatform.iOS => 'ios',
      TargetPlatform.macOS => 'macos',
      TargetPlatform.windows => 'windows',
      TargetPlatform.linux => 'linux',
      TargetPlatform.fuchsia => 'fuchsia',
    };
  }
}
