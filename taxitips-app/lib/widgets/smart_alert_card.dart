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
    final likelihood = likelihoodForAlert(alert);
    final travel = TravelOptions.of(alert);
    // Sista avgången = ingen tar sig hem själv. Angiven ersättningsbuss =
    // resenären behöver sannolikt inte taxi. Motsatt innebörd, alltså inte
    // samma färg.
    final travelColor = travel == null
        ? TbColors.muted
        : (travel.isStrong
              ? TbColors.live
              : (travel.isWeak ? TbColors.muted : TbColors.ink));
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
                        // Mode is more specific than kind when the source
                        // states it (SL reports metro/tram/bus outright), so
                        // prefer it and fall back to the coarse transit/road
                        // split for sources that don't.
                        if (kind == 'transit' || kind == 'road')
                          Icon(
                            switch (alert['mode']?.toString()) {
                              'train' => Icons.train,
                              'metro' => Icons.subway,
                              'tram' => Icons.tram,
                              'bus' => Icons.directions_bus,
                              _ => kind == 'transit'
                                  ? Icons.train
                                  : Icons.directions_car,
                            },
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
                        // Lagstadgad förseningsersättning (lag 2015:953):
                        // resenären kan få sin taxiresa ersatt upp till
                        // beloppet. Det säger inget om hur allvarlig
                        // störningen är -- det är ett separat fält i
                        // backend av just det skälet -- men det är det
                        // starkaste enskilda skälet för någon på perrongen
                        // att faktiskt ta taxi i stället för att vänta.
                        if (alert['compensation_eligible'] == true)
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 6,
                              vertical: 1,
                            ),
                            decoration: BoxDecoration(
                              color: const Color(0xFFE7F4EC),
                              borderRadius: BorderRadius.circular(6),
                              border: Border.all(color: TbColors.live),
                            ),
                            child: Text(
                              compensationLabel(
                                alert['compensation_amount_kr'] as num?,
                                perPerson:
                                    alert['compensation_per_person'] as bool?,
                              ),
                              style: const TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w800,
                                color: TbColors.live,
                              ),
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
                  LikelihoodBadge(
                    likelihood: likelihood,
                    distanceKm: (alert['distance_km'] as num?)?.toDouble(),
                  ),
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
              // Nästa avgång / ersättningstrafik. Placerad före den fria
              // texten: det är det som avgör om resan dit är värd något,
              // och en förare som bara hinner läsa en rad ska läsa den här.
              if (travel != null) ...[
                const SizedBox(height: 6),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      travel.isLastDeparture
                          ? Icons.last_page
                          : (travel.hasAlternative
                                ? Icons.directions_bus
                                : Icons.schedule_send),
                      size: 15,
                      color: travelColor,
                    ),
                    const SizedBox(width: 5),
                    Expanded(
                      child: Text(
                        travel.summary!,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 13,
                          height: 1.25,
                          fontWeight: FontWeight.w700,
                          color: travelColor,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
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
