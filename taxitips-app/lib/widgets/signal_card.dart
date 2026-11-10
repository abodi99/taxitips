import 'dart:async';

import 'package:flutter/material.dart';

import '../severity_labels.dart';
import '../signal_kinds.dart';
import '../theme.dart';

/// Serverns rad 2: vad som hänt, högst fyra ord ("Tåg 22:48 inställt").
/// Tom för äldre servrar och för "Övrigt" -- då faller vyerna tillbaka på
/// dagens rubrik.
String serverHeadline(Map alert) => _field(alert['headline']);

/// Serverns rad 3: det som avgör ("Nästa tåg 23:48"). Tom om den saknas.
String serverDecision(Map alert) => _field(alert['decision']);

/// Färgen på beslutsraden. go = ingen annan väg, värt att köra (grönt); no =
/// resenärerna klarar sig (grått); wait/okänt = osäkert (mörkt). Texten bär
/// alltid orden, färgen är bara förstärkning.
Color decisionColor(Map alert) {
  switch (_field(alert['decision_tone'])) {
    case 'go':
      return TbColors.live;
    case 'no':
      return TbColors.skiffer;
    default:
      return TbColors.midnatt;
  }
}

/// Ett tips i listan, byggt för en blick från förarplatsen: tre rader.
///
/// 1. VAR (plats, avstånd till höger). 2. VAD (kort rubrik + styrkeordet).
/// 3. BESLUTET (det som avgör, i färg efter tonen; 💰 när taxi betalas).
/// Färgad vänsterkant och ikonruta bär styrkan, men ordet står kvar så att
/// färg aldrig är ensam bärare. Källans fria text hör hemma i detaljvyn.
class SignalCard extends StatelessWidget {
  const SignalCard({
    super.key,
    required this.alert,
    this.onTap,
    this.onToggleFollow,
    this.onDrive,
    this.compact = false,
  });

  final Map<String, dynamic> alert;
  final VoidCallback? onTap;

  /// "Kör dit" direkt från listan: ett tryck till navigeringen. Visas bara på
  /// stora kort med koordinat som inte tagit slut. `null` = ingen knapp.
  final VoidCallback? onDrive;

  /// En rad i stället för ett kort: för svaga tips och "Övrigt". De ska
  /// synas men inte ta plats från det som är värt att köra på.
  final bool compact;

  /// `null` = ingen stjärna alls (backend kan inte spara), aldrig en knapp som
  /// tyst inte gör något. Stjärnan visas bara på redan sparade tips; att spara
  /// görs i detaljvyn.
  final ValueChanged<bool>? onToggleFollow;

