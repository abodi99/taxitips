import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../navigation.dart';
import '../signal_kinds.dart';
import '../theme.dart';
import 'signal_card.dart' show FollowButton;

/// Färjor på väg in och evenemang i förarens område: kort i listan, markörer på
/// kartan och detaljblad. Datan kommer från /api/ferries och /api/events -- se
/// maritime/approach.py och events/api.py i backenden.

const _weekdays = ['mån', 'tis', 'ons', 'tor', 'fre', 'lör', 'sön'];
const _months = [
  'jan',
  'feb',
  'mar',
  'apr',
  'maj',
  'jun',
  'jul',
  'aug',
  'sep',
  'okt',
  'nov',
  'dec',
];

const _weekdaysLong = [
  'måndag',
  'tisdag',
  'onsdag',
  'torsdag',
  'fredag',
  'lördag',
  'söndag',
];
const _monthsLong = [
  'januari',
  'februari',
  'mars',
  'april',
  'maj',
  'juni',
  'juli',
  'augusti',
  'september',
  'oktober',
  'november',
  'december',
];

String _cap(String s) =>
    s.isEmpty ? s : '${s[0].toUpperCase()}${s.substring(1)}';

String weekdayShort(DateTime d) => _weekdays[d.weekday - 1];
String monthShort(DateTime d) => _months[d.month - 1];
String monthLong(DateTime d) => _monthsLong[d.month - 1];

/// "Lördag 20 september".
String dayHeading(DateTime d) =>
    '${_cap(_weekdaysLong[d.weekday - 1])} ${d.day} ${_monthsLong[d.month - 1]}';

/// "20 sep".
String shortDate(DateTime d) => '${d.day} ${_months[d.month - 1]}';

Color ferryColor(String? status) => switch (status) {
  'approaching' => const Color(0xFFE8590C),
  'docking' => const Color(0xFFC92A2A),
  'berthed' => const Color(0xFF6C757D),
  _ => const Color(0xFF1C7ED6),
};

String? _clock(String? iso) {
  final t = iso == null ? null : DateTime.tryParse(iso)?.toLocal();
  if (t == null) return null;
  return '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

String _km(num value) => value < 10
    ? value.toStringAsFixed(1).replaceAll('.', ',')
    : value.round().toString();

/// "Framme ca 19:24 · om 5 min", eller "Vid kaj".
String ferryEtaText(Map<String, dynamic> f) {
  if (f['status'] == 'berthed' || f['arrived'] == true) return 'Vid kaj';
  // relevance.build (pipeline /farjor): expectedAt + hämtningsfönster.
  if (f['expectedAt'] != null || f['pickupFrom'] != null) {
    final eta = _clock(f['expectedAt']?.toString());
    final from = _clock(f['pickupFrom']?.toString());
    final until = _clock(f['pickupUntil']?.toString());
    if (from != null && until != null) {
      return eta == null
          ? 'Hämtning $from–$until'
          : 'Framme ca $eta · hämtning $from–$until';
    }
    if (eta != null) return 'Framme ca $eta';
  }
  final eta = _clock(f['eta']?.toString());
  final minutes = (f['etaMinutes'] as num?)?.toInt();
  if (eta == null) return f['statusLabel']?.toString() ?? '';
  return minutes != null
      ? 'Framme ca $eta · om $minutes min'
      : 'Framme ca $eta';
}

/// True om raden kommer från relevance.build (tidtabell+AIS), inte bara AIS-live.
bool isFerryArrival(Map<String, dynamic> f) =>
    f['kindLabel'] != null || f['headline'] != null;

/// "lör 20 sep · 19:30", "i dag · 19:30", "Pågår nu".
String eventWhenText(Map<String, dynamic> e) {
  if (e['ongoing'] == true) return 'Pågår nu';
  final date = DateTime.tryParse(e['startDate']?.toString() ?? '');
  final time = e['timeKnown'] == false ? null : e['startLocal']?.toString();
  if (date == null) return time ?? '';
  final today = DateTime.now();
  final days = DateTime(
    date.year,
    date.month,
    date.day,
  ).difference(DateTime(today.year, today.month, today.day)).inDays;
  final day = switch (days) {
    0 => 'i dag',
    1 => 'i morgon',
    _ =>
      '${_weekdays[date.weekday - 1]} ${date.day} ${_months[date.month - 1]}',
  };
  return time == null ? day : '$day · $time';
}

/// Pil i fartygets kurs, i lägets färg. Utan kurs: en prick.
class FerryArrow extends StatelessWidget {
  const FerryArrow({
    super.key,
    required this.status,
    this.course,
    this.size = 30,
  });

  final String? status;
  final num? course;
  final double size;

  @override
  Widget build(BuildContext context) {
    final color = ferryColor(status);
    if (course == null) {
      return Center(
        child: Container(
          width: size * 0.55,
          height: size * 0.55,
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
            border: Border.all(color: TbColors.vit, width: 2),
          ),
        ),
      );
    }
    return Transform.rotate(
      angle: course!.toDouble() * math.pi / 180,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Icon(Icons.navigation, size: size + 4, color: TbColors.vit),
          Icon(Icons.navigation, size: size, color: color),
        ],
      ),
    );
  }
}

