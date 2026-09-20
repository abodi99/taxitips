import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart' show MapController;
import 'package:google_maps_flutter/google_maps_flutter.dart' as gm;
import 'package:latlong2/latlong.dart' show LatLng;

import '../severity_labels.dart';
import '../theme.dart';
import 'ferry_event_widgets.dart' show ferryColor;

/// Google Maps i förarkartan: plattformens eget trafiklager (segare vägar i gult och rött)
/// och Trafikverkets olyckor och avstängningar ovanpå.
///
/// Slås på vid bygget med `--dart-define=GOOGLE_MAPS=true`, och kräver en nyckel med Maps SDK
/// för Android och iOS (android/local.properties respektive ios/Flutter/Maps.xcconfig,
/// `MAPS_API_KEY`). Utan flaggan används flutter_map (HotspotMap) som förut: Google Maps utan
/// nyckel avslutar appen på Android.
const bool kGoogleMapsEnabled = bool.fromEnvironment('GOOGLE_MAPS');

/// Flyttar kartan, vilken av de två som visas.
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
}

/// Olyckor och avstängningar från Trafikverket bland tipsen: de som påverkar vägen dit.
bool isRoadIncident(Map a) =>
    a['kind'] == 'road' && a['severity_tier'] == 'road_accident_or_closure';

class TrafficMap extends StatefulWidget {
  const TrafficMap({
    super.key,
    required this.focus,
    required this.opportunities,
    required this.incidents,
    required this.events,
    required this.ferries,
    required this.ferryTerminals,
    this.userLat,
    this.userLon,
    this.onSelectOpportunity,
    this.onSelectEvent,
    this.onSelectFerry,
  });

  final MapFocus focus;
  final List<Map<String, dynamic>> opportunities;
  final List<Map<String, dynamic>> incidents;
  final List<Map<String, dynamic>> events;
  final List<Map<String, dynamic>> ferries;
  final List<Map<String, dynamic>> ferryTerminals;
  final double? userLat;
  final double? userLon;
  final ValueChanged<Map<String, dynamic>>? onSelectOpportunity;
  final ValueChanged<Map<String, dynamic>>? onSelectEvent;
  final ValueChanged<Map<String, dynamic>>? onSelectFerry;

  @override
  State<TrafficMap> createState() => _TrafficMapState();
}

