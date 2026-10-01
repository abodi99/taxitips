import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../api_client.dart';
import '../net_status.dart';
import '../theme.dart';

/// "Jag är förare": logga in med e-posten chefen bjöd in.
///
/// Föraren fick ett mejl, valde lösenord på taxitips.se/forare och loggar in
/// här. Servern löser in inbjudan och kopplar telefonen till bilen
/// (fleet/driver_invites.py) -- samma godkännande som en engångskod. Koden
/// finns kvar som reserv: "Har du en kod?".
///
/// Enkel svenska och stora knappar: många förare har svenska som andraspråk
/// och använder appen i bilen.
class DriverLoginScreen extends StatefulWidget {
  const DriverLoginScreen({
    super.key,
    required this.api,
    required this.onPaired,
    required this.onOwner,
    required this.onUseCode,
    required this.onBack,
  });

  final ApiClient api;

  /// Telefonen är kopplad till bilen.
  final VoidCallback onPaired;

  /// Kontot hör till ett företag (ägaren valde fel väg): fortsätt som ägare.
  final VoidCallback onOwner;
  final VoidCallback onUseCode;
  final VoidCallback onBack;

  @override
  State<DriverLoginScreen> createState() => _DriverLoginScreenState();
}

class _DriverLoginScreenState extends State<DriverLoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  String? _error;
  String? _notice;
  bool _busy = false;

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
      setState(() => _error = 'Skriv din e-post och ditt lösenord.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      final result = await widget.api.driverLogin(
        email: email,
        password: password,
      );
      if (!mounted) return;
      if (result['owner'] == true) {
        widget.onOwner();
      } else {
        widget.onPaired();
      }
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
        _error = 'Skriv din e-post först. Sedan trycker du Glömt lösenord.';
      });
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      await widget.api.sendDriverPasswordReset(email);
      if (!mounted) return;
      setState(
        () => _notice =
            'Vi har skickat ett mejl till $email. Tryck på länken, välj ett '
            'nytt lösenord och logga in här igen.',
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
      return 'Fel e-post eller lösenord. Har du inte valt lösenord än? '
          'Tryck på länken i mejlet från din chef.';
    }
    if (text.contains('Email not confirmed')) {
      return 'Tryck på länken i mejlet först.';
    }
    if (text.contains('rate limit') || text.contains('security purposes')) {
      return 'Vänta en minut och försök igen.';
    }
    if (e is ApiException) return e.message;
    final net = netFailureOf(e);
    if (net != null) return netMessage(net);
    return 'Det gick inte att logga in. Försök igen.';
  }

  @override
  Widget build(BuildContext context) {
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
                    'Jag är förare',
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
                    'Logga in med e-posten som din chef bjöd in.',
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
                            autocorrect: false,
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
                            onSubmitted: (_) => _busy ? null : _submit(),
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
                            _Message(text: _error!, error: true),
                          ],
                          if (_notice != null) ...[
                            const SizedBox(height: 14),
                            _Message(text: _notice!, error: false),
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
                          const SizedBox(height: 4),
                          TextButton(
                            onPressed: _busy ? null : _forgot,
                            style: TextButton.styleFrom(
                              minimumSize: const Size.fromHeight(48),
                            ),
                            child: const Text(
                              'Glömt lösenord?',
                              style: TextStyle(fontWeight: FontWeight.w700),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Ingen inbjudan? Be din chef bjuda in dig med din e-post.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white70, fontSize: 14),
                  ),
                  const SizedBox(height: 20),
                  Material(
                    color: Colors.white.withValues(alpha: 0.06),
                    borderRadius: BorderRadius.circular(16),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(16),
                      onTap: _busy ? null : widget.onUseCode,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 14,
                        ),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(color: Colors.white24, width: 1.5),
                        ),
                        child: const Row(
                          children: [
                            Icon(Icons.pin_outlined, color: TbColors.taxi, size: 28),
                            SizedBox(width: 14),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Har du en kod?',
                                    style: TextStyle(
                                      color: TbColors.foam,
                                      fontSize: 17,
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                  Text(
                                    'Anslut med koden från din chef',
                                    style: TextStyle(
                                      color: Colors.white70,
                                      fontSize: 14,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Icon(Icons.chevron_right, color: Colors.white54),
                          ],
                        ),
                      ),
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

class _Message extends StatelessWidget {
  const _Message({required this.text, required this.error});

  final String text;
  final bool error;

  @override
  Widget build(BuildContext context) {
    final color = error ? TbColors.danger : TbColors.live;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(
          error ? Icons.error_outline : Icons.mark_email_read_outlined,
          color: color,
          size: 20,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            text,
            style: TextStyle(color: color, fontWeight: FontWeight.w600),
          ),
        ),
      ],
    );
  }
}
