import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../theme.dart';
import 'settings_ui.dart';

const _primaryCities = [
  'Malmö',
  'Lund',
  'Helsingborg',
  'Kristianstad',
  'Hässleholm',
  'Landskrona',
  'Ystad',
  'Trelleborg',
  'Eslöv',
  'Ängelholm',
];

/// Företagsinställningar i samma liststil som Konto ovanför.
class CompanySettingsPanel extends StatefulWidget {
  const CompanySettingsPanel({super.key, required this.api});

  final ApiClient api;

  @override
  State<CompanySettingsPanel> createState() => _CompanySettingsPanelState();
}

class _CompanySettingsPanelState extends State<CompanySettingsPanel> {
  bool _loading = true;
  String? _error;
  String? _ok;
  Map<String, dynamic>? _me;
  List<String> _catalog = [];
  final Set<String> _selected = {};
  bool _savingAreas = false;
  bool _regenCode = false;
  bool _billingBusy = false;
  Timer? _saveTimer;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void dispose() {
    _saveTimer?.cancel();
    super.dispose();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final me = await widget.api.me();
      final areas = await widget.api.getAreas();
      final watched =
          (areas['watchedAreas'] as List?)?.map((e) => e.toString()).toList() ??
          [];
      final catalog =
          (areas['catalog'] as List?)?.map((e) => e.toString()).toList() ?? [];
      if (!mounted) return;
      setState(() {
        _me = me;
        _catalog = catalog;
        _selected
          ..clear()
          ..addAll(watched);
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

  String _cleanError(Object e) =>
      e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), '');

  void _showSnack(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? TbColors.danger : TbColors.live,
      ),
    );
  }

  String get _areasSummary =>
      _selected.isEmpty ? 'Hela Skåne' : _selected.join(', ');

  bool _showMoreCities = false;

  void _toggleCity(String name) {
    setState(() {
      if (_selected.contains(name)) {
        _selected.remove(name);
      } else {
        _selected.add(name);
      }
      _ok = null;
    });
    _saveTimer?.cancel();
    _saveTimer = Timer(const Duration(milliseconds: 500), _saveAreas);
  }

  Future<void> _saveAreas() async {
    setState(() => _savingAreas = true);
    try {
      await widget.api.saveAreas(_selected.toList());
      if (!mounted) return;
      setState(() {
        _ok = _selected.isEmpty
            ? 'Hela Skåne'
            : '${_selected.length} orter sparade';
      });
    } catch (e) {
      if (mounted) setState(() => _error = _cleanError(e));
    } finally {
      if (mounted) setState(() => _savingAreas = false);
    }
  }

  Future<void> _regenJoinCode() async {
    setState(() {
      _regenCode = true;
      _error = null;
    });
    try {
      final data = await widget.api.regenerateJoinCode();
      if (!mounted) return;
      setState(() {
        final company = Map<String, dynamic>.from(
          _me?['company'] as Map? ?? {},
        );
        company['joinCode'] = data['joinCode'];
        _me = {...?_me, 'company': company};
        _ok = 'Ny bolagskod skapad';
      });
    } catch (e) {
      if (mounted) setState(() => _error = _cleanError(e));
    } finally {
      if (mounted) setState(() => _regenCode = false);
    }
  }

  Future<void> _copyJoinCode(String code) async {
    await Clipboard.setData(ClipboardData(text: code));
    _showSnack('Bolagskod kopierad');
  }

  Future<void> _openAreasSheet() async {
    var showMore = _showMoreCities;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: TbColors.foam,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) {
          final visible = showMore
              ? [
                  ..._primaryCities.where(_catalog.contains),
                  ..._catalog.where((c) => !_primaryCities.contains(c)),
                ]
              : (_primaryCities.where(_catalog.contains).toList().isNotEmpty
                    ? _primaryCities.where(_catalog.contains).toList()
                    : _catalog.take(10).toList());

          return Padding(
            padding: EdgeInsets.fromLTRB(
              16,
              12,
              16,
              16 + MediaQuery.paddingOf(ctx).bottom,
            ),
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
                const Text(
                  'Orter ni kör i',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 6),
                Text(
                  'Inget valt = hela Skåne.',
                  style: TextStyle(color: Colors.grey.shade700),
                ),
                if (_savingAreas)
                  const Padding(
                    padding: EdgeInsets.only(top: 8),
                    child: LinearProgressIndicator(
                      color: TbColors.taxi,
                      minHeight: 3,
                    ),
                  ),
                const SizedBox(height: 12),
                Flexible(
                  child: SingleChildScrollView(
                    child: Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final name in visible)
                          FilterChip(
                            label: Text(
                              name,
                              style: const TextStyle(
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            selected: _selected.contains(name),
                            selectedColor: TbColors.taxi,
                            checkmarkColor: TbColors.ink,
                            onSelected: (_) {
                              _toggleCity(name);
                              setSheetState(() {});
                            },
                          ),
                      ],
                    ),
                  ),
                ),
                TextButton(
                  onPressed: () {
                    setSheetState(() => showMore = !showMore);
                    setState(() => _showMoreCities = showMore);
                  },
                  child: Text(
                    showMore ? 'Visa färre orter' : 'Visa fler orter',
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Future<void> _openJoinCodeSheet(String joinCode, int freeSeats) async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: TbColors.foam,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) => Padding(
        padding: EdgeInsets.fromLTRB(
          16,
          12,
          16,
          16 + MediaQuery.paddingOf(ctx).bottom,
        ),
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
            const Text(
              'Bolagskod till förarna',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 6),
            Text(
              'Föraren öppnar appen → Registrera telefon → anger koden. '
              '${freeSeats > 0 ? '$freeSeats ledig${freeSeats == 1 ? '' : 'a'} plats${freeSeats == 1 ? '' : 'er'}.' : 'Inga lediga platser — använd byteskod för att byta telefon.'}',
              style: TextStyle(color: Colors.grey.shade700, height: 1.35),
            ),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: TbColors.taxi.withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: TbColors.taxiDeep),
              ),
              child: Text(
                joinCode,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 5,
                ),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () {
                      _copyJoinCode(joinCode);
                      Navigator.pop(ctx);
                    },
                    icon: const Icon(Icons.copy),
                    label: const Text('Kopiera'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton(
                    onPressed: _regenCode
                        ? null
                        : () async {
                            await _regenJoinCode();
                            if (ctx.mounted) Navigator.pop(ctx);
                          },
                    child: Text(_regenCode ? '…' : 'Ny kod'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _makeTransfer(Map<String, dynamic> device) async {
    try {
      final data = await widget.api.createTransferCode(device['id'].toString());
      if (!mounted) return;
      final code = data['code']?.toString() ?? '';
      final label = device['label']?.toString() ?? 'Telefon';
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text('Byteskod för $label'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                code,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 4,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Ange på den nya telefonen under “Byt telefon”. Gäller 30 min.',
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () {
                Clipboard.setData(ClipboardData(text: code));
                _showSnack('Byteskod kopierad');
              },
              child: const Text('Kopiera'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Stäng'),
            ),
          ],
        ),
      );
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    }
  }

  Future<void> _deleteDevice(String id) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Ta bort telefon?'),
        content: const Text(
          'Platsen frigörs. Föraren kan registrera en ny med bolagskoden.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Nej'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Ja, ta bort'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.deleteDevice(id);
      await _reload();
      _showSnack('Telefon borttagen');
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    }
  }

  Future<void> _addMember() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => _MemberDialog(api: widget.api),
    );
    if (ok == true) {
      await _reload();
      _showSnack('Medlem tillagd — inbjudan skickad');
    }
  }

  Future<void> _openUsersSheet(
    List<Map<String, dynamic>> devices,
    List<Map<String, dynamic>> members,
    String joinCode,
    int freeSeats,
  ) async {
    const roleSv = {
      'company_owner': 'Ägare',
      'company_admin': 'Admin',
      'driver': 'Förare',
    };
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: TbColors.foam,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) => FractionallySizedBox(
        heightFactor: 0.86,
        child: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
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
                    const Text(
                      'Hantera användare',
                      style: TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    Text(
                      '${members.length} admin${members.length == 1 ? '' : 'er'} · ${devices.length} förare',
                      style: TextStyle(color: Colors.grey.shade700),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                  children: [
                    SettingsGroup(
                      children: [
                        SettingsNavRow(
                          icon: Icons.vpn_key_outlined,
                          title: 'Bolagskod',
                          subtitle: '$joinCode · $freeSeats lediga platser',
                          trailing: IconButton(
                            tooltip: 'Kopiera',
                            icon: const Icon(Icons.copy, size: 20),
                            onPressed: joinCode == '—'
                                ? null
                                : () => _copyJoinCode(joinCode),
                          ),
                          onTap: () => _openJoinCodeSheet(joinCode, freeSeats),
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),
                    const SettingsGroupLabel('Admins'),
                    SettingsGroup(
                      children: [
                        for (final m in members)
                          ListTile(
                            leading: Icon(
                              m['role'] == 'company_owner'
                                  ? Icons.star_outline
                                  : Icons.person_outline,
                              color: TbColors.muted,
                            ),
                            title: Text(
                              (m['name']?.toString().isNotEmpty ?? false)
                                  ? m['name'].toString()
                                  : (m['email']?.toString() ?? '—'),
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            subtitle: Text(
                              '${m['email']} · ${roleSv[m['role']] ?? m['role']}',
                            ),
                            trailing: m['role'] != 'company_owner'
                                ? IconButton(
                                    tooltip: 'Ta bort admin',
                                    icon: const Icon(
                                      Icons.person_remove_outlined,
                                      color: TbColors.danger,
                                    ),
                                    onPressed: () async {
                                      Navigator.pop(ctx);
                                      await _removeMember(
                                        m['userId'].toString(),
                                      );
                                    },
                                  )
                                : null,
                          ),
                        SettingsNavRow(
                          icon: Icons.person_add_outlined,
                          title: 'Lägg till admin',
                          subtitle: 'Bjud in kollega till kontoret',
                          onTap: () async {
                            Navigator.pop(ctx);
                            await _addMember();
                          },
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),
                    const SettingsGroupLabel('Förare och enheter'),
                    SettingsGroup(
                      children: [
                        if (devices.isEmpty)
                          const SettingsInfoRow(
                            icon: Icons.smartphone_outlined,
                            title: 'Inga telefoner',
                            value: 'Ge bolagskoden till föraren',
                          ),
                        for (final d in devices)
                          ListTile(
                            leading: const Icon(
                              Icons.smartphone_outlined,
                              color: TbColors.muted,
                            ),
                            title: Text(
                              d['label']?.toString() ?? 'Telefon',
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            subtitle: Text(
                              '${d['hasPush'] == true ? 'Redo' : 'Öppnad'} · ${d['swapsRemainingThisMonth'] ?? 2} byte kvar i månaden',
                            ),
                            trailing: PopupMenuButton<String>(
                              onSelected: (value) async {
                                Navigator.pop(ctx);
                                if (value == 'transfer') {
                                  await _makeTransfer(d);
                                } else if (value == 'delete') {
                                  await _deleteDevice(d['id'].toString());
                                }
                              },
                              itemBuilder: (_) => const [
                                PopupMenuItem(
                                  value: 'transfer',
                                  child: Text('Byt telefon (byteskod)'),
                                ),
                                PopupMenuItem(
                                  value: 'delete',
                                  child: Text('Ta bort telefon'),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _removeMember(String userId) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Ta bort medlem?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Nej'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Ja, ta bort'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.removeMember(userId);
      await _reload();
      _showSnack('Medlem borttagen');
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    }
  }

  String _billingStatusLabel() {
    final company = _me?['company'] as Map<String, dynamic>? ?? {};
    final billing = _me?['billing'] as Map<String, dynamic>? ?? {};
    if (company['status'] == 'owner') return 'Ägare · gratis';
    final status = company['status']?.toString() ?? '';
    final trialEnd = billing['trialEndsAt'] ?? company['trialEndsAt'];
    if (status == 'trial' && trialEnd is num) {
      final days =
          ((trialEnd - DateTime.now().millisecondsSinceEpoch) / 86400000)
              .ceil();
      return 'Provperiod · $days dag${days == 1 ? '' : 'ar'} kvar';
    }
    if (status == 'active') return 'Aktivt medlemskap';
    if (status == 'past_due') return 'Betalning saknas';
    if (status == 'canceled') return 'Avslutas vid periodens slut';
    return 'Ej aktivt medlemskap';
  }

  Future<void> _openBillingPortal() async {
    setState(() => _billingBusy = true);
    try {
      final data = await widget.api.billingPortal();
      final url = data['url']?.toString();
      if (url != null && url.isNotEmpty) {
        await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
      }
    } catch (_) {
      _showSnack(
        'Starta först medlemskapet — sedan kan du hantera betalningen.',
        isError: true,
      );
    } finally {
      if (mounted) setState(() => _billingBusy = false);
    }
  }

  Future<void> _changeSeats() async {
    final seats = await showDialog<int>(
      context: context,
      builder: (_) => _SeatsDialog(
        initialSeats: (_me?['company']?['seats'] ?? 1).toString(),
      ),
    );
    if (seats == null || seats < 1) return;
    setState(() => _billingBusy = true);
    try {
      await widget.api.updateBillingQuantity(seats);
      await _reload();
      _showSnack('Antal enheter uppdaterat');
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    } finally {
      if (mounted) setState(() => _billingBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Center(child: CircularProgressIndicator(color: TbColors.taxi)),
      );
    }

    final company = _me?['company'] as Map<String, dynamic>?;
    final devices =
        (_me?['devices'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    final members =
        (_me?['members'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    final joinCode = company?['joinCode']?.toString() ?? '—';
    final seats = company?['seats'] is num
        ? (company!['seats'] as num).toInt()
        : 1;
    final freeSeats = seats - devices.length;
    final billing = _me?['billing'] as Map<String, dynamic>? ?? {};
    final hasSubscription = billing['subscription'] != null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_error != null) ...[
          _StatusBanner(message: _error!, color: TbColors.danger),
          const SizedBox(height: 12),
        ],
        if (_ok != null) ...[
          _StatusBanner(message: _ok!, color: TbColors.live),
          const SizedBox(height: 12),
        ],
        const SettingsGroupLabel('Medlemskap'),
        SettingsGroup(
          children: [
            SettingsInfoRow(
              icon: Icons.card_membership_outlined,
              title: 'Status',
              value: _billingStatusLabel(),
            ),
            SettingsNavRow(
              icon: Icons.credit_card_outlined,
              title: hasSubscription
                  ? 'Hantera betalning'
                  : 'Starta medlemskap',
              onTap: _billingBusy ? () {} : _openBillingPortal,
            ),
            SettingsNavRow(
              icon: Icons.phone_android_outlined,
              title: 'Antal bilar och telefoner',
              subtitle: '${devices.length}/$seats bilar',
              onTap: _billingBusy ? () {} : _changeSeats,
            ),
          ],
        ),
        const SizedBox(height: 20),
        const SettingsGroupLabel('Företag'),
        SettingsGroup(
          children: [
            SettingsNavRow(
              icon: Icons.location_on_outlined,
              title: 'Orter ni kör i',
              subtitle: _areasSummary,
              onTap: _openAreasSheet,
            ),
            SettingsNavRow(
              icon: Icons.manage_accounts_outlined,
              title: 'Hantera användare',
              subtitle:
                  '${members.length} admin${members.length == 1 ? '' : 'er'} · ${devices.length} förare',
              onTap: () =>
                  _openUsersSheet(devices, members, joinCode, freeSeats),
            ),
          ],
        ),
      ],
    );
  }
}

class _SeatsDialog extends StatefulWidget {
  const _SeatsDialog({required this.initialSeats});

  final String initialSeats;

  @override
  State<_SeatsDialog> createState() => _SeatsDialogState();
}

class _SeatsDialogState extends State<_SeatsDialog> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialSeats);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Antal bilar/mobiler'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: _controller,
            keyboardType: TextInputType.number,
            autofocus: true,
            decoration: const InputDecoration(labelText: 'Antal bilar'),
          ),
          const SizedBox(height: 12),
          Text(
            'Pris per månad:\n1–3 bilar: 199 kr/bil\n4–10 bilar: 179 kr/bil\n11+ bilar: 149 kr/bil',
            style: TextStyle(color: Colors.grey.shade700, height: 1.4),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Avbryt'),
        ),
        FilledButton(
          onPressed: () =>
              Navigator.pop(context, int.tryParse(_controller.text) ?? 0),
          child: const Text('Spara'),
        ),
      ],
    );
  }
}

class _MemberDialog extends StatefulWidget {
  const _MemberDialog({required this.api});

  final ApiClient api;

  @override
  State<_MemberDialog> createState() => _MemberDialogState();
}

class _MemberDialogState extends State<_MemberDialog> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final email = _email.text.trim();
    if (email.isEmpty) {
      setState(() => _error = 'Fyll i e-post.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.addMember(email: email, name: _name.text.trim());
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = e.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Lägg till admin'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _name,
            decoration: const InputDecoration(labelText: 'Namn (valfritt)'),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _email,
            keyboardType: TextInputType.emailAddress,
            autofocus: true,
            decoration: const InputDecoration(labelText: 'E-post'),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(
              _error!,
              style: const TextStyle(
                color: TbColors.danger,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.pop(context, false),
          child: const Text('Avbryt'),
        ),
        FilledButton(
          onPressed: _busy ? null : _submit,
          child: Text(_busy ? '…' : 'Bjud in'),
        ),
      ],
    );
  }
}

class _StatusBanner extends StatelessWidget {
  const _StatusBanner({required this.message, required this.color});

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
