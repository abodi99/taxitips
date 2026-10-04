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

/// Rubriken för en grupp i Inställningar: ett kort namn och en rad om vad man
/// kan göra där. Stor nog att läsa i bilen.
class SettingsSectionHeader extends StatelessWidget {
  const SettingsSectionHeader({
    super.key,
    required this.title,
    required this.description,
  });

  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 0, 4, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            header: true,
            child: Text(
              title,
              style: const TextStyle(
                fontFamily: kDisplayFont,
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: TbColors.ink,
              ),
            ),
          ),
          const SizedBox(height: 2),
          Text(
            description,
            style: const TextStyle(
              fontSize: 15,
              height: 1.35,
              color: TbColors.muted,
            ),
          ),
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
      color: Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: TbColors.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) const Divider(height: 1, indent: 52),
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
    return ListTile(
      leading: Icon(icon, color: TbColors.muted),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
      subtitle: Text(value, style: TextStyle(color: Colors.grey.shade700)),
      trailing: const Icon(Icons.chevron_right),
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
    this.iconColor,
    this.titleColor,
  });

  // Kan vara IconData eller Widget (t.ex. BrandIcons)
  final dynamic icon;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final IconData trailingIcon;
  final Color? iconColor;
  final Color? titleColor;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: icon is Widget
          ? SizedBox(width: 24, height: 24, child: icon)
          : Icon(icon as IconData, color: iconColor ?? TbColors.muted),
      title: Text(
        title,
        style: TextStyle(fontWeight: FontWeight.w700, color: titleColor),
      ),
      subtitle: subtitle == null ? null : Text(subtitle!),
      trailing: trailing ?? Icon(trailingIcon, size: 20),
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
      leading: Icon(icon, color: TbColors.muted),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
      subtitle: Text(value),
    );
  }
}
