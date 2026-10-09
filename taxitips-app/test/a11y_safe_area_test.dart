import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/app_version.dart';
import 'package:taxitips_app/screens/driver_screen.dart';
import 'package:taxitips_app/screens/events_screen.dart';
import 'package:taxitips_app/screens/history_screen.dart';
import 'package:taxitips_app/screens/login_screen.dart';
import 'package:taxitips_app/screens/onboarding_screen.dart';
import 'package:taxitips_app/screens/settings_screen.dart';
import 'package:taxitips_app/screens/support_chat_screen.dart';
import 'package:taxitips_app/screens/trial_welcome_screen.dart';
import 'package:taxitips_app/screens/welcome_screen.dart';
import 'package:taxitips_app/theme.dart';
import 'package:taxitips_app/widgets/county_checklist.dart';
import 'package:taxitips_app/widgets/ferry_event_widgets.dart';
import 'package:taxitips_app/widgets/force_upgrade_overlay.dart';
import 'package:taxitips_app/widgets/google_signal_map.dart';
import 'package:taxitips_app/widgets/guided_tour.dart';
import 'package:taxitips_app/widgets/notify_prefs_sheet.dart';
import 'package:taxitips_app/widgets/signal_card.dart';
import 'package:taxitips_app/widgets/signal_map.dart';
import 'package:taxitips_app/widgets/tip_sheet.dart';

import 'driver_test_support.dart';

