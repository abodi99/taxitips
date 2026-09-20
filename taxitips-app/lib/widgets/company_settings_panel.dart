import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../theme.dart';
import 'brand_icons.dart';
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

/// En plats i abonnemanget = en förartelefon som får vara kopplad samtidigt.
/// Ägare/admin loggar in med e-post och räknas inte som plats.
const _seatsExplainShort =
    'En plats = en förartelefon som kan vara kopplad samtidigt. '
    'Ni betalar för telefonplatser, inte för bilar.';

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
      _selected.isEmpty ? 'Inga standardorter valda' : _selected.join(', ');

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
                  'Bolagets standardorter',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 6),
                Text(
                  'Valfritt — påverkar ortkatalogen. Förarens länsfilter '
                  '(Skåne, Stockholm …) och notiser styrs från huvudskärmen.',
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
                                fontWeight: FontWeight.w700,
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
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 6),
            Text(
              'Föraren öppnar appen → Registrera telefon → anger koden. '
              '${freeSeats > 0 ? '$freeSeats ledig${freeSeats == 1 ? '' : 'a'} plats${freeSeats == 1 ? '' : 'er'} kvar.' : 'Inga lediga platser — ta bort en telefon eller öka antalet platser, alternativt använd byteskod för att byta telefon.'}',
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
                  fontWeight: FontWeight.w700,
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
                  fontWeight: FontWeight.w700,
                  letterSpacing: 4,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Ange på den nya telefonen under “Byt telefon”. Gäller 30 min. '
                'Platsen flyttas — ni behöver ingen extra plats.',
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
      _showSnack('Telefon borttagen — platsen är ledig');
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    }
  }

  Future<void> _inviteAdminViaMail() async {
    final company = _me?['company'] as Map<String, dynamic>? ?? {};
    final name = company['name']?.toString() ?? 'bolaget';
    final uri = Uri.parse(
      'mailto:hej@taxitips.se'
      '?subject=${Uri.encodeComponent('Bjud in admin — $name')}'
      '&body=${Uri.encodeComponent(
        'Hej!\n\nVi vill bjuda in en kollega som admin till $name.\n'
        'E-post till den som ska bjudas in: \n\nTack!',
      )}',
    );
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Bjud in kollega'),
        content: const Text(
          'Ägare och admins loggar in med e-post — de tar ingen plats i '
          'abonnemanget. Just nu skapas nya inloggningar via support '
          '(webbportalen saknar ännu egen inbjudan).',
          style: TextStyle(height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Avbryt'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Mejla support'),
          ),
        ],
      ),
    );
    if (ok == true) {
      await launchUrl(uri);
    }
  }

  Future<void> _openTeamSheet(
    List<Map<String, dynamic>> devices,
    List<Map<String, dynamic>> members,
    String joinCode,
    int seats,
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
        heightFactor: 0.88,
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
                      'Team',
                      style: TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${members.length} inloggad${members.length == 1 ? '' : 'e'} · '
                      '${devices.length} av $seats förartelefon'
                      '${seats == 1 ? '' : 'er'}',
                      style: TextStyle(color: Colors.grey.shade700),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Inloggade (ägare/admin) tar ingen plats. '
                      'Varje förartelefon tar en plats.',
                      style: TextStyle(
                        color: Colors.grey.shade600,
                        fontSize: 13,
                        height: 1.35,
                      ),
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
                          subtitle: freeSeats > 0
                              ? '$joinCode · $freeSeats ledig'
                                    '${freeSeats == 1 ? '' : 'a'} '
                                    'plats${freeSeats == 1 ? '' : 'er'}'
                              : '$joinCode · fullt — öka platser eller byt telefon',
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
                    const SettingsGroupLabel('Alla i teamet'),
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
                                  : ((m['email']?.toString().isNotEmpty ??
                                          false)
                                      ? m['email'].toString()
                                      : 'Admin'),
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            subtitle: Text(
                              [
                                if ((m['email']?.toString().isNotEmpty ??
                                        false) &&
                                    (m['name']?.toString().isNotEmpty ??
                                        false))
                                  m['email'],
                                'Inloggning · tar ingen plats',
                              ].join(' · '),
                            ),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                _RoleChip(
                                  label: roleSv[m['role']] ??
                                      m['role']?.toString() ??
                                      'Admin',
                                ),
                                if (m['role'] != 'company_owner')
                                  IconButton(
                                    tooltip: 'Ta bort',
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
                                  ),
                              ],
                            ),
                          ),
                        if (devices.isEmpty)
                          const SettingsInfoRow(
                            icon: Icons.smartphone_outlined,
                            title: 'Inga förartelefoner ännu',
                            value: 'Dela bolagskoden så kopplar föraren sin telefon',
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
                              '${d['hasPush'] == true ? 'Redo för notiser' : 'Öppnad'} · '
                              '${d['swapsRemainingThisMonth'] ?? 2} byte kvar i månaden · '
                              '1 plats',
                            ),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const _RoleChip(label: 'Förare'),
                                PopupMenuButton<String>(
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
                              ],
                            ),
                          ),
                        SettingsNavRow(
                          icon: Icons.person_add_outlined,
                          title: 'Bjud in kollega (admin)',
                          subtitle: 'Via support — tar ingen plats',
                          onTap: () async {
                            Navigator.pop(ctx);
                            await _inviteAdminViaMail();
                          },
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
        content: const Text(
          'Personen kan inte längre logga in som admin. '
          'Förartelefoner påverkas inte.',
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
      await widget.api.removeMember(userId);
      await _reload();
      _showSnack('Medlem borttagen');
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    }
  }

  bool get _hasSubscription {
    final billing = _me?['billing'] as Map<String, dynamic>? ?? {};
    if (billing['hasSubscription'] == true) return true;
    final company = _me?['company'] as Map<String, dynamic>? ?? {};
    final id =
        company['stripeSubscriptionId'] ?? company['stripe_subscription_id'];
    return id != null && id.toString().isNotEmpty;
  }

  String _billingStatusLabel() {
    final company = _me?['company'] as Map<String, dynamic>? ?? {};
    final billing = _me?['billing'] as Map<String, dynamic>? ?? {};
    final status =
        (billing['status'] ?? company['status'])?.toString() ?? '';
    final subStatus =
        (billing['subscriptionStatus'] ??
                company['subscriptionStatus'] ??
                company['subscription_status'])
            ?.toString() ??
        '';

    if (status == 'trial') return 'Provperiod · aktiv';
    if (status == 'active' || subStatus == 'active') {
      return 'Aktivt medlemskap';
    }
    if (status == 'past_due' || subStatus == 'past_due') {
      return 'Betalning saknas — tips pausade';
    }
    if (status == 'canceled' ||
        subStatus == 'canceled' ||
        subStatus == 'unpaid') {
      return 'Uppsagt — tips pausade';
    }
    if (_hasSubscription) return 'Medlemskap registrerat';
    return 'Ej aktivt medlemskap';
  }

  /// Starta = Stripe Checkout. Hantera/avsluta = Customer Portal.
  Future<void> _startOrManageMembership() async {
    setState(() => _billingBusy = true);
    try {
      final seats = (_me?['company']?['seats'] is num)
          ? (_me!['company']['seats'] as num).toInt()
          : 1;
      final data = _hasSubscription
          ? await widget.api.billingPortal()
          : await widget.api.createCheckoutSession(seats: seats);
      final url = data['url']?.toString();
      if (url == null || url.isEmpty) {
        _showSnack('Kunde inte öppna Stripe.', isError: true);
        return;
      }
      await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
      if (!_hasSubscription) {
        _showSnack(
          'När du betalat: dra ner för att uppdatera status.',
        );
      }
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    } finally {
      if (mounted) setState(() => _billingBusy = false);
    }
  }

  Future<void> _changeSeats() async {
    final deviceCount = (_me?['devices'] as List?)?.length ?? 0;
    final seats = await showDialog<int>(
      context: context,
      builder: (_) => _SeatsDialog(
        initialSeats: (_me?['company']?['seats'] is num)
            ? (_me!['company']['seats'] as num).toInt()
            : 1,
        deviceCount: deviceCount,
      ),
    );
    if (seats == null || seats < 1) return;
    if (seats < deviceCount) {
      _showSnack(
        'Ta bort ${deviceCount - seats} telefon'
        '${deviceCount - seats == 1 ? '' : 'er'} först.',
        isError: true,
      );
      return;
    }
    setState(() => _billingBusy = true);
    try {
      final res = await widget.api.updateBillingQuantity(seats);
      await _reload();
      if (res['synced'] == true) {
        _showSnack(
          seats == 1
              ? '1 plats uppdaterad i Stripe'
              : '$seats platser uppdaterade i Stripe',
        );
      } else if (_hasSubscription) {
        _showSnack(
          'Sparat lokalt — synka Stripe via Hantera betalning om beloppet ser fel ut',
          isError: true,
        );
      } else {
        _showSnack('Platser sparade (gäller när ni startar medlemskap)');
      }
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    } finally {
      if (mounted) setState(() => _billingBusy = false);
    }
  }

  Future<void> _openSupport() async {
    final choice = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Support'),
        content: const Text(
          'Kontakta oss via mejl eller öppna kontaktsidan på webben.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Avbryt'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, 'web'),
            child: const Text('Webb'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, 'mail'),
            child: const Text('Mejla'),
          ),
        ],
      ),
    );
    if (choice == 'mail') {
      await launchUrl(
        Uri.parse('mailto:hej@taxitips.se?subject=TaxiTips%20support'),
      );
    } else if (choice == 'web') {
      await launchUrl(
        Uri.parse('https://taxitips.se/#kontakt'),
        mode: LaunchMode.externalApplication,
      );
    }
  }

  (Color, IconData) _statusColorAndIcon() {
    final company = _me?['company'] as Map<String, dynamic>? ?? {};
    final billing = _me?['billing'] as Map<String, dynamic>? ?? {};
    final status =
        (billing['status'] ?? company['status'])?.toString() ?? '';
    final subStatus =
        (billing['subscriptionStatus'] ??
                company['subscriptionStatus'] ??
                company['subscription_status'])
            ?.toString() ??
        '';
    if (status == 'trial') {
      return (TbColors.taxiDeep, Icons.hourglass_top_outlined);
    }
    if (status == 'active' || subStatus == 'active') {
      return (TbColors.live, Icons.check_circle_outline);
    }
    if (status == 'past_due' || subStatus == 'past_due') {
      return (TbColors.danger, Icons.warning_amber_outlined);
    }
    if (status == 'canceled' ||
        subStatus == 'canceled' ||
        subStatus == 'unpaid') {
      return (TbColors.muted, Icons.cancel_outlined);
    }
    if (_hasSubscription) return (TbColors.live, Icons.check_circle_outline);
    return (TbColors.muted, Icons.radio_button_unchecked);
  }

  String _statusChipLabel() {
    final company = _me?['company'] as Map<String, dynamic>? ?? {};
    final billing = _me?['billing'] as Map<String, dynamic>? ?? {};
    final status =
        (billing['status'] ?? company['status'])?.toString() ?? '';
    final subStatus =
        (billing['subscriptionStatus'] ??
                company['subscriptionStatus'] ??
                company['subscription_status'])
            ?.toString() ??
        '';
    if (status == 'trial') return 'Provperiod';
    if (status == 'active' || subStatus == 'active') return 'Aktivt';
    if (status == 'past_due' || subStatus == 'past_due') return 'Obetalt';
    if (status == 'canceled' ||
        subStatus == 'canceled' ||
        subStatus == 'unpaid') {
      return 'Uppsagt';
    }
    if (_hasSubscription) return 'Aktivt';
    return 'Ej aktivt';
  }

  List<Widget> _buildMembershipWarningBanner() {
    final company = _me?['company'] as Map<String, dynamic>? ?? {};
    final billing = _me?['billing'] as Map<String, dynamic>? ?? {};
    final status =
        (billing['status'] ?? company['status'])?.toString() ?? '';
    final subStatus =
        (billing['subscriptionStatus'] ??
                company['subscriptionStatus'] ??
                company['subscription_status'])
            ?.toString() ??
        '';
    if (status == 'past_due' || subStatus == 'past_due') {
      return [
        const _StatusBanner(
          message:
              'Betalning saknas — tipsen är pausade. '
              'Uppdatera kortuppgifterna via "Hantera / avsluta betalning".',
          color: TbColors.danger,
        ),
        const SizedBox(height: 12),
      ];
    }
    if (status == 'canceled' ||
        subStatus == 'canceled' ||
        subStatus == 'unpaid') {
      return [
        const _StatusBanner(
          message:
              'Abonnemanget är uppsagt — tipsen är pausade. '
              'Starta ett nytt för att återaktivera.',
          color: TbColors.muted,
        ),
        const SizedBox(height: 12),
      ];
    }
    return const [];
  }

  String _seatsSubtitle(int used, int seats, int free) {
    final base =
        '$used av $seats plats${seats == 1 ? '' : 'er'} med förartelefon';
    if (free > 0) {
      return '$base · $free ledig${free == 1 ? '' : 'a'}';
    }
    return '$base · fullt';
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
    final freeSeats = (seats - devices.length).clamp(0, seats);
    final (statusColor, statusIcon) = _statusColorAndIcon();
    final fill = seats <= 0 ? 0.0 : (devices.length / seats).clamp(0.0, 1.0);

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
        ..._buildMembershipWarningBanner(),

        // ── MEDLEMSKAP ─────────────────────────────────────────────────
        const SettingsGroupLabel('Medlemskap'),
        SettingsGroup(
          children: [
            ListTile(
              leading: Icon(statusIcon, color: statusColor),
              title: const Text(
                'Status',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
              subtitle: Text(_billingStatusLabel()),
              trailing: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 4,
                ),
                decoration: BoxDecoration(
                  color: statusColor.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(
                    color: statusColor.withValues(alpha: 0.35),
                  ),
                ),
                child: Text(
                  _statusChipLabel(),
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: statusColor,
                  ),
                ),
              ),
            ),
            SettingsNavRow(
              icon: Icons.credit_card_outlined,
              title: _hasSubscription
                  ? 'Hantera / avsluta betalning'
                  : 'Starta medlemskap',
              subtitle: _hasSubscription
                  ? 'Stripe — kort, faktura, uppsägning'
                  : 'Stripe Checkout · betala per förartelefonplats',
              onTap: _billingBusy ? () {} : _startOrManageMembership,
            ),
          ],
        ),

        const SizedBox(height: 20),

        // ── PLATSER ────────────────────────────────────────────────────
        const SettingsGroupLabel('Platser'),
        SettingsGroup(
          children: [
            ListTile(
              leading: const Icon(
                Icons.smartphone_outlined,
                color: TbColors.muted,
              ),
              title: const Text(
                'Förartelefoner i abonnemanget',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 4),
                  Text(_seatsSubtitle(devices.length, seats, freeSeats)),
                  const SizedBox(height: 8),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(
                      value: fill,
                      minHeight: 6,
                      backgroundColor: TbColors.line,
                      color: freeSeats == 0 && devices.isNotEmpty
                          ? TbColors.taxiDeep
                          : TbColors.taxi,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _seatsExplainShort,
                    style: TextStyle(
                      color: Colors.grey.shade600,
                      fontSize: 12,
                      height: 1.35,
                    ),
                  ),
                ],
              ),
              isThreeLine: true,
              trailing: const Icon(Icons.chevron_right, size: 20),
              onTap: _billingBusy ? null : _changeSeats,
            ),
          ],
        ),

        const SizedBox(height: 20),

        // ── TEAM ───────────────────────────────────────────────────────
        const SettingsGroupLabel('Team'),
        SettingsGroup(
          children: [
            SettingsNavRow(
              icon: Icons.groups_outlined,
              title: 'Hantera team',
              subtitle: members.isEmpty && devices.isEmpty
                  ? 'Bolagskod, admins och förartelefoner'
                  : '${members.length + devices.length} i teamet · '
                      '${freeSeats > 0 ? '$freeSeats lediga platser' : 'inga lediga platser'}',
              onTap: () => _openTeamSheet(
                devices,
                members,
                joinCode,
                seats,
                freeSeats,
              ),
            ),
          ],
        ),

        const SizedBox(height: 20),

        // ── STANDARDORTER ──────────────────────────────────────────────
        const SettingsGroupLabel('Standardorter'),
        SettingsGroup(
          children: [
            SettingsNavRow(
              icon: BrandIcons.office(size: 24, color: TbColors.muted),
              title: 'Bolagets standardorter',
              subtitle:
                  '$_areasSummary · förarens filter sätts på huvudskärmen',
              onTap: _openAreasSheet,
            ),
          ],
        ),

        const SizedBox(height: 20),

        // ── SUPPORT ────────────────────────────────────────────────────
        const SettingsGroupLabel('Support'),
        SettingsGroup(
          children: [
            SettingsNavRow(
              icon: Icons.support_agent_outlined,
              title: 'Kontakta oss',
              subtitle: 'hej@taxitips.se · taxitips.se',
              trailingIcon: Icons.open_in_new,
              onTap: _openSupport,
            ),
          ],
        ),
      ],
    );
  }
}

