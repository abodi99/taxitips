import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../theme.dart';

/// Varumärkets 12 funktionsikoner från taxitips2.
///
/// Varje ikon är en 24 × 24-SVG med 1,8 px linjebredd och rundade ändar.
/// Originalen har midnatt (#14213D) som stroke-färg; [colorFilter] byter
/// den vid behov (vitt på mörk bakgrund, guld för aktivt val).
///
/// Guiden: "Använd midnatt på ljust och vitt på mörkt. Gul accent markerar
/// ett aktivt val."
class BrandIcons {
  BrandIcons._();

  static const _base = 'assets/brand/icons';

  /// Bygger en SVG-ikon med valfri storlek och färg.
  static Widget _icon(
    String name, {
    double size = 24,
    Color color = TbColors.midnatt,
  }) {
    return SvgPicture.asset(
      '$_base/$name.svg',
      width: size,
      height: size,
      colorFilter: ColorFilter.mode(color, BlendMode.srcIn),
    );
  }

  // ── De tolv funktionsikonerna ──────────────────────────────

  /// Buss — kollektivtrafik (SL, Västtrafik, Trafiklab).
  static Widget bus({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('bus', size: size, color: color);

  /// Klocka — tidsinformation, nästa avgång.
  static Widget clock({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('clock', size: size, color: color);

  /// Förare — förarlistor, teamöversikt.
  static Widget drivers({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('drivers', size: size, color: color);

  /// Filter — filtrera tipslistan.
  static Widget filter({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('filter', size: size, color: color);

  /// Hotspot — plats med hög sannolikhet.
  static Widget hotspot({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('hotspot', size: size, color: color);

  /// Kartnål — geografisk plats.
  static Widget mapPin({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('map-pin', size: size, color: color);

  /// Notis — push-notifikation.
  static Widget notification({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('notification', size: size, color: color);

  /// Kontor — bolagsvy, administration.
  static Widget office({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('office', size: size, color: color);

  /// Rutt — resväg, alternativ.
  static Widget route({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('route', size: size, color: color);

  /// Taxi — taxirelevans, fordonsvy.
  static Widget taxi({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('taxi', size: size, color: color);

  /// Trafikstörning — varningstriangel.
  static Widget trafficAlert({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('traffic-alert', size: size, color: color);

  /// Tåg — järnvägstrafik.
  static Widget train({double size = 24, Color color = TbColors.midnatt}) =>
      _icon('train', size: size, color: color);
}
