import 'dart:async';

import 'package:flutter/material.dart';

import '../severity_labels.dart';
import '../theme.dart';
import 'brand_icons.dart';
import 'signal_card.dart' show LiveTravelText;

/// Avgångstavlan: den drabbade avgången stort, "om X" räknat mot den, och hur
/// länge resenären blir stående efter den. Mörk som en riktig tavla, så att
/// den syns först -- det är den raden föraren fattar beslutet på.
class DepartureBoard extends StatefulWidget {
  const DepartureBoard({
    super.key,
    required this.travel,
    this.showAlternative = true,
  });

  final TravelOptions travel;

  /// Raden om ersättningstrafik. Tipsbladet visar den under "Mer om tipset"
  /// i stället, så att tavlan bara svarar på "när" och "hur länge".
  final bool showAlternative;

  @override
  State<DepartureBoard> createState() => _DepartureBoardState();
}

class _DepartureBoardState extends State<DepartureBoard> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // "om 49 min" ska stämma medan föraren tittar.
    _timer = Timer.periodic(const Duration(seconds: 20), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final travel = widget.travel;
    final dep = travel.departure!;
    final rel = relativeDeparture(dep.at);
    final wait = travel.waitText;
    final waitStrong = travel.isLastDeparture || (travel.gapMinutes ?? 0) > 30;
    final alternative =
        widget.showAlternative &&
        travel.hasAlternative &&
        (travel.alternative ?? '').isNotEmpty;
    final (chip, chipBg, chipFg) = dep.cancelled
        ? ('INSTÄLLD', TbColors.danger, TbColors.vit)
        : (
            dep.delayMinutes == null
                ? 'FÖRSENAD'
                : 'FÖRSENAD ${humanMinutes(dep.delayMinutes!).toUpperCase()}',
            TbColors.guld,
            TbColors.midnatt,
          );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      decoration: BoxDecoration(
        color: TbColors.midnatt,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: chipBg,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  chip,
                  style: TextStyle(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.6,
                    color: chipFg,
                  ),
                ),
              ),
              const Spacer(),
              Text(
                rel,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: Color(0xCCFFFFFF),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.end,
            spacing: 10,
            children: [
              Text(
                dep.clock,
                style: TextStyle(
                  fontFamily: kDisplayFont,
                  fontSize: 34,
                  height: 1.05,
                  fontWeight: FontWeight.w800,
                  color: dep.cancelled ? const Color(0x99FFFFFF) : TbColors.vit,
                  decoration: dep.cancelled ? TextDecoration.lineThrough : null,
                  decorationColor: TbColors.danger,
                  decorationThickness: 3,
                ),
              ),
              if (!dep.cancelled && dep.newClock != null)
                Text(
                  '→ ${dep.newClock}',
                  style: const TextStyle(
                    fontFamily: kDisplayFont,
                    fontSize: 34,
                    height: 1.05,
                    fontWeight: FontWeight.w800,
                    color: TbColors.guld,
                  ),
                ),
            ],
          ),
          if (dep.destination != null) ...[
            const SizedBox(height: 4),
            Text(
              'mot ${dep.destination}',
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: TbColors.vit,
              ),
            ),
          ],
          if (wait != null || alternative) ...[
            const SizedBox(height: 12),
            Container(height: 1, color: const Color(0x26FFFFFF)),
            const SizedBox(height: 10),
          ],
          if (wait != null)
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  travel.isLastDeparture
                      ? Icons.last_page_rounded
                      : Icons.schedule_rounded,
                  size: 19,
                  color: waitStrong ? TbColors.guld : const Color(0xB3FFFFFF),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    wait,
                    style: TextStyle(
                      fontSize: 16,
                      height: 1.3,
                      fontWeight: FontWeight.w700,
                      color: waitStrong
                          ? TbColors.guld
                          : const Color(0xB3FFFFFF),
                    ),
                  ),
                ),
              ],
            ),
          if (alternative)
            Padding(
              padding: EdgeInsets.only(top: wait != null ? 6 : 0),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  BrandIcons.bus(size: 19, color: const Color(0xB3FFFFFF)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      travel.alternative!,
                      style: const TextStyle(
                        fontSize: 15,
                        height: 1.3,
                        fontWeight: FontWeight.w600,
                        color: Color(0xB3FFFFFF),
                      ),
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

/// "Därför" -- läget och omständigheterna bakom ett tips, som korta rader:
/// en grön bock för det som talar för, ett grått streck för det som talar
/// emot. Inga poäng: raderna är beslutsunderlaget, siffran är det inte.
class FactorList extends StatelessWidget {
  const FactorList({super.key, required this.factors});

  final List<TipFactor> factors;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final f in factors)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  f.supports
                      ? Icons.check_circle_rounded
                      : Icons.remove_circle_outline_rounded,
                  size: 22,
                  color: f.supports ? TbColors.live : TbColors.skiffer,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    f.text,
                    style: TextStyle(
                      fontSize: 16.5,
                      height: 1.3,
                      fontWeight: FontWeight.w600,
                      color: f.supports ? TbColors.ink : TbColors.skiffer,
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Nästa avgång som en egen ruta: hur länge folk blir stående är det som
/// avgör om tipset är värt en körning. Bara resan -- aldrig vilken tjänst som
/// svarade. Används när tipset saknar en egen drabbad avgång (då tar
/// [DepartureBoard] över).
class NextDepartureBox extends StatelessWidget {
  const NextDepartureBox({super.key, required this.travel});

  final TravelOptions travel;

  @override
  Widget build(BuildContext context) {
    final color = travel.isStrong ? TbColors.live : TbColors.midnatt;
    final Widget icon = travel.isLastDeparture
        ? Icon(Icons.last_page, size: 22, color: color)
        : travel.hasAlternative
        ? BrandIcons.bus(size: 22, color: color)
        : Icon(Icons.schedule_rounded, size: 22, color: color);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: travel.isStrong
            ? TbColors.live.withValues(alpha: 0.08)
            : TbColors.vit,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: travel.isStrong
              ? TbColors.live.withValues(alpha: 0.4)
              : TbColors.line,
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(padding: const EdgeInsets.only(top: 1), child: icon),
          const SizedBox(width: 10),
          Expanded(
            child: LiveTravelText(
              travel,
              style: TextStyle(
                fontSize: 17,
                height: 1.35,
                fontWeight: FontWeight.w700,
                color: travel.isStrong ? TbColors.live : TbColors.ink,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
