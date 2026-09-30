/// Märkningen som gör att ingen tar demon för levande data, plus vägarna ut:
/// "Avsluta demo" tillbaka till startsidan och "Prova gratis i 14 dagar".
///
/// Inga priser och inga betallänkar (docs/fleet-abonnemang.md §9c): knappen
/// leder till registreringen, där provet är kortfritt.
library;

import 'package:flutter/material.dart';

import '../theme.dart';

class DemoBanner extends StatelessWidget {
  const DemoBanner({super.key, this.onExit, this.onSignup});

  final VoidCallback? onExit;
  final VoidCallback? onSignup;

  static const badgeText = 'Demo – påhittade exempel';
  static const ctaText = 'Prova gratis i 14 dagar';
  static const exitText = 'Avsluta demo';

  static Future<void> explain(BuildContext context) => showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text(badgeText),
      content: const Text(
        'Det här är ett exempel med påhittad information, så att du kan '
        'se hur TaxiTips fungerar. Inget är live och inget sparas.',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Stäng'),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 6, 6, 6),
      decoration: BoxDecoration(
        color: TbColors.midnatt,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: InkWell(
                  onTap: () => explain(context),
                  child: const Row(
                    children: [
                      Icon(Icons.info_outline, size: 18, color: TbColors.guld),
                      SizedBox(width: 6),
                      Flexible(
                        child: Text(
                          badgeText,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: TbColors.vit,
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              if (onExit != null)
                TextButton(
                  onPressed: onExit,
                  style: TextButton.styleFrom(
                    foregroundColor: TbColors.vit,
                    visualDensity: VisualDensity.compact,
                  ),
                  child: const Text(exitText),
                ),
            ],
          ),
          if (onSignup != null)
            Padding(
              padding: const EdgeInsets.only(right: 6, bottom: 2),
              child: FilledButton(
                onPressed: onSignup,
                style: FilledButton.styleFrom(
                  backgroundColor: TbColors.guld,
                  foregroundColor: TbColors.midnatt,
                  minimumSize: const Size.fromHeight(40),
                  textStyle: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                child: const Text(ctaText),
              ),
            ),
        ],
      ),
    );
  }
}
