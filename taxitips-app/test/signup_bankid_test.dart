import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/bankid_flow.dart';
import 'package:taxitips_app/membership_copy.dart';
import 'package:taxitips_app/screens/signup_screen.dart';

/// Registreringen med BankID: först bara BankID-knappen och beskedet att det
/// inte binder till något; efter BankID en fråga per steg, inget
/// organisationsnummer, och ingen behöver ett företag.
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

  const anna = BankIdResult(
    ticket: 't',
    name: 'Anna Andersson',
    givenName: 'Anna',
  );

  Future<void> tapText(WidgetTester tester, String text) async {
    final f = find.text(text);
    await tester.ensureVisible(f);
    await tester.tap(f);
    await tester.pump();
  }

  testWidgets('första steget säger att inget företag behövs', (tester) async {
    await pump(tester);
    expect(find.text('Inget företag behövs'), findsOneWidget);
    expect(find.text('Har du redan ett konto? Logga in'), findsOneWidget);
  });

  testWidgets('efter BankID: hälsning och valet "Hur kör du?", inget fält', (
    tester,
  ) async {
    await pump(tester, identity: anna);
    expect(find.text('Hej Anna! Hur kör du?'), findsOneWidget);
    expect(find.text('Jag kör själv'), findsOneWidget);
    expect(find.text('Jag har ett taxibolag'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    expect(find.textContaining('Organisationsnummer'), findsNothing);
  });

  testWidgets('kör själv: inget företagsnamn, en fråga per steg', (
    tester,
  ) async {
    await pump(tester, identity: anna);
    await tapText(tester, 'Jag kör själv');
    expect(find.text('Steg 2 av 4'), findsOneWidget);
    expect(find.text('Ditt mobilnummer'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);

    // Fel visas vid fältet, med ett exempel, och man kommer inte vidare.
    await tapText(tester, 'Nästa');
    expect(
      find.textContaining('Skriv till exempel 070 123 45 67'),
      findsOneWidget,
    );
    expect(find.text('Ditt mobilnummer'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '070 812 34 91');
    await tapText(tester, 'Nästa');
    expect(find.text('Steg 3 av 4'), findsOneWidget);
    expect(find.text('Din e-post'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'anna@gmail.com');
    await tapText(tester, 'Nästa');
    expect(find.text('Steg 4 av 4'), findsOneWidget);
    expect(find.text('Skapa kontot'), findsOneWidget);
    expect(find.textContaining('företaget'), findsNothing);

    // Tillbaka går ett steg och behåller det som skrivits.
    await tester.tap(find.byTooltip('Tillbaka'));
    await tester.pump();
    expect(find.text('anna@gmail.com'), findsOneWidget);
  });

  testWidgets('taxibolag: ett steg till, företagets namn', (tester) async {
    await pump(tester, identity: anna);
    await tapText(tester, 'Jag har ett taxibolag');
    expect(find.text('Steg 2 av 5'), findsOneWidget);
    expect(find.text('Vad heter företaget?'), findsOneWidget);
    expect(find.text('Organisationsnummer behövs inte nu.'), findsOneWidget);
    await tapText(tester, 'Nästa');
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
