import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../analytics.dart';
import '../api_client.dart';
import '../membership_copy.dart';
import '../signal_kinds.dart';
import '../theme.dart';

/// Välkomsten till provet: visas för ägaren en gång, direkt efter att företaget
/// registrerats och e-posten bekräftats, och går att öppna igen från
/// Inställningar ("Så fungerar Taxi Tips").
///
/// Fyra sidor, en sak per sida, enkel svenska -- många förare och ägare har
/// svenska som andraspråk: vad Taxi Tips gör, provet, nästa steg och vad som
/// ingår. "Hoppa över" finns hela tiden.
///
/// **Vad som gäller kommer från servern.** Provets längd, start och slut ur
/// `GET /api/fleet/company` (`trial`), och vilka kategorier som ingår ur
/// `features` (fleet/features.py). Appen räknar inte ut åtkomst själv: saknas
/// uppgiften säger sidan det i stället för att gissa. **Inget säljs här** --
/// ingen länk, inget pris, ingen knapp till en betalning (membership_copy.dart).
class TrialWelcomeScreen extends StatefulWidget {
  const TrialWelcomeScreen({
    super.key,
    required this.api,
    required this.onDone,
    this.replay = false,
  });

  final ApiClient api;
  final VoidCallback onDone;

  /// Öppnad igen från Inställningar: "Stäng" i stället för "Hoppa över".
  final bool replay;

  /// Bumpa versionen när innehållet ändras så mycket att alla bör se det igen.
  static const seenKey = 'tt_trial_welcome_seen_v1';

  static Future<bool> seen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(seenKey) ?? false;
    } catch (_) {
      return true; // Hellre ingen välkomst än en som fastnar.
    }
  }

  /// Från Inställningar: samma sidor, och tillbaka dit med Stäng/Klar.
  static Future<void> openFromSettings(BuildContext context, ApiClient api) {
    return Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (ctx) => TrialWelcomeScreen(
          api: api,
          replay: true,
          onDone: () => Navigator.of(ctx).pop(),
        ),
      ),
    );
  }

  @override
  State<TrialWelcomeScreen> createState() => _TrialWelcomeScreenState();
}

/// Det servern sagt om provet, för sidorna 2 och 4. Allt är valfritt: ett fält
/// som saknas visas inte, det gissas inte.
class TrialWelcomeInfo {
  const TrialWelcomeInfo({
    this.status,
    this.days,
    this.endsAt,
    this.vehicleLimit,
    this.included,
    this.locked,
  });

  /// `pending` (startar vid första telefonen), `active`, annat = slut.
  final String? status;

  /// Provets längd i dagar: `plannedDays`, annars start till slut.
  final int? days;
  final DateTime? endsAt;
  final int? vehicleLimit;

  /// Kategorierna ur `features`. Null = servern sa inget.
  final List<SignalCategory>? included;
  final List<SignalCategory>? locked;

  bool get hasFeatures => included != null && locked != null;

  static TrialWelcomeInfo fromServer({
    Map<String, dynamic>? company,
    Map<String, dynamic>? features,
  }) {
    final trial = company?['trial'] is Map
        ? Map<String, dynamic>.from(company!['trial'] as Map)
        : null;
    int? days = (trial?['plannedDays'] as num?)?.toInt();
    final startedAt = DateTime.tryParse(trial?['startedAt']?.toString() ?? '');
    final endsAt = DateTime.tryParse(trial?['endsAt']?.toString() ?? '');
    if (days == null && startedAt != null && endsAt != null) {
      days = (endsAt.difference(startedAt).inHours / 24).round();
    }
    if (days != null && days <= 0) days = null;

    List<SignalCategory>? pick(Object? raw) => raw is List
        ? [
            for (final c in signalCategoryOrder)
              if (raw.any((k) => signalCategoryFromFeatureKey(k) == c)) c,
          ]
        : null;

    return TrialWelcomeInfo(
      status: trial?['status']?.toString(),
      days: days,
      endsAt: endsAt?.toLocal(),
      vehicleLimit: (trial?['vehicleLimit'] as num?)?.toInt(),
      included: pick(features?['categories']),
      locked: pick(features?['locked']),
    );
  }
}

