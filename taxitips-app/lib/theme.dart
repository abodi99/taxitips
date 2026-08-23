import 'package:flutter/material.dart';

/// taxitips brand — Canva kit TaxiTips
class TbColors {
  static const navy = Color(0xFF08254C);
  static const navyDeep = Color(0xFF051A36);
  static const foam = Color(0xFFF8F7F2);
  static const sand = Color(0xFFEFEEE8);
  static const yellow = Color(0xFFFFC400);
  static const yellowDeep = Color(0xFFE0AC00);
  static const cyan = Color(0xFF19C2D1);
  static const cyanDeep = Color(0xFF1098A6);
  static const live = Color(0xFF1F8A5B);
  static const ink = Color(0xFF08254C);
  static const muted = Color(0xFF3D4F6A);
  static const danger = Color(0xFFC0392B);

  // aliases
  static const asphalt = navy;
  static const road = navyDeep;
  static const taxi = yellow;
  static const taxiDeep = yellowDeep;
  static const signal = cyan;
}

ThemeData buildTaxiTheme() {
  const scheme = ColorScheme(
    brightness: Brightness.light,
    primary: TbColors.yellow,
    onPrimary: TbColors.navy,
    secondary: TbColors.cyan,
    onSecondary: Colors.white,
    error: TbColors.danger,
    onError: Colors.white,
    surface: Colors.white,
    onSurface: TbColors.ink,
    surfaceContainerHighest: TbColors.sand,
    outline: Color(0xFFC9D0DA),
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: TbColors.foam,
    fontFamily: 'Roboto',
    appBarTheme: const AppBarTheme(
      backgroundColor: TbColors.navy,
      foregroundColor: TbColors.foam,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: TbColors.foam,
        fontSize: 20,
        fontWeight: FontWeight.w800,
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: TbColors.yellow,
        foregroundColor: TbColors.navy,
        // Size.fromHeight uses infinite width and breaks buttons inside Row.
        minimumSize: const Size(64, 52),
        textStyle: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: TbColors.ink,
        side: const BorderSide(color: Color(0xFFC9D0DA), width: 1.5),
        minimumSize: const Size(64, 48),
        textStyle: const TextStyle(fontWeight: FontWeight.w700),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: TbColors.cyanDeep,
        textStyle: const TextStyle(fontWeight: FontWeight.w700),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: Colors.white,
      selectedColor: TbColors.yellow,
      disabledColor: TbColors.sand,
      labelStyle: const TextStyle(fontWeight: FontWeight.w700, color: TbColors.ink),
      secondaryLabelStyle: const TextStyle(fontWeight: FontWeight.w700, color: TbColors.ink),
      side: const BorderSide(color: Color(0xFFC9D0DA)),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Color(0xFFC9D0DA), width: 1.5),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: TbColors.cyan, width: 2),
      ),
    ),
    cardTheme: CardThemeData(
      color: Colors.white,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: Color(0xFFC9D0DA)),
      ),
    ),
    listTileTheme: const ListTileThemeData(
      textColor: TbColors.ink,
      iconColor: TbColors.ink,
      titleTextStyle: TextStyle(color: TbColors.ink, fontWeight: FontWeight.w800, fontSize: 16),
      subtitleTextStyle: TextStyle(color: TbColors.muted, fontSize: 13),
    ),
    textTheme: const TextTheme(
      bodyLarge: TextStyle(color: TbColors.ink),
      bodyMedium: TextStyle(color: TbColors.ink),
      bodySmall: TextStyle(color: TbColors.muted),
      titleLarge: TextStyle(color: TbColors.ink, fontWeight: FontWeight.w900),
      titleMedium: TextStyle(color: TbColors.ink, fontWeight: FontWeight.w800),
      titleSmall: TextStyle(color: TbColors.ink, fontWeight: FontWeight.w700),
      labelLarge: TextStyle(color: TbColors.ink, fontWeight: FontWeight.w700),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: TbColors.navy,
      indicatorColor: TbColors.yellow,
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return TextStyle(
          fontWeight: FontWeight.w800,
          fontSize: 13,
          color: selected ? TbColors.yellow : TbColors.foam.withValues(alpha: 0.7),
        );
      }),
      iconTheme: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return IconThemeData(
          color: selected ? TbColors.navy : TbColors.foam.withValues(alpha: 0.75),
          size: 26,
        );
      }),
    ),
  );
}