class _RoleChip extends StatelessWidget {
  const _RoleChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(right: 4),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: TbColors.midnatt.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: TbColors.line),
      ),
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: TbColors.skiffer,
        ),
      ),
    );
  }
}

class _SeatsDialog extends StatefulWidget {
  const _SeatsDialog({
    required this.initialSeats,
    required this.deviceCount,
  });

  final int initialSeats;
  final int deviceCount;

  @override
  State<_SeatsDialog> createState() => _SeatsDialogState();
}

class _SeatsDialogState extends State<_SeatsDialog> {
  late int _seats;

  @override
  void initState() {
    super.initState();
    _seats = widget.initialSeats.clamp(1, 999);
  }

  int get _min => widget.deviceCount < 1 ? 1 : widget.deviceCount;

  void _bump(int delta) {
    setState(() {
      _seats = (_seats + delta).clamp(_min, 999);
    });
  }

  @override
  Widget build(BuildContext context) {
    final monthlyHint = _seats * 199;
    return AlertDialog(
      title: const Text('Antal platser'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              _seatsExplainShort,
              style: TextStyle(color: Colors.grey.shade700, height: 1.4),
            ),
            const SizedBox(height: 8),
            Text(
              'En bil med två telefoner behöver två platser. '
              'Ägare och admin som bara loggar in räknas inte.',
              style: TextStyle(color: Colors.grey.shade700, height: 1.4),
            ),
            const SizedBox(height: 20),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton.filledTonal(
                  onPressed: _seats > _min ? () => _bump(-1) : null,
                  icon: const Icon(Icons.remove),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Column(
                    children: [
                      Text(
                        '$_seats',
                        style: const TextStyle(
                          fontSize: 36,
                          fontWeight: FontWeight.w700,
                          fontFamily: kDisplayFont,
                        ),
                      ),
                      Text(
                        _seats == 1 ? 'plats' : 'platser',
                        style: TextStyle(color: Colors.grey.shade700),
                      ),
                    ],
                  ),
                ),
                IconButton.filledTonal(
                  onPressed: _seats < 999 ? () => _bump(1) : null,
                  icon: const Icon(Icons.add),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text(
              'Kopplade nu: ${widget.deviceCount} telefon'
              '${widget.deviceCount == 1 ? '' : 'er'}. '
              '${widget.deviceCount > 0 ? 'Du kan inte sänka under det.' : ''}',
              style: TextStyle(color: Colors.grey.shade700, height: 1.35),
            ),
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: TbColors.foam,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: TbColors.line),
              ),
              child: Text(
                'Indikativt: ca $monthlyHint kr/mån '
                '($_seats × 199 kr) exkl. moms. '
                'Exakt belopp bekräftas i Stripe. '
                'Ändring gäller från nästa faktura.',
                style: TextStyle(
                  color: Colors.grey.shade800,
                  height: 1.4,
                  fontSize: 13,
                ),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Avbryt'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _seats),
          child: const Text('Spara'),
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
