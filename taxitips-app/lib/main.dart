import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_svg/flutter_svg.dart';

import 'analytics.dart';
import 'api_client.dart';
import 'client_info.dart';
import 'client_log.dart';
import 'crashlytics.dart';
import 'net_status.dart';
import 'performance_monitoring.dart';
import 'push_service.dart';
import 'remote_config_service.dart';
import 'screens/driver_screen.dart';
import 'screens/login_screen.dart';
import 'screens/membership_county_screen.dart';
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
  membershipCounty,
  shell,
  driverInvite,
  loginError,
}

class _TaxiPrognosAppState extends State<TaxiPrognosApp> {
  late AppRoute _route;
  String? _invite;
  // Medlemskapet länvalet gäller, när kontot redan har en plats (inbjuden
  // förare). Null = ett nytt prov utan plats ännu.
  Map<String, dynamic>? _membership;
  bool _booting = true;
  // Felmeddelande när inloggning/registrering inte kunde slutföras.
  String? _loginError;

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
        unawaited(_afterLogin());
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
  /// klart innan appen visas, och medlemskapet tas (eller länen väljs).
  ///
  /// Blev företaget registrerat just nu (länken i mejlet, sedan inloggning)
  /// får ägaren alltid länvalet och välkomsten till provet, innan appen öppnas.
  Future<void> _afterLogin() async {
    final Map<String, dynamic>? registered;
    try {
      registered = await widget.api.completePendingRegistration();
    } catch (e) {
      _showLoginError(friendlyError(e));
      return;
    }
    if (!mounted) return;
    // Registrerades företaget just nu är nästa steg alltid länvalet -- oavsett
    // vad medlemskapsanropen nedan råkar svara under en ostadig uppkoppling.
    if (registered != null && registered['created'] == true) {
      // Inget prov (t.ex. organisationsnumret har redan haft ett de senaste 24
      // månaderna): visa serverns besked i stället för att skicka ägaren till
      // länvalet, där "Provet är inte aktivt" annars möter hen utan förklaring.
      if (registered['trial'] == null) {
        final message = registered['message']?.toString();
        _showLoginError(
          (message != null && message.isNotEmpty)
              ? message
              : 'Kontot är skapat men provet kunde inte starta. Kontakta TaxiTips.',
        );
        return;
      }
      // Varje nytt företag får sin egen välkomst till provet, även om samma
      // telefon sett den för ett tidigare företag -- nollställ innan länvalet.
      await TrialWelcomeScreen.resetSeen();
      _membership = null;
      setState(() {
        _route = AppRoute.membershipCounty;
        _invite = null;
      });
      return;
    }
    await _enterApp();
  }

  /// Skärmen efter inloggning, avgjord av servern -- appen räknar inte ut något
  /// som servern redan vet.
  ///
  /// 1. Kontots medlemskap: saknas län väljs de (kontobaserat medlemskap), och
  ///    annars tas platsen i appen (en öppen session per konto).
  /// 2. Ett nytt prov utan plats ännu: ägaren väljer län först ("registrera dig,
  ///    bekräfta med kod, tillbaka i appen och välj län").
  /// 3. Allt annat: rakt in i appen, som förut.
  Future<void> _enterApp() async {
    Map<String, dynamic> m;
    try {
      m = await widget.api.memberships();
    } catch (e) {
      _showLoginError(friendlyError(e));
      return;
    }
    final list = (m['memberships'] as List?) ?? const [];
    if (list.isNotEmpty) {
      final activeId = m['activeLicenseId']?.toString();
      Map<String, dynamic>? chosen;
      for (final row in list) {
        if (row is Map &&
            activeId != null &&
            row['licenseId']?.toString() == activeId) {
          chosen = Map<String, dynamic>.from(row);
          break;
        }
      }
      chosen ??= Map<String, dynamic>.from(list.first as Map);
      if (((chosen['counties'] as List?) ?? const []).isEmpty) {
        if (!mounted) return;
        _membership = chosen;
        setState(() {
          _route = AppRoute.membershipCounty;
          _invite = null;
        });
        return;
      }
      try {
        await widget.api.startMembershipSession(
          licenseId: chosen['licenseId']?.toString(),
        );
      } catch (e) {
        _showLoginError(friendlyError(e));
        return;
      }
      _goShell();
      return;
    }

    Map<String, dynamic> data;
    try {
      data = await widget.api.fleetCompany();
    } catch (e) {
      _showLoginError(friendlyError(e));
      return;
    }
    final trial = data['trial'];
    final licenses = (data['licenses'] as List?) ?? const [];
    // Provet är numera aktivt redan efter e-postbekräftelsen (inte bara
    // `pending`), men platsen saknas tills ägaren valt län i appen.
    final trialOpen =
        trial is Map && (trial['status'] == 'pending' || trial['status'] == 'active');
    if (trialOpen && licenses.isEmpty) {
      if (!mounted) return;
      _membership = null;
      setState(() {
        _route = AppRoute.membershipCounty;
        _invite = null;
      });
      return;
    }
    _goShell();
  }

