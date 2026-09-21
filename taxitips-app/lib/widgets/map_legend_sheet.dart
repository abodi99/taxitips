import 'package:flutter/material.dart';

import '../signal_kinds.dart';
import '../theme.dart';
import 'signal_card.dart' show StrengthPill;
import 'signal_marker.dart';

/// "Vad betyder symbolerna?" -- kartans förklaring, en skärm, inga stycken.
///
/// Varje rad är symbolen som den ser ut på kartan och några få ord. Den som
/// inte läser svenska obehindrat ska kunna lära sig kartan av bilderna.
Future<void> showMapLegend(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: TbColors.ljusgra,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
    ),
    builder: (ctx) => SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.sizeOf(ctx).height * 0.9,
        ),
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                margin: const EdgeInsets.only(bottom: 14),
                decoration: BoxDecoration(
                  color: TbColors.line,
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            ),
            const Text(
              'Symbolerna på kartan',
              style: TextStyle(
                fontFamily: kDisplayFont,
                fontSize: 22,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 16),
            const _Heading('Typ'),
            for (final c in signalCategoryOrder)
              _Row(
                symbol: c == SignalCategory.road
                    ? const HazardSign(
                        icon: Icons.car_crash_rounded,
                        strength: SignalStrength.high,
                      )
                    : SignalPin(
                        icon: c.icon,
                        strength: SignalStrength.high,
                        category: c,
                      ),
                title: c.label,
                text: c.explanation,
              ),
            const SizedBox(height: 8),
            const _Heading('Färg = hur viktigt'),
            for (final s in SignalStrength.values)
              _Row(
                symbol: SignalPin(
                  icon: Icons.train_rounded,
                  strength: s,
                  category: SignalCategory.transit,
                ),
                titleWidget: StrengthPill(strength: s, large: true),
                text: switch (s) {
                  SignalStrength.high =>
                    'Många behöver taxi. Värt att köra dit.',
                  SignalStrength.medium => 'Kanske kunder. Titta på avståndet.',
                  SignalStrength.low => 'Få kunder. Bra att veta.',
                },
              ),
            const SizedBox(height: 8),
            const _Heading('Väg (Trafikverket)'),
            // Bara olyckor visas -- se thresholds.ROAD_SHOWN_CONDITIONS.
            const _Row(
              symbol: HazardSign(
                icon: Icons.car_crash_rounded,
                strength: SignalStrength.high,
              ),
              titleWidget: StrengthPill(
                strength: SignalStrength.high,
                category: SignalCategory.road,
                large: true,
              ),
              text: 'Trafikolycka. Räkna med kö, eller kör en annan väg.',
            ),
            const SizedBox(height: 8),
            const _Heading('Övrigt'),
            const _Row(
              symbol: ClusterBubble(
                count: 5,
                strength: SignalStrength.high,
                hazard: false,
              ),
              title: 'Flera på samma plats',
              text: 'Tryck för att zooma in.',
            ),
            const _Row(
              symbol: SignalPin(
                icon: Icons.train_rounded,
                strength: SignalStrength.medium,
                category: SignalCategory.transit,
                followed: true,
              ),
              title: 'Följer',
              text: 'Du följer den här. Tryck på stjärnan för att följa något.',
            ),
          ],
        ),
      ),
    ),
  );
}

class _Heading extends StatelessWidget {
  const _Heading(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 6, top: 4),
    child: Text(
      text.toUpperCase(),
      style: const TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w700,
        letterSpacing: 0.8,
        color: TbColors.skiffer,
      ),
    ),
  );
}

class _Row extends StatelessWidget {
  const _Row({
    required this.symbol,
    required this.text,
    this.title,
    this.titleWidget,
  });

  final Widget symbol;
  final String? title;
  final Widget? titleWidget;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          SizedBox(width: 64, height: 60, child: Center(child: symbol)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (titleWidget != null)
                  titleWidget!
                else
                  Text(
                    title ?? '',
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: TbColors.midnatt,
                    ),
                  ),
                const SizedBox(height: 2),
                Text(
                  text,
                  style: const TextStyle(
                    fontSize: 14,
                    height: 1.3,
                    color: TbColors.skiffer,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
