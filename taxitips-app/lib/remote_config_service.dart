import 'package:firebase_remote_config/firebase_remote_config.dart';
import 'package:flutter/foundation.dart';

import 'app_version.dart';
import 'push_service.dart';

FirebaseRemoteConfig? _remoteConfig;

/// Nycklar i Firebase Remote Config (primär källa för versionsgränser).
const kRcAndroidMin = 'android_min_version';
const kRcIosMin = 'ios_min_version';
const kRcAndroidRecommended = 'android_recommended_version';
const kRcIosRecommended = 'ios_recommended_version';
const kRcAndroidStoreUrl = 'android_store_url';
const kRcIosStoreUrl = 'ios_store_url';
const kRcForceUpgradeMessage = 'force_upgrade_message';

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
    });
    try {
      await rc.fetchAndActivate();
    } catch (e) {
      debugPrint('Remote Config fetch skipped: $e');
    }
    _remoteConfig = rc;
  } catch (e) {
    debugPrint('Remote Config init failed: $e');
    _remoteConfig = null;
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
  );
}

/// För test: nollställ initierat tillstånd.
@visibleForTesting
void resetRemoteConfigForTest() {
  _remoteConfig = null;
}
