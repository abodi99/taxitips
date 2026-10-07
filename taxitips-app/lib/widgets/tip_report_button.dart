import 'package:flutter/material.dart';

import '../api_client.dart';
import '../theme.dart';

/// Dialogen där föraren beskriver vad som är fel med tipset.
///
/// Äger [TextEditingController] själv: att slänga den när `showDialog`
/// returnerar (medan rutan fortfarande animerar bort och tangentbordet
/// stängs) gav `used after being disposed` och
/// `framework.dart: '_dependents.isEmpty': is not true`.
Future<String?> showTipReportDialog(BuildContext context) {
  return showDialog<String>(
    context: context,
    useRootNavigator: true,
    builder: (ctx) => const _TipReportDialog(),
  );
}

class _TipReportDialog extends StatefulWidget {
  const _TipReportDialog();

  @override
  State<_TipReportDialog> createState() => _TipReportDialogState();
}

class _TipReportDialogState extends State<_TipReportDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      scrollable: true,
      title: const Text('Rapportera felaktigt tips'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Berätta kort vad som inte stämmer, till exempel fel plats eller att störningen redan är löst.',
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _controller,
            maxLines: 3,
            textInputAction: TextInputAction.done,
            decoration: const InputDecoration(
              hintText: 'Valfri förklaring',
              border: OutlineInputBorder(),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Avbryt'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _controller.text.trim()),
          child: const Text('Skicka rapport'),
        ),
      ],
    );
  }
}

/// Rapportera att tipset visar felaktig information (skilt från 👍/👎).
class TipReportButton extends StatefulWidget {
  const TipReportButton({
    super.key,
    required this.api,
    required this.opportunityId,
  });

  final ApiClient api;
  final String opportunityId;

  @override
  State<TipReportButton> createState() => _TipReportButtonState();
}

class _TipReportButtonState extends State<TipReportButton> {
  bool _busy = false;
  bool _sent = false;

  Future<void> _openDialog() async {
    if (_busy || _sent) return;
    final reason = await showTipReportDialog(context);
    if (reason == null || !mounted) return;
    setState(() => _busy = true);
    try {
      await widget.api.submitTipReport(
        opportunityId: widget.opportunityId,
        reason: reason,
      );
      if (!mounted) return;
      setState(() => _sent = true);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Tack — vi granskar tipset.')),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Kunde inte skicka rapporten. Prova igen.'),
        ),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_sent) {
      return Text(
        'Rapport mottagen — tack.',
        style: TextStyle(color: TbColors.muted, fontSize: 14.5),
      );
    }
    return Align(
      alignment: Alignment.centerLeft,
      child: TextButton.icon(
        style: TextButton.styleFrom(
          foregroundColor: TbColors.muted,
          padding: const EdgeInsets.symmetric(horizontal: 4),
          minimumSize: const Size(0, 48),
          textStyle: const TextStyle(
            fontSize: 14.5,
            fontWeight: FontWeight.w600,
          ),
        ),
        onPressed: _busy ? null : _openDialog,
        icon: _busy
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.flag_outlined, size: 16),
        label: const Text('Rapportera felaktigt tips'),
      ),
    );
  }
}
