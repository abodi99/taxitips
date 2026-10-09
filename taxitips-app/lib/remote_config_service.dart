import 'dart:async';

import 'package:firebase_remote_config/firebase_remote_config.dart';
import 'package:flutter/foundation.dart';

import 'app_version.dart';
import 'push_service.dart';

FirebaseRemoteConfig? _remoteConfig;
StreamSubscription<RemoteConfigUpdate>? _realtime;

/// Räknas upp varje gång nya värden aktiverats under körning. Spärren
/// (widgets/force_upgrade_overlay.dart) lyssnar och prövar om direkt: en
/// lägsta version som sätts i Firebase ska nå en app som står öppen hela
/// passet, inte först vid nästa start efter den timslånga hämtcachen.
final ValueNotifier<int> remoteConfigRevision = ValueNotifier<int>(0);

/// Nycklar i Firebase Remote Config (primär källa för versionsgränser).
const kRcAndroidMin = 'android_min_version';
const kRcIosMin = 'ios_min_version';
const kRcAndroidRecommended = 'android_recommended_version';
const kRcIosRecommended = 'ios_recommended_version';
const kRcAndroidStoreUrl = 'android_store_url';
const kRcIosStoreUrl = 'ios_store_url';
const kRcForceUpgradeMessage = 'force_upgrade_message';

/// Kommaseparerade versioner som inte får köras, t.ex. `1.4.0, 1.4.1+33`.
const kRcAndroidBlocked = 'android_blocked_versions';
const kRcIosBlocked = 'ios_blocked_versions';

Future<void> initRemoteConfigSafe() async {
  if (!firebaseReady || kIsWeb) return;
  try {
    final rc = FirebaseRemoteConfig.instance;
    await rc.setConfigSettings(
      RemoteConfigSettings(
        fetchTimeout: const Duration(seconds: 12),
        minimumFetchInterval: kDebugMode
            ? Duration.zero
            : const Duration(hours: 1),
      ),
    );
    await rc.setDefaults(const {
      kRcAndroidMin: '',
      kRcIosMin: '',
      kRcAndroidRecommended: '',
      kRcIosRecommended: '',
      kRcAndroidStoreUrl: '',
      kRcIosStoreUrl: '',
      kRcForceUpgradeMessage: '',
      kRcAndroidBlocked: '',
      kRcIosBlocked: '',
    });
    try {
      await rc.fetchAndActivate();
    } catch (e) {
      debugPrint('Remote Config fetch skipped: $e');
    }
    _remoteConfig = rc;
    _listenForUpdates(rc);
  } catch (e) {
    debugPrint('Remote Config init failed: $e');
    _remoteConfig = null;
  }
}

void _listenForUpdates(FirebaseRemoteConfig rc) {
  _realtime?.cancel();
  try {
    _realtime = rc.onConfigUpdated.listen(
      (_) async {
        try {
          await rc.activate();
          remoteConfigRevision.value++;
        } catch (e) {
          debugPrint('Remote Config activate failed: $e');
        }
      },
      onError: (Object e) => debugPrint('Remote Config realtime: $e'),
    );
  } catch (e) {
    debugPrint('Remote Config realtime unavailable: $e');
  }
}

String? _rcText(FirebaseRemoteConfig rc, String key) {
  final s = rc.getString(key).trim();
  return s.isEmpty ? null : s;
}

/// Gränser från Remote Config för en plattform. Null om Firebase saknas.
UpgradePolicy? remoteUpgradePolicy(String platform) {
  final rc = _remoteConfig;
  if (rc == null) return null;
  final isAndroid = platform == 'android';
  return UpgradePolicy(
    min: _rcText(rc, isAndroid ? kRcAndroidMin : kRcIosMin),
    recommended: _rcText(
      rc,
      isAndroid ? kRcAndroidRecommended : kRcIosRecommended,
    ),
    storeUrl: _rcText(rc, isAndroid ? kRcAndroidStoreUrl : kRcIosStoreUrl),
    message: _rcText(rc, kRcForceUpgradeMessage),
    blocked: UpgradePolicy.parseList(
      _rcText(rc, isAndroid ? kRcAndroidBlocked : kRcIosBlocked),
    ),
  );
}

/// För test: nollställ initierat tillstånd.
@visibleForTesting
void resetRemoteConfigForTest() {
  _realtime?.cancel();
  _realtime = null;
  _remoteConfig = null;
}
