import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_svg/flutter_svg.dart';

import 'analytics.dart';
import 'api_client.dart';
import 'client_info.dart';
import 'client_log.dart';
import 'crashlytics.dart';
import 'performance_monitoring.dart';
import 'push_service.dart';
import 'remote_config_service.dart';
import 'screens/driver_screen.dart';
import 'screens/join_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/signup_screen.dart';
import 'theme.dart';
import 'screens/welcome_screen.dart';
import 'widgets/force_upgrade_overlay.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initFirebaseSafe();
  await initRemoteConfigSafe();
  await initCrashlyticsSafe();
  await initPerformanceSafe();
  // Efter Crashlytics: våra hanterare kedjar på dess, så att båda får felet.
  ClientLog.installErrorHandlers();
  // Version och telefonmodell till headrarna. Högst en kort stund -- appen
  // startar hellre utan dem än väntar (lib/client_info.dart).
  await ClientInfo.load().timeout(
    const Duration(milliseconds: 1500),
    onTimeout: () {},
  );
  await initAnalyticsSafe();
  final api = ApiClient();
  ClientLog.attach(api.sendClientLog);
  await api.ensureInitialized();
  await api.loadTokens();
  runApp(TaxiPrognosApp(api: api));
}

class TaxiPrognosApp extends StatefulWidget {
  const TaxiPrognosApp({super.key, required this.api});

  final ApiClient api;

  @override
  State<TaxiPrognosApp> createState() => _TaxiPrognosAppState();
}

/// `welcome` är inloggningen -- en för förare, ägare och kontor
/// (screens/welcome_screen.dart). Rollen avgörs av servern efter inloggning.
enum AppRoute { welcome, signup, join, shell, driverInvite }

class _TaxiPrognosAppState extends State<TaxiPrognosApp> {
  late AppRoute _route;
  String? _invite;
  bool _booting = true;

  @override
  void initState() {
    super.initState();
    _route = AppRoute.welcome;
    widget.api.listenForAuthSignIn(() {
      if (!mounted) return;
      registerForPush(widget.api);
      if (_route == AppRoute.welcome || _route == AppRoute.signup) {
        _goShell();
      }
    });
    _boot();
  }

  Future<void> _boot() async {
    final frag = Uri.base.fragment;
    final path = frag.startsWith('/') ? frag : '/$frag';
    final uri = Uri.parse(
      path.contains('?') || path.startsWith('/')
          ? 'http://x$path'
          : 'http://x/$path',
    );
    final invite =
        uri.queryParameters['invite'] ?? uri.queryParameters['token'];

    if (invite != null && invite.isNotEmpty) {
      _invite = invite;
      _route = AppRoute.driverInvite;
    } else if (uri.path.contains('join') || uri.path.contains('register')) {
      _route = AppRoute.join;
    } else if (widget.api.sessionToken != null) {
      try {
        await widget.api.me();
        _route = AppRoute.shell;
        // Befintlig session: koppla enhet + uppdatera last_seen / FCM.
        unawaited(registerForPush(widget.api));
        if (uri.path.contains('driver')) {
          // Keep the driver view as the only main destination.
        }
      } catch (_) {
        await widget.api.saveSession(null);
        _route = AppRoute.welcome;
      }
    } else if (widget.api.deviceToken != null) {
      _route = AppRoute.shell;
      // FCM-permission får inte blockera boot (hänger ofta på webben).
      unawaited(registerForPush(widget.api));
    }
    if (mounted) setState(() => _booting = false);
  }

  /// Efter inloggning: en registrering som väntade på bekräftad e-post görs
  /// klart innan appen visas. Ett fel där (t.ex. orgnr som redan finns) visas
  /// i företagspanelen, som försöker igen -- det får inte stänga ute kontot.
  Future<void> _afterLogin() async {
    try {
      await widget.api.completePendingRegistration();
    } catch (_) {}
    if (mounted) _goShell();
  }

