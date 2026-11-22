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
  _FakeBankIdApi()
    : super(supabaseUrl: 'http://localhost', supabaseAnonKey: 'x');

  int collects = 0;
  final cancelled = <String>[];

  @override
  Future<Map<String, dynamic>> bankIdStart(String purpose) async => {
    'orderRef': 'order-1',
    'autoStartToken': 'auto-1',
    'qrData': 'bankid.q.0.abc',
  };

  @override
  Future<Map<String, dynamic>> bankIdCollect(String orderRef) async {
    collects++;
    return {
      'status': 'pending',
      'hintCode': 'outstandingTransaction',
      'message': 'Öppna BankID-appen.',
      'qrData': 'bankid.q.$collects.def',
    };
  }

  @override
  Future<void> bankIdCancel(String orderRef) async => cancelled.add(orderRef);
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<_FakeBankIdApi> open(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final api = _FakeBankIdApi();
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

  test('BankID öppnas med autostart-token, utan väg tillbaka via webben', () {
    expect(
      bankIdAutostartUri('t').toString(),
      'https://app.bankid.com/?autostarttoken=t&redirect=null',
    );
    expect(bankIdSchemeUri('t').scheme, 'bankid');
  });
}