  void _showLoginError(String message) {
    if (!mounted) return;
    setState(() {
      _loginError = message;
      _route = AppRoute.loginError;
      _invite = null;
    });
  }

  Future<void> _logoutToLogin() async {
    await widget.api.leaveAll();
    if (!mounted) return;
    setState(() {
      _loginError = null;
      _route = AppRoute.login;
    });
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
      _loginError = null;
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
                // Konto skapat och e-post bekräftad: ta medlemskapet och välj
                // län (eller välkomsten till provet).
                onDone: () async {
                  await registerForPush(widget.api);
                  await _afterLogin();
                },
                onLogin: () => setState(() => _route = AppRoute.login),
                onBack: () => setState(() => _route = AppRoute.welcome),
              ),
              AppRoute.trialWelcome => TrialWelcomeScreen(
                api: widget.api,
                onDone: _goShell,
              ),
              // Registrerat och e-posten bekräftad: välj län för provet. Ett nytt
              // prov går vidare till välkomsten, en inbjuden förare rakt in.
              AppRoute.membershipCounty => MembershipCountyScreen(
                api: widget.api,
                licenseId: _membership?['licenseId']?.toString(),
                onDone: () {
                  final newTrial = _membership == null;
                  _membership = null;
                  if (newTrial) {
                    unawaited(_goAfterRegistration());
                  } else {
                    _goShell();
                  }
                },
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
              AppRoute.loginError => _LoginErrorScreen(
                message: _loginError ?? 'Något gick fel.',
                onRetry: () => unawaited(_afterLogin()),
                onLogout: () => unawaited(_logoutToLogin()),
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

/// Ett fel under inloggning/registrering som inte får sväljas: serverns text,
/// ett nytt försök och en utväg tillbaka till inloggningen.
class _LoginErrorScreen extends StatelessWidget {
  const _LoginErrorScreen({
    required this.message,
    required this.onRetry,
    required this.onLogout,
  });

  final String message;
  final VoidCallback onRetry;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.navy,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(),
              const Icon(
                Icons.error_outline_rounded,
                color: TbColors.taxi,
                size: 56,
              ),
              const SizedBox(height: 20),
              Text(
                message,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 17,
                  height: 1.4,
                ),
              ),
              const Spacer(),
              FilledButton(
                onPressed: onRetry,
                style: FilledButton.styleFrom(
                  backgroundColor: TbColors.taxi,
                  foregroundColor: TbColors.ink,
                  minimumSize: const Size.fromHeight(54),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
                child: const Text(
                  'Försök igen',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: onLogout,
                child: const Text(
                  'Logga ut',
                  style: TextStyle(color: Colors.white),
                ),
              ),
            ],
          ),
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
