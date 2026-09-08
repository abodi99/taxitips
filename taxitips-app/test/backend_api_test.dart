import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:taxibehov_app/api_client.dart' show ApiException;
import 'package:taxibehov_app/backend_api.dart';

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

  test('förartoken följer med som header, inte som query', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000/',
      client: respond({'alerts': [], 'entitled': true}),
    );
    await api.alerts(lat: 55.6, lon: 13.0, deviceToken: 'tok-1');

    expect(seen.single.headers['X-Device-Token'], 'tok-1');
    expect(seen.single.url.queryParameters, {'lat': '55.6', 'lon': '13.0'});
    // Avslutande snedstreck i basadressen får inte bli en dubbel i sökvägen.
    expect(seen.single.url.path, '/api/alerts');
  });

  test('ägarens JWT skickas som Bearer när den finns', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'alerts': [], 'entitled': true}),
    );
    await api.alerts(accessToken: 'jwt-abc');
    expect(seen.single.headers['Authorization'], 'Bearer jwt-abc');
  });

  test('utan tokens skickas inga tomma auth-headers', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'alerts': [], 'entitled': false, 'reason': 'x'}),
    );
    await api.alerts(deviceToken: '', accessToken: null);
    expect(seen.single.headers.containsKey('X-Device-Token'), isFalse);
    expect(seen.single.headers.containsKey('Authorization'), isFalse);
  });

  test('ej berättigad är ett svar, inte ett fel', () async {
    // Tomt flöde ska rendera som "inga tips just nu", inte krascha kortet.
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({
        'alerts': [],
        'entitled': false,
        'reason': 'unknown_device_token',
      }),
    );
    final body = await api.alerts(deviceToken: 'fel');
    expect(body['entitled'], isFalse);
    expect(body['alerts'], isEmpty);
  });

  test('felstatus blir ApiException med backendens skäl', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'error': 'not_entitled'}, status: 403),
    );
    expect(
      () => api.opportunityDetail('abc', deviceToken: 'tok'),
      throwsA(
        isA<ApiException>()
            .having((e) => e.status, 'status', 403)
            .having((e) => e.message, 'message', 'not_entitled'),
      ),
    );
  });

  test('feedback skickar opportunity_id och verdict', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true}),
    );
    await api.submitFeedback(
      opportunityId: 'op-1',
      verdict: 'heading',
      deviceToken: 'tok',
    );
    expect(jsonDecode(seen.single.body), {
      'opportunity_id': 'op-1',
      'verdict': 'heading',
    });
  });
}
