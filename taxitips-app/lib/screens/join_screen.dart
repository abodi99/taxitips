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
      backgroundColor: TbColors.asphalt,
      appBar: AppBar(
        backgroundColor: TbColors.asphalt,
        foregroundColor: TbColors.foam,
        title: Text(_requestMode ? 'Be om åtkomst' : 'Anslut telefonen'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: widget.onBack,
        ),
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: TbColors.foam,
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      _requestMode
                          ? 'Ange bolagskoden. Vi skickar en ansökan till din '
                                'administratör, som godkänner telefonen med en '
                                'anslutningskod. Bolagskoden ger ingen åtkomst i sig.'
                          : 'Ange anslutningskoden du fått av din administratör. '
                                'Den gäller i fem minuter och kopplar telefonen '
                                'till en bestämd bil.',
                      style: TextStyle(color: Colors.grey.shade800, height: 1.35),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _code,
                      autocorrect: false,
                      textCapitalization: TextCapitalization.characters,
                      inputFormatters: [
                        UpperCaseTextFormatter(),
                        LengthLimitingTextInputFormatter(12),
                      ],
                      decoration: InputDecoration(
                        labelText: _requestMode ? 'Bolagskod' : 'Anslutningskod',
                        hintText: _requestMode ? 'ABC123' : 'ABCD2345',
                        border: const OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _label,
                      decoration: const InputDecoration(
                        labelText: 'Namn på telefonen (valfritt)',
                        hintText: 'Nattbil, Anna, Bil 3 …',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        _error!,
                        style: const TextStyle(color: Color(0xFFB3261E)),
                      ),
                    ],
                    if (_notice != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        _notice!,
                        style: const TextStyle(color: Color(0xFF1B5E20)),
                      ),
                    ],
                    const SizedBox(height: 16),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: Text(
                        _busy
                            ? 'Vänta …'
                            : (_requestMode ? 'Skicka ansökan' : 'Anslut'),
                      ),
                    ),
                    const SizedBox(height: 8),
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () => setState(() {
                              _requestMode = !_requestMode;
                              _error = null;
                              _notice = null;
                            }),
                      child: Text(
                        _requestMode
                            ? 'Jag har en anslutningskod'
                            : 'Jag har bara bolagskoden',
                      ),
                    ),
                  ],
                ),
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
