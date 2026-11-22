import 'package:flutter/material.dart';

import '../api_client.dart';
import '../follow_up.dart';
import '../l10n/l10n.dart';
import '../theme.dart';
import 'alert_feedback_bar.dart';

/// Överst i listan en halvtimme efter "Kör dit": hur gick det vid tipset?
///
/// Samma två knappar som i tipsbladet. Krysset stänger frågan för gott;
/// ett svar stänger den efter att "Tack!" hunnit synas.
class FollowUpCard extends StatelessWidget {
  const FollowUpCard({
    super.key,
    required this.api,
    required this.followUp,
    required this.onDone,
  });

  final ApiClient api;
  final FollowUp followUp;

  /// Frågan är klar (besvarad eller bortklickad). Får tipsets id: svaret
  /// kommer med fördröjning, och då kan en annan fråga redan stå i listan.
  final ValueChanged<String> onDone;

  /// Så länge "Tack!" syns innan kortet går.
  static const thanksFor = Duration(milliseconds: 1200);

  @override
  Widget build(BuildContext context) {
    final at = followUp.at;
    final clock = formatTime(at);
    return Material(
      color: TbColors.vit,
      elevation: 3,
      shadowColor: Colors.black26,
      borderRadius: BorderRadius.circular(14),
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(14, 6, 6, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(
                  Icons.local_taxi_rounded,
                  size: 20,
                  color: TbColors.ink,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    tr.followUpCardDrove(followUp.place, clock),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: TbColors.ink,
                    ),
                  ),
                ),
                IconButton(
                  tooltip: tr.followUpCardClose,
                  icon: const Icon(Icons.close_rounded),
                  onPressed: () => onDone(followUp.id),
                ),
              ],
            ),
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 8),
              child: AlertFeedbackBar(
                api: api,
                opportunityId: followUp.id,
                onAnswered: () =>
                    Future.delayed(thanksFor, () => onDone(followUp.id)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
