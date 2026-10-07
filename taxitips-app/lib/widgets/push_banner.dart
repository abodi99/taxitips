/// Notisen som kommer medan appen är öppen, visad som appens eget kort --
/// inte som en rå `SnackBar`.
///
/// Android visar INGEN systemnotis när appen ligger i förgrunden, så appen
/// måste visa den själv (lib/push_service.dart). Den gamla visningen skrev
/// `"$title\n$body"` som två radbrytna rader i bottenpanelen: ingen ikon,
/// ingen kategori, ingen tryckyta -- och en förare som lärt sig symbolerna på
/// kartan kände inte igen något. Kortet här ritas med SAMMA ikon, färg och
/// ord som kortet i listan och på kartan (lib/signal_kinds.dart): en sanning
/// för typ och styrka, även i notisen.
///
/// Banderollen ligger i appens rot-Overlay, alltså ovanför Navigatorn. En
/// notis behövs där föraren är -- i supportchatten och på inställningarna
/// lika väl som i listan -- och den ska inte gå att "backa" bort eller bli
/// kvar i historiken som en rutt.
library;

import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';

import '../signal_kinds.dart';
import '../theme.dart';

/// Det en notis bär in i appen, tolkat för visning.
///
/// Fälten kommer ur FCM-meddelandet: rubriken och texten ur `notification`,
/// resten ur `data` (core/notify.py `_send_due`). `kind` skickas med just
/// för ikonen -- utan den hade en färja och ett inställt tåg fått samma
/// symbol.
@immutable
class PushBannerData {
  const PushBannerData({
    required this.title,
    this.body = '',
    this.opportunityId = '',
    this.kind = '',
    this.severityTier = '',
    this.level = '',
    this.demandScore = 0,
    this.isSupportReply = false,
  });

  final String title;
  final String body;

  /// Tipset bakom notisen. Tomt för ett meddelande som inte handlar om ett.
  final String opportunityId;
  final String kind;
  final String severityTier;

  /// Backendens bedömning (`high`/`medium`/`low`), samma fält som listan
  /// färgar efter. Utan det räknar appen styrkan själv ur `worth_it_score`
  /// -- som notisen inte bär -- och allt blir "Svag".
  final String level;
  final num demandScore;
  final bool isSupportReply;

  /// En testnotis (`send_test_push` skickar `kind: test`) ska se ut som ett
  /// meddelande, aldrig som ett tips: ingen styrka och ingen färg en förare
  /// läser som "kör dit".
  bool get isTest => kind == 'test' && !isSupportReply;

  bool get isTip => !isSupportReply && !isTest;

  factory PushBannerData.fromMessage(RemoteMessage message) {
    final data = message.data;
    final type = data['type']?.toString() ?? '';
    return PushBannerData(
      title:
          message.notification?.title ?? data['title']?.toString() ?? 'TaxiTips',
      body: message.notification?.body ?? data['body']?.toString() ?? '',
      opportunityId: data['opportunity_id']?.toString() ?? '',
      kind: data['kind']?.toString() ?? '',
      severityTier: data['severity_tier']?.toString() ?? '',
      level: data['level']?.toString() ?? '',
      demandScore: (data['demand_score'] as num?) ?? 0,
      isSupportReply: type == 'support_reply',
    );
  }

  /// Tipset som en alert-lik rad, så att kategorin och styrkan räknas av
  /// samma kod som listan och kartan (lib/signal_kinds.dart).
  Map<String, dynamic> get asAlert => {
    'kind': kind,
    'severity_tier': severityTier,
    'level': level,
    'demand_score': demandScore,
  };

  SignalCategory get category => categoryOfAlert(asAlert);

  SignalStrength get strength => strengthOfAlert(asAlert);

  /// Färgen från styrkan. Bara ett tips har en styrka -- ett supportmeddelande
  /// har ingen, och en testnotis ska inte se ut som ett tips.
  Color get signalColor =>
      isTip ? strengthColor(strength, category: category) : TbColors.skiffer;

  IconData get icon => isSupportReply
      ? Icons.support_agent_rounded
      : isTest
      ? Icons.notifications_rounded
      : category.icon;

  /// Raden ovanför rubriken: vad det är, och hur starkt. Ett ord räcker --
  /// samma ord som i kortet (signal_kinds.strengthWord).
  String get eyebrow => isSupportReply
      ? 'Support'
      : isTest
      ? 'Testnotis'
      : '${strengthWord(strength, category: category)} · ${category.label}';
}

/// Kortet. Ren presentation -- anroparen äger tryck och stängning, så att
/// widgettestet kan pröva det utan en Overlay.
class PushBanner extends StatelessWidget {
  const PushBanner({
    super.key,
    required this.data,
    this.onOpen,
    this.onDismiss,
  });

  final PushBannerData data;

