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
import 'screens/login_screen.dart';
import 'screens/onboarding_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/signup_screen.dart';
import 'screens/trial_welcome_screen.dart';
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

/// Första start: onboarding → välkomst (Logga in / Registrera). Inloggningen
/// är en för förare, ägare och kontor, bara e-post och lösenord; rollen
/// avgörs av servern (ApiClient.signIn). Ingen bolagskod.
///
/// `trialWelcome` är ägarens välkomst till provet, en gång direkt efter att
/// ett nytt företag registrerats (TrialWelcomeScreen).
enum AppRoute {
  onboarding,
  welcome,
  login,
  signup,
  trialWelcome,
  shell,
  driverInvite,
}

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
      if (_route == AppRoute.welcome ||
          _route == AppRoute.login ||
          _route == AppRoute.signup) {
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
    } else if (uri.path.contains('register')) {
      _route = AppRoute.signup;
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
    // Första starten utan konto: introduktionen före välkomstskärmen, en
    // gång efter installationen. Startar appen i något annat läge (en
    // inloggning som redan finns, en inbjudan, en registreringslänk) är
    // introduktionen avklarad: den ska inte dyka upp först när föraren loggat
    // ut och startar om. Huvudskärmens guidade genomgång tar över.
    if (_route == AppRoute.welcome) {
      if (!await OnboardingScreen.seen()) _route = AppRoute.onboarding;
    } else {
      unawaited(OnboardingScreen.markSeen());
    }
    if (mounted) setState(() => _booting = false);
  }

  /// Efter inloggning: en registrering som väntade på bekräftad e-post görs
  /// klart innan appen visas. Ett fel där (t.ex. orgnr som redan finns) visas
  /// i företagspanelen, som försöker igen -- det får inte stänga ute kontot.
  ///
  /// Blev företaget registrerat just nu (länken i mejlet, sedan inloggning)
  /// får ägaren välkomsten till provet, precis som efter koden i appen.
  Future<void> _afterLogin() async {
    Map<String, dynamic>? registered;
    try {
      registered = await widget.api.completePendingRegistration();
    } catch (_) {}
    if (!mounted) return;
    if (registered?['created'] == true) {
      await _goAfterRegistration();
    } else {
      _goShell();
    }
  }

  /// Ett nytt företag är registrerat: välkomsten till provet, en gång. Är den
  /// redan sedd går ägaren rakt in i appen. Den finns kvar i Inställningar.
  Future<void> _goAfterRegistration() async {
    if (await TrialWelcomeScreen.seen()) {
      if (mounted) _goShell();
      return;
    }
    if (!mounted) return;
    setState(() {
      _route = AppRoute.trialWelcome;
      _invite = null;
    });
  }

  void _goShell() {
    // Inloggad: introduktionen är avklarad, också när den hoppades över.
    unawaited(OnboardingScreen.markSeen());
    setState(() {
      _route = AppRoute.shell;
      _invite = null;
    });
  }

  AppRoute? _loggedRoute;

  /// En skärmvisning per byte (inte per omritning).
  void _logRoute() {
    if (_booting || _loggedRoute == _route) return;
    _loggedRoute = _route;
    unawaited(logScreen(_route.name));
  }

  @override
  Widget build(BuildContext context) {
    _logRoute();
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
              AppRoute.onboarding => OnboardingScreen(
                onDone: () => setState(() => _route = AppRoute.welcome),
              ),
              AppRoute.welcome => WelcomeScreen(
                onLogin: () => setState(() => _route = AppRoute.login),
                onSignup: () => setState(() => _route = AppRoute.signup),
              ),
              // Alla loggar in med e-post och lösenord: ägare, kontor och förare
              // (ägarens beslut 2026-10-04). Servern avgör vem som loggade in.
              AppRoute.login => LoginScreen(
                api: widget.api,
                // Ägare/kontor: registrering som väntade görs klart först.
                onOwner: () async {
                  await logAnalyticsEvent(
                    'login',
                    params: {'method': 'email', 'role': 'owner'},
                  );
                  await registerForPush(widget.api);
                  await _afterLogin();
                },
                // Förare: telefonen är kopplad till bilen.
                onDriver: () async {
                  await logAnalyticsEvent(
                    'login',
                    params: {'method': 'email', 'role': 'driver'},
                  );
                  await registerForPush(widget.api);
                  _goShell();
                },
                onSignup: () => setState(() => _route = AppRoute.signup),
                onBack: () => setState(() => _route = AppRoute.welcome),
              ),
              AppRoute.signup => SignupScreen(
                api: widget.api,
                // Konto skapat och e-post bekräftad: välkomsten till provet.
                onDone: () async {
                  await registerForPush(widget.api);
                  await _goAfterRegistration();
                },
                onLogin: () => setState(() => _route = AppRoute.login),
                onBack: () => setState(() => _route = AppRoute.welcome),
              ),
              AppRoute.trialWelcome => TrialWelcomeScreen(
                api: widget.api,
                onDone: _goShell,
              ),
              AppRoute.shell => _AppShell(
                api: widget.api,
                // Utloggning lämnar telefonen helt: kontot OCH telefonens
                // koppling. Annars startade appen nästa gång direkt i
                // förarläget med det förra kontots bolag. Installations-id:t
                // ligger kvar, så samma telefon känns igen vid nästa inloggning
                // (räknas inte som ett telefonbyte).
                onLogout: () async {
                  await widget.api.leaveAll();
                  if (mounted) setState(() => _route = AppRoute.login);
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

  /// Förarskärmen läser om när Inställningarna stängs (nytt län, ny bil).
  final _driverRefresh = ValueNotifier<int>(0);

  /// "Visa genomgången igen" i Inställningar: förarskärmen startar den guidade
  /// genomgången när Inställningarna stängts.
  final _driverTour = ValueNotifier<int>(0);

  @override
  void dispose() {
    _driverRefresh.dispose();
    _driverTour.dispose();
    super.dispose();
  }

  Future<void> _openSettings(BuildContext context) async {
    final tokenBefore = widget.api.deviceToken;
    final showTour = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => SettingsScreen(
          api: widget.api,
          onShowTour: () => Navigator.of(context).pop(true),
          // Stäng inställningarna först: de låg annars kvar ovanpå
          // inloggningen, halvt utloggade.
          onLogout: () {
            Navigator.of(context).popUntil((route) => route.isFirst);
            widget.onLogout();
          },
          onLeftDevice: () {
            Navigator.of(context).pop();
            widget.onLeftDevice();
          },
        ),
      ),
    );
    if (mounted && widget.api.deviceToken != tokenBefore) {
      setState(() => _driverEpoch++);
    } else if (mounted) {
      _driverRefresh.value++;
    }
    // Efter bilden ovan: en ny förarskärm (ny bil) hinner då lyssna först.
    if (showTour == true && mounted) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _driverTour.value++;
      });
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
        refresh: _driverRefresh,
        tourRequest: _driverTour,
      ),
    );
  }
}
