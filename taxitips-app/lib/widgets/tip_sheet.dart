import 'dart:async';

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../config.dart';
import '../follow_up.dart';
import '../navigation.dart';
import '../severity_labels.dart';
import '../signal_kinds.dart';
import '../theme.dart';
import 'alert_feedback_bar.dart';
import 'brand_icons.dart';
import 'signal_card.dart';
import 'tip_detail_parts.dart';
import 'tip_report_button.dart';

/// Tipsbladet: det som öppnas när föraren trycker på ett tips.
///
/// Ordningen följer förarens frågor, uppifrån och ner:
///
/// 1. **Vad händer och var?** Rubrik i klarspråk, platsen och avståndet.
/// 2. **Hur bråttom?** Avgången, när det slutar, när det började.
/// 3. **Är det värt att köra dit?** Styrkan, ersättningen och de viktigaste
///    skälen. Resten av skälen ligger bakom "Visa alla skäl".
/// 4. **Vad gör jag nu?** "Kör dit" och "Spara" ligger fast i nederkanten,
///    där tummen når. "Hur gick det?" och "Rapportera" står direkt efter
///    beslutet, inte före det.
/// 5. **Mer om tipset.** Alternativ trafik, meddelandets text, källa och tid.
///
/// Särfall: ett meddelande som inte är ett tips ("Övrigt") och en väghändelse
/// får ingen styrka och ingen "värt att köra"-del. Ett avslutat tips säger
/// tydligt att det är slut och ber inte föraren köra.
///
/// Bladet läser tipset och gör inga egna anrop utöver återkopplingen och
/// rapporteringen (som sköter sig själva). Favorit, öppna sidan och stäng
/// kommer in som funktioner från skärmen.
class TipSheetBody extends StatefulWidget {
  const TipSheetBody({
    super.key,
    required this.alert,
    required this.api,
    this.scrollController,
    this.distanceKm,
    this.onToggleFavorite,
    this.onOpenSourcePage,
    this.onClose,
    this.now,
  });

  final Map<String, dynamic> alert;
  final ApiClient api;

  /// Från DraggableScrollableSheet: samma rullning flyttar och scrollar bladet.
  final ScrollController? scrollController;

  /// Km från föraren, om positionen finns.
  final double? distanceKm;

  /// `null` = backend kan inte spara favoriter: ingen Spara-knapp alls.
  /// Funktionen skriver resultatet i tipset (`is_favorite`); knappen läser
  /// det när svaret kommit, så ett misslyckat sparande backar tillbaka.
  final Future<void> Function(bool favorite)? onToggleFavorite;

  /// Öppnar trafikbolagets egen sida. `null` = tipset har ingen sida.
  final VoidCallback? onOpenSourcePage;

  /// Stäng bladet. Utan den stänger krysset närmaste rutt.
  final VoidCallback? onClose;

  /// Klockan, för tester. Annars den riktiga.
  final DateTime? now;

  @override
  State<TipSheetBody> createState() => _TipSheetBodyState();
}

