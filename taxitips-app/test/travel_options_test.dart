import 'package:flutter_test/flutter_test.dart';
import 'package:taxibehov_app/severity_labels.dart';

void main() {
  Map<String, dynamic> alert(Map<String, dynamic>? options) => {
    'title': 'Tåg inställt',
    'travel_options': ?options,
  };

  test('utan travel_options visas ingen rad alls', () {
    // Supabase-vägen skickar inte fältet. Kortet ska då inte visa en tom
    // rad som ser ut som saknad data.
    expect(TravelOptions.of(alert(null)), isNull);
    expect(TravelOptions.of(alert({'summary': null})), isNull);
    expect(TravelOptions.of(alert({'summary': ''})), isNull);
  });

  test('meningen kommer från backend, appen formulerar inte om den', () {
    final t = TravelOptions.of(
      alert({
        'summary': 'Nästa avgång 14:35 (om 22 min) · Buss ersätter',
        'next_departure_minutes': 22,
        'has_alternative': true,
        'is_last_departure': false,
      }),
    )!;
    expect(t.summary, 'Nästa avgång 14:35 (om 22 min) · Buss ersätter');
    expect(t.minutes, 22);
    expect(t.hasAlternative, isTrue);
  });

  group('stark eller svag signal', () {
    test('sista avgången är stark — ingen tar sig hem själv', () {
      final t = TravelOptions.of(
        alert({
          'summary': 'Sista avgången härifrån',
          'is_last_departure': true,
        }),
      )!;
      expect(t.isStrong, isTrue);
      expect(t.isWeak, isFalse);
    });

    test('ett långt glapp är stark', () {
      final t = TravelOptions.of(
        alert({
          'summary': 'Nästa avgång om 5 tim',
          'next_departure_minutes': 300,
        }),
      )!;
      expect(t.isStrong, isTrue);
    });

    test('angiven ersättningsbuss är svag — resenären behöver ingen taxi', () {
      final t = TravelOptions.of(
        alert({
          'summary': 'Nästa avgång om 10 min · Buss ersätter',
          'next_departure_minutes': 10,
          'has_alternative': true,
        }),
      )!;
      expect(t.isWeak, isTrue);
      expect(t.isStrong, isFalse);
    });

    test('sista avgången är stark även när ersättningstrafik nämns', () {
      // Motsatta signaler i samma tips: att det var sista turen väger
      // tyngre än att en buss nämns, eftersom bussen kan vara på väg någon
      // annanstans.
      final t = TravelOptions.of(
        alert({
          'summary': 'Sista avgången härifrån · Ersättningstrafik',
          'is_last_departure': true,
          'has_alternative': true,
        }),
      )!;
      expect(t.isStrong, isTrue);
      expect(t.isWeak, isFalse);
    });
  });

  group('relativ tid räknas mot klockan, inte mot när tipset skrevs', () {
    final at = DateTime(2026, 9, 30, 13, 50);

    test('relativeDeparture', () {
      expect(
        relativeDeparture(at, now: DateTime(2026, 9, 30, 12, 0)),
        'om 1 tim 50 min',
      );
      expect(
        relativeDeparture(at, now: DateTime(2026, 9, 30, 13, 40)),
        'om 10 min',
      );
      expect(
        relativeDeparture(at, now: DateTime(2026, 9, 30, 12, 50)),
        'om 1 tim',
      );
      expect(
        relativeDeparture(at, now: DateTime(2026, 9, 30, 13, 50)),
        'avgår nu',
      );
      expect(
        relativeDeparture(at, now: DateTime(2026, 9, 30, 13, 49, 40)),
        'avgår nu',
      );
      expect(
        relativeDeparture(at, now: DateTime(2026, 9, 30, 14, 30)),
        'har gått',
      );
    });

    TravelOptions t() => TravelOptions.of(
      alert({
        'summary': 'Nästa avgång 13:50 (om 1 tim 50 min) · Buss ersätter',
        'next_departure_at': at.toIso8601String(),
        'next_departure_minutes': 110,
        'summary_head_upcoming': 'Nästa avgång 13:50',
        'summary_head_departed': 'Nästa avgång gick 13:50',
        'summary_tail': 'Buss ersätter',
      }),
    )!;

    test('texten byggs om från absolut tid', () {
      expect(
        t().text(now: DateTime(2026, 9, 30, 13, 40)),
        'Nästa avgång 13:50 (om 10 min) · Buss ersätter',
      );
      expect(
        t().text(now: DateTime(2026, 9, 30, 14, 0)),
        'Nästa avgång gick 13:50 · Buss ersätter',
      );
    });

    test('utan absolut tid gäller backends mening', () {
      final o = TravelOptions.of(
        alert({'summary': 'Sista avgången härifrån'}),
      )!;
      expect(o.text(), 'Sista avgången härifrån');
    });
  });
}
