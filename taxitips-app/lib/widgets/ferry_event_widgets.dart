import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../navigation.dart';
import '../severity_labels.dart' show humanMinutes;
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

// --- Färjor ---------------------------------------------------------------
//
// Kartan och listan läser samma rader: `rows` i /api/ferries (maritime/views.py).
// Kortet och bladet visar det en förare behöver för ett underbyggt beslut
// (ägarkrav 2026-10-11): när den lägger till och när folk kommer ut, hur säker
// tiden är, var kajen är och hur långt dit, vilka som kliver av och vad mer som
// händer vid kajen. Inga källor, inga fartygsnummer, ingen fart eller kurs och
// inga passagerarantal. Det servern inte vet visas inte alls.

/// Färjorna för både kartan och listan. Äldre servrar utan `rows`: listan fick
/// ankomsterna och kartan AIS-fartygen -- här blir det deras union, så att
/// listan ändå har allt kartan visar.
List<Map<String, dynamic>> ferryRowsOf(Map<String, dynamic> body) {
  List<Map<String, dynamic>> maps(Object? v) => v is List
      ? [
          for (final e in v)
            if (e is Map) Map<String, dynamic>.from(e),
        ]
      : <Map<String, dynamic>>[];
  if (body['rows'] is List) return maps(body['rows']);
  final arrivals = maps(body['arrivals']);
  final ships = maps(body['ferries']);
  final named = {
    for (final a in arrivals)
      ((a['vessel'] as Map?)?['name'] ?? '').toString().toUpperCase(),
  }..remove('');
  return [
    ...arrivals,
    for (final s in ships)
      if (!named.contains((s['name'] ?? '').toString().toUpperCase())) s,
  ];
}

String _shipName(Object? v) {
  final name = (v ?? '').toString().trim();
  return name.isEmpty || name.toUpperCase().startsWith('MMSI') ? '' : name;
}

/// Fartygets namn, annars linjen. Aldrig ett fartygsnummer.
String ferryName(Map<String, dynamic> f) {
  for (final candidate in [
    _shipName(f['name']),
    _shipName((f['vessel'] as Map?)?['name']),
    (f['route'] ?? '').toString().trim(),
  ]) {
    if (candidate.isNotEmpty) return candidate;
  }
  return 'Färja';
}

/// Kajen där föraren ska stå.
String ferryPort(Map<String, dynamic> f) {
  final terminal = f['terminal'];
  return (f['portName'] ??
          (terminal is Map ? terminal['name'] : null) ??
          f['terminalName'] ??
          '')
      .toString();
}

/// Ungefär hur stor färjan är, i ord ("Stor färja"). Längden visas inte.
String ferrySize(Map<String, dynamic> f) {
  final label = (f['sizeLabel'] ?? '').toString();
  if (label.isNotEmpty) return label;
  final length =
      ((f['vessel'] as Map?)?['lengthM'] as num?) ?? (f['lengthM'] as num?);
  // Samma band som serverns tips (maritime/tips.py SIZE_BANDS).
  if (length != null && length >= 170) return 'Stor färja';
  if (length != null && length >= 130) return 'Medelstor färja';
  if (length != null && length >= 100) return 'Mindre färja';
  final kind = (f['kindLabel'] ?? '').toString();
  if (kind.isEmpty || kind == 'Stort passagerarfartyg') return 'Färja';
  return kind;
}

bool ferryArrived(Map<String, dynamic> f) =>
    f['status'] == 'berthed' || f['arrived'] == true;

/// Var på kartan färjan ritas: fartyget där det är, annars vid kajen.
(double, double)? ferryPoint(Map<String, dynamic> f) {
  final lat = (f['lat'] as num?)?.toDouble();
  final lon = (f['lon'] as num?)?.toDouble();
  if (lat != null && lon != null) return (lat, lon);
  final v = f['vessel'];
  if (v is Map && v['lat'] is num && v['lon'] is num) {
    return ((v['lat'] as num).toDouble(), (v['lon'] as num).toDouble());
  }
  final t = f['terminal'];
  if (t is Map && t['lat'] is num && t['lon'] is num) {
    return ((t['lat'] as num).toDouble(), (t['lon'] as num).toDouble());
  }
  return null;
}