/// Kantsäkert, säkra zoner och klickbart (ägarkrav 2026-10-09).
///
/// Varje huvudskärm och varje blad pumpas med realistisk data på telefoner
/// som förarna har i bilen -- en liten Android med gestfält, en Galaxy S22,
/// en iPhone med notch och liggande med kamerahål på sidorna -- och i
/// textstorlek 1,0 och 1,5 (2,0 för tipsbladet och förarskärmen). För varje
/// fall kontrolleras:
///
/// * Flutters riktlinjer: Android 48x48 och iOS 44x44 tryckytor, en etikett
///   på varje tryckbart, och textkontrast.
/// * Inget spill (RenderFlex overflow) eller annat layoutfel.
/// * Säkra zoner: allt tryckbart ligger innanför skärmen minus statusfältet,
///   notchen, kamerahålen och gestfältet. Fasta knappar (Kör dit, kartans
///   knappar, krysset i bladet) får aldrig ligga under dem. Innehåll som rullar
///   får glida in under kanten, men det första måste gå att se under
///   statusfältet och det sista måste gå att rulla upp ovanför gestfältet.
///
/// Undantag, med skäl:
/// * Kartan (SignalMap/GoogleSignalMap): hela kartytan är en gestyta från
///   kant till kant, och markörerna kan ligga var som helst på kartan --
///   kartan panoreras för att nå dem. Kartans egna knappar ligger utanför
///   kartwidgeten och kontrolleras.
/// * ModalBarrier (den mörka ytan bakom ett blad) och stora ytor som täcker
///   mer än 40 % av skärmen: de är bakgrunder att trycka bort ett blad med,
///   inte knappar.
void main() {
  setUpAll(() async {
    await loadAppFonts();
    // Kartans rutcache frågar efter en katalog; utan svar kastar den ett
    // fel mitt i granskningen. Ingen ruta laddas ändå i testerna.
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel('plugins.flutter.io/path_provider'),
          (call) async => Directory.systemTemp.path,
        );
  });
  setUp(
    () => SharedPreferences.setMockInitialValues({
      GuidedTour.seenKey: true,
      // Tipsbladets genomgång och liknande ska inte lägga sig ovanpå.
      'driver_tour_seen': true,
    }),
  );

  for (final profile in _profiles) {
    for (final screen in _screens) {
      if (profile.keyboard > 0 && !screen.typing) continue;
      final scales = [1.0, 1.5, if (screen.critical) 2.0];
      for (final scale in scales) {
        testWidgets('${screen.name} · ${profile.name} · text $scale', (
          tester,
        ) async {
          await _audit(tester, screen, profile, scale);
        });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Telefonerna

class _Profile {
  const _Profile(
    this.name,
    this.size, {
    this.top = 0,
    this.bottom = 0,
    this.left = 0,
    this.right = 0,
    this.keyboard = 0,
  });

  final String name;
  final Size size;
  final double top;
  final double bottom;
  final double left;
  final double right;

  /// Tangentbordets höjd (viewInsets.bottom); 0 = inget tangentbord.
  final double keyboard;

  Rect get safe => Rect.fromLTRB(
    left,
    top,
    size.width - right,
    size.height - (keyboard > bottom ? keyboard : bottom),
  );
}

const _profiles = [
  _Profile('liten Android 360x640', Size(360, 640), top: 24, bottom: 24),
  _Profile('S22 360x780', Size(360, 780), top: 32, bottom: 16),
  _Profile('iPhone notch 390x844', Size(390, 844), top: 47, bottom: 34),
  // Tangentbordet uppe (bara skärmar med textfält, se [_Screen.typing]).
  _Profile(
    'S22 med tangentbord',
    Size(360, 780),
    top: 32,
    bottom: 16,
    keyboard: 300,
  ),
  // Appen låser inte orienteringen (Info.plist och AndroidManifest tillåter
  // liggande), så liggande med kamerahål på sidorna ingår.
  _Profile(
    'liggande 780x360',
    Size(780, 360),
    top: 24,
    bottom: 16,
    left: 32,
    right: 32,
  ),
];

// ---------------------------------------------------------------------------
// Skärmarna

class _Screen {
  const _Screen(
    this.name,
    this.build, {
    this.open,
    this.critical = false,
    this.overMap = false,
    this.typing = false,
  });

  final String name;
  final Widget Function() build;

  /// Det som ska göras efter att skärmen visats, t.ex. öppna ett blad.
  final Future<void> Function(WidgetTester tester)? open;
  final bool critical;

  /// Kartan syns bakom knapparna: textkontrasten mäts inte (se nedan).
  final bool overMap;

  /// Har textfält: granskas också med tangentbordet uppe.
  final bool typing;
}

Widget _app(Widget home, {TransitionBuilder? builder}) =>
    MaterialApp(theme: buildTaxiTheme(), builder: builder, home: home);

/// En knapp som öppnar ett blad, så som appen öppnar det.
Widget _opener(void Function(BuildContext context) open) => Scaffold(
  body: Builder(
    builder: (context) => Center(
      child: TextButton(
        onPressed: () => open(context),
        child: const Text('öppna'),
      ),
    ),
  ),
);

Future<void> _openFirstTip(WidgetTester tester) async {
  // Liggande och med stor text ryms inget kort i den nedfällda listan: dra
  // upp listan tills det första syns.
  final card = find.byType(SignalCard).first;
  if (find.byType(SignalCard).evaluate().isEmpty) {
    await tester.drag(
      find.textContaining('Alla tips ·'),
      const Offset(0, -900),
    );
    await _settle(tester);
    await tester.scrollUntilVisible(
      card,
      150,
      scrollable: find
          .descendant(
            of: find.byType(DraggableScrollableSheet),
            matching: find.byType(Scrollable),
          )
          .first,
    );
  }
  await tester.ensureVisible(card);
  await tester.pump();
  await tester.tap(card);
  await _settle(tester);
  expect(find.byType(TipSheetBody), findsOneWidget, reason: 'bladet öppnades');
}

Future<void> _tapOpener(WidgetTester tester) async {
  await tester.tap(find.text('öppna'));
  await _settle(tester);
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 8; i++) {
    await tester.pump(const Duration(milliseconds: 250));
  }
}

final _screens = <_Screen>[
  _Screen(
    'förarskärmen, listan nere',
    () => DriverScreen(api: _AuditApi(owner: true), onOpenSettings: () {}),
    open: settleDriverScreen,
    critical: true,
    overMap: true,
  ),
  _Screen(
    'förarskärmen, listan uppdragen',
    () => DriverScreen(api: _AuditApi(owner: true), onOpenSettings: () {}),
    open: (tester) async {
      await settleDriverScreen(tester);
      await tester.drag(
        find.textContaining('Alla tips ·'),
        const Offset(0, -900),
      );
      await _settle(tester);
    },
    critical: true,
  ),
  _Screen(
    'tipsbladet',
    () => DriverScreen(api: _AuditApi(owner: true), onOpenSettings: () {}),
    open: (tester) async {
      await settleDriverScreen(tester);
      await _openFirstTip(tester);
    },
    critical: true,
  ),
  _Screen(
    'tipsbladet, helt uppdraget',
    () => DriverScreen(api: _AuditApi(owner: true), onOpenSettings: () {}),
    open: (tester) async {
      await settleDriverScreen(tester);
      await _openFirstTip(tester);
      // Dra upp bladet till sitt största läge (0,96).
      await tester.drag(find.byType(TipSheetBody), const Offset(0, -400));
      await _settle(tester);
    },
    critical: true,
  ),
  _Screen(
    'tipsbladet, avslutat tips',
    () => _opener(
      (context) => showTipSheet(
        context,
        builder: (ctx, controller) => TipSheetBody(
          alert: _endedTip(),
          api: _AuditApi(),
          scrollController: controller,
          onToggleFavorite: null,
          onClose: () => Navigator.pop(ctx),
        ),
      ),
    ),
    open: _tapOpener,
    critical: true,
  ),
  _Screen(
    'tipsbladet, med ersättningslänk',
    () => _opener(
      (context) => showTipSheet(
        context,
        builder: (ctx, controller) => TipSheetBody(
          alert: _strongTip(),
          api: _AuditApi(),
          scrollController: controller,
          distanceKm: 3.2,
          onToggleFavorite: (v) async {},
          onOpenSourcePage: () {},
          onOpenUrl: (url) async {},
          onClose: () => Navigator.pop(ctx),
        ),
      ),
    ),
    open: _tapOpener,
    critical: true,
  ),
  _Screen(
    'filterbladet',
    () => DriverScreen(api: _AuditApi(owner: true), onOpenSettings: () {}),
    open: (tester) async {
      await settleDriverScreen(tester);
      await tester.tap(find.widgetWithText(FloatingActionButton, 'Filter'));
      await _settle(tester);
    },
  ),
  _Screen(
    'förklaringen (symbolerna)',
    () => DriverScreen(api: _AuditApi(owner: true), onOpenSettings: () {}),
    open: (tester) async {
      await settleDriverScreen(tester);
      await tester.tap(
        find.byKey(const ValueKey('map_legend_button')),
        warnIfMissed: false,
      );
      await _settle(tester);
    },
  ),
  _Screen(
    'historiken',
    () => HistoryScreen(
      api: _AuditApi(),
      counties: const ['14'],
      areaLabel: 'Västra Götaland',
      onOpenTip: (_) async {},
    ),
    open: _settle,
  ),
  _Screen(
    'evenemangen',
    () => EventsScreen(
      api: _AuditApi(),
      counties: const ['14'],
      areaLabel: 'Västra Götaland',
    ),
    open: _settle,
  ),
  _Screen(
    'evenemangsbladet',
    () => _opener(
      (context) => showEventSheet(
        context,
        _eventRow(0),
        attribution: 'Evenemangsdata: Ticketmaster',
        onToggleFollow: (_) {},
      ),
    ),
    open: _tapOpener,
  ),
  _Screen(
    'färjekorten',
    () => Scaffold(
      appBar: AppBar(title: const Text('Färjor')),
      // Korten så som de ligger i en lista med säkra kanter; det som granskas
      // är kortet (tryckyta, spill, kontrast), inte den här ramen.
      body: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            for (var i = 0; i < 3; i++)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: FerryCard(ferry: _ferryRow(i), onTap: () {}),
              ),
          ],
        ),
      ),
    ),
    open: _settle,
  ),
  _Screen(
    'färjebladet',
    () => _opener(
      (context) => showFerrySheet(
        context,
        {
          ..._ferryRow(0),
          'pickupFrom': DateTime.now()
              .add(const Duration(minutes: 20))
              .toIso8601String(),
          'pickupUntil': DateTime.now()
              .add(const Duration(minutes: 55))
              .toIso8601String(),
        },
        harborLat: 57.70,
        harborLon: 11.95,
      ),
    ),
    open: _tapOpener,
  ),
  _Screen(
    'inställningar, förare',
    () => SettingsScreen(api: _AuditApi(), onShowTour: () {}),
    open: _settle,
  ),
  _Screen(
    'inställningar, ägare',
    () => SettingsScreen(
      api: _AuditApi(owner: true),
      onLogout: () {},
      onShowTour: () {},
    ),
    open: _settle,
  ),
  _Screen(
    'notisbladet',
    () => _opener((context) => showNotifyPrefsSheet(context, _AuditApi())),
    open: _tapOpener,
  ),
  _Screen(
    'länlistan',
    () => _opener(
      (context) => showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        backgroundColor: TbColors.foam,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
        ),
        builder: (ctx) => ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.of(ctx).size.height * 0.8,
          ),
          child: CountyPickerSheet(
            api: _AuditApi(),
            onChangeTrialCounty: () {},
          ),
        ),
      ),
    ),
    open: _tapOpener,
  ),
  _Screen(
    'chatten med supporten',
    () => SupportChatScreen(api: _AuditApi()),
    open: _settle,
    typing: true,
  ),
  _Screen(
    'välkomst',
    () => WelcomeScreen(onLogin: () {}, onSignup: () {}),
    open: _settle,
  ),
  _Screen(
    'introduktionen',
    () => OnboardingScreen(onDone: () {}),
    open: _settle,
  ),
  _Screen(
    'inloggning',
    () => LoginScreen(
      api: _AuditApi(device: null),
      onOwner: () {},
      onDriver: () {},
      onSignup: () {},
      onBack: () {},
    ),
    open: _settle,
    typing: true,
  ),
  _Screen(
    'välkomst till provet',
    () => TrialWelcomeScreen(api: _AuditApi(device: null), onDone: () {}),
    open: _settle,
  ),
  _Screen(
    'spärren: uppdatera appen',
    () => const Scaffold(body: Center(child: Text('Tips'))),
    open: _settle,
  ),
];

