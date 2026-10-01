import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Senaste tipsflödet på disk, så en kallstart i en tunnel visar något.
///
/// Det som visas härifrån är ALLTID gammalt och ska märkas så. Ett tips vars
/// `end_time` passerat får aldrig se pågående ut: [markExpired] sätter
/// `is_active: false` på det, och kortlistan gråar redan sådana.
class FeedCache {
  FeedCache._();

  static const _key = 'feed_cache_v1';

  /// Äldre än så här är inte värt att visa alls ("tips från i förrgår").
  static const maxAge = Duration(hours: 24);

  /// Fält som sparas. `active`/`week`/`events` byggs om vid inläsning: de är
  /// samma lista som `alerts`, och tre kopior hade tredubblat filen.
  static const _fields = [
    'alerts',
    'favorites',
    'placeStats',
    'roadTotal',
    'roadAll',
    'needsArea',
    'reason',
    'entitled',
    'message',
    'features',
    'source',
  ];

  static Future<void> save(Map<String, dynamic> data, {DateTime? now}) async {
    try {
      final at = (now ?? DateTime.now()).millisecondsSinceEpoch;
      final slim = {
        for (final k in _fields)
          if (data[k] != null) k: data[k],
      };
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        _key,
        jsonEncode({'v': 1, 'savedAt': at, 'data': slim}),
      );
    } catch (e) {
      // Cachen är en bonus; ett skrivfel får aldrig störa flödet.
      debugPrint('FeedCache.save: $e');
    }
  }

  /// Sparat flöde i samma form som `ApiClient.taxi()` svarar, med
  /// `updatedAt` = när det hämtades och utgångna tips markerade. Null om
  /// inget finns, det är för gammalt eller filen är trasig.
  static Future<Map<String, dynamic>?> load({DateTime? now}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_key);
      if (raw == null) return null;
      return decode(raw, now: now ?? DateTime.now());
    } catch (e) {
      debugPrint('FeedCache.load: $e');
      return null;
    }
  }

  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
  }

  @visibleForTesting
  static Map<String, dynamic>? decode(String raw, {required DateTime now}) {
    final m = jsonDecode(raw);
    if (m is! Map || m['v'] != 1 || m['data'] is! Map) return null;
    final savedAt = (m['savedAt'] as num?)?.toInt();
    if (savedAt == null) return null;
    final saved = DateTime.fromMillisecondsSinceEpoch(savedAt);
    if (now.difference(saved) > maxAge) return null;
    final data = Map<String, dynamic>.from(m['data'] as Map);
    final alerts = markExpired(data['alerts'], now);
    return {
      ...data,
      'alerts': alerts,
      'active': alerts,
      'week': alerts,
      'events': const [],
      'favorites': markExpired(data['favorites'], now),
      'updatedAt': savedAt,
      'fromCache': true,
    };
  }

  /// Tips vars `end_time` har passerat blir `is_active: false` (gråas och
  /// hamnar under "avslutade"). Ändrar inte indatan; returnerar nya kartor.
  /// Utan `end_time` lämnas tipset som det är -- appen gissar inte.
  static List<Map<String, dynamic>> markExpired(dynamic rows, DateTime now) {
    if (rows is! List) return const [];
    return [
      for (final r in rows)
        if (r is Map)
          () {
            final row = Map<String, dynamic>.from(r);
            final end = DateTime.tryParse(row['end_time']?.toString() ?? '');
            if (end != null && !end.isAfter(now)) row['is_active'] = false;
            return row;
          }(),
    ];
  }

  /// Samma sak för ett redan inläst flöde (offline-läge, varje tick).
  static Map<String, dynamic> expireFeed(
    Map<String, dynamic> data,
    DateTime now,
  ) {
    final alerts = markExpired(data['alerts'], now);
    return {
      ...data,
      'alerts': alerts,
      'active': alerts,
      'week': alerts,
      if (data['favorites'] != null)
        'favorites': markExpired(data['favorites'], now),
    };
  }
}
