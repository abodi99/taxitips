import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/bankid_flow.dart';
import 'package:taxitips_app/membership_copy.dart';
import 'package:taxitips_app/screens/signup_screen.dart';

/// Registreringen med BankID: först bara BankID-knappen och beskedet att det
/// inte binder till något; efter BankID fyra fält och inget organisationsnummer.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pump(WidgetTester tester, {BankIdResult? identity}) async {
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        home: SignupScreen(
          api: ApiClient(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x'),
          onDone: () {},
          onLogin: () {},
          initialIdentity: identity,
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('första steget: BankID och att det inte binder', (tester) async {
    await pump(tester);
    expect(find.text('Fortsätt med BankID'), findsOneWidget);
    for (final line in kBankIdPromises) {
      expect(find.text(line), findsOneWidget);
    }
    expect(find.byType(TextField), findsNothing);
    expect(find.textContaining('Organisationsnummer'), findsNothing);
  });

  testWidgets('efter BankID: hälsning och fyra fält, inget org.nr', (
    tester,
  ) async {
    await pump(
      tester,
      identity: const BankIdResult(
        ticket: 't',
        name: 'Anna Andersson',
        givenName: 'Anna',
      ),
    );
    expect(find.text('Hej Anna!'), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(4));
    expect(find.widgetWithText(TextField, 'Företag'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Organisationsnummer'), findsNothing);
  });

  testWidgets('fel i formuläret visas utan att något skickas', (tester) async {
    await pump(
      tester,
      identity: const BankIdResult(
        ticket: 't',
        name: 'Anna',
        givenName: 'Anna',
      ),
    );
    final submit = find.text('Starta provet');
    await tester.ensureVisible(submit);
    await tester.tap(submit);
    await tester.pump();
    expect(find.text('Skriv företagets namn.'), findsOneWidget);
  });

  test('BankID-texterna säljer ingenting', () {
    for (final text in kBankIdPromises) {
      expect(text, isNot(contains('kr')));
      expect(text.toLowerCase(), isNot(contains('köp')));
      expect(text.toLowerCase(), isNot(contains('prenumer')));
      expect(text, isNot(contains('http')));
    }
    // BankID är inget avtal: det ska synas direkt.
    expect(kBankIdPromises, contains('Ingen bindning'));
  });
}
