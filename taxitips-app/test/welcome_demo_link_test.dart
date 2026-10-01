import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:taxibehov_app/config.dart';
import 'package:taxibehov_app/screens/welcome_screen.dart';

void main() {
  test('demon är webbsidan, ingen sida i appen', () {
    expect(TaxiTipsConfig.demoUrl, 'https://taxitips.se/demo');
  });

  testWidgets('startskärmen länkar till demon i webbläsaren', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: WelcomeScreen(
          onLogin: () {},
          onSignup: () {},
          onDriver: () {},
        ),
      ),
    );
    expect(find.text('Se demon'), findsOneWidget);
    expect(find.text('Öppnas i webbläsaren'), findsOneWidget);
  });
}