class _InfoChip extends StatelessWidget {
  const _InfoChip(this.icon, this.text, {this.strong = false});

  final IconData icon;
  final String text;
  final bool strong;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: strong ? TbColors.taxi.withValues(alpha: 0.22) : TbColors.foam,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: TbColors.ink),
          const SizedBox(width: 5),
          Text(
            text,
            style: TextStyle(
              fontSize: 12.5,
              fontWeight: strong ? FontWeight.w800 : FontWeight.w600,
              color: TbColors.ink,
            ),
          ),
        ],
      ),
    );
  }
}

class _CardShell extends StatelessWidget {
  const _CardShell({required this.child, this.onTap, this.accent});

  final Widget child;
  final VoidCallback? onTap;
  final Color? accent;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: TbColors.vit,
      borderRadius: BorderRadius.circular(16),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Container(
          decoration: accent == null
              ? null
              : BoxDecoration(
                  border: Border(left: BorderSide(color: accent!, width: 4)),
                ),
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          child: child,
        ),
      ),
    );
  }
}

/// En färja på väg in, som lägger till eller ligger vid kaj — eller en
/// tidtabellsankomst från relevance (samma som pipeline /farjor).
class FerryCard extends StatelessWidget {
  const FerryCard({super.key, required this.ferry, this.onTap});

