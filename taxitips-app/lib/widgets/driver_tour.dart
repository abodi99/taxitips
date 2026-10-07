import 'package:flutter/material.dart';

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
      title: 'Tipslistan',
      text:
          'Här är tipsen nära dig. Det starkaste ligger överst. '
          'Dra listan uppåt för att se fler.',
      keys: [keys.list],
    ),
    TourStep(
      id: 'strength',
      title: 'Färgen visar styrkan',
      text:
          'Varje tips har en färg och ett ord. Längst ner i listan finns '
          '"Övrigt": meddelanden från trafikbolag. Det är information, '
          'inte tips.',
      keys: [keys.firstCard, keys.list],
      extra: const _StrengthLegend(),
    ),
    TourStep(
      id: 'map',
      title: 'Kartan och nålarna',
      text:
          'Varje nål är ett tips. Nålen har samma färg som tipset. Tryck på '
          'en nål för att öppna tipset. Knappen med frågetecken förklarar '
          'symbolerna.',
      area: mapArea,
    ),
    TourStep(
      id: 'tip',
      title: 'Tryck på ett tips',
      text:
          'Då öppnas ett blad med mer om tipset. Där kan du köra dit, spara '
          'tipset och svara hur det gick. Svaren gör tipsen bättre.',
      keys: [keys.firstCard, keys.list],
      extra: const _TipSheetButtons(),
    ),
    TourStep(
      id: 'categories',
      title: 'Kategorier',
      text:
          'Välj vad du vill se: tåg och buss, väg, flyg, färja eller event. '
          'Siffran är antal tips. Sparat visar tipsen du har sparat.',
      keys: [keys.categories],
    ),
    TourStep(
      id: 'filter',
      title: 'Filter och län',
      text:
          'Med Filter väljer du län, hur starka tips du vill se och vad som '
          'ska döljas. Välj ditt län här så får du tips därifrån.',
      keys: [keys.filter],
    ),
    TourStep(
      id: 'settings',
      title: 'Inställningar',
      text: owner
          ? 'Här väljer du län och slår på notiser. Förare bjuds in på webben. '
                'Här väljer du också vilken plats du kör med. '
                'Genomgången finns kvar under Hjälp.'
          : 'Här slår du på notiser och väljer bilen du kör. Notiser säger '
                'till när ett starkt tips dyker upp nära dig. Genomgången '
                'finns kvar under Hjälp.',
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
          chip(Icons.navigation_rounded, 'Kör dit'),
          chip(Icons.star_outline_rounded, 'Spara'),
          chip(Icons.thumbs_up_down_rounded, 'Hur gick det?'),
        ],
      ),
    );
  }
}
