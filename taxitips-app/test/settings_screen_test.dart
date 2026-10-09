import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/membership_copy.dart';
import 'package:taxitips_app/screens/settings_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/county_checklist.dart';
import 'package:taxitips_app/widgets/settings_ui.dart';

import 'driver_test_support.dart';

/// Inställningarna är grupperade med korta rubriker. Ägare/admin får en
/// genväg till kundportalen som kontohantering; förare får bara neutral
/// text utan länk (membership_copy.dart).
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

  testWidgets('ägaren ser alla grupper och portalgenvägen', (tester) async {
    await pumpSettings(
      tester,
      api: FakeDriverApi(owner: true),
      onShowTour: () {},
    );
    for (final title in [
      'Företaget',
      'Medlemskap',
      'Notiser',
      'Konto',
      'Hjälp',
    ]) {
      final f = find.widgetWithText(SettingsSectionHeader, title);
      await reveal(tester, f);
      expect(f, findsOneWidget, reason: title);
    }
    final portal = find.text(kPortalAccountTitle);
    await reveal(tester, portal);
    expect(portal, findsOneWidget);
    expect(find.text(kPortalAccountSubtitle), findsOneWidget);
    // Tappbar rad (kontohantering), inte en död note-rad.
    expect(
      find.ancestor(of: portal, matching: find.byType(ListTile)),
      findsOneWidget,
    );
    // E-post och lösenord redigeras inte i appen.
    expect(find.text('E-post'), findsNothing);
    expect(find.text('Lösenord'), findsNothing);
    // Ingen rå URL i UI, och ingen köpformulering.
    expect(find.textContaining('http'), findsNothing);
    expect(find.textContaining('prenumer'), findsNothing);

    await reveal(tester, find.text('Visa genomgången igen'));
    expect(find.text('Så fungerar Taxi Tips'), findsOneWidget);
    expect(find.text('Visa genomgången igen'), findsOneWidget);
  });

  testWidgets('föraren ser sina grupper, utan portalgenväg', (tester) async {
    await pumpSettings(tester, api: FakeDriverApi(), onShowTour: () {});
    expect(find.text('Företaget'), findsNothing);
    expect(find.text(kPortalAccountTitle), findsNothing);
    expect(find.text(kInvoicesOnWeb), findsNothing);
    for (final title in ['Medlemskap', 'Notiser', 'Konto', 'Hjälp']) {
      final f = find.widgetWithText(SettingsSectionHeader, title);
      await reveal(tester, f);
      expect(f, findsOneWidget, reason: title);
    }
    // Kontobaserad vy: ingen bil att välja och ingen notishistorik-rad.
    expect(find.text('Välj bil'), findsNothing);
    expect(find.text('Bilen du kör'), findsNothing);
    expect(find.text('Notishistorik'), findsNothing);
    // Neutral fakturatext längst ner, utan länk.
    final note = find.text(kBillingOnWeb);
    await reveal(tester, note);
    expect(note, findsOneWidget);
    expect(
      find.ancestor(of: note, matching: find.byType(InkWell)),
      findsNothing,
    );
    expect(
      find.ancestor(of: note, matching: find.byType(ListTile)),
      findsNothing,
    );
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

  testWidgets('"Dina län" visar en kryssruta per län i medlemskapet', (
    tester,
  ) async {
    await pumpSettings(tester, api: FakeDriverApi());
    final county = find.text('Dina län');
    await reveal(tester, county);
    await tester.tap(county);
    await tester.pumpAndSettle();
    // Länen i licensen (FakeDriverApi: bara 14), förbockade -- inte provets
    // väljare med ett enda val bland alla 21 län.
    expect(find.byType(CountyPickerSheet), findsOneWidget);
    final boxes = tester.widgetList<CheckboxListTile>(
      find.byType(CheckboxListTile),
    );
    expect(boxes.map((b) => b.value), [true]);
    expect(find.text('Var vill du köra?'), findsNothing);
    // Inget prov: ingen genväg till provets länbyte.
    expect(find.text('Byt provets län'), findsNothing);
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