  final Map<String, dynamic> ferry;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    if (isFerryArrival(ferry)) return _arrivalCard();
    return _aisCard();
  }

  Widget _arrivalCard() {
    final kind = ferry['kindLabel']?.toString() ?? 'Färja';
    final vessel = ferry['vessel'] as Map?;
    final name =
        vessel?['name']?.toString() ??
        ferry['route']?.toString() ??
        ferry['headline']?.toString() ??
        'Färja';
    final terminal = (ferry['terminal'] as Map?)?['name']?.toString() ?? '';
    final length = (vessel?['lengthM'] as num?)?.toInt();
    final traits =
        (ferry['traits'] as List?)
            ?.map((t) => t.toString())
            .where((t) => t.isNotEmpty)
            .toList() ??
        const [];
    final color = ferry['arrived'] == true
        ? ferryColor('berthed')
        : ferryColor('approaching');
    return _CardShell(
      onTap: onTap,
      accent: color,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.directions_boat_filled, color: color, size: 24),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: TbColors.ink,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  terminal.isEmpty ? kind : '$kind · $terminal',
                  style: TextStyle(fontSize: 14, color: Colors.grey.shade800),
                ),
                if ((ferry['headline']?.toString() ?? '').isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    ferry['headline'].toString(),
                    style: TextStyle(fontSize: 13, color: Colors.grey.shade600),
                  ),
                ],
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    _InfoChip(
                      Icons.schedule,
                      ferryEtaText(ferry),
                      strong: ferry['arrived'] != true,
                    ),
                    if (length != null)
                      _InfoChip(Icons.directions_boat_outlined, '$length m'),
                    for (final t in traits.take(2))
                      _InfoChip(Icons.label_outline, t),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _aisCard() {
    final status = ferry['status']?.toString();
    final color = ferryColor(status);
    final berthed = status == 'berthed';
    final distance = ferry['distanceKm'] as num?;
    final knots = ferry['knots'] as num?;
    final length = (ferry['lengthM'] as num?)?.toInt();
    return _CardShell(
      onTap: onTap,
      accent: color,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.directions_boat_filled, color: color, size: 24),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  ferry['name']?.toString() ?? 'Färja',
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: TbColors.ink,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '${ferry['statusLabel'] ?? ''} ${berthed ? 'i' : 'mot'} ${ferry['terminalName'] ?? ''}',
                  style: TextStyle(fontSize: 14, color: Colors.grey.shade800),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    _InfoChip(
                      Icons.schedule,
                      ferryEtaText(ferry),
                      strong: !berthed,
                    ),
                    if (!berthed && distance != null)
                      _InfoChip(Icons.straighten, '${_km(distance)} km kvar'),
                    if (!berthed && knots != null)
                      _InfoChip(Icons.speed, '${_km(knots)} knop'),
                    if (length != null)
                      _InfoChip(Icons.directions_boat_outlined, '$length m'),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Ett evenemang: vad, var, när det börjar och när publiken går.
class EventCard extends StatelessWidget {
  const EventCard({
    super.key,
    required this.event,
    this.onTap,
    this.showDate = false,
    this.compactTime = false,
    this.followed = false,
    this.onToggleFollow,
  });

  final Map<String, dynamic> event;
  final VoidCallback? onTap;
  // Stjärnan: följ evenemanget (sparas på telefonen, se followed_events.dart).
  final bool followed;
  final ValueChanged<bool>? onToggleFollow;
  // Kalenderruta till vänster -- i listor som inte redan har en datumrubrik.
  final bool showDate;
  // Bara klockslaget i översta raden -- under en datumrubrik.
  final bool compactTime;

  String get _whenText {
    if (!compactTime) return eventWhenText(event);
    if (event['ongoing'] == true) return 'Pågår nu';
    if (event['timeKnown'] == false) return 'Tid ej satt';
    final start = event['startLocal']?.toString();
    return start == null ? '' : 'Kl $start';
  }

  Widget? _dateTile() {
    if (!showDate) return null;
    final date = DateTime.tryParse(event['startDate']?.toString() ?? '');
    if (date == null) return null;
    return Container(
      width: 54,
      padding: const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(
        color: TbColors.midnatt,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        children: [
          Text(
            weekdayShort(date).toUpperCase(),
            style: const TextStyle(
              fontSize: 10.5,
              fontWeight: FontWeight.w800,
              color: TbColors.guld,
            ),
          ),
          Text(
            '${date.day}',
            style: const TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
              color: TbColors.vit,
              height: 1.15,
            ),
          ),
          Text(
            monthShort(date),
            style: const TextStyle(fontSize: 11.5, color: TbColors.vit),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final venue = event['venueName']?.toString() ?? '';
    final city = event['city']?.toString() ?? '';
    final county = event['countyName']?.toString() ?? '';
    final place = [
      venue,
      if (city.isNotEmpty && !venue.contains(city)) city,
      if (county.isNotEmpty && city != county) county,
    ].where((s) => s.isNotEmpty).join(', ');
    final end = event['endLocal']?.toString();
    final leave = event['leaveUntilLocal']?.toString();
    // Publikprognos (PredictHQ) när den finns, annars arenans storlek (TheSportsDB) -- en
    // kapacitet, inte en siffra på hur många som kommer.
    final capacity = (event['venueCapacity'] as num?)?.toInt();
    final attendance = (event['attendanceText']?.toString() ?? '').isNotEmpty
        ? event['attendanceText'].toString()
        : (capacity != null && capacity > 0
              ? 'Arena för ${_thousands(capacity)}'
              : '');
    final distance = event['distanceKm'] as num?;
    final status = event['statusLabel']?.toString() ?? '';
    final ongoing = event['ongoing'] == true;
    final tile = _dateTile();
    final body = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Etikett, avstånd och stjärna på första raden, tiden på en egen rad:
        // på en smal telefon (384 dp) klämdes tiden annars till en bokstav
        // per rad bredvid en lång etikett som "MÄSSA OCH KONFERENS".
        Row(
          children: [
            Expanded(
              child: Align(
                alignment: Alignment.centerLeft,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: TbColors.midnatt,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(iconForEvent(event), size: 14, color: TbColors.guld),
                      const SizedBox(width: 4),
                      Flexible(
                        child: Text(
                          (((event['sportLabel']?.toString() ?? '').isNotEmpty
                                          ? event['sportLabel']
                                          : event['categoryLabel'])
                                      ?.toString() ??
                                  'Evenemang')
                              .toUpperCase(),
                          style: const TextStyle(
                            fontSize: 10.5,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 0.6,
                            color: TbColors.vit,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            if (distance != null)
              Text(
                '${_km(distance)} km',
                style: const TextStyle(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w700,
                  color: TbColors.skiffer,
                ),
              ),
            if (onToggleFollow != null)
              SizedBox(
                width: 40,
                height: 32,
                child: OverflowBox(
                  maxWidth: 48,
                  maxHeight: 48,
                  child: FollowButton(
                    followed: followed,
                    onChanged: onToggleFollow!,
                  ),
                ),
              ),
          ],
        ),
        const SizedBox(height: 6),
        Text(
          _whenText,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w800,
            color: ongoing ? TbColors.live : TbColors.ink,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          event['name']?.toString() ?? '',
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w800,
            color: TbColors.ink,
            height: 1.25,
          ),
        ),
        if (place.isNotEmpty) ...[
          const SizedBox(height: 4),
          Row(
            children: [
              Icon(Icons.place_outlined, size: 15, color: Colors.grey.shade700),
              const SizedBox(width: 4),
              Expanded(
                child: Text(
                  place,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 13.5, color: Colors.grey.shade800),
                ),
              ),
            ],
          ),
        ],
        if (end != null || attendance.isNotEmpty) ...[
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              if (end != null) _InfoChip(Icons.logout, 'Slutar ca $end'),
              if (leave != null)
                _InfoChip(
                  Icons.local_taxi,
                  'Folk går till $leave',
                  strong: true,
                ),
              if (attendance.isNotEmpty)
                _InfoChip(Icons.groups_outlined, attendance),
            ],
          ),
        ],
        if (status.isNotEmpty && event['happening'] == false) ...[
          const SizedBox(height: 6),
          Text(
            status,
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w800,
              color: TbColors.danger,
            ),
          ),
        ],
      ],
    );
    return _CardShell(
      onTap: onTap,
      accent: ongoing ? TbColors.live : TbColors.midnatt,
      child: tile == null
          ? body
          : Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                tile,
                const SizedBox(width: 12),
                Expanded(child: body),
              ],
            ),
    );
  }
}

