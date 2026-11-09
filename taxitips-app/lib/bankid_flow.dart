import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
import 'theme.dart';

/// Vad BankID gav: namnet att hälsa med och biljetten servern kräver i nästa
/// steg. Personnumret når aldrig appen (fleet/bankid.py).
class BankIdResult {
  const BankIdResult({
    required this.ticket,
    required this.name,
    required this.givenName,
  });

  final String ticket;
  final String name;
  final String givenName;
}

/// Legitimering med BankID på samma telefon, i ett ark. Samma flöde som
/// Volonteras `bankid_auth_service.dart`: starta, öppna BankID-appen med
/// autostart-token, fråga servern varannan sekund. Null = avbrutet.
Future<BankIdResult?> runBankId(
  BuildContext context,
  ApiClient api, {
  required String purpose,
}) {
  return showModalBottomSheet<BankIdResult>(
    context: context,
    isDismissible: false,
    enableDrag: false,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
    ),
    builder: (_) => _BankIdSheet(api: api, purpose: purpose),
  );
}

/// BankID:s egen adress för autostart. Öppnar BankID-appen om den finns.
Uri bankIdAutostartUri(String autoStartToken) => Uri.parse(
  'https://app.bankid.com/?autostarttoken=$autoStartToken&redirect=null',
);

class _BankIdSheet extends StatefulWidget {
  const _BankIdSheet({required this.api, required this.purpose});

  final ApiClient api;
  final String purpose;

  @override
  State<_BankIdSheet> createState() => _BankIdSheetState();
}

class _BankIdSheetState extends State<_BankIdSheet> {
  static const _interval = Duration(seconds: 2);
  // BankID låter en order leva i tre minuter.
  static const _maxWait = Duration(minutes: 3);

  String? _orderRef;
  String? _autoStart;
  String _message = 'Startar BankID …';
  String? _error;
  Timer? _timer;
  DateTime? _startedAt;
  bool _done = false;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _start() async {
    setState(() {
      _error = null;
      _message = 'Startar BankID …';
    });
    try {
      final data = await widget.api.bankIdStart(widget.purpose);
      _orderRef = data['orderRef']?.toString();
      _autoStart = data['autoStartToken']?.toString();
      _startedAt = DateTime.now();
      if (!mounted) return;
      setState(() => _message = 'Öppna BankID-appen.');
      await _openApp();
      _timer?.cancel();
      _timer = Timer.periodic(_interval, (_) => _poll());
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) setState(() => _error = 'BankID svarar inte just nu.');
    }
  }

  Future<void> _openApp() async {
    final token = _autoStart;
    if (token == null || token.isEmpty) return;
    final opened = await launchUrl(
      bankIdAutostartUri(token),
      mode: LaunchMode.externalApplication,
    );
    if (!opened && mounted) {
      setState(
        () => _message =
            'Vi kunde inte öppna BankID-appen. Kontrollera att den är installerad.',
      );
    }
  }

  bool _polling = false;

  Future<void> _poll() async {
    final ref = _orderRef;
    if (ref == null || _polling || _done) return;
    if (_startedAt != null &&
        DateTime.now().difference(_startedAt!) > _maxWait) {
      _timer?.cancel();
      await widget.api.bankIdCancel(ref);
      if (mounted) {
        setState(() => _error = 'Det tog för lång tid. Försök igen.');
      }
      return;
    }
    _polling = true;
    try {
      final data = await widget.api.bankIdCollect(ref);
      if (!mounted) return;
      final status = data['status']?.toString();
      final message = data['message']?.toString();
      if (status == 'complete') {
        _done = true;
        _timer?.cancel();
        Navigator.of(context).pop(
          BankIdResult(
            ticket: data['ticket'].toString(),
            name: data['name']?.toString() ?? '',
            givenName: data['givenName']?.toString() ?? '',
          ),
        );
        return;
      }
      if (status == 'failed') {
        _timer?.cancel();
        setState(
          () => _error = message ?? 'Legitimeringen misslyckades. Försök igen.',
        );
        return;
      }
      setState(() => _message = message ?? 'Fortsätt i BankID-appen.');
    } on ApiException catch (e) {
      _timer?.cancel();
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      // Tappat nät en stund: nästa poll försöker igen.
    } finally {
      _polling = false;
    }
  }

  Future<void> _cancel() async {
    _timer?.cancel();
    final ref = _orderRef;
    if (ref != null && !_done) await widget.api.bankIdCancel(ref);
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final failed = _error != null;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Legitimera dig med BankID',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontFamily: kDisplayFont,
                color: TbColors.ink,
                fontSize: 22,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 20),
            if (!failed)
              const Center(
                child: SizedBox(
                  width: 32,
                  height: 32,
                  child: CircularProgressIndicator(strokeWidth: 3),
                ),
              ),
            const SizedBox(height: 16),
            Text(
              _error ?? _message,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: failed ? TbColors.danger : TbColors.ink,
                fontSize: 15,
                fontWeight: failed ? FontWeight.w600 : FontWeight.normal,
              ),
            ),
            const SizedBox(height: 24),
            if (failed)
              FilledButton(
                onPressed: _start,
                style: FilledButton.styleFrom(
                  backgroundColor: TbColors.ink,
                  foregroundColor: TbColors.foam,
                  minimumSize: const Size.fromHeight(52),
                ),
                child: const Text('Försök igen'),
              )
            else
              OutlinedButton(
                onPressed: _autoStart == null ? null : _openApp,
                style: OutlinedButton.styleFrom(
                  foregroundColor: TbColors.ink,
                  minimumSize: const Size.fromHeight(52),
                ),
                child: const Text('Öppna BankID igen'),
              ),
            const SizedBox(height: 8),
            TextButton(onPressed: _cancel, child: const Text('Avbryt')),
          ],
        ),
      ),
    );
  }
}

