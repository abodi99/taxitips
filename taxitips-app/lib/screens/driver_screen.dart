import 'package:flutter_svg/flutter_svg.dart';

import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import '../analytics.dart';
import '../api_client.dart';
import '../widgets/ferry_event_widgets.dart';
import 'events_screen.dart';
import '../push_service.dart';
import '../severity_labels.dart';
import '../theme.dart';
import '../widgets/alert_feedback_bar.dart';
import '../widgets/brand_icons.dart';
import '../followed_events.dart';
import '../signal_kinds.dart';
import '../widgets/category_bar.dart';
import '../widgets/map_legend_sheet.dart';
import '../widgets/signal_card.dart';
import '../widgets/signal_map.dart';
import '../widgets/vehicle_session_sheet.dart';
import '../widgets/google_signal_map.dart';

class DriverScreen extends StatefulWidget {
  const DriverScreen({
    super.key,
    required this.api,
    this.inviteToken,
    this.demo = false,
    this.onBack,
    this.onLeftDevice,
    this.onOpenSettings,
  });

  final ApiClient api;
  final String? inviteToken;
  final bool demo;
  final VoidCallback? onBack;
  final VoidCallback? onLeftDevice;
  final VoidCallback? onOpenSettings;

  @override
  State<DriverScreen> createState() => _DriverScreenState();
}