DateTime? _time(Object? iso) =>
    iso == null ? null : DateTime.tryParse(iso.toString())?.toLocal();

/// Fartygets läge är sett och kopplat till turen. `null` på äldre servrar.
bool? ferryConfirmed(Map<String, dynamic> f) =>
    f['confirmed'] is bool ? f['confirmed'] as bool : null;

/// Sorten i ord ("Stor färja", "Öbåt"), annars storleken.
String ferryKind(Map<String, dynamic> f) {
  final kind = (f['kindLabel'] ?? '').toString().trim();
  return kind.isNotEmpty ? kind : ferrySize(f);
}

/// "Lägger till 14:35 · om 25 min", "Lägger till nu", "Vid kaj sedan 14:30".
/// Utan sett fartyg säger en passerad tid bara vad tidtabellen sa.
String ferryEtaText(Map<String, dynamic> f, {DateTime? now}) {
  final iso = (f['expectedAt'] ?? f['eta'])?.toString();
  final at = _time(iso);
  if (ferryArrived(f)) {
    if (at == null) return 'Vid kaj';
    return ferryConfirmed(f) == false
        ? 'Skulle lägga till ${_clock(iso)} enligt tidtabell'
        : 'Vid kaj sedan ${_clock(iso)}';
  }
  if (at == null) return 'På väg in';
  final minutes =
      (f['etaMinutes'] as num?)?.toInt() ??
      at.difference(now ?? DateTime.now()).inMinutes;
  if (minutes <= 0) return 'Lägger till nu';
  return 'Lägger till ${_clock(iso)} · om ${humanMinutes(minutes)}';
}

/// "Från Visby" när det är känt.
String ferryFromText(Map<String, dynamic> f) {
  final from = (f['from'] ?? '').toString().trim();
  return from.isEmpty ? '' : 'Från $from';
}

/// "Visby, avgick 11:15" (tidtabellens avgång), annars bara orten.
String ferryOriginText(Map<String, dynamic> f, {DateTime? now}) {
  final from = (f['departedFrom'] ?? f['from'] ?? '').toString().trim();
  if (from.isEmpty) return '';
  final iso = f['departedAt']?.toString();
  final at = _time(iso);
  if (at == null) return from;
  final verb = at.isAfter(now ?? DateTime.now()) ? 'avgår' : 'avgick';
  return '$from, $verb ${_clock(iso)}';
}

/// "14:10–14:45": när resenärerna kommer ut, om det är känt.
String ferryPickupText(Map<String, dynamic> f) {
  final from = _clock(f['pickupFrom']?.toString());
  final until = _clock(f['pickupUntil']?.toString());
  return from == null || until == null ? '' : '$from–$until';
}

/// "Folk kommer ut 14:45–15:20", eller "Folk kommer ut nu, till 15:20".
String ferryPickupLine(Map<String, dynamic> f, {DateTime? now}) {
  final start = _time(f['pickupFrom']);
  final end = _time(f['pickupUntil']);
  if (start == null || end == null) return '';
  final t = now ?? DateTime.now();
  if (!t.isBefore(end)) return '';
  if (!t.isBefore(start)) {
    return 'Folk kommer ut nu, till ${_clock(f['pickupUntil'].toString())}';
  }
  return 'Folk kommer ut ${ferryPickupText(f)}';
}

/// "12 min sen", "5 min tidig", "I tid". Tom när förseningen inte är känd --
/// en tur utan sett fartyg är inte "i tid", den är okänd.
String ferryDelayText(Map<String, dynamic> f) {
  final delay = (f['delayMinutes'] as num?)?.round();
  if (delay == null) return '';
  if (delay >= 3) return '${humanMinutes(delay)} sen';
  if (delay <= -3) return '${humanMinutes(-delay)} tidig';
  return 'I tid';
}

