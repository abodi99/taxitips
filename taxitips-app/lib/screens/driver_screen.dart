import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../push_service.dart';
import '../severity_labels.dart';
import '../theme.dart';
import '../widgets/alert_feedback_bar.dart';
import '../widgets/brand_icons.dart';
import '../widgets/hotspot_map.dart';
import '../widgets/likelihood_badge.dart';
import '../widgets/smart_alert_card.dart';

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

class _DriverScreenState extends State<DriverScreen> {
  // Anti-overload cap: how many live signals to show at once when no explicit
  // filter narrows the list. Tunable here after live driving -- don't hardcode
  // inline where it's easy to lose track of. Signals are sorted by severity/score
  // (see _sortSignals) before this cap is applied, so the cap always drops the
  // weakest signals, not an arbitrary tail.
  static const int _maxVisibleSignals = 10;

  Map<String, dynamic>? _data;
  String? _error;
  String? _status;
  Timer? _timer;
  bool _claiming = false;
  bool _refreshing = false;
  bool? _entitled; // null = okänt/inte kollat än, kör inte spärr förrän vi vet.
  // Av som default: med dagens data (många planerade ersättningsarbeten
  // korrekt märkta low) ger "Bara hög prio" en tom lista som ser ut som
  // "inga störningar". Föraren slår på filtret när hen vill korta ner.
  // Sparad preferens i SharedPreferences vinner fortfarande.
  bool _highOnly = false;
  bool _nearMe = false;

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

  String _sourceFilter = 'all'; // all | transit | road
  // Per-signal markers by default. The place-aggregated view depends on
  // placeStats, which is built from taxi.places -- a legacy field that is
  // always empty for real opportunities, so the default map rendered
  // literally nothing while 121 signals had perfectly good coordinates.
  // Showing where each disruption actually is also answers the driver's
  // real question ("var kör jag?") better than a count bubble per town.
  bool _mapShowsPerOpportunity = true;
  String? _region; // null = alla län/regioner
  String? _place; // null = alla
  double? _userLat;
  double? _userLon;
  static const _nearKm = 25.0;

  // Filter choices persist locally so a driver doesn't have to re-set them
  // every time they open the app -- "Bara hög prio" is exactly the kind of
  // thing you turn on once and expect to stay on, not something to
  // reconfigure at every stoplight. Not synced to the account/device row
  // (this is a per-phone UI preference, not a server-side setting) --
  // plain SharedPreferences, same pattern already used elsewhere in this
  // client (see api_client.dart's saveDevice/saveSession).
  static const _prefsHighOnlyKey = 'tb_filter_high_only';
  static const _prefsNearMeKey = 'tb_filter_near_me';
  static const _prefsSourceKey = 'tb_filter_source';
  static const _prefsHiddenTiersKey = 'tb_filter_hidden_tiers';
  static const _prefsRegionKey = 'tb_filter_region';
  static const _prefsPlaceKey = 'tb_filter_place';

  static const _regionLabels = <String, String>{
    'skane': 'Skåne',
    'sl': 'Stockholm',
    'vt': 'Västra Götaland',
    'ul': 'Uppsala',
    'otraf': 'Östergötland',
    'klt': 'Kalmar',
    'varm': 'Värmland',
    'dt': 'Dalarna',
    'xt': 'Gävleborg',
    'vastmanland': 'Västmanland',
    'krono': 'Kronoberg',
    'jlt': 'Jönköping',
    'orebro': 'Örebro',
    'blekinge': 'Blekinge',
    'gotland': 'Gotland',
  };

