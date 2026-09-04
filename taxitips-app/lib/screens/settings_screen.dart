import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../theme.dart';
import '../widgets/company_settings_panel.dart';
import '../widgets/notify_prefs_sheet.dart';
import '../widgets/settings_ui.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    required this.api,
    this.onLogout,
    this.onLeftDevice,
  });

  final ApiClient api;
  final VoidCallback? onLogout;
  final VoidCallback? onLeftDevice;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _loading = true;
  String? _error;
  bool _refreshingCompany = false;

  // Office
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _orgNumber = TextEditingController();

  // Driver
  final _label = TextEditingController();
  String? _companyName;

  bool get _isOffice => widget.api.sessionToken != null;
  bool get _isDevice => widget.api.deviceToken != null;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _orgNumber.dispose();
    _label.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      if (_isOffice) {
        final me = await widget.api.me();
        final company = me['company'] as Map<String, dynamic>? ?? {};
        _name.text = company['name']?.toString() ?? '';
        _email.text = company['email']?.toString() ?? '';
        _orgNumber.text = company['orgNumber']?.toString() ?? '';
      }
      if (_isDevice) {
        final data = await widget.api.getDeviceMe();
        final device = data['device'] as Map<String, dynamic>? ?? {};
        final company = data['company'] as Map<String, dynamic>? ?? {};
        _label.text = device['label']?.toString() ?? '';
        _companyName = company['name']?.toString();
      }
      if (mounted) setState(() => _loading = false);
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = _cleanError(e);
        });
      }
    }
  }

  String _cleanError(Object e) =>
      e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), '');

  void _showSnack(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? TbColors.danger : TbColors.live,
      ),
    );
  }

  Future<void> _refreshCompanyDetails() async {
    setState(() => _refreshingCompany = true);
    try {
      final me = await widget.api.me();
      final company = me['company'] as Map<String, dynamic>? ?? {};
      if (!mounted) return;
      setState(() {
        _name.text = company['name']?.toString() ?? '';
        _orgNumber.text = company['orgNumber']?.toString() ?? '';
      });
      _showSnack('Företagsuppgifter uppdaterade');
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    } finally {
      if (mounted) setState(() => _refreshingCompany = false);
    }
  }

  Future<void> _editEmail() async {
    final ok = await showDialog<dynamic>(
      context: context,
      builder: (_) =>
          _EmailChangeDialog(api: widget.api, currentEmail: _email.text),
    );
    if (ok is String && mounted) {
      setState(() => _email.text = ok);
      _showSnack('E-post uppdaterad');
    }
  }

  Future<void> _editPassword() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) =>
          _PasswordChangeDialog(api: widget.api, email: _email.text),
    );
    if (ok == true) _showSnack('Lösenord bytt');
  }

  Future<void> _editLabel() async {
    final controller = TextEditingController(text: _label.text);
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => _EditDialog(
        title: 'Telefonnamn',
        fields: [
          TextField(
            controller: controller,
            autofocus: true,
            decoration: const InputDecoration(labelText: 'Namn på telefonen'),
          ),
        ],
        onSubmit: () async {
          await widget.api.updateDeviceLabel(controller.text.trim());
          if (mounted) setState(() => _label.text = controller.text.trim());
        },
        controllers: [controller],
      ),
    );
    if (ok == true) _showSnack('Telefonnamn sparat');
  }

  Future<void> _openLegal(String path) async {
    final base = widget.api.baseUrl.replaceAll(RegExp(r'/$'), '');
    final uri = Uri.parse('$base$path');
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  Future<void> _openNotify() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: TbColors.foam,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) => NotifyPrefsSheet(api: widget.api),
    );
  }

  Future<void> _leaveDevice() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Lämna denna telefon?'),
        content: const Text(
          'Telefonen avregistreras lokalt. Anslut igen med bolagskod.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Avbryt'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Lämna'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await widget.api.clearDevice();
    widget.onLeftDevice?.call();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.foam,
      appBar: AppBar(title: const Text('Inställningar')),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: TbColors.taxi))
          : RefreshIndicator(
              color: TbColors.taxiDeep,
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                children: [
                  if (_error != null) ...[
                    _ErrorBanner(message: _error!),
                    const SizedBox(height: 16),
                  ],
                  if (_isOffice) ...[
                    const SettingsGroupLabel('Konto'),
                    SettingsGroup(
                      children: [
                        SettingsInfoRow(
                          icon: Icons.storefront_outlined,
                          title: 'Företagsnamn',
                          value: _name.text.isEmpty ? '—' : _name.text,
                        ),
                        SettingsInfoRow(
                          icon: Icons.badge_outlined,
                          title: 'Organisationsnummer',
                          value: _orgNumber.text.isEmpty
                              ? '—'
                              : _orgNumber.text,
                        ),
                        SettingsNavRow(
                          icon: Icons.refresh,
                          title: 'Uppdatera företagsuppgifter',
                          subtitle: 'Hämta senaste uppgifterna från API:t',
                          onTap: _refreshingCompany
                              ? () {}
                              : _refreshCompanyDetails,
                        ),
                        SettingsEditRow(
                          icon: Icons.email_outlined,
                          title: 'E-post',
                          value: _email.text.isEmpty ? '—' : _email.text,
                          onTap: _editEmail,
                        ),
                        SettingsEditRow(
                          icon: Icons.lock_outline,
                          title: 'Lösenord',
                          value: '••••••••',
                          onTap: _editPassword,
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),
                    CompanySettingsPanel(api: widget.api),
                  ],
                  if (_isDevice) ...[
                    const SettingsGroupLabel('Den här telefonen'),
                    SettingsGroup(
                      children: [
                        if (_companyName != null)
                          SettingsInfoRow(
                            icon: Icons.storefront_outlined,
                            title: 'Bolag',
                            value: _companyName!,
                          ),
                        SettingsEditRow(
                          icon: Icons.smartphone_outlined,
                          title: 'Telefonnamn',
                          value: _label.text.isEmpty ? '—' : _label.text,
                          onTap: _editLabel,
                        ),
                        SettingsNavRow(
                          icon: Icons.notifications_outlined,
                          title: 'Notiser',
                          subtitle:
                              'Orter och vilka händelser som får störa dig',
                          onTap: _openNotify,
                        ),
                        SettingsNavRow(
                          icon: Icons.logout,
                          title: 'Lämna denna telefon',
                          iconColor: TbColors.danger,
                          titleColor: TbColors.danger,
                          onTap: _leaveDevice,
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),
                  ],
                  if (!_isOffice && !_isDevice) ...[
                    const Text(
                      'Logga in eller registrera telefon för att se kontouppgifter.',
                    ),
                    const SizedBox(height: 20),
                  ],
                  const SettingsGroupLabel('Om appen'),
                  SettingsGroup(
                    children: [
                      SettingsNavRow(
                        icon: Icons.info_outline,
                        title: 'Om datan',
                        subtitle: 'Vad förslagen bygger på',
                        onTap: () => showDataInfoDialog(context),
                      ),
                      SettingsNavRow(
                        icon: Icons.privacy_tip_outlined,
                        title: 'Datapolicy',
                        trailingIcon: Icons.open_in_new,
                        onTap: () => _openLegal('/privacy.html'),
                      ),
                      SettingsNavRow(
                        icon: Icons.description_outlined,
                        title: 'Villkor',
                        trailingIcon: Icons.open_in_new,
                        onTap: () => _openLegal('/terms.html'),
                      ),
                    ],
                  ),
                  if (_isOffice && widget.onLogout != null) ...[
                    const SizedBox(height: 20),
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        onPressed: widget.onLogout,
                        icon: const Icon(Icons.logout, color: TbColors.danger),
                        label: const Text('Logga ut'),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: TbColors.danger,
                          side: const BorderSide(color: TbColors.danger),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
    );
  }
}

class _EmailChangeDialog extends StatefulWidget {
  const _EmailChangeDialog({required this.api, required this.currentEmail});

  final ApiClient api;
  final String currentEmail;

  @override
  State<_EmailChangeDialog> createState() => _EmailChangeDialogState();
}

class _EmailChangeDialogState extends State<_EmailChangeDialog> {
  late final TextEditingController _oldEmail;
  final _newEmail = TextEditingController();
  final _code = TextEditingController();
  bool _codeSent = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _oldEmail = TextEditingController(text: widget.currentEmail);
  }

  @override
  void dispose() {
    _oldEmail.dispose();
    _newEmail.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _sendCode() async {
    final email = _oldEmail.text.trim();
    if (email.isEmpty) {
      setState(() => _error = 'Din gamla e-postadress saknas.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.sendEmailChangeCode(email);
      if (!mounted) return;
      setState(() {
        _codeSent = true;
        _busy = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.toString().replaceFirst(
          RegExp(r'^(ApiException|Exception):\s*'),
          '',
        );
      });
    }
  }

  Future<void> _submit() async {
    if (_code.text.trim().isEmpty || _newEmail.text.trim().isEmpty) {
      setState(() => _error = 'Fyll i verifieringskod och ny e-postadress.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.changeEmailWithCode(
        oldEmail: _oldEmail.text,
        code: _code.text,
        newEmail: _newEmail.text,
      );
      if (mounted) {
        Navigator.of(context).pop(_newEmail.text.trim().toLowerCase());
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.toString().replaceFirst(
          RegExp(r'^(ApiException|Exception):\s*'),
          '',
        );
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Byt e-post'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _oldEmail,
              readOnly: true,
              decoration: const InputDecoration(labelText: 'Nuvarande e-post'),
            ),
            const SizedBox(height: 8),
            if (!_codeSent)
              FilledButton.icon(
                onPressed: _busy ? null : _sendCode,
                icon: const Icon(Icons.mail_outline),
                label: Text(
                  _busy ? 'Skickar…' : 'Skicka kod till gammal e-post',
                ),
              )
            else ...[
              const Text('Verifiera först koden från din gamla e-post.'),
              const SizedBox(height: 8),
              TextField(
                controller: _code,
                autofocus: true,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Verifieringskod'),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _newEmail,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Ny e-post'),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: const TextStyle(
                  color: TbColors.danger,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(false),
          child: const Text('Avbryt'),
        ),
        if (_codeSent)
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? 'Byter…' : 'Byt e-post'),
          ),
      ],
    );
  }
}

class _PasswordChangeDialog extends StatefulWidget {
  const _PasswordChangeDialog({required this.api, required this.email});

  final ApiClient api;
  final String email;

  @override
  State<_PasswordChangeDialog> createState() => _PasswordChangeDialogState();
}

class _PasswordChangeDialogState extends State<_PasswordChangeDialog> {
  late final TextEditingController _email;
  final _code = TextEditingController();
  final _newPassword = TextEditingController();
  bool _codeSent = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _email = TextEditingController(text: widget.email);
  }

  @override
  void dispose() {
    _email.dispose();
    _code.dispose();
    _newPassword.dispose();
    super.dispose();
  }

  Future<void> _sendCode() async {
    final email = _email.text.trim();
    if (email.isEmpty) {
      setState(() => _error = 'Fyll i e-postadressen.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.sendPasswordCode(email);
      if (!mounted) return;
      setState(() {
        _codeSent = true;
        _busy = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.toString().replaceFirst(
          RegExp(r'^(ApiException|Exception):\s*'),
          '',
        );
      });
    }
  }

  Future<void> _submit() async {
    if (_code.text.trim().isEmpty || _newPassword.text.isEmpty) {
      setState(() => _error = 'Fyll i kod och nytt lösenord.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.changePasswordWithCode(
        email: _email.text,
        code: _code.text,
        newPassword: _newPassword.text,
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.toString().replaceFirst(
          RegExp(r'^(ApiException|Exception):\s*'),
          '',
        );
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Byt lösenord'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _email,
              enabled: !_codeSent && !_busy,
              keyboardType: TextInputType.emailAddress,
              autofocus: !_codeSent,
              decoration: const InputDecoration(labelText: 'E-postadress'),
            ),
            const SizedBox(height: 8),
            if (!_codeSent)
              FilledButton.icon(
                onPressed: _busy ? null : _sendCode,
                icon: const Icon(Icons.mail_outline),
                label: Text(_busy ? 'Skickar…' : 'Skicka verifieringskod'),
              )
            else ...[
              const Text('En verifieringskod har skickats till din e-post.'),
              const SizedBox(height: 8),
              TextField(
                controller: _code,
                autofocus: true,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Verifieringskod'),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _newPassword,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'Nytt lösenord (minst 8)',
                ),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: const TextStyle(
                  color: TbColors.danger,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(false),
          child: const Text('Avbryt'),
        ),
        if (_codeSent)
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? 'Byter…' : 'Byt lösenord'),
          ),
      ],
    );
  }
}

/// Reusable dialog for single-field or multi-field edits opened from a row.
class _EditDialog extends StatefulWidget {
  const _EditDialog({
    required this.title,
    required this.fields,
    required this.onSubmit,
    this.controllers = const [],
  });

  final String title;
  final List<Widget> fields;
  final Future<void> Function() onSubmit;
  final List<TextEditingController> controllers;

  @override
  State<_EditDialog> createState() => _EditDialogState();
}

class _EditDialogState extends State<_EditDialog> {
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in widget.controllers) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.onSubmit();
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.toString().replaceFirst(
          RegExp(r'^(ApiException|Exception):\s*'),
          '',
        );
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(
        widget.title,
        style: const TextStyle(fontWeight: FontWeight.w800),
      ),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ...widget.fields,
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: const TextStyle(
                  color: TbColors.danger,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(false),
          child: const Text('Avbryt'),
        ),
        FilledButton(
          onPressed: _busy ? null : _submit,
          child: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Spara'),
        ),
      ],
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: TbColors.danger.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: TbColors.danger.withValues(alpha: 0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error_outline, color: TbColors.danger, size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(
                color: TbColors.danger,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