  @override
  Widget build(BuildContext context) {
    final category = categoryOfAlert(alert);
    final strength = strengthOfAlert(alert);
    final color = strengthColor(strength, category: category);
    final active = alert['is_active'] != false;
    final followed = alert['is_favorite'] == true;
    final minor = alert['minor'] == true;
    // Rad 1 är VAR. Saknas station tar vi länet ("Skåne") när servern har en
    // rubrik för rad 2 -- annars stod samma sak två gånger ("Buss: Försening"
    // över "Buss sen"). "Övrigt" har ingen rubrik: där är källans titel allt.
    final county = countyShort(alert['countyName']?.toString() ?? '');
    final place = tipStation(alert).isNotEmpty
        ? tipStation(alert)
        : (!minor && serverHeadline(alert).isNotEmpty && county.isNotEmpty
              ? county
              : alertPlaceTitle(alert));
    final distance = alert['distance_km'] as num?;
    final headline = serverHeadline(alert).isNotEmpty
        ? serverHeadline(alert)
        : shortWhat(alert);
    final decision = serverDecision(alert);
    final travel = TravelOptions.of(alert);
    final edge = active ? color : TbColors.skiffer;

    // Rad 3: slut > serverns beslut > dagens avgångsrad > ingenting.
    Widget? row3;
    if (!active) {
      row3 = const Text(
        'Slut',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w700,
          color: TbColors.skiffer,
        ),
      );
    } else if (decision.isNotEmpty) {
      row3 = Text(
        decision,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.w800,
          color: decisionColor(alert),
        ),
      );
    } else if (travel != null) {
      row3 = LiveTravelText(
        travel,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w700,
          color: travel.isStrong
              ? TbColors.live
              : (travel.isWeak ? TbColors.skiffer : TbColors.midnatt),
        ),
      );
    }
    final pays = active && alert['compensation_eligible'] == true;

    if (compact) {
      // En rad: prick i styrkans färg, plats, vad som hänt, avstånd.
      final detail = [
        headline,
        if (active && decision.isNotEmpty) decision,
        if (!active) 'Slut',
      ].join(' · ');
      return Material(
        color: active ? TbColors.vit : TbColors.ljusgra,
        borderRadius: BorderRadius.circular(12),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: 52),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: TbColors.line),
            ),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                Icon(iconForAlert(alert), size: 22, color: edge),
                const SizedBox(width: 10),
                Expanded(
                  child: Text.rich(
                    TextSpan(
                      children: [
                        TextSpan(
                          text: place,
                          style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            color: TbColors.midnatt,
                          ),
                        ),
                        TextSpan(
                          text: '  $detail',
                          style: const TextStyle(color: TbColors.skiffer),
                        ),
                      ],
                    ),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 15, height: 1.25),
                  ),
                ),
                if (distance != null) ...[
                  const SizedBox(width: 8),
                  Text(
                    distanceText(distance),
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: TbColors.skiffer,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      );
    }

    final canDrive =
        onDrive != null &&
        active &&
        alert['lat'] != null &&
        alert['lon'] != null;

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
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(width: 4, color: edge),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(10, 10, 4, 10),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _IconTile(
                          icon: iconForAlert(alert),
                          color: edge,
                          hazard: category == SignalCategory.road,
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      place,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                        fontFamily: kDisplayFont,
                                        fontSize: 18,
                                        fontWeight: FontWeight.w700,
                                        height: 1.2,
                                        color: TbColors.midnatt,
                                      ),
                                    ),
                                  ),
                                  if (distance != null) ...[
                                    const SizedBox(width: 8),
                                    Text(
                                      distanceText(distance),
                                      maxLines: 1,
                                      style: const TextStyle(
                                        fontSize: 14,
                                        fontWeight: FontWeight.w700,
                                        color: TbColors.skiffer,
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                              const SizedBox(height: 2),
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      headline,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                        fontSize: 15,
                                        fontWeight: FontWeight.w600,
                                        color: TbColors.midnatt,
                                      ),
                                    ),
                                  ),
                                  const SizedBox(width: 6),
                                  // "Övrigt" är trafikbolagets meddelande,
                                  // inte en bedömning: ingen styrka att visa.
                                  if (!minor)
                                    StrengthPill(
                                      strength: strength,
                                      category: category,
                                      muted: !active,
                                    ),
                                ],
                              ),
                              if (row3 != null || pays) ...[
                                const SizedBox(height: 2),
                                Row(
                                  children: [
                                    Expanded(child: row3 ?? const SizedBox()),
                                    if (pays)
                                      const Icon(
                                        Icons.payments_rounded,
                                        size: 20,
                                        color: TbColors.live,
                                        semanticLabel: 'Taxi betalas',
                                      ),
                                  ],
                                ),
                              ],
                            ],
                          ),
                        ),
                        if (canDrive)
                          // Ett tryck till navigeringen, utan att öppna tipset.
                          Padding(
                            padding: const EdgeInsets.only(left: 8, right: 6),
                            child: Center(
                              child: IconButton.filled(
                                onPressed: onDrive,
                                tooltip: 'Kör dit',
                                style: IconButton.styleFrom(
                                  backgroundColor: TbColors.taxi,
                                  foregroundColor: TbColors.ink,
                                  minimumSize: const Size(48, 48),
                                ),
                                icon: const Icon(
                                  Icons.navigation_rounded,
                                  semanticLabel: 'Kör dit',
                                ),
                              ),
                            ),
                          )
                        else if (followed && onToggleFollow != null)
                          FollowButton(
                            followed: followed,
                            onChanged: onToggleFollow!,
                          )
                        else
                          const SizedBox(width: 8),
                      ],
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

/// Förarbeskedet från backend (core/briefs.py): en rad i förarens ord, bara
/// skriven ur tipsets egna fält. `null` när det saknas -- då visas det som
/// alltid visats.
String? tipBrief(Map alert) {
  final brief = alert['brief']?.toString().trim() ?? '';
  return brief.isEmpty ? null : brief;
}

