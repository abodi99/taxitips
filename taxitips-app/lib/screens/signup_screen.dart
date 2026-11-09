import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../api_client.dart';
import '../bankid_flow.dart';
import '../membership_copy.dart';
import '../net_status.dart';
import '../theme.dart';
import '../widgets/password_visibility.dart';

/// Registreringen (2026-11): BankID först, sedan e-post, lösenord, mobil och
/// företagets namn. Kontot och provet skapas direkt på servern
/// (fleet/registration.py:register_with_bankid) -- ingen länk i mejlet och
/// inget organisationsnummer. Det anges i kundportalen om kunden vill
/// fortsätta efter provet.
class SignupScreen extends StatefulWidget {
  const SignupScreen({
    super.key,
    required this.api,
    required this.onDone,
    required this.onLogin,
    this.onBack,
    this.initialIdentity,
  });

  final ApiClient api;
  final VoidCallback onDone;
  final VoidCallback onLogin;
  final VoidCallback? onBack;

  /// Bara för tester och förhandsvisning: hoppa över BankID-steget.
  final BankIdResult? initialIdentity;

  @override
  State<SignupScreen> createState() => SignupScreenState();
}

class SignupScreenState extends State<SignupScreen> {
  final _company = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _phone = TextEditingController();
  BankIdResult? _identity;
  String? _error;
  bool _busy = false;
  bool _hidePassword = true;

  @override
  void initState() {
    super.initState();
    // Ingen förifyllning: en ny registrering börjar med tomma fält.
    _identity = widget.initialIdentity;
  }

  @override
  void dispose() {
    _company.dispose();
    _email.dispose();
    _password.dispose();
    _phone.dispose();
    super.dispose();
  }

  // Formkontrollerna nedan används inte längre i registreringen (BankID ersatte
  // organisationsnumret) men är samma regler som servern och prövas i
  // test/signup_org_test.dart. Mobilnumret prövas fortfarande här.

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

  Future<void> _bankId() async {
    setState(() => _error = null);
    final result = await runBankId(context, widget.api, purpose: 'register');
    if (!mounted || result == null) return;
    setState(() => _identity = result);
  }

