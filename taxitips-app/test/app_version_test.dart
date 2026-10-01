import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/app_version.dart';
import 'package:taxitips_app/widgets/force_upgrade_overlay.dart';

AppVersion v(String s) => AppVersion.tryParse(s)!;

Map<String, dynamic> config({
  String? min,
  String? recommended,
  String? storeUrl = 'https://play.google.com/store/apps/details?id=x',
  String? message,
}) => {
  'notifyScoreFloor': 50,
  'appVersion': {
    'android': {'min': min, 'recommended': recommended, 'storeUrl': storeUrl},
    'ios': {'min': null, 'recommended': null, 'storeUrl': null},
    'message': message,
  },
};

UpgradeAction decide(String installed, Map<String, dynamic>? cfg) =>
    decideUpgrade(
      installed: AppVersion.tryParse(installed),
      policy: UpgradePolicy.fromConfig(cfg, 'android'),
    ).action;

void main() {
  group('AppVersion', () {
    test('leden jämförs som tal, inte som text', () {
      expect(v('1.0.10').compareTo(v('1.0.9')), 1);
      expect(v('1.0.9').isBelow(v('1.0.10')), isTrue);
      expect(v('2.0').compareTo(v('1.99.99')), 1);
    });

    test('saknade led är noll', () {
      expect(v('1.2').compareTo(v('1.2.0')), 0);
      expect(v('1').isBelow(v('1.0.1')), isTrue);
    });

    test('byggnumret räknas bara när båda har ett', () {
      expect(v('1.0.1+3').isBelow(v('1.0.1+5')), isTrue);
      expect(v('1.0.1+7').compareTo(v('1.0.1')), 0);
      expect(v('1.0.2+1').compareTo(v('1.0.1+99')), 1);
    });

    test('installerad version byggs av version + buildNumber', () {
      expect(AppVersion.installed('1.0.1', '2').toString(), '1.0.1+2');
      expect(AppVersion.installed('1.0.1', '').toString(), '1.0.1');
    });

    test('skräp är ingen version', () {
      for (final s in [
        '',
        'v1.0',
        '1.0.0-beta',
        '1..2',
        '99999',
        '1.2.3.4.5',
      ]) {
        expect(AppVersion.tryParse(s), isNull, reason: s);
      }
    });
  });

  group('decideUpgrade', () {
    test('under minsta version blockeras', () {
      expect(decide('1.0.1+2', config(min: '1.0.2')), UpgradeAction.block);
      expect(decide('1.0.9', config(min: '1.0.10')), UpgradeAction.block);
      expect(decide('1.0.2+1', config(min: '1.0.2+5')), UpgradeAction.block);
    });

    test('under rekommenderad version föreslås en uppdatering', () {
      expect(
        decide('1.0.2', config(min: '1.0.1', recommended: '1.0.3')),
        UpgradeAction.nudge,
      );
    });

    test('ny nog: ingenting', () {
      expect(
        decide('1.0.10', config(min: '1.0.9', recommended: '1.0.10')),
        UpgradeAction.none,
      );
      expect(decide('1.0.2+1', config(min: '1.0.2')), UpgradeAction.none);
      expect(decide('1.0.1', config()), UpgradeAction.none);
    });

    test('okänt släpper igenom (fail open)', () {
      // Anropet misslyckades.
      expect(decide('1.0.1', null), UpgradeAction.none);
      // Äldre server utan blocket.
      expect(decide('1.0.1', {'notifyScoreFloor': 50}), UpgradeAction.none);
      // Trasigt värde från servern.
      expect(decide('1.0.1', config(min: 'nästa')), UpgradeAction.none);
      // Oläsbar installerad version.
      expect(decide('okänd', config(min: '9.0.0')), UpgradeAction.none);
    });

    test('ingen butikslänk: aldrig en spärr utan väg ut', () {
      expect(
        decide('1.0.1', config(min: '1.0.2', storeUrl: null)),
        UpgradeAction.nudge,
      );
    });

    test('Remote Config fyller tomma backend-fält', () {
      final remote = const UpgradePolicy(
        min: '1.0.3',
        recommended: null,
        storeUrl: 'https://play.example/a',
        message: 'Från RC',
      );
      final backend = UpgradePolicy.fromConfig(
        config(min: '1.0.2', recommended: '1.0.4', message: 'Från API'),
        'android',
      );
      final merged = UpgradePolicy.merge(remote, backend)!;
      expect(merged.min, '1.0.3');
      expect(merged.recommended, '1.0.4');
      expect(merged.storeUrl, 'https://play.example/a');
      expect(merged.message, 'Från RC');
    });

    test('meddelandet följer med', () {
      final d = decideUpgrade(
        installed: v('1.0.1'),
        policy: UpgradePolicy.fromConfig(
          config(min: '1.0.2', message: 'Ny karta.'),
          'android',
        ),
      );
      expect(d.required, '1.0.2');
      expect(d.message, 'Ny karta.');
    });
  });

  group('ForceUpgradeOverlay', () {
    var taps = 0;
    setUp(() => taps = 0);

    Widget app({
      required Future<Map<String, dynamic>> Function() fetch,
      String installed = '1.0.1+2',
    }) => MaterialApp(
      builder: (context, child) => ForceUpgradeOverlay(
        platform: 'android',
        fetchConfig: fetch,
        installedVersion: () async => AppVersion.tryParse(installed),
        child: child!,
      ),
      home: Scaffold(
        body: Center(
          child: ElevatedButton(
            onPressed: () => taps++,
            child: const Text('Tips'),
          ),
        ),
      ),
    );

    testWidgets('spärren täcker appen och går inte att stänga', (t) async {
      await t.pumpWidget(app(fetch: () async => config(min: '1.0.2')));
      await t.pumpAndSettle();
      expect(find.text('Uppdatera appen'), findsOneWidget);
      expect(find.text('Uppdatera'), findsOneWidget);
      expect(find.byIcon(Icons.close), findsNothing);
      expect(find.textContaining('Krävs: 1.0.2'), findsOneWidget);
      // Knappen under spärren går inte att nå.
      await t.tap(find.text('Tips'), warnIfMissed: false);
      expect(taps, 0);
    });

    testWidgets('banderollen går att stänga', (t) async {
      await t.pumpWidget(
        app(
          fetch: () async => config(min: '1.0.0', recommended: '1.0.5'),
        ),
      );
      await t.pumpAndSettle();
      expect(
        find.text('Ny version finns. Uppdatera när du kan.'),
        findsOneWidget,
      );
      expect(find.text('Uppdatera appen'), findsNothing);
      await t.tap(find.byIcon(Icons.close));
      await t.pump();
      expect(
        find.text('Ny version finns. Uppdatera när du kan.'),
        findsNothing,
      );
      await t.tap(find.text('Tips'));
      expect(taps, 1);
    });

    testWidgets('servern nere: appen körs som vanligt', (t) async {
      await t.pumpWidget(app(fetch: () async => throw Exception('503')));
      await t.pumpAndSettle();
      expect(find.text('Uppdatera appen'), findsNothing);
      expect(
        find.text('Ny version finns. Uppdatera när du kan.'),
        findsNothing,
      );
      expect(find.text('Tips'), findsOneWidget);
    });

    testWidgets('en sänkt gräns släpper när appen kommer tillbaka', (t) async {
      var cfg = config(min: '1.0.2');
      await t.pumpWidget(app(fetch: () async => cfg));
      await t.pumpAndSettle();
      expect(find.text('Uppdatera appen'), findsOneWidget);
      cfg = config(min: '1.0.1');
      t.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await t.pumpAndSettle();
      expect(find.text('Uppdatera appen'), findsNothing);
    });
  });

  group('spärrade versioner (Remote Config)', () {
    UpgradeDecision decide(
      String installed,
      List<String> blocked, {
      String? store = 'https://play.google.com/x',
    }) => decideUpgrade(
      installed: AppVersion.tryParse(installed),
      policy: UpgradePolicy(
        min: '1.0.0',
        recommended: '1.5.0',
        storeUrl: store,
        blocked: blocked,
      ),
    );

    test('en spärrad version blockeras trots att den är över min', () {
      final d = decide('1.4.0+31', ['1.4.0']);
      expect(d.action, UpgradeAction.block);
      expect(d.required, '1.5.0');
    });

    test('ett spärrat bygge träffar bara det bygget', () {
      expect(decide('1.4.0+31', ['1.4.0+31']).action, UpgradeAction.block);
      expect(decide('1.4.0+32', ['1.4.0+31']).action, UpgradeAction.nudge);
    });

    test('ingen butikslänk ger förslag, aldrig utelåsning', () {
      expect(
        decide('1.4.0', ['1.4.0'], store: null).action,
        UpgradeAction.nudge,
      );
    });

    test('listan tål mellanslag och skräp', () {
      expect(UpgradePolicy.parseList(' 1.4.0, 1.4.1+33 ;x, '), [
        '1.4.0',
        '1.4.1+33',
      ]);
      expect(UpgradePolicy.parseList(null), isEmpty);
    });

    test('listorna från Remote Config och servern slås ihop', () {
      final merged = UpgradePolicy.merge(
        const UpgradePolicy(blocked: ['1.4.0']),
        const UpgradePolicy(blocked: ['1.3.9'], storeUrl: 'x'),
      )!;
      expect(merged.blocked, containsAll(['1.4.0', '1.3.9']));
    });
  });
}
