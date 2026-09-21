import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// Evenemang föraren följer, sparade på telefonen.
///
/// Tips följs på servern (`OpportunityFavorite`), men ett evenemang är inte
/// ett tips -- det har ingen rad i opportunities att peka på. Att följa en
/// match lördag kväll är en påminnelse för den här föraren, inte något
/// bolaget behöver dela, så telefonen räcker.
///
/// En kopia av evenemanget sparas, inte bara id:t: annars försvann det ur
/// listan så fort det låg utanför det datumfönster som råkade vara laddat.
/// Passerade evenemang rensas bort (dagen efter att de slutat).
class FollowedEvents {
  FollowedEvents._();

  static const _key = 'tb_followed_events_v1';

  static Future<Map<String, Map<String, dynamic>>> load({DateTime? now}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_key);
      if (raw == null || raw.isEmpty) return {};
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return {};
      final out = <String, Map<String, dynamic>>{};
      for (final entry in decoded.entries) {
        if (entry.value is Map) {
          final event = Map<String, dynamic>.from(entry.value as Map);
          if (!isPast(event, now: now)) out[entry.key.toString()] = event;
        }
      }
      return out;
    } catch (_) {
      return {};
    }
  }

  static Future<void> save(Map<String, Map<String, dynamic>> events) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_key, jsonEncode(events));
    } catch (_) {
      // Bekvämlighet, inte funktion: utan lagring följs evenemanget bara
      // så länge appen är öppen.
    }
  }

  /// Slutdagen passerad (eller startdagen om slutet är okänt).
  static bool isPast(Map event, {DateTime? now}) {
    final day = (event['endDate'] ?? event['startDate'])?.toString();
    final date = day == null ? null : DateTime.tryParse(day);
    if (date == null) return false;
    final today = now ?? DateTime.now();
    final lastDay = DateTime(date.year, date.month, date.day);
    return DateTime(today.year, today.month, today.day).isAfter(lastDay);
  }
}
