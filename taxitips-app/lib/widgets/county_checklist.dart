import 'package:flutter/material.dart';

import '../api_client.dart';
import '../county_selection.dart';
import '../net_status.dart';
import '../signal_kinds.dart' show countyShort;
import '../theme.dart';

/// En kryssruta per län i licensen -- alla förbockade tills föraren väljer
/// bort något. Används av körområdet på kartan och av "Dina län" i
/// Inställningar, så att båda visar samma sak.
///
/// [selected] tomt = alla licensens län (se lib/county_selection.dart). Det
/// sista förbockade länet går inte att kryssa ur.
class CountyChecklist extends StatelessWidget {
  const CountyChecklist({
    super.key,
    required this.licensed,
    required this.names,
    required this.selected,
    required this.onChanged,
    this.enabled = true,
    this.below,
  });

  /// Länkoderna licensen omfattar, i serverns ordning.
  final List<String> licensed;

  /// Länkod -> namn. Saknas namnet visas koden.
  final Map<String, String> names;

  final Set<String> selected;
  final ValueChanged<Set<String>> onChanged;
  final bool enabled;

  /// Något under ett förbockat län, t.ex. kommunvalet på kartan.
  final Widget? Function(String code)? below;

  @override
  Widget build(BuildContext context) {
    final licensedSet = licensed.toSet();
    final codes = [...licensed]
      ..sort((a, b) => (names[a] ?? a).compareTo(names[b] ?? b));
    final checkedCount = codes.where((c) => countyChecked(selected, c)).length;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final code in codes) ...[
          CheckboxListTile(
            key: ValueKey('county-$code'),
            dense: true,
            contentPadding: const EdgeInsets.symmetric(horizontal: 8),
            controlAffinity: ListTileControlAffinity.leading,
            title: Text(
              names[code] ?? code,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            value: countyChecked(selected, code),
            activeColor: TbColors.taxiDeep,
            // Det sista förbockade länet: ett körområde utan län ger ingen
            // lista och inga notiser.
            onChanged:
                !enabled || (countyChecked(selected, code) && checkedCount <= 1)
                ? null
                : (on) => onChanged(
                    toggleCounty(
                      chosen: selected,
                      code: code,
                      on: on == true,
                      licensed: licensedSet,
                    ),
                  ),
          ),
          if (countyChecked(selected, code) && below != null) ?below!(code),
        ],
      ],
    );
  }
}

/// "Dina län" i Inställningar: en kryssruta per län i licensen.
///
/// Licensens län kommer från servern (`licensedCounties` i
/// `/api/notify-prefs`) varje gång bladet öppnas -- ett län admin just lagt
/// till syns direkt, utan ominstallation. Valet sparas på samma ställe som
/// kartans körområde (lib/county_selection.dart) och skickas till servern som
/// telefonens notisområde, så att listan och notiserna följer samma län.
///
/// [onChangeTrialCounty] finns bara för ett prov: där väljer kunden själv
/// länet (MembershipCountyScreen). En betald eller beviljad plats får sina län
/// av företagets admin, inte i appen.
class CountyPickerSheet extends StatefulWidget {
  const CountyPickerSheet({
    super.key,
    required this.api,
    this.onChangeTrialCounty,
  });

  final ApiClient api;
  final VoidCallback? onChangeTrialCounty;

  @override
  State<CountyPickerSheet> createState() => _CountyPickerSheetState();
}

class _CountyPickerSheetState extends State<CountyPickerSheet> {
  bool _loading = true;
  bool _readOnly = false;
  String? _error;
  List<String> _licensed = const [];
  Map<String, String> _names = const {};
  Set<String> _selected = {};
  Set<String> _municipalities = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Set<String> _codes(Object? raw) => {
    for (final c in (raw is List ? raw : const [])) c.toString(),
  };

  Future<void> _load() async {
    try {
      final data = await widget.api.getNotifyPrefs();
      final stored = await CountySelectionStore.load();
      final licensed = _codes(data['licensedCounties']);
      final prefs = data['prefs'] is Map
          ? Map<String, dynamic>.from(data['prefs'] as Map)
          : <String, dynamic>{};
      var chosen = stored.counties;
      var recorded = stored.licensed;
      var municipalities = stored.municipalities;
      // Ett val från en äldre app saknar anteckningen: serverns sparade
      // område är redan avstämt mot licensen och får avgöra.
      if (recorded == null && chosen.isNotEmpty) {
        final server = _codes(prefs['counties']);
        if (server.isNotEmpty) {
          chosen = server;
          municipalities = _codes(prefs['municipalities']);
          recorded = prefs['entitledCounties'] is List
              ? _codes(prefs['entitledCounties'])
              : licensed;
        }
      }
      final selected = reconcileCounties(
        chosen: chosen,
        licensed: licensed,
        recorded: recorded,
      );
      if (!mounted) return;
      setState(() {
        _licensed = licensed.toList()..sort();
        _names = {
          for (final c in (data['countyCatalog'] as List?) ?? const [])
            if (c is Map && c['code'] != null)
              c['code'].toString(): countyShort(c['name']?.toString() ?? ''),
        };
        _selected = selected;
        _municipalities = keepMunicipalities(
          municipalities,
          chosen: selected,
          licensed: licensed,
        );
        _readOnly = data['readOnly'] == true;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = netAwareText(e);
        _loading = false;
      });
    }
  }

  Future<void> _change(Set<String> next) async {
    final licensed = _licensed.toSet();
    final municipalities = keepMunicipalities(
      _municipalities,
      chosen: next,
      licensed: licensed,
    );
    setState(() {
      _selected = next;
      _municipalities = municipalities;
      _error = null;
    });
    try {
      await CountySelectionStore.save(
        counties: next,
        municipalities: municipalities,
        licensed: licensed,
      );
      if (_readOnly) return;
      await widget.api.saveNotifyPrefs(
        regions: const [],
        cities: const [],
        counties: countiesForServer(next, licensed),
        municipalities: municipalities.toList()..sort(),
      );
    } catch (e) {
      if (mounted) setState(() => _error = netAwareText(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final all = _selected.isEmpty;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 12, 8, 12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(8, 0, 8, 4),
              child: Text(
                'Dina län',
                style: TextStyle(
                  fontFamily: kDisplayFont,
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            if (_loading)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Center(
                  child: CircularProgressIndicator(color: TbColors.taxi),
                ),
              )
            else if (_licensed.isEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 4, 8, 12),
                child: Text(
                  _error ?? 'Medlemskapet har inga län än.',
                  style: const TextStyle(color: TbColors.muted, height: 1.35),
                ),
              )
            else ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
                child: Text(
                  all
                      ? 'Du ser tips från alla län i medlemskapet. Bocka ur '
                            'dem du inte vill se.'
                      : 'Du ser tips från ${_selected.length} av '
                            '${_licensed.length} län.',
                  style: const TextStyle(color: TbColors.muted, height: 1.35),
                ),
              ),
              Flexible(
                child: SingleChildScrollView(
                  child: CountyChecklist(
                    licensed: _licensed,
                    names: _names,
                    selected: _selected,
                    onChanged: (next) => _change(next),
                  ),
                ),
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
                  child: Text(
                    _error!,
                    style: const TextStyle(
                      color: TbColors.danger,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
            ],
            if (widget.onChangeTrialCounty != null && !_loading)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  onPressed: widget.onChangeTrialCounty,
                  child: const Text('Byt provets län'),
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
              child: FilledButton(
                onPressed: () => Navigator.of(context).maybePop(),
                child: const Text('Klar'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
