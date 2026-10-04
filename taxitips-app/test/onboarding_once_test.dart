import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/main.dart';
import 'package:taxitips_app/screens/onboarding_screen.dart';
import 'package:taxitips_app/screens/welcome_screen.dart';

import 'driver_test_support.dart';

/// Introduktionen visas EN gång efter installationen: aldrig igen, inte heller
/// efter utloggning, och inte när appen första gången startar inloggad.
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> boot(WidgetTester tester, FakeDriverApi api) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(TaxiPrognosApp(api: api));
    for (var i = 0; i < 14; i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
  }

  testWidgets('första starten: introduktionen, sedan aldrig mer', (
    tester,
  ) async {
    await boot(tester, FakeDriverApi(device: null));
    expect(find.byType(OnboardingScreen), findsOneWidget);
    await tester.tap(find.text('Hoppa över'));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(WelcomeScreen), findsOneWidget);

    // Appen startas om: välkomstskärmen, ingen introduktion.
    await disposeScreen(tester);
    await boot(tester, FakeDriverApi(device: null));
    expect(find.byType(OnboardingScreen), findsNothing);
    expect(find.byType(WelcomeScreen), findsOneWidget);
    await disposeScreen(tester);
  });

  testWidgets('startar appen inloggad är introduktionen avklarad, även efter '
      'utloggning', (tester) async {
    await boot(tester, FakeDriverApi());
    expect(find.byType(OnboardingScreen), findsNothing);
    expect(await OnboardingScreen.seen(), isTrue);
    await disposeScreen(tester);

    // Utloggad och omstartad: ingen introduktion mitt i.
    await boot(tester, FakeDriverApi(device: null));
    expect(find.byType(OnboardingScreen), findsNothing);
    expect(find.byType(WelcomeScreen), findsOneWidget);
    await disposeScreen(tester);
  });

  testWidgets(
    'introduktionen från Inställningar sparar inget och stängs med Klar',
    (tester) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      var done = 0;
      await tester.pumpWidget(
        MaterialApp(home: OnboardingScreen(replay: true, onDone: () => done++)),
      );
      await tester.pump();
      expect(await OnboardingScreen.seen(), isFalse);
      await tester.tap(find.text('Stäng'));
      await tester.pump(const Duration(milliseconds: 300));
      expect(done, 1);
      expect(await OnboardingScreen.seen(), isFalse);
      await disposeScreen(tester);
    },
  );
}
