import 'package:firebase_analytics/firebase_analytics.dart';
import 'package:flutter/foundation.dart';

import 'analytics_consent.dart';
import 'push_service.dart';

FirebaseAnalytics? _analytics;
bool _collectionEnabled = false;

FirebaseAnalyticsObserver? analyticsObserver() {
  final a = _analytics;
  if (a == null || !_collectionEnabled) return null;
  return FirebaseAnalyticsObserver(analytics: a);
}

Future<void> initAnalyticsSafe() async {
  if (!firebaseReady) return;
  try {
    _analytics = FirebaseAnalytics.instance;
    final allowed = await analyticsConsentGranted();
    await _analytics!.setAnalyticsCollectionEnabled(allowed);
    _collectionEnabled = allowed;
    if (allowed) {
      await _analytics!.logAppOpen();
    }
    listenAnalyticsConsentChanges((granted) async {
      final a = _analytics;
      if (a == null) return;
      await a.setAnalyticsCollectionEnabled(granted);
      _collectionEnabled = granted;
      if (granted) {
        await a.logAppOpen();
      }
    });
  } catch (e) {
    debugPrint('Analytics init failed: $e');
    _analytics = null;
    _collectionEnabled = false;
  }
}

Future<void> logAnalyticsEvent(
  String name, {
  Map<String, Object?>? params,
}) async {
  final a = _analytics;
  if (a == null || !_collectionEnabled) return;
  try {
    final cleaned = <String, Object>{};
    params?.forEach((k, v) {
      if (v != null) cleaned[k] = v;
    });
    await a.logEvent(name: name, parameters: cleaned.isEmpty ? null : cleaned);
  } catch (e) {
    debugPrint('Analytics event failed: $e');
  }
}
