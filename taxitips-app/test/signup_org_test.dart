import 'package:flutter_test/flutter_test.dart';
import 'package:taxibehov_app/screens/signup_screen.dart';

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
}
