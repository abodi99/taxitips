import 'package:flutter/material.dart';
import '../severity_labels.dart';
import '../theme.dart';
import 'likelihood_badge.dart';

/// Compact, glanceable card for the live signal list. Tapping it opens the full
/// detail sheet (`_openAlertDetail` in driver_screen.dart), which now shows the
/// "why" reasoning immediately, no extra tap required -- this card only needs to
/// answer "is this worth a glance while I'm driving?".
class SmartAlertCard extends StatelessWidget {
  final Map<String, dynamic> alert;
  final VoidCallback? onTap;

  const SmartAlertCard({super.key, required this.alert, this.onTap});

  @override
  Widget build(BuildContext context) {
    final title = displayTitle(
      title: alert['title']?.toString(),
      mode: alert['mode']?.toString(),
    );
    final summary = alert['summary']?.toString() ?? '';
    final score = ((alert['worth_it_score'] as num?) ?? 0);
    final likelihood = customerLikelihood(
      severityTier: alert['severity_tier']?.toString(),
      worthItScore: score,
      demandScore: (alert['demand_score'] as num?) ?? 0,
    );
    final endTimeStr = alert['end_time'] ?? alert['ends_at'];
    final kind = alert['kind']?.toString();
    final severityTier = alert['severity_tier']?.toString();
    final confidence = alert['confidence']?.toString();
    final isActive = alert['is_active'] != false;

    DateTime? endTime;
    if (endTimeStr != null) {
      endTime = DateTime.tryParse(endTimeStr);
    }

    // How LONG a disruption lasts is the wrong question, and end_time can't
    // answer it anyway: Trafiklab's end_time is the alert's own publishing
    // validity window, not the disruption's duration. Every cancelled
    // departure in a batch ends at the same wall-clock time (21:59 on live
    // data), so "Pågår i 7 tim 50 min till" told a driver a single cancelled
    // bus would keep being cancelled all evening -- confusing and untrue.
    //
    // What actually matters at a glance is how FRESH it is: a cancellation
    // 4 minutes ago means people are still standing there; one from 3 hours
    // ago means they've long since found another way.
    final startTimeStr = alert['start_time'];
    final startTime = startTimeStr == null
        ? null
        : DateTime.tryParse(startTimeStr.toString());

    String timeLeft = 'Tidpunkt okänd';
    if (!isActive && endTime != null) {
      timeLeft = 'Avslutades ${dateTimeLabel(endTimeStr.toString())}';
    } else if (startTime != null) {
      final age = DateTime.now().difference(startTime);
      if (age.isNegative) {
        timeLeft = 'Börjar ${dateTimeLabel(startTimeStr.toString())}';
      } else if (age.inMinutes < 1) {
        timeLeft = 'Just nu';
      } else if (age.inMinutes < 60) {
        timeLeft = 'För ${age.inMinutes} min sedan';
      } else if (age.inHours < 24) {
        timeLeft = 'För ${age.inHours} tim sedan';
      } else {
        timeLeft = dateTimeLabel(startTimeStr.toString());
      }
    }

    // A low-confidence read is worth flagging inline -- a driver shouldn't treat
    // a guess with the same weight as a clearly-stated cancellation.
    final isLowConfidence = confidence == 'low';

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      elevation: isActive ? 1 : 0,
      color: isActive ? null : Colors.grey.shade50,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: isActive
            ? BorderSide.none
            : BorderSide(color: Colors.grey.shade300),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Row 1: mode/severity chip on the left, Worth-It score on the right.
              // This is the single most important glance -- what kind of disruption,
              // how sure are we, how urgent is it -- without reading any prose.
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        if (kind == 'transit' || kind == 'road')
                          Icon(
                            kind == 'transit'
                                ? Icons.train
                                : Icons.directions_car,
                            size: 15,
                            color: TbColors.muted,
                          ),
                        if (severityTierShortLabels.containsKey(severityTier))
                          Text(
                            severityTierShortLabels[severityTier]!,
                            style: const TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w800,
                              color: TbColors.muted,
                            ),
                          ),
                        if (isLowConfidence)
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 5,
                              vertical: 1,
                            ),
                            decoration: BoxDecoration(
                              color: TbColors.sand,
                              borderRadius: BorderRadius.circular(6),
                              border: Border.all(
                                color: const Color(0xFFC9D0DA),
                              ),
                            ),
                            child: const Text(
                              'osäker',
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w800,
                                color: TbColors.muted,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  LikelihoodBadge(likelihood: likelihood),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 2),
              Row(
                children: [
                  const Icon(
                    Icons.schedule,
                    size: 13,
                    color: Colors.grey,
                  ),
                  const SizedBox(width: 4),
                  Text(
                    timeLeft,
                    style: TextStyle(
                      fontSize: 13,
                      color: Colors.grey.shade700,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  // "Pågår i X min till" says how much is left, but not WHEN
                  // this started -- worth showing plainly since some alerts
                  // (esp. thin ones like a bare "Försening" with no place
                  // name) give a driver almost nothing else to go on.
                  if (alert['start_time'] != null) ...[
                    Text(
                      '  ·  ',
                      style: TextStyle(fontSize: 13, color: Colors.grey.shade400),
                    ),
                    Text(
                      dateTimeLabel(alert['start_time']?.toString()),
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.grey.shade700,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ],
              ),
              if (summary.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  summary,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13.5,
                    color: Colors.grey.shade800,
                    height: 1.3,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
