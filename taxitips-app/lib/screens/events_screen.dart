import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api_client.dart';
import '../theme.dart';
import '../widgets/ferry_event_widgets.dart';

/// Sporten för sportevenemang, annars kategorin -- samma sort som filtret på pipeline-sidan.
String eventKindOf(Map e) {
  final sport = e['sport']?.toString() ?? '';
  if (sport.isNotEmpty) return sport;
  final category = e['category']?.toString() ?? '';
  return category.isNotEmpty ? category : 'ovrigt';
}

String eventKindLabelOf(Map e) {
  final sport = e['sportLabel']?.toString() ?? '';
  if (sport.isNotEmpty) return sport;
  return e['categoryLabel']?.toString() ?? 'Övrigt';
}

/// Alla evenemang i förarens område, med datumet i centrum: en dag, helgen, en vecka,
/// månader framåt eller en egen period -- så långt fram som backenden hämtar
/// (`maxDays` i svaret från /api/events, i dag 120 dagar).
class EventsScreen extends StatefulWidget {
  const EventsScreen({
    super.key,
    required this.api,
    this.lat,
    this.lon,
    this.counties,
    this.municipalities,
    this.areaLabel = '',
  });

  final ApiClient api;
  final double? lat;
  final double? lon;
  final List<String>? counties;
  final List<String>? municipalities;
  final String areaLabel;

  @override
  State<EventsScreen> createState() => _EventsScreenState();
}

class _Period {
  const _Period(this.key, this.label, this.from, this.to);

  final String key;
  final String label;
  final DateTime from;
  final DateTime to;

  bool get singleDay => _sameDay(from, to);
}

bool _sameDay(DateTime a, DateTime b) => a.year == b.year && a.month == b.month && a.day == b.day;

DateTime _day(DateTime d) => DateTime(d.year, d.month, d.day);

