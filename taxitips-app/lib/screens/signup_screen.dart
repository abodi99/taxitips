import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../api_client.dart';
import '../bankid_flow.dart';
import '../l10n/l10n.dart';
import '../membership_copy.dart';
import '../net_status.dart';
import '../theme.dart';
import '../widgets/ltr_input.dart';
import '../widgets/password_visibility.dart';

/// Ett steg i registreringen efter BankID. En fråga per skärm.
enum SignupStep { kind, company, phone, email, password }

/// Registreringen (2026-11): BankID först, sedan EN fråga per skärm -- "Hur
/// kör du?", (företagets namn), mobil, e-post, lösenord. Kontot och provet
/// skapas direkt på servern (fleet/registration.py:register_with_bankid).
///
/// **Ingen behöver ett företag.** "Jag kör själv" skapar kontot i personens
/// namn från BankID (`accountKind: private`), utan företagsnamn och utan
/// organisationsnummer. Ett taxibolag skriver bara namnet; organisationsnumret
/// anges först om kunden vill fortsätta efter provet.
///
/// Byggd för den som inte är van vid appar: en sak i taget, stor text, ett
/// exempel under varje fält, felet vid fältet (inte längst ner), "Steg 2 av 4"
/// överst och Tillbaka som går ett steg bakåt utan att tömma något.
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

  /// En fokusnod per fråga. Markören ska stå kvar i fältet efter ett fel och
  /// flytta in i nästa fält av sig själv -- med nästa frågas tangentbord.
  final _focus = {for (final s in SignupStep.values) s: FocusNode()};
  FocusNode get _fieldFocus => _focus[_step]!;
  BankIdResult? _identity;

  /// null = inte valt än, true = kör själv utan företag.
  bool? _private;
  SignupStep _step = SignupStep.kind;

  /// Felet på det här steget, visat vid fältet.
  String? _error;

  /// Ett besked på BankID-steget (t.ex. att BankID-biljetten gått ut).
  String? _startError;

  /// Servern säger att personen eller adressen redan har ett konto: visa
  /// "Logga in" direkt vid beskedet i stället för att låta hen leta.
  bool _offerLogin = false;
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
    for (final node in _focus.values) {
      node.dispose();
    }
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
      return tr.signupScreenDateInvalid;
    }
    var age = now.year - born.year;
    if (now.month < born.month ||
        (now.month == born.month && now.day < born.day)) {
      age--;
    }
    if (age < 18) {
      return tr.signupScreenUnder18;
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

  static final _emailShape = RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$');

  /// Stegen för det val som gjorts. Företagsnamnet bara för ett taxibolag.
  List<SignupStep> get _steps => [
    SignupStep.kind,
    if (_private == false) SignupStep.company,
    SignupStep.phone,
    SignupStep.email,
    SignupStep.password,
  ];

  Future<void> _bankId() async {
    setState(() => _startError = null);
    final result = await runBankId(context, widget.api, purpose: 'register');
    if (!mounted || result == null) return;
    setState(() {
      _identity = result;
      _step = SignupStep.kind;
      _error = null;
    });
  }

  void _choose(bool private) {
    setState(() {
      _private = private;
      _error = null;
      _offerLogin = false;
      _step = private ? SignupStep.phone : SignupStep.company;
    });
    _focusField();
  }

  /// Vad som är fel på ett steg, i vanliga ord och med ett exempel.
  String? _problem(SignupStep step) => switch (step) {
    SignupStep.kind => _private == null ? tr.signupScreenProblemChoose : null,
    SignupStep.company =>
      _company.text.trim().isEmpty ? tr.signupScreenProblemCompany : null,
    SignupStep.phone =>
      phoneLooksValid(_phone.text) ? null : tr.signupScreenProblemPhone,
    SignupStep.email =>
      _emailShape.hasMatch(_email.text.trim())
          ? null
          : tr.signupScreenProblemEmail,
    SignupStep.password =>
      _password.text.length < 8 ? tr.signupScreenProblemPassword : null,
  };

  void _next() {
    if (_busy) return;
    final problem = _problem(_step);
    if (problem != null) {
      setState(() => _error = problem);
      _focusField();
      return;
    }
    final steps = _steps;
    final i = steps.indexOf(_step);
    if (i == steps.length - 1) {
      _submit();
      return;
    }
    setState(() {
      _error = null;
      _offerLogin = false;
      _step = steps[i + 1];
    });
    _focusField();
  }

  /// Markören i fältet efter nästa ritning (det nya steget eller felet).
  void _focusField() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _identity != null && _step != SignupStep.kind) {
        _fieldFocus.requestFocus();
      }
    });
  }

  /// Ett steg bakåt. Det som skrivits finns kvar. Från första frågan tillbaka
  /// till BankID-steget (BankID görs då om).
  void _back() {
    final steps = _steps;
    final i = steps.indexOf(_step);
    setState(() {
      _error = null;
      _offerLogin = false;
      if (i <= 0) {
        _identity = null;
        _private = null;
      } else {
        _step = steps[i - 1];
      }
    });
  }

  /// Vilket steg ett fel från servern hör till, så att föraren hamnar där
  /// felet kan rättas.
  static SignupStep? _stepFor(String? reason) {
    final r = reason ?? '';
    if (r.contains('email')) return SignupStep.email;
    if (r.contains('phone')) return SignupStep.phone;
    if (r.contains('password')) return SignupStep.password;
    if (r.contains('name')) return SignupStep.company;
    return null;
  }

  Future<void> _submit() async {
    final identity = _identity;
    if (identity == null) return;
    for (final step in _steps) {
      final problem = _problem(step);
      if (problem != null) {
        setState(() {
          _step = step;
          _error = problem;
        });
        return;
      }
    }
    setState(() {
      _busy = true;
      _error = null;
      _offerLogin = false;
    });
    try {
      await widget.api.bankIdRegister(
        ticket: identity.ticket,
        email: _email.text,
        password: _password.text,
        phone: _phone.text,
        companyName: _company.text,
        private: _private == true,
      );
      widget.onDone();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        // Biljetten gäller i 15 minuter. Har den gått ut börjar man om med
        // BankID; det som skrivits finns kvar.
        if (e.reason == 'ticket_expired' || e.reason == 'invalid_ticket') {
          _identity = null;
          _startError = e.message;
          return;
        }
        _error = e.message;
        _offerLogin =
            e.reason == 'person_has_account' || e.reason == 'email_taken';
        final target = _stepFor(e.reason);
        if (target != null && _steps.contains(target)) _step = target;
      });
      _focusField();
    } catch (e) {
      if (!mounted) return;
      final net = netFailureOf(e);
      setState(
        () => _error = net != null
            ? netMessage(net)
            : tr.signupScreenSomethingWrong,
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // --- Byggstenar --------------------------------------------------------

  Widget _title(String text) => Text(
    text,
    textAlign: TextAlign.center,
    style: const TextStyle(
      fontFamily: kDisplayFont,
      color: TbColors.ink,
      fontSize: 28,
      height: 1.15,
      fontWeight: FontWeight.w800,
    ),
  );

  /// Frågan på ett steg: stor rubrik och en rad förklaring.
  Widget _question(String text, {String? help}) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        text,
        style: const TextStyle(
          fontFamily: kDisplayFont,
          color: TbColors.ink,
          fontSize: 26,
          height: 1.15,
          fontWeight: FontWeight.w800,
        ),
      ),
      if (help != null) ...[
        const SizedBox(height: 8),
        Text(
          help,
          style: const TextStyle(
            color: TbColors.muted,
            fontSize: 17,
            height: 1.35,
          ),
        ),
      ],
    ],
  );

  ButtonStyle get _primary => FilledButton.styleFrom(
    backgroundColor: TbColors.ink,
    foregroundColor: TbColors.foam,
    minimumSize: const Size.fromHeight(58),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
  );

  /// "Steg 2 av 4" och en stapel, så att det syns hur långt det är kvar.
  Widget _progress() {
    final steps = _steps;
    final n = steps.indexOf(_step) + 1;
    return Semantics(
      label: tr.signupScreenStepOf(n, steps.length),
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tr.signupScreenStepOf(n, steps.length),
            style: const TextStyle(
              color: TbColors.muted,
              fontSize: 15,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: n / steps.length,
              minHeight: 8,
              backgroundColor: TbColors.ljusgraDjup,
              color: TbColors.taxi,
            ),
          ),
        ],
      ),
    );
  }

  /// Ett stort fält: frågan står ovanför, exemplet i fältet, felet under.
  Widget _input({
    required TextEditingController controller,
    required String label,
    required IconData icon,
    String? hint,
    TextInputType? keyboard,
    List<String>? autofill,
    bool obscure = false,
    Widget? suffix,
    TextCapitalization capitalization = TextCapitalization.none,
    bool suggestions = false,
    bool last = false,
    // Mobil, e-post, lösenord: vänster till höger även på arabiska.
    bool ltr = false,
  }) => TextField(
    // Ett nytt fält per fråga (nyckel och fokusnod per steg). Förut byttes
    // bara tangentbordstypen på ETT fält som behöll fokus, och telefonens
    // tangentbord (Samsung, Gboard, iOS) byter då inte: siffror stod kvar på
    // e-postfrågan och bokstäver på mobilfrågan. Ett nytt fält kopplar upp
    // tangentbordet på nytt med rätt typ; Flutter håller det uppe under bytet,
    // så det blinkar inte bort mellan frågorna.
    key: ValueKey(_step),
    controller: controller,
    focusNode: _fieldFocus,
    autofocus: true,
    enabled: !_busy,
    keyboardType: keyboard,
    autofillHints: autofill,
    autocorrect: false,
    enableSuggestions: suggestions,
    // Fältet, felet under det och Nästa-knappen ska synas ovanför
    // tangentbordet: iPhones siffertangentbord (mobilfrågan) har ingen
    // Nästa-tangent, så knappen är enda vägen vidare där.
    scrollPadding: const EdgeInsets.only(bottom: 220),
    obscureText: obscure,
    textCapitalization: capitalization,
    textDirection: ltr ? kLtrInputDirection : null,
    textAlign: ltr ? ltrInputAlign(context) : TextAlign.start,
    textInputAction: last ? TextInputAction.done : TextInputAction.next,
    // I stället för standardbeteendet, som flyttar markören till knappen
    // eller stänger tangentbordet: samma sak som att trycka på Nästa.
    onEditingComplete: _next,
    onChanged: (_) {
      if (_error != null || _step == SignupStep.password) {
        setState(() => _error = null);
      }
    },
    style: const TextStyle(fontSize: 20),
    decoration: InputDecoration(
      labelText: label,
      hintText: hint,
      hintTextDirection: ltr ? kLtrInputDirection : null,
      floatingLabelBehavior: FloatingLabelBehavior.always,
      errorText: _error == null ? null : ltrRuns(_error!),
      errorMaxLines: 4,
      errorStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      prefixIcon: Icon(icon),
      suffixIcon: suffix,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 20),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
    ),
  );

  /// Tre korta löften med bock. Lätta att läsa även med lite svenska.
  Widget _promises() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      for (final line in kBankIdPromises)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(
            children: [
              const Icon(Icons.check_circle, color: TbColors.taxi, size: 26),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  line,
                  style: const TextStyle(
                    color: TbColors.ink,
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
        ),
    ],
  );

  Widget _errorBox(String text) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: TbColors.danger.withValues(alpha: 0.1),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      children: [
        const Icon(Icons.error_outline, color: TbColors.danger, size: 22),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(
              color: TbColors.danger,
              fontSize: 16,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    ),
  );

  // --- Stegen ------------------------------------------------------------

  List<Widget> _bankIdStep() => [
    _title(tr.signupScreenTitle),
    const SizedBox(height: 20),
    _promises(),
    const SizedBox(height: 24),
    if (_startError != null) ...[
      _errorBox(_startError!),
      const SizedBox(height: 16),
    ],
    FilledButton.icon(
      onPressed: _bankId,
      style: _primary,
      icon: const Icon(Icons.fingerprint, size: 26),
      label: Text(
        tr.signupScreenContinueBankId,
        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
      ),
    ),
    const SizedBox(height: 12),
    TextButton(
      onPressed: widget.onLogin,
      style: TextButton.styleFrom(
        foregroundColor: TbColors.navy,
        minimumSize: const Size.fromHeight(52),
      ),
      child: Text(
        tr.signupScreenHaveAccount,
        style: const TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.w700,
          decoration: TextDecoration.underline,
        ),
      ),
    ),
  ];

  List<Widget> _kindStep(BankIdResult identity) {
    final hello = identity.givenName.isNotEmpty
        ? identity.givenName
        : identity.name;
    return [
      _question(
        hello.isEmpty
            ? tr.signupScreenKindQuestion
            : tr.signupScreenKindQuestionNamed(hello),
      ),
      const SizedBox(height: 20),
      _ChoiceCard(
        icon: Icons.person_rounded,
        title: tr.signupScreenSoloTitle,
        text: tr.signupScreenSoloText,
        selected: _private == true,
        onTap: () => _choose(true),
      ),
      const SizedBox(height: 12),
      _ChoiceCard(
        icon: Icons.local_taxi_rounded,
        title: tr.signupScreenCompanyTitle,
        text: tr.signupScreenCompanyText,
        selected: _private == false,
        onTap: () => _choose(false),
      ),
      const SizedBox(height: 16),
      Text(
        tr.signupScreenNotSure,
        style: const TextStyle(color: TbColors.muted, fontSize: 16),
      ),
      if (_error != null) ...[const SizedBox(height: 12), _errorBox(_error!)],
    ];
  }

  List<Widget> _fieldStep() {
    final last = _step == SignupStep.password;
    final field = switch (_step) {
      SignupStep.company => [
        _question(
          tr.signupScreenCompanyQuestion,
          help: tr.signupScreenCompanyHelp,
        ),
        const SizedBox(height: 20),
        _input(
          controller: _company,
          label: tr.signupScreenCompanyLabel,
          hint: tr.signupScreenCompanyHint,
          icon: Icons.business_outlined,
          keyboard: TextInputType.text,
          autofill: const [AutofillHints.organizationName],
          capitalization: TextCapitalization.words,
          // Ett firmanamn är vanliga ord: förslagen hjälper.
          suggestions: true,
        ),
      ],
      SignupStep.phone => [
        _question(tr.signupScreenPhoneQuestion),
        const SizedBox(height: 20),
        _input(
          controller: _phone,
          ltr: true,
          label: tr.signupScreenPhoneLabel,
          hint: '070 123 45 67',
          icon: Icons.phone_outlined,
          keyboard: TextInputType.phone,
          autofill: const [AutofillHints.telephoneNumber],
        ),
      ],
      SignupStep.email => [
        _question(tr.signupScreenEmailQuestion, help: tr.signupScreenEmailHelp),
        const SizedBox(height: 20),
        _input(
          controller: _email,
          ltr: true,
          label: tr.signupScreenEmailLabel,
          hint: 'namn@gmail.com',
          icon: Icons.email_outlined,
          keyboard: TextInputType.emailAddress,
          autofill: const [AutofillHints.email],
        ),
      ],
      SignupStep.password => [
        _question(tr.signupScreenPasswordQuestion),
        const SizedBox(height: 20),
        _input(
          controller: _password,
          ltr: true,
          label: tr.signupScreenPasswordLabel,
          icon: Icons.lock_outline,
          obscure: _hidePassword,
          // Lösenordstangentbordet: inga ordförslag, ingen autokorrigering,
          // och telefonens lösenordshanterare kan föreslå ett starkt lösenord.
          keyboard: TextInputType.visiblePassword,
          autofill: const [AutofillHints.newPassword],
          last: true,
          suffix: PasswordVisibilityButton(
            hidden: _hidePassword,
            onToggle: () => setState(() => _hidePassword = !_hidePassword),
          ),
        ),
        const SizedBox(height: 12),
        _Requirement(
          met: _password.text.length >= 8,
          text: tr.signupScreenPasswordMin,
        ),
      ],
      SignupStep.kind => const <Widget>[],
    };
    return [
      ...field,
      if (_offerLogin) ...[
        const SizedBox(height: 12),
        OutlinedButton(
          onPressed: widget.onLogin,
          style: OutlinedButton.styleFrom(
            foregroundColor: TbColors.ink,
            minimumSize: const Size.fromHeight(56),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
          ),
          child: Text(
            tr.signupScreenLoginInstead,
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
          ),
        ),
      ],
      const SizedBox(height: 24),
      FilledButton(
        onPressed: _busy ? null : _next,
        style: _primary,
        child: _busy
            ? const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(
                  strokeWidth: 2.5,
                  color: TbColors.foam,
                ),
              )
            : Text(
                last ? tr.signupScreenCreateAccount : tr.signupScreenNext,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final identity = _identity;
    final List<Widget> content;
    if (identity == null) {
      content = _bankIdStep();
    } else {
      content = [
        _progress(),
        const SizedBox(height: 24),
        ...(_step == SignupStep.kind ? _kindStep(identity) : _fieldStep()),
      ];
    }
    return PopScope(
      // Systemets bakåt (Android) går ett steg bakåt, som pilen.
      canPop: identity == null,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && !_busy) _back();
      },
      child: Scaffold(
        backgroundColor: TbColors.navy,
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          elevation: 0,
          leading: widget.onBack == null && identity == null
              ? null
              : IconButton(
                  tooltip: tr.signupScreenBack,
                  onPressed: _busy
                      ? null
                      : (identity != null ? _back : widget.onBack),
                  icon: const Icon(Icons.arrow_back, color: TbColors.foam),
                ),
        ),
        extendBodyBehindAppBar: true,
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 32),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 480),
                child: Column(
                  children: [
                    SvgPicture.asset(
                      'assets/brand/logo-on-dark.svg',
                      width: identity == null ? 240 : 170,
                      height: identity == null ? 70 : 48,
                      fit: BoxFit.contain,
                    ),
                    SizedBox(height: identity == null ? 32 : 20),
                    Container(
                      padding: const EdgeInsets.all(24),
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
                      child: AutofillGroup(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: content,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Ett stort val med ikon, rubrik och en rad förklaring. Hela kortet är
/// tryckbart och minst 88 punkter högt.
class _ChoiceCard extends StatelessWidget {
  const _ChoiceCard({
    required this.icon,
    required this.title,
    required this.text,
    required this.selected,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String text;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      child: Material(
        color: selected ? TbColors.taxi.withValues(alpha: 0.12) : Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(
            color: selected ? TbColors.taxi : TbColors.line,
            width: selected ? 2.5 : 1.5,
          ),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 88),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 26,
                    backgroundColor: TbColors.navy,
                    child: Icon(icon, color: TbColors.taxi, size: 28),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          title,
                          style: const TextStyle(
                            color: TbColors.ink,
                            fontSize: 19,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          text,
                          style: const TextStyle(
                            color: TbColors.muted,
                            fontSize: 16,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const Icon(Icons.chevron_right, color: TbColors.muted),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Ett krav med bock som blir grön när det är uppfyllt (lösenordet).
class _Requirement extends StatelessWidget {
  const _Requirement({required this.met, required this.text});

  final bool met;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(
          met ? Icons.check_circle : Icons.radio_button_unchecked,
          color: met ? TbColors.live : TbColors.muted,
          size: 22,
        ),
        const SizedBox(width: 8),
        Text(
          text,
          style: TextStyle(
            color: met ? TbColors.live : TbColors.muted,
            fontSize: 16,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}
