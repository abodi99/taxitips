import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/membership_copy.dart';
import 'package:taxitips_app/screens/history_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/signal_card.dart' show StrengthPill;
import 'package:taxitips_app/widgets/tip_sheet.dart';

import 'driver_test_support.dart';

/// Historiken: de senaste timmarnas tips i förarens område, nyast först och
/// per timme, avslutade inräknade. Ett avslutat tips öppnas utan "Kör dit".
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pumpHistory(
    WidgetTester tester,
    FakeDriverApi api, {
    Future<void> Function(Map<String, dynamic>)? onOpenTip,
  }) async {
    tester.view.physicalSize = const Size(360, 720);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTaxiTheme(),
        home: HistoryScreen(
          api: api,
          counties: const ['14'],
          areaLabel: 'Västra Götaland',
          onOpenTip: onOpenTip,
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
  }

  testWidgets('visar tipsen nyast först, med tid, styrka och om de är slut', (
    tester,
  ) async {
    final api = FakeDriverApi();
    await pumpHistory(tester, api);

    expect(find.text('Historik'), findsOneWidget);
    expect(find.text('Västra Götaland'), findsOneWidget);
    expect(api.historyCalls, [24]);
    expect(
      find.text('2 tips de senaste 24 timmarna · 1 pågår'),
      findsOneWidget,
    );

    final rows = find.byType(HistoryRow);
    expect(rows, findsNWidgets(2));
    // Nyast först: tåget som pågår, sedan flyget som tog slut.
    final first = tester.getTopLeft(rows.at(0)).dy;
    final second = tester.getTopLeft(rows.at(1)).dy;
    expect(first, lessThan(second));
    expect(
      find.descendant(of: rows.at(0), matching: find.text('Pågår')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: rows.at(1), matching: find.text('Slut')),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: rows.at(1),
        matching: find.text('Landvetter flygplats · Västra Götaland'),
      ),
      findsOneWidget,
    );
    // Styrkan medan flyget pågick (Medel), inte Svag för att det tagit slut.
    final pill = tester.widget<StrengthPill>(
      find.descendant(of: rows.at(1), matching: find.byType(StrengthPill)),
    );
    expect(pill.strength.name, 'medium');
    expect(pill.muted, isTrue);
    await disposeScreen(tester);
  });

  testWidgets('6, 12 eller 24 timmar: valet hämtar om', (tester) async {
    final api = FakeDriverApi();
    await pumpHistory(tester, api);
    await tester.tap(find.text('6 tim'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(api.historyCalls, [24, 6]);
    expect(find.textContaining('de senaste 6 timmarna'), findsOneWidget);
    await disposeScreen(tester);
  });

  testWidgets('ett avslutat tips öppnas utan Kör dit', (tester) async {
    final api = FakeDriverApi();
    await pumpHistory(tester, api);
    await tester.tap(find.byType(HistoryRow).at(1));
    await tester.pumpAndSettle(const Duration(milliseconds: 100));

    expect(find.byType(TipSheetBody), findsOneWidget);
    expect(find.textContaining('Kör dit'), findsNothing);
    // Bara att titta i: ingen Spara-knapp i historiken.
    expect(find.text('Spara'), findsNothing);
    await disposeScreen(tester);
  });

  testWidgets('tipsbladet får styrkan medan tipset pågick', (tester) async {
    final api = FakeDriverApi();
    final opened = <Map<String, dynamic>>[];
    await pumpHistory(tester, api, onOpenTip: (a) async => opened.add(a));
    await tester.tap(find.byType(HistoryRow).at(1));
    await tester.pump();
    expect(opened.single['level'], 'medium');
    expect(opened.single['is_active'], isFalse);
    await disposeScreen(tester);
  });

  testWidgets('låsta kategorier räknas, med appens egen neutrala text', (
    tester,
  ) async {
    final api = FakeDriverApi()
      ..historyBody = {
        'alerts': sampleHistory().take(1).toList(),
        'entitled': true,
        'features': {
          'plan': 'trial',
          'hiddenCounts': {'flight': 2, 'ferry': 1},
        },
      };
    await pumpHistory(tester, api);
    expect(
      find.text(
        '3 tips i Flyg och Färja visas inte. ${lockedNoteFor('trial')}',
      ),
      findsOneWidget,
    );
    await disposeScreen(tester);
  });

  testWidgets('utan körområde och utan åtkomst: en rad, ingen lista', (
    tester,
  ) async {
    final area = FakeDriverApi()
      ..historyBody = {'alerts': [], 'entitled': true, 'needsArea': true};
    await pumpHistory(tester, area);
    expect(
      find.text('Välj ditt körområde för att se historiken.'),
      findsOneWidget,
    );
    await disposeScreen(tester);

    final blocked = FakeDriverApi()
      ..historyBody = {
        'alerts': [],
        'entitled': false,
        'reason': 'trial_ended',
      };
    await pumpHistory(tester, blocked);
    expect(find.textContaining('Provperioden är slut.'), findsOneWidget);
    expect(find.byType(HistoryRow), findsNothing);
    await disposeScreen(tester);
  });

  group('groupHistoryByHour', () {
    final now = DateTime(2026, 10, 9, 14, 30);
    Map<String, dynamic> at(DateTime t, String id) => {
      'id': id,
      'history_at': t.toUtc().toIso8601String(),
    };

    test(
      'en grupp per timme, nyast först, det som började före fönstret sist',
      () {
        final groups = groupHistoryByHour([
          at(DateTime(2026, 10, 9, 13, 5), 'a'),
          at(DateTime(2026, 10, 9, 14, 20), 'b'),
          at(DateTime(2026, 10, 9, 13, 50), 'c'),
          at(DateTime(2026, 10, 7, 9, 0), 'gammal'),
        ], since: now.subtract(const Duration(hours: 24)));

        expect(groups.map((g) => g.rows.map((r) => r['id']).toList()), [
          ['b'],
          ['c', 'a'],
          ['gammal'],
        ]);
        expect(groups.first.label(now), 'I dag 9 okt · 14:00–15:00');
        expect(groups.last.label(now), 'Började tidigare');
      },
    );
  });
}
