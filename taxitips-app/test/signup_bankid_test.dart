import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/bankid_flow.dart';
import 'package:taxitips_app/l10n/l10n.dart';
import 'package:taxitips_app/widgets/ltr_input.dart';
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

  testWidgets('första steget: två löften, inget om företag', (tester) async {
    await pump(tester);
    expect(find.text('Inget kort'), findsOneWidget);
    expect(find.text('Ingen bindning'), findsOneWidget);
    expect(find.text('Inget företag behövs'), findsNothing);
    expect(find.text('Har du redan ett konto? Logga in'), findsOneWidget);
  });

  testWidgets(
    'efter BankID: hälsning och valet "Är du förare eller ägare?", inget fält',
    (tester) async {
      await pump(tester, identity: anna);
      expect(find.text('Hej Anna! Är du förare eller ägare?'), findsOneWidget);
      expect(find.text('Jag är förare'), findsOneWidget);
      expect(find.text('Jag äger ett taxibolag'), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      expect(find.textContaining('Organisationsnummer'), findsNothing);
    },
  );

  testWidgets('kör själv: inget företagsnamn, en fråga per steg', (
    tester,
  ) async {
    await pump(tester, identity: anna);
    await tapText(tester, 'Jag är förare');
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

  testWidgets('varje fråga får sitt eget tangentbord, och fokus följer med', (
    tester,
  ) async {
    // Förut byttes bara tangentbordstypen på ett och samma fält, och telefonen
    // behöll det gamla tangentbordet (siffror på e-postfrågan). Nu är varje
    // fråga ett nytt fält som får fokus direkt.
    TextField field() => tester.widget<TextField>(find.byType(TextField));
    Future<void> next() async {
      await tester.tap(find.text('Nästa'));
      await tester.pump();
      await tester.pump();
    }

    await pump(tester, identity: anna);
    await tapText(tester, 'Jag äger ett taxibolag');
    await tester.pump();
    var f = field();
    expect(f.keyboardType, TextInputType.text);
    expect(f.textCapitalization, TextCapitalization.words);
    expect(f.focusNode!.hasFocus, isTrue);
    final companyKey = f.key;

    await tester.enterText(find.byType(TextField), 'Annas Taxi');
    await next();
    f = field();
    expect(f.key, isNot(companyKey), reason: 'ett nytt fält per fråga');
    expect(f.keyboardType, TextInputType.phone);
    expect(f.autofillHints, contains(AutofillHints.telephoneNumber));
    expect(f.focusNode!.hasFocus, isTrue);
    expect(f.scrollPadding.bottom, greaterThanOrEqualTo(200));

    await tester.enterText(find.byType(TextField), '070 812 34 91');
    await next();
    f = field();
    expect(f.keyboardType, TextInputType.emailAddress);
    expect(f.autocorrect, isFalse);
    expect(f.enableSuggestions, isFalse);
    expect(f.focusNode!.hasFocus, isTrue);

    await tester.enterText(find.byType(TextField), 'anna@gmail.com');
    await next();
    f = field();
    expect(f.keyboardType, TextInputType.visiblePassword);
    expect(f.obscureText, isTrue);
    expect(f.enableSuggestions, isFalse);
    expect(f.autofillHints, contains(AutofillHints.newPassword));
    expect(f.textInputAction, TextInputAction.done);
    expect(f.focusNode!.hasFocus, isTrue);
  });

  testWidgets(
    'det man skriver efter Nästa hamnar i nästa fält, utan att trycka i det',
    (tester) async {
      // Förarens väg: tangentbordet är redan uppe, ingen trycker i fältet.
      // testTextInput skriver till det fält som har tangentbordskopplingen --
      // tappas kopplingen mellan frågorna hamnar texten ingenstans (sett
      // 2026-11-22 när alla frågor delade en fokusnod).
      Future<void> type(String text) async {
        tester.testTextInput.enterText(text);
        await tester.pump();
      }

      Future<void> submit() async {
        await tester.testTextInput.receiveAction(TextInputAction.next);
        await tester.pump();
        await tester.pump();
      }

      await pump(tester, identity: anna);
      await tapText(tester, 'Jag är förare');
      await tester.pump();

      await type('070 812 34 91');
      expect(find.text('070 812 34 91'), findsOneWidget);
      await submit();
      expect(find.text('Din e-post'), findsOneWidget);
      expect(tester.testTextInput.hasAnyClients, isTrue);

      await type('anna@gmail.com');
      expect(find.text('anna@gmail.com'), findsOneWidget);
      await submit();
      expect(find.text('Skapa kontot'), findsOneWidget);
      expect(tester.testTextInput.hasAnyClients, isTrue);

      await type('hemligt123');
      final password = tester.widget<TextField>(find.byType(TextField));
      expect(password.controller!.text, 'hemligt123');

      // Tillbaka: e-posten finns kvar och går att skriva vidare i.
      await tester.tap(find.byTooltip('Tillbaka'));
      await tester.pump();
      await tester.pump();
      expect(find.text('anna@gmail.com'), findsOneWidget);
    },
  );

  testWidgets('taxibolag: ett steg till, företagets namn', (tester) async {
    await pump(tester, identity: anna);
    await tapText(tester, 'Jag äger ett taxibolag');
    expect(find.text('Steg 2 av 5'), findsOneWidget);
    expect(find.text('Vad heter företaget?'), findsOneWidget);
    expect(find.text('Organisationsnummer behövs inte nu.'), findsOneWidget);
    await tapText(tester, 'Nästa');
    expect(find.text('Skriv företagets namn.'), findsOneWidget);
  });

  testWidgets(
    'arabiska: föraren får inte frågan om företag, och mobilen skrivs vänster till höger',
    (tester) async {
      setTrLocale(const Locale('ar'));
      addTearDown(() => setTrLocale(const Locale('sv')));
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        MaterialApp(
          home: Directionality(
            textDirection: TextDirection.rtl,
            child: SignupScreen(
              api: ApiClient(
                supabaseUrl: 'http://localhost',
                supabaseAnonKey: 'x',
              ),
              onDone: () {},
              onLogin: () {},
              initialIdentity: anna,
            ),
          ),
        ),
      );
      await tester.pump();
      expect(
        find.text('مرحباً Anna! هل أنت سائق أم صاحب شركة؟'),
        findsOneWidget,
      );
      await tapText(tester, 'أنا سائق');
      expect(find.text('الخطوة 2 من 4'), findsOneWidget);
      expect(find.text('رقم جوالك'), findsOneWidget);
      final field = tester.widget<TextField>(find.byType(TextField));
      expect(field.textDirection, TextDirection.ltr);
      expect(field.textAlign, TextAlign.right);
      // Felet visar exemplet i rätt ordning (vänster till höger inne i arabiskan).
      await tapText(tester, 'التالي');
      expect(find.textContaining('\u2066070 123 45 67\u2069'), findsOneWidget);
    },
  );

  test('nummer och adresser i text skrivs vänster till höger, ord lämnas', () {
    expect(
      ltrRuns('اكتب مثلاً 070 123 45 67.'),
      'اكتب مثلاً \u2066070 123 45 67\u2069.',
    );
    expect(
      ltrRuns('مثلاً name@gmail.com.'),
      'مثلاً \u2066name@gmail.com\u2069.',
    );
    expect(ltrRuns('تابع باستخدام BankID'), 'تابع باستخدام BankID');
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
