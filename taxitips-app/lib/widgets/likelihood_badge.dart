import 'package:flutter/material.dart';
import '../severity_labels.dart';
import '../theme.dart';

/// Priority + distance, shown identically on the list card and in the detail
/// sheet so the sheet confirms what the card already claimed.
///
/// This used to read "Osannolikt just nu" / "Möjligt att det finns kunder"
/// -- a verdict rather than information. A driver can't act on a guess about
/// probability, and it hid the three facts that actually decide whether to
/// drive: what kind of disruption, how far, how fresh. Severity is on the
/// card already and freshness is the timestamp, so this badge now carries
/// the distance and uses colour for priority at a glance.
///
/// Colour is never the only signal: high/medium are filled with a glyph,
/// low is outlined without one. Fill-vs-outline is a shape/luminance cue
/// that survives bright sunlight and colour-vision deficiency, where hue
/// alone would not.
class LikelihoodBadge extends StatelessWidget {
  const LikelihoodBadge({
    super.key,
    required this.likelihood,
    this.distanceKm,
    this.fontSize = 14,
  });

  final CustomerLikelihood likelihood;

  /// Straight-line km from the driver. Null when the alert carries no
  /// coordinates -- roughly 40% of live signals -- in which case the badge
  /// says so plainly instead of implying a distance it doesn't know.
  final double? distanceKm;

  final double fontSize;

  Color get _color => switch (likelihood) {
    CustomerLikelihood.high => TbColors.likelihoodHigh,
    CustomerLikelihood.medium => TbColors.likelihoodMedium,
    CustomerLikelihood.low => TbColors.likelihoodLow,
  };

  IconData? get _glyph => switch (likelihood) {
    CustomerLikelihood.high => Icons.priority_high,
    CustomerLikelihood.medium => Icons.circle,
    CustomerLikelihood.low => null,
  };

  String get _label {
    final d = distanceKm;
    if (d == null) return 'Plats okänd';
    if (d < 1) return 'Under 1 km';
    if (d < 10) return '${d.toStringAsFixed(1)} km';
    return '${d.round()} km';
  }

  @override
  Widget build(BuildContext context) {
    final filled = likelihood != CustomerLikelihood.low;
    final color = _color;
    final glyph = _glyph;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: filled ? color : Colors.transparent,
        borderRadius: BorderRadius.circular(20),
        border: filled ? null : Border.all(color: color, width: 1.5),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (glyph != null) ...[
            Icon(
              glyph,
              size: likelihood == CustomerLikelihood.medium ? 8 : fontSize,
              color: Colors.white,
            ),
            const SizedBox(width: 4),
          ],
          Text(
            _label,
            style: TextStyle(
              fontWeight: FontWeight.bold,
              fontSize: fontSize,
              color: filled ? Colors.white : color,
            ),
          ),
        ],
      ),
    );
  }
}
