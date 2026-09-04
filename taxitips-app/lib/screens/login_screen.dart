import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../api_client.dart';
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
    defaultValue: true,
  );
  static const _prefillEmail = String.fromEnvironment(
    'PREFILL_EMAIL',
    defaultValue: 'test@taxitips.se',
  );
  static const _prefillPassword = String.fromEnvironment(
    'PREFILL_PASSWORD',
    defaultValue: 'TaxiTips123!',
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
      widget.onLoggedIn();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _oauth(String provider) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final ok = provider == 'google'
          ? await widget.api.signInWithGoogle()
          : await widget.api.signInWithApple();
      if (!ok && mounted) {
        setState(
          () => _error =
              'Kunde inte starta ${provider == 'google' ? 'Google' : 'Apple'}-inloggningen.',
        );
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_ready) {
      return const Scaffold(
        backgroundColor: TbColors.asphalt,
        body: Center(child: CircularProgressIndicator(color: TbColors.taxi)),
      );
    }
    return Scaffold(
      backgroundColor: TbColors.asphalt,
      appBar: AppBar(
        backgroundColor: TbColors.asphalt,
        leading: IconButton(
          tooltip: 'Tillbaka',
          onPressed: widget.onBack,
          icon: const Icon(Icons.arrow_back),
        ),
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SvgPicture.asset(
                    'assets/brand/logo-on-dark.svg',
                    width: 320,
                    height: 74,
                    fit: BoxFit.contain,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Rätt plats. Rätt tid.\nKontor: logga in · Förare: bolagskod',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: TbColors.foam, height: 1.4),
                  ),
                  const SizedBox(height: 28),
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      color: TbColors.foam,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text(
                          'Kontor',
                          style: TextStyle(
                            fontWeight: FontWeight.w800,
                            fontSize: 18,
                          ),
                        ),
                        const SizedBox(height: 14),
                        TextField(
                          controller: _email,
                          decoration: const InputDecoration(
                            labelText: 'E-post',
                          ),
                          keyboardType: TextInputType.emailAddress,
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _password,
                          decoration: const InputDecoration(
                            labelText: 'Lösenord',
                          ),
                          obscureText: true,
                          onSubmitted: (_) => _submit(),
                        ),
                        if (_error != null) ...[
                          const SizedBox(height: 12),
                          Text(
                            _error!,
                            style: const TextStyle(
                              color: TbColors.danger,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                        const SizedBox(height: 18),
                        FilledButton(
                          onPressed: _busy ? null : _submit,
                          child: Text(_busy ? 'Loggar in…' : 'Logga in'),
                        ),
                        TextButton(
                          onPressed: widget.onSignup,
                          child: const Text('Skapa företagskonto'),
                        ),
                        const SizedBox(height: 4),
                        Row(
                          children: [
                            const Expanded(child: Divider()),
                            Padding(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 12,
                              ),
                              child: Text(
                                'eller',
                                style: TextStyle(
                                  color: Colors.grey.shade600,
                                  fontSize: 13,
                                ),
                              ),
                            ),
                            const Expanded(child: Divider()),
                          ],
                        ),
                        const SizedBox(height: 12),
                        OutlinedButton.icon(
                          onPressed: _busy ? null : () => _oauth('google'),
                          icon: const Icon(Icons.g_mobiledata, size: 22),
                          label: const Text('Fortsätt med Google'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: TbColors.ink,
                            minimumSize: const Size.fromHeight(48),
                          ),
                        ),
                        const SizedBox(height: 10),
                        OutlinedButton.icon(
                          onPressed: _busy ? null : () => _oauth('apple'),
                          icon: const Icon(Icons.apple, size: 22),
                          label: const Text('Fortsätt med Apple'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: TbColors.ink,
                            minimumSize: const Size.fromHeight(48),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: TbColors.taxi,
                      side: const BorderSide(color: TbColors.taxi),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                    onPressed: widget.onJoinPhone,
                    icon: const Icon(Icons.phone_android),
                    label: const Text('Jag kör — registrera telefon med kod'),
                  ),
                  if (widget.onDemo != null) ...[
                    const SizedBox(height: 10),
                    TextButton(
                      onPressed: widget.onDemo,
                      child: const Text(
                        'Prova förardemo (utan login)',
                        style: TextStyle(
                          color: TbColors.foam,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
