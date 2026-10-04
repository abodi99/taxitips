import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/follow_up.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/alert_feedback_bar.dart';
import 'package:taxitips_app/widgets/follow_up_card.dart';

void main() {
  final drove = DateTime(2026, 10, 4, 11, 20);
  final tip = {
    'id': 'tip-1',
    'title': 'Västtågen 13871 11:33 är inställt från Herrljunga C',
    'places': ['Herrljunga C'],
  };

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('FollowUps: frågan ställs när svaret finns', () {
    test('inte direkt, men efter en halvtimme', () async {
      await FollowUps.remember(tip, now: drove);
      expect(
        await FollowUps.due(now: drove.add(const Duration(minutes: 10))),
        isNull,
      );
      final due = await FollowUps.due(
        now: drove.add(const Duration(minutes: 31)),
      );
      expect(due?.id, 'tip-1');
      expect(due?.place, 'Herrljunga C');
      expect(due?.at, drove);
    });

    test('inte efter ett helt pass', () async {
      await FollowUps.remember(tip, now: drove);
      expect(
        await FollowUps.due(now: drove.add(const Duration(hours: 5))),
        isNull,
      );
    });

    test('besvarad eller stängd frågas inte igen', () async {
      await FollowUps.remember(tip, now: drove);
      await FollowUps.remember({...tip, 'id': 'tip-2'}, now: drove);
      final later = drove.add(const Duration(minutes: 40));

      await FeedbackChoices.set('tip-1', 'fare');
      expect((await FollowUps.due(now: later))?.id, 'tip-2');

      await FollowUps.done('tip-2');
      expect(await FollowUps.due(now: later), isNull);
    });

    test('samma tips igen flyttar inte frågan framåt', () async {
      await FollowUps.remember(tip, now: drove);
      await FollowUps.remember(
        tip,
        now: drove.add(const Duration(minutes: 20)),
      );
      expect(
        (await FollowUps.due(now: drove.add(const Duration(minutes: 31))))?.id,
        'tip-1',
      );
    });

    test('utan plats används en kortad titel', () {
      expect(
        FollowUps.placeOf({'title': 'Inställd avgång'}),
        'Inställd avgång',
      );
      expect(FollowUps.placeOf({'title': 'x' * 60}).length, 40);
    });
  });

  group('FollowUpCard', () {
    setUp(() => AlertFeedbackBar.debugAlwaysShow = true);
    tearDown(() => AlertFeedbackBar.debugAlwaysShow = false);

    testWidgets('frågar om platsen och kan stängas', (tester) async {
      String? closed;
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: Scaffold(
            body: FollowUpCard(
              api: ApiClient(
                supabaseUrl: 'http://localhost',
                supabaseAnonKey: 'x',
              ),
              followUp: FollowUp(id: 'tip-1', place: 'Herrljunga C', at: drove),
              onDone: (id) => closed = id,
            ),
          ),
        ),
      );
      await tester.pump();

      expect(find.text('Du körde mot Herrljunga C 11:20'), findsOneWidget);
      expect(find.text('Hur gick det?'), findsOneWidget);
      expect(find.text('Fick körning'), findsOneWidget);
      expect(find.text('Ingen kund'), findsOneWidget);

      await tester.tap(find.byTooltip('Stäng'));
      expect(closed, 'tip-1');
    });
  });
}