/// Glömt lösenord eller bytt e-post, för konton som skapats med BankID:
/// legitimera, välj nytt lösenord (och ny e-post om du vill). Returnerar
/// adressen att logga in med, eller null om användaren avbröt.
Future<String?> recoverWithBankId(BuildContext context, ApiClient api) async {
  final identity = await runBankId(context, api, purpose: 'recover');
  if (identity == null || !context.mounted) return null;
  return showDialog<String>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _RecoverDialog(api: api, identity: identity),
  );
}

class _RecoverDialog extends StatefulWidget {
  const _RecoverDialog({required this.api, required this.identity});

  final ApiClient api;
  final BankIdResult identity;

  @override
  State<_RecoverDialog> createState() => _RecoverDialogState();
}

class _RecoverDialogState extends State<_RecoverDialog> {
  final _password = TextEditingController();
  final _email = TextEditingController();
  bool _changeEmail = false;
  bool _hide = true;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _password.dispose();
    _email.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_password.text.length < 8) {
      setState(() => _error = 'Lösenordet behöver minst 8 tecken.');
      return;
    }
    if (_changeEmail && !_email.text.contains('@')) {
      setState(() => _error = 'Skriv en giltig e-postadress.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final email = await widget.api.bankIdRecover(
        ticket: widget.identity.ticket,
        newPassword: _password.text,
        newEmail: _changeEmail ? _email.text : '',
      );
      if (mounted) Navigator.of(context).pop(email);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) setState(() => _error = 'Något gick fel. Försök igen.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final name = widget.identity.givenName;
    return AlertDialog(
      title: Text(name.isEmpty ? 'Nytt lösenord' : 'Hej $name!'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Välj ett nytt lösenord för ditt konto.'),
            const SizedBox(height: 16),
            TextField(
              controller: _password,
              obscureText: _hide,
              decoration: InputDecoration(
                labelText: 'Nytt lösenord (minst 8 tecken)',
                border: const OutlineInputBorder(),
                suffixIcon: IconButton(
                  tooltip: _hide ? 'Visa lösenord' : 'Dölj lösenord',
                  onPressed: () => setState(() => _hide = !_hide),
                  icon: Icon(
                    _hide
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                  ),
                ),
              ),
            ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: _changeEmail,
              onChanged: (v) => setState(() => _changeEmail = v ?? false),
              title: const Text('Byt också e-postadress'),
            ),
            if (_changeEmail)
              TextField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: 'Ny e-postadress',
                  border: OutlineInputBorder(),
                ),
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
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(),
          child: const Text('Avbryt'),
        ),
        FilledButton(
          onPressed: _busy ? null : _save,
          child: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Spara'),
        ),
      ],
    );
  }
}
