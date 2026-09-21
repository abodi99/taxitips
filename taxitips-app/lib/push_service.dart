import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'firebase_options.dart';
import 'push_platform.dart';

bool firebaseReady = false;

/// Notiser som kommer medan appen är öppen.
///
/// Android visar INTE en FCM-notis i systemfältet när appen ligger i
/// förgrunden -- den levereras till `onMessage` och försvinner om ingen
/// lyssnar. För en förare som har TaxiTips uppe under ett pass betydde det
/// att varje notis tappades tyst. Förarskärmen lyssnar på den här strömmen,
/// visar notisen och hämtar om flödet så att tipset syns direkt.
///
/// (`setForegroundNotificationPresentationOptions` nedan gäller bara iOS.)
final StreamController<RemoteMessage> _foreground =
    StreamController<RemoteMessage>.broadcast();
Stream<RemoteMessage> get foregroundMessages => _foreground.stream;
StreamSubscription<RemoteMessage>? _onMessageSub;

/// Notisen som öppnade appen, och en signal när en ny kommer.
///
/// Tidigare lyssnade appen inte alls på att den öppnats av en notis, så ett
/// tryck startade appen men visade aldrig tipset notisen handlade om.
///
/// Två vägar in: `onMessageOpenedApp` när appen låg i bakgrunden, och
/// `getInitialMessage()` när den var helt stängd (kallstart). Vid kallstart
/// finns förarskärmen inte än när meddelandet kommer, så det sparas och
/// hämtas en gång med `takeOpenedMessage()`. Båda vägarna går genom den
/// funktionen, så varje notis öppnas exakt en gång.
final StreamController<void> _opened = StreamController<void>.broadcast();
Stream<void> get openedMessageSignals => _opened.stream;
RemoteMessage? _pendingOpened;
StreamSubscription<RemoteMessage>? _openedSub;

RemoteMessage? takeOpenedMessage() {
  final message = _pendingOpened;
  _pendingOpened = null;
  return message;
}

void _deliverOpened(RemoteMessage message) {
  _pendingOpened = message;
  _opened.add(null);
}

Future<void> _listenForOpens() async {
  if (_openedSub != null) return;
  _openedSub = FirebaseMessaging.onMessageOpenedApp.listen(
    _deliverOpened,
    onError: (Object e) => debugPrint('Push onMessageOpenedApp error: $e'),
  );
  try {
    final initial = await FirebaseMessaging.instance.getInitialMessage();
    if (initial != null) _deliverOpened(initial);
  } catch (e) {
    debugPrint('Push getInitialMessage error: $e');
  }
}

void _listenInForeground() {
  if (_onMessageSub != null) return;
  _onMessageSub = FirebaseMessaging.onMessage.listen(
    _foreground.add,
    onError: (Object e) => debugPrint('Push onMessage error: $e'),
  );
}

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
    // Tidigt: getInitialMessage() måste läsas innan något annat hinner
    // konsumera kallstarten, och det kräver inget notistillstånd.
    if (!kIsWeb) unawaited(_listenForOpens());
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
        _listenInForeground();
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
