import 'package:flutter/material.dart';

import 'analytics.dart';
import 'api_client.dart';
import 'push_service.dart';
import 'screens/dashboard_screen.dart';
import 'screens/driver_screen.dart';
import 'screens/join_screen.dart';
import 'screens/login_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/signup_screen.dart';
import 'theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initFirebaseSafe();
  await initAnalyticsSafe();
  final api = ApiClient();
  await api.loadTokens();
  runApp(TaxiPrognosApp(api: api));
}

class TaxiPrognosApp extends StatefulWidget {
  const TaxiPrognosApp({super.key, required this.api});

  final ApiClient api;

  @override
  State<TaxiPrognosApp> createState() => _TaxiPrognosAppState();
}

enum AppRoute { login, signup, join, shell, driverInvite, demo }

class _TaxiPrognosAppState extends State<TaxiPrognosApp> {
  late AppRoute _route;
  String? _invite;
  String? _banner;
  bool _booting = true;
  int _tab = 0; // 0 = förare, 1 = kontor

  @override
  void initState() {
    super.initState();
    _route = AppRoute.login;
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
    if (uri.queryParameters['paid'] == '1') {
      _banner = 'Kontot är klart — välj orter och ge bolagskoden under Kontor.';
      _tab = 1;
    } else if (uri.queryParameters['canceled'] == '1') {
      _banner = 'Du kan fortsätta utan betalning i denna MVP.';
      _tab = 1;
    }

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
        if (uri.path.contains('driver')) _tab = 0;
        if (uri.path.contains('dashboard') || uri.path.contains('kontor'))
          _tab = 1;
      } catch (_) {
        await widget.api.saveSession(null);
        _route = AppRoute.login;
      }
    } else if (widget.api.deviceToken != null) {
      _route = AppRoute.shell;
      _tab = 0;
    }
    if (mounted) setState(() => _booting = false);
  }

  void _goShell({int tab = 0}) {
    setState(() {
      _route = AppRoute.shell;
      _tab = tab;
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
                onLoggedIn: () => _goShell(tab: 0),
                onSignup: () => setState(() => _route = AppRoute.signup),
                onJoinPhone: () => setState(() => _route = AppRoute.join),
                onDemo: () => setState(() => _route = AppRoute.demo),
              ),
              AppRoute.signup => SignupScreen(
                api: widget.api,
                onDone: () {
                  _banner =
                      'Konto skapat. 1) Välj orter  2) Ge bolagskoden till förarna.';
                  _goShell(tab: 1);
                },
                onLogin: () => setState(() => _route = AppRoute.login),
              ),
              AppRoute.join => JoinScreen(
                api: widget.api,
                onJoined: () => _goShell(tab: 0),
                onBack: () => setState(() => _route = AppRoute.login),
              ),
              AppRoute.shell => _AppShell(
                api: widget.api,
                tab: _tab,
                banner: _banner,
                onTab: (i) => setState(() {
                  _tab = i;
                  _banner = null;
                }),
                onLogout: () async {
                  await widget.api.logout();
                  setState(() {
                    _banner = null;
                    _route = AppRoute.login;
                  });
                },
                onLeftDevice: () {
                  setState(() {
                    _banner = null;
                    _route = AppRoute.login;
                  });
                },
              ),
              AppRoute.driverInvite => DriverScreen(
                api: widget.api,
                inviteToken: _invite,
                onBack: () => _goShell(tab: 0),
              ),
              AppRoute.demo => DriverScreen(
                api: widget.api,
                demo: true,
                onBack: () => setState(() => _route = AppRoute.login),
              ),
            },
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: TbColors.navy,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Image(
              image: AssetImage('assets/brand/splash_mark.png'),
              width: 128,
              height: 128,
              filterQuality: FilterQuality.high,
            ),
            SizedBox(height: 18),
            Image(
              image: AssetImage('assets/brand/splash_wordmark.png'),
              width: 240,
              filterQuality: FilterQuality.high,
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
    required this.tab,
    required this.onTab,
    required this.onLogout,
    required this.onLeftDevice,
    this.banner,
  });

  final ApiClient api;
  final int tab;
  final ValueChanged<int> onTab;
  final VoidCallback onLogout;
  final VoidCallback onLeftDevice;
  final String? banner;

  @override
  Widget build(BuildContext context) {
    final isLoggedIn = api.sessionToken != null;
    final destinations = <NavigationDestination>[
      const NavigationDestination(
        icon: Icon(Icons.local_taxi_outlined),
        selectedIcon: Icon(Icons.local_taxi),
        label: 'Förare',
      ),
      if (isLoggedIn)
        const NavigationDestination(
          icon: Icon(Icons.storefront_outlined),
          selectedIcon: Icon(Icons.storefront),
          label: 'Kontor',
        ),
    ];

    return Scaffold(
      body: IndexedStack(
        index: isLoggedIn ? tab.clamp(0, 1) : 0,
        children: [
          DriverScreen(
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
          if (isLoggedIn)
            DashboardScreen(
              api: api,
              banner: banner,
              onLogout: onLogout,
              onOpenDriver: () => onTab(0),
              onOpenSettings: () {
                Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => SettingsScreen(
                      api: api,
                      onLogout: () {
                        Navigator.of(context).pop();
                        onLogout();
                      },
                    ),
                  ),
                );
              },
            )
          else
            const SizedBox.shrink(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: isLoggedIn ? tab.clamp(0, 1) : 0,
        onDestinationSelected: onTab,
        destinations: destinations,
      ),
    );
  }
}
