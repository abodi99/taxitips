import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/api_client.dart';

/// Appens riktiga typsnitt. Utan dem ritar testerna med Ahem, där varje tecken
/// är en hel fyrkant -- texten blir dubbelt så bred och ett test som letar
/// spill över kanten larmar för sådant som aldrig händer på en telefon.
Future<void> loadAppFonts() async {
  Future<void> load(String family, List<String> files) async {
    final loader = FontLoader(family);
    for (final f in files) {
      loader.addFont(rootBundle.load('fonts/$f'));
    }
    await loader.load();
  }

  const inter = [
    'Inter-Regular.ttf',
    'Inter-Medium.ttf',
    'Inter-SemiBold.ttf',
    'Inter-Bold.ttf',
  ];
  await load('Inter', inter);
  await load('Montserrat', ['Montserrat-SemiBold.ttf', 'Montserrat-Bold.ttf']);
  // Text utan angiven familj (t.ex. inuti flutter_map) ritas i testerna med
  // Ahem. På en telefon blir det systemets typsnitt, ungefär lika brett som
  // Inter -- så Inter tar Ahems plats här.
  await load('Ahem', inter);
}

/// En server som svarar med tre tips och inget annat -- till de test som
/// pumpar förarskärmen. Inget går ut på nätet.
class FakeDriverApi extends ApiClient {
  FakeDriverApi({
    this.owner = false,
    this.tips = true,
    String? device = 'enhet',
  }) : super(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x') {
    deviceToken = device;
    if (owner) sessionToken = 'session';
  }

  final bool owner;
  final bool tips;

  @override
  Future<Map<String, dynamic>> taxi({
    double? userLat,
    double? userLon,
    List<String>? regions,
    List<String>? counties,
    List<String>? municipalities,
    bool roadAll = false,
  }) async {
    final rows = tips ? sampleTips() : <Map<String, dynamic>>[];
    return {
      'alerts': rows,
      'favorites': const [],
      'active': rows,
      'week': rows,
      'events': const [],
      'placeStats': const {},
      'source': 'django',
    };
  }

  @override
  Future<Map<String, dynamic>> entitlements() async => {
    'ok': true,
    'entitled': true,
    'licensedCounties': const ['14'],
    'unrestrictedCounties': false,
  };

  @override
  Future<Map<String, dynamic>> ferries({
    double? lat,
    double? lon,
    List<String>? counties,
    List<String>? municipalities,
  }) async => const {'ferries': [], 'terminals': []};

  @override
  Future<Map<String, dynamic>> events({
    double? lat,
    double? lon,
    List<String>? counties,
    List<String>? municipalities,
    String? from,
    String? to,
  }) async => const {'events': []};

  @override
  Future<void> refreshPresence({double? lat, double? lon}) async {}

  @override
  Future<int> flushPendingFeedback() async => 0;

  @override
  Future<int> supportUnread() async => 0;

  @override
  Future<Map<String, dynamic>> getNotifyPrefs() async => {
    'licensedCounties': const ['14'],
    'countyCatalog': [
      {'code': '14', 'name': 'Västra Götalands län'},
    ],
    'prefs': const {'counties': <String>[]},
  };

  @override
  Future<Map<String, dynamic>> fleetStatus() async => {
    'company': {'name': 'Test Taxi AB'},
    'vehicles': [
      {'plate': 'ABC123', 'isMine': true},
    ],
  };

  @override
  Future<Map<String, dynamic>> fleetCompany() async => {
    'company': {'name': 'Test Taxi AB'},
    'licenses': const [],
    'permissions': const ['manage_vehicles', 'manage_devices'],
  };

  @override
  void listenForAuthSignIn(void Function() onSignedIn) {}

  @override
  Future<void> ensureInitialized() async {}

  @override
  Future<void> loadTokens() async {}

  @override
  Future<Map<String, dynamic>> me() async => {};
}

/// Tre tips så som appen läser dem (api_client `_alertFromRow`): ett starkt
/// tåg, ett medelstarkt flyg och ett "Övrigt" från trafikbolaget.
List<Map<String, dynamic>> sampleTips() {
  final now = DateTime.now().toUtc();
  String iso(Duration d) => now.add(d).toIso8601String();
  Map<String, dynamic> tip(
    String id,
    String stop,
    String level, {
    bool minor = false,
    String kind = 'transit',
    String tier = 'vehicle_cancelled',
  }) => {
    'id': id,
    'title': 'Tåg inställt',
    'summary': 'Tåg mellan $stop och Alingsås är inställt.',
    'kind': kind,
    'mode': 'train',
    'severity_tier': minor ? 'ignore' : tier,
    'minor': minor,
    'confidence': 'high',
    'rule_id': 'rail.vehicle_cancelled',
    'stop_name': stop,
    'lat': 57.708,
    'lon': 11.973,
    'countyName': 'Västra Götalands län',
    'taxi': {
      'places': [stop],
      'level': level,
    },
    'level': level,
    'is_active': true,
    'is_favorite': false,
    'start_time': iso(const Duration(minutes: -25)),
    'end_time': iso(const Duration(minutes: 70)),
    'worth_it_score': switch (level) {
      'high' => 80,
      'medium' => 55,
      _ => 20,
    },
    'factors': const [],
  };
  return [
    tip('t1', 'Göteborg C', 'high'),
    tip('t2', 'Landvetter flygplats', 'medium', kind: 'flight'),
    tip('t3', 'Alingsås', 'low', minor: true),
  ];
}

/// Pumpar tills förarskärmen hunnit hämta tipsen och starta det den ska.
Future<void> settleDriverScreen(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 500));
  }
}

/// Byter ut skärmen mot en tom och släpper alla timers.
Future<void> disposeScreen(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(milliseconds: 100));
}
