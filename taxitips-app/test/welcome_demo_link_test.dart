import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/config.dart';
import 'package:taxitips_app/screens/welcome_screen.dart';

void main() {
  test('demon är webbsidan, ingen sida i appen', () {
    // app=1: demon döljer sina knappar till registrering och kontakt, så att
    // appen inte leder vidare mot ett köp (taxitips-web/src/demo/main.js).
    expect(TaxiTipsConfig.demoUrl, 'https://taxitips.se/demo?app=1');
  });

  testWidgets('startskärmen länkar till demon i webbläsaren', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: WelcomeScreen(onLogin: () {}, onSignup: () {}, onDriver: () {}),
      ),
    );
    expect(find.text('Se demon på webben'), findsOneWidget);
  });
}
