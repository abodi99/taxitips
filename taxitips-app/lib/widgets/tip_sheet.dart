import 'dart:async';

import 'package:flutter/material.dart';

import '../analytics.dart';
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
/// Designat för låg kognitiv belastning i bilen:
///
/// 1. **Snabbknappar överst** (kompakta `TextButton`s som inte tar höjd):
///    Kör dit, Spara, Fick körning, Ingen kund, Rapportera felaktigt tips och Stäng.
/// 2. **Samlat huvudkort med tre tydliga sektioner (avdelade med sektionsbrytare)**:
///    - **Del 1 (Sträcka / Stationer)**: Kategori, avstånd, län, `Station A → Station B`
///      samt eventuell enradig AI-sammanfattning (`brief`).
///    - **Sektionsbrytare 1**
///    - **Del 2 (Status, Avgångstid, Nästa avgång & Tåginfo)**:
///      Status (`INSTÄLLD` / `FÖRSENAD X MIN`), överstruken avgångstid i tydlig
///      smal ruta med hög kontrast, nästa avgång samt tågnamn, tåg-/linjenummer
///      och operatör/huvudman (`Pågatågen · Tåg 1249 · Skånetrafiken`, `SJ`, `Västtrafik` osv.).
///      Bredvid tåget: när det började (`Började för 25 min sedan · kl 19:35`).
///      Ingen sluttid -- trafikbolagens prognos är för opålitlig.
///    - **Sektionsbrytare 2**
///    - **Del 3 (Händelse & Beskrivning)**: Rubrik i klarspråk och källans beskrivning.
/// 3. **Kombinerat kort för Beslutsunderlag & Taxiersättning**:
///    - Styrkebedömning (`Stark signal` / `Medel signal` / `Svag signal`) och skäl
///      (rensade från dubletter).
///    - Neutral, enkel och icke-bindande sektion för taxiersättning med hänvisning
///      till ansvarigt trafikbolag (`SJ`, `Skånetrafiken`, `Västtrafik`, `SL` m.fl.)
///      och berörda parter.
/// 4. **Mer om tipset**: Alternativ trafik, källa och tekniska tidsdetaljer.
class TipSheetBody extends StatefulWidget {
  const TipSheetBody({
    super.key,
    required this.alert,
    required this.api,
    this.scrollController,
    this.distanceKm,
    this.onToggleFavorite,
    this.onOpenSourcePage,
    this.onOpenUrl,
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

  /// Öppnar extern länk (t.ex. trafikbolagets villkorssida).
  final Future<void> Function(String url)? onOpenUrl;

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
    // "Började för 25 min sedan" ska stämma medan föraren tittar.
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
    final showWorthIt = !ended && !minor && !road;
    final hasId = a['id'] != null;
    final lat = (a['lat'] as num?)?.toDouble();
    final lon = (a['lon'] as num?)?.toDouble();
    final canDrive = !road && lat != null && lon != null;
    final inset = MediaQuery.viewPaddingOf(context).bottom;
    final closeSheet = widget.onClose ?? () => Navigator.maybePop(context);

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
              padding: EdgeInsets.fromLTRB(18, 10, 18, 18 + inset),
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
                  // 1. Kompakta åtgärdsknappar längst upp (tar minimalt med plats)
                  _TopActionBar(
                    alert: a,
                    api: widget.api,
                    canDrive: canDrive,
                    ended: ended,
                    road: road,
                    hasId: hasId,
                    distanceKm: widget.distanceKm,
                    onToggleFavorite: widget.onToggleFavorite,
                    onOpenSourcePage: widget.onOpenSourcePage,
                    onClose: closeSheet,
                    onDriving: ended || !hasId || !TaxiTipsConfig.usesDjangoApi
                        ? null
                        : () => _drivingTo(a),
                  ),
                  const SizedBox(height: 10),

                  // 2. Samlat huvudkort:
                  //    Station A → Station B
                  //    --- Sektionsbrytare 1 ---
                  //    Inställd/Status + Sträckad tid + Nästa avgång + Tågnamn/Nummer/Operatör
                  //    --- Sektionsbrytare 2 ---
                  //    Händelse & Beskrivning
                  _UnifiedOverviewAndEventCard(
                    alert: a,
                    travel: travel,
                    distanceKm: widget.distanceKm,
                    start: start,
                    end: end,
                    now: now,
                    ended: ended,
                    minor: minor,
                    road: road,
                  ),

                  // 3. Särskilda omständigheter (natt, väder, stor station) & Riktlinjer vid försening
                  //    Visas BARA om det finns unik info som inte redan nämnts längre upp.
                  if ((showWorthIt && tipFactors(a).isNotEmpty) ||
                      a['compensation_eligible'] == true) ...[
                    const SizedBox(height: 12),
                    _WorthItAndCompensationCard(
                      alert: a,
                      travel: travel,
                      showWorthIt: showWorthIt,
                      onOpenUrl: widget.onOpenUrl,
                    ),
                  ],

                  const SizedBox(height: 10),
                  const TipsNotPromisesNote(),
                ],
              ),
            ),
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
  final labeled = severityTierLabel(tier, alert);
  if (labeled.isNotEmpty) return labeled;
  return shortWhat(alert);
}

/// Platsen (hållplats, station, ort). `null` när det bara finns en rubrik att
/// gå på och rubriken redan står överst.
String? tipPlace(Map alert) {
  final stop = alert['stop_name']?.toString() ?? '';
  if (stop.isNotEmpty) return stop;
  final places = alertPlacesList(alert);
  if (places.isNotEmpty && places.first.isNotEmpty) {
    return places.first;
  }
  if (isMinorTip(alert)) return null;
  return displayTitle(
    title: alert['title']?.toString(),
    mode: alert['mode']?.toString(),
  );
}

