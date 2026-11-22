import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';
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
    this.accountEmail,
  });

  final String ticket;
  final String name;
  final String givenName;

  /// Bara vid återställning: kontots e-post, eller null om personen inte har
  /// något BankID-konto.
  final String? accountEmail;
}

/// Legitimering med BankID i ett ark: på den här telefonen (BankID-appen öppnas
/// direkt) eller på en annan (QR-kod). Fråga servern tills ordern är klar.
/// Null = avbrutet.
Future<BankIdResult?> runBankId(
  BuildContext context,
  ApiClient api, {
  required String purpose,
}) {
  return showModalBottomSheet<BankIdResult>(
    context: context,
    isDismissible: false,
    enableDrag: false,
    // QR-koden behöver mer än halva skärmen på en liten telefon.
    isScrollControlled: true,
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

/// Samma sak via BankID:s egen adress (äldre, men fungerar där länken ovan
/// inte är kopplad till appen).
Uri bankIdSchemeUri(String autoStartToken) =>
    Uri.parse('bankid:///?autostarttoken=$autoStartToken&redirect=null');

/// Öppnar BankID-appen på telefonen -- aldrig webbläsaren. Förut kunde länken
/// öppnas i webbläsaren (Android visade då en "intent"-sida i Chrome, eller ett
/// val av app). Nu: bara en installerad app får länken, annars BankID:s eget
/// schema, annars false -- och arket visar QR-koden i stället.
Future<bool> openBankIdApp(String autoStartToken) async {
  if (kIsWeb) return false;
  try {
    if (await launchUrl(
      bankIdAutostartUri(autoStartToken),
      mode: LaunchMode.externalNonBrowserApplication,
    )) {
      return true;
    }
  } catch (_) {}
  try {
    if (await launchUrl(
      bankIdSchemeUri(autoStartToken),
      mode: LaunchMode.externalApplication,
    )) {
      return true;
    }
  } catch (_) {}
  return false;
}

/// Det arket använder för att öppna BankID-appen. Byts bara ut i tester.
@visibleForTesting
Future<bool> Function(String autoStartToken) bankIdAppOpener = openBankIdApp;

class _BankIdSheet extends StatefulWidget {
  const _BankIdSheet({required this.api, required this.purpose});

  final ApiClient api;
  final String purpose;

  @override
  State<_BankIdSheet> createState() => _BankIdSheetState();
}

/// Två sätt, som BankID:s riktlinjer säger: BankID på den här telefonen
/// (öppnas direkt) eller på en annan telefon (QR-kod som skannas). Saknas
/// BankID-appen här visas QR-koden av sig själv.
class _BankIdSheetState extends State<_BankIdSheet> {
  // Varje sekund: QR-koden byts varje sekund.
  static const _interval = Duration(seconds: 1);
  // BankID låter en order leva i tre minuter.
  static const _maxWait = Duration(minutes: 3);

  String? _orderRef;
  String? _autoStart;
  String? _qrData;
  String? _status;
  String? _notice;
  String? _error;
  Timer? _timer;
  DateTime? _startedAt;
  bool _done = false;
  bool _starting = true;

  /// true = QR-koden (BankID på en annan telefon). På webben alltid.
  bool _qr = kIsWeb;

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
    _timer?.cancel();
    setState(() {
      _error = null;
      _status = null;
      _starting = true;
    });
    try {
      final data = await widget.api.bankIdStart(widget.purpose);
      _orderRef = data['orderRef']?.toString();
      _autoStart = data['autoStartToken']?.toString();
      _qrData = data['qrData']?.toString();
      _startedAt = DateTime.now();
      if (!mounted) return;
      setState(() => _starting = false);
      if (!_qr) await _openApp();
      _timer = Timer.periodic(_interval, (_) => _poll());
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _starting = false;
          _error = e.message;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _starting = false;
          _error = 'BankID svarar inte just nu. Försök igen.';
        });
      }
    }
  }

  Future<void> _openApp() async {
    final token = _autoStart;
    if (token == null || token.isEmpty) return;
    final opened = await bankIdAppOpener(token);
    if (!opened && mounted) {
      setState(() {
        _qr = true;
        _notice =
            'Vi hittar inte BankID-appen på den här telefonen. '
            'Skanna koden med BankID på en annan telefon.';
      });
    }
  }

  void _useOtherPhone() => setState(() {
    _qr = true;
    _notice = null;
  });

  Future<void> _useThisPhone() async {
    setState(() {
      _qr = false;
      _notice = null;
    });
    await _openApp();
  }

  bool _polling = false;
  int _tick = 0;

  Future<void> _poll() async {
    final ref = _orderRef;
    if (ref == null || _polling || _done) return;
    // På samma telefon räcker varannan sekund; QR-koden behöver varje.
    if (!_qr && (_tick++).isOdd) return;
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
            accountEmail: data['accountEmail']?.toString(),
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
      final hint = data['hintCode']?.toString();
      setState(() {
        _qrData = data['qrData']?.toString() ?? _qrData;
        // "Öppna BankID-appen" är redan instruktionen; visa bara det som
        // händer sedan (t.ex. "Skriv in din säkerhetskod").
        _status = (hint == 'outstandingTransaction' || hint == 'noClient')
            ? null
            : message;
      });
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

  static const _text = TextStyle(
    color: TbColors.ink,
    fontSize: 17,
    height: 1.35,
  );

  ButtonStyle get _primary => FilledButton.styleFrom(
    backgroundColor: TbColors.ink,
    foregroundColor: TbColors.foam,
    minimumSize: const Size.fromHeight(56),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
  );

  List<Widget> _failed() => [
    Text(
      _error!,
      textAlign: TextAlign.center,
      style: const TextStyle(
        color: TbColors.danger,
        fontSize: 17,
        fontWeight: FontWeight.w600,
      ),
    ),
    const SizedBox(height: 20),
    FilledButton(
      onPressed: _start,
      style: _primary,
      child: const Text('Försök igen', style: TextStyle(fontSize: 17)),
    ),
  ];

  List<Widget> _thisPhone() => [
    const Center(
      child: SizedBox(
        width: 36,
        height: 36,
        child: CircularProgressIndicator(strokeWidth: 3),
      ),
    ),
    const SizedBox(height: 16),
    Text(
      _status ?? 'Godkänn i BankID-appen. Kom sedan tillbaka hit.',
      textAlign: TextAlign.center,
      style: _text,
    ),
    const SizedBox(height: 20),
    FilledButton.icon(
      onPressed: _autoStart == null ? null : _openApp,
      style: _primary,
      icon: const Icon(Icons.fingerprint),
      label: const Text('Öppna BankID', style: TextStyle(fontSize: 17)),
    ),
    const SizedBox(height: 4),
    TextButton(
      onPressed: _useOtherPhone,
      style: TextButton.styleFrom(minimumSize: const Size.fromHeight(48)),
      child: const Text(
        'BankID på en annan telefon',
        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
    ),
  ];

  List<Widget> _otherPhone() => [
    if (_notice != null) ...[
      Text(
        _notice!,
        textAlign: TextAlign.center,
        style: _text.copyWith(fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 12),
    ] else ...[
      const Text(
        'Öppna BankID på din andra telefon och skanna koden.',
        textAlign: TextAlign.center,
        style: _text,
      ),
      const SizedBox(height: 12),
    ],
    Center(
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border.all(color: TbColors.line),
          borderRadius: BorderRadius.circular(16),
        ),
        child: SizedBox(
          width: 200,
          height: 200,
          child: _qrData == null
              ? const Center(child: CircularProgressIndicator(strokeWidth: 3))
              : QrImageView(
                  data: _qrData!,
                  size: 200,
                  padding: EdgeInsets.zero,
                  semanticsLabel: 'QR-kod för BankID',
                ),
        ),
      ),
    ),
    if (_status != null) ...[
      const SizedBox(height: 12),
      Text(_status!, textAlign: TextAlign.center, style: _text),
    ],
    if (!kIsWeb) ...[
      const SizedBox(height: 8),
      TextButton(
        onPressed: _useThisPhone,
        style: TextButton.styleFrom(minimumSize: const Size.fromHeight(48)),
        child: const Text(
          'BankID på den här telefonen',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        ),
      ),
    ],
  ];

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'BankID',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontFamily: kDisplayFont,
                color: TbColors.ink,
                fontSize: 24,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 20),
            if (_error != null)
              ..._failed()
            else if (_starting)
              const Center(
                child: Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: CircularProgressIndicator(strokeWidth: 3),
                ),
              )
            else if (_qr)
              ..._otherPhone()
            else
              ..._thisPhone(),
            const SizedBox(height: 4),
            TextButton(
              onPressed: _cancel,
              style: TextButton.styleFrom(
                foregroundColor: TbColors.muted,
                minimumSize: const Size.fromHeight(48),
              ),
              child: const Text('Avbryt'),
            ),
          ],
        ),
      ),
    );
  }
}

