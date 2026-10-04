import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';

import '../api_client.dart';
import '../membership_copy.dart';
import '../signal_kinds.dart';
import '../net_status.dart';
import '../theme.dart';

/// Notisinställningar: färdiga lägen (Rekommenderat, Bara de starkaste, Allt
/// i mina län, Tyst), paus, kategorier, styrka, svagare tips, tysta timmar,
/// tak per timme och enskilda händelsetyper. Lägena och reglerna kommer från
/// servern (core/notify_prefs.py); företagets administratör kan ändra samma
/// sak i kundportalen.
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

  /// Förarens enkla regler (core/notify.py): kategori av/på, lägsta nivå, paus.
  List<Map<String, dynamic>> _categoryCatalog = [];
  Map<String, bool> _categories = {};
  String _minLevel = 'all';
  DateTime? _pausedUntil;
  Set<String> _licensedCounties = {};

  /// Kategorier provet inte omfattar (`features.locked`, fleet/features.py).
  /// Servern skickar ingen notis för dem; reglaget är därför låst i stället
  /// för att se påslaget ut utan att något händer.
  Set<SignalCategory> _lockedCategories = {};

  /// Färdiga lägen och detaljerade val (core/notify_prefs.py). Tom katalog =
  /// äldre server: då visas varken lägena eller de nya reglagen.
  List<Map<String, dynamic>> _presetCatalog = [];
  String? _preset;
  bool _weak = false;
  ({int from, int to})? _quiet;
  int? _maxPerHour;
  int _weakMax = 3;
  List<int> _maxChoices = const [2, 4, 6];

  bool get _detailed => _presetCatalog.isNotEmpty;

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
    final quiet = prefs['quietHours'];
    final from = quiet is Map ? int.tryParse('${quiet['from']}') : null;
    final to = quiet is Map ? int.tryParse('${quiet['to']}') : null;
    _quiet = from != null && to != null && from != to
        ? (from: from, to: to)
        : null;
    _maxPerHour = int.tryParse('${prefs['maxPerHour'] ?? ''}');
  }

  String get _geoSummary {
    if (!_enabled) return 'Notiser av — ingen push skickas.';
    if (_counties.isEmpty && _licensedCounties.isNotEmpty) {
      final names = [
        for (final code in (_licensedCounties.toList()..sort()))
          countyShort(_countyNames[code] ?? code),
      ];
      return 'Alla dina län: ${names.join(', ')}';
    }
    if (_counties.isEmpty) {
      return 'Inget körområde valt: inga notiser förrän du väljer län '
          'eller slår på I tjänst';
    }
    final names = [
      for (final code in (_counties.toList()..sort()))
        _countyNames[code] ?? code,
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
      setState(() {
        _readRules(prefs);
        _onDuty = onDuty;
        _presetCatalog = [
          for (final p in (data['presetCatalog'] as List?) ?? const [])
            if (p is Map) Map<String, dynamic>.from(p),
        ];
        _preset = data['preset']?.toString();
        _weakMax = int.tryParse('${data['weakMaxPerHour'] ?? ''}') ?? 3;
        final choices = [
          for (final n in (data['maxPerHourChoices'] as List?) ?? const [])
            ?int.tryParse('$n'),
        ];
        if (choices.isNotEmpty) _maxChoices = choices;
        _counties = {
          for (final c in (prefs['counties'] as List?) ?? []) c.toString(),
        };
        _municipalities = {
          for (final m in (prefs['municipalities'] as List?) ?? [])
            m.toString(),
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
        _licensedCounties = {
          for (final c in (data['licensedCounties'] as List?) ?? const [])
            c.toString(),
        };
        final features = data['features'];
        _lockedCategories = {
          if (features is Map)
            for (final k in (features['locked'] as List?) ?? const [])
              ?signalCategoryFromFeatureKey(k),
        };
        _catalog =
            (meta['catalog'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        _tips =
            (meta['tips'] as List?)?.map((e) => e.toString()).toList() ?? [];
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
      if (mounted) {
        setState(() {
          _error = netAwareText(e);
        });
      }
    } finally {
      if (mounted) setState(() => _dutyBusy = false);
    }
  }

  Future<void> _persist() async {
    if (_detailed) {
      // Samma regler via vägen som också svarar med läget (Egna val o.s.v.).
      return _saveRules({
        'enabled': _enabled,
        'types': _types,
        'categories': _categories,
        'minLevel': _minLevel,
      });
    }
    setState(() => _saving = true);
    try {
      // Spara reglerna -- län och kommuner ägs av huvudskärmens filter.
      await widget.api.saveNotifyPrefs(
        enabled: _enabled,
        types: _types,
        categories: _categories,
        minLevel: _minLevel,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Notisinställningar sparade')),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = netAwareText(e);
        });
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// Sparar ett läge eller detaljerade val och läser tillbaka det servern
  /// sparade: den rättar själv det som säger emot sig (svagare tips + bara
  /// starka blir medel och uppåt), och läget räknas där.
  Future<void> _saveRules(
    Map<String, dynamic> body, {
    String done = 'Notisinställningar sparade',
  }) async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final res = await widget.api.saveNotifyRules(body);
      final prefs = res['prefs'];
      if (!mounted) return;
      setState(() {
        if (prefs is Map) _readRules(Map<String, dynamic>.from(prefs));
        _preset = res['preset']?.toString();
      });
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
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
      if (mounted) {
        setState(() => _error = netAwareText(e));
      }
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

  Widget _section(String title) => Padding(
    padding: const EdgeInsets.only(top: 18, bottom: 8),
    child: Text(
      title,
      style: const TextStyle(
        fontWeight: FontWeight.w700,
        fontSize: 16,
        color: TbColors.midnatt,
      ),
    ),
  );

  /// Paus, kategorier och nivå -- det de flesta vill ändra, överst och enkelt.
  List<Widget> _rules() {
    final editable = _enabled && !_readOnly;
    final paused = _pausedUntil != null;
    return [
      if (_detailed) ...[
        _section('Välj läge'),
        for (final p in _presetCatalog) _presetTile(p),
        if (_preset == 'custom')
          Text(
            'Nu: egna val. Välj ett läge ovan för att börja om.',
            style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
          ),
      ],
      _section('Pausa'),
      if (paused)
        Material(
          color: TbColors.guld.withValues(alpha: 0.18),
          borderRadius: BorderRadius.circular(12),
          child: ListTile(
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
                onPressed: editable && !_saving ? () => _pause(hours) : null,
              ),
          ],
        ),
      if (_categoryCatalog.isNotEmpty) ...[
        _section('Vilka notiser?'),
        for (final c in _categoryCatalog)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Builder(
              builder: (context) {
                final category = signalCategoryFromKey(c['id']?.toString());
                final locked =
                    category != null && _lockedCategories.contains(category);
                return Material(
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
                    // Låst: inga notiser för kategorin ingår i provet.
                    subtitle: locked ? const Text(kNotInTrial) : null,
                    value: locked
                        ? false
                        : (_categories[c['id']?.toString()] ?? true),
                    activeThumbColor: TbColors.ink,
                    activeTrackColor: TbColors.signal,
                    onChanged: editable && !locked
                        ? (v) {
                            setState(() => _categories[c['id'].toString()] = v);
                            _persist();
                          }
                        : null,
                  ),
                );
              },
            ),
          ),
      ],
      _section('Hur viktiga?'),
      SegmentedButton<String>(
        style: SegmentedButton.styleFrom(
          selectedBackgroundColor: TbColors.taxi,
          selectedForegroundColor: TbColors.ink,
        ),
        segments: const [
          ButtonSegment(value: 'all', label: Text('Alla')),
          ButtonSegment(value: 'medium', label: Text('Medel +')),
          ButtonSegment(value: 'high', label: Text('Bara starka')),
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
      Text(switch (_minLevel) {
        'high' => 'Bara när många sannolikt behöver taxi.',
        'medium' => 'Medel och starka. Inga svaga.',
        _ =>
          _weak
              ? 'Allt, även svagare tips.'
              : 'Allt som är värt en notis. Svaga tips väcker dig inte.',
      }, style: TextStyle(fontSize: 13, color: Colors.grey.shade700)),
      if (_detailed) ...[
        const SizedBox(height: 12),
        Material(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          child: SwitchListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 12),
            title: const Text(
              'Även svagare tips',
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
            subtitle: Text(
              'Fler notiser, till exempel förseningar. Högst $_weakMax i '
              'timmen. Av från början.',
              style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
            ),
            value: _weak,
            activeThumbColor: TbColors.ink,
            activeTrackColor: TbColors.signal,
            onChanged: editable && !_saving
                ? (v) => _saveRules({'weak': v})
                : null,
          ),
        ),
        _section('Tysta timmar'),
        _choices<({int from, int to})?>(
          options: [
            (null, 'Inga'),
            ((from: 23, to: 6), '23–06'),
            ((from: 1, to: 6), '01–06'),
            if (_quiet != null &&
                !({(from: 23, to: 6), (from: 1, to: 6)}.contains(_quiet)))
              (_quiet, '${_hh(_quiet!.from)}–${_hh(_quiet!.to)}'),
          ],
          selected: _quiet,
          enabled: editable,
          onSelected: (v) => _saveRules({
            'quietHours': v == null ? null : {'from': v.from, 'to': v.to},
          }),
        ),
        const SizedBox(height: 6),
        Text(
          'Inga notiser de timmarna, varje natt. Tipsen finns kvar i listan.',
          style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
        ),
        _section('Högst antal i timmen'),
        _choices<int?>(
          options: [
            (null, 'Inget tak'),
            for (final n in _maxChoices) (n, '$n'),
            if (_maxPerHour != null && !_maxChoices.contains(_maxPerHour))
              (_maxPerHour, '$_maxPerHour'),
          ],
          selected: _maxPerHour,
          enabled: editable,
          onSelected: (v) => _saveRules({'maxPerHour': v}),
        ),
      ],
    ];
  }

  static String _hh(int h) => h.toString().padLeft(2, '0');

  /// Ett färdigt läge: en rad med en mening om vad det betyder.
  Widget _presetTile(Map<String, dynamic> p) {
    final id = p['id']?.toString() ?? '';
    final selected = id == _preset;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: selected ? TbColors.taxi.withValues(alpha: 0.22) : Colors.white,
        borderRadius: BorderRadius.circular(12),
        child: ListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: 12),
          leading: Icon(
            selected
                ? Icons.radio_button_checked_rounded
                : Icons.radio_button_unchecked_rounded,
            color: TbColors.midnatt,
          ),
          title: Text(
            p['label']?.toString() ?? '',
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
          subtitle: Text(
            p['help']?.toString() ?? '',
            style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
          ),
          selected: selected,
          onTap: _readOnly || _saving || selected
              ? null
              : () => _saveRules({
                  'preset': id,
                }, done: '${p['label'] ?? 'Läget'} är valt'),
        ),
      ),
    );
  }

  Widget _choices<T>({
    required List<(T, String)> options,
    required T selected,
    required bool enabled,
    required void Function(T) onSelected,
  }) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final (value, label) in options)
          ChoiceChip(
            label: Text(label),
            selected: value == selected,
            onSelected: enabled && !_saving && value != selected
                ? (_) => onSelected(value)
                : null,
          ),
      ],
    );
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
                'Push till den här telefonen. Svaga tips syns i listan och '
                'väcker dig bara om du valt det.',
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
                    'Den här telefonen är inte kopplad till en bil. Du kan se '
                    'inställningarna men inte spara dem. Öppna Inställningar, '
                    'tryck på bilen och välj "Kör själv med den här '
                    'telefonen".',
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
                    style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
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
                    style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
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
              ..._rules(),
              const SizedBox(height: 10),
              Theme(
                data: Theme.of(
                  context,
                ).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: EdgeInsets.zero,
                  title: const Text(
                    'Fler val: enskilda störningstyper',
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
                      const SizedBox(height: 8),
                    ],
                  ],
                ),
              ),
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
