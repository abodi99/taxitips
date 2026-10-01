import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../api_client.dart';
import '../net_status.dart';
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
  // Bolagsverkets svar för numret i fältet. Null = inte hämtat, eller gick
  // inte att hämta; då skriver användaren företagsnamnet själv.
  Map<String, dynamic>? _registry;
  bool _registryChecked = false;
  bool _lookingUp = false;
  int _lookupSeq = 0;
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
  /// de tio sista siffrorna), samma regel som servern (fleet/orgnr.py). Ett
  /// nummer som klarar den slås upp hos Bolagsverket (`_checkOrg`); ett som
  /// inte gör det skickas aldrig.
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

  /// Svenskt mobilnummer (07X + sju siffror), med eller utan +46. Servern
  /// prövar samma sak och mer (fleet/signup_checks.py); det här är bara för
  /// att säga det direkt.
  static bool phoneLooksValid(String input) {
    var digits = input.replaceAll(RegExp(r'\D'), '');
    if (digits.startsWith('0046')) {
      digits = digits.substring(4);
    } else if (input.trim().startsWith('+')) {
      if (!digits.startsWith('46')) return false;
      digits = digits.substring(2);
    } else if (digits.startsWith('46') && digits.length == 11) {
      digits = digits.substring(2);
    } else if (digits.startsWith('0')) {
      digits = digits.substring(1);
    } else {
      return false;
    }
    // "+46 (0)70 …"
    if (digits.startsWith('0')) digits = digits.substring(1);
    return RegExp(r'^7[02369]\d{7}$').hasMatch(digits);
  }

  /// Personnummer (enskild firma) har månad 01–12; juridiska personer har
  /// oftast ≥ 20 i samma position. Bolagsverket har inte enskilda firmor.
  static bool looksLikeSoleTrader(String input) {
    var digits = input.replaceAll(RegExp(r'\D'), '');
    if (digits.length == 12) digits = digits.substring(2);
    if (digits.length != 10) return false;
    final month = int.tryParse(digits.substring(2, 4)) ?? 0;
    return month >= 1 && month <= 12;
  }

  Future<void> _checkOrg() async {
    final digits = _org.text.replaceAll(RegExp(r'\D'), '');
    if (!mounted) return;
    final seq = ++_lookupSeq;
    final valid = digits.length >= 10 && orgNumberLooksValid(_org.text);
    setState(() {
      _registry = null;
      _registryChecked = false;
      _lookingUp = valid;
      _lookupHint = digits.length < 10 || valid
          ? null
          : 'Numret stämmer inte. Kontrollera siffrorna.';
    });
    if (!valid) return;
    // Namn, adress och status hämtas från Bolagsverket; användaren behöver
    // inte skriva av dem (fleet/bolagsverket.py).
    final registry = await widget.api.registryLookup(_org.text.trim());
    // Ett äldre svar får inte skriva över ett nyare: användaren kan ha
    // fortsatt skriva medan uppslaget pågick.
    if (!mounted || seq != _lookupSeq) return;
    setState(() {
      _registry = registry;
      _registryChecked = true;
      _lookingUp = false;
    });
  }

  bool get _registryFound => _registry?['found'] == true;
  bool get _registryBlocks => _registry?['blocksSignup'] == true;

  /// Uppslaget gick inte att göra (nätet, backenden eller Bolagsverket). Inte
  /// samma sak som "finns inte" -- då ska användaren kunna försöka igen, inte
  /// få höra att bolaget saknas (2026-09-30: backenden låg nere och appen sa
  /// "Vi hittade inte bolaget" om ett aktivt aktiebolag).
  bool get _registryUnavailable => _registryChecked && _registry == null;

  /// Aktiebolag, ekonomisk förening och handelsbolag (5/7/9) finns alltid hos
  /// Bolagsverket. Saknas de där är numret fel, och servern nekar
  /// (fleet/signup_checks.py:check_registry).
  bool get _registryRejects =>
      _registryChecked &&
      _registry != null &&
      !_registryFound &&
      !_soleTrader &&
      RegExp(r'^[579]').hasMatch(_org.text.replaceAll(RegExp(r'\D'), '').replaceFirst(RegExp(r'^16'), ''));

  /// Företagsnamnet behöver bara skrivas när registret inte har bolaget
  /// (t.ex. en enskild firma) eller inte gick att nå.
  bool get _needsCompanyName =>
      _registryChecked && !_registryFound && !_registryRejects;

  bool get _soleTrader => looksLikeSoleTrader(_org.text);

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
        // Tomt när Bolagsverket har bolaget: servern tar namnet därifrån.
        companyName: _needsCompanyName ? _name.text.trim() : '',
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
    if (_lookingUp) return 'Vänta, vi hämtar bolaget från Bolagsverket.';
    if (_registryBlocks) {
      return 'Bolaget är avregistrerat hos Bolagsverket och kan inte skapa ett konto.';
    }
    if (!_registryChecked) return 'Vänta, vi kontrollerar organisationsnumret.';
    if (_registryRejects) {
      return 'Bolagsverket hittar inte organisationsnumret. Kontrollera siffrorna.';
    }
    if (_needsCompanyName && _name.text.trim().isEmpty) {
      return _soleTrader
          ? 'Skriv firmanamnet (enskild firma finns inte hos Bolagsverket).'
          : 'Skriv företagets namn.';
    }
    if (_contact.text.trim().isEmpty) return 'Skriv ditt namn.';
    if (!phoneLooksValid(_phone.text)) {
      return 'Skriv ett svenskt mobilnummer, till exempel 070-123 45 67.';
    }
    if (!_email.text.contains('@')) return 'Skriv en giltig e-postadress.';
    if (_password.text.length < 8) return 'Lösenordet behöver minst 8 tecken.';
    return null;
  }

  /// Supabase Auths engelska fel, i klartext.
  String _friendly(Object e) {
    final net = netFailureOf(e);
    if (net != null) return netMessage(net);
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
                    _ConfirmCard(
                      email: _confirmEmail!,
                      onLogin: widget.onLogin,
                      onResend: () => widget.api.resendConfirmation(_confirmEmail!),
                    )
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
                          'Prova gratis i 7 dagar med en bil. Inget kort behövs. '
                          'Under provet visas tåg och buss.',
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
                            helperText: 'Enskild firma: ditt personnummer',
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
                        if (_lookingUp) ...[
                          const SizedBox(height: 10),
                          const Row(
                            children: [
                              SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              ),
                              SizedBox(width: 10),
                              Text(
                                'Hämtar bolaget från Bolagsverket …',
                                style: TextStyle(color: TbColors.muted, fontSize: 13),
                              ),
                            ],
                          ),
                        ],
                        if (_registryFound) ...[
                          const SizedBox(height: 10),
                          _RegistryCard(registry: _registry!),
                        ],
                        if (_registryRejects) ...[
                          const SizedBox(height: 8),
                          const Text(
                            'Bolagsverket hittar inte organisationsnumret. Kontrollera siffrorna.',
                            style: TextStyle(color: TbColors.danger, fontSize: 13),
                          ),
                        ],
                        if (_registryUnavailable) ...[
                          const SizedBox(height: 8),
                          Row(
                            children: [
                              const Expanded(
                                child: Text(
                                  'Kunde inte nå Bolagsverket just nu.',
                                  style: TextStyle(fontSize: 13),
                                ),
                              ),
                              TextButton(
                                onPressed: _checkOrg,
                                child: const Text('Försök igen'),
                              ),
                            ],
                          ),
                        ],
                        if (_needsCompanyName) ...[
                          const SizedBox(height: 16),
                          TextField(
                            controller: _name,
                            textCapitalization: TextCapitalization.words,
                            decoration: InputDecoration(
                              labelText: _soleTrader
                                  ? 'Firmanamn'
                                  : 'Företagsnamn',
                              helperText: _soleTrader
                                  ? 'Enskild firma hämtas inte från Bolagsverket — skriv namnet ni använder.'
                                  : _registryUnavailable
                                  ? 'Eller skriv företagets namn, så kontrollerar vi det senare.'
                                  : 'Vi hittade inte bolaget hos Bolagsverket. Skriv namnet så ni syns rätt.',
                              prefixIcon: const Icon(Icons.business_outlined),
                              border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                            ),
                          ),
                        ],
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
                            labelText: 'Mobilnummer',
                            helperText: 'Vi ringer och hjälper dig i gång under provet.',
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
                              _Step(n: 2, text: 'Lägg till bilen'),
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
                          onPressed: _busy || _registryBlocks ? null : _submit,
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
class _ConfirmCard extends StatefulWidget {
  const _ConfirmCard({
    required this.email,
    required this.onLogin,
    required this.onResend,
  });

