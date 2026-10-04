import 'dart:async';

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../membership_copy.dart';
import '../push_service.dart';
import '../signal_kinds.dart';
import '../net_status.dart';
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
/// Länbyten kvar för en provbil den här kalendermånaden, ur licensradens
/// `countyChanges` (servern räknar; en gräns per bil och månad).
///
/// `total` är `remaining + used`: det är månadens hela utrymme oavsett om
/// servern lägger extra byten i `limit` eller bredvid den. Null när servern
/// inte skickar fältet (äldre server) -- då visar appen ingen räknare och
/// stänger inget; servern säger själv nej med `county_change_limit`.
class CountyChanges {
  const CountyChanges({required this.remaining, required this.total});

  final int remaining;
  final int total;

  bool get exhausted => remaining <= 0;

  String get label => 'Länbyten kvar den här månaden: $remaining av $total';
}

CountyChanges? countyChangesOf(Map<String, dynamic> license) {
  final raw = license['countyChanges'];
  if (raw is! Map) return null;
  final remaining = (raw['remaining'] as num?)?.toInt();
  if (remaining == null) return null;
  final used = (raw['used'] as num?)?.toInt();
  final limit = (raw['limit'] as num?)?.toInt();
  final left = remaining < 0 ? 0 : remaining;
  final total = used != null ? left + used : (limit ?? left);
  return CountyChanges(remaining: left, total: total < left ? left : total);
}

class CompanySettingsPanel extends StatefulWidget {
  const CompanySettingsPanel({super.key, required this.api, this.onChanged});

  final ApiClient api;

