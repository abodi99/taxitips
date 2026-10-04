import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/widgets/guided_tour.dart';

/// Den guidade genomgången: pekar ut ett element i taget, hoppar över det som
/// inte syns, sparar att den visats, och följer med när skärmen vrids.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  // Tre element på skärmen; `ghost` finns aldrig (som ett tips i en tom lista).
  final first = GlobalKey(debugLabel: 'first');
  final second = GlobalKey(debugLabel: 'second');
  final ghost = GlobalKey(debugLabel: 'ghost');

  List<TourStep> steps() => [
    TourStep(
      id: 'first',
      title: 'Första',
      text: 'Det här är det första.',
      keys: [first],
    ),
    TourStep(
      id: 'ghost',
      title: 'Spöket',
      text: 'Det här elementet finns inte.',
      keys: [ghost],
    ),
    TourStep(
      id: 'second',
      title: 'Andra',
      text: 'Det här är det andra.',
      // Reserv: första nyckeln saknas, då används nästa som syns.
      keys: [ghost, second],
    ),
  ];

  Future<void> pumpScreen(
    WidgetTester tester, {
    Size size = const Size(360, 640),
    bool showSecond = true,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              const SizedBox(height: 60),
              Container(key: first, height: 56, color: Colors.amber),
              const SizedBox(height: 120),
              if (showSecond)
                Container(key: second, height: 56, color: Colors.green),
            ],
          ),
        ),
      ),
    );
  }

  TourController? start(WidgetTester tester, [List<TourStep>? list]) =>
      GuidedTour.start(
        tester.element(find.byType(Scaffold)),
        steps: list ?? steps(),
      );

  Future<void> close(WidgetTester tester, TourController? tour) async {
    tour?.dismiss();
    await tester.pumpWidget(const SizedBox());
  }

  testWidgets('visas en gång: sparas som sedd, och kan startas igen', (
    tester,
  ) async {
    expect(await GuidedTour.seen(), isFalse);
    await pumpScreen(tester);

    final tour = start(tester);
    await tester.pump();
    expect(tour, isNotNull);
    expect(find.text('Första'), findsOneWidget);
    expect(await GuidedTour.seen(), isTrue);

    // Hoppa över stänger den.
    await tester.tap(find.text('Hoppa över'));
    await tester.pump();
    expect(find.text('Första'), findsNothing);
    expect(tour!.active, isFalse);

    // Igen från Inställningar: samma steg, trots att den är sedd.
    final again = start(tester);
    await tester.pump();
    expect(find.text('Första'), findsOneWidget);
    await close(tester, again);
  });

  testWidgets('steg utan element hoppas över och räknas inte', (tester) async {
    await pumpScreen(tester);
    final tour = start(tester);
    await tester.pump();

    // Spöket syns inte: bara två steg återstår.
    expect(find.text('Steg 1 av 2'), findsOneWidget);
    expect(find.text('Första'), findsOneWidget);
    await tester.tap(find.text('Nästa'));
    await tester.pumpAndSettle();
    expect(find.text('Spöket'), findsNothing);
    expect(find.text('Steg 2 av 2'), findsOneWidget);
    expect(find.text('Andra'), findsOneWidget);
    // Sista steget säger Klar och stänger.
    expect(find.text('Nästa'), findsNothing);
    await tester.tap(find.text('Klar'));
    await tester.pump();
    expect(find.text('Andra'), findsNothing);
    expect(tour!.active, isFalse);
    await close(tester, null);
  });

  testWidgets('inget syns: ingen genomgång och inget sparas som sett', (
    tester,
  ) async {
    await pumpScreen(tester);
    final tour = start(tester, [
      TourStep(
        id: 'ghost',
        title: 'Spöket',
        text: 'Finns inte.',
        keys: [ghost],
      ),
    ]);
    await tester.pump();
    expect(tour, isNull);
    expect(find.text('Spöket'), findsNothing);
    expect(await GuidedTour.seen(), isFalse);
    await close(tester, null);
  });

  testWidgets('ett element som försvinner under tiden hoppas över', (
    tester,
  ) async {
    await pumpScreen(tester);
    final tour = start(tester);
    await tester.pump();
    expect(find.text('Steg 1 av 2'), findsOneWidget);

    // Första elementet försvinner (en banner, vridning): stegen rycker fram.
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              const SizedBox(height: 180),
              Container(key: second, height: 56, color: Colors.green),
            ],
          ),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Första'), findsNothing);
    expect(find.text('Andra'), findsOneWidget);
    await close(tester, tour);
  });

  testWidgets('ett eget område, och bara när det syns', (tester) async {
    await pumpScreen(tester);
    final tour = start(tester, [
      TourStep(
        id: 'map',
        title: 'Kartan',
        text: 'Här är kartan.',
        area: () => const Rect.fromLTWH(12, 200, 336, 200),
      ),
      TourStep(
        id: 'nowhere',
        title: 'Utanför',
        text: 'Utanför skärmen.',
        area: () => const Rect.fromLTWH(12, 900, 336, 200),
      ),
    ]);
    await tester.pump();
    expect(find.text('Kartan'), findsOneWidget);
    // Det andra området ligger utanför skärmen: det är inget steg.
    expect(find.text('Steg 1 av 1'), findsOneWidget);
    await close(tester, tour);
  });

  testWidgets('tillbaka-knappen lämnar genomgången, inte appen', (
    tester,
  ) async {
    await pumpScreen(tester);
    final tour = start(tester);
    await tester.pump();
    final handled = await tester.binding.handlePopRoute();
    await tester.pump();
    expect(handled, isTrue);
    expect(find.text('Första'), findsNothing);
    expect(tour!.active, isFalse);
    await close(tester, null);
  });

  testWidgets('stängs utifrån när skärmen försvinner', (tester) async {
    await pumpScreen(tester);
    final tour = start(tester);
    await tester.pump();
    expect(find.text('Första'), findsOneWidget);
    tour!.dismiss();
    await tester.pump();
    expect(find.text('Första'), findsNothing);
    await tour.done;
    await close(tester, null);
  });

  for (final (name, size, scale) in [
    ('liten telefon, stor text', const Size(360, 640), 1.3),
    ('stor telefon', const Size(430, 932), 1.0),
    ('liggande telefon, stor text', const Size(640, 360), 1.3),
  ]) {
    testWidgets('kortet ryms och knapparna syns: $name', (tester) async {
      await pumpScreen(tester, size: size);
      tester.platformDispatcher.textScaleFactorTestValue = scale;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final tour = start(tester);
      await tester.pump();
      expect(tester.takeException(), isNull);

      // Knapparna ligger i bild och är minst 48 höga.
      for (final label in ['Hoppa över', 'Nästa']) {
        final box = tester.getRect(
          find.ancestor(
            of: find.text(label),
            matching: find.bySubtype<ButtonStyleButton>(),
          ),
        );
        expect(box.height, greaterThanOrEqualTo(48), reason: label);
        expect(
          Offset.zero & size,
          predicate<Rect>((r) => r.inflate(0.5).overlaps(box)),
          reason: label,
        );
        expect(box.bottom, lessThanOrEqualTo(size.height), reason: label);
      }
      await close(tester, tour);
    });
  }

  testWidgets('vridning: ramen följer elementet och inget spiller över', (
    tester,
  ) async {
    await pumpScreen(tester);
    final tour = start(tester);
    await tester.pump();
    expect(find.text('Första'), findsOneWidget);

    // Vrid telefonen: genomgången mäter om och fortsätter.
    tester.view.physicalSize = const Size(640, 360);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(tester.takeException(), isNull);
    expect(find.text('Första'), findsOneWidget);
    await close(tester, tour);
  });
}