/// Spärren läggs runt hela appen (MaterialApp.builder), som i main.dart.
TransitionBuilder? _builderFor(_Screen screen) {
  if (screen.name != 'spärren: uppdatera appen') return null;
  return (context, child) => ForceUpgradeOverlay(
    platform: 'android',
    fetchConfig: () async => {
      'notifyScoreFloor': 50,
      'appVersion': {
        'android': {
          'min': '1.0.2',
          'recommended': null,
          'storeUrl': 'https://play.google.com/store/apps/details?id=x',
        },
        'ios': {'min': null, 'recommended': null, 'storeUrl': null},
        'message': 'Den nya versionen visar färjorna på kartan.',
      },
    },
    installedVersion: () async => AppVersion.tryParse('1.0.1+2'),
    child: child!,
  );
}

// ---------------------------------------------------------------------------
// Data

class _AuditApi extends FakeDriverApi {
  _AuditApi({super.owner, super.device}) {
    ferriesBody = {
      'ferries': [for (var i = 0; i < 2; i++) _ferryRow(i)],
      'terminals': const [],
    };
  }

  @override
  Future<Map<String, dynamic>> taxi({
    double? userLat,
    double? userLon,
    List<String>? regions,
    List<String>? counties,
    List<String>? municipalities,
    bool roadAll = false,
  }) async {
    final rows = [_strongTip(), ...sampleTips().skip(1), _endedTip()];
    return {
      'alerts': rows,
      'favorites': const [],
      'active': rows,
      'week': rows,
      'events': [_eventRow(0)],
      'placeStats': const {},
      'source': 'django',
    };
  }

