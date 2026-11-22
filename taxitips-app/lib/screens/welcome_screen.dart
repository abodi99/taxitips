import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config.dart';
import '../l10n/l10n.dart';
import '../theme.dart';
import '../widgets/language_picker.dart';

/// Välkomstskärmen: loggan, en rad och två knappar -- "Skapa konto gratis"
/// och "Logga in". Så lite text som möjligt: den som inte läser mycket ska
/// ändå se vad som går att göra. Knapparna ligger nere, där tummen når dem.
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
        SnackBar(content: Text(tr.welcomeScreenBrowserFailed)),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.navy,
      body: SafeArea(
        child: Stack(
          children: [
            LayoutBuilder(
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
                          SizedBox(
                            height: constraints.maxHeight < 700 ? 20 : 56,
                          ),
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
                              Text(
                                tr.welcomeScreenHeadline,
                                textAlign: TextAlign.center,
                                style: const TextStyle(
                                  fontFamily: kDisplayFont,
                                  color: TbColors.foam,
                                  fontSize: 30,
                                  height: 1.15,
                                  fontWeight: FontWeight.w800,
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
                                // Två knappar, inga förklaringar: "Skapa konto"
                                // för den som är ny (förare utan bolag och
                                // taxibolag, samma väg), "Logga in" för alla med
                                // konto -- också den inbjudna föraren.
                                FilledButton(
                                  onPressed: onSignup,
                                  style: FilledButton.styleFrom(
                                    backgroundColor: TbColors.taxi,
                                    foregroundColor: TbColors.ink,
                                    minimumSize: const Size.fromHeight(60),
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(14),
                                    ),
                                  ),
                                  child: Text(
                                    tr.welcomeScreenCreateAccount,
                                    style: const TextStyle(
                                      fontSize: 18,
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 14),
                                OutlinedButton(
                                  onPressed: onLogin,
                                  style: OutlinedButton.styleFrom(
                                    foregroundColor: TbColors.foam,
                                    side: const BorderSide(
                                      color: TbColors.foam,
                                      width: 1.5,
                                    ),
                                    minimumSize: const Size.fromHeight(60),
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(14),
                                    ),
                                  ),
                                  child: Text(
                                    tr.welcomeScreenLogin,
                                    style: const TextStyle(
                                      fontSize: 18,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 8),
                                if (!kIsWeb)
                                  TextButton(
                                    onPressed: () => _openDemo(context),
                                    style: TextButton.styleFrom(
                                      foregroundColor: Colors.white70,
                                      minimumSize: const Size.fromHeight(48),
                                    ),
                                    child: Text(
                                      tr.welcomeScreenSeeDemo,
                                      style: const TextStyle(
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
            // Språket syns innan man loggar in: den som inte läser svenska
            // ska hitta sitt språk direkt (lib/widgets/language_picker.dart).
            const PositionedDirectional(
              top: 4,
              end: 4,
              child: LanguageButton(),
            ),
          ],
        ),
      ),
    );
  }
}