class _TrafficMapState extends State<TrafficMap> {
  _Icons? _icons;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_icons == null) {
      final ratio = MediaQuery.devicePixelRatioOf(context);
      _Icons.load(ratio).then((icons) {
        if (mounted) setState(() => _icons = icons);
      });
    }
  }

  @override
  void dispose() {
    widget.focus.google = null;
    super.dispose();
  }

  static double? _d(Object? v) => (v as num?)?.toDouble();

  @override
  Widget build(BuildContext context) {
    final icons = _icons;
    final markers = <gm.Marker>{};
    final lines = <gm.Polyline>{};
    if (icons != null) {
      for (final (i, o) in widget.opportunities.indexed) {
        final lat = _d(o['lat']), lon = _d(o['lon']);
        if (lat == null || lon == null || isRoadIncident(o)) continue;
        markers.add(gm.Marker(
          markerId: gm.MarkerId('tip:$i:${o['id'] ?? o['title']}'),
          position: gm.LatLng(lat, lon),
          icon: icons.tip(likelihoodForAlert(o)),
          anchor: const Offset(0.5, 0.5),
          zIndexInt: 2,
          onTap: () => widget.onSelectOpportunity?.call(o),
        ));
      }
      for (final (i, a) in widget.incidents.indexed) {
        final lat = _d(a['lat']), lon = _d(a['lon']);
        if (lat == null || lon == null) continue;
        markers.add(gm.Marker(
          markerId: gm.MarkerId('road:$i:${a['id'] ?? a['title']}'),
          position: gm.LatLng(lat, lon),
          icon: icons.incident,
          anchor: const Offset(0.5, 0.5),
          zIndexInt: 3,
          onTap: () => widget.onSelectOpportunity?.call(a),
        ));
      }
      for (final (i, e) in widget.events.indexed) {
        final lat = _d(e['lat']), lon = _d(e['lon']);
        if (lat == null || lon == null) continue;
        markers.add(gm.Marker(
          markerId: gm.MarkerId('event:$i:${e['id']}'),
          position: gm.LatLng(lat, lon),
          icon: icons.event,
          anchor: const Offset(0.5, 0.5),
          zIndexInt: 1,
          onTap: () => widget.onSelectEvent?.call(e),
        ));
      }
      final terminals = <String, gm.LatLng>{};
      for (final t in widget.ferryTerminals) {
        final lat = _d(t['lat']), lon = _d(t['lon']);
        if (lat == null || lon == null) continue;
        terminals[t['key']?.toString() ?? ''] = gm.LatLng(lat, lon);
      }
      for (final (i, f) in widget.ferries.indexed) {
        final lat = _d(f['lat']), lon = _d(f['lon']);
        if (lat == null || lon == null) continue;
        final status = f['status']?.toString();
        final here = gm.LatLng(lat, lon);
        final terminal = terminals[f['terminal']?.toString() ?? ''];
        if (terminal != null && (status == 'approaching' || status == 'docking')) {
          lines.add(gm.Polyline(
            polylineId: gm.PolylineId('ferry:$i'),
            points: [here, terminal],
            color: ferryColor(status),
            width: 3,
            patterns: [gm.PatternItem.dash(18), gm.PatternItem.gap(12)],
          ));
        }
        markers.add(gm.Marker(
          markerId: gm.MarkerId('ferry:$i:${f['mmsi'] ?? f['name']}'),
          position: here,
          icon: icons.ferry,
          anchor: const Offset(0.5, 0.5),
          flat: true,
          rotation: _d(f['course']) ?? 0,
          zIndexInt: 2,
          onTap: () => widget.onSelectFerry?.call(f),
        ));
      }
    }

    final dark = MediaQuery.platformBrightnessOf(context) == Brightness.dark;
    final hasUser = widget.userLat != null && widget.userLon != null;
    return gm.GoogleMap(
      initialCameraPosition: gm.CameraPosition(
        target: hasUser ? gm.LatLng(widget.userLat!, widget.userLon!) : const gm.LatLng(62.0, 15.0),
        zoom: hasUser ? 12 : 4.6,
      ),
      onMapCreated: (controller) => widget.focus.google = controller,
      // Det föraren behöver: trafiken och den egna positionen. Inget som stjäl blicken.
      trafficEnabled: true,
      myLocationEnabled: hasUser,
      myLocationButtonEnabled: false,
      zoomControlsEnabled: false,
      mapToolbarEnabled: false,
      compassEnabled: false,
      tiltGesturesEnabled: false,
      rotateGesturesEnabled: false,
      buildingsEnabled: false,
      indoorViewEnabled: false,
      style: dark ? _darkStyle : _calmStyle,
      markers: markers,
      polylines: lines,
    );
  }
}

/// Kartstil utan butiker, sevärdheter och hållplatsnamn: trafiken och vägarna först.
const _calmStyle = '''[
  {"featureType":"poi","stylers":[{"visibility":"off"}]},
  {"featureType":"transit","elementType":"labels.icon","stylers":[{"visibility":"off"}]},
  {"featureType":"road","elementType":"labels.icon","stylers":[{"visibility":"off"}]}
]''';

/// Mörk variant för kvällspasset, så att skärmen inte bländar i bilen.
const _darkStyle = '''[
  {"elementType":"geometry","stylers":[{"color":"#1d2330"}]},
  {"elementType":"labels.text.fill","stylers":[{"color":"#9aa4b5"}]},
  {"elementType":"labels.text.stroke","stylers":[{"color":"#1d2330"}]},
  {"featureType":"road","elementType":"geometry","stylers":[{"color":"#2c3446"}]},
  {"featureType":"road.highway","elementType":"geometry","stylers":[{"color":"#3a4560"}]},
  {"featureType":"water","elementType":"geometry","stylers":[{"color":"#0e1624"}]},
  {"featureType":"poi","stylers":[{"visibility":"off"}]},
  {"featureType":"transit","elementType":"labels.icon","stylers":[{"visibility":"off"}]},
  {"featureType":"road","elementType":"labels.icon","stylers":[{"visibility":"off"}]}
]''';

