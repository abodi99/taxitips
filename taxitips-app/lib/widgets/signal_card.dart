import 'package:flutter/material.dart';

import '../severity_labels.dart';
import '../signal_kinds.dart';
import '../theme.dart';

/// Ett tips i listan, byggt för en blick från förarplatsen.
///
/// Uppifrån och ner: VAD (ikonrutan och platsen), HUR VIKTIGT (färg + ett
/// ord), NÄR och HUR LÅNGT (siffror med ikon), och sist varför resenären kan
/// behöva taxi (nästa avgång). Den fria texten från källan visas i detaljvyn,
/// inte här -- den är lång, på myndighetssvenska och sällan det som avgör.
class SignalCard extends StatelessWidget {
  const SignalCard({
    super.key,
    required this.alert,
    this.onTap,
    this.onToggleFollow,
  });

  final Map<String, dynamic> alert;
  final VoidCallback? onTap;

  /// `null` = ingen stjärna alls (backend kan inte spara), aldrig en knapp som
  /// tyst inte gör något.
  final ValueChanged<bool>? onToggleFollow;

  @override
  Widget build(BuildContext context) {
    final category = categoryOfAlert(alert);
    final strength = strengthOfAlert(alert);
    final color = strengthColor(strength, category: category);
    final active = alert['is_active'] != false;
    final followed = alert['is_favorite'] == true;
    final title = alertPlaceTitle(alert);
    final start = DateTime.tryParse(
      alert['start_time']?.toString() ?? '',
    )?.toLocal();
    final distance = alert['distance_km'] as num?;
    final travel = TravelOptions.of(alert);

    return Material(
      color: active ? TbColors.vit : TbColors.ljusgra,
      borderRadius: BorderRadius.circular(16),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: TbColors.line),
          ),
          padding: const EdgeInsets.fromLTRB(12, 12, 4, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _IconTile(
                icon: iconForAlert(alert),
                color: active ? color : TbColors.skiffer,
                hazard: category == SignalCategory.road,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: kDisplayFont,
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        height: 1.2,
                        color: TbColors.midnatt,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        StrengthPill(
                          strength: strength,
                          category: category,
                          muted: !active,
                        ),
                        Text(
                          shortWhat(alert),
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: TbColors.skiffer,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 14,
                      runSpacing: 6,
                      children: [
                        if (!active)
                          const MetaItem(
                            icon: Icons.history_rounded,
                            text: 'Slut',
                          )
                        else if (start != null)
                          MetaItem(
                            icon: Icons.schedule_rounded,
                            text: ageText(start),
                          ),
                        if (distance != null)
                          MetaItem(
                            icon: Icons.near_me_rounded,
                            text: distanceText(distance),
                          ),
                        if (alert['compensation_eligible'] == true)
                          const MetaItem(
                            icon: Icons.payments_rounded,
                            text: 'Taxi betalas',
                            color: TbColors.live,
                          ),
                        if ((alert['countyName']?.toString() ?? '').isNotEmpty)
                          MetaItem(
                            icon: Icons.place_rounded,
                            text: countyShort(alert['countyName'].toString()),
                          ),
                      ],
                    ),
                    if (travel != null) ...[
                      const SizedBox(height: 8),
                      Text(
                        travel.summary!,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 14,
                          height: 1.3,
                          fontWeight: FontWeight.w600,
                          color: travel.isStrong
                              ? TbColors.live
                              : (travel.isWeak
                                    ? TbColors.skiffer
                                    : TbColors.midnatt),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (onToggleFollow != null)
                FollowButton(followed: followed, onChanged: onToggleFollow!),
            ],
          ),
        ),
      ),
    );
  }
}

/// Platsen först ("Göteborg C"), annars källans rubrik med färdsättet.
String alertPlaceTitle(Map<String, dynamic> alert) {
  final places = ((alert['taxi'] as Map?)?['places'] as List?) ?? const [];
  final stop = alert['stop_name']?.toString() ?? '';
  if (stop.isNotEmpty) return stop;
  if (places.isNotEmpty && places.first.toString().isNotEmpty) {
    return places.first.toString();
  }
  return displayTitle(
    title: alert['title']?.toString(),
    mode: alert['mode']?.toString(),
  );
}

/// Ikonruta i styrkans färg. Väghinder får triangelns ikon på varningsfärgen,
/// allt annat sin typs ikon.
class _IconTile extends StatelessWidget {
  const _IconTile({
    required this.icon,
    required this.color,
    required this.hazard,
  });

  final IconData icon;
  final Color color;
  final bool hazard;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 48,
      height: 48,
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(hazard ? 8 : 14),
      ),
      child: Icon(icon, color: TbColors.vit, size: 28),
    );
  }
}

/// Färgad prick + ett ord: "● Stark", "● Stopp". Aldrig bara färg.
class StrengthPill extends StatelessWidget {
  const StrengthPill({
    super.key,
    required this.strength,
    this.category,
    this.muted = false,
    this.large = false,
  });

  final SignalStrength strength;
  final SignalCategory? category;
  final bool muted;
  final bool large;

  @override
  Widget build(BuildContext context) {
    final color = muted
        ? TbColors.skiffer
        : strengthColor(strength, category: category);
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: large ? 10 : 8,
        vertical: large ? 4 : 2,
      ),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: large ? 10 : 8,
            height: large ? 10 : 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 5),
          Text(
            strengthWord(strength, category: category),
            style: TextStyle(
              fontSize: large ? 15 : 13,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

/// Ikon + kort text: "🕒 5 min", "➤ 3,2 km".
class MetaItem extends StatelessWidget {
  const MetaItem({
    super.key,
    required this.icon,
    required this.text,
    this.color,
  });

  final IconData icon;
  final String text;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? TbColors.midnatt;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: color ?? TbColors.skiffer),
        const SizedBox(width: 4),
        Text(
          text,
          style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: c),
        ),
      ],
    );
  }
}

/// Stjärnan. 48 × 48 tryckyta -- den ska gå att träffa med tummen i en bil.
class FollowButton extends StatelessWidget {
  const FollowButton({
    super.key,
    required this.followed,
    required this.onChanged,
  });

  final bool followed;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      onPressed: () => onChanged(!followed),
      iconSize: 28,
      constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
      tooltip: followed ? 'Sluta följa' : 'Följ',
      icon: Icon(
        followed ? Icons.star_rounded : Icons.star_outline_rounded,
        color: followed ? TbColors.guldDjup : TbColors.skiffer,
        semanticLabel: followed ? 'Sluta följa' : 'Följ',
      ),
    );
  }
}