/// Vad den gör som inte har något BankID-konto: oftast en förare som bjudits
/// in med e-post (kontot skapades utan BankID). Ett tydligt nästa steg i
/// stället för en återvändsgränd.
const kNoBankIdAccountHelp =
    'Ditt BankID har inget konto här.\n\n'
    'Fick du en inbjudan från ditt taxibolag? Be dem skicka inbjudan igen. '
    'Då får du ett mejl där du väljer ett nytt lösenord.\n\n'
    'Har du inget konto? Tryck på Skapa konto.';

/// Glömt lösenord eller bytt e-post, för konton som skapats med BankID:
/// legitimera, välj nytt lösenord (och ny e-post om du vill). Returnerar
/// adressen att logga in med, eller null om användaren avbröt.
Future<String?> recoverWithBankId(BuildContext context, ApiClient api) async {
  final identity = await runBankId(context, api, purpose: 'recover');
  if (identity == null || !context.mounted) return null;
  if (identity.accountEmail == null) {
    await showDialog<void>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Vi hittar inget konto'),
        content: const Text(kNoBankIdAccountHelp),
        actions: [
          FilledButton(
            onPressed: () => Navigator.of(dialog).pop(),
            child: const Text('OK'),
          ),
        ],
      ),
    );
    return null;
  }
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
      setState(() => _error = 'Lösenordet: minst 8 tecken.');
      return;
    }
    if (_changeEmail && !_email.text.contains('@')) {
      setState(() => _error = 'Fel e-post.');
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
            const Text('Ditt konto:'),
            const SizedBox(height: 4),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: TbColors.foam,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: TbColors.line),
              ),
              child: Row(
                children: [
                  const Icon(Icons.email_outlined, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      widget.identity.accountEmail ?? '',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _password,
              obscureText: _hide,
              decoration: InputDecoration(
                labelText: 'Nytt lösenord',
                helperText: 'Minst 8 tecken',
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
              title: const Text('Byt e-post också'),
            ),
            if (_changeEmail)
              TextField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: 'Ny e-post',
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