/// Förhandsvisning av evenemang under utveckling -- se events/api.py.
class PreviewBanner extends StatelessWidget {
  const PreviewBanner({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: TbColors.taxi.withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.visibility_outlined, size: 18, color: TbColors.ink),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                fontSize: 12.5,
                height: 1.35,
                color: TbColors.ink,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    if (value.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 130,
            child: Text(
              label,
              style: TextStyle(fontSize: 14, color: Colors.grey.shade700),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: TbColors.ink,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

Widget _sheet(BuildContext context, List<Widget> children) {
  return SafeArea(
    child: SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Center(
            child: Container(
              width: 44,
              height: 5,
              decoration: BoxDecoration(
                color: Colors.grey.shade400,
                borderRadius: BorderRadius.circular(3),
              ),
            ),
          ),
          const SizedBox(height: 14),
          ...children,
        ],
      ),
    ),
  );
}

/// [harborLat]/[harborLon]: terminalens läge, för "Kör till hamnen". Fartygets
/// egen position är ute på vattnet och går inte att köra till.
Future<void> showFerrySheet(
  BuildContext context,
  Map<String, dynamic> f, {
  String attribution = '',
  double? harborLat,
  double? harborLon,
}) {
  final harbor = ActionRow(
    lat: harborLat,
    lon: harborLon,
    driveLabel: 'Kör till hamnen',
  );
  if (isFerryArrival(f)) {
    final vessel = f['vessel'] as Map?;
    final why =
        (f['why'] as List?)?.map((e) => e.toString()).toList() ?? const [];
    final name =
        vessel?['name']?.toString() ??
        f['route']?.toString() ??
        f['headline']?.toString() ??
        'Färja';
    final terminal = (f['terminal'] as Map?)?['name']?.toString() ?? '';
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: TbColors.foam,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => _sheet(ctx, [
        Text(
          name,
          style: const TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w800,
            color: TbColors.ink,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          [
            if ((f['kindLabel']?.toString() ?? '').isNotEmpty) f['kindLabel'],
            if (terminal.isNotEmpty) terminal,
          ].join(' · '),
          style: TextStyle(fontSize: 15, color: Colors.grey.shade800),
        ),
        if ((f['headline']?.toString() ?? '').isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(
            f['headline'].toString(),
            style: TextStyle(fontSize: 14, color: Colors.grey.shade700),
          ),
        ],
        const SizedBox(height: 12),
        harbor,
        const SizedBox(height: 12),
        _DetailRow('Ankomst', ferryEtaText(f)),
        _DetailRow('Riktning', f['direction']?.toString() ?? ''),
        _DetailRow('Tidpunkt', f['expectedBasis']?.toString() ?? ''),
        _DetailRow(
          'Längd',
          vessel?['lengthM'] == null ? '' : '${vessel!['lengthM']} m',
        ),
        for (final line in why) ...[
          const SizedBox(height: 8),
          Text(
            line,
            style: TextStyle(
              fontSize: 13,
              height: 1.35,
              color: Colors.grey.shade800,
            ),
          ),
        ],
        const SizedBox(height: 12),
        Text(
          'Samma urval som pipeline-sidan /farjor. Passagerarantal saknas i källorna.'
          '${attribution.isEmpty ? '' : ' $attribution'}',
          style: TextStyle(
            fontSize: 12,
            height: 1.4,
            color: Colors.grey.shade700,
          ),
        ),
      ]),
    );
  }

