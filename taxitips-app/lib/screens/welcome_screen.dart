import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../theme.dart';

class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({
    super.key,
    required this.onLogin,
    required this.onSignup,
    required this.onDriver,
    this.onDemo,
  });

  /// "Jag äger bolaget": ägarens och kontorets inloggning.
  final VoidCallback onLogin;
  final VoidCallback onSignup;

  /// "Jag är förare": inloggning med e-postinbjudan, med koden som reserv.
  final VoidCallback onDriver;
  final VoidCallback? onDemo;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.navy,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SvgPicture.asset(
                    'assets/brand/logo-on-dark.svg',
                    width: double.infinity,
                    height: 100,
                    fit: BoxFit.contain,
                  ),
                  const SizedBox(height: 48),
                  
                  if (kIsWeb) ...[
                    // --- WEB VIEW (Admins) ---
                    const Text(
                      'Kontorsportal',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontFamily: kDisplayFont,
                        color: TbColors.foam,
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      'Hantera bilar, licenser och fakturering från webben.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: TbColors.foam, fontSize: 16, height: 1.4),
                    ),
                    const SizedBox(height: 48),
                    FilledButton(
                      onPressed: onLogin,
                      style: FilledButton.styleFrom(
                        backgroundColor: TbColors.taxi,
                        foregroundColor: TbColors.ink,
                        minimumSize: const Size.fromHeight(60),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                      ),
                      child: const Text('Logga in', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                    ),
                    const SizedBox(height: 16),
                    OutlinedButton(
                      onPressed: onSignup,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: TbColors.foam,
                        side: const BorderSide(color: TbColors.foam, width: 2),
                        minimumSize: const Size.fromHeight(60),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                      ),
                      child: const Text('Registrera företag', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                    ),
                  ] else ...[
                    // --- MOBILE VIEW (Drivers + Admins) ---
                    const Text(
                      'Kör smartare.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontFamily: kDisplayFont,
                        color: TbColors.foam,
                        fontSize: 32,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      'Aktuella trafiktips som hjälper dig hitta rätt körning snabbare.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: TbColors.foam, fontSize: 16, height: 1.4),
                    ),
                    const SizedBox(height: 48),
                    
                    // Två vägar, en per person: föraren och den som äger
                    // bolaget. Föraren loggar in med e-posten chefen bjöd in;
                    // koden finns kvar inne på förarsidan ("Har du en kod?").
                    _PathButton(
                      primary: true,
                      icon: Icons.local_taxi,
                      title: 'Jag är förare',
                      subtitle: 'Logga in med din e-post',
                      onTap: onDriver,
                    ),
                    const SizedBox(height: 14),
                    _PathButton(
                      primary: false,
                      icon: Icons.business_center_outlined,
                      title: 'Jag äger bolaget',
                      subtitle: 'Logga in och sköt bilar och förare',
                      onTap: onLogin,
                    ),
                    const SizedBox(height: 12),
                    // Nya företag ska inte behöva leta: registreringen låg förut
                    // bakom inloggningen, två tryck bort.
                    TextButton(
                      onPressed: onSignup,
                      style: TextButton.styleFrom(
                        foregroundColor: TbColors.taxi,
                        minimumSize: const Size.fromHeight(48),
                      ),
                      child: const Text(
                        'Nytt företag? Prova gratis i 14 dagar',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                      ),
                    ),
                    
                    if (onDemo != null) ...[
                      const SizedBox(height: 24),
                      TextButton(
                        onPressed: onDemo,
                        child: const Text(
                          'Prova appen (Demo)',
                          style: TextStyle(color: Colors.white54, fontSize: 14, decoration: TextDecoration.underline),
                        ),
                      ),
                    ],
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// En stor knapp per väg: ikon, vem den gäller, och en rad om vad som händer.
class _PathButton extends StatelessWidget {
  const _PathButton({
    required this.primary,
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final bool primary;
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final fg = primary ? TbColors.ink : TbColors.foam;
    return Material(
      color: primary ? TbColors.taxi : Colors.white.withValues(alpha: 0.06),
      borderRadius: BorderRadius.circular(16),
      elevation: primary ? 4 : 0,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 72),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          decoration: primary
              ? null
              : BoxDecoration(
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: Colors.white30, width: 2),
                ),
          child: Row(
            children: [
              Icon(icon, size: 30, color: primary ? TbColors.ink : TbColors.taxi),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      title,
                      style: TextStyle(
                        color: fg,
                        fontSize: 19,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: TextStyle(
                        color: primary ? TbColors.ink : Colors.white70,
                        fontSize: 14,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: fg),
            ],
          ),
        ),
      ),
    );
  }
}