/// Särskilda omständigheter (t.ex. natt, rusning, väder, stor station) som
/// inte redan står i avgångsstatusen, beskrivningen eller ersättningsrutan.
/// Allt som upprepar försening, inställd avgång, stopp, väntetid eller
/// ersättning filtreras bort så att varje uppgift bara förekommer en gång.
List<TipFactor> tipFactors(Map alert) {
  final factors = TipFactor.of(alert);
  return [
    for (final f in factors)
      if (!f.text.startsWith('Nästa ') &&
          !f.text.startsWith('Sista avgången') &&
          !f.text.startsWith('Okänt när nästa') &&
          !f.text.startsWith('Försenat ') &&
          !f.text.startsWith('En enstaka avgång') &&
          !f.text.startsWith('Hela linjen står still') &&
          !f.text.startsWith('Ersättningstrafik') &&
          !f.text.startsWith('Trafikbolaget anvisar') &&
          !f.text.startsWith('Oklart läge') &&
          !f.text.startsWith('Resenären kan få taxin betald'))
        f,
  ];
}

/// "25 min", "1 tim 6 min", "3 d" -- hur långt, så kort som det går.
String _span(int minutes) {
  if (minutes >= 2880) return '${minutes ~/ 1440} d';
  return humanMinutes(minutes);
}

/// Hur länge sedan det började, eller hur länge till.
/// "Började för 25 min sedan" / "Börjar om 25 min".
///
/// Ingen "väntas sluta": trafikbolagens sluttider stämmer för sällan för att
/// köra efter.
String startedPhrase(DateTime start, DateTime now) {
  final secs = now.difference(start).inSeconds;
  if (secs >= 60) return 'Började för ${_span((secs / 60).round())} sedan';
  if (secs <= -60) return 'Börjar om ${_span((-secs / 60).round())}';
  return secs >= 0 ? 'Började nyss' : 'Börjar nu';
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
    final text = dateText(t, now: now);
    return text.isEmpty ? text : text[0].toLowerCase() + text.substring(1);
  }
  final h = t.hour.toString().padLeft(2, '0');
  final m = t.minute.toString().padLeft(2, '0');
  return 'kl $h:$m';
}

/// Platserna tipset gäller (stationer/hållplatser), som backend skickar dem
/// under `taxi.places`. Tomt betyder att tipset saknar plats; en tom första
/// sträng räknas som "ingen plats", så att [tipPlace] faller tillbaka på
/// titeln i stället för att visa en tom rad.
List<String> alertPlacesList(Map alert) {
  final raw = (alert['taxi'] as Map?)?['places'];
  if (raw is! List) return const [];
  return [for (final p in raw) p.toString()];
}

/// Trafikbolag/huvudman som nämns i en text, eller null. Korta förkortningar
/// matchas som hela ord så att t.ex. "SL" inte hittas mitt i ett annat ord.
String? _mentionedOperator(String text) {
  const names = [
    'Storstockholms Lokaltrafik',
    'Skånetrafiken',
    'Västtrafik',
    'Östgötatrafiken',
    'Jönköpings Länstrafik',
    'Länstrafiken Kronoberg',
    'Kalmar länstrafik',
    'Blekingetrafiken',
    'Hallandstrafiken',
    'Värmlandstrafik',
    'Länstrafiken Örebro',
    'Dalatrafik',
    'X-trafik',
    'Din Tur',
    'Sörmlandstrafiken',
    'Länstrafiken i Jämtlands län',
    'Länstrafiken i Västerbotten',
    'Länstrafiken Norrbotten',
    'Öresundståg',
    'Pågatågen',
    'Mälartåg',
    'Norrtåg',
  ];
  for (final op in names) {
    if (text.contains(op)) return op;
  }
  for (final op in const ['SJ', 'SL', 'UL', 'VL', 'JLT', 'KLT']) {
    if (RegExp('\\b$op\\b').hasMatch(text)) return op;
  }
  return null;
}

/// Länets regionala kollektivtrafikmyndighet, ur samma underlag som backend
/// (docs/transit-compensation-rules.md). Null när länet inte är känt.
const _countyOperator = <String, String>{
  'Stockholms län': 'SL',
  'Uppsala län': 'UL',
  'Södermanlands län': 'Sörmlandstrafiken',
  'Östergötlands län': 'Östgötatrafiken',
  'Jönköpings län': 'Jönköpings Länstrafik',
  'Kronobergs län': 'Länstrafiken Kronoberg',
  'Kalmar län': 'Kalmar länstrafik',
  'Gotlands län': 'Gotlands kollektivtrafik',
  'Blekinge län': 'Blekingetrafiken',
  'Skåne län': 'Skånetrafiken',
  'Hallands län': 'Hallandstrafiken',
  'Västra Götalands län': 'Västtrafik',
  'Värmlands län': 'Värmlandstrafik',
  'Örebro län': 'Länstrafiken Örebro',
  'Västmanlands län': 'VL',
  'Dalarnas län': 'Dalatrafik',
  'Gävleborgs län': 'X-trafik',
  'Västernorrlands län': 'Din Tur',
  'Jämtlands län': 'Länstrafiken i Jämtlands län',
  'Västerbottens län': 'Länstrafiken i Västerbotten',
  'Norrbottens län': 'Länstrafiken Norrbotten',
};

/// Huvudmannen som står för trafiken i tipset, i den ordning vi kan veta det:
/// ur rubrik/beskrivning, sedan ur länet, annars neutralt.
String _compensationOperator(Map alert) {
  final text = [
    alert['title']?.toString() ?? '',
    alert['summary']?.toString() ?? '',
  ].join(' ');
  return _mentionedOperator(text) ??
      _countyOperator[alert['countyName']?.toString() ?? ''] ??
      'trafikbolaget';
}

