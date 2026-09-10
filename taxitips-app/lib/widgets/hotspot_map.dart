import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../severity_labels.dart';
import '../theme.dart';
import 'brand_icons.dart';

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
    const c = TbColors.vit;
    return switch (mode) {
      'train' => BrandIcons.train(size: 18, color: c),
      'metro' => const Icon(Icons.subway, size: 18, color: c),
      'tram' => const Icon(Icons.tram, size: 18, color: c),
      'bus' => BrandIcons.bus(size: 18, color: c),
      _ => BrandIcons.taxi(size: 18, color: c),
    };
  }

  @override
  Widget build(BuildContext context) {
    final markers = <Marker>[];

    if (perOpportunity) {
      for (final o in opportunities) {
        final lat = (o['lat'] as num?)?.toDouble();
        final lon = (o['lon'] as num?)?.toDouble();
        if (lat == null || lon == null) continue;
        final likelihood = likelihoodForAlert(o);
        markers.add(
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
        markers.add(
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
      markers.add(
        Marker(
          point: LatLng(lat, lon),
          width: 36,
          height: 44,
          alignment: Alignment.bottomCenter,
          child: GestureDetector(
            onTap: () => onSelectPlace?.call(
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

    if (userLat != null && userLon != null) {
      markers.add(
        Marker(
          point: LatLng(userLat!, userLon!),
          width: 22,
          height: 22,
          child: Container(
            decoration: BoxDecoration(
              color: TbColors.guld,
              shape: BoxShape.circle,
              border: Border.all(color: TbColors.vit, width: 3),
              boxShadow: const [
                BoxShadow(
                  blurRadius: 8,
                  offset: Offset(0, 2),
                  color: Color(0x66000000),
                ),
              ],
            ),
          ),
        ),
      );
    }

    return FlutterMap(
      mapController: mapController,
      options: _options,
      children: [
        TileLayer(
          urlTemplate: 'https://tile.openstreetmap.de/{z}/{x}/{y}.png',
          userAgentPackageName: 'se.taxibehov.app',
        ),
        SimpleAttributionWidget(
          source: const Text('© OpenStreetMap'),
          alignment: Alignment.bottomLeft,
          backgroundColor: TbColors.vit.withValues(alpha: 0.7),
        ),
        MarkerLayer(markers: markers),
      ],
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
