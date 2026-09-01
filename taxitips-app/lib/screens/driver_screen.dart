import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../push_service.dart';
import '../severity_labels.dart';
import '../theme.dart';
import '../widgets/hotspot_map.dart';
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
  bool _highOnly = false;
  bool _nearMe = false;
  String _kindFilter = 'all'; // all | traffic | event
  String _sourceFilter =
      'all'; // all | transit | road — bara relevant inom "traffic"
  bool _mapShowsPerOpportunity =
      false; // false = platsaggregerad karta (default), true = en markör per signal
  String? _place; // null = alla
  double? _userLat;
  double? _userLon;
  static const _nearKm = 25.0;

  @override
  void initState() {
    super.initState();
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

  bool _isEvent(Map<String, dynamic> a) =>
      a['sourceKind'] == 'event' || (a['taxi'] as Map?)?['reason'] == 'event';

  List<Map<String, dynamic>> get _rawEvents =>
      _asMaps(_data?['events']).map((e) {
        return {
          ...e,
          'header': e['name'] ?? e['header'],
          'taxi': e['taxi'] is Map
              ? Map<String, dynamic>.from(e['taxi'] as Map)
              : e['taxi'],
          'sourceKind': 'event',
        };
      }).toList();

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

  void _sortSignals(List<Map<String, dynamic>> list) {
    list.sort((a, b) {
      final pe =
          _phaseRank((a['taxi'] as Map?)?['phase']) -
          _phaseRank((b['taxi'] as Map?)?['phase']);
      if (pe != 0) return pe;
      final ra = _rank((a['taxi'] as Map?)?['level']);
      final rb = _rank((b['taxi'] as Map?)?['level']);
      if (rb != ra) return rb.compareTo(ra);
      // Within the same phase/level bucket, break ties on the actual numeric
      // worth_it_score (e.g. two 'high' alerts aren't equally worth chasing --
      // a 100-point cancelled train line should still rank above an 85-point one).
      final sa = ((a['worth_it_score'] as num?) ?? 0);
      final sb = ((b['worth_it_score'] as num?) ?? 0);
      if (sa != sb) return sb.compareTo(sa);
      return _placeName(a).compareTo(_placeName(b));
    });
  }

  int _phaseRank(Object? phase) {
    switch (phase) {
      case 'after':
        return 0;
      case 'approaching':
        return 1;
      case 'live':
        return 2;
      case 'upcoming':
        return 3;
      default:
        return 4;
    }
  }

  List<Map<String, dynamic>> get _hotEvents {
    if (_kindFilter == 'traffic') return [];
    var list = _geoFilter(_rawEvents).where((a) {
      final phase = (a['taxi'] as Map?)?['phase']?.toString();
      return phase != 'upcoming';
    }).toList();
    if (_highOnly) {
      list = list
          .where((a) => (a['taxi'] as Map?)?['level'] == 'high')
          .toList();
    }
    _sortSignals(list);
    return list;
  }

  /// Kommande evenemang — visas även när "bara hög prio" (annars försvinner de).
  List<Map<String, dynamic>> get _upcomingEvents {
    if (_kindFilter == 'traffic') return [];
    final list = _geoFilter(_rawEvents).where((a) {
      return (a['taxi'] as Map?)?['phase']?.toString() == 'upcoming';
    }).toList();
    _sortSignals(list);
    return list;
  }

  List<Map<String, dynamic>> get _trafficSignals {
    if (_kindFilter == 'event') return [];
    var list = _sourceFilterList(_geoFilter(_rawActive));
    if (_highOnly) {
      list = list
          .where((a) => (a['taxi'] as Map?)?['level'] == 'high')
          .toList();
    }
    _sortSignals(list);
    return list;
  }

  List<Map<String, dynamic>> get _trafficSignalsVisible {
    final list = _trafficSignals;
    if (_kindFilter == 'all' && list.length > _maxVisibleSignals) {
      return list.take(_maxVisibleSignals).toList();
    }
    return list;
  }

  List<Map<String, dynamic>> get _weekSignals {
    if (_kindFilter == 'event') return [];
    var list = _sourceFilterList(
      _geoFilter(_rawWeek).where((a) => !_isEvent(a)).toList(),
    );
    if (_highOnly) {
      list = list
          .where((a) => (a['taxi'] as Map?)?['level'] == 'high')
          .toList();
    }
    _sortSignals(list);
    return list.take(12).toList();
  }

  List<Map<String, dynamic>> get _signals => [
    ..._hotEvents,
    ..._upcomingEvents,
    ..._trafficSignalsVisible,
  ];

  bool get _filtersActive =>
      _highOnly ||
      _nearMe ||
      _place != null ||
      _kindFilter != 'all' ||
      _sourceFilter != 'all';

  String get _filterSummary {
    final bits = <String>[];
    if (_kindFilter == 'traffic') bits.add('Tåg & väg');
    if (_kindFilter == 'event') bits.add('Evenemang');
    if (_sourceFilter == 'transit') bits.add('Bara kollektivtrafik');
    if (_sourceFilter == 'road') bits.add('Bara vägtrafik');
    if (_highOnly) bits.add('Hög prio');
    if (_nearMe) bits.add('Nära dig');
    if (_place != null) bits.add(_place!);
    if (bits.isEmpty) return 'Alla signaler · tryck filter för att smalna av';
    return bits.join(' · ');
  }

  void _clearFilters() {
    setState(() {
      _place = null;
      _highOnly = false;
      _nearMe = false;
      _kindFilter = 'all';
      _sourceFilter = 'all';
      _status = null;
    });
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
                      subtitle: const Text('Starkaste signalerna först'),
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
                      'Visa',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      children: [
                        for (final opt in const [
                          ('all', 'Alla'),
                          ('traffic', 'Tåg & väg'),
                          ('event', 'Evenemang'),
                        ])
                          ChoiceChip(
                            label: Text(
                              opt.$2,
                              style: const TextStyle(
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            selected: _kindFilter == opt.$1,
                            selectedColor: TbColors.taxi,
                            onSelected: (_) =>
                                apply(() => _kindFilter = opt.$1),
                          ),
                      ],
                    ),
                    if (_kindFilter != 'event') ...[
                      const SizedBox(height: 16),
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
            );
          },
        );
      },
    );
  }

  List<Map<String, dynamic>> get _mapEvents {
    if (_kindFilter == 'traffic') return [];
    // Kartan visar alla event i filtret (inkl. kommande), även vid hög prio.
    return _geoFilter(_rawEvents);
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
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _nearMe = false;
        _error = 'Kunde inte hämta position';
      });
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
    return 'Skåne';
  }

  String _hint(Map<String, dynamic> a) {
    final taxiRaw = a['taxi'];
    final taxi = taxiRaw is Map
        ? Map<String, dynamic>.from(taxiRaw)
        : <String, dynamic>{};
    final hint = taxi['driverHint']?.toString().trim();
    if (hint != null && hint.isNotEmpty) return hint;
    final header = a['header']?.toString().trim() ?? '';
    return header.isEmpty ? 'Störning i kollektivtrafiken' : header;
  }

  List<Map<String, dynamic>> get _places {
    final statsByName = <String, Map<String, dynamic>>{
      for (final p in _asMaps(_data?['placeStats']))
        if (p['name'] != null) p['name'].toString(): p,
    };

    // Räkna från samma signaler som listan (före ort-filter).
    final sources = <Map<String, dynamic>>[
      if (_kindFilter != 'traffic') ..._rawEvents,
      if (_kindFilter != 'event') ..._rawActive,
    ];

    var list = sources;
    if (_highOnly) {
      list = list.where((a) {
        final phase = (a['taxi'] as Map?)?['phase']?.toString();
        // Kommande evenemang syns ändå — räkna dem i chips.
        if (_isEvent(a) && phase == 'upcoming') return true;
        return (a['taxi'] as Map?)?['level'] == 'high';
      }).toList();
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

  String? _phaseLabel(Object? phase) {
    switch (phase) {
      case 'approaching':
        return 'Folk på väg dit (före start)';
      case 'live':
        return 'Pågår nu';
      case 'after':
        return 'Folk vill hem (efter slut)';
      case 'upcoming':
        return 'Kommande — bra att veta';
      default:
        return null;
    }
  }

  String? _formatWhen(Object? iso) {
    if (iso == null) return null;
    final d = DateTime.tryParse(iso.toString())?.toLocal();
    if (d == null) return null;
    const days = ['mån', 'tis', 'ons', 'tor', 'fre', 'lör', 'sön'];
    const months = [
      'jan',
      'feb',
      'mar',
      'apr',
      'maj',
      'jun',
      'jul',
      'aug',
      'sep',
      'okt',
      'nov',
      'dec',
    ];
    final wd = days[(d.weekday - 1).clamp(0, 6)];
    final mo = months[(d.month - 1).clamp(0, 11)];
    final hh = d.hour.toString().padLeft(2, '0');
    final mm = d.minute.toString().padLeft(2, '0');
    return '$wd ${d.day} $mo $hh:$mm';
  }

  List<String> _detailLines(Map<String, dynamic> a) {
    final lines = <String>[];
    if (_isEvent(a)) {
      final venue = a['venue']?.toString();
      final city = a['city']?.toString();
      final when = _formatWhen(a['startsAt']);
      final phase = _phaseLabel((a['taxi'] as Map?)?['phase']);
      final size = a['sizeHint']?.toString();
      final source = a['source']?.toString();
      if (venue != null && venue.isNotEmpty) lines.add('Plats: $venue');
      if (city != null && city.isNotEmpty) lines.add('Ort: $city');
      if (when != null) lines.add('Start: $when');
      if (phase != null) lines.add(phase);
      if (size != null && size.isNotEmpty) lines.add(size);
      if (source != null && source.isNotEmpty) lines.add('Källa: $source');
    } else {
      final desc = a['description']?.toString().trim();
      final header = a['header']?.toString().trim();
      final hint = (a['taxi'] as Map?)?['driverHint']?.toString().trim();
      if (desc != null && desc.isNotEmpty) {
        lines.add(desc);
      } else if (header != null && header.isNotEmpty && header != hint) {
        lines.add(header);
      }
      final effect = a['effect']?.toString();
      final cause = a['cause']?.toString();
      if (effect != null && effect.isNotEmpty) lines.add('Effekt: $effect');
      if (cause != null && cause.isNotEmpty) lines.add('Orsak: $cause');
    }
    return lines;
  }

  Future<void> _openAlertDetail(Map<String, dynamic> a) async {
    final isEvent = _isEvent(a);
    final lines = _detailLines(a);
    final url = a['url']?.toString();
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
                  Text(
                    isEvent
                        ? 'EVENEMANG'
                        : a['sourceKind'] == 'road'
                        ? 'VÄG'
                        : 'KOLLEKTIV',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w900,
                      letterSpacing: 0.6,
                      color: isEvent
                          ? const Color(0xFF2F6FED)
                          : Colors.grey.shade700,
                    ),
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
                  const SizedBox(height: 8),
                  Text(
                    _hint(a),
                    style: const TextStyle(
                      fontSize: 17,
                      height: 1.35,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  if (lines.isNotEmpty) ...[
                    const SizedBox(height: 16),
                    Text(
                      isEvent ? 'Om evenemanget' : 'Mer info',
                      style: TextStyle(
                        fontWeight: FontWeight.w900,
                        color: Colors.grey.shade800,
                      ),
                    ),
                    const SizedBox(height: 8),
                    for (final line in lines)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Text(
                          line,
                          style: TextStyle(
                            fontSize: 15,
                            height: 1.4,
                            color: Colors.grey.shade800,
                          ),
                        ),
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
                        label: Text(
                          isEvent ? 'Öppna evenemang' : 'Öppna mer info',
                        ),
                      ),
                    ),
                  ],
                  if (!isEvent && a['id'] != null) ...[
                    const SizedBox(height: 16),
                    _ExplainSection(
                      opportunityId: a['id'].toString(),
                      api: widget.api,
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
                    // Top bar
                    Container(
                      color: TbColors.asphalt,
                      padding: const EdgeInsets.fromLTRB(12, 6, 8, 10),
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
                            const SizedBox(width: 4),
                          const Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Taxi Tips',
                                style: TextStyle(
                                  fontSize: 22,
                                  fontWeight: FontWeight.w900,
                                  color: TbColors.foam,
                                  height: 1.1,
                                ),
                              ),
                              Text(
                                'Tips när taxi behövs',
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                  color: Color(0xFFB9AFA2),
                                ),
                              ),
                            ],
                          ),
                          const Spacer(),
                          _LivePill(
                            live: live,
                            demo: widget.demo,
                            time: _clock(_data?['updatedAt']),
                          ),
                          IconButton(
                            tooltip: 'Filter',
                            onPressed: _openFilters,
                            icon: Badge(
                              isLabelVisible: _filtersActive,
                              smallSize: 8,
                              backgroundColor: TbColors.taxi,
                              child: const Icon(
                                Icons.tune,
                                color: TbColors.foam,
                              ),
                            ),
                          ),
                          if (widget.onOpenSettings != null)
                            IconButton(
                              tooltip: 'Inställningar',
                              onPressed: widget.onOpenSettings,
                              icon: const Icon(
                                Icons.settings_outlined,
                                color: TbColors.foam,
                              ),
                            ),
                          IconButton(
                            onPressed: _refreshing ? null : () => _load(),
                            icon: _refreshing
                                ? const SizedBox(
                                    width: 20,
                                    height: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: TbColors.taxi,
                                    ),
                                  )
                                : const Icon(
                                    Icons.refresh,
                                    color: TbColors.foam,
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
                          const Text(
                            'Var behövs taxi?',
                            style: TextStyle(
                              fontSize: 28,
                              fontWeight: FontWeight.w900,
                              height: 1.1,
                              color: TbColors.ink,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            _filterSummary,
                            style: TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                              color: Colors.grey.shade700,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Row(
                            children: [
                              Icon(
                                live ? Icons.circle : Icons.circle_outlined,
                                size: 8,
                                color: live
                                    ? TbColors.live
                                    : Colors.grey.shade400,
                              ),
                              const SizedBox(width: 6),
                              Text(
                                live
                                    ? 'Live · uppdaterad ${_clock(_data?['updatedAt'])}'
                                    : 'Data ej live · senast ${_clock(_data?['updatedAt'])}',
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  color: live
                                      ? TbColors.live
                                      : Colors.grey.shade600,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          if (_kindFilter != 'event')
                            Align(
                              alignment: Alignment.centerRight,
                              child: TextButton.icon(
                                onPressed: () => setState(() {
                                  _mapShowsPerOpportunity =
                                      !_mapShowsPerOpportunity;
                                }),
                                icon: Icon(
                                  _mapShowsPerOpportunity
                                      ? Icons.blur_on
                                      : Icons.pin_drop_outlined,
                                  size: 16,
                                ),
                                label: Text(
                                  _mapShowsPerOpportunity
                                      ? 'Visa orter'
                                      : 'Visa signaler + avstånd',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                style: TextButton.styleFrom(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 4,
                                  ),
                                  minimumSize: Size.zero,
                                  tapTargetSize:
                                      MaterialTapTargetSize.shrinkWrap,
                                ),
                              ),
                            ),
                          HotspotMap(
                            placeStats: _kindFilter == 'event'
                                ? const []
                                : _asMaps(_data?['placeStats']),
                            events: _mapEvents,
                            userLat: _userLat,
                            userLon: _userLon,
                            selectedPlace: _place,
                            highOnly: _highOnly && _kindFilter != 'event',
                            perOpportunity:
                                _mapShowsPerOpportunity &&
                                _kindFilter != 'event',
                            opportunities: _sourceFilterList(
                              _geoFilter(_rawActive),
                            ),
                            onSelectPlace: (name) => setState(() {
                              _place = _place == name ? null : name;
                            }),
                            onSelectOpportunity: (o) => _openAlertDetail(o),
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

                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
                      child: Text(
                        () {
                          final hotE = _hotEvents.length;
                          final upE = _upcomingEvents.length;
                          final traf = _trafficSignals.length;
                          if (hotE + upE + traf == 0) return 'Inget just nu';
                          final bits = <String>[];
                          if (_kindFilter != 'traffic') {
                            bits.add('${hotE + upE} event');
                          }
                          if (_kindFilter != 'event') {
                            bits.add('$traf trafik');
                          }
                          final where = _place == null ? '' : ' · $_place';
                          return '${bits.join(' · ')}$where';
                        }(),
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          color: Colors.grey.shade700,
                        ),
                      ),
                    ),

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
                                  Text(
                                    _filtersActive
                                        ? 'Inget i filtret.\nÄndra Alla / typ / nära mig / hög prio.'
                                        : 'Lugnt läge — inga starka taxisignaler.',
                                    textAlign: TextAlign.center,
                                    style: TextStyle(
                                      fontSize: 17,
                                      height: 1.4,
                                      color: Colors.grey.shade700,
                                    ),
                                  ),
                                  if (_filtersActive) ...[
                                    const SizedBox(height: 16),
                                    Center(
                                      child: FilledButton(
                                        onPressed: _clearFilters,
                                        child: const Text('Visa allt'),
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
                                  if (_hotEvents.isNotEmpty ||
                                      _trafficSignalsVisible.isNotEmpty) ...[
                                    const _SectionTitle('Nu — kör hit'),
                                    for (final a in _hotEvents) ...[
                                      SmartAlertCard(
                                        alert: a,
                                        onTap: () => _openAlertDetail(a),
                                      ),
                                      const SizedBox(height: 10),
                                    ],
                                    for (final a in _trafficSignalsVisible.take(
                                      8,
                                    )) ...[
                                      SmartAlertCard(
                                        alert: a,
                                        onTap: () => _openAlertDetail(a),
                                      ),
                                      const SizedBox(height: 10),
                                    ],
                                    if (_trafficSignalsVisible.length > 8)
                                      Padding(
                                        padding: const EdgeInsets.only(
                                          bottom: 10,
                                        ),
                                        child: Text(
                                          '+${_trafficSignalsVisible.length - 8} fler trafiksignaler — öppna Filter → Tåg & väg',
                                          style: TextStyle(
                                            fontSize: 13,
                                            color: Colors.grey.shade700,
                                            fontWeight: FontWeight.w600,
                                          ),
                                        ),
                                      ),
                                  ],
                                  if (_upcomingEvents.isNotEmpty) ...[
                                    const _SectionTitle(
                                      'Kommande 48 h — planera',
                                    ),
                                    for (final a in _upcomingEvents) ...[
                                      SmartAlertCard(
                                        alert: a,
                                        onTap: () => _openAlertDetail(a),
                                      ),
                                      const SizedBox(height: 10),
                                    ],
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
/// scoring rule/confidence and the underlying source event(s) in plain language,
/// with the full raw API payload available behind a secondary expand for anyone
/// who wants to see exactly what Trafiklab/Trafikverket sent.
class _ExplainSection extends StatefulWidget {
  const _ExplainSection({required this.opportunityId, required this.api});
  final String opportunityId;
  final ApiClient api;

  @override
  State<_ExplainSection> createState() => _ExplainSectionState();
}

class _ExplainSectionState extends State<_ExplainSection> {
  bool _loading = true;
  bool _showRaw = false;
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

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: SizedBox(
          height: 20,
          width: 20,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      );
    }

    if (_error != null) {
      return Text(
        _error!,
        style: TextStyle(color: Colors.red.shade700, fontSize: 13),
      );
    }

    final opp = _detail?['opportunity'] as Map?;
    final sourceEvents = (_detail?['source_events'] as List?) ?? const [];
    if (opp == null) {
      return const Text(
        'Ingen ytterligare information tillgänglig.',
        style: TextStyle(fontSize: 13),
      );
    }

    final severityTier = opp['severity_tier']?.toString();
    final confidence = opp['confidence']?.toString();

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: TbColors.sand,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Varför visas detta?',
            style: TextStyle(
              fontWeight: FontWeight.w900,
              color: Colors.grey.shade800,
            ),
          ),
          const SizedBox(height: 8),
          _ExplainRow(
            label: 'Bedömning',
            value: severityTierLabels[severityTier] ?? severityTier ?? 'Okänd',
          ),
          _ExplainRow(
            label: 'Säkerhet',
            value: confidenceLabels[confidence] ?? confidence ?? 'Okänd',
          ),
          _ExplainRow(
            label: 'Poäng',
            value: '${opp['demand_score'] ?? '—'} / 100',
          ),
          if (opp['expired_reason'] != null)
            _ExplainRow(
              label: 'Status',
              value: opp['expired_reason'].toString(),
            ),
          if (sourceEvents.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              'Källa',
              style: TextStyle(
                fontWeight: FontWeight.w800,
                color: Colors.grey.shade800,
                fontSize: 13,
              ),
            ),
            for (final se in sourceEvents.cast<Map>()) ...[
              const SizedBox(height: 4),
              Text(
                switch (se['source']) {
                  'trafiklab' => 'Trafiklab',
                  'trafikverket' => 'Trafikverket',
                  'smhi' => 'SMHI (väder)',
                  _ => se['source']?.toString() ?? '—',
                },
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
              Text(
                se['source'] == 'smhi'
                    ? _weatherSummary(se['raw'] as Map?)
                    : ((se['raw'] as Map?)?['description']?.toString() ??
                          (se['raw'] as Map?)?['header']?.toString() ??
                          '—'),
                style: TextStyle(fontSize: 12, color: Colors.grey.shade700),
              ),
            ],
          ],
          const SizedBox(height: 6),
          TextButton(
            onPressed: () => setState(() => _showRaw = !_showRaw),
            style: TextButton.styleFrom(
              padding: EdgeInsets.zero,
              minimumSize: Size.zero,
            ),
            child: Text(
              _showRaw ? 'Dölj rådata' : 'Visa rådata',
              style: const TextStyle(fontSize: 12),
            ),
          ),
          if (_showRaw)
            Container(
              margin: const EdgeInsets.only(top: 6),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: Colors.black87,
                borderRadius: BorderRadius.circular(6),
              ),
              child: SelectableText(
                const JsonEncoder.withIndent('  ').convert(sourceEvents),
                style: const TextStyle(
                  fontSize: 10,
                  color: Colors.white,
                  fontFamily: 'monospace',
                ),
              ),
            ),
        ],
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

class _ExplainRow extends StatelessWidget {
  const _ExplainRow({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: RichText(
        text: TextSpan(
          style: TextStyle(fontSize: 13, color: Colors.grey.shade800),
          children: [
            TextSpan(
              text: '$label: ',
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            TextSpan(text: value),
          ],
        ),
      ),
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
