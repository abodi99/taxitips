import 'package:flutter/material.dart';

/// taxitips varumärke — varumärkesguiden taxitips2 (midnatt + guld).
///
/// Paletten är fem färger och inget mer: midnatt, guld, vit, ljusgrå och
/// skiffer. Allt annat här är antingen en härledd nyans av samma kulör (för
/// hover, djup och linjer) eller en statusfärg. Statusfärger får finnas
/// utanför paletten men ska alltid följas av text eller ikon — guiden tillåter
/// aldrig färg som ensam bärare av betydelse.
class TbColors {
  // De fem varumärkesfärgerna.
  static const midnatt = Color(0xFF14213D);
  static const guld = Color(0xFFFCA311);
  static const vit = Color(0xFFFFFFFF);
  static const ljusgra = Color(0xFFF5F7FA);
  static const skiffer = Color(0xFF526078);

  // Härledda nyanser.
  static const midnattDjup = Color(0xFF0D1729);
  static const midnattMjuk = Color(0xFF253551);
  static const guldDjup = Color(0xFFE08F00);
  static const ljusgraDjup = Color(0xFFE7EBF1);
  static const line = Color(0xFFD9DCE0);

  // Statusfärger — alltid tillsammans med text eller ikon.
  static const live = Color(0xFF1F8A5B);
  static const danger = Color(0xFFC0392B);

  // Kundsannolikhet -- ett färgsystem som återanvänds identiskt i kortets
  // pill, i båda kartlägena och i detaljvyns förklaringsribba. Skalan ligger
  // inom paletten så långt den kan: guld för mellanläget (guld = markör och
  // tips i guiden) och skiffer för det svaga läget. Endast det höga läget tar
  // en statusfärg, eftersom grönt är den enda signal en förare läser som
  // "det här är värt att köra på" utan att först läsa etiketten.
  static const likelihoodHigh = live;
  static const likelihoodMedium = guldDjup;
  static const likelihoodLow = skiffer;

  // Alias. Namnen fanns före varumärkesbytet och används på ~150 ställen i
  // appen; de pekar nu på paletten i stället för på den gamla marinblå/cyan-
  // uppsättningen. Cyan finns inte kvar som varumärkesfärg: den pekade både
  // på "hög allvarlighetsgrad" i ena kartläget och på "tåg" i det andra, så
  // den delas nu upp på skiffer (UI-krom) och midnatt (länkar).
  static const navy = midnatt;
  static const navyDeep = midnattDjup;
  static const foam = ljusgra;
  static const sand = ljusgraDjup;
  static const yellow = guld;
  static const yellowDeep = guldDjup;
  static const cyan = skiffer;
  static const cyanDeep = midnatt;
  static const ink = midnatt;
  static const muted = skiffer;
  static const asphalt = midnatt;
  static const road = midnattDjup;
  static const taxi = guld;
  static const taxiDeep = guldDjup;
  static const signal = skiffer;
}

/// Montserrat i rubriker och logotyp, Inter i brödtext och gränssnitt.
/// Guiden slutar på Bold 700 — inga tyngre vikter finns i de medföljande
/// typsnittsfilerna, så w800/w900 skulle bara falla tillbaka på 700 ändå.
const String kDisplayFont = 'Montserrat';
const String kBodyFont = 'Inter';

