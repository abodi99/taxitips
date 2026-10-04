import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/screens/driver_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/guided_tour.dart';

import 'driver_test_support.dart';

/// Den guidade genomgången på förarskärmen: startar av sig själv första
/// gången, bara då, och kan visas igen när föraren ber om det. Ägare och
/// förare får olika text i sista steget.
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pumpDriver(
    WidgetTester tester, {
    required FakeDriverApi api,
    Listenable? tourRequest,
    Size size = const Size(360, 640),
    bool withSettings = true,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTaxiTheme(),
        home: DriverScreen(
          api: api,
          onOpenSettings: withSettings ? () {} : null,
          tourRequest: tourRequest,
        ),
      ),
    );
    await settleDriverScreen(tester);
  }

  const driverSteps = [
    'Tipslistan',
    'Färgen visar styrkan',
    'Kartan och nålarna',
    'Tryck på ett tips',
    'Kategorier',
    'Filter och län',
    'Inställningar',
  ];

  testWidgets('startar av sig själv första gången och går igenom alla steg', (
    tester,
  ) async {
    expect(await GuidedTour.seen(), isFalse);
    await pumpDriver(tester, api: FakeDriverApi());

    for (var i = 0; i < driverSteps.length; i++) {
      expect(
        find.text('Steg ${i + 1} av ${driverSteps.length}'),
        findsOneWidget,
      );
      expect(find.text(driverSteps[i]), findsOneWidget);
      await tester.tap(
        find.text(i == driverSteps.length - 1 ? 'Klar' : 'Nästa'),
      );
      await tester.pumpAndSettle(const Duration(milliseconds: 100));
    }
    expect(find.text('Steg 1 av 7'), findsNothing);
    expect(await GuidedTour.seen(), isTrue);
    await disposeScreen(tester);
  });

  testWidgets('visas aldrig igen av sig själv, men går att visa på begäran', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({GuidedTour.seenKey: true});
    final request = ValueNotifier<int>(0);
    addTearDown(request.dispose);
    await pumpDriver(tester, api: FakeDriverApi(), tourRequest: request);
    expect(find.text('Tipslistan'), findsNothing);

    // "Visa genomgången igen" i Inställningar.
    request.value++;
    await settleDriverScreen(tester);
    expect(find.text('Tipslistan'), findsOneWidget);

    await tester.tap(find.text('Hoppa över'));
    await tester.pump();
    expect(find.text('Tipslistan'), findsNothing);
    await disposeScreen(tester);
  });

  testWidgets('utan tips hoppas tipskortets steg över, listan visas ändå', (
    tester,
  ) async {
    await pumpDriver(tester, api: FakeDriverApi(tips: false));
    // Färgen och "tryck på ett tips" pekar på listans rubrik när inget kort
    // finns -- stegen finns kvar, men inget pekar på ett kort som saknas.
    expect(find.text('Tipslistan'), findsOneWidget);
    expect(find.text('Steg 1 av 7'), findsOneWidget);
    await disposeScreen(tester);
  });

  testWidgets('utan Inställningar-knapp hoppas det sista steget över', (
    tester,
  ) async {
    await pumpDriver(tester, api: FakeDriverApi(), withSettings: false);
    expect(find.text('Steg 1 av 6'), findsOneWidget);
    await disposeScreen(tester);
  });

  testWidgets('förare och ägare får olika text om Inställningar', (
    tester,
  ) async {
    Future<void> toLastStep() async {
      for (var i = 0; i < driverSteps.length - 1; i++) {
        await tester.tap(find.text('Nästa'));
        await tester.pumpAndSettle(const Duration(milliseconds: 100));
      }
    }

    await pumpDriver(tester, api: FakeDriverApi());
    await toLastStep();
    expect(find.textContaining('Här slår du på notiser'), findsOneWidget);
    expect(find.textContaining('bjuder in förare'), findsNothing);
    await disposeScreen(tester);

    SharedPreferences.setMockInitialValues({});
    await pumpDriver(tester, api: FakeDriverApi(owner: true));
    await toLastStep();
    expect(find.textContaining('bjuder in förare'), findsOneWidget);
    expect(find.textContaining('lägger du till bilar'), findsOneWidget);
    await disposeScreen(tester);
  });
}