  final String email;
  final VoidCallback onLogin;
  final Future<void> Function() onResend;

  @override
  State<_ConfirmCard> createState() => _ConfirmCardState();
}

class _ConfirmCardState extends State<_ConfirmCard> {
  String? _note;
  bool _busy = false;

  Future<void> _resend() async {
    setState(() {
      _busy = true;
      _note = null;
    });
    try {
      await widget.onResend();
      _note = 'Skickat igen.';
    } catch (e) {
      // Supabase begränsar hur ofta samma adress får ett nytt mejl.
      _note = e.toString().contains('seconds')
          ? 'Vänta en minut och försök igen.'
          : 'Det gick inte att skicka. Försök igen om en stund.';
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

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
            'Vi skickade en länk till ${widget.email}. Tryck på länken, '
            'kom tillbaka hit och logga in.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey.shade700, height: 1.4),
          ),
          const SizedBox(height: 6),
          Text(
            'Syns inget? Titta i skräpposten.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey.shade600, fontSize: 13),
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: widget.onLogin,
            style: FilledButton.styleFrom(
              backgroundColor: TbColors.ink,
              foregroundColor: TbColors.foam,
              minimumSize: const Size.fromHeight(52),
            ),
            child: const Text('Logga in'),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: _busy ? null : _resend,
            child: Text(_note ?? 'Skicka mejlet igen'),
          ),
        ],
      ),
    );
  }
}


