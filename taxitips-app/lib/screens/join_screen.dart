import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../theme.dart';

/// Förarens parkoppling: administratörens engångskod, eller bolagskoden som
/// ansökan.
///
/// **Vad som ändrats och varför.** Skärmen tog tidigare emot bolagskoden och
/// anropade `join_device`, som delade ut en permanent enhetstoken direkt.
/// Koden står på ett papper i fikarummet och syns i administratörsvyn, så den
/// som läste den fick betald data tills någon bytte kod -- och bytet låste ut
/// alla förare samtidigt.
///
/// Nu gäller två vägar:
///
/// * **Anslutningskod** (åtta tecken, giltig fem minuter). Administratören
///   väljer bil och skapar koden. Telefonen blir godkänd för just den bilen.
/// * **Bolagskod**, som bara skickar en ansökan. Ingen åtkomst, ingen token --
///   administratören svarar med en anslutningskod.
///
/// Byteskoden är borttagen: den gav en ny enhetstoken utan att någon godkände
/// telefonen för en bil.
class JoinScreen extends StatefulWidget {
  const JoinScreen({
    super.key,
    required this.api,
    required this.onJoined,
    required this.onBack,
  });

  final ApiClient api;
  final VoidCallback onJoined;
  final VoidCallback onBack;

  @override
  State<JoinScreen> createState() => _JoinScreenState();
}

class _JoinScreenState extends State<JoinScreen> {
  final _code = TextEditingController();
  final _label = TextEditingController();
  bool _requestMode = false;
  bool _busy = false;
  String? _error;
  String? _notice;

  @override
  void dispose() {
    _code.dispose();
    _label.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      final label = _label.text.trim().isEmpty ? 'Förare' : _label.text.trim();
      if (_requestMode) {
        final result = await widget.api.requestJoin(
          joinCode: _code.text.trim(),
          label: label,
        );
        if (!mounted) return;
        setState(() {
          _notice =
              result['message']?.toString() ??
              'Ansökan skickad. Din administratör godkänner telefonen med en '
                  'anslutningskod.';
          _code.clear();
        });
      } else {
        await widget.api.pairWithCode(code: _code.text.trim(), label: label);
        widget.onJoined();
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
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
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(
                    Icons.directions_car_filled_outlined,
                    color: TbColors.taxi,
                    size: 64,
                  ),
                  const SizedBox(height: 24),
                  Text(
                    _requestMode ? 'Ansök om åtkomst' : 'Anslut telefonen',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontFamily: kDisplayFont,
                      color: TbColors.foam,
                      fontSize: 28,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    _requestMode
                        ? 'Skicka en förfrågan med bolagskod.'
                        : 'Ange anslutningskoden du fått av chefen.',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Colors.white70, fontSize: 16),
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
                        Container(
                          padding: const EdgeInsets.all(16),
                          decoration: BoxDecoration(
                            color: Colors.grey.shade100,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Text(
                            _requestMode
                                ? 'Bolagskoden hittar du på kontoret. Den skickar en förfrågan som chefen sedan måste godkänna.'
                                : 'Anslutningskoden är 8 tecken lång och gäller i 5 minuter. Den kopplar dig till rätt bil direkt.',
                            style: TextStyle(
                              color: Colors.grey.shade800,
                              height: 1.4,
                              fontSize: 14,
                            ),
                          ),
                        ),
                        const SizedBox(height: 24),
                        TextField(
                          controller: _code,
                          autocorrect: false,
                          textCapitalization: TextCapitalization.characters,
                          style: const TextStyle(
                            fontSize: 24,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 2,
                          ),
                          textAlign: TextAlign.center,
                          inputFormatters: [
                            UpperCaseTextFormatter(),
                            LengthLimitingTextInputFormatter(12),
                          ],
                          decoration: InputDecoration(
                            labelText: _requestMode
                                ? 'Bolagskod'
                                : 'Anslutningskod',
                            hintText: _requestMode ? 'ABC123' : 'ABCD2345',
                            floatingLabelAlignment:
                                FloatingLabelAlignment.center,
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(16),
                            ),
                          ),
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _label,
                          decoration: InputDecoration(
                            labelText: 'Ditt namn / Bil (Frivilligt)',
                            hintText: 'T.ex. Anna, Bil 3...',
                            prefixIcon: const Icon(Icons.person_outline),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
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
                                const Icon(
                                  Icons.error_outline,
                                  color: TbColors.danger,
                                  size: 20,
                                ),
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
                        if (_notice != null) ...[
                          const SizedBox(height: 16),
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: Colors.green.withValues(alpha: 0.1),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Row(
                              children: [
                                const Icon(
                                  Icons.check_circle_outline,
                                  color: Colors.green,
                                  size: 20,
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Text(
                                    _notice!,
                                    style: const TextStyle(
                                      color: Colors.green,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                        const SizedBox(height: 24),
                        FilledButton.icon(
                          onPressed: _busy ? null : _submit,
                          icon: _busy
                              ? const SizedBox(
                                  width: 20,
                                  height: 20,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: Colors.black,
                                  ),
                                )
                              : Icon(_requestMode ? Icons.send : Icons.link),
                          label: Text(
                            _busy
                                ? 'Väntar...'
                                : (_requestMode
                                      ? 'Skicka ansökan'
                                      : 'Anslut telefon'),
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          style: FilledButton.styleFrom(
                            backgroundColor: TbColors.taxi,
                            foregroundColor: TbColors.ink,
                            minimumSize: const Size.fromHeight(60),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 32),
                  TextButton(
                    onPressed: _busy
                        ? null
                        : () => setState(() {
                            _requestMode = !_requestMode;
                            _error = null;
                            _notice = null;
                          }),
                    style: TextButton.styleFrom(
                      foregroundColor: Colors.white70,
                    ),
                    child: Text(
                      _requestMode
                          ? 'Växla: Jag har en anslutningskod för en specifik bil'
                          : 'Växla: Jag har bara bolagskod',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        decoration: TextDecoration.underline,
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

/// Koderna skrivs med versaler. Att rätta det åt föraren är billigare än ett
/// felmeddelande om en kod som egentligen var rätt.
class UpperCaseTextFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) => TextEditingValue(
    text: newValue.text.toUpperCase(),
    selection: newValue.selection,
  );
}
