import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_map/flutter_map.dart' show MapController;
import 'package:google_maps_flutter/google_maps_flutter.dart' as gm;
import 'package:latlong2/latlong.dart' show LatLng;

import '../theme.dart';
import 'ferry_event_widgets.dart';
import 'signal_map.dart' show MapItem, clusterItems, kClusterUntilZoom;
import 'signal_marker.dart';

/// Google Maps i förarkartan: samma symboler, samma gruppering och samma val
/// som [SignalMap] -- plus Googles eget **trafiklager** (sega vägar i gult och
/// rött), det som gör kartan värd en egen nyckel för en taxiförare.
///
/// Används på Android när bygget har `GOOGLE_MAPS=true` och en Maps-nyckel i
/// `android/local.properties` (`MAPS_API_KEY`). Google Maps utan nyckel avslutar
/// appen, så utan flaggan -- och alltid på webben och iPhone tills en iOS-nyckel
/// finns -- ritas flutter_map som förut.
const bool _googleMapsDefine = bool.fromEnvironment('GOOGLE_MAPS');

bool get useGoogleMaps =>
    _googleMapsDefine && !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

/// Flyttar och zoomar kartan, vilken av de två som visas.
class MapFocus {
  MapFocus(this.flutterMap);

  final MapController flutterMap;
  gm.GoogleMapController? google;

  void move(double lat, double lon, double zoom) {
    final g = google;
    if (g != null) {
      unawaited(g.animateCamera(gm.CameraUpdate.newLatLngZoom(gm.LatLng(lat, lon), zoom)));
      return;
    }
    try {
      flutterMap.move(LatLng(lat, lon), zoom);
    } catch (_) {
      // Kartan är inte ritad än.
    }
  }

  void zoomBy(double delta) {
    final g = google;
    if (g != null) {
      unawaited(g.animateCamera(gm.CameraUpdate.zoomBy(delta)));
      return;
    }
    try {
      final camera = flutterMap.camera;
      flutterMap.move(camera.center, (camera.zoom + delta).clamp(3.0, 18.0));
    } catch (_) {
      // Kartan är inte ritad än.
    }
  }
}

class GoogleSignalMap extends StatefulWidget {
  const GoogleSignalMap({
    super.key,
    required this.items,
    required this.focus,
    this.ferries = const [],
    this.ferryTerminals = const [],
    this.onSelectFerry,
    this.selectedId,
  });

  final List<MapItem> items;
  final MapFocus focus;
  final List<Map<String, dynamic>> ferries;
  final List<Map<String, dynamic>> ferryTerminals;
  final ValueChanged<Map<String, dynamic>>? onSelectFerry;
  final String? selectedId;

  @override
  State<GoogleSignalMap> createState() => _GoogleSignalMapState();
}

class _GoogleSignalMapState extends State<GoogleSignalMap> {
  double _zoom = 5;
  final _icons = _IconCache();

  static final _sweden = gm.LatLngBounds(
    southwest: const gm.LatLng(55.2, 10.5),
    northeast: const gm.LatLng(69.2, 24.5),
  );

  @override
  void dispose() {
    widget.focus.google = null;
    super.dispose();
  }

  void _onCamera(gm.CameraPosition position) {
    // Halva zoomsteg räcker, samma som flutter_map-kartan: klustren behöver
    // inte räknas om för varje pixel.
    final bucket = (position.zoom * 2).floor() / 2;
    if (bucket != _zoom && mounted) setState(() => _zoom = bucket);
  }

  void _openCluster(List<MapItem> group) {
    final g = widget.focus.google;
    if (g == null) return;
    final lats = group.map((i) => i.lat);
    final lons = group.map((i) => i.lon);
    final south = lats.reduce(math.min), north = lats.reduce(math.max);
    final west = lons.reduce(math.min), east = lons.reduce(math.max);
    if ((north - south) + (east - west) < 0.0005) {
      unawaited(g.animateCamera(gm.CameraUpdate.newLatLngZoom(
        gm.LatLng(group.first.lat, group.first.lon),
        math.max(_zoom + 2, kClusterUntilZoom),
      )));
      return;
    }
    unawaited(g.animateCamera(gm.CameraUpdate.newLatLngBounds(
      gm.LatLngBounds(
        southwest: gm.LatLng(south, west),
        northeast: gm.LatLng(north, east),
      ),
      90,
    )));
  }