class _TrialWelcomeScreenState extends State<TrialWelcomeScreen> {
  static const _pageCount = 4;

  final _pages = PageController();
  int _page = 0;
  TrialWelcomeInfo _info = const TrialWelcomeInfo();

  @override
  void initState() {
    super.initState();
    // Sedd redan när den visas, som introduktionen: den som stänger appen mitt
    // i ska inte mötas av den igen. Inställningar har den kvar.
    unawaited(_markSeen());
    unawaited(_load());
  }

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  static Future<void> _markSeen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(TrialWelcomeScreen.seenKey, true);
    } catch (_) {}
  }

  /// Provet och funktionerna ur servern. Ett fel här stoppar ingenting: sidorna
  /// står på egna ben utan siffror.
  Future<void> _load() async {
    Map<String, dynamic>? company;
    Map<String, dynamic>? features;
    try {
      company = await widget.api.fleetCompany();
      if (company['features'] is Map) {
        features = Map<String, dynamic>.from(company['features'] as Map);
      }
    } catch (_) {}
    if (features == null) {
      try {
        final prefs = await widget.api.getNotifyPrefs();
        if (prefs['features'] is Map) {
          features = Map<String, dynamic>.from(prefs['features'] as Map);
        }
      } catch (_) {}
    }
    if (!mounted) return;
    setState(
      () => _info = TrialWelcomeInfo.fromServer(
        company: company,
        features: features,
      ),
    );
  }

  bool get _last => _page == _pageCount - 1;

  Future<void> _finish({required bool skipped}) async {
    await logAnalyticsEvent(
      skipped ? 'trial_welcome_skip' : 'trial_welcome_complete',
      params: {'page': _page + 1, 'replay': widget.replay ? 1 : 0},
    );
    widget.onDone();
  }

  void _next() {
    if (_last) {
      unawaited(_finish(skipped: false));
      return;
    }
    _pages.nextPage(
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeOut,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.foam,
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: Alignment.centerRight,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(8, 4, 8, 0),
                child: TextButton(
                  onPressed: () => _finish(skipped: true),
                  style: TextButton.styleFrom(
                    foregroundColor: TbColors.ink,
                    minimumSize: const Size(48, 48),
                  ),
                  child: Text(
                    widget.replay ? 'Stäng' : 'Hoppa över',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
              ),
            ),
            Expanded(
              child: PageView(
                controller: _pages,
                onPageChanged: (i) => setState(() => _page = i),
                children: [
                  const _WhatPage(),
                  _TrialPage(info: _info),
                  const _StepsPage(),
                  _IncludedPage(info: _info),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 8, 24, 20),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Semantics(
                    label: 'Sida ${_page + 1} av $_pageCount',
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        for (var i = 0; i < _pageCount; i++)
                          AnimatedContainer(
                            duration: const Duration(milliseconds: 250),
                            margin: const EdgeInsets.symmetric(horizontal: 4),
                            width: i == _page ? 24 : 8,
                            height: 8,
                            decoration: BoxDecoration(
                              color: TbColors.ink.withValues(
                                alpha: i == _page ? 0.9 : 0.25,
                              ),
                              borderRadius: BorderRadius.circular(4),
                            ),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: _next,
                      style: FilledButton.styleFrom(
                        backgroundColor: TbColors.taxi,
                        foregroundColor: TbColors.ink,
                        minimumSize: const Size.fromHeight(56),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14),
                        ),
                      ),
                      child: Text(
                        _last ? 'Klar' : 'Nästa',
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
          ],
        ),
      ),
    );
  }
}

/// Gemensam ram för en sida: ikon, rubrik och innehåll som kan rulla (stor
/// text eller liten telefon ska inte klippa något).
class _PageFrame extends StatelessWidget {
  const _PageFrame({
    required this.icon,
    required this.title,
    required this.children,
  });

