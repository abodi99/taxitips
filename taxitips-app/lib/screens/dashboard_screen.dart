import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../theme.dart';

/// Vanligaste orterna först — resten under "Fler orter".
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

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({
    super.key,
    required this.api,
    required this.onLogout,
    required this.onOpenDriver,
    this.onOpenSettings,
    this.banner,
  });

  final ApiClient api;
  final VoidCallback onLogout;
  final VoidCallback onOpenDriver;
  final VoidCallback? onOpenSettings;
  final String? banner;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Map<String, dynamic>? _me;
  List<String> _catalog = [];
  final Set<String> _selected = {};
  String? _error;
  String? _ok;
  String? _transferCode;
  String? _transferLabel;
  bool _loading = true;
  bool _saving = false;
  bool _regen = false;
  bool _showMoreCities = false;
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
      final watched = (areas['watchedAreas'] as List?)?.map((e) => e.toString()).toList() ?? [];
      final catalog = (areas['catalog'] as List?)?.map((e) => e.toString()).toList() ?? [];
      setState(() {
        _me = me;
        _catalog = catalog;
        _selected
          ..clear()
          ..addAll(watched);
      });
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

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
    setState(() => _saving = true);
    try {
      await widget.api.saveAreas(_selected.toList());
      if (!mounted) return;
      setState(() {
        _ok = _selected.isEmpty ? 'Hela Skåne' : '${_selected.length} orter sparade';
      });
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _regenCode() async {
    setState(() {
      _regen = true;
      _error = null;
    });
    try {
      final data = await widget.api.regenerateJoinCode();
      setState(() {
        final company = Map<String, dynamic>.from(_me?['company'] as Map? ?? {});
        company['joinCode'] = data['joinCode'];
        _me = {...?_me, 'company': company};
        _ok = 'Ny bolagskod skapad. Ge den till förarna.';
      });
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _regen = false);
    }
  }

  Future<void> _makeTransfer(Map<String, dynamic> device) async {
    try {
      final data = await widget.api.createTransferCode(device['id'].toString());
      if (!mounted) return;
      setState(() {
        _transferCode = data['code']?.toString();
        _transferLabel = device['label']?.toString() ?? 'Telefon';
        _ok = 'Byteskod skapad — giltig 30 min. Max 2 byten/månad per telefon.';
      });
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  Future<void> _deleteDevice(String id) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Ta bort telefon?'),
        content: const Text('Platsen frigörs. Föraren kan registrera en ny med bolagskoden.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Nej')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Ja, ta bort')),
        ],
      ),
    );
    if (ok != true) return;
    await widget.api.deleteDevice(id);
    await _reload();
  }

  List<String> get _visibleCities {
    final ordered = _primaryCities.where(_catalog.contains).toList();
    if (!_showMoreCities) return ordered.isNotEmpty ? ordered : _catalog.take(10).toList();
    final rest = _catalog.where((c) => !_primaryCities.contains(c)).toList();
    return [...ordered, ...rest];
  }

  @override
  Widget build(BuildContext context) {
    final company = _me?['company'] as Map<String, dynamic>?;
    final devices = (_me?['devices'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    final joinCode = company?['joinCode']?.toString() ?? '—';
    final seats = company?['seats'] ?? 1;
    final free = (seats is num ? seats.toInt() : 1) - devices.length;

    return Scaffold(
      backgroundColor: TbColors.foam,
      appBar: AppBar(
        title: Text(company?['name']?.toString() ?? 'Kontor'),
        actions: [
          if (widget.onOpenSettings != null)
            IconButton(
              tooltip: 'Inställningar',
              onPressed: widget.onOpenSettings,
              icon: const Icon(Icons.settings_outlined),
            ),
          TextButton(
            onPressed: widget.onLogout,
            child: const Text('Logga ut', style: TextStyle(color: TbColors.foam)),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: TbColors.taxi))
          : RefreshIndicator(
              color: TbColors.taxiDeep,
              onRefresh: _reload,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  if (widget.banner != null) _Banner(widget.banner!, TbColors.live),
                  if (_error != null) _Banner(_error!, TbColors.danger),
                  if (_ok != null) _Banner(_ok!, TbColors.live),

                  _BillingCard(
                    api: widget.api,
                    me: _me,
                    onChanged: _reload,
                  ),
                  const SizedBox(height: 14),

                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: TbColors.asphalt,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Så kör du igång', style: TextStyle(color: TbColors.taxi, fontWeight: FontWeight.w900, fontSize: 16)),
                        SizedBox(height: 8),
                        Text(
                          '1. Välj orter  →  2. Ge bolagskod till föraren  →  3. Hen registrerar telefonen själv',
                          style: TextStyle(color: TbColors.foam, height: 1.4, fontWeight: FontWeight.w600),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  FilledButton.icon(
                    onPressed: widget.onOpenDriver,
                    icon: const Icon(Icons.local_taxi),
                    label: const Text('Till förarvyn'),
                  ),
                  const SizedBox(height: 20),

                  const Text('1. Orter ni kör i', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 4),
                  Text(
                    _selected.isEmpty
                        ? 'Inget valt = hela Skåne. Tryck för att begränsa.'
                        : 'Valt: ${_selected.join(', ')}',
                    style: TextStyle(color: Colors.grey.shade700),
                  ),
                  if (_saving)
                    const Padding(
                      padding: EdgeInsets.only(top: 6),
                      child: LinearProgressIndicator(color: TbColors.taxi, minHeight: 3),
                    ),
                  const SizedBox(height: 10),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final name in _visibleCities)
                        FilterChip(
                          label: Text(name, style: const TextStyle(fontWeight: FontWeight.w800)),
                          selected: _selected.contains(name),
                          selectedColor: TbColors.taxi,
                          checkmarkColor: TbColors.ink,
                          onSelected: (_) => _toggleCity(name),
                        ),
                    ],
                  ),
                  TextButton(
                    onPressed: () => setState(() => _showMoreCities = !_showMoreCities),
                    child: Text(_showMoreCities ? 'Visa färre orter' : 'Visa fler orter'),
                  ),
                  const SizedBox(height: 20),

                  const Text('2. Bolagskod till förarna', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 4),
                  Text(
                    'Föraren öppnar appen → Registrera telefon → anger koden. '
                    '${free > 0 ? '$free ledig${free == 1 ? '' : 'a'} plats${free == 1 ? '' : 'er'}.' : 'Inga lediga platser — använd byteskod för att byta telefon.'}',
                    style: TextStyle(color: Colors.grey.shade700),
                  ),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: TbColors.taxi.withValues(alpha: 0.22),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: TbColors.taxiDeep),
                    ),
                    child: Column(
                      children: [
                        Text(
                          joinCode,
                          style: const TextStyle(
                            fontSize: 36,
                            fontWeight: FontWeight.w900,
                            letterSpacing: 6,
                          ),
                        ),
                        const SizedBox(height: 10),
                        Row(
                          children: [
                            Expanded(
                              child: OutlinedButton.icon(
                                onPressed: () {
                                  Clipboard.setData(ClipboardData(text: joinCode));
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    const SnackBar(content: Text('Bolagskod kopierad')),
                                  );
                                },
                                icon: const Icon(Icons.copy),
                                label: const Text('Kopiera'),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: FilledButton(
                                onPressed: _regen ? null : _regenCode,
                                child: Text(_regen ? '…' : 'Ny kod'),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),

                  if (_transferCode != null) ...[
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: TbColors.asphalt,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            'Byteskod för $_transferLabel',
                            style: const TextStyle(color: TbColors.taxi, fontWeight: FontWeight.w900),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            _transferCode!,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              color: TbColors.foam,
                              fontSize: 32,
                              fontWeight: FontWeight.w900,
                              letterSpacing: 6,
                            ),
                          ),
                          const SizedBox(height: 6),
                          const Text(
                            'Ange på den nya telefonen under “Byt telefon”. Gäller 30 min.',
                            style: TextStyle(color: TbColors.foam),
                          ),
                          TextButton(
                            onPressed: () {
                              Clipboard.setData(ClipboardData(text: _transferCode!));
                            },
                            child: const Text('Kopiera byteskod', style: TextStyle(color: TbColors.taxi)),
                          ),
                        ],
                      ),
                    ),
                  ],

                  if (devices.isNotEmpty) ...[
                    const SizedBox(height: 16),
                    const Text('Aktiva telefoner', style: TextStyle(fontWeight: FontWeight.w900)),
                    const SizedBox(height: 4),
                    Text('Max 2 telefonbyten per plats och månad.', style: TextStyle(color: Colors.grey.shade700, fontSize: 13)),
                    ...devices.map(
                      (d) {
                        final left = d['swapsRemainingThisMonth'] ?? 2;
                        return ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const CircleAvatar(
                            backgroundColor: TbColors.taxi,
                            child: Icon(Icons.phone_android, color: TbColors.ink),
                          ),
                          title: Text(d['label']?.toString() ?? 'Telefon', style: const TextStyle(fontWeight: FontWeight.w800)),
                          subtitle: Text(
                            '${d['hasPush'] == true ? 'Redo' : 'Öppnad'} · $left byte kvar i månaden',
                          ),
                          trailing: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                tooltip: 'Byt telefon',
                                icon: const Icon(Icons.phonelink_setup),
                                onPressed: () => _makeTransfer(d),
                              ),
                              IconButton(
                                icon: const Icon(Icons.delete_outline),
                                onPressed: () => _deleteDevice(d['id'].toString()),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
                  ] else ...[
                    const SizedBox(height: 16),
                    Text('Inga telefoner ännu — ge bolagskoden till föraren.', style: TextStyle(color: Colors.grey.shade700)),
                  ],
                  const SizedBox(height: 20),
                  _MembersCard(
                    api: widget.api,
                    members: (_me?['members'] as List?)?.cast<Map<String, dynamic>>() ?? [],
                    onChanged: _reload,
                  ),
                  const SizedBox(height: 24),
                ],
              ),
            ),
    );
  }
}

