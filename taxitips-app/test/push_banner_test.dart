import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/signal_kinds.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/push_banner.dart';

/// Notisen som kommer medan appen är öppen.
///
/// Den gamla visningen var en `SnackBar` med `"$title\n$body"`: två radbrytna
/// rader i botten, utan ikon och utan kategori. Kortet här ska bära SAMMA
/// ikon, färg och ord som listan och kartan (lib/signal_kinds.dart) -- och en
/// testnotis ska aldrig se ut som ett tips.
void main() {
  group('notisens innehåll', () {
    test('en färja blir färjekortet, inte tåget', () {
      const data = PushBannerData(
        title: 'Färja in till Visby',
        body: 'Gotlandia II ankommer 14:20.',
        opportunityId: 'o1',
        kind: 'ferry',
        severityTier: 'arrival_wave',
        level: 'medium',
        demandScore: 80,
      );
      expect(data.isTip, isTrue);
      expect(data.category, SignalCategory.ferry);
      expect(data.icon, SignalCategory.ferry.icon);
      expect(data.eyebrow, 'Medel · Färja');
    });

    test('ett inställt tåg blir tåget, med styrkan som ord', () {
      const data = PushBannerData(
        title: 'Avgång inställd',
        kind: 'transit',
        severityTier: 'line_paused',
        level: 'high',
        demandScore: 80,
      );
      expect(data.category, SignalCategory.transit);
      expect(data.eyebrow, 'Stark · Tåg & buss');
      expect(data.signalColor, TbColors.likelihoodHigh);
    });

    test('utan level blir styrkan svag, aldrig påhittat stark', () {
      // Äldre notiser i kön saknar `level`. Att då gissa "Stark" hade lovat
      // mer än data bär (varumärkesguiden: ett läge vi ser, aldrig ett löfte).
      const data = PushBannerData(
        title: 'Avgång inställd',
        kind: 'transit',
        severityTier: 'line_paused',
        demandScore: 80,
      );
      expect(data.eyebrow, 'Svag · Tåg & buss');
      expect(data.signalColor, TbColors.likelihoodLow);
    });

    test('ett supportmeddelande är inte ett tips', () {
      const data = PushBannerData(
        title: 'Svar från supporten',
        body: 'Hej! Vi tittar på det.',
        isSupportReply: true,
      );
      expect(data.isTip, isFalse);
      expect(data.eyebrow, 'Support');
      expect(data.icon, Icons.support_agent_rounded);
      expect(data.signalColor, TbColors.skiffer);
    });

    test('en testnotis ser inte ut som ett tips', () {
      const data = PushBannerData(
        title: 'TaxiTips',
        body: 'Testnotis: notiserna fungerar.',
        kind: 'test',
      );
      expect(data.isTip, isFalse);
      expect(data.eyebrow, 'Testnotis');
      expect(data.signalColor, TbColors.skiffer);
    });

    test('FCM-meddelandet tolkas: kind, level och öppningen', () {
      final message = RemoteMessage.fromMap({
        'data': {
          'opportunity_id': 'o9',
          'kind': 'flight',
          'severity_tier': 'arrival_wave',
          'level': 'medium',
          'demand_score': 62,
        },
        'notification': {'title': 'Många plan landar', 'body': 'Arlanda 18:30.'},
      });
      final data = PushBannerData.fromMessage(message);
      expect(data.title, 'Många plan landar');
      expect(data.body, 'Arlanda 18:30.');
      expect(data.opportunityId, 'o9');
      expect(data.category, SignalCategory.flight);
      expect(data.isTip, isTrue);
      expect(data.eyebrow, 'Medel · Flyg');
    });
  });

  group('kortet', () {
    const tip = PushBannerData(
      title: 'Avgång inställd',
      body: 'Tåg 123 från Lund C är inställt.',
      opportunityId: 'o1',
      kind: 'transit',
      severityTier: 'line_paused',
      level: 'high',
      demandScore: 80,
    );

    Future<void> pumpCard(
      WidgetTester tester, {
      VoidCallback? onOpen,
      VoidCallback? onDismiss,
    }) => tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: PushBanner(data: tip, onOpen: onOpen, onDismiss: onDismiss),
          ),
        ),
      ),
    );

    testWidgets('kategoriraden, rubriken, texten och "Visa" syns', (tester) async {
      await pumpCard(tester, onOpen: () {});
      expect(find.text('Stark · Tåg & buss'), findsOneWidget);
      expect(find.text('Avgång inställd'), findsOneWidget);
      expect(find.text('Tåg 123 från Lund C är inställt.'), findsOneWidget);
      expect(find.text('Visa'), findsOneWidget);
      expect(find.byIcon(SignalCategory.transit.icon), findsOneWidget);
    });

    testWidgets('tryck på kortet öppnar tipset', (tester) async {
      var opened = 0;
      await pumpCard(tester, onOpen: () => opened++);
      await tester.tap(find.text('Avgång inställd'));
      expect(opened, 1);
    });

    testWidgets('krysset stänger', (tester) async {
      var closed = 0;
      await pumpCard(tester, onDismiss: () => closed++);
      await tester.tap(find.byIcon(Icons.close));
      expect(closed, 1);
    });

    testWidgets('en notis utan tips är inte tryckbar och visar inget "Visa"', (
      tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: PushBanner(
              data: const PushBannerData(
                title: 'TaxiTips',
                body: 'Testnotis: notiserna fungerar.',
                kind: 'test',
              ),
              onDismiss: () {},
            ),
          ),
        ),
      );
      expect(find.text('Testnotis'), findsOneWidget);
      expect(find.text('Visa'), findsNothing);
      expect(find.byIcon(SignalCategory.transit.icon), findsNothing);
    });
  });

  group('banderollen i appen', () {
    const data = PushBannerData(
      title: 'Avgång inställd',
      body: 'Tåg 123 är inställt.',
      opportunityId: 'o1',
      kind: 'transit',
      severityTier: 'line_paused',
      level: 'high',
      demandScore: 80,
    );

    Future<BuildContext> pumpHost(WidgetTester tester) async {
      late BuildContext ctx;
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (c) {
              ctx = c;
              return const Scaffold(body: SizedBox.shrink());
            },
          ),
        ),
      );
      return ctx;
    }

    testWidgets('visas högst upp och försvinner av sig själv', (tester) async {
      final ctx = await pumpHost(tester);
      showPushBanner(ctx, data, duration: const Duration(milliseconds: 400));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Avgång inställd'), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 500));
      await tester.pumpAndSettle();
      expect(find.text('Avgång inställd'), findsNothing);
    });

    testWidgets('en ny notis ersätter den förra', (tester) async {
      final ctx = await pumpHost(tester);
      showPushBanner(ctx, data, duration: const Duration(seconds: 8));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Avgång inställd'), findsOneWidget);

      showPushBanner(
        ctx,
        const PushBannerData(
          title: 'Andra notisen',
          kind: 'transit',
          level: 'high',
        ),
        duration: const Duration(milliseconds: 400),
      );
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Avgång inställd'), findsNothing);
      expect(find.text('Andra notisen'), findsOneWidget);

      await tester.pump(const Duration(milliseconds: 500));
      await tester.pumpAndSettle();
      expect(find.text('Andra notisen'), findsNothing);
    });

    testWidgets('hidePushBanner tar bort den medan den visas', (tester) async {
      final ctx = await pumpHost(tester);
      showPushBanner(ctx, data, duration: const Duration(seconds: 8));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Avgång inställd'), findsOneWidget);
      hidePushBanner();
      await tester.pumpAndSettle();
      expect(find.text('Avgång inställd'), findsNothing);
    });
  });
}