  final IconData icon;
  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(
              color: TbColors.taxi.withValues(alpha: 0.18),
              borderRadius: BorderRadius.circular(22),
            ),
            child: Icon(icon, size: 40, color: TbColors.taxiDeep),
          ),
          const SizedBox(height: 20),
          Text(
            title,
            style: const TextStyle(
              fontFamily: kDisplayFont,
              color: TbColors.ink,
              fontSize: 28,
              height: 1.15,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 14),
          ...children,
        ],
      ),
    );
  }
}

const _bodyStyle = TextStyle(fontSize: 18, height: 1.45, color: TbColors.ink);

/// Sida 1: vad Taxi Tips gör, med kategorierna som finns i appen.
class _WhatPage extends StatelessWidget {
  const _WhatPage();

  /// En rad per kategori, med försiktigt språk: ett tips är en signal, aldrig
  /// ett löfte om kunder.
  static String _line(SignalCategory c) => switch (c) {
    SignalCategory.transit =>
      'Tåg och buss som är sena eller inställda. '
          'Sista avgången.',
    SignalCategory.road => 'Trafikolyckor som stoppar trafiken.',
    SignalCategory.flight => 'Flyg som är sena, eller när många flyg landar.',
    SignalCategory.ferry => 'Färjor som lägger till i hamnen.',
    SignalCategory.event => 'Event som slutar: match, konsert eller annat.',
  };

  @override
  Widget build(BuildContext context) {
    return _PageFrame(
      icon: Icons.location_on_rounded,
      title: 'Välkommen till Taxi Tips',
      children: [
        const Text(
          'Taxi Tips visar var folk kan behöva taxi just nu. Det är tips, '
          'inte löften. Du bestämmer själv om det är värt att åka.',
          style: _bodyStyle,
        ),
        const SizedBox(height: 18),
        const Text(
          'Vi bevakar',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w800,
            color: TbColors.muted,
          ),
        ),
        const SizedBox(height: 8),
        for (final c in signalCategoryOrder)
          _CategoryRow(category: c, text: _line(c)),
        const SizedBox(height: 8),
        const Text(
          'Färgen visar hur stark signalen är. En stark signal betyder att '
          'många sannolikt behöver taxi.',
          style: TextStyle(fontSize: 16, height: 1.4, color: TbColors.muted),
        ),
      ],
    );
  }
}

class _CategoryRow extends StatelessWidget {
  const _CategoryRow({
    required this.category,
    required this.text,
    this.lock = false,
  });

  final SignalCategory category;
  final String text;
  final bool lock;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: TbColors.line),
        ),
        child: Row(
          children: [
            Icon(category.icon, color: TbColors.midnatt, size: 28),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    category.label,
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w800,
                      color: TbColors.ink,
                    ),
                  ),
                  if (text.isNotEmpty)
                    Text(
                      text,
                      style: const TextStyle(
                        fontSize: 15,
                        height: 1.35,
                        color: TbColors.muted,
                      ),
                    ),
                ],
              ),
            ),
            if (lock) const Icon(Icons.lock_rounded, color: TbColors.skiffer),
          ],
        ),
      ),
    );
  }
}

/// Sida 2: provet. Längd och datum ur servern; saknas de sägs inget om dem.
class _TrialPage extends StatelessWidget {
  const _TrialPage({required this.info});

  final TrialWelcomeInfo info;

