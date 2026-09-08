import 'package:flutter_test/flutter_test.dart';
import 'package:taxibehov_app/severity_labels.dart';

void main() {
  test('the three live vehicle_cancelled cases that were mislabeled', () {
    // 16.2 km away, reachable -> genuinely worth driving to
    expect(customerLikelihood(severityTier: 'vehicle_cancelled', worthItScore: 39.5, demandScore: 72),
        CustomerLikelihood.high);
    // 52.4 km, unreachable before it ends -> honestly not worth it
    expect(customerLikelihood(severityTier: 'vehicle_cancelled', worthItScore: 0, demandScore: 72),
        CustomerLikelihood.low);
    // 55.2 km, same
    expect(customerLikelihood(severityTier: 'vehicle_cancelled', worthItScore: 0, demandScore: 72),
        CustomerLikelihood.low);
  });

  test('weak cancellation stays medium even when reachable', () {
    expect(customerLikelihood(severityTier: 'vehicle_cancelled', worthItScore: 30, demandScore: 40),
        CustomerLikelihood.medium);
  });

  test('line_paused reachable is high; unreachable is low', () {
    expect(customerLikelihood(severityTier: 'line_paused', worthItScore: 60, demandScore: 85),
        CustomerLikelihood.high);
    expect(customerLikelihood(severityTier: 'line_paused', worthItScore: 0, demandScore: 85),
        CustomerLikelihood.low);
  });

  test('road tiers never reach high (deliberate business rule)', () {
    expect(customerLikelihood(severityTier: 'road_accident_or_closure', worthItScore: 80, demandScore: 90),
        CustomerLikelihood.low);
  });

  test('bus running late never reaches high', () {
    expect(customerLikelihood(severityTier: 'vehicle_delayed', worthItScore: 25, demandScore: 25),
        CustomerLikelihood.low);
  });

  group('backendens bedömning går före appens kopia', () {
    // Django räknar ut `level` i core/thresholds.py. Appens egna regler
    // finns kvar som fallback för cachead/Supabase-hämtad data, men får
    // aldrig överpröva backend -- annars är tröskeln duplicerad igen, vilket
    // var hela skälet att flytta den.
    test('level från backend vinner över de lokala reglerna', () {
      expect(
        likelihoodForAlert({
          'severity_tier': 'road_accident_or_closure',
          'worth_it_score': 80,
          'demand_score': 90,
          'level': 'high',
        }),
        CustomerLikelihood.high,
      );
      expect(
        likelihoodForAlert({
          'severity_tier': 'line_paused',
          'worth_it_score': 60,
          'demand_score': 85,
          'level': 'low',
        }),
        CustomerLikelihood.low,
      );
    });

    test('utan level räknas det ut lokalt, som förut', () {
      expect(
        likelihoodForAlert({
          'severity_tier': 'line_paused',
          'worth_it_score': 60,
          'demand_score': 85,
        }),
        CustomerLikelihood.high,
      );
    });

    test('ett okänt level ignoreras i stället för att gissa', () {
      expect(
        likelihoodForAlert({
          'severity_tier': 'line_paused',
          'worth_it_score': 60,
          'demand_score': 85,
          'level': 'väldigt hög',
        }),
        CustomerLikelihood.high,
      );
    });
  });

  group('ersättningsetiketten', () {
    test('beloppet skrivs ut när backend har det', () {
      expect(compensationLabel(500), 'Taxi ersätts · upp till 500 kr');
    });

    test('utan belopp gissar appen inte', () {
      expect(compensationLabel(null), 'Taxi kan ersättas');
    });

    test('per resenär skrivs ut bara när huvudmannen gör det', () {
      // Skånetrafiken skriver "per betalande resenär", SL skriver att
      // beloppet inte blir högre vid samåkning, Västtrafik säger emot sig
      // själv — och då säger kortet inget.
      expect(compensationLabel(2960, perPerson: true),
          'Taxi ersätts · upp till 2960 kr per resenär');
      expect(compensationLabel(1480, perPerson: false),
          'Taxi ersätts · upp till 1480 kr per resa');
      expect(compensationLabel(1500), 'Taxi ersätts · upp till 1500 kr');
    });
  });
}
