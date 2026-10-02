import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/pending_feedback.dart';
import 'package:taxitips_app/signal_kinds.dart';

/// Datumet står alltid i tipset, också i dag; "Fick körning" och "Ingen
/// kund" köas som ett svar, inte två.
void main() {
  final now = DateTime(2026, 10, 1, 21, 0); // torsdag

  test('kortet visar datumet även i dag', () {
    expect(
      dateText(DateTime(2026, 10, 1, 22, 15), now: now),
      'I dag 1 okt · 22:15',
    );
    expect(
      dateText(DateTime(2026, 9, 30, 7, 5), now: now),
      'I går 30 sep · 07:05',
    );
    expect(
      dateText(DateTime(2026, 10, 2, 6, 0), now: now),
      'I morgon 2 okt · 06:00',
    );
    expect(
      dateText(DateTime(2026, 10, 5, 6, 0), now: now),
      'Mån 5 okt · 06:00',
    );
    expect(
      dateText(DateTime(2025, 12, 24, 6, 0), now: now),
      'Ons 24 dec 2025 · 06:00',
    );
  });

  test('detaljvyn skriver ut veckodag och månad', () {
    expect(
      longDateText(DateTime(2026, 10, 1, 22, 15), now: now),
      'I dag, torsdag 1 oktober · 22:15',
    );
    expect(
      longDateText(DateTime(2026, 10, 5, 6, 0), now: now),
      'Måndag 5 oktober · 06:00',
    );
  });

  test('i dag stämmer över sommartidsbytet', () {
    final night = DateTime(2026, 10, 25, 23, 30);
    expect(
      dateText(DateTime(2026, 10, 25, 1, 0), now: night),
      startsWith('I dag'),
    );
    expect(
      dateText(DateTime(2026, 10, 24, 23, 0), now: night),
      startsWith('I går'),
    );
  });

  test('offlinekön behåller bara senaste svaret om utfallet', () async {
    SharedPreferences.setMockInitialValues({});
    await PendingFeedback.add('t1', 'heading', now: now);
    await PendingFeedback.add('t1', 'fare', now: now);
    await PendingFeedback.add('t1', 'empty', now: now);
    await PendingFeedback.add('t2', 'fare', now: now);
    await PendingFeedback.add('t1', 'none', now: now);
    final items = await PendingFeedback.load(now: now);
    expect(
      [for (final i in items) '${i['id']}:${i['verdict']}'],
      ['t1:heading', 't2:fare', 't1:none'],
    );
  });
}