  @override
  Future<Map<String, dynamic>> events({
    double? lat,
    double? lon,
    List<String>? counties,
    List<String>? municipalities,
    String? from,
    String? to,
  }) async => {
    'events': [for (var i = 0; i < 4; i++) _eventRow(i)],
    'attribution': 'Evenemangsdata: Ticketmaster',
  };

  @override
  Future<Map<String, dynamic>> supportConversation({
    bool markRead = false,
  }) async => {
    'messages': [
      {
        'id': 1,
        'sender': 'driver',
        'body': 'Hej! Tipsen på Landvetter syns inte i listan, bara på kartan.',
        'createdAt': DateTime.now()
            .subtract(const Duration(minutes: 30))
            .toUtc()
            .toIso8601String(),
      },
      {
        'id': 2,
        'sender': 'staff',
        'author': 'Taxi Tips',
        'body':
            'Tack, vi tittar på det. Prova att dra ner listan för att uppdatera.',
        'createdAt': DateTime.now()
            .subtract(const Duration(minutes: 12))
            .toUtc()
            .toIso8601String(),
      },
    ],
  };

  @override
  Future<Map<String, dynamic>> memberships() async => {
    'memberships': [
      {'trial': true, 'licenseId': 'l1', 'status': 'active'},
    ],
  };
}

