import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/severity_labels.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/alert_feedback_bar.dart';
import 'package:taxitips_app/widgets/tip_sheet.dart';

/// Tipsbladet följer förarens frågor i ordning: vad och var, hur bråttom, värt
/// att köra dit, vad gör jag nu, mer om tipset. Särfallen (Övrigt, avslutat,
/// väghändelse) får ingen "värt att köra"-del.
void main() {
  final now = DateTime(2026, 10, 3, 20, 0);
  String iso(DateTime t) => t.toUtc().toIso8601String();

  /// Ett starkt tågtips med inställd avgång, ersättning och fyra skäl, så som
  /// backend (core/api.py `_serialize`) och appens `_alertFromRow` ger det.
  Map<String, dynamic> strongTip() => {
    'id': 't1',
    'title': 'Tåg inställt',
    'summary':
        'Tåg 123 mellan Göteborg C och Alingsås är inställt på grund av fordonsfel.',
    'kind': 'transit',
    'mode': 'train',
    'severity_tier': 'vehicle_cancelled',
    'minor': false,
    'confidence': 'high',
    'rule_id': 'rail.vehicle_cancelled',
    'lat': 57.708,
    'lon': 11.973,
    'countyName': 'Västra Götalands län',
    'taxi': {
      'places': ['Göteborg C'],
      'level': 'high',
    },
    'level': 'high',
    'is_active': true,
    'is_favorite': false,
    'start_time': iso(now.subtract(const Duration(minutes: 25))),
    'end_time': iso(now.add(const Duration(minutes: 70))),
    'compensation_eligible': true,
    'compensation_amount_kr': 1500,
    'compensation_per_person': true,
    'has_alternative': false,
    'factors': [
      {'text': 'Nästa tåg går först 1 tim 6 min senare', 'sign': '+'},
      {'text': 'Natt – nästan inga andra sätt att ta sig hem', 'sign': '+'},
      {
        'text': 'Resenären kan få taxin betald (upp till 1 500 kr)',
        'sign': '+',
      },
      {'text': 'Stor station – många resenärer', 'sign': '+'},
    ],
    'travel_options': {
      'summary': 'Inställd 20:12 mot Alingsås',
      'departure': {
        'at': iso(DateTime.now().add(const Duration(minutes: 12))),
        'clock': '20:12',
        'status': 'cancelled',
        'destination': 'Alingsås',
      },
      'gap_minutes': 66,
      'next_clock': '21:18',
      'is_last_departure': false,
      'has_alternative': false,
    },
  };

  /// Utan avgångstavla och utan ersättning: bara läget och skälen.
  Map<String, dynamic> plainTip() => strongTip()
    ..['compensation_eligible'] = false
    ..['travel_options'] = null
    ..['factors'] = [
      {'text': 'Hela linjen står still', 'sign': '+'},
      {'text': 'Natt – nästan inga andra sätt att ta sig hem', 'sign': '+'},
      {'text': 'Stor station – många resenärer', 'sign': '+'},
      {'text': 'Sent på kvällen – färre alternativ', 'sign': '+'},
    ];

  Map<String, dynamic> minorTip() => strongTip()
    ..['title'] = 'Spårvagn 7 har ändrad körväg'
    ..['summary'] = 'Spårvagn 7 kör en annan väg på grund av underhåll.'
    ..['severity_tier'] = 'ignore'
    ..['minor'] = true
    ..['level'] = 'low'
    ..['compensation_eligible'] = false
    ..['travel_options'] = null
    ..['factors'] = [];

  Map<String, dynamic> endedTip() => strongTip()
    ..['is_active'] = false
    ..['level'] = 'low'
    ..['factors'] = []
    ..['end_time'] = iso(now.subtract(const Duration(minutes: 8)));

  Map<String, dynamic> roadTip() => strongTip()
    ..['kind'] = 'road'
    ..['mode'] = 'road'
    ..['title'] = 'E6 Kungsbacka mot Göteborg'
    ..['summary'] = 'Olycka på E6 södergående. Ett körfält är avstängt.'
    ..['severity_tier'] = 'road_accident_or_closure'
    ..['rule_id'] = 'road.high.accident'
    ..['compensation_eligible'] = false
    ..['travel_options'] = null
    ..['factors'] = []
    ..['taxi'] = {'places': []};

  Future<void> pumpSheet(
    WidgetTester tester,
    Map<String, dynamic> alert, {
    Future<void> Function(bool)? onToggleFavorite,
    VoidCallback? onOpenSourcePage,
    VoidCallback? onClose,
    double? distanceKm = 3.2,
  }) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTaxiTheme(),
        home: Scaffold(
          body: Align(
            alignment: Alignment.bottomCenter,
            child: SizedBox(
              height: 720,
              child: TipSheetBody(
                alert: alert,
                api: ApiClient(
                  supabaseUrl: 'http://localhost',
                  supabaseAnonKey: 'x',
                ),
                distanceKm: distanceKm,
                now: now,
                onToggleFavorite: onToggleFavorite ?? (v) async {},
                onOpenSourcePage: onOpenSourcePage,
                onClose: onClose,
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();
  }

  double top(WidgetTester tester, Finder f) => tester.getTopLeft(f).dy;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    AlertFeedbackBar.debugAlwaysShow = true;
  });
  tearDown(() => AlertFeedbackBar.debugAlwaysShow = false);

  group('ordningen: förarens frågor uppifrån och ner', () {
    testWidgets('rubrik och plats före styrkan, styrkan före återkopplingen', (
      tester,
    ) async {
      await pumpSheet(tester, strongTip());

      final headline = find.text('En avgång inställd');
      final place = find.text('Göteborg C');
      final distance = find.text('3,2 km från dig');
      final board = find.text('INSTÄLLD');
      final timing = find.textContaining('Väntas sluta');
      final question = find.text('Är det värt att köra dit?');
      final strength = find.text('Stark signal');
      final compensation = find.textContaining('Resenären kan få taxin betald');
      final feedback = find.text('Hur gick det?');
      final report = find.text('Rapportera felaktigt tips');
      final more = find.text('Mer om tipset');

      for (final f in [
        headline,
        place,
        distance,
        board,
        timing,
        question,
        strength,
        compensation,
        feedback,
        report,
        more,
      ]) {
        expect(f, findsOneWidget);
      }

      final order = [
        top(tester, headline),
        top(tester, place),
        top(tester, distance),
        top(tester, board),
        top(tester, timing),
        top(tester, question),
        top(tester, strength),
        top(tester, compensation),
        top(tester, feedback),
        top(tester, report),
        top(tester, more),
      ];
      expect(order, orderedEquals([...order]..sort()));
      // Strikt stigande: ingen sak delar rad med en annan.
      for (var i = 1; i < order.length; i++) {
        expect(order[i], greaterThan(order[i - 1]));
      }
    });

    testWidgets('Kör dit och Spara ligger fast i nederkanten', (tester) async {
      await pumpSheet(tester, strongTip());

      final drive = find.widgetWithText(FilledButton, 'Kör dit · 3,2 km');
      final save = find.widgetWithText(OutlinedButton, 'Spara');
      expect(drive, findsOneWidget);
      expect(save, findsOneWidget);

      // Samma rad, Spara till höger om Kör dit, och längst ner på bladet.
      expect(top(tester, drive), top(tester, save));
      expect(
        tester.getTopLeft(save).dx,
        greaterThan(tester.getTopLeft(drive).dx),
      );
      expect(tester.getBottomLeft(drive).dy, greaterThan(844 - 90));
      // Stor tryckyta.
      expect(tester.getSize(drive).height, greaterThanOrEqualTo(56));
      expect(tester.getSize(save).height, greaterThanOrEqualTo(56));

      // Rullar föraren ner följer knapparna med: de är inte en del av innehållet.
      final before = top(tester, drive);
      await tester.drag(
        find.byType(SingleChildScrollView),
        const Offset(0, -300),
      );
      await tester.pump();
      expect(top(tester, drive), before);
    });

    testWidgets('alternativ trafik och källan ligger längst ner, hopfällda', (
      tester,
    ) async {
      final tip = strongTip();
      (tip['travel_options'] as Map)['has_alternative'] = true;
      (tip['travel_options'] as Map)['alternative'] =
          'Ersättningsbuss går från Lerum till Alingsås.';
      await pumpSheet(tester, tip);

      final alternative = find.text('Alternativ trafik');
      expect(alternative, findsOneWidget);
      expect(
        top(tester, alternative),
        greaterThan(top(tester, find.text('Mer om tipset'))),
      );
      // Ersättningsbussen står inte i avgångstavlan, bara under "Mer om tipset".
      expect(
        find.textContaining('Ersättningsbuss går från Lerum'),
        findsOneWidget,
      );

      // Källans text är hopfälld tills man öppnar den.
      expect(find.text('Typ'), findsNothing);
      final source = find.text('Hela meddelandet och källan');
      await tester.ensureVisible(source);
      await tester.tap(source);
      await tester.pump();
      expect(find.text('Typ'), findsOneWidget);
      expect(find.text('Tåg'), findsOneWidget);
      expect(find.text('Började'), findsOneWidget);
      expect(find.text('Slutar'), findsOneWidget);
      expect(find.textContaining('Hög'), findsOneWidget);
    });
  });

  group('värt att köra dit', () {
    testWidgets('ersättningen får en egen ruta och står inte två gånger', (
      tester,
    ) async {
      await pumpSheet(tester, strongTip());
      final sentence = find.textContaining('Resenären kan få taxin betald');
      expect(sentence, findsOneWidget);
      final text = (tester.widget(sentence) as Text).data!;
      // "kan få", aldrig "har rätt till"; beloppet med hårda mellanslag.
      expect(text, contains('upp till 1 500 kr per resenär'));
      expect(find.textContaining('har rätt'), findsNothing);
    });

    testWidgets('utan ersättning finns ingen ersättningsruta', (tester) async {
      await pumpSheet(tester, plainTip());
      expect(find.textContaining('taxin betald'), findsNothing);
    });

    testWidgets('de tre viktigaste skälen först, resten bakom Visa alla skäl', (
      tester,
    ) async {
      await pumpSheet(tester, plainTip());
      expect(find.text('Hela linjen står still'), findsOneWidget);
      expect(
        find.text('Natt – nästan inga andra sätt att ta sig hem'),
        findsOneWidget,
      );
      expect(find.text('Stor station – många resenärer'), findsOneWidget);
      expect(find.text('Sent på kvällen – färre alternativ'), findsNothing);

      final all = find.text('Visa alla skäl');
      await tester.ensureVisible(all);
      await tester.tap(all);
      await tester.pump();
      expect(find.text('Sent på kvällen – färre alternativ'), findsOneWidget);
      expect(find.text('Visa färre skäl'), findsOneWidget);
    });

    testWidgets('inget "Visa alla skäl" när alla skäl redan syns', (
      tester,
    ) async {
      final tip = plainTip()
        ..['factors'] = [
          {'text': 'Hela linjen står still', 'sign': '+'},
          {'text': 'Ersättningstrafik är insatt', 'sign': '-'},
        ];
      await pumpSheet(tester, tip);
      expect(find.text('Visa alla skäl'), findsNothing);
      expect(find.text('Ersättningstrafik är insatt'), findsOneWidget);
    });

    testWidgets('styrkan är en bedömning med försiktigt språk', (tester) async {
      await pumpSheet(tester, plainTip());
      expect(find.text('Stark signal'), findsOneWidget);
      expect(find.text('Troligt att folk behöver taxi här.'), findsOneWidget);

      final weak = plainTip()..['level'] = 'low';
      await pumpSheet(tester, weak);
      await tester.pumpAndSettle();
      expect(find.text('Svag signal'), findsOneWidget);
      expect(find.text('Troligen få som behöver taxi här.'), findsOneWidget);
      // Inget löfte: aldrig "kunder väntar".
      expect(find.textContaining('väntar'), findsNothing);
    });
  });

  group('särfall', () {
    testWidgets('Övrigt: meddelandet och platsen, ingen styrka', (
      tester,
    ) async {
      await pumpSheet(tester, minorTip());

      expect(find.text('Spårvagn 7 har ändrad körväg'), findsOneWidget);
      expect(find.text('Göteborg C'), findsOneWidget);
      expect(find.text('Trafikbolagets meddelande'), findsOneWidget);
      expect(
        find.text('Spårvagn 7 kör en annan väg på grund av underhåll.'),
        findsOneWidget,
      );
      // Ingen styrka och inget "värt att köra"-påstående.
      expect(find.text('Är det värt att köra dit?'), findsNothing);
      expect(find.textContaining('signal'), findsNothing);
      expect(find.text('Stark'), findsNothing);
      expect(
        find.textContaining('Vi bedömer inte om det är värt att köra dit'),
        findsOneWidget,
      );
      // Kör dit och Spara finns kvar.
      expect(
        find.widgetWithText(FilledButton, 'Kör dit · 3,2 km'),
        findsOneWidget,
      );
      expect(find.widgetWithText(OutlinedButton, 'Spara'), findsOneWidget);
    });

    testWidgets('minor räknas också när bara severity_tier säger ignore', (
      tester,
    ) async {
      final tip = minorTip()..remove('minor');
      await pumpSheet(tester, tip);
      expect(find.text('Är det värt att köra dit?'), findsNothing);
      expect(find.textContaining('signal'), findsNothing);
    });

    testWidgets('avslutat tips: tydligt slut, ingen uppmaning att köra', (
      tester,
    ) async {
      await pumpSheet(tester, endedTip());

      expect(find.text('Slut. Tipset gäller inte längre.'), findsOneWidget);
      expect(find.textContaining('Tog slut för 8 min sedan'), findsOneWidget);
      // Ingen styrka, inget "värt att köra", ingen "Kör dit"-huvudknapp.
      expect(find.text('Är det värt att köra dit?'), findsNothing);
      expect(find.textContaining('signal'), findsNothing);
      expect(find.textContaining('Kör dit'), findsNothing);
      expect(find.byType(FilledButton), findsNothing);
      // Avgången är kvar som sammanhang, under "Mer om tipset".
      expect(
        top(tester, find.text('INSTÄLLD')),
        greaterThan(top(tester, find.text('Mer om tipset'))),
      );
      // Navigeringen och Spara finns, men tyst.
      expect(
        find.widgetWithText(OutlinedButton, 'Öppna navigering'),
        findsOneWidget,
      );
      expect(find.widgetWithText(OutlinedButton, 'Spara'), findsOneWidget);
    });

    testWidgets('väghändelse: vägen dit, ingen körning och ingen styrka', (
      tester,
    ) async {
      await pumpSheet(tester, roadTip());

      expect(find.text('Olycka'), findsOneWidget);
      expect(find.text('E6 Kungsbacka mot Göteborg'), findsOneWidget);
      expect(find.text('Vägen dit'), findsOneWidget);
      expect(
        find.text('Räkna med kö, eller välj en annan väg.'),
        findsOneWidget,
      );
      expect(find.text('Är det värt att köra dit?'), findsNothing);
      expect(find.textContaining('signal'), findsNothing);
      expect(find.textContaining('Kör dit'), findsNothing);
      // Ett hinder lovar inga kunder: ingen "Hur gick det?", men rapporten finns.
      expect(find.text('Hur gick det?'), findsNothing);
      expect(find.text('Rapportera felaktigt tips'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Spara'), findsOneWidget);
    });
  });

  group('knapparna', () {
    testWidgets('Spara skickar valet och visar Sparat', (tester) async {
      final tip = strongTip();
      final calls = <bool>[];
      await pumpSheet(
        tester,
        tip,
        onToggleFavorite: (v) async {
          calls.add(v);
          tip['is_favorite'] = v;
        },
      );
      await tester.tap(find.text('Spara'));
      await tester.pump();
      await tester.pump();
      expect(calls, [true]);
      expect(find.text('Sparat'), findsOneWidget);

      await tester.tap(find.text('Sparat'));
      await tester.pump();
      await tester.pump();
      expect(calls, [true, false]);
      expect(find.text('Spara'), findsOneWidget);
    });

    testWidgets('misslyckas sparandet backar knappen', (tester) async {
      final tip = strongTip();
      // Som skärmens _toggleFavorite: den återställer tipset vid fel.
      await pumpSheet(tester, tip, onToggleFavorite: (v) async {});
      await tester.tap(find.text('Spara'));
      await tester.pump();
      await tester.pump();
      expect(find.text('Spara'), findsOneWidget);
      expect(find.text('Sparat'), findsNothing);
    });

    testWidgets('utan stöd för favoriter finns ingen Spara-knapp', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: Scaffold(
            body: TipSheetBody(
              alert: strongTip(),
              api: ApiClient(
                supabaseUrl: 'http://localhost',
                supabaseAnonKey: 'x',
              ),
              now: now,
            ),
          ),
        ),
      );
      expect(find.text('Spara'), findsNothing);
      expect(find.widgetWithText(FilledButton, 'Kör dit'), findsOneWidget);
    });

    testWidgets('Fick körning och Ingen kund finns kvar efter beslutet', (
      tester,
    ) async {
      await pumpSheet(tester, strongTip());
      expect(find.text('Fick körning'), findsOneWidget);
      expect(find.text('Ingen kund'), findsOneWidget);
    });

    testWidgets('trafikbolagets sida öppnas från källrutan', (tester) async {
      var opened = 0;
      await pumpSheet(tester, strongTip(), onOpenSourcePage: () => opened++);
      final source = find.text('Hela meddelandet och källan');
      await tester.ensureVisible(source);
      await tester.tap(source);
      await tester.pump();
      final link = find.text('Trafikbolagets sida');
      await tester.ensureVisible(link);
      await tester.tap(link);
      expect(opened, 1);
    });

    testWidgets('utan egen sida finns ingen länk', (tester) async {
      await pumpSheet(tester, strongTip());
      final source = find.text('Hela meddelandet och källan');
      await tester.ensureVisible(source);
      await tester.tap(source);
      await tester.pump();
      expect(find.text('Typ'), findsOneWidget);
      expect(find.text('Trafikbolagets sida'), findsNothing);
    });

    testWidgets('krysset stänger bladet', (tester) async {
      var closed = 0;
      await pumpSheet(tester, strongTip(), onClose: () => closed++);
      final close = find.byTooltip('Stäng');
      expect(tester.getSize(close).width, greaterThanOrEqualTo(48));
      await tester.tap(close);
      expect(closed, 1);
    });

    testWidgets('lång text fälls ut med Visa hela texten', (tester) async {
      final long = List.filled(12, 'Spårvagnen kör en annan väg.').join(' ');
      await pumpSheet(tester, minorTip()..['summary'] = long);
      expect(find.text(long), findsNothing);
      final more = find.text('Visa hela texten');
      await tester.ensureVisible(more);
      await tester.tap(more);
      await tester.pump();
      expect(find.text(long), findsOneWidget);
    });
  });

  group('i det riktiga bladet', () {
    /// Samma uppsättning som driver_screen.dart: dragbart blad med bladets
    /// egen rullning kopplad till innehållet.
    Future<void> openSheet(
      WidgetTester tester,
      Map<String, dynamic> tip,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: Builder(
            builder: (context) => Scaffold(
              body: Center(
                child: TextButton(
                  onPressed: () => showModalBottomSheet<void>(
                    context: context,
                    isScrollControlled: true,
                    backgroundColor: Colors.transparent,
                    builder: (ctx) => DraggableScrollableSheet(
                      expand: false,
                      initialChildSize: 0.85,
                      minChildSize: 0.35,
                      maxChildSize: 0.96,
                      snap: true,
                      snapSizes: const [0.35, 0.85, 0.96],
                      shouldCloseOnMinExtent: true,
                      builder: (_, controller) => TipSheetBody(
                        alert: tip,
                        api: ApiClient(
                          supabaseUrl: 'http://localhost',
                          supabaseAnonKey: 'x',
                        ),
                        scrollController: controller,
                        distanceKm: 3.2,
                        now: now,
                        onToggleFavorite: (v) async {},
                        onClose: () => Navigator.pop(ctx),
                      ),
                    ),
                  ),
                  child: const Text('Öppna'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Öppna'));
      await tester.pumpAndSettle();
    }

    testWidgets('visar beslutet och knapparna utan att rulla', (tester) async {
      await openSheet(tester, strongTip());
      expect(tester.takeException(), isNull);
      // På 0,85 av en 844 hög skärm syns rubrik, plats, tavla och styrkan...
      final strength = find.text('Stark signal');
      expect(strength, findsOneWidget);
      expect(top(tester, strength), lessThan(844 - 90));
      // ...och Kör dit ligger i nederkanten.
      final drive = find.widgetWithText(FilledButton, 'Kör dit · 3,2 km');
      expect(tester.getBottomLeft(drive).dy, greaterThan(844 - 90));
    });

    testWidgets('att dra ner i rubriken stänger bladet', (tester) async {
      await openSheet(tester, strongTip());
      await tester.drag(find.text('En avgång inställd'), const Offset(0, 700));
      await tester.pumpAndSettle();
      expect(find.byType(TipSheetBody), findsNothing);
    });

    testWidgets('krysset stänger bladet', (tester) async {
      await openSheet(tester, strongTip());
      await tester.tap(find.byTooltip('Stäng'));
      await tester.pumpAndSettle();
      expect(find.byType(TipSheetBody), findsNothing);
    });
  });

  group('inget om köp', () {
    testWidgets('ingen köpknapp, inget pris att betala, ingen betallänk', (
      tester,
    ) async {
      await pumpSheet(tester, strongTip());
      final forbidden = RegExp(
        r'uppgradera|prenumer|köp |betala dig|checkout|stripe|/mån|per månad',
        caseSensitive: false,
      );
      final texts = tester.widgetList<Text>(find.byType(Text));
      for (final t in texts) {
        expect(forbidden.hasMatch(t.data ?? ''), isFalse, reason: t.data);
      }
    });
  });

  group('hjälparna', () {
    test('rubriken är klarspråk, ett meddelande får sin egen titel', () {
      expect(tipHeadline(strongTip()), 'En avgång inställd');
      expect(
        tipHeadline({'severity_tier': 'line_paused', 'kind': 'transit'}),
        'Hela linjen är stoppad',
      );
      expect(tipHeadline(roadTip()), 'Olycka');
      expect(tipHeadline(minorTip()), 'Spårvagn 7 har ändrad körväg');
      // Okänd typ: kategorins ord, aldrig en tom rubrik.
      expect(tipHeadline({'kind': 'flight', 'severity_tier': 'x'}), 'Flyg');
    });

    test(
      'platsen: hållplats eller ort, annars titeln -- aldrig för Övrigt',
      () {
        expect(tipPlace(strongTip()), 'Göteborg C');
        expect(tipPlace({'stop_name': 'Brunnsparken'}), 'Brunnsparken');
        expect(tipPlace({'title': 'Tåg inställt', 'mode': 'train'}), isNotNull);
        expect(
          tipPlace({'title': 'Ändrad körväg', 'severity_tier': 'ignore'}),
          isNull,
        );
      },
    );

    test('Övrigt, slut och väg känns igen', () {
      expect(isMinorTip({'minor': true}), isTrue);
      expect(isMinorTip({'severity_tier': 'ignore'}), isTrue);
      expect(isMinorTip(strongTip()), isFalse);
      expect(isEndedTip({'is_active': false}), isTrue);
      expect(isEndedTip({}), isFalse);
      expect(isRoadTip({'kind': 'road'}), isTrue);
      expect(isRoadTip(strongTip()), isFalse);
    });

    test('tiderna räknas mot klockan, aldrig negativt', () {
      expect(
        startedPhrase(now.subtract(const Duration(minutes: 25)), now),
        'Började för 25 min sedan',
      );
      expect(
        startedPhrase(now.add(const Duration(minutes: 40)), now),
        'Börjar om 40 min',
      );
      expect(
        startedPhrase(now.subtract(const Duration(seconds: 20)), now),
        'Började nyss',
      );
      expect(
        startedPhrase(now.add(const Duration(seconds: 20)), now),
        'Börjar nu',
      );
      expect(
        endsPhrase(now.add(const Duration(minutes: 70)), now),
        'Väntas sluta om 1 tim 10 min',
      );
      expect(
        endsPhrase(now.add(const Duration(seconds: 30)), now),
        'Slutar nu',
      );
      expect(
        endsPhrase(now.subtract(const Duration(minutes: 5)), now),
        'Slutar nu',
      );
      expect(
        endedPhrase(now.subtract(const Duration(minutes: 8)), now),
        'Tog slut för 8 min sedan',
      );
      expect(
        endedPhrase(now.subtract(const Duration(seconds: 10)), now),
        'Tog slut nyss',
      );
      expect(
        startedPhrase(now.subtract(const Duration(days: 4)), now),
        'Började för 4 d sedan',
      );
    });

    test('skälen: utan väntan som tavlan visar och utan ersättningen', () {
      final texts = [for (final f in tipFactors(strongTip())) f.text];
      expect(texts, [
        'Natt – nästan inga andra sätt att ta sig hem',
        'Stor station – många resenärer',
      ]);
      // Utan tavla och utan ersättning står alla fyra kvar.
      expect(tipFactors(plainTip()), hasLength(4));
    });

    test('ersättningsmeningen: kan få, belopp och per vem', () {
      expect(
        compensationSentence(1500, perPerson: true),
        'Resenären kan få taxin betald upp till 1 500 kr per resenär',
      );
      expect(
        compensationSentence(2960, perPerson: false),
        'Resenären kan få taxin betald upp till 2 960 kr per resa',
      );
      expect(
        compensationSentence(800),
        'Resenären kan få taxin betald upp till 800 kr',
      );
      // Inget belopp: inget påstående om belopp.
      expect(compensationSentence(null), 'Resenären kan få taxin betald');
    });
  });
}
