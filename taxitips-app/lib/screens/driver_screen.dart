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
  // On by default: the screen exists to answer "var finns taxibehov just nu",
  // and the honest answer is a short list of places actually worth driving to
  // -- not 250 signals dominated by buses running a few minutes late. Weaker
  // signals stay one tap away for a driver who deliberately wants them.
  bool _highOnly = true;
  bool _nearMe = false;
  String _sourceFilter = 'all'; // all | transit | road
  bool _mapShowsPerOpportunity =
      false; // false = platsaggregerad karta (default), true = en markör per signal
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

  Future<void> _loadSavedFilters() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final highOnly = prefs.getBool(_prefsHighOnlyKey);
      final nearMe = prefs.getBool(_prefsNearMeKey);
      final source = prefs.getString(_prefsSourceKey);
      if (!mounted) return;
      setState(() {
        if (highOnly != null) _highOnly = highOnly;
        if (source != null) _sourceFilter = source;
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
    await _load();
    _timer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => _load(silent: true),
    );
  }

  String _friendly(Object e) {
    final s = e.toString();
    if (s.contains('Ogiltig'))
      return 'Koden funkar inte — be kontoret om rätt bolags-/byteskod.';
    if (s.contains('401') || s.contains('licens'))
      return 'Ingen access. Registrera telefonen med bolagskod eller logga in.';
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

  /// Place + near-me filters (not kind / high-only).
  List<Map<String, dynamic>> _geoFilter(List<Map<String, dynamic>> list) {
    var out = list;
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
    if (_sourceFilter == 'all') return list;
    return list.where((a) => a['kind'] == _sourceFilter).toList();
  }

  // "Bara hög prio" means "severe disruption", NOT "reachable from here" --
  // those are different questions. taxi.level is worth_it_score-derived (it
  // folds in distance/time-to-reach), so a genuinely severe but far-away
  // line_paused event was silently disappearing under this filter even at a
  // demand_score of 90, which is backwards: severity is what "priority" should
  // mean here, reachability is what worth_it_score/sorting already handles
  // separately. Falls back to taxi.level for events, which don't carry
  // severity_tier/demand_score at all.
  //
  // Road tiers are deliberately excluded -- an accident/closure delays people
  // already in a car, it doesn't strand pedestrians who'd need a taxi, so it's
  // never "high priority" here regardless of how bad the road situation reads.
  /// "Hög prio" must mean the same thing the card's badge means, or the
  /// screen contradicts itself. It used to key off demand_score (raw
  /// severity), while the badge keys off customerLikelihood() (which folds
  /// in reachability via worth_it_score) -- so a line_paused 55 km away
  /// passed the filter while its own badge read "Osannolikt just nu".
  /// Both now ask one question: is this worth driving to right now?
  bool _isHighSeverity(Map<String, dynamic> a) {
    final severityTier = a['severity_tier']?.toString();
    if (severityTier == null) {
      return (a['taxi'] as Map?)?['level'] == 'high';
    }
    return customerLikelihood(
          severityTier: severityTier,
          worthItScore: (a['worth_it_score'] as num?) ?? 0,
          demandScore: (a['demand_score'] as num?) ?? 0,
        ) ==
        CustomerLikelihood.high;
  }

  void _sortSignals(List<Map<String, dynamic>> list) {
    list.sort((a, b) {
      // Active disruptions always rank above yesterday's ended ones,
      // regardless of score -- "what to act on now" beats "what happened".
      final aActive = a['is_active'] != false;
      final bActive = b['is_active'] != false;
      if (aActive != bActive) return aActive ? -1 : 1;
      final ra = _rank((a['taxi'] as Map?)?['level']);
      final rb = _rank((b['taxi'] as Map?)?['level']);
      if (rb != ra) return rb.compareTo(ra);
      // Within the same level bucket, break ties on the actual numeric
      // worth_it_score (e.g. two 'high' alerts aren't equally worth chasing --
      // a 100-point cancelled train line should still rank above an 85-point one).
      final sa = ((a['worth_it_score'] as num?) ?? 0);
      final sb = ((b['worth_it_score'] as num?) ?? 0);
      if (sa != sb) return sb.compareTo(sa);
      return _placeName(a).compareTo(_placeName(b));
    });
  }

  List<Map<String, dynamic>> get _trafficSignals {
    var list = _sourceFilterList(_geoFilter(_rawActive));
    if (_highOnly) {
      list = list
          .where(_isHighSeverity)
          .toList();
    }
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
      _highOnly || _nearMe || _place != null || _sourceFilter != 'all';

  String get _filterSummary {
    final bits = <String>[];
    if (_sourceFilter == 'transit') bits.add('Bara kollektivtrafik');
    if (_sourceFilter == 'road') bits.add('Bara vägtrafik');
    if (_highOnly) bits.add('Hög prio');
    if (_nearMe) bits.add('Nära dig');
    if (_place != null) bits.add(_place!);
    if (bits.isEmpty) return 'Alla signaler';
    return bits.join(' · ');
  }

  // Resets to the app's default view (high prio only), not to "show
  // everything" -- the default IS the intended answer to "var finns
  // taxibehov just nu", so returning to it is what "nollställ" should mean.
  void _clearFilters() {
    setState(() {
      _place = null;
      _highOnly = true;
      _nearMe = false;
      _sourceFilter = 'all';
      _status = null;
    });
    _saveFilters();
  }

  Future<void> _openFilters() async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: TbColors.foam,
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
                        fontSize: 24,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 12),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text(
                        'Bara hög prio',
                        style: TextStyle(fontWeight: FontWeight.w800),
                      ),
                      subtitle: const Text(
                        'Bara allvarliga störningar (oavsett avstånd)',
                      ),
                      value: _highOnly,
                      onChanged: (v) => apply(() => _highOnly = v),
                    ),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text(
                        'Nära mig',
                        style: TextStyle(fontWeight: FontWeight.w800),
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
                      style: TextStyle(fontWeight: FontWeight.w800),
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
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            selected: _sourceFilter == opt.$1,
                            selectedColor: TbColors.taxi,
                            onSelected: (_) =>
                                apply(() => _sourceFilter = opt.$1),
                          ),
                      ],
                    ),
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
    final likelihood = customerLikelihood(
      severityTier: a['severity_tier']?.toString(),
      worthItScore: (a['worth_it_score'] as num?) ?? 0,
      demandScore: (a['demand_score'] as num?) ?? 0,
    );
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
                          fontWeight: FontWeight.w900,
                          letterSpacing: 0.6,
                          color: Colors.grey.shade700,
                        ),
                      ),
                      // Restates the same likelihood the card already showed
                      // -- the sheet shouldn't require remembering it from
                      // the list.
                      LikelihoodBadge(likelihood: likelihood, fontSize: 13),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _placeName(a),
                    style: const TextStyle(
                      fontSize: 28,
                      fontWeight: FontWeight.w900,
                      height: 1.1,
                    ),
                  ),
                  const SizedBox(height: 10),
                  // Stat row: date/time + score up front so a driver scanning
                  // the sheet can place it in time and judge it at a glance,
                  // without scrolling into "Varför visas detta?" for either.
                  Row(
                    children: [
                      _DetailStat(
                        icon: Icons.schedule,
                        label: a['is_active'] == false
                            ? '${dateTimeLabel(a['start_time']?.toString())} → ${dateTimeLabel(a['end_time']?.toString())}'
                            : dateTimeLabel(a['start_time']?.toString()),
                      ),
                      const SizedBox(width: 8),
                      _DetailStat(
                        icon: Icons.speed,
                        label: '${(a['demand_score'] as num?)?.round() ?? '—'}/100',
                      ),
                      if (a['is_active'] == false) ...[
                        const SizedBox(width: 8),
                        const _DetailStat(
                          icon: Icons.history,
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
    final live =
        _data?['source'] == 'trafiklab' ||
        (_data?['source']?.toString().contains('trafik') ?? false);

    return Scaffold(
      backgroundColor: TbColors.foam,
      body: DefaultTextStyle(
        style: const TextStyle(
          color: TbColors.ink,
          fontSize: 15,
          fontWeight: FontWeight.w500,
          decoration: TextDecoration.none,
        ),
        child: SafeArea(
          child: _claiming
              ? const Center(
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
                )
              : Column(
                  children: [
                    // Top bar -- kept to one job each: identity (title + live
                    // status), and one standard action (settings). Filter and
                    // refresh both moved down next to the list they actually
                    // affect (see _filterSummary row below) instead of living
                    // here -- neither is identity/global-app chrome, they're
                    // both list controls. A soft shadow gives it depth against
                    // the flat sand background below instead of a hard edge.
                    Container(
                      decoration: const BoxDecoration(
                        color: TbColors.asphalt,
                        boxShadow: [
                          BoxShadow(
                            color: Color(0x33000000),
                            blurRadius: 8,
                            offset: Offset(0, 2),
                          ),
                        ],
                      ),
                      padding: const EdgeInsets.fromLTRB(8, 8, 8, 12),
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
                              fontSize: 21,
                              fontWeight: FontWeight.w900,
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
                      _EntitlementBanner(onOpenSettings: widget.onOpenSettings),

                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Expanded(
                                child: Text(
                                  'Var behövs taxi?',
                                  style: TextStyle(
                                    fontSize: 28,
                                    fontWeight: FontWeight.w900,
                                    height: 1.1,
                                    color: TbColors.ink,
                                  ),
                                ),
                              ),
                              // Filter and refresh live here, next to the list
                              // they control, instead of in the top bar's
                              // global-app chrome.
                              Padding(
                                padding: const EdgeInsets.only(top: 2),
                                child: Row(
                                  children: [
                                    SizedBox(
                                      width: 48,
                                      height: 48,
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
                                            color: Color(0xFFC9D0DA),
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
                                        child: const Icon(Icons.tune, size: 18),
                                      ),
                                      label: const Text('Filter'),
                                      style: OutlinedButton.styleFrom(
                                        foregroundColor: TbColors.ink,
                                        padding: const EdgeInsets.symmetric(
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
                          const SizedBox(height: 8),
                          // Filter-summary and live-status used to be two
                          // separate stacked lines doing similar "state of the
                          // world" jobs -- merged into one so a driver scans
                          // one line instead of two before reaching the map.
                          // An active filter tints just that segment instead
                          // of adding its own row.
                          Row(
                            children: [
                              Icon(
                                live ? Icons.circle : Icons.circle_outlined,
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
                                            ? 'Live · uppdaterad ${_clock(_data?['updatedAt'])}'
                                            : 'Data ej live · senast ${_clock(_data?['updatedAt'])}',
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
                          const SizedBox(height: 10),
                          Stack(
                            children: [
                              HotspotMap(
                                placeStats: _asMaps(_data?['placeStats']),
                                events: _mapEvents,
                                userLat: _userLat,
                                userLon: _userLon,
                                selectedPlace: _place,
                                highOnly: _highOnly,
                                perOpportunity: _mapShowsPerOpportunity,
                                opportunities: _sourceFilterList(
                                  _geoFilter(_rawActive),
                                ),
                                onSelectPlace: (name) => setState(() {
                                  _place = _place == name ? null : name;
                                }),
                                onSelectOpportunity: (o) =>
                                    _openAlertDetail(o),
                              ),
                              Positioned(
                                top: 8,
                                right: 8,
                                child: SizedBox(
                                  width: 44,
                                  height: 44,
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
                                      size: 20,
                                      color: TbColors.ink,
                                    ),
                                    style: IconButton.styleFrom(
                                      backgroundColor: Colors.white
                                          .withValues(alpha: 0.9),
                                      shape: const CircleBorder(),
                                      elevation: 2,
                                    ),
                                  ),
                                ),
                              ),
                            ],
                          ),
                          if (_status != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                _status!,
                                style: const TextStyle(
                                  color: TbColors.live,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          if (_error != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                _error!,
                                style: const TextStyle(
                                  color: TbColors.danger,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),

                    if (_places.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      SizedBox(
                        height: 44,
                        child: ListView(
                          scrollDirection: Axis.horizontal,
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          children: [
                            _OrtChip(
                              label: 'Alla',
                              selected: _place == null,
                              onTap: () => setState(() => _place = null),
                            ),
                            for (final p in _places.take(12))
                              Padding(
                                padding: const EdgeInsets.only(left: 8),
                                child: _OrtChip(
                                  label: p['name']?.toString() ?? '',
                                  count: (p['count'] as num?)?.toInt(),
                                  hot: p['maxLevel'] == 'high',
                                  selected: _place == p['name'],
                                  onTap: () => setState(() {
                                    final name = p['name']?.toString();
                                    _place = _place == name ? null : name;
                                  }),
                                ),
                              ),
                          ],
                        ),
                      ),
                    ],

                    Expanded(
                      child: RefreshIndicator(
                        color: TbColors.taxiDeep,
                        onRefresh: () => _load(),
                        child: _signals.isEmpty && _weekSignals.isEmpty
                            ? ListView(
                                physics: const AlwaysScrollableScrollPhysics(),
                                padding: const EdgeInsets.all(40),
                                children: [
                                  Icon(
                                    Icons.local_taxi,
                                    size: 64,
                                    color: Colors.grey.shade300,
                                  ),
                                  const SizedBox(height: 12),
                                  // "Nothing high-prio right now" is a real,
                                  // useful answer -- not an error state. Since
                                  // high-prio is the default, offer the one
                                  // action that actually reveals more (turning
                                  // it off) rather than a reset that would
                                  // land right back here.
                                  Text(
                                    _highOnly
                                        ? 'Inga starka taxisignaler just nu.'
                                        : 'Inget i filtret.\nÄndra typ, nära mig eller ort.',
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
                                          setState(() => _highOnly = false);
                                          _saveFilters();
                                        },
                                        child: const Text('Visa svagare signaler'),
                                      ),
                                    ),
                                  ] else if (_filtersActive) ...[
                                    const SizedBox(height: 16),
                                    Center(
                                      child: FilledButton(
                                        onPressed: _clearFilters,
                                        child: const Text('Nollställ filter'),
                                      ),
                                    ),
                                  ],
                                ],
                              )
                            : ListView(
                                physics: const AlwaysScrollableScrollPhysics(),
                                padding: const EdgeInsets.fromLTRB(
                                  16,
                                  4,
                                  16,
                                  28,
                                ),
                                children: [
                                  if (_trafficSignalsVisible.isNotEmpty) ...[
                                    if (_activeSignalsVisible.isNotEmpty) ...[
                                      _SectionTitle(
                                        'Nu — kör hit (${_trafficSignals.length})',
                                      ),
                                      for (final a in _activeSignalsVisible) ...[
                                        SmartAlertCard(
                                          alert: a,
                                          onTap: () => _openAlertDetail(a),
                                        ),
                                        const SizedBox(height: 10),
                                      ],
                                    ],
                                    if (_endedSignalsVisible.isNotEmpty) ...[
                                      const _SectionTitle('Senaste dygnet'),
                                      for (final a in _endedSignalsVisible) ...[
                                        SmartAlertCard(
                                          alert: a,
                                          onTap: () => _openAlertDetail(a),
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
                                        dividerColor: Colors.transparent,
                                      ),
                                      child: ExpansionTile(
                                        initiallyExpanded: false,
                                        tilePadding: EdgeInsets.zero,
                                        childrenPadding: EdgeInsets.zero,
                                        title: const Text(
                                          'Senaste veckan',
                                          style: TextStyle(
                                            fontSize: 18,
                                            fontWeight: FontWeight.w900,
                                          ),
                                        ),
                                        children: [
                                          for (final a in _weekSignals) ...[
                                            SmartAlertCard(
                                              alert: a,
                                              onTap: () => _openAlertDetail(a),
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
          fontWeight: FontWeight.w900,
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
                        fontWeight: FontWeight.w900,
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
  final IconData icon;
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
          Icon(icon, size: 13, color: Colors.grey.shade700),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: Colors.grey.shade800,
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
            fontWeight: FontWeight.w800,
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
                    fontWeight: FontWeight.w900,
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
        border: Border.all(color: const Color(0xFFD4CBBC)),
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
            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12),
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
                  : const Color(0xFF8A7F70),
              width: 1.5,
            ),
          ),
          child: Text(
            count == null ? label : '$label  $count',
            style: TextStyle(
              fontWeight: FontWeight.w900,
              fontSize: 15,
              color: fg,
            ),
          ),
        ),
      ),
    );
  }
}
