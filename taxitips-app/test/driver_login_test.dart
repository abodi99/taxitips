import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:taxitips_app/api_client.dart';
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
        home: WelcomeScreen(
          api: ApiClient(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x'),
          onOwner: () => taps.add('owner'),
          onDriver: () => taps.add('driver'),
          onUseCode: () => taps.add('code'),
          onSignup: () => taps.add('signup'),
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

  testWidgets('kod och nytt företag finns som länkar', (tester) async {
    final r = await pump(tester);
    await tester.ensureVisible(find.textContaining('Har du en kod'));
    await tester.tap(find.textContaining('Har du en kod'));
    await tester.tap(find.textContaining('Nytt företag?'));
    expect(r.taps, ['code', 'signup']);
  });
}
