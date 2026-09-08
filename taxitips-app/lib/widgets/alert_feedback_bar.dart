import 'package:flutter/material.dart';

import '../api_client.dart';
import '../config.dart';
import '../theme.dart';

/// 🚕 / 👍 / 👎 -- förarens svar på ett tips.
///
/// Visas bara när appen kör mot Django-backenden. Det är inte en flagga för
/// säkerhets skull: Supabase-vägen skriver till `alert_feedback`, vars
/// främmande nyckel pekar på `alerts`, medan tipsen kommer från
/// `opportunities`. Den skrivningen har aldrig kunnat lyckas (0 av 4345
/// överlappande id:n, tabellen har noll rader), så knapparna hade sett ut
/// att fungera och tyst kastat bort varje svar. Hellre ingen knapp än en
/// död knapp.
///
/// Svaret är det enda som någonsin kan kalibrera poängsättningen mot
/// verkligheten -- allt annat i pipelinen är gissningar om vad en störning
/// betyder för någon som står på perrongen.
class AlertFeedbackBar extends StatefulWidget {
  const AlertFeedbackBar({
    super.key,
    required this.api,
    required this.opportunityId,
  });

  final ApiClient api;
  final String opportunityId;

  @override
  State<AlertFeedbackBar> createState() => _AlertFeedbackBarState();
}

class _AlertFeedbackBarState extends State<AlertFeedbackBar> {
  final _sent = <String>{};
  String? _busy;
  String? _error;

  Future<void> _send(String verdict) async {
    setState(() {
      _busy = verdict;
      _error = null;
    });
    final res = await widget.api.submitAlertFeedback(
      widget.opportunityId,
      verdict == 'fare',
      verdict: verdict,
    );
    if (!mounted) return;
    setState(() {
      _busy = null;
      if (res['error'] == null) {
        _sent.add(verdict);
      } else {
        // Sagt rakt ut. Ett svar som inte kom fram ska inte se ut som ett
        // som gjorde det -- det var precis så den gamla vägen kunde vara
        // trasig i månader utan att någon märkte det.
        _error = 'Kunde inte spara svaret. Försök igen.';
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!TaxiTipsConfig.usesDjangoApi) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 16),
        const Text(
          'Stämde tipset?',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w800,
            letterSpacing: 0.4,
            color: TbColors.muted,
          ),
        ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _FeedbackButton(
              label: 'Kör dit',
              icon: Icons.local_taxi,
              verdict: 'heading',
              sent: _sent.contains('heading'),
              busy: _busy == 'heading',
              onTap: _send,
            ),
            _FeedbackButton(
              label: 'Fick körning',
              icon: Icons.thumb_up_alt_outlined,
              verdict: 'fare',
              sent: _sent.contains('fare'),
              busy: _busy == 'fare',
              onTap: _send,
            ),
            _FeedbackButton(
              label: 'Ingen kund',
              icon: Icons.thumb_down_alt_outlined,
              verdict: 'empty',
              sent: _sent.contains('empty'),
              busy: _busy == 'empty',
              onTap: _send,
            ),
          ],
        ),
        if (_error != null) ...[
          const SizedBox(height: 6),
          Text(
            _error!,
            style: const TextStyle(
              fontSize: 12.5,
              fontWeight: FontWeight.w600,
              color: TbColors.danger,
            ),
          ),
        ],
      ],
    );
  }
}

class _FeedbackButton extends StatelessWidget {
  const _FeedbackButton({
    required this.label,
    required this.icon,
    required this.verdict,
    required this.sent,
    required this.busy,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final String verdict;
  final bool sent;
  final bool busy;
  final void Function(String verdict) onTap;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      // Skickat = kvitterat, inte återställbart. Ett svar per omdöme och
      // tips är vad backend lagrar (unik nyckel), så knappen ska inte
      // inbjuda till en andra tryckning som ändå ignoreras.
      onPressed: sent || busy ? null : () => onTap(verdict),
      icon: busy
          ? const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Icon(sent ? Icons.check : icon, size: 17),
      label: Text(sent ? 'Tack!' : label),
      style: OutlinedButton.styleFrom(
        foregroundColor: sent ? TbColors.live : TbColors.ink,
        side: BorderSide(color: sent ? TbColors.live : const Color(0xFFC9D0DA)),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        textStyle: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700),
      ),
    );
  }
}