  /// Bilarna eller länen ändrades: Inställningarnas länöversikt och
  /// förarskärmen läser om direkt, i stället för vid nästa uppdatering.
  final VoidCallback? onChanged;

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
          thisDeviceId =
              status['deviceId']?.toString() ??
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
    final net = netFailureOf(e);
    if (net != null) return netMessage(net);
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
      if (c is Map)
        c['code'].toString(): countyShort(c['name']?.toString() ?? ''),
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
    final cars =
        '${trial?['vehiclesUsed'] ?? 0} av ${trial?['vehicleLimit'] ?? 1} ${(trial?['vehicleLimit'] ?? 1) == 1 ? 'bil' : 'bilar'}';
    if (_suspended) {
      return (TbColors.danger, 'Avstängt', 'Kontakta oss i chatten.');
    }
    if (trial != null && trial['status'] == 'pending') {
      return (
        TbColors.taxiDeep,
        'Provperiod',
        'Startar när första telefonen kopplas · $cars',
      );
    }
    if (access['ok'] == true) {
      if (reason == 'trial') {
        final continues = trial?['cardOnFile'] == true;
        final until = _daysLeft(access['validUntil']);
        if (continues) {
          // Inget om kort eller förnyelse: bara att företaget fortsätter.
          return (
            TbColors.live,
            'Provperiod',
            'Medlemskapet fortsätter efter provet · $until · $cars',
          );
        }
        return (TbColors.taxiDeep, 'Provperiod', '$until · $cars');
      }
      if (reason == 'grace') {
        return (
          TbColors.taxiDeep,
          'Medlemskap pausas snart',
          'Tipsen fungerar till ${_date(access['validUntil'])}.',
        );
      }
      final until = _date(access['validUntil']);
      return (TbColors.live, 'Aktivt', until.isEmpty ? '' : 'Förnyas $until');
    }
    if (reason == 'trial_ended') {
      return (TbColors.muted, 'Provet är slut', 'Tipsen är pausade.');
    }
    // Serverns text visas bara för skäl som inte handlar om medlemskap
    // (membershipNotice): en uppmaning att betala hör inte hemma i appen.
    return (
      TbColors.muted,
      'Pausat',
      isMembershipReason(reason)
          ? 'Tipsen är pausade.'
          : membershipNotice(
              reason,
              serverMessage: access['message']?.toString(),
              fallback: '',
            ),
    );
  }

  /// En neutral rad under rubriken när medlemskapet är orsaken till att tipsen
  /// är pausade eller snart pausas. Ingen länk, inget pris, ingen knapp.
  String? get _membershipNote {
    final access = Map<String, dynamic>.from(_data?['access'] as Map? ?? {});
    final reason = access['reason']?.toString();
    return isMembershipReason(reason) || reason == 'grace'
        ? kMembershipOnWeb
        : null;
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
    return '${d.day} ${months[d.month - 1]} ${d.year}';
  }

  // ── Förare: inbjudan med e-post ────────────────────────────────────────

  /// En ny förare: chefen skriver förarens e-post. Föraren får ett mejl,
  /// väljer lösenord och loggar in i appen med e-post och lösenord -- då
  /// kopplas telefonen till bilen med bilens län (fleet/driver_invites.py).
  Future<void> _inviteDriver(Map<String, dynamic> license) async {
    final plate = license['vehicle']?.toString() ?? 'bilen';
    final vehicleId = license['vehicleId']?.toString();
    if (vehicleId == null) {
      _snack('Bilen saknas på licensen. Kontakta support.', isError: true);
      return;
    }
    final result = await showDialog<(String, String)>(
      context: context,
      builder: (_) => _InviteDriverDialog(plate: plate),
    );
    if (result == null) return;
    final (email, name) = result;
    try {
      await widget.api.inviteDriver(
        licenseId: license['licenseId'].toString(),
        vehicleId: vehicleId,
        email: email,
        label: name,
      );
      if (!mounted) return;
      await _reload();
      _snack('Inbjudan skickad till $email');
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  Future<void> _resendInvite(Map<String, dynamic> invite) async {
    try {
      await widget.api.resendDriverInvite(invite['inviteId'].toString());
      if (!mounted) return;
      await _reload();
      _snack('Inbjudan skickad igen till ${invite['email']}');
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  Future<void> _revokeInvite(Map<String, dynamic> invite) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Ta bort inbjudan?'),
        content: Text(
          '${invite['email']} kan inte längre använda inbjudan för att logga in.',
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
      await widget.api.revokeDriverInvite(invite['inviteId'].toString());
      if (!mounted) return;
      await _reload();
      _snack('Inbjudan är borttagen');
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
          'Föraren behöver en ny inbjudan för att komma in igen.',
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
      widget.onChanged?.call();
      _snack('${result.$1} är tillagd');
    } catch (e) {
      _snack(_cleanError(e), isError: true);
    }
  }

  // ── Bilens blad ────────────────────────────────────────────────────────

  Future<void> _changeCounty(Map<String, dynamic> license) async {
    final current = license['baseCounty']?.toString();
    final changes = countyChangesOf(license);
    // Raden är avstängd när inga byten finns kvar; det här är bältet och
    // hängslena, och servern avgör ändå (`county_change_limit`).
    if (changes != null && changes.exhausted) {
      _snack('Inga länbyten kvar den här månaden.', isError: true);
      return;
    }
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
              padding: EdgeInsets.fromLTRB(20, 0, 20, 4),
              child: Text(
                'Var kör bilen?',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
              ),
            ),
            if (changes != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                child: Text(
                  '${changes.label}. Ett byte använder ett av dem.',
                  style: const TextStyle(color: TbColors.muted, height: 1.35),
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
      widget.onChanged?.call();
      _snack(
        '${license['vehicle']} kör nu i ${_countyNames[picked] ?? picked}',
      );
    } on ApiException catch (e) {
      // Gränsen är nådd: serverns svenska text visas som den är, och raden
      // läses om så att räknaren stämmer (och bytet stängs av).
      if (e.reason == 'county_change_limit' && mounted) await _reload();
      _snack(e.message, isError: true);
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
      widget.onChanged?.call();
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
    final invites = ((license['pendingInvites'] as List?) ?? const [])
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
    final changes = countyChangesOf(license);

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
                  // Raden gör något eller säger varför den inte gör det --
                  // ingen tryckyta som inte svarar.
                  if (canEditCar && !(changes?.exhausted ?? false))
                    SettingsNavRow(
                      icon: Icons.place_outlined,
                      title: counties.isEmpty ? 'Inget län' : counties,
                      subtitle: [
                        'Tryck för att byta län',
                        if (changes != null) changes.label,
                      ].join('\n'),
                      onTap: () => act(ctx, () => _changeCounty(license)),
                    )
                  else
                    SettingsInfoRow(
                      icon: Icons.place_outlined,
                      title: counties.isEmpty ? 'Inget län' : counties,
                      value: canEditCar
                          // Inga byten kvar: nästa månad börjar om.
                          ? '${changes!.label}\n'
                                'Du kan byta län igen nästa månad.'
                          : isTrial
                          ? 'Bara en administratör kan byta län.'
                          : 'Länet kan inte bytas i appen.',
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
                  for (final invite in invites)
                    ListTile(
                      leading: const Icon(
                        Icons.mark_email_unread_outlined,
                        color: TbColors.muted,
                      ),
                      title: Text(
                        (invite['label']?.toString().isNotEmpty ?? false)
                            ? invite['label'].toString()
                            : invite['email']?.toString() ?? 'Förare',
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      subtitle: Text(
                        invite['expired'] == true
                            ? 'Inbjudan har gått ut'
                            : 'Inbjuden · har inte loggat in än',
                        style: TextStyle(
                          color: invite['expired'] == true
                              ? TbColors.danger
                              : TbColors.muted,
                        ),
                      ),
                      trailing: canManage
                          ? PopupMenuButton<String>(
                              tooltip: 'Mer',
                              onSelected: (choice) => act(
                                ctx,
                                () => choice == 'resend'
                                    ? _resendInvite(invite)
                                    : _revokeInvite(invite),
                              ),
                              itemBuilder: (_) => const [
                                PopupMenuItem(
                                  value: 'resend',
                                  child: Text('Skicka igen'),
                                ),
                                PopupMenuItem(
                                  value: 'revoke',
                                  child: Text(
                                    'Ta bort inbjudan',
                                    style: TextStyle(color: TbColors.danger),
                                  ),
                                ),
                              ],
                            )
                          : null,
                    ),
                  if (phones.isEmpty && invites.isEmpty)
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
                // Föraren bjuds in med e-post, väljer lösenord via mejlet och
                // loggar in med det (fleet/driver_invites.py).
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: TbColors.taxi,
                    foregroundColor: TbColors.ink,
                    minimumSize: const Size.fromHeight(52),
                  ),
                  onPressed: () => act(ctx, () => _inviteDriver(license)),
                  icon: const Icon(Icons.forward_to_inbox_outlined),
                  label: const Text(
                    'Bjud in förare med e-post',
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
                  style: TextButton.styleFrom(foregroundColor: TbColors.danger),
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
    final canAddTrialCar =
        _trialOpen &&
        !_suspended &&
        _permissions.contains('manage_vehicles') &&
        ((trial?['vehiclesUsed'] as num?) ?? 0) <
            ((trial?['vehicleLimit'] as num?) ?? 1);
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
        if (_membershipNote != null) ...[
          const SizedBox(height: 12),
          _InfoNote(icon: Icons.info_outline, text: _membershipNote!),
        ],
        if (_trialOpen && trial?['cardOnFile'] != true) ...[
          const SizedBox(height: 12),
          _TrialIncludesNote(endsAt: trial?['endsAt']?.toString()),
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
    final invited = (license['pendingInvites'] as List?)?.length ?? 0;
    final driver = active != null
        ? 'Kör: $active'
        : phones == 0
        ? (invited > 0 ? '$invited inbjuden' : 'Ingen förare')
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
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 4,
                ),
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

/// Förarens e-post och (frivilligt) namn. Returnerar (e-post, namn).
class _InviteDriverDialog extends StatefulWidget {
  const _InviteDriverDialog({required this.plate});

  final String plate;

  @override
  State<_InviteDriverDialog> createState() => _InviteDriverDialogState();
}

class _InviteDriverDialogState extends State<_InviteDriverDialog> {
  static final _emailPattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

  final _email = TextEditingController();
  final _name = TextEditingController();
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _name.dispose();
    super.dispose();
  }

  void _send() {
    final email = _email.text.trim();
    if (!_emailPattern.hasMatch(email)) {
      setState(() => _error = 'Skriv förarens e-post, t.ex. namn@exempel.se');
      return;
    }
    Navigator.pop(context, (email, _name.text.trim()));
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Bjud in förare till ${widget.plate}'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Föraren får ett mejl, väljer lösenord och loggar in i appen. '
            'Då kopplas telefonen till bilen.',
            style: TextStyle(color: TbColors.muted, height: 1.35),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _email,
            autofocus: true,
            keyboardType: TextInputType.emailAddress,
            autocorrect: false,
            textInputAction: TextInputAction.next,
            decoration: InputDecoration(
              labelText: 'Förarens e-post',
              errorText: _error,
            ),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _name,
            textCapitalization: TextCapitalization.words,
            onSubmitted: (_) => _send(),
            decoration: const InputDecoration(
              labelText: 'Förarens namn (frivilligt)',
              hintText: 't.ex. Anna',
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Avbryt'),
        ),
        FilledButton(onPressed: _send, child: const Text('Skicka inbjudan')),
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

/// Vad provet omfattar, i neutrala ord. Ingen länk, inget pris, ingen
/// köpknapp, ingen hänvisning till ett mejl om hur man fortsätter: Apple och
/// Google tillåter inte att appen leder till en betalning utanför butikerna
/// (docs/fleet-abonnemang.md §9c, lib/membership_copy.dart). Vilka kategorier
/// som ingår står inte här -- det är serverns (`features`), och i appen syns
/// det som ett lås.
class _TrialIncludesNote extends StatelessWidget {
  const _TrialIncludesNote({this.endsAt});

  final String? endsAt;

  @override
  Widget build(BuildContext context) {
    final until = DateTime.tryParse(endsAt ?? '')?.toLocal();
    final date = until == null
        ? ''
        : 'Provet gäller till '
              '${until.year}-'
              '${until.month.toString().padLeft(2, '0')}-'
              '${until.day.toString().padLeft(2, '0')}. ';
    return _InfoNote(
      icon: Icons.lock_outline,
      text:
          '${date}Det som har ett lås i appen ingår inte i provet. '
          '$kMembershipOnWeb',
    );
  }
}

/// En neutral informationsruta (gul ton) med ikon och text.
class _InfoNote extends StatelessWidget {
  const _InfoNote({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: TbColors.taxi.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: TbColors.taxiDeep, size: 22),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                fontWeight: FontWeight.w600,
                color: TbColors.ink,
              ),
            ),
          ),
        ],
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
