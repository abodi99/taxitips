/// Påhittad exempeldata för demoläget ("Prova appen").
///
/// Allt här är hittepå, skapat för att en tänkt kund ska förstå appen:
/// tågnummer, fartyg och arenor finns inte, och inget bolag utom TaxiTips
/// nämns vid namn. Platserna är riktiga orter så att kartan ser rätt ut.
///
/// Datan byggs mot klockan ([DateTime.now]) varje gång den efterfrågas, så
/// att den alltid ser levande ut: en avgång är alltid "om ett tag", ett
/// evenemang slutar alltid snart. Formen är densamma som backend skickar
/// (se ApiClient._alertFromRow, events/api.py, maritime/relevance.py), så
/// korten och detaljvyerna är de riktiga -- bara datan är påhittad.
///
/// Kategorierna och styrkan definieras i lib/signal_kinds.dart. Den här
/// filen sätter bara fälten (`kind`, `mode`, `level`, `severity_tier`) som
/// den filen läser, och upprepar inga egna trösklar.
library;

import 'dart:math' as math;

/// Hela demomängden vid ett visst ögonblick.
class DemoSnapshot {
  const DemoSnapshot({
    required this.alerts,
    required this.events,
    required this.ferries,
    required this.ferryShips,
    required this.terminals,
    required this.notifications,
    required this.dayCounts,
  });

  /// Tips: tåg och buss, väg och flyg. Färjor och evenemang ligger i egna
  /// listor, som i riktiga flödet.
  final List<Map<String, dynamic>> alerts;
  final List<Map<String, dynamic>> events;
  final List<Map<String, dynamic>> ferries;
  final List<Map<String, dynamic>> ferryShips;
  final List<Map<String, dynamic>> terminals;
  final List<Map<String, dynamic>> notifications;
  final Map<String, int> dayCounts;
}

class DemoData {
  const DemoData._();

  /// Demoförarens "position": Stockholms central. Ingen riktig GPS används.
  static const userLat = 59.3303;
  static const userLon = 18.0586;

  /// Tips som är sparade (stjärnmärkta) från början.
  static const initialFavoriteIds = {'demo-tag-uppsala', 'demo-flyg-arlanda'};

  static const _county = '01';
  static const _countyName = 'Stockholms län';

  static String _iso(DateTime t) => t.toUtc().toIso8601String();
  static String _date(DateTime t) =>
      '${t.year.toString().padLeft(4, '0')}-'
      '${t.month.toString().padLeft(2, '0')}-'
      '${t.day.toString().padLeft(2, '0')}';
  static String _hhmm(DateTime t) {
    final l = t.toLocal();
    return '${l.hour.toString().padLeft(2, '0')}:'
        '${l.minute.toString().padLeft(2, '0')}';
  }

  /// Avrundad till närmaste 5 min: en avgångstid ser aldrig ut som
  /// "19:13:47", och raden "om X min" räknas ändå live mot klockan.
  static DateTime _at(DateTime now, int minutes) {
    final t = now.add(Duration(minutes: minutes));
    final rounded = (t.minute / 5).round() * 5;
    return DateTime(
      t.year,
      t.month,
      t.day,
      t.hour,
    ).add(Duration(minutes: rounded));
  }

  static double _km(double lat1, double lon1, double lat2, double lon2) {
    const r = 6371.0;
    double rad(double d) => d * math.pi / 180;
    final dLat = rad(lat2 - lat1);
    final dLon = rad(lon2 - lon1);
    final a =
        math.pow(math.sin(dLat / 2), 2) +
        math.cos(rad(lat1)) *
            math.cos(rad(lat2)) *
            math.pow(math.sin(dLon / 2), 2);
    return 2 * r * math.asin(math.sqrt(a));
  }

  static double _dist(double lat, double lon) =>
      double.parse(_km(userLat, userLon, lat, lon).toStringAsFixed(1));

