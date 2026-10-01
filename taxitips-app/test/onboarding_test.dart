import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/screens/onboarding_screen.dart';

/// Introduktionen visas en gång: "Hoppa över" och "Kom igång" sparar att den
/// är sedd. Färgerna Stark/Medel/Svag förklaras.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<List<String>> pump(WidgetTester tester) async {
    final done = <String>[];
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(home: OnboardingScreen(onDone: () => done.add('done'))),
    );
    await tester.pump();
    return done;
  }

  testWidgets('hoppa över sparar att introduktionen är sedd', (tester) async {
    expect(await OnboardingScreen.seen(), isFalse);
    final done = await pump(tester);
    expect(find.text('Hitta körningarna först'), findsOneWidget);
    await tester.tap(find.text('Hoppa över'));
    await tester.pumpAndSettle();
    expect(done, ['done']);
    expect(await OnboardingScreen.seen(), isTrue);
  });

  testWidgets('nästa går igenom alla sidor till Kom igång', (tester) async {
    final done = await pump(tester);
    // liquid_swipe animerar med timers: låt tiden gå mellan trycken.
    Future<void> settle() async {
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
    }

    await tester.tap(find.text('Nästa'));
    await settle();
    expect(find.text('Stark'), findsWidgets);
    for (var i = 0; i < 2; i++) {
      await tester.tap(find.text('Nästa'));
      await settle();
    }
    await tester.tap(find.widgetWithText(FilledButton, 'Kom igång'));
    await settle();
    expect(done, ['done']);
  });
}