Map<String, dynamic> _strongTip() {
  final now = DateTime.now();
  String iso(DateTime t) => t.toUtc().toIso8601String();
  return {
    'id': 't1',
    'title': 'Tåg inställt',
    'summary':
        'Tåg 123 mellan Göteborg C och Alingsås är inställt på grund av fordonsfel.',
    'kind': 'transit',
    'mode': 'train',
    'severity_tier': 'vehicle_cancelled',
    'minor': false,
    'confidence': 'high',
    'rule_id': 'rail.vehicle_cancelled',
    'stop_name': 'Göteborg Centralstation',
    'lat': 57.708,
    'lon': 11.973,
    'countyName': 'Västra Götalands län',
    'taxi': {
      'places': ['Göteborg Centralstation'],
      'level': 'high',
    },
    'level': 'high',
    'is_active': true,
    'is_favorite': false,
    'start_time': iso(now.subtract(const Duration(minutes: 25))),
    'end_time': iso(now.add(const Duration(minutes: 70))),
    'worth_it_score': 80,
    'compensation_eligible': true,
    'compensation_amount_kr': 1500,
    'compensation_per_person': true,
    'compensation_source': 'Västtrafik',
    'compensation_url': 'https://www.vasttrafik.se/regler/',
    'has_alternative': false,
    'url': 'https://www.trafikverket.se/',
    'factors': [
      {'text': 'Nästa tåg går först 1 tim 6 min senare', 'sign': '+'},
      {'text': 'Natt – nästan inga andra sätt att ta sig hem', 'sign': '+'},
      {
        'text': 'Resenären kan få taxin betald (upp till 1 500 kr)',
        'sign': '+',
      },
      {'text': 'Stor station – många resenärer', 'sign': '+'},
    ],
    'travel_options': {
      'summary': 'Inställd 20:12 mot Alingsås',
      'departure': {
        'at': iso(now.add(const Duration(minutes: 12))),
        'clock': '20:12',
        'status': 'cancelled',
        'destination': 'Alingsås',
      },
      'gap_minutes': 66,
      'next_clock': '21:18',
      'is_last_departure': false,
      'has_alternative': false,
    },
  };
}

Map<String, dynamic> _endedTip() => _strongTip()
  ..['id'] = 't9'
  ..['is_active'] = false
  ..['level'] = 'low'
  ..['compensation_eligible'] = false
  ..['factors'] = []
  ..['end_time'] = DateTime.now()
      .subtract(const Duration(minutes: 8))
      .toUtc()
      .toIso8601String();

