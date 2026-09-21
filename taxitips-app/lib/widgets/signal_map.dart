import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../signal_kinds.dart';
import '../theme.dart';
import 'ferry_event_widgets.dart';
import 'signal_marker.dart';

/// En sak på kartan: ett tips, ett väghinder eller ett evenemang.
///
/// Byggs av förarskärmen, som vet vad som är filtrerat bort. Kartan vet bara
/// hur det ska ritas -- så att filtret och kartan aldrig kan säga olika saker.
class MapItem {
  const MapItem({
    required this.id,
    required this.lat,
    required this.lon,
    required this.category,
    required this.strength,
    required this.icon,
    required this.onTap,
    this.followed = false,
  });

  final String id;
  final double lat;
  final double lon;
  final SignalCategory category;
  final SignalStrength strength;
  final IconData icon;
  final VoidCallback onTap;
  final bool followed;

  bool get hazard => category == SignalCategory.road;
  LatLng get point => LatLng(lat, lon);
}

/// CARTO-nyckeln för bakgrundskartan. Skickas in vid bygget
/// (`--dart-define-from-file=dart_defines.local.json`) och checkas aldrig in --
/// repot är publikt. Utan nyckel ritas Esri i stället: CARTO stämplar annars
/// "API KEY REQUIRED" över varje ruta.
const String kCartoKey = String.fromEnvironment('CARTO_KEY');

/// Zoomnivån där klustren löses upp: på gatunivå ska varje sak synas för sig.
const double kClusterUntilZoom = 15;

