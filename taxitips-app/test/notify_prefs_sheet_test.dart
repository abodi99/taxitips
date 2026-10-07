import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/membership_copy.dart';
import 'package:taxitips_app/widgets/notify_prefs_sheet.dart';

/// Servern som notisbladet ser den: /api/notify-prefs med lägena
/// (core/notify_prefs.py). Inget går ut på nätet; det appen skickar sparas.
class _FakeApi extends ApiClient {
  _FakeApi({this.withPresets = true})
    : super(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x');

  String preset = 'recommended';
  final bool withPresets;
  Map<String, dynamic> prefs = {
    'counties': ['12'],
  };
  final sent = <Map<String, dynamic>>[];

  @override
  Future<bool> onDuty() async => false;

  @override
  Future<Map<String, dynamic>> getNotifyPrefs() async => {
    'prefs': prefs,
    'readOnly': false,
    'countyCatalog': const [
      {'code': '12', 'name': 'Skåne län'},
    ],
    'licensedCounties': const ['12'],
    'categoryCatalog': const [
      {'id': 'transit', 'label': 'Tåg & buss'},
      {'id': 'road', 'label': 'Väg'},
    ],
    'features': const {
      'plan': 'trial',
      'categories': ['transit'],
      'locked': ['road'],
    },
    'meta': {
      'catalog': const [
        {
          'id': 'line_paused',
          'label': 'Hela linjen står stilla',
          'notifiable': true,
          'weakOnly': false,
          'defaultOn': true,
        },
        {
          'id': 'line_delayed',
          'label': 'Förseningar',
          'notifiable': false,
          'weakOnly': true,
          'defaultOn': false,
        },
        {
          'id': 'road_work_or_queue',
          'label': 'Vägarbete eller köbildning',
          'notifiable': false,
          'weakOnly': false,
          'defaultOn': false,
        },
      ],
      'tips': const <String>[],
    },
    if (withPresets) ...{
      'preset': preset,
      'presetCatalog': const [
        {
          'id': 'recommended',
          'label': 'Rekommenderat',
          'help': 'Bara starka tips.',
        },
        {
          'id': 'strongest',
          'label': 'Bara de starkaste',
          'help': 'Färre notiser.',
        },
        {
          'id': 'everything',
          'label': 'Allt i mina län',
          'help': 'Starka och svaga.',
        },
        {'id': 'silent', 'label': 'Tyst', 'help': 'Inga notiser.'},
      ],
      'weakMaxPerHour': 3,
      'maxPerHourChoices': const [2, 4, 6],
    },
  };

  @override
  Future<Map<String, dynamic>> saveNotifyRules(
    Map<String, dynamic> body,
  ) async {
    sent.add(body);
    prefs = {...prefs, ...body};
    if (body['preset'] == 'everything') prefs['weak'] = true;
    if (body.containsKey('weak')) preset = 'custom';
    if (body['preset'] is String) preset = body['preset'] as String;
    return {'prefs': prefs, 'preset': preset};
  }
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pump(WidgetTester tester, ApiClient api) async {
    tester.view.physicalSize = const Size(1170, 9000);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: NotifyPrefsSheet(api: api)),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('en låst kategori i provet visas neutralt, utan köpväg', (
    tester,
  ) async {
    await pump(tester, _FakeApi());
    expect(find.text(kNotInTrial), findsOneWidget);
    expect(find.textContaining('Köp'), findsNothing);
  });

  testWidgets('en typ som aldrig kan ge notis visas inte', (tester) async {
    await pump(tester, _FakeApi());
    await tester.tap(find.text('Fler val'));
    await tester.pumpAndSettle();
    expect(find.text('Förseningar'), findsOneWidget);
    expect(find.text('Vägarbete eller köbildning'), findsNothing);
  });

  testWidgets('en äldre server utan lägen ger samma blad som förut', (
    tester,
  ) async {
    await pump(tester, _FakeApi(withPresets: false));
    expect(find.text('Välj läge'), findsNothing);
    expect(find.text('Även svagare tips'), findsNothing);
    expect(find.text('Hur viktiga?'), findsOneWidget);
  });

  testWidgets('reglagen är korta: på/av, paus, kategorier och nivå', (
    tester,
  ) async {
    await pump(tester, _FakeApi());
    expect(find.text('Skicka notiser'), findsOneWidget);
    expect(find.text('Paus'), findsOneWidget);
    expect(find.text('Vilka notiser?'), findsOneWidget);
    expect(find.text('1 tim'), findsOneWidget);
  });
}
