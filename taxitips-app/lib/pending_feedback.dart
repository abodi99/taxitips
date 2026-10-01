import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Svar (🚕 / 👍 / 👎) som gavs utan nät och väntar på att skickas.
///
/// Svaret är det som kalibrerar poängsättningen, och det ges ofta just när
/// föraren står i en dålig täckning. Att kasta det vore att kasta data;
/// att be föraren trycka igen längre fram vore att be om för mycket.
/// Backend har unik nyckel per tips och omdöme, så ett dubbelt skick är
/// ofarligt.
class PendingFeedback {
  PendingFeedback._();

  static const _key = 'pending_feedback_v1';
  static const maxItems = 50;

  /// Äldre svar än så här skickas inte: tipset är borta och minnet om det
  /// stämde är inte längre något att lita på.
  static const maxAge = Duration(hours: 48);

  static Future<List<Map<String, dynamic>>> load({DateTime? now}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_key);
      if (raw == null) return [];
      return prune(jsonDecode(raw), now ?? DateTime.now());
    } catch (e) {
      debugPrint('PendingFeedback.load: $e');
      return [];
    }
  }

  static Future<void> _save(List<Map<String, dynamic>> items) async {
    final prefs = await SharedPreferences.getInstance();
    if (items.isEmpty) {
      await prefs.remove(_key);
    } else {
      await prefs.setString(_key, jsonEncode(items));
    }
  }

  /// Lägger till ett svar. Samma tips + omdöme ersätter det gamla.
  static Future<void> add(
    String opportunityId,
    String verdict, {
    DateTime? now,
  }) async {
    final t = now ?? DateTime.now();
    final items = await load(now: t);
    items.removeWhere(
      (i) => i['id'] == opportunityId && i['verdict'] == verdict,
    );
    items.add({
      'id': opportunityId,
      'verdict': verdict,
      'at': t.millisecondsSinceEpoch,
    });
    await _save(
      items.length > maxItems ? items.sublist(items.length - maxItems) : items,
    );
  }

  static Future<void> replaceAll(List<Map<String, dynamic>> items) =>
      _save(items);

  /// Rensar bort trasiga och för gamla poster.
  @visibleForTesting
  static List<Map<String, dynamic>> prune(dynamic raw, DateTime now) {
    if (raw is! List) return [];
    final out = <Map<String, dynamic>>[];
    for (final r in raw) {
      if (r is! Map) continue;
      final id = r['id']?.toString();
      final verdict = r['verdict']?.toString();
      final at = (r['at'] as num?)?.toInt();
      if (id == null || id.isEmpty || verdict == null || at == null) continue;
      final age = now.difference(DateTime.fromMillisecondsSinceEpoch(at));
      if (age > maxAge) continue;
      out.add({'id': id, 'verdict': verdict, 'at': at});
    }
    return out;
  }
}
