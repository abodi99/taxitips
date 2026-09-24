import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../api_client.dart';
import '../theme.dart';

class SignupScreen extends StatefulWidget {
  const SignupScreen({
    super.key,
    required this.api,
    required this.onDone,
    required this.onLogin,
    this.onBack,
  });

  final ApiClient api;
  final VoidCallback onDone;
  final VoidCallback onLogin;
  final VoidCallback? onBack;

  @override
  State<SignupScreen> createState() => SignupScreenState();
}

class SignupScreenState extends State<SignupScreen> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _org = TextEditingController();
  final _contact = TextEditingController();
  final _phone = TextEditingController();
  String? _error;
  String? _lookupHint;
  // Satt när Supabase kräver att e-posten bekräftas innan kontot kan logga in.
  String? _confirmEmail;
  bool _busy = false;
  Timer? _lookupTimer;

  @override
  void initState() {
    super.initState();
    _prefill();
    _org.addListener(_onOrgChanged);
  }

  Future<void> _prefill() async {
    final saved = await widget.api.loadSavedCredentials();
    final dev = await widget.api.loadDevTestLogin();
    const defEmail = String.fromEnvironment('PREFILL_EMAIL', defaultValue: '');
    const defPass = String.fromEnvironment(
      'PREFILL_PASSWORD',
      defaultValue: '',
    );
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

  void _onOrgChanged() {
    _lookupTimer?.cancel();
    _lookupTimer = Timer(const Duration(milliseconds: 450), _checkOrg);
  }

  /// Kontrollsiffran i ett svenskt organisations- eller personnummer (Luhn på
  /// de tio sista siffrorna), samma regel som servern (fleet/orgnr.py). Bara
  /// en kontroll av skrivfel: vem som äger numret prövas inte här, och appen
  /// låtsas inte slå upp något namn.
  static bool orgNumberLooksValid(String input) {
    var digits = input.replaceAll(RegExp(r'\D'), '');
    if (digits.length == 12) digits = digits.substring(2);
    if (digits.length != 10) return false;
    var sum = 0;
    for (var i = 0; i < 10; i++) {
      var d = int.parse(digits[i]) * (i.isEven ? 2 : 1);
      if (d > 9) d -= 9;
      sum += d;
    }
    return sum % 10 == 0;
  }

  void _checkOrg() {
    final digits = _org.text.replaceAll(RegExp(r'\D'), '');
    if (!mounted) return;
    setState(() {
      if (digits.length < 10) {
        _lookupHint = null;
      } else {
        _lookupHint = orgNumberLooksValid(_org.text)
            ? null
            : 'Numret stämmer inte. Kontrollera siffrorna.';
      }
    });
  }

  @override
  void dispose() {
    _lookupTimer?.cancel();
    _org.removeListener(_onOrgChanged);
    _name.dispose();
    _email.dispose();
    _password.dispose();
    _org.dispose();
    _contact.dispose();
    _phone.dispose();
    super.dispose();
  }

  /// Konto och företag i ett steg. Ingen betalning: provet är kortfritt och
  /// startar när den första telefonen kopplas (fleet/registration.py).
  Future<void> _submit() async {
    final problem = _validate();
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final data = await widget.api.signup(
        name: _contact.text.trim(),
        email: _email.text.trim(),
        password: _password.text,
        orgNumber: _org.text.trim(),
        companyName: _name.text.trim(),
        phone: _phone.text.trim(),
      );
      if (data['needsConfirmation'] == true) {
        if (mounted) setState(() => _confirmEmail = _email.text.trim());
        return;
      }
      widget.onDone();
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _validate() {
    if (!orgNumberLooksValid(_org.text)) {
      return 'Kontrollera organisationsnumret (10 siffror).';
    }
    if (_name.text.trim().isEmpty) return 'Skriv företagets namn.';
    if (_contact.text.trim().isEmpty) return 'Skriv ditt namn.';
    if (!_email.text.contains('@')) return 'Skriv en giltig e-postadress.';
    if (_password.text.length < 8) return 'Lösenordet behöver minst 8 tecken.';
    return null;
  }

  /// Supabase Auths engelska fel, i klartext.
  String _friendly(Object e) {
    final text = e.toString();
    if (text.contains('already registered') || text.contains('already been registered')) {
      return 'Det finns redan ett konto med den e-postadressen. Logga in i stället.';
    }
    if (text.contains('Password should be')) return 'Lösenordet är för svagt.';
    return text.replaceFirst(RegExp(r'^\w*Exception:\s*'), '');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.navy,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: widget.onBack == null
            ? null
            : IconButton(
                tooltip: 'Tillbaka',
                onPressed: widget.onBack,
                icon: const Icon(Icons.arrow_back, color: TbColors.foam),
              ),
      ),
      extendBodyBehindAppBar: true,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  SvgPicture.asset(
                    'assets/brand/logo-on-dark.svg',
                    width: 240,
                    height: 70,
                    fit: BoxFit.contain,
                  ),
                  const SizedBox(height: 32),
                  if (_confirmEmail != null)
                    _ConfirmCard(email: _confirmEmail!, onLogin: widget.onLogin)
                  else
                  Container(
                    padding: const EdgeInsets.all(32),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(24),
                      boxShadow: const [
                        BoxShadow(
                          color: Colors.black12,
                          blurRadius: 20,
                          offset: Offset(0, 8),
                        ),
                      ],
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text(
                          'Skapa företagskonto',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontFamily: kDisplayFont,
                            color: TbColors.ink,
                            fontSize: 28,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Prova gratis i 14 dagar med upp till 3 bilar. Inget kort behövs.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.grey.shade600,
                            fontSize: 14,
                            height: 1.4,
                          ),
                        ),
                        const SizedBox(height: 24),
                        TextField(
                          controller: _org,
                          keyboardType: TextInputType.number,
                          decoration: InputDecoration(
                            labelText: 'Organisationsnummer',
                            prefixIcon: const Icon(
                              Icons.business_center_outlined,
                            ),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                        ),
                        if (_lookupHint != null) ...[
                          const SizedBox(height: 8),
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: TbColors.taxi.withValues(alpha: 0.15),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Row(
                              children: [
                                const Icon(
                                  Icons.info_outline,
                                  color: TbColors.ink,
                                  size: 20,
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Text(
                                    _lookupHint!,
                                    style: const TextStyle(
                                      color: TbColors.ink,
                                      fontSize: 13,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                        const SizedBox(height: 16),
                        TextField(
                          controller: _name,
                          decoration: InputDecoration(
                            labelText: 'Företagsnamn',
                            prefixIcon: const Icon(Icons.business_outlined),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _contact,
                          textCapitalization: TextCapitalization.words,
                          decoration: InputDecoration(
                            labelText: 'Ditt namn',
                            prefixIcon: const Icon(Icons.person_outline),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _phone,
                          keyboardType: TextInputType.phone,
                          decoration: InputDecoration(
                            labelText: 'Telefon (valfritt)',
                            prefixIcon: const Icon(Icons.phone_outlined),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _email,
                          keyboardType: TextInputType.emailAddress,
                          decoration: InputDecoration(
                            labelText: 'E-postadress',
                            prefixIcon: const Icon(Icons.email_outlined),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _password,
                          obscureText: true,
                          decoration: InputDecoration(
                            labelText: 'Lösenord (minst 8 tecken)',
                            prefixIcon: const Icon(Icons.lock_outline),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                        ),
                        const SizedBox(height: 16),
                        Container(
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: TbColors.foam,
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(color: TbColors.line),
                          ),
                          child: const Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              _Step(n: 1, text: 'Skapa kontot'),
                              _Step(n: 2, text: 'Lägg till bilarna'),
                              _Step(n: 3, text: 'Ge förarna en kod — provet startar'),
                            ],
                          ),
                        ),
                        if (_error != null) ...[
                          const SizedBox(height: 16),
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: TbColors.danger.withValues(alpha: 0.1),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Row(
                              children: [
                                const Icon(
                                  Icons.error_outline,
                                  color: TbColors.danger,
                                  size: 20,
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Text(
                                    _error!,
                                    style: const TextStyle(
                                      color: TbColors.danger,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                        const SizedBox(height: 24),
                        FilledButton(
                          onPressed: _busy ? null : _submit,
                          style: FilledButton.styleFrom(
                            backgroundColor: TbColors.ink,
                            foregroundColor: TbColors.foam,
                            minimumSize: const Size.fromHeight(56),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          child: _busy
                              ? const SizedBox(
                                  width: 24,
                                  height: 24,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: TbColors.foam,
                                  ),
                                )
                              : const Text(
                                  'Skapa konto och prova gratis',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                        ),
                        const SizedBox(height: 16),
                        OutlinedButton(
                          onPressed: widget.onLogin,
                          style: OutlinedButton.styleFrom(
                            foregroundColor: TbColors.ink,
                            minimumSize: const Size.fromHeight(56),
                            side: const BorderSide(color: Colors.black12),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          child: const Text('Jag har redan ett konto'),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({required this.n, required this.text});

  final int n;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          CircleAvatar(
            radius: 11,
            backgroundColor: TbColors.taxi,
            child: Text(
              '$n',
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: TbColors.ink,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(fontWeight: FontWeight.w600, color: TbColors.ink),
            ),
          ),
        ],
      ),
    );
  }
}

/// Kontot är skapat men e-posten måste bekräftas först. Företagsuppgifterna
/// ligger sparade i telefonen och registreras vid första inloggningen.
class _ConfirmCard extends StatelessWidget {
  const _ConfirmCard({required this.email, required this.onLogin});

  final String email;
  final VoidCallback onLogin;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(28),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(24),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(Icons.mark_email_read_outlined, size: 56, color: TbColors.taxiDeep),
          const SizedBox(height: 16),
          const Text(
            'Bekräfta din e-post',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontFamily: kDisplayFont,
              fontSize: 24,
              fontWeight: FontWeight.w800,
              color: TbColors.ink,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Vi har skickat en länk till $email. Öppna den och logga sedan in '
            'här — då skapas företaget och provperioden.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey.shade700, height: 1.4),
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: onLogin,
            style: FilledButton.styleFrom(
              backgroundColor: TbColors.ink,
              foregroundColor: TbColors.foam,
              minimumSize: const Size.fromHeight(52),
            ),
            child: const Text('Till inloggningen'),
          ),
        ],
      ),
    );
  }
}
