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
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SvgPicture.asset(
                    'assets/brand/logo-on-dark.svg',
                    width: 240,
                    height: 70,
                    fit: BoxFit.contain,
                  ),
                  const SizedBox(height: 24),
                  const Text(
                    'Logga in till kontoret',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: kDisplayFont,
                      color: TbColors.foam,
                      fontSize: 26,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 32),
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
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TextField(
                          controller: _email,
                          decoration: InputDecoration(
                            labelText: 'E-post',
                            prefixIcon: const Icon(Icons.email_outlined),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          keyboardType: TextInputType.emailAddress,
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _password,
                          decoration: InputDecoration(
                            labelText: 'Lösenord',
                            prefixIcon: const Icon(Icons.lock_outline),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          obscureText: true,
                          onSubmitted: (_) => _submit(),
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
                                const Icon(Icons.error_outline, color: TbColors.danger, size: 20),
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
                            minimumSize: const Size.fromHeight(56),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          child: _busy 
                              ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                              : const Text('Logga in med e-post', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                        ),
                        // Bara på webben -- se welcome_screen.dart.
                        if (kIsWeb) ...[
                          const SizedBox(height: 12),
                          TextButton(
                            onPressed: widget.onSignup,
                            child: const Text('Skapa företagskonto'),
                          ),
                        ],
                        const SizedBox(height: 24),
                        Row(
                          children: [
                            Expanded(child: Divider(color: Colors.grey.shade300)),
                            Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 16),
                              child: Text(
                                'ELLER',
                                style: TextStyle(
                                  color: Colors.grey.shade500,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  letterSpacing: 1,
                                ),
                              ),
                            ),
                            Expanded(child: Divider(color: Colors.grey.shade300)),
                          ],
                        ),
                        const SizedBox(height: 24),
                        OutlinedButton.icon(
                          onPressed: _busy ? null : () => _oauth('google'),
                          icon: Icon(Icons.g_mobiledata, size: 28), // Fallback if no asset, but usually there's one. Assuming standard icon.
                          label: const Text('Fortsätt med Google', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: TbColors.ink,
                            side: BorderSide(color: Colors.grey.shade300),
                            minimumSize: const Size.fromHeight(52),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          ),
                        ),
                        const SizedBox(height: 12),
                        OutlinedButton.icon(
                          onPressed: _busy ? null : () => _oauth('apple'),
                          icon: const Icon(Icons.apple, size: 24),
                          label: const Text('Fortsätt med Apple', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: TbColors.ink,
                            side: BorderSide(color: Colors.grey.shade300),
                            minimumSize: const Size.fromHeight(52),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          ),
                        ),
                      ],
                    ),
                  ),
                  
                  // For those who accidentally ended up here
                  const SizedBox(height: 32),
                  Row(
                    children: [
                      const Expanded(child: Divider(color: Colors.white24, thickness: 1)),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        child: Text('ÄR DU FÖRARE?', style: TextStyle(color: Colors.white54, fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 1)),
                      ),
                      const Expanded(child: Divider(color: Colors.white24, thickness: 1)),
                    ],
                  ),
                  const SizedBox(height: 24),
                  
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: TbColors.foam,
                      side: const BorderSide(color: Colors.white30, width: 1.5),
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                    ),
                    onPressed: widget.onJoinPhone,
                    icon: const Icon(Icons.phone_android),
                    label: const Text('Anslut bil med bolagskod', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
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