Map<String, dynamic> _ferryRow(int n) {
  final at = DateTime.now().add(Duration(minutes: 10 + n));
  return {
    'id': 'ais:26500000$n',
    'name': n == 0 ? 'STENA DANICA' : 'STENA GERMANICA $n',
    'sizeLabel': 'Stor färja',
    'from': n == 0 ? 'Frederikshavn' : 'Kiel',
    'terminal': 'goteborg',
    'portName': 'Göteborg Stena Line Masthuggskajen',
    'portLat': 57.70,
    'portLon': 11.95,
    'lat': 57.70 + n * 0.002,
    'lon': 11.95,
    'status': 'approaching',
    'arrived': false,
    'expectedAt': at.toUtc().toIso8601String(),
    'etaMinutes': 10 + n,
  };
}

Map<String, dynamic> _eventRow(int n) {
  final day = DateTime.now().add(Duration(days: n));
  final date =
      '${day.year}-${day.month.toString().padLeft(2, '0')}-${day.day.toString().padLeft(2, '0')}';
  return {
    'id': 'e$n',
    'name': n.isEven
        ? 'IFK Göteborg – Malmö FF'
        : "OpenTech Talks: Europe's New Tech Landscape and Beyond",
    'categoryLabel': n.isEven ? 'Sport' : 'Mässa och konferens',
    'sportLabel': n.isEven ? 'Fotboll' : '',
    'venueName': n.isEven ? 'Gamla Ullevi' : 'Svenska Mässan',
    'venueCapacity': n.isEven ? 18000 : 5000,
    'attendanceText': 'Upp till 18 000 besökare',
    'city': 'Göteborg',
    'address': 'Skånegatan 1, Göteborg',
    'countyName': 'Västra Götalands län',
    'startDate': date,
    'startLocal': '19:00',
    'endLocal': '21:00',
    'endBasis': 'estimated',
    'endNote': 'Matchen brukar ta knappt två timmar.',
    'leaveUntilLocal': '21:45',
    'timeKnown': true,
    'lat': 57.706,
    'lon': 11.98,
    'distanceKm': 2.4 + n,
    'url': 'https://www.ticketmaster.se/',
    'links': const [],
  };
}

// ---------------------------------------------------------------------------
// Granskningen

