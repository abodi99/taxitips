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
}
