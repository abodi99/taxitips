import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:taxibehov_app/api_client.dart' show ApiException;
import 'package:taxibehov_app/backend_api.dart';

/// Klientsidan av parkoppling och skiftbyte.
///
/// Tyngdpunkten ligger på det som kan gå tyst fel: en hemlighet som hamnar i
/// en URL, en `force` som skickas utan att föraren fått frågan, och ett
/// felskäl som appen inte kan grena på.
void main() {
  late List<http.Request> seen;

  MockClient respond(Object body, {int status = 200}) {
    seen = [];
    return MockClient((req) async {
      seen.add(req);
      return http.Response(
        jsonEncode(body),
        status,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    });
  }

  test('parkoppling skickar koden i kroppen, aldrig i URL:en', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({
        'ok': true,
        'deviceToken': 'hemlighet-123',
        'plate': 'ABC123',
      }),
    );
    final result = await api.pair(
      code: 'ABCD2345',
      installationId: 'installation-1234567890',
      label: 'Nattbil',
      platform: 'android',
    );

    expect(seen.single.url.path, '/api/fleet/pair');
    // En kod i query-strängen hamnar i serverloggar och i proxyhistorik.
    expect(seen.single.url.query, isEmpty);
    expect(jsonDecode(seen.single.body), {
      'code': 'ABCD2345',
      'installation_id': 'installation-1234567890',
      'label': 'Nattbil',
      'platform': 'android',
    });
    // Parkopplingen bär ingen enhetstoken -- det är anropet som skapar den.
    expect(seen.single.headers.containsKey('X-Device-Token'), isFalse);
    expect(result['deviceToken'], 'hemlighet-123');
  });

  test('bilstatus bär enhetstoken som header, inte som query', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'vehicles': [], 'session': null}),
    );
    await api.fleetStatus(deviceToken: 'hemlighet-123');

    expect(seen.single.url.path, '/api/fleet/me');
    expect(seen.single.url.query, isEmpty);
    expect(seen.single.headers['X-Device-Token'], 'hemlighet-123');
  });

  test('bilvalet skickar force: false först', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'sessionId': 's1'}),
    );
    await api.startVehicleSession(
      licenseId: 'lic-1',
      deviceToken: 'hemlighet-123',
    );
    expect(jsonDecode(seen.single.body), {
      'license_id': 'lic-1',
      'force': false,
    });
  });

  test('övertagande skickar force: true', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'sessionId': 's2'}),
    );
    await api.startVehicleSession(
      licenseId: 'lic-1',
      deviceToken: 'hemlighet-123',
      force: true,
    );
    expect(jsonDecode(seen.single.body)['force'], isTrue);
  });

  test('takeover_required kommer fram som ett skäl appen kan grena på', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({
        'ok': false,
        'reason': 'takeover_required',
        'message': 'Nattbil använder bilen. Vill du ta över?',
        'detail': {'currentDeviceLabel': 'Nattbil'},
      }, status: 409),
    );

    try {
      await api.startVehicleSession(
        licenseId: 'lic-1',
        deviceToken: 'hemlighet-123',
      );
      fail('skulle ha kastat');
    } on ApiException catch (e) {
      // Grenen går på `reason`, inte på texten: en omformulering i backend
      // ska inte kunna få frågan till föraren att utebli.
      expect(e.reason, 'takeover_required');
      expect(e.status, 409);
      expect(e.detail?['currentDeviceLabel'], 'Nattbil');
      expect(e.message, contains('Vill du ta över'));
    }
  });

  test('bolagskoden skapar en ansökan och ger ingen token', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({
        'ok': true,
        'companyName': 'Taxi Demo AB',
        'message': 'Ansökan skickad.',
      }),
    );
    final result = await api.joinRequest(
      joinCode: 'ABC123',
      installationId: 'installation-1234567890',
    );

    expect(seen.single.url.path, '/api/fleet/join-request');
    // Det här är hela poängen: koden får inte kunna ge en credential.
    expect(result.containsKey('deviceToken'), isFalse);
    expect(result.containsKey('token'), isFalse);
  });

  test('ett fel utan reason blir ändå ett begripligt meddelande', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'error': 'Något gick fel'}, status: 500),
    );
    try {
      await api.fleetStatus(deviceToken: 'x');
      fail('skulle ha kastat');
    } on ApiException catch (e) {
      expect(e.message, 'Något gick fel');
      expect(e.reason, isNull);
    }
  });
}