Future<void> _audit(
  WidgetTester tester,
  _Screen screen,
  _Profile p,
  double scale,
) async {
  // Täthet 1: logiska punkter = bildpunkter. Täthet 3 ger samma resultat men
  // gör kontrastmätningen (en skärmbild per text) femtio gånger långsammare.
  const dpr = 1.0;
  tester.view.physicalSize = p.size * dpr;
  tester.view.devicePixelRatio = dpr;
  final pad = FakeViewPadding(
    left: p.left * dpr,
    top: p.top * dpr,
    right: p.right * dpr,
    bottom: p.bottom * dpr,
  );
  tester.view.viewPadding = pad;
  if (p.keyboard > 0) {
    // Med tangentbordet uppe är gestfältet täckt: padding.bottom blir 0 och
    // tangentbordet ligger i viewInsets, som på en riktig telefon.
    tester.view.padding = FakeViewPadding(
      left: p.left * dpr,
      top: p.top * dpr,
      right: p.right * dpr,
    );
    tester.view.viewInsets = FakeViewPadding(bottom: p.keyboard * dpr);
  } else {
    tester.view.padding = pad;
  }
  tester.platformDispatcher.textScaleFactorTestValue = scale;
  addTearDown(tester.view.reset);
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  final semantics = tester.ensureSemantics();

  final problems = <String>[];
  // Alla layoutfel samlas, med vilken widget och var i koden (inte bara det
  // sista, som tester.takeException ger).
  final previousOnError = FlutterError.onError;
  FlutterError.onError = (details) {
    final text = details.toString();
    final first = details.exceptionAsString().split('\n').first;
    final where = RegExp(
      r'The relevant error-causing widget was:\s*\n\s*(.+)\n\s*(.+)',
    ).firstMatch(text);
    problems.add(
      'layoutfel: $first'
      '${where == null ? '' : ' -- ${where.group(1)!.trim()} ${where.group(2)!.trim()}'}',
    );
  };
  void layoutErrors(String when) {
    final e = tester.takeException();
    if (e != null) problems.add('layoutfel $when: $e');
  }

  try {
    await tester.pumpWidget(_app(screen.build(), builder: _builderFor(screen)));
    await tester.pump();
    layoutErrors('vid start');
    if (screen.open != null) await screen.open!(tester);
    layoutErrors('efter öppning');
    for (final g in <AccessibilityGuideline>[
      androidTapTargetGuideline,
      iOSTapTargetGuideline,
      labeledTapTargetGuideline,
      // Kontrasten mäts på en skärmbild av varje texts yta. Över kartan blandar
      // mätningen in kartans grå bakgrund och listans skugga i de vita
      // kartknapparnas rundade hörn och larmar (1,88) för "Filter", som är
      // mörk text på vitt (över 15:1) -- samma knapp klarar mätningen fristående.
      if (!screen.overMap) textContrastGuideline,
    ]) {
      final r = await g.evaluate(tester);
      if (!r.passed) problems.add('${g.description}:\n${r.reason}');
    }

    problems.addAll(_safeZoneProblems(tester, p, atEnd: false));
    // Rulla allt lodrätt till slutet: det sista ska gå att få upp ovanför
    // gestfältet.
    // Listor som bygger raderna efter hand vet inte sin längd förrän de rullats
    // dit: rulla tills slutet står still.
    for (var i = 0; i < 6; i++) {
      _scrollVertical(tester, toEnd: true);
      await tester.pump();
    }
    {
      await tester.pump(const Duration(milliseconds: 100));
      problems.addAll(_safeZoneProblems(tester, p, atEnd: true));
    }
    layoutErrors('efter rullning');
  } catch (e, st) {
    final at = st
        .toString()
        .split('\n')
        .firstWhere((l) => l.contains('a11y_safe_area_test'), orElse: () => '');
    problems.add(
      'fel under granskningen: ${e.toString().split('\n').first} $at',
    );
  } finally {
    semantics.dispose();
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 5));
    tester.takeException();
    FlutterError.onError = previousOnError;
  }

  for (final pr in problems) {
    for (final line in pr.split('\n')) {
      if (line.trim().isEmpty) continue;
      // ignore: avoid_print
      print('AUDIT ${screen.name} | ${p.name} | $scale | $line');
    }
  }
  expect(
    problems,
    isEmpty,
    reason: '${problems.length} problem, se AUDIT-raderna',
  );
}

bool _isTappable(Widget w) =>
    (w is InkResponse && (w.onTap != null || w.onLongPress != null)) ||
    (w is GestureDetector && (w.onTap != null || w.onLongPress != null)) ||
    (w is ButtonStyleButton && w.onPressed != null) ||
    (w is IconButton && w.onPressed != null) ||
    (w is FloatingActionButton && w.onPressed != null);

/// Ligger elementet i något vi inte granskar? Kartan och den mörka
/// bakgrunden (se överst), en skärm som ligger under ett blad eller en annan
/// skärm, och knappar som är bortfällda (osynliga eller släpper igenom tryck).
bool _excluded(Element e) {
  final route = ModalRoute.of(e);
  if (route != null && !route.isCurrent) return true;
  var skip = false;
  e.visitAncestorElements((a) {
    final w = a.widget;
    if (w is SignalMap ||
        w is GoogleSignalMap ||
        w is ModalBarrier ||
        (w is IgnorePointer && w.ignoring) ||
        (w is AbsorbPointer && w.absorbing) ||
        (w is Opacity && w.opacity == 0) ||
        (w is FadeTransition && w.opacity.value == 0) ||
        (w is Offstage && w.offstage)) {
      skip = true;
      return false;
    }
    return true;
  });
  return skip;
}

/// Rullningsytorna runt elementet, närmast först.
List<ScrollableState> _scrollables(Element e) {
  final out = <ScrollableState>[];
  e.visitAncestorElements((a) {
    if (a is StatefulElement && a.state is ScrollableState) {
      out.add(a.state as ScrollableState);
    }
    return true;
  });
  return out;
}

Rect _globalRect(RenderBox box) =>
    MatrixUtils.transformRect(box.getTransformTo(null), Offset.zero & box.size);