String _iso(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

class _EventsScreenState extends State<EventsScreen> {
  late _Period _period;
  List<Map<String, dynamic>> _events = const [];
  Map<String, int> _dayCounts = const {};
  bool _loading = true;
  String? _error;
  bool _preview = false;
  String _previewNote = '';
  String _attribution = '';
  int _maxDays = 120;

  DateTime get _today => _day(DateTime.now());

  /// Sorter föraren har slagit av: fotboll, ishockey, handboll, konsert, festival ...
  /// Opt-out, så att en ny sort syns tills föraren väljer bort den. Sparas på telefonen.
  Set<String> _kindsOff = {};
  static const _prefsKindsOffKey = 'tb_event_kinds_off';

  @override
  void initState() {
    super.initState();
    _period = _preset('month');
    _loadKinds();
    _load();
  }

  Future<void> _loadKinds() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final off = prefs.getStringList(_prefsKindsOffKey);
      if (off != null && mounted) setState(() => _kindsOff = off.toSet());
    } catch (_) {}
  }

  Future<void> _saveKinds() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(_prefsKindsOffKey, _kindsOff.toList());
    } catch (_) {}
  }

  _Period _preset(String key) {
    final t = _today;
    switch (key) {
      case 'today':
        return _Period(key, 'I dag', t, t);
      case 'tomorrow':
        final d = t.add(const Duration(days: 1));
        return _Period(key, 'I morgon', d, d);
      case 'weekend':
        // Fredag–söndag den här veckan; på lördag och söndag resten av helgen.
        final friday = t.weekday <= DateTime.friday
            ? t.add(Duration(days: DateTime.friday - t.weekday))
            : t;
        final sunday = t.add(Duration(days: DateTime.sunday - t.weekday));
        return _Period(key, 'Helgen', friday, sunday);
      case 'week':
        return _Period(key, '7 dagar', t, t.add(const Duration(days: 6)));
      case 'quarter':
        return _Period(key, '3 månader', t, t.add(const Duration(days: 91)));
      default:
        return _Period('month', '30 dagar', t, t.add(const Duration(days: 29)));
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final body = await widget.api.events(
        lat: widget.lat,
        lon: widget.lon,
        counties: widget.counties,
        municipalities: widget.municipalities,
        from: _iso(_period.from),
        to: _iso(_period.to),
      );
      if (!mounted) return;
      final raw = body['dayCounts'];
      setState(() {
        _events = [
          for (final e in (body['events'] as List?) ?? const [])
            if (e is Map) Map<String, dynamic>.from(e),
        ];
        _dayCounts = raw is Map
            ? {for (final entry in raw.entries) entry.key.toString(): (entry.value as num).toInt()}
            : const {};
        _preview = body['preview'] == true;
        _previewNote = body['previewNote']?.toString() ?? '';
        _attribution = body['attribution']?.toString() ?? '';
        _maxDays = (body['maxDays'] as num?)?.toInt() ?? _maxDays;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), '');
        _loading = false;
      });
    }
  }

  void _select(_Period period) {
    setState(() => _period = period);
    _load();
  }

  DateTime get _lastDay => _today.add(Duration(days: _maxDays));

  Future<void> _pickDate() async {
    final initial = _period.from.isBefore(_today) ? _today : _period.from;
    final picked = await showDatePicker(
      context: context,
      initialDate: initial.isAfter(_lastDay) ? _lastDay : initial,
      firstDate: _today,
      lastDate: _lastDay,
      helpText: 'Välj dag',
    );
    if (picked != null) {
      final d = _day(picked);
      _select(_Period('day', dayHeading(d), d, d));
    }
  }

  Future<void> _pickRange() async {
    final end = _period.to.isAfter(_lastDay) ? _lastDay : _period.to;
    final picked = await showDateRangePicker(
      context: context,
      firstDate: _today,
      lastDate: _lastDay,
      initialDateRange: DateTimeRange(start: _period.from, end: end),
      helpText: 'Välj period',
    );
    if (picked != null) {
      final from = _day(picked.start);
      final to = _day(picked.end);
      _select(_Period('range', '${shortDate(from)}–${shortDate(to)}', from, to));
    }
  }

  String get _periodText => _period.singleDay
      ? dayHeading(_period.from)
      : '${shortDate(_period.from)} – ${shortDate(_period.to)}';

  List<Map<String, dynamic>> get _visibleEvents =>
      _events.where((e) => !_kindsOff.contains(eventKindOf(e))).toList();

  /// Sorterna i perioden: sporterna först, sedan flest evenemang.
  Widget _kindChips() {
    final counts = <String, int>{};
    final labels = <String, String>{};
    for (final e in _events) {
      final k = eventKindOf(e);
      counts[k] = (counts[k] ?? 0) + 1;
      labels[k] = eventKindLabelOf(e);
    }
    const sports = ['fotboll', 'ishockey', 'handboll', 'annan'];
    final kinds = counts.keys.toList()
      ..sort((a, b) {
        final sa = sports.indexOf(a), sb = sports.indexOf(b);
        if (sa != -1 || sb != -1) return (sa == -1 ? 99 : sa).compareTo(sb == -1 ? 99 : sb);
        return counts[b]!.compareTo(counts[a]!);
      });
    final allOn = kinds.every((k) => !_kindsOff.contains(k));
    void toggle(String k) {
      setState(() {
        if (allOn) {
          // Första trycket när allt syns: visa bara den sorten.
          _kindsOff = kinds.where((x) => x != k).toSet();
        } else if (_kindsOff.contains(k)) {
          _kindsOff.remove(k);
        } else {
          _kindsOff.add(k);
        }
      });
      _saveKinds();
    }

    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        FilterChip(
          label: const Text('Alla sorter', style: TextStyle(fontWeight: FontWeight.w700)),
          selected: allOn,
          selectedColor: TbColors.taxi,
          showCheckmark: false,
          onSelected: (_) {
            setState(() => _kindsOff = {});
            _saveKinds();
          },
        ),
        for (final k in kinds)
          FilterChip(
            label: Text('${labels[k]} ${counts[k]}', style: const TextStyle(fontWeight: FontWeight.w700)),
            selected: !_kindsOff.contains(k) && !allOn,
            selectedColor: TbColors.taxi,
            showCheckmark: false,
            onSelected: (_) => toggle(k),
          ),
      ],
    );
  }

  /// Evenemangen per dag. Det som redan pågår när perioden börjar hör till första dagen.
  Map<String, List<Map<String, dynamic>>> get _byDay {
    final first = _iso(_period.from);
    final out = <String, List<Map<String, dynamic>>>{};
    for (final e in _visibleEvents) {
      var day = e['startDate']?.toString() ?? first;
      if (e['ongoing'] == true || day.compareTo(first) < 0) day = first;
      out.putIfAbsent(day, () => []).add(e);
    }
    return out;
  }

  Widget _periodChips() {
    final presets = ['today', 'tomorrow', 'weekend', 'week', 'month', 'quarter'];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final key in presets)
          ChoiceChip(
            label: Text(_preset(key).label, style: const TextStyle(fontWeight: FontWeight.w700)),
            selected: _period.key == key,
            selectedColor: TbColors.taxi,
            onSelected: (_) => _select(_preset(key)),
          ),
        ActionChip(
          avatar: const Icon(Icons.today, size: 18),
          label: Text(
            _period.key == 'day' ? _period.label : 'Välj dag',
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
          backgroundColor: _period.key == 'day' ? TbColors.taxi : null,
          onPressed: _pickDate,
        ),
        ActionChip(
          avatar: const Icon(Icons.date_range, size: 18),
          label: Text(
            _period.key == 'range' ? _period.label : 'Välj period',
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
          backgroundColor: _period.key == 'range' ? TbColors.taxi : null,
          onPressed: _pickRange,
        ),
      ],
    );
  }

  /// Dagarna som har evenemang, över hela horisonten -- tryck för att visa den dagen.
  Widget _dateStrip() {
    final days = _dayCounts.keys.toList()..sort();
    return SizedBox(
      height: 84,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: days.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (context, i) {
          final date = DateTime.parse(days[i]);
          final selected = _period.singleDay && _sameDay(_period.from, date);
          final fg = selected ? TbColors.vit : TbColors.ink;
          return InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () => _select(_Period('day', dayHeading(date), date, date)),
            child: Container(
              width: 60,
              padding: const EdgeInsets.symmetric(vertical: 8),
              decoration: BoxDecoration(
                color: selected ? TbColors.midnatt : TbColors.vit,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: selected ? TbColors.midnatt : TbColors.line),
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    weekdayShort(date).toUpperCase(),
                    style: TextStyle(
                      fontSize: 10.5,
                      fontWeight: FontWeight.w800,
                      color: selected ? TbColors.guld : Colors.grey.shade600,
                    ),
                  ),
                  Text(
                    '${date.day}',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: fg, height: 1.2),
                  ),
                  Text(monthShort(date), style: TextStyle(fontSize: 11, color: fg)),
                  const SizedBox(height: 2),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                      color: selected ? TbColors.guld : TbColors.taxi.withValues(alpha: 0.3),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      '${_dayCounts[days[i]]}',
                      style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: TbColors.ink),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  List<Widget> _groupedList() {
    final groups = _byDay;
    final days = groups.keys.toList()..sort();
    final longPeriod = _period.to.difference(_period.from).inDays > 31;
    final today = _iso(_today);
    final tomorrow = _iso(_today.add(const Duration(days: 1)));
    final out = <Widget>[];
    String? month;
    for (final day in days) {
      final date = DateTime.parse(day);
      final monthKey = day.substring(0, 7);
      if (longPeriod && monthKey != month) {
        month = monthKey;
        out.add(
          Padding(
            padding: const EdgeInsets.fromLTRB(2, 18, 2, 2),
            child: Text(
              '${monthLong(date)} ${date.year}'.toUpperCase(),
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                letterSpacing: 1.1,
                color: Colors.grey.shade600,
              ),
            ),
          ),
        );
      }
      final events = groups[day]!;
      final prefix = day == today ? 'I dag · ' : (day == tomorrow ? 'I morgon · ' : '');
      out.add(
        Padding(
          padding: const EdgeInsets.fromLTRB(2, 14, 2, 8),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '$prefix${dayHeading(date)}',
                  style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: TbColors.ink),
                ),
              ),
              Text(
                '${events.length} ${events.length == 1 ? 'evenemang' : 'evenemang'}',
                style: TextStyle(fontSize: 13, color: Colors.grey.shade700, fontWeight: FontWeight.w600),
              ),
            ],
          ),
        ),
      );
      for (final e in events) {
        out.add(
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: EventCard(
              event: e,
              compactTime: true,
              onTap: () => showEventSheet(
                context,
                e,
                attribution: _attribution,
                previewNote: _preview ? _previewNote : '',
              ),
            ),
          ),
        );
      }
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.foam,
      appBar: AppBar(
        backgroundColor: TbColors.foam,
        surfaceTintColor: TbColors.foam,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Evenemang', style: TextStyle(fontWeight: FontWeight.w800)),
            if (widget.areaLabel.isNotEmpty)
              Text(
                widget.areaLabel,
                style: TextStyle(fontSize: 13, color: Colors.grey.shade700, fontWeight: FontWeight.w600),
              ),
          ],
        ),
      ),
      body: RefreshIndicator(
        color: TbColors.taxiDeep,
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: EdgeInsets.fromLTRB(16, 4, 16, 32 + MediaQuery.paddingOf(context).bottom),
          children: [
            _periodChips(),
            if (_dayCounts.isNotEmpty) ...[
              const SizedBox(height: 14),
              _dateStrip(),
            ],
            if (_events.isNotEmpty) ...[
              const SizedBox(height: 14),
              _kindChips(),
            ],
            const SizedBox(height: 14),
            Text(
              _loading
                  ? 'Hämtar $_periodText…'
                  : _visibleEvents.length == _events.length
                      ? '${_events.length} evenemang · $_periodText'
                      : '${_visibleEvents.length} av ${_events.length} evenemang · $_periodText',
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: TbColors.ink),
            ),
            if (_preview && _previewNote.isNotEmpty) ...[
              const SizedBox(height: 10),
              PreviewBanner(text: _previewNote),
            ],
            if (_loading)
              const Padding(
                padding: EdgeInsets.all(40),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 24),
                child: Text('Kunde inte hämta evenemangen: $_error', style: const TextStyle(color: TbColors.danger)),
              )
            else if (_events.isEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 32, 8, 8),
                child: Column(
                  children: [
                    Icon(Icons.event_busy, size: 52, color: Colors.grey.shade400),
                    const SizedBox(height: 10),
                    Text(
                      'Inga evenemang $_periodText i ditt område.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 16, color: Colors.grey.shade800, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _dayCounts.isEmpty
                          ? 'Ticketmaster har tunt utbud utanför Stockholm. Prova ett annat län.'
                          : 'Dagarna ovan har evenemang — tryck på en av dem, eller välj en längre period.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 13.5, height: 1.4, color: Colors.grey.shade700),
                    ),
                  ],
                ),
              )
            else
              ..._groupedList(),
            if (_attribution.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text(_attribution, style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
            ],
          ],
        ),
      ),
    );
  }
}
