import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../push_service.dart';
import '../signal_kinds.dart';
import '../theme.dart';
import 'settings_ui.dart';

/// Företagets administration i appen: status, bilar, förare och telefoner.
///
/// Byggd på den nya modellen (GET /api/fleet/company): en billicens per bil,
/// län som rättighet, telefoner som godkänns med en engångskod.
///
/// **Inget köps här.** Appen visar vad företaget har och låter ägaren koppla
/// förare och spärra telefoner. Avtal, beställningar och fakturor sköts mellan
/// TaxiTips och företaget, utanför appen -- ett köp av en digital tjänst i appen
/// är det Apple och Google kräver sina egna betalsystem för. Därför finns
/// inga priser, inga köpknappar och inga länkar till betalning i den här filen.
class CompanySettingsPanel extends StatefulWidget {
  const CompanySettingsPanel({super.key, required this.api});

  final ApiClient api;

  @override
  State<CompanySettingsPanel> createState() => _CompanySettingsPanelState();
}

class _CompanySettingsPanelState extends State<CompanySettingsPanel> {
  bool _loading = true;
  String? _error;
  Map<String, dynamic>? _data;
  /// Den här telefonens device-id när den redan är parkopplad. Används för
  /// att dölja "Kör själv …" när telefonen redan står under bilen.
  String? _thisDeviceId;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // En registrering som väntade på att e-posten bekräftades görs klart
      // här, första gången ägaren öppnar sitt företag.
      try {
        await widget.api.completePendingRegistration();
      } on ApiException catch (e) {
        if (mounted) setState(() => _error = e.message);
      }
      final data = await widget.api.fleetCompany();
      String? thisDeviceId;
      if (widget.api.deviceToken != null) {
        try {
          final status = await widget.api.fleetStatus();
          thisDeviceId = status['deviceId']?.toString() ??
              (status['device'] is Map
                  ? (status['device'] as Map)['id']?.toString()
                  : null);
        } catch (_) {
          // Utan device-id visas knappen; parkopplingen fungerar ändå.
        }
      }
      if (!mounted) return;
      setState(() {
        _data = data;
        _thisDeviceId = thisDeviceId;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = _cleanError(e);
      });
    }
  }

  /// True när den här telefonen redan är godkänd för bilen.
  bool _thisPhoneOn(Map<String, dynamic> license) {
    final id = _thisDeviceId;
    if (id == null || id.isEmpty) return false;
    for (final phone in (license['approvedPhones'] as List?) ?? const []) {
      if (phone is Map && phone['deviceId']?.toString() == id) return true;
    }
    return false;
  }

  String _cleanError(Object e) {
    if (e is ApiException) return e.message;
    final raw = e.toString();
    // PostgREST-fel ska aldrig visas råa i UI (t.ex. device_by_token).
    if (raw.contains('PostgrestException') || raw.contains('Postgrest')) {
      return 'Kunde inte läsa företaget just nu. Dra ner för att försöka igen.';
    }
    return raw.replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), '');
  }

  void _snack(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? TbColors.danger : TbColors.live,
      ),
    );
  }

  List<Map<String, dynamic>> get _licenses =>
      ((_data?['licenses'] as List?) ?? const [])
          .whereType<Map>()
          .map((m) => Map<String, dynamic>.from(m))
          .toList();

  Map<String, String> get _countyNames => {
    for (final c in (_data?['countyCatalog'] as List?) ?? const [])
      if (c is Map) c['code'].toString(): countyShort(c['name']?.toString() ?? ''),
  };

  Set<String> get _permissions => {
    for (final p in (_data?['permissions'] as List?) ?? const []) p.toString(),
  };

  bool get _suspended => _data?['company']?['suspended'] == true;

  Map<String, dynamic>? get _trial => _data?['trial'] is Map
      ? Map<String, dynamic>.from(_data!['trial'] as Map)
      : null;

  bool get _trialOpen =>
      _trial != null && ['pending', 'active'].contains(_trial!['status']);

  // ── Status ─────────────────────────────────────────────────────────────

  /// (färg, rubrik, rad) för läget företaget är i. Skälet kommer från servern
  /// (`access.reason`) -- appen räknar inte ut åtkomsten själv.
  (Color, String, String) _status() {
    final access = Map<String, dynamic>.from(_data?['access'] as Map? ?? {});
    final reason = access['reason']?.toString() ?? '';
    final trial = _trial;
    final cars = '${trial?['vehiclesUsed'] ?? 0} av ${trial?['vehicleLimit'] ?? 3} bilar';
    if (_suspended) {
      return (TbColors.danger, 'Avstängt', 'Kontakta oss i chatten.');
    }
    if (trial != null && trial['status'] == 'pending') {
      return (TbColors.taxiDeep, 'Provperiod', 'Startar när första telefonen kopplas · $cars');
    }
    if (access['ok'] == true) {
      if (reason == 'trial') {
        final card = trial?['cardOnFile'] == true;
        final until = _daysLeft(access['validUntil']);
        if (card) {
          return (
            TbColors.live,
            'Provperiod',
            'Kort sparat · auto-förnyelse $until · $cars',
          );
        }
        return (TbColors.taxiDeep, 'Provperiod', '$until · $cars');
      }
      if (reason == 'grace') {
        return (
          TbColors.danger,
          'Betalningen saknas',
          'Tipsen fungerar till ${_date(access['validUntil'])}.',
        );
      }
      final until = _date(access['validUntil']);
      return (TbColors.live, 'Aktivt', until.isEmpty ? '' : 'Förnyas $until');
    }
    if (reason == 'trial_ended') {
      return (TbColors.muted, 'Provet är slut', 'Vi har mejlat hur ni fortsätter.');
    }
    return (TbColors.muted, 'Pausat', access['message']?.toString() ?? '');
  }

  String _daysLeft(Object? iso) {
    final end = DateTime.tryParse(iso?.toString() ?? '')?.toLocal();
    if (end == null) return '';
    final days = end.difference(DateTime.now()).inHours / 24;
    if (days <= 1) return 'Sista dagen';
    return '${days.ceil()} dagar kvar';
  }

  String _date(Object? iso) {
    final d = DateTime.tryParse(iso?.toString() ?? '')?.toLocal();
    if (d == null) return '';
    const months = [
      'jan', 'feb', 'mar', 'apr', 'maj', 'jun',
      'jul', 'aug', 'sep', 'okt', 'nov', 'dec',
    ];
    return '${d.day} ${months[d.month - 1]} ${d.year}';
  }

  // ── Förare: engångskod ─────────────────────────────────────────────────

  Future<void> _connectDriver(Map<String, dynamic> license) async {
    final plate = license['vehicle']?.toString() ?? 'bilen';
    final vehicleId = license['vehicleId']?.toString();
    if (vehicleId == null) {
      _snack('Bilen saknas på licensen. Kontakta support.', isError: true);
      return;
    }
    final nameCtrl = TextEditingController();
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Ny förare i $plate'),
        content: TextField(
          controller: nameCtrl,
          autofocus: true,
          textCapitalization: TextCapitalization.words,
          decoration: const InputDecoration(
            labelText: 'Förarens namn',
            hintText: 'Visas som telefonens namn',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Avbryt'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, nameCtrl.text.trim()),
            child: const Text('Skapa kod'),
          ),
        ],
      ),
    );
    nameCtrl.dispose();
    if (name == null) return;
    try {
      final issued = await widget.api.issuePairingCode(
        licenseId: license['licenseId'].toString(),
        vehicleId: vehicleId,
        label: name.isEmpty ? 'Förare' : name,
      );
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (_) => _PairingCodeDialog(
          code: issued['code']?.toString() ?? '',
          expiresAt: DateTime.tryParse(issued['expiresAt']?.toString() ?? ''),
          subtitle: '${name.isEmpty ? 'Förare' : name} · $plate',
        ),
      );
      if (!mounted) return;
      await _reload();
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  Future<void> _blockPhone(Map<String, dynamic> phone) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Spärra ${phone['label'] ?? 'telefonen'}?'),
        content: const Text(
          'Telefonen slutar visa tips direkt och lämnar bilen. '
          'Föraren behöver en ny kod för att komma in igen.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Avbryt'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: TbColors.danger),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Spärra'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.blockPhone(phone['approvalId'].toString());
      if (!mounted) return;
      await _reload();
      _snack('Telefonen är spärrad');
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  // ── Ägaren kör själv ───────────────────────────────────────────────────

  /// Kopplar DEN HÄR telefonen till bilen, utan att logga ut. Samma
  /// engångskod som för en förare -- skapas och löses in direkt här, så att
  /// godkännandet, spärren och revisionen är desamma. Förut fick ägaren logga
  /// ut, välja "Anslut telefonen" och klistra in sin egen kod (2026-09-26).
  Future<void> _driveMyself(Map<String, dynamic> license) async {
    final plate = license['vehicle']?.toString() ?? 'bilen';
    final vehicleId = license['vehicleId']?.toString();
    if (vehicleId == null) {
      _snack('Bilen saknas på licensen. Kontakta support.', isError: true);
      return;
    }
    try {
      final issued = await widget.api.issuePairingCode(
        licenseId: license['licenseId'].toString(),
        vehicleId: vehicleId,
        label: 'Min telefon',
      );
      final paired = await widget.api.pairWithCode(
        code: issued['code']?.toString() ?? '',
        label: 'Min telefon',
      );
      unawaited(registerForPush(widget.api));
      if (!mounted) return;
      await _reload();
      _snack(
        paired['sessionStarted'] == true
            ? 'Den här telefonen kör nu $plate'
            : 'Telefonen är kopplad till $plate. Välj bilen i listan.',
      );
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  // ── Provbil ────────────────────────────────────────────────────────────

  Future<void> _addTrialCar() async {
    final result = await showDialog<(String, String)>(
      context: context,
      builder: (_) => _AddCarDialog(countyNames: _countyNames),
    );
    if (result == null) return;
    try {
      await widget.api.addTrialVehicle(plate: result.$1, baseCounty: result.$2);
      if (!mounted) return;
      await _reload();
      _snack('${result.$1} är tillagd');
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  // ── Bilens blad ────────────────────────────────────────────────────────

  Future<void> _changeCounty(Map<String, dynamic> license) async {
    final current = license['baseCounty']?.toString();
    final entries = _countyNames.entries.toList()
      ..sort((a, b) => a.value.compareTo(b.value));
    final picked = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: TbColors.foam,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text(
                'Var kör bilen?',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
              ),
            ),
            for (final c in entries)
              ListTile(
                title: Text(c.value),
                trailing: c.key == current
                    ? const Icon(Icons.check, color: TbColors.live)
                    : null,
                onTap: () => Navigator.pop(ctx, c.key),
              ),
          ],
        ),
      ),
    );
    if (picked == null || picked == current) return;
    try {
      await widget.api.setTrialCounty(license['licenseId'].toString(), picked);
      if (!mounted) return;
      await _reload();
      _snack('${license['vehicle']} kör nu i ${_countyNames[picked] ?? picked}');
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  Future<void> _renamePhone(Map<String, dynamic> phone) async {
    final ctrl = TextEditingController(text: phone['label']?.toString() ?? '');
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Förarens namn'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          textCapitalization: TextCapitalization.words,
          decoration: const InputDecoration(hintText: 't.ex. Anna'),
          onSubmitted: (v) => Navigator.pop(ctx, v.trim()),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Avbryt'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
            child: const Text('Spara'),
          ),
        ],
      ),
    );
    ctrl.dispose();
    if (name == null || name.isEmpty) return;
    try {
      await widget.api.renamePhone(phone['approvalId'].toString(), name);
      if (!mounted) return;
      await _reload();
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  Future<void> _removeCar(Map<String, dynamic> license) async {
    final plate = license['vehicle']?.toString() ?? 'bilen';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Ta bort $plate?'),
        content: const Text(
          'Förarna i bilen slutar få tips direkt. Platsen i provet blir ledig.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Avbryt'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: TbColors.danger),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Ta bort'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.removeTrialVehicle(license['licenseId'].toString());
      if (!mounted) return;
      await _reload();
      _snack('$plate är borttagen');
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  String _counties(Map<String, dynamic> license) =>
      ((license['counties'] as List?) ?? const [])
          .map((c) => _countyNames[c.toString()] ?? c.toString())
          .join(', ');

  Future<void> _openCar(Map<String, dynamic> license) async {
    final phones = ((license['approvedPhones'] as List?) ?? const [])
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();
    final activeDevice = license['activePhone'] is Map
        ? (license['activePhone'] as Map)['deviceId']?.toString()
        : null;
    final isTrial = license['status'] == 'trial';
    final canManage = _permissions.contains('manage_devices') && !_suspended;
    final canEditCar =
        isTrial && _permissions.contains('manage_vehicles') && !_suspended;
    final counties = _counties(license);

    void act(BuildContext ctx, Future<void> Function() action) {
      Navigator.pop(ctx);
      action();
    }

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: TbColors.foam,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                license['vehicle']?.toString() ?? 'Bil',
                style: const TextStyle(
                  fontFamily: kDisplayFont,
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 16),
              SettingsGroup(
                children: [
                  SettingsNavRow(
                    icon: Icons.place_outlined,
                    title: counties.isEmpty ? 'Inget län' : counties,
                    subtitle: canEditCar ? 'Tryck för att byta län' : null,
                    trailingIcon: canEditCar
                        ? Icons.chevron_right
                        : Icons.lock_outline,
                    onTap: canEditCar
                        ? () => act(ctx, () => _changeCounty(license))
                        : () {},
                  ),
                ],
              ),
              const SizedBox(height: 16),
              const SettingsGroupLabel('Förare'),
              SettingsGroup(
                children: [
                  for (final phone in phones)
                    ListTile(
                      leading: const Icon(
                        Icons.person_outline,
                        color: TbColors.muted,
                      ),
                      title: Text(
                        phone['deviceId']?.toString() == _thisDeviceId
                            ? 'Den här telefonen'
                            : (phone['label']?.toString() ?? 'Förare'),
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      subtitle: phone['deviceId']?.toString() == activeDevice
                          ? const Text(
                              'Kör nu',
                              style: TextStyle(
                                color: TbColors.live,
                                fontWeight: FontWeight.w700,
                              ),
                            )
                          : (phone['deviceId']?.toString() == _thisDeviceId
                              ? const Text('Redan kopplad')
                              : null),
                      trailing: canManage
                          ? PopupMenuButton<String>(
                              tooltip: 'Mer',
                              onSelected: (choice) => act(
                                ctx,
                                () => choice == 'rename'
                                    ? _renamePhone(phone)
                                    : _blockPhone(phone),
                              ),
                              itemBuilder: (_) => const [
                                PopupMenuItem(
                                  value: 'rename',
                                  child: Text('Byt namn'),
                                ),
                                PopupMenuItem(
                                  value: 'block',
                                  child: Text(
                                    'Spärra telefonen',
                                    style: TextStyle(color: TbColors.danger),
                                  ),
                                ),
                              ],
                            )
                          : null,
                    ),
                  if (phones.isEmpty)
                    const ListTile(
                      leading: Icon(
                        Icons.person_outline,
                        color: TbColors.muted,
                      ),
                      title: Text(
                        'Ingen förare kopplad',
                        style: TextStyle(color: TbColors.muted),
                      ),
                    ),
                ],
              ),
              if (canManage) ...[
                const SizedBox(height: 20),
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: TbColors.taxi,
                    foregroundColor: TbColors.ink,
                    minimumSize: const Size.fromHeight(52),
                  ),
                  onPressed: () => act(ctx, () => _connectDriver(license)),
                  icon: const Icon(Icons.person_add_alt_1),
                  label: const Text(
                    'Koppla en förare',
                    style: TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
                if (!_thisPhoneOn(license)) ...[
                  const SizedBox(height: 10),
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(52),
                    ),
                    onPressed: () => act(ctx, () => _driveMyself(license)),
                    icon: const Icon(Icons.phone_android),
                    label: const Text('Kör själv med den här telefonen'),
                  ),
                ],
              ],
              if (canEditCar) ...[
                const SizedBox(height: 8),
                TextButton(
                  onPressed: () => act(ctx, () => _removeCar(license)),
                  style: TextButton.styleFrom(
                    foregroundColor: TbColors.danger,
                  ),
                  child: const Text('Ta bort bilen'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  // ── Bygget ─────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Center(child: CircularProgressIndicator(color: TbColors.taxi)),
      );
    }
    if (_data == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Banner(
            message: _error ?? 'Kunde inte läsa företaget.',
            color: TbColors.danger,
          ),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: _reload, child: const Text('Försök igen')),
        ],
      );
    }

    final (color, statusTitle, statusLine) = _status();
    final licenses = _licenses;
    final trial = _trial;
    final canAddTrialCar = _trialOpen &&
        !_suspended &&
        _permissions.contains('manage_vehicles') &&
        ((trial?['vehiclesUsed'] as num?) ?? 0) <
            ((trial?['vehicleLimit'] as num?) ?? 3);
    final name = _data?['company']?['name']?.toString() ?? '';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_error != null) ...[
          _Banner(message: _error!, color: TbColors.danger),
          const SizedBox(height: 12),
        ],
        _CompanyHeader(
          name: name,
          status: statusTitle,
          line: statusLine,
          color: color,
        ),
        if (_trialOpen && trial?['cardOnFile'] != true) ...[
          const SizedBox(height: 12),
          _PortalContinueBanner(endsAt: trial?['endsAt']?.toString()),
        ],
        const SizedBox(height: 20),
        const SettingsGroupLabel('Bilar'),
        SettingsGroup(
          children: [
            for (final license in licenses)
              SettingsNavRow(
                icon: Icons.local_taxi_outlined,
                title: license['vehicle']?.toString().isNotEmpty == true
                    ? license['vehicle'].toString()
                    : 'Bil',
                subtitle: _carSubtitle(license),
                onTap: () => _openCar(license),
              ),
            if (licenses.isEmpty && !canAddTrialCar)
              const ListTile(
                leading: Icon(Icons.local_taxi_outlined, color: TbColors.muted),
                title: Text(
                  'Inga bilar',
                  style: TextStyle(color: TbColors.muted),
                ),
              ),
            if (canAddTrialCar)
              SettingsNavRow(
                icon: Icons.add,
                iconColor: TbColors.taxiDeep,
                title: 'Lägg till bil',
                titleColor: TbColors.taxiDeep,
                onTap: _addTrialCar,
              ),
          ],
        ),
      ],
    );
  }

  String _carSubtitle(Map<String, dynamic> license) {
    final counties = _counties(license);
    final phones = (license['approvedPhones'] as List?)?.length ?? 0;
    final active = license['activePhone'] is Map
        ? (license['activePhone'] as Map)['label']?.toString()
        : null;
    final driver = active != null
        ? 'Kör: $active'
        : phones == 0
        ? 'Ingen förare'
        : '$phones förare';
    return [if (counties.isNotEmpty) counties, driver].join(' · ');
  }
}

