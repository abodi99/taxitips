import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/signal_card.dart';

/// Kortet är tre rader: plats + avstånd, vad som hänt, det som avgör.
void main() {
  Map<String, dynamic> tip({
    String? headline = 'Tåg 22:48 inställt',
    String? decision = 'Nästa tåg 23:48',
    String? tone = 'go',
    bool pays = false,
    bool active = true,
    bool favorite = false,
  }) => {
    'id': 't1',
    'title': 'Tåg inställt',
    'kind': 'transit',
    'mode': 'train',
    'level': 'high',
    'severity_tier': 'line_paused',
    'station': 'Ronneby',
    'countyName': 'Blekinge län',
    'start_time': '2026-10-03T18:00:00Z',
    'distance_km': 12,
    'is_active': active,
    'is_favorite': favorite,
    'compensation_eligible': pays,
    'headline': ?headline,
    'decision': ?decision,
    'decision_tone': ?tone,
  };

  Future<void> pump(WidgetTester tester, Map<String, dynamic> alert) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTaxiTheme(),
        home: Scaffold(
          body: SignalCard(alert: alert, onToggleFollow: (_) {}),
        ),
      ),
    );
  }

  Color colorOf(WidgetTester tester, String text) =>
      tester.widget<Text>(find.text(text)).style!.color!;

  testWidgets('plats, rubrik, beslut och avstånd', (tester) async {
    await pump(tester, tip());
    expect(find.text('Ronneby'), findsOneWidget);
    expect(find.text('Tåg 22:48 inställt'), findsOneWidget);
    expect(find.text('Nästa tåg 23:48'), findsOneWidget);
    expect(find.text('12 km'), findsOneWidget);
    expect(find.text('Stark'), findsOneWidget);
    // Plats och avstånd på samma rad.
    expect(
      tester.getCenter(find.text('Ronneby')).dy,
      closeTo(tester.getCenter(find.text('12 km')).dy, 6),
    );
  });

  testWidgets('beslutets färg följer tonen', (tester) async {
    await pump(tester, tip(tone: 'go'));
    expect(colorOf(tester, 'Nästa tåg 23:48'), TbColors.live);
    await pump(tester, tip(tone: 'no'));
    expect(colorOf(tester, 'Nästa tåg 23:48'), TbColors.skiffer);
    await pump(tester, tip(tone: 'wait'));
    expect(colorOf(tester, 'Nästa tåg 23:48'), TbColors.midnatt);
  });

  testWidgets('Taxi betalas som ikon, inte som text', (tester) async {
    await pump(tester, tip(pays: true));
    expect(find.byIcon(Icons.payments_rounded), findsOneWidget);
    expect(
      tester.widget<Icon>(find.byIcon(Icons.payments_rounded)).semanticLabel,
      'Taxi betalas',
    );
    expect(find.text('Taxi betalas'), findsNothing);
    await pump(tester, tip(pays: false));
    expect(find.byIcon(Icons.payments_rounded), findsNothing);
  });

  testWidgets('utan de nya fälten faller kortet tillbaka på dagens rubrik', (
    tester,
  ) async {
    await pump(tester, tip(headline: null, decision: null, tone: null));
    expect(find.text('Ronneby'), findsOneWidget);
    expect(find.text('Nästa tåg 23:48'), findsNothing);
    expect(find.text('Stark'), findsOneWidget);
  });

  testWidgets('inget län, ingen starttid, ingen "Sparat"-text', (tester) async {
    await pump(tester, tip(favorite: true));
    expect(find.textContaining('Blekinge'), findsNothing);
    expect(find.text('Sparat'), findsNothing);
    expect(find.textContaining('okt'), findsNothing);
    // Stjärnan finns på sparade tips.
    expect(find.byTooltip('Ta bort sparat'), findsOneWidget);
  });

  testWidgets('osparade tips har ingen stjärna', (tester) async {
    await pump(tester, tip());
    expect(find.byTooltip('Spara tipset'), findsNothing);
  });

  testWidgets('avslutat tips: rad 3 är "Slut"', (tester) async {
    await pump(tester, tip(active: false, pays: true));
    expect(find.text('Slut'), findsOneWidget);
    expect(find.text('Nästa tåg 23:48'), findsNothing);
  });

  testWidgets('kortet är lågt: tre rader får plats i ca 90 px', (tester) async {
    await pump(tester, tip(pays: true));
    expect(tester.getSize(find.byType(SignalCard)).height, lessThan(100));
  });

  group('rad och Kör dit', () {
    Future<void> pumpCard(WidgetTester tester, Widget card) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: SizedBox(width: 360, child: card)),
        ),
      );
    }

    final tip = <String, dynamic>{
      'id': '1',
      'kind': 'transit',
      'mode': 'bus',
      'level': 'low',
      'station': 'Centralen',
      'headline': 'Buss 791 sen',
      'decision': 'Upp till 10 min',
      'decision_tone': 'wait',
      'distance_km': 3.2,
      'lat': 59.33,
      'lon': 18.06,
      'is_active': true,
    };

    testWidgets('ett svagt tips ryms på en rad med plats, vad och avstånd', (
      tester,
    ) async {
      await pumpCard(tester, SignalCard(alert: tip, compact: true));
      expect(
        find.textContaining('Centralen', findRichText: true),
        findsOneWidget,
      );
      expect(
        find.textContaining(
          'Buss 791 sen · Upp till 10 min',
          findRichText: true,
        ),
        findsOneWidget,
      );
      expect(find.text('3,2 km'), findsOneWidget);
      expect(tester.getSize(find.byType(SignalCard)).height, lessThan(70));
      // Ingen navigeringsknapp på en rad: den hör till de stora korten.
      expect(find.byTooltip('Kör dit'), findsNothing);
    });

    testWidgets('avstånd långt bort (annat län) visas inte', (tester) async {
      await pumpCard(
        tester,
        SignalCard(alert: {...tip, 'distance_km': 483}, compact: true),
      );
      expect(find.text('483 km'), findsNothing);
      await pumpCard(tester, SignalCard(alert: {...tip, 'distance_km': 483}));
      expect(find.text('483 km'), findsNothing);
    });

    testWidgets('ett stort kort har Kör dit, och trycket öppnar inte tipset', (
      tester,
    ) async {
      var drove = 0;
      var opened = 0;
      await pumpCard(
        tester,
        SignalCard(
          alert: {...tip, 'level': 'high'},
          onTap: () => opened++,
          onDrive: () => drove++,
        ),
      );
      await tester.tap(find.byTooltip('Kör dit'));
      expect((drove, opened), (1, 0));
    });

    testWidgets('inget Kör dit utan koordinat eller när tipset är slut', (
      tester,
    ) async {
      await pumpCard(
        tester,
        SignalCard(alert: {...tip, 'lat': null}, onDrive: () {}),
      );
      expect(find.byTooltip('Kör dit'), findsNothing);
      await pumpCard(
        tester,
        SignalCard(alert: {...tip, 'is_active': false}, onDrive: () {}),
      );
      expect(find.byTooltip('Kör dit'), findsNothing);
    });
  });
}
