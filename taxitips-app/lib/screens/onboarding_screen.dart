import 'package:flutter/material.dart';
import 'package:liquid_swipe/liquid_swipe.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../analytics.dart';
import '../theme.dart';

/// Visad en gång, före välkomstskärmen: vad appen gör, att tipsen är tips
/// och inte löften, hur man svarar på ett tips och hur man kommer igång. En
/// sak per sida, kort svenska -- många förare har svenska som andraspråk.
///
/// Sidorna byts med liquid_swipe (svep eller "Nästa"). "Hoppa över" finns
/// hela tiden: den som redan kan appen ska inte tvingas igenom.
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key, required this.onDone});

  final VoidCallback onDone;

  /// Bumpa versionen när innehållet ändras så mycket att alla bör se det igen.
  static const seenKey = 'tt_onboarding_seen_v1';

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
    _markSeen();
  }

  static Future<void> _markSeen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(OnboardingScreen.seenKey, true);
    } catch (_) {}
  }

  static const _pages = <_PageData>[
    _PageData(
      background: TbColors.navy,
      foreground: TbColors.foam,
      accent: TbColors.taxi,
      icon: Icons.location_on_rounded,
      title: 'Tips från trafiken',
      body:
          'Inställda tåg, sena flyg, färjor och event som slutar. Vi visar '
          'var folk kan behöva taxi.',
    ),
    _PageData(
      background: Colors.white,
      foreground: TbColors.ink,
      accent: TbColors.navy,
      icon: Icons.traffic_rounded,
      title: 'Färgen visar hur starkt tipset är',
      body:
          'Det är tips, inte beställningar. Du avgör själv om det är värt '
          'att åka.',
      levels: true,
    ),
    _PageData(
      background: TbColors.taxi,
      foreground: TbColors.ink,
      accent: TbColors.navy,
      icon: Icons.thumbs_up_down_rounded,
      title: 'Säg hur det gick',
      body:
          'Tryck på ett tips och välj Fick körning eller Ingen kund. Då blir '
          'tipsen bättre för alla.',
    ),
    _PageData(
      background: TbColors.navyDeep,
      foreground: TbColors.foam,
      accent: TbColors.taxi,
      icon: Icons.local_taxi_rounded,
      title: 'Kom igång',
      body:
          'Logga in med din e-post. Slå på notiser så säger vi till när ett '
          'starkt tips dyker upp nära dig.',
    ),
  ];

  bool get _last => _page == _pages.length - 1;

  Future<void> _finish({required bool skipped}) async {
    await _markSeen();
    await logAnalyticsEvent(
      skipped ? 'onboarding_skip' : 'onboarding_complete',
      params: {'page': _page + 1},
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
    return Scaffold(
      backgroundColor: current.background,
      body: Stack(
        children: [
          LiquidSwipe(
            pages: [for (final p in _pages) _Page(data: p)],
            liquidController: _controller,
            enableLoop: false,
            enableSideReveal: true,
            waveType: WaveType.liquidReveal,
            slideIconWidget: Icon(
              Icons.arrow_back_ios_new_rounded,
              color: current.foreground.withValues(alpha: 0.7),
              size: 20,
            ),
            positionSlideIcon: 0.55,
            onPageChangeCallback: (page) => setState(() => _page = page),
          ),
          SafeArea(
            child: Align(
              alignment: Alignment.topRight,
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
                    child: const Text(
                      'Hoppa över',
                      style: TextStyle(fontWeight: FontWeight.w700),
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
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 20),
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
                          _last ? 'Kom igång' : 'Nästa',
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
          // Höger: plats för liquid_swipes kant med nästa sida och pilen.
          padding: const EdgeInsets.fromLTRB(32, 64, 56, 140),
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
          const _Level(
            color: TbColors.likelihoodHigh,
            label: 'Stark',
            text: 'Många kan behöva taxi.',
          ),
          const _Level(
            color: TbColors.likelihoodMedium,
            label: 'Medel',
            text: 'Kan bli körningar. Håll koll.',
          ),
          const _Level(
            color: TbColors.likelihoodLow,
            label: 'Svag',
            text: 'Bra att veta, sällan värt att åka.',
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
      label: 'Sida ${index + 1} av $count',
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
