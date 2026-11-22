import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:taxitips_app/l10n/l10n.dart';

void main() {
  tearDown(resetTrForTest);

  group('telefonens språk', () {
    test('appen tar telefonens språk när den finns på det', () {
      expect(
        resolveDeviceLocales(const [Locale('ar', 'SE')]),
        const Locale('ar'),
      );
      expect(
        resolveDeviceLocales(const [Locale('en', 'GB')]),
        const Locale('en'),
      );
      expect(
        resolveDeviceLocales(const [Locale('sv', 'SE')]),
        const Locale('sv'),
      );
    });

    test('första språket i telefonens lista som appen har vinner', () {
      expect(
        resolveDeviceLocales(const [Locale('fa'), Locale('en'), Locale('sv')]),
        const Locale('en'),
      );
    });

    test('ett språk appen inte har ger svenska', () {
      expect(
        resolveDeviceLocales(const [Locale('so'), Locale('fa')]),
        const Locale('sv'),
      );
      expect(resolveDeviceLocales(null), const Locale('sv'));
    });
  });

  group('valet', () {
    test('sparas och läses tillbaka', () async {
      SharedPreferences.setMockInitialValues({});
      await chooseLocale(const Locale('ar'));
      chosenLocale.value = null;
      await loadChosenLocale();
      expect(chosenLocale.value, const Locale('ar'));
    });

    test('"telefonens språk" tar bort valet', () async {
      SharedPreferences.setMockInitialValues({'tt_locale': 'en'});
      await loadChosenLocale();
      expect(chosenLocale.value, const Locale('en'));
      await chooseLocale(null);
      await loadChosenLocale();
      expect(chosenLocale.value, isNull);
    });

    test('ett okänt sparat värde ger telefonens språk', () async {
      SharedPreferences.setMockInitialValues({'tt_locale': 'xx'});
      await loadChosenLocale();
      expect(chosenLocale.value, isNull);
    });
  });

  group('texterna', () {
    test('tr är svenska utan app, och byter med språket', () {
      expect(tr.languageTitle, 'Språk');
      setTrLocale(const Locale('en'));
      expect(tr.languageTitle, 'Language');
      expect(isRtl, isFalse);
      setTrLocale(const Locale('ar'));
      expect(tr.languageTitle, 'اللغة');
      expect(isRtl, isTrue);
    });

    test('arabiska klockslag har västerländska siffror', () {
      setTrLocale(const Locale('ar'));
      expect(formatTime(DateTime(2026, 11, 22, 14, 5)), '14:05');
    });

    test('alla tre språkfilerna har samma nycklar', () {
      Map<String, dynamic> read(String lang) =>
          jsonDecode(File('lib/l10n/app_$lang.arb').readAsStringSync())
              as Map<String, dynamic>;
      Set<String> keys(Map<String, dynamic> arb) =>
          arb.keys.where((k) => !k.startsWith('@')).toSet();
      final sv = keys(read('sv'));
      expect(keys(read('en')), sv);
      expect(keys(read('ar')), sv);
    });
  });
}
