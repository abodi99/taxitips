import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../analytics.dart';
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

  /// Vad som är fel med ett personnummer (enskild firma), eller null. Samma
  /// regler som servern (fleet/signup_checks.py:check_identity): datumet ska
  /// finnas (samordningsnummer har dag + 60) och personen ska ha fyllt 18.
  /// Kontrollsiffran prövas separat (orgNumberLooksValid). Visar bara att
  /// numret är rätt skrivet -- inte att det är personens eget.
  static String? personalNumberProblem(String input, {DateTime? today}) {
    var digits = input.replaceAll(RegExp(r'\D'), '');
    int? century;
    if (digits.length == 12) {
      century = int.tryParse(digits.substring(0, 2));
      digits = digits.substring(2);
    }
    if (digits.length != 10 || !looksLikeSoleTrader(digits)) return null;
    final now = today ?? DateTime.now();
    final yy = int.parse(digits.substring(0, 2));
    final mm = int.parse(digits.substring(2, 4));
    var dd = int.parse(digits.substring(4, 6));
    if (dd > 60) dd -= 60;
    final year = century != null
        ? century * 100 + yy
        : ((now.year ~/ 100) * 100 + yy <= now.year
              ? (now.year ~/ 100) * 100 + yy
              : (now.year ~/ 100 - 1) * 100 + yy);
    final born = DateTime(year, mm, dd);
    if (dd < 1 || born.month != mm || born.day != dd || born.isAfter(now)) {
      return 'Personnumret har ett datum som inte finns. Kontrollera numret.';
    }
    var age = now.year - born.year;
    if (now.month < born.month ||
        (now.month == born.month && now.day < born.day)) {
      age--;
    }
    if (age < 18) {
      return 'En enskild firma registreras av någon som fyllt 18. Kontrollera numret.';
    }
    return null;
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
    final luhn = digits.length >= 10 && orgNumberLooksValid(_org.text);
    final personal = luhn ? personalNumberProblem(_org.text) : null;
    final valid = luhn && personal == null;
    setState(() {
      _registry = null;
      _registryChecked = false;
      _lookingUp = valid;
      _lookupHint = digits.length < 10 || valid
          ? null
          : (personal ?? 'Numret stämmer inte. Kontrollera siffrorna.');
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
      RegExp(r'^[579]').hasMatch(
        _org.text
            .replaceAll(RegExp(r'\D'), '')
            .replaceFirst(RegExp(r'^16'), ''),
      );

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
    final personal = personalNumberProblem(_org.text);
    if (personal != null) return personal;
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
    if (text.contains('already registered') ||
        text.contains('already been registered')) {
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
                    _CodeCard(
                      email: _confirmEmail!,
                      onVerify: (code) async {
                        await widget.api.verifySignupCode(
                          email: _confirmEmail!,
                          code: code,
                        );
                        await logAnalyticsEvent(
                          'sign_up',
                          params: {'method': 'email_otp'},
                        );
                        widget.onDone();
                      },
                      onResend: () =>
                          widget.api.resendConfirmation(_confirmEmail!),
                      onChangeEmail: () => setState(() => _confirmEmail = null),
                      onLogin: widget.onLogin,
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
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                ),
                                SizedBox(width: 10),
                                Text(
                                  'Hämtar bolaget från Bolagsverket …',
                                  style: TextStyle(
                                    color: TbColors.muted,
                                    fontSize: 13,
                                  ),
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
                              style: TextStyle(
                                color: TbColors.danger,
                                fontSize: 13,
                              ),
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
                              helperText:
                                  'Vi ringer och hjälper dig i gång under provet.',
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
                                _Step(
                                  n: 3,
                                  text: 'Ge förarna en kod — provet startar',
                                ),
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
                            onPressed: _busy || _registryBlocks
                                ? null
                                : _submit,
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

/// Kontot är skapat; e-posten bekräftas med koden i mejlet (6 siffror).
/// Rätt kod loggar in direkt och registrerar företaget. Länken i samma mejl
/// fungerar som reserv ("Tryckte du på länken? Logga in").
class _CodeCard extends StatefulWidget {
  const _CodeCard({
    required this.email,
    required this.onVerify,
    required this.onResend,
    required this.onChangeEmail,
    required this.onLogin,
  });

  final String email;
  final Future<void> Function(String code) onVerify;
  final Future<void> Function() onResend;
  final VoidCallback onChangeEmail;
  final VoidCallback onLogin;

  @override
  State<_CodeCard> createState() => _CodeCardState();
}

class _CodeCardState extends State<_CodeCard> {
  static const _length = 6;
  static const _cooldown = 60;

  final _code = TextEditingController();
  String? _error;
  String? _note;
  bool _busy = false;
  int _wait = _cooldown;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _startCooldown();
    _code.addListener(() {
      final digits = _code.text.replaceAll(RegExp(r'\D'), '');
      if (digits.length == _length && !_busy) _verify();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _code.dispose();
    super.dispose();
  }

  /// Utan setState: anropas också från initState. Anroparna ritar om själva.
  void _startCooldown() {
    _timer?.cancel();
    _wait = _cooldown;
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return t.cancel();
      setState(() => _wait--);
      if (_wait <= 0) t.cancel();
    });
  }

  Future<void> _verify() async {
    final code = _code.text.replaceAll(RegExp(r'\D'), '');
    if (code.length != _length) {
      setState(() => _error = 'Skriv de $_length siffrorna från mejlet.');
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
      _note = null;
    });
    try {
      await widget.onVerify(code);
    } catch (e) {
      if (!mounted) return;
      final text = e.toString();
      setState(() {
        _error = text.contains('expired') || text.contains('invalid')
            ? 'Koden stämmer inte eller har gått ut. Försök igen eller begär en ny.'
            : (netFailureOf(e) != null
                  ? netMessage(netFailureOf(e)!)
                  : 'Det gick inte att bekräfta. Försök igen.');
      });
      _code.clear();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _resend() async {
    setState(() {
      _busy = true;
      _error = null;
      _note = null;
    });
    try {
      await widget.onResend();
      _note = 'Ny kod skickad till ${widget.email}.';
      _startCooldown();
    } catch (e) {
      // Supabase begränsar hur ofta samma adress får ett nytt mejl.
      _error = e.toString().contains('seconds')
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
          const Icon(
            Icons.mark_email_read_outlined,
            size: 52,
            color: TbColors.taxiDeep,
          ),
          const SizedBox(height: 14),
          const Text(
            'Skriv koden från mejlet',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontFamily: kDisplayFont,
              fontSize: 24,
              fontWeight: FontWeight.w800,
              color: TbColors.ink,
            ),
          ),
          const SizedBox(height: 8),
          Text.rich(
            TextSpan(
              style: const TextStyle(color: TbColors.muted, height: 1.4),
              children: [
                const TextSpan(text: 'Vi skickade en kod med 6 siffror till\n'),
                TextSpan(
                  text: widget.email,
                  style: const TextStyle(
                    color: TbColors.ink,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 20),
          TextField(
            controller: _code,
            enabled: !_busy,
            autofocus: true,
            keyboardType: TextInputType.number,
            autofillHints: const [AutofillHints.oneTimeCode],
            maxLength: _length,
            textAlign: TextAlign.center,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            style: const TextStyle(
              fontSize: 30,
              fontWeight: FontWeight.w800,
              letterSpacing: 14,
              color: TbColors.ink,
            ),
            decoration: InputDecoration(
              counterText: '',
              hintText: '••••••',
              hintStyle: const TextStyle(
                color: TbColors.sand,
                letterSpacing: 14,
              ),
              filled: true,
              fillColor: TbColors.foam,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: BorderSide.none,
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: const BorderSide(color: TbColors.navy, width: 2),
              ),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(
              _error!,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: TbColors.danger,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
          if (_note != null) ...[
            const SizedBox(height: 10),
            Text(
              _note!,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: TbColors.live,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
          const SizedBox(height: 18),
          FilledButton(
            onPressed: _busy ? null : _verify,
            style: FilledButton.styleFrom(
              backgroundColor: TbColors.taxi,
              foregroundColor: TbColors.ink,
              minimumSize: const Size.fromHeight(54),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
              ),
            ),
            child: _busy
                ? const SizedBox(
                    height: 22,
                    width: 22,
                    child: CircularProgressIndicator(
                      color: TbColors.ink,
                      strokeWidth: 2.5,
                    ),
                  )
                : const Text(
                    'Bekräfta',
                    style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
                  ),
          ),
          const SizedBox(height: 6),
          TextButton(
            onPressed: _busy || _wait > 0 ? null : _resend,
            child: Text(
              _wait > 0 ? 'Skicka ny kod om $_wait s' : 'Skicka ny kod',
            ),
          ),
          Text(
            'Syns inget? Titta i skräpposten.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey.shade600, fontSize: 13),
          ),
          const SizedBox(height: 4),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              TextButton(
                onPressed: _busy ? null : widget.onChangeEmail,
                child: const Text('Ändra e-post'),
              ),
              const Text('·', style: TextStyle(color: TbColors.muted)),
              TextButton(
                onPressed: _busy ? null : widget.onLogin,
                child: const Text('Tryckte på länken? Logga in'),
              ),
            ],
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
            blocks
                ? Icons.block
                : (warn ? Icons.warning_amber : Icons.verified),
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
                      style: TextStyle(
                        color: color,
                        fontWeight: FontWeight.w600,
                      ),
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
