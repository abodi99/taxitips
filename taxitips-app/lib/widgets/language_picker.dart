import 'package:flutter/material.dart';

import '../l10n/l10n.dart';
import '../theme.dart';

/// Språkväljaren: telefonens språk, svenska, engelska eller arabiska.
///
/// Varje språk står på sitt eget språk ("English", "العربية"), så att den som
/// inte läser det språk appen visar just nu ändå hittar sitt.
Future<void> showLanguagePicker(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    backgroundColor: Colors.white,
    builder: (sheetContext) => const _LanguageSheet(),
  );
}

/// Vad raden i inställningarna visar: "Svenska (telefonens språk)" eller "English".
String currentLanguageLabel() {
  final name = languageName(currentLanguage);
  return chosenLocale.value == null ? tr.languageCurrentAuto(name) : name;
}

class _LanguageSheet extends StatelessWidget {
  const _LanguageSheet();

  @override
  Widget build(BuildContext context) {
    final chosen = chosenLocale.value?.languageCode;
    final phone = resolveDeviceLocales(
      WidgetsBinding.instance.platformDispatcher.locales,
    ).languageCode;
    Widget option({
      required String title,
      String? subtitle,
      required bool selected,
      required Locale? value,
    }) {
      return ListTile(
        contentPadding: const EdgeInsetsDirectional.fromSTEB(24, 4, 16, 4),
        title: Text(
          title,
          style: const TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 17,
            color: TbColors.ink,
          ),
        ),
        subtitle: subtitle == null ? null : Text(subtitle),
        trailing: selected
            ? const Icon(Icons.check_circle, color: TbColors.live)
            : const Icon(Icons.circle_outlined, color: TbColors.muted),
        onTap: () async {
          Navigator.of(context).pop();
          await chooseLocale(value);
        },
      );
    }

    return SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsetsDirectional.fromSTEB(24, 0, 24, 8),
            child: Row(
              children: [
                const Icon(Icons.language, color: TbColors.ink),
                const SizedBox(width: 10),
                Text(
                  tr.languageTitle,
                  style: const TextStyle(
                    fontFamily: kDisplayFont,
                    fontWeight: FontWeight.w700,
                    fontSize: 20,
                    color: TbColors.ink,
                  ),
                ),
              ],
            ),
          ),
          option(
            title: tr.languageFollowPhone,
            subtitle: tr.languageFollowPhoneDetail(languageName(phone)),
            selected: chosen == null,
            value: null,
          ),
          for (final code in supportedLanguages)
            option(
              title: languageName(code),
              selected: chosen == code,
              value: Locale(code),
            ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}

/// Språkknappen på välkomstskärmen: jordglob och språkets namn.
class LanguageButton extends StatelessWidget {
  const LanguageButton({super.key, this.color = Colors.white});

  final Color color;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: tr.languageButtonLabel,
      child: TextButton.icon(
        onPressed: () => showLanguagePicker(context),
        style: TextButton.styleFrom(
          foregroundColor: color,
          minimumSize: const Size(48, 48),
          padding: const EdgeInsets.symmetric(horizontal: 12),
        ),
        icon: const Icon(Icons.language, size: 22),
        label: Text(
          languageName(currentLanguage),
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }
}
