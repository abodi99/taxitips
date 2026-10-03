import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../api_client.dart';
import '../net_status.dart';
import '../theme.dart';

/// "Jag är förare": bara e-post. Chefen har redan bjudit in adressen till en
/// bil och valt länen (fleet/driver_invites.py). Föraren skriver sin e-post,
/// får en sexsiffrig kod i mejlet och skriver in den -- sedan är telefonen
/// kopplad till bilen. Inget lösenord, ingen kod att få uppläst.
///
/// Koden i mejlet finns för säkerhetens skull: utan den hade vem som helst
/// som känner till förarens e-post kunnat ta förarens bil.
///
/// Enkel svenska och stora mål: många förare har svenska som andraspråk och
/// använder appen i bilen.
class DriverLoginScreen extends StatefulWidget {
  const DriverLoginScreen({
    super.key,
    required this.api,
    required this.onDone,
    required this.onBack,
  });

  final ApiClient api;
  final VoidCallback onDone;
  final VoidCallback onBack;

  @override
  State<DriverLoginScreen> createState() => _DriverLoginScreenState();
}

class _DriverLoginScreenState extends State<DriverLoginScreen> {
  final _email = TextEditingController();
  final _code = TextEditingController();
  final _codeFocus = FocusNode();
  bool _codeSent = false;
  bool _busy = false;
  String? _error;
  String? _notice;

  @override
  void dispose() {
    _email.dispose();
    _code.dispose();
    _codeFocus.dispose();
    super.dispose();
  }

  Future<void> _sendCode() async {
    final email = _email.text.trim();
    if (!email.contains('@') || !email.contains('.')) {
      setState(() {
        _notice = null;
        _error = 'Skriv din e-post, till exempel namn@exempel.se.';
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
      await widget.api.driverLoginStart(email);
      if (!mounted) return;
      setState(() {
        _codeSent = true;
        _code.clear();
        _notice =
            'Om din chef har bjudit in $email kommer en kod till mejlet nu. '
            'Titta också i skräpposten.';
      });
      _codeFocus.requestFocus();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verify() async {
    final code = _code.text.replaceAll(RegExp(r'\D'), '');
    if (code.length != 6) {
      setState(() {
        _notice = null;
        _error = 'Koden har sex siffror. Du hittar den i mejlet.';
      });
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.driverLoginVerify(email: _email.text, code: code);
      TextInput.finishAutofillContext();
      if (!mounted) return;
      widget.onDone();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _friendly(Object e) {
    if (e is ApiException) {
      switch (e.reason) {
        case 'invalid_code':
          return 'Fel kod. Kontrollera mejlet och försök igen.';
        case 'code_expired':
          return 'Koden har gått ut. Tryck på "Skicka ny kod".';
        case 'too_many_attempts':
          return 'För många försök. Tryck på "Skicka ny kod".';
        case 'no_invite':
        case 'invite_used':
        case 'invite_expired':
          return 'Vi hittar ingen inbjudan för den här e-posten. Be din chef '
              'bjuda in dig i Taxi Tips.';
        case 'driver_blocked':
        case 'vehicle_changed':
        case 'device_swap_limit':
          return e.message;
        case 'rate_limited':
          return 'Vänta en stund och försök igen.';
      }
      if (e.message.isNotEmpty) return e.message;
    }
    final net = netFailureOf(e);
    if (net != null) return netMessage(net);
    return 'Det gick inte att logga in. Försök igen.';
  }

  InputDecoration _field(String label, IconData icon) => InputDecoration(
    labelText: label,
    prefixIcon: Icon(icon),
    filled: true,
    fillColor: const Color(0xFFF5F7FA),
    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
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

  Widget _primary(String label, VoidCallback onPressed) => FilledButton(
    onPressed: _busy ? null : onPressed,
    style: FilledButton.styleFrom(
      backgroundColor: TbColors.taxi,
      foregroundColor: TbColors.ink,
      disabledBackgroundColor: TbColors.taxi.withValues(alpha: 0.6),
      minimumSize: const Size.fromHeight(56),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
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
        : Text(
            label,
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
          ),
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: SingleChildScrollView(
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
                    Padding(
                      padding: const EdgeInsets.fromLTRB(28, 40, 28, 32),
                      child: Center(
                        child: SvgPicture.asset(
                          'assets/brand/logo-on-dark.svg',
                          width: 220,
                          height: 60,
                          fit: BoxFit.contain,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: 'Tillbaka',
                      onPressed: _busy ? null : widget.onBack,
                      icon: const Icon(Icons.arrow_back, color: TbColors.foam),
                    ),
                  ],
                ),
              ),
            ),
            ColoredBox(
              color: TbColors.navy,
              child: Container(
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
                    child: AutofillGroup(child: _form()),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _form() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Jag är förare',
          style: TextStyle(
            fontFamily: kDisplayFont,
            color: TbColors.ink,
            fontSize: 26,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          _codeSent
              ? 'Skriv koden från mejlet.'
              : 'Skriv e-posten som din chef bjöd in. Du behöver inget lösenord.',
          style: const TextStyle(color: TbColors.muted, fontSize: 15),
        ),
        const SizedBox(height: 22),
        TextField(
          controller: _email,
          enabled: !_busy && !_codeSent,
          keyboardType: TextInputType.emailAddress,
          autocorrect: false,
          enableSuggestions: false,
          autofillHints: const [AutofillHints.email],
          textInputAction: TextInputAction.send,
          onSubmitted: (_) => _busy ? null : _sendCode(),
          style: const TextStyle(fontSize: 17),
          decoration: _field('E-post', Icons.mail_outline),
        ),
        if (_codeSent) ...[
          const SizedBox(height: 14),
          TextField(
            controller: _code,
            focusNode: _codeFocus,
            enabled: !_busy,
            keyboardType: TextInputType.number,
            autofillHints: const [AutofillHints.oneTimeCode],
            inputFormatters: [
              FilteringTextInputFormatter.digitsOnly,
              LengthLimitingTextInputFormatter(6),
            ],
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _busy ? null : _verify(),
            style: const TextStyle(
              fontSize: 26,
              letterSpacing: 8,
              fontWeight: FontWeight.w800,
            ),
            decoration: _field('Kod (6 siffror)', Icons.pin_outlined),
          ),
        ],
        const SizedBox(height: 14),
        if (_error != null) _Message(text: _error!, error: true),
        if (_notice != null && _error == null)
          _Message(text: _notice!, error: false),
        const SizedBox(height: 4),
        _codeSent
            ? _primary('Logga in', _verify)
            : _primary('Skicka kod', _sendCode),
        if (_codeSent) ...[
          const SizedBox(height: 8),
          TextButton(
            onPressed: _busy ? null : _sendCode,
            style: TextButton.styleFrom(
              foregroundColor: TbColors.navy,
              minimumSize: const Size.fromHeight(48),
            ),
            child: const Text(
              'Skicka ny kod',
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
          TextButton(
            onPressed: _busy
                ? null
                : () => setState(() {
                    _codeSent = false;
                    _error = null;
                    _notice = null;
                  }),
            style: TextButton.styleFrom(
              foregroundColor: TbColors.muted,
              minimumSize: const Size.fromHeight(48),
            ),
            child: const Text('Byt e-post'),
          ),
        ],
        const SizedBox(height: 16),
        const Text(
          'Ingen inbjudan? Be din chef bjuda in dig i Taxi Tips.',
          textAlign: TextAlign.center,
          style: TextStyle(color: TbColors.muted, fontSize: 13.5),
        ),
      ],
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