class _TipSheetBodyState extends State<TipSheetBody> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // "Slutar om 40 min" ska stämma medan föraren tittar.
    _timer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  /// Föraren kör mot tipset: 🚕 till backend, och frågan "hur gick det?"
  /// en halvtimme senare (follow_up.dart). Ingenting av det syns nu.
  void _drivingTo(Map<String, dynamic> alert) {
    unawaited(FollowUps.remember(alert));
    unawaited(
      widget.api.submitAlertFeedback(
        alert['id'].toString(),
        false,
        verdict: 'heading',
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.alert;
    final now = widget.now ?? DateTime.now();
    final ended = isEndedTip(a);
    final minor = isMinorTip(a);
    final road = isRoadTip(a);
    final travel = TravelOptions.of(a);
    final start = DateTime.tryParse(
      a['start_time']?.toString() ?? '',
    )?.toLocal();
    final end = DateTime.tryParse(a['end_time']?.toString() ?? '')?.toLocal();
    // En körning att värdera: inte ett meddelande, inte ett väghinder, inte
    // något som redan är slut.
    final showWorthIt = !ended && !minor && !road;
    final hasId = a['id'] != null;
    final lat = (a['lat'] as num?)?.toDouble();
    final lon = (a['lon'] as num?)?.toDouble();
    // Ett väghinder kör man runt, inte till: där finns bara Spara.
    final canDrive = !road && lat != null && lon != null;
    final canFollow = widget.onToggleFavorite != null;
    final hasActions = canDrive || canFollow;
    final inset = MediaQuery.viewPaddingOf(context).bottom;
    final board = travel?.departure != null;

    return DecoratedBox(
      decoration: const BoxDecoration(
        color: TbColors.foam,
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      child: Column(
        children: [
          Expanded(
            child: SingleChildScrollView(
              controller: widget.scrollController,
              padding: EdgeInsets.fromLTRB(
                20,
                12,
                20,
                hasActions ? 12 : 16 + inset,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Center(
                    child: Container(
                      width: 40,
                      height: 4,
                      margin: const EdgeInsets.only(bottom: 10),
                      decoration: BoxDecoration(
                        color: Colors.grey.shade400,
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                  ),
                  // 1. Vad händer och var?
                  _WhatAndWhere(
                    alert: a,
                    distanceKm: widget.distanceKm,
                    onClose:
                        widget.onClose ?? () => Navigator.maybePop(context),
                  ),
                  // 2. Hur bråttom?
                  const SizedBox(height: 16),
                  if (ended)
                    _EndedBanner(end: end, now: now)
                  else ...[
                    if (travel != null && board)
                      DepartureBoard(travel: travel, showAlternative: false)
                    else if (travel != null)
                      NextDepartureBox(travel: travel),
                    if (travel != null && (start != null || end != null))
                      const SizedBox(height: 10),
                    _Timing(start: start, end: end, now: now, compact: board),
                  ],
                  // 3. Är det värt att köra dit? (eller meddelandet, eller vägen)
                  if (showWorthIt) ...[
                    const SizedBox(height: 16),
                    _WorthItCard(alert: a),
                  ] else if (road || minor) ...[
                    const SizedBox(height: 16),
                    _MessageCard(alert: a, road: road),
                  ],
                  // Efter beslutet: hur gick det, och stämmer det här alls?
                  if (hasId) ...[
                    const SizedBox(height: 20),
                    if (!road)
                      AlertFeedbackBar(
                        api: widget.api,
                        opportunityId: a['id'].toString(),
                      ),
                    TipReportButton(
                      api: widget.api,
                      opportunityId: a['id'].toString(),
                    ),
                  ],
                  // 5. Sammanhang
                  const SizedBox(height: 16),
                  _MoreSection(
                    alert: a,
                    travel: travel,
                    now: now,
                    showSummaryHere: !(road || minor),
                    showCompensation:
                        !showWorthIt && a['compensation_eligible'] == true,
                    onOpenSourcePage: widget.onOpenSourcePage,
                  ),
                  const SizedBox(height: 4),
                  const TipsNotPromisesNote(),
                ],
              ),
            ),
          ),
          if (hasActions)
            _ActionBar(
              alert: a,
              canDrive: canDrive,
              ended: ended,
              distanceKm: widget.distanceKm,
              onToggleFavorite: widget.onToggleFavorite,
              bottomInset: inset,
              onDriving: ended || !hasId || !TaxiTipsConfig.usesDjangoApi
                  ? null
                  : () => _drivingTo(a),
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Rena hjälpare: det som går att testa utan att rita något.

/// Ett meddelande som inte räknas som ett tips ("Övrigt – trafikbolagets
/// meddelande"). Visas, men utan styrka och utan "värt att köra".
bool isMinorTip(Map alert) =>
    alert['minor'] == true || alert['severity_tier']?.toString() == 'ignore';

/// Tips som tagit slut men ligger kvar en stund ("Nyss slut").
bool isEndedTip(Map alert) => alert['is_active'] == false;

bool isRoadTip(Map alert) => categoryOfAlert(alert) == SignalCategory.road;

/// Rubriken: vad som hänt, i klarspråk. Ett meddelande utan egen typ får sin
/// egen rubrik (titeln), för den är det enda som säger vad det gäller.
String tipHeadline(Map alert) {
  final tier = alert['severity_tier']?.toString();
  if (isMinorTip(alert)) {
    return displayTitle(
      title: alert['title']?.toString(),
      mode: alert['mode']?.toString(),
    );
  }
  if (isRoadTip(alert)) {
    final road = roadConditionLabels[roadCondition(alert)];
    if (road != null) return road;
  }
  return severityTierLabels[tier] ?? shortWhat(alert);
}

/// Platsen (hållplats, station, ort). `null` när det bara finns en rubrik att
/// gå på och rubriken redan står överst.
String? tipPlace(Map alert) {
  final stop = alert['stop_name']?.toString() ?? '';
  if (stop.isNotEmpty) return stop;
  final places = ((alert['taxi'] as Map?)?['places'] as List?) ?? const [];
  if (places.isNotEmpty && places.first.toString().isNotEmpty) {
    return places.first.toString();
  }
  if (isMinorTip(alert)) return null;
  return displayTitle(
    title: alert['title']?.toString(),
    mode: alert['mode']?.toString(),
  );
}

/// "Därför"-raderna som hör hemma under "Är det värt det?": utan väntan när
/// avgångstavlan redan visar den, och utan ersättningen när den har en egen ruta.
List<TipFactor> tipFactors(Map alert) {
  var factors = TipFactor.of(alert);
  final travel = TravelOptions.of(alert);
  if (travel?.departure != null && travel?.waitText != null) {
    factors = [
      for (final f in factors)
        if (!f.text.startsWith('Nästa ') &&
            !f.text.startsWith('Sista avgången'))
          f,
    ];
  }
  if (alert['compensation_eligible'] == true) {
    factors = [
      for (final f in factors)
        if (!f.text.startsWith('Resenären kan få taxin betald')) f,
    ];
  }
  return factors;
}

/// "25 min", "1 tim 6 min", "3 d" -- hur långt, så kort som det går.
String _span(int minutes) {
  if (minutes >= 2880) return '${minutes ~/ 1440} d';
  return humanMinutes(minutes);
}

/// Hur länge sedan det började, eller hur länge till: (etikett, värde).
/// "Började" + "för 25 min sedan", "Börjar" + "om 25 min".
(String, String) _startedParts(DateTime start, DateTime now) {
  final secs = now.difference(start).inSeconds;
  if (secs >= 60) return ('Började', 'för ${_span((secs / 60).round())} sedan');
  if (secs <= -60) return ('Börjar', 'om ${_span((-secs / 60).round())}');
  return secs >= 0 ? ('Började', 'nyss') : ('Börjar', 'nu');
}

/// "Väntas" + "sluta om 40 min". "Väntas": sluttiden är trafikbolagets (eller
/// vår gräns), och en störning kan hålla i sig längre.
(String, String) _endsParts(DateTime end, DateTime now) {
  final secs = end.difference(now).inSeconds;
  if (secs < 60) return ('Slutar', 'nu');
  return ('Väntas sluta', 'om ${_span((secs / 60).round())}');
}

/// "Började för 25 min sedan" / "Börjar om 25 min".
String startedPhrase(DateTime start, DateTime now) {
  final (label, value) = _startedParts(start, now);
  return '$label $value';
}

/// "Väntas sluta om 40 min".
String endsPhrase(DateTime end, DateTime now) {
  final (label, value) = _endsParts(end, now);
  return '$label $value';
}

/// "Tog slut för 8 min sedan".
String endedPhrase(DateTime end, DateTime now) {
  final secs = now.difference(end).inSeconds;
  if (secs < 60) return 'Tog slut nyss';
  return 'Tog slut för ${_span((secs / 60).round())} sedan';
}

/// "kl 21:30" i dag, annars datumet med klockslag.
String _clockOrDate(DateTime t, DateTime now) {
  final sameDay =
      t.year == now.year && t.month == now.month && t.day == now.day;
  if (!sameDay) {
    // "i morgon 4 okt · 00:26": liten bokstav, det står efter ett annat ord.
    final text = dateText(t, now: now);
    return text.isEmpty ? text : text[0].toLowerCase() + text.substring(1);
  }
  final h = t.hour.toString().padLeft(2, '0');
  final m = t.minute.toString().padLeft(2, '0');
  return 'kl $h:$m';
}

// ---------------------------------------------------------------------------
// 1. Vad händer och var?

class _WhatAndWhere extends StatelessWidget {
  const _WhatAndWhere({
    required this.alert,
    required this.distanceKm,
    required this.onClose,
  });

  final Map<String, dynamic> alert;
  final double? distanceKm;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final category = categoryOfAlert(alert);
    final ended = isEndedTip(alert);
    final minor = isMinorTip(alert);
    final quiet = ended || minor;
    final tileColor = quiet
        ? TbColors.skiffer
        : strengthColor(strengthOfAlert(alert), category: category);
    final place = tipPlace(alert);
    final county = alert['countyName']?.toString() ?? '';
    final distance = distanceKm == null
        ? ''
        : '${distanceText(distanceKm)} från dig';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: tileColor,
                borderRadius: BorderRadius.circular(
                  category == SignalCategory.road ? 8 : 14,
                ),
              ),
              child: Icon(iconForAlert(alert), color: TbColors.vit, size: 28),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      category.label,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: TbColors.skiffer,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      tipHeadline(alert),
                      style: TextStyle(
                        fontFamily: kDisplayFont,
                        fontSize: 24,
                        fontWeight: FontWeight.w700,
                        height: 1.15,
                        color: ended ? TbColors.skiffer : TbColors.midnatt,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            // Stäng: 48 x 48. Dra ner bladet fungerar också.
            IconButton(
              onPressed: onClose,
              iconSize: 28,
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              tooltip: 'Stäng',
              icon: const Icon(Icons.close_rounded, color: TbColors.skiffer),
            ),
          ],
        ),
        if (place != null) ...[
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.only(top: 1),
                child: Icon(
                  Icons.place_rounded,
                  size: 24,
                  color: TbColors.midnatt,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  place,
                  style: const TextStyle(
                    fontFamily: kDisplayFont,
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                    height: 1.2,
                    color: TbColors.midnatt,
                  ),
                ),
              ),
            ],
          ),
        ],
        if (distance.isNotEmpty || county.isNotEmpty) ...[
          const SizedBox(height: 6),
          Wrap(
            spacing: 16,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if (distance.isNotEmpty)
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.near_me_rounded,
                      size: 20,
                      color: TbColors.skiffer,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      distance,
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                        color: TbColors.midnatt,
                      ),
                    ),
                  ],
                ),
              if (county.isNotEmpty)
                Text(
                  countyShort(county),
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: TbColors.skiffer,
                  ),
                ),
            ],
          ),
        ],
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// 2. Hur bråttom?

