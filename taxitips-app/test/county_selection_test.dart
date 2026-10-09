import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/county_selection.dart';
import 'package:taxitips_app/screens/driver_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/county_checklist.dart';

import 'driver_test_support.dart';

/// Medlemskapets län når appen (2026-10-09): admin gav ett medlemskap tre
/// län, men appen låg kvar på ett gammalt val med ett län och "Dina län"
/// erbjöd ett enda val bland alla 21. Valet stäms nu av mot licensen med
/// samma regel som servern (fleet/device_prefs.align_prefs_to_entitlement).

const _names = {
  '01': 'Stockholm',
  '05': 'Östergötland',
  '08': 'Kalmar',
  '12': 'Skåne',
};

/// En server där licensen har [licensed] och telefonens sparade område är
/// [serverPrefs]. Sparar varje notisområde appen skickar.
class _CountyApi extends FakeDriverApi {
  _CountyApi(this.licensed, {this.serverPrefs = const {}});

  List<String> licensed;
  Map<String, dynamic> serverPrefs;
  final saved = <List<String>?>[];
  final feedCounties = <List<String>?>[];

  @override
  Future<Map<String, dynamic>> entitlements() async => {
    'ok': true,
    'entitled': true,
    'licensedCounties': licensed,
    'unrestrictedCounties': false,
  };

  @override
  Future<Map<String, dynamic>> getNotifyPrefs() async => {
    'licensedCounties': licensed,
    'countyCatalog': [
      for (final e in _names.entries)
        {'code': e.key, 'name': '${e.value}s län'},
    ],
    'prefs': serverPrefs,
  };

  @override
  Future<Map<String, dynamic>> saveNotifyPrefs({
    bool? enabled,
    List<String>? cities,
    List<String>? regions,
    List<String>? counties,
    List<String>? municipalities,
    Map<String, bool>? types,
    Map<String, bool>? categories,
    String? minLevel,
    double? pauseHours,
  }) async {
    saved.add(counties);
    return {'counties': counties};
  }

  @override
  Future<Map<String, dynamic>> taxi({
    double? userLat,
    double? userLon,
    List<String>? regions,
    List<String>? counties,
    List<String>? municipalities,
    bool roadAll = false,
  }) {
    feedCounties.add(counties);
    return super.taxi(
      userLat: userLat,
      userLon: userLon,
      regions: regions,
      counties: counties,
      municipalities: municipalities,
      roadAll: roadAll,
    );
  }
}

List<bool?> _checkboxValues(WidgetTester tester) => tester
    .widgetList<CheckboxListTile>(find.byType(CheckboxListTile))
    .map((c) => c.value)
    .toList();