/// Bolaget som Bolagsverket har det: namn, adress och form. Rött när det är
/// avregistrerat, gult när en konkurs eller likvidation pågår.
class _RegistryCard extends StatelessWidget {
  const _RegistryCard({required this.registry});

  final Map<String, dynamic> registry;

  @override
  Widget build(BuildContext context) {
    final blocks = registry['blocksSignup'] == true;
    final status = registry['status']?.toString() ?? '';
    final warn = status == 'winding_up' || status == 'inactive';
    final color = blocks
        ? TbColors.danger
        : (warn ? TbColors.taxiDeep : TbColors.live);
    final line1 = registry['line1']?.toString() ?? '';
    final line2 = registry['line2']?.toString() ?? '';
    final postal = [
      registry['postalCode']?.toString() ?? '',
      registry['city']?.toString() ?? '',
    ].where((s) => s.isNotEmpty).join(' ');
    final form = registry['legalForm']?.toString() ?? '';
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            blocks ? Icons.block : (warn ? Icons.warning_amber : Icons.verified),
            color: color,
            size: 22,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  registry['name']?.toString() ?? '',
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    color: TbColors.ink,
                  ),
                ),
                if (form.isNotEmpty)
                  Text(form, style: const TextStyle(color: TbColors.muted)),
                if (line1.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(line1, style: const TextStyle(color: TbColors.ink)),
                ],
                if (line2.isNotEmpty)
                  Text(line2, style: const TextStyle(color: TbColors.ink)),
                if (postal.isNotEmpty)
                  Text(postal, style: const TextStyle(color: TbColors.ink)),
                if (blocks || warn)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                      registry['statusText']?.toString() ?? '',
                      style: TextStyle(color: color, fontWeight: FontWeight.w600),
                    ),
                  ),
                if (!blocks && !warn)
                  const Padding(
                    padding: EdgeInsets.only(top: 4),
                    child: Text(
                      'Hämtat från Bolagsverket — du behöver inte skriva om det.',
                      style: TextStyle(color: TbColors.muted, fontSize: 12),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
