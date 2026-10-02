import 'package:flutter_test/flutter_test.dart';

import 'package:taxitips_app/screens/events_screen.dart';
import 'package:taxitips_app/severity_labels.dart';

void main() {
  group('därför', () {
    test('raderna läses som backend skrev dem, högst fyra', () {
      final factors = TipFactor.of({
        'factors': [
          {'text': 'Nästa tåg går först 45 min senare', 'sign': '+'},
          {'text': 'Ersättningstrafik är insatt', 'sign': '-'},
          {'text': '', 'sign': '+'},
          'trasig rad',
          {'text': 'Morgon en vardag – folk ska till jobbet', 'sign': '+'},
          {'text': 'Stor station – många resenärer', 'sign': '+'},
          {'text': 'Femte raden', 'sign': '+'},
        ],
      });
      expect(factors, hasLength(4));
      expect(factors.first.text, 'Nästa tåg går först 45 min senare');
      expect(factors.first.supports, isTrue);
      expect(factors[1].supports, isFalse);
    });

    test('äldre svar utan fältet visar ingenting', () {
      expect(TipFactor.of({}), isEmpty);
      expect(TipFactor.of({'factors': null}), isEmpty);
    });
  });

  group('evenemangens sort', () {
    test('sporten före kategorin', () {
      expect(
        eventKindOf({'sport': 'ishockey', 'category': 'sport'}),
        'ishockey',
      );
      expect(
        eventKindLabelOf({
          'sport': 'ishockey',
          'sportLabel': 'Ishockey',
          'categoryLabel': 'Sport',
        }),
        'Ishockey',
      );
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
          'summary':
              'Nästa resa mot Stockholm C: Regional tåg 178 14:09 (om 37 min)',
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
