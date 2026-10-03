import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/screens/signup_screen.dart';

/// Registreringen har ett lösenordsfält, och det har ett öga: samma knapp och
/// samma texter som i inloggningen. Inget här pratar med servern.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pump(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        home: SignupScreen(
          api: ApiClient(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x'),
          onDone: () {},
          onLogin: () {},
        ),
      ),
    );
    await tester.pump();
  }

  TextField passwordField(WidgetTester tester) => tester.widget<TextField>(
    find.widgetWithText(TextField, 'Lösenord (minst 8 tecken)'),
  );

  testWidgets('lösenordet kan visas och döljas med ögat', (tester) async {
    await pump(tester);
    expect(passwordField(tester).obscureText, isTrue);

    final show = find.byTooltip('Visa lösenord');
    expect(show, findsOneWidget);
    await tester.ensureVisible(show);
    await tester.tap(show);
    await tester.pump();
    expect(passwordField(tester).obscureText, isFalse);
    expect(find.byTooltip('Dölj lösenord'), findsOneWidget);
    expect(find.byTooltip('Visa lösenord'), findsNothing);

    await tester.tap(find.byTooltip('Dölj lösenord'));
    await tester.pump();
    expect(passwordField(tester).obscureText, isTrue);
  });

  testWidgets('det som skrivs finns kvar när lösenordet visas', (tester) async {
    await pump(tester);
    await tester.enterText(
      find.widgetWithText(TextField, 'Lösenord (minst 8 tecken)'),
      'hemligt-123',
    );
    await tester.ensureVisible(find.byTooltip('Visa lösenord'));
    await tester.tap(find.byTooltip('Visa lösenord'));
    await tester.pump();
    expect(find.text('hemligt-123'), findsOneWidget);
  });

  testWidgets('stegen säger inget om en kod att läsa upp', (tester) async {
    await pump(tester);
    expect(find.textContaining('Bjud in förarna'), findsOneWidget);
    expect(find.textContaining('Ge förarna en kod'), findsNothing);
  });
}
