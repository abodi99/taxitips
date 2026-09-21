import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../signal_kinds.dart';
import '../theme.dart';

/// Kartans symboler. Två former, så att de går att skilja åt utan färgseende
/// och utan att läsa:
///
/// * **Rund nål** -- något som kan ge körningar (tåg, flyg, färja, event).
///   Färgen och storleken är styrkan, ikonen är typen.
/// * **Varningstriangel** -- ett väghinder från Trafikverket. Samma form som
///   vägmärket, så att den läses som "kör runt", aldrig som "kör hit".
///
/// Storlekarna är valda för en förare i en hållare på instrumentbrädan:
/// även den svagaste symbolen är 32 px, och tryckytan är minst 48 px.

double pinHead(SignalStrength s) => switch (s) {
  SignalStrength.high => 44,
  SignalStrength.medium => 38,
  SignalStrength.low => 32,
};

class SignalPin extends StatelessWidget {
  const SignalPin({
    super.key,
    required this.icon,
    required this.strength,
    required this.category,
    this.followed = false,
    this.selected = false,
  });

  final IconData icon;
  final SignalStrength strength;
  final SignalCategory category;
  final bool followed;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final head = pinHead(strength) + (selected ? 6 : 0);
    final fill = strengthColor(strength, category: category);
    // Exakt huvud + spets på höjden: kartan placerar spetsen på platsen.
    return SizedBox(
      width: head + 12,
      height: head + 9,
      child: Stack(
        clipBehavior: Clip.none,
        alignment: Alignment.topCenter,
        children: [
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: head,
                height: head,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: fill,
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: selected ? TbColors.guld : TbColors.vit,
                    width: selected ? 4 : 3,
                  ),
                  boxShadow: const [
                    BoxShadow(
                      blurRadius: 8,
                      offset: Offset(0, 3),
                      color: Color(0x66000000),
                    ),
                  ],
                ),
                child: Icon(icon, color: TbColors.vit, size: head * 0.52),
              ),
              CustomPaint(size: const Size(14, 9), painter: _PinTip(fill)),
            ],
          ),
          if (followed)
            const Positioned(top: -4, right: 0, child: _FollowBadge()),
        ],
      ),
    );
  }
}

class HazardSign extends StatelessWidget {
  const HazardSign({
    super.key,
    required this.icon,
    required this.strength,
    this.followed = false,
    this.selected = false,
  });

  final IconData icon;
  final SignalStrength strength;
  final bool followed;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final size = pinHead(strength) + 4 + (selected ? 6 : 0);
    final fill = strengthColor(strength, category: SignalCategory.road);
    return SizedBox(
      width: size + 8,
      height: size + 4,
      child: Stack(
        clipBehavior: Clip.none,
        alignment: Alignment.center,
        children: [
          CustomPaint(
            size: Size(size, size),
            painter: _Triangle(
              fill,
              border: selected ? TbColors.guld : TbColors.vit,
            ),
          ),
          Padding(
            padding: EdgeInsets.only(top: size * 0.30),
            child: Icon(icon, color: TbColors.vit, size: size * 0.36),
          ),
          if (followed)
            const Positioned(top: -4, right: 0, child: _FollowBadge()),
        ],
      ),
    );
  }
}

/// Flera symboler på samma ställe. Antalet i mitten, färgen från den starkaste,
/// formen från innehållet (triangel för väghinder). Ett tryck zoomar in.
class ClusterBubble extends StatelessWidget {
  const ClusterBubble({
    super.key,
    required this.count,
    required this.strength,
    required this.hazard,
    this.category,
  });

  final int count;
  final SignalStrength strength;
  final bool hazard;
  final SignalCategory? category;

  @override
  Widget build(BuildContext context) {
    final size = count >= 10 ? 52.0 : 46.0;
    final fill = strengthColor(
      strength,
      category: hazard ? SignalCategory.road : category,
    );
    final label = Text(
      count > 99 ? '99+' : '$count',
      style: const TextStyle(
        fontFamily: kDisplayFont,
        fontWeight: FontWeight.w700,
        fontSize: 16,
        color: TbColors.vit,
        height: 1,
      ),
    );
    if (hazard) {
      return SizedBox(
        width: size + 8,
        height: size + 4,
        child: Stack(
          alignment: Alignment.center,
          children: [
            CustomPaint(
              size: Size(size, size),
              painter: _Triangle(fill, border: TbColors.vit),
            ),
            Padding(
              padding: EdgeInsets.only(top: size * 0.25),
              child: label,
            ),
          ],
        ),
      );
    }
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: fill,
        shape: BoxShape.circle,
        border: Border.all(color: TbColors.vit, width: 3),
        boxShadow: [
          // En andra ring säger "det här är en grupp", inte en enskild nål.
          BoxShadow(color: fill.withValues(alpha: 0.35), spreadRadius: 6),
          const BoxShadow(
            blurRadius: 8,
            offset: Offset(0, 3),
            color: Color(0x55000000),
          ),
        ],
      ),
      child: label,
    );
  }
}

class _FollowBadge extends StatelessWidget {
  const _FollowBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 20,
      height: 20,
      decoration: BoxDecoration(
        color: TbColors.guld,
        shape: BoxShape.circle,
        border: Border.all(color: TbColors.vit, width: 2),
      ),
      child: const Icon(Icons.star_rounded, size: 13, color: TbColors.midnatt),
    );
  }
}

class _PinTip extends CustomPainter {
  _PinTip(this.color);
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
  bool shouldRepaint(covariant _PinTip old) => old.color != color;
}

class _Triangle extends CustomPainter {
  _Triangle(this.fill, {required this.border});
  final Color fill;
  final Color border;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    ui.Path tri(double inset) => ui.Path()
      ..moveTo(w / 2, inset * 1.4)
      ..lineTo(w - inset, h - inset)
      ..lineTo(inset, h - inset)
      ..close();
    canvas.drawPath(
      tri(1).shift(const Offset(0, 2)),
      Paint()
        ..color = const Color(0x55000000)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3),
    );
    final outer = tri(1);
    canvas.drawPath(outer, Paint()..color = border);
    canvas.drawPath(
      outer,
      Paint()
        ..color = border
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..strokeJoin = StrokeJoin.round,
    );
    canvas.drawPath(tri(5), Paint()..color = fill);
  }

  @override
  bool shouldRepaint(covariant _Triangle old) =>
      old.fill != fill || old.border != border;
}
