import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/severity_labels.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/alert_feedback_bar.dart';
import 'package:taxitips_app/widgets/signal_card.dart';
import 'package:taxitips_app/widgets/tip_sheet.dart';

class _FakeApi extends ApiClient {
  _FakeApi() : super(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x');

  final reports = <({String id, String reason})>[];

  @override
  Future<Map<String, dynamic>> submitTipReport({
    required String opportunityId,
    String reason = '',
  }) async {
    reports.add((id: opportunityId, reason: reason));
    return {'ok': true};
  }
}

/// Tipsbladet i den återställda designen: snabbknappar överst, ett samlat
/// huvudkort (sträcka → status → händelse) och ett kombinerat kort för
/// särskilda omständigheter + taxiersättning. Särfallen (Övrigt, avslutat,
/// väghändelse) får ingen bedömning och ingen "Kör dit".
void main() {
  final now = DateTime(2026, 10, 3, 20, 0);
  String iso(DateTime t) => t.toUtc().toIso8601String();

  /// Ett starkt tågtips med inställd avgång, ersättning och skäl, så som
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

  /// Fyra skäl som alla ska synas som beslutsunderlag: de tre första direkt,
  /// det fjärde bakom "Visa alla skäl".
  Map<String, dynamic> manyFactorsTip() => strongTip()
    ..['compensation_eligible'] = false
    ..['travel_options'] = null
    ..['factors'] = [
      {'text': 'Natt – nästan inga andra sätt att ta sig hem', 'sign': '+'},
      {'text': 'Stor station – många resenärer', 'sign': '+'},
      {'text': 'Sent på kvällen – färre alternativ', 'sign': '+'},
      {'text': 'Halka på vägarna', 'sign': '+'},
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
    ..['compensation_eligible'] = false
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
    double? distanceKm,
    Future<void> Function(bool favorite)? onToggleFavorite,
    VoidCallback? onOpenSourcePage,
    VoidCallback? onClose,
    Future<void> Function(String url)? onOpenUrl,
    ApiClient? api,
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
                api:
                    api ??
                    ApiClient(
                      supabaseUrl: 'http://localhost',
                      supabaseAnonKey: 'x',
                    ),
                distanceKm: distanceKm,
                now: now,
                onToggleFavorite: onToggleFavorite ?? (v) async {},
                onOpenSourcePage: onOpenSourcePage,
                onOpenUrl: onOpenUrl,
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

  /// Detaljerna står öppna (ingen "Mer" att trycka på); kvar som ett steg
  /// i testerna så att de läses som förut.
  Future<void> openMore(WidgetTester tester) async {
    await tester.pumpAndSettle();
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    AlertFeedbackBar.debugAlwaysShow = true;
  });
  tearDown(() => AlertFeedbackBar.debugAlwaysShow = false);

  group('ordningen: snabbknappar överst, huvudkortet följer', () {
    testWidgets('innehållet först, knapparna efter', (tester) async {
      await pumpSheet(tester, strongTip(), distanceKm: 3.2);

      final drive = find.widgetWithText(FilledButton, 'Kör dit');
      final fare = find.text('Fick körning');
      expect(drive, findsOneWidget);
      expect(fare, findsOneWidget);
      expect(find.byTooltip('Spara tipset'), findsOneWidget);
      // Inget är hopfällt: huvudkortet syns utan ett tryck.
      expect(find.text('Mer'), findsNothing);

      final line = find.byKey(const ValueKey('tip-line-station'));
      final status = find.text('INSTÄLLD');
      final section = find.text('Händelse & beskrivning');
      for (final f in [line, status, section]) {
        expect(f, findsOneWidget);
      }
      expect((tester.widget(line) as Text).data, 'Tåg 123 → Alingsås');
      // Läsordningen: linje, status, källans text -- sedan knapparna.
      expect(top(tester, line), lessThan(top(tester, status)));
      expect(top(tester, status), lessThan(top(tester, section)));
      expect(top(tester, section), lessThan(top(tester, drive)));
      expect(top(tester, drive), lessThan(top(tester, fare)));
    });

    testWidgets('ersättningen får en egen ruta och står inte två gånger', (
      tester,
    ) async {
      await pumpSheet(tester, strongTip());
      await openMore(tester);
      final sentence = find.textContaining('Resenären kan få taxin betald');
      expect(sentence, findsOneWidget);
      final text = (tester.widget(sentence) as Text).data!;
      expect(text, contains('upp till 1\u00A0500\u00A0kr per resenär'));
      expect(find.textContaining('har rätt'), findsNothing);
      expect(find.text('Taxiersättning'), findsOneWidget);
    });

    testWidgets('utan ersättning finns ingen ersättningsruta', (tester) async {
      await pumpSheet(tester, plainTip());
      expect(find.textContaining('taxin betald'), findsNothing);
      expect(find.text('Taxiersättning'), findsNothing);
    });
  });

  group('linje och station', () {
    testWidgets('linjen och målet på en rad: "Buss 725 → Alingsås"', (
      tester,
    ) async {
      await pumpSheet(
        tester,
        strongTip()
          ..['line'] = 'Buss 725'
          ..['station'] = 'Tumba station',
      );
      final row = find.byKey(const ValueKey('tip-line-station'));
      expect(row, findsOneWidget);
      // Linjen från backend går före numret ur texten.
      expect((tester.widget(row) as Text).data, 'Buss 725 → Alingsås');
      // Platsen står en gång: stort överst, inte en gång till i kortet.
      expect(find.text('Tumba station'), findsOneWidget);
    });

    testWidgets('utan linje från backend: numret ur texten', (tester) async {
      await pumpSheet(tester, strongTip());
      expect(
        (tester.widget(find.byKey(const ValueKey('tip-line-station'))) as Text)
            .data,
        'Tåg 123 → Alingsås',
      );
      expect(find.text('Göteborg C'), findsOneWidget);
    });

    test('tolkas försiktigt: saknade fält är tomma', () {
      expect(tipLineStation({}), isNull);
      expect(tipLineStation({'line': null, 'station': null}), isNull);
      expect(tipLineStation({'line': '', 'station': ''}), isNull);
      expect(
        tipLineStation({
          'line': '',
          'station': '',
          'taxi': {
            'places': ['Tumba station'],
          },
        }),
        'Tumba station',
      );
      expect(tipLineStation({'line': 'Buss 725'}), 'Buss 725');
      expect(
        tipLineStation({'line': ' Buss 725 ', 'station': 'Tumba station '}),
        'Buss 725 · Tumba station',
      );
      // Stationen före platserna.
      expect(
        tipStation({
          'station': 'Tumba station',
          'taxi': {
            'places': ['Huddinge'],
          },
        }),
        'Tumba station',
      );
      expect(tipPlace({'station': 'Tumba station'}), 'Tumba station');
    });
  });

  group('reglerna för ersättningen', () {
    Map<String, dynamic> withRules() => strongTip()
      ..['compensation_source'] = 'Västtrafik'
      ..['compensation_url'] =
          'https://www.vasttrafik.se/forseningsersattning/';

    testWidgets('länken öppnar huvudmannens sida', (tester) async {
      final opened = <String>[];
      await pumpSheet(
        tester,
        withRules(),
        onOpenUrl: (url) async => opened.add(url),
      );
      await openMore(tester);
      final link = find.byKey(const ValueKey('compensation-rules-link'));
      await tester.scrollUntilVisible(
        link,
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('Läs reglerna hos Västtrafik'), findsOneWidget);
      // Står vid meningen om att taxin kan betalas.
      expect(
        top(tester, link),
        greaterThan(
          top(tester, find.textContaining('Resenären kan få taxin betald')),
        ),
      );
      expect(tester.getSize(link).height, greaterThanOrEqualTo(48));
      await tester.tap(link);
      expect(opened, ['https://www.vasttrafik.se/forseningsersattning/']);
    });

    testWidgets('utan adress ingen länk', (tester) async {
      await pumpSheet(
        tester,
        withRules()..['compensation_url'] = '',
        onOpenUrl: (url) async {},
      );
      await openMore(tester);
      expect(find.textContaining('Läs reglerna'), findsNothing);
      expect(find.textContaining('taxin betald'), findsOneWidget);
    });

    testWidgets('äldre backend utan fälten: ingen länk', (tester) async {
      await pumpSheet(tester, strongTip(), onOpenUrl: (url) async {});
      expect(find.textContaining('Läs reglerna'), findsNothing);
    });

    test('bara http(s)-adresser blir en länk', () {
      expect(compensationRulesUrl({}), isNull);
      expect(compensationRulesUrl({'compensation_url': null}), isNull);
      expect(
        compensationRulesUrl({'compensation_url': 'javascript:x'}),
        isNull,
      );
      expect(
        compensationRulesUrl({'compensation_url': 'sl.se/regler'}),
        isNull,
      );
      expect(
        compensationRulesUrl({'compensation_url': 'https://sl.se/regler'}),
        'https://sl.se/regler',
      );
    });
  });

  group('särfall', () {
    testWidgets('Övrigt: meddelandet utan bedömning och ersättning', (
      tester,
    ) async {
      await pumpSheet(tester, minorTip());
      expect(find.text('Trafikbolagets meddelande'), findsOneWidget);
      expect(find.text('Spårvagn 7 har ändrad körväg'), findsWidgets);
      expect(
        find.text(
          'Allmänt meddelande. Vi bedömer inte om det är värt att köra dit.',
        ),
        findsOneWidget,
      );
      expect(find.text('Särskilda omständigheter'), findsNothing);
      expect(find.text('Taxiersättning'), findsNothing);
    });

    testWidgets('avslutat tips: tydligt slut, ingen uppmaning att köra', (
      tester,
    ) async {
      await pumpSheet(tester, endedTip());
      // Rad 3 i huvudvyn: bara "Slut". Detaljerna ligger under Mer.
      expect(find.text('Slut'), findsOneWidget);
      await openMore(tester);

      expect(find.text('Slut. Tipset gäller inte längre.'), findsOneWidget);
      expect(find.textContaining('Tog slut för 8 min sedan'), findsOneWidget);
      expect(find.textContaining('Kör dit'), findsNothing);
      expect(
        find.widgetWithText(OutlinedButton, 'Öppna navigering'),
        findsOneWidget,
      );
      expect(find.byTooltip('Spara tipset'), findsOneWidget);
      expect(find.text('Särskilda omständigheter'), findsNothing);
    });

    testWidgets('väghändelse: vägen dit, ingen körning och ingen bedömning', (
      tester,
    ) async {
      await pumpSheet(tester, roadTip());

      expect(find.text('Olycka'), findsWidgets);
      expect(find.text('E6 Kungsbacka mot Göteborg'), findsWidgets);
      expect(find.text('Vägen dit'), findsOneWidget);
      expect(
        find.text('Räkna med kö, eller välj en annan väg.'),
        findsOneWidget,
      );
      expect(find.textContaining('Kör dit'), findsNothing);
      expect(find.text('Fick körning'), findsNothing);
      expect(find.text('Ingen kund'), findsNothing);
      // Väghändelser har "Mer" öppet från start.
      expect(find.text('Rapportera felaktigt tips'), findsOneWidget);
      expect(find.byTooltip('Spara tipset'), findsOneWidget);
    });
  });

  group('knapparna', () {
    testWidgets('Stjärnan skickar valet och visar att tipset är sparat', (
      tester,
    ) async {
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
      await tester.tap(find.byTooltip('Spara tipset'));
      await tester.pump();
      await tester.pump();
      expect(calls, [true]);
      expect(find.byTooltip('Ta bort sparat'), findsOneWidget);

      await tester.tap(find.byTooltip('Ta bort sparat'));
      await tester.pump();
      await tester.pump();
      expect(calls, [true, false]);
      expect(find.byTooltip('Spara tipset'), findsOneWidget);
    });

    testWidgets('misslyckas sparandet backar knappen', (tester) async {
      final tip = strongTip();
      await pumpSheet(tester, tip, onToggleFavorite: (v) async {});
      await tester.tap(find.byTooltip('Spara tipset'));
      await tester.pump();
      await tester.pump();
      expect(find.byTooltip('Spara tipset'), findsOneWidget);
      expect(find.byTooltip('Ta bort sparat'), findsNothing);
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
      expect(find.byTooltip('Spara tipset'), findsNothing);
      expect(find.text('Kör dit'), findsOneWidget);
    });

    testWidgets('Fick körning och Ingen kund ligger bland snabbknapparna', (
      tester,
    ) async {
      await pumpSheet(tester, strongTip());
      expect(find.text('Fick körning'), findsOneWidget);
      expect(find.text('Ingen kund'), findsOneWidget);
    });

    testWidgets('trafikbolagets sida öppnas från snabbknappen', (tester) async {
      var opened = 0;
      await pumpSheet(tester, strongTip(), onOpenSourcePage: () => opened++);
      await openMore(tester);
      await tester.ensureVisible(find.text('Trafikbolagets sida'));
      await tester.tap(find.text('Trafikbolagets sida'));
      expect(opened, 1);
    });

    testWidgets('utan egen sida finns ingen länk', (tester) async {
      await pumpSheet(tester, strongTip());
      await openMore(tester);
      expect(find.text('Trafikbolagets sida'), findsNothing);
    });

    testWidgets('rapporten skickas utan att slänga textfältet för tidigt', (
      tester,
    ) async {
      final api = _FakeApi();
      await pumpSheet(tester, strongTip(), api: api);
      await openMore(tester);

      await tester.ensureVisible(find.text('Rapportera felaktigt tips'));
      await tester.tap(find.text('Rapportera felaktigt tips'));
      await tester.pumpAndSettle();
      expect(find.text('Skicka rapport'), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'Fel plats');
      await tester.tap(find.text('Skicka rapport'));
      await tester.pumpAndSettle();

      expect(api.reports, [(id: 't1', reason: 'Fel plats')]);
      expect(find.text('Rapporterat'), findsOneWidget);
      expect(find.text('Tack — vi granskar tipset.'), findsOneWidget);
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

  group('beslutsunderlaget', () {
    testWidgets('alla skäl står öppet, en gång var', (tester) async {
      await pumpSheet(tester, manyFactorsTip());
      for (final text in [
        'Natt – nästan inga andra sätt att ta sig hem',
        'Stor station – många resenärer',
        'Sent på kvällen – färre alternativ',
        'Halka på vägarna',
      ]) {
        expect(find.text(text), findsOneWidget, reason: text);
      }
      expect(find.text('Visa alla skäl'), findsNothing);
    });

    testWidgets('inget "Visa alla skäl" när alla skäl redan syns', (
      tester,
    ) async {
      await pumpSheet(tester, plainTip());
      expect(find.text('Visa alla skäl'), findsNothing);
      expect(find.text('Sent på kvällen – färre alternativ'), findsOneWidget);
    });
  });

  group('i det riktiga bladet', () {
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

    testWidgets('visar huvudkortet och snabbknapparna utan att rulla', (
      tester,
    ) async {
      await openSheet(tester, strongTip());
      expect(tester.takeException(), isNull);
      expect(find.widgetWithText(FilledButton, 'Kör dit'), findsOneWidget);
      expect(find.text('Fick körning'), findsOneWidget);
    });

    testWidgets('att dra ner i innehållet stänger bladet', (tester) async {
      await openSheet(tester, strongTip());
      await tester.drag(find.text('Göteborg C').first, const Offset(0, 700));
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

  group('beslutet utan scroll på 360×640', () {
    Future<void> pumpSmall(
      WidgetTester tester,
      Map<String, dynamic> tip,
    ) async {
      await tester.binding.setSurfaceSize(const Size(360, 640));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: Scaffold(
            body: TipSheetBody(
              alert: tip,
              api: ApiClient(
                supabaseUrl: 'http://localhost',
                supabaseAnonKey: 'x',
              ),
              now: now,
              distanceKm: 12,
              onToggleFavorite: (v) async {},
            ),
          ),
        ),
      );
      await tester.pump();
    }

    Map<String, dynamic> withLines() => strongTip()
      ..['station'] = 'Ronneby'
      ..['headline'] = 'Tåg 22:48 inställt'
      ..['decision'] = 'Nästa tåg 23:48'
      ..['decision_tone'] = 'go';

    testWidgets('beslutet och skälen syns direkt, utan scroll', (tester) async {
      await pumpSmall(tester, withLines());
      expect(tester.takeException(), isNull);
      for (final f in [
        find.text('Ronneby'),
        find.text('Tåg 22:48 inställt'),
        find.text('Nästa tåg 23:48'),
        find.text('Taxi betalas'),
        find.byKey(const ValueKey('tip-line-station')),
      ]) {
        expect(f, findsOneWidget);
        expect(tester.getBottomLeft(f).dy, lessThan(640), reason: '$f');
      }
      // Serverns rubrik säger redan vad som hänt: ingen statusbricka till.
      expect(find.text('INSTÄLLD'), findsNothing);
      expect(
        tester.getSize(find.widgetWithText(FilledButton, 'Kör dit')).height,
        greaterThanOrEqualTo(56),
      );
      expect(
        tester.widget<Text>(find.text('Nästa tåg 23:48')).style!.color,
        TbColors.live,
      );
    });

    testWidgets('källans text står öppet, utan Mer', (tester) async {
      await pumpSmall(tester, withLines());
      expect(find.text('Mer'), findsNothing);
      expect(find.textContaining('fordonsfel'), findsOneWidget);
    });

    testWidgets('Övrigt: titeln som förut och Mer öppet', (tester) async {
      await pumpSmall(tester, minorTip());
      expect(find.text('Spårvagn 7 har ändrad körväg'), findsWidgets);
      expect(find.text('Trafikbolagets meddelande'), findsOneWidget);
    });

    testWidgets('utan nya fält: dagens rubrik och avgångsraden', (
      tester,
    ) async {
      await pumpSmall(tester, strongTip());
      expect(tester.takeException(), isNull);
      expect(find.text('En avgång inställd'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Kör dit'), findsOneWidget);
    });
  });

  group('inget om köp', () {
    testWidgets('ingen köpknapp, inget pris att betala, ingen betallänk', (
      tester,
    ) async {
      // Med länken till huvudmannens regler: information, inget köp.
      await pumpSheet(
        tester,
        strongTip()
          ..['compensation_source'] = 'Västtrafik'
          ..['compensation_url'] = 'https://www.vasttrafik.se/regler/',
        onOpenUrl: (url) async {},
      );
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

    test('alertPlacesList läser taxi.places', () {
      expect(alertPlacesList(strongTip()), ['Göteborg C']);
      expect(
        alertPlacesList({
          'taxi': {
            'places': ['A', 'B'],
          },
        }),
        ['A', 'B'],
      );
      expect(alertPlacesList({'taxi': {}}), isEmpty);
      expect(alertPlacesList({}), isEmpty);
    });

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
      // Utan tavla och utan ersättning står tre av fyra kvar: "Hela linjen
      // står still" upprepas av statusbrickan i huvudkortet.
      expect(tipFactors(plainTip()), hasLength(3));
    });

    test('ersättningsmeningen: kan få, belopp och per vem', () {
      expect(
        compensationSentence(1500, perPerson: true),
        'Resenären kan få taxin betald upp till 1\u00A0500\u00A0kr per resenär',
      );
      expect(
        compensationSentence(2960, perPerson: false),
        'Resenären kan få taxin betald upp till 2\u00A0960\u00A0kr per resa',
      );
      expect(
        compensationSentence(800),
        'Resenären kan få taxin betald upp till 800\u00A0kr',
      );
      expect(compensationSentence(null), 'Resenären kan få taxin betald');
    });
  });
}