/// Platsen först ("Göteborg C"), annars källans rubrik med färdsättet.
String alertPlaceTitle(Map<String, dynamic> alert) {
  final station = tipStation(alert);
  if (station.isNotEmpty) return station;
  return displayTitle(
    title: alert['title']?.toString(),
    mode: alert['mode']?.toString(),
  );
}

String _field(Object? value) => value == null ? '' : value.toString().trim();

/// Linjen tipset gäller ("Buss 725", "Pågatåg 1612"), som backend skickar
/// den i `line`. Tom när den saknas -- äldre svar har inget sådant fält.
String tipLine(Map alert) => _field(alert['line']);

/// Stationen eller hållplatsen tipset gäller: backendens `station`, annars
/// hållplatsnamnet eller första platsen i `taxi.places`. Tom när ingen finns.
String tipStation(Map alert) {
  final station = _field(alert['station']);
  if (station.isNotEmpty) return station;
  final stop = _field(alert['stop_name']);
  if (stop.isNotEmpty) return stop;
  final places = (alert['taxi'] as Map?)?['places'];
  if (places is List && places.isNotEmpty) return _field(places.first);
  return '';
}

/// "Buss 725 · Tumba station": linje och station på en rad, det föraren
/// letar efter först. Bara det som finns; `null` när båda saknas, och då
/// visas inget extra.
String? tipLineStation(Map alert) {
  final line = tipLine(alert);
  final station = tipStation(alert);
  final parts = [
    if (line.isNotEmpty) line,
    if (station.isNotEmpty && station.toLowerCase() != line.toLowerCase())
      station,
  ];
  return parts.isEmpty ? null : parts.join(' · ');
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
        // Flexible: med stor text bryts raden i stället för att spilla över.
        Flexible(
          child: Text(
            text,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: c,
            ),
          ),
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
      tooltip: followed ? 'Ta bort sparat' : 'Spara tipset',
      icon: Icon(
        followed ? Icons.star_rounded : Icons.star_outline_rounded,
        color: followed ? TbColors.guldDjup : TbColors.skiffer,
        semanticLabel: followed ? 'Ta bort sparat' : 'Spara tipset',
      ),
    );
  }
}

/// Nästa-avgång-raden som räknar om "om X min" mot klockan var 20:e sekund,
/// så ett kort som ligger kvar i listan inte fryser på det avstånd som gällde
/// när det hämtades.
class LiveTravelText extends StatefulWidget {
  const LiveTravelText(
    this.travel, {
    super.key,
    this.style,
    this.maxLines,
    this.overflow,
  });

  final TravelOptions travel;
  final TextStyle? style;
  final int? maxLines;
  final TextOverflow? overflow;

  @override
  State<LiveTravelText> createState() => _LiveTravelTextState();
}

class _LiveTravelTextState extends State<LiveTravelText> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    if (widget.travel.nextDepartureAt != null) {
      _timer = Timer.periodic(const Duration(seconds: 20), (_) {
        if (mounted) setState(() {});
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Text(
    widget.travel.text(),
    style: widget.style,
    maxLines: widget.maxLines,
    overflow: widget.overflow,
  );
}

/// Tipsen är vad vi läser ut ur trafiken, inte beställda körningar.
///
/// En kort rad längst ner -- den syns varje gång, så den ska inte ta plats.
/// Tryck för en mening till.
class TipsNotPromisesNote extends StatelessWidget {
  const TipsNotPromisesNote({super.key});

  static const title = 'Tips, inte beställningar';
  static const body =
      'Vi läser av trafiken och visar var folk kan behöva taxi. Du avgör '
      'själv om det är värt att åka.';

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: '$title. Visa mer',
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () => showDialog<void>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text(title),
            content: const Text(body),
            actions: [
              FilledButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Uppfattat'),
              ),
            ],
          ),
        ),
        child: const Padding(
          padding: EdgeInsets.symmetric(vertical: 8),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                Icons.info_outline_rounded,
                size: 15,
                color: TbColors.skiffer,
              ),
              SizedBox(width: 6),
              Flexible(
                child: Text(
                  'Tips från trafikläget, ingen garanti för körning',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 12.5, color: TbColors.skiffer),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