/// När det började och när det väntas sluta. Stort när det är det enda som
/// säger hur bråttom det är, litet när avgångstavlan redan gör det.
class _Timing extends StatelessWidget {
  const _Timing({
    required this.start,
    required this.end,
    required this.now,
    required this.compact,
  });

  final DateTime? start;
  final DateTime? end;
  final DateTime now;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final startedLater = start != null && start!.isAfter(now);
    final endsAhead = end != null && end!.isAfter(now);
    // Det som avgör bråttomheten står först: en start som ligger framåt, annars
    // slutet, annars när det började.
    final rows = <_TimingRow>[];
    if (startedLater) {
      final (label, value) = _startedParts(start!, now);
      rows.add(
        _TimingRow(
          Icons.schedule_rounded,
          label,
          value,
          _clockOrDate(start!, now),
        ),
      );
    }
    if (endsAhead) {
      final (label, value) = _endsParts(end!, now);
      rows.add(
        _TimingRow(
          Icons.hourglass_bottom_rounded,
          label,
          value,
          _clockOrDate(end!, now),
          soon: end!.difference(now).inMinutes < 15,
        ),
      );
    }
    if (start != null && !startedLater) {
      final (label, value) = _startedParts(start!, now);
      rows.add(
        _TimingRow(
          Icons.history_toggle_off_rounded,
          label,
          value,
          _clockOrDate(start!, now),
        ),
      );
    }
    if (rows.isEmpty) return const SizedBox.shrink();