ThemeData buildTaxiTheme() {
  const scheme = ColorScheme(
    brightness: Brightness.light,
    primary: TbColors.guld,
    onPrimary: TbColors.midnatt,
    secondary: TbColors.midnatt,
    onSecondary: TbColors.vit,
    error: TbColors.danger,
    onError: TbColors.vit,
    surface: TbColors.vit,
    onSurface: TbColors.midnatt,
    surfaceContainerHighest: TbColors.ljusgraDjup,
    outline: TbColors.line,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: TbColors.ljusgra,
    fontFamily: kBodyFont,
    appBarTheme: const AppBarTheme(
      backgroundColor: TbColors.midnatt,
      foregroundColor: TbColors.vit,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontFamily: kDisplayFont,
        color: TbColors.vit,
        fontSize: 20,
        fontWeight: FontWeight.w700,
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: TbColors.guld,
        foregroundColor: TbColors.midnatt,
        // Size.fromHeight uses infinite width and breaks buttons inside Row.
        minimumSize: const Size(64, 52),
        textStyle: const TextStyle(
          fontFamily: kBodyFont,
          fontWeight: FontWeight.w600,
          fontSize: 16,
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: TbColors.midnatt,
        side: const BorderSide(color: TbColors.line, width: 1.5),
        minimumSize: const Size(64, 48),
        textStyle: const TextStyle(
          fontFamily: kBodyFont,
          fontWeight: FontWeight.w600,
          fontSize: 16,
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: TbColors.midnatt,
        textStyle: const TextStyle(
          fontFamily: kBodyFont,
          fontWeight: FontWeight.w600,
        ),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: TbColors.vit,
      selectedColor: TbColors.guld,
      disabledColor: TbColors.ljusgraDjup,
      labelStyle: const TextStyle(
        fontFamily: kBodyFont,
        fontWeight: FontWeight.w600,
        color: TbColors.midnatt,
      ),
      secondaryLabelStyle: const TextStyle(
        fontFamily: kBodyFont,
        fontWeight: FontWeight.w600,
        color: TbColors.midnatt,
      ),
      side: const BorderSide(color: TbColors.line),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: TbColors.vit,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: TbColors.line, width: 1.5),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: TbColors.midnatt, width: 2),
      ),
    ),
    cardTheme: CardThemeData(
      color: TbColors.vit,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: TbColors.line),
      ),
    ),
    listTileTheme: const ListTileThemeData(
      textColor: TbColors.midnatt,
      iconColor: TbColors.midnatt,
      titleTextStyle: TextStyle(
        fontFamily: kDisplayFont,
        color: TbColors.midnatt,
        fontWeight: FontWeight.w600,
        fontSize: 16,
      ),
      subtitleTextStyle: TextStyle(
        fontFamily: kBodyFont,
        color: TbColors.skiffer,
        fontSize: 13,
      ),
    ),
    textTheme: const TextTheme(
      headlineLarge: TextStyle(
        fontFamily: kDisplayFont,
        color: TbColors.midnatt,
        fontWeight: FontWeight.w700,
      ),
      headlineMedium: TextStyle(
        fontFamily: kDisplayFont,
        color: TbColors.midnatt,
        fontWeight: FontWeight.w700,
      ),
      headlineSmall: TextStyle(
        fontFamily: kDisplayFont,
        color: TbColors.midnatt,
        fontWeight: FontWeight.w700,
      ),
      titleLarge: TextStyle(
        fontFamily: kDisplayFont,
        color: TbColors.midnatt,
        fontWeight: FontWeight.w700,
      ),
      titleMedium: TextStyle(
        fontFamily: kDisplayFont,
        color: TbColors.midnatt,
        fontWeight: FontWeight.w600,
      ),
      titleSmall: TextStyle(
        fontFamily: kDisplayFont,
        color: TbColors.midnatt,
        fontWeight: FontWeight.w600,
      ),
      bodyLarge: TextStyle(fontFamily: kBodyFont, color: TbColors.midnatt),
      bodyMedium: TextStyle(fontFamily: kBodyFont, color: TbColors.midnatt),
      bodySmall: TextStyle(fontFamily: kBodyFont, color: TbColors.skiffer),
      labelLarge: TextStyle(
        fontFamily: kBodyFont,
        color: TbColors.midnatt,
        fontWeight: FontWeight.w600,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: TbColors.midnatt,
      indicatorColor: TbColors.guld,
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return TextStyle(
          fontWeight: FontWeight.w600,
          fontSize: 13,
          color: selected ? TbColors.guld : TbColors.vit.withValues(alpha: 0.7),
        );
      }),
      iconTheme: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return IconThemeData(
          color: selected
              ? TbColors.midnatt
              : TbColors.vit.withValues(alpha: 0.75),
          size: 26,
        );
      }),
    ),
  );
}