  Future<void> _submit() async {
    final identity = _identity;
    if (identity == null) return;
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
      await widget.api.bankIdRegister(
        ticket: identity.ticket,
        email: _email.text,
        password: _password.text,
        phone: _phone.text,
        companyName: _company.text,
      );
      widget.onDone();
    } on ApiException catch (e) {
      setState(() {
        _error = e.message;
        // Biljetten gäller i 15 minuter. Har den gått ut börjar man om med
        // BankID; det som skrivits finns kvar.
        if (e.reason == 'ticket_expired' || e.reason == 'invalid_ticket') {
          _identity = null;
        }
      });
    } catch (e) {
      final net = netFailureOf(e);
      setState(
        () => _error = net != null
            ? netMessage(net)
            : 'Något gick fel. Försök igen.',
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _validate() {
    if (_company.text.trim().isEmpty) {
      return 'Skriv namnet på företaget du kör för.';
    }
    if (!phoneLooksValid(_phone.text)) {
      return 'Skriv ett svenskt mobilnummer, till exempel 070-123 45 67.';
    }
    if (!_email.text.contains('@')) return 'Skriv en giltig e-postadress.';
    if (_password.text.length < 8) return 'Lösenordet behöver minst 8 tecken.';
    return null;
  }

  InputDecoration _field(String label, IconData icon, {String? helper}) =>
      InputDecoration(
        labelText: label,
        helperText: helper,
        helperMaxLines: 2,
        prefixIcon: Icon(icon),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      );

  Widget _title(String text) => Text(
    text,
    textAlign: TextAlign.center,
    style: const TextStyle(
      fontFamily: kDisplayFont,
      color: TbColors.ink,
      fontSize: 28,
      fontWeight: FontWeight.w800,
    ),
  );

  Widget _note(String text, {IconData icon = Icons.verified_user_outlined}) =>
      Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: TbColors.foam,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: TbColors.line),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: TbColors.ink, size: 20),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                text,
                style: const TextStyle(
                  color: TbColors.ink,
                  fontSize: 14,
                  height: 1.4,
                ),
              ),
            ),
          ],
        ),
      );

  ButtonStyle get _primary => FilledButton.styleFrom(
    backgroundColor: TbColors.ink,
    foregroundColor: TbColors.foam,
    minimumSize: const Size.fromHeight(56),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
  );

  List<Widget> _bankIdStep() => [
    _title('Starta en veckas gratis prov'),
    const SizedBox(height: 8),
    Text(
      'En bil i ett län i 7 dagar. Inget kort behövs. Under provet visas tåg och buss.',
      textAlign: TextAlign.center,
      style: TextStyle(color: Colors.grey.shade600, fontSize: 14, height: 1.4),
    ),
    const SizedBox(height: 24),
    FilledButton.icon(
      onPressed: _bankId,
      style: _primary,
      icon: const Icon(Icons.fingerprint),
      label: const Text(
        'Fortsätt med BankID',
        style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
      ),
    ),
    const SizedBox(height: 16),
    _note(kBankIdNoCommitment),
    const SizedBox(height: 16),
    const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Step(n: 1, text: 'Legitimera dig med BankID'),
        _Step(n: 2, text: 'Skriv e-post, lösenord, mobil och företag'),
        _Step(n: 3, text: 'Välj län – provet startar direkt'),
      ],
    ),
  ];

  List<Widget> _detailsStep(BankIdResult identity) {
    final hello = identity.givenName.isNotEmpty
        ? identity.givenName
        : identity.name;
    return [
      _title(hello.isEmpty ? 'Nästan klart' : 'Hej $hello!'),
      const SizedBox(height: 8),
      Text(
        'Du är legitimerad. Nu behöver vi bara det här för att skapa kontot.',
        textAlign: TextAlign.center,
        style: TextStyle(
          color: Colors.grey.shade600,
          fontSize: 14,
          height: 1.4,
        ),
      ),
      const SizedBox(height: 24),
      TextField(
        controller: _company,
        textCapitalization: TextCapitalization.words,
        decoration: _field(
          'Företaget du kör för',
          Icons.business_outlined,
          helper: 'Namnet räcker. Organisationsnummer behövs inte nu.',
        ),
      ),
      const SizedBox(height: 16),
      TextField(
        controller: _phone,
        keyboardType: TextInputType.phone,
        decoration: _field(
          'Mobilnummer',
          Icons.phone_outlined,
          helper: 'Vi ringer och hjälper dig i gång under provet.',
        ),
      ),
      const SizedBox(height: 16),
      TextField(
        controller: _email,
        keyboardType: TextInputType.emailAddress,
        autocorrect: false,
        decoration: _field('E-postadress', Icons.email_outlined),
      ),
      const SizedBox(height: 16),
      TextField(
        controller: _password,
        obscureText: _hidePassword,
        decoration: _field('Lösenord (minst 8 tecken)', Icons.lock_outline)
            .copyWith(
              suffixIcon: PasswordVisibilityButton(
                hidden: _hidePassword,
                onToggle: () => setState(() => _hidePassword = !_hidePassword),
              ),
            ),
      ),
      const SizedBox(height: 16),
      _note(kBankIdLaterDetails, icon: Icons.info_outline),
      if (_error != null) ...[const SizedBox(height: 16), _errorBox(_error!)],
      const SizedBox(height: 24),
      FilledButton(
        onPressed: _busy ? null : _submit,
        style: _primary,
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
                'Skapa konto och starta provet',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              ),
      ),
    ];
  }

  Widget _errorBox(String text) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: TbColors.danger.withValues(alpha: 0.1),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      children: [
        const Icon(Icons.error_outline, color: TbColors.danger, size: 20),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(
              color: TbColors.danger,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final identity = _identity;
    return Scaffold(
      backgroundColor: TbColors.navy,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: widget.onBack == null && identity == null
            ? null
            : IconButton(
                tooltip: 'Tillbaka',
                onPressed: identity != null
                    ? () => setState(() {
                        _identity = null;
                        _error = null;
                      })
                    : widget.onBack,
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
                children: [
                  SvgPicture.asset(
                    'assets/brand/logo-on-dark.svg',
                    width: 240,
                    height: 70,
                    fit: BoxFit.contain,
                  ),
                  const SizedBox(height: 32),
                  Container(
                    padding: const EdgeInsets.all(28),
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
                        ...(identity == null
                            ? _bankIdStep()
                            : _detailsStep(identity)),
                        if (identity == null && _error != null) ...[
                          const SizedBox(height: 16),
                          _errorBox(_error!),
                        ],
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