    // Under avgångstavlan: bara raderna, utan egen ruta -- tavlan bär redan
    // bråttomheten och bladet ska inte bli längre än det måste.
    if (compact) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < rows.length; i++) ...[
              if (i > 0) const SizedBox(height: 6),
              _TimingLine(row: rows[i], big: false, compact: true),
            ],
          ],
        ),
      );
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      decoration: BoxDecoration(
        color: TbColors.vit,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: TbColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < rows.length; i++) ...[
            if (i > 0) const SizedBox(height: 10),
            _TimingLine(row: rows[i], big: i == 0),
          ],
        ],
      ),
    );
  }
}

class _TimingRow {
  const _TimingRow(
    this.icon,
    this.label,
    this.value,
    this.detail, {
    this.soon = false,
  });

  final IconData icon;

  /// "Väntas sluta", "Började".
  final String label;

  /// "om 1 tim 10 min", "för 25 min sedan".
  final String value;

  /// Klockslaget: "kl 21:10".
  final String detail;

  /// Mindre än en kvart kvar: texten får varningsfärg (minuterna bär
  /// betydelsen, färgen understryker bara).
  final bool soon;
}

/// En rad: etiketten och klockslaget litet, själva tiden stor. Den korta
/// formen (under avgångstavlan) är en enda rad med hela meningen.
class _TimingLine extends StatelessWidget {
  const _TimingLine({
    required this.row,
    required this.big,
    this.compact = false,
  });

