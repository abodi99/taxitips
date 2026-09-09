import 'package:flutter/material.dart';

import '../api_client.dart';
import '../theme.dart';

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
  Set<String> _cities = {};
  Set<String> _regions = {};
  List<Map<String, dynamic>> _catalog = [];
  List<Map<String, dynamic>> _regionCatalog = [];
  List<String> _uncovered = [];
  List<String> _tips = [];
  List<String> _areaChoices = [];
  bool _readOnly = false;

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
      final prefs = data['prefs'] as Map<String, dynamic>? ?? {};
      final meta = data['meta'] as Map<String, dynamic>? ?? {};
      final typesRaw = prefs['types'] as Map? ?? {};
      final types = <String, bool>{};
      for (final e in typesRaw.entries) {
        types[e.key.toString()] = e.value == true;
      }
      final company = (data['companyAreas'] as List?)?.map((e) => e.toString()).toList() ?? [];
      final catalogAreas = (data['areaCatalog'] as List?)?.map((e) => e.toString()).toList() ?? [];
      final choices = company.isNotEmpty ? company : catalogAreas;
      setState(() {
        _enabled = prefs['enabled'] != false;
        _types = types;
        _cities = {
          for (final c in (prefs['cities'] as List?) ?? []) c.toString(),
        };
        _regions = {
          for (final r in (prefs['regions'] as List?) ?? []) r.toString(),
        };
        _regionCatalog =
            (data['regionCatalog'] as List?)?.cast<Map<String, dynamic>>() ??
            const [];
        _uncovered =
            (data['uncoveredCounties'] as List?)
                ?.map((e) => e.toString())
                .toList() ??
            const [];
        _readOnly = data['readOnly'] == true;
        _catalog = (meta['catalog'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        _tips = (meta['tips'] as List?)?.map((e) => e.toString()).toList() ?? [];
        _areaChoices = choices;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _loading = false;
        _error = e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), '');
      });
    }
  }

  Future<void> _persist() async {
    setState(() => _saving = true);
    try {
      await widget.api.saveNotifyPrefs(
        enabled: _enabled,
        cities: _cities.toList()..sort(),
        regions: _regions.toList()..sort(),
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
          _error = e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), '');
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
        initialChildSize: 0.88,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        builder: (context, scroll) {
          if (_loading) {
            return const Center(child: CircularProgressIndicator(color: TbColors.taxi));
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
                style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: TbColors.ink),
              ),
              const SizedBox(height: 6),
              Text(
                'Gäller push till den här telefonen. Notiser skickas bara för störningar som är värda att avbryta för — svaga signaler (t.ex. en buss några minuter sen) syns i listan men stör dig aldrig. Listfiltret “Bara hög prio” ändrar bara vad du ser i appen.',
                style: TextStyle(fontSize: 14, height: 1.4, color: Colors.grey.shade700),
              ),
              if (_error != null) ...[
                const SizedBox(height: 10),
                Text(_error!, style: const TextStyle(color: TbColors.danger, fontWeight: FontWeight.w700)),
              ],
              const SizedBox(height: 12),
              Material(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                child: SwitchListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                  title: const Text('Alla notiser', style: TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text(
                    _enabled ? 'På — filtreras enligt nedan' : 'Av — ingen push',
                    style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
                  ),
                  value: _enabled,
                  activeThumbColor: TbColors.ink,
                  activeTrackColor: TbColors.signal,
                  onChanged: (v) {
                    setState(() => _enabled = v);
                    _persist();
                  },
                ),
              ),
              const SizedBox(height: 18),
              // Länen först, och orterna som en förfining under. Ordningen
              // speglar hur mycket de faktiskt går att lita på: mätt på 506
              // aktiva tips bär ALLA en region, medan 61% saknar ortsuppgift
              // helt. Ett ortsfilter ensamt hade tystat majoriteten av alla
              // riktiga störningar -- se core/notify.py.
              if (_regionCatalog.isNotEmpty) ...[
                Text(
                  'Län du kör i',
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 16,
                    color: Colors.grey.shade800,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  _regions.isEmpty
                      ? 'Inga valda = notiser från hela landet.'
                      : 'Notiser från valda län. Störningar utan känt län släpps alltid igenom.',
                  style: TextStyle(fontSize: 13, color: Colors.grey.shade600),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final r in _regionCatalog)
                      FilterChip(
                        label: Text(
                          r['label']?.toString() ?? '',
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        // Järnvägen är ett eget val, inte ett län:
                        // Trafikverkets tågdata saknar länsfält, så ett
                        // tågtips skrivs som "rail" oavsett var stationen
                        // ligger. Väljer man det tillsammans med ett län
                        // avgränsas tågen ändå geografiskt av
                        // marknadsradien -- samma 150 km som listan
                        // använder (core/notify.py:within_reach).
                        tooltip: (r['note']?.toString() ?? '').isEmpty
                            ? null
                            : r['note'].toString(),
                        selected: _regions.contains(r['key']?.toString()),
                        selectedColor: TbColors.taxi,
                        checkmarkColor: TbColors.ink,
                        onSelected: _enabled && !_readOnly
                            ? (sel) {
                                final key = r['key']?.toString();
                                if (key == null) return;
                                setState(() {
                                  if (sel) {
                                    _regions.add(key);
                                  } else {
                                    _regions.remove(key);
                                  }
                                });
                                _persist();
                              }
                            : null,
                      ),
                  ],
                ),
                if (_regions.isNotEmpty)
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton(
                      onPressed: _enabled && !_readOnly
                          ? () {
                              setState(() => _regions.clear());
                              _persist();
                            }
                          : null,
                      child: const Text('Rensa länsval (hela landet)'),
                    ),
                  ),
                if (_uncovered.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  // Ärligt om luckorna i stället för att tiga om dem: de här
                  // länen saknar kollektivtrafikkälla (404 hos Trafiklab).
                  // Ett val vi inte kan infria hade lästs som "lugnt där".
                  Text(
                    'Saknar kollektivtrafikdata: ${_uncovered.join(', ')}. '
                    'Tåg och väg täcks ändå i hela landet.',
                    style: TextStyle(
                      fontSize: 12,
                      height: 1.35,
                      color: Colors.grey.shade600,
                    ),
                  ),
                ],
                const SizedBox(height: 18),
              ],
              Text(
                'Orter du kör i',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: Colors.grey.shade800),
              ),
              const SizedBox(height: 4),
              // Honest about the actual behaviour: a city filter removes
              // signals known to be somewhere else, but a signal whose plats
              // saknas (very common -- Trafiklab often sends no place at all)
              // is still let through rather than silently dropped.
              Text(
                _cities.isEmpty
                    ? 'Inga valda = notiser från hela området.'
                    : 'Notiser från valda orter, plus störningar utan angiven ort.',
                style: TextStyle(fontSize: 13, color: Colors.grey.shade600),
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final city in _areaChoices)
                    FilterChip(
                      label: Text(city, style: const TextStyle(fontWeight: FontWeight.w700)),
                      selected: _cities.contains(city),
                      selectedColor: TbColors.taxi,
                      checkmarkColor: TbColors.ink,
                      onSelected: _enabled
                          ? (sel) {
                              setState(() {
                                if (sel) {
                                  _cities.add(city);
                                } else {
                                  _cities.remove(city);
                                }
                              });
                              _persist();
                            }
                          : null,
                    ),
                ],
              ),
              if (_cities.isNotEmpty)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: _enabled
                        ? () {
                            setState(() => _cities.clear());
                            _persist();
                          }
                        : null,
                    child: const Text('Rensa ortval (följ bolaget)'),
                  ),
                ),
              const SizedBox(height: 18),
              Text(
                'Vilka händelser?',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: Colors.grey.shade800),
              ),
              const SizedBox(height: 8),
              for (final t in _catalog) ...[
                Material(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(12),
                  child: SwitchListTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                    title: Text(
                      t['label']?.toString() ?? '',
                      style: const TextStyle(fontWeight: FontWeight.w700, color: TbColors.ink),
                    ),
                    subtitle: Text(
                      '${t['short'] ?? ''}\n${t['help'] ?? ''}',
                      style: TextStyle(fontSize: 13, height: 1.35, color: Colors.grey.shade700),
                    ),
                    isThreeLine: true,
                    // A type absent from saved prefs (new device, never
                    // touched this toggle) falls back to the catalog's
                    // default rather than reading as "off" -- otherwise every
                    // fresh install would silently start with zero
                    // notifications, including for the highest-value tier.
                    value: _types[t['id']?.toString()] ?? (t['defaultOn'] == true),
                    activeThumbColor: TbColors.ink,
                    activeTrackColor: TbColors.signal,
                    onChanged: _enabled
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
                      const Text('Tips', style: TextStyle(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 6),
                      for (final tip in _tips)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Text('· $tip', style: TextStyle(fontSize: 13, height: 1.35, color: Colors.grey.shade800)),
                        ),
                    ],
                  ),
                ),
              ],
              if (_saving)
                const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: Center(child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))),
                ),
            ],
          );
        },
      ),
    );
  }
}
