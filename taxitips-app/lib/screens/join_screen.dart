import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../theme.dart';

/// Förare registrerar telefon med bolagskod, eller byter telefon med byteskod.
class JoinScreen extends StatefulWidget {
  const JoinScreen({super.key, required this.api, required this.onJoined, required this.onBack});

  final ApiClient api;
  final VoidCallback onJoined;
  final VoidCallback onBack;

  @override
  State<JoinScreen> createState() => _JoinScreenState();
}

class _JoinScreenState extends State<JoinScreen> {
  final _code = TextEditingController();
  final _label = TextEditingController();
  bool _transferMode = false;
  bool _busy = false;
  String? _error;

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
    });
    try {
      if (_transferMode) {
        await widget.api.transferWithCode(
          transferCode: _code.text.trim(),
          label: _label.text.trim().isEmpty ? null : _label.text.trim(),
        );
      } else {
        await widget.api.joinWithCode(
          joinCode: _code.text.trim(),
          label: _label.text.trim().isEmpty ? 'Förare' : _label.text.trim(),
        );
      }
      widget.onJoined();
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
        title: Text(_transferMode ? 'Byt telefon' : 'Registrera telefon'),
        leading: IconButton(icon: const Icon(Icons.arrow_back), onPressed: widget.onBack),
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
                      _transferMode
                          ? 'Ange byteskoden från kontoret (eller din gamla telefon). Gäller 30 min.'
                          : 'Ange bolagskoden från kontoret. Telefonen kopplas in själv.',
                      style: TextStyle(color: Colors.grey.shade800, height: 1.35),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _code,
                      textCapitalization: _transferMode ? TextCapitalization.none : TextCapitalization.characters,
                      keyboardType: _transferMode ? TextInputType.number : TextInputType.text,
                      inputFormatters: [
                        if (_transferMode) FilteringTextInputFormatter.digitsOnly,
                        LengthLimitingTextInputFormatter(8),
                      ],
                      decoration: InputDecoration(
                        labelText: _transferMode ? 'Byteskod (6 siffror)' : 'Bolagskod',
                        border: const OutlineInputBorder(),
                        hintText: _transferMode ? '123456' : 'AB12CD',
                      ),
                      style: const TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.w900,
                        letterSpacing: 4,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _label,
                      decoration: const InputDecoration(
                        labelText: 'Ditt namn / bil (valfritt)',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(_error!, style: const TextStyle(color: TbColors.danger, fontWeight: FontWeight.w700)),
                    ],
                    const SizedBox(height: 18),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: Text(_busy ? 'Kopplar…' : (_transferMode ? 'Byt till den här telefonen' : 'Registrera den här telefonen')),
                    ),
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () => setState(() {
                                _transferMode = !_transferMode;
                                _error = null;
                                _code.clear();
                              }),
                      child: Text(
                        _transferMode ? 'Har bolagskod i stället?' : 'Byter du telefon? Ange byteskod',
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
