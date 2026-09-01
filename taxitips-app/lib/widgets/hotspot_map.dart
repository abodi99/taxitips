import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../theme.dart';

class HotspotMap extends StatelessWidget {
  const HotspotMap({
    super.key,
    required this.placeStats,
    required this.events,
    this.userLat,
    this.userLon,
    this.selectedPlace,
    this.onSelectPlace,
    this.highOnly = false,
    this.perOpportunity = false,
    this.opportunities = const [],
  });

  final List<Map<String, dynamic>> placeStats;
  final List<Map<String, dynamic>> events;
  final double? userLat;
  final double? userLon;
  final String? selectedPlace;
  final ValueChanged<String?>? onSelectPlace;
  final bool highOnly;

  /// When true, show one marker per opportunity (colored/labeled by transport
  /// mode, with distance-from-driver) instead of the default place-aggregated
  /// view. Opt-in, not the default -- per-opportunity markers can get noisy with
  /// many simultaneous disruptions, which is exactly the "over-informed" clutter
  /// the place-aggregated view was built to avoid.
  final bool perOpportunity;

  /// Raw opportunity rows from get_smart_alerts (id/title/mode/lat/lon/
  /// distance_km/worth_it_score), only read when [perOpportunity] is true.
  final List<Map<String, dynamic>> opportunities;

  @override
  Widget build(BuildContext context) {
    final markers = <Marker>[];
    final points = <LatLng>[];

    if (perOpportunity) {
      for (final o in opportunities) {
        final lat = (o['lat'] as num?)?.toDouble();
        final lon = (o['lon'] as num?)?.toDouble();
        if (lat == null || lon == null) continue;
        final mode = o['mode']?.toString();
        final distanceKm = (o['distance_km'] as num?)?.toDouble();
        final point = LatLng(lat, lon);
        points.add(point);
        final color = mode == 'train'
            ? TbColors.signal
            : mode == 'bus'
                ? TbColors.taxi
                : TbColors.muted; // road / unknown
        final icon = mode == 'train'
            ? Icons.train
            : mode == 'bus'
                ? Icons.directions_bus
                : Icons.directions_car;
        markers.add(
          Marker(
            point: point,
            width: 64,
            height: 58,
            alignment: Alignment.bottomCenter,
            child: GestureDetector(
              onTap: () => onSelectPlace?.call(o['title']?.toString()),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    padding: const EdgeInsets.all(6),
                    decoration: BoxDecoration(
                      color: color,
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 2),
                      boxShadow: const [BoxShadow(blurRadius: 6, color: Colors.black26)],
                    ),
                    child: Icon(icon, size: 16, color: Colors.white),
                  ),
                  if (distanceKm != null)
                    Container(
                      margin: const EdgeInsets.only(top: 2),
                      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(color: const Color(0xFFC9D0DA)),
                      ),
                      child: Text(
                        '${distanceKm.toStringAsFixed(1)} km',
                        style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800, color: TbColors.ink),
                      ),
                    ),
                ],
              ),
            ),
          ),
        );
      }
    }

    for (final p in placeStats) {
      if (perOpportunity) break; // per-opportunity view replaces place aggregation
      if (highOnly && p['maxLevel'] != 'high') continue;
      final lat = (p['lat'] as num?)?.toDouble();
      final lon = (p['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final level = p['maxLevel']?.toString() ?? 'low';
      final count = (p['count'] as num?)?.toInt() ?? 0;
      final name = p['name']?.toString() ?? '';
      final point = LatLng(lat, lon);
      points.add(point);
      final size = level == 'high' ? 44.0 : level == 'medium' ? 36.0 : 30.0;
      final color = level == 'high'
          ? TbColors.signal
          : level == 'medium'
              ? TbColors.taxi
              : const Color(0xFF6B6358);
      markers.add(
        Marker(
          point: point,
          width: size,
          height: size,
          child: GestureDetector(
            onTap: () => onSelectPlace?.call(name),
            child: Container(
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: color,
                shape: BoxShape.circle,
                border: Border.all(color: Colors.white, width: 2),
                boxShadow: const [BoxShadow(blurRadius: 6, color: Colors.black26)],
              ),
              child: Text(
                '$count',
                style: TextStyle(
                  fontWeight: FontWeight.w900,
                  fontSize: 12,
                  color: level == 'high' ? Colors.white : TbColors.ink,
                ),
              ),
            ),
          ),
        ),
      );
    }

    for (final e in events) {
      // Evenemang (inkl. kommande) visas alltid på kartan när de skickas in.
      final lat = (e['lat'] as num?)?.toDouble();
      final lon = (e['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final point = LatLng(lat, lon);
      points.add(point);
      markers.add(
        Marker(
          point: point,
          width: 36,
          height: 36,
          child: GestureDetector(
            onTap: () => onSelectPlace?.call(e['place']?.toString() ?? e['city']?.toString()),
            child: Container(
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: const Color(0xFF2F6FED),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.white, width: 2),
              ),
              child: const Text('E', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900)),
            ),
          ),
        ),
      );
    }

    if (userLat != null && userLon != null) {
      final me = LatLng(userLat!, userLon!);
      points.add(me);
      markers.add(
        Marker(
          point: me,
          width: 18,
          height: 18,
          child: Container(
            decoration: BoxDecoration(
              color: TbColors.taxi,
              shape: BoxShape.circle,
              border: Border.all(color: TbColors.ink, width: 2),
            ),
          ),
        ),
      );
    }

    LatLng center = const LatLng(55.7, 13.2);
    var zoom = 9.0;
    if (points.isNotEmpty) {
      center = points.first;
    }

    return ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: SizedBox(
        height: 220,
        child: FlutterMap(
          options: MapOptions(
            initialCenter: center,
            initialZoom: zoom,
            interactionOptions: const InteractionOptions(flags: InteractiveFlag.all),
          ),
          children: [
            TileLayer(
              urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              userAgentPackageName: 'se.taxibehov.app',
            ),
            MarkerLayer(markers: markers),
          ],
        ),
      ),
    );
  }
}
