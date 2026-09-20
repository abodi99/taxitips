import 'package:flutter_test/flutter_test.dart';

import 'package:taxibehov_app/screens/events_screen.dart';
import 'package:taxibehov_app/severity_labels.dart';

void main() {
  group('evenemangens sort', () {
    test('sporten före kategorin', () {
      expect(eventKindOf({'sport': 'ishockey', 'category': 'sport'}), 'ishockey');
      expect(eventKindLabelOf({'sport': 'ishockey', 'sportLabel': 'Ishockey', 'categoryLabel': 'Sport'}), 'Ishockey');
    });
    test('annars kategorin, och övrigt när den saknas', () {
      expect(eventKindOf({'sport': '', 'category': 'konsert'}), 'konsert');
      expect(eventKindOf({}), 'ovrigt');
      expect(eventKindLabelOf({'categoryLabel': 'Festival'}), 'Festival');
    });
  });

  group('nästa resa', () {
    test('reseplanerarens resa och vem som svarade', () {
      final travel = TravelOptions.of({
        'travel_options': {
          'summary': 'Nästa resa mot Stockholm C: Regional tåg 178 14:09 (om 37 min)',
          'next_departure_minutes': 37,
          'planner': 'ResRobot',
        },
      })!;
      expect(travel.planner, 'ResRobot');
      expect(travel.summary, startsWith('Nästa resa mot Stockholm C'));
    });
    test('ersättningsbuss har ingen reseplanerare', () {
      final travel = TravelOptions.of({
        'travel_options': {'summary': 'Buss ersätter', 'has_alternative': true},
      })!;
      expect(travel.planner, isNull);
      expect(travel.isWeak, isTrue);
    });
  });
}
