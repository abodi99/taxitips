/// Appens språk: svenska, engelska och arabiska.
///
/// **Vilket språk.** Har användaren valt ett språk i appen gäller det. Annars
/// telefonens språk, om appen finns på det (första träffen i telefonens
/// språklista). Annars svenska -- tjänsten finns i Sverige.
///
/// **`tr` i stället för `AppLocalizations.of(context)`.** Många texter byggs i
/// funktioner utan `BuildContext` (lib/signal_kinds.dart, severity_labels.dart,
/// membership_copy.dart). `tr` är det aktiva språkets texter och sätts av
/// appen varje gång språket byts; hela trädet byggs om då, så en text som
/// läses i `build` är alltid rätt. Utan app (tester av rena funktioner) är
/// `tr` svenska.
///
/// **Siffror.** Arabiska visas med västerländska siffror (0–9): klockslag,
/// registreringsnummer och linjenummer ska se ut som på skyltarna.
library;

import 'package:flutter/widgets.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_localizations.dart';

export 'app_localizations.dart';

/// Språken appen finns på, i den ordning de visas i väljaren.
const supportedLanguages = ['sv', 'en', 'ar'];
const supportedLocales = [Locale('sv'), Locale('en'), Locale('ar')];
const _fallback = Locale('sv');
const _prefsKey = 'tt_locale';

AppLocalizations _tr = lookupAppLocalizations(_fallback);

/// Det aktiva språkets texter.
AppLocalizations get tr => _tr;

/// Språkkoden som används just nu (`sv`, `en` eller `ar`).
String get currentLanguage => _tr.localeName;

/// Höger till vänster (arabiska).
bool get isRtl => currentLanguage == 'ar';

/// Sätts av appen (MaterialApp.builder) och av tester.
void setTrLocale(Locale locale) {
  _initIntl();
  final resolved = resolveLocale(locale);
  if (_tr.localeName == resolved.languageCode) return;
  _tr = lookupAppLocalizations(resolved);
  Intl.defaultLocale = resolved.languageCode;
}

/// Det närmaste språket appen har för en telefons språk.
Locale resolveLocale(Locale? locale) {
  if (locale != null && supportedLanguages.contains(locale.languageCode)) {
    return Locale(locale.languageCode);
  }
  return _fallback;
}

/// Telefonens språklista -> första språket appen har, annars svenska.
Locale resolveDeviceLocales(List<Locale>? locales) {
  for (final l in locales ?? const <Locale>[]) {
    if (supportedLanguages.contains(l.languageCode)) return Locale(l.languageCode);
  }
  return _fallback;
}

/// Användarens val. `null` = följ telefonens språk.
final ValueNotifier<Locale?> chosenLocale = ValueNotifier<Locale?>(null);

/// Läser valet före runApp. Tyst vid fel: då gäller telefonens språk.
Future<void> loadChosenLocale() async {
  _initIntl();
  try {
    final prefs = await SharedPreferences.getInstance();
    final code = prefs.getString(_prefsKey);
    chosenLocale.value =
        code != null && supportedLanguages.contains(code) ? Locale(code) : null;
  } catch (_) {
    chosenLocale.value = null;
  }
}

/// Sparar valet. `null` = följ telefonens språk igen.
Future<void> chooseLocale(Locale? locale) async {
  chosenLocale.value = locale == null ? null : resolveLocale(locale);
  try {
    final prefs = await SharedPreferences.getInstance();
    if (locale == null) {
      await prefs.remove(_prefsKey);
    } else {
      await prefs.setString(_prefsKey, resolveLocale(locale).languageCode);
    }
  } catch (_) {
    // Valet gäller ändå tills appen startas om.
  }
}

/// Språkets eget namn, så att man hittar sitt språk oavsett vilket som visas.
String languageName(String code) => switch (code) {
  'sv' => 'Svenska',
  'en' => 'English',
  'ar' => 'العربية',
  _ => code,
};

bool _intlReady = false;

void _initIntl() {
  if (_intlReady) return;
  _intlReady = true;
  // Datumdata för alla språk. Lokal data laddas synkront, framtiden behövs
  // inte (appen gör samma sak via GlobalMaterialLocalizations).
  initializeDateFormatting();
  // Västerländska siffror även på arabiska (se ovan).
  DateFormat.useNativeDigitsByDefaultFor('ar', false);
}

/// Klockslag "14:05" i det aktiva språket.
String formatTime(DateTime t) {
  _initIntl();
  return DateFormat.Hm(currentLanguage).format(t);
}

/// Tal med språkets skiljetecken ("1 234,5" / "1,234.5").
String formatNumber(num n, {int decimals = 0}) {
  _initIntl();
  final f = NumberFormat.decimalPatternDigits(
    locale: currentLanguage == 'ar' ? 'en' : currentLanguage,
    decimalDigits: decimals,
  );
  return f.format(n);
}

@visibleForTesting
void resetTrForTest() {
  _tr = lookupAppLocalizations(_fallback);
  Intl.defaultLocale = null;
}
