import 'package:flutter/material.dart';

import '../theme.dart';

class SettingsGroupLabel extends StatelessWidget {
  const SettingsGroupLabel(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
      child: Text(
        text.toUpperCase(),
        style: const TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w700,
          color: TbColors.muted,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
}

/// Rubriken för en grupp i Inställningar. Kort, i brödtypsnittet — inte en
/// visningsrubrik. Extra förklaring hör hemma på raden, inte under titeln.
class SettingsSectionHeader extends StatelessWidget {
  const SettingsSectionHeader({
    super.key,
    required this.title,
    this.description = '',
  });

  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            header: true,
            child: Text(
              title,
              style: const TextStyle(
                fontFamily: kBodyFont,
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: TbColors.muted,
                letterSpacing: 0.2,
              ),
            ),
          ),
          if (description.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              description,
              style: const TextStyle(
                fontFamily: kBodyFont,
                fontSize: 13,
                height: 1.35,
                color: TbColors.muted,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// En rad med bara text: något att veta, inget att trycka på.
class SettingsNoteRow extends StatelessWidget {
  const SettingsNoteRow({super.key, required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: TbColors.muted),
          const SizedBox(width: 16),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                fontSize: 15,
                height: 1.4,
                fontWeight: FontWeight.w500,
                color: TbColors.ink,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class SettingsGroup extends StatelessWidget {
  const SettingsGroup({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: TbColors.vit,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: TbColors.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) const Divider(height: 1, indent: 56),
            children[i],
          ],
        ],
      ),
    );
  }
}

class SettingsEditRow extends StatelessWidget {
  const SettingsEditRow({
    super.key,
    required this.icon,
    required this.title,
    required this.value,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String value;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return SettingsNavRow(
      icon: icon,
      title: title,
      subtitle: value,
      onTap: onTap,
    );
  }
}

class SettingsNavRow extends StatelessWidget {
  const SettingsNavRow({
    super.key,
    required this.icon,
    required this.title,
    required this.onTap,
    this.subtitle,
    this.trailing,
    this.trailingIcon = Icons.chevron_right,
    this.showChevron = true,
    this.iconColor,
    this.titleColor,
  });

  // Kan vara IconData eller Widget (t.ex. BrandIcons)
  final dynamic icon;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final IconData trailingIcon;
  final bool showChevron;
  final Color? iconColor;
  final Color? titleColor;
  final VoidCallback onTap;

  static const _titleStyle = TextStyle(
    fontFamily: kBodyFont,
    fontWeight: FontWeight.w600,
    fontSize: 16,
    height: 1.25,
    color: TbColors.ink,
  );
  static const _subtitleStyle = TextStyle(
    fontFamily: kBodyFont,
    fontWeight: FontWeight.w400,
    fontSize: 13,
    height: 1.35,
    color: TbColors.muted,
  );

  @override
  Widget build(BuildContext context) {
    final leading = icon is Widget
        ? SizedBox(width: 22, height: 22, child: icon as Widget)
        : Icon(icon as IconData, size: 22, color: iconColor ?? TbColors.muted);
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
      minLeadingWidth: 28,
      minVerticalPadding: 10,
      leading: leading,
      title: Text(title, style: _titleStyle.copyWith(color: titleColor)),
      subtitle: subtitle == null ? null : Text(subtitle!, style: _subtitleStyle),
      trailing:
          trailing ??
          (showChevron
              ? Icon(trailingIcon, size: 20, color: TbColors.muted)
              : null),
      onTap: onTap,
    );
  }
}

// Where the app's data comes from used to be shown directly on every card/
// detail sheet (raw source names, a raw-JSON dump) -- that's internal
// plumbing a driver deciding whether to drive somewhere doesn't need. Moved
// here, one tap away in Settings, so it's still discoverable without being
// in the way of the list a driver actually uses while working.
Future<void> showDataInfoDialog(BuildContext context) async {
  await showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('Om datan'),
      content: const Text(
        'Taxi Tips bygger på officiell trafikinformation: tåg, buss, väg, '
        'flyg och färjor. Event och väder räknas också in. Varje tips '
        'räknas fram automatiskt. Det är en bedömning, inte ett löfte. '
        'Hur mycket vi ser är olika i olika län.',
        style: TextStyle(height: 1.4),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Stäng'),
        ),
      ],
    ),
  );
}

class SettingsInfoRow extends StatelessWidget {
  const SettingsInfoRow({
    super.key,
    required this.icon,
    required this.title,
    required this.value,
  });

  final IconData icon;
  final String title;
  final String value;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
      minLeadingWidth: 28,
      minVerticalPadding: 10,
      leading: Icon(icon, size: 22, color: TbColors.muted),
      title: Text(
        title,
        style: const TextStyle(
          fontFamily: kBodyFont,
          fontWeight: FontWeight.w600,
          fontSize: 16,
          height: 1.25,
          color: TbColors.ink,
        ),
      ),
      subtitle: Text(
        value,
        style: const TextStyle(
          fontFamily: kBodyFont,
          fontWeight: FontWeight.w400,
          fontSize: 13,
          height: 1.35,
          color: TbColors.muted,
        ),
      ),
    );
  }
}