/// Grupperar symboler som skulle rita över varandra vid [zoom].
///
/// Rutnät i skärmpixlar (Web Mercator), `cellPx` brett. Väghinder och övrigt
/// grupperas var för sig: en triangel får aldrig gömmas i en rund bubbla och
/// läsas som "kör hit". Ordningen inom en grupp är den starkaste först.
List<List<MapItem>> clusterItems(
  List<MapItem> items,
  double zoom, {
  double cellPx = 64,
}) {
  if (zoom >= kClusterUntilZoom) {
    return [
      for (final i in items) [i],
    ];
  }
  final scale = 256 * math.pow(2, zoom);
  final groups = <String, List<MapItem>>{};
  for (final item in items) {
    final x = (item.lon + 180) / 360 * scale;
    final lat = item.lat.clamp(-85.0, 85.0) * math.pi / 180;
    final y =
        (1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * scale;
    final key =
        '${item.hazard ? 'h' : 'o'}:${(x / cellPx).floor()}:${(y / cellPx).floor()}';
    groups.putIfAbsent(key, () => []).add(item);
  }
  return [
    for (final group in groups.values)
      group..sort((a, b) => a.strength.index.compareTo(b.strength.index)),
  ];
}

class SignalMap extends StatefulWidget {
  const SignalMap({
    super.key,
    required this.items,
    required this.mapController,
    this.ferries = const [],
    this.ferryTerminals = const [],
    this.onSelectFerry,
    this.userLat,
    this.userLon,
    this.selectedId,
  });

  final List<MapItem> items;
  final MapController mapController;
  final List<Map<String, dynamic>> ferries;
  final List<Map<String, dynamic>> ferryTerminals;
  final ValueChanged<Map<String, dynamic>>? onSelectFerry;
  final double? userLat;
  final double? userLon;
  final String? selectedId;

  @override
  State<SignalMap> createState() => _SignalMapState();
}

class _SignalMapState extends State<SignalMap> {
  double _zoom = 5;

  static final _swedenBounds = LatLngBounds(
    const LatLng(55.2, 10.5),
    const LatLng(69.2, 24.5),
  );

  // Skapas EN gång. FlutterMap jämför options med ==, och nya instanser vid
  // varje ombyggnad gjorde kameran hoppig under zoom.
  late final MapOptions _options = MapOptions(
    initialCenter: const LatLng(62.0, 15.0),
    initialZoom: 5.0,
    initialCameraFit: CameraFit.bounds(
      bounds: _swedenBounds,
      padding: const EdgeInsets.all(16),
      maxZoom: 6.0,
    ),
    cameraConstraint: const CameraConstraint.containLatitude(),
    backgroundColor: TbColors.ljusgra,
    minZoom: 4.0,
    maxZoom: 18,
    interactionOptions: const InteractionOptions(
      flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
      enableMultiFingerGestureRace: true,
      rotationThreshold: 25,
    ),
    onPositionChanged: _onMove,
  );

  void _onMove(MapCamera camera, bool hasGesture) {
    // Halva zoomsteg räcker: klustren behöver inte räknas om för varje pixel.
    final bucket = (camera.zoom * 2).floor() / 2;
    if (bucket != _zoom && mounted) setState(() => _zoom = bucket);
  }

  void _openCluster(List<MapItem> group) {
    final points = [for (final i in group) i.point];
    final bounds = LatLngBounds.fromPoints(points);
    final spread = bounds.north - bounds.south + bounds.east - bounds.west;
    try {
      if (spread < 0.0005) {
        widget.mapController.move(
          points.first,
          math.max(_zoom + 2, kClusterUntilZoom),
        );
      } else {
        widget.mapController.fitCamera(
          CameraFit.bounds(
            bounds: bounds,
            padding: const EdgeInsets.all(90),
            maxZoom: 17,
          ),
        );
      }
    } catch (_) {
      // Kartan är inte ritad än.
    }
  }

  List<Marker> _itemMarkers() {
    final out = <Marker>[];
    for (final group in clusterItems(widget.items, _zoom)) {
      final first = group.first;
      if (group.length == 1) {
        final selected = first.id == widget.selectedId;
        final head = pinHead(first.strength) + (selected ? 6 : 0);
        out.add(
          Marker(
            point: first.point,
            width: first.hazard ? head + 12 : head + 12,
            height: first.hazard ? head + 8 : head + 9,
            // Nålens spets pekar på platsen; triangeln står mitt på den.
            alignment: first.hazard ? Alignment.center : Alignment.topCenter,
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: first.onTap,
              child: first.hazard
                  ? HazardSign(
                      icon: first.icon,
                      strength: first.strength,
                      followed: first.followed,
                      selected: selected,
                    )
                  : SignalPin(
                      icon: first.icon,
                      strength: first.strength,
                      category: first.category,
                      followed: first.followed,
                      selected: selected,
                    ),
            ),
          ),
        );
        continue;
      }
      final center = LatLng(
        group.map((i) => i.lat).reduce((a, b) => a + b) / group.length,
        group.map((i) => i.lon).reduce((a, b) => a + b) / group.length,
      );
      final categories = {for (final i in group) i.category};
      out.add(
        Marker(
          point: center,
          width: 64,
          height: 64,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => _openCluster(group),
            child: Center(
              child: ClusterBubble(
                count: group.length,
                strength: first.strength,
                hazard: first.hazard,
                category: categories.length == 1 ? categories.first : null,
              ),
            ),
          ),
        ),
      );
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    // Färjorna: terminalerna som små ankare, fartygen som pilar i sin kurs, och
    // en streckad linje till terminalen för dem som är på väg in eller lägger till.
    final terminals = <String, LatLng>{};
    final terminalMarkers = <Marker>[];
    for (final t in widget.ferryTerminals) {
      final lat = (t['lat'] as num?)?.toDouble();
      final lon = (t['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      terminals[t['key']?.toString() ?? ''] = LatLng(lat, lon);
      terminalMarkers.add(
        Marker(
          point: LatLng(lat, lon),
          width: 24,
          height: 24,
          child: Container(
            decoration: BoxDecoration(
              color: TbColors.vit,
              shape: BoxShape.circle,
              border: Border.all(color: TbColors.midnatt, width: 2),
            ),
            child: const Icon(Icons.anchor, size: 13, color: TbColors.midnatt),
          ),
        ),
      );
    }
    final ferryMarkers = <Marker>[];
    final ferryLines = <Polyline>[];
    for (final f in widget.ferries) {
      final lat = (f['lat'] as num?)?.toDouble();
      final lon = (f['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final status = f['status']?.toString();
      final terminal = terminals[f['terminal']?.toString() ?? ''];
      if (terminal != null &&
          (status == 'approaching' || status == 'docking')) {
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
          width: 44,
          height: 44,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: widget.onSelectFerry == null
                ? null
                : () => widget.onSelectFerry!(f),
            child: Center(
              child: FerryArrow(status: status, course: f['course'] as num?),
            ),
          ),
        ),
      );
    }

    return FlutterMap(
      mapController: widget.mapController,
      options: _options,
      children: [
        // CARTO Voyager: ljus, lugn gatukarta i samma stil som de vanliga
        // kartapparna -- symbolerna syns, bakgrunden gör det inte. Skarpa
        // @2x-rutor på täta skärmar. Ofiltrerad och alltid ljus: en mörk
        // variant upplevdes som för mörk i bilen. Esri är reserven när bygget
        // saknar nyckel.
        if (kCartoKey.isNotEmpty)
          TileLayer(
            urlTemplate:
                'https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png?key={key}',
            additionalOptions: const {'key': kCartoKey},
            retinaMode: RetinaMode.isHighDensity(context),
            userAgentPackageName: 'se.taxibehov.taxibehov_app',
            maxNativeZoom: 20,
          )
        else
          TileLayer(
            urlTemplate:
                'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
            userAgentPackageName: 'se.taxibehov.taxibehov_app',
            maxNativeZoom: 19,
          ),
        SimpleAttributionWidget(
          source: Text(
            kCartoKey.isNotEmpty
                ? '© CARTO · OpenStreetMap'
                : '© Esri · OpenStreetMap',
          ),
          alignment: Alignment.bottomLeft,
          backgroundColor: TbColors.vit.withValues(alpha: 0.7),
        ),
        if (ferryLines.isNotEmpty) PolylineLayer(polylines: ferryLines),
        if (terminalMarkers.isNotEmpty) MarkerLayer(markers: terminalMarkers),
        MarkerLayer(markers: _itemMarkers()),
        if (ferryMarkers.isNotEmpty) MarkerLayer(markers: ferryMarkers),
        // Egen lager överst -- annars täcks "du är här" av nålar.
        if (widget.userLat != null && widget.userLon != null)
          MarkerLayer(
            markers: [
              Marker(
                point: LatLng(widget.userLat!, widget.userLon!),
                width: 56,
                height: 56,
                child: const IgnorePointer(child: _UserDot()),
              ),
            ],
          ),
      ],
    );
  }
}

/// Blå prick med ring -- "du är här", samma som i telefonens egen karta.
class _UserDot extends StatelessWidget {
  const _UserDot();

  @override
  Widget build(BuildContext context) {
    return Stack(
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
    );
  }
}
