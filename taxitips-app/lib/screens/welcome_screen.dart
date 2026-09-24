import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../theme.dart';

class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({
    super.key,
    required this.onLogin,
    required this.onSignup,
    required this.onJoinPhone,
    this.onDemo,
  });

  final VoidCallback onLogin;
  final VoidCallback onSignup;
  final VoidCallback onJoinPhone;
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
                    
                    FilledButton.icon(
                      onPressed: onJoinPhone,
                      icon: const Icon(Icons.phone_android, size: 28),
                      label: const Text('Jag är förare (Anslut)', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                      style: FilledButton.styleFrom(
                        backgroundColor: TbColors.taxi,
                        foregroundColor: TbColors.ink,
                        minimumSize: const Size.fromHeight(64),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                        elevation: 4,
                      ),
                    ),
                    const SizedBox(height: 24),
                    
                    Row(
                      children: [
                        const Expanded(child: Divider(color: Colors.white24, thickness: 1)),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          child: Text('ADMINISTRATION', style: TextStyle(color: Colors.white54, fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 1)),
                        ),
                        const Expanded(child: Divider(color: Colors.white24, thickness: 1)),
                      ],
                    ),
                    const SizedBox(height: 24),
                    
                    OutlinedButton(
                      onPressed: onLogin,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: TbColors.foam,
                        side: const BorderSide(color: Colors.white30, width: 2),
                        minimumSize: const Size.fromHeight(56),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                      ),
                      child: const Text('Logga in som administratör', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
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