/// Linje-/tågnumret ur rubrik eller beskrivning, när källan skriver ut det.
String? _trainNumber(Map alert) {
  final text = [
    alert['title']?.toString() ?? '',
    alert['summary']?.toString() ?? '',
  ].join(' ');
  final match = RegExp(
    r'(?:Tåg|tåg|linje|Linje|spårvagn|Spårvagn|buss|Buss)\s*([0-9]{1,5})',
  ).firstMatch(text);
  return match?.group(1);
}

/// Färdsättets namn på svenska, som fallback när tipset saknar operatör och
/// linjenummer. Bygger på samma översättning som [displayTitle].
String _modeLabel(Map alert) {
  return switch (alertFilterMode(Map<String, dynamic>.from(alert))) {
    'metro' => 'Tunnelbana',
    'tram' => 'Spårvagn',
    'bus' => 'Buss',
    'boat' => 'Båt',
    'flight' => 'Flyg',
    'road' => 'Väg',
    _ => 'Tåg',
  };
}

/// En rutt som kan ritas i huvudkortet: "Station A → Station B".
class _ParsedRoute {
  const _ParsedRoute({required this.from, this.to, this.clock, this.nextHint});

  final String from;
  final String? to;
  final String? clock;
  final String? nextHint;
}

/// Tåg-/linjedetaljer till brickorna i huvudkortet.
class _TrainDetails {
  const _TrainDetails({
    required this.badgeText,
    this.operator,
    this.trainNumber,
  });

  final String badgeText;
  final String? operator;
  final String? trainNumber;
}

/// Riktlinjen bakom ersättningsrutan: vem som ansvarar, och hur det ska läsas.
class _CompensationGuideline {
  const _CompensationGuideline({
    required this.title,
    required this.operatorName,
    required this.affectedParties,
    required this.disclaimer,
    this.url,
    this.linkLabel,
  });

  final String title;
  final String operatorName;
  final String affectedParties;
  final String disclaimer;
  final String? url;
  final String? linkLabel;
}

// ---------------------------------------------------------------------------
// 1. Snabbknappar längst upp (Kompakta TextButtons)

class _TopActionBar extends StatefulWidget {
  const _TopActionBar({
    required this.alert,
    required this.api,
    required this.canDrive,
    required this.ended,
    required this.road,
    required this.hasId,
    required this.distanceKm,
    required this.onToggleFavorite,
    required this.onClose,
    this.onDriving,
    this.onOpenSourcePage,
  });

  final Map<String, dynamic> alert;
  final ApiClient api;
  final bool canDrive;
  final bool ended;
  final bool road;
  final bool hasId;
  final double? distanceKm;
  final Future<void> Function(bool favorite)? onToggleFavorite;
  final VoidCallback onClose;
  final VoidCallback? onDriving;
  final VoidCallback? onOpenSourcePage;

  @override
  State<_TopActionBar> createState() => _TopActionBarState();
}

class _TopActionBarState extends State<_TopActionBar> {
  late bool _followed = widget.alert['is_favorite'] == true;
  bool _busyFollow = false;
  String? _feedbackChoice;
  bool _busyFeedback = false;
  bool _reported = false;

  String get _oppId => widget.alert['id']?.toString() ?? '';

  bool get _showFeedback =>
      widget.hasId && !widget.road && AlertFeedbackBar.shouldShow;

  @override
  void initState() {
    super.initState();
    if (_showFeedback && _oppId.isNotEmpty) {
      FeedbackChoices.get(_oppId).then((v) {
        if (mounted && v != null) setState(() => _feedbackChoice = v);
      });
    }
  }

