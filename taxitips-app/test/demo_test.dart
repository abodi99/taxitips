import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:taxibehov_app/api_client.dart' show ApiException;
import 'package:taxibehov_app/demo/demo_api_client.dart';
import 'package:taxibehov_app/demo/demo_banner.dart';
import 'package:taxibehov_app/demo/demo_data.dart';
import 'package:taxibehov_app/screens/driver_screen.dart';
import 'package:taxibehov_app/severity_labels.dart';
import 'package:taxibehov_app/signal_kinds.dart';

/// Skriver upp vilka värdar något försöker nå. Kartan hämtar egna
/// kartrutor från en kartserver; det är inte TaxiTips-backenden, och testet
/// säger bara att ingen väg går dit.
class _RecordingHttpOverrides extends HttpOverrides {
  final hosts = <String>[];

  @override
  HttpClient createHttpClient(SecurityContext? context) =>
      _RecordingClient(hosts);
}

/// Låtsasklient: skriver upp värden och vägrar alla anslutningar.
class _RecordingClient implements HttpClient {
  _RecordingClient(this._hosts);
  final List<String> _hosts;

  @override
  dynamic noSuchMethod(Invocation invocation) {
    final args = invocation.positionalArguments;
    final name = invocation.memberName.toString();
    if (name.contains('"openUrl"') || name.contains('"getUrl"')) {
      _hosts.add(args.last is Uri ? (args.last as Uri).host : '?');
      return Future<HttpClientRequest>.error(const SocketException('test'));
    }
    if (name.contains('"open"') || name.contains('"get"')) {
      _hosts.add(args.length > 1 ? args[1].toString() : '?');
      return Future<HttpClientRequest>.error(const SocketException('test'));
    }
    return null;
  }
}

