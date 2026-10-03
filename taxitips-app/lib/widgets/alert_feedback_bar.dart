import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../analytics.dart';
import '../api_client.dart';
import '../config.dart';
import '../theme.dart';

/// 👍 / 👎 -- förarens svar på hur ett tips gick: "Fick körning" eller
/// "Ingen kund".
///
/// Visas bara när appen kör mot Django-backenden. Det är inte en flagga för
/// säkerhets skull: Supabase-vägen skriver till `alert_feedback`, vars
/// främmande nyckel pekar på `alerts`, medan tipsen kommer från
/// `opportunities`. Den skrivningen har aldrig kunnat lyckas (0 av 4345
/// överlappande id:n, tabellen har noll rader), så knapparna hade sett ut
/// att fungera och tyst kastat bort varje svar. Hellre ingen knapp än en
/// död knapp.
///
/// Ett val i taget: de två svaren utesluter varandra, och ett tryck på det
/// valda tar bort det (backend gör samma sak, se core/api.py feedback).
/// "Kör dit" som omdöme är borttaget -- det gav föraren ingenting tillbaka.
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

  /// Tester bygger utan API_BASE_URL och skulle aldrig se knapparna.
  @visibleForTesting
  static bool debugAlwaysShow = false;

  @override
  State<AlertFeedbackBar> createState() => _AlertFeedbackBarState();
}

class _AlertFeedbackBarState extends State<AlertFeedbackBar> {
  /// 'fare', 'empty' eller null.
  String? _choice;
  bool _busy = false;
  String? _error;
  // Sparat men inte skickat: inget nät just nu.
  bool _queued = false;

  @override
  void initState() {
    super.initState();
    FeedbackChoices.get(widget.opportunityId).then((v) {
      if (mounted && v != null) setState(() => _choice = v);
    });
  }

  Future<void> _tap(String verdict) async {
    if (_busy) return;
    final previous = _choice;
    final next = previous == verdict ? null : verdict;
    // Valet syns direkt; ett fel nedan backar tillbaka det.
    setState(() {
      _choice = next;
      _busy = true;
      _error = null;
    });
    final res = await widget.api.submitAlertFeedback(
      widget.opportunityId,
      next == 'fare',
      verdict: next ?? 'none',
    );
    if (!mounted) return;
    final ok = res['error'] == null;
    if (ok) {
      await FeedbackChoices.set(widget.opportunityId, next);
      logAnalyticsEvent('tip_feedback', params: {'verdict': next ?? 'none'});
    }
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (ok) {
        _queued = res['queued'] == true;
      } else {
        // Sagt rakt ut. Ett svar som inte kom fram ska inte se ut som ett
        // som gjorde det -- det var precis så den gamla vägen kunde vara
        // trasig i månader utan att någon märkte det.
        _choice = previous;
        _error = 'Kunde inte spara svaret. Försök igen.';
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!TaxiTipsConfig.usesDjangoApi && !AlertFeedbackBar.debugAlwaysShow) {
      return const SizedBox.shrink();
    }

    // Kompakt: en rubrikrad och två knappar. Status bara när något hänt.
    final status = _error != null
        ? (_error!, TbColors.danger)
        : _queued
        ? ('Sparat. Skickas när du har nät.', TbColors.muted)
        : _choice != null
        ? ('Tack!', TbColors.live)
        : null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text(
              'Hur gick det?',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: TbColors.ink,
              ),
            ),
            if (status != null) ...[
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  status.$1,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: status.$2,
                  ),
                ),
              ),
            ],
          ],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: _ChoiceButton(
                label: 'Fick körning',
                icon: Icons.thumb_up_alt_rounded,
                color: TbColors.live,
                selected: _choice == 'fare',
                onTap: () => _tap('fare'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _ChoiceButton(
                label: 'Ingen kund',
                icon: Icons.thumb_down_alt_rounded,
                color: TbColors.danger,
                selected: _choice == 'empty',
                onTap: () => _tap('empty'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _ChoiceButton extends StatelessWidget {
  const _ChoiceButton({
    required this.label,
    required this.icon,
    required this.color,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final Color color;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      child: OutlinedButton.icon(
        onPressed: onTap,
        icon: Icon(
          selected ? Icons.check_circle_rounded : icon,
          size: 20,
          color: selected ? TbColors.vit : color,
        ),
        label: Text(label),
        style: OutlinedButton.styleFrom(
          // 52 hög: svaret ska gå att träffa med tummen i en bil.
          minimumSize: const Size.fromHeight(52),
          padding: const EdgeInsets.symmetric(horizontal: 8),
          backgroundColor: selected ? color : null,
          foregroundColor: selected ? TbColors.vit : TbColors.ink,
          side: BorderSide(color: selected ? color : TbColors.line, width: 1.5),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: const TextStyle(
            fontSize: 15.5,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}

/// Förarens senaste svar per tips, sparat på telefonen så att valet syns
/// igen när tipset öppnas på nytt.
class FeedbackChoices {
  FeedbackChoices._();

  static const _key = 'tip_feedback_choice_v1';
  static const _maxItems = 200;

  static Future<Map<String, String>> _load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_key);
      if (raw == null) return {};
      final map = jsonDecode(raw);
      if (map is! Map) return {};
      return {
        for (final e in map.entries)
          if (e.value is String) e.key.toString(): e.value as String,
      };
    } catch (_) {
      return {};
    }
  }

  static Future<String?> get(String opportunityId) async =>
      (await _load())[opportunityId];

  static Future<void> set(String opportunityId, String? verdict) async {
    try {
      final map = await _load();
      map.remove(opportunityId);
      if (verdict != null) map[opportunityId] = verdict;
      // Äldst först i en LinkedHashMap: släpp de äldsta.
      while (map.length > _maxItems) {
        map.remove(map.keys.first);
      }
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_key, jsonEncode(map));
    } catch (_) {}
  }
}
