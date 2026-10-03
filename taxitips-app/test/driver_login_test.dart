import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/screens/driver_login_screen.dart';
import 'package:taxitips_app/screens/login_screen.dart';
import 'package:taxitips_app/screens/welcome_screen.dart';

/// Startsidan är EN inloggning för förare, ägare och kontor -- servern avgör
/// rollen. Koden, nytt företag och demon är länkar, inte konkurrerande vägar.
/// Inget här pratar med servern.
void main() {
  Future<({List<String> taps})> pump(WidgetTester tester) async {
    final taps = <String>[];
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        home: LoginScreen(
          api: ApiClient(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x'),
          onOwner: () => taps.add('owner'),
          onDriver: () => taps.add('driver'),
          onSignup: () => taps.add('signup'),
          onBack: () => taps.add('back'),
        ),
      ),
    );
    return (taps: taps);
  }

  testWidgets('en inloggning, inga rollval', (tester) async {
    await pump(tester);
    expect(find.text('Logga in'), findsNWidgets(2)); // rubrik + knapp
    expect(find.text('Jag är förare'), findsNothing);
    expect(find.text('Jag äger bolaget'), findsNothing);
    // Inga priser eller köp i appen (docs/fleet-abonnemang.md §9c).
    expect(find.textContaining(' kr'), findsNothing);
  });

  testWidgets('tomma fält ger ett tydligt fel, Glömt lösenord kräver e-post', (
    tester,
  ) async {
    await pump(tester);
    await tester.enterText(find.byType(TextField).at(0), '');
    await tester.enterText(find.byType(TextField).at(1), '');
    await tester.tap(find.widgetWithText(FilledButton, 'Logga in'));
    await tester.pump();
    expect(find.text('Skriv din e-post och ditt lösenord.'), findsOneWidget);

    await tester.tap(find.text('Glömt lösenord?'));
    await tester.pump();
    expect(find.textContaining('Skriv din e-post först'), findsOneWidget);
  });

  testWidgets('lösenordet kan visas och döljas', (tester) async {
    await pump(tester);
    TextField password() =>
        tester.widget<TextField>(find.byType(TextField).at(1));
    expect(password().obscureText, isTrue);
    await tester.tap(find.byTooltip('Visa lösenord'));
    await tester.pump();
    expect(password().obscureText, isFalse);
  });

  testWidgets('ingen bolagskod: bara e-post, registrera och tillbaka', (
    tester,
  ) async {
    final r = await pump(tester);
    expect(find.textContaining('kod'), findsNothing);
    await tester.ensureVisible(find.textContaining('Inget konto?'));
    await tester.tap(find.textContaining('Inget konto?'));
    await tester.tap(find.byTooltip('Tillbaka'));
    expect(r.taps, ['signup', 'back']);
  });

  testWidgets('välkomstskärmen: förare, ägare eller registrera', (tester) async {
    final taps = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        home: WelcomeScreen(
          onLogin: () => taps.add('login'),
          onSignup: () => taps.add('signup'),
          onDriver: () => taps.add('driver'),
        ),
      ),
    );
    await tester.tap(find.text('Jag är förare'));
    await tester.tap(find.text('Logga in som ägare eller kontor'));
    await tester.tap(find.text('Registrera företag'));
    expect(taps, ['driver', 'login', 'signup']);
    expect(find.textContaining('kod'), findsNothing);
  });

  testWidgets('föraren: bara e-post, inget lösenord', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: DriverLoginScreen(
          api: ApiClient(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x'),
          onDone: () {},
          onBack: () {},
        ),
      ),
    );
    expect(find.text('Jag är förare'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'E-post'), findsOneWidget);
    expect(find.textContaining('Lösenord'), findsNothing);
    // Utan giltig e-post skickas ingen kod.
    await tester.tap(find.text('Skicka kod'));
    await tester.pump();
    expect(find.textContaining('Skriv din e-post'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Kod (6 siffror)'), findsNothing);
  });
}
