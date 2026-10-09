import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/screens/driver_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/ferry_event_widgets.dart';
import 'package:taxitips_app/widgets/guided_tour.dart';

import 'driver_test_support.dart';

/// Färjekortet (ägarkrav 2026-10-09): bara det en förare behöver för att hämta
/// folk -- namn, ungefär hur stor, vid vilken kaj och när. Inga källor, inga
/// fartygsnummer, ingen fart eller kurs. Och kartan och listan visar samma färjor.

/// En rad så som /api/ferries skickar den (`rows`, maritime/views.py), med
/// tekniska fält som en äldre server kunde ha med -- de får aldrig synas.
Map<String, dynamic> ferryRow(
  int n, {
  String status = 'approaching',
  double lat = 57.70,
  double lon = 11.95,
}) {
  final at = DateTime.now().add(Duration(minutes: 10 + n));
  return {
    'id': 'ais:26500000$n',
    'name': 'STENA $n',
    'sizeLabel': 'Stor färja',
    'from': n == 0 ? 'Frederikshavn' : '',
    'terminal': 'goteborg',
    'portName': 'Göteborg Stena Line',
    'portLat': 57.70,
    'portLon': 11.95,
    'lat': lat + n * 0.002,
    'lon': lon,
    'course': 120.0,
    'status': status,
    'arrived': status == 'berthed',
    'expectedAt': status == 'berthed' ? null : at.toUtc().toIso8601String(),
    'etaMinutes': status == 'berthed' ? null : 10 + n,
    // Sådant som inte hör hemma hos föraren:
    'mmsi': 265000000 + n,
    'knots': 14.2,
    'lengthM': 222,
    'destination': 'SEGOT',
    'expectedBasis': 'AIS: sträcka till terminalen × farledsfaktor / fart',
    'source': 'tidtabell + AIS',
  };
}

void main() {
  setUpAll(loadAppFonts);

  Future<void> pumpCard(WidgetTester tester, Map<String, dynamic> f) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTaxiTheme(),
        home: Scaffold(
          body: Center(child: FerryCard(ferry: f)),
        ),
      ),
    );
  }

  final forbidden = RegExp(
    r'AIS|MMSI|AISStream|Trafiklab|GTFS|PredictHQ|knop|°|pipeline|farjor|urval|\d+ m\b',
  );

  testWidgets('kortet visar namn, storlek, kaj och ankomst -- inget annat', (
    tester,
  ) async {
    await pumpCard(tester, ferryRow(0));
    expect(find.text('STENA 0'), findsOneWidget);
    expect(find.text('Stor färja · Göteborg Stena Line'), findsOneWidget);
    expect(find.textContaining('Anländer ca'), findsOneWidget);
    expect(find.textContaining('om 10 min'), findsOneWidget);
    expect(find.text('Från Frederikshavn'), findsOneWidget);
    for (final t in tester.widgetList<Text>(find.byType(Text))) {
      expect(t.data ?? '', isNot(matches(forbidden)), reason: t.data);
    }
  });

  testWidgets('en färja vid kaj säger "Vid kaj"', (tester) async {
    await pumpCard(tester, ferryRow(1, status: 'berthed'));
    expect(find.text('Vid kaj'), findsOneWidget);
  });

  testWidgets('bladet: Kör dit och kajen, ingen källa eller teknik', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTaxiTheme(),
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showFerrySheet(
                context,
                {
                  ...ferryRow(0),
                  'pickupFrom': DateTime.now()
                      .add(const Duration(minutes: 20))
                      .toIso8601String(),
                  'pickupUntil': DateTime.now()
                      .add(const Duration(minutes: 55))
                      .toIso8601String(),
                },
                harborLat: 57.70,
                harborLon: 11.95,
              ),
              child: const Text('öppna'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('öppna'));
    await tester.pumpAndSettle();
    expect(find.text('Kör dit'), findsOneWidget);
    expect(find.text('Kaj'), findsOneWidget);
    expect(find.text('Folk kommer ut'), findsOneWidget);
    for (final t in tester.widgetList<Text>(find.byType(Text))) {
      expect(t.data ?? '', isNot(matches(forbidden)), reason: t.data);
    }
  });

  test('ett fartygsnummer blir aldrig ett namn', () {
    expect(ferryName({'name': 'MMSI 265000000'}), 'Färja');
    expect(
      ferryName({
        'vessel': {'name': 'VISBORG'},
      }),
      'VISBORG',
    );
  });

  test('äldre server utan rows: listan får ankomsterna OCH kartans fartyg', () {
    final rows = ferryRowsOf({
      'arrivals': [
        {
          'id': 'tt:1',
          'vessel': {'name': 'VISBORG'},
        },
      ],
      'ferries': [
        {'name': 'VISBORG', 'lat': 1.0, 'lon': 2.0},
        {'name': 'FINNPARTNER', 'lat': 1.0, 'lon': 2.0},
      ],
    });
    expect(rows.map(ferryName), ['VISBORG', 'FINNPARTNER']);
  });

  group('förarskärmen', () {
    setUp(
      () => SharedPreferences.setMockInitialValues({GuidedTour.seenKey: true}),
    );

    testWidgets('listan har alla färjor som kartan ritar', (tester) async {
      tester.view.physicalSize = const Size(420, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final rows = [
        for (var n = 0; n < 4; n++) ferryRow(n),
        ferryRow(4, status: 'berthed'),
        ferryRow(5, status: 'berthed'),
      ];
      final api = FakeDriverApi(tips: false)
        ..ferriesBody = {
          'rows': rows,
          // Det äldre urvalet: bara en ankomst. Listan får inte nöja sig med den.
          'arrivals': [rows.first],
          'ferries': rows,
          'terminals': [
            {
              'key': 'goteborg',
              'name': 'Göteborg Stena Line',
              'lat': 57.70,
              'lon': 11.95,
            },
          ],
        };
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: DriverScreen(api: api, onOpenSettings: () {}),
        ),
      );
      await settleDriverScreen(tester);

      // Färje-läget: kartans pilar och listans kort är samma sex färjor.
      await tester.tap(find.text('6 färjor'));
      await settleDriverScreen(tester);
      await tester.drag(
        find.textContaining('Färjor ·'),
        const Offset(0, -1500),
      );
      await settleDriverScreen(tester);

      expect(find.byType(FerryArrow), findsNWidgets(6));
      final cards = tester.widgetList<FerryCard>(find.byType(FerryCard));
      expect(
        cards.map((c) => c.ferry['id']).toSet(),
        rows.map((r) => r['id']).toSet(),
      );
      await disposeScreen(tester);
    });
  });
}
