import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../severity_labels.dart';
import '../theme.dart';
import 'brand_icons.dart';
import 'ferry_event_widgets.dart';

class HotspotMap extends StatelessWidget {
  const HotspotMap({
    super.key,
    required this.placeStats,
    required this.events,
    this.userLat,
    this.userLon,
    this.selectedPlace,
    this.onSelectPlace,
    this.onSelectOpportunity,
    this.highOnly = false,
    this.perOpportunity = false,
    this.opportunities = const [],
    this.mapController,
    this.ferries = const [],
    this.ferryTerminals = const [],
    this.onSelectFerry,
    this.onSelectEvent,
  });

  final List<Map<String, dynamic>> placeStats;
  final List<Map<String, dynamic>> events;
  final double? userLat;
  final double? userLon;
  final String? selectedPlace;
  final ValueChanged<String?>? onSelectPlace;
  final MapController? mapController;
  final ValueChanged<Map<String, dynamic>>? onSelectOpportunity;
  final bool highOnly;
  final bool perOpportunity;
  final List<Map<String, dynamic>> opportunities;
  // Färjor på väg in och deras terminaler -- se /api/ferries.
  final List<Map<String, dynamic>> ferries;
  final List<Map<String, dynamic>> ferryTerminals;
  final ValueChanged<Map<String, dynamic>>? onSelectFerry;
  final ValueChanged<Map<String, dynamic>>? onSelectEvent;

  // Statiska referenser så MapOptions == håller mellan rebuilds. FlutterMap
  // jämför options med ==; nya CameraFit-instanser varje poll gjorde att
  // options byttes under zoom och kameran kändes hoppig.
  static final _swedenBounds = LatLngBounds(
    const LatLng(55.2, 10.5),
    const LatLng(69.2, 24.5),
  );

  static final _initialFit = CameraFit.bounds(
    bounds: _swedenBounds,
    padding: const EdgeInsets.all(16),
    maxZoom: 6.0,
  );

  static const _interaction = InteractionOptions(
    flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
    enableMultiFingerGestureRace: true,
    rotationThreshold: 25,
  );

  static final _options = MapOptions(
    initialCenter: const LatLng(62.0, 15.0),
    initialZoom: 5.0,
    initialCameraFit: _initialFit,
    cameraConstraint: const CameraConstraint.containLatitude(),
    backgroundColor: TbColors.ljusgra,
    minZoom: 4.0,
    maxZoom: 18,
    interactionOptions: _interaction,
  );

  static Widget _modeGlyph(String? mode) {
    return BrandIcons.forMode(mode, size: 18, color: TbColors.vit);
  }

  @override
  Widget build(BuildContext context) {
    final tipMarkers = <Marker>[];
    final userMarkers = <Marker>[];

    if (perOpportunity) {
      for (final o in opportunities) {
        final lat = (o['lat'] as num?)?.toDouble();
        final lon = (o['lon'] as num?)?.toDouble();
        if (lat == null || lon == null) continue;
        final likelihood = likelihoodForAlert(o);
        tipMarkers.add(
          Marker(
            point: LatLng(lat, lon),
            width: 40,
            height: 48,
            alignment: Alignment.bottomCenter,
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: () => onSelectOpportunity != null
                  ? onSelectOpportunity!(o)
                  : onSelectPlace?.call(o['title']?.toString()),
              child: _TipPin(
                likelihood: likelihood,
                child: _modeGlyph(o['mode']?.toString()),
              ),
            ),
          ),
        );
      }
    } else {
      for (final p in placeStats) {
        if (highOnly && p['maxLevel'] != 'high') continue;
        final lat = (p['lat'] as num?)?.toDouble();
        final lon = (p['lon'] as num?)?.toDouble();
        if (lat == null || lon == null) continue;
        final level = p['maxLevel']?.toString() ?? 'low';
        final count = (p['count'] as num?)?.toInt() ?? 0;
        final name = p['name']?.toString() ?? '';
        final likelihood = switch (level) {
          'high' => CustomerLikelihood.high,
          'medium' => CustomerLikelihood.medium,
          _ => CustomerLikelihood.low,
        };
        tipMarkers.add(
          Marker(
            point: LatLng(lat, lon),
            width: 40,
            height: 48,
            alignment: Alignment.bottomCenter,
            child: GestureDetector(
              onTap: () => onSelectPlace?.call(name),
              child: _TipPin(
                likelihood: likelihood,
                child: Text(
                  '$count',
                  style: const TextStyle(
                    fontFamily: kDisplayFont,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                    color: TbColors.vit,
                    height: 1,
                  ),
                ),
              ),
            ),
          ),
        );
      }
    }