String _describe(Element e) {
  String? text;
  void find(Element c) {
    if (text != null) return;
    final w = c.widget;
    if (w is Text) {
      text = w.data ?? w.textSpan?.toPlainText();
    } else if (w is Tooltip) {
      text = w.message;
    } else if (w is Icon) {
      text = 'ikon ${w.icon?.codePoint.toRadixString(16)}';
    }
    c.visitChildElements(find);
  }

  find(e);
  final w = e.widget;
  final key = w.key == null ? '' : ' ${w.key}';
  return '${w.runtimeType}$key "${text ?? '?'}"';
}

List<String> _safeZoneProblems(
  WidgetTester tester,
  _Profile p, {
  required bool atEnd,
}) {
  final screen = Offset.zero & p.size;
  final safe = p.safe;
  final out = <String>[];
  final seen = <RenderObject>{};
  final seenRects = <Rect>{};
  for (final e in find.byWidgetPredicate(_isTappable).evaluate()) {
    final ro = e.renderObject;
    if (ro is! RenderBox || !ro.hasSize || !ro.attached) continue;
    if (!seen.add(ro)) continue;
    if (_excluded(e)) continue;
    final rect = _globalRect(ro);
    // InkWell, GestureDetector och knappen runt dem är samma sak att trycka på.
    if (!seenRects.add(rect)) continue;
    // En yta som täcker en stor del av skärmen är en bakgrund, inte en knapp.
    if (rect.width * rect.height > 0.4 * p.size.width * p.size.height) {
      continue;
    }
    final scrolls = _scrollables(e);
    var clip = screen;
    for (final s in scrolls) {
      final vp = s.context.findRenderObject();
      if (vp is RenderBox && vp.hasSize) clip = clip.intersect(_globalRect(vp));
    }
    final visible = rect.intersect(clip);
    if (visible.width <= 0.5 || visible.height <= 0.5) continue;
    final vertical = scrolls.any((s) => s.position.axis == Axis.vertical);
    final horizontal = scrolls.any((s) => s.position.axis == Axis.horizontal);
    final what = _describe(e);
    const eps = 0.5;
    String fmt(Rect r) =>
        '(${r.left.toStringAsFixed(0)},${r.top.toStringAsFixed(0)} '
        '${r.width.toStringAsFixed(0)}x${r.height.toStringAsFixed(0)})';

    if (!vertical) {
      if (atEnd) continue; // fasta saker kontrolleras redan i första varvet
      if (visible.top < safe.top - eps) {
        out.add('fast $what ${fmt(visible)} under statusfältet/notchen');
      }
      if (visible.bottom > safe.bottom + eps) {
        out.add('fast $what ${fmt(visible)} under gestfältet');
      }
    } else if (!atEnd && visible.top < safe.top - eps) {
      out.add('rullande $what ${fmt(visible)} under statusfältet i början');
    } else if (atEnd && visible.bottom > safe.bottom + eps) {
      out.add(
        'rullande $what ${fmt(visible)} går inte att rulla upp ovanför '
        'gestfältet',
      );
    }
    if (!horizontal && !atEnd) {
      if (visible.left < safe.left - eps || visible.right > safe.right + eps) {
        out.add('$what ${fmt(visible)} under kamerahålet/sidokanten');
      }
    }
  }
  return out;
}

/// Rullar alla lodräta rullningsytor (utanför kartan) till slutet.
bool _scrollVertical(WidgetTester tester, {required bool toEnd}) {
  for (final e in find.byType(Scrollable).evaluate()) {
    if (_excluded(e)) continue;
    final s = (e as StatefulElement).state as ScrollableState;
    final pos = s.position;
    if (pos.axis != Axis.vertical || !pos.hasContentDimensions) continue;
    final target = toEnd ? pos.maxScrollExtent : pos.minScrollExtent;
    if (pos.pixels == target) continue;
    pos.jumpTo(target);
  }
  // Även om inget rullades: innehåll som får plats ska ändå granskas längst
  // ner.
  return true;
}