  final _TimingRow row;
  final bool big;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final color = row.soon ? TbColors.guldDjup : TbColors.midnatt;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(row.icon, size: big ? 28 : 22, color: color),
        const SizedBox(width: 10),
        Expanded(
          child: compact
              ? Text(
                  '${row.label} ${row.value}',
                  style: TextStyle(
                    fontSize: 17,
                    height: 1.2,
                    fontWeight: FontWeight.w700,
                    color: color,
                  ),
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${row.label} · ${row.detail}',
                      style: const TextStyle(
                        fontSize: 14.5,
                        height: 1.2,
                        fontWeight: FontWeight.w600,
                        color: TbColors.skiffer,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      row.value,
                      style: TextStyle(
                        fontFamily: big ? kDisplayFont : null,
                        fontSize: big ? 26 : 18,
                        height: 1.2,
                        fontWeight: FontWeight.w700,
                        color: color,
                      ),
                    ),
                  ],
                ),
        ),
      ],
    );
  }
}

/// Tydligt att tipset är slut. Ingen uppmaning, ingen styrka.
class _EndedBanner extends StatelessWidget {
  const _EndedBanner({required this.end, required this.now});

  final DateTime? end;
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: TbColors.ljusgraDjup,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.history_rounded, size: 26, color: TbColors.skiffer),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Slut. Tipset gäller inte längre.',
                  style: TextStyle(
                    fontFamily: kDisplayFont,
                    fontSize: 20,
                    height: 1.2,
                    fontWeight: FontWeight.w700,
                    color: TbColors.midnatt,
                  ),
                ),
                if (end != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    '${endedPhrase(end!, now)} · ${_clockOrDate(end!, now)}',
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: TbColors.skiffer,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 3. Är det värt att köra dit?

/// Styrkan, ersättningen och de viktigaste skälen. Ordet är en bedömning av
/// läget ("Stark signal"), aldrig ett löfte om kunder.
class _WorthItCard extends StatefulWidget {
  const _WorthItCard({required this.alert});

  final Map<String, dynamic> alert;

  @override
  State<_WorthItCard> createState() => _WorthItCardState();
}

class _WorthItCardState extends State<_WorthItCard> {
  static const _shown = 3;
  bool _all = false;

  @override
  Widget build(BuildContext context) {
    final a = widget.alert;
    final category = categoryOfAlert(a);
    final strength = strengthOfAlert(a);
    final color = strengthColor(strength, category: category);
    final factors = tipFactors(a);
    final visible = _all ? factors : factors.take(_shown).toList();
    final hidden = factors.length - _shown;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TbColors.vit,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: TbColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Är det värt att köra dit?',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: TbColors.skiffer,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Container(
                width: 14,
                height: 14,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              ),
              const SizedBox(width: 8),
              Text(
                '${strengthWord(strength, category: category)} signal',
                style: TextStyle(
                  fontFamily: kDisplayFont,
                  fontSize: 24,
                  fontWeight: FontWeight.w700,
                  color: color,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            strengthMeaning(strength),
            style: const TextStyle(
              fontSize: 16,
              height: 1.3,
              fontWeight: FontWeight.w600,
              color: TbColors.midnatt,
            ),
          ),
          // Ersättningen är ett starkt argument: resenären kan få taxin
          // betald. Därför en egen ruta före skälen, inte en rad bland dem.
          if (a['compensation_eligible'] == true) ...[
            const SizedBox(height: 12),
            CompensationBox(alert: a),
          ],
          if (factors.isNotEmpty) ...[
            const SizedBox(height: 14),
            FactorList(factors: visible),
            if (hidden > 0)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  style: TextButton.styleFrom(
                    foregroundColor: TbColors.midnatt,
                    minimumSize: const Size(0, 48),
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    textStyle: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  onPressed: () => setState(() => _all = !_all),
                  icon: Icon(
                    _all
                        ? Icons.expand_less_rounded
                        : Icons.expand_more_rounded,
                    size: 22,
                  ),
                  label: Text(_all ? 'Visa färre skäl' : 'Visa alla skäl'),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

/// "Resenären kan få taxin betald upp till 1 500 kr". Grön, med ikon och text:
/// färgen är aldrig ensam bärare.
class CompensationBox extends StatelessWidget {
  const CompensationBox({super.key, required this.alert});

  final Map alert;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: TbColors.live.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TbColors.live.withValues(alpha: 0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.payments_rounded, size: 24, color: TbColors.live),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              compensationSentence(
                alert['compensation_amount_kr'] as num?,
                perPerson: alert['compensation_per_person'] as bool?,
              ),
              style: const TextStyle(
                fontSize: 16.5,
                height: 1.3,
                fontWeight: FontWeight.w700,
                color: TbColors.live,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// I stället för "värt att köra": trafikbolagets meddelande (Övrigt) eller
/// sammanhanget för vägen (väghändelse). Inget om styrka, ingen bedömning.
class _MessageCard extends StatelessWidget {
  const _MessageCard({required this.alert, required this.road});

  final Map<String, dynamic> alert;
  final bool road;

  @override
  Widget build(BuildContext context) {
    final summary = alert['summary']?.toString().trim() ?? '';
    final title = road ? 'Vägen dit' : 'Trafikbolagets meddelande';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TbColors.vit,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: TbColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: TbColors.skiffer,
            ),
          ),
          if (road) ...[
            const SizedBox(height: 8),
            const Text(
              'Räkna med kö, eller välj en annan väg.',
              style: TextStyle(
                fontSize: 17,
                height: 1.3,
                fontWeight: FontWeight.w700,
                color: TbColors.midnatt,
              ),
            ),
          ],
          if (summary.isNotEmpty) ...[
            const SizedBox(height: 8),
            _LongText(summary),
          ] else if (!road) ...[
            const SizedBox(height: 8),
            const Text(
              'Ingen ytterligare beskrivning tillgänglig.',
              style: TextStyle(fontSize: 15, color: TbColors.skiffer),
            ),
          ],
          if (!road) ...[
            const SizedBox(height: 10),
            const Text(
              'Allmänt meddelande. Vi bedömer inte om det är värt att köra dit.',
              style: TextStyle(
                fontSize: 14.5,
                height: 1.3,
                fontWeight: FontWeight.w600,
                color: TbColors.skiffer,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Källans text. Lång text visas till en början kort, med "Visa hela texten":
/// ingenting tas bort, och bladet fylls inte av en stycke myndighetssvenska.
class _LongText extends StatefulWidget {
  const _LongText(this.text);

  final String text;

  @override
  State<_LongText> createState() => _LongTextState();
}

class _LongTextState extends State<_LongText> {
  static const _limit = 220;
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final long = widget.text.length > _limit;
    final shown = long && !_open
        ? '${widget.text.substring(0, _limit).trimRight()}…'
        : widget.text;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          shown,
          style: const TextStyle(
            fontSize: 16,
            height: 1.4,
            fontWeight: FontWeight.w500,
            color: TbColors.ink,
          ),
        ),
        if (long)
          TextButton(
            style: TextButton.styleFrom(
              foregroundColor: TbColors.midnatt,
              minimumSize: const Size(0, 48),
              padding: const EdgeInsets.symmetric(horizontal: 4),
              textStyle: const TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w700,
              ),
            ),
            onPressed: () => setState(() => _open = !_open),
            child: Text(_open ? 'Visa mindre' : 'Visa hela texten'),
          ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// 4. Vad gör jag nu?

/// "Kör dit" och "Spara", fasta i nederkanten där tummen når. Ett avslutat
/// tips får inte "Kör dit" som huvudknapp: navigeringen finns kvar, men tyst.
class _ActionBar extends StatefulWidget {
  const _ActionBar({
    required this.alert,
    required this.canDrive,
    required this.ended,
    required this.distanceKm,
    required this.onToggleFavorite,
    required this.bottomInset,
    this.onDriving,
  });

  final Map<String, dynamic> alert;
  final bool canDrive;
  final bool ended;
  final double? distanceKm;
  final Future<void> Function(bool favorite)? onToggleFavorite;
  final double bottomInset;

  /// Navigeringen öppnades mot tipset. `null` för ett avslutat tips.
  final VoidCallback? onDriving;

  @override
  State<_ActionBar> createState() => _ActionBarState();
}

class _ActionBarState extends State<_ActionBar> {
  late bool _followed = widget.alert['is_favorite'] == true;
  bool _busy = false;

  Future<void> _toggleFollow() async {
    final toggle = widget.onToggleFavorite;
    if (toggle == null || _busy) return;
    final next = !_followed;
    // Syns direkt; svaret (eller ett fel som backar) läses ur tipset nedan.
    setState(() {
      _followed = next;
      _busy = true;
    });
    try {
      await toggle(next);
    } finally {
      if (mounted) {
        setState(() {
          _followed = widget.alert['is_favorite'] == true;
          _busy = false;
        });
      }
    }
  }

  Future<void> _drive() async {
    final lat = (widget.alert['lat'] as num?)?.toDouble();
    final lon = (widget.alert['lon'] as num?)?.toDouble();
    if (lat == null || lon == null) return;
    final ok = await openNavigation(lat, lon);
    if (ok) widget.onDriving?.call();
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Kunde inte öppna navigeringen.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final canFollow = widget.onToggleFavorite != null;
    const height = 60.0;
    final shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(14),
    );
    final distance = widget.distanceKm == null
        ? ''
        : ' · ${distanceText(widget.distanceKm)}';

    final Widget? drive = !widget.canDrive
        ? null
        : widget.ended
        ? OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(64, height),
              shape: shape,
            ),
            icon: const Icon(Icons.navigation_outlined, size: 24),
            label: const FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(
                'Öppna navigering',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
              ),
            ),
            onPressed: _drive,
          )
        : FilledButton.icon(
            style: FilledButton.styleFrom(
              minimumSize: const Size(64, height),
              shape: shape,
            ),
            icon: const Icon(Icons.navigation_rounded, size: 26),
            label: FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(
                'Kör dit$distance',
                style: const TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            onPressed: _drive,
          );

    final Widget? follow = !canFollow
        ? null
        : OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(64, height),
              shape: shape,
              backgroundColor: _followed
                  ? TbColors.guld.withValues(alpha: 0.18)
                  : null,
              side: BorderSide(
                color: _followed ? TbColors.guldDjup : TbColors.line,
                width: 1.5,
              ),
            ),
            icon: Icon(
              _followed ? Icons.star_rounded : Icons.star_outline_rounded,
              size: 26,
              color: _followed ? TbColors.guldDjup : TbColors.midnatt,
            ),
            label: FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(
                _followed ? 'Sparat' : 'Spara',
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            onPressed: _toggleFollow,
          );

    return DecoratedBox(
      decoration: const BoxDecoration(
        color: TbColors.vit,
        border: Border(top: BorderSide(color: TbColors.line)),
        boxShadow: [
          BoxShadow(
            color: Colors.black12,
            blurRadius: 12,
            offset: Offset(0, -2),
          ),
        ],
      ),
      child: Padding(
        padding: EdgeInsets.fromLTRB(20, 10, 20, 10 + widget.bottomInset),
        child: Row(
          children: [
            if (drive != null) Expanded(flex: 3, child: drive),
            if (drive != null && follow != null) const SizedBox(width: 10),
            if (follow != null) Expanded(flex: 2, child: follow),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 5. Mer om tipset

/// Det som inte avgör beslutet men som föraren kan vilja veta: alternativ
/// trafik, meddelandets text, källa och tid. Texten och källraderna är
/// hopfällda.
class _MoreSection extends StatelessWidget {
  const _MoreSection({
    required this.alert,
    required this.travel,
    required this.now,
    required this.showSummaryHere,
    required this.showCompensation,
    required this.onOpenSourcePage,
  });

  final Map<String, dynamic> alert;
  final TravelOptions? travel;
  final DateTime now;

  /// Meddelandets text ligger här, utom när den redan står i egen ruta.
  final bool showSummaryHere;

  /// Ersättningen, när "Är det värt det?" inte visas och den därför inte
  /// har någon annan plats.
  final bool showCompensation;
  final VoidCallback? onOpenSourcePage;

  @override
  Widget build(BuildContext context) {
    final t = travel;
    final ended = isEndedTip(alert);
    final alternative =
        t != null && t.hasAlternative && (t.alternative ?? '').isNotEmpty;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Mer om tipset',
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            color: TbColors.skiffer,
          ),
        ),
        const SizedBox(height: 8),
        if (showCompensation) ...[
          CompensationBox(alert: alert),
          const SizedBox(height: 10),
        ],
        // Avgången hör till "Hur bråttom?" -- utom när tipset är slut, då
        // är den bara sammanhang.
        if (ended && t != null) ...[
          if (t.departure != null)
            DepartureBoard(travel: t, showAlternative: false)
          else
            NextDepartureBox(travel: t),
          const SizedBox(height: 10),
        ],
        if (alternative) ...[
          _AlternativeCard(text: t.alternative!),
          const SizedBox(height: 10),
        ],
        _SourceDetails(
          alert: alert,
          now: now,
          showSummary: showSummaryHere,
          onOpenSourcePage: onOpenSourcePage,
        ),
      ],
    );
  }
}

/// "Ersättningsbussar går": vad resenären gör i stället. Med ordet
/// "Alternativ trafik" först, så att det inte läses som en körning.
class _AlternativeCard extends StatelessWidget {
  const _AlternativeCard({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: TbColors.vit,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: TbColors.line),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          BrandIcons.bus(size: 24, color: TbColors.midnatt),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Alternativ trafik',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: TbColors.skiffer,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  text,
                  style: const TextStyle(
                    fontSize: 16,
                    height: 1.35,
                    fontWeight: FontWeight.w600,
                    color: TbColors.midnatt,
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

/// Hopfälld ruta: källans text, trafikbolagets sida och källa/tid.
class _SourceDetails extends StatefulWidget {
  const _SourceDetails({
    required this.alert,
    required this.now,
    required this.showSummary,
    required this.onOpenSourcePage,
  });

  final Map<String, dynamic> alert;
  final DateTime now;
  final bool showSummary;
  final VoidCallback? onOpenSourcePage;

  @override
  State<_SourceDetails> createState() => _SourceDetailsState();
}

class _SourceDetailsState extends State<_SourceDetails> {
  bool _open = false;

  /// "Tåg", "Buss" ... eller kategorin när färdsättet saknas.
  String _typeLabel() {
    final key = alertFilterMode(widget.alert);
    for (final (k, label) in filterModeOptions) {
      if (k == key) return label;
    }
    return categoryOfAlert(widget.alert).label;
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.alert;
    final summary = a['summary']?.toString().trim() ?? '';
    final start = DateTime.tryParse(
      a['start_time']?.toString() ?? '',
    )?.toLocal();
    final end = DateTime.tryParse(a['end_time']?.toString() ?? '')?.toLocal();
    final county = a['countyName']?.toString() ?? '';
    final confidence = confidenceLabels[a['confidence']?.toString()];
    final ended = isEndedTip(a);
    final text = widget.showSummary
        ? (summary.isNotEmpty
              ? summary
              : 'Ingen ytterligare beskrivning tillgänglig.')
        : null;
    final preview = text ?? 'Källa, tid och länk';

    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: TbColors.vit,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: TbColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () => setState(() => _open = !_open),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 56),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            widget.showSummary
                                ? 'Hela meddelandet och källan'
                                : 'Källa och tid',
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: TbColors.midnatt,
                            ),
                          ),
                          if (!_open) ...[
                            const SizedBox(height: 2),
                            Text(
                              preview,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 14,
                                color: TbColors.skiffer,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                    Icon(
                      _open
                          ? Icons.expand_less_rounded
                          : Icons.expand_more_rounded,
                      size: 28,
                      color: TbColors.skiffer,
                    ),
                  ],
                ),
              ),
            ),
          ),
          if (_open)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (text != null) ...[
                    Text(
                      text,
                      style: const TextStyle(
                        fontSize: 15.5,
                        height: 1.4,
                        fontWeight: FontWeight.w500,
                        color: TbColors.ink,
                      ),
                    ),
                    const SizedBox(height: 10),
                  ],
                  if (widget.onOpenSourcePage != null)
                    TextButton.icon(
                      style: TextButton.styleFrom(
                        foregroundColor: TbColors.midnatt,
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        minimumSize: const Size(0, 48),
                        textStyle: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      onPressed: widget.onOpenSourcePage,
                      icon: const Icon(Icons.open_in_new, size: 18),
                      label: const Text('Trafikbolagets sida'),
                    ),
                  _FactRow('Typ', _typeLabel()),
                  if (county.isNotEmpty) _FactRow('Län', countyShort(county)),
                  if (start != null)
                    _FactRow('Började', dateText(start, now: widget.now)),
                  if (end != null)
                    _FactRow(
                      ended ? 'Tog slut' : 'Slutar',
                      dateText(end, now: widget.now),
                    ),
                  if (confidence != null) _FactRow('Säkerhet', confidence),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _FactRow extends StatelessWidget {
  const _FactRow(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 84,
            child: Text(
              label,
              style: const TextStyle(
                fontSize: 14.5,
                fontWeight: FontWeight.w600,
                color: TbColors.skiffer,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                fontSize: 14.5,
                height: 1.3,
                fontWeight: FontWeight.w600,
                color: TbColors.midnatt,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
