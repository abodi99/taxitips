import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/screens/login_screen.dart';
import 'package:taxitips_app/screens/welcome_screen.dart';

/// EN inloggning med e-post och lösenord för förare, ägare och kontor --
/// servern avgör rollen (ägarens beslut 2026-10-04). Ingen kod i mejlet, inget
/// rollval. Inget här pratar med servern.
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

  testWidgets('förare ser hur de loggar in efter inbjudan', (tester) async {
    await pump(tester);
    expect(find.textContaining('För förare, ägare och kontor'), findsOneWidget);
    expect(find.textContaining('länken i inbjudan'), findsOneWidget);
    expect(find.textContaining('bara e-post'), findsNothing);
  });

  testWidgets('välkomstskärmen: logga in eller registrera, inget rollval', (
    tester,
  ) async {
    final taps = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        home: WelcomeScreen(
          onLogin: () => taps.add('login'),
          onSignup: () => taps.add('signup'),
        ),
      ),
    );
    expect(find.text('Jag är förare'), findsNothing);
    expect(find.textContaining('För förare, ägare och kontor'), findsOneWidget);
    await tester.tap(find.text('Logga in'));
    await tester.tap(find.text('Registrera företag'));
    expect(taps, ['login', 'signup']);
    expect(find.textContaining('kod'), findsNothing);
  });
}