class _BillingCard extends StatefulWidget {
  const _BillingCard({
    required this.api,
    required this.me,
    required this.onChanged,
  });

  final ApiClient api;
  final Map<String, dynamic>? me;
  final VoidCallback onChanged;

  @override
  State<_BillingCard> createState() => _BillingCardState();
}

class _BillingCardState extends State<_BillingCard> {
  bool _busy = false;

  String _statusLabel() {
    final company = widget.me?['company'] as Map<String, dynamic>? ?? {};
    final billing = widget.me?['billing'] as Map<String, dynamic>? ?? {};
    if (company['status'] == 'owner') return 'Ägare · gratis';
    final status = company['status']?.toString() ?? '';
    final trialEnd = billing['trialEndsAt'] ?? company['trialEndsAt'];
    if (status == 'trial' && trialEnd is num) {
      final days = ((trialEnd - DateTime.now().millisecondsSinceEpoch) / 86400000).ceil();
      return 'Provperiod · $days dag${days == 1 ? '' : 'ar'} kvar';
    }
    if (status == 'active') return 'Aktivt medlemskap';
    if (status == 'past_due') return 'Betalning saknas — åtgärda!';
    if (status == 'canceled') return 'Avslutas vid periodens slut';
    return 'Ej aktivt medlemskap';
  }

