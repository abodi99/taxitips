import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/membership_copy.dart';
import 'package:taxitips_app/widgets/company_settings_panel.dart';

/// Länbyten på provbilen: servern räknar (`countyChanges` på licensraden,
/// felet `county_change_limit`), appen visar vad som är kvar och stänger av
/// bytet när inget är kvar. Fältet kan saknas -- en äldre server skickar det
/// inte.
class _FakeApi extends ApiClient {
  _FakeApi(this.license, {this.limitReached = false, this.access})
    : super(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x');

  Map<String, dynamic> license;
  final bool limitReached;
  final Map<String, dynamic>? access;
  int loads = 0;
  final changed = <String>[];

  @override
  Future<Map<String, dynamic>> fleetCompany() async {
    loads++;
    return {
      'ok': true,
      'company': {'name': 'Taxi Test AB', 'suspended': false},
      'access': access ?? {'ok': true, 'reason': 'trial', 'validUntil': null},
      'permissions': ['manage_vehicles', 'manage_devices', 'view_company'],
      'trial': {
        'status': 'active',
        'vehicleLimit': 1,
        'vehiclesUsed': 1,
        'endsAt': '2099-01-01T00:00:00Z',
        'cardOnFile': false,
      },
      'licenses': [license],
      'countyCatalog': [
        {'code': '12', 'name': 'Skåne län'},
        {'code': '01', 'name': 'Stockholms län'},
      ],
    };
  }

  @override
  Future<Map<String, dynamic>> setTrialCounty(String licenseId, String base) {
    if (limitReached) {
      throw ApiException(
        409,
        'Du har bytt län två gånger den här månaden. Nästa byte går att göra i november.',
        reason: 'county_change_limit',
      );
    }
    changed.add(base);
    return Future.value({'ok': true});
  }
}

Map<String, dynamic> _license({Map<String, dynamic>? countyChanges}) => {
  'licenseId': 'lic-1',
  'vehicleId': 'veh-1',
  'vehicle': 'ABC123',
  'status': 'trial',
  'baseCounty': '12',
  'counties': ['12'],
  'approvedPhones': <Map>[],
  'pendingInvites': <Map>[],
  'countyChanges': ?countyChanges,
};

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('countyChangesOf', () {
    test('kvar och månadens hela utrymme', () {
      final c = countyChangesOf(
        _license(
          countyChanges: {
            'month': '2026-10',
            'used': 1,
            'limit': 2,
            'extra': 0,
            'remaining': 1,
          },
        ),
      );
      expect(c!.remaining, 1);
      expect(c.total, 2);
      expect(c.label, 'Länbyten kvar den här månaden: 1 av 2');
      expect(c.exhausted, isFalse);
    });

    test('extra byten: utrymmet är kvar + använda, vem som än lägger ihop', () {
      final c = countyChangesOf(
        _license(
          countyChanges: {'used': 1, 'limit': 2, 'extra': 1, 'remaining': 2},
        ),
      );
      expect(c!.label, 'Länbyten kvar den här månaden: 2 av 3');
    });

    test('inga kvar', () {
      final c = countyChangesOf(
        _license(countyChanges: {'used': 2, 'limit': 2, 'remaining': 0}),
      );
      expect(c!.exhausted, isTrue);
      expect(c.label, 'Länbyten kvar den här månaden: 0 av 2');
    });

    test('fältet saknas eller är trasigt: ingen räknare', () {
      expect(countyChangesOf(_license()), isNull);
      expect(countyChangesOf(_license(countyChanges: {'month': 'x'})), isNull);
      expect(countyChangesOf({'countyChanges': 'nej'}), isNull);
    });
  });

