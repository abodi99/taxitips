import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:taxibehov_app/followed_events.dart';
import 'package:taxibehov_app/signal_kinds.dart';
import 'package:taxibehov_app/theme.dart';
import 'package:taxibehov_app/widgets/category_bar.dart';
import 'package:taxibehov_app/widgets/map_legend_sheet.dart';
import 'package:taxibehov_app/widgets/signal_card.dart';
import 'package:taxibehov_app/widgets/signal_map.dart';

MapItem item(
  String id,
  double lat,
  double lon, {
  SignalCategory c = SignalCategory.transit,
  SignalStrength s = SignalStrength.low,
}) => MapItem(
  id: id,
  lat: lat,
  lon: lon,
  category: c,
  strength: s,
  icon: Icons.train,
  onTap: () {},
);

void main() {
  group('kategori', () {
    test('färjan från AIS är en färja, inte en båtlinje', () {
      expect(
        categoryOfAlert({'kind': 'ferry', 'mode': 'boat'}),
        SignalCategory.ferry,
      );
      expect(
        categoryOfAlert({'kind': 'transit', 'mode': 'boat'}),
        SignalCategory.transit,
      );
    });
    test('väg och flyg känns igen på kind eller mode', () {
      expect(categoryOfAlert({'kind': 'road'}), SignalCategory.road);
      expect(categoryOfAlert({'mode': 'flight'}), SignalCategory.flight);
      expect(
        categoryOfAlert({'kind': 'transit', 'mode': 'train'}),
        SignalCategory.transit,
      );
    });
    test('nyckeln går fram och tillbaka', () {
      for (final c in SignalCategory.values) {
        expect(signalCategoryFromKey(c.key), c);
      }
      expect(signalCategoryFromKey('followed'), isNull);
    });
  });

  group('styrka', () {
    test('väghinder har egen skala, oberoende av kundsannolikhet', () {
      expect(
        strengthOfAlert({
          'kind': 'road',
          'severity_tier': 'road_accident_or_closure',
        }),
        SignalStrength.high,
      );
      expect(
        strengthOfAlert({
          'kind': 'road',
          'severity_tier': 'road_work_or_queue',
        }),
        SignalStrength.medium,
      );
      expect(
        strengthOfAlert({'kind': 'road', 'severity_tier': 'road_work'}),
        SignalStrength.low,
      );
    });
    test('tips följer backendens nivå', () {
      expect(
        strengthOfAlert({'kind': 'transit', 'level': 'high'}),
        SignalStrength.high,
      );
      expect(
        strengthOfAlert({'kind': 'transit', 'level': 'low'}),
        SignalStrength.low,
      );
    });
    test('evenemangets storlek från backendens sizeLevel', () {
      expect(strengthOfEvent({'sizeLevel': 'stor'}), SignalStrength.high);
      expect(strengthOfEvent({'sizeLevel': 'medel'}), SignalStrength.medium);
      expect(strengthOfEvent({'sizeLevel': 'okand'}), SignalStrength.low);
    });
    test('en olycka är röd, ett starkt tips grönt -- aldrig samma färg', () {
      expect(
        strengthColor(SignalStrength.high, category: SignalCategory.road),
        TbColors.danger,
      );
      expect(
        strengthColor(SignalStrength.high, category: SignalCategory.transit),
        TbColors.likelihoodHigh,
      );
      expect(
        strengthWord(SignalStrength.high, category: SignalCategory.road),
        'Stopp',
      );
      expect(strengthWord(SignalStrength.high), 'Stark');
    });
  });

  group('ikoner', () {
    test('väghinder efter typ, evenemang efter sport', () {
      expect(
        iconForAlert({
          'kind': 'road',
          'severity_tier': 'road_accident_or_closure',
        }),
        Icons.car_crash_rounded,
      );
      expect(
        iconForAlert({'kind': 'transit', 'mode': 'bus'}),
        Icons.directions_bus_rounded,
      );
      expect(iconForEvent({'sport': 'ishockey'}), Icons.sports_hockey_rounded);
      expect(iconForEvent({'category': 'konsert'}), Icons.music_note_rounded);
    });
  });

  group('texter', () {
    test('avstånd läses på en halv sekund', () {
      expect(distanceText(0.42), '400 m');
      expect(distanceText(3.26), '3,3 km');
      expect(distanceText(27.6), '28 km');
      expect(distanceText(null), '');
    });
    test('länet i grundform, kort och lätt att känna igen', () {
      expect(countyShort('Västra Götalands län'), 'Västra Götaland');
      expect(countyShort('Skåne län'), 'Skåne');
      expect(countyShort('Hallands län'), 'Halland');
      expect(countyShort('Uppsala län'), 'Uppsala');
    });
    test('ålder', () {
      final now = DateTime(2026, 9, 21, 12);
      expect(
        ageText(now.subtract(const Duration(seconds: 20)), now: now),
        'Nu',
      );
      expect(
        ageText(now.subtract(const Duration(minutes: 5)), now: now),
        '5 min',
      );
      expect(
        ageText(now.subtract(const Duration(hours: 3)), now: now),
        '3 tim',
      );
      expect(
        ageText(now.add(const Duration(minutes: 30)), now: now),
        'om 30 min',
      );
    });
  });

  group('klustring', () {
    test(
      'nära varandra blir en grupp vid låg zoom, var för sig på gatunivå',
      () {
        final items = [
          item('a', 57.7089, 11.9746),
          item('b', 57.7090, 11.9747, s: SignalStrength.high),
          item('c', 55.6050, 13.0038),
        ];
        final far = clusterItems(items, 8);
        expect(far.length, 2);
        final gbg = far.firstWhere((g) => g.length == 2);
        expect(
          gbg.first.id,
          'b',
          reason: 'den starkaste först, den ger bubblans färg',
        );
        expect(clusterItems(items, kClusterUntilZoom).length, 3);
      },
    );
    test('ett väghinder göms aldrig i en rund bubbla', () {
      final items = [
        item('tip', 57.7089, 11.9746),
        item('road', 57.7089, 11.9746, c: SignalCategory.road),
      ];
      expect(clusterItems(items, 8).length, 2);
    });
  });

  group('följda evenemang', () {
    test('passerade rensas dagen efter att de slutat', () {
      final now = DateTime(2026, 9, 21, 10);
      expect(
        FollowedEvents.isPast({'startDate': '2026-09-20'}, now: now),
        isTrue,
      );
      expect(
        FollowedEvents.isPast({'startDate': '2026-09-21'}, now: now),
        isFalse,
      );
      expect(
        FollowedEvents.isPast({
          'startDate': '2026-09-19',
          'endDate': '2026-09-21',
        }, now: now),
        isFalse,
      );
    });
  });

  group('widgets', () {
    Widget wrap(Widget child) => MaterialApp(
      theme: buildTaxiTheme(),
      home: Scaffold(body: child),
    );

    testWidgets(
      'kortet visar plats, styrkeord och en stjärna som går att trycka på',
      (tester) async {
        bool? followed;
        await tester.pumpWidget(
          wrap(
            SignalCard(
              alert: const {
                'title': 'Göteborg C',
                'kind': 'transit',
                'mode': 'train',
                'level': 'high',
                'severity_tier': 'line_paused',
                'distance_km': 3.2,
              },
              onToggleFollow: (v) => followed = v,
            ),
          ),
        );
        expect(find.text('Göteborg C'), findsOneWidget);
        expect(find.text('Stark'), findsOneWidget);
        expect(find.text('3,2 km'), findsOneWidget);
        await tester.tap(find.byTooltip('Följ'));
        expect(followed, isTrue);
      },
    );

    testWidgets('kategoriraden visar antal och väljer', (tester) async {
      String? selected = 'none';
      await tester.pumpWidget(
        wrap(
          CategoryBar(
            selected: null,
            counts: const {SignalCategory.road: 4, SignalCategory.transit: 2},
            followedCount: 1,
            onSelect: (v) => selected = v,
          ),
        ),
      );
      expect(find.text('Väg'), findsOneWidget);
      expect(find.text('4'), findsOneWidget);
      expect(find.text('6'), findsOneWidget, reason: 'Alla = summan');
      await tester.tap(find.text('Väg'));
      expect(selected, 'road');
    });

    testWidgets('förklaringen öppnas och visar alla typer', (tester) async {
      await tester.pumpWidget(
        wrap(
          Builder(
            builder: (context) => TextButton(
              onPressed: () => showMapLegend(context),
              child: const Text('?'),
            ),
          ),
        ),
      );
      await tester.tap(find.text('?'));
      await tester.pumpAndSettle();
      expect(find.text('Symbolerna på kartan'), findsOneWidget);
      for (final c in signalCategoryOrder) {
        expect(find.text(c.label), findsWidgets);
      }
    });
  });
}
