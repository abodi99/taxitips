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
    expect(find.textContaining('Lägger till'), findsOneWidget);
    expect(find.textContaining('om 10 min'), findsOneWidget);
    expect(find.text('Från Frederikshavn'), findsOneWidget);
    for (final t in tester.widgetList<Text>(find.byType(Text))) {
      expect(t.data ?? '', isNot(matches(forbidden)), reason: t.data);
    }
  });

  testWidgets('en färja vid kaj utan tid säger "Vid kaj"', (tester) async {
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
    // En äldre rad utan beslutsfälten: inga tomma rader eller avsnitt.
    expect(find.text('Sammanhang'), findsNothing);
    expect(find.text('Försening'), findsNothing);
    expect(find.text('Hur säkert'), findsNothing);
    for (final t in tester.widgetList<Text>(find.byType(Text))) {
      expect(t.data ?? '', isNot(matches(forbidden)), reason: t.data);
    }
  });

  group('beslutsunderlaget (ägarkrav 2026-10-11)', () {
    final now = DateTime(2026, 10, 11, 14, 10);
    String iso(int minutes) =>
        now.add(Duration(minutes: minutes)).toUtc().toIso8601String();

    /// En rad med allt servern kan veta: Gotlandsfärjan, sedd på väg in, 12 min sen.
    Map<String, dynamic> rich({bool confirmed = true}) => {
      'id': 'tt:2026-10-11:T1',
      'name': 'VISBORG',
      'sizeLabel': 'Stor färja',
      'kindLabel': 'Stor färja',
      'kindDetail': 'Många kliver av, ofta med bagage och utan bil.',
      'from': 'Visby',
      'terminal': 'nynashamn',
      'portName': 'Nynäshamns färjeterminal',
      'portLat': 58.90,
      'portLon': 17.95,
      'lat': 58.80,
      'lon': 18.00,
      'status': 'approaching',
      'arrived': false,
      'expectedAt': iso(25),
      'etaMinutes': 25,
      'scheduledAt': iso(13),
      'delayMinutes': confirmed ? 12 : null,
      'confirmed': confirmed,
      'pickupFrom': iso(35),
      'pickupUntil': iso(70),
      'operator': 'Destination Gotland',
      'route': 'Visby - Nynäshamn',
      'departedFrom': 'Visby',
      'departedAt': iso(-170),
      'international': false,
      'sameTerminalSoon': {'count': 1, 'nextAt': iso(40)},
      'terminalNote':
          'Buss, spårvagn eller tåg finns nära kajen: en del åker kollektivt vidare.',
    };

    String clock(int minutes) {
      final t = now.add(Duration(minutes: minutes));
      return '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    }

    final technical = RegExp(
      r'AIS|MMSI|AISStream|Trafiklab|GTFS|Trafikanalys|knop|kurs|fart\b|°|passagerare|miljoner',
      caseSensitive: false,
    );

    void noTechnicalWords(WidgetTester tester) {
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        expect(t.data ?? '', isNot(matches(technical)), reason: t.data);
        expect(t.data ?? '', isNot(matches(forbidden)), reason: t.data);
      }
    }

    testWidgets(
      'kortet: när, hämtning, försening, säkerhet, avstånd, varifrån',
      (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            theme: buildTaxiTheme(),
            home: Scaffold(
              body: Center(
                child: FerryCard(ferry: rich(), distanceKm: 12.4, now: now),
              ),
            ),
          ),
        );
        expect(find.text('VISBORG'), findsOneWidget);
        expect(
          find.text('Stor färja · Nynäshamns färjeterminal'),
          findsOneWidget,
        );
        expect(
          find.text('Lägger till ${clock(25)} · om 25 min'),
          findsOneWidget,
        );
        expect(
          find.text('Folk kommer ut ${clock(35)}–${clock(70)}'),
          findsOneWidget,
        );
        expect(find.text('12 min sen'), findsOneWidget);
        expect(find.text('Bekräftad'), findsOneWidget);
        expect(find.textContaining('12 km · ca'), findsOneWidget);
        expect(find.text('Från Visby, avgick ${clock(-170)}'), findsOneWidget);
        noTechnicalWords(tester);
      },
    );

    testWidgets(
      'kortet utan sett fartyg: "Enligt tidtabell", ingen försening',
      (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            theme: buildTaxiTheme(),
            home: Scaffold(
              body: Center(
                child: FerryCard(ferry: rich(confirmed: false), now: now),
              ),
            ),
          ),
        );
        expect(find.text('Enligt tidtabell'), findsOneWidget);
        expect(find.text('Bekräftad'), findsNothing);
        expect(find.textContaining('sen'), findsNothing);
        expect(find.text('I tid'), findsNothing);
        expect(find.textContaining('km'), findsNothing);
      },
    );

    testWidgets('kortet döljer det som saknas', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: Scaffold(
            body: Center(
              child: FerryCard(
                ferry: {
                  'id': 'ais:1',
                  'name': 'FINNPARTNER',
                  'sizeLabel': 'Stor färja',
                  'status': 'berthed',
                  'arrived': true,
                  'confirmed': true,
                  'from': '',
                },
                now: now,
              ),
            ),
          ),
        ),
      );
      expect(find.text('Vid kaj'), findsOneWidget);
      expect(find.textContaining('Folk kommer ut'), findsNothing);
      expect(find.textContaining('Från'), findsNothing);
      expect(find.textContaining('sen'), findsNothing);
    });

    test('vid kaj: sedan när, och tidtabellens tid sägs som tidtabell', () {
      final berthed = {
        ...rich(),
        'arrived': true,
        'status': 'berthed',
        'expectedAt': iso(-5),
      };
      expect(ferryEtaText(berthed, now: now), 'Vid kaj sedan ${clock(-5)}');
      expect(
        ferryEtaText({...berthed, 'confirmed': false}, now: now),
        'Skulle lägga till ${clock(-5)} enligt tidtabell',
      );
      expect(
        ferryConfidenceText(berthed),
        'Bekräftad – fartyget ligger vid kaj',
      );
    });

    test('förseningen i ord', () {
      expect(ferryDelayText({'delayMinutes': 12}), '12 min sen');
      expect(ferryDelayText({'delayMinutes': 1}), 'I tid');
      expect(ferryDelayText({'delayMinutes': -6}), '6 min tidig');
      expect(ferryDelayText({'delayMinutes': null}), '');
    });

    test('hämtningen pågår: "nu, till"', () {
      final f = {'pickupFrom': iso(-5), 'pickupUntil': iso(30)};
      expect(
        ferryPickupLine(f, now: now),
        'Folk kommer ut nu, till ${clock(30)}',
      );
      expect(
        ferryPickupLine({
          'pickupFrom': iso(-50),
          'pickupUntil': iso(-1),
        }, now: now),
        '',
      );
    });

    test('samma kaj: en eller flera', () {
      expect(
        ferrySameTerminalText({
          'sameTerminalSoon': {'count': 1, 'nextAt': iso(40)},
        }),
        '1 färja till anländer ${clock(40)}',
      );
      expect(
        ferrySameTerminalText({
          'sameTerminalSoon': {'count': 3, 'nextAt': iso(20)},
        }),
        '3 färjor till anländer, första ${clock(20)}',
      );
      expect(ferrySameTerminalText({'sameTerminalSoon': null}), '');
    });

    test('hinner du: framkomst mot hämtningsfönstret', () {
      final f = rich();
      // 12 km ≈ 21 min: framme före 35 min.
      expect(ferryReachText(f, 12, now: now), contains('före folk kommer ut'));
      expect(ferryReachText(f, 30, now: now), contains('medan folk kommer ut'));
      expect(ferryReachText(f, 80, now: now), contains('efter att de flesta'));
      expect(ferryReachText(f, null, now: now), '');
    });

    testWidgets('bladet: När, Var, Vilka kliver av, Sammanhang och Kör dit', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(420, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () => showFerrySheet(
                  context,
                  rich(),
                  harborLat: 58.90,
                  harborLon: 17.95,
                  distanceKm: 12.4,
                  now: now,
                ),
                child: const Text('öppna'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('öppna'));
      await tester.pumpAndSettle();
      for (final heading in ['När', 'Var', 'Vilka kliver av', 'Sammanhang']) {
        expect(find.text(heading), findsOneWidget, reason: heading);
      }
      expect(find.text('Kör dit'), findsOneWidget);
      expect(find.text('Lägger till ${clock(25)} · om 25 min'), findsOneWidget);
      expect(find.text('${clock(35)}–${clock(70)}'), findsOneWidget);
      expect(find.text(clock(13)), findsOneWidget); // tidtabellens tid
      expect(find.text('12 min sen'), findsOneWidget);
      expect(find.text('Bekräftad – fartyget är på väg in'), findsOneWidget);
      expect(find.text('Nynäshamns färjeterminal'), findsOneWidget);
      expect(find.textContaining('12 km · ca'), findsOneWidget);
      expect(find.textContaining('Framme ca'), findsOneWidget);
      expect(
        find.text(
          'Stor färja – många kliver av, ofta med bagage och utan bil.',
        ),
        findsOneWidget,
      );
      expect(find.text('Visby, avgick ${clock(-170)}'), findsOneWidget);
      expect(find.text('Destination Gotland'), findsOneWidget);
      expect(find.text('Visby - Nynäshamn'), findsOneWidget);
      expect(find.text('Utrikes'), findsNothing);
      expect(find.text('1 färja till anländer ${clock(40)}'), findsOneWidget);
      expect(find.textContaining('kollektivt vidare'), findsOneWidget);
      noTechnicalWords(tester);
    });

    testWidgets('bladet utan sett fartyg och utan sammanhang', (tester) async {
      tester.view.physicalSize = const Size(420, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () => showFerrySheet(context, {
                  ...rich(confirmed: false),
                  'sameTerminalSoon': null,
                  'terminalNote': null,
                  'operator': null,
                  'international': true,
                }, now: now),
                child: const Text('öppna'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('öppna'));
      await tester.pumpAndSettle();
      expect(find.text('Enligt tidtabell'), findsOneWidget);
      expect(find.text('Försening'), findsNothing);
      expect(find.text('Sammanhang'), findsNothing);
      expect(find.text('Rederi'), findsNothing);
      expect(find.text('Avstånd'), findsNothing);
      expect(find.text('Hinner du'), findsNothing);
      expect(find.text('Utrikes'), findsOneWidget);
      noTechnicalWords(tester);
    });
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
