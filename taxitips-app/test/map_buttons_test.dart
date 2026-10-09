import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/screens/driver_screen.dart';
import 'package:taxitips_app/screens/history_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/guided_tour.dart';

import 'driver_test_support.dart';

/// Kartans knappar: det som används ofta ligger nere där tummen når, i två
/// grupper (vänster: Filter, med ord; höger: zoom och min position).
/// Historik, förklaringen (?) och Inställningar är tysta ikoner i raden
/// överst. Ingen funktion har försvunnit.
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

  /// Drar listan hela vägen upp.
  Future<void> expandSheet(WidgetTester tester) async {
    await tester.drag(
      find.textContaining('Alla tips ·'),
      const Offset(0, -500),
    );
    await tester.pumpAndSettle(const Duration(milliseconds: 100));
  }

  testWidgets('alla kartans funktioner finns kvar, grupperade', (tester) async {
    await pumpDriver(tester);
    expect(tester.takeException(), isNull);

    final view = find.byKey(const ValueKey('map_view_buttons'));
    final actions = find.byKey(const ValueKey('map_action_buttons'));
    expect(view, findsOneWidget);
    expect(actions, findsOneWidget);

    // Vänster nere: bara Filter, med ikon och ord.
    expect(
      find.descendant(of: view, matching: find.text('Filter')),
      findsOneWidget,
    );
    // Historik är inte längre en stor knapp nere.
    expect(
      find.descendant(of: view, matching: find.text('Historik')),
      findsNothing,
    );
    expect(
      find.descendant(of: view, matching: find.byIcon(Icons.history_rounded)),
      findsNothing,
    );
    expect(find.widgetWithText(FloatingActionButton, 'Historik'), findsNothing);

    // Höger: zoom och min position.
    for (final tip in ['Zooma in', 'Zooma ut', 'Min position']) {
      expect(
        find.descendant(of: actions, matching: find.byTooltip(tip)),
        findsOneWidget,
        reason: tip,
      );
    }
    // Förklaringen ligger inte bland tummens knappar ...
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

  testWidgets('Historik är en tyst ikon i vänstra hörnet överst', (
    tester,
  ) async {
    await pumpDriver(tester);
    final history = find.byTooltip('Historik');
    expect(history, findsOneWidget);
    // En ikonknapp som förklaringen och Inställningar, utan ord.
    final button = find.ancestor(
      of: find.byIcon(Icons.history_rounded),
      matching: find.byType(IconButton),
    );
    expect(button, findsOneWidget);
    expect(find.text('Historik'), findsNothing);
    expect(
      tester.widget<IconButton>(button).color,
      tester
          .widget<IconButton>(
            find.ancestor(
              of: find.byIcon(Icons.help_outline_rounded),
              matching: find.byType(IconButton),
            ),
          )
          .color,
    );

    // Överst, i samma rad som förklaringen, i vänstra hörnet.
    final historyCenter = tester.getCenter(history);
    final legendCenter = tester.getCenter(
      find.byKey(const ValueKey('map_legend_button')),
    );
    expect(historyCenter.dy, lessThan(100));
    expect((historyCenter.dy - legendCenter.dy).abs(), lessThan(1));
    expect(historyCenter.dx, lessThan(360 / 4));
    expect(legendCenter.dx, greaterThan(360 / 2));
    // Loggan i mitten krockar inte med ikonerna.
    expect(tester.takeException(), isNull);
    await disposeScreen(tester);
  });

  testWidgets('kartknapparna är stora nog att träffa i bilen', (tester) async {
    await pumpDriver(tester);
    for (final finder in [
      find.byTooltip('Min position'),
      find.byTooltip('Zooma in'),
      find.byTooltip('Zooma ut'),
      // Ikonknapparna överst: tryckytan (IconButton med sin utfyllnad),
      // inte bara den ritade cirkeln.
      find.ancestor(
        of: find.byIcon(Icons.history_rounded),
        matching: find.byType(IconButton),
      ),
      find.ancestor(
        of: find.byIcon(Icons.help_outline_rounded),
        matching: find.byType(IconButton),
      ),
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
    await tester.tap(find.byTooltip('Historik'));
    await tester.pumpAndSettle(const Duration(milliseconds: 100));
    expect(find.byType(HistoryScreen), findsOneWidget);
    expect(api.historyCalls, [24]);
    expect(find.byType(HistoryRow), findsNWidgets(2));
    await disposeScreen(tester);
  });

  testWidgets(
    'uppdragen lista: Filter och sortering i rubriken, ingen Historik',
    (tester) async {
      await pumpDriver(tester);
      await expandSheet(tester);
      expect(tester.takeException(), isNull);

      final header = find.ancestor(
        of: find.textContaining('Alla tips ·'),
        matching: find.byType(Row),
      );
      // Kartknapparna är bortdragna; Filter finns i rubriken i stället.
      expect(
        find.descendant(of: header.first, matching: find.byTooltip('Filter')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: header.first, matching: find.byTooltip('Sortera')),
        findsOneWidget,
      );
      // Historik visas inte i listan.
      expect(
        find.descendant(
          of: header.first,
          matching: find.byIcon(Icons.history_rounded),
        ),
        findsNothing,
      );
      expect(
        find.descendant(of: header.first, matching: find.byTooltip('Historik')),
        findsNothing,
      );
      await disposeScreen(tester);
    },
  );

  testWidgets('Filter visar ingen sortering; den finns i listans rubrik', (
    tester,
  ) async {
    await pumpDriver(tester);
    // Sorteringen i rubriken, utan att dra upp listan.
    expect(find.byTooltip('Sortera'), findsOneWidget);
    expect(find.text('Viktigast'), findsOneWidget);

    await tester.tap(find.widgetWithText(FloatingActionButton, 'Filter'));
    await tester.pumpAndSettle(const Duration(milliseconds: 100));
    final sheet = find.byType(BottomSheet);
    expect(sheet, findsOneWidget);
    expect(
      find.descendant(of: sheet, matching: find.text('Filter')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: sheet, matching: find.text('Sortera')),
      findsNothing,
    );
    expect(
      find.descendant(
        of: sheet,
        matching: find.byType(SegmentedButton<String>),
      ),
      findsNothing,
    );
    for (final label in ['Viktigast', 'Närmast', 'Nyast']) {
      expect(
        find.descendant(of: sheet, matching: find.text(label)),
        findsNothing,
        reason: label,
      );
    }
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
