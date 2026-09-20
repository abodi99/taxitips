import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'firebase_options.dart';
import 'push_platform.dart';

bool firebaseReady = false;

/// Serialiserar registerForPush — boot + auth-listener + driver_screen
/// kan annars köra requestPermission samtidigt och FCM svarar
/// "A request for permissions is already running".
Future<String?>? _registerInFlight;

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

/// Registrera FCM och koppla telefonen till inloggat konto / förarenhet.
///
/// Anropas efter login, kontobyte, join och när shell bootar med session.
/// Utan Firebase sparas ändå session-kopplingen (installation_id + user)
/// så last_seen och user_id uppdateras.
Future<String?> registerForPush(ApiClient api) {
  final existing = _registerInFlight;
  if (existing != null) return existing;
  final future = _registerForPushOnce(api);
  _registerInFlight = future;
  future.whenComplete(() {
    if (identical(_registerInFlight, future)) {
      _registerInFlight = null;
    }
  });
  return future;
}

Future<String?> _registerForPushOnce(ApiClient api) async {
  final platform = pushPlatformName();
  String? fcmToken;

  if (firebaseReady) {
    try {
      final messaging = FirebaseMessaging.instance;
      final settings = await messaging.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );
      if (settings.authorizationStatus != AuthorizationStatus.denied) {
        if (!kIsWeb) {
          await messaging.setForegroundNotificationPresentationOptions(
            alert: true,
            badge: true,
            sound: true,
          );
        }
        final vapid = const String.fromEnvironment(
          'FCM_VAPID_KEY',
          defaultValue: '',
        );
        fcmToken = await messaging.getToken(
          vapidKey: vapid.isEmpty ? null : vapid,
        );
        messaging.onTokenRefresh.listen((t) async {
          if (t.isEmpty) return;
          try {
            await api.registerPushToken(fcmToken: t, platform: platform);
          } catch (e) {
            debugPrint('Push token refresh failed: $e');
          }
        });
      }
    } catch (e) {
      debugPrint('Push FCM step failed: $e');
    }
  } else {
    debugPrint('Push: Firebase not configured — session link only');
  }

  try {
    if (fcmToken != null && fcmToken.isNotEmpty) {
      await api.registerPushToken(fcmToken: fcmToken, platform: platform);
      debugPrint('Push FCM registered (len=${fcmToken.length})');
      return fcmToken;
    }
    // Ingen FCM (web/simulator/nekad permission) — koppla ändå enhet↔konto.
    await api.linkDeviceSession(platform: platform);
  } catch (e) {
    debugPrint('Device/push registration failed: $e');
  }
  return fcmToken;
}
