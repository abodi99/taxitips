import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import 'analytics.dart';
import 'api_client.dart';
import 'push_service.dart';
import 'screens/driver_screen.dart';
import 'screens/join_screen.dart';
import 'screens/login_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/signup_screen.dart';
import 'theme.dart';
import 'screens/welcome_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initFirebaseSafe();
  await initAnalyticsSafe();
  final api = ApiClient();
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

enum AppRoute { welcome, login, signup, join, shell, driverInvite, demo }

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
    } else if (uri.path.contains('join') || uri.path.contains('register')) {
      _route = AppRoute.join;
    } else if (uri.path.contains('demo')) {
      _route = AppRoute.demo;
    } else if (widget.api.sessionToken != null) {
      try {
        await widget.api.me();
        _route = AppRoute.shell;
        if (uri.path.contains('driver')) {
          // Keep the driver view as the only main destination.
        }
      } catch (_) {
        await widget.api.saveSession(null);
        _route = AppRoute.welcome;
      }
    } else if (widget.api.deviceToken != null) {
      _route = AppRoute.shell;
    }
    if (mounted) setState(() => _booting = false);
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
      title: 'Taxi Tips',
      theme: buildTaxiTheme(),
      debugShowCheckedModeBanner: false,
      navigatorObservers: [?observer],
      home: _booting
          ? const _SplashScreen()
          : switch (_route) {
              AppRoute.login => LoginScreen(
                api: widget.api,
                onLoggedIn: _goShell,
                onSignup: () => setState(() => _route = AppRoute.signup),
                onJoinPhone: () => setState(() => _route = AppRoute.join),
                onBack: () => setState(() => _route = AppRoute.welcome),
                onDemo: () => setState(() => _route = AppRoute.demo),
              ),
              AppRoute.welcome => WelcomeScreen(
                onLogin: () => setState(() => _route = AppRoute.login),
                onSignup: () => setState(() => _route = AppRoute.signup),
              ),
              AppRoute.signup => SignupScreen(
                api: widget.api,
                onDone: () {
                  _goShell();
                },
                onLogin: () => setState(() => _route = AppRoute.welcome),
                onBack: () => setState(() => _route = AppRoute.welcome),
              ),
              AppRoute.join => JoinScreen(
                api: widget.api,
                onJoined: _goShell,
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
              AppRoute.demo => DriverScreen(
                api: widget.api,
                demo: true,
                onBack: () => setState(() => _route = AppRoute.welcome),
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
              height: 74,
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

class _AppShell extends StatelessWidget {
  const _AppShell({
    required this.api,
    required this.onLogout,
    required this.onLeftDevice,
  });

  final ApiClient api;
  final VoidCallback onLogout;
  final VoidCallback onLeftDevice;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DriverScreen(
        api: api,
        demo: false,
        onLeftDevice: onLeftDevice,
        onOpenSettings: () {
          Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => SettingsScreen(
                api: api,
                onLogout: onLogout,
                onLeftDevice: () {
                  Navigator.of(context).pop();
                  onLeftDevice();
                },
              ),
            ),
          );
        },
      ),
    );
  }
}