    for (final e in events) {
      final lat = (e['lat'] as num?)?.toDouble();
      final lon = (e['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      tipMarkers.add(
        Marker(
          point: LatLng(lat, lon),
          width: 36,
          height: 44,
          alignment: Alignment.bottomCenter,
          child: GestureDetector(
            onTap: () => onSelectEvent != null
                ? onSelectEvent!(e)
                : onSelectPlace?.call(
                    e['place']?.toString() ?? e['city']?.toString(),
                  ),
            child: const _TipPin(
              likelihood: CustomerLikelihood.medium,
              fillOverride: TbColors.midnatt,
              child: Text(
                'E',
                style: TextStyle(
                  fontFamily: kDisplayFont,
                  color: TbColors.vit,
                  fontWeight: FontWeight.w700,
                  fontSize: 13,
                  height: 1,
                ),
              ),
            ),
          ),
        ),
      );
    }

    // Färjorna: terminalerna som små ankare, fartygen som pilar i sin kurs, och en
    // streckad linje till terminalen för dem som är på väg in eller lägger till.
    final terminalMarkers = <Marker>[];
    final terminals = <String, LatLng>{};
    for (final t in ferryTerminals) {
      final lat = (t['lat'] as num?)?.toDouble();
      final lon = (t['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      terminals[t['key']?.toString() ?? ''] = LatLng(lat, lon);
      terminalMarkers.add(
        Marker(
          point: LatLng(lat, lon),
          width: 22,
          height: 22,
          child: Container(
            decoration: BoxDecoration(
              color: TbColors.vit,
              shape: BoxShape.circle,
              border: Border.all(color: TbColors.midnatt, width: 2),
            ),
            child: const Icon(Icons.anchor, size: 12, color: TbColors.midnatt),
          ),
        ),
      );
    }
    final ferryMarkers = <Marker>[];
    final ferryLines = <Polyline>[];
    for (final f in ferries) {
      final lat = (f['lat'] as num?)?.toDouble();
      final lon = (f['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final status = f['status']?.toString();
      final terminal = terminals[f['terminal']?.toString() ?? ''];
      if (terminal != null && (status == 'approaching' || status == 'docking')) {
        ferryLines.add(
          Polyline(
            points: [LatLng(lat, lon), terminal],
            color: ferryColor(status).withValues(alpha: 0.85),
            strokeWidth: 3,
            pattern: StrokePattern.dashed(segments: const [10, 8]),
          ),
        );
      }
      ferryMarkers.add(
        Marker(
          point: LatLng(lat, lon),
          width: 36,
          height: 36,
          child: GestureDetector(
            onTap: onSelectFerry == null ? null : () => onSelectFerry!(f),
            child: FerryArrow(status: status, course: f['course'] as num?),
          ),
        ),
      );
    }

    if (userLat != null && userLon != null) {
      userMarkers.add(
        Marker(
          point: LatLng(userLat!, userLon!),
          width: 56,
          height: 56,
          alignment: Alignment.center,
          child: const IgnorePointer(child: _UserDot()),
        ),
      );
    }

    return FlutterMap(
      mapController: mapController,
      options: _options,
      children: [
        // Carto basemaps vattenstämplar "API KEY REQUIRED" utan nyckel
        // (HTTP 200 med watermark). Esri World Street Map är gratis raster
        // utan nyckel; notera z/y/x (inte z/x/y).
        TileLayer(
          urlTemplate:
              'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
          userAgentPackageName: 'se.taxibehov.taxibehov_app',
          maxNativeZoom: 19,
        ),
        SimpleAttributionWidget(
          source: const Text('© Esri · OpenStreetMap'),
          alignment: Alignment.bottomLeft,
          backgroundColor: TbColors.vit.withValues(alpha: 0.7),
        ),
        if (ferryLines.isNotEmpty) PolylineLayer(polylines: ferryLines),
        MarkerLayer(markers: tipMarkers),
        if (terminalMarkers.isNotEmpty || ferryMarkers.isNotEmpty)
          MarkerLayer(markers: [...terminalMarkers, ...ferryMarkers]),
        // Egen lager ovanpå tippsen — annars täcks "du är här" av nålar.
        if (userMarkers.isNotEmpty) MarkerLayer(markers: userMarkers),
      ],
    );
  }
}

/// Gul prick med vit ring — "du är här". Större än tippins så den syns
/// ovanpå täta knippen utan att se ut som ett tips.
class _UserDot extends StatelessWidget {
  const _UserDot();

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 56,
      height: 56,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: const Color(0xFF4285F4).withValues(alpha: 0.22),
              shape: BoxShape.circle,
            ),
          ),
          Container(
            width: 22,
            height: 22,
            decoration: BoxDecoration(
              color: const Color(0xFF4285F4),
              shape: BoxShape.circle,
              border: Border.all(color: TbColors.vit, width: 3),
              boxShadow: const [
                BoxShadow(
                  blurRadius: 10,
                  offset: Offset(0, 2),
                  color: Color(0x88000000),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Kartnål: cirkel + spets. Fyllnadsfärg = prio (ikon/siffra alltid vit).
/// Spetsen sitter i botten så alignment.bottomCenter pekar på koordinaten.
class _TipPin extends StatelessWidget {
  const _TipPin({
    required this.likelihood,
    required this.child,
    this.fillOverride,
  });

  final CustomerLikelihood likelihood;
  final Widget child;
  final Color? fillOverride;

  Color get _fill =>
      fillOverride ??
      switch (likelihood) {
        CustomerLikelihood.high => TbColors.likelihoodHigh,
        CustomerLikelihood.medium => TbColors.likelihoodMedium,
        CustomerLikelihood.low => TbColors.midnatt,
      };

  double get _head => switch (likelihood) {
    CustomerLikelihood.high => 34,
    CustomerLikelihood.medium => 30,
    CustomerLikelihood.low => 28,
  };

  @override
  Widget build(BuildContext context) {
    final head = _head;
    final fill = _fill;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: head,
          height: head,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: fill,
            shape: BoxShape.circle,
            border: Border.all(color: TbColors.vit, width: 2.5),
            boxShadow: const [
              BoxShadow(
                blurRadius: 6,
                offset: Offset(0, 2),
                color: Color(0x55000000),
              ),
            ],
          ),
          child: child,
        ),
        CustomPaint(
          size: const Size(12, 8),
          painter: _PinTipPainter(fill),
        ),
      ],
    );
  }
}

class _PinTipPainter extends CustomPainter {
  _PinTipPainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final path = ui.Path()
      ..moveTo(0, 0)
      ..lineTo(size.width / 2, size.height)
      ..lineTo(size.width, 0)
      ..close();
    canvas.drawPath(path, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant _PinTipPainter old) => old.color != color;
}
