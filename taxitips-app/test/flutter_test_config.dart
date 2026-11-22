import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/l10n/l10n.dart';

/// Gäller alla tester: varje test börjar på svenska.
///
/// Ett test som startar hela appen byter `tr` till testmiljöns språk (en_US),
/// och utan nollställning hade nästa test i samma fil sett engelska texter.
/// Testerna jämför mot svensk text; ett test som vill se ett annat språk
/// anropar `setTrLocale` själv.
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  setUp(resetTrForTest);
  await testMain();
}
