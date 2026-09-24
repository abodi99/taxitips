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

  test('I tjänst: positionen i headern, avrundad, aldrig i URL eller body', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'on': true}),
    );
    await api.setPresence(on: true, lat: 55.60498, lon: 13.00382, deviceToken: 'tok-1');
    expect(seen.single.url.path, '/api/presence');
    expect(seen.single.url.queryParameters, isEmpty);
    expect(seen.single.headers['X-TT-Position'], '55.60,13.00');
    expect(jsonDecode(seen.single.body), {'on': true});

    await api.setPresence(on: false, lat: 55.6, lon: 13.0, deviceToken: 'tok-1');
    // Av skickar ingen position alls.
    expect(seen.last.headers.containsKey('X-TT-Position'), isFalse);
    expect(jsonDecode(seen.last.body), {'on': false});
  });

  test('färjor: område i query, position avrundad i headern', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ferries': [], 'terminals': []}),
    );
    await api.ferries(lat: 56.04321, lon: 12.65432, counties: ['12', '01'], deviceToken: 'tok-1');
    expect(seen.single.url.path, '/api/ferries');
    expect(seen.single.url.queryParameters, {'counties': '01,12'});
    expect(seen.single.headers['X-TT-Position'], '56.04,12.65');
    expect(seen.single.headers['X-Device-Token'], 'tok-1');
  });

  test('evenemang: dagar och kommuner i query, ingen position i URL:en', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'events': []}),
    );
    await api.events(lat: 59.33, lon: 18.07, municipalities: ['0180'], deviceToken: 'tok-1');
    expect(seen.single.url.path, '/api/events');
    expect(seen.single.url.queryParameters, {'days': '14', 'municipalities': '0180'});
    expect(seen.single.headers['X-TT-Position'], '59.33,18.07');
  });

  test('evenemang: en vald period skickas som from och to i stället för days', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'events': []}),
    );
    await api.events(from: '2026-10-03', to: '2026-10-05', counties: ['01']);
    expect(seen.single.url.queryParameters, {'from': '2026-10-03', 'to': '2026-10-05', 'counties': '01'});
  });

  test('förartoken följer med som header, inte som query', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000/',
      client: respond({'alerts': [], 'entitled': true}),
    );
    await api.alerts(lat: 55.6, lon: 13.0, deviceToken: 'tok-1');

    expect(seen.single.headers['X-Device-Token'], 'tok-1');
    // Positionen går i en header, avrundad -- aldrig i URL:en, där den hamnar
    // i proxyloggar.
    expect(seen.single.url.queryParameters, isEmpty);
    expect(seen.single.headers['X-TT-Position'], '55.60,13.00');
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

  // --- Favoriter och notiser -------------------------------------------

  test('favorit sparas med opportunity_id och favorite-flagga', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'favorite': true}),
    );
    await api.setFavorite(
      opportunityId: 'opp-1',
      favorite: true,
      note: 'kolla perrongen',
      deviceToken: 'tok-1',
    );

    final body = jsonDecode(seen.single.body) as Map;
    expect(body['opportunity_id'], 'opp-1');
    expect(body['favorite'], true);
    expect(body['note'], 'kolla perrongen');
    expect(seen.single.headers['X-Device-Token'], 'tok-1');
  });

  test('avmarkering skickar favorite: false, inte en radering', () async {
    // POST med favorite:false i stället för DELETE -- samma endpoint åt
    // båda hållen gör stjärnknappen till ETT anrop, och backend svarar
    // idempotent på båda.
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'favorite': false, 'removed': true}),
    );
    await api.setFavorite(opportunityId: 'opp-1', favorite: false);
    expect((jsonDecode(seen.single.body) as Map)['favorite'], false);
  });

  test('note utelämnas helt när den inte satts', () async {
    // `?note` får inte bli "note": null -- backend skulle skriva över en
    // befintlig anteckning med tom sträng.
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'favorite': true}),
    );
    await api.setFavorite(opportunityId: 'opp-1', favorite: true);
    expect((jsonDecode(seen.single.body) as Map).containsKey('note'), isFalse);
  });

  test('favoritlistan skickar position så avståndet kan räknas', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'favorites': []}),
    );
    await api.favorites(lat: 55.6, lon: 13.0, deviceToken: 'tok-1');
    expect(seen.single.url.path, '/api/favorites');
    expect(seen.single.url.queryParameters, {'lat': '55.6', 'lon': '13.0'});
  });

  test('notishistoriken bär skälet när enheten saknas', () async {
    // "Ingen parad telefon" är ett annat svar än "du har inte fått några
    // notiser än", och en tom lista utan skäl hade blandat ihop dem.
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({
        'notifications': [],
        'reason': 'no_device',
        'hint': 'Notiser skickas till en parad enhet.',
      }),
    );
    final body = await api.notifications(accessToken: 'jwt-abc');
    expect(body['reason'], 'no_device');
    expect(body['notifications'], isEmpty);
  });

  test('notisinställningar skickar län och orter var för sig', () async {
    // Två skilda filter med olika tillförlitlighet: länet finns på alla
    // tips, orten på 39%. Slås de ihop i klienten går den skillnaden
    // förlorad -- se core/notify.py.
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'prefs': {}}),
    );
    await api.saveNotifyPrefs(
      enabled: true,
      regions: ['skane', 'rail'],
      cities: ['Malmö'],
      types: {'line_paused': true},
      deviceToken: 'tok-1',
    );

    final body = jsonDecode(seen.single.body) as Map;
    expect(body['regions'], ['skane', 'rail']);
    expect(body['cities'], ['Malmö']);
    expect(body['types'], {'line_paused': true});
  });

  test('ospecificerade fält utelämnas i stället för att nollställas', () async {
    // Sparar man bara "av/på" ska länsvalen ligga kvar. Skickas de som
    // null tolkar backend det som en tom lista -- alltså "alla län", vilket
    // tyst hade tagit bort förarens geografiska filter.
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'prefs': {}}),
    );
    await api.saveNotifyPrefs(enabled: false);

    final body = jsonDecode(seen.single.body) as Map;
    expect(body, {'enabled': false});
  });

  test('ägarens vägar bär inloggningen, aldrig en förartoken', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({'ok': true, 'companyId': 'c1'}, status: 201),
    );
    await api.ownerPost(
      'register',
      {'orgNumber': '5560360793', 'companyName': 'Nya Taxi AB'},
      accessToken: 'jwt-1',
    );
    expect(seen.single.url.path, '/api/fleet/register');
    expect(seen.single.headers['Authorization'], 'Bearer jwt-1');
    expect(seen.single.headers.containsKey('X-Device-Token'), isFalse);
    expect(jsonDecode(seen.single.body)['companyName'], 'Nya Taxi AB');
  });

  test('ägarens fel når fram med skäl, t.ex. ett orgnr som redan finns', () async {
    final api = BackendApi(
      baseUrl: 'http://localhost:8000',
      client: respond({
        'ok': false,
        'reason': 'company_exists',
        'message': 'Företaget har redan ett konto.',
      }, status: 409),
    );
    await expectLater(
      api.ownerPost('register', {}, accessToken: 'jwt-1'),
      throwsA(isA<ApiException>()
          .having((e) => e.reason, 'reason', 'company_exists')
          .having((e) => e.status, 'status', 409)),
    );
  });
}