/// Hur säker tiden är, utan källnamn. [short]: för kortets chip.
String ferryConfidenceText(Map<String, dynamic> f, {bool short = false}) {
  final confirmed = ferryConfirmed(f);
  if (confirmed == null) return '';
  if (!confirmed) return 'Enligt tidtabell';
  if (short) return 'Bekräftad';
  return ferryArrived(f)
      ? 'Bekräftad – fartyget ligger vid kaj'
      : 'Bekräftad – fartyget är på väg in';
}

/// Sorten och vad den betyder för den som hämtar: "Stor färja – många kliver
/// av, ofta med bagage och utan bil."
String ferryKindDetailText(Map<String, dynamic> f) {
  final label = (f['kindLabel'] ?? '').toString().trim();
  final detail = (f['kindDetail'] ?? '').toString().trim();
  if (detail.isEmpty) return label;
  final lower = '${detail[0].toLowerCase()}${detail.substring(1)}';
  return label.isEmpty ? detail : '$label – $lower';
}

/// "1 färja till anländer 14:50" / "2 färjor till anländer, första 14:50".
String ferrySameTerminalText(Map<String, dynamic> f) {
  final soon = f['sameTerminalSoon'];
  if (soon is! Map) return '';
  final count = (soon['count'] as num?)?.toInt() ?? 0;
  if (count <= 0) return '';
  final at = _clock(soon['nextAt']?.toString());
  if (count == 1) {
    return at == null ? '1 färja till anländer' : '1 färja till anländer $at';
  }
  return at == null
      ? '$count färjor till anländer'
      : '$count färjor till anländer, första $at';
}

// Körtiden räknas grovt ur avståndet fågelvägen: vägen är sällan rak (x1,3)
// och snittet i stad och förort ungefär 45 km/h. Den visas alltid som "ca".
const _roadFactor = 1.3;
const _avgKmh = 45.0;

/// Ungefärlig körtid i minuter ur avståndet fågelvägen.
int ferryDriveMinutes(num km) =>
    math.max(1, (km * _roadFactor / _avgKmh * 60).round());

/// "12 km · ca 21 min med bil".
String ferryDistanceText(num? km) {
  if (km == null) return '';
  return '${distanceText(km)} · ca ${humanMinutes(ferryDriveMinutes(km))} med bil';
}