  final age = ((f['ageSeconds'] as num?) ?? 0) ~/ 60;
  final knots = f['knots'] as num?;
  final course = f['course'] as num?;
  final distance = f['distanceKm'] as num?;
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: TbColors.foam,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (ctx) => _sheet(ctx, [
      Row(
        children: [
          SizedBox(
            width: 34,
            height: 34,
            child: FerryArrow(
              status: f['status']?.toString(),
              course: course,
              size: 26,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              f['name']?.toString() ?? 'Färja',
              style: const TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: TbColors.ink,
              ),
            ),
          ),
        ],
      ),
      const SizedBox(height: 6),
      Text(
        '${f['statusLabel'] ?? ''} ${f['status'] == 'berthed' ? 'i' : 'mot'} ${f['terminalName'] ?? ''}',
        style: TextStyle(fontSize: 15, color: Colors.grey.shade800),
      ),
      const SizedBox(height: 12),
      harbor,
      const SizedBox(height: 12),
      _DetailRow(
        'Beräknad ankomst',
        f['status'] == 'berthed' ? 'Ligger vid kaj' : ferryEtaText(f),
      ),
      _DetailRow(
        'Kvar till terminalen',
        distance == null ? '' : '${_km(distance)} km',
      ),
      _DetailRow('Fart', knots == null ? 'saknas' : '${_km(knots)} knop'),
      _DetailRow('Kurs', course == null ? 'saknas' : '${course.round()}°'),
      _DetailRow('Längd', f['lengthM'] == null ? '' : '${f['lengthM']} m'),
      _DetailRow('AIS-destination', f['destination']?.toString() ?? ''),
      _DetailRow('Senaste position', age < 1 ? 'nyss' : 'för $age min sedan'),
      const SizedBox(height: 12),
      Text(
        'Beräknad ankomst = sträcka till terminalen × farledens krokighet / farten. '
        'Fartygets egen ETA i AIS är handinmatad och visas inte som tid.'
        '${attribution.isEmpty ? '' : ' $attribution.'}',
        style: TextStyle(
          fontSize: 12,
          height: 1.4,
          color: Colors.grey.shade700,
        ),
      ),
    ]),
  );
}

