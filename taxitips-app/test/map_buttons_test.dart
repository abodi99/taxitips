import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/screens/driver_screen.dart';
import 'package:taxitips_app/screens/history_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/guided_tour.dart';

import 'driver_test_support.dart';

/// Kartans knappar: det som används ofta ligger nere där tummen når, i två
/// grupper (vänster: Historik och Filter, med ord; höger: zoom och min
/// position). Förklaringen (?) och Inställningar ligger i raden överst.
/// Ingen funktion har försvunnit.
void main() {
  setUpAll(loadAppFonts);
  setUp(
    () => SharedPreferences.setMockInitialValues({GuidedTour.seenKey: true}),
  );

  Future<FakeDriverApi> pumpDriver(WidgetTester tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = FakeDriverApi();
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTaxiTheme(),
        home: DriverScreen(api: api, onOpenSettings: () {}),
      ),
    );
    await settleDriverScreen(tester);
    return api;
  }

  testWidgets('alla kartans funktioner finns kvar, grupperade', (tester) async {
    await pumpDriver(tester);
    expect(tester.takeException(), isNull);

    final view = find.byKey(const ValueKey('map_view_buttons'));
    final actions = find.byKey(const ValueKey('map_action_buttons'));
    expect(view, findsOneWidget);
    expect(actions, findsOneWidget);

    // Vänster: Historik och Filter, med ikon och ord.
    expect(
      find.descendant(of: view, matching: find.text('Historik')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: view, matching: find.byIcon(Icons.history_rounded)),
      findsOneWidget,
    );
    expect(
      find.descendant(of: view, matching: find.text('Filter')),
      findsOneWidget,
    );

    // Höger: zoom och min position.
    for (final tip in ['Zooma in', 'Zooma ut', 'Min position']) {
      expect(
        find.descendant(of: actions, matching: find.byTooltip(tip)),
        findsOneWidget,
        reason: tip,
      );
    }
    // Förklaringen ligger inte längre bland tummens knappar ...
    expect(
      find.descendant(
        of: actions,
        matching: find.byIcon(Icons.help_outline_rounded),
      ),
      findsNothing,
    );
    // ... utan överst, bredvid Inställningar.
    expect(find.byKey(const ValueKey('map_legend_button')), findsOneWidget);
    expect(find.byTooltip('Vad betyder symbolerna?'), findsOneWidget);
    expect(find.byTooltip('Inställningar'), findsOneWidget);

    // Förklaringen överst och tummens knappar nere.
    final legendY = tester
        .getCenter(find.byKey(const ValueKey('map_legend_button')))
        .dy;
    final locationY = tester.getCenter(find.byTooltip('Min position')).dy;
    expect(legendY, lessThan(100));
    expect(locationY, greaterThan(250));
    await disposeScreen(tester);
  });

  testWidgets('kartknapparna är stora nog att träffa i bilen', (tester) async {
    await pumpDriver(tester);
    for (final finder in [
      find.byTooltip('Min position'),
      find.byTooltip('Zooma in'),
      find.byTooltip('Zooma ut'),
      find.widgetWithText(FloatingActionButton, 'Historik'),
      find.widgetWithText(FloatingActionButton, 'Filter'),
    ]) {
      final size = tester.getSize(finder);
      expect(size.height, greaterThanOrEqualTo(48), reason: '$finder');
      expect(size.width, greaterThanOrEqualTo(48), reason: '$finder');
    }
    await disposeScreen(tester);
  });

  testWidgets('Historik öppnar historiken för det senaste dygnet', (
    tester,
  ) async {
    final api = await pumpDriver(tester);
    await tester.tap(find.text('Historik'));
    await tester.pumpAndSettle(const Duration(milliseconds: 100));
    expect(find.byType(HistoryScreen), findsOneWidget);
    expect(api.historyCalls, [24]);
    expect(find.byType(HistoryRow), findsNWidgets(2));
    await disposeScreen(tester);
  });

  testWidgets('förklaringen öppnas från raden överst', (tester) async {
    await pumpDriver(tester);
    await tester.tap(find.byKey(const ValueKey('map_legend_button')));
    await tester.pumpAndSettle(const Duration(milliseconds: 100));
    expect(find.text('Symbolerna på kartan'), findsOneWidget);
    await disposeScreen(tester);
  });
}
