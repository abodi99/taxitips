import 'package:flutter/material.dart';

/// Ögat i ett lösenordsfält: visa eller dölj det man skrivit. Samma knapp
/// överallt (inloggning, registrering, byta lösenord), så att den som tryckt på
/// den en gång känner igen den. Stor tryckyta (IconButton ger 48 px) och en
/// text för skärmläsare.
///
/// Fältet äger tillståndet: `hidden` är dess `obscureText`.
class PasswordVisibilityButton extends StatelessWidget {
  const PasswordVisibilityButton({
    super.key,
    required this.hidden,
    required this.onToggle,
  });

  final bool hidden;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: hidden ? 'Visa lösenord' : 'Dölj lösenord',
      onPressed: onToggle,
      icon: Icon(
        hidden ? Icons.visibility_outlined : Icons.visibility_off_outlined,
      ),
    );
  }
}
