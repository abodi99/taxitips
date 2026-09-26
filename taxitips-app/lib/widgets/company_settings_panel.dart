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

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
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
      if (!mounted) return;
      setState(() {
        _data = data;
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

  String _cleanError(Object e) {
    if (e is ApiException) return e.message;
    return e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), '');
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

  /// (färg, ikon, rubrik, förklaring) för det läge företaget är i. Skälet kommer
  /// från servern (`access.reason`) -- appen räknar inte ut åtkomsten själv.
  (Color, IconData, String, String) _status() {
    final access = Map<String, dynamic>.from(_data?['access'] as Map? ?? {});
    final reason = access['reason']?.toString() ?? '';
    final until = _date(access['validUntil']);
    final trial = _trial;
    if (_suspended) {
      return (
        TbColors.danger,
        Icons.block,
        'Kontot är avstängt',
        access['message']?.toString() ?? 'Kontakta TaxiTips support.',
      );
    }
    if (trial != null && trial['status'] == 'pending') {
      return (
        TbColors.taxiDeep,
        Icons.hourglass_empty,
        'Provperiod redo',
        '14 dagar gratis. Startar när den första telefonen kopplas. '
            '${trial['vehiclesUsed'] ?? 0} av ${trial['vehicleLimit'] ?? 3} bilar.',
      );
    }
    if (access['ok'] == true) {
      if (reason == 'trial') {
        return (
          TbColors.taxiDeep,
          Icons.hourglass_top_outlined,
          'Provperiod',
          'Gäller till $until. ${trial?['vehiclesUsed'] ?? 0} av '
              '${trial?['vehicleLimit'] ?? 3} bilar.',
        );
      }
      if (reason == 'grace') {
        return (
          TbColors.danger,
          Icons.warning_amber_outlined,
          'Betalningen har inte kommit in',
          'Tipsen fungerar till $until. Kontakta den som sköter er faktura.',
        );
      }
      return (
        TbColors.live,
        Icons.check_circle_outline,
        'Aktivt',
        until.isEmpty ? 'Tipsen är på.' : 'Gäller till $until.',
      );
    }
    if (reason == 'trial_ended') {
      return (
        TbColors.muted,
        Icons.hourglass_bottom,
        'Provperioden är slut',
        'Er kontaktperson på TaxiTips hjälper er att fortsätta.',
      );
    }
    return (
      TbColors.muted,
      Icons.pause_circle_outline,
      'Inte aktivt',
      access['message']?.toString() ?? 'Tipsen är pausade.',
    );
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
          code: issued['code'].toString(),
          expiresAt: DateTime.tryParse(issued['expiresAt']?.toString() ?? ''),
          subtitle: '${name.isEmpty ? 'Förare' : name} · $plate',
        ),
      );
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
        code: issued['code'].toString(),
        label: 'Min telefon',
      );
      unawaited(registerForPush(widget.api));
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
      await _reload();
      _snack('${result.$1} är tillagd');
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  // ── Bilens blad ────────────────────────────────────────────────────────

  Future<void> _openCar(Map<String, dynamic> license) async {
    final phones = ((license['approvedPhones'] as List?) ?? const [])
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();
    final active = license['activePhone'] is Map
        ? Map<String, dynamic>.from(license['activePhone'] as Map)
        : null;
    final counties = ((license['counties'] as List?) ?? const [])
        .map((c) => _countyNames[c.toString()] ?? c.toString())
        .join(', ');
    final canManage = _permissions.contains('manage_devices') && !_suspended;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: TbColors.foam,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  width: 36,
                  height: 4,
                  decoration: BoxDecoration(
                    color: Colors.grey.shade400,
                    borderRadius: BorderRadius.circular(99),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text(
                license['vehicle']?.toString() ?? 'Bil',
                style: const TextStyle(
                  fontFamily: kDisplayFont,
                  fontSize: 24,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                counties.isEmpty ? 'Inga län' : 'Tips i $counties',
                style: const TextStyle(color: TbColors.muted),
              ),
              const SizedBox(height: 16),
              SettingsGroup(
                children: [
                  SettingsInfoRow(
                    icon: Icons.local_taxi_outlined,
                    title: 'Kör nu',
                    value: active == null
                        ? 'Ingen'
                        : active['label']?.toString() ?? 'Förare',
                  ),
                  for (final phone in phones)
                    ListTile(
                      leading: const Icon(
                        Icons.smartphone_outlined,
                        color: TbColors.muted,
                      ),
                      title: Text(
                        phone['label']?.toString() ?? 'Telefon',
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      subtitle: Text('Godkänd ${_date(phone['approvedAt'])}'),
                      trailing: canManage
                          ? TextButton(
                              onPressed: () {
                                Navigator.pop(ctx);
                                _blockPhone(phone);
                              },
                              child: const Text(
                                'Spärra',
                                style: TextStyle(color: TbColors.danger),
                              ),
                            )
                          : null,
                    ),
                  if (phones.isEmpty)
                    const SettingsInfoRow(
                      icon: Icons.smartphone_outlined,
                      title: 'Telefoner',
                      value: 'Ingen kopplad än',
                    ),
                ],
              ),
              const SizedBox(height: 16),
              if (canManage)
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: TbColors.taxi,
                    foregroundColor: TbColors.ink,
                    minimumSize: const Size.fromHeight(52),
                  ),
                  onPressed: () {
                    Navigator.pop(ctx);
                    _connectDriver(license);
                  },
                  icon: const Icon(Icons.person_add_alt_1),
                  label: const Text(
                    'Koppla en förare',
                    style: TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
              if (canManage) ...[
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(52),
                  ),
                  onPressed: () {
                    Navigator.pop(ctx);
                    _driveMyself(license);
                  },
                  icon: const Icon(Icons.phone_android),
                  label: const Text(
                    'Kör bilen själv med den här telefonen',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _openSupport() async {
    final ok = await launchUrl(
      Uri.parse('mailto:hej@taxitips.se?subject=TaxiTips%20support'),
    );
    if (!ok) _snack('Mejla hej@taxitips.se', isError: true);
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

    final (color, icon, title, detail) = _status();
    final licenses = _licenses;
    final trial = _trial;
    final canAddTrialCar = _trialOpen &&
        !_suspended &&
        _permissions.contains('manage_vehicles') &&
        ((trial?['vehiclesUsed'] as num?) ?? 0) <
            ((trial?['vehicleLimit'] as num?) ?? 3);
    final canManage = _permissions.contains('manage_devices') && !_suspended;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_error != null) ...[
          _Banner(message: _error!, color: TbColors.danger),
          const SizedBox(height: 12),
        ],

        const SettingsGroupLabel('Företaget'),
        SettingsGroup(
          children: [
            ListTile(
              leading: Icon(icon, color: color),
              title: Text(
                title,
                style: TextStyle(fontWeight: FontWeight.w800, color: color),
              ),
              subtitle: Text(detail),
            ),
          ],
        ),

        const SizedBox(height: 20),
        const SettingsGroupLabel('Bilar och förare'),
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
            if (licenses.isEmpty)
              SettingsInfoRow(
                icon: Icons.local_taxi_outlined,
                title: 'Inga bilar än',
                value: canAddTrialCar ? 'Lägg till en nedan' : '—',
              ),
            if (canAddTrialCar)
              SettingsNavRow(
                icon: Icons.add_circle_outline,
                iconColor: TbColors.taxiDeep,
                title: 'Lägg till bil i provet',
                subtitle:
                    '${trial?['vehiclesUsed'] ?? 0} av ${trial?['vehicleLimit'] ?? 3} bilar',
                onTap: _addTrialCar,
              ),
          ],
        ),
        if (licenses.isNotEmpty && canManage)
          const Padding(
            padding: EdgeInsets.fromLTRB(4, 8, 4, 0),
            child: Text(
              'Tryck på en bil för att koppla en förare, eller för att köra '
              'den själv med den här telefonen.',
              style: TextStyle(color: TbColors.muted, fontSize: 13, height: 1.35),
            ),
          ),

        const SizedBox(height: 20),
        const SettingsGroupLabel('Support'),
        SettingsGroup(
          children: [
            SettingsNavRow(
              icon: Icons.support_agent_outlined,
              title: 'Kontakta TaxiTips',
              subtitle: 'Fler bilar, kollegor och frågor · hej@taxitips.se',
              trailingIcon: Icons.mail_outline,
              onTap: _openSupport,
            ),
          ],
        ),
      ],
    );
  }

  String _carSubtitle(Map<String, dynamic> license) {
    final counties = ((license['counties'] as List?) ?? const [])
        .map((c) => _countyNames[c.toString()] ?? c.toString())
        .join(', ');
    final phones = (license['approvedPhones'] as List?)?.length ?? 0;
    final active = license['activePhone'] is Map
        ? (license['activePhone'] as Map)['label']?.toString()
        : null;
    final parts = [
      if (counties.isNotEmpty) counties,
      if (license['status'] == 'trial') 'prov',
      active != null
          ? 'kör: $active'
          : '$phones telefon${phones == 1 ? '' : 'er'}',
    ];
    return parts.join(' · ');
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
            onChanged: (v) => setState(() => _county = v),
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