  Color _statusColor() {
    final company = widget.me?['company'] as Map<String, dynamic>? ?? {};
    final s = company['status']?.toString() ?? '';
    if (s == 'active' || s == 'owner') return TbColors.live;
    if (s == 'trial') return TbColors.taxiDeep;
    if (s == 'past_due') return TbColors.danger;
    return TbColors.muted;
  }

  Future<void> _openPortal() async {
    try {
      final data = await widget.api.billingPortal();
      final url = data['url']?.toString();
      if (url != null && url.isNotEmpty) {
        await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Starta först medlemskapet — sedan kan du hantera betalningen.')),
        );
      }
    }
  }

  Future<void> _changeSeats() async {
    final controller = TextEditingController(
      text: (widget.me?['company']?['seats'] ?? 1).toString(),
    );
    final seats = await showDialog<int>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Antal bilar/mobiler'),
        content: TextField(
          controller: controller,
          keyboardType: TextInputType.number,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Antal (199 kr/mån per bil)'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Avbryt')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, int.tryParse(controller.text) ?? 0),
            child: const Text('Spara'),
          ),
        ],
      ),
    );
    if (seats == null || seats < 1) return;
    setState(() => _busy = true);
    try {
      final res = await widget.api.updateBillingQuantity(seats);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Antal uppdaterat till ${res['quantity']}. ${res['synced'] == true ? 'Fakturan justeras direkt via Stripe.' : 'Faktureras vid nästa checkout.'}',
          ),
        ),
      );
      widget.onChanged();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.toString())));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final company = widget.me?['company'] as Map<String, dynamic>? ?? {};
    final billing = widget.me?['billing'] as Map<String, dynamic>? ?? {};
    final devices = (widget.me?['devices'] as List?)?.length ?? 0;
    final seats = (company['seats'] is num ? company['seats'] as int : 1);
    final pricing = widget.me?['pricing'] as Map<String, dynamic>? ?? {};
    final unit = (pricing['unitPrice'] as num?)?.toInt() ?? 199;
    final hasSubscription = billing['subscription'] != null;

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFD4CBBC)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text('Medlemskap', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: _statusColor().withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  _statusLabel(),
                  style: TextStyle(color: _statusColor(), fontWeight: FontWeight.w800, fontSize: 12),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              _stat('Enheter', '$devices/$seats'),
              const SizedBox(width: 18),
              _stat('Pris', '$unit kr/mån per bil'),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: _busy ? null : _openPortal,
                icon: const Icon(Icons.credit_card),
                label: Text(hasSubscription ? 'Hantera betalning' : 'Starta medlemskap'),
              ),
              OutlinedButton.icon(
                onPressed: _busy ? null : _changeSeats,
                icon: const Icon(Icons.phone_android),
                label: const Text('Ändra antal'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

Widget _stat(String label, String value) {
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        value,
        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900, color: TbColors.ink),
      ),
      Text(
        label,
        style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
      ),
    ],
  );
}

