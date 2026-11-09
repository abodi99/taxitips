import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/api_client.dart';

/// Appen kopierar tipsets fält ett och ett ur serverns svar. Ett fält som
/// servern skickar men som inte kopieras når aldrig kortet -- och kortet
/// faller då tyst tillbaka på det gamla (hände med kortets två rader
/// 2026-11-10). Testet håller ihop serverns fält och appens.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('kortets rader från servern följer med till kortet', () {
    final api = ApiClient(
      supabaseUrl: 'http://localhost',
      supabaseAnonKey: 'x',
    );
    final alert = api.alertFromRowForTest({
      'id': '1',
      'headline': 'Tåg 22:48 inställt',
      'decision': 'Nästa tåg 23:48',
      'decision_tone': 'go',
    });
    expect(alert['headline'], 'Tåg 22:48 inställt');
    expect(alert['decision'], 'Nästa tåg 23:48');
    expect(alert['decision_tone'], 'go');
  });

  test('äldre svar utan raderna ger tomma strängar, inte null', () {
    final api = ApiClient(
      supabaseUrl: 'http://localhost',
      supabaseAnonKey: 'x',
    );
    final alert = api.alertFromRowForTest({'id': '1'});
    expect(alert['headline'], '');
    expect(alert['decision'], '');
  });
}
