import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';

import '../api_client.dart';
import '../membership_copy.dart';
import '../net_status.dart';
import '../signal_kinds.dart';
import '../theme.dart';

/// Notisinställningarna -- så korta som möjligt: på/av, paus, vilka
/// kategorier och hur viktiga tipsen ska vara. Servern äger reglerna
/// (core/notify_prefs.py); samma rattar finns i kundportalen och adminwebben.
///
/// Län och orter styrs från huvudskärmens filter och synkas till
/// `devices.notify_prefs` därifrån -- ingen dubbel kontroll här (en död ratt
/// hade lurat föraren att notiser och lista kunde säga olika saker).
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
  Map<String, bool> _categories = {};
  List<Map<String, dynamic>> _categoryCatalog = [];
  String _minLevel = 'all';
  DateTime? _pausedUntil;

  /// Enskilda störningstyper, under "Fler val".
  Map<String, bool> _types = {};
  List<Map<String, dynamic>> _catalog = [];
  bool _weak = false;

  bool _onDuty = false;
  bool _dutyBusy = false;

  /// Kategorier provet inte omfattar (fleet/features.py). Servern skickar
  /// ingen notis för dem; reglaget är därför låst i stället för att se
  /// påslaget ut utan att något händer.
  Set<SignalCategory> _lockedCategories = {};

  /// Inloggad ägare utan parad telefon: katalogerna går att visa, men det
  /// finns ingen enhet att spara för (servern svarar readOnly).
  bool _readOnly = false;

  /// Körområdet, en kort rad. Sätts av filtret på huvudskärmen.
  Set<String> _counties = {};
  Map<String, String> _countyNames = {};

  /// Läser reglerna ur sparade prefs. Anropas inuti setState.
  void _readRules(Map<String, dynamic> prefs) {
    _enabled = prefs['enabled'] != false;
    final typesRaw = prefs['types'] as Map? ?? {};
    _types = {
      for (final e in typesRaw.entries) e.key.toString(): e.value == true,
    };
    final cats = prefs['categories'];
    _categories = {
      if (cats is Map)
        for (final e in cats.entries) e.key.toString(): e.value != false,
    };
    _minLevel = prefs['minLevel']?.toString() ?? 'all';
    _weak = prefs['weak'] == true;
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
      setState(() {
        _readRules(prefs);
        _onDuty = onDuty;
        _counties = {
          for (final c in (prefs['counties'] as List?) ?? []) c.toString(),
        };
        _countyNames = {
          for (final c in (data['countyCatalog'] as List?) ?? const [])
            if (c is Map) c['code'].toString(): c['name']?.toString() ?? '',
        };
        _readOnly = data['readOnly'] == true;
        _categoryCatalog = [
          for (final c in (data['categoryCatalog'] as List?) ?? const [])
            if (c is Map) Map<String, dynamic>.from(c),
        ];
        final paused = DateTime.tryParse(
          prefs['pausedUntil']?.toString() ?? '',
        )?.toLocal();
        _pausedUntil = paused != null && paused.isAfter(DateTime.now())
            ? paused
            : null;
        final features = data['features'];
        _lockedCategories = {
          if (features is Map)
            for (final k in (features['locked'] as List?) ?? const [])
              ?signalCategoryFromFeatureKey(k),
        };
        _catalog =
            (meta['catalog'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _loading = false;
        _error = netAwareText(e);
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
      if (mounted) setState(() => _error = netAwareText(e));
    } finally {
      if (mounted) setState(() => _dutyBusy = false);
    }
  }

  Future<void> _persist() async {
    setState(() => _saving = true);
    try {
      // Län och kommuner ägs av huvudskärmens filter -- bara reglerna här.
      await widget.api.saveNotifyPrefs(
        enabled: _enabled,
        types: _types,
        categories: _categories,
        minLevel: _minLevel,
      );
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Sparat')));
      }
    } catch (e) {
      if (mounted) setState(() => _error = netAwareText(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// Pausar notiserna [hours] timmar, eller tar bort pausen (0). Tiden räknas
  /// på servern, så att en telefon med fel klocka inte kan pausa i ett år.
  Future<void> _pause(double hours) async {
    setState(() => _saving = true);
    try {
      final prefs = await widget.api.saveNotifyPrefs(pauseHours: hours);
      final until = DateTime.tryParse(
        prefs['pausedUntil']?.toString() ?? '',
      )?.toLocal();
      if (!mounted) return;
      setState(() => _pausedUntil = until);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            until == null
                ? 'Notiserna är på igen.'
                : 'Pausat till ${_clock(until)}.',
          ),
        ),
      );
    } catch (e) {
      if (mounted) setState(() => _error = netAwareText(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  static String _clock(DateTime t) {
    final now = DateTime.now();
    final hm =
        '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    return t.day == now.day ? hm : 'i morgon $hm';
  }

  /// Timmar till kl 07 nästa morgon -- "tyst i natt" (högst 24).
  double get _hoursToMorning {
    final now = DateTime.now();
    var morning = DateTime(now.year, now.month, now.day, 7);
    if (!morning.isAfter(now)) morning = morning.add(const Duration(days: 1));
    return (morning.difference(now).inMinutes / 60).clamp(0.5, 24);
  }

  String? get _areaLine {
    if (!_enabled || _counties.isEmpty) return null;
    final names = [
      for (final c in (_counties.toList()..sort()))
        countyShort(_countyNames[c] ?? c),
    ];
    return 'Körområde: ${names.join(', ')}';
  }

  Widget _label(String text) => Padding(
    padding: const EdgeInsets.only(top: 20, bottom: 6),
    child: Text(
      text,
      style: const TextStyle(
        fontWeight: FontWeight.w700,
        fontSize: 15,
        color: TbColors.midnatt,
      ),
    ),
  );

  Widget _categoryTile(Map<String, dynamic> c, bool editable) {
    final category = signalCategoryFromKey(c['id']?.toString());
    final locked = category != null && _lockedCategories.contains(category);
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        child: SwitchListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: 12),
          secondary: Icon(
            category?.icon ?? Icons.notifications_rounded,
            color: TbColors.midnatt,
          ),
          title: Text(
            c['label']?.toString() ?? '',
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
          subtitle: locked ? const Text(kNotInTrial) : null,
          value: locked ? false : (_categories[c['id']?.toString()] ?? true),
          activeThumbColor: TbColors.ink,
          activeTrackColor: TbColors.signal,
          onChanged: editable && !locked
              ? (v) {
                  setState(() => _categories[c['id'].toString()] = v);
                  _persist();
                }
              : null,
        ),
      ),
    );
  }


  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.viewInsetsOf(context).bottom;
    return Padding(
      padding: EdgeInsets.only(bottom: bottom),
      child: DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.7,
        minChildSize: 0.4,
        maxChildSize: 0.95,
        builder: (context, scroll) {
          if (_loading) {
            return const Center(
              child: CircularProgressIndicator(color: TbColors.taxi),
            );
          }
          final editable = _enabled && !_readOnly;
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
                  fontSize: 24,
                  fontWeight: FontWeight.w700,
                  color: TbColors.ink,
                ),
              ),
              if (_areaLine != null)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(
                    _areaLine!,
                    style: TextStyle(fontSize: 13, color: Colors.grey.shade600),
                  ),
                ),
              if (_readOnly) ...[
                const SizedBox(height: 10),
                const Text(
                  'Ingen aktiv plats på den här enheten — inställningarna '
                  'kan inte sparas.',
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    color: TbColors.ink,
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
              const SizedBox(height: 4),
              Material(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                child: SwitchListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                  title: const Text(
                    'Skicka notiser',
                    style: TextStyle(fontWeight: FontWeight.w700),
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
              _label('Paus'),
              if (_pausedUntil != null)
                Material(
                  color: TbColors.guld.withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(12),
                  child: ListTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                    leading: const Icon(
                      Icons.notifications_paused_rounded,
                      color: TbColors.guldDjup,
                    ),
                    title: Text(
                      'Pausat till ${_clock(_pausedUntil!)}',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    trailing: TextButton(
                      onPressed: _saving ? null : () => _pause(0),
                      child: const Text('Starta igen'),
                    ),
                  ),
                )
              else
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final (label, hours) in [
                      ('1 tim', 1.0),
                      ('4 tim', 4.0),
                      ('I natt', _hoursToMorning),
                    ])
                      ActionChip(
                        avatar: const Icon(
                          Icons.notifications_paused_outlined,
                          size: 18,
                        ),
                        label: Text(label),
                        onPressed: editable && !_saving
                            ? () => _pause(hours)
                            : null,
                      ),
                  ],
                ),

              if (_categoryCatalog.isNotEmpty) ...[
                _label('Vilka notiser?'),
                for (final c in _categoryCatalog) _categoryTile(c, editable),
              ],
              _label('Hur viktiga?'),
              SegmentedButton<String>(
                style: SegmentedButton.styleFrom(
                  selectedBackgroundColor: TbColors.taxi,
                  selectedForegroundColor: TbColors.ink,
                ),
                segments: const [
                  ButtonSegment(value: 'all', label: Text('Alla')),
                  ButtonSegment(value: 'medium', label: Text('Medel +')),
                  ButtonSegment(value: 'high', label: Text('Starka')),
                ],
                selected: {_minLevel},
                onSelectionChanged: editable
                    ? (v) {
                        setState(() => _minLevel = v.first);
                        _persist();
                      }
                    : null,
              ),
              const SizedBox(height: 6),
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
                    _onDuty ? 'Inom 30 km av dig' : 'Enligt körområdet',
                  ),
                  value: _onDuty,
                  activeThumbColor: TbColors.ink,
                  activeTrackColor: TbColors.signal,
                  onChanged: _readOnly || !_enabled || _dutyBusy
                      ? null
                      : _toggleOnDuty,
                ),
              ),
              const SizedBox(height: 10),
              Theme(
                data: Theme.of(
                  context,
                ).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: EdgeInsets.zero,
                  title: const Text(
                    'Fler val',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                  children: [
                    // Typer som aldrig kan ge notis (varken starka eller
                    // svagare) visas inte: ett reglage utan verkan är dött.
                    for (final t in _catalog.where(
                      (t) =>
                          t['notifiable'] != false || t['weakOnly'] != false,
                    )) ...[
                      Material(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(12),
                        child: SwitchListTile(
                          contentPadding: const EdgeInsets.symmetric(
                            horizontal: 12,
                          ),
                          title: Text(
                            t['label']?.toString() ?? '',
                            style: const TextStyle(
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          // En svag typ som inte rörts är PÅ när svagare tips
                          // är påslaget (core/notify.type_enabled).
                          value:
                              _types[t['id']?.toString()] ??
                              (t['defaultOn'] == true ||
                                  (t['weakOnly'] == true && _weak)),
                          activeThumbColor: TbColors.ink,
                          activeTrackColor: TbColors.signal,
                          onChanged:
                              _enabled &&
                                  !_readOnly &&
                                  !(t['weakOnly'] == true && !_weak)
                              ? (v) {
                                  final id = t['id']?.toString();
                                  if (id == null) return;
                                  setState(() => _types[id] = v);
                                  _persist();
                                }
                              : null,
                        ),
                      ),
                      const SizedBox(height: 6),
                    ],
                  ],
                ),
              ),
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