  static Map<String, dynamic> _alert({
    required DateTime now,
    required String id,
    required String title,
    required String summary,
    required double lat,
    required double lon,
    required int startedMinutesAgo,
    required String kind,
    required String mode,
    required String tier,
    required String level,
    required int demand,
    required int worthIt,
    required List<String> reasons,
    required String ruleId,
    String confidence = 'medium',
    String? municipality,
    bool hasAlternative = false,
    Map<String, dynamic>? travelOptions,
    bool notifyWorthy = false,
    List<String> places = const [],
  }) => {
    'id': id,
    'title': title,
    'summary': summary,
    'lat': lat,
    'lon': lon,
    'start_time': _iso(now.subtract(Duration(minutes: startedMinutesAgo))),
    'end_time': null,
    'demand_score': demand,
    'worth_it_score': worthIt,
    'reasons': reasons,
    'distance_km': _dist(lat, lon),
    'is_active': true,
    'kind': kind,
    'mode': mode,
    'region': 'sl',
    'county': _county,
    'countyName': _countyName,
    'municipality': municipality,
    'severity_tier': tier,
    'rule_id': ruleId,
    'confidence': confidence,
    'level': level,
    'notify_worthy': notifyWorthy,
    'has_alternative': hasAlternative,
    'compensation_eligible': false,
    'compensation_amount_kr': null,
    'compensation_per_person': null,
    'travel_options': travelOptions,
    'is_favorite': false,
    'purged': false,
    'taxi': {'level': level, 'places': places},
  };

  /// Raden "Nästa avgång ..." i samma form som core/alternatives.py.
  static Map<String, dynamic> _travel({
    required DateTime departure,
    required DateTime now,
    required String head,
    required String headDeparted,
    String? tail,
    bool hasAlternative = false,
    bool isLast = false,
  }) {
    final minutes = departure.difference(now).inMinutes;
    return {
      'summary': ['$head (om $minutes min)', ?tail].join(' · '),
      'summary_head_upcoming': head,
      'summary_head_departed': headDeparted,
      'summary_tail': tail,
      'next_departure_at': _iso(departure),
      'next_departure_minutes': minutes,
      'is_last_departure': isLast,
      'has_alternative': hasAlternative,
      'planner': null,
    };
  }

