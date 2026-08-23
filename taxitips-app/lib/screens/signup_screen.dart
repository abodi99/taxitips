import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../theme.dart';

class SignupScreen extends StatefulWidget {
  const SignupScreen({super.key, required this.api, required this.onDone, required this.onLogin});

  final ApiClient api;
  final VoidCallback onDone;
  final VoidCallback onLogin;

  @override
  State<SignupScreen> createState() => _SignupScreenState();
}

class _SignupScreenState extends State<SignupScreen> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _org = TextEditingController();
  final _seats = TextEditingController(text: '1');
  String? _error;
  String? _lookupHint;
  String? _priceHint;
  bool _busy = false;
  bool _nameFromApi = false;
  Timer? _lookupTimer;

  @override
  void initState() {
    super.initState();
    _prefill();
    _loadPricing();
    _org.addListener(_onOrgChanged);
  }

  Future<void> _prefill() async {
    final saved = await widget.api.loadSavedCredentials();
    final dev = await widget.api.loadDevTestLogin();
    const defEmail = String.fromEnvironment('PREFILL_EMAIL', defaultValue: '');
    const defPass = String.fromEnvironment('PREFILL_PASSWORD', defaultValue: '');
    if (!mounted) return;
    setState(() {
      _email.text = saved.email?.isNotEmpty == true
          ? saved.email!
          : (dev.email ?? (defEmail.isNotEmpty ? defEmail : ''));
      _password.text = saved.password?.isNotEmpty == true
          ? saved.password!
          : (dev.password ?? (defPass.isNotEmpty ? defPass : ''));
    });
  }

  Future<void> _loadPricing() async {
    try {
      final p = await widget.api.pricing();
      final seats = int.tryParse(_seats.text) ?? 1;
      final unit = seats >= (p['fleetMin'] as num? ?? 5)
          ? (p['fleetPerDevice'] as num? ?? 79)
          : (p['perDevice'] as num? ?? 99);
      if (!mounted) return;
      setState(() {
        _priceHint = '$seats enhet${seats == 1 ? '' : 'er'} · $unit kr/enhet/mån · ${unit * seats} kr/mån via Stripe';
      });
    } catch (_) {}
  }

  void _onOrgChanged() {
    _lookupTimer?.cancel();
    _lookupTimer = Timer(const Duration(milliseconds: 450), _lookupOrg);
  }

  Future<void> _lookupOrg() async {
    final org = _org.text.trim();
    if (org.replaceAll(RegExp(r'\D'), '').length < 10) {
      setState(() => _lookupHint = 'Ange org.nr eller personnummer (enskild firma)');
      return;
    }
    setState(() => _lookupHint = 'Hämtar företagsinfo…');
    try {
      final data = await widget.api.lookupCompany(org);
      if (!mounted) return;
      if (data['valid'] != true) {
        setState(() => _lookupHint = data['error']?.toString() ?? 'Ogiltigt org.nr');
        return;
      }
      if (data['found'] == true && data['name'] != null) {
        if (_name.text.isEmpty || _nameFromApi) {
          _name.text = data['name'].toString();
          _nameFromApi = true;
        }
        final addr = data['address'];
        final bits = <String>[
          if (data['legalForm'] != null) data['legalForm'].toString(),
          if (addr is Map)
            [addr['street'], addr['zip'], addr['city']].whereType<String>().where((s) => s.isNotEmpty).join(', '),
        ].where((s) => s.isNotEmpty);
        setState(() {
          final kind = data['companyKind'] == 'enskild_firma' || data['idKind'] == 'person'
              ? 'enskild firma · '
              : '';
          _lookupHint = 'Hittade: $kind${data['name']}${bits.isEmpty ? '' : ' · ${bits.join(' · ')}'} (${data['source']})';
        });
      } else {
        setState(() {
          _lookupHint = data['message']?.toString() ??
              (data['idKind'] == 'person'
                  ? 'Personnummer giltigt. Ingen registrerad enskild firma hittades — fyll i namn manuellt.'
                  : 'Org.nr giltigt. Fyll i företagsnamn om uppslag saknas.');
        });
      }
    } catch (e) {
      if (mounted) setState(() => _lookupHint = e.toString());
    }
  }

  @override
  void dispose() {
    _lookupTimer?.cancel();
    _org.removeListener(_onOrgChanged);
    _name.dispose();
    _email.dispose();
    _password.dispose();
    _org.dispose();
    _seats.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final seats = int.tryParse(_seats.text.trim()) ?? 1;
      final origin = Uri.base.origin;
      final data = await widget.api.signup(
        name: _name.text.trim(),
        email: _email.text.trim(),
        password: _password.text,
        orgNumber: _org.text.trim(),
        seats: seats,
        startCheckout: true,
        successUrl: '$origin/#/dashboard?paid=1',
        cancelUrl: '$origin/#/dashboard?canceled=1',
      );
      await widget.api.saveCredentials(_email.text.trim(), _password.text);

      final checkout = data['checkout'] as Map<String, dynamic>?;
      final url = checkout?['url']?.toString();
      if (url != null && url.isNotEmpty && checkout?['mode'] == 'stripe') {
        final uri = Uri.parse(url);
        final ok = await launchUrl(uri, webOnlyWindowName: '_self');
        if (!ok && mounted) {
          setState(() => _error = 'Kunde inte öppna Stripe Checkout');
        }
        // Om redirect lyckas lämnar vi sidan; annars fortsätt till dashboard
        return;
      }
      // Utan Stripe-nycklar: auto-aktiverad trial/manual
      widget.onDone();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.navy,
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Card(
            color: TbColors.foam,
            margin: const EdgeInsets.all(24),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Image(
                    image: AssetImage('assets/brand/splash_mark.png'),
                    height: 76,
                    fit: BoxFit.contain,
                    filterQuality: FilterQuality.high,
                  ),
                  Text('Skapa konto', style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
                  const SizedBox(height: 8),
                  const Text(
                    'Org.nr → företagsinfo. Sedan väljer du orter och kopplar telefoner.',
                  ),
                  const SizedBox(height: 20),
                  TextField(
                    controller: _org,
                    decoration: const InputDecoration(labelText: 'Organisationsnummer'),
                    keyboardType: TextInputType.number,
                  ),
                  if (_lookupHint != null) ...[
                    const SizedBox(height: 6),
                    Text(_lookupHint!, style: Theme.of(context).textTheme.bodySmall),
                  ],
                  const SizedBox(height: 12),
                  TextField(
                    controller: _name,
                    decoration: const InputDecoration(labelText: 'Företagsnamn'),
                    onChanged: (_) => _nameFromApi = false,
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _email,
                    decoration: const InputDecoration(labelText: 'E-post'),
                    keyboardType: TextInputType.emailAddress,
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _password,
                    decoration: const InputDecoration(labelText: 'Lösenord (minst 6)'),
                    obscureText: true,
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _seats,
                    decoration: const InputDecoration(labelText: 'Antal telefoner/enheter'),
                    keyboardType: TextInputType.number,
                    onChanged: (_) => _loadPricing(),
                  ),
                  if (_priceHint != null) ...[
                    const SizedBox(height: 8),
                    Text(_priceHint!, style: Theme.of(context).textTheme.bodySmall),
                  ],
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: Text(_busy ? 'Skapar…' : 'Skapa konto & betala'),
                  ),
                  TextButton(onPressed: widget.onLogin, child: const Text('Har redan konto')),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
