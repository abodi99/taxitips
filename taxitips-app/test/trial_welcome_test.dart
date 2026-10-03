import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/membership_copy.dart';
import 'package:taxitips_app/screens/trial_welcome_screen.dart';

/// Servern som ägaren ser den: provet ur GET /api/fleet/company och
/// kategorierna ur `features`. Inget går ut på nätet.
class _FakeApi extends ApiClient {
  _FakeApi({this.company, this.features, this.fail = false})
    : super(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x');

  final Map<String, dynamic>? company;
  final Map<String, dynamic>? features;
  final bool fail;

  @override
  Future<Map<String, dynamic>> fleetCompany() async {
    if (fail) throw ApiException(0, 'Inget nät');
    return company ?? {};
  }

  @override
  Future<Map<String, dynamic>> getNotifyPrefs() async {
    if (fail) throw ApiException(0, 'Inget nät');
    return {'features': ?features};
  }
}

const _trialFeatures = {
  'plan': 'trial',
  'categories': ['transit'],
  'locked': ['road', 'flight', 'ferry', 'events'],
};

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<List<String>> pump(
    WidgetTester tester,
    ApiClient api, {
    bool replay = false,
  }) async {
    final done = <String>[];
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        home: TrialWelcomeScreen(
          api: api,
          replay: replay,
          onDone: () => done.add('done'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    return done;
  }

  Future<void> next(WidgetTester tester) async {
    await tester.tap(find.widgetWithText(FilledButton, 'Nästa'));
    await tester.pumpAndSettle();
  }

  testWidgets('sida 1: vad Taxi Tips gör, med kategorierna som finns', (
    tester,
  ) async {
    await pump(tester, _FakeApi(features: _trialFeatures));
    expect(find.text('Välkommen till Taxi Tips'), findsOneWidget);
    for (final label in ['Tåg & buss', 'Väg', 'Flyg', 'Färja', 'Event']) {
      expect(find.text(label), findsOneWidget, reason: label);
    }
    // Försiktigt språk: tips och starka signaler, aldrig ett löfte om kunder.
    expect(find.textContaining('tips, inte löften'), findsOneWidget);
    expect(find.textContaining('stark signal'), findsOneWidget);
  });

  testWidgets('sida 2: provets längd kommer från servern', (tester) async {
    await pump(
      tester,
      _FakeApi(
        company: {
          'trial': {'status': 'pending', 'plannedDays': 14, 'vehicleLimit': 1},
        },
        features: _trialFeatures,
      ),
    );
    await next(tester);
    expect(find.text('Du provar gratis i 14 dagar'), findsOneWidget);
    expect(
      find.textContaining('Provet startar när du kopplar den första telefonen'),
      findsOneWidget,
    );
    expect(find.text('Du kan ha 1 bil i provet.'), findsOneWidget);
  });

  testWidgets('sida 2: pågående prov visar slutdatum, längd räknas ur datum', (
    tester,
  ) async {
    await pump(
      tester,
      _FakeApi(
        company: {
          'trial': {
            'status': 'active',
            'startedAt': '2026-10-01T08:00:00Z',
            'endsAt': '2026-10-08T08:00:00Z',
            'vehicleLimit': 3,
          },
        },
      ),
    );
    await next(tester);
    expect(find.text('Du provar gratis i 7 dagar'), findsOneWidget);
    expect(
      find.textContaining('Provet pågår. Det gäller till 2026-10-08'),
      findsOneWidget,
    );
    expect(find.text('Du kan ha upp till 3 bilar i provet.'), findsOneWidget);
  });

  testWidgets('utan svar från servern gissas ingen längd', (tester) async {
    await pump(tester, _FakeApi(fail: true));
    await next(tester);
    expect(find.text('Du provar gratis'), findsOneWidget);
    expect(find.textContaining('dagar'), findsNothing);
  });

  testWidgets('sida 3: nästa steg med e-post, ingen kod att läsa upp', (
    tester,
  ) async {
    await pump(tester, _FakeApi(features: _trialFeatures));
    await next(tester);
    await next(tester);
    expect(find.text('Lägg till bil och välj län'), findsOneWidget);
    expect(
      find.textContaining('Kör själv med den här telefonen'),
      findsOneWidget,
    );
    expect(find.text('Bjud in förare med e-post'), findsOneWidget);
    expect(find.textContaining('bolagskod'), findsNothing);
    expect(find.textContaining('läs upp'), findsNothing);
  });

  testWidgets('sida 4: vad som ingår kommer från features, resten är låst', (
    tester,
  ) async {
    await pump(tester, _FakeApi(features: _trialFeatures));
    await next(tester);
    await next(tester);
    await next(tester);
    expect(find.text('Vad ingår i provet?'), findsOneWidget);
    expect(find.text('Ingår i provet'), findsOneWidget);
    expect(find.text(kNotInTrial), findsOneWidget);
    // En kategori ingår, fyra är låsta.
    expect(find.byIcon(Icons.lock_rounded), findsNWidgets(4));
    expect(find.text('Tåg & buss'), findsOneWidget);
    // Neutral text, ingen länk eller knapp till köp.
    expect(find.textContaining(kMembershipOnWeb), findsOneWidget);
    expect(find.byType(TextButton), findsOneWidget); // bara "Hoppa över"
    expect(find.widgetWithText(FilledButton, 'Klar'), findsOneWidget);
  });

  testWidgets('features i företagssvaret går före notisinställningarnas', (
    tester,
  ) async {
    await pump(
      tester,
      _FakeApi(
        company: {
          'features': {
            'categories': ['transit', 'road', 'flight', 'ferry', 'events'],
            'locked': <String>[],
          },
        },
        features: _trialFeatures,
      ),
    );
    await next(tester);
    await next(tester);
    await next(tester);
    expect(find.text('Allt ingår just nu.'), findsOneWidget);
    expect(find.byIcon(Icons.lock_rounded), findsNothing);
  });

  testWidgets('utan features sägs bara hur ett lås ser ut', (tester) async {
    await pump(tester, _FakeApi(fail: true));
    await next(tester);
    await next(tester);
    await next(tester);
    expect(
      find.textContaining('Det som inte ingår har ett lås'),
      findsOneWidget,
    );
    expect(find.text(kNotInTrial), findsNothing);
  });

  testWidgets('hoppa över sparar att den är sedd; Klar avslutar', (
    tester,
  ) async {
    expect(await TrialWelcomeScreen.seen(), isFalse);
    final done = await pump(tester, _FakeApi());
    // Sedd redan när den visas.
    expect(await TrialWelcomeScreen.seen(), isTrue);
    await tester.tap(find.text('Hoppa över'));
    await tester.pumpAndSettle();
    expect(done, ['done']);

    final done2 = await pump(tester, _FakeApi());
    for (var i = 0; i < 3; i++) {
      await next(tester);
    }
    await tester.tap(find.widgetWithText(FilledButton, 'Klar'));
    await tester.pumpAndSettle();
    expect(done2, ['done']);
  });

  testWidgets('igen från Inställningar: Stäng i stället för Hoppa över', (
    tester,
  ) async {
    final done = await pump(tester, _FakeApi(), replay: true);
    expect(find.text('Hoppa över'), findsNothing);
    await tester.tap(find.text('Stäng'));
    await tester.pumpAndSettle();
    expect(done, ['done']);
  });

  testWidgets('inget pris, ingen köpknapp och ingen länk på någon sida', (
    tester,
  ) async {
    await pump(
      tester,
      _FakeApi(
        company: {
          'trial': {'status': 'pending', 'plannedDays': 7, 'vehicleLimit': 1},
        },
        features: _trialFeatures,
      ),
    );
    // Dart tolkar \b ASCII-bundet: "kräver" skulle annars räknas som "kr".
    final forbidden = RegExp(
      r'(?<![a-zåäö])kr(?![a-zåäö])|SEK|pris|köp|betal|(?<![a-zåäö])kort(?![a-zåäö])|'
      r'abonnemang|portal|http|www\.',
      caseSensitive: false,
    );
    for (var page = 0; page < 4; page++) {
      final texts = tester
          .widgetList<Text>(find.byType(Text))
          .map((t) => t.data ?? t.textSpan?.toPlainText() ?? '')
          .where(forbidden.hasMatch)
          .toList();
      expect(texts, isEmpty, reason: 'sida ${page + 1}: $texts');
      if (page < 3) await next(tester);
    }
  });
}
