import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../analytics.dart';
import '../theme.dart';

/// Den guidade genomgången: mörkar skärmen, lyser upp ETT element i taget med
/// en guldram och säger med några korta meningar vad det är och var man
/// trycker. "Nästa" och "Hoppa över" -- inget annat.
///
/// Inga tunga beroenden: en [OverlayEntry] ovanpå appen, och elementens läge
/// hämtas ur deras [GlobalKey]. Det som inte syns just nu (inget tips i
/// listan, en knapp som göms när listan dras upp, en liten skärm) får steget
/// hoppa över i stället för att peka på ingenting.
///
/// Visas en gång (versionerad nyckel) och kan visas igen från Inställningar.
class GuidedTour {
  GuidedTour._();

  /// Bumpa versionen när stegen ändras så mycket att alla bör se dem igen.
  static const seenKey = 'tt_tour_seen_v1';

  static Future<bool> seen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(seenKey) ?? false;
    } catch (_) {
      return true; // Hellre ingen genomgång än en som fastnar.
    }
  }

  static Future<void> markSeen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(seenKey, true);
    } catch (_) {}
  }

  /// Startar genomgången över [context]s skärm. Returnerar null när inget steg
  /// syns (då har ingenting visats och inget sparas som sett).
  ///
  /// Sparas som sedd redan när den visas, som introduktionen: den som stänger
  /// appen mitt i ska inte mötas av den igen. Inställningar har den kvar.
  static TourController? start(
    BuildContext context, {
    required List<TourStep> steps,
    String role = 'driver',
  }) {
    final overlay = Overlay.maybeOf(context, rootOverlay: true);
    if (overlay == null) return null;
    final shown = [
      for (final s in steps)
        if (s.resolve() != null) s,
    ];
    if (shown.isEmpty) return null;

    unawaited(markSeen());
    final controller = TourController._();
    final entry = OverlayEntry(
      builder: (_) =>
          _TourOverlay(steps: shown, controller: controller, role: role),
    );
    controller._entry = entry;
    overlay.insert(entry);
    unawaited(logAnalyticsEvent('tour_start', params: {'role': role}));
    return controller;
  }
}

/// Ett steg: vad som lyses upp och vad som sägs om det.
class TourStep {
  const TourStep({
    required this.id,
    required this.title,
    required this.text,
    this.keys = const [],
    this.area,
    this.extra,
  });

  /// Kort namn till statistiken och testerna.
  final String id;
  final String title;
  final String text;

  /// Elementen som kan lysas upp. Det första som syns används; de följande är
  /// reserv (ett tips i listan, annars listans rubrik).
  final List<GlobalKey> keys;

  /// Ett eget område när inget enskilt element passar (kartan). Null = syns
  /// inte, och steget hoppas över.
  final Rect? Function()? area;

  /// Något att visa under texten, t.ex. styrkans färger med ord.
  final Widget? extra;

  /// Var elementet är på skärmen just nu, eller null när det inte syns.
  Rect? resolve() {
    final custom = area?.call();
    if (custom != null) return tourVisibleRect(custom);
    for (final key in keys) {
      final rect = tourRectOfKey(key);
      if (rect != null) return rect;
    }
    return null;
  }
}

/// Handtaget till en pågående genomgång: stängs när skärmen den hör till
/// försvinner (annars blev den kvar ovanpå inloggningen).
class TourController {
  TourController._();

  OverlayEntry? _entry;
  final _done = Completer<void>();

  /// Klar när genomgången är slut, hoppad över eller stängd.
  Future<void> get done => _done.future;

  bool get active => _entry != null;

  void dismiss() {
    final entry = _entry;
    if (entry == null) return;
    _entry = null;
    entry.remove();
    entry.dispose();
    if (!_done.isCompleted) _done.complete();
  }
}

/// Elementets rektangel på skärmen, eller null när det inte syns (ingen
/// byggd widget, ingen storlek, eller mest utanför skärmen).
Rect? tourRectOfKey(GlobalKey key) {
  final context = key.currentContext;
  if (context == null || !context.mounted) return null;
  final box = context.findRenderObject();
  if (box is! RenderBox || !box.attached || !box.hasSize) return null;
  if (box.debugNeedsLayout) return null;
  if (box.size.isEmpty) return null;
  return tourVisibleRect(box.localToGlobal(Offset.zero) & box.size);
}

/// Rektangeln beskuren mot skärmen, eller null när för lite av den syns för
/// att peka på. Skärmen är hela fönstret: det som ligger utanför kan inte lysas.
Rect? tourVisibleRect(Rect rect) {
  final view = WidgetsBinding.instance.platformDispatcher.views.firstOrNull;
  if (view == null) return null;
  final screen = Offset.zero & (view.physicalSize / view.devicePixelRatio);
  final visible = rect.intersect(screen);
  if (visible.width < 24 || visible.height < 24) return null;
  final shownArea = visible.width * visible.height;
  final fullArea = rect.width * rect.height;
  // Ett kort som är mer än hälften utanför är inte det föraren ska titta på.
  if (shownArea < fullArea * 0.5) return null;
  return visible;
}

