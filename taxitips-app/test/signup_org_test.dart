import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/screens/signup_screen.dart';

void main() {
  test('organisationsnummer: kontrollsiffran prövas som på servern', () {
    expect(SignupScreenState.orgNumberLooksValid('556036-0793'), isTrue);
    expect(SignupScreenState.orgNumberLooksValid('5560360793'), isTrue);
    // Tolvsiffrig form med sekelsiffror.
    expect(SignupScreenState.orgNumberLooksValid('16556036-0793'), isTrue);
    expect(SignupScreenState.orgNumberLooksValid('5560360794'), isFalse);
    expect(SignupScreenState.orgNumberLooksValid('55603607'), isFalse);
  });

  test('enskild firma: personnummer-form känns igen (månad 01–12)', () {
    expect(SignupScreenState.looksLikeSoleTrader('556036-0793'), isFalse);
    expect(SignupScreenState.looksLikeSoleTrader('850101-2395'), isTrue);
    expect(SignupScreenState.looksLikeSoleTrader('8501012395'), isTrue);
  });

  test('mobilnummer: samma former som servern godtar', () {
    for (final ok in [
      '0708123491',
      '070-812 34 91',
      '+46 70 812 34 91',
      '0046708123491',
      '46708123491',
      '+46 (0)70 812 34 91',
    ]) {
      expect(SignupScreenState.phoneLooksValid(ok), isTrue, reason: ok);
    }
    for (final bad in ['040-12 34 56', '0711234567', '+4712345678', '0708', '']) {
      expect(SignupScreenState.phoneLooksValid(bad), isFalse, reason: bad);
    }
  });
}
