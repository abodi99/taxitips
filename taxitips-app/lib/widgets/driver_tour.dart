import 'package:flutter/material.dart';

import '../l10n/l10n.dart';
import '../signal_kinds.dart';
import '../theme.dart';
import 'guided_tour.dart';
import 'signal_card.dart';

/// Elementen på huvudskärmen som genomgången pekar på. Förarskärmen sätter
/// nycklarna på sina egna widgets; här står bara vilka som finns.
class DriverTourKeys {
  /// Listans rubrik ("Alla tips · 12") -- finns alltid, även utan tips.
  final list = GlobalKey(debugLabel: 'tour_list');

  /// Första tipskortet. Saknas när listan är tom eller kortet inte syns.
  final firstCard = GlobalKey(debugLabel: 'tour_first_card');

  final categories = GlobalKey(debugLabel: 'tour_categories');
  final filter = GlobalKey(debugLabel: 'tour_filter');

  /// Historik-knappen: klockan i raden överst, i vänstra hörnet.
  final history = GlobalKey(debugLabel: 'tour_history');
  final settings = GlobalKey(debugLabel: 'tour_settings');
}

/// Stegen i den guidade genomgången, i den ordning en förare behöver dem:
/// listan och styrkan, kartan, vad som händer när man trycker på ett tips,
/// kategorierna, filtret och sist Inställningar.
///
/// Ägare och förare får olika text i sista steget: en ägare hanterar bilar, län
/// och förare i Inställningar, en förare slår på notiser och väljer bil.
///
/// Texterna är korta och i enkel svenska. Inget lovar kunder: styrkan säger
/// hur troligt det är, aldrig att någon väntar (se [strengthMeaning]).
List<TourStep> driverTourSteps({
  required DriverTourKeys keys,
  required bool owner,
  required Rect? Function() mapArea,
}) {
  return [
    TourStep(
      id: 'list',
      title: tr.driverTourListTitle,
      text: tr.driverTourListText,
      keys: [keys.list],
    ),
    TourStep(
      id: 'strength',
      title: tr.driverTourStrengthTitle,
      text: tr.driverTourStrengthText,
      keys: [keys.firstCard, keys.list],
      extra: const _StrengthLegend(),
    ),
    TourStep(
      id: 'map',
      title: tr.driverTourMapTitle,
      text: tr.driverTourMapText,
      area: mapArea,
    ),
    TourStep(
      id: 'tip',
      title: tr.driverTourTipTitle,
      text: tr.driverTourTipText,
      keys: [keys.firstCard, keys.list],
      extra: const _TipSheetButtons(),
    ),
    TourStep(
      id: 'categories',
      title: tr.driverTourCategoriesTitle,
      text: tr.driverTourCategoriesText,
      keys: [keys.categories],
    ),
    TourStep(
      id: 'filter',
      title: tr.driverTourFilterTitle,
      text: tr.driverTourFilterText,
      keys: [keys.filter],
    ),
    TourStep(
      id: 'settings',
      title: tr.driverTourSettingsTitle,
      text: owner ? tr.driverTourSettingsOwner : tr.driverTourSettingsDriver,
      keys: [keys.settings],
    ),
  ];
}

/// Stark, Medel och Svag med appens egna färger och ordet bredvid -- aldrig
/// bara färg.
class _StrengthLegend extends StatelessWidget {
  const _StrengthLegend();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final s in SignalStrength.values)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Wrap(
              spacing: 10,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                StrengthPill(strength: s, large: true),
                Text(
                  strengthMeaning(s),
                  style: const TextStyle(
                    fontSize: 15,
                    height: 1.3,
                    color: TbColors.skiffer,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Knapparna i tipsbladet, som de ser ut där -- bara att titta på.
class _TipSheetButtons extends StatelessWidget {
  const _TipSheetButtons();

  @override
  Widget build(BuildContext context) {
    Widget chip(IconData icon, String label) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: TbColors.ljusgra,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TbColors.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 20, color: TbColors.midnatt),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: TbColors.midnatt,
            ),
          ),
        ],
      ),
    );
    return ExcludeSemantics(
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          chip(Icons.navigation_rounded, tr.driverTourDrive),
          chip(Icons.star_outline_rounded, tr.driverTourSave),
          chip(Icons.thumbs_up_down_rounded, tr.driverTourHowWasIt),
        ],
      ),
    );
  }
}