  Future<void> _toggleFollow() async {
    final toggle = widget.onToggleFavorite;
    if (toggle == null || _busyFollow) return;
    final next = !_followed;
    setState(() {
      _followed = next;
      _busyFollow = true;
    });
    try {
      await toggle(next);
    } finally {
      if (mounted) {
        setState(() {
          _followed = widget.alert['is_favorite'] == true;
          _busyFollow = false;
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

  Future<void> _pickFeedback(String verdict) async {
    if (_busyFeedback || _oppId.isEmpty) return;
    final previous = _feedbackChoice;
    final next = previous == verdict ? null : verdict;
    setState(() {
      _feedbackChoice = next;
      _busyFeedback = true;
    });
    final res = await widget.api.submitAlertFeedback(
      _oppId,
      next == 'fare',
      verdict: next ?? 'none',
    );
    if (!mounted) return;
    if (res['error'] != null) {
      setState(() {
        _feedbackChoice = previous;
        _busyFeedback = false;
      });
      return;
    }
    await FeedbackChoices.set(_oppId, next);
    unawaited(
      logAnalyticsEvent('tip_feedback', params: {'verdict': next ?? 'none'}),
    );
    if (mounted) setState(() => _busyFeedback = false);
  }

  Future<void> _openReportDialog() async {
    if (_reported || _oppId.isEmpty) return;
    final reason = await showTipReportDialog(context);
    if (reason == null || !mounted) return;
    try {
      await widget.api.submitTipReport(opportunityId: _oppId, reason: reason);
      if (!mounted) return;
      setState(() => _reported = true);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Tack — vi granskar tipset.')),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Kunde inte skicka rapporten. Prova igen.'),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final canFollow = widget.onToggleFavorite != null;
    final distance = widget.distanceKm == null
        ? ''
        : ' · ${distanceText(widget.distanceKm)}';
    final isFare = _feedbackChoice == 'fare';
    final isEmpty = _feedbackChoice == 'empty';

    final compactShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(9),
    );

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Wrap(
            spacing: 6,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              // Kör dit / Öppna navigering
              if (widget.canDrive)
                widget.ended
                    ? OutlinedButton.icon(
                        style: OutlinedButton.styleFrom(
                          foregroundColor: TbColors.midnatt,
                          backgroundColor: TbColors.vit,
                          side: const BorderSide(color: TbColors.line),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 11,
                            vertical: 7,
                          ),
                          minimumSize: const Size(0, 36),
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                          shape: compactShape,
                        ),
                        icon: const Icon(Icons.navigation_outlined, size: 16),
                        label: const Text(
                          'Öppna navigering',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        onPressed: _drive,
                      )
                    : FilledButton.icon(
                        style: FilledButton.styleFrom(
                          foregroundColor: TbColors.midnatt,
                          backgroundColor: TbColors.taxi,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 7,
                          ),
                          minimumSize: const Size(0, 36),
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                          shape: compactShape,
                        ),
                        icon: const Icon(Icons.navigation_rounded, size: 16),
                        label: Text(
                          'Kör dit$distance',
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        onPressed: _drive,
                      ),

              // Spara / Sparat
              if (canFollow)
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: _followed
                        ? TbColors.guldDjup
                        : TbColors.midnatt,
                    backgroundColor: _followed
                        ? TbColors.guld.withValues(alpha: 0.18)
                        : TbColors.vit,
                    side: BorderSide(
                      color: _followed ? TbColors.guldDjup : TbColors.line,
                    ),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 7,
                    ),
                    minimumSize: const Size(0, 36),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    shape: compactShape,
                  ),
                  icon: Icon(
                    _followed ? Icons.star_rounded : Icons.star_outline_rounded,
                    size: 16,
                    color: _followed ? TbColors.guldDjup : TbColors.midnatt,
                  ),
                  label: Text(
                    _followed ? 'Sparat' : 'Spara',
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  onPressed: _toggleFollow,
                ),

              // Fick körning & Ingen kund
              if (_showFeedback) ...[
                TextButton.icon(
                  style: TextButton.styleFrom(
                    foregroundColor: isFare ? TbColors.vit : TbColors.midnatt,
                    backgroundColor: isFare ? TbColors.live : TbColors.vit,
                    side: BorderSide(
                      color: isFare ? TbColors.live : TbColors.line,
                    ),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 7,
                    ),
                    minimumSize: const Size(0, 36),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    shape: compactShape,
                  ),
                  icon: Icon(
                    isFare
                        ? Icons.thumb_up_alt_rounded
                        : Icons.thumb_up_alt_outlined,
                    size: 15,
                  ),
                  label: const Text(
                    'Fick körning',
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  onPressed: _busyFeedback ? null : () => _pickFeedback('fare'),
                ),
                TextButton.icon(
                  style: TextButton.styleFrom(
                    foregroundColor: isEmpty ? TbColors.vit : TbColors.skiffer,
                    backgroundColor: isEmpty ? TbColors.skiffer : TbColors.vit,
                    side: BorderSide(
                      color: isEmpty ? TbColors.skiffer : TbColors.line,
                    ),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 7,
                    ),
                    minimumSize: const Size(0, 36),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    shape: compactShape,
                  ),
                  icon: Icon(
                    isEmpty
                        ? Icons.thumb_down_alt_rounded
                        : Icons.thumb_down_alt_outlined,
                    size: 15,
                  ),
                  label: const Text(
                    'Ingen kund',
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  onPressed: _busyFeedback
                      ? null
                      : () => _pickFeedback('empty'),
                ),
              ],

              // Rapportera felaktigt tips
              if (widget.hasId)
                TextButton.icon(
                  style: TextButton.styleFrom(
                    foregroundColor: TbColors.skiffer,
                    backgroundColor: TbColors.vit,
                    side: const BorderSide(color: TbColors.line),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 7,
                    ),
                    minimumSize: const Size(0, 36),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    shape: compactShape,
                  ),
                  icon: Icon(
                    _reported ? Icons.check_rounded : Icons.flag_outlined,
                    size: 15,
                  ),
                  label: Text(
                    _reported ? 'Rapporterat' : 'Rapportera felaktigt tips',
                    style: const TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  onPressed: _reported ? null : _openReportDialog,
                ),

              // Trafikbolagets sida
              if (widget.onOpenSourcePage != null)
                TextButton.icon(
                  style: TextButton.styleFrom(
                    foregroundColor: TbColors.skiffer,
                    backgroundColor: TbColors.vit,
                    side: const BorderSide(color: TbColors.line),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 7,
                    ),
                    minimumSize: const Size(0, 36),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    shape: compactShape,
                  ),
                  icon: const Icon(Icons.open_in_new, size: 15),
                  label: const Text(
                    'Trafikbolagets sida',
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  onPressed: widget.onOpenSourcePage,
                ),
            ],
          ),
        ),
        const SizedBox(width: 4),
        IconButton(
          onPressed: widget.onClose,
          iconSize: 24,
          constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
          tooltip: 'Stäng',
          icon: const Icon(Icons.close_rounded, color: TbColors.skiffer),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// 2. Samlat huvudkort:
//    Del 1: Station A -> Station B
//    Sektionsbrytare 1
//    Del 2: Inställd/Försenad + Sträckad tid + Nästa avgång + Tågnamn/Nummer/Operatör
//    Sektionsbrytare 2
//    Del 3: Händelse & Beskrivning

class _UnifiedOverviewAndEventCard extends StatelessWidget {
  const _UnifiedOverviewAndEventCard({
    required this.alert,
    required this.travel,
    required this.distanceKm,
    required this.start,
    required this.end,
    required this.now,
    required this.ended,
    required this.minor,
    required this.road,
  });

  final Map<String, dynamic> alert;
  final TravelOptions? travel;
  final double? distanceKm;
  final DateTime? start;
  final DateTime? end;
  final DateTime now;
  final bool ended;
  final bool minor;
  final bool road;

  /// "Station A → Station B" ur tipset: starten från platsen/hållplatsen,
  /// målet från den drabbade avgångens destination när den finns.
  _ParsedRoute parseAlertRoute(Map<String, dynamic> alert, TravelOptions? travel) {
    final from = tipPlace(alert) ?? tipHeadline(alert);
    final dep = travel?.departure;
    String? to;
    final destination = dep?.destination;
    if (destination != null && destination.isNotEmpty) {
      to = destination;
    } else {
      final places = alertPlacesList(alert);
      if (places.length > 1 &&
          places[1].isNotEmpty &&
          places[1].toLowerCase() != from.toLowerCase()) {
        to = places[1];
      }
    }
    return _ParsedRoute(
      from: from,
      to: to,
      clock: dep?.clock,
      nextHint: travel?.summary,
    );
  }

  /// Tåg-/linjedetaljerna som en bricka: operatör/huvudman och linjenummer,
  /// med färdsättet som fallback när källan inte namnger något av dem.
  _TrainDetails parseAlertTrainDetails(
    Map<String, dynamic> alert,
    TravelOptions? travel,
  ) {
    final text = [
      alert['title']?.toString() ?? '',
      alert['summary']?.toString() ?? '',
    ].join(' ');
    final operator = _mentionedOperator(text);
    final trainNumber = _trainNumber(alert);
    final trainLabel =
        trainNumber == null ? null : '${_modeLabel(alert)} $trainNumber';
    final parts = <String>[?operator, ?trainLabel];
    final badgeText = parts.isEmpty ? _modeLabel(alert) : parts.join(' · ');
    return _TrainDetails(
      badgeText: badgeText,
      operator: operator,
      trainNumber: trainNumber,
    );
  }

  /// Förseningsminuterna från den drabbade avgången, när källan anger dem.
  int? extractAlertDelayMinutes(Map<String, dynamic> alert, TravelOptions? travel) {
    return travel?.departure?.delayMinutes;
  }

  @override
  Widget build(BuildContext context) {
    final category = categoryOfAlert(alert);
    final quiet = ended || minor;
    final tileColor = quiet
        ? TbColors.skiffer
        : strengthColor(strengthOfAlert(alert), category: category);
    final route = parseAlertRoute(alert, travel);
    final place = tipPlace(alert);
    final county = alert['countyName']?.toString() ?? '';
    final distance = distanceKm == null
        ? ''
        : '${distanceText(distanceKm)} från dig';
    final trainDetails = parseAlertTrainDetails(alert, travel);

    // Status & avgångstider
    final dep = travel?.departure;
    final titleLower = (alert['title']?.toString() ?? '').toLowerCase();
    final summaryLower = (alert['summary']?.toString() ?? '').toLowerCase();
    final shortLower = shortWhat(alert).toLowerCase();
    final tier = alert['severity_tier']?.toString() ?? '';

    final isCancelled =
        dep?.cancelled == true ||
        tier.contains('cancelled') ||
        shortLower.contains('inställ') ||
        titleLower.contains('inställ') ||
        summaryLower.contains('inställ');

    final isStopp =
        tier == 'line_paused' ||
        shortLower.contains('stopp') ||
        titleLower.contains('stopp') ||
        summaryLower.contains('stopp');

    final delayMin = extractAlertDelayMinutes(alert, travel);
    final isDelayed =
        (delayMin != null && delayMin > 0) ||
        tier.contains('delay') ||
        shortLower.contains('försen') ||
        titleLower.contains('försen');

    String statusLabel;
    Color statusBg;
    Color statusFg;
    IconData statusIcon;

    if (isCancelled) {
      statusLabel = 'INSTÄLLD';
      statusBg = TbColors.danger;
      statusFg = TbColors.vit;
      statusIcon = Icons.cancel_rounded;
    } else if (isStopp) {
      statusLabel = 'STOPP I TRAFIKEN';
      statusBg = TbColors.danger;
      statusFg = TbColors.vit;
      statusIcon = Icons.error_rounded;
    } else if (isDelayed) {
      statusLabel = delayMin != null
          ? 'FÖRSENAD ${humanMinutes(delayMin).toUpperCase()}'
          : 'FÖRSENAD';
      statusBg = TbColors.guld;
      statusFg = TbColors.midnatt;
      statusIcon = Icons.schedule_rounded;
    } else if (minor) {
      statusLabel = 'MEDDELANDE';
      statusBg = tileColor;
      statusFg = TbColors.vit;
      statusIcon = iconForAlert(alert);
    } else {
      statusLabel = tipHeadline(alert).toUpperCase();
      statusBg = tileColor;
      statusFg = TbColors.vit;
      statusIcon = iconForAlert(alert);
    }

    // Klockslag som är inställt, försenat eller passerat
    final strikeClock = (dep?.clock != null && dep!.clock.isNotEmpty)
        ? dep.clock
        : route.clock;
    final showStrikeClock =
        strikeClock != null &&
        (isCancelled ||
            isDelayed ||
            (dep?.newClock != null && dep!.newClock!.isNotEmpty) ||
            (dep != null && dep.at.isBefore(now)));

    final nextText = travel?.waitText ?? route.nextHint;
    final showTrain =
        !road &&
        (trainDetails.operator != null ||
            trainDetails.trainNumber != null ||
            category == SignalCategory.transit);
    final showStarted = !ended && start != null;
    final summary = alert['summary']?.toString().trim() ?? '';
    final brief = ended ? null : tipBrief(alert);

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
          // --- DEL 1: KATEGORI, AVSTÅND & STRÄCKA (STATION A -> STATION B) ---
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: tileColor,
                  borderRadius: BorderRadius.circular(
                    category == SignalCategory.road ? 8 : 11,
                  ),
                ),
                child: Icon(iconForAlert(alert), color: TbColors.vit, size: 22),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          category.label,
                          style: const TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700,
                            color: TbColors.skiffer,
                          ),
                        ),
                        if (county.isNotEmpty) ...[
                          const Text(
                            ' · ',
                            style: TextStyle(
                              fontSize: 13.5,
                              fontWeight: FontWeight.w700,
                              color: TbColors.skiffer,
                            ),
                          ),
                          Flexible(
                            child: Text(
                              countyShort(county),
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 13.5,
                                fontWeight: FontWeight.w600,
                                color: TbColors.skiffer,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                    if (distance.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(
                            Icons.near_me_rounded,
                            size: 16,
                            color: TbColors.skiffer,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            distance,
                            style: const TextStyle(
                              fontSize: 14.5,
                              fontWeight: FontWeight.w700,
                              color: TbColors.midnatt,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // Etikett för Sträcka / Stationer
          Row(
            children: [
              Icon(
                route.to != null
                    ? Icons.alt_route_rounded
                    : Icons.place_rounded,
                size: 15,
                color: TbColors.skiffer,
              ),
              const SizedBox(width: 5),
              Text(
                route.to != null ? 'STRÄCKA / STATIONER' : 'STATION / PLATS',
                style: const TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 0.6,
                  color: TbColors.skiffer,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),

          // Station A -> Station B
          if (minor && place == null)
            Text(
              route.from,
              style: const TextStyle(
                fontFamily: kDisplayFont,
                fontSize: 18,
                fontWeight: FontWeight.w700,
                height: 1.2,
                color: TbColors.skiffer,
              ),
            )
          else if (route.to != null)
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Expanded(
                  child: Text(
                    route.from,
                    style: const TextStyle(
                      fontFamily: kDisplayFont,
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                      height: 1.2,
                      color: TbColors.midnatt,
                    ),
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 8),
                  child: ExcludeSemantics(
                    child: Icon(
                      Icons.arrow_forward_rounded,
                      size: 20,
                      color: TbColors.skiffer,
                    ),
                  ),
                ),
                Expanded(
                  child: Text(
                    route.to!,
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
            )
          else
            Text(
              place ?? route.from,
              style: const TextStyle(
                fontFamily: kDisplayFont,
                fontSize: 20,
                fontWeight: FontWeight.w700,
                height: 1.2,
                color: TbColors.midnatt,
              ),
            ),

          // Om tipPlace är en specifik hållplats som inte är identisk med från/till
          if (place != null &&
              route.to != null &&
              place.toLowerCase() != route.from.toLowerCase() &&
              place.toLowerCase() != route.to!.toLowerCase()) ...[
            const SizedBox(height: 6),
            Row(
              children: [
                const Icon(
                  Icons.place_rounded,
                  size: 16,
                  color: TbColors.skiffer,
                ),
                const SizedBox(width: 4),
                Flexible(
                  child: Text(
                    place,
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: TbColors.midnatt,
                    ),
                  ),
                ),
              ],
            ),
          ],

          // Kort sagt: vad, var, när och varför, i en rad (core/briefs.py).
          if (!ended && brief != null) ...[
            const SizedBox(height: 8),
            Text(
              brief,
              key: const ValueKey('tip-brief'),
              style: const TextStyle(
                fontSize: 15.5,
                height: 1.3,
                fontWeight: FontWeight.w600,
                color: TbColors.midnatt,
              ),
            ),
          ],

          // --- SEKTIONSBRYTARE 1 ---
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 14),
            child: Divider(height: 1, thickness: 1, color: TbColors.line),
          ),

          // --- DEL 2: STATUS (INSTÄLLD), STRÄCKAD TID, NÄSTA AVGÅNG & TÅGINFO ---
          if (ended) ...[
            _EndedBanner(end: end, now: now),
            const SizedBox(height: 10),
          ],

          Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              // Status-etikett (t.ex. INSTÄLLD / FÖRSENAD 25 MIN)
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 5,
                ),
                decoration: BoxDecoration(
                  color: statusBg,
                  borderRadius: BorderRadius.circular(7),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(statusIcon, size: 15, color: statusFg),
                    const SizedBox(width: 5),
                    Flexible(
                      child: Text(
                        statusLabel,
                        style: TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 0.5,
                          color: statusFg,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              // Överstruken inställd/passerad tid: större text, smal ruta & tunn linje
              if (showStrikeClock)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 9,
                    vertical: 3.5,
                  ),
                  decoration: BoxDecoration(
                    color: TbColors.danger.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(7),
                    border: Border.all(
                      color: TbColors.danger.withValues(alpha: 0.32),
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        'kl $strikeClock',
                        style: const TextStyle(
                          fontFamily: kDisplayFont,
                          fontSize: 19,
                          height: 1.1,
                          fontWeight: FontWeight.w800,
                          color: TbColors.midnatt,
                          decoration: TextDecoration.lineThrough,
                          decorationColor: TbColors.danger,
                          decorationThickness: 1.3,
                        ),
                      ),
                      if (!isCancelled &&
                          dep?.newClock != null &&
                          dep!.newClock!.isNotEmpty) ...[
                        const SizedBox(width: 6),
                        Text(
                          '→ ${dep.newClock}',
                          style: const TextStyle(
                            fontFamily: kDisplayFont,
                            fontSize: 19,
                            height: 1.1,
                            fontWeight: FontWeight.w800,
                            color: TbColors.midnatt,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),

              // Nästa avgång / väntetid
              if (nextText != null && nextText.isNotEmpty)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 5,
                  ),
                  decoration: BoxDecoration(
                    color: TbColors.foam,
                    borderRadius: BorderRadius.circular(7),
                    border: Border.all(color: TbColors.line),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        travel?.isLastDeparture == true
                            ? Icons.last_page_rounded
                            : Icons.schedule_rounded,
                        size: 15,
                        color: TbColors.midnatt,
                      ),
                      const SizedBox(width: 5),
                      Flexible(
                        child: Text(
                          nextText,
                          style: const TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700,
                            color: TbColors.midnatt,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),

          // Om travel finns utan specifik departure men med summary/nextDepartureAt
          if (!ended &&
              travel != null &&
              travel!.departure == null &&
              nextText == null) ...[
            const SizedBox(height: 10),
            NextDepartureBox(travel: travel!),
          ],

          // Tåget (namn, nummer, operatör) och när det började, som brickor
          // i samma stil. Ingen sluttid: trafikbolagens prognos håller inte.
          if (showTrain || showStarted) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (showTrain)
                  _MetaChip(
                    icon: iconForAlert(alert),
                    text: trainDetails.badgeText,
                  ),
                if (showStarted)
                  _MetaChip(
                    icon: start!.isAfter(now)
                        ? Icons.update_rounded
                        : Icons.history_rounded,
                    text: startedPhrase(start!, now),
                    detail: _clockOrDate(start!, now),
                  ),
              ],
            ),
          ],

          // --- SEKTIONSBRYTARE 2 ---
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 14),
            child: Divider(height: 1, thickness: 1, color: TbColors.line),
          ),

          // --- DEL 3: HÄNDELSE & BESKRIVNING ---
          Row(
            children: [
              const Icon(
                Icons.notes_rounded,
                size: 15,
                color: TbColors.skiffer,
              ),
              const SizedBox(width: 5),
              Expanded(
                child: Text(
                  road
                      ? 'Vägen dit'
                      : minor
                      ? 'Trafikbolagets meddelande'
                      : 'Händelse & beskrivning',
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    color: TbColors.skiffer,
                  ),
                ),
              ),
            ],
          ),
          // Visa bara rubriken här om den inte redan framgår av statusbrickan i Del 2
          if (road ||
              minor ||
              summary.isEmpty ||
              (!isCancelled && !isDelayed && !isStopp)) ...[
            const SizedBox(height: 6),
            Text(
              tipHeadline(alert),
              style: TextStyle(
                fontFamily: kDisplayFont,
                fontSize: 20,
                fontWeight: FontWeight.w700,
                height: 1.2,
                color: ended ? TbColors.skiffer : TbColors.midnatt,
              ),
            ),
          ],
          if (road) ...[
            const SizedBox(height: 6),
            const Text(
              'Räkna med kö, eller välj en annan väg.',
              style: TextStyle(
                fontSize: 16,
                height: 1.3,
                fontWeight: FontWeight.w700,
                color: TbColors.midnatt,
              ),
            ),
          ],
          if (summary.isNotEmpty) ...[
            const SizedBox(height: 6),
            _LongText(summary),
          ] else if (!road) ...[
            const SizedBox(height: 6),
            const Text(
              'Ingen ytterligare beskrivning tillgänglig.',
              style: TextStyle(fontSize: 15, color: TbColors.skiffer),
            ),
          ],
          if (minor && !road) ...[
            const SizedBox(height: 8),
            const Text(
              'Allmänt meddelande. Vi bedömer inte om det är värt att köra dit.',
              style: TextStyle(
                fontSize: 14,
                height: 1.3,
                fontWeight: FontWeight.w600,
                color: TbColors.skiffer,
              ),
            ),
          ],
          if (travel != null &&
              travel!.hasAlternative &&
              (travel!.alternative ?? '').isNotEmpty) ...[
            const SizedBox(height: 10),
            _AlternativeCard(text: travel!.alternative!),
          ],
        ],
      ),
    );
  }
}

/// En liten bricka i huvudkortets stil: ikon, text och ev. en grå detalj
/// ("Började för 25 min sedan · kl 19:35").
class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.icon, required this.text, this.detail});

  final IconData icon;
  final String text;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: TbColors.foam,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: TbColors.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: TbColors.midnatt),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              text,
              style: const TextStyle(
                fontSize: 13.5,
                fontWeight: FontWeight.w700,
                color: TbColors.midnatt,
              ),
            ),
          ),
          if (detail != null && detail!.isNotEmpty) ...[
            const SizedBox(width: 5),
            Text(
              '· $detail',
              style: const TextStyle(
                fontSize: 13.5,
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
                    fontSize: 19,
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
                      fontSize: 14.5,
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
// 3. Särskilda omständigheter (natt, väder, stor station) & Riktlinjer vid försening
//    Ingen upprepning av signalstyrka, försening eller inställd avgång.

class _WorthItAndCompensationCard extends StatefulWidget {
  const _WorthItAndCompensationCard({
    required this.alert,
    required this.travel,
    required this.showWorthIt,
    this.onOpenUrl,
  });

  final Map<String, dynamic> alert;
  final TravelOptions? travel;
  final bool showWorthIt;
  final Future<void> Function(String url)? onOpenUrl;

  @override
  State<_WorthItAndCompensationCard> createState() =>
      _WorthItAndCompensationCardState();
}

class _WorthItAndCompensationCardState
    extends State<_WorthItAndCompensationCard> {
  static const _shown = 3;
  bool _all = false;

  @override
  Widget build(BuildContext context) {
    final a = widget.alert;
    final factors = widget.showWorthIt ? tipFactors(a) : const <TipFactor>[];
    final visible = _all ? factors : factors.take(_shown).toList();
    final hidden = factors.length - _shown;
    final hasCompensation = a['compensation_eligible'] == true;

    if (factors.isEmpty && !hasCompensation) {
      return const SizedBox.shrink();
    }

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
          if (factors.isNotEmpty) ...[
            const Text(
              'Särskilda omständigheter',
              style: TextStyle(
                fontSize: 13.5,
                fontWeight: FontWeight.w800,
                color: TbColors.skiffer,
              ),
            ),
            const SizedBox(height: 8),
            FactorList(factors: visible),
            if (hidden > 0)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  style: TextButton.styleFrom(
                    foregroundColor: TbColors.midnatt,
                    minimumSize: const Size(0, 44),
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    textStyle: const TextStyle(
                      fontFamily: kBodyFont,
                      fontSize: 14.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  onPressed: () => setState(() => _all = !_all),
                  icon: Icon(
                    _all
                        ? Icons.expand_less_rounded
                        : Icons.expand_more_rounded,
                    size: 20,
                  ),
                  label: Text(_all ? 'Visa färre skäl' : 'Visa alla skäl'),
                ),
              ),
          ],
          if (factors.isNotEmpty && hasCompensation)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Divider(height: 1, thickness: 1, color: TbColors.line),
            ),
          if (hasCompensation)
            CompensationBox(
              alert: a,
              travel: widget.travel,
              onOpenUrl: widget.onOpenUrl,
            ),
        ],
      ),
    );
  }
}

