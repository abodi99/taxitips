import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config.dart';
import '../theme.dart';

/// Välkomstskärmen: två val, inget mer. Logga in (förare, ägare och kontor
/// har samma inloggning) eller registrera ett nytt företag. Knapparna ligger
/// nere, där tummen når dem.
class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({
    super.key,
    required this.onLogin,
    required this.onSignup,
  });

  final VoidCallback onLogin;
  final VoidCallback onSignup;

  /// Demon finns på webben (taxitips.se/demo): samma slags tips på en
  /// Sverigekarta, utan konto.
  Future<void> _openDemo(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    var opened = false;
    try {
      opened = await launchUrl(
        Uri.parse(TaxiTipsConfig.demoUrl),
        mode: LaunchMode.externalApplication,
      );
    } catch (_) {}
    if (!opened) {
      messenger.showSnackBar(
        const SnackBar(content: Text('Kunde inte öppna webbläsaren')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.navy,
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            // Minst skärmens höjd, så att spaceBetween lägger knapparna nere
            // vid tummen; längre innehåll scrollar.
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: IntrinsicHeight(
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 420),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const SizedBox(height: 56),
                        Column(
                          children: [
                            SvgPicture.asset(
                              'assets/brand/logo-on-dark.svg',
                              width: 260,
                              height: 76,
                              fit: BoxFit.contain,
                            ),
                            const SizedBox(height: 40),
                            const Text(
                              'Se var folk behöver taxi',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                fontFamily: kDisplayFont,
                                color: TbColors.foam,
                                fontSize: 30,
                                height: 1.15,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            const SizedBox(height: 12),
                            const Text(
                              'Vi visar var körningarna finns — innan kön växer.',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                color: Colors.white70,
                                fontSize: 17,
                                height: 1.4,
                              ),
                            ),
                          ],
                        ),
                        Padding(
                          padding: const EdgeInsets.only(top: 40, bottom: 16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              FilledButton(
                                onPressed: onLogin,
                                style: FilledButton.styleFrom(
                                  backgroundColor: TbColors.taxi,
                                  foregroundColor: TbColors.ink,
                                  minimumSize: const Size.fromHeight(56),
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(14),
                                  ),
                                ),
                                child: const Text(
                                  'Logga in',
                                  style: TextStyle(
                                    fontSize: 17,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                              ),
                              const SizedBox(height: 12),
                              OutlinedButton(
                                onPressed: onSignup,
                                style: OutlinedButton.styleFrom(
                                  foregroundColor: TbColors.foam,
                                  side: const BorderSide(
                                    color: Colors.white54,
                                    width: 1.5,
                                  ),
                                  minimumSize: const Size.fromHeight(56),
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(14),
                                  ),
                                ),
                                child: const Text(
                                  'Registrera företag',
                                  style: TextStyle(
                                    fontSize: 17,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                              const SizedBox(height: 10),
                              const Text(
                                'Gratis i 7 dagar. Inget kort.',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  color: Colors.white60,
                                  fontSize: 13.5,
                                ),
                              ),
                              if (!kIsWeb)
                                TextButton(
                                  onPressed: () => _openDemo(context),
                                  style: TextButton.styleFrom(
                                    foregroundColor: Colors.white70,
                                    minimumSize: const Size.fromHeight(48),
                                  ),
                                  child: const Text(
                                    'Se demon på webben',
                                    style: TextStyle(
                                      decoration: TextDecoration.underline,
                                    ),
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
