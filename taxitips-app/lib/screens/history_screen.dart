import 'dart:async';

import 'package:flutter/material.dart';

import '../analytics.dart';
import '../api_client.dart';
import '../membership_copy.dart';
import '../net_status.dart';
import '../signal_kinds.dart';
import '../theme.dart';
import '../widgets/signal_card.dart' show StrengthPill, tipLineStation;
import '../widgets/tip_sheet.dart';

/// Hur långt bak historiken kan visa. Servern tar upp till 48 timmar
/// (core/thresholds.HISTORY_MAX_HOURS); tre val räcker för en förare.
const kHistoryHourOptions = [6, 12, 24];

/// Historiken: hur det sett ut i förarens område de senaste timmarna.
///
/// Inte ett flöde att agera på -- en lista att titta i. Nyast först, i en
/// grupp per timme, med avslutade tips inräknade. Varje rad bär tid, ikon och
/// styrka (samma som kartan och listan, lib/signal_kinds.dart), rubrik, plats
/// och om tipset är slut. Ett tryck öppnar tipsbladet; för ett avslutat tips
/// finns där ingen "Kör dit" (tip_sheet.dart, `isEndedTip`).
///
/// Styrkan är den tipset hade medan det pågick (`history_level` från
/// servern). `level` säger Svag för allt som tagit slut, och då hade
/// historiken bara visat Svag.
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({
    super.key,
    required this.api,
    this.lat,
    this.lon,
    this.counties,
    this.municipalities,
    this.areaLabel = '',
    this.initialHours = 24,
    this.onOpenTip,
    this.now,
  });

  final ApiClient api;
  final double? lat;
  final double? lon;
  final List<String>? counties;
  final List<String>? municipalities;

  /// "Skåne", "Stockholm + Uppsala" -- visas under rubriken.
  final String areaLabel;
  final int initialHours;

  /// Öppnar tipsbladet. Utan den öppnar skärmen bladet själv, utan Spara.
  final Future<void> Function(Map<String, dynamic> alert)? onOpenTip;

  /// Klockan, för tester.
  final DateTime? now;

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  late int _hours = kHistoryHourOptions.contains(widget.initialHours)
      ? widget.initialHours
      : 24;
  List<Map<String, dynamic>> _rows = const [];
  Map<String, dynamic>? _features;
  bool _loading = true;
  bool _truncated = false;
  bool _needsArea = false;
  bool _unavailable = false;
  String? _blocked;
  String? _error;
  int _seq = 0;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    final seq = ++_seq;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final body = await widget.api.alertHistory(
        hours: _hours,
        lat: widget.lat,
        lon: widget.lon,
        counties: widget.counties,
        municipalities: widget.municipalities,
      );
      if (!mounted || seq != _seq) return;
      final entitled = body['entitled'] != false;
      setState(() {
        _rows = [
          for (final r in (body['alerts'] as List?) ?? const [])
            if (r is Map) Map<String, dynamic>.from(r),
        ];
        _features = body['features'] is Map
            ? Map<String, dynamic>.from(body['features'] as Map)
            : null;
        _truncated = body['truncated'] == true;
        _needsArea = body['needsArea'] == true;
        _unavailable = body['unavailable'] == true;
        _blocked = entitled
            ? null
            : membershipNotice(
                body['reason']?.toString(),
                serverMessage: body['message']?.toString(),
                fallback:
                    'Historiken visas när telefonen har åtkomst till tips.',
              );
        _loading = false;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      final net = netFailureOf(e);
      setState(() {
        _error = net != null
            ? netMessage(net)
            : 'Kunde inte hämta historiken. Försök igen.';
        _loading = false;
      });
    }
  }

  void _setHours(int hours) {
    if (hours == _hours) return;
    setState(() => _hours = hours);
    unawaited(logAnalyticsEvent('history_window', params: {'hours': hours}));
    unawaited(_load());
  }

  Future<void> _open(Map<String, dynamic> row) async {
    // Bladet läser `level`; i historiken är det styrkan medan tipset pågick.
    final alert = historyAlert(row);
    final open = widget.onOpenTip;
    if (open != null) return open(alert);
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.85,
        minChildSize: 0.35,
        maxChildSize: 0.96,
        snap: true,
        snapSizes: const [0.35, 0.85, 0.96],
        shouldCloseOnMinExtent: true,
        builder: (_, scroll) => TipSheetBody(
          alert: alert,
          api: widget.api,
          scrollController: scroll,
          distanceKm: (alert['distance_km'] as num?)?.toDouble(),
          onClose: () => Navigator.pop(ctx),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final now = widget.now ?? DateTime.now();
    return Scaffold(
      backgroundColor: TbColors.foam,
      appBar: AppBar(
        backgroundColor: TbColors.foam,
        surfaceTintColor: TbColors.foam,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Historik',
              style: TextStyle(fontWeight: FontWeight.w800),
            ),
            if (widget.areaLabel.isNotEmpty)
              Text(
                widget.areaLabel,
                style: TextStyle(
                  fontSize: 13,
                  color: Colors.grey.shade700,
                  fontWeight: FontWeight.w600,
                ),
              ),
          ],
        ),
      ),
      body: RefreshIndicator(
        color: TbColors.taxiDeep,
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: EdgeInsets.fromLTRB(
            16,
            4,
            16,
            32 + MediaQuery.paddingOf(context).bottom,
          ),
          children: [_hourPicker(), const SizedBox(height: 12), ..._body(now)],
        ),
      ),
    );
  }

  Widget _hourPicker() {
    return SizedBox(
      width: double.infinity,
      child: SegmentedButton<int>(
        key: const ValueKey('history_hours'),
        showSelectedIcon: false,
        style: SegmentedButton.styleFrom(
          selectedBackgroundColor: TbColors.taxi,
          selectedForegroundColor: TbColors.ink,
          minimumSize: const Size(0, 48),
          textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        ),
        segments: [
          for (final h in kHistoryHourOptions)
            ButtonSegment(value: h, label: Text('$h tim')),
        ],
        selected: {_hours},
        onSelectionChanged: (s) => _setHours(s.first),
      ),
    );
  }

  List<Widget> _body(DateTime now) {
    if (_loading && _rows.isEmpty) {
      return const [
        Padding(
          padding: EdgeInsets.only(top: 48),
          child: Center(
            child: CircularProgressIndicator(color: TbColors.taxiDeep),
          ),
        ),
      ];
    }
    if (_error != null) {
      return [
        _Message(
          icon: Icons.cloud_off_rounded,
          text: _error!,
          action: 'Försök igen',
          onAction: _load,
        ),
      ];
    }
    if (_unavailable) {
      return const [
        _Message(
          icon: Icons.history_rounded,
          text: 'Historiken finns inte i den här versionen.',
        ),
      ];
    }
    if (_blocked != null) {
      return [_Message(icon: Icons.lock_outline_rounded, text: _blocked!)];
    }
    if (_needsArea) {
      return const [
        _Message(
          icon: Icons.map_outlined,
          text: 'Välj ditt körområde för att se historiken.',
        ),
      ];
    }

    final active = _rows.where((r) => r['is_active'] != false).length;
    final out = <Widget>[
      Text(
        _rows.isEmpty
            ? 'Inga tips de senaste $_hours timmarna.'
            : '${_rows.length} tips de senaste $_hours timmarna · $active pågår',
        style: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w700,
          color: TbColors.ink,
        ),
      ),
    ];
    final locked = _lockedNote();
    if (locked != null) {
      out
        ..add(const SizedBox(height: 10))
        ..add(locked);
    }
    if (_truncated) {
      out
        ..add(const SizedBox(height: 8))
        ..add(
          Text(
            'Visar de ${_rows.length} senaste.',
            style: const TextStyle(fontSize: 14, color: TbColors.skiffer),
          ),
        );
    }

    final since = now.subtract(Duration(hours: _hours));
    for (final group in groupHistoryByHour(_rows, since: since)) {
      out.add(
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 18, 4, 8),
          child: Text(
            group.label(now),
            style: const TextStyle(
              fontFamily: kDisplayFont,
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: TbColors.midnatt,
            ),
          ),
        ),
      );
      for (final row in group.rows) {
        out.add(
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: HistoryRow(alert: row, onTap: () => _open(row)),
          ),
        );
      }
    }
    return out;
  }

  /// "3 tips i Flyg och Färja visas inte." plus vem som sköter medlemskapet.
  /// Neutral text, ingen länk (membership_copy.dart).
  Widget? _lockedNote() {
    final hidden = _features?['hiddenCounts'];
    if (hidden is! Map || hidden.isEmpty) return null;
    var count = 0;
    final labels = <String>[];
    hidden.forEach((key, value) {
      final n = (value as num?)?.toInt() ?? 0;
      if (n <= 0) return;
      count += n;
      final c = signalCategoryFromFeatureKey(key);
      if (c != null) labels.add(c.label);
    });
    if (count == 0) return null;
    final where = labels.isEmpty ? '' : ' i ${labels.join(' och ')}';
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: TbColors.vit,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TbColors.line),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.lock_rounded, size: 20, color: TbColors.skiffer),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '$count tips$where visas inte. '
              '${lockedNoteFor(_features?['plan'])}',
              style: const TextStyle(
                fontSize: 14,
                height: 1.35,
                color: TbColors.skiffer,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Raden som tipsbladet ska läsa: `level` = styrkan medan tipset pågick.
Map<String, dynamic> historyAlert(Map<String, dynamic> row) {
  final level = row['history_level'];
  if (level == null) return row;
  return {
    ...row,
    'level': level,
    'taxi': {...?(row['taxi'] as Map?), 'level': level},
  };
}

/// När tipset blev aktuellt: `history_at`, annars starttiden.
DateTime? historyTime(Map row) => DateTime.tryParse(
  (row['history_at'] ?? row['start_time'])?.toString() ?? '',
)?.toLocal();

/// En timme i historiken, eller (start == null) tipsen som pågick redan
/// innan fönstret började.
class HistoryGroup {
  HistoryGroup(this.start, this.rows);

  final DateTime? start;
  final List<Map<String, dynamic>> rows;

  /// "I dag 9 okt · 14:00–15:00", eller "Började tidigare".
  String label(DateTime now) {
    final s = start;
    if (s == null) return 'Började tidigare';
    final end = (s.hour + 1) % 24;
    return '${dateText(s, now: now)}–${end.toString().padLeft(2, '0')}:00';
  }
}

/// Raderna i en grupp per timme, nyast först. Det som blev aktuellt före
/// [since] (eller saknar tid) hamnar sist, i en egen grupp.
List<HistoryGroup> groupHistoryByHour(
  List<Map<String, dynamic>> rows, {
  required DateTime since,
}) {
  final byHour = <DateTime, List<Map<String, dynamic>>>{};
  final earlier = <Map<String, dynamic>>[];
  for (final row in rows) {
    final t = historyTime(row);
    if (t == null || t.isBefore(since)) {
      earlier.add(row);
      continue;
    }
    final hour = DateTime(t.year, t.month, t.day, t.hour);
    byHour.putIfAbsent(hour, () => []).add(row);
  }
  int newestFirst(Map a, Map b) {
    final ta = historyTime(a);
    final tb = historyTime(b);
    if (ta == null && tb == null) return 0;
    if (ta == null) return 1;
    if (tb == null) return -1;
    return tb.compareTo(ta);
  }

  final hours = byHour.keys.toList()..sort((a, b) => b.compareTo(a));
  return [
    for (final h in hours) HistoryGroup(h, byHour[h]!..sort(newestFirst)),
    if (earlier.isNotEmpty) HistoryGroup(null, earlier..sort(newestFirst)),
  ];
}

/// En rad i historiken: tid, ikon i styrkans färg, styrka, rubrik, plats och
/// om tipset är slut. Hela raden är tryckbar och minst 64 hög.
class HistoryRow extends StatelessWidget {
  const HistoryRow({super.key, required this.alert, this.onTap});

  final Map<String, dynamic> alert;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final shown = historyAlert(alert);
    final category = categoryOfAlert(shown);
    final strength = strengthOfAlert(shown);
    final ended = isEndedTip(shown);
    final minor = isMinorTip(shown);
    final color = ended || minor
        ? TbColors.skiffer
        : strengthColor(strength, category: category);
    final time = historyTime(shown);
    final clock = time == null
        ? ''
        : '${time.hour.toString().padLeft(2, '0')}:'
              '${time.minute.toString().padLeft(2, '0')}';
    // Linje och station ("Buss 725 · Tumba station") när de finns.
    final place = tipLineStation(shown) ?? tipPlace(shown);
    final county = shown['countyName']?.toString() ?? '';
    final where = [
      if (place != null && place.isNotEmpty) place,
      if (county.isNotEmpty) countyShort(county),
    ].join(' · ');

    return Material(
      color: ended ? TbColors.ljusgra : TbColors.vit,
      borderRadius: BorderRadius.circular(14),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 64),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: TbColors.line),
          ),
          padding: const EdgeInsets.fromLTRB(10, 10, 4, 10),
          child: Row(
            children: [
              SizedBox(
                width: 48,
                child: Text(
                  clock,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    color: TbColors.midnatt,
                    fontFeatures: [FontFeature.tabularFigures()],
                  ),
                ),
              ),
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: color,
                  borderRadius: BorderRadius.circular(
                    category == SignalCategory.road ? 8 : 12,
                  ),
                ),
                child: Icon(iconForAlert(shown), color: TbColors.vit, size: 24),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      tipHeadline(shown),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        height: 1.2,
                        color: TbColors.midnatt,
                      ),
                    ),
                    if (where.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        where,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: TbColors.skiffer,
                        ),
                      ),
                    ],
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        if (!minor)
                          StrengthPill(
                            strength: strength,
                            category: category,
                            muted: ended,
                          ),
                        _StatusTag(ended: ended),
                      ],
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: TbColors.skiffer),
            ],
          ),
        ),
      ),
    );
  }
}