/// Neutral, saklig och icke-bindande sektion för taxiersättning med hänvisning
/// till berört trafikbolag (SJ, Skånetrafiken, Västtrafik, SL m.fl.) och
/// berörda parter. Aldrig grön och aldrig ett löfte om ersättning.
///
/// Kort i bilen: rubrik och en mening. Berörd part och villkoren ligger bakom
/// "Läs mer"; länken till bolagets riktlinjer syns alltid.
class CompensationBox extends StatefulWidget {
  const CompensationBox({
    super.key,
    required this.alert,
    this.travel,
    this.onOpenUrl,
  });

  final Map alert;
  final TravelOptions? travel;
  final Future<void> Function(String url)? onOpenUrl;

  @override
  State<CompensationBox> createState() => _CompensationBoxState();
}

class _CompensationBoxState extends State<CompensationBox> {
  bool _open = false;

  /// Riktlinjen för ersättningsrutan. Neutral: vi vet villkoren, inte om just
  /// den här resenären uppfyller dem -- därför ingen grön "ersätts"-färg och
  /// ingen påhittad länk.
  _CompensationGuideline compensationGuidelineForAlert(
    Map alert,
    TravelOptions? travel,
  ) {
    final operatorName = _compensationOperator(alert);
    return _CompensationGuideline(
      title: 'Taxiersättning',
      operatorName: operatorName,
      affectedParties: operatorName,
      disclaimer:
          'Beloppet gäller när trafikbolagets villkor är uppfyllda. Vi kan '
          'inte bedöma den enskilda resan.',
      // Villkoren står på huvudmannens egen sida. En felaktig länk vore värre
      // än ingen: därför visas ingen förrän vi har rätt adress per bolag.
      url: null,
      linkLabel: null,
    );
  }