/// Hinner föraren dit? Jämför ungefärlig framkomst med när folk kommer ut.
String ferryReachText(Map<String, dynamic> f, num? km, {DateTime? now}) {
  if (km == null) return '';
  final t = now ?? DateTime.now();
  final there = t.add(Duration(minutes: ferryDriveMinutes(km)));
  final clock =
      '${there.hour.toString().padLeft(2, '0')}:${there.minute.toString().padLeft(2, '0')}';
  final start = _time(f['pickupFrom']);
  final end = _time(f['pickupUntil']);
  if (start == null || end == null) return 'Framme ca $clock';
  if (!there.isAfter(start)) return 'Framme ca $clock – före folk kommer ut';
  if (there.isBefore(end)) return 'Framme ca $clock – medan folk kommer ut';
  return 'Framme ca $clock – efter att de flesta gått';
}

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
          // Flexible: med stor text bryts raden i stället för att spilla
          // över kortets kant.
          Flexible(
            child: Text(
              text,
              style: TextStyle(
                fontSize: 12.5,
                fontWeight: strong ? FontWeight.w800 : FontWeight.w600,
                color: TbColors.ink,
              ),
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

/// En färja i listan: namn och sort, när den lägger till, när folk kommer ut,
/// hur säker tiden är, avstånd och varifrån den kommer. Allt i bladet
/// (showFerrySheet); här bara det som avgör om föraren ska öppna det.
class FerryCard extends StatelessWidget {
  const FerryCard({
    super.key,
    required this.ferry,
    this.onTap,
    this.distanceKm,
    this.now,
  });

  final Map<String, dynamic> ferry;
  final VoidCallback? onTap;

  /// Fågelvägen från föraren till kajen, när appen har en position.
  final double? distanceKm;

  /// För tester; annars nu.
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    final arrived = ferryArrived(ferry);
    final color = ferryColor(arrived ? 'berthed' : ferry['status']?.toString());
    final port = ferryPort(ferry);
    final pickup = ferryPickupLine(ferry, now: now);
    final delay = ferryDelayText(ferry);
    final confidence = ferryConfidenceText(ferry, short: true);
    final origin = ferryOriginText(ferry, now: now);
    final late = ((ferry['delayMinutes'] as num?) ?? 0) >= 3;
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
                  ferryName(ferry),
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: TbColors.ink,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  [
                    ferryKind(ferry),
                    port,
                  ].where((s) => s.isNotEmpty).join(' · '),
                  style: TextStyle(fontSize: 14, color: Colors.grey.shade800),
                ),
                const SizedBox(height: 8),
                Text(
                  ferryEtaText(ferry, now: now),
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    color: arrived ? TbColors.ink : color,
                  ),
                ),
                if (pickup.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Padding(
                        padding: EdgeInsets.only(top: 2),
                        child: Icon(
                          Icons.local_taxi,
                          size: 15,
                          color: TbColors.ink,
                        ),
                      ),
                      const SizedBox(width: 5),
                      Expanded(
                        child: Text(
                          pickup,
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: TbColors.ink,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
                if (delay.isNotEmpty ||
                    confidence.isNotEmpty ||
                    distanceKm != null) ...[
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      if (delay.isNotEmpty)
                        _InfoChip(
                          late ? Icons.hourglass_bottom : Icons.check,
                          delay,
                          strong: late,
                        ),
                      if (confidence.isNotEmpty)
                        _InfoChip(
                          ferryConfirmed(ferry) == true
                              ? Icons.verified_outlined
                              : Icons.event_note_outlined,
                          confidence,
                        ),
                      if (distanceKm != null)
                        _InfoChip(
                          Icons.near_me_outlined,
                          ferryDistanceText(distanceKm),
                        ),
                    ],
                  ),
                ],
                if (origin.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text(
                    'Från $origin',
                    style: TextStyle(
                      fontSize: 13.5,
                      color: Colors.grey.shade800,
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
    // Publikprognos när servern har en, annars arenans storlek (TheSportsDB) -- en
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
    final labelText = Text(
      label,
      style: TextStyle(fontSize: 14, color: Colors.grey.shade700),
    );
    final valueText = Text(
      value,
      style: const TextStyle(
        fontSize: 14,
        fontWeight: FontWeight.w700,
        color: TbColors.ink,
      ),
    );
    // Med stor text: etiketten ovanför värdet, så att ingen av dem bryts
    // en bokstav i taget i en smal kolumn.
    if (MediaQuery.textScalerOf(context).scale(14) > 14 * 1.3) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [labelText, valueText],
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 130, child: labelText),
          Expanded(child: valueText),
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

class _SheetSection extends StatelessWidget {
  const _SheetSection(this.title, this.rows);

  final String title;
  final List<_DetailRow> rows;

  @override
  Widget build(BuildContext context) {
    final shown = rows.where((r) => r.value.isNotEmpty).toList();
    if (shown.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            header: true,
            child: Text(
              title,
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w800,
                letterSpacing: 0.4,
                color: TbColors.skiffer,
              ),
            ),
          ),
          const SizedBox(height: 2),
          ...shown,
        ],
      ),
    );
  }
}

