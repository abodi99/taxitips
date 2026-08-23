import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'firebase_options.dart';
import 'push_platform.dart';

bool firebaseReady = false;

Future<void> initFirebaseSafe() async {
  try {
    if (Firebase.apps.isEmpty) {
      await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
    }
    firebaseReady = true;
  } catch (e) {
    debugPrint('Firebase init failed: $e');
    firebaseReady = false;
  }
}

Future<String?> registerForPush(ApiClient api) async {
  if (!firebaseReady) {
    debugPrint('Push: Firebase not configured');
    return null;
  }
  try {
    final messaging = FirebaseMessaging.instance;
    final settings = await messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );
    if (settings.authorizationStatus == AuthorizationStatus.denied) {
      return null;
    }

    if (!kIsWeb) {
      await messaging.setForegroundNotificationPresentationOptions(
        alert: true,
        badge: true,
        sound: true,
      );
    }

    final vapid = const String.fromEnvironment('FCM_VAPID_KEY', defaultValue: '');
    final token = await messaging.getToken(
      vapidKey: vapid.isEmpty ? null : vapid,
    );
    if (token == null || token.isEmpty) return null;
    final platform = pushPlatformName();
    if (api.deviceToken != null) {
      await api.registerPushToken(fcmToken: token, platform: platform);
    }
    messaging.onTokenRefresh.listen((t) async {
      if (api.deviceToken == null || t.isEmpty) return;
      try {
        await api.registerPushToken(fcmToken: t, platform: platform);
      } catch (e) {
        debugPrint('Push token refresh failed: $e');
      }
    });
    return token;
  } catch (e) {
    debugPrint('Push register failed: $e');
    return null;
  }
}