  static String _date(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-'
      '${d.day.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final days = info.days;
    final started = info.status == 'active';
    final ended =
        info.status != null && !['pending', 'active'].contains(info.status);
    final limit = info.vehicleLimit;
    return _PageFrame(
      icon: Icons.card_giftcard_rounded,
      title: days == null
          ? 'Du provar gratis'
          : 'Du provar gratis i $days dagar',
      children: [
        const Text('Det kostar inget att prova.', style: _bodyStyle),
        const SizedBox(height: 12),
        if (ended)
          const Text('Provet är slut. $kMembershipOnWeb', style: _bodyStyle)
        else if (started && info.endsAt != null)
          Text(
            'Provet pågår. Det gäller till ${_date(info.endsAt!)}.',
            style: _bodyStyle,
          )
        else
          Text(
            // "Tills dess går ingen tid" säger bara servern (status pending);
            // utan svar sägs bara när provet startar.
            info.status == 'pending'
                ? 'Provet startar när du kopplar den första telefonen. '
                      'Tills dess går ingen tid.'
                : 'Provet startar när du kopplar den första telefonen.',
            style: _bodyStyle,
          ),
        if (limit != null) ...[
          const SizedBox(height: 12),
          Text(
            limit == 1
                ? 'Du kan ha 1 bil i provet.'
                : 'Du kan ha upp till $limit bilar i provet.',
            style: _bodyStyle,
          ),
        ],
      ],
    );
  }
}

/// Sida 3: nästa steg, med var i appen man gör det.
class _StepsPage extends StatelessWidget {
  const _StepsPage();

  @override
  Widget build(BuildContext context) {
    return const _PageFrame(
      icon: Icons.flag_rounded,
      title: 'Så kommer du igång',
      children: [
        _Step(
          n: 1,
          title: 'Lägg till bil och välj län',
          text:
              'Öppna Inställningar och tryck på Lägg till bil. '
              'Länet styr vilka tips bilen får.',
        ),
        _Step(
          n: 2,
          title: 'Kör själv?',
          text: 'Öppna bilen och tryck på "Kör själv med den här telefonen".',
        ),
        _Step(
          n: 3,
          title: 'Bjud in förare med e-post',
          text:
              'Öppna bilen och tryck på "Bjud in förare med e-post". '
              'Föraren trycker på "Jag är förare" i appen och skriver '
              'koden som kommer i mejlet.',
        ),
      ],
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({required this.n, required this.title, required this.text});

  final int n;
  final String title;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 16,
            backgroundColor: TbColors.taxi,
            child: Text(
              '$n',
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w800,
                color: TbColors.ink,
              ),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    color: TbColors.ink,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  text,
                  style: const TextStyle(
                    fontSize: 16,
                    height: 1.4,
                    color: TbColors.muted,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Sida 4: vad som ingår i provet och vad som kräver medlemskap. Listorna är
/// serverns (`features`); utan dem säger sidan bara hur ett lås ser ut.
class _IncludedPage extends StatelessWidget {
  const _IncludedPage({required this.info});

  final TrialWelcomeInfo info;

  @override
  Widget build(BuildContext context) {
    final included = info.included ?? const <SignalCategory>[];
    final locked = info.locked ?? const <SignalCategory>[];
    return _PageFrame(
      icon: Icons.lock_open_rounded,
      title: 'Vad ingår i provet?',
      children: [
        if (!info.hasFeatures)
          const Text(
            'Det som ingår i provet ser du i appen. Det som inte ingår har '
            'ett lås.',
            style: _bodyStyle,
          )
        else ...[
          if (included.isNotEmpty) ...[
            const Text(
              'Ingår i provet',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w800,
                color: TbColors.live,
              ),
            ),
            const SizedBox(height: 8),
            for (final c in included) _CategoryRow(category: c, text: ''),
          ],
          if (locked.isNotEmpty) ...[
            const SizedBox(height: 8),
            const Text(
              kNotInTrial,
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w800,
                color: TbColors.muted,
              ),
            ),
            const SizedBox(height: 8),
            for (final c in locked)
              _CategoryRow(category: c, text: '', lock: true),
            const SizedBox(height: 8),
            const Text(
              'Det kräver medlemskap. $kMembershipOnWeb',
              style: _bodyStyle,
            ),
          ] else
            const Text('Allt ingår just nu.', style: _bodyStyle),
        ],
      ],
    );
  }
}
