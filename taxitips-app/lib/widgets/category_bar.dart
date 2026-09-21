import 'package:flutter/material.dart';

import '../signal_kinds.dart';
import '../theme.dart';

/// Kategoriraden överst på kartan: Alla · Tåg & buss · Väg · Flyg · Färja ·
/// Event · Följer.
///
/// Ett val i taget. Det styr BÅDE kartan och listan, så att föraren aldrig
/// behöver förstå två olika filter. Varje knapp har ikon, ett kort ord och
/// antalet -- en knapp med 0 är nedtonad men går att trycka på, så att
/// "inget just nu" syns i stället för att knappen försvinner.
///
/// `null` = Alla, `'followed'` = Följer, annars en [SignalCategory.key].
class CategoryBar extends StatelessWidget {
  const CategoryBar({
    super.key,
    required this.selected,
    required this.counts,
    required this.followedCount,
    required this.onSelect,
    this.hidden = const {},
  });

  final String? selected;
  final Map<SignalCategory, int> counts;
  final int followedCount;
  final ValueChanged<String?> onSelect;

  /// Kategorier föraren stängt av helt i filtret -- visas inte i raden.
  final Set<SignalCategory> hidden;

  @override
  Widget build(BuildContext context) {
    final total = counts.values.fold<int>(0, (a, b) => a + b);
    return SizedBox(
      height: 48,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        children: [
          _CategoryChip(
            icon: Icons.apps_rounded,
            label: 'Alla',
            count: total,
            selected: selected == null,
            onTap: () => onSelect(null),
          ),
          for (final c in signalCategoryOrder)
            if (!hidden.contains(c))
              _CategoryChip(
                icon: c.icon,
                label: c.label,
                count: counts[c] ?? 0,
                selected: selected == c.key,
                onTap: () => onSelect(c.key),
              ),
          _CategoryChip(
            icon: Icons.star_rounded,
            label: 'Följer',
            count: followedCount,
            selected: selected == 'followed',
            onTap: () => onSelect('followed'),
            accent: true,
          ),
        ],
      ),
    );
  }
}

class _CategoryChip extends StatelessWidget {
  const _CategoryChip({
    required this.icon,
    required this.label,
    required this.count,
    required this.selected,
    required this.onTap,
    this.accent = false,
  });

  final IconData icon;
  final String label;
  final int count;
  final bool selected;
  final VoidCallback onTap;
  final bool accent;

  @override
  Widget build(BuildContext context) {
    final empty = count == 0 && !selected;
    final fg = selected
        ? TbColors.vit
        : (empty ? TbColors.skiffer : TbColors.midnatt);
    final bg = selected ? TbColors.midnatt : TbColors.vit;
    return Padding(
      padding: const EdgeInsets.only(right: 8, top: 2, bottom: 6),
      child: Material(
        color: bg,
        elevation: selected ? 3 : 2,
        shadowColor: Colors.black26,
        shape: StadiumBorder(
          side: BorderSide(color: selected ? TbColors.midnatt : TbColors.line),
        ),
        child: InkWell(
          customBorder: const StadiumBorder(),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 8, 0),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  icon,
                  size: 20,
                  color: accent && !selected
                      ? TbColors.guldDjup
                      : (selected && accent ? TbColors.guld : fg),
                ),
                const SizedBox(width: 6),
                Text(
                  label,
                  style: TextStyle(
                    fontFamily: kBodyFont,
                    fontWeight: FontWeight.w700,
                    fontSize: 15,
                    color: fg,
                  ),
                ),
                const SizedBox(width: 6),
                Container(
                  constraints: const BoxConstraints(minWidth: 24),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: selected ? TbColors.guld : TbColors.ljusgraDjup,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    count > 99 ? '99+' : '$count',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 13,
                      color: TbColors.midnatt,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
