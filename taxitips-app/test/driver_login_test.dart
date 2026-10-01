import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/screens/driver_login_screen.dart';
import 'package:taxitips_app/screens/welcome_screen.dart';

/// Startsidan har två tydliga vägar -- förare och ägare -- och förarens
/// inloggning har koden kvar som reserv. Inget här pratar med servern.
void main() {
  testWidgets('startsidan: förare och ägare har var sin knapp', (tester) async {
    var driver = 0;
    var owner = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: WelcomeScreen(
          onLogin: () => owner++,
          onSignup: () {},
          onDriver: () => driver++,
        ),
      ),
    );
    await tester.tap(find.text('Jag är förare'));
    await tester.tap(find.text('Jag äger bolaget'));
    expect((driver, owner), (1, 1));
    // Inga priser eller köp i appen (docs/fleet-abonnemang.md §9c).
    expect(find.textContaining('kr'), findsNothing);
  });

  testWidgets('förarens inloggning: tomma fält ger ett tydligt fel och koden finns kvar', (
    tester,
  ) async {
    var usedCode = false;
    await tester.pumpWidget(
      MaterialApp(
        home: DriverLoginScreen(
          api: ApiClient(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x'),
          onPaired: () {},
          onOwner: () {},
          onUseCode: () => usedCode = true,
          onBack: () {},
        ),
      ),
    );
    await tester.tap(find.text('Logga in'));
    await tester.pump();
    expect(find.text('Skriv din e-post och ditt lösenord.'), findsOneWidget);

    await tester.tap(find.text('Glömt lösenord?'));
    await tester.pump();
    expect(find.textContaining('Skriv din e-post först'), findsOneWidget);

    await tester.ensureVisible(find.text('Har du en kod?'));
    await tester.tap(find.text('Har du en kod?'));
    expect(usedCode, isTrue);
  });
}