Future<void> showEventSheet(
  BuildContext context,
  Map<String, dynamic> e, {
  String attribution = '',
  String previewNote = '',
  bool followed = false,
  ValueChanged<bool>? onToggleFollow,
}) {
  final lat = (e['lat'] as num?)?.toDouble();
  final lon = (e['lon'] as num?)?.toDouble();
  final links = (e['links'] as List?)?.whereType<Map>().toList() ?? const [];
  final url = e['url']?.toString() ?? '';
  final endBasis = e['endBasis']?.toString();
  final endNote = e['endNote']?.toString() ?? '';
  final end = e['endLocal']?.toString();
  final leave = e['leaveUntilLocal']?.toString();
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: TbColors.foam,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (ctx) => _sheet(ctx, [
      if (previewNote.isNotEmpty) ...[
        PreviewBanner(text: previewNote),
        const SizedBox(height: 12),
      ],
      Text(
        (((e['sportLabel']?.toString() ?? '').isNotEmpty
                        ? e['sportLabel']
                        : e['categoryLabel'])
                    ?.toString() ??
                'Evenemang')
            .toUpperCase(),
        style: TextStyle(
          fontSize: 11.5,
          fontWeight: FontWeight.w800,
          letterSpacing: 0.8,
          color: Colors.grey.shade700,
        ),
      ),
      const SizedBox(height: 4),
      Text(
        e['name']?.toString() ?? '',
        style: const TextStyle(
          fontFamily: kDisplayFont,
          fontSize: 22,
          fontWeight: FontWeight.w700,
          color: TbColors.ink,
          height: 1.2,
        ),
      ),
      const SizedBox(height: 12),
      ActionRow(
        lat: lat,
        lon: lon,
        driveLabel: 'Kör dit',
        followed: followed,
        onToggleFollow: onToggleFollow,
      ),
      const SizedBox(height: 12),
      _DetailRow('När', eventWhenText(e)),
      _DetailRow(
        'Var',
        [
          e['venueName'],
          e['address'],
          e['city'],
          e['countyName'],
        ].whereType<String>().where((s) => s.isNotEmpty).toSet().join(', '),
      ),
      _DetailRow('Slutar ca', end ?? 'okänt'),
      _DetailRow(
        'Folk på väg ut',
        leave == null || end == null ? '' : '$end–$leave',
      ),
      _DetailRow(
        'Storlek',
        [
          e['attendanceText'],
          if ((e['venueCapacity'] as num?) != null)
            'arena för ${_thousands((e['venueCapacity'] as num).toInt())} (kapacitet, inte publik)',
        ].whereType<String>().where((s) => s.isNotEmpty).join(' · '),
      ),
      _DetailRow(
        'Avstånd',
        e['distanceKm'] == null ? '' : '${_km(e['distanceKm'] as num)} km',
      ),
      _DetailRow(
        'Status',
        e['happening'] == false ? (e['statusLabel']?.toString() ?? '') : '',
      ),
      if (endBasis != null && endBasis != 'source') ...[
        const SizedBox(height: 6),
        Text(
          endNote.isNotEmpty
              ? endNote
              : 'Sluttiden är uppskattad, inte angiven av arrangören.',
          style: TextStyle(
            fontSize: 12.5,
            height: 1.4,
            color: Colors.grey.shade700,
          ),
        ),
      ],
      const SizedBox(height: 14),
      for (final link
          in links.isNotEmpty
              ? links
              : [
                  if (url.isNotEmpty) {'url': url, 'label': 'källan'},
                ])
        if ((link['url']?.toString() ?? '').isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                style: FilledButton.styleFrom(
                  backgroundColor: TbColors.midnatt,
                  foregroundColor: TbColors.vit,
                ),
                icon: const Icon(Icons.open_in_new, size: 18),
                label: Text('Öppna hos ${link['label'] ?? 'källan'}'),
                onPressed: () => launchUrl(
                  Uri.parse(link['url'].toString()),
                  mode: LaunchMode.externalApplication,
                ),
              ),
            ),
          ),
      if (attribution.isNotEmpty)
        Text(
          attribution,
          style: TextStyle(fontSize: 12, color: Colors.grey.shade700),
        ),
    ]),
  );
}

