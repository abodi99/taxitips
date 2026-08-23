import 'package:flutter/material.dart';

import '../api_client.dart';
import '../theme.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    required this.api,
    required this.onLoggedIn,
    required this.onSignup,
    required this.onJoinPhone,
    this.onDemo,
  });

  final ApiClient api;
  final VoidCallback onLoggedIn;
  final VoidCallback onSignup;
  final VoidCallback onJoinPhone;
  final VoidCallback? onDemo;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
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
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.login(email: _email.text.trim(), password: _password.text);
      widget.onLoggedIn();
    } catch (e) {
      setState(() => _error = e.toString());
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
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Image(
                    image: AssetImage('assets/brand/splash_wordmark.png'),
                    height: 72,
                    fit: BoxFit.contain,
                    filterQuality: FilterQuality.high,
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
                        const Text('Kontor', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18)),
                        const SizedBox(height: 14),
                        TextField(
                          controller: _email,
                          decoration: const InputDecoration(labelText: 'E-post'),
                          keyboardType: TextInputType.emailAddress,
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _password,
                          decoration: const InputDecoration(labelText: 'Lösenord'),
                          obscureText: true,
                          onSubmitted: (_) => _submit(),
                        ),
                        if (_error != null) ...[
                          const SizedBox(height: 12),
                          Text(_error!, style: const TextStyle(color: TbColors.danger, fontWeight: FontWeight.w600)),
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
                        style: TextStyle(color: TbColors.foam, fontWeight: FontWeight.w700),
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