  Future<_FakeApi> pumpPanel(WidgetTester tester, _FakeApi api) async {
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: CompanySettingsPanel(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    return api;
  }

  Future<void> openCar(WidgetTester tester) async {
    await tester.tap(find.text('ABC123'));
    await tester.pumpAndSettle();
  }

  testWidgets('visar länbyten kvar vid bilen och låter ägaren byta', (
    tester,
  ) async {
    final api = await pumpPanel(
      tester,
      _FakeApi(
        _license(
          countyChanges: {'used': 1, 'limit': 2, 'extra': 0, 'remaining': 1},
        ),
      ),
    );
    await openCar(tester);
    expect(
      find.textContaining('Länbyten kvar den här månaden: 1 av 2'),
      findsOneWidget,
    );
    expect(find.textContaining('Tryck för att byta län'), findsOneWidget);

    await tester.tap(find.textContaining('Tryck för att byta län'));
    await tester.pumpAndSettle();
    expect(find.text('Var kör bilen?'), findsOneWidget);
    await tester.tap(find.text('Stockholm'));
    await tester.pumpAndSettle();
    expect(api.changed, ['01']);
  });

  testWidgets('inga byten kvar: bytet är avstängt och säger varför', (
    tester,
  ) async {
    final api = await pumpPanel(
      tester,
      _FakeApi(
        _license(countyChanges: {'used': 2, 'limit': 2, 'remaining': 0}),
      ),
    );
    await openCar(tester);
    expect(
      find.textContaining('Länbyten kvar den här månaden: 0 av 2'),
      findsOneWidget,
    );
    expect(find.textContaining('igen nästa månad'), findsOneWidget);
    expect(find.textContaining('Tryck för att byta län'), findsNothing);
    // Raden är en informationsrad, inte en tryckyta.
    await tester.tap(find.textContaining('Länbyten kvar den här månaden'));
    await tester.pumpAndSettle();
    expect(find.text('Var kör bilen?'), findsNothing);
    expect(api.changed, isEmpty);
  });

  testWidgets(
    'äldre server utan countyChanges: ingen räknare, bytet fungerar',
    (tester) async {
      await pumpPanel(tester, _FakeApi(_license()));
      await openCar(tester);
      expect(find.textContaining('Länbyten kvar'), findsNothing);
      expect(find.textContaining('Tryck för att byta län'), findsOneWidget);
    },
  );

  testWidgets('county_change_limit: serverns text visas och bilen läses om', (
    tester,
  ) async {
    final api = await pumpPanel(
      tester,
      _FakeApi(_license(), limitReached: true),
    );
    final loadsBefore = api.loads;
    await openCar(tester);
    await tester.tap(find.textContaining('Tryck för att byta län'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Stockholm'));
    await tester.pumpAndSettle();
    expect(
      find.text(
        'Du har bytt län två gånger den här månaden. Nästa byte går att göra i november.',
      ),
      findsOneWidget,
    );
    // Panelen läser om raden, så att räknaren stämmer.
    expect(api.loads, greaterThan(loadsBefore));
  });

  testWidgets('en betald bil: länet kan inte bytas i appen', (tester) async {
    final paid = _license()..['status'] = 'active';
    await pumpPanel(tester, _FakeApi(paid));
    await openCar(tester);
    expect(find.text('Länet kan inte bytas i appen.'), findsOneWidget);
    expect(find.textContaining('Tryck för att byta län'), findsNothing);
  });

  group('medlemskap i ägarpanelen: neutral text, ingen uppmaning', () {
    testWidgets('provet är slut', (tester) async {
      await pumpPanel(
        tester,
        _FakeApi(
          _license(),
          access: {
            'ok': false,
            'reason': 'trial_ended',
            'message':
                'Provperioden är slut. Kontakta TaxiTips för att fortsätta.',
          },
        ),
      );
      expect(find.text('Provet är slut'), findsOneWidget);
      expect(find.text(kMembershipOnWeb), findsOneWidget);
      expect(find.textContaining('Kontakta TaxiTips'), findsNothing);
    });

    testWidgets(
      'betalningen har inte gått igenom: serverns uppmaning visas inte',
      (tester) async {
        await pumpPanel(
          tester,
          _FakeApi(
            _license(),
            access: {
              'ok': false,
              'reason': 'past_due',
              'message':
                  'Betalningen har inte gått igenom. Uppdatera betalmetoden.',
            },
          ),
        );
        expect(find.text('Pausat'), findsOneWidget);
        expect(find.textContaining('betalmetoden'), findsNothing);
        expect(find.textContaining('Betalningen'), findsNothing);
        expect(find.text(kMembershipOnWeb), findsOneWidget);
      },
    );

    testWidgets('provet visar att något inte ingår, utan länk', (tester) async {
      await pumpPanel(tester, _FakeApi(_license()));
      expect(
        find.textContaining('Det som har ett lås i appen ingår inte i provet.'),
        findsOneWidget,
      );
      expect(find.textContaining('mejl'), findsNothing);
      expect(find.byType(TextButton), findsNothing);
    });
  });
}
