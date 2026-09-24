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
}