class _MembersCard extends StatefulWidget {
  const _MembersCard({
    required this.api,
    required this.members,
    required this.onChanged,
  });

  final ApiClient api;
  final List<Map<String, dynamic>> members;
  final VoidCallback onChanged;

  @override
  State<_MembersCard> createState() => _MembersCardState();
}

class _MembersCardState extends State<_MembersCard> {
  final _email = TextEditingController();
  final _name = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _add() async {
    final email = _email.text.trim();
    if (email.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.addMember(email: email, name: _name.text.trim());
      if (!mounted) return;
      _email.clear();
      _name.clear();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Medlem tillagd — inbjudan skickad via e-post')),
      );
      widget.onChanged();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove(String userId) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Ta bort medlem?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Nej')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Ja, ta bort')),
        ],
      ),
    );
    if (ok != true) return;
    await widget.api.removeMember(userId);
    widget.onChanged();
  }

  @override
  Widget build(BuildContext context) {
    const roleSv = {'company_owner': 'Ägare', 'company_admin': 'Admin', 'driver': 'Förare'};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Medlemmar & admin', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
        const SizedBox(height: 4),
        Text(
          'Kollegor som loggar in på kontoret. De sätter sitt eget lösenord via e-post.',
          style: TextStyle(color: Colors.grey.shade700, fontSize: 13),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _name,
          decoration: const InputDecoration(labelText: 'Namn (valfritt)'),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _email,
          keyboardType: TextInputType.emailAddress,
          decoration: const InputDecoration(labelText: 'E-post'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 8),
          Text(_error!, style: const TextStyle(color: TbColors.danger, fontWeight: FontWeight.w700)),
        ],
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            onPressed: _busy ? null : _add,
            icon: const Icon(Icons.person_add_alt),
            label: Text(_busy ? 'Lägger till…' : 'Lägg till admin'),
          ),
        ),
        const SizedBox(height: 12),
        for (final m in widget.members) ...[
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: CircleAvatar(
              backgroundColor: m['role'] == 'company_owner' ? TbColors.asphalt : TbColors.taxi,
              child: Icon(
                m['role'] == 'company_owner' ? Icons.star : Icons.person,
                color: m['role'] == 'company_owner' ? TbColors.taxi : TbColors.ink,
              ),
            ),
            title: Text(
              (m['name']?.toString().isNotEmpty ?? false) ? m['name'].toString() : (m['email']?.toString() ?? '—'),
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            subtitle: Text('${m['email']} · ${roleSv[m['role']] ?? m['role']}'),
            trailing: m['role'] != 'company_owner'
                ? IconButton(
                    tooltip: 'Ta bort medlem',
                    icon: const Icon(Icons.person_remove_outlined, color: TbColors.danger),
                    onPressed: () => _remove(m['userId'].toString()),
                  )
                : null,
          ),
        ],
      ],
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner(this.text, this.color);
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(text, style: TextStyle(color: color, fontWeight: FontWeight.w800)),
    );
  }
}
