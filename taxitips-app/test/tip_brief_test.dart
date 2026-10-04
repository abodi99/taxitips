import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/signal_card.dart';
import 'package:taxitips_app/widgets/tip_sheet.dart';

void main() {
  final now = DateTime.now();
  String iso(DateTime t) => t.toUtc().toIso8601String();

  Map<String, dynamic> tip({String? brief, bool active = true}) => {
    'id': 't1',
    'title': 'Inställd tur',
    'summary': 'Inställd p.g.a. fordonsfel.',
    'kind': 'transit',
    'mode': 'bus',
    'severity_tier': 'vehicle_cancelled',
    'minor': false,
    'level': 'high',
    'is_active': active,
    'lat': 59.33,
    'lon': 18.06,
    'start_time': iso(now.subtract(const Duration(minutes: 5))),
    'end_time': iso(now.add(Duration(minutes: active ? 40 : -5))),
    'brief': ?brief,
  };

  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pump(WidgetTester tester, Widget child) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTaxiTheme(),
        home: Scaffold(body: child),
      ),
    );
    await tester.pump();
  }

  testWidgets('kortet visar beskedet när avgångsuppgift saknas', (
    tester,
  ) async {
    await pump(
      tester,
      SignalCard(alert: tip(brief: 'Buss inställd vid Slussen – fordonsfel')),
    );
    expect(find.text('Buss inställd vid Slussen – fordonsfel'), findsOneWidget);
  });

  testWidgets('utan besked ser kortet ut som förut', (tester) async {
    await pump(tester, SignalCard(alert: tip()));
    expect(tipBrief(tip()), isNull);
    expect(find.byType(SignalCard), findsOneWidget);
  });

  testWidgets(
    'bladet visar beskedet under platsen, inte för ett avslutat tips',
    (tester) async {
      final api = ApiClient(
        supabaseUrl: 'http://localhost',
        supabaseAnonKey: 'x',
      );
      await pump(
        tester,
        SizedBox(
          height: 720,
          child: TipSheetBody(
            alert: tip(brief: 'Buss inställd vid Slussen'),
            api: api,
          ),
        ),
      );
      expect(find.byKey(const ValueKey('tip-brief')), findsOneWidget);

      await pump(
        tester,
        SizedBox(
          height: 720,
          child: TipSheetBody(
            alert: tip(brief: 'Buss inställd vid Slussen', active: false),
            api: api,
          ),
        ),
      );
      expect(find.byKey(const ValueKey('tip-brief')), findsNothing);
    },
  );
}