/// "Slut" eller "Pågår" -- med ikon, aldrig bara färg.
class _StatusTag extends StatelessWidget {
  const _StatusTag({required this.ended});

  final bool ended;

  @override
  Widget build(BuildContext context) {
    final color = ended ? TbColors.skiffer : TbColors.live;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          ended ? Icons.history_rounded : Icons.circle,
          size: ended ? 16 : 10,
          color: color,
        ),
        const SizedBox(width: 4),
        Text(
          ended ? 'Slut' : 'Pågår',
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w700,
            color: color,
          ),
        ),
      ],
    );
  }
}

class _Message extends StatelessWidget {
  const _Message({
    required this.icon,
    required this.text,
    this.action,
    this.onAction,
  });

  final IconData icon;
  final String text;
  final String? action;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 32),
      child: Column(
        children: [
          Icon(icon, size: 40, color: TbColors.skiffer),
          const SizedBox(height: 12),
          Text(
            text,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 16,
              height: 1.35,
              fontWeight: FontWeight.w600,
              color: TbColors.ink,
            ),
          ),
          if (action != null) ...[
            const SizedBox(height: 12),
            FilledButton(
              onPressed: onAction,
              style: FilledButton.styleFrom(
                backgroundColor: TbColors.taxi,
                foregroundColor: TbColors.ink,
                minimumSize: const Size(0, 48),
              ),
              child: Text(
                action!,
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
