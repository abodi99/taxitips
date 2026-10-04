import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/screens/driver_screen.dart';
import 'package:taxitips_app/screens/login_screen.dart';
import 'package:taxitips_app/screens/onboarding_screen.dart';
import 'package:taxitips_app/screens/settings_screen.dart';
import 'package:taxitips_app/screens/signup_screen.dart';
import 'package:taxitips_app/screens/trial_welcome_screen.dart';
import 'package:taxitips_app/screens/welcome_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/guided_tour.dart';
import 'package:taxitips_app/widgets/signal_card.dart';

import 'driver_test_support.dart';

/// Huvudskärmarna på en liten telefon (360x640), en stor (430x932) och med
/// textstorlek 1,3. Flutter gör ett spill över kanten (RenderFlex overflow) till
/// ett testfel, så varje skärm här pumpas och får inte kasta något. Appens
/// riktiga typsnitt laddas: i Ahem blir all text dubbelt så bred.
void main() {
  setUpAll(loadAppFonts);
  setUp(
    () => SharedPreferences.setMockInitialValues({
      // Ingen genomgång som lägger sig ovanpå skärmen.
      GuidedTour.seenKey: true,
    }),
  );

  final configs = <(String, Size, double)>[
    ('360x640', const Size(360, 640), 1.0),
    ('360x640, text 1,3', const Size(360, 640), 1.3),
    ('430x932', const Size(430, 932), 1.0),
    ('430x932, text 1,3', const Size(430, 932), 1.3),
  ];

  Future<void> pumpAt(
    WidgetTester tester,
    Widget screen,
    Size size,
    double scale,
  ) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = scale;
    addTearDown(tester.view.reset);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await tester.pumpWidget(MaterialApp(theme: buildTaxiTheme(), home: screen));
  }

  FakeDriverApi plain() => FakeDriverApi(device: null);

  final screens = <String, Widget Function()>{
    'introduktionen': () => OnboardingScreen(onDone: () {}),
    'välkomst': () => WelcomeScreen(onLogin: () {}, onSignup: () {}),
    'inloggning': () => LoginScreen(
      api: plain(),
      onOwner: () {},
      onDriver: () {},
      onSignup: () {},
      onBack: () {},
    ),
    'registrering': () => SignupScreen(
      api: plain(),
      onDone: () {},
      onLogin: () {},
      onBack: () {},
    ),
    'välkomst till provet': () =>
        TrialWelcomeScreen(api: plain(), onDone: () {}),
    'inställningar, förare': () =>
        SettingsScreen(api: FakeDriverApi(), onShowTour: () {}),
    'inställningar, ägare': () => SettingsScreen(
      api: FakeDriverApi(owner: true),
      onLogout: () {},
      onShowTour: () {},
    ),
  };

  for (final (name, size, scale) in configs) {
    for (final entry in screens.entries) {
      testWidgets('${entry.key} ryms: $name', (tester) async {
        await pumpAt(tester, entry.value(), size, scale);
        for (var i = 0; i < 6; i++) {
          await tester.pump(const Duration(milliseconds: 300));
        }
        expect(tester.takeException(), isNull);
        await disposeScreen(tester);
      });
    }

    testWidgets('huvudskärmen och tipsbladet ryms: $name', (tester) async {
      await pumpAt(
        tester,
        DriverScreen(api: FakeDriverApi(owner: true), onOpenSettings: () {}),
        size,
        scale,
      );
      await settleDriverScreen(tester);
      expect(tester.takeException(), isNull);
      expect(find.byType(SignalCard), findsWidgets);

      // Tryck på första tipset: bladet med Kör dit och Spara.
      await tester.tap(find.byType(SignalCard).first);
      for (var i = 0; i < 6; i++) {
        await tester.pump(const Duration(milliseconds: 300));
      }
      expect(tester.takeException(), isNull);
      expect(find.textContaining('Kör dit'), findsWidgets);
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 5));
    });
  }
}