void main() {
  group('demodata', () {
    final now = DateTime.now();
    final snap = DemoData.build(now: now);

    test('täcker varje kategori', () {
      final cats = <SignalCategory>{
        for (final a in snap.alerts) categoryOfAlert(a),
        if (snap.ferries.isNotEmpty) SignalCategory.ferry,
        if (snap.events.isNotEmpty) SignalCategory.event,
      };
      expect(cats, SignalCategory.values.toSet());
    });

    test('blandar styrkor bland tipsen', () {
      final strengths = {for (final a in snap.alerts) strengthOfAlert(a)};
      expect(strengths, containsAll(SignalStrength.values));
    });

    test('alla tips har koordinater, skäl och id', () {
      final ids = <String>{};
      for (final a in snap.alerts) {
        expect(ids.add(a['id'] as String), isTrue, reason: 'unikt id');
        expect(a['lat'], isA<double>());
        expect(a['lon'], isA<double>());
        expect((a['reasons'] as List), isNotEmpty);
        expect(a['title'].toString(), isNotEmpty);
        expect(DateTime.tryParse(a['start_time'] as String), isNotNull);
        expect(DateTime.parse(a['start_time'] as String).isAfter(now), isFalse);
      }
    });

    test('inställt tåg: avgången ligger framåt och ersättningsbuss finns', () {
      final cancelled = snap.alerts.firstWhere(
        (a) => a['severity_tier'] == 'vehicle_cancelled',
      );
      final t = TravelOptions.of(cancelled)!;
      expect(t.hasAlternative, isTrue);
      expect(t.nextDepartureAt!.isAfter(now), isTrue);
      expect(t.headUpcoming, isNotEmpty);
      expect(t.headDeparted, isNotEmpty);
      expect(t.tail, contains('ersättningsbuss'));
      expect(t.text(now: now), contains('om '));
    });

    test('alla avgångar, ankomster och slut ligger i framtiden', () {
      for (final a in snap.alerts) {
        final raw = a['travel_options'];
        if (raw is Map) {
          expect(
            DateTime.parse(raw['next_departure_at'] as String).isAfter(now),
            isTrue,
          );
        }
      }
      for (final f in snap.ferries) {
        expect(DateTime.parse(f['expectedAt'] as String).isAfter(now), isTrue);
        expect(
          DateTime.parse(
            f['pickupUntil'] as String,
          ).isAfter(DateTime.parse(f['pickupFrom'] as String)),
          isTrue,
        );
      }
      for (final e in snap.events) {
        final start = DateTime.parse(e['startAt'] as String);
        final end = DateTime.parse(e['endAt'] as String);
        expect(end.isAfter(start), isTrue);
        expect(end.isAfter(now), isTrue, reason: '${e['name']} slutar framåt');
      }
    });

    test('evenemang slutar snart med besökarprognos', () {
      final ongoing = snap.events.firstWhere((e) => e['ongoing'] == true);
      expect(ongoing['attendanceText'], contains('besökare'));
      expect(ongoing['endLocal'], isNotEmpty);
    });

    test('inga exakta antal väntande kunder påstås', () {
      final text = [
        for (final a in snap.alerts) ...[
          a['title'],
          a['summary'],
          ...a['reasons'],
        ],
      ].join(' ').toLowerCase();
      expect(text, isNot(contains('kunder väntar')));
      expect(
        RegExp(r'\d+ (kunder|passagerare|personer)').hasMatch(text),
        isFalse,
      );
    });
  });

  group('DemoApiClient', () {
    test(
      'favoriter fungerar lokalt och sparas inte någon annanstans',
      () async {
        final api = DemoApiClient();
        var body = await api.taxi();
        expect(
          (body['favorites'] as List).length,
          DemoData.initialFavoriteIds.length,
        );
        await api.setFavorite(opportunityId: 'demo-vag-e4', favorite: true);
        body = await api.taxi();
        expect(
          (body['favorites'] as List).length,
          DemoData.initialFavoriteIds.length + 1,
        );
      },
    );

    test('inget är låst och skrivningar avvisas', () async {
      final api = DemoApiClient();
      final body = await api.taxi();
      expect(body.containsKey('features'), isFalse);
      expect(body['entitled'], isNot(false));
      expect(
        () => api.sendSupportMessage('hej'),
        throwsA(
          isA<ApiException>().having(
            (e) => e.toString(),
            'text',
            demoSavesNothing,
          ),
        ),
      );
    });
  });

  group('demo i förarskärmen', () {
    testWidgets('visar märkningen och pratar aldrig med nätet', (tester) async {
      SharedPreferences.setMockInitialValues({});
      final overrides = _RecordingHttpOverrides();
      final previous = HttpOverrides.current;
      HttpOverrides.global = overrides;
      addTearDown(() => HttpOverrides.global = previous);

      var exited = false;
      var signup = false;
      await tester.binding.setSurfaceSize(const Size(1000, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          home: DriverScreen(
            api: DemoApiClient(),
            demo: true,
            onBack: () => exited = true,
            onDemoSignup: () => signup = true,
          ),
        ),
      );
      await tester.pump(const Duration(seconds: 1));
      await tester.pump(const Duration(seconds: 1));

      expect(find.text(DemoBanner.badgeText), findsOneWidget);
      expect(find.text(DemoBanner.ctaText), findsOneWidget);
      expect(find.text(DemoBanner.exitText), findsOneWidget);
      // Inget lås i kategoriraden.
      expect(find.byIcon(Icons.lock_rounded), findsNothing);
      // Demons tips syns.
      // Kategoriraden visar demons tips (sju tips, en färja, ett event).
      expect(find.text('Alla'), findsOneWidget);
      expect(find.text('9'), findsWidgets);

      await tester.tap(find.text(DemoBanner.ctaText));
      await tester.tap(find.text(DemoBanner.exitText));
      expect(signup, isTrue);
      expect(exited, isTrue);

      for (final host in overrides.hosts) {
        expect(
          host,
          isNot(contains('taxitips')),
          reason: 'backend-anrop i demon',
        );
        expect(host, isNot(contains('127.0.0.1')));
        expect(host, isNot(contains('localhost')));
        expect(host, isNot(contains('supabase')));
      }
    });
  });
}