  static DemoSnapshot build({DateTime? now, Set<String>? favoriteIds}) {
    final n = now ?? DateTime.now();
    final favs = favoriteIds ?? initialFavoriteIds;

    // --- Tips --------------------------------------------------------------

    // 1. Inställt pendeltåg med ersättningsbuss: svag signal, buss finns.
    final nextFromMarsta = _at(n, 34);
    final cancelled = _alert(
      now: n,
      id: 'demo-tag-marsta',
      title: 'Pendeltåg 99412 inställt',
      summary:
          'Avgången från Märsta mot Stockholm är inställd. Nästa tåg går '
          'enligt tidtabell, och ersättningsbuss är insatt.',
      lat: 59.6249,
      lon: 17.8546,
      startedMinutesAgo: 12,
      kind: 'transit',
      mode: 'train',
      tier: 'vehicle_cancelled',
      level: 'low',
      demand: 38,
      worthIt: 34,
      reasons: const [
        'inställd avgång',
        'ersättningsbuss insatt',
        'nästa tåg går om en halvtimme',
      ],
      ruleId: 'train.vehicle_cancelled.replacement',
      confidence: 'high',
      municipality: '0127',
      hasAlternative: true,
      places: const ['Märsta'],
      travelOptions: _travel(
        departure: nextFromMarsta,
        now: n,
        head: 'Nästa avgång ${_hhmm(nextFromMarsta)}',
        headDeparted: 'Nästa tåg har gått (${_hhmm(nextFromMarsta)})',
        tail: 'ersättningsbuss från Märsta station',
        hasAlternative: true,
      ),
    );

    // 2. Hela linjen stoppad, inget alternativ, lång väntan: stark signal.
    final nextFromUppsala = _at(n, 95);
    final paused = _alert(
      now: n,
      id: 'demo-tag-uppsala',
      title: 'Tåg 99207 Uppsala–Stockholm stoppat',
      summary:
          'Trafiken mellan Uppsala och Knivsta står still efter ett '
          'signalfel. Ingen ersättningstrafik är angiven.',
      lat: 59.8586,
      lon: 17.6389,
      startedMinutesAgo: 18,
      kind: 'transit',
      mode: 'train',
      tier: 'line_paused',
      level: 'high',
      demand: 82,
      worthIt: 78,
      reasons: const [
        'hela linjen stoppad',
        'ingen ersättningstrafik angiven',
        'nästa avgång först om över en timme',
        'kväll, många resenärer på väg hem',
      ],
      ruleId: 'train.line_paused',
      confidence: 'high',
      municipality: '0380',
      notifyWorthy: true,
      places: const ['Uppsala centralstation'],
      travelOptions: _travel(
        departure: nextFromUppsala,
        now: n,
        head: 'Nästa avgång ${_hhmm(nextFromUppsala)}',
        headDeparted: 'Nästa tåg har gått (${_hhmm(nextFromUppsala)})',
        tail: 'ingen ersättningstrafik angiven',
      ),
    );

    // 3. Försenat pendeltåg: medelstark.
    final nextFromSodertalje = _at(n, 15);
    final delayed = _alert(
      now: n,
      id: 'demo-tag-sodertalje',
      title: 'Pendeltåg 99688 försenat 25 min',
      summary:
          'Tåget mot Södertälje är försenat på grund av fordonsfel. '
          'Andra avgångar går som vanligt.',
      lat: 59.1955,
      lon: 17.6253,
      startedMinutesAgo: 9,
      kind: 'transit',
      mode: 'train',
      tier: 'line_delayed',
      level: 'medium',
      demand: 55,
      worthIt: 50,
      reasons: const ['försenat 25 min', 'tåg går fortfarande på linjen'],
      ruleId: 'train.line_delayed',
      municipality: '0181',
      places: const ['Södertälje syd'],
      travelOptions: _travel(
        departure: nextFromSodertalje,
        now: n,
        head: 'Nästa avgång ${_hhmm(nextFromSodertalje)}',
        headDeparted: 'Nästa tåg har gått (${_hhmm(nextFromSodertalje)})',
      ),
    );

    // 4. Tunnelbana, medel.
    final metro = _alert(
      now: n,
      id: 'demo-tunnelbana-hjulsta',
      title: 'Tunnelbanan: stopp mot Hjulsta',
      summary:
          'Stopp på sträckan mot Hjulsta. Trafiken går i pendel på en del '
          'av sträckan.',
      lat: 59.3934,
      lon: 17.8847,
      startedMinutesAgo: 7,
      kind: 'transit',
      mode: 'metro',
      tier: 'line_paused',
      level: 'medium',
      demand: 52,
      worthIt: 47,
      reasons: const [
        'stopp på sträckan',
        'pendeltrafik på en del av sträckan',
      ],
      ruleId: 'metro.line_paused',
      municipality: '0180',
      places: const ['Hjulsta'],
    );

    // 5. Flygvåg: många landningar i ett 30-minutersfönster. Kategoriskt,
    // aldrig ett antal passagerare (AGENTS.md: GTFS-beläggning hålls kategorisk).
    final waveStart = _at(n, 20);
    final waveEnd = waveStart.add(const Duration(minutes: 30));
    final wave = _alert(
      now: n,
      id: 'demo-flyg-arlanda',
      title: 'Arlanda: många landningar väntas',
      summary:
          'Flera flyg landar mellan ${_hhmm(waveStart)} och ${_hhmm(waveEnd)}. '
          'Tidigare liknande kvällar har gett köer vid taxihållplatsen.',
      lat: 59.6519,
      lon: 17.9186,
      startedMinutesAgo: 5,
      kind: 'flight',
      mode: 'flight',
      tier: 'arrival_wave',
      level: 'high',
      demand: 76,
      worthIt: 72,
      reasons: [
        'många planerade landningar ${_hhmm(waveStart)}–${_hhmm(waveEnd)}',
        'kvällstid, färre andra sätt att ta sig till stan',
        'starkt tecken, men ingen vet hur många som väntar på taxi',
      ],
      ruleId: 'flight.arrival_wave',
      confidence: 'medium',
      municipality: '0191',
      notifyWorthy: true,
      places: const ['Arlanda flygplats'],
    );

    // 6. Sista ankomsten, svagare.
    final lastArrival = _alert(
      now: n,
      id: 'demo-flyg-sista',
      title: 'Arlanda: sista planet för kvällen',
      summary:
          'Kvällens sista planerade landning är ${_hhmm(_at(n, 70))}. '
          'Efter det är det tunt med annat än taxi.',
      lat: 59.6519,
      lon: 17.9186,
      startedMinutesAgo: 3,
      kind: 'flight',
      mode: 'flight',
      tier: 'last_arrival',
      level: 'medium',
      demand: 54,
      worthIt: 49,
      reasons: const [
        'sista planerade landningen',
        'färre alternativ sent på kvällen',
      ],
      ruleId: 'flight.last_arrival',
      municipality: '0191',
      places: const ['Arlanda flygplats'],
    );

    // 7. Olycka på väg: sammanhang, inget skäl att köra dit.
    final accident = _alert(
      now: n,
      id: 'demo-vag-e4',
      title: 'Olycka på E4 vid Häggvik',
      summary:
          'Trafikolycka på E4 norrut. Räkna med kö, eller välj en annan väg.',
      lat: 59.4360,
      lon: 17.9400,
      startedMinutesAgo: 14,
      kind: 'road',
      mode: 'road',
      tier: 'road_accident_or_closure',
      level: 'low',
      demand: 12,
      worthIt: 10,
      reasons: const [
        'trafikolycka rapporterad',
        'påverkar vägen mellan Stockholm och Arlanda',
      ],
      ruleId: 'road.high.accident',
      confidence: 'high',
      municipality: '0191',
    );

    final alerts = [
      cancelled,
      paused,
      delayed,
      metro,
      wave,
      lastArrival,
      accident,
    ];
    for (final a in alerts) {
      a['is_favorite'] = favs.contains(a['id']);
    }

    // --- Färjor --------------------------------------------------------------

    final expected = _at(n, 25);
    final pickupFrom = expected.add(const Duration(minutes: 10));
    final pickupUntil = expected.add(const Duration(minutes: 45));
    final ferry = <String, dynamic>{
      'id': 'demo-farja-nordlyset',
      'kind': 'ship',
      'kindLabel': 'Stort passagerarfartyg',
      'traits': <String>[],
      'name': 'M/S Nordlyset',
      'vessel': {'name': 'M/S Nordlyset', 'lengthM': 212},
      'lengthM': 212,
      'terminal': {'name': 'Värtahamnen', 'lat': 59.3516, 'lon': 18.1086},
      'terminalName': 'Värtahamnen',
      'from': 'Helsingfors',
      'headline': 'Till Värtahamnen från Helsingfors',
      'direction': 'Kommer in till Värtahamnen',
      'route': 'Helsingfors–Stockholm',
      'status': 'approaching',
      'statusLabel': 'På väg in',
      'expectedAt': _iso(expected),
      'expectedBasis': 'tidtabell och fartygets position',
      'arrived': false,
      'pickupFrom': _iso(pickupFrom),
      'pickupUntil': _iso(pickupUntil),
      'etaMinutes': expected.difference(n).inMinutes,
      'eta': _iso(expected),
      'lat': 59.3412,
      'lon': 18.2304,
      'course': 285,
      'knots': 11.5,
      'distanceKm': _dist(59.3516, 18.1086),
      'why': [
        'Stort passagerarfartyg som kommer in till kaj enligt tidtabellen.',
        'Hämtning ${_hhmm(pickupFrom)}–${_hhmm(pickupUntil)} vid Värtahamnen.',
        'Ett starkt tecken, men hur många som tar taxi går inte att veta.',
      ],
    };
    final terminals = [
      {
        'key': 'vartahamnen',
        'name': 'Värtahamnen',
        'lat': 59.3516,
        'lon': 18.1086,
      },
    ];

    // --- Evenemang -----------------------------------------------------------

    // Ett pågående evenemang som slutar snart: konsert med besökarprognos.
    final concertEnd = _at(n, 35);
    final concertStart = concertEnd.subtract(const Duration(hours: 3));
    final tomorrow = n.add(const Duration(days: 1));
    final d3 = n.add(const Duration(days: 3));
    final d5 = n.add(const Duration(days: 5));
    final d6 = n.add(const Duration(days: 6));
    Map<String, dynamic> event({
      required String id,
      required String name,
      required String category,
      required String categoryLabel,
      String sport = '',
      String sportLabel = '',
      required DateTime start,
      DateTime? end,
      required String venue,
      required String city,
      required double lat,
      required double lon,
      int? attendance,
      String size = 'medel',
      bool ongoing = false,
      String endBasis = 'estimated',
      String endNote = 'Sluttiden är en uppskattning.',
    }) {
      final leaveUntil = end?.add(const Duration(minutes: 45));
      return {
        'id': id,
        'source': 'demo',
        'sources': ['demo'],
        'sourceLabel': 'Demo',
        'name': name,
        'sourceName': name,
        'url': '',
        'links': const [],
        'category': category,
        'categoryLabel': categoryLabel,
        'sport': sport,
        'sportLabel': sportLabel,
        'status': 'scheduled',
        'statusLabel': ongoing ? 'Pågår' : '',
        'happening': ongoing,
        'attendance': attendance,
        'attendanceText': attendance == null
            ? ''
            : '≈ ${_thousands(attendance)} besökare',
        'sizeLevel': size,
        'sizeLabel': size,
        'venueCapacity': null,
        'startDate': _date(start),
        'startAt': _iso(start),
        'startLocal': _hhmm(start),
        'timeKnown': true,
        'endAt': end == null ? null : _iso(end),
        'endLocal': end == null ? null : _hhmm(end),
        'endDate': end == null ? null : _date(end),
        'endBasis': endBasis,
        'endNote': endNote,
        'leaveFrom': end == null ? null : _iso(end),
        'leaveUntil': leaveUntil == null ? null : _iso(leaveUntil),
        'leaveUntilLocal': leaveUntil == null ? null : _hhmm(leaveUntil),
        'ongoing': ongoing,
        'multiDay': false,
        'venueName': venue,
        'address': '',
        'city': city,
        'lat': lat,
        'lon': lon,
        'region': 'sl',
        'county': _county,
        'countyName': _countyName,
        'municipality': null,
        'distanceKm': _dist(lat, lon),
      };
    }

    final events = [
      event(
        id: 'demo:konsert-nordstaden',
        name: 'Sommarkonsert med Lyckoorkestern',
        category: 'konsert',
        categoryLabel: 'Konsert',
        start: concertStart,
        end: concertEnd,
        venue: 'Nordstaden Arena',
        city: 'Solna',
        lat: 59.3727,
        lon: 18.0000,
        attendance: 14000,
        size: 'stor',
        ongoing: true,
      ),
      event(
        id: 'demo:hockey-norra',
        name: 'Ishockey: Norrhamn mot Söderstad',
        category: 'sport',
        categoryLabel: 'Sport',
        sport: 'ishockey',
        sportLabel: 'Ishockey',
        start: DateTime(tomorrow.year, tomorrow.month, tomorrow.day, 19),
        end: DateTime(tomorrow.year, tomorrow.month, tomorrow.day, 21, 30),
        venue: 'Södra Isarenan',
        city: 'Stockholm',
        lat: 59.2934,
        lon: 18.0837,
        attendance: 8500,
        size: 'stor',
      ),
      event(
        id: 'demo:massa-kista',
        name: 'Teknikmässan Framtidsdagen',
        category: 'massa',
        categoryLabel: 'Mässa och konferens',
        start: DateTime(d3.year, d3.month, d3.day, 9),
        end: DateTime(d3.year, d3.month, d3.day, 17),
        venue: 'Kista Mässcenter',
        city: 'Kista',
        lat: 59.4031,
        lon: 17.9441,
        size: 'medel',
      ),
      event(
        id: 'demo:teater-city',
        name: 'Teater: Nattens gäster',
        category: 'teater',
        categoryLabel: 'Teater',
        start: DateTime(d5.year, d5.month, d5.day, 19, 30),
        end: DateTime(d5.year, d5.month, d5.day, 22),
        venue: 'Kvarterets teater',
        city: 'Stockholm',
        lat: 59.3326,
        lon: 18.0649,
        size: 'liten',
      ),
      event(
        id: 'demo:fotboll-norra',
        name: 'Fotboll: Norrhamns FF mot Uppsala Södra',
        category: 'sport',
        categoryLabel: 'Sport',
        sport: 'fotboll',
        sportLabel: 'Fotboll',
        start: DateTime(d6.year, d6.month, d6.day, 15),
        end: DateTime(d6.year, d6.month, d6.day, 17),
        venue: 'Norra Fotbollsarenan',
        city: 'Solna',
        lat: 59.3722,
        lon: 18.0000,
        attendance: 21000,
        size: 'stor',
      ),
    ];

    final dayCounts = <String, int>{};
    for (final e in events) {
      final d = e['startDate'] as String;
      dayCounts[d] = (dayCounts[d] ?? 0) + 1;
    }

    // --- Notiser -------------------------------------------------------------

    final notifications = <Map<String, dynamic>>[
      {
        'id': 'demo-notis-1',
        'opportunity_id': 'demo-flyg-arlanda',
        'title': 'Arlanda: många landningar väntas',
        'body':
            'Starkt tecken: flera landningar ${_hhmm(waveStart)}–${_hhmm(waveEnd)}.',
        'sent_at': _iso(n.subtract(const Duration(minutes: 4))),
        'is_favorite': favs.contains('demo-flyg-arlanda'),
      },
      {
        'id': 'demo-notis-2',
        'opportunity_id': 'demo-tag-uppsala',
        'title': 'Tåg 99207 Uppsala–Stockholm stoppat',
        'body': 'Värt att titta på: lång väntan till nästa avgång.',
        'sent_at': _iso(n.subtract(const Duration(minutes: 16))),
        'is_favorite': favs.contains('demo-tag-uppsala'),
      },
    ];

    return DemoSnapshot(
      alerts: alerts,
      events: events,
      ferries: [ferry],
      ferryShips: [ferry],
      terminals: terminals,
      notifications: notifications,
      dayCounts: dayCounts,
    );
  }

  static String _thousands(int v) {
    final s = v.toString();
    final out = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) out.write(' ');
      out.write(s[i]);
    }
    return out.toString();
  }
}
