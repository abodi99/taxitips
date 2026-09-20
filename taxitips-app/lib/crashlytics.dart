import 'package:firebase_crashlytics/firebase_crashlytics.dart';
import 'package:flutter/foundation.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'push_service.dart';

/// Crashlytics för native (iOS/Android). Web saknar meningsfullt stöd — hoppas över.
///
/// SDK:t skickar redan versionsnummer till "Release Monitoring" / latest release.
/// Custom keys gör samma info synlig på varje kraschrapport och i filter.
Future<void> initCrashlyticsSafe() async {
  if (!firebaseReady || kIsWeb) return;
  try {
    final crashlytics = FirebaseCrashlytics.instance;
    // Debug: samla inte — annars fylls konsolen med utvecklarkrascher.
    await crashlytics.setCrashlyticsCollectionEnabled(!kDebugMode);

    try {
      final info = await PackageInfo.fromPlatform();
      await Future.wait([
        crashlytics.setCustomKey('app_version', info.version),
        crashlytics.setCustomKey('build_number', info.buildNumber),
        crashlytics.setCustomKey('package_name', info.packageName),
      ]);
    } catch (e) {
      debugPrint('Crashlytics version keys skipped: $e');
    }

    FlutterError.onError = (details) {
      FlutterError.presentError(details);
      crashlytics.recordFlutterFatalError(details);
    };
    PlatformDispatcher.instance.onError = (error, stack) {
      crashlytics.recordError(error, stack, fatal: true);
      return true;
    };
  } catch (e) {
    debugPrint('Crashlytics init failed: $e');
  }
}
