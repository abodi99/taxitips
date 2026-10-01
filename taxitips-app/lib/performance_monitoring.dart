import 'package:firebase_performance/firebase_performance.dart';
import 'package:flutter/foundation.dart';

import 'push_service.dart';

Future<void> initPerformanceSafe() async {
  if (!firebaseReady || kIsWeb) return;
  try {
    await FirebasePerformance.instance.setPerformanceCollectionEnabled(
      !kDebugMode,
    );
  } catch (e) {
    debugPrint('Performance Monitoring init failed: $e');
  }
}