  /// Öppnar det notisen handlar om. Null = inget att öppna (t.ex. en
  /// testnotis); då är kortet inte tryckbart.
  final VoidCallback? onOpen;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    final accent = data.signalColor;
    return Semantics(
      liveRegion: true,
      button: onOpen != null,
      label: 'Notis: ${data.eyebrow}. ${data.title}. ${data.body}',
      child: Material(
        color: TbColors.vit,
        elevation: 10,
        shadowColor: Colors.black38,
        borderRadius: BorderRadius.circular(16),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onOpen,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 6, 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: accent.withValues(alpha: 0.14),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(data.icon, size: 22, color: accent),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        data.eyebrow,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 0.3,
                          color: accent,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        data.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                          color: TbColors.ink,
                        ),
                      ),
                      if (data.body.isNotEmpty) ...[
                        const SizedBox(height: 3),
                        Text(
                          data.body,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 13,
                            height: 1.35,
                            color: Colors.grey.shade700,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                if (data.isTip && onOpen != null)
                  const Padding(
                    padding: EdgeInsets.only(top: 20, right: 4),
                    child: Text(
                      'Visa',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w800,
                        color: TbColors.taxiDeep,
                      ),
                    ),
                  ),
                if (onDismiss != null)
                  IconButton(
                    onPressed: onDismiss,
                    icon: const Icon(Icons.close, size: 18),
                    color: Colors.grey.shade500,
                    tooltip: 'Stäng',
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}


/// Visar notisen högst upp i appen. En ny notis ersätter den förra -- samma
/// sak en riktig notis gör, och samma sak den gamla SnackBar:en gjorde.
void showPushBanner(
  BuildContext context,
  PushBannerData data, {
  VoidCallback? onOpen,
  Duration duration = const Duration(seconds: 8),
}) {
  final overlay = Overlay.maybeOf(context, rootOverlay: true);
  if (overlay == null) return;
  hidePushBanner();
  // `late` för att stängningen nedan jämför sig med posten som just skapas.
  late final _BannerHandle handle;
  handle = _BannerHandle(
    overlay: overlay,
    data: data,
    onOpen: onOpen,
    duration: duration,
    onGone: () {
      if (identical(_activeBanner, handle)) _activeBanner = null;
    },
  );
  _activeBanner = handle;
  handle.insert();
}

/// Tar bort banderollen om en visas. Anropas när nästa notis kommer, och av
/// en skärm som lämnas medan notisen ligger uppe.
void hidePushBanner() {
  final active = _activeBanner;
  _activeBanner = null;
  active?.dismiss();
}

_BannerHandle? _activeBanner;

/// Håller Overlay-posten och låter widgeten spela klart sin utgång först.
class _BannerHandle {
  _BannerHandle({
    required this.overlay,
    required this.data,
    required this.duration,
    required this.onGone,
    this.onOpen,
  });

  final OverlayState overlay;
  final PushBannerData data;
  final Duration duration;
  final VoidCallback onGone;
  final VoidCallback? onOpen;

  final GlobalKey<_PushBannerHostState> _key = GlobalKey<_PushBannerHostState>();
  OverlayEntry? _entry;
  bool _gone = false;

  void insert() {
    _entry = OverlayEntry(
      builder: (_) => _PushBannerHost(
        key: _key,
        data: data,
        onOpen: onOpen,
        duration: duration,
        onGone: remove,
      ),
    );
    overlay.insert(_entry!);
  }

  /// Stäng nu: låt widgeten animera ut om den hunnit byggas, annars bort med
  /// posten direkt (notisen hann aldrig synas).
  void dismiss() {
    final state = _key.currentState;
    if (state != null) {
      unawaited(state.close());
      return;
    }
    remove();
  }

  void remove() {
    if (_gone) return;
    _gone = true;
    _entry?.remove();
    _entry = null;
    onGone();
  }
}

class _PushBannerHost extends StatefulWidget {
  const _PushBannerHost({
    super.key,
    required this.data,
    required this.duration,
    required this.onGone,
    this.onOpen,
  });

  final PushBannerData data;
  final Duration duration;
  final VoidCallback onGone;
  final VoidCallback? onOpen;

  @override
  State<_PushBannerHost> createState() => _PushBannerHostState();
}

class _PushBannerHostState extends State<_PushBannerHost>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 240),
    reverseDuration: const Duration(milliseconds: 180),
  );
  Timer? _timer;
  bool _closing = false;

  @override
  void initState() {
    super.initState();
    _controller.forward();
    _timer = Timer(widget.duration, () => unawaited(close()));
  }

  @override
  void dispose() {
    _timer?.cancel();
    _controller.dispose();
    super.dispose();
  }

  /// Glider ut och tar bort posten. Idempotent: timern, krysset, svepet och en
  /// ny notis kan alla komma samtidigt.
  Future<void> close() async {
    if (_closing) return;
    _closing = true;
    _timer?.cancel();
    if (mounted) await _controller.reverse();
    widget.onGone();
  }

  void _open() {
    final open = widget.onOpen;
    unawaited(close());
    open?.call();
  }

  @override
  Widget build(BuildContext context) {
    final slide = Tween<Offset>(
      begin: const Offset(0, -1.2),
      end: Offset.zero,
    ).chain(CurveTween(curve: Curves.easeOutCubic)).animate(_controller);

    return Positioned(
      top: 0,
      left: 0,
      right: 0,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: FadeTransition(
            opacity: _controller,
            child: SlideTransition(
              position: slide,
              child: Dismissible(
                key: const ValueKey('push-banner'),
                direction: DismissDirection.up,
                onDismissed: (_) => unawaited(close()),
                child: PushBanner(
                  data: widget.data,
                  onOpen: widget.onOpen == null ? null : _open,
                  onDismiss: () => unawaited(close()),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

