import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/membership_copy.dart';
import 'package:taxitips_app/screens/settings_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/settings_ui.dart';

import 'driver_test_support.dart';

/// Inställningarna är grupperade med korta rubriker och en rad om vad man kan
/// göra i varje. Fakturor och medlemskap är en neutral rad: ingen länk, ingen
/// knapp (Apples och Googles regler, membership_copy.dart).
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pumpSettings(
    WidgetTester tester, {
    required FakeDriverApi api,
    VoidCallback? onShowTour,
    VoidCallback? onLogout,
  }) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTaxiTheme(),
        home: SettingsScreen(
          api: api,
          onLogout: onLogout ?? () {},
          onShowTour: onShowTour,
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump(const Duration(milliseconds: 500));
  }

  Future<void> reveal(WidgetTester tester, Finder f) async {
    // Listan bygger raderna efter hand: börja överst och rulla neråt.
    final list = find.byType(Scrollable).first;
    await tester.drag(list, const Offset(0, 5000));
    await tester.pump();
    await tester.scrollUntilVisible(f, 150, scrollable: list);
    await tester.pump();
  }

  testWidgets('ägaren ser alla grupper och den neutrala fakturaraden', (
    tester,
  ) async {
    await pumpSettings(
      tester,
      api: FakeDriverApi(owner: true),
      onShowTour: () {},
    );
    for (final title in [
      'Företaget och bilarna',
      'Den här telefonen',
      'Notiser',
      'Konto',
      'Hjälp',
    ]) {
      final f = find.widgetWithText(SettingsSectionHeader, title);
      await reveal(tester, f);
      expect(f, findsOneWidget, reason: title);
    }
    // Fakturaraden: exakt texten, och inget som går att trycka på.
    final note = find.text(kInvoicesOnWeb);
    await reveal(tester, note);
    expect(
      kInvoicesOnWeb,
      'Fakturor och medlemskap hanteras av företagets administratör på webben.',
    );
    expect(note, findsOneWidget);
    expect(
      find.ancestor(of: note, matching: find.byType(InkWell)),
      findsNothing,
    );
    expect(
      find.ancestor(of: note, matching: find.byType(ListTile)),
      findsNothing,
    );
    expect(find.textContaining('http'), findsNothing);

    await reveal(tester, find.text('Visa genomgången igen'));
    expect(find.text('Så fungerar Taxi Tips'), findsOneWidget);
    expect(find.text('Visa genomgången igen'), findsOneWidget);
  });

  testWidgets('föraren ser sina grupper, utan företagsdelen', (tester) async {
    await pumpSettings(tester, api: FakeDriverApi(), onShowTour: () {});
    expect(find.text('Företaget och bilarna'), findsNothing);
    expect(find.text(kInvoicesOnWeb), findsNothing);
    for (final title in ['Den här telefonen', 'Notiser', 'Konto', 'Hjälp']) {
      final f = find.widgetWithText(SettingsSectionHeader, title);
      await reveal(tester, f);
      expect(f, findsOneWidget, reason: title);
    }
  });

  testWidgets('"Visa genomgången igen" kallar på genomgången', (tester) async {
    var shown = 0;
    await pumpSettings(tester, api: FakeDriverApi(), onShowTour: () => shown++);
    await reveal(tester, find.text('Visa genomgången igen'));
    await tester.tap(find.text('Visa genomgången igen'));
    expect(shown, 1);
  });

  testWidgets('utan genomgång att visa finns ingen rad (ingen död knapp)', (
    tester,
  ) async {
    await pumpSettings(tester, api: FakeDriverApi());
    await reveal(tester, find.text('Så fungerar Taxi Tips'));
    expect(find.text('Visa genomgången igen'), findsNothing);
  });

  testWidgets('föraren kan inte koppla bort telefonen -- bara logga ut', (
    tester,
  ) async {
    var loggedOut = 0;
    await pumpSettings(
      tester,
      api: FakeDriverApi(),
      onLogout: () => loggedOut++,
    );
    await reveal(tester, find.text('Logga ut'));
    expect(find.text('Logga ut'), findsOneWidget);
    // "Koppla från telefonen" är borttagen (2026-10-07): ett telefonbyte sker
    // genom att logga in på en annan telefon, och servern tillåter ett byte per
    // kalendermånad. Inställningarna har därför ingen avkopplingsknapp kvar.
    expect(find.text('Koppla från telefonen'), findsNothing);
    await tester.tap(find.text('Logga ut'));
    expect(loggedOut, 1);
  });
}