/// 30000 -> "30 000", som svensk text.
String _thousands(int n) {
  final digits = n.toString();
  final out = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) out.write('\u00a0');
    out.write(digits[i]);
  }
  return out.toString();
}

/// "Kör dit" och "Följ" -- de två saker en förare gör med ett tips, ett
/// evenemang eller en färja. Stora knappar, samma plats i alla detaljvyer.
///
/// "Kör dit" öppnar telefonens egen navigering (navigation.dart). "Följ"
/// byter läge direkt i knappen, så att föraren ser att trycket tog.
class ActionRow extends StatefulWidget {
  const ActionRow({
    super.key,
    this.lat,
    this.lon,
    this.driveLabel = 'Kör dit',
    this.followed = false,
    this.onToggleFollow,
  });

  final double? lat;
  final double? lon;
  final String driveLabel;
  final bool followed;
  final ValueChanged<bool>? onToggleFollow;

  @override
  State<ActionRow> createState() => _ActionRowState();
}

class _ActionRowState extends State<ActionRow> {
  late bool _followed = widget.followed;

  @override
  Widget build(BuildContext context) {
    final canDrive = widget.lat != null && widget.lon != null;
    final canFollow = widget.onToggleFollow != null;
    if (!canDrive && !canFollow) return const SizedBox.shrink();
    return Row(
      children: [
        if (canDrive)
          Expanded(
            flex: 3,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(minimumSize: const Size(64, 56)),
              icon: const Icon(Icons.navigation_rounded),
              label: Text(
                widget.driveLabel,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                ),
              ),
              onPressed: () async {
                final ok = await openNavigation(widget.lat!, widget.lon!);
                if (!ok && context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Kunde inte öppna navigeringen.'),
                    ),
                  );
                }
              },
            ),
          ),
        if (canDrive && canFollow) const SizedBox(width: 10),
        if (canFollow)
          Expanded(
            flex: 2,
            child: OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size(64, 56),
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
                color: _followed ? TbColors.guldDjup : TbColors.midnatt,
              ),
              label: Text(
                _followed ? 'Följer' : 'Följ',
                style: const TextStyle(fontSize: 17),
              ),
              onPressed: () {
                setState(() => _followed = !_followed);
                widget.onToggleFollow!(_followed);
              },
            ),
          ),
      ],
    );
  }
}
