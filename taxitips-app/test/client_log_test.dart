import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:taxitips_app/api_client.dart' show ApiException;
import 'package:taxitips_app/backend_api.dart';
import 'package:taxitips_app/client_info.dart';
import 'package:taxitips_app/client_log.dart';

void main() {
  late List<Map<String, dynamic>> sent;

  setUp(() {
    ClientLog.resetForTest();
    sent = [];
  });

  Future<void> flush() => Future<void>.delayed(Duration.zero);

  group('ClientInfo', () {
    test('headrarna tål inte tecken som fäller ett HTTP-anrop', () {
      expect(ClientInfo.clean('Pixel é 8\n'), 'Pixel  8');
      expect(ClientInfo.clean('x' * 100, max: 10), 'x' * 10);
    });

    test('plattformen finns alltid, även innan versionen hunnit läsas', () {
      expect(ClientInfo.headers['X-App-Platform'], isNotEmpty);
    });
  });

  group('BackendApi', () {
    test(
      'varje anrop bär appens plattform, och tokens skrivs inte över',
      () async {
        final seen = <http.Request>[];
        final api = BackendApi(
          baseUrl: 'http://localhost:8000',
          client: MockClient((req) async {
            seen.add(req);
            return http.Response('{"ok": true}', 202);
          }),
        );
        await api.clientLog({
          'kind': 'flow',
          'flow': 'feed',
          'message': 'x',
        }, deviceToken: 'tok-1');
        final req = seen.single;
        expect(req.url.path, '/api/client-log');
        expect(req.method, 'POST');
        expect(req.headers['X-App-Platform'], ClientInfo.platformName());
        expect(req.headers['X-Device-Token'], 'tok-1');
        expect(jsonDecode(req.body), {
          'kind': 'flow',
          'flow': 'feed',
          'message': 'x',
        });
      },
    );
  });

  group('ClientLog', () {
    test('bara kritiska operationer rapporteras', () async {
      ClientLog.attach((body) async => sent.add(body));
      ClientLog.apiFailure('setFavorite', Exception('x'));
      ClientLog.apiFailure(
        'taxi.alerts',
        ApiException(503, 'Backend nere', reason: 'internal_error'),
      );
      await flush();
      expect(sent, hasLength(1));
      expect(sent.single['flow'], 'feed');
      expect(sent.single['kind'], 'flow');
      expect(sent.single['status'], 503);
      expect(sent.single['reason'], 'internal_error');
      expect(sent.single['errorType'], 'ApiException');
    });

    test('samma fel inom fem minuter skickas en gång', () async {
      ClientLog.attach((body) async => sent.add(body));
      for (var i = 0; i < 5; i++) {
        ClientLog.flowFailure('login', Exception('Auth-fel'));
      }
      ClientLog.flowFailure('login', Exception('Annat fel'));
      await flush();
      expect(sent, hasLength(2));
    });

    test('en app i en felloop skickar högst maxPerRun rapporter', () async {
      ClientLog.attach((body) async => sent.add(body));
      for (var i = 0; i < ClientLog.maxPerRun + 20; i++) {
        ClientLog.flowFailure('feed', Exception('fel $i'));
      }
      await flush();
      expect(sent, hasLength(ClientLog.maxPerRun));
    });

    test('fel innan avsändaren finns skickas när den kopplas in', () async {
      ClientLog.flowFailure('me', Exception('tidigt fel'));
      expect(sent, isEmpty);
      ClientLog.attach((body) async => sent.add(body));
      await flush();
      expect(sent.single['message'], contains('tidigt fel'));
    });

    test('en avsändare som kastar blir aldrig ett fel i appen', () async {
      ClientLog.attach((body) async => throw Exception('offline'));
      ClientLog.flowFailure('feed', Exception('x'));
      await flush();
      // Inget kastades hit.
    });

    test('långa texter kapas innan de skickas', () {
      final body = ClientLog.buildBody(
        kind: 'crash',
        flow: 'uncaught',
        error: Exception('a' * 5000),
        stack: StackTrace.fromString('b' * 9000),
      );
      expect((body['message'] as String).length, lessThanOrEqualTo(1000));
      expect((body['stack'] as String).length, lessThanOrEqualTo(4000));
    });

    test('krascher fångas utan att den tidigare hanteraren tappas', () async {
      final originalFlutter = FlutterError.onError;
      final originalPlatform = PlatformDispatcher.instance.onError;
      final previous = <FlutterErrorDetails>[];
      try {
        FlutterError.onError = previous.add;
        ClientLog.installErrorHandlers();
        ClientLog.attach((body) async => sent.add(body));
        FlutterError.onError!(
          FlutterErrorDetails(exception: StateError('trasig widget')),
        );
        await flush();
      } finally {
        FlutterError.onError = originalFlutter;
        PlatformDispatcher.instance.onError = originalPlatform;
      }
      expect(previous, hasLength(1));
      expect(sent.single['kind'], 'crash');
      expect(sent.single['flow'], 'flutter');
      expect(sent.single['message'], contains('trasig widget'));
    });
  });
}