  void _goShell() {
    setState(() {
      _route = AppRoute.shell;
      _invite = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final observer = analyticsObserver();
    return MaterialApp(
      title: 'Taxitips',
      theme: buildTaxiTheme(),
      // Svenska för datumväljare och andra Material-texter.
      locale: const Locale('sv'),
      supportedLocales: const [Locale('sv'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      debugShowCheckedModeBanner: false,
      navigatorObservers: [?observer],
      builder: (context, child) =>
          ForceUpgradeOverlay(child: child ?? const SizedBox.shrink()),
      home: _booting
          ? const _SplashScreen()
          : switch (_route) {
              AppRoute.welcome => WelcomeScreen(
                api: widget.api,
                // Ägare/kontor: registrering som väntade görs klart först.
                onOwner: () async {
                  await registerForPush(widget.api);
                  await _afterLogin();
                },
                // Förare: telefonen är kopplad till bilen, samma väg som en kod.
                onDriver: () async {
                  await registerForPush(widget.api);
                  _goShell();
                },
                onUseCode: () => setState(() => _route = AppRoute.join),
                onSignup: () => setState(() => _route = AppRoute.signup),
              ),
              AppRoute.signup => SignupScreen(
                api: widget.api,
                onDone: () async {
                  await registerForPush(widget.api);
                  _goShell();
                },
                onLogin: () => setState(() => _route = AppRoute.welcome),
                onBack: () => setState(() => _route = AppRoute.welcome),
              ),
              AppRoute.join => JoinScreen(
                api: widget.api,
                onJoined: () async {
                  await registerForPush(widget.api);
                  _goShell();
                },
                // Koden nås från inloggningen ("Anslut med kod").
                onBack: () => setState(() => _route = AppRoute.welcome),
              ),
              AppRoute.shell => _AppShell(
                api: widget.api,
                onLogout: () async {
                  await widget.api.logout();
                  setState(() {
                    _route = AppRoute.welcome;
                  });
                },
                onLeftDevice: () {
                  setState(() {
                    _route = AppRoute.welcome;
                  });
                },
              ),
              AppRoute.driverInvite => DriverScreen(
                api: widget.api,
                inviteToken: _invite,
                onBack: _goShell,
              ),
            },
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.navy,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SvgPicture.asset(
              'assets/brand/logo-on-dark.svg',
              width: 320,
              height: 93,
              fit: BoxFit.contain,
            ),
            SizedBox(height: 28),
            SizedBox(
              width: 22,
              height: 22,
              child: CircularProgressIndicator(
                strokeWidth: 2.5,
                color: TbColors.yellow,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AppShell extends StatefulWidget {
  const _AppShell({
    required this.api,
    required this.onLogout,
    required this.onLeftDevice,
  });

  final ApiClient api;
  final VoidCallback onLogout;
  final VoidCallback onLeftDevice;

  @override
  State<_AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<_AppShell> {
  /// Byts när telefonen kopplats till en bil från inställningarna ("Kör
  /// bilen själv"). Förarskärmen byggs då om från början, med den nya bilens
  /// län och pass -- annars låg den gamla vyn kvar tills appen startades om.
  int _driverEpoch = 0;

  Future<void> _openSettings(BuildContext context) async {
    final tokenBefore = widget.api.deviceToken;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => SettingsScreen(
          api: widget.api,
          onLogout: widget.onLogout,
          onLeftDevice: () {
            Navigator.of(context).pop();
            widget.onLeftDevice();
          },
        ),
      ),
    );
    if (mounted && widget.api.deviceToken != tokenBefore) {
      setState(() => _driverEpoch++);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DriverScreen(
        key: ValueKey(_driverEpoch),
        api: widget.api,
        onLeftDevice: widget.onLeftDevice,
        onOpenSettings: () => _openSettings(context),
      ),
    );
  }
}
