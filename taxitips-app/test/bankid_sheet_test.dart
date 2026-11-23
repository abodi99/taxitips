import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';
import 'package:taxitips_app/bankid_flow.dart';

/// BankID-rutan: öppnar BankID-appen direkt (aldrig webbläsaren) och visar
/// QR-koden när appen inte finns på telefonen, eller när föraren väljer
/// "BankID på en annan telefon".
class _FakeBankIdApi extends ApiClient {
  _FakeBankIdApi({this.oldServer = false})
    : super(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x');

  /// En server före 2026-11-22: kodens delar, aldrig den färdiga koden.
  final bool oldServer;

  int collects = 0;
  final cancelled = <String>[];

  @override
  Future<Map<String, dynamic>> bankIdStart(String purpose) async => {
    'orderRef': 'order-1',
    'autoStartToken': 'auto-1',
    if (oldServer) ...{
      'qrStartToken': 'tok',
      'qrStartSecret': 'hemlig',
    } else
      'qrData': 'bankid.q.0.abc',
  };

  @override
  Future<Map<String, dynamic>> bankIdCollect(String orderRef) async {
    collects++;
    return {
      'status': 'pending',
      'hintCode': 'outstandingTransaction',
      'message': 'Öppna BankID-appen.',
      'qrData': oldServer ? null : 'bankid.q.$collects.def',
    };
  }

  @override
  Future<void> bankIdCancel(String orderRef) async => cancelled.add(orderRef);
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<_FakeBankIdApi> open(
    WidgetTester tester, {
    bool oldServer = false,
  }) async {
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final api = _FakeBankIdApi(oldServer: oldServer);
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () => runBankId(context, api, purpose: 'register'),
                child: const Text('Starta'),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Starta'));
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    return api;
  }

  testWidgets('utan BankID-app på telefonen: QR-koden och ett tydligt besked', (
    tester,
  ) async {
    final opened = <String>[];
    bankIdAppOpener = (token) async {
      opened.add(token);
      return false; // ingen BankID-app på telefonen
    };
    addTearDown(() => bankIdAppOpener = openBankIdApp);
    final api = await open(tester);
    expect(opened, ['auto-1']);
    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.textContaining('hittar inte BankID-appen'), findsOneWidget);
    expect(find.text('BankID på den här telefonen'), findsOneWidget);

    // Koden byts när servern ger en ny.
    await tester.pump(const Duration(seconds: 1));
    expect(api.collects, greaterThan(0));

    await tester.tap(find.text('Avbryt'));
    await tester.pumpAndSettle();
    expect(api.cancelled, ['order-1']);
  });

  testWidgets('med BankID-appen: ingen QR-kod, men den går att välja', (
    tester,
  ) async {
    bankIdAppOpener = (token) async => true;
    addTearDown(() => bankIdAppOpener = openBankIdApp);
    await open(tester);
    expect(find.byType(QrImageView), findsNothing);
    expect(find.text('Öppna BankID'), findsOneWidget);
    await tester.tap(find.text('BankID på en annan telefon'));
    await tester.pump();
    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.textContaining('skanna koden'), findsOneWidget);
    await tester.tap(find.text('Avbryt'));
    await tester.pumpAndSettle();
  });

  testWidgets('servern skickar bara kodens delar: appen räknar QR-koden', (
    tester,
  ) async {
    bankIdAppOpener = (token) async => false;
    addTearDown(() => bankIdAppOpener = openBankIdApp);
    final api = await open(tester, oldServer: true);
    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);

    // Servern svarar utan kod: appens egen kod står kvar, ingen snurra.
    await tester.pump(const Duration(seconds: 1));
    expect(api.collects, greaterThan(0));
    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);

    await tester.tap(find.text('Avbryt'));
    await tester.pumpAndSettle();
  });

  test('QR-koden följer BankID:s format och exempel', () {
    // Exemplet i BankID:s dokumentation ("QR code", tid 0).
    expect(
      bankIdQrData(
        '67df3917-fa0d-44e5-b327-edcc928297f8',
        'd28db9a7-4cde-429e-a983-359be676944c',
        0,
      ),
      'bankid.67df3917-fa0d-44e5-b327-edcc928297f8.0.'
      'dc69358e712458a66a7525beef148ae8526b1c71610eff2c16cdffb4cdac9bf8',
    );
    // Koden byts varje sekund, och tiden går aldrig bakåt.
    expect(bankIdQrData('t', 's', 1), isNot(bankIdQrData('t', 's', 2)));
    expect(bankIdQrData('t', 's', -3), bankIdQrData('t', 's', 0));
  });

  test('BankID öppnas med autostart-token, utan väg tillbaka via webben', () {
    expect(
      bankIdAutostartUri('t').toString(),
      'https://app.bankid.com/?autostarttoken=t&redirect=null',
    );
    expect(bankIdSchemeUri('t').scheme, 'bankid');
  });
}