/// Kartsymbolerna, ritade en gång: tipsprick i prioritetsfärg, varningstriangel för olyckor,
/// E för evenemang och en pil för färjor (vrids efter kursen).
class _Icons {
  _Icons(this._tips, this.incident, this.event, this.ferry);

  final Map<CustomerLikelihood, gm.BitmapDescriptor> _tips;
  final gm.BitmapDescriptor incident;
  final gm.BitmapDescriptor event;
  final gm.BitmapDescriptor ferry;

  gm.BitmapDescriptor tip(CustomerLikelihood l) => _tips[l]!;

  static Future<_Icons> load(double ratio) async {
    Future<gm.BitmapDescriptor> draw(double size, void Function(Canvas c, double s) paint) async {
      final px = size * ratio;
      final recorder = ui.PictureRecorder();
      final canvas = Canvas(recorder);
      canvas.scale(ratio);
      paint(canvas, size);
      final image = await recorder.endRecording().toImage(px.ceil(), px.ceil());
      final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      return gm.BitmapDescriptor.bytes(bytes!.buffer.asUint8List(), width: size, height: size);
    }

    void dot(Canvas c, double s, Color fill, String label) {
      final center = Offset(s / 2, s / 2);
      c.drawCircle(center.translate(0, 1.5), s / 2 - 2, Paint()..color = const Color(0x44000000));
      c.drawCircle(center, s / 2 - 2, Paint()..color = TbColors.vit);
      c.drawCircle(center, s / 2 - 5, Paint()..color = fill);
      if (label.isEmpty) return;
      final text = TextPainter(
        text: TextSpan(
          text: label,
          style: TextStyle(color: TbColors.vit, fontWeight: FontWeight.w800, fontSize: s * 0.42),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      text.paint(c, center - Offset(text.width / 2, text.height / 2));
    }

    final tips = <CustomerLikelihood, gm.BitmapDescriptor>{
      CustomerLikelihood.high: await draw(34, (c, s) => dot(c, s, TbColors.likelihoodHigh, '')),
      CustomerLikelihood.medium: await draw(30, (c, s) => dot(c, s, TbColors.likelihoodMedium, '')),
      CustomerLikelihood.low: await draw(26, (c, s) => dot(c, s, TbColors.midnatt, '')),
    };
    final incident = await draw(34, (c, s) {
      final path = ui.Path()
        ..moveTo(s / 2, 2)
        ..lineTo(s - 2, s - 4)
        ..lineTo(2, s - 4)
        ..close();
      c.drawPath(path.shift(const Offset(0, 1.5)), Paint()..color = const Color(0x44000000));
      c.drawPath(path, Paint()..color = TbColors.vit);
      final inner = ui.Path()
        ..moveTo(s / 2, 7)
        ..lineTo(s - 6, s - 7)
        ..lineTo(6, s - 7)
        ..close();
      c.drawPath(inner, Paint()..color = const Color(0xFFD7263D));
      final text = TextPainter(
        text: const TextSpan(
          text: '!',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 15),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      text.paint(c, Offset(s / 2 - text.width / 2, s / 2 - text.height / 2 + 2));
    });
    final event = await draw(28, (c, s) => dot(c, s, TbColors.midnatt, 'E'));
    final ferry = await draw(30, (c, s) {
      final center = Offset(s / 2, s / 2);
      c.drawCircle(center, s / 2 - 1, Paint()..color = TbColors.vit);
      final arrow = ui.Path()
        ..moveTo(s / 2, 4)
        ..lineTo(s - 7, s - 6)
        ..lineTo(s / 2, s - 10)
        ..lineTo(7, s - 6)
        ..close();
      c.drawPath(arrow, Paint()..color = TbColors.midnatt);
      c.drawCircle(center, s / 2 - 1, Paint()
        ..color = TbColors.midnatt
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5);
    });
    return _Icons(tips, incident, event, ferry);
  }
}
