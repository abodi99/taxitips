/// ApiClient för demoläget: svarar med påhittad data ur demo_data.dart och
/// pratar aldrig med en server.
///
/// Varje metod som skärmarna i förarappen kan anropa är överskriven. Läsningar
/// ger demodata; skrivningar (favoriter, inställningar, support, parkoppling)
/// antingen sker lokalt i minnet eller avvisas med [demoSavesNothing]. Inget
/// här rör nätet, Supabase eller enhetens lagrade inloggning.
library;

import '../api_client.dart';
import 'demo_data.dart';

/// Texten när något inte kan sparas i demoläget.
const demoSavesNothing = 'I demoläget sparas inget';

class DemoApiClient extends ApiClient {
  DemoApiClient()
    : super(supabaseUrl: 'demo://ingen-server', supabaseAnonKey: 'demo');

  /// Sparade tips, bara i minnet. Försvinner när demon avslutas.
  final Set<String> _favoriteIds = {...DemoData.initialFavoriteIds};

  /// Antal anrop som *skulle* ha gått till en server. Alltid noll: finns för
  /// att testet ska kunna säga det rakt ut.
  int get networkCalls => 0;

  DemoSnapshot get _snapshot => DemoData.build(favoriteIds: _favoriteIds);

  static Never _refuse() => throw ApiException(403, demoSavesNothing);

  // --- Läsningar ----------------------------------------------------------

  @override
  Future<void> ensureInitialized() async {}

  @override
  bool get supportsFavorites => true;

  @override
  bool get canUseSupport => false;

  @override
  Future<Map<String, dynamic>> taxi({
    bool demo = false,
    double? userLat,
    double? userLon,
    List<String>? regions,
    List<String>? counties,
    List<String>? municipalities,
    bool roadAll = false,
  }) async {
    final s = _snapshot;
    final all = [for (final a in s.alerts) Map<String, dynamic>.from(a)];
    final favorites = [
      for (final a in all)
        if (_favoriteIds.contains(a['id'])) Map<String, dynamic>.from(a),
    ];
    final roadCount = all.where((a) => a['kind'] == 'road').length;
    return {
      'alerts': all,
      'favorites': favorites,
      'active': all,
      'week': all,
      'events': const [],
      'placeStats': const [],
      'demo': true,
      'roadTotal': roadCount,
      'roadAll': roadAll,
      'updatedAt': DateTime.now().millisecondsSinceEpoch,
      'source': 'demo',
      'needsArea': false,
      // Ingen `features`: inget är låst i demon.
    };
  }

  @override
  Future<Map<String, dynamic>> entitlements() async => {
    'ok': true,
    'entitled': true,
    'licensedCounties': const ['01'],
  };

  @override
  Future<Map<String, dynamic>> ferries({
    double? lat,
    double? lon,
    List<String>? counties,
    List<String>? municipalities,
  }) async {
    final s = _snapshot;
    return {
      'arrivals': s.ferries,
      'ferries': s.ferryShips,
      'terminals': s.terminals,
      'attribution': 'Påhittade exempel',
    };
  }

  @override
  Future<Map<String, dynamic>> events({
    double? lat,
    double? lon,
    List<String>? counties,
    List<String>? municipalities,
    String? from,
    String? to,
  }) async {
    final s = _snapshot;
    final list = [
      for (final e in s.events)
        if (e['ongoing'] == true ||
            ((from == null ||
                    (e['startDate'] as String).compareTo(from) >= 0) &&
                (to == null || (e['startDate'] as String).compareTo(to) <= 0)))
          e,
    ];
    final counts = <String, int>{};
    for (final e in list) {
      final d = e['startDate'] as String;
      counts[d] = (counts[d] ?? 0) + 1;
    }
    return {
      'events': list,
      'dayCounts': counts,
      'entitled': true,
      'preview': false,
      'maxDays': 30,
      'attribution': 'Påhittade exempel',
    };
  }

  @override
  Future<Map<String, dynamic>> opportunityDetail(String opportunityId) async {
    final found = _snapshot.alerts.where((a) => a['id'] == opportunityId);
    if (found.isEmpty) return {};
    return {
      'opportunity': Map<String, dynamic>.from(found.first),
      'source_events': const [],
    };
  }

  @override
  Future<Map<String, dynamic>?> alertById(String opportunityId) async {
    final found = _snapshot.alerts.where((a) => a['id'] == opportunityId);
    return found.isEmpty ? null : Map<String, dynamic>.from(found.first);
  }

  @override
  Future<List<Map<String, dynamic>>> favorites({
    double? userLat,
    double? userLon,
  }) async => [
    for (final a in _snapshot.alerts)
      if (_favoriteIds.contains(a['id'])) a,
  ];

  @override
  Future<Map<String, dynamic>> notifications() async => {
    'notifications': _snapshot.notifications,
    'reason': null,
    'hint': null,
  };

  @override
  Future<Map<String, dynamic>> getNotifyPrefs() async => {
    'prefs': const <String, dynamic>{},
    'municipalityCatalog': const <String, dynamic>{},
  };

  @override
  Future<int> supportUnread() async => 0;

  @override
  Future<void> refreshPresence({double? lat, double? lon}) async {}

  @override
  Future<bool> onDuty() async => false;

  // --- Skrivningar: lokalt eller avvisade -----------------------------------

  /// Favoriter fungerar, men bara i minnet.
  @override
  Future<bool> setFavorite({
    required String opportunityId,
    required bool favorite,
    String? note,
  }) async {
    if (favorite) {
      _favoriteIds.add(opportunityId);
    } else {
      _favoriteIds.remove(opportunityId);
    }
    return favorite;
  }

  /// 🚕 / 👍 / 👎 "sparas" bara som en bock på skärmen.
  @override
  Future<Map<String, dynamic>> submitAlertFeedback(
    String alertId,
    bool result, {
    String? verdict,
  }) async => {'success': true, 'demo': true};

  @override
  Future<Map<String, dynamic>> saveNotifyPrefs({
    List<String>? regions,
    List<String>? cities,
    List<String>? counties,
    List<String>? municipalities,
    Map<String, bool>? types,
    Map<String, bool>? categories,
    String? minLevel,
    bool? enabled,
    double? pauseHours,
  }) async => _refuse();

  @override
  Future<void> setOnDuty(bool on, {double? lat, double? lon}) async =>
      _refuse();

  @override
  Future<Map<String, dynamic>> supportConversation({
    bool markRead = false,
  }) async => _refuse();

  @override
  Future<Map<String, dynamic>> sendSupportMessage(String body) async =>
      _refuse();

  @override
  Future<Map<String, dynamic>> fleetStatus() async => _refuse();

  @override
  Future<Map<String, dynamic>> startVehicleSession({
    required String licenseId,
    bool force = false,
  }) async => _refuse();

  @override
  Future<Map<String, dynamic>> endVehicleSession() async => _refuse();

  @override
  Future<Map<String, dynamic>> claimInvite(String token) async => _refuse();

  @override
  Future<Map<String, dynamic>> registerPushToken({
    required String fcmToken,
    String label = '',
    String platform = '',
  }) async => _refuse();
}
