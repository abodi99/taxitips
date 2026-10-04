import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../api_client.dart';
import '../net_status.dart';
import '../theme.dart';

/// Inloggningen: EN för förare, ägare och kontor, bara e-post och lösenord.
///
/// Ingen ska behöva veta vilken "väg" de hör till -- servern avgör rollen
/// (ApiClient.signIn): medlem i ett företag ser företagsvyn, en inbjuden
/// förare kopplas till sin bil. Ingen bolagskod: föraren bjuds in med e-post.
///
/// Enkel svenska och stora mål: många förare har svenska som andraspråk och
/// använder appen i bilen.
class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    required this.api,
    required this.onOwner,
    required this.onDriver,
    required this.onSignup,
    required this.onBack,
  });

  final ApiClient api;

  /// Kontot hör till ett företag (eller registrerar ett).
  final VoidCallback onOwner;

  /// Telefonen är kopplad till förarens bil.
  final VoidCallback onDriver;
  final VoidCallback onSignup;
  final VoidCallback onBack;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  // Förifyllt testkonto, BARA i debugbyggen och bara när det skickas in vid
  // bygget: `flutter run --dart-define=PREFILL_EMAIL=… --dart-define=PREFILL_PASSWORD=…`
  // (konton ur `manage.py seed_local_demo`, se DEV.md). Inga standardvärden:
  // en adress eller ett lösenord här följde med i varje byggd app, även den i
  // butikerna. `kDebugMode` är en konstant, så releasebygget saknar grenen.
  static const _prefillEnabled =
      kDebugMode &&
      bool.fromEnvironment('ENABLE_TEST_LOGIN', defaultValue: true);
  static const _prefillEmail = String.fromEnvironment('PREFILL_EMAIL');
  static const _prefillPassword = String.fromEnvironment('PREFILL_PASSWORD');

  final _email = TextEditingController();
  final _password = TextEditingController();
  final _passwordFocus = FocusNode();
  bool _hidePassword = true;
  bool _busy = false;
  String? _error;
  String? _notice;

  @override
  void initState() {
    super.initState();
    if (_prefillEnabled && _prefillEmail.isNotEmpty) {
      _email.text = _prefillEmail;
      _password.text = _prefillPassword;
    }
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _passwordFocus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final email = _email.text.trim();
    final password = _password.text;
    if (email.isEmpty || password.isEmpty) {
      setState(() {
        _notice = null;
        _error = 'Skriv din e-post och ditt lösenord.';
      });
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      final role = await widget.api.signIn(email: email, password: password);
      TextInput.finishAutofillContext();
      if (!mounted) return;
      role == 'owner' ? widget.onOwner() : widget.onDriver();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _forgot() async {
    final email = _email.text.trim();
    if (email.isEmpty || !email.contains('@')) {
      setState(() {
        _notice = null;
        _error = 'Skriv din e-post först. Tryck sedan på Glömt lösenord.';
      });
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      await widget.api.sendPasswordReset(email);
      if (!mounted) return;
      setState(
        () => _notice =
            'Vi har mejlat en länk till $email. Välj ett nytt lösenord och '
            'logga in här igen.',
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Supabase Auths engelska fel och serverns skäl, i enkel svenska.
  String _friendly(Object e) {
    final text = e.toString();
    if (text.contains('Invalid login credentials')) {
      return 'Fel e-post eller lösenord. Ny förare? Välj först ett lösenord '
          'med länken i inbjudan, eller tryck Glömt lösenord.';
    }
    if (text.contains('Email not confirmed')) {
      return 'Bekräfta din e-post först. Tryck på länken i mejlet.';
    }
    if (text.contains('rate limit') || text.contains('security purposes')) {
      return 'Vänta en minut och försök igen.';
    }
    if (e is ApiException) {
      if (e.reason == 'no_invite') {
        return 'Kontot är inte kopplat till något företag. Be din chef bjuda '
            'in dig, eller registrera ditt företag nedan.';
      }
      if (e.reason == 'device_swap_limit') {
        return e.message.isNotEmpty
            ? e.message
            : 'Du har bytt telefon två gånger den här månaden. '
                  'Kontakta support så hjälper vi dig byta igen.';
      }
      return e.message;
    }
    final net = netFailureOf(e);
    if (net != null) return netMessage(net);
    return 'Det gick inte att logga in. Försök igen.';
  }

  InputDecoration _field(String label, IconData icon, {Widget? suffix}) =>
      InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon),
        suffixIcon: suffix,
        filled: true,
        fillColor: const Color(0xFFF5F7FA),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 18,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: Color(0xFFE2E6EC)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: TbColors.navy, width: 2),
        ),
      );

  @override
  Widget build(BuildContext context) {
    // Navy huvud, vit panel under. Vanliga block i en scrollbar kolumn (ingen
    // intrinsic-mätning): på en låg skärm eller med tangentbordet uppe
    // scrollar man, och under panelen fortsätter vitt.
    return Scaffold(
      backgroundColor: Colors.white,
      body: LayoutBuilder(
        builder: (context, constraints) => SingleChildScrollView(
          physics: const ClampingScrollPhysics(),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ColoredBox(
                color: TbColors.navy,
                child: SafeArea(
                  bottom: false,
                  child: Stack(
                    children: [
                      _Header(compact: constraints.maxHeight < 680),
                      IconButton(
                        tooltip: 'Tillbaka',
                        onPressed: _busy ? null : widget.onBack,
                        icon: const Icon(
                          Icons.arrow_back,
                          color: TbColors.foam,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              ColoredBox(color: TbColors.navy, child: _panel(context)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _panel(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      padding: EdgeInsets.fromLTRB(
        24,
        28,
        24,
        24 + MediaQuery.paddingOf(context).bottom,
      ),
      child: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: AutofillGroup(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Logga in',
                  style: TextStyle(
                    fontFamily: kDisplayFont,
                    color: TbColors.ink,
                    fontSize: 26,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 4),
                const Text(
                  'För förare, ägare och kontor. Ny förare? Välj först ett '
                  'lösenord med länken i inbjudan.',
                  style: TextStyle(color: TbColors.muted, fontSize: 15),
                ),
                const SizedBox(height: 22),
                TextField(
                  controller: _email,
                  enabled: !_busy,
                  keyboardType: TextInputType.emailAddress,
                  autocorrect: false,
                  enableSuggestions: false,
                  autofillHints: const [
                    AutofillHints.email,
                    AutofillHints.username,
                  ],
                  textInputAction: TextInputAction.next,
                  onSubmitted: (_) => _passwordFocus.requestFocus(),
                  style: const TextStyle(fontSize: 17),
                  decoration: _field('E-post', Icons.mail_outline),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _password,
                  focusNode: _passwordFocus,
                  enabled: !_busy,
                  obscureText: _hidePassword,
                  autofillHints: const [AutofillHints.password],
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => _busy ? null : _submit(),
                  style: const TextStyle(fontSize: 17),
                  decoration: _field(
                    'Lösenord',
                    Icons.lock_outline,
                    suffix: IconButton(
                      tooltip: _hidePassword
                          ? 'Visa lösenord'
                          : 'Dölj lösenord',
                      onPressed: () =>
                          setState(() => _hidePassword = !_hidePassword),
                      icon: Icon(
                        _hidePassword
                            ? Icons.visibility_outlined
                            : Icons.visibility_off_outlined,
                      ),
                    ),
                  ),
                ),
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                    onPressed: _busy ? null : _forgot,
                    style: TextButton.styleFrom(
                      foregroundColor: TbColors.navy,
                      minimumSize: const Size(48, 44),
                    ),
                    child: const Text(
                      'Glömt lösenord?',
                      style: TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
                ),
                if (_error != null) _Message(text: _error!, error: true),
                if (_notice != null) _Message(text: _notice!, error: false),
                const SizedBox(height: 8),
                FilledButton(
                  onPressed: _busy ? null : _submit,
                  style: FilledButton.styleFrom(
                    backgroundColor: TbColors.taxi,
                    foregroundColor: TbColors.ink,
                    disabledBackgroundColor: TbColors.taxi.withValues(
                      alpha: 0.6,
                    ),
                    minimumSize: const Size.fromHeight(56),
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
                          'Logga in',
                          style: TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                ),
                const SizedBox(height: 28),
                _LinkRow(
                  lead: 'Inget konto?',
                  action: 'Registrera ditt företag',
                  onTap: _busy ? null : widget.onSignup,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Logga och en mening om vad appen gör. Kortare på små skärmar, så att
/// formuläret syns utan att man scrollar när tangentbordet är uppe.
class _Header extends StatelessWidget {
  const _Header({required this.compact});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
        28,
        compact ? 16 : 48,
        28,
        compact ? 20 : 36,
      ),
      child: Column(
        children: [
          SvgPicture.asset(
            'assets/brand/logo-on-dark.svg',
            width: 220,
            height: compact ? 52 : 64,
            fit: BoxFit.contain,
          ),
          const SizedBox(height: 14),
          const Text(
            'Se var folk behöver taxi,\ninnan kön växer.',
            textAlign: TextAlign.center,
            style: TextStyle(color: TbColors.foam, fontSize: 16, height: 1.35),
          ),
        ],
      ),
    );
  }
}

/// "Fråga? Svar" på en rad: en kort fråga och en tydlig länk. Hela raden är
/// tryckbar och minst 48 punkter hög.
class _LinkRow extends StatelessWidget {
  const _LinkRow({required this.lead, required this.action, this.onTap});

  final String lead;
  final String action;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 48),
        child: Center(
          child: Text.rich(
            TextSpan(
              style: const TextStyle(fontSize: 15, color: TbColors.muted),
              children: [
                TextSpan(text: '$lead '),
                TextSpan(
                  text: action,
                  style: const TextStyle(
                    color: TbColors.navy,
                    fontWeight: FontWeight.w700,
                    decoration: TextDecoration.underline,
                  ),
                ),
              ],
            ),
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message({required this.text, required this.error});

  final String text;
  final bool error;

  @override
  Widget build(BuildContext context) {
    final color = error ? TbColors.danger : TbColors.live;
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            error ? Icons.error_outline : Icons.mark_email_read_outlined,
            color: color,
            size: 20,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                color: color,
                fontWeight: FontWeight.w600,
                height: 1.35,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
