import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'widgets/alert_feedback_bar.dart' show FeedbackChoices;

/// Ett tips föraren körde mot, och när.
class FollowUp {
  const FollowUp({required this.id, required this.place, required this.at});

  final String id;
  final String place;
  final DateTime at;
}

/// "Hur gick det?" -- frågan ställd när svaret finns, inte när tipset öppnas.
///
/// Knapparna i tipsbladet gav 4 svar på en vecka (2026-10-04): föraren
/// öppnar bladet INNAN körningen, och då finns inget att svara. Den här
/// listan minns tipsen föraren tryckt "Kör dit" på och lyfter fram frågan
/// en halvtimme senare, överst i listan. Svaret är det enda som kan
/// kalibrera poängen mot verkligheten.
///
/// Bara på telefonen: ingen ny endpoint, svaret går samma väg som bladets
/// knappar (FeedbackChoices, PendingFeedback).
class FollowUps {
  FollowUps._();

  static const _key = 'tip_follow_ups_v1';
  static const maxItems = 20;

  /// Tidigast då: föraren har hunnit fram och vet om det blev en körning.
  static const askAfter = Duration(minutes: 30);

  /// Senast då: efter ett helt pass minns ingen hur det gick vid ett tips.
  static const askUntil = Duration(hours: 4);

  static Future<List<Map<String, dynamic>>> _load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_key);
      if (raw == null) return [];
      final list = jsonDecode(raw);
      if (list is! List) return [];
      return [
        for (final item in list)
          if (item is Map && item['id'] is String && item['at'] is int)
            Map<String, dynamic>.from(item),
      ];
    } catch (e) {
      debugPrint('FollowUps.load: $e');
      return [];
    }
  }

  static Future<void> _save(List<Map<String, dynamic>> items) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_key, jsonEncode(items));
    } catch (e) {
      debugPrint('FollowUps.save: $e');
    }
  }

  /// Var tipset gäller, kort: första platsen, annars titeln.
  static String placeOf(Map<String, dynamic> alert) {
    final places = alert['places'];
    if (places is List && places.isNotEmpty) {
      final first = places.first?.toString().trim() ?? '';
      if (first.isNotEmpty) return first;
    }
    final title = (alert['title'] ?? '').toString().trim();
    return title.length > 40 ? '${title.substring(0, 39)}…' : title;
  }

  /// Föraren tryckte "Kör dit". Samma tips igen flyttar inte frågan framåt:
  /// det är den första körningen frågan gäller.
  static Future<void> remember(
    Map<String, dynamic> alert, {
    DateTime? now,
  }) async {
    final id = alert['id']?.toString();
    if (id == null || id.isEmpty) return;
    final items = await _load();
    if (items.any((i) => i['id'] == id)) return;
    items.add({
      'id': id,
      'place': placeOf(alert),
      'at': (now ?? DateTime.now()).millisecondsSinceEpoch,
      'done': false,
    });
    while (items.length > maxItems) {
      items.removeAt(0);
    }
    await _save(items);
  }

  /// Den äldsta frågan som är mogen och obesvarad, eller null.
  static Future<FollowUp?> due({DateTime? now}) async {
    final t = now ?? DateTime.now();
    final items = await _load();
    for (final item in items) {
      if (item['done'] == true) continue;
      final at = DateTime.fromMillisecondsSinceEpoch(item['at'] as int);
      final age = t.difference(at);
      if (age < askAfter || age > askUntil) continue;
      final id = item['id'] as String;
      // Redan besvarat i bladet: ingen anledning att fråga igen.
      if (await FeedbackChoices.get(id) != null) continue;
      return FollowUp(id: id, place: (item['place'] ?? '').toString(), at: at);
    }
    return null;
  }

  /// Besvarad eller bortklickad: frågan ställs inte igen.
  static Future<void> done(String id) async {
    final items = await _load();
    for (final item in items) {
      if (item['id'] == id) item['done'] = true;
    }
    await _save(items);
  }
}
