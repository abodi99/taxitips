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

  /// Förare, ägare och kontor: samma inloggning med e-post och lösenord.
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
            // vid tummen; längre innehåll scrollar. Bredden begränsas FÖRE
            // IntrinsicHeight: annars mäts texten på hela bredden (liggande)
            // men ritas på 420, blir högre än mätt och spiller över nederkanten.
            child: Center(
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  minHeight: constraints.maxHeight,
                  maxWidth: 420,
                ),
                child: IntrinsicHeight(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // Tre knappar sedan förarvägen: på en låg skärm
                      // mindre luft upptill, så att allt får plats.
                      SizedBox(height: constraints.maxHeight < 700 ? 20 : 56),
                      Column(
                        children: [
                          SvgPicture.asset(
                            'assets/brand/logo-on-dark.svg',
                            width: 260,
                            height: 76,
                            fit: BoxFit.contain,
                          ),
                          SizedBox(
                            height: constraints.maxHeight < 700 ? 24 : 40,
                          ),
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
                        padding: EdgeInsets.only(
                          top: constraints.maxHeight < 700 ? 24 : 40,
                          bottom: 16,
                        ),
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
                            const SizedBox(height: 8),
                            const Text(
                              'För förare, ägare och kontor. Förare: '
                              'använd e-posten från inbjudan och lösenordet du valde.',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                color: Colors.white70,
                                fontSize: 14,
                                height: 1.35,
                              ),
                            ),
                            const SizedBox(height: 12),
                            TextButton(
                              onPressed: onSignup,
                              style: TextButton.styleFrom(
                                foregroundColor: TbColors.foam,
                                minimumSize: const Size.fromHeight(52),
                              ),
                              child: const Text(
                                'Registrera företag',
                                style: TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w700,
                                  decoration: TextDecoration.underline,
                                  decorationColor: TbColors.foam,
                                ),
                              ),
                            ),
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
    );
  }
}
