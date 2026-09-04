import 'package:flutter/material.dart';
import '../severity_labels.dart';
import '../theme.dart';

/// The "should I go" answer, shown identically on the list card and in the
/// detail sheet so the sheet visually confirms what the card already
/// claimed, rather than making the driver remember it.
///
/// Color alone is never the only signal: High/Medium are filled with a
/// small glyph, Low is outlined with no glyph. Fill-vs-outline is a
/// shape/luminance cue that still works in bright sunlight or for a
/// color-vision-deficient driver, when hue alone might not.
class LikelihoodBadge extends StatelessWidget {
  const LikelihoodBadge({super.key, required this.likelihood, this.fontSize = 14});

  final CustomerLikelihood likelihood;
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
            customerLikelihoodLabels[likelihood]!,
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