void main() {
  setUpAll(loadAppFonts);

  group('reconcileCounties', () {
    test('alla län förblir alla när licensen växer', () {
      expect(
        reconcileCounties(chosen: {}, licensed: {'01', '05', '08'}),
        isEmpty,
      );
    });

    test('ett län admin lagt till läggs till ett snävare val', () {
      expect(
        reconcileCounties(
          chosen: {'01'},
          licensed: {'01', '05', '08', '12'},
          recorded: {'01', '05', '08'},
        ),
        {'01', '12'},
      );
    });

    test('ett bortvalt län står kvar som bortvalt', () {
      expect(
        reconcileCounties(
          chosen: {'01', '08'},
          licensed: {'01', '05', '08'},
          recorded: {'01', '05', '08'},
        ),
        {'01', '08'},
      );
    });

    test('ett län som tas bort ur licensen försvinner ur valet', () {
      expect(
        reconcileCounties(
          chosen: {'01', '05'},
          licensed: {'01', '08'},
          recorded: {'01', '05', '08'},
        ),
        {'01'},
      );
    });

    test('blir inget kvar gäller hela licensen', () {
      expect(
        reconcileCounties(
          chosen: {'05'},
          licensed: {'01', '08'},
          recorded: {'01', '05', '08'},
        ),
        isEmpty,
      );
    });

    test('det gamla valet med ett län och licensens ett län -> alla tre', () {
      // Felet från telefonen: valet sparades när licensen bara hade 01.
      expect(
        reconcileCounties(
          chosen: {'01'},
          licensed: {'01', '05', '08'},
          recorded: {'01'},
        ),
        isEmpty,
      );
    });

    test('utan anteckning gäller hela licensen, som på servern', () {
      expect(
        reconcileCounties(chosen: {'01'}, licensed: {'01', '05'}),
        isEmpty,
      );
    });

    test('okänd licens rör ingenting', () {
      expect(reconcileCounties(chosen: {'01'}, licensed: {}), {'01'});
    });
  });

  group('toggleCounty', () {
    const licensed = {'01', '05', '08'};

    test('att kryssa ur ett län ur "alla" ger resten', () {
      expect(
        toggleCounty(chosen: {}, code: '05', on: false, licensed: licensed),
        {'01', '08'},
      );
    });

    test('att kryssa i det sista ger "alla" igen', () {
      expect(
        toggleCounty(
          chosen: {'01', '08'},
          code: '05',
          on: true,
          licensed: licensed,
        ),
        isEmpty,
      );
    });

    test('det sista länet går inte att kryssa ur', () {
      expect(
        toggleCounty(chosen: {'01'}, code: '01', on: false, licensed: licensed),
        {'01'},
      );
    });

    test('utan licens gäller exakt de ikryssade', () {
      expect(toggleCounty(chosen: {}, code: '12', on: true), {'12'});
    });
  });

  group('CountyChecklist', () {
    Future<Set<String>?> pump(
      WidgetTester tester, {
      required List<String> licensed,
      required Set<String> selected,
    }) async {
      Set<String>? changed;
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: Scaffold(
            body: CountyChecklist(
              licensed: licensed,
              names: _names,
              selected: selected,
              onChanged: (next) => changed = next,
            ),
          ),
        ),
      );
      return changed;
    }

    testWidgets('en förbockad kryssruta per län i licensen', (tester) async {
      await pump(tester, licensed: const ['01', '05', '08'], selected: {});
      expect(find.byType(CheckboxListTile), findsNWidgets(3));
      expect(_checkboxValues(tester), [true, true, true]);
      for (final name in ['Stockholm', 'Östergötland', 'Kalmar']) {
        expect(find.text(name), findsOneWidget);
      }
      expect(find.text('Skåne'), findsNothing);
    });

    testWidgets('att kryssa ur ett län smalnar av valet', (tester) async {
      Set<String>? changed;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CountyChecklist(
              licensed: const ['01', '05', '08'],
              names: _names,
              selected: const {},
              onChanged: (next) => changed = next,
            ),
          ),
        ),
      );
      await tester.tap(find.text('Kalmar'));
      expect(changed, {'01', '05'});
    });

    testWidgets('det sista förbockade länet är låst', (tester) async {
      await pump(tester, licensed: const ['01', '05'], selected: {'05'});
      final boxes = tester
          .widgetList<CheckboxListTile>(find.byType(CheckboxListTile))
          .toList();
      expect(boxes.map((b) => b.value), [false, true]);
      expect(boxes[0].onChanged, isNotNull);
      expect(boxes[1].onChanged, isNull);
    });
  });

  group('CountyPickerSheet ("Dina län")', () {
    Future<void> pumpSheet(WidgetTester tester, _CountyApi api) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: Scaffold(body: CountyPickerSheet(api: api)),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('visar en kryssruta per län, alla förbockade', (tester) async {
      SharedPreferences.setMockInitialValues({});
      await pumpSheet(tester, _CountyApi(['01', '05', '08']));
      expect(find.byType(CheckboxListTile), findsNWidgets(3));
      expect(_checkboxValues(tester), [true, true, true]);
      expect(find.text('Byt provets län'), findsNothing);
    });

    testWidgets('ett gammalt val med ett län ger alla tre när licensen växt', (
      tester,
    ) async {
      SharedPreferences.setMockInitialValues({
        CountySelectionStore.countiesKey: ['01'],
        CountySelectionStore.licensedKey: ['01'],
      });
      await pumpSheet(tester, _CountyApi(['01', '05', '08']));
      expect(_checkboxValues(tester), [true, true, true]);
    });

    testWidgets('ett län som tas bort försvinner, bortvalet står kvar', (
      tester,
    ) async {
      SharedPreferences.setMockInitialValues({
        CountySelectionStore.countiesKey: ['01', '05'],
        CountySelectionStore.licensedKey: ['01', '05', '08'],
      });
      await pumpSheet(tester, _CountyApi(['01', '08']));
      expect(find.byType(CheckboxListTile), findsNWidgets(2));
      // Kalmar (08) valdes bort förut och ligger kvar urbockat.
      expect(_checkboxValues(tester), [false, true]);
    });

    testWidgets('att kryssa ur sparar valet och skickar det till servern', (
      tester,
    ) async {
      SharedPreferences.setMockInitialValues({});
      final api = _CountyApi(['01', '05', '08']);
      await pumpSheet(tester, api);
      await tester.tap(find.text('Kalmar'));
      await tester.pumpAndSettle();
      expect(_checkboxValues(tester), [false, true, true]);
      expect(api.saved.last, ['01', '05']);
      final stored = await CountySelectionStore.load();
      expect(stored.counties, {'01', '05'});
      expect(stored.licensed, {'01', '05', '08'});
    });
  });

  group('förarskärmen', () {
    Future<void> pumpDriver(WidgetTester tester, _CountyApi api) async {
      // Ingen GPS i testet: platstjänsten är avslagen.
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        const MethodChannel('flutter.baseflow.com/geolocator'),
        (call) async =>
            call.method == 'isLocationServiceEnabled' ? false : null,
      );
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTaxiTheme(),
          home: DriverScreen(api: api, onOpenSettings: () {}),
        ),
      );
      await settleDriverScreen(tester);
    }

    testWidgets('ett sparat län från förr följer med när admin ger tre', (
      tester,
    ) async {
      SharedPreferences.setMockInitialValues({
        CountySelectionStore.countiesKey: ['01'],
        CountySelectionStore.licensedKey: ['01'],
      });
      final api = _CountyApi(['01', '05', '08']);
      await pumpDriver(tester, api);

      // Det gamla valet skickades aldrig till servern före avstämningen.
      expect(api.saved, isNot(contains(equals(['01']))));
      expect(api.saved.last, ['01', '05', '08']);
      // Listan hämtas om med alla licensens län (null = alla).
      expect(api.feedCounties.last, isNull);
      final stored = await CountySelectionStore.load();
      expect(stored.counties, isEmpty);
      expect(stored.licensed, {'01', '05', '08'});
      await disposeScreen(tester);
    });

    testWidgets('ett val från en äldre app avgörs av servern', (tester) async {
      // Ingen anteckning lokalt; servern har stämt av och vet att föraren
      // valt bort Kalmar.
      SharedPreferences.setMockInitialValues({
        CountySelectionStore.countiesKey: ['01'],
      });
      final api = _CountyApi(
        ['01', '05', '08'],
        serverPrefs: {
          'counties': ['01', '05'],
          'entitledCounties': ['01', '05', '08'],
        },
      );
      await pumpDriver(tester, api);
      expect(api.feedCounties.last, ['01', '05']);
      final stored = await CountySelectionStore.load();
      expect(stored.counties, {'01', '05'});
      expect(stored.licensed, {'01', '05', '08'});
      await disposeScreen(tester);
    });

    testWidgets('licensen krymper medan appen är öppen', (tester) async {
      SharedPreferences.setMockInitialValues({
        CountySelectionStore.countiesKey: ['01', '05'],
        CountySelectionStore.licensedKey: ['01', '05', '08'],
      });
      final api = _CountyApi(['01', '05', '08']);
      await pumpDriver(tester, api);
      expect(api.feedCounties.last, ['01', '05']);

      api.licensed = ['01', '08'];
      // Nästa hämtning (poll, återkomst, dra-för-att-uppdatera) läser licensen.
      await tester.pump(const Duration(seconds: 75));
      await settleDriverScreen(tester);
      expect(api.feedCounties.last, ['01']);
      await disposeScreen(tester);
    });
  });
}
