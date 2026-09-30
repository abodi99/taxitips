import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxibehov_app/api_client.dart' show ApiException;
import 'package:taxibehov_app/feed_cache.dart';
import 'package:taxibehov_app/net_status.dart';
import 'package:taxibehov_app/pending_feedback.dart';
import 'package:taxibehov_app/widgets/offline_banner.dart';

void main() {
  group('netFailureOf', () {
    test('ClientException med värduppslag = offline', () {
      final e = http.ClientException(
        'Failed host lookup: api.taxitips.se',
      );
      expect(netFailureOf(e), NetFailure.offline);
    });

    test('ClientException med återställd anslutning = servern nåddes inte', () {
      final e = http.ClientException('Connection reset by peer');
      expect(netFailureOf(e), NetFailure.unreachable);
    });

    test('TimeoutException = timeout', () {
      expect(netFailureOf(TimeoutException('x')), NetFailure.timeout);
    });

    test('serverfel med meddelande är inget nätfel', () {
      expect(netFailureOf(ApiException(500, 'Något hände')), isNull);
      expect(netFailureOf(ApiException(403, 'Ingen åtkomst')), isNull);
      expect(netFailureOf(FormatException('x')), isNull);
    });

    test('ApiException med net-reason klassas', () {
      final e = ApiException(
        0,
        netMessage(NetFailure.offline),
        reason: netReason(NetFailure.offline),
      );
      expect(netFailureOf(e), NetFailure.offline);
      expect(isNetworkError(e), isTrue);
    });
  });

  group('text', () {
    test('korta svenska meddelanden', () {
      expect(netMessage(NetFailure.offline), 'Ingen internetanslutning');
      expect(netMessage(NetFailure.unreachable), 'Servern svarar inte just nu');
    });

    test('friendlyError läcker aldrig råtext', () {
      expect(
        friendlyError(http.ClientException('Failed host lookup: x')),
        'Ingen internetanslutning',
      );
      expect(friendlyError(ApiException(409, 'Bilen är upptagen')), 'Bilen är upptagen');
      expect(
        friendlyError(StateError('intern detalj')),
        'Något gick fel. Försök igen.',
      );
    });

    test('netAwareText tar bort prefix för övriga fel', () {
      expect(netAwareText(Exception('Fel kod')), 'Fel kod');
    });
  });

  test('retryDelay växer och når taket 60 s', () {
    final secs = [for (var i = 0; i < 8; i++) retryDelay(i).inSeconds];
    expect(secs, [4, 8, 16, 32, 60, 60, 60, 60]);
    expect(retryDelay(-1).inSeconds, 4);
  });

  test('NetAwareClient gör nätfel till ApiException', () async {
    final client = NetAwareClient(
      _Throwing(http.ClientException('Failed host lookup: x')),
    );
    await expectLater(
      client.get(Uri.parse('https://example.invalid')),
      throwsA(
        isA<ApiException>().having((e) => e.reason, 'reason', 'net_offline'),
      ),
    );
  });

  group('FeedCache', () {
    final now = DateTime(2026, 9, 30, 12, 0);
    String raw({required DateTime saved, String? end}) =>
        '{"v":1,"savedAt":${saved.millisecondsSinceEpoch},"data":'
        '{"alerts":[{"id":"a","end_time":${end == null ? 'null' : '"$end"'},'
        '"is_active":true},{"id":"b","end_time":null,"is_active":true}],'
        '"favorites":[],"source":"django"}}';

    test('utgånget tips gråas, tips utan sluttid lämnas', () {
      final d = FeedCache.decode(
        raw(
          saved: now.subtract(const Duration(minutes: 5)),
          end: now.subtract(const Duration(minutes: 1)).toUtc().toIso8601String(),
        ),
        now: now,
      )!;
      final alerts = d['alerts'] as List;
      expect(alerts[0]['is_active'], false);
      expect(alerts[1]['is_active'], true);
      expect(d['active'], alerts);
      expect(d['fromCache'], true);
    });

    test('pågående tips förblir aktivt', () {
      final d = FeedCache.decode(
        raw(
          saved: now,
          end: now.add(const Duration(hours: 1)).toUtc().toIso8601String(),
        ),
        now: now,
      )!;
      expect((d['alerts'] as List)[0]['is_active'], true);
    });

    test('för gammal cache visas inte', () {
      expect(
        FeedCache.decode(
          raw(saved: now.subtract(const Duration(hours: 25))),
          now: now,
        ),
        isNull,
      );
    });

    test('updatedAt är när det hämtades', () {
      final saved = now.subtract(const Duration(minutes: 8));
      final d = FeedCache.decode(raw(saved: saved), now: now)!;
      expect(d['updatedAt'], saved.millisecondsSinceEpoch);
    });

    test('expireFeed ändrar inte indatan', () {
      final input = {
        'alerts': [
          {'id': 'a', 'end_time': '2020-01-01T00:00:00Z', 'is_active': true},
        ],
      };
      final out = FeedCache.expireFeed(input, now);
      expect((out['alerts'] as List)[0]['is_active'], false);
      expect((input['alerts'] as List)[0]['is_active'], true);
    });

    test('save + load går via disk', () async {
      SharedPreferences.setMockInitialValues({});
      await FeedCache.save({
        'alerts': [
          {'id': 'a', 'end_time': null, 'is_active': true},
        ],
        'source': 'django',
      });
      final d = await FeedCache.load();
      expect((d!['alerts'] as List).length, 1);
    });
  });

  group('PendingFeedback', () {
    final now = DateTime(2026, 9, 30, 12);
    test('köar, ersätter dubbletter och gallrar gamla', () async {
      SharedPreferences.setMockInitialValues({});
      await PendingFeedback.add('1', 'fare', now: now);
      await PendingFeedback.add('1', 'fare', now: now);
      await PendingFeedback.add('2', 'empty', now: now);
      expect((await PendingFeedback.load(now: now)).length, 2);
      final later = now.add(const Duration(hours: 49));
      expect(await PendingFeedback.load(now: later), isEmpty);
    });
  });

  group('OfflineBanner', () {
    testWidgets('visar tid och Försök igen', (tester) async {
      var taps = 0;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OfflineBanner(
              failure: NetFailure.offline,
              lastUpdated: DateTime(2026, 9, 30, 12, 4),
              onRetry: () => taps++,
            ),
          ),
        ),
      );
      expect(find.text('Offline – visar senaste tips från 12:04'), findsOneWidget);
      await tester.tap(find.text('Försök igen'));
      expect(taps, 1);
    });

    testWidgets('utan data står bara felet', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: OfflineBanner(failure: NetFailure.unreachable)),
        ),
      );
      expect(find.text('Servern svarar inte just nu'), findsOneWidget);
      expect(find.text('Försök igen'), findsNothing);
    });

    testWidgets('visar spinner medan nytt försök pågår', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OfflineBanner(
              failure: NetFailure.timeout,
              retrying: true,
              onRetry: () {},
            ),
          ),
        ),
      );
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Försök igen'), findsNothing);
    });
  });
}

class _Throwing extends http.BaseClient {
  _Throwing(this.error);
  final Object error;
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) =>
      Future.error(error);
}