  Future<void> _loadSavedFilters() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final highOnly = prefs.getBool(_prefsHighOnlyKey);
      final nearMe = prefs.getBool(_prefsNearMeKey);
      final source = prefs.getString(_prefsSourceKey);
      final hiddenTiers = prefs.getStringList(_prefsHiddenTiersKey);
      final region = prefs.getString(_prefsRegionKey);
      final place = prefs.getString(_prefsPlaceKey);
      if (!mounted) return;
      setState(() {
        if (highOnly != null) _highOnly = highOnly;
        if (source != null) _sourceFilter = source;
        if (hiddenTiers != null) _hiddenTiers = hiddenTiers.toSet();
        _region = region;
        _place = place;
      });
      // "Nära mig" needs a real GPS fix to actually filter anything
      // (_geoFilter no-ops until _userLat/_userLon are set) -- re-run the
      // real permission+location flow rather than just restoring the flag,
      // so a saved "on" choice takes effect immediately instead of silently
      // doing nothing until the driver happens to reopen the filter sheet.
      if (nearMe == true) {
        await _toggleNearMe(true);
      }
    } catch (_) {
      // Best-effort -- a driver seeing default filters once is fine, an
      // exception here should never block the app from loading signals.
    }
  }

  Future<void> _saveFilters() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(_prefsHighOnlyKey, _highOnly);
      await prefs.setBool(_prefsNearMeKey, _nearMe);
      await prefs.setString(_prefsSourceKey, _sourceFilter);
      await prefs.setStringList(_prefsHiddenTiersKey, _hiddenTiers.toList());
      if (_region == null) {
        await prefs.remove(_prefsRegionKey);
      } else {
        await prefs.setString(_prefsRegionKey, _region!);
      }
      if (_place == null) {
        await prefs.remove(_prefsPlaceKey);
      } else {
        await prefs.setString(_prefsPlaceKey, _place!);
      }
    } catch (_) {
      // Non-fatal -- losing a saved preference isn't worth surfacing an
      // error over.
    }
  }

  @override
  void initState() {
    super.initState();
    _loadSavedFilters();
    _bootstrap();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    if (widget.inviteToken != null && widget.inviteToken!.isNotEmpty) {
      setState(() => _claiming = true);
      try {
        await widget.api.claimInvite(widget.inviteToken!);
        await registerForPush(widget.api);
        setState(() => _status = 'Telefon kopplad');
      } catch (e) {
        setState(() => _error = _friendly(e));
      } finally {
        if (mounted) setState(() => _claiming = false);
      }
    } else if (widget.api.deviceToken != null) {
      await registerForPush(widget.api);
    }
    await _updateCurrentPosition();
    await _load();
    _timer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => _load(silent: true),
    );
  }

  Future<void> _updateCurrentPosition() async {
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm == LocationPermission.denied ||
          perm == LocationPermission.deniedForever) {
        return;
      }
      final pos = await Geolocator.getCurrentPosition();
      if (!mounted) return;
      setState(() {
        _userLat = pos.latitude;
        _userLon = pos.longitude;
      });
    } catch (_) {
      // Location is an enhancement; the feed still works without a fix.
    }
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

  Future<void> _load({bool silent = false}) async {
    if (!silent && mounted) setState(() => _refreshing = true);
    try {
      final results = await Future.wait([
        widget.api.taxi(
          demo: widget.demo,
          userLat: _userLat,
          userLon: _userLon,
        ),
        _checkEntitlement(),
      ]);
      final data = results[0] as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _data = data;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _refreshing = false);
    }
  }

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
      setState(() => _entitled = result['entitled'] == true);
    } catch (e) {
      // Nätverksfel etc — behåll senast kända status hellre än att larma i onödan.
      debugPrint('DriverScreen[_checkEntitlement] error: $e');
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

  List<Map<String, dynamic>> get _rawWeek => _asMaps(_data?['week']);

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

  /// Place + near-me filters (not kind / high-only).
  List<Map<String, dynamic>> _geoFilter(List<Map<String, dynamic>> list) {
    var out = list;
    if (_region != null) {
      // Järnväg skrivs alltid som region="rail" (saknar länsfält hos
      // Trafikverket). Ett länsfilter som krävt exakt match hade dolt
      // varje tågtips -- samma fälla som invariant 14 i AGENTS.md för
      // notiser. Feedet har redan kapats till 150 km, så rail i svaret
      // hör hemma i vald marknad.
      out = out
          .where((a) {
            final r = a['region']?.toString();
            return r == _region || r == 'rail';
          })
          .toList();
    }
    if (_place != null) {
      out = out.where((a) {
        final places = ((a['taxi'] as Map?)?['places'] as List?) ?? [];
        return places.map((e) => e.toString()).contains(_place);
      }).toList();
    }
    if (_nearMe && _userLat != null && _userLon != null) {
      final stats = _asMaps(_data?['placeStats']);
      out = out.where((a) => _alertNear(a, stats)).toList();
    }
    return out;
  }

  /// Väg/kollektivtrafik-filter — gäller bara live-signaler (kind: 'road'/'transit'),
  /// ett no-op för evenemang som saknar 'kind'.
  List<Map<String, dynamic>> _sourceFilterList(
    List<Map<String, dynamic>> list,
  ) {
    var out = list;
    if (_sourceFilter != 'all') {
      out = out.where((a) => a['kind'] == _sourceFilter).toList();
    }
    if (_hiddenTiers.isNotEmpty) {
      out = out
          .where((a) => !_hiddenTiers.contains(a['severity_tier']?.toString()))
          .toList();
    }
    return out;
  }

  // "Bara hög prio" means "severe disruption", NOT "reachable from here" --
  // those are different questions, and the backend now keeps them apart:
  // worth_it_score no longer subtracts distance, so it answers only "how
  // strong is this signal". Distance is shown on the card and left to the
  // driver, who knows their own shift, traffic and willingness to drive
  // better than any formula does.
  //
  // Road tiers are deliberately excluded -- an accident/closure delays people
  // already in a car, it doesn't strand pedestrians who'd need a taxi, so it's
  // never "high priority" here regardless of how bad the road situation reads.
  //
  // Ersättningstrafik (has_alternative) räknas som low på backend -- annars
  // fyllde filtret listan med planerade ombyggnader där bussen redan går.
  /// "Hög prio" must mean the same thing the card's badge means, or the
  /// screen contradicts itself -- both ask: how strong is this signal?
  bool _isHighSeverity(Map<String, dynamic> a) {
    final severityTier = a['severity_tier']?.toString();
    if (severityTier == null) {
      return (a['taxi'] as Map?)?['level'] == 'high';
    }
    return likelihoodForAlert(a) == CustomerLikelihood.high;
  }

  DateTime? _signalTime(Map<String, dynamic> a) {
    final raw = a['start_time'] ?? a['computed_at'];
    if (raw is String && raw.isNotEmpty) return DateTime.tryParse(raw);
    if (raw is num) {
      return DateTime.fromMillisecondsSinceEpoch(raw.toInt());
    }
    return null;
  }

  void _sortSignals(List<Map<String, dynamic>> list) {
    list.sort((a, b) {
      // Active disruptions always rank above yesterday's ended ones,
      // regardless of score -- "what to act on now" beats "what happened".
      final aActive = a['is_active'] != false;
      final bActive = b['is_active'] != false;
      if (aActive != bActive) return aActive ? -1 : 1;
      // Nyast först inom varje sektion -- föraren vill se vad som just
      // hänt, inte det äldsta högpoängstipset från i natt.
      final ta = _signalTime(a);
      final tb = _signalTime(b);
      if (ta != null && tb != null && ta != tb) {
        return tb.compareTo(ta);
      }
      if (ta != null && tb == null) return -1;
      if (ta == null && tb != null) return 1;
      // Same time: stronger score first, then place name.
      final sa = ((a['worth_it_score'] as num?) ?? 0);
      final sb = ((b['worth_it_score'] as num?) ?? 0);
      if (sa != sb) return sb.compareTo(sa);
      return _placeName(a).compareTo(_placeName(b));
    });
  }

  List<Map<String, dynamic>> get _trafficSignals {
    var list = _sourceFilterList(_geoFilter(_rawActive));
    if (_highOnly) {
      list = list.where(_isHighSeverity).toList();
    }
    _sortSignals(list);
    return list;
  }

  /// Kartmarkörer: samma ort/källa/nära-mig-filter som listan, men INTE
  /// "Bara hög prio". Annars töms kartan när ersättningstrafik korrekt
  /// räknas som low — föraren ser ingen plats att köra till trots att
  /// det finns koordinatsatta tips. Ringfärgen på markören visar prio.
  List<Map<String, dynamic>> get _mapOpportunities {
    final list = _sourceFilterList(_geoFilter(_rawActive));
    _sortSignals(list);
    return list;
  }

  List<Map<String, dynamic>> get _trafficSignalsVisible {
    final list = _trafficSignals;
    if (list.length > _maxVisibleSignals) {
      return list.take(_maxVisibleSignals).toList();
    }
    return list;
  }

  // _trafficSignalsVisible is sorted active-first (see _sortSignals) but is
  // one flat list -- split it for display so "Nu — kör hit" only ever shows
  // things worth driving to right now, and yesterday's already-ended
  // disruptions get their own clearly-labeled "Senaste dygnet" section
  // instead of silently blending into the actionable list.
  List<Map<String, dynamic>> get _activeSignalsVisible =>
      _trafficSignalsVisible.where((a) => a['is_active'] != false).toList();

  List<Map<String, dynamic>> get _endedSignalsVisible =>
      _trafficSignalsVisible.where((a) => a['is_active'] == false).toList();

  List<Map<String, dynamic>> get _weekSignals {
    var list = _sourceFilterList(_geoFilter(_rawWeek));
    if (_highOnly) {
      list = list.where(_isHighSeverity).toList();
    }
    _sortSignals(list);
    return list.take(12).toList();
  }

  List<Map<String, dynamic>> get _signals => _trafficSignalsVisible;

  bool get _filtersActive =>
      _highOnly ||
      _nearMe ||
      _region != null ||
      _place != null ||
      _sourceFilter != 'all' ||
      _hiddenTiers.isNotEmpty;

  String get _filterSummary {
    final bits = <String>[];
    if (_sourceFilter == 'transit') bits.add('Bara kollektivtrafik');
    if (_sourceFilter == 'road') bits.add('Bara vägtrafik');
    if (_highOnly) bits.add('Hög prio');
    if (_nearMe) bits.add('Nära dig');
    if (_region != null) bits.add(_regionLabels[_region] ?? _region!);
    if (_place != null) bits.add(_place!);
    if (_hiddenTiers.isNotEmpty) bits.add('${_hiddenTiers.length} typ dold');
    if (bits.isEmpty) return 'Alla signaler';
    return bits.join(' · ');
  }

  // Resets to "visa allt i marknaden" -- inte till hög-prio-filtret.
  // Hög-prio som default tömde listan när ersättningstrafik korrekt
  // räknades som low, och såg ut som att pipelinen var död.
  void _clearFilters() {
    setState(() {
      _place = null;
      _region = null;
      _highOnly = false;
      _nearMe = false;
      _sourceFilter = 'all';
      _hiddenTiers = {};
      _status = null;
    });
    _saveFilters();
  }

  Future<void> _openFilters() async {
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
              setState(fn);
              setModal(() {});
              _saveFilters();
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
                        const SizedBox(height: 12),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text(
                            'Bara hög prio',
                            style: TextStyle(fontWeight: FontWeight.w700),
                          ),
                          subtitle: const Text(
                            'Bara allvarliga störningar (oavsett avstånd)',
                          ),
                          value: _highOnly,
                          onChanged: (v) => apply(() => _highOnly = v),
                        ),
                        const SizedBox(height: 12),
                        const Text(
                          'Län / region',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        DropdownButtonFormField<String>(
                          initialValue: _region ?? '__all__',
                          isExpanded: true,
                          decoration: const InputDecoration(
                            isDense: true,
                            border: OutlineInputBorder(),
                          ),
                          items: [
                            const DropdownMenuItem(
                              value: '__all__',
                              child: Text('Hela Sverige'),
                            ),
                            for (final region in _availableRegions)
                              DropdownMenuItem(
                                value: region,
                                child: Text(_regionLabels[region] ?? region),
                              ),
                          ],
                          onChanged: (value) => apply(
                            () => _region = value == '__all__' ? null : value,
                          ),
                        ),
                        const SizedBox(height: 12),
                        const Text(
                          'Stad',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        DropdownButtonFormField<String>(
                          initialValue: _place ?? '__all__',
                          isExpanded: true,
                          decoration: const InputDecoration(
                            isDense: true,
                            border: OutlineInputBorder(),
                          ),
                          items: [
                            const DropdownMenuItem(
                              value: '__all__',
                              child: Text('Alla städer'),
                            ),
                            for (final city in _availableCities)
                              DropdownMenuItem(value: city, child: Text(city)),
                          ],
                          onChanged: (value) => apply(
                            () => _place = value == '__all__' ? null : value,
                          ),
                        ),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
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
                        const SizedBox(height: 8),
                        const Text(
                          'Källa',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 8,
                          children: [
                            for (final opt in const [
                              ('all', 'Alla källor'),
                              ('transit', 'Kollektivtrafik'),
                              ('road', 'Vägtrafik'),
                            ])
                              ChoiceChip(
                                label: Text(
                                  opt.$2,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                selected: _sourceFilter == opt.$1,
                                selectedColor: TbColors.taxi,
                                onSelected: (_) =>
                                    apply(() => _sourceFilter = opt.$1),
                              ),
                          ],
                        ),
                        // Per-type control only matters once "hög prio" is off --
                        // with it on, the tier set is already narrowed to the ones
                        // worth driving to, and offering to hide those too would
                        // just be a way to end up with an empty screen.
                        if (!_highOnly) ...[
                          const SizedBox(height: 16),
                          const Text(
                            'Typ av händelse',
                            style: TextStyle(fontWeight: FontWeight.w700),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            'Avmarkera det du inte vill se. Sparas till nästa gång.',
                            style: TextStyle(
                              fontSize: 13,
                              color: Colors.grey.shade600,
                            ),
                          ),
                          const SizedBox(height: 8),
                          for (final tier in _filterableTiers)
                            CheckboxListTile(
                              contentPadding: EdgeInsets.zero,
                              dense: true,
                              controlAffinity: ListTileControlAffinity.leading,
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
                        const SizedBox(height: 16),
                        Row(
                          children: [
                            TextButton(
                              onPressed: () {
                                _clearFilters();
                                setModal(() {});
                              },
                              child: const Text('Nollställ'),
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
  }

  // No scheduled-event data source exists yet (api_client.dart's taxi() always
  // returns events: []) -- HotspotMap still accepts an events list for when
  // that's built, so keep passing an empty one rather than changing its API.
  List<Map<String, dynamic>> get _mapEvents => const [];

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
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm == LocationPermission.denied ||
          perm == LocationPermission.deniedForever) {
        setState(() {
          _nearMe = false;
          _error = 'GPS-tillstånd saknas';
        });
        _saveFilters();
        return;
      }
      final pos = await Geolocator.getCurrentPosition();
      if (!mounted) return;
      setState(() {
        _nearMe = true;
        _userLat = pos.latitude;
        _userLon = pos.longitude;
        _status = 'Nära dig (25 km)';
        _error = null;
      });
      _saveFilters();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _nearMe = false;
        _error = 'Kunde inte hämta position';
      });
      _saveFilters();
    }
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

  List<String> get _availableRegions {
    final regions = <String>{..._regionLabels.keys};
    for (final alert in _rawActive) {
      final region = alert['region']?.toString();
      if (region != null && region.isNotEmpty) regions.add(region);
    }
    return regions.toList()..sort(
      (a, b) => (_regionLabels[a] ?? a).compareTo(_regionLabels[b] ?? b),
    );
  }

  List<String> get _availableCities {
    final cities = <String>{};
    for (final alert in _rawActive) {
      if (_region != null && alert['region']?.toString() != _region) continue;
      final places = ((alert['taxi'] as Map?)?['places'] as List?) ?? [];
      cities.addAll(
        places
            .map((place) => place.toString().trim())
            .where((place) => place.isNotEmpty),
      );
    }
    return cities.toList()..sort();
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

    // Räkna från samma signaler som listan (före ort-filter).
    var list = _rawActive;
    if (_highOnly) {
      list = list.where(_isHighSeverity).toList();
    }
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
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: TbColors.foam,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
            child: SingleChildScrollView(
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
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        (a['kind'] ?? a['sourceKind']) == 'road'
                            ? 'VÄG'
                            : 'KOLLEKTIV',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 0.6,
                          color: Colors.grey.shade700,
                        ),
                      ),
                      // Restates the same likelihood the card already showed
                      // -- the sheet shouldn't require remembering it from
                      // the list.
                      LikelihoodBadge(
                        likelihood: likelihood,
                        distanceKm: (a['distance_km'] as num?)?.toDouble(),
                        fontSize: 13,
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _placeName(a),
                    style: const TextStyle(
                      fontFamily: kDisplayFont,
                      fontSize: 28,
                      fontWeight: FontWeight.w700,
                      height: 1.1,
                    ),
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
                          child: Text(
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
                    AlertFeedbackBar(
                      api: widget.api,
                      opportunityId: a['id'].toString(),
                    ),
                    const SizedBox(height: 16),
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
  }

  @override
  Widget build(BuildContext context) {
    final places = _places;
    if (_place != null && !places.any((p) => p['name'] == _place)) {
      // Ort finns inte i aktuellt filter — nollställ utan att störa setState mid-build.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted &&
            _place != null &&
            !_places.any((p) => p['name'] == _place)) {
          setState(() => _place = null);
        }
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
                    child: HotspotMap(
                      placeStats: _asMaps(_data?['placeStats']),
                      events: _mapEvents,
                      userLat: _userLat,
                      userLon: _userLon,
                      selectedPlace: _place,
                      highOnly: false,
                      perOpportunity: _mapShowsPerOpportunity,
                      opportunities: _mapOpportunities,
                      onSelectPlace: (name) => setState(() {
                        _place = _place == name ? null : name;
                      }),
                      onSelectOpportunity: (o) => _openAlertDetail(o),
                    ),
                  ),

                  // 2. Toppmeny (svävande ovanpå kartan)
                  Positioned(
                    top: 0,
                    left: 0,
                    right: 0,
                    child: SafeArea(
                      bottom: false,
                      child: Column(
                        children: [
                          Container(
                            margin: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                            decoration: BoxDecoration(
                              color: TbColors.asphalt.withValues(alpha: 0.95),
                              borderRadius: BorderRadius.circular(16),
                              boxShadow: const [
                                BoxShadow(
                                  color: Colors.black26,
                                  blurRadius: 10,
                                  offset: Offset(0, 4),
                                ),
                              ],
                            ),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 8,
                            ),
                            child: Row(
                              children: [
                                if (widget.onBack != null)
                                  IconButton(
                                    onPressed: widget.onBack,
                                    icon: const Icon(
                                      Icons.arrow_back,
                                      color: TbColors.foam,
                                    ),
                                  )
                                else
                                  const SizedBox(width: 8),
                                const Text(
                                  'Taxi Tips',
                                  style: TextStyle(
                                    fontSize: 20,
                                    fontWeight: FontWeight.w700,
                                    color: TbColors.foam,
                                    letterSpacing: -0.2,
                                  ),
                                ),
                                const SizedBox(width: 10),
                                _LivePill(
                                  live: live,
                                  demo: widget.demo,
                                  time: _clock(_data?['updatedAt']),
                                ),
                                const Spacer(),
                                if (widget.onOpenSettings != null)
                                  IconButton(
                                    tooltip: 'Inställningar',
                                    onPressed: widget.onOpenSettings,
                                    icon: const Icon(
                                      Icons.settings_outlined,
                                      color: TbColors.foam,
                                    ),
                                    style: IconButton.styleFrom(
                                      backgroundColor: Colors.white.withValues(
                                        alpha: 0.08,
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                          if (_entitled == false)
                            Padding(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 16,
                              ),
                              child: _EntitlementBanner(
                                onOpenSettings: widget.onOpenSettings,
                              ),
                            ),
                          if (_status != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 4),
                              child: Text(
                                _status!,
                                style: const TextStyle(
                                  color: TbColors.live,
                                  fontWeight: FontWeight.w900,
                                  shadows: [
                                    Shadow(
                                      blurRadius: 3,
                                      color: Colors.black45,
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          if (_error != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 4),
                              child: Text(
                                _error!,
                                style: const TextStyle(
                                  color: TbColors.danger,
                                  fontWeight: FontWeight.w900,
                                  shadows: [
                                    Shadow(
                                      blurRadius: 3,
                                      color: Colors.black45,
                                    ),
                                  ],
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),

                  // 3. FAB för kartkontroller
                  Positioned(
                    right: 16,
                    bottom: MediaQuery.of(context).size.height * 0.42 + 16,
                    child: SafeArea(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          SizedBox(
                            width: 52,
                            height: 52,
                            child: IconButton(
                              tooltip: _mapShowsPerOpportunity
                                  ? 'Visa orter'
                                  : 'Visa signaler + avstånd',
                              onPressed: () => setState(() {
                                _mapShowsPerOpportunity =
                                    !_mapShowsPerOpportunity;
                              }),
                              icon: Icon(
                                _mapShowsPerOpportunity
                                    ? Icons.blur_on
                                    : Icons.pin_drop_outlined,
                                size: 24,
                                color: TbColors.ink,
                              ),
                              style: IconButton.styleFrom(
                                backgroundColor: Colors.white,
                                shape: const CircleBorder(),
                                elevation: 4,
                                shadowColor: Colors.black45,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),

                  // 4. Bottenmeny (Sheet)
                  DraggableScrollableSheet(
                    initialChildSize: 0.42,
                    minChildSize: 0.15,
                    maxChildSize: 0.9,
                    snap: true,
                    snapSizes: const [0.15, 0.42, 0.9],
                    builder: (context, scrollController) {
                      return Container(
                        decoration: const BoxDecoration(
                          color: TbColors.foam,
                          borderRadius: BorderRadius.vertical(
                            top: Radius.circular(24),
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black26,
                              blurRadius: 16,
                              offset: Offset(0, -4),
                            ),
                          ],
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            // Drag handle
                            Center(
                              child: Container(
                                margin: const EdgeInsets.only(
                                  top: 10,
                                  bottom: 4,
                                ),
                                width: 40,
                                height: 4,
                                decoration: BoxDecoration(
                                  color: Colors.grey.shade400,
                                  borderRadius: BorderRadius.circular(2),
                                ),
                              ),
                            ),
                            // Header-del (rullar inte med listan inuti)
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      const Expanded(
                                        child: Text(
                                          'Var behövs taxi?',
                                          style: TextStyle(
                                            fontFamily: kDisplayFont,
                                            fontSize: 26,
                                            fontWeight: FontWeight.w700,
                                            height: 1.1,
                                            color: TbColors.ink,
                                          ),
                                        ),
                                      ),
                                      Padding(
                                        padding: const EdgeInsets.only(top: 2),
                                        child: Row(
                                          children: [
                                            SizedBox(
                                              width: 44,
                                              height: 44,
                                              child: IconButton(
                                                tooltip: 'Uppdatera',
                                                onPressed: _refreshing
                                                    ? null
                                                    : () => _load(),
                                                padding: EdgeInsets.zero,
                                                icon: _refreshing
                                                    ? const SizedBox(
                                                        width: 20,
                                                        height: 20,
                                                        child:
                                                            CircularProgressIndicator(
                                                              strokeWidth: 2,
                                                            ),
                                                      )
                                                    : const Icon(
                                                        Icons.refresh,
                                                        size: 22,
                                                        color: TbColors.ink,
                                                      ),
                                                style: IconButton.styleFrom(
                                                  side: const BorderSide(
                                                    color: TbColors.line,
                                                  ),
                                                  shape: const CircleBorder(),
                                                ),
                                              ),
                                            ),
                                            const SizedBox(width: 8),
                                            OutlinedButton.icon(
                                              onPressed: _openFilters,
                                              icon: Badge(
                                                isLabelVisible: _filtersActive,
                                                smallSize: 8,
                                                backgroundColor: TbColors.taxi,
                                                child: BrandIcons.filter(
                                                  size: 18,
                                                  color: TbColors.midnatt,
                                                ),
                                              ),
                                              label: const Text('Filter'),
                                              style: OutlinedButton.styleFrom(
                                                foregroundColor: TbColors.ink,
                                                padding:
                                                    const EdgeInsets.symmetric(
                                                      horizontal: 12,
                                                    ),
                                                textStyle: const TextStyle(
                                                  fontSize: 15,
                                                  fontWeight: FontWeight.w700,
                                                ),
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 6),
                                  Row(
                                    children: [
                                      Icon(
                                        live
                                            ? Icons.circle
                                            : Icons.circle_outlined,
                                        size: 9,
                                        color: live
                                            ? TbColors.live
                                            : Colors.grey.shade400,
                                      ),
                                      const SizedBox(width: 6),
                                      Expanded(
                                        child: RichText(
                                          overflow: TextOverflow.ellipsis,
                                          text: TextSpan(
                                            style: TextStyle(
                                              fontSize: 14,
                                              fontWeight: FontWeight.w600,
                                              color: live
                                                  ? TbColors.live
                                                  : Colors.grey.shade600,
                                            ),
                                            children: [
                                              TextSpan(
                                                text: live
                                                    ? 'Live · ${_clock(_data?['updatedAt'])}'
                                                    : 'Ej live · ${_clock(_data?['updatedAt'])}',
                                              ),
                                              TextSpan(
                                                text: ' · $_filterSummary',
                                                style: TextStyle(
                                                  color: _filtersActive
                                                      ? TbColors.taxiDeep
                                                      : TbColors.muted,
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                                  if (_places.isNotEmpty) ...[
                                    const SizedBox(height: 10),
                                    SizedBox(
                                      height: 44,
                                      child: ListView(
                                        scrollDirection: Axis.horizontal,
                                        padding: EdgeInsets.zero,
                                        children: [
                                          _OrtChip(
                                            label: 'Alla',
                                            selected: _place == null,
                                            onTap: () =>
                                                setState(() => _place = null),
                                          ),
                                          for (final p in _places.take(12))
                                            Padding(
                                              padding: const EdgeInsets.only(
                                                left: 8,
                                              ),
                                              child: _OrtChip(
                                                label:
                                                    p['name']?.toString() ?? '',
                                                count: (p['count'] as num?)
                                                    ?.toInt(),
                                                hot: p['maxLevel'] == 'high',
                                                selected: _place == p['name'],
                                                onTap: () => setState(() {
                                                  final name = p['name']
                                                      ?.toString();
                                                  _place = _place == name
                                                      ? null
                                                      : name;
                                                }),
                                              ),
                                            ),
                                        ],
                                      ),
                                    ),
                                  ],
                                  const SizedBox(height: 8),
                                ],
                              ),
                            ),

                            // Rullbar lista inuti sheetet
                            Expanded(
                              child: RefreshIndicator(
                                color: TbColors.taxiDeep,
                                onRefresh: () => _load(),
                                child: _signals.isEmpty && _weekSignals.isEmpty
                                    ? ListView(
                                        controller: scrollController,
                                        physics:
                                            const AlwaysScrollableScrollPhysics(),
                                        padding: const EdgeInsets.all(40),
                                        children: [
                                          BrandIcons.taxi(
                                            size: 64,
                                            color: Colors.grey.shade300,
                                          ),
                                          const SizedBox(height: 12),
                                          Text(
                                            _highOnly
                                                ? 'Inga starka taxisignaler just nu.'
                                                : 'Inget i filtret.\\nÄndra typ, nära mig eller ort.',
                                            textAlign: TextAlign.center,
                                            style: TextStyle(
                                              fontSize: 17,
                                              height: 1.4,
                                              color: Colors.grey.shade700,
                                            ),
                                          ),
                                          if (_highOnly) ...[
                                            const SizedBox(height: 16),
                                            Center(
                                              child: FilledButton(
                                                onPressed: () {
                                                  setState(
                                                    () => _highOnly = false,
                                                  );
                                                  _saveFilters();
                                                  _openFilters();
                                                },
                                                child: const Text(
                                                  'Visa svagare signaler',
                                                ),
                                              ),
                                            ),
                                          ] else if (_filtersActive) ...[
                                            const SizedBox(height: 16),
                                            Center(
                                              child: FilledButton(
                                                onPressed: _clearFilters,
                                                child: const Text(
                                                  'Nollställ filter',
                                                ),
                                              ),
                                            ),
                                          ],
                                        ],
                                      )
                                    : ListView(
                                        controller: scrollController,
                                        physics:
                                            const AlwaysScrollableScrollPhysics(),
                                        padding: const EdgeInsets.fromLTRB(
                                          16,
                                          4,
                                          16,
                                          40,
                                        ),
                                        children: [
                                          // Sparade tips ligger ÖVER de
                                          // filtrerade listorna och ritas
                                          // aldrig genom något filter. Det
                                          // är hela poängen: ett tips som
                                          // föraren aktivt sparat ska inte
                                          // kunna gömmas av ett filter som
                                          // råkar ligga kvar sedan förra
                                          // passet.
                                          if (_favorites.isNotEmpty) ...[
                                            _SectionTitle(
                                              'Sparade (${_favorites.length})',
                                            ),
                                            for (final a in _favorites) ...[
                                              SmartAlertCard(
                                                alert: a,
                                                onTap: () =>
                                                    _openAlertDetail(a),
                                                onToggleFavorite: (v) =>
                                                    _toggleFavorite(a, v),
                                              ),
                                              const SizedBox(height: 10),
                                            ],
                                            const SizedBox(height: 6),
                                          ],
                                          if (_trafficSignalsVisible
                                              .isNotEmpty) ...[
                                            if (_activeSignalsVisible
                                                .isNotEmpty) ...[
                                              _SectionTitle(
                                                'Nu — kör hit (${_trafficSignals.length})',
                                              ),
                                              for (final a
                                                  in _activeSignalsVisible) ...[
                                                SmartAlertCard(
                                                  alert: a,
                                                  onTap: () =>
                                                      _openAlertDetail(a),
                                                  onToggleFavorite:
                                                      widget
                                                          .api
                                                          .supportsFavorites
                                                      ? (v) => _toggleFavorite(
                                                          a,
                                                          v,
                                                        )
                                                      : null,
                                                ),
                                                const SizedBox(height: 10),
                                              ],
                                            ],
                                            if (_endedSignalsVisible
                                                .isNotEmpty) ...[
                                              const _SectionTitle(
                                                'Senaste dygnet',
                                              ),
                                              for (final a
                                                  in _endedSignalsVisible) ...[
                                                SmartAlertCard(
                                                  alert: a,
                                                  onTap: () =>
                                                      _openAlertDetail(a),
                                                  onToggleFavorite:
                                                      widget
                                                          .api
                                                          .supportsFavorites
                                                      ? (v) => _toggleFavorite(
                                                          a,
                                                          v,
                                                        )
                                                      : null,
                                                ),
                                                const SizedBox(height: 10),
                                              ],
                                            ],
                                            if (_trafficSignals.length >
                                                _trafficSignalsVisible.length)
                                              Padding(
                                                padding: const EdgeInsets.only(
                                                  bottom: 10,
                                                ),
                                                child: Text(
                                                  '+${_trafficSignals.length - _trafficSignalsVisible.length} fler trafiksignaler — öppna Filter → Källa',
                                                  style: TextStyle(
                                                    fontSize: 13,
                                                    color: Colors.grey.shade700,
                                                    fontWeight: FontWeight.w600,
                                                  ),
                                                ),
                                              ),
                                          ],
                                          if (_weekSignals.isNotEmpty) ...[
                                            const SizedBox(height: 8),
                                            Theme(
                                              data: Theme.of(context).copyWith(
                                                dividerColor:
                                                    Colors.transparent,
                                              ),
                                              child: ExpansionTile(
                                                initiallyExpanded: false,
                                                tilePadding: EdgeInsets.zero,
                                                childrenPadding:
                                                    EdgeInsets.zero,
                                                title: const Text(
                                                  'Senaste veckan',
                                                  style: TextStyle(
                                                    fontSize: 18,
                                                    fontWeight: FontWeight.w700,
                                                  ),
                                                ),
                                                children: [
                                                  for (final a
                                                      in _weekSignals) ...[
                                                    SmartAlertCard(
                                                      alert: a,
                                                      onTap: () =>
                                                          _openAlertDetail(a),
                                                      onToggleFavorite:
                                                          widget
                                                              .api
                                                              .supportsFavorites
                                                          ? (v) =>
                                                                _toggleFavorite(
                                                                  a,
                                                                  v,
                                                                )
                                                          : null,
                                                    ),
                                                    const SizedBox(height: 10),
                                                  ],
                                                ],
                                              ),
                                            ),
                                          ],
                                        ],
                                      ),
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ],
              ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(0, 8, 0, 10),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 18,
          fontWeight: FontWeight.w700,
          color: Colors.grey.shade800,
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

/// Icke-blockerande banner som visas när bolagets provperiod/prenumeration
/// inte längre är aktiv. Signalerna töms redan tyst server-side i det läget
/// (get_smart_alerts), så det här ger föraren en förklaring i stället för
/// en tom skärm utan anledning.
class _EntitlementBanner extends StatelessWidget {
  const _EntitlementBanner({this.onOpenSettings});

  final VoidCallback? onOpenSettings;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 10, 16, 0),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: TbColors.sand,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: TbColors.taxiDeep, width: 1.5),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline, color: TbColors.taxiDeep),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Ditt företags provperiod har gått ut',
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 15,
                    color: TbColors.ink,
                  ),
                ),
                const SizedBox(height: 4),
                const Text(
                  'Prenumerationen är inte aktiv just nu, så nya taxisignaler visas inte förrän kontoret förnyar den.',
                  style: TextStyle(
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
                    child: const Text('Se inställningar'),
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

class _LivePill extends StatelessWidget {
  const _LivePill({required this.live, required this.demo, required this.time});

  final bool live;
  final bool demo;
  final String time;

  @override
  Widget build(BuildContext context) {
    final label = demo
        ? 'Demo'
        : live
        ? 'Live $time'
        : 'Offline';
    final color = demo
        ? TbColors.taxiDeep
        : live
        ? TbColors.live
        : Colors.grey;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: TbColors.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _OrtChip extends StatelessWidget {
  const _OrtChip({
    required this.label,
    required this.selected,
    required this.onTap,
    this.count,
    this.hot = false,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;
  final int? count;
  final bool hot;

  @override
  Widget build(BuildContext context) {
    final bg = selected
        ? (hot ? TbColors.signal : TbColors.taxi)
        : Colors.white;
    final fg = selected && hot ? Colors.white : TbColors.ink;

    return Material(
      color: bg,
      borderRadius: BorderRadius.circular(28),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(28),
        child: Container(
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(28),
            border: Border.all(
              color: selected
                  ? (hot ? TbColors.signal : TbColors.taxiDeep)
                  : TbColors.line,
              width: 1.5,
            ),
          ),
          child: Text(
            count == null ? label : '$label  $count',
            style: TextStyle(
              fontWeight: FontWeight.w700,
              fontSize: 15,
              color: fg,
            ),
          ),
        ),
      ),
    );
  }
}
