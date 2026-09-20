import 'package:flutter/material.dart';
import '../severity_labels.dart';
import '../theme.dart';
import 'brand_icons.dart';
import 'likelihood_badge.dart';

/// Compact, glanceable card for the live signal list. Tapping it opens the full
/// detail sheet (`_openAlertDetail` in driver_screen.dart), which now shows the
/// "why" reasoning immediately, no extra tap required -- this card only needs to
/// answer "is this worth a glance while I'm driving?".
class SmartAlertCard extends StatelessWidget {
  final Map<String, dynamic> alert;
  final VoidCallback? onTap;

  /// Stjärnan ritas bara när det finns någonstans att spara till.
  /// `onToggleFavorite: null` = ingen knapp alls, inte en knapp som tyst
  /// inte gör något -- se ApiClient.supportsFavorites.
  final ValueChanged<bool>? onToggleFavorite;

  const SmartAlertCard({
    super.key,
    required this.alert,
    this.onTap,
    this.onToggleFavorite,
  });

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
    final isFavorite = alert['is_favorite'] == true;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      elevation: isActive ? 2 : 0,
      shadowColor: Colors.black38,
      color: isActive ? Colors.white : Colors.grey.shade50,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: isActive
            ? BorderSide(color: Colors.grey.shade200)
            : BorderSide(color: Colors.grey.shade300),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 14),
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
                        if (kind == 'transit' ||
                            kind == 'road' ||
                            kind == 'flight' ||
                            alert['mode'] != null)
                          BrandIcons.forMode(
                            alert['mode']?.toString() ??
                                (kind == 'road'
                                    ? 'road'
                                    : kind == 'flight'
                                    ? 'flight'
                                    : null),
                            size: 15,
                            color: TbColors.muted,
                          ),
                        if (severityTierShortLabels.containsKey(severityTier))
                          Text(
                            severityTierShortLabels[severityTier]!,
                            style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                              color: TbColors.muted,
                            ),
                          ),
                        if ((alert['countyName']?.toString() ?? '').isNotEmpty)
                          Text(
                            alert['countyName'].toString(),
                            style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
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
                              color: TbColors.live.withValues(alpha: 0.10),
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
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
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
                              border: Border.all(color: TbColors.line),
                            ),
                            child: const Text(
                              'osäker',
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                                color: TbColors.muted,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  if (alert['worth_it_score'] != null)
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      margin: const EdgeInsets.only(right: 6),
                      decoration: BoxDecoration(
                        color: TbColors.taxiDeep,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        '${(alert['worth_it_score'] as num).round()} p',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w800,
                          fontSize: 14,
                        ),
                      ),
                    ),
                  LikelihoodBadge(
                    likelihood: likelihood,
                    distanceKm: (alert['distance_km'] as num?)?.toDouble(),
                  ),
                  if (onToggleFavorite != null) ...[
                    const SizedBox(width: 2),
                    // Sparat tips. Fylld stjärna = det här kortet överlever
                    // filtren, marknadsradien och att störningen tar slut --
                    // det ligger kvar under Sparade tills föraren tar bort
                    // det. Se core/models.py:OpportunityFavorite.
                    InkWell(
                      onTap: () => onToggleFavorite!(!isFavorite),
                      borderRadius: BorderRadius.circular(20),
                      child: Padding(
                        padding: const EdgeInsets.all(4),
                        child: Icon(
                          isFavorite ? Icons.star : Icons.star_border,
                          size: 22,
                          color: isFavorite ? TbColors.taxi : TbColors.muted,
                          semanticLabel: isFavorite
                              ? 'Ta bort från sparade'
                              : 'Spara tipset',
                        ),
                      ),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 6),
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 2),
              Row(
                children: [
                  BrandIcons.clock(size: 13, color: Colors.grey),
                  const SizedBox(width: 4),
                  Text(
                    timeLeft,
                    style: TextStyle(
                      fontSize: 15,
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
                      style: TextStyle(
                        fontSize: 15,
                        color: Colors.grey.shade400,
                      ),
                    ),
                    Text(
                      dateTimeLabel(alert['start_time']?.toString()),
                      style: TextStyle(
                        fontSize: 15,
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
                    travel.isLastDeparture
                        ? Icon(Icons.last_page, size: 15, color: travelColor)
                        : travel.hasAlternative
                        ? BrandIcons.bus(size: 15, color: travelColor)
                        : Icon(
                            Icons.schedule_send,
                            size: 15,
                            color: travelColor,
                          ),
                    const SizedBox(width: 5),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            travel.summary!,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 15,
                              height: 1.25,
                              fontWeight: FontWeight.w700,
                              color: travelColor,
                            ),
                          ),
                          if (travel.planner != null)
                            Text(
                              'Enligt reseplaneraren ${travel.planner}',
                              style: const TextStyle(
                                fontSize: 12,
                                color: TbColors.muted,
                              ),
                            ),
                        ],
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
                    fontSize: 15.5,
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