/// [harborLat]/[harborLon]: kajens läge, för "Kör dit". Fartygets egen
/// position är ute på vattnet och går inte att köra till.
/// [distanceKm]: fågelvägen från föraren till kajen, när appen har en position.
///
/// Fyra avsnitt: När, Var, Vilka kliver av, Sammanhang. En rad utan data visas
/// inte, och ett avsnitt utan rader visas inte.
Future<void> showFerrySheet(
  BuildContext context,
  Map<String, dynamic> f, {
  double? harborLat,
  double? harborLon,
  double? distanceKm,
  DateTime? now,
}) {
  final port = ferryPort(f);
  final pickupLine = ferryPickupLine(f, now: now);
  final scheduled = _clock(f['scheduledAt']?.toString());
  final size = ferrySize(f);
  final kind = (f['kindLabel'] ?? '').toString().trim();
  final route = (f['route'] ?? '').toString().trim();
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: TbColors.foam,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (ctx) => _sheet(ctx, [
      Text(
        ferryName(f),
        style: const TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.w800,
          color: TbColors.ink,
        ),
      ),
      const SizedBox(height: 6),
      Text(
        [ferryKind(f), port].where((s) => s.isNotEmpty).join(' · '),
        style: TextStyle(fontSize: 15, color: Colors.grey.shade800),
      ),
      const SizedBox(height: 12),
      ActionRow(lat: harborLat, lon: harborLon, driveLabel: 'Kör dit'),
      _SheetSection('När', [
        _DetailRow('Ankomst', ferryEtaText(f, now: now)),
        _DetailRow(
          'Folk kommer ut',
          pickupLine.replaceFirst('Folk kommer ut ', ''),
        ),
        _DetailRow('Tidtabell', scheduled ?? ''),
        _DetailRow('Försening', ferryDelayText(f)),
        _DetailRow('Hur säkert', ferryConfidenceText(f)),
      ]),
      _SheetSection('Var', [
        _DetailRow('Kaj', port),
        _DetailRow('Avstånd', ferryDistanceText(distanceKm)),
        _DetailRow('Hinner du', ferryReachText(f, distanceKm, now: now)),
      ]),
      _SheetSection('Vilka kliver av', [
        _DetailRow('Sort', ferryKindDetailText(f)),
        _DetailRow('Storlek', size == kind ? '' : size),
        _DetailRow('Kommer från', ferryOriginText(f, now: now)),
        _DetailRow('Rederi', (f['operator'] ?? '').toString().trim()),
        _DetailRow('Linje', route == ferryName(f) ? '' : route),
        _DetailRow('Trafik', f['international'] == true ? 'Utrikes' : ''),
      ]),
      _SheetSection('Sammanhang', [
        _DetailRow('Samma kaj ±30 min', ferrySameTerminalText(f)),
        _DetailRow('Vid kajen', (f['terminalNote'] ?? '').toString().trim()),
      ]),
    ]),
  );
}

Future<void> showEventSheet(
  BuildContext context,
  Map<String, dynamic> e, {
  String previewNote = '',
  bool followed = false,
  ValueChanged<bool>? onToggleFollow,
}) {
  final lat = (e['lat'] as num?)?.toDouble();
  final lon = (e['lon'] as num?)?.toDouble();
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
    this.compact = false,
  });

  final double? lat;
  final double? lon;
  final String driveLabel;
  final bool followed;
  final ValueChanged<bool>? onToggleFollow;

  /// Lägre knappar och mindre text -- tipsets detaljvy, där beslutsfakta
  /// står ovanför och knapparna inte ska dominera.
  final bool compact;

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
    final height = widget.compact ? 46.0 : 56.0;
    final fontSize = widget.compact ? 15.0 : 17.0;
    final iconSize = widget.compact ? 20.0 : 24.0;
    return Row(
      children: [
        if (canDrive)
          Expanded(
            flex: 3,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(minimumSize: Size(64, height)),
              icon: Icon(Icons.navigation_rounded, size: iconSize),
              label: Text(
                widget.driveLabel,
                style: TextStyle(
                  fontSize: fontSize,
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
                minimumSize: Size(64, height),
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
                size: iconSize,
                color: _followed ? TbColors.guldDjup : TbColors.midnatt,
              ),
              label: Text(
                _followed ? 'Följer' : 'Följ',
                style: TextStyle(fontSize: fontSize),
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