  Set<gm.Marker> _markers(double ratio) {
    final out = <gm.Marker>{};
    final ready = <Future<void>>[];

    for (final group in clusterItems(widget.items, _zoom)) {
      final first = group.first;
      if (group.length == 1) {
        final selected = first.id == widget.selectedId;
        final key = 'item:${first.hazard}:${first.category.name}:${first.strength.name}:'
            '${first.icon.codePoint}:${first.followed}:$selected';
        final icon = _icons.get(key, ratio, () {
          final head = pinHead(first.strength) + (selected ? 6 : 0);
          return _Spec(
            first.hazard
                ? HazardSign(
                    icon: first.icon, strength: first.strength,
                    followed: first.followed, selected: selected,
                  )
                : SignalPin(
                    icon: first.icon, strength: first.strength, category: first.category,
                    followed: first.followed, selected: selected,
                  ),
            Size(head + 12, first.hazard ? head + 8 : head + 9),
          );
        }, ready);
        if (icon == null) continue;
        out.add(gm.Marker(
          markerId: gm.MarkerId('i:${first.id}'),
          position: gm.LatLng(first.lat, first.lon),
          icon: icon,
          // Nålens spets pekar på platsen; triangeln står mitt på den.
          anchor: first.hazard ? const Offset(0.5, 0.5) : const Offset(0.5, 1.0),
          zIndexInt: selected ? 10 : (first.hazard ? 1 : 2),
          consumeTapEvents: true,
          onTap: first.onTap,
        ));
        continue;
      }
      final categories = {for (final i in group) i.category};
      final category = categories.length == 1 ? categories.first : null;
      final key = 'cluster:${group.length}:${first.strength.name}:${first.hazard}:${category?.name}';
      final icon = _icons.get(key, ratio, () => _Spec(
        Center(
          child: ClusterBubble(
            count: group.length, strength: first.strength,
            hazard: first.hazard, category: category,
          ),
        ),
        const Size(64, 64),
      ), ready);
      if (icon == null) continue;
      out.add(gm.Marker(
        markerId: gm.MarkerId('c:${first.id}:${group.length}'),
        position: gm.LatLng(
          group.map((i) => i.lat).reduce((a, b) => a + b) / group.length,
          group.map((i) => i.lon).reduce((a, b) => a + b) / group.length,
        ),
        icon: icon,
        anchor: const Offset(0.5, 0.5),
        zIndexInt: 3,
        consumeTapEvents: true,
        onTap: () => _openCluster(group),
      ));
    }

    // Färjorna: terminalerna som små ankare, fartygen som pilar i sin kurs.
    for (final t in widget.ferryTerminals) {
      final lat = (t['lat'] as num?)?.toDouble();
      final lon = (t['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final icon = _icons.get('terminal', ratio, () => _Spec(
        Container(
          decoration: BoxDecoration(
            color: TbColors.vit,
            shape: BoxShape.circle,
            border: Border.all(color: TbColors.midnatt, width: 2),
          ),
          child: const Icon(Icons.anchor, size: 13, color: TbColors.midnatt),
        ),
        const Size(24, 24),
      ), ready);
      if (icon == null) continue;
      out.add(gm.Marker(
        markerId: gm.MarkerId('t:${t['key']}'),
        position: gm.LatLng(lat, lon),
        icon: icon,
        anchor: const Offset(0.5, 0.5),
        zIndexInt: 0,
      ));
    }
    for (final (i, f) in widget.ferries.indexed) {
      final lat = (f['lat'] as num?)?.toDouble();
      final lon = (f['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final status = f['status']?.toString();
      final course = f['course'] as num?;
      // Pilen ritas rakt upp och vrids av kartan -- en bild per status, inte en per grad.
      final icon = _icons.get('ferry:$status:${course != null}', ratio, () => _Spec(
        Center(child: FerryArrow(status: status, course: course == null ? null : 0)),
        const Size(44, 44),
      ), ready);
      if (icon == null) continue;
      out.add(gm.Marker(
        markerId: gm.MarkerId('f:${f['mmsi'] ?? i}'),
        position: gm.LatLng(lat, lon),
        icon: icon,
        anchor: const Offset(0.5, 0.5),
        rotation: course?.toDouble() ?? 0,
        flat: course != null,
        zIndexInt: 4,
        consumeTapEvents: true,
        onTap: widget.onSelectFerry == null ? null : () => widget.onSelectFerry!(f),
      ));
    }

    if (ready.isNotEmpty) {
      // Nya symboler ritas i bakgrunden; kartan byggs om när de finns.
      unawaited(Future.wait(ready).then((_) {
        if (mounted) setState(() {});
      }));
    }
    return out;
  }

  Set<gm.Polyline> _ferryLines() {
    final terminals = <String, gm.LatLng>{
      for (final t in widget.ferryTerminals)
        if (t['lat'] is num && t['lon'] is num)
          t['key']?.toString() ?? '': gm.LatLng(
            (t['lat'] as num).toDouble(), (t['lon'] as num).toDouble(),
          ),
    };
    final out = <gm.Polyline>{};
    for (final (i, f) in widget.ferries.indexed) {
      final status = f['status']?.toString();
      final terminal = terminals[f['terminal']?.toString() ?? ''];
      if (terminal == null || f['lat'] is! num || f['lon'] is! num) continue;
      if (status != 'approaching' && status != 'docking') continue;
      out.add(gm.Polyline(
        polylineId: gm.PolylineId('fl:$i'),
        points: [gm.LatLng((f['lat'] as num).toDouble(), (f['lon'] as num).toDouble()), terminal],
        color: ferryColor(status).withValues(alpha: 0.85),
        width: 3,
        patterns: [gm.PatternItem.dash(20), gm.PatternItem.gap(14)],
      ));
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final ratio = MediaQuery.devicePixelRatioOf(context);
    return gm.GoogleMap(
      initialCameraPosition: const gm.CameraPosition(target: gm.LatLng(62.0, 15.0), zoom: 5),
      onMapCreated: (controller) {
        widget.focus.google = controller;
        unawaited(controller.moveCamera(gm.CameraUpdate.newLatLngBounds(_sweden, 16)));
      },
      onCameraMove: _onCamera,
      // Det här är skälet till Google-kartan: köer och stopp i realtid.
      trafficEnabled: true,
      // Telefonens egen "du är här"-prick; appens knapp för min position används.
      myLocationEnabled: true,
      myLocationButtonEnabled: false,
      compassEnabled: false,
      rotateGesturesEnabled: false,
      tiltGesturesEnabled: false,
      mapToolbarEnabled: false,
      zoomControlsEnabled: false,
      buildingsEnabled: false,
      minMaxZoomPreference: const gm.MinMaxZoomPreference(4, 19),
      markers: _markers(ratio),
      polylines: _ferryLines(),
    );
  }
}

class _Spec {
  const _Spec(this.widget, this.size);
  final Widget widget;
  final Size size;
}

/// Symbolerna som bilder, en gång per utseende. Samma widgetar som i
/// flutter_map-kartan ritas utanför skärmen, så att de två kartorna aldrig kan
/// se olika ut.
class _IconCache {
  final _done = <String, gm.BitmapDescriptor>{};
  final _pending = <String>{};

  gm.BitmapDescriptor? get(
    String key,
    double ratio,
    _Spec Function() spec,
    List<Future<void>> ready,
  ) {
    final full = '$key@$ratio';
    final hit = _done[full];
    if (hit != null) return hit;
    if (_pending.add(full)) {
      final s = spec();
      ready.add(_render(s.widget, s.size, ratio).then((bitmap) {
        _done[full] = bitmap;
        _pending.remove(full);
      }));
    }
    return null;
  }
}

Future<gm.BitmapDescriptor> _render(Widget child, Size size, double ratio) async {
  final boundary = RenderRepaintBoundary();
  final view = ui.PlatformDispatcher.instance.implicitView ??
      ui.PlatformDispatcher.instance.views.first;
  final renderView = RenderView(
    view: view,
    child: RenderPositionedBox(alignment: Alignment.center, child: boundary),
    configuration: ViewConfiguration(
      logicalConstraints: BoxConstraints.tight(size),
      physicalConstraints: BoxConstraints.tight(size * ratio),
      devicePixelRatio: ratio,
    ),
  );
  final pipeline = PipelineOwner()..rootNode = renderView;
  renderView.prepareInitialFrame();
  final buildOwner = BuildOwner(focusManager: FocusManager());
  final root = RenderObjectToWidgetAdapter<RenderBox>(
    container: boundary,
    child: Directionality(
      textDirection: TextDirection.ltr,
      child: MediaQuery(
        data: MediaQueryData(devicePixelRatio: ratio),
        child: SizedBox.fromSize(size: size, child: child),
      ),
    ),
  ).attachToRenderTree(buildOwner);
  buildOwner
    ..buildScope(root)
    ..finalizeTree();
  pipeline
    ..flushLayout()
    ..flushCompositingBits()
    ..flushPaint();
  final image = await boundary.toImage(pixelRatio: ratio);
  final data = await image.toByteData(format: ui.ImageByteFormat.png);
  image.dispose();
  return gm.BitmapDescriptor.bytes(
    data!.buffer.asUint8List(),
    imagePixelRatio: ratio,
    width: size.width,
    height: size.height,
  );
}
