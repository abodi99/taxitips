import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';

import '../api_client.dart';
import '../theme.dart';

/// Notisinställningar: på/av och händelsetyper.
///
/// Län och orter styrs från huvudskärmens filter och synkas till
/// `devices.notify_prefs` därifrån — ingen dubbel UI här (död kontroll
/// hade lurat föraren att notiser och listan kunde säga olika saker).
class NotifyPrefsSheet extends StatefulWidget {
  const NotifyPrefsSheet({super.key, required this.api});
  final ApiClient api;

  @override
  State<NotifyPrefsSheet> createState() => _NotifyPrefsSheetState();
}

class _NotifyPrefsSheetState extends State<NotifyPrefsSheet> {
  bool _loading = true;
  bool _saving = false;
  String? _error;
  bool _enabled = true;
  Map<String, bool> _types = {};
  Set<String> _counties = {};
  Set<String> _municipalities = {};
  Map<String, String> _countyNames = {};
  List<Map<String, dynamic>> _catalog = [];
  List<String> _tips = [];
  bool _readOnly = false;
  bool _onDuty = false;
  bool _dutyBusy = false;

  String get _geoSummary {
    if (!_enabled) return 'Notiser av — ingen push skickas.';
    if (_counties.isEmpty) {
      return 'Inget körområde valt: inga notiser förrän du väljer län '
          'eller slår på I tjänst';
    }
    final names = [
      for (final code in (_counties.toList()..sort())) _countyNames[code] ?? code,
    ];
    final municipalities = _municipalities.isEmpty
        ? 'hela länen'
        : '${_municipalities.length} ${_municipalities.length == 1 ? 'kommun' : 'kommuner'}';
    return '${names.join(', ')} · $municipalities';
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await widget.api.getNotifyPrefs();
      final onDuty = await widget.api.onDuty();
      final prefs = data['prefs'] as Map<String, dynamic>? ?? {};
      final meta = data['meta'] as Map<String, dynamic>? ?? {};
      final typesRaw = prefs['types'] as Map? ?? {};
      final types = <String, bool>{};
      for (final e in typesRaw.entries) {
        types[e.key.toString()] = e.value == true;
      }
      setState(() {
        _enabled = prefs['enabled'] != false;
        _onDuty = onDuty;
        _types = types;
        _counties = {
          for (final c in (prefs['counties'] as List?) ?? []) c.toString(),
        };
        _municipalities = {
          for (final m in (prefs['municipalities'] as List?) ?? []) m.toString(),
        };
        _countyNames = {
          for (final c in (data['countyCatalog'] as List?) ?? const [])
            if (c is Map) c['code'].toString(): c['name']?.toString() ?? '',
        };
        _readOnly = data['readOnly'] == true;
        _catalog =
            (meta['catalog'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        _tips =
            (meta['tips'] as List?)?.map((e) => e.toString()).toList() ?? [];
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _loading = false;
        _error = e.toString().replaceFirst(
          RegExp(r'^(ApiException|Exception):\s*'),
          '',
        );
      });
    }
  }

  /// "I tjänst": positionen hämtas en gång nu och förnyas sedan bara medan
  /// appen är öppen (se ApiClient.refreshPresence).
  Future<void> _toggleOnDuty(bool on) async {
    setState(() {
      _dutyBusy = true;
      _error = null;
    });
    try {
      double? lat;
      double? lon;
      if (on) {
        var perm = await Geolocator.checkPermission();
        if (perm == LocationPermission.denied) {
          perm = await Geolocator.requestPermission();
        }
        if (perm == LocationPermission.denied ||
            perm == LocationPermission.deniedForever) {
          throw Exception('I tjänst behöver plats när appen används');
        }
        final pos = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(
            accuracy: LocationAccuracy.low,
            timeLimit: Duration(seconds: 20),
          ),
        );
        lat = pos.latitude;
        lon = pos.longitude;
      }
      await widget.api.setOnDuty(on, lat: lat, lon: lon);
      if (mounted) setState(() => _onDuty = on);
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString().replaceFirst(
            RegExp(r'^(ApiException|Exception):\s*'),
            '',
          );
        });
      }
    } finally {
      if (mounted) setState(() => _dutyBusy = false);
    }
  }

  Future<void> _persist() async {
    setState(() => _saving = true);
    try {
      // Spara bara enabled/types — regions/cities ägs av huvudskärmens filter.
      await widget.api.saveNotifyPrefs(
        enabled: _enabled,
        types: _types,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Notisinställningar sparade')),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString().replaceFirst(
            RegExp(r'^(ApiException|Exception):\s*'),
            '',
          );
        });
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.viewInsetsOf(context).bottom;
    return Padding(
      padding: EdgeInsets.only(bottom: bottom),
      child: DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.75,
        minChildSize: 0.45,
        maxChildSize: 0.95,
        builder: (context, scroll) {
          if (_loading) {
            return const Center(
              child: CircularProgressIndicator(color: TbColors.taxi),
            );
          }
          return ListView(
            controller: scroll,
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
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
                'Notiser',
                style: TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w700,
                  color: TbColors.ink,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'Push till den här telefonen. Svaga signaler syns i listan '
                'men väcker dig aldrig.',
                style: TextStyle(
                  fontSize: 14,
                  height: 1.4,
                  color: Colors.grey.shade700,
                ),
              ),
              if (_readOnly) ...[
                const SizedBox(height: 10),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: TbColors.sand,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: TbColors.taxiDeep),
                  ),
                  child: const Text(
                    'Ingen enhet kopplad — du kan se filtren men inte spara. '
                    'Öppna appen med bolagskod på telefonen först.',
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      height: 1.35,
                      color: TbColors.ink,
                    ),
                  ),
                ),
              ],
              if (_error != null) ...[
                const SizedBox(height: 10),
                Text(
                  _error!,
                  style: const TextStyle(
                    color: TbColors.danger,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: TbColors.ljusgraDjup,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Område (följer huvudskärmen)',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.4,
                        color: Colors.grey.shade700,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _geoSummary,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        height: 1.35,
                        color: TbColors.ink,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Ändra län och kommuner under filtret på tipslistan — '
                      'notiserna använder samma val när du inte är i tjänst.',
                      style: TextStyle(
                        fontSize: 13,
                        height: 1.35,
                        color: Colors.grey.shade700,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              Material(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                child: SwitchListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                  title: const Text(
                    'Alla notiser',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                  subtitle: Text(
                    _enabled
                        ? 'På — filtreras enligt område och typ'
                        : 'Av — ingen push',
                    style: TextStyle(
                      fontSize: 13,
                      color: Colors.grey.shade700,
                    ),
                  ),
                  value: _enabled,
                  activeThumbColor: TbColors.ink,
                  activeTrackColor: TbColors.signal,
                  onChanged: _readOnly
                      ? null
                      : (v) {
                          setState(() => _enabled = v);
                          _persist();
                        },
                ),
              ),
              const SizedBox(height: 12),
              Material(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                child: SwitchListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                  title: const Text(
                    'I tjänst',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                  subtitle: Text(
                    _onDuty
                        ? 'På — notiser inom 30 km från där du är. Gäller 30 min '
                              'efter att appen senast var öppen, sedan körområdet.'
                        : 'Av — notiser enligt körområdet.',
                    style: TextStyle(
                      fontSize: 13,
                      color: Colors.grey.shade700,
                    ),
                  ),
                  value: _onDuty,
                  activeThumbColor: TbColors.ink,
                  activeTrackColor: TbColors.signal,
                  onChanged: _readOnly || !_enabled || _dutyBusy
                      ? null
                      : _toggleOnDuty,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'Servern sparar bara ett område på ungefär 5 km, skriver över '
                'det vid varje uppdatering och hämtar aldrig plats i bakgrunden.',
                style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
              ),
              const SizedBox(height: 18),
              Text(
                'Vilka händelser?',
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 16,
                  color: Colors.grey.shade800,
                ),
              ),
              const SizedBox(height: 8),
              for (final t in _catalog) ...[
                Material(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(12),
                  child: SwitchListTile(
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 4,
                    ),
                    title: Text(
                      t['label']?.toString() ?? '',
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        color: TbColors.ink,
                      ),
                    ),
                    subtitle: Text(
                      '${t['short'] ?? ''}\n${t['help'] ?? ''}',
                      style: TextStyle(
                        fontSize: 13,
                        height: 1.35,
                        color: Colors.grey.shade700,
                      ),
                    ),
                    isThreeLine: true,
                    value:
                        _types[t['id']?.toString()] ??
                        (t['defaultOn'] == true),
                    activeThumbColor: TbColors.ink,
                    activeTrackColor: TbColors.signal,
                    onChanged: _enabled && !_readOnly
                        ? (v) {
                            final id = t['id']?.toString();
                            if (id == null) return;
                            setState(() => _types[id] = v);
                            _persist();
                          }
                        : null,
                  ),
                ),
                const SizedBox(height: 8),
              ],
              if (_tips.isNotEmpty) ...[
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: TbColors.ljusgraDjup,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Tips',
                        style: TextStyle(fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 6),
                      for (final tip in _tips)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Text(
                            '· $tip',
                            style: TextStyle(
                              fontSize: 13,
                              height: 1.35,
                              color: Colors.grey.shade800,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
              if (_saving)
                const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: Center(
                    child: SizedBox(
                      width: 22,
                      height: 22,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}