  @override
  Widget build(BuildContext context) {
    final alert = widget.alert;
    final guide = compensationGuidelineForAlert(
      alert,
      widget.travel ?? TravelOptions.of(alert),
    );
    final sentence = compensationSentence(
      alert['compensation_amount_kr'] as num?,
      perPerson: alert['compensation_per_person'] as bool?,
    );
    final onOpenUrl = widget.onOpenUrl;
    final hasLink =
        guide.url != null && guide.linkLabel != null && onOpenUrl != null;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
      decoration: BoxDecoration(
        color: TbColors.foam,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TbColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.policy_outlined,
                size: 18,
                color: TbColors.midnatt,
              ),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  guide.title,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                    color: TbColors.midnatt,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: TbColors.vit,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: TbColors.line),
                ),
                child: Text(
                  guide.operatorName,
                  style: const TextStyle(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w700,
                    color: TbColors.midnatt,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            sentence,
            style: const TextStyle(
              fontSize: 15,
              height: 1.3,
              fontWeight: FontWeight.w700,
              color: TbColors.midnatt,
            ),
          ),
          const SizedBox(height: 4),
          SizedBox(
            width: double.infinity,
            child: Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 8,
              runSpacing: 4,
              children: [
                TextButton.icon(
                  style: TextButton.styleFrom(
                    foregroundColor: TbColors.midnatt,
                    minimumSize: const Size(0, 40),
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    textStyle: const TextStyle(
                      fontFamily: kBodyFont,
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  onPressed: () => setState(() => _open = !_open),
                  icon: Icon(
                    _open
                        ? Icons.expand_less_rounded
                        : Icons.expand_more_rounded,
                    size: 20,
                  ),
                  label: Text(_open ? 'Dölj' : 'Läs mer'),
                ),
                if (hasLink)
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: TbColors.midnatt,
                      backgroundColor: TbColors.vit,
                      side: const BorderSide(color: TbColors.line),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 6,
                      ),
                      minimumSize: const Size(0, 36),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                    onPressed: () => onOpenUrl(guide.url!),
                    icon: const Icon(Icons.open_in_new_rounded, size: 14),
                    label: Text(
                      guide.linkLabel!,
                      style: const TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
              ],
            ),
          ),
          if (_open) ...[
            const SizedBox(height: 6),
            Text(
              'Berörd part: ${guide.affectedParties}',
              style: const TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w700,
                color: TbColors.skiffer,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              guide.disclaimer,
              style: const TextStyle(
                fontSize: 12.5,
                height: 1.35,
                fontWeight: FontWeight.w500,
                color: TbColors.skiffer,
              ),
            ),
            const SizedBox(height: 4),
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
            fontSize: 15.5,
            height: 1.4,
            fontWeight: FontWeight.w500,
            color: TbColors.ink,
          ),
        ),
        if (long)
          TextButton(
            style: TextButton.styleFrom(
              foregroundColor: TbColors.midnatt,
              minimumSize: const Size(0, 44),
              padding: const EdgeInsets.symmetric(horizontal: 4),
              textStyle: const TextStyle(
                fontFamily: kBodyFont,
                fontSize: 14.5,
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
                    fontSize: 14.5,
                    fontWeight: FontWeight.w700,
                    color: TbColors.skiffer,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  text,
                  style: const TextStyle(
                    fontSize: 15.5,
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