/// Företagets namn och läge överst i inställningarna: en rad, inget mer.
class _CompanyHeader extends StatelessWidget {
  const _CompanyHeader({
    required this.name,
    required this.status,
    required this.line,
    required this.color,
  });

  final String name;
  final String status;
  final String line;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: TbColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            name.isEmpty ? 'Ditt företag' : name,
            style: const TextStyle(
              fontFamily: kDisplayFont,
              fontSize: 22,
              fontWeight: FontWeight.w800,
              color: TbColors.ink,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(99),
                ),
                child: Text(
                  status,
                  style: TextStyle(
                    color: color,
                    fontWeight: FontWeight.w800,
                    fontSize: 13,
                  ),
                ),
              ),
              if (line.isNotEmpty) ...[
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    line,
                    style: const TextStyle(color: TbColors.muted),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

/// Koden visas stort, med nedräkning: den gäller i fem minuter och bara en
/// gång. Kopiera-knappen finns för den som skickar koden i ett sms.
class _PairingCodeDialog extends StatefulWidget {
  const _PairingCodeDialog({
    required this.code,
    required this.expiresAt,
    required this.subtitle,
  });

  final String code;
  final DateTime? expiresAt;
  final String subtitle;

  @override
  State<_PairingCodeDialog> createState() => _PairingCodeDialogState();
}

class _PairingCodeDialogState extends State<_PairingCodeDialog> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final left = widget.expiresAt == null
        ? 0
        : widget.expiresAt!.difference(DateTime.now()).inSeconds.clamp(0, 3600);
    final expired = widget.expiresAt != null && left == 0;
    return AlertDialog(
      title: const Text('Anslutningskod'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(widget.subtitle, style: const TextStyle(color: TbColors.muted)),
          const SizedBox(height: 16),
          SelectableText(
            widget.code,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontFamily: 'monospace',
              fontSize: 34,
              fontWeight: FontWeight.w800,
              letterSpacing: 4,
              color: expired ? TbColors.muted : TbColors.ink,
              decoration: expired ? TextDecoration.lineThrough : null,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            expired
                ? 'Koden har gått ut. Skapa en ny.'
                : 'Gäller i ${left ~/ 60}:${(left % 60).toString().padLeft(2, '0')}',
            style: TextStyle(
              fontWeight: FontWeight.w700,
              color: expired ? TbColors.danger : TbColors.ink,
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            'Föraren öppnar TaxiTips, väljer "Anslut telefonen" och skriver '
            'in koden. Koden visas bara en gång.',
            textAlign: TextAlign.center,
            style: TextStyle(color: TbColors.muted, height: 1.35),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: expired
              ? null
              : () => Clipboard.setData(ClipboardData(text: widget.code)),
          child: const Text('Kopiera'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Klar'),
        ),
      ],
    );
  }
}

class _AddCarDialog extends StatefulWidget {
  const _AddCarDialog({required this.countyNames});

  final Map<String, String> countyNames;

  @override
  State<_AddCarDialog> createState() => _AddCarDialogState();
}

class _AddCarDialogState extends State<_AddCarDialog> {
  final _plate = TextEditingController();
  String? _county;

  @override
  void dispose() {
    _plate.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final counties = widget.countyNames.entries.toList()
      ..sort((a, b) => a.value.compareTo(b.value));
    final plate = _plate.text.replaceAll(' ', '').toUpperCase();
    return AlertDialog(
      title: const Text('Lägg till bil'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _plate,
            autofocus: true,
            textCapitalization: TextCapitalization.characters,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Registreringsnummer',
              hintText: 'ABC123',
            ),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _county,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Län där bilen kör'),
            items: [
              for (final c in counties)
                DropdownMenuItem(value: c.key, child: Text(c.value)),
            ],
            onChanged: counties.isEmpty
                ? null
                : (v) => setState(() => _county = v),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Avbryt'),
        ),
        FilledButton(
          onPressed: plate.length < 2 || _county == null
              ? null
              : () => Navigator.pop(context, (plate, _county!)),
          child: const Text('Lägg till'),
        ),
      ],
    );
  }
}

/// Informativ länk till kundportalen — inga priser, ingen köpknapp (§9c).
class _PortalContinueBanner extends StatelessWidget {
  const _PortalContinueBanner({this.endsAt});

  final String? endsAt;

  @override
  Widget build(BuildContext context) {
    final until = DateTime.tryParse(endsAt ?? '')?.toLocal();
    final date = until == null
        ? ''
        : ' Provet gäller till '
            '${until.year}-'
            '${until.month.toString().padLeft(2, '0')}-'
            '${until.day.toString().padLeft(2, '0')}.';
    return Material(
      color: TbColors.taxi.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => launchUrl(
          Uri.parse('https://taxitips.se/portal#fortsatt'),
          mode: LaunchMode.externalApplication,
        ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              const Icon(Icons.open_in_new, color: TbColors.taxiDeep, size: 22),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  'Hantera fortsatt åtkomst på taxitips.se/portal.$date',
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    color: TbColors.ink,
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

class _Banner extends StatelessWidget {
  const _Banner({required this.message, required this.color});

  final String message;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Text(
        message,
        style: TextStyle(color: color, fontWeight: FontWeight.w700),
      ),
    );
  }
}
