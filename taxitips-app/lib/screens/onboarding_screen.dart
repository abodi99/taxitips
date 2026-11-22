import 'dart:async';

import 'package:flutter/material.dart';
import 'package:liquid_swipe/liquid_swipe.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../analytics.dart';
import '../l10n/l10n.dart';
import '../theme.dart';

/// Visad EN gång efter installationen, före välkomstskärmen: vad appen gör,
/// att tipsen är tips och inte löften, hur man svarar på ett tips och hur man
/// kommer igång. En sak per sida, kort svenska -- många förare har svenska som
/// andraspråk.
///
/// "Sedd" sparas redan när den visas, och även när appen startar med en
/// inloggning som redan finns ([markSeen] i main.dart): en förare som loggar
/// ut och in, eller en ägare som kom in via en länk, möter den aldrig mitt i.
/// Efter den följer en guidad genomgång på huvudskärmen (guided_tour.dart).
///
/// Sidorna byts med liquid_swipe (svep eller "Nästa"). "Hoppa över" finns
/// hela tiden: den som redan kan appen ska inte tvingas igenom. Från
/// Inställningar ("Så fungerar Taxi Tips") öppnas den igen som [replay].
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({
    super.key,
    required this.onDone,
    this.replay = false,
  });

  final VoidCallback onDone;

  /// Öppnad igen från Inställningar: "Stäng" och "Klar", sista sidan om
  /// notiser i stället för inloggning.
  final bool replay;

  /// Bumpa versionen när innehållet ändras så mycket att alla bör se det igen.
  static const seenKey = 'tt_onboarding_seen_v1';

  /// Från Inställningar: samma sidor, och tillbaka dit med Stäng/Klar.
  static Future<void> openFromSettings(BuildContext context) {
    return Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (ctx) => OnboardingScreen(
          replay: true,
          onDone: () => Navigator.of(ctx).pop(),
        ),
      ),
    );
  }

  /// Sparar att introduktionen är sedd, utan att visa den.
  static Future<void> markSeen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(seenKey, true);
    } catch (_) {}
  }

  static Future<bool> seen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(seenKey) ?? false;
    } catch (_) {
      return true; // Hellre ingen introduktion än en som fastnar.
    }
  }

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _controller = LiquidController();
  int _page = 0;

  @override
  void initState() {
    super.initState();
    // Sedd redan när den visas, inte först när den klickats igenom: den som
    // stänger appen mitt i ska inte mötas av samma introduktion igen.
    if (!widget.replay) unawaited(OnboardingScreen.markSeen());
  }

  /// Första starten: två sidor -- vad appen gör och hur man kommer igång.
  /// Färgerna och hur man svarar på ett tips visar rundturen på huvudskärmen,
  /// där föraren ser det på riktigt (driver_tour.dart); att läsa om dem före
  /// inloggningen var mest text att ta sig igenom. Från Inställningar visas
  /// allt.
  List<_PageData> get _pages => widget.replay
      ? [_traffic, _colors, _feedback, _replayLast]
      : [_traffic, _start];

  /// Sista sidan när introduktionen öppnas igen från Inställningar: föraren är
  /// redan inloggad, så här står det som återstår.
  static _PageData get _replayLast => _PageData(
    background: TbColors.navyDeep,
    foreground: TbColors.foam,
    accent: TbColors.taxi,
    icon: Icons.notifications_active_rounded,
    title: tr.onboardingScreenNotifTitle,
    body: tr.onboardingScreenNotifBody,
  );

  static _PageData get _traffic => _PageData(
    background: TbColors.navy,
    foreground: TbColors.foam,
    accent: TbColors.taxi,
    icon: Icons.location_on_rounded,
    title: tr.onboardingScreenTrafficTitle,
    body: tr.onboardingScreenTrafficBody,
  );

  static _PageData get _colors => _PageData(
    background: Colors.white,
    foreground: TbColors.ink,
    accent: TbColors.navy,
    icon: Icons.traffic_rounded,
    title: tr.onboardingScreenColorsTitle,
    body: tr.onboardingScreenColorsBody,
    levels: true,
  );

  static _PageData get _feedback => _PageData(
    background: TbColors.taxi,
    foreground: TbColors.ink,
    accent: TbColors.navy,
    icon: Icons.thumbs_up_down_rounded,
    title: tr.onboardingScreenFeedbackTitle,
    body: tr.onboardingScreenFeedbackBody,
  );

  static _PageData get _start => _PageData(
    background: TbColors.navyDeep,
    foreground: TbColors.foam,
    accent: TbColors.taxi,
    icon: Icons.local_taxi_rounded,
    title: tr.onboardingScreenStartTitle,
    body: tr.onboardingScreenStartBody,
  );

  bool get _last => _page == _pages.length - 1;

  Future<void> _finish({required bool skipped}) async {
    if (!widget.replay) await OnboardingScreen.markSeen();
    await logAnalyticsEvent(
      skipped ? 'onboarding_skip' : 'onboarding_complete',
      params: {'page': _page + 1, 'replay': widget.replay ? 1 : 0},
    );
    widget.onDone();
  }

  void _next() {
    // Från kontrollerns sida, inte vår egen: liquid_swipe ignorerar ett nytt
    // byte medan ett pågår, och anropar inte onPageChangeCallback vid byte i
    // kod. Ett snabbt dubbeltryck får då samma mål två gånger, inte ett steg
    // för långt.
    final target = _controller.currentPage + 1;
    if (target >= _pages.length) {
      _finish(skipped: false);
      return;
    }
    _controller.animateToPage(page: target, duration: 500);
    setState(() => _page = target);
  }

  @override
  Widget build(BuildContext context) {
    final current = _pages[_page];
    // liquid_swipe har vågen fast vid högerkanten och saknar riktningsval. På
    // arabiska speglas därför hela svepet (och varje sida speglas tillbaka):
    // vågen ligger då vid vänsterkanten och nästa sida kommer med ett svep åt
    // höger, som i övriga appen.
    Widget swipe = LiquidSwipe(
      pages: [
        for (final p in _pages)
          isRtl ? _Mirror(child: _Page(data: p)) : _Page(data: p),
      ],
      liquidController: _controller,
      enableLoop: false,
      enableSideReveal: true,
      waveType: WaveType.liquidReveal,
      slideIconWidget: Icon(
        Icons.arrow_back_ios_new_rounded,
        // Alltid "vänster" här: på arabiska speglas hela svepet efteråt.
        textDirection: TextDirection.ltr,
        color: current.foreground.withValues(alpha: 0.7),
        size: 20,
      ),
      positionSlideIcon: 0.55,
      onPageChangeCallback: (page) => setState(() => _page = page),
    );
    if (isRtl) swipe = _Mirror(child: swipe);
    return Scaffold(
      backgroundColor: current.background,
      body: Stack(
        children: [
          swipe,
          SafeArea(
            child: Align(
              alignment: AlignmentDirectional.topEnd,
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: AnimatedOpacity(
                  opacity: _last ? 0 : 1,
                  duration: const Duration(milliseconds: 200),
                  child: TextButton(
                    onPressed: _last ? null : () => _finish(skipped: true),
                    style: TextButton.styleFrom(
                      foregroundColor: current.foreground,
                      minimumSize: const Size(48, 48),
                    ),
                    child: Text(
                      widget.replay
                          ? tr.onboardingScreenClose
                          : tr.onboardingScreenSkip,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                ),
              ),
            ),
          ),
          SafeArea(
            child: Align(
              alignment: Alignment.bottomCenter,
              child: Padding(
                padding: const EdgeInsetsDirectional.fromSTEB(24, 0, 24, 20),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _Dots(
                      count: _pages.length,
                      index: _page,
                      color: current.foreground,
                    ),
                    const SizedBox(height: 20),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: _next,
                        style: FilledButton.styleFrom(
                          backgroundColor: current.background == TbColors.taxi
                              ? TbColors.navy
                              : TbColors.taxi,
                          foregroundColor: current.background == TbColors.taxi
                              ? TbColors.foam
                              : TbColors.ink,
                          minimumSize: const Size.fromHeight(56),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14),
                          ),
                        ),
                        child: Text(
                          _last
                              ? (widget.replay
                                    ? tr.onboardingScreenDone
                                    : tr.onboardingScreenStartTitle)
                              : tr.onboardingScreenNext,
                          style: const TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Speglar sitt barn vågrätt (bara för arabiskans svep, se build ovan).
class _Mirror extends StatelessWidget {
  const _Mirror({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) =>
      Transform.flip(flipX: true, child: child);
}

class _PageData {
  const _PageData({
    required this.background,
    required this.foreground,
    required this.accent,
    required this.icon,
    required this.title,
    required this.body,
    this.levels = false,
  });

  final Color background;
  final Color foreground;
  final Color accent;
  final IconData icon;
  final String title;
  final String body;

  /// Visa Stark/Medel/Svag med appens egna färger.
  final bool levels;
}

class _Page extends StatelessWidget {
  const _Page({required this.data});

  final _PageData data;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: data.background,
      width: double.infinity,
      child: SafeArea(
        child: Padding(
          // Plats under för prickar och knapp (ritas ovanpå i skärmen).
          // Änden (vid vågen): plats för liquid_swipes kant med nästa sida och pilen.
          padding: const EdgeInsetsDirectional.fromSTEB(32, 64, 56, 140),
          // Skrollbar men centrerad: stor textstorlek eller en liten
          // telefon ska inte klippa texten.
          child: LayoutBuilder(
            builder: (context, box) => SingleChildScrollView(
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: box.maxHeight),
                child: _content(),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _content() {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 88,
          height: 88,
          decoration: BoxDecoration(
            color: data.accent.withValues(alpha: 0.14),
            borderRadius: BorderRadius.circular(26),
          ),
          child: Icon(data.icon, size: 48, color: data.accent),
        ),
        const SizedBox(height: 32),
        Text(
          data.title,
          style: TextStyle(
            fontFamily: kDisplayFont,
            color: data.foreground,
            fontSize: 30,
            height: 1.15,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 14),
        if (data.levels) ...[
          const SizedBox(height: 6),
          _Level(
            color: TbColors.likelihoodHigh,
            label: tr.onboardingScreenLevelStrong,
            text: tr.onboardingScreenLevelStrongText,
          ),
          _Level(
            color: TbColors.likelihoodMedium,
            label: tr.onboardingScreenLevelMedium,
            text: tr.onboardingScreenLevelMediumText,
          ),
          _Level(
            color: TbColors.likelihoodLow,
            label: tr.onboardingScreenLevelWeak,
            text: tr.onboardingScreenLevelWeakText,
          ),
          const SizedBox(height: 14),
        ],
        Text(
          data.body,
          style: TextStyle(
            color: data.foreground.withValues(alpha: 0.85),
            fontSize: 18,
            height: 1.45,
          ),
        ),
      ],
    );
  }
}

class _Level extends StatelessWidget {
  const _Level({required this.color, required this.label, required this.text});

  final Color color;
  final String label;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        children: [
          Container(
            width: 72,
            padding: const EdgeInsets.symmetric(vertical: 6),
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(999),
            ),
            child: Text(
              label,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                color: TbColors.ink,
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Dots extends StatelessWidget {
  const _Dots({required this.count, required this.index, required this.color});

  final int count;
  final int index;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: tr.onboardingScreenPageOf(index + 1, count),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          for (var i = 0; i < count; i++)
            AnimatedContainer(
              duration: const Duration(milliseconds: 250),
              margin: const EdgeInsets.symmetric(horizontal: 4),
              width: i == index ? 24 : 8,
              height: 8,
              decoration: BoxDecoration(
                color: color.withValues(alpha: i == index ? 0.9 : 0.3),
                borderRadius: BorderRadius.circular(4),
              ),
            ),
        ],
      ),
    );
  }
}
