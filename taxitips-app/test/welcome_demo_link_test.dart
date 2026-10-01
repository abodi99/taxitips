import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/config.dart';
import 'package:taxitips_app/screens/welcome_screen.dart';

void main() {
  test('demon är webbsidan, ingen sida i appen', () {
    expect(TaxiTipsConfig.demoUrl, 'https://taxitips.se/demo');
  });

  testWidgets('startskärmen länkar till demon i webbläsaren', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: WelcomeScreen(
          api: ApiClient(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x'),
          onOwner: () {},
          onDriver: () {},
          onUseCode: () {},
          onSignup: () {},
        ),
      ),
    );
    expect(find.text('Se demon på webben'), findsOneWidget);
  });
}