class _DriverScreenState extends State<DriverScreen>
    with WidgetsBindingObserver {
  // Anti-overload: max tips i listan (prioritetssorterade). Kartan har egen
  // gräns så nålarna inte täcker varandra.
  static const int _maxVisibleSignals = 5000;

  Map<String, dynamic>? _data;
  String? _error;
  String? _status;
  Timer? _timer;
  // Behåller sheet-höjd över poll-rebuilds. Utan controller återställs
  // DraggableScrollableSheet till initialChildSize varje setState →
  // listan "går alltid ner" var 30:e sekund.
  final _sheetController = DraggableScrollableController();

  /// Aktuell sheet-höjd (0–1) — FAB ska sitta ovanför, inte mitt i sheetet.
  double _sheetExtent = 0.40;

  /// Listan är uppdragen över kartan: kartknapparna skulle hamna under
  /// statusraden, så de göms och filtret flyttar in i listans rubrik.
  bool get _sheetHigh => _sheetExtent > 0.6;

  /// Kartan har flyttats till förarens första position.
  bool _centeredOnUser = false;
  final _mapController = MapController();
  // Flyttar vilken karta som visas: Google Maps med trafik, eller flutter_map.
  late final _mapFocus = MapFocus(_mapController);
  bool _claiming = false;
  bool _refreshing = false;
  bool? _entitled; // null = okänt/inte kollat än, kör inte spärr förrän vi vet.
  // Serverns skäl och text när åtkomsten saknas (fleet/access.py) -- en ny
  // provkund och ett uppsagt bolag ska inte få samma besked.
  String? _entitlementReason;
  String? _entitlementMessage;
  // Av som default: med dagens data (många planerade ersättningsarbeten
  // korrekt märkta low) ger "Bara hög prio" en tom lista som ser ut som
  // "inga störningar". Föraren slår på filtret när hen vill korta ner.
  // Sparad preferens i SharedPreferences vinner fortfarande.
  //
  // Poängspann 0–100 (worth_it/demand). Default hela spannet. Tidigare
  // boolen `_highOnly` migreras till min=50 vid laddning.
  double _scoreMin = 0;
  double _scoreMax = 100;
  bool _nearMe = false;
  String _sortMode = 'score'; // 'score', 'distance', 'newest'

  /// Event types the driver has explicitly switched off. Stored as an
  /// opt-OUT set rather than an opt-in list so a new severity_tier added
  /// server-side shows up by default instead of being silently invisible
  /// to everyone who saved a filter before it existed.
  Set<String> _hiddenTiers = {};

  /// Tiers offered in the filter sheet: whatever actually appears in the
  /// current data, plus anything already hidden (so a driver can always
  /// un-hide a type even when none are live right now). Data-driven rather
  /// than a hardcoded list -- offering a checkbox for a type that never
  /// occurs is noise, and silently omitting a hidden one would strand the
  /// driver with a filter they can't undo.
  List<String> get _filterableTiers {
    final seen = <String>{
      for (final a in _rawActive)
        if (a['severity_tier'] != null) a['severity_tier'].toString(),
      ..._hiddenTiers,
    }..removeWhere((t) => !severityTierShortLabels.containsKey(t));
    final ordered = [
      'line_paused',
      'vehicle_cancelled',
      'line_delayed',
      'vehicle_delayed',
      'road_accident_or_closure',
      'road_work_or_queue',
      'road_work',
      'disruption_unclassified',
    ];
    return [
      for (final t in ordered)
        if (seen.contains(t)) t,
    ];
  }

  /// Färdsätt/källor föraren stängt av. Opt-out så nya källor syns
  /// automatiskt. 'ferry' och 'events' styr AIS-färjor respektive evenemang
  /// (egna API:er), övriga filtrerar tipslistan via [alertFilterMode].
  Set<String> _hiddenModes = {};

  /// Kategorin i raden överst: null = Alla, 'followed' = Följer, annars en
  /// [SignalCategory.key]. EN väljare styr både kartan och listan -- föraren
  /// ska aldrig behöva förstå två olika filter för samma sak.
  String? _category;

  /// Evenemangens dag i Event-läget: today, tomorrow, weekend, week eller all
  /// (hela fönstret backend skickar, 14 dagar).
  String _eventDay = 'today';

  /// Evenemang inom så här många km. null = alla i förarens län.
  double? _eventRadiusKm;

  /// Evenemang föraren följer. Sparas på telefonen (followed_events.dart);
  /// tipsen följs på servern (`favorites` i flödet).
  Map<String, Map<String, dynamic>> _followedEvents = {};

  /// Det föraren senast tryckte på -- markeras med guldring på kartan.
  String? _selectedId;

  /// Länen licensen omfattar (från /api/fleet/me). null = okänt eller
  /// bolaget är inte på licensmodellen än; då erbjuds alla län, och servern
  /// avgör ändå.
  Set<String>? _licensedCounties;

  /// Länen föraren kan välja i filtret: bara licensens, när de är kända.
  Iterable<MapEntry<String, String>> get _pickableCounties =>
      _countyNames.entries.where(
        (e) => _licensedCounties == null || _licensedCounties!.contains(e.key),
      );

  Set<String> _regions = {};
  Set<String> _cities = {};
  // Körområde i län (SCB-kod). Styr listan när platsen saknas och alla notiser.
  Set<String> _counties = {};
  // Kommuner (SCB-kod) som förfinar ett valt län. Inga valda = hela länet.
  Set<String> _municipalities = {};
  // Kommunerna per län, från /api/notify-prefs första gången länsvalet öppnas.
  Map<String, List<Map<String, dynamic>>> _municipalityCatalog = {};
  // Servern hade varken plats eller körområde att gå på (needsArea).
  bool _needsArea = false;
  // Telefonen är godkänd men kör ingen bil just nu. Inte ett fel -- föraren
  // ska välja bil, och först då lämnas tipsen ut (se fleet/access.py).
  bool _needsVehicle = false;
  StreamSubscription<RemoteMessage>? _pushSub;
  StreamSubscription<void>? _openedSub;
  // Färjor: `arrivals` = relevance (tidtabell+AIS, samma som /farjor);
  // `_ferryShips` = AIS-live för kartans nålar.
  List<Map<String, dynamic>> _ferries = const [];
  List<Map<String, dynamic>> _ferryShips = const [];
  List<Map<String, dynamic>> _ferryTerminals = const [];
  String _ferryAttribution = '';
  List<Map<String, dynamic>> _events = const [];
  bool _eventsPreview = false;
  String _eventsPreviewNote = '';
  String _eventsAttribution = '';
  String? _eventsKey;
  // Evenemangskällan svarade (inte `no_licensed_sources`): då går sidan att öppna.
  bool _eventsSourceOk = false;
  DateTime? _eventsLoadedAt;
  Timer? _ferryTimer;
  // Färjornas lägen uppdateras oftare än tipsen: de rör sig.
  static const _ferryPoll = Duration(seconds: 30);
  static const _eventsMaxAge = Duration(minutes: 5);
  bool _foreground = true;
  final _random = math.Random();

  // 60 s med ±10 s spridning, så att alla telefoner inte frågar samma sekund.
  static const _pollBase = Duration(seconds: 60);
  static const _pollJitterSeconds = 10;

  /// Sveriges 21 län med SCB-kod -- samma koder som backend (core/areas.py).
  /// Ett län utan kollektivtrafikkälla går att välja: tåg, väg, flyg och
  /// evenemang kan ändå ha tips där.
  static const _countyNames = <String, String>{
    '01': 'Stockholms län',
    '03': 'Uppsala län',
    '04': 'Södermanlands län',
    '05': 'Östergötlands län',
    '06': 'Jönköpings län',
    '07': 'Kronobergs län',
    '08': 'Kalmar län',
    '09': 'Gotlands län',
    '10': 'Blekinge län',
    '12': 'Skåne län',
    '13': 'Hallands län',
    '14': 'Västra Götalands län',
    '17': 'Värmlands län',
    '18': 'Örebro län',
    '19': 'Västmanlands län',
    '20': 'Dalarnas län',
    '21': 'Gävleborgs län',
    '22': 'Västernorrlands län',
    '23': 'Jämtlands län',
    '24': 'Västerbottens län',
    '25': 'Norrbottens län',
  };
  double? _userLat;
  double? _userLon;
  static const _nearKm = 25.0;

  // Filter choices persist locally so a driver doesn't have to re-set them
  // every time they open the app -- "Bara hög prio" is exactly the kind of
  // thing you turn on once and expect to stay on, not something to
  // reconfigure at every stoplight. Regions/cities ALSO sync to
  // devices.notify_prefs so push_cycle uses the same geography as the list
  // (one source of truth: huvudskärmens filter).
  static const _prefsHighOnlyKey = 'tb_filter_high_only'; // legacy
  static const _prefsScoreMinKey = 'tb_filter_score_min';
  static const _prefsScoreMaxKey = 'tb_filter_score_max';
  static const _prefsNearMeKey = 'tb_filter_near_me';
  static const _prefsSourceKey = 'tb_filter_source'; // legacy exclusive
  static const _prefsHiddenModesKey = 'tb_filter_hidden_modes';
  static const _prefsHiddenTiersKey = 'tb_filter_hidden_tiers';
  static const _prefsRegionKey = 'tb_filter_region'; // legacy single
  static const _prefsPlaceKey = 'tb_filter_place'; // legacy single
  static const _prefsSortModeKey = 'tb_filter_sort_mode';
  static const _prefsRegionsKey = 'tb_filter_regions';
  static const _prefsCitiesKey = 'tb_filter_cities';
  static const _prefsCountiesKey = 'tb_filter_counties';
  static const _prefsMunicipalitiesKey = 'tb_filter_municipalities';
  static const _prefsCategoryKey = 'tb_map_category';
  static const _prefsEventDayKey = 'tb_event_day';

  Future<void> _loadSavedFilters() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final highOnly = prefs.getBool(_prefsHighOnlyKey);
      final scoreMin = prefs.getDouble(_prefsScoreMinKey);
      final scoreMax = prefs.getDouble(_prefsScoreMaxKey);
      final nearMe = prefs.getBool(_prefsNearMeKey);
      final hiddenModes = prefs.getStringList(_prefsHiddenModesKey);
      final legacySource = prefs.getString(_prefsSourceKey);
      final hiddenTiers = prefs.getStringList(_prefsHiddenTiersKey);
      final regions = prefs.getStringList(_prefsRegionsKey);
      final cities = prefs.getStringList(_prefsCitiesKey);
      final counties = prefs.getStringList(_prefsCountiesKey);
      final municipalities = prefs.getStringList(_prefsMunicipalitiesKey);
      // Äldre envärdesnycklar → set, så befintliga sparade filter inte tappas.
      final legacyRegion = prefs.getString(_prefsRegionKey);
      final legacyPlace = prefs.getString(_prefsPlaceKey);
      final sortMode = prefs.getString(_prefsSortModeKey);
      final category = prefs.getString(_prefsCategoryKey);
      final eventDay = prefs.getString(_prefsEventDayKey);
      final followedEvents = await FollowedEvents.load();
      if (!mounted) return;
      setState(() {
        if (sortMode != null) _sortMode = sortMode;
        if (category == 'followed' || signalCategoryFromKey(category) != null) {
          _category = category;
        }
        if (eventDay != null) _eventDay = eventDay;
        _followedEvents = followedEvents;
        if (scoreMin != null) _scoreMin = scoreMin.clamp(0, 100);
        if (scoreMax != null) _scoreMax = scoreMax.clamp(0, 100);
        if (_scoreMin > _scoreMax) {
          final t = _scoreMin;
          _scoreMin = _scoreMax;
          _scoreMax = t;
        }
        // Legacy: "Bara hög prio" → minst 50 poäng.
        if (scoreMin == null && highOnly == true) _scoreMin = 50;
        if (hiddenModes != null) {
          _hiddenModes = hiddenModes.toSet();
        } else if (legacySource != null && legacySource != 'all') {
          // Tidigare exclusive chip → göm allt annat.
          _hiddenModes = filterModeKeys.toSet();
          if (legacySource == 'transit') {
            _hiddenModes.removeAll(const {
              'train',
              'metro',
              'tram',
              'bus',
              'boat',
            });
          } else {
            _hiddenModes.remove(legacySource);
          }
        }
        if (hiddenTiers != null) _hiddenTiers = hiddenTiers.toSet();
        if (regions != null) {
          _regions = regions.toSet();
        } else if (legacyRegion != null && legacyRegion.isNotEmpty) {
          _regions = {legacyRegion};
        }
        if (counties != null) _counties = counties.toSet();
        if (municipalities != null) _municipalities = municipalities.toSet();
        if (cities != null) {
          _cities = cities.toSet();
        } else if (legacyPlace != null && legacyPlace.isNotEmpty) {
          _cities = {legacyPlace};
        }
      });
      // "Nära mig" needs a real GPS fix to actually filter anything
      // (_geoFilter no-ops until _userLat/_userLon are set) -- re-run the
      // real permission+location flow rather than just restoring the flag,
      // so a saved "on" choice takes effect immediately instead of silently
      // doing nothing until the driver happens to reopen the filter sheet.
      if (nearMe == true) {
        await _toggleNearMe(true);
      }
      // Äldre marknads- och ortval blir län och kommuner; sedan följer
      // notiserna listfiltret.
      if (_regions.isNotEmpty || _cities.isNotEmpty) {
        await _migrateLegacyArea();
      } else {
        await _syncNotifyRegionsFromFilter();
      }
    } catch (_) {
      // Best-effort -- a driver seeing default filters once is fine, an
      // exception here should never block the app from loading signals.
    }
  }

  Future<void> _saveFilters({bool reloadFeed = false}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_prefsSortModeKey, _sortMode);
      if (_category == null) {
        await prefs.remove(_prefsCategoryKey);
      } else {
        await prefs.setString(_prefsCategoryKey, _category!);
      }
      await prefs.setString(_prefsEventDayKey, _eventDay);
      await prefs.setDouble(_prefsScoreMinKey, _scoreMin);
      await prefs.setDouble(_prefsScoreMaxKey, _scoreMax);
      await prefs.remove(_prefsHighOnlyKey);
      await prefs.setBool(_prefsNearMeKey, _nearMe);
      await prefs.setStringList(_prefsHiddenModesKey, _hiddenModes.toList());
      await prefs.remove(_prefsSourceKey);
      await prefs.setStringList(_prefsHiddenTiersKey, _hiddenTiers.toList());
      await prefs.setStringList(_prefsRegionsKey, _regions.toList()..sort());
      await prefs.setStringList(_prefsCitiesKey, _cities.toList()..sort());
      await prefs.setStringList(_prefsCountiesKey, _counties.toList()..sort());
      await prefs.setStringList(
        _prefsMunicipalitiesKey,
        _municipalities.toList()..sort(),
      );
      await prefs.remove(_prefsRegionKey);
      await prefs.remove(_prefsPlaceKey);
    } catch (_) {
      // Non-fatal -- losing a saved preference isn't worth surfacing an
      // error over.
    }
    await _syncNotifyRegionsFromFilter();
    // Länsbyte kräver ny hämtning: GPS-bubblan räcker inte när föraren
    // valt Stockholm från Malmö (eller tvärtom).
    if (reloadFeed) await _load(silent: true);
  }

  /// Skriver huvudskärmens län och kommuner till devices.notify_prefs. De äldre
  /// fälten (marknader och orter) töms, så att de inte filtrerar notiserna utan
  /// att gå att se eller ändra.
  ///
  /// Inget valt betyder "alla bilens län", inte "inga län": då skickas
  /// licensens län, och är de inte kända än skickas ingenting. Förut skickades
  /// en tom lista, som skrev över länen parkopplingen just satt -- och en
  /// telefon utan län får inga notiser alls (core/notify.py, `no_area`).
  Future<void> _syncNotifyRegionsFromFilter() async {
    if (widget.api.deviceToken == null) return;
    final counties = _counties.isEmpty && _municipalities.isEmpty
        ? _licensedCounties
        : _counties;
    if (counties == null) return;
    try {
      await widget.api.saveNotifyPrefs(
        regions: const [],
        cities: const [],
        counties: counties.toList()..sort(),
        municipalities: _municipalities.toList()..sort(),
      );
    } catch (_) {
      // Best-effort — listfiltret fungerar lokalt ändå.
    }
  }

  /// Marknadsnyckel -> länskod, samma som backendens core/areas.MARKET_COUNTY.
  static const _marketCounty = <String, String>{
    'sl': '01',
    'ul': '03',
    'otraf': '05',
    'jlt': '06',
    'krono': '07',
    'klt': '08',
    'gotland': '09',
    'blekinge': '10',
    'skane': '12',
    'vt': '14',
    'varm': '17',
    'orebro': '18',
    'vastmanland': '19',
    'dt': '20',
    'xt': '21',
    'dintur': '22',
  };

  /// Äldre marknadsval och orter blir län och kommuner, en gång. Filtret med
  /// marknader och orter finns inte längre; ett sparat val där hade annars
  /// filtrerat listan utan att gå att ändra. En ort blir kommunen med samma namn;
  /// en ort utan motsvarighet täcks av sitt län.
  Future<void> _migrateLegacyArea() async {
    final counties = {..._counties};
    if (counties.isEmpty) {
      for (final region in _regions) {
        final county = _marketCounty[region];
        if (county != null) counties.add(county);
      }
    }
    final municipalities = {..._municipalities};
    if (_cities.isNotEmpty) {
      await _loadMunicipalityCatalog();
      for (final entry in _municipalityCatalog.entries) {
        for (final row in entry.value) {
          if (_cities.contains(row['name']?.toString())) {
            municipalities.add(row['code'].toString());
            counties.add(entry.key);
          }
        }
      }
    }
    if (!mounted) return;
    setState(() {
      _counties = counties;
      _municipalities = municipalities;
      _regions = {};
      _cities = {};
    });
    await _saveFilters(reloadFeed: true);
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _pushSub = foregroundMessages.listen(_onForegroundPush);
    _openedSub = openedMessageSignals.listen((_) => _openFromNotification());
    _bootstrap();
    // Kallstart från en notis: meddelandet kom innan skärmen fanns.
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _openFromNotification(),
    );
  }

  /// Öppnar tipset en notis handlade om. Först ur det laddade flödet
  /// (direkt, ingen nätväg), annars hämtat från servern.
  Future<void> _openFromNotification() async {
    final message = takeOpenedMessage();
    if (message == null) return;
    final id = message.data['opportunity_id']?.toString() ?? '';
    // En testnotis eller en notis utan tips: att appen öppnas räcker.
    if (id.isEmpty) return;

    Map<String, dynamic>? alert;
    final data = _data;
    if (data != null) {
      for (final key in const ['alerts', 'favorites']) {
        for (final row in (data[key] as List?) ?? const []) {
          if (row is Map && row['id']?.toString() == id) {
            alert = Map<String, dynamic>.from(row);
            break;
          }
        }
        if (alert != null) break;
      }
    }
    alert ??= await widget.api.alertById(id);
    if (!mounted) return;
    if (alert == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Tipset finns inte längre, eller så har bilen inte tillgång till det.',
          ),
        ),
      );
      return;
    }
    await _openAlertDetail(alert);
  }

  /// En notis medan appen är öppen: visa den och hämta om flödet, så att
  /// tipset som notisen handlar om redan ligger i listan när föraren tittar.
  void _onForegroundPush(RemoteMessage message) {
    if (!mounted) return;
    final title = message.notification?.title ?? 'TaxiTips';
    final body = message.notification?.body ?? '';
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(body.isEmpty ? title : '$title\n$body'),
          duration: const Duration(seconds: 8),
          behavior: SnackBarBehavior.floating,
          action: (message.data['opportunity_id']?.toString() ?? '').isEmpty
              ? null
              : SnackBarAction(
                  label: 'Visa',
                  onPressed: () async {
                    final alert = await widget.api.alertById(
                      message.data['opportunity_id'].toString(),
                    );
                    if (alert != null && mounted) await _openAlertDetail(alert);
                  },
                ),
        ),
      );
    _load(silent: true);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Ingen hämtning i bakgrunden: en telefon i fickan ska inte fråga servern
    // varje minut. Tillbaka i förgrunden hämtas direkt.
    final foreground = state == AppLifecycleState.resumed;
    if (foreground == _foreground) return;
    _foreground = foreground;
    if (foreground) {
      _load(silent: true);
      _schedulePoll();
      _scheduleFerryPoll();
    } else {
      _timer?.cancel();
      _ferryTimer?.cancel();
    }
  }

  void _schedulePoll() {
    _timer?.cancel();
    final jitter =
        _random.nextInt(_pollJitterSeconds * 2 + 1) - _pollJitterSeconds;
    _timer = Timer(_pollBase + Duration(seconds: jitter), () async {
      await _load(silent: true);
      if (mounted && _foreground) _schedulePoll();
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pushSub?.cancel();
    _openedSub?.cancel();
    _timer?.cancel();
    _ferryTimer?.cancel();
    _sheetController.dispose();
    _mapController.dispose();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    // Filter (län) måste finnas innan första hämtningen -- annars går GPS-
    // bubblan först och ett sparat Stockholm-val tömmer listan lokalt.
    await _loadSavedFilters();
    if (widget.inviteToken != null && widget.inviteToken!.isNotEmpty) {
      setState(() => _claiming = true);
      try {
        await widget.api.claimInvite(widget.inviteToken!);
        unawaited(registerForPush(widget.api));
        setState(() => _status = 'Telefon kopplad');
      } catch (e) {
        setState(() => _error = _friendly(e));
      } finally {
        if (mounted) setState(() => _claiming = false);
      }
    } else if (widget.api.deviceToken != null) {
      // FCM-permission på webben kan hänga i en dialog som aldrig syns —
      // tipsflödet får inte vänta på den.
      unawaited(registerForPush(widget.api));
    }
    // GPS får aldrig blockera första hämtningen: på webben kan
    // requestPermission hänga utan dialog, och då syns "Offline" forever
    // medan tipsen redan finns på servern. Körområdet räcker.
    await _updateCurrentPosition().timeout(
      const Duration(seconds: 4),
      onTimeout: () => 'Plats tog för lång tid',
    );
    await _load();
    _schedulePoll();
    _scheduleFerryPoll();
  }

  /// Hämtar GPS. Returnerar null vid lycka, annars ett kort felmeddelande.
  Future<String?> _updateCurrentPosition({bool explain = false}) async {
    try {
      final serviceOn = await Geolocator.isLocationServiceEnabled();
      if (!serviceOn) {
        if (explain) {
          await Geolocator.openLocationSettings();
        }
        return 'Slå på plats (GPS) i telefonens inställningar';
      }

      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm == LocationPermission.denied) {
        return 'Platsbehörighet nekades';
      }
      if (perm == LocationPermission.deniedForever) {
        if (explain) {
          await Geolocator.openAppSettings();
        }
        return 'Tillåt plats för TaxiTips i telefonens inställningar';
      }

      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 20),
        ),
      );
      if (!mounted) return 'Avbrutet';
      setState(() {
        _userLat = pos.latitude;
        _userLon = pos.longitude;
        if (_data != null) _enrichClientDistances(_data!);
        _error = null;
      });
      // Första positionen flyttar kartan till föraren, en gång. Annars
      // startade kartan över hela Sverige med listan över södra halvan --
      // en förare i Helsingborg såg Norrland.
      if (!_centeredOnUser) {
        _centeredOnUser = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!mounted || _userLat == null || _userLon == null) return;
          try {
            _mapFocus.move(_userLat!, _userLon!, 10);
          } catch (_) {}
        });
      }
      return null;
    } on TimeoutException {
      return 'GPS tog för lång tid — försök utomhus eller igen';
    } catch (e) {
      debugPrint('DriverScreen[_updateCurrentPosition] $e');
      return 'Kunde inte hämta din position';
    }
  }

  Future<void> _goToMyLocation() async {
    setState(() => _status = 'Hämtar position…');
    final err = await _updateCurrentPosition(explain: true);
    if (!mounted) return;
    if (err != null || _userLat == null || _userLon == null) {
      setState(() {
        _status = null;
        _error = err ?? 'Kunde inte hämta din position';
      });
      return;
    }
    setState(() => _status = null);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || _userLat == null || _userLon == null) return;
      try {
        _mapFocus.move(_userLat!, _userLon!, 14);
      } catch (e) {
        debugPrint('DriverScreen[_goToMyLocation] map move: $e');
      }
    });
  }

  String _friendly(Object e) {
    final s = e.toString();
    if (s.contains('Ogiltig')) {
      return 'Koden funkar inte — be kontoret om rätt bolags-/byteskod.';
    }
    if (s.contains('401') || s.contains('licens')) {
      return 'Ingen access. Registrera telefonen med bolagskod eller logga in.';
    }
    return s.replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), '');
  }

  /// Numrerar laddningarna. Ett byte till eller från Väg laddar om medan en
  /// poll kan vara på väg, och den som svarar sist vann: på telefonen låg
  /// Väg-lägets alla väghändelser kvar i "Alla" tills nästa poll.
  int _loadSeq = 0;

  Future<void> _load({bool silent = false}) async {
    final seq = ++_loadSeq;
    if (!silent && mounted) setState(() => _refreshing = true);
    // Fräscha GPS innan varje poll så avståndsbadgen inte visar gårdagens
    // parkering — en one-shot i bootstrap räckte inte under ett pass.
    if (silent) await _updateCurrentPosition();
    // "I tjänst" förnyas bara härifrån, alltså bara när appen är öppen.
    unawaited(widget.api.refreshPresence(lat: _userLat, lon: _userLon));
    try {
      final results = await Future.wait([
        widget.api.taxi(
          demo: widget.demo,
          roadAll: _category == SignalCategory.road.key,
          userLat: _userLat,
          userLon: _userLon,
          counties: _counties.isEmpty ? null : (_counties.toList()..sort()),
          municipalities: _municipalities.isEmpty
              ? null
              : (_municipalities.toList()..sort()),
        ),
        _checkEntitlement(),
      ]);
      final data = results[0] as Map<String, dynamic>;
      // En nyare laddning har startat sedan den här: dess svar gäller.
      if (!mounted || seq != _loadSeq) return;
      _enrichClientDistances(data);
      setState(() {
        _data = data;
        _needsArea = data['needsArea'] == true;
        // Backend säger varför flödet är tomt. `no_active_session` betyder
        // att bilval saknas -- inte att perioden gått ut.
        _needsVehicle = data['reason'] == 'no_active_session';
        _error = null;
      });
      // Färjor och evenemang i samma område; ett fel där får inte dölja tipsen.
      unawaited(_loadFerries());
      unawaited(_loadEvents());
    } catch (e) {
      if (!mounted || seq != _loadSeq) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted && seq == _loadSeq) setState(() => _refreshing = false);
    }
  }

  /// Fyller `distance_km` lokalt när servern saknar det (t.ex. tips utan
  /// lat/lon i DB men med koordinater i svaret, eller GPS som kom efter
  /// första svaret). Muterar listorna på plats — samma map som setState får.
  void _enrichClientDistances(Map<String, dynamic> data) {
    if (_userLat == null || _userLon == null) return;
    for (final key in const ['active', 'alerts']) {
      final list = data[key];
      if (list is! List) continue;
      for (final raw in list) {
        if (raw is! Map) continue;
        if (raw['distance_km'] != null) continue;
        final lat = (raw['lat'] as num?)?.toDouble();
        final lon = (raw['lon'] as num?)?.toDouble();
        if (lat == null || lon == null) continue;
        raw['distance_km'] = double.parse(
          _km(_userLat!, _userLon!, lat, lon).toStringAsFixed(1),
        );
      }
    }
  }

  double? _distanceFor(Map<String, dynamic> a) {
    final existing = (a['distance_km'] as num?)?.toDouble();
    if (existing != null) return existing;
    if (_userLat == null || _userLon == null) return null;
    final lat = (a['lat'] as num?)?.toDouble();
    final lon = (a['lon'] as num?)?.toDouble();
    if (lat == null || lon == null) return null;
    return double.parse(_km(_userLat!, _userLon!, lat, lon).toStringAsFixed(1));
  }

  /// Färjornas lägen var 30:e sekund medan appen är öppen -- aldrig i bakgrunden.
  void _scheduleFerryPoll() {
    _ferryTimer?.cancel();
    _ferryTimer = Timer.periodic(_ferryPoll, (_) {
      if (mounted && _foreground) _loadFerries();
    });
  }

  List<String>? get _countyParam =>
      _counties.isEmpty ? null : (_counties.toList()..sort());
  List<String>? get _municipalityParam =>
      _municipalities.isEmpty ? null : (_municipalities.toList()..sort());

  Future<void> _loadFerries() async {
    if (widget.demo) return;
    try {
      final body = await widget.api.ferries(
        lat: _userLat,
        lon: _userLon,
        counties: _countyParam,
        municipalities: _municipalityParam,
      );
      if (!mounted) return;
      final arrivals = _asMaps(body['arrivals']);
      final ships = _asMaps(body['ferries']);
      setState(() {
        // Lista: pipeline-urvalet. Saknas arrivals (äldre server) → AIS.
        _ferries = arrivals.isNotEmpty ? arrivals : ships;
        _ferryShips = ships;
        _ferryTerminals = _asMaps(body['terminals']);
        _ferryAttribution = body['attribution']?.toString() ?? '';
      });
    } catch (e) {
      debugPrint('DriverScreen[_loadFerries] $e');
    }
  }

  /// Evenemangen ändras sällan: hämtas om efter fem minuter, eller direkt när
  /// området eller positionen (på en tiondels grad) ändrats.
  Future<void> _loadEvents() async {
    if (widget.demo) return;
    final key =
        '${_countyParam?.join(',')}|${_municipalityParam?.join(',')}|'
        '${_userLat?.toStringAsFixed(1)},${_userLon?.toStringAsFixed(1)}';
    final loadedAt = _eventsLoadedAt;
    final fresh =
        loadedAt != null && DateTime.now().difference(loadedAt) < _eventsMaxAge;
    if (key == _eventsKey && fresh) return;
    try {
      final body = await widget.api.events(
        lat: _userLat,
        lon: _userLon,
        counties: _countyParam,
        municipalities: _municipalityParam,
      );
      if (!mounted) return;
      setState(() {
        _events = _asMaps(body['events']);
        _eventsPreview = body['preview'] == true;
        _eventsPreviewNote = body['previewNote']?.toString() ?? '';
        _eventsAttribution = body['attribution']?.toString() ?? '';
        _eventsKey = key;
        _eventsLoadedAt = DateTime.now();
        _eventsSourceOk =
            body['entitled'] == true && body['reason'] != 'no_licensed_sources';
      });
    } catch (e) {
      debugPrint('DriverScreen[_loadEvents] $e');
    }
  }

  bool get _showFerries => !_hiddenModes.contains('ferry');
  bool get _showEvents => !_hiddenModes.contains('events');
  List<Map<String, dynamic>> get _ferriesVisible =>
      _showFerries ? _ferries : const [];
  List<Map<String, dynamic>> get _eventsVisible =>
      _showEvents ? _events : const [];

  void _openFerry(Map<String, dynamic> f) {
    final harbor = _harborFor(f);
    showFerrySheet(
      context,
      f,
      attribution: _ferryAttribution,
      harborLat: harbor?.$1,
      harborLon: harbor?.$2,
    );
  }

  /// Alla evenemang per datum, i samma område som listan.
  Future<void> _openEventsScreen() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => EventsScreen(
          api: widget.api,
          lat: _userLat,
          lon: _userLon,
          counties: _countyParam,
          municipalities: _municipalityParam,
          areaLabel: _counties.isEmpty ? 'Nära dig' : _areaFilterSummary,
        ),
      ),
    );
    // Föraren kan ha följt eller slutat följa evenemang där.
    final followed = await FollowedEvents.load();
    if (mounted) setState(() => _followedEvents = followed);
  }

  void _openEvent(Map<String, dynamic> e) {
    showEventSheet(
      context,
      e,
      attribution: _eventsAttribution,
      previewNote: _eventsPreview ? _eventsPreviewNote : '',
      followed: _isFollowedEvent(e),
      onToggleFollow: (v) => _toggleFollowEvent(e, v),
    );
  }

  Widget _sourceNote(String text) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
    child: Text(
      text,
      style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
    ),
  );

  void _focusOpportunity(Map<String, dynamic> o) {
    final lat = (o['lat'] as num?)?.toDouble();
    final lon = (o['lon'] as num?)?.toDouble();
    if (lat == null || lon == null) return;
    setState(() {
      _selectedId = o.containsKey('startDate') ? 'event:${o['id']}' : _tipId(o);
    });
    // Gatunivå: klustren löses upp där, så att just den här syns för sig.
    _mapFocus.move(lat, lon, kClusterUntilZoom);
  }

  /// Zooma med knapp, för den som kör med en hand eller har handskar på.
  /// Mitten ligger kvar; bara zoomnivån ändras, inom kartans gränser.
  void _zoomBy(double delta) => _mapFocus.zoomBy(delta);

  /// Kollar entitlement separat från _load så att ett fel här inte döljer
  /// alert-datan (t.ex. i demo-läge finns ingen deviceToken alls).
  Future<void> _checkEntitlement() async {
    if (widget.demo) {
      if (mounted) setState(() => _entitled = true);
      return;
    }
    try {
      final result = await widget.api.entitlements();
      if (!mounted) return;
      final licensed = {
        for (final c in (result['licensedCounties'] as List?) ?? const [])
          c.toString(),
      };
      setState(() {
        _entitled = result['entitled'] == true;
        _entitlementReason = result['reason']?.toString();
        _entitlementMessage = result['message']?.toString();
        if (licensed.isNotEmpty) {
          _licensedCounties = licensed;
          // Sparade val utanför licensen hade bara gett en tom lista.
          final before = _counties.length + _municipalities.length;
          _counties.removeWhere((c) => !licensed.contains(c));
          _municipalities.removeWhere(
            (m) => !licensed.contains(m.substring(0, 2)),
          );
          if (_counties.length + _municipalities.length != before) {
            WidgetsBinding.instance.addPostFrameCallback(
              (_) => _saveFilters(reloadFeed: true),
            );
          }
        }
        // Godkänd men utan bil är inte "provperioden slut". Backend säger
        // vilket av dem det är; skärmen ska inte gissa.
        if (result['needsSession'] == true ||
            result['reason'] == 'no_active_session') {
          _needsVehicle = true;
        }
      });
    } catch (e) {
      // Nätverksfel etc — behåll senast kända status hellre än att larma i onödan.
      debugPrint('DriverScreen[_checkEntitlement] error: $e');
    }
  }

  /// Bilvalet och skiftbytet. Hämtar om flödet när föraren tagit en bil --
  /// länen som tipsen filtreras mot är bilens, så listan blir en annan.
  Future<void> _openVehiclePicker() async {
    final changed = await VehicleSessionSheet.show(context, widget.api);
    if (changed && mounted) {
      setState(() => _needsVehicle = false);
      await _load();
    }
  }

  List<Map<String, dynamic>> _asMaps(dynamic raw) {
    if (raw is! List) return [];
    return [
      for (final e in raw)
        if (e is Map) Map<String, dynamic>.from(e),
    ];
  }

  List<Map<String, dynamic>> get _rawActive => _asMaps(_data?['active']);

  /// Sparade tips. Kommer färdiga från backend i samma svar som flödet och
  /// filtreras ALDRIG här -- hela poängen med en favorit är att den
  /// överlever filtren, marknadsradien och att störningen tar slut.
  List<Map<String, dynamic>> get _favorites => _asMaps(_data?['favorites']);

  /// Stjärnmarkerar eller avmarkerar ett tips.
  ///
  /// Skriver optimistiskt i den lokala listan innan svaret kommit: en
  /// stjärna som väntar på nätet känns trasig, och backend är idempotent
  /// (en dubbelsparning svarar `duplicate: true`, inte ett fel). Går det
  /// fel återställs den och föraren får veta -- tyst misslyckande är värre
  /// än en synlig återställning.
  Future<void> _toggleFavorite(
    Map<String, dynamic> alert,
    bool favorite,
  ) async {
    final id = alert['id']?.toString();
    if (id == null || id.isEmpty) return;

    setState(() => alert['is_favorite'] = favorite);
    try {
      await widget.api.setFavorite(opportunityId: id, favorite: favorite);
      unawaited(
        logAnalyticsEvent(
          'tip_favorited',
          params: {'favorite': favorite ? 1 : 0},
        ),
      );
      if (mounted) _followedSnack(favorite);
      // Hämtar om flödet så att `favorites`-listan speglar det som just
      // sparades -- den byggs av backend, inte här.
      await _load(silent: true);
    } catch (e) {
      if (!mounted) return;
      setState(() => alert['is_favorite'] = !favorite);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            favorite ? 'Kunde inte spara tipset' : 'Kunde inte ta bort tipset',
          ),
        ),
      );
    }
  }

  /// Säger var det följda hamnar -- annars vet föraren inte att "Följer" finns.
  void _followedSnack(bool followed) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(
            followed
                ? 'Du följer den nu. Den finns under ⭐ Följer.'
                : 'Du följer den inte längre.',
          ),
          action: followed
              ? SnackBarAction(
                  label: 'Visa',
                  onPressed: () => _selectCategory('followed'),
                )
              : null,
        ),
      );
  }

  Future<void> _toggleFollowEvent(
    Map<String, dynamic> event,
    bool follow,
  ) async {
    final id = event['id']?.toString();
    if (id == null || id.isEmpty) return;
    setState(() {
      if (follow) {
        _followedEvents[id] = Map<String, dynamic>.from(event);
      } else {
        _followedEvents.remove(id);
      }
    });
    await FollowedEvents.save(_followedEvents);
    unawaited(
      logAnalyticsEvent('event_followed', params: {'follow': follow ? 1 : 0}),
    );
    if (mounted) _followedSnack(follow);
  }

  bool _isFollowedEvent(Map e) =>
      _followedEvents.containsKey(e['id']?.toString());

  void _selectCategory(String? category) {
    final road = SignalCategory.road.key;
    final reload = (category == road) != (_category == road);
    setState(() => _category = category);
    _saveFilters();
    // Väg-läget hämtar alla väghändelser; de andra bara de närmaste 50.
    if (reload) unawaited(_load(silent: true));
    unawaited(
      logAnalyticsEvent(
        'map_category',
        params: {'category': category ?? 'all'},
      ),
    );
  }

  // --- Evenemang: dag och avstånd -----------------------------------------

  /// Dagarna för [_eventDay], eller null för hela fönstret.
  (DateTime, DateTime)? get _eventDayRange {
    final now = DateTime.now();
    final t = DateTime(now.year, now.month, now.day);
    switch (_eventDay) {
      case 'today':
        return (t, t);
      case 'tomorrow':
        final d = t.add(const Duration(days: 1));
        return (d, d);
      case 'weekend':
        final friday = t.weekday <= DateTime.friday
            ? t.add(Duration(days: DateTime.friday - t.weekday))
            : t;
        return (friday, t.add(Duration(days: DateTime.sunday - t.weekday)));
      case 'week':
        return (t, t.add(const Duration(days: 6)));
      default:
        return null;
    }
  }

  bool _eventInDays(Map e) {
    final range = _eventDayRange;
    if (range == null) return true;
    final start = DateTime.tryParse(e['startDate']?.toString() ?? '');
    final end =
        DateTime.tryParse((e['endDate'] ?? e['startDate'])?.toString() ?? '') ??
        start;
    if (start == null || end == null) return e['ongoing'] == true;
    return !end.isBefore(range.$1) && !start.isAfter(range.$2);
  }

  bool _eventWithinRadius(Map e) {
    final radius = _eventRadiusKm;
    if (radius == null) return true;
    final d = (e['distanceKm'] as num?)?.toDouble();
    return d != null && d <= radius;
  }

  /// Evenemangen i Event-läget: vald dag och avstånd, tidigast först.
  List<Map<String, dynamic>> get _eventsInWindow {
    final list = _eventsVisible
        .where(_eventInDays)
        .where(_eventWithinRadius)
        .toList();
    list.sort((a, b) {
      if ((a['ongoing'] == true) != (b['ongoing'] == true)) {
        return a['ongoing'] == true ? -1 : 1;
      }
      final sa = a['startAt']?.toString() ?? a['startDate']?.toString() ?? '';
      final sb = b['startAt']?.toString() ?? b['startDate']?.toString() ?? '';
      final c = sa.compareTo(sb);
      if (c != 0) return c;
      return ((a['distanceKm'] as num?) ?? 9999).compareTo(
        (b['distanceKm'] as num?) ?? 9999,
      );
    });
    return list;
  }

  /// Evenemang i dag -- de som visas på kartan under Alla.
  List<Map<String, dynamic>> get _eventsToday {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    return _eventsVisible.where((e) {
      if (e['ongoing'] == true) return true;
      final start = DateTime.tryParse(e['startDate']?.toString() ?? '');
      return start != null &&
          start.year == today.year &&
          start.month == today.month &&
          start.day == today.day;
    }).toList();
  }

  // --- Kategorierna -------------------------------------------------------

  SignalCategory? get _lens => signalCategoryFromKey(_category);

  /// Kategorier föraren stängt av helt i filtret. Tåg & buss räknas som
  /// avstängt först när alla dess färdsätt är det.
  Set<SignalCategory> get _hiddenCategories => {
    if (const [
      'train',
      'metro',
      'tram',
      'bus',
      'boat',
    ].every(_hiddenModes.contains))
      SignalCategory.transit,
    if (_hiddenModes.contains('road')) SignalCategory.road,
    if (_hiddenModes.contains('flight')) SignalCategory.flight,
    if (_hiddenModes.contains('ferry')) SignalCategory.ferry,
    if (_hiddenModes.contains('events')) SignalCategory.event,
  };

  Map<SignalCategory, int> get _categoryCounts {
    final counts = {for (final c in SignalCategory.values) c: 0};
    for (final a in _activeSignalsVisible) {
      final c = categoryOfAlert(a);
      counts[c] = counts[c]! + 1;
    }
    counts[SignalCategory.ferry] =
        counts[SignalCategory.ferry]! + _ferriesVisible.length;
    counts[SignalCategory.event] = _eventsToday.length;
    // Utanför Väg-läget skickar servern bara de närmaste väghändelserna, men
    // räknar alla. Knappen ska säga hur många föraren får se när hen trycker.
    final roadTotal = (_data?['roadTotal'] as num?)?.toInt();
    if (_data?['roadAll'] != true &&
        roadTotal != null &&
        !_hiddenModes.contains('road') &&
        roadTotal > counts[SignalCategory.road]!) {
      counts[SignalCategory.road] = roadTotal;
    }
    return counts;
  }

  int get _followedCount => _favorites.length + _followedEvents.length;

  String _tipId(Map<String, dynamic> a) =>
      'tip:${a['id'] ?? a['external_id'] ?? a['title']}';

  /// Det kartan ritar, för den valda kategorin. Samma urval som listan.
  List<MapItem> get _mapItems {
    final items = <MapItem>[];
    void addTip(Map<String, dynamic> a, {bool followed = false}) {
      final lat = (a['lat'] as num?)?.toDouble();
      final lon = (a['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) return;
      final id = _tipId(a);
      items.add(
        MapItem(
          id: id,
          lat: lat,
          lon: lon,
          category: categoryOfAlert(a),
          strength: strengthOfAlert(a),
          icon: iconForAlert(a),
          followed: followed || a['is_favorite'] == true,
          onTap: () {
            setState(() => _selectedId = id);
            _openAlertDetail(a);
          },
        ),
      );
    }

    void addEvent(Map<String, dynamic> e) {
      final lat = (e['lat'] as num?)?.toDouble();
      final lon = (e['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) return;
      final id = 'event:${e['id']}';
      items.add(
        MapItem(
          id: id,
          lat: lat,
          lon: lon,
          category: SignalCategory.event,
          strength: strengthOfEvent(e),
          icon: iconForEvent(e),
          followed: _isFollowedEvent(e),
          onTap: () {
            setState(() => _selectedId = id);
            _openEvent(e);
          },
        ),
      );
    }

    if (_category == 'followed') {
      for (final a in _favorites) {
        addTip(a, followed: true);
      }
      for (final e in _followedEvents.values) {
        addEvent(e);
      }
      return items;
    }
    final lens = _lens;
    for (final a in _activeSignalsVisible) {
      if (lens == null || categoryOfAlert(a) == lens) addTip(a);
    }
    if (lens == SignalCategory.event) {
      _eventsInWindow.forEach(addEvent);
    } else if (lens == null) {
      _eventsToday.forEach(addEvent);
    }
    return items;
  }

  bool get _mapShowsFerries =>
      _showFerries &&
      (_category == null || _category == SignalCategory.ferry.key);

  /// Terminalens läge för en färja -- dit föraren kör, inte till fartyget.
  (double, double)? _harborFor(Map<String, dynamic> f) {
    final t = f['terminal'];
    if (t is Map && t['lat'] is num && t['lon'] is num) {
      return ((t['lat'] as num).toDouble(), (t['lon'] as num).toDouble());
    }
    final key = t?.toString() ?? '';
    for (final terminal in _ferryTerminals) {
      if (terminal['key']?.toString() == key &&
          terminal['lat'] is num &&
          terminal['lon'] is num) {
        return (
          (terminal['lat'] as num).toDouble(),
          (terminal['lon'] as num).toDouble(),
        );
      }
    }
    return null;
  }

  /// Place + near-me filters (not kind / high-only).
  List<Map<String, dynamic>> _geoFilter(List<Map<String, dynamic>> list) {
    var out = list;
    if (_nearMe && _userLat != null && _userLon != null) {
      final stats = _asMaps(_data?['placeStats']);
      out = out.where((a) => _alertNear(a, stats)).toList();
    }
    return out;
  }

  /// Färdsätt + typfilter — giltig för tipslistan (inte AIS/evenemang).
  List<Map<String, dynamic>> _sourceFilterList(
    List<Map<String, dynamic>> list,
  ) {
    var out = list;
    if (_hiddenModes.isNotEmpty) {
      out = out
          .where((a) => !_hiddenModes.contains(alertFilterMode(a)))
          .toList();
    }
    if (_hiddenTiers.isNotEmpty) {
      out = out
          .where((a) => !_hiddenTiers.contains(a['severity_tier']?.toString()))
          .toList();
    }
    return out;
  }

  // "Bara hög prio" ersattes av poängslidaren — se `_inScoreRange`.

  /// Kart + bottenlista: starkast först (samma färg som pinnarna).
  ///
  /// Tidigare sorterade listan på nyast — då hamnade ett svagt tips från
  /// just nu över ett starkt tips från för en timme sedan, medan kartans
  /// ringfärg sa något annat. Avstånd bryter lika prio (närmast först).
  void _sortByPriority(List<Map<String, dynamic>> list) {
    int rank(Map<String, dynamic> a) => switch (likelihoodForAlert(a)) {
      CustomerLikelihood.high => 0,
      CustomerLikelihood.medium => 1,
      CustomerLikelihood.low => 2,
    };
    list.sort((a, b) {
      final aActive = a['is_active'] != false;
      final bActive = b['is_active'] != false;
      if (aActive != bActive) return aActive ? -1 : 1;

      final da = (a['distance_km'] as num?) ?? double.infinity;
      final db = (b['distance_km'] as num?) ?? double.infinity;
      final ta = (a['start_time'] as String?) ?? '';
      final tb = (b['start_time'] as String?) ?? '';

      if (_sortMode == 'score') {
        final sa = (a['worth_it_score'] as num?) ?? 0;
        final sb = (b['worth_it_score'] as num?) ?? 0;
        if (sa != sb) return sb.compareTo(sa); // Högst först
      } else if (_sortMode == 'distance') {
        if (da != db) return da.compareTo(db); // Närmast först
      } else if (_sortMode == 'newest') {
        if (ta != tb) return tb.compareTo(ta); // Nyast först
      }

      final ra = rank(a);
      final rb = rank(b);
      if (ra != rb) return ra.compareTo(rb);
      if (da != db) return da.compareTo(db);
      return tb.compareTo(ta);
    });
  }

  /// Poäng 0–100 som slidaren filtrerar på. worth_it först, annars demand.
  double _alertScore(Map<String, dynamic> a) {
    final worth = (a['worth_it_score'] as num?)?.toDouble();
    if (worth != null) return worth.clamp(0, 100);
    final demand = (a['demand_score'] as num?)?.toDouble();
    if (demand != null) return demand.clamp(0, 100);
    return switch (likelihoodForAlert(a)) {
      CustomerLikelihood.high => 75,
      CustomerLikelihood.medium => 40,
      CustomerLikelihood.low => 15,
    };
  }

  bool _inScoreRange(Map<String, dynamic> a) {
    final s = _alertScore(a);
    return s >= _scoreMin && s <= _scoreMax;
  }

  bool get _scoreFilterActive => _scoreMin > 0 || _scoreMax < 100;

  /// 0 = alla, 1 = starka (50+), 2 = akuta (70+), -1 = egen slidare i Filter.
  int get _scorePreset {
    if (_scoreMin <= 0 && _scoreMax >= 100) return 0;
    if (_scoreMin == 50 && _scoreMax >= 100) return 1;
    if (_scoreMin == 70 && _scoreMax >= 100) return 2;
    return -1;
  }

  void _applyScorePreset(int preset) {
    setState(() {
      if (preset == 1) {
        _scoreMin = 50;
        _scoreMax = 100;
      } else if (preset == 2) {
        _scoreMin = 70;
        _scoreMax = 100;
      } else {
        _scoreMin = 0;
        _scoreMax = 100;
      }
    });
    _saveFilters();
  }

  Future<void> _expandSheet([double to = 0.72]) async {
    if (!_sheetController.isAttached) return;
    await _sheetController.animateTo(
      to,
      duration: const Duration(milliseconds: 280),
      curve: Curves.easeOutCubic,
    );
  }

  /// Tips i listan — samma filter som pipelinens förarvy. Koordinater krävs
  /// inte: många SL-tips saknar plats men ska fortfarande synas.
  List<Map<String, dynamic>>? _listMemo;
  String? _listMemoKey;

  /// Filtrerad och sorterad lista. Räknas om bara när data eller filter ändras:
  /// med 1 800 väghändelser och en panel som byggs om vid varje drag hade
  /// sorteringen annars körts hundratals gånger i sekunden.
  List<Map<String, dynamic>> get _listOpportunities {
    final key = [
      identityHashCode(_data),
      _scoreMin,
      _scoreMax,
      _nearMe,
      _sortMode,
      (_hiddenModes.toList()..sort()).join(','),
      (_hiddenTiers.toList()..sort()).join(','),
      _userLat?.toStringAsFixed(3),
      _userLon?.toStringAsFixed(3),
    ].join('|');
    if (key == _listMemoKey && _listMemo != null) return _listMemo!;
    _listMemo = _computeListOpportunities();
    _listMemoKey = key;
    return _listMemo!;
  }

  List<Map<String, dynamic>> _computeListOpportunities() {
    var list = _sourceFilterList(_geoFilter(_rawActive));
    // Styrkefiltret gäller körningar, inte väghinder: en olycka på vägen dit
    // ska synas även när föraren bara vill se de starkaste tipsen.
    list = list
        .where(
          (a) => _inScoreRange(a) || categoryOfAlert(a) == SignalCategory.road,
        )
        .toList();
    _sortByPriority(list);
    return list;
  }

  List<Map<String, dynamic>> get _trafficSignals => _listOpportunities;

  List<Map<String, dynamic>> get _trafficSignalsVisible {
    final list = _trafficSignals;
    if (list.length > _maxVisibleSignals) {
      return list.take(_maxVisibleSignals).toList();
    }
    return list;
  }

  // Aktiva högst, avslutade i egen sektion — men båda kommer från samma
  // listfilter och är redan prioritetssorterade.
  List<Map<String, dynamic>> get _activeSignalsVisible =>
      _trafficSignalsVisible.where((a) => a['is_active'] != false).toList();

  List<Map<String, dynamic>> get _endedSignalsVisible =>
      _trafficSignalsVisible.where((a) => a['is_active'] == false).toList();

  bool get _filtersActive =>
      _scoreFilterActive ||
      _nearMe ||
      _counties.isNotEmpty ||
      _hiddenModes.isNotEmpty ||
      _hiddenTiers.isNotEmpty;

  List<String> _municipalitiesIn(String county) =>
      _municipalities.where((m) => m.startsWith(county)).toList()..sort();

  String _municipalityName(String code) {
    for (final rows in _municipalityCatalog.values) {
      for (final row in rows) {
        if (row['code'] == code) return row['name']?.toString() ?? code;
      }
    }
    return code;
  }

  /// Kommunlistan per län. Utan den går länen ändå att välja i sin helhet.
  Future<void> _loadMunicipalityCatalog() async {
    if (_municipalityCatalog.isNotEmpty) return;
    try {
      final data = await widget.api.getNotifyPrefs().timeout(
        const Duration(seconds: 4),
      );
      final raw = data['municipalityCatalog'];
      if (raw is! Map || !mounted) return;
      setState(() {
        _municipalityCatalog = {
          for (final entry in raw.entries)
            entry.key.toString(): [
              for (final row in (entry.value as List? ?? const []))
                Map<String, dynamic>.from(row as Map),
            ],
        };
      });
    } catch (_) {
      // Ingen katalog: länen räcker.
    }
  }

  String get _areaFilterSummary {
    if (_counties.isNotEmpty) {
      final names = [
        for (final code in (_counties.toList()..sort()))
          if (_municipalitiesIn(code).isEmpty)
            _countyNames[code] ?? code
          else
            ..._municipalitiesIn(code).map(_municipalityName),
      ];
      return names.length <= 2
          ? names.join(', ')
          : '${names.take(2).join(', ')} +${names.length - 2}';
    }
    if (_licensedCounties != null) {
      return 'Alla dina län (${_licensedCounties!.length})';
    }
    return 'Inget län valt';
  }

  /// Checklista för län + städer — kompakt i stället för långa chip-rader.
  Future<void> _openAreaChecklist() async {
    await _loadMunicipalityCatalog();
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: TbColors.foam,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setModal) {
            void apply(VoidCallback fn) {
              setState(fn);
              setModal(() {});
              _saveFilters(reloadFeed: true);
            }

            return SafeArea(
              child: SizedBox(
                height: MediaQuery.of(context).size.height * 0.72,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Center(
                      child: Container(
                        width: 40,
                        height: 4,
                        margin: const EdgeInsets.only(top: 10, bottom: 12),
                        decoration: BoxDecoration(
                          color: Colors.grey.shade400,
                          borderRadius: BorderRadius.circular(4),
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                      child: Row(
                        children: [
                          const Icon(Icons.map_outlined, color: TbColors.ink),
                          const SizedBox(width: 10),
                          const Expanded(
                            child: Text(
                              'Län och kommuner',
                              style: TextStyle(
                                fontFamily: kDisplayFont,
                                fontSize: 22,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          if (_counties.isNotEmpty ||
                              _municipalities.isNotEmpty)
                            TextButton(
                              onPressed: () => apply(() {
                                _counties.clear();
                                _municipalities.clear();
                                _regions.clear();
                                _cities.clear();
                              }),
                              child: const Text('Rensa'),
                            ),
                        ],
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                      child: Text(
                        _areaFilterSummary,
                        style: TextStyle(
                          fontSize: 13,
                          color: Colors.grey.shade600,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    const Divider(height: 1),
                    Expanded(
                      child: ListView(
                        padding: const EdgeInsets.fromLTRB(8, 8, 8, 24),
                        children: [
                          const Padding(
                            padding: EdgeInsets.fromLTRB(8, 4, 8, 4),
                            child: Text(
                              'Körområde',
                              style: TextStyle(
                                fontWeight: FontWeight.w700,
                                fontSize: 15,
                              ),
                            ),
                          ),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
                            child: Text(
                              'Länen du kör i. Notiserna, och listan när appen '
                              'inte har din plats, följer körområdet.',
                              style: TextStyle(
                                color: Colors.grey.shade600,
                                height: 1.35,
                              ),
                            ),
                          ),
                          if (_licensedCounties != null)
                            Padding(
                              padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
                              child: Text(
                                'Bara länen ni har licens för visas här.',
                                style: TextStyle(
                                  color: Colors.grey.shade700,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          for (final county in _pickableCounties) ...[
                            CheckboxListTile(
                              dense: true,
                              contentPadding: const EdgeInsets.symmetric(
                                horizontal: 8,
                              ),
                              controlAffinity: ListTileControlAffinity.leading,
                              title: Text(
                                county.value,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              value: _counties.contains(county.key),
                              activeColor: TbColors.taxiDeep,
                              onChanged: (on) => apply(() {
                                if (on == true) {
                                  _counties.add(county.key);
                                } else {
                                  _counties.remove(county.key);
                                  _municipalities.removeWhere(
                                    (m) => m.startsWith(county.key),
                                  );
                                }
                              }),
                            ),
                            if (_counties.contains(county.key) &&
                                (_municipalityCatalog[county.key] ?? const [])
                                    .isNotEmpty)
                              Padding(
                                padding: const EdgeInsets.only(left: 40),
                                child: ExpansionTile(
                                  title: Text(
                                    _municipalitiesIn(county.key).isEmpty
                                        ? 'Hela länet · välj kommuner'
                                        : '${_municipalitiesIn(county.key).length} kommuner valda',
                                    style: TextStyle(
                                      fontSize: 13,
                                      color: Colors.grey.shade700,
                                    ),
                                  ),
                                  children: [
                                    for (final row
                                        in _municipalityCatalog[county.key]!)
                                      CheckboxListTile(
                                        dense: true,
                                        controlAffinity:
                                            ListTileControlAffinity.leading,
                                        title: Text(
                                          row['name']?.toString() ?? '',
                                        ),
                                        value: _municipalities.contains(
                                          row['code'],
                                        ),
                                        activeColor: TbColors.taxiDeep,
                                        onChanged: (on) => apply(() {
                                          final code = row['code'].toString();
                                          if (on == true) {
                                            _municipalities.add(code);
                                          } else {
                                            _municipalities.remove(code);
                                          }
                                        }),
                                      ),
                                  ],
                                ),
                              ),
                          ],
                        ],
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                      child: FilledButton(
                        onPressed: () => Navigator.pop(ctx),
                        child: const Text('Klar'),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
    if (mounted) setState(() {});
  }

  // Resets to "visa allt i marknaden" -- inte till hög-prio-filtret.
  // Hög-prio som default tömde listan när ersättningstrafik korrekt
  // räknades som low, och såg ut som att pipelinen var död.
  void _clearFilters() {
    setState(() {
      _cities.clear();
      _regions.clear();
      _counties.clear();
      _municipalities.clear();
      _scoreMin = 0;
      _scoreMax = 100;
      _nearMe = false;
      _hiddenModes = {};
      _hiddenTiers = {};
      _status = null;
    });
    _saveFilters(reloadFeed: true);
    unawaited(logAnalyticsEvent('filter_cleared'));
  }

  Future<void> _openFilters() async {
    unawaited(
      logAnalyticsEvent(
        'filter_opened',
        params: {
          'near_me': _nearMe ? 1 : 0,
          'hidden_modes': _hiddenModes.length,
          'active': _filtersActive ? 1 : 0,
        },
      ),
    );
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: TbColors.foam,
      // Scrollable: the type-of-event list grows with whatever tiers are
      // live, so a fixed-height sheet overflows on smaller screens.
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setModal) {
            void apply(VoidCallback fn) {
              fn();
              setModal(() {});
            }

            return SafeArea(
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: MediaQuery.of(context).size.height * 0.85,
                ),
                child: SingleChildScrollView(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Center(
                          child: Container(
                            width: 40,
                            height: 4,
                            margin: const EdgeInsets.only(bottom: 14),
                            decoration: BoxDecoration(
                              color: Colors.grey.shade400,
                              borderRadius: BorderRadius.circular(4),
                            ),
                          ),
                        ),
                        const Text(
                          'Filter',
                          style: TextStyle(
                            fontFamily: kDisplayFont,
                            fontSize: 24,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 14),
                        const Text(
                          'Sortera',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 8),
                        SegmentedButton<String>(
                          style: SegmentedButton.styleFrom(
                            selectedBackgroundColor: TbColors.taxi,
                            selectedForegroundColor: TbColors.ink,
                          ),
                          segments: [
                            for (final (value, icon, label) in _sortOptions)
                              ButtonSegment(
                                value: value,
                                icon: Icon(icon, size: 18),
                                label: Text(label),
                              ),
                          ],
                          selected: {_sortMode},
                          onSelectionChanged: (set) =>
                              apply(() => _sortMode = set.first),
                        ),
                        // Alltid med: färdsätten går att dölja även när
                        // inga störningstyper finns att välja bland.
                        Theme(
                          data: Theme.of(
                            ctx,
                          ).copyWith(dividerColor: Colors.transparent),
                          child: ExpansionTile(
                            tilePadding: EdgeInsets.zero,
                            childrenPadding: EdgeInsets.zero,
                            title: const Text(
                              'Fler val: dölj typer',
                              style: TextStyle(fontWeight: FontWeight.w700),
                            ),
                            children: [
                              const Align(
                                alignment: Alignment.centerLeft,
                                child: Padding(
                                  padding: EdgeInsets.only(bottom: 8),
                                  child: Text(
                                    'Gul = visas. Tryck för att dölja.',
                                    style: TextStyle(color: TbColors.skiffer),
                                  ),
                                ),
                              ),
                              Wrap(
                                spacing: 8,
                                runSpacing: 8,
                                children: [
                                  for (final opt in filterModeOptions)
                                    FilterChip(
                                      avatar: BrandIcons.forMode(
                                        opt.$1,
                                        size: 16,
                                        color: _hiddenModes.contains(opt.$1)
                                            ? Colors.grey
                                            : TbColors.ink,
                                      ),
                                      label: Text(
                                        opt.$2,
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w700,
                                        ),
                                      ),
                                      selected: !_hiddenModes.contains(opt.$1),
                                      selectedColor: TbColors.taxi,
                                      showCheckmark: false,
                                      onSelected: (on) => apply(() {
                                        if (on) {
                                          _hiddenModes.remove(opt.$1);
                                        } else {
                                          _hiddenModes.add(opt.$1);
                                        }
                                      }),
                                    ),
                                ],
                              ),
                              const SizedBox(height: 8),
                              for (final tier in _filterableTiers)
                                CheckboxListTile(
                                  contentPadding: EdgeInsets.zero,
                                  dense: true,
                                  controlAffinity:
                                      ListTileControlAffinity.leading,
                                  title: Text(
                                    severityTierShortLabels[tier] ?? tier,
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                  value: !_hiddenTiers.contains(tier),
                                  onChanged: (on) => apply(() {
                                    if (on == true) {
                                      _hiddenTiers.remove(tier);
                                    } else {
                                      _hiddenTiers.add(tier);
                                    }
                                  }),
                                ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 16),
                        const Text(
                          'Styrka',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            for (final (i, label) in const [
                              (0, 'Alla'),
                              (1, 'Starka'),
                              (2, 'Starkast'),
                            ]) ...[
                              if (i > 0) const SizedBox(width: 8),
                              Expanded(
                                child: _ScorePresetChip(
                                  label: label,
                                  selected: _scorePreset == i,
                                  onTap: () {
                                    _applyScorePreset(i);
                                    setModal(() {});
                                  },
                                ),
                              ),
                            ],
                          ],
                        ),
                        const SizedBox(height: 8),
                        const Text(
                          'Område',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: Badge(
                            isLabelVisible: _counties.isNotEmpty,
                            smallSize: 8,
                            backgroundColor: TbColors.taxi,
                            child: const Icon(
                              Icons.map_outlined,
                              color: TbColors.ink,
                            ),
                          ),
                          title: const Text(
                            'Län och kommuner',
                            style: TextStyle(fontWeight: FontWeight.w700),
                          ),
                          subtitle: Text(
                            _areaFilterSummary,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () async {
                            await _openAreaChecklist();
                            setModal(() {});
                          },
                        ),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          secondary: Icon(
                            _nearMe ? Icons.near_me : Icons.near_me_disabled,
                            color: TbColors.ink,
                          ),
                          title: const Text(
                            'Nära mig',
                            style: TextStyle(fontWeight: FontWeight.w700),
                          ),
                          subtitle: const Text('Inom ca 25 km'),
                          value: _nearMe,
                          onChanged: (v) async {
                            if (v) {
                              Navigator.pop(ctx);
                              await _toggleNearMe(true);
                            } else {
                              apply(() => _nearMe = false);
                            }
                          },
                        ),
                        const SizedBox(height: 16),
                        Row(
                          children: [
                            TextButton.icon(
                              onPressed: () {
                                _clearFilters();
                                setModal(() {});
                              },
                              icon: const Icon(
                                Icons.filter_alt_off_outlined,
                                size: 18,
                              ),
                              label: const Text('Återställ filter'),
                            ),
                            const Spacer(),
                            FilledButton(
                              onPressed: () => Navigator.pop(ctx),
                              child: const Text('Klar'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          },
        );
      },
    );
    if (mounted) {
      setState(() {});
      _saveFilters();
    }
  }

  bool _alertNear(Map<String, dynamic> a, List<Map<String, dynamic>> stats) {
    final lat = (a['lat'] as num?)?.toDouble();
    final lon = (a['lon'] as num?)?.toDouble();
    if (lat != null && lon != null && _userLat != null && _userLon != null) {
      return _km(_userLat!, _userLon!, lat, lon) <= _nearKm;
    }
    final places = ((a['taxi'] as Map?)?['places'] as List?) ?? [];
    for (final name in places) {
      Map<String, dynamic>? st;
      for (final p in stats) {
        if (p['name'] == name) {
          st = p;
          break;
        }
      }
      final plat = (st?['lat'] as num?)?.toDouble();
      final plon = (st?['lon'] as num?)?.toDouble();
      if (plat != null &&
          plon != null &&
          _userLat != null &&
          _userLon != null) {
        if (_km(_userLat!, _userLon!, plat, plon) <= _nearKm) return true;
      }
    }
    // Ingen geo = inte "nära dig".
    return false;
  }

  double _km(double lat1, double lon1, double lat2, double lon2) {
    const r = 6371.0;
    final dLat = _rad(lat2 - lat1);
    final dLon = _rad(lon2 - lon1);
    final a =
        math.sin(dLat / 2) * math.sin(dLat / 2) +
        math.cos(_rad(lat1)) *
            math.cos(_rad(lat2)) *
            math.sin(dLon / 2) *
            math.sin(dLon / 2);
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a));
  }

  double _rad(double d) => d * math.pi / 180;

  Future<void> _toggleNearMe(bool on) async {
    if (!on) {
      setState(() => _nearMe = false);
      _saveFilters();
      return;
    }
    final err = await _updateCurrentPosition(explain: true);
    if (!mounted) return;
    if (err != null || _userLat == null || _userLon == null) {
      setState(() {
        _nearMe = false;
        _error = err ?? 'Kunde inte hämta position';
      });
      _saveFilters();
      return;
    }
    setState(() {
      _nearMe = true;
      _status = 'Nära dig (25 km)';
      _error = null;
    });
    _saveFilters();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || _userLat == null || _userLon == null) return;
      try {
        _mapFocus.move(_userLat!, _userLon!, 12);
      } catch (_) {}
    });
  }

  int _rank(Object? level) => level == 'high'
      ? 3
      : level == 'medium'
      ? 2
      : 1;

  String _placeName(Map<String, dynamic> a) {
    final places = ((a['taxi'] as Map?)?['places'] as List?) ?? [];
    if (places.isNotEmpty) return places.first.toString();
    // Real opportunities never carry taxi.places (that's a legacy events-era
    // field) -- fall back to the actual title rather than a hardcoded "Skåne"
    // that told the driver nothing about which disruption they'd tapped.
    final title = a['title']?.toString().trim();
    if (title == null || title.isEmpty) return 'Skåne';
    return displayTitle(title: title, mode: a['mode']?.toString());
  }

  // 'header'/'taxi.driverHint' were legacy events-era fields never populated
  // on real opportunities (get_smart_alerts never returns them) -- this always
  // fell through to a generic placeholder instead of the actual, specific
  // description that's right there in a['summary'] and already shown on the
  // card the driver just tapped. Showing that same real text here, not a
  // vaguer restatement, is what makes the sheet worth opening.
  String _hint(Map<String, dynamic> a) {
    final summary = a['summary']?.toString().trim();
    if (summary != null && summary.isNotEmpty) return summary;
    return 'Ingen ytterligare beskrivning tillgänglig.';
  }

  List<Map<String, dynamic>> get _places {
    final statsByName = <String, Map<String, dynamic>>{
      for (final p in _asMaps(_data?['placeStats']))
        if (p['name'] != null) p['name'].toString(): p,
    };

    // Samma länsfilter som kartan/listan, men utan stadsfilter (chips
    // ska lista orter i länet, inte bara den redan valda staden).
    var list = List<Map<String, dynamic>>.from(_rawActive);
    list = list.where(_inScoreRange).toList();
    if (_nearMe && _userLat != null && _userLon != null) {
      final stats = statsByName.values.toList();
      list = list.where((a) => _alertNear(a, stats)).toList();
    }

    final map = <String, Map<String, dynamic>>{};
    for (final a in list) {
      final places = ((a['taxi'] as Map?)?['places'] as List?) ?? [];
      final level = (a['taxi'] as Map?)?['level']?.toString() ?? 'low';
      for (final p in places) {
        final name = p.toString();
        if (name.isEmpty) continue;
        final base = statsByName[name];
        final cur =
            map[name] ??
            {
              'name': name,
              'count': 0,
              'maxLevel': level,
              if (base?['lat'] != null) 'lat': base!['lat'],
              if (base?['lon'] != null) 'lon': base!['lon'],
              if (base?['isHub'] != null) 'isHub': base!['isHub'],
            };
        cur['count'] = ((cur['count'] as num?)?.toInt() ?? 0) + 1;
        if (_rank(level) > _rank(cur['maxLevel'])) cur['maxLevel'] = level;
        map[name] = cur;
      }
    }

    final out = map.values.toList()
      ..sort((a, b) {
        final ra = _rank(a['maxLevel']);
        final rb = _rank(b['maxLevel']);
        if (rb != ra) return rb.compareTo(ra);
        return ((b['count'] as num?) ?? 0).compareTo((a['count'] as num?) ?? 0);
      });
    return out;
  }

  String _clock(Object? ts) {
    final n = ts is num ? ts.toInt() : int.tryParse('$ts');
    if (n == null) return '—';
    final d = DateTime.fromMillisecondsSinceEpoch(n);
    return '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
  }

  Future<void> _openAlertDetail(Map<String, dynamic> a) async {
    final url = a['url']?.toString();
    final likelihood = likelihoodForAlert(a);
    final kind = (a['kind'] ?? a['sourceKind'] ?? 'unknown').toString();
    final score = a['score'];
    unawaited(
      logAnalyticsEvent(
        'tip_opened',
        params: {'kind': kind, if (score is num) 'score': score.round()},
      ),
    );
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      // DraggableScrollableSheet hanterar bakgrund och hörn; transparent
      // här så att inget double-clip på hörnen sker.
      backgroundColor: Colors.transparent,
      builder: (ctx) {
        // DraggableScrollableSheet koordinerar scroll och sheet-drag som
        // EN mekanism via scrollController. Utan detta konkurrerar
        // BottomSheets drag-detektor med SingleChildScrollView om
        // gesterna: föraren försöker skrolla ner i en lång text men
        // sheetet stängs istället. initialChildSize 0.85 ger plats för
        // de allra flesta tipsbeskrivningar; användaren drar upp till
        // 0.96 om "Varför"-sektionen behöver mer utrymme.
        return DraggableScrollableSheet(
          expand: false,
          initialChildSize: 0.85,
          minChildSize: 0.35,
          maxChildSize: 0.96,
          snap: true,
          snapSizes: const [0.35, 0.85, 0.96],
          // true: om föraren drar ner förbi minsta storlek stängs sheetet
          // automatiskt (samma känsla som en vanlig modal bottom sheet).
          shouldCloseOnMinExtent: true,
          builder: (_, scrollController) {
            return DecoratedBox(
              decoration: const BoxDecoration(
                color: TbColors.foam,
                borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
              ),
              child: SafeArea(
                top: false,
                child: SingleChildScrollView(
                  controller: scrollController,
                  padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Center(
                        child: Container(
                          width: 40,
                          height: 4,
                          margin: const EdgeInsets.only(bottom: 14),
                          decoration: BoxDecoration(
                            color: Colors.grey.shade400,
                            borderRadius: BorderRadius.circular(4),
                          ),
                        ),
                      ),
                      // VAD och HUR VIKTIGT, som på kortet och kartan: samma
                      // ikon, samma färg, samma ord.
                      Row(
                        children: [
                          Container(
                            width: 52,
                            height: 52,
                            decoration: BoxDecoration(
                              color: strengthColor(
                                strengthOfAlert(a),
                                category: categoryOfAlert(a),
                              ),
                              borderRadius: BorderRadius.circular(
                                categoryOfAlert(a) == SignalCategory.road
                                    ? 8
                                    : 14,
                              ),
                            ),
                            child: Icon(
                              iconForAlert(a),
                              color: TbColors.vit,
                              size: 30,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '${categoryOfAlert(a).label} · ${shortWhat(a)}'
                                      .toUpperCase(),
                                  style: const TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w700,
                                    letterSpacing: 0.6,
                                    color: TbColors.skiffer,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                StrengthPill(
                                  strength: strengthOfAlert(a),
                                  category: categoryOfAlert(a),
                                  large: true,
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Text(
                        _placeName(a),
                        style: const TextStyle(
                          fontFamily: kDisplayFont,
                          fontSize: 26,
                          fontWeight: FontWeight.w700,
                          height: 1.15,
                        ),
                      ),
                      const SizedBox(height: 14),
                      // Kör dit (telefonens navigering) och Följ -- de två saker
                      // föraren gör med ett tips, överst och stora. Ett väghinder
                      // kör man runt, inte till: där finns bara Följ.
                      ActionRow(
                        lat: categoryOfAlert(a) == SignalCategory.road
                            ? null
                            : (a['lat'] as num?)?.toDouble(),
                        lon: (a['lon'] as num?)?.toDouble(),
                        driveLabel: _distanceFor(a) == null
                            ? 'Kör dit'
                            : 'Kör dit · ${distanceText(_distanceFor(a))}',
                        followed: a['is_favorite'] == true,
                        onToggleFollow: widget.api.supportsFavorites
                            ? (v) => _toggleFavorite(a, v)
                            : null,
                      ),
                      const SizedBox(height: 10),
                      // Stat row: date/time + score up front so a driver scanning
                      // the sheet can place it in time and judge it at a glance,
                      // without scrolling into "Varför visas detta?" for either.
                      Row(
                        children: [
                          // Flexible: datum/tid-etiketten kan bli lång ("→"-intervall
                          // för avslutade larm) och får krympa/klippas i stället för
                          // att trycka ut score-badgen på smala skärmar.
                          Flexible(
                            child: _DetailStat(
                              icon: BrandIcons.clock(
                                size: 13,
                                color: Colors.grey.shade700,
                              ),
                              label: a['is_active'] == false
                                  ? '${dateTimeLabel(a['start_time']?.toString())} → ${dateTimeLabel(a['end_time']?.toString())}'
                                  : dateTimeLabel(a['start_time']?.toString()),
                            ),
                          ),
                          const SizedBox(width: 8),
                          _DetailStat(
                            icon: Icon(
                              Icons.speed,
                              size: 13,
                              color: Colors.grey.shade700,
                            ),
                            label:
                                '${(a['demand_score'] as num?)?.round() ?? '—'}/100',
                          ),
                          if (a['is_active'] == false) ...[
                            const SizedBox(width: 8),
                            _DetailStat(
                              icon: Icon(
                                Icons.history,
                                size: 13,
                                color: Colors.grey.shade700,
                              ),
                              label: 'Avslutad',
                            ),
                          ],
                        ],
                      ),
                      const SizedBox(height: 10),
                      // This is the real, specific description (the same text
                      // shown on the card the driver just tapped) -- sized and
                      // spaced to read at a glance from a driver's seat: large
                      // enough, generous line height, high-contrast ink instead
                      // of a lighter grey.
                      Text(
                        _hint(a),
                        style: const TextStyle(
                          fontSize: 18,
                          height: 1.45,
                          fontWeight: FontWeight.w600,
                          color: TbColors.ink,
                        ),
                      ),
                      // Nästa avgång och ersättningstrafik, utskrivet. Samma
                      // mening som kortet visar -- backend formulerar den en
                      // gång (core/alternatives.py).
                      if (TravelOptions.of(a) case final travel?) ...[
                        const SizedBox(height: 10),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            (() {
                              final color = travel.isStrong
                                  ? TbColors.live
                                  : TbColors.muted;
                              if (travel.isLastDeparture) {
                                return Icon(
                                  Icons.last_page,
                                  size: 17,
                                  color: color,
                                );
                              }
                              if (travel.hasAlternative) {
                                return BrandIcons.bus(size: 17, color: color);
                              }
                              return Icon(
                                Icons.schedule_send,
                                size: 17,
                                color: color,
                              );
                            })(),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    travel.summary!,
                                    style: TextStyle(
                                      fontSize: 15,
                                      height: 1.35,
                                      fontWeight: FontWeight.w700,
                                      color: travel.isStrong
                                          ? TbColors.live
                                          : TbColors.ink,
                                    ),
                                  ),
                                  if (travel.planner != null)
                                    Padding(
                                      padding: const EdgeInsets.only(top: 2),
                                      child: Text(
                                        'Nästa resa mot samma mål enligt reseplaneraren '
                                        '${travel.planner} (Trafiklab), inte bara nästa tåg från stationen.',
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: TbColors.muted,
                                        ),
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ],
                      // Ersättningsrätten, utskriven. Kortets chip säger att den
                      // finns; här står vad den betyder för den som står kvar på
                      // perrongen -- och därmed varför just det här tipset kan
                      // vara värt att köra till.
                      if (a['compensation_eligible'] == true) ...[
                        const SizedBox(height: 10),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Icon(
                              Icons.receipt_long,
                              size: 17,
                              color: TbColors.live,
                            ),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                '${compensationLabel(a['compensation_amount_kr'] as num?, perPerson: a['compensation_per_person'] as bool?)} — resenären har rätt till ersättning för taxi enligt lag 2015:953.',
                                style: const TextStyle(
                                  fontSize: 14,
                                  height: 1.35,
                                  fontWeight: FontWeight.w600,
                                  color: TbColors.live,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                      if (url != null && url.isNotEmpty) ...[
                        const SizedBox(height: 16),
                        SizedBox(
                          width: double.infinity,
                          child: FilledButton.icon(
                            onPressed: () async {
                              final uri = Uri.tryParse(url);
                              if (uri != null) {
                                await launchUrl(
                                  uri,
                                  mode: LaunchMode.externalApplication,
                                );
                              }
                            },
                            icon: const Icon(Icons.open_in_new),
                            label: const Text('Öppna mer info'),
                          ),
                        ),
                      ],
                      if (a['id'] != null) ...[
                        // "Fick körning / Ingen kund" frågar om ett tips gav
                        // kunder -- ett väghinder lovar inga.
                        if (categoryOfAlert(a) != SignalCategory.road) ...[
                          AlertFeedbackBar(
                            api: widget.api,
                            opportunityId: a['id'].toString(),
                          ),
                          const SizedBox(height: 16),
                        ],
                        _ExplainSection(
                          opportunityId: a['id'].toString(),
                          api: widget.api,
                          likelihood: likelihood,
                        ),
                      ],
                      const SizedBox(height: 8),
                      TextButton(
                        onPressed: () => Navigator.pop(ctx),
                        child: const Text('Stäng'),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final places = _places;
    // Rensa ortval som inte längre finns i listan (t.ex. efter regionbyte).
    final known = places
        .map((p) => p['name']?.toString())
        .whereType<String>()
        .toSet();
    if (_cities.isNotEmpty && _cities.any((c) => !known.contains(c))) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        setState(() => _cities.removeWhere((c) => !known.contains(c)));
      });
    }
    // Vilken väg datan kom (`django` eller `trafiklab`) säger inget om
    // huruvida den är färsk -- båda läser samma pipeline. Utan `django` här
    // slocknade live-indikatorn så fort appen bytte till Spår B.
    final source = _data?['source']?.toString() ?? '';
    final live = source == 'django' || source.contains('trafik');

    return Scaffold(
      backgroundColor: TbColors.foam,
      body: DefaultTextStyle(
        style: const TextStyle(
          color: TbColors.ink,
          fontSize: 15,
          fontWeight: FontWeight.w500,
          decoration: TextDecoration.none,
        ),
        child: _claiming
            ? const SafeArea(
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      CircularProgressIndicator(color: TbColors.taxi),
                      SizedBox(height: 16),
                      Text(
                        'Kopplar telefon…',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                          color: TbColors.ink,
                        ),
                      ),
                    ],
                  ),
                ),
              )
            : Stack(
                children: [
                  // 1. Karta (underst)
                  Positioned.fill(
                    child: useGoogleMaps
                        ? GoogleSignalMap(
                            items: _mapItems,
                            focus: _mapFocus,
                            ferries: _mapShowsFerries ? _ferryShips : const [],
                            ferryTerminals: _mapShowsFerries
                                ? _ferryTerminals
                                : const [],
                            onSelectFerry: _openFerry,
                            selectedId: _selectedId,
                          )
                        : SignalMap(
                            items: _mapItems,
                            mapController: _mapController,
                            ferries: _mapShowsFerries ? _ferryShips : const [],
                            ferryTerminals: _mapShowsFerries
                                ? _ferryTerminals
                                : const [],
                            onSelectFerry: _openFerry,
                            userLat: _userLat,
                            userLon: _userLon,
                            selectedId: _selectedId,
                          ),
                  ),

                  // 2. Uppe: logotyp och inställningar, kategoriraden, och en rad
                  // när något behöver åtgärdas.
                  Positioned(
                    top: 0,
                    left: 0,
                    right: 0,
                    child: SafeArea(
                      bottom: false,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Padding(
                            padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 6,
                                    vertical: 6,
                                  ),
                                  decoration: BoxDecoration(
                                    color: Colors.white.withValues(alpha: 0.96),
                                    borderRadius: BorderRadius.circular(32),
                                    boxShadow: const [
                                      BoxShadow(
                                        color: Colors.black12,
                                        blurRadius: 12,
                                        offset: Offset(0, 4),
                                      ),
                                    ],
                                  ),
                                  child: Stack(
                                    alignment: Alignment.center,
                                    children: [
                                      SvgPicture.asset(
                                        'assets/brand/logo.svg',
                                        height: 24,
                                      ),
                                      Row(
                                        mainAxisAlignment:
                                            MainAxisAlignment.spaceBetween,
                                        children: [
                                          if (widget.onBack != null)
                                            IconButton(
                                              icon: const Icon(
                                                Icons.arrow_back,
                                              ),
                                              tooltip: 'Tillbaka',
                                              color: TbColors.ink,
                                              onPressed: widget.onBack!,
                                            )
                                          else
                                            const SizedBox(width: 48),
                                          if (widget.onOpenSettings != null)
                                            IconButton(
                                              icon: const Icon(
                                                Icons.settings_outlined,
                                              ),
                                              tooltip: 'Inställningar',
                                              color: TbColors.ink,
                                              onPressed: widget.onOpenSettings!,
                                            )
                                          else
                                            const SizedBox(width: 48),
                                        ],
                                      ),
                                    ],
                                  ),
                                ),
                                if (_needsVehicle) ...[
                                  const SizedBox(height: 8),
                                  _Notice(
                                    icon: Icons.local_taxi_outlined,
                                    text:
                                        'Välj vilken bil du kör för att se tips.',
                                    action: 'Välj bil',
                                    onAction: _openVehiclePicker,
                                  ),
                                ] else if (_entitled == false) ...[
                                  const SizedBox(height: 8),
                                  _EntitlementBanner(
                                    reason: _entitlementReason,
                                    message: _entitlementMessage,
                                    onOpenSettings: widget.onOpenSettings,
                                  ),
                                ] else if (_needsArea) ...[
                                  const SizedBox(height: 8),
                                  _Notice(
                                    icon: Icons.map_outlined,
                                    text:
                                        'Välj ditt körområde för att se tips.',
                                    action: 'Välj',
                                    onAction: _openAreaChecklist,
                                  ),
                                ],
                                if (_error != null) ...[
                                  const SizedBox(height: 8),
                                  _Notice(
                                    icon: Icons.cloud_off,
                                    text: _error!,
                                    danger: true,
                                  ),
                                ] else if (_data != null &&
                                    !live &&
                                    !widget.demo) ...[
                                  const SizedBox(height: 8),
                                  _Notice(
                                    icon: Icons.schedule,
                                    text:
                                        'Inte uppdaterat sedan ${_clock(_data?['updatedAt'])}',
                                  ),
                                ],
                                if (_status != null) ...[
                                  const SizedBox(height: 8),
                                  _Notice(
                                    icon: Icons.info_outline,
                                    text: _status!,
                                  ),
                                ],
                              ],
                            ),
                          ),
                          const SizedBox(height: 8),
                          CategoryBar(
                            selected: _category,
                            counts: _categoryCounts,
                            followedCount: _followedCount,
                            hidden: _hiddenCategories,
                            onSelect: _selectCategory,
                          ),
                        ],
                      ),
                    ),
                  ),

                  // 3. Kartknapparna nere till höger, där tummen når: filter och min position.
                  // De följer listans överkant och tonas bort när listan dras upp
                  // -- annars hamnar de under statusraden. Filtret finns då i
                  // listans rubrik i stället.
                  Positioned(
                    left: 12,
                    right: 12,
                    bottom:
                        MediaQuery.of(context).size.height * _sheetExtent + 12,
                    child: IgnorePointer(
                      ignoring: _sheetHigh,
                      child: AnimatedOpacity(
                        opacity: _sheetHigh ? 0 : 1,
                        duration: const Duration(milliseconds: 150),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Badge(
                              isLabelVisible: _filtersActive,
                              smallSize: 12,
                              backgroundColor: TbColors.taxiDeep,
                              child: FloatingActionButton.extended(
                                heroTag: 'filter_fab',
                                onPressed: _openFilters,
                                backgroundColor: Colors.white,
                                foregroundColor: TbColors.ink,
                                elevation: 4,
                                icon: const Icon(Icons.tune),
                                label: const Text(
                                  'Filter',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ),
                            Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                _ZoomButtons(
                                  onZoomIn: () => _zoomBy(1),
                                  onZoomOut: () => _zoomBy(-1),
                                ),
                                const SizedBox(height: 10),
                                FloatingActionButton.small(
                                  heroTag: 'legend_fab',
                                  onPressed: () => showMapLegend(context),
                                  backgroundColor: Colors.white,
                                  foregroundColor: TbColors.ink,
                                  elevation: 4,
                                  tooltip: 'Vad betyder symbolerna?',
                                  child: const Icon(Icons.help_outline_rounded),
                                ),
                                const SizedBox(height: 10),
                                FloatingActionButton(
                                  heroTag: 'location_fab',
                                  onPressed: _goToMyLocation,
                                  backgroundColor: Colors.white,
                                  foregroundColor: _userLat != null
                                      ? const Color(0xFF1A73E8)
                                      : TbColors.ink,
                                  elevation: 4,
                                  tooltip: 'Min position',
                                  child: Icon(
                                    _userLat != null
                                        ? Icons.my_location
                                        : Icons.location_searching,
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),

                  // 4. Bottenmeny — EN scrollvy så den går att dra upp från start
                  NotificationListener<DraggableScrollableNotification>(
                    onNotification: (n) {
                      if ((n.extent - _sheetExtent).abs() > 0.01) {
                        setState(() => _sheetExtent = n.extent);
                      }
                      return false;
                    },
                    child: DraggableScrollableSheet(
                      controller: _sheetController,
                      initialChildSize: 0.42,
                      minChildSize: 0.15,
                      maxChildSize: 0.9,
                      snap: true,
                      snapSizes: const [0.15, 0.42, 0.9],
                      shouldCloseOnMinExtent: false,
                      builder: (context, scrollController) {
                        return Material(
                          color: TbColors.vit,
                          elevation: 16,
                          shadowColor: Colors.black26,
                          borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(32),
                          ),
                          clipBehavior: Clip.antiAlias,
                          child: RefreshIndicator(
                            color: TbColors.taxiDeep,
                            onRefresh: () => _load(),
                            child: ListView(
                              controller: scrollController,
                              physics: const AlwaysScrollableScrollPhysics(),
                              padding: EdgeInsets.only(
                                bottom:
                                    24 + MediaQuery.paddingOf(context).bottom,
                              ),
                              children: [
                                // Handtaget: tryck för att växla mellan lista och karta.
                                GestureDetector(
                                  behavior: HitTestBehavior.opaque,
                                  onTap: () => _expandSheet(
                                    _sheetExtent < 0.5 ? 0.9 : 0.42,
                                  ),
                                  child: Center(
                                    child: Container(
                                      margin: const EdgeInsets.fromLTRB(
                                        0,
                                        12,
                                        0,
                                        8,
                                      ),
                                      width: 64,
                                      height: 6,
                                      decoration: BoxDecoration(
                                        color: Colors.grey.shade400,
                                        borderRadius: BorderRadius.circular(3),
                                      ),
                                    ),
                                  ),
                                ),
                                // Uppdateras listan syns det som en tunn linje, inget mer.
                                SizedBox(
                                  height: 3,
                                  child: _refreshing
                                      ? const LinearProgressIndicator(
                                          minHeight: 2,
                                        )
                                      : null,
                                ),
                                _sheetHeader(),
                                if (_lens == SignalCategory.road)
                                  _roadScopeNote(),
                                _activeFilterBar(),
                                const SizedBox(height: 8),
                                ..._buildSheetItems(),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                ],
              ),
      ),
    );
  }

  /// Rubriken i bottenpanelen: vad som visas, hur många, och sorteringen.
  Widget _sheetHeader() {
    final lens = _lens;
    final String title;
    final int count;
    if (_category == 'followed') {
      title = 'Följer';
      count = _followedCount;
    } else if (lens == SignalCategory.event) {
      title = 'Event';
      count = _eventsInWindow.length;
    } else if (lens == SignalCategory.ferry) {
      title = 'Färjor';
      count = _ferriesVisible.length + _tipsIn(lens).length;
    } else {
      title = lens?.label ?? 'Alla tips';
      count = _tipsIn(lens).length;
    }
    final sortable = _category != 'followed' && lens != SignalCategory.event;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 8, 0),
      child: Row(
        children: [
          Icon(
            _category == 'followed'
                ? Icons.star_rounded
                : (lens?.icon ?? Icons.apps_rounded),
            color: _category == 'followed'
                ? TbColors.guldDjup
                : TbColors.midnatt,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '$title · $count',
              style: const TextStyle(
                fontFamily: kDisplayFont,
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: TbColors.midnatt,
              ),
            ),
          ),
          if (_sheetHigh)
            Badge(
              isLabelVisible: _filtersActive,
              smallSize: 10,
              backgroundColor: TbColors.taxiDeep,
              offset: const Offset(-6, 6),
              child: IconButton(
                tooltip: 'Filter',
                onPressed: _openFilters,
                icon: const Icon(Icons.tune, color: TbColors.midnatt),
              ),
            ),
          if (sortable)
            PopupMenuButton<String>(
              tooltip: 'Sortera',
              initialValue: _sortMode,
              onSelected: (v) {
                setState(() => _sortMode = v);
                _saveFilters();
              },
              itemBuilder: (_) => [
                for (final (value, icon, label) in _sortOptions)
                  PopupMenuItem(
                    value: value,
                    child: Row(
                      children: [
                        Icon(icon, size: 20, color: TbColors.midnatt),
                        const SizedBox(width: 10),
                        Text(
                          label,
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                      ],
                    ),
                  ),
              ],
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(_sortIcon, size: 20, color: TbColors.midnatt),
                    const SizedBox(width: 4),
                    Text(
                      _sortLabel,
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        color: TbColors.midnatt,
                      ),
                    ),
                    const Icon(
                      Icons.arrow_drop_down_rounded,
                      color: TbColors.midnatt,
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// Vad som är bortfiltrerat, i klartext, med en knapp som tar bort allt.
  /// Utan den ser ett filter som sattes för en vecka sedan ut som att data saknas.
  /// Väg-läget visar bara trafikolyckor -- och säger det, så att ett
  /// vägarbete som saknas inte ser ut som ett fel. Urvalet görs i backend:
  /// thresholds.ROAD_SHOWN_CONDITIONS.
  Widget _roadScopeNote() => Padding(
    padding: const EdgeInsets.fromLTRB(16, 0, 16, 6),
    child: Text(
      'Bara trafikolyckor. Vägarbeten och avstängningar visas inte.',
      style: TextStyle(fontSize: 13.5, color: Colors.grey.shade700),
    ),
  );

  Widget _activeFilterBar() {
    if (!_filtersActive) return const SizedBox.shrink();
    final modeLabels = {
      for (final (key, label) in filterModeOptions) key: label,
    };
    final parts = <String>[
      if (_scorePreset == 1)
        'Bara starka'
      else if (_scorePreset == 2)
        'Bara starkast'
      else if (_scoreFilterActive)
        'Styrka ${_scoreMin.round()}–${_scoreMax.round()}',
      if (_nearMe) 'Nära mig',
      if (_counties.isNotEmpty || _municipalities.isNotEmpty)
        _areaFilterSummary,
      if (_hiddenModes.isNotEmpty)
        'Dolt: ${_hiddenModes.map((m) => modeLabels[m] ?? m).join(', ')}',
      if (_hiddenTiers.isNotEmpty)
        '${_hiddenTiers.length} störningstyper dolda',
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 8, 4),
      child: Material(
        color: TbColors.guld.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 4, 4, 4),
          child: Row(
            children: [
              const Icon(
                Icons.filter_alt_rounded,
                size: 20,
                color: TbColors.guldDjup,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  parts.join(' · '),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    color: TbColors.midnatt,
                  ),
                ),
              ),
              TextButton(
                onPressed: _clearFilters,
                child: const Text('Visa allt'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  static const _sortOptions = <(String, IconData, String)>[
    ('score', Icons.bolt_rounded, 'Viktigast'),
    ('distance', Icons.near_me_rounded, 'Närmast'),
    ('newest', Icons.schedule_rounded, 'Nyast'),
  ];

  IconData get _sortIcon => _sortOptions
      .firstWhere((o) => o.$1 == _sortMode, orElse: () => _sortOptions.first)
      .$2;
  String get _sortLabel => _sortOptions
      .firstWhere((o) => o.$1 == _sortMode, orElse: () => _sortOptions.first)
      .$3;

  List<Map<String, dynamic>> _tipsIn(SignalCategory? lens) => [
    for (final a in _activeSignalsVisible)
      if (lens == null || categoryOfAlert(a) == lens) a,
  ];

  /// Bottenpanelens lista för den valda kategorin.
  List<Widget> _buildSheetItems() {
    Widget empty(
      String text, {
      IconData? icon,
      String? action,
      VoidCallback? onAction,
    }) => Padding(
      padding: const EdgeInsets.fromLTRB(32, 20, 32, 24),
      child: Column(
        children: [
          if (icon != null) ...[
            Icon(icon, size: 44, color: TbColors.skiffer),
            const SizedBox(height: 10),
          ],
          Text(
            text,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 16,
              height: 1.4,
              color: TbColors.skiffer,
            ),
          ),
          if (action != null) ...[
            const SizedBox(height: 14),
            FilledButton(onPressed: onAction, child: Text(action)),
          ],
        ],
      ),
    );
    Widget pad(Widget child) => Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
      child: child,
    );
    Widget tipCard(Map<String, dynamic> a) => pad(
      SignalCard(
        alert: a,
        onTap: () {
          _focusOpportunity(a);
          _openAlertDetail(a);
        },
        onToggleFollow: widget.api.supportsFavorites
            ? (v) => _toggleFavorite(a, v)
            : null,
      ),
    );
    Widget eventCard(Map<String, dynamic> e) => pad(
      EventCard(
        event: e,
        showDate: true,
        followed: _isFollowedEvent(e),
        onToggleFollow: (v) => _toggleFollowEvent(e, v),
        onTap: () {
          _focusOpportunity(e);
          _openEvent(e);
        },
      ),
    );

    // --- Följer ---
    if (_category == 'followed') {
      final events = _followedEvents.values.toList()
        ..sort(
          (a, b) => (a['startDate']?.toString() ?? '').compareTo(
            b['startDate']?.toString() ?? '',
          ),
        );
      if (_favorites.isEmpty && events.isEmpty) {
        return [
          empty(
            'Du följer inget än.\n\nTryck på ☆ på ett tips eller ett event. '
            'Då sparas det här, också när det är över.',
            icon: Icons.star_outline_rounded,
          ),
        ];
      }
      return [
        if (_favorites.isNotEmpty) ...[
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: _SectionTitle('Tips'),
          ),
          ..._favorites.map(tipCard),
        ],
        if (events.isNotEmpty) ...[
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: _SectionTitle('Event'),
          ),
          ...events.map(eventCard),
        ],
      ];
    }

    final lens = _lens;

    // --- Event ---
    if (lens == SignalCategory.event) {
      final events = _eventsInWindow;
      return [
        _eventFilters(),
        if (_eventsPreview && _eventsPreviewNote.isNotEmpty)
          pad(PreviewBanner(text: _eventsPreviewNote)),
        if (events.isEmpty)
          _eventsSourceOk
              ? empty(
                  _eventRadiusKm != null
                      ? 'Inga event inom ${_eventRadiusKm!.round()} km. Välj ett längre avstånd.'
                      : 'Inga event de här dagarna.',
                  icon: Icons.event_busy_rounded,
                  action: 'Fler datum',
                  onAction: _openEventsScreen,
                )
              : empty(
                  'Kan inte hämta event just nu.',
                  icon: Icons.cloud_off_rounded,
                ),
        ...events.take(30).map(eventCard),
        if (events.isNotEmpty)
          pad(
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(52),
              ),
              onPressed: _openEventsScreen,
              icon: const Icon(Icons.calendar_month_rounded),
              label: const Text('Fler datum'),
            ),
          ),
        if (_eventsAttribution.isNotEmpty) _sourceNote(_eventsAttribution),
      ];
    }

    // --- Färjor ---
    if (lens == SignalCategory.ferry) {
      final tips = _tipsIn(lens);
      if (_ferriesVisible.isEmpty && tips.isEmpty) {
        return [
          empty(
            'Inga färjor på väg in just nu.',
            icon: Icons.directions_boat_rounded,
          ),
        ];
      }
      return [
        ...tips.map(tipCard),
        for (final f in _ferriesVisible)
          pad(
            FerryCard(
              ferry: f,
              onTap: () {
                _focusOpportunity(f);
                _openFerry(f);
              },
            ),
          ),
        if (_ferryAttribution.isNotEmpty) _sourceNote(_ferryAttribution),
      ];
    }

    // --- Alla, eller en typ av tips ---
    final tips = _tipsIn(lens);
    final ended = [
      for (final a in _endedSignalsVisible)
        if (lens == null || categoryOfAlert(a) == lens) a,
    ];
    final out = <Widget>[];
    if (lens == null) {
      final today = _eventsToday.length;
      final ferries = _ferriesVisible.length;
      if (today > 0 || ferries > 0) {
        out.add(
          SizedBox(
            height: 48,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              children: [
                if (today > 0)
                  _ShortcutChip(
                    icon: Icons.stadium_rounded,
                    label: '$today event i dag',
                    onTap: () => _selectCategory(SignalCategory.event.key),
                  ),
                if (ferries > 0)
                  _ShortcutChip(
                    icon: Icons.directions_boat_rounded,
                    label: '$ferries färjor på väg in',
                    onTap: () => _selectCategory(SignalCategory.ferry.key),
                  ),
              ],
            ),
          ),
        );
      }
    }
    out.addAll(tips.map(tipCard));
    if (tips.isEmpty) {
      out.add(
        _filtersActive
            ? empty(
                'Inga tips med de här filtren.',
                icon: Icons.filter_alt_off_rounded,
                action: 'Rensa filter',
                onAction: _clearFilters,
              )
            : empty(
                lens == SignalCategory.road
                    ? 'Inga trafikolyckor i ditt område just nu.'
                    : 'Inga störningar i ditt område just nu.',
                icon: Icons.check_circle_outline_rounded,
              ),
      );
    }
    if (ended.isNotEmpty) {
      out.add(
        Theme(
          data: ThemeData(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: const EdgeInsets.symmetric(horizontal: 16),
            title: Text(
              'Tidigare i dag (${ended.length})',
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
            ),
            children: [for (final a in ended) tipCard(a)],
          ),
        ),
      );
    }
    return out;
  }

  /// Dag och avstånd för event. Avståndet kräver position -- utan den visas
  /// en knapp som hämtar den i stället för val som inte kan göra något.
  Widget _eventFilters() {
    const days = [
      ('today', 'I dag'),
      ('tomorrow', 'I morgon'),
      ('weekend', 'Helgen'),
      ('week', '7 dagar'),
      ('all', '14 dagar'),
    ];
    const radii = <(double?, String)>[
      (null, 'Hela länet'),
      (10, '10 km'),
      (25, '25 km'),
      (50, '50 km'),
    ];
    Widget chip(
      String label,
      bool selected,
      VoidCallback onTap, {
      IconData? icon,
    }) => Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        avatar: icon == null
            ? null
            : Icon(
                icon,
                size: 18,
                color: selected ? TbColors.midnatt : TbColors.skiffer,
              ),
        label: Text(label),
        selected: selected,
        showCheckmark: false,
        selectedColor: TbColors.guld,
        labelStyle: const TextStyle(
          fontWeight: FontWeight.w700,
          color: TbColors.midnatt,
          fontSize: 15,
        ),
        onSelected: (_) => onTap(),
      ),
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            height: 48,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              children: [
                for (final (key, label) in days)
                  chip(
                    label,
                    _eventDay == key,
                    () {
                      setState(() => _eventDay = key);
                      _saveFilters();
                    },
                    icon: key == 'today' ? Icons.today_rounded : null,
                  ),
              ],
            ),
          ),
          SizedBox(
            height: 48,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              children: [
                if (_userLat == null)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ActionChip(
                      avatar: const Icon(Icons.my_location_rounded, size: 18),
                      label: const Text(
                        'Visa avstånd',
                        style: TextStyle(fontWeight: FontWeight.w700),
                      ),
                      onPressed: _goToMyLocation,
                    ),
                  )
                else
                  for (final (km, label) in radii)
                    chip(
                      label,
                      _eventRadiusKm == km,
                      () => setState(() => _eventRadiusKm = km),
                      icon: km == null
                          ? Icons.map_rounded
                          : Icons.near_me_rounded,
                    ),
              ],
            ),
          ),
          if (_counties.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 2, 16, 0),
              child: Row(
                children: [
                  const Icon(
                    Icons.place_rounded,
                    size: 16,
                    color: TbColors.skiffer,
                  ),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      _areaFilterSummary,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w600,
                        color: TbColors.skiffer,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Avsnittsetikett i tips-sheetet (Sparade / Nu / Senaste dygnet).
class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.title);
  final String title;

  @override
  Widget build(BuildContext context) {
    return Text(
      title,
      style: const TextStyle(
        fontFamily: kDisplayFont,
        fontSize: 15,
        fontWeight: FontWeight.w700,
        color: TbColors.ink,
      ),
    );
  }
}

/// Snabbval för poänggräns i filter-sheetet (Alla / Starka / Akuta).
class _ScorePresetChip extends StatelessWidget {
  const _ScorePresetChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? TbColors.taxi.withValues(alpha: 0.35) : Colors.white,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: selected ? TbColors.taxiDeep : TbColors.line,
              width: 1.5,
            ),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontWeight: FontWeight.w700,
              fontSize: 13,
              color: selected ? TbColors.taxiDeep : TbColors.ink,
            ),
          ),
        ),
      ),
    );
  }
}

/// "Varför visas detta?" -- lazy-loaded on tap, not fetched for every card, so
/// browsing the list doesn't cost an extra round-trip per signal. Shows the
/// scoring rule/confidence and, when a weather bonus applied, a plain-language
/// weather summary. No raw API/source payload is shown here -- that's internal
/// plumbing, not something a driver deciding whether to drive somewhere needs
/// to see; it's available in Settings → Om datan for anyone who wants it.
class _ExplainSection extends StatefulWidget {
  const _ExplainSection({
    required this.opportunityId,
    required this.api,
    required this.likelihood,
  });
  final String opportunityId;
  final ApiClient api;

  /// Already known by the caller before this section's own fetch resolves --
  /// passed in so the accent bar/header can render immediately instead of
  /// waiting on the async load, and so the sheet's "why" visually ties back
  /// to the "should I go" badge shown higher up using the same color.
  final CustomerLikelihood likelihood;

  @override
  State<_ExplainSection> createState() => _ExplainSectionState();
}

class _ExplainSectionState extends State<_ExplainSection> {
  bool _loading = true;
  Map<String, dynamic>? _detail;
  String? _error;

  @override
  void initState() {
    super.initState();
    // Load immediately -- the driver already tapped the card to see this detail
    // sheet, an extra "Varför visas detta?" tap just to reveal the reasoning
    // that's the whole point of opening it was a redundant step, not a real gate.
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final detail = await widget.api.opportunityDetail(widget.opportunityId);
      if (!mounted) return;
      setState(() => _detail = detail);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'Kunde inte hämta detaljer.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Color get _accentColor => switch (widget.likelihood) {
    CustomerLikelihood.high => TbColors.likelihoodHigh,
    CustomerLikelihood.medium => TbColors.likelihoodMedium,
    CustomerLikelihood.low => TbColors.likelihoodLow,
  };

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (_loading) {
      body = const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: SizedBox(
          height: 20,
          width: 20,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      );
    } else if (_error != null) {
      body = Text(
        _error!,
        style: TextStyle(color: Colors.red.shade700, fontSize: 13),
      );
    } else {
      final opp = _detail?['opportunity'] as Map?;
      final sourceEvents = (_detail?['source_events'] as List?) ?? const [];
      if (opp == null) {
        body = const Text(
          'Ingen ytterligare information tillgänglig.',
          style: TextStyle(fontSize: 13),
        );
      } else {
        final severityTier = opp['severity_tier']?.toString();
        body = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _ExplainRow(
              label: 'Bedömning',
              value:
                  severityTierLabels[severityTier] ?? severityTier ?? 'Okänd',
            ),
            // Säkerhet/confidence-raden borttagen på användarens begäran --
            // "tydligt i källdatan"-texten upplevdes som brus, inte som
            // hjälpsam information. Kortets "osäker"-badge (confidence ==
            // 'low') finns kvar oförändrad -- det är fortfarande värt att
            // flagga en gissning inline på kortet, bara inte förklara den
            // här med en egen rad.
            // Poäng flyttat till header-raden ovan -- ingen anledning att visa
            // samma siffra två gånger i samma blad.
            if (opp['expired_reason'] != null) ...[
              const SizedBox(height: 10),
              _ExplainRow(
                label: 'Status',
                value: opp['expired_reason'].toString(),
              ),
            ],
            // Only a plain-language weather summary survives here -- it's the
            // one piece of context not shown anywhere else when a weather
            // bonus applied. Visually subordinate to the two facts above
            // (smaller, below a divider) since it's genuinely the least
            // critical line in this section.
            for (final se in sourceEvents.cast<Map>())
              if (se['source'] == 'smhi')
                if (_weatherSummary(se['raw'] as Map?) case final desc
                    when desc != '—') ...[
                  Divider(color: TbColors.sand, height: 24),
                  Text(
                    desc,
                    style: TextStyle(fontSize: 13, color: TbColors.muted),
                  ),
                ],
          ],
        );
      }
    }

    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: TbColors.sand),
      ),
      clipBehavior: Clip.antiAlias,
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(width: 4, color: _accentColor),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Varför visas detta?',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: TbColors.ink,
                      ),
                    ),
                    const SizedBox(height: 10),
                    body,
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// SMHI's raw fields (see worker/src/smhi.js summarize()) aren't prose like
/// Trafiklab/Trafikverket's, so render a short human sentence instead of
/// falling back to a missing 'description'/'header' key.
String _weatherSummary(Map? raw) {
  if (raw == null) return '—';
  final point = raw['point']?.toString();
  final temp = (raw['temperatureC'] as num?)?.round();
  final bits = <String>[];
  if (temp != null) bits.add('$temp°C');
  final precip = (raw['precipitationMmPerH'] as num?) ?? 0;
  final precipProb = (raw['precipitationProbabilityPct'] as num?) ?? 0;
  if (precip >= 1.0 && precipProb >= 40) {
    final frozen = (raw['frozenPrecipitationProbabilityPct'] as num?) ?? 0;
    bits.add(frozen >= 40 ? 'snöfall' : 'regn');
  }
  final gust = (raw['windGustMs'] as num?) ?? (raw['windSpeedMs'] as num?) ?? 0;
  if (gust >= 12) bits.add('hård vind (${gust.round()} m/s)');
  final thunder = (raw['thunderstormProbabilityPct'] as num?) ?? 0;
  if (thunder >= 30) bits.add('åskrisk $thunder%');
  final where = point != null ? '$point: ' : '';
  return bits.isEmpty
      ? '${where}inga varningsvärda förhållanden'
      : '$where${bits.join(', ')}';
}

/// Compact icon+label chip for the detail sheet's header stat row (date/time,
/// score, active/ended) -- deliberately small and un-colored so it reads as
/// metadata, not another badge competing with the likelihood pill above it.
class _DetailStat extends StatelessWidget {
  const _DetailStat({required this.icon, required this.label});
  final Widget icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.grey.shade100,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(width: 13, height: 13, child: icon),
          const SizedBox(width: 4),
          Flexible(
            child: Text(
              label,
              overflow: TextOverflow.ellipsis,
              maxLines: 1,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: Colors.grey.shade800,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// A single "why" fact -- a small uppercase eyebrow label above a large,
/// high-contrast value line, instead of one small inline "label: value" --
/// brings this up to the same glanceable size as the sheet's main hint text
/// above it, since this used to be the smallest, lowest-contrast text in the
/// whole sheet despite being the "why should I trust this" answer.
class _ExplainRow extends StatelessWidget {
  const _ExplainRow({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label.toUpperCase(),
          style: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.4,
            color: TbColors.muted,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: TbColors.ink,
            height: 1.3,
          ),
        ),
      ],
    );
  }
}

/// Icke-blockerande banner när företaget saknar åtkomst. Rubrik och text följer
/// serverns skäl (fleet/access.py): en ny provkund som inte kopplat någon
/// telefon än ska få veta vad nästa steg är, inte att provet "gått ut".
class _EntitlementBanner extends StatelessWidget {
  const _EntitlementBanner({this.reason, this.message, this.onOpenSettings});

  final String? reason;
  final String? message;
  final VoidCallback? onOpenSettings;

  (String, String, IconData, Color) get _copy => switch (reason) {
    'trial_not_started' => (
      'Välkommen! Ett steg kvar',
      'Lägg till en bil och ge föraren en kod under Inställningar. '
          'Provperioden på 14 dagar startar när den första telefonen kopplas.',
      Icons.flag_outlined,
      TbColors.live,
    ),
    'company_suspended' || 'account_blocked' => (
      'Kontot är avstängt',
      message ?? 'Kontakta TaxiTips support.',
      Icons.block,
      TbColors.danger,
    ),
    'trial_ended' => (
      'Provperioden är slut',
      'Nya tips visas inte just nu. Er kontaktperson på TaxiTips hjälper er '
          'att fortsätta — det är inte samma sak som "inga störningar just nu".',
      Icons.info_outline,
      TbColors.taxiDeep,
    ),
    _ => (
      'Tipsen är pausade',
      '${message ?? 'Företagets abonnemang är inte aktivt.'} Det är inte samma '
          'sak som "inga störningar just nu".',
      Icons.info_outline,
      TbColors.taxiDeep,
    ),
  };

  @override
  Widget build(BuildContext context) {
    final (title, body, icon, color) = _copy;
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 10, 16, 0),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: TbColors.sand,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color, width: 1.5),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 15,
                    color: TbColors.ink,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  body,
                  style: const TextStyle(
                    fontSize: 13,
                    height: 1.35,
                    fontWeight: FontWeight.w600,
                    color: TbColors.muted,
                  ),
                ),
                if (onOpenSettings != null) ...[
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: onOpenSettings,
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      alignment: Alignment.centerLeft,
                    ),
                    child: Text(
                      reason == 'trial_not_started'
                          ? 'Lägg till bil och förare'
                          : 'Se inställningar',
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Plus och minus i en stapel, samma vita stil som kartans andra knappar.
class _ZoomButtons extends StatelessWidget {
  const _ZoomButtons({required this.onZoomIn, required this.onZoomOut});

  final VoidCallback onZoomIn;
  final VoidCallback onZoomOut;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      elevation: 4,
      borderRadius: BorderRadius.circular(14),
      clipBehavior: Clip.antiAlias,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            tooltip: 'Zooma in',
            onPressed: onZoomIn,
            iconSize: 26,
            color: TbColors.ink,
            constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
            icon: const Icon(Icons.add),
          ),
          Container(width: 28, height: 1, color: TbColors.line),
          IconButton(
            tooltip: 'Zooma ut',
            onPressed: onZoomOut,
            iconSize: 26,
            color: TbColors.ink,
            constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
            icon: const Icon(Icons.remove),
          ),
        ],
      ),
    );
  }
}

class _ShortcutChip extends StatelessWidget {
  const _ShortcutChip({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ActionChip(
        avatar: Icon(icon, size: 18, color: TbColors.midnatt),
        label: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              label,
              style: const TextStyle(
                fontWeight: FontWeight.w700,
                color: TbColors.midnatt,
              ),
            ),
            const Icon(
              Icons.chevron_right_rounded,
              size: 18,
              color: TbColors.midnatt,
            ),
          ],
        ),
        backgroundColor: TbColors.ljusgra,
        side: const BorderSide(color: TbColors.line),
        onPressed: onTap,
      ),
    );
  }
}

/// En kort rad överst på kartan när något behöver göras eller inte fungerar.
class _Notice extends StatelessWidget {
  const _Notice({
    required this.icon,
    required this.text,
    this.action,
    this.onAction,
    this.danger = false,
  });

  final IconData icon;
  final String text;
  final String? action;
  final VoidCallback? onAction;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final color = danger ? TbColors.danger : TbColors.ink;
    return Material(
      color: TbColors.vit,
      elevation: 3,
      shadowColor: Colors.black26,
      borderRadius: BorderRadius.circular(14),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 6, 6, 6),
        child: Row(
          children: [
            Icon(icon, size: 20, color: color),
            const SizedBox(width: 10),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  text,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: color,
                  ),
                ),
              ),
            ),
            if (action != null)
              TextButton(
                onPressed: onAction,
                child: Text(
                  action!,
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
