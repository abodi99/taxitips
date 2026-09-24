import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../api_client.dart';
import '../push_service.dart';
import '../theme.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    required this.api,
    required this.onLoggedIn,
    required this.onSignup,
    required this.onJoinPhone,
    required this.onBack,
    this.onDemo,
  });

  final ApiClient api;
  final VoidCallback onLoggedIn;
  final VoidCallback onSignup;
  final VoidCallback onJoinPhone;
  final VoidCallback onBack;
  final VoidCallback? onDemo;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  static const _prefillEnabled = bool.fromEnvironment(
    'ENABLE_TEST_LOGIN',
    defaultValue: kDebugMode,
  );
  static const _prefillEmail = String.fromEnvironment(
    'PREFILL_EMAIL',
    defaultValue: 'agare@malmotaxi.se',
  );
  static const _prefillPassword = String.fromEnvironment(
    'PREFILL_PASSWORD',
    defaultValue: 'taxitips123',
  );

  final _email = TextEditingController();
  final _password = TextEditingController();
  String? _error;
  bool _busy = false;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _prefill();
  }

  Future<void> _prefill() async {
    if (!mounted) return;
    setState(() {
      if (_prefillEnabled) {
        _email.text = _prefillEmail;
        _password.text = _prefillPassword;
      }
      _ready = true;
    });
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final email = _email.text.trim();
    final password = _password.text;
    if (email.isEmpty || password.isEmpty) {
      setState(() => _error = 'Fyll i e-post och lösenord först.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.login(email: email, password: password);
      await registerForPush(widget.api);
      widget.onLoggedIn();
    } catch (e) {
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Supabase Auths engelska fel, i klartext.
  String _friendly(Object e) {
    final text = e.toString();
    if (text.contains('Invalid login credentials')) {
      return 'Fel e-post eller lösenord.';
    }
    if (text.contains('Email not confirmed')) {
      return 'Bekräfta din e-post först. Titta i inkorgen.';
    }
    if (e is ApiException) return e.message;
    return 'Det gick inte att logga in. Försök igen.';
  }

  @override
  Widget build(BuildContext context) {
    if (!_ready) {
      return const Scaffold(
        backgroundColor: TbColors.asphalt,
        body: Center(child: CircularProgressIndicator(color: TbColors.taxi)),
      );
    }
    // En sida, ett jobb: ägaren eller kontoret loggar in. Föraren och nya
    // företag har var sin tydlig väg härifrån. Google/Apple visas inte: de
    // är inte påslagna i produktionens Supabase Auth, och en knapp som inte
    // fungerar är värre än ingen.
    return Scaffold(
      backgroundColor: TbColors.navy,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(
          tooltip: 'Tillbaka',
          onPressed: widget.onBack,
          icon: const Icon(Icons.arrow_back, color: TbColors.foam),
        ),
      ),
      extendBodyBehindAppBar: true,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SvgPicture.asset(
                    'assets/brand/logo-on-dark.svg',
                    width: 200,
                    height: 58,
                    fit: BoxFit.contain,
                  ),
                  const SizedBox(height: 28),
                  const Text(
                    'Logga in',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: kDisplayFont,
                      color: TbColors.foam,
                      fontSize: 30,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'För ägare och kontor',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white70, fontSize: 16),
                  ),
                  const SizedBox(height: 24),
                  Container(
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(24),
                    ),
                    child: AutofillGroup(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          TextField(
                            controller: _email,
                            keyboardType: TextInputType.emailAddress,
                            autofillHints: const [AutofillHints.email],
                            textInputAction: TextInputAction.next,
                            decoration: InputDecoration(
                              labelText: 'E-post',
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
                            autofillHints: const [AutofillHints.password],
                            onSubmitted: (_) => _submit(),
                            decoration: InputDecoration(
                              labelText: 'Lösenord',
                              prefixIcon: const Icon(Icons.lock_outline),
                              border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                            ),
                          ),
                          if (_error != null) ...[
                            const SizedBox(height: 14),
                            Row(
                              children: [
                                const Icon(
                                  Icons.error_outline,
                                  color: TbColors.danger,
                                  size: 20,
                                ),
                                const SizedBox(width: 8),
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
                          ],
                          const SizedBox(height: 20),
                          FilledButton(
                            onPressed: _busy ? null : _submit,
                            style: FilledButton.styleFrom(
                              backgroundColor: TbColors.taxi,
                              foregroundColor: TbColors.ink,
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
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 28),
                  _Choice(
                    icon: Icons.local_taxi_outlined,
                    title: 'Jag är förare',
                    subtitle: 'Ange koden från din chef',
                    onTap: widget.onJoinPhone,
                  ),
                  const SizedBox(height: 12),
                  _Choice(
                    icon: Icons.add_business_outlined,
                    title: 'Nytt företag',
                    subtitle: 'Prova gratis i 14 dagar',
                    onTap: widget.onSignup,
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

/// En stor, tydlig väg vidare: ikon, en rad, en förklaring på fem ord.
class _Choice extends StatelessWidget {
  const _Choice({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white.withValues(alpha: 0.06),
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: Colors.white24, width: 1.5),
          ),
          child: Row(
            children: [
              Icon(icon, color: TbColors.taxi, size: 28),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        color: TbColors.foam,
                        fontSize: 17,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    Text(
                      subtitle,
                      style: const TextStyle(color: Colors.white70, fontSize: 14),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Colors.white54),
            ],
          ),
        ),
      ),
    );
  }
}
