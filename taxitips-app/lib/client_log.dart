import 'dart:async';

import 'package:firebase_crashlytics/firebase_crashlytics.dart';
import 'package:flutter/foundation.dart';

import 'api_client.dart' show ApiException;
import 'push_service.dart' show firebaseReady;

/// Skickar felrapporten till backenden (ApiClient.sendClientLog).
typedef ClientLogSender = Future<void> Function(Map<String, dynamic> body);

/// Appens felrapporter till backenden: krascher och kritiska flöden som
/// misslyckas. Hamnar i adminwebbens "Appar och fel" (fleet/client_log_api.py).
///
/// **Varför både detta och Crashlytics.** Crashlytics ser krascher på
/// iOS/Android men inte webben, och inte "inloggningen misslyckades" -- det
/// är ingen krasch. Och det kopplas inte till ett företag eller en telefon i
/// adminwebben, vilket är var supporten sitter när kunden ringer.
/// Crashlytics behålls som förut; flödesfelen skickas dit också, som
/// icke-fatala.
///
/// **Aldrig ett problem för föraren.** Allt här sväljer sina egna fel, väntar
/// aldrig på svar, slår ihop samma fel inom fem minuter och skickar högst
/// [maxPerRun] rapporter per körning. En app i en felloop ska inte kunna
/// bränna förarens mobildata eller fylla servern -- servern har dessutom
/// egna gränser.
///
/// Servern tvättar texten (tokens, e-post, telefonnummer, position) innan den
/// sparas; här kapas den bara, för att inte skicka mer än nödvändigt.
class ClientLog {
  ClientLog._();

  static const maxPerRun = 40;
  static const dedupWindow = Duration(minutes: 5);
  static const _maxMessage = 1000;
  static const _maxStack = 4000;

  /// Flödena som räknas som kritiska: utan dem kommer föraren inte in eller
  /// ser inga tips. Namnen är operationerna i ApiClient.
  static const criticalOperations = {
    'login': 'login',
    'me': 'me',
    'signup': 'signup',
    'register': 'register',
    'pairing': 'pairing',
    'taxi.alerts': 'feed',
  };

  static ClientLogSender? _sender;
  static final List<Map<String, dynamic>> _pending = [];
  static final Map<String, DateTime> _recent = {};
  static int _sent = 0;

  /// Kopplar in avsändaren. Rapporter från innan (t.ex. ett fel vid start)
  /// skickas nu.
  static void attach(ClientLogSender sender) {
    _sender = sender;
    final queued = List.of(_pending);
    _pending.clear();
    for (final body in queued) {
      unawaited(_send(body));
    }
  }

  @visibleForTesting
  static void resetForTest() {
    _sender = null;
    _pending.clear();
    _recent.clear();
    _sent = 0;
  }

  /// Fångar krascher som ingen annan fångar. Kedjar på de hanterare som redan
  /// finns (Crashlytics sätter sina i initCrashlyticsSafe), så att inget
  /// befintligt beteende försvinner.
  static void installErrorHandlers() {
    final previousFlutter = FlutterError.onError;
    FlutterError.onError = (details) {
      if (previousFlutter != null) {
        previousFlutter(details);
      } else {
        FlutterError.presentError(details);
      }
      report(
        kind: 'crash',
        flow: 'flutter',
        error: details.exception,
        stack: details.stack,
        fatal: !details.silent,
      );
    };
    final previousPlatform = PlatformDispatcher.instance.onError;
    PlatformDispatcher.instance.onError = (error, stack) {
      report(kind: 'crash', flow: 'uncaught', error: error, stack: stack, fatal: true);
      // Samma svar som förut: Crashlyticss hanterare säger "hanterat", utan
      // den får motorn skriva ut felet som vanligt.
      return previousPlatform?.call(error, stack) ?? false;
    };
  }

  /// Ett misslyckat anrop i ApiClient. Bara de kritiska operationerna
  /// rapporteras; resten är vardag (ett tips som hunnit försvinna).
  static void apiFailure(String operation, Object error, [StackTrace? stack]) {
    final flow = criticalOperations[operation];
    if (flow == null) return;
    report(kind: 'flow', flow: flow, error: error, stack: stack);
  }

  /// Ett misslyckat kritiskt flöde utanför ApiClients felväg.
  static void flowFailure(String flow, Object error, [StackTrace? stack]) {
    report(kind: 'flow', flow: flow, error: error, stack: stack);
  }

  static void report({
    required String kind,
    required String flow,
    required Object error,
    StackTrace? stack,
    bool fatal = false,
  }) {
    try {
      final body = buildBody(
        kind: kind,
        flow: flow,
        error: error,
        stack: stack,
        fatal: fatal,
      );
      final key = '$kind|$flow|${body['errorType']}|${body['message']}';
      final now = DateTime.now();
      final last = _recent[key];
      if (last != null && now.difference(last) < dedupWindow) return;
      if (_recent.length > 200) _recent.clear();
      _recent[key] = now;
      if (kind == 'flow') _crashlyticsNonFatal(flow, error, stack);
      if (_sender == null) {
        if (_pending.length < 5) _pending.add(body);
        return;
      }
      unawaited(_send(body));
    } catch (_) {
      // Rapporteringen får aldrig själv bli ett fel.
    }
  }

  @visibleForTesting
  static Map<String, dynamic> buildBody({
    required String kind,
    required String flow,
    required Object error,
    StackTrace? stack,
    bool fatal = false,
  }) {
    final api = error is ApiException ? error : null;
    return {
      'kind': kind,
      'flow': flow,
      'errorType': api != null ? 'ApiException' : error.runtimeType.toString(),
      'message': _cap(error.toString(), _maxMessage),
      if (stack != null) 'stack': _cap(stack.toString(), _maxStack),
      'fatal': fatal,
      if (api != null) 'status': api.status,
      if (api?.reason != null) 'reason': api!.reason,
    };
  }

  static String _cap(String value, int max) =>
      value.length > max ? value.substring(0, max) : value;

  static Future<void> _send(Map<String, dynamic> body) async {
    final sender = _sender;
    // Taket gäller hela körningen. Ett fel i själva sändningen fångas här och
    // rapporteras inte vidare -- avsändaren går inte genom ApiClients
    // felväg, så ingen rapport kan ge upphov till en ny.
    if (sender == null || _sent >= maxPerRun) return;
    _sent++;
    try {
      await sender(body);
    } catch (_) {
      // Ingen kö: ett fel som inte når fram offline är inte värt förarens
      // mobildata senare. Crashlytics har sin egen.
    }
  }

  static void _crashlyticsNonFatal(String flow, Object error, StackTrace? stack) {
    if (!firebaseReady || kIsWeb) return;
    try {
      unawaited(
        FirebaseCrashlytics.instance.recordError(
          error,
          stack,
          reason: 'flow:$flow',
          fatal: false,
        ),
      );
    } catch (_) {}
  }
}