class _TourOverlay extends StatefulWidget {
  const _TourOverlay({
    required this.steps,
    required this.controller,
    required this.role,
  });

  final List<TourStep> steps;
  final TourController controller;
  final String role;

  @override
  State<_TourOverlay> createState() => _TourOverlayState();
}

class _TourOverlayState extends State<_TourOverlay>
    with WidgetsBindingObserver, SingleTickerProviderStateMixin {
  int _index = 0;
  Rect? _rect;
  Rect? _from;
  Timer? _watch;
  late final AnimationController _move;

  TourStep get _step => widget.steps[_index];
  bool get _last => _index == widget.steps.length - 1;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _move = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 240),
    );
    _rect = _step.resolve();
    // Skärmen under kan ändras medan genomgången visas (ny hämtning, ny
    // banner): följ elementet i stället för att peka på där det låg.
    _watch = Timer.periodic(
      const Duration(milliseconds: 400),
      (_) => _remeasure(),
    );
  }

  @override
  void dispose() {
    _watch?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _move.dispose();
    super.dispose();
  }

  /// Vridning och ändrad storlek: mät om när skärmen under hunnit ritas om.
  @override
  void didChangeMetrics() {
    WidgetsBinding.instance.addPostFrameCallback((_) => _remeasure());
  }

  /// Tillbaka-knappen lämnar genomgången, inte appen.
  @override
  Future<bool> didPopRoute() async {
    if (!widget.controller.active) return false;
    _finish(skipped: true);
    return true;
  }

  void _remeasure() {
    if (!mounted) return;
    final now = _step.resolve();
    if (now == null) {
      // Elementet försvann (vridning, mindre skärm): hoppa till nästa steg.
      _advance();
      return;
    }
    final before = _rect;
    if (before == null || !_nearlySame(before, now)) {
      setState(() => _rect = now);
    }
  }

  /// Nästa steg som syns just nu; inget kvar = klar.
  void _advance() {
    for (var i = _index + 1; i < widget.steps.length; i++) {
      final rect = widget.steps[i].resolve();
      if (rect != null) {
        setState(() {
          _from = _rect;
          _index = i;
          _rect = rect;
        });
        _move.forward(from: 0);
        return;
      }
    }
    _finish(skipped: false);
  }

  void _finish({required bool skipped}) {
    unawaited(
      logAnalyticsEvent(
        skipped ? 'tour_skip' : 'tour_complete',
        params: {
          'step': _index + 1,
          'of': widget.steps.length,
          'role': widget.role,
        },
      ),
    );
    widget.controller.dismiss();
  }

  void _next() {
    if (_last) {
      _finish(skipped: false);
    } else {
      _advance();
    }
  }

  @override
  Widget build(BuildContext context) {
    final rect = _rect;
    final media = MediaQuery.of(context);
    final size = media.size;
    final target = rect?.inflate(_pad);
    final place = target == null
        ? null
        : _CardPlacement.choose(
            target: target,
            size: size,
            safe: media.padding,
          );

    return Material(
      type: MaterialType.transparency,
      child: Stack(
        children: [
          // Tar alla tryck: det som lyses upp är något att titta på, inte att
          // trycka på. Då trycker ingen av misstag på kartan under.
          Positioned.fill(
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: () {},
              child: AnimatedBuilder(
                animation: _move,
                builder: (context, _) {
                  final from = _from;
                  final t = Curves.easeOutCubic.transform(_move.value);
                  final shown = target == null
                      ? null
                      : (from == null || !_move.isAnimating
                            ? target
                            : Rect.lerp(from.inflate(_pad), target, t));
                  return CustomPaint(painter: _SpotlightPainter(shown));
                },
              ),
            ),
          ),
          if (place != null)
            Positioned.fromRect(
              rect: place.zone,
              child: Align(
                alignment: place.alignment,
                child: ConstrainedBox(
                  constraints: BoxConstraints(maxWidth: place.maxWidth),
                  child: _TourCard(
                    step: _step,
                    position: _index + 1,
                    total: widget.steps.length,
                    last: _last,
                    onNext: _next,
                    onSkip: () => _finish(skipped: true),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Samma ruta, så när som på en pixel (skärmen under ritas om hela tiden).
bool _nearlySame(Rect a, Rect b) =>
    (a.left - b.left).abs() <= 1 &&
    (a.top - b.top).abs() <= 1 &&
    (a.right - b.right).abs() <= 1 &&
    (a.bottom - b.bottom).abs() <= 1;

/// Luft mellan elementet och guldramen.
const double _pad = 8;

/// Var kortet får plats: under, över eller bredvid elementet -- den yta som är
/// störst. Står kortet ingenstans (elementet fyller skärmen) läggs det över
/// skärmens andra hälft, hellre än att lämna föraren utan "Nästa".
class _CardPlacement {
  const _CardPlacement(this.zone, this.alignment, this.maxWidth);

  final Rect zone;
  final Alignment alignment;
  final double maxWidth;

  static const _gap = 12.0;
  static const _margin = 16.0;
  static const _maxCardWidth = 440.0;
  static const _minWidth = 260.0;
  static const _minHeight = 170.0;

  static _CardPlacement choose({
    required Rect target,
    required Size size,
    required EdgeInsets safe,
  }) {
    final top = safe.top + 8;
    final bottom = size.height - safe.bottom - 8;
    final left = math.max(_margin, safe.left);
    final right = size.width - math.max(_margin, safe.right);

    final candidates = <(Rect, Alignment)>[
      (
        Rect.fromLTRB(
          left,
          math.min(target.bottom + _gap, bottom),
          right,
          bottom,
        ),
        Alignment.topCenter,
      ),
      (
        Rect.fromLTRB(left, top, right, math.max(target.top - _gap, top)),
        Alignment.bottomCenter,
      ),
      (
        Rect.fromLTRB(math.min(target.right + _gap, right), top, right, bottom),
        Alignment.center,
      ),
      (
        Rect.fromLTRB(left, top, math.max(target.left - _gap, left), bottom),
        Alignment.center,
      ),
    ];
    _CardPlacement? best;
    var bestScore = 0.0;
    for (final (zone, alignment) in candidates) {
      if (zone.width < _minWidth || zone.height < _minHeight) continue;
      final score =
          math.min(zone.width, _maxCardWidth) * math.min(zone.height, 380);
      if (score > bestScore) {
        bestScore = score;
        best = _CardPlacement(
          zone,
          alignment,
          math.min(zone.width, _maxCardWidth),
        );
      }
    }
    if (best != null) return best;

    // Ingen fri yta: kortet över den halva av skärmen som elementet inte är i.
    final upper = target.center.dy > size.height / 2;
    final zone = upper
        ? Rect.fromLTRB(
            left,
            top,
            right,
            math.max(top + _minHeight, size.height * 0.55),
          )
        : Rect.fromLTRB(
            left,
            math.min(size.height * 0.45, bottom - _minHeight),
            right,
            bottom,
          );
    return _CardPlacement(
      zone,
      upper ? Alignment.topCenter : Alignment.bottomCenter,
      math.min(zone.width, _maxCardWidth),
    );
  }
}

class _SpotlightPainter extends CustomPainter {
  const _SpotlightPainter(this.hole);

  final Rect? hole;

  @override
  void paint(Canvas canvas, Size size) {
    final scrim = Paint()..color = TbColors.midnattDjup.withValues(alpha: 0.78);
    final full = Offset.zero & size;
    final hole = this.hole;
    if (hole == null) {
      canvas.drawRect(full, scrim);
      return;
    }
    final rrect = RRect.fromRectAndRadius(hole, const Radius.circular(16));
    canvas.drawPath(
      Path()
        ..fillType = PathFillType.evenOdd
        ..addRect(full)
        ..addRRect(rrect),
      scrim,
    );
    canvas.drawRRect(
      rrect,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..color = TbColors.guld,
    );
  }

  @override
  bool shouldRepaint(_SpotlightPainter old) => old.hole != hole;
}

/// Kortet med texten och knapparna. Texten rullar när skärmen är liten eller
/// textstorleken stor; knapparna ligger alltid kvar i kortets nederkant.
class _TourCard extends StatelessWidget {
  const _TourCard({
    required this.step,
    required this.position,
    required this.total,
    required this.last,
    required this.onNext,
    required this.onSkip,
  });

  final TourStep step;
  final int position;
  final int total;
  final bool last;
  final VoidCallback onNext;
  final VoidCallback onSkip;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      liveRegion: true,
      label: 'Steg $position av $total. ${step.title}. ${step.text}',
      child: Material(
        color: TbColors.vit,
        elevation: 12,
        borderRadius: BorderRadius.circular(20),
        clipBehavior: Clip.antiAlias,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Steg $position av $total',
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: TbColors.skiffer,
                ),
              ),
              const SizedBox(height: 4),
              Flexible(
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        step.title,
                        style: const TextStyle(
                          fontFamily: kDisplayFont,
                          fontSize: 21,
                          height: 1.2,
                          fontWeight: FontWeight.w700,
                          color: TbColors.midnatt,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        step.text,
                        style: const TextStyle(
                          fontSize: 17,
                          height: 1.4,
                          color: TbColors.midnatt,
                        ),
                      ),
                      if (step.extra != null) ...[
                        const SizedBox(height: 12),
                        step.extra!,
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Wrap(
                alignment: WrapAlignment.spaceBetween,
                crossAxisAlignment: WrapCrossAlignment.center,
                runSpacing: 8,
                children: [
                  TextButton(
                    onPressed: onSkip,
                    style: TextButton.styleFrom(
                      minimumSize: const Size(48, 48),
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                    ),
                    child: const Text(
                      'Hoppa över',
                      style: TextStyle(fontSize: 16),
                    ),
                  ),
                  FilledButton(
                    onPressed: onNext,
                    style: FilledButton.styleFrom(
                      minimumSize: const Size(112, 52),
                    ),
                    child: Text(
                      last ? 'Klar' : 'Nästa',
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
