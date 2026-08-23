import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../theme.dart';
import '../widgets/notify_prefs_sheet.dart';

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
  String? _ok;

  // Office
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _newEmail = TextEditingController();
  final _emailPassword = TextEditingController();
  final _currentPassword = TextEditingController();
  final _newPassword = TextEditingController();

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
    _newEmail.dispose();
    _emailPassword.dispose();
    _currentPassword.dispose();
    _newPassword.dispose();
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
          _error = e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), '');
        });
      }
    }
  }

  Future<void> _saveName() async {
    setState(() {
      _error = null;
      _ok = null;
    });
    try {
      await widget.api.updateCompanyProfile(name: _name.text.trim());
      setState(() => _ok = 'Bolagsnamn sparat');
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), ''));
    }
  }

  Future<void> _saveEmail() async {
    setState(() {
      _error = null;
      _ok = null;
    });
    try {
      await widget.api.changeEmail(
        currentPassword: _emailPassword.text,
        newEmail: _newEmail.text.trim(),
      );
      _email.text = _newEmail.text.trim().toLowerCase();
      _newEmail.clear();
      _emailPassword.clear();
      setState(() => _ok = 'E-post uppdaterad');
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), ''));
    }
  }

  Future<void> _savePassword() async {
    setState(() {
      _error = null;
      _ok = null;
    });
    try {
      await widget.api.changePassword(
        currentPassword: _currentPassword.text,
        newPassword: _newPassword.text,
      );
      _currentPassword.clear();
      _newPassword.clear();
      setState(() => _ok = 'Lösenord bytt');
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), ''));
    }
  }

  Future<void> _saveLabel() async {
    setState(() {
      _error = null;
      _ok = null;
    });
    try {
      await widget.api.updateDeviceLabel(_label.text.trim());
      setState(() => _ok = 'Telefonnamn sparat');
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst(RegExp(r'^(ApiException|Exception):\s*'), ''));
    }
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
        content: const Text('Telefonen avregistreras lokalt. Anslut igen med bolagskod.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Avbryt')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Lämna')),
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
      appBar: AppBar(
        title: const Text('Inställningar', style: TextStyle(fontWeight: FontWeight.w900)),
        backgroundColor: TbColors.foam,
        foregroundColor: TbColors.ink,
        elevation: 0,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: TbColors.taxi))
          : ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
              children: [
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Text(_error!, style: const TextStyle(color: TbColors.danger, fontWeight: FontWeight.w700)),
                  ),
                if (_ok != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Text(_ok!, style: const TextStyle(color: TbColors.live, fontWeight: FontWeight.w700)),
                  ),
                if (_isOffice) ..._officeBlocks(),
                if (_isDevice) ..._deviceBlocks(),
                if (!_isOffice && !_isDevice)
                  const Text('Logga in eller registrera telefon för att se kontouppgifter.'),
                const SizedBox(height: 18),
                const Text('Juridiskt', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
                const SizedBox(height: 8),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Datapolicy', style: TextStyle(fontWeight: FontWeight.w700)),
                  trailing: const Icon(Icons.open_in_new, size: 18),
                  onTap: () => _openLegal('/privacy.html'),
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Villkor', style: TextStyle(fontWeight: FontWeight.w700)),
                  trailing: const Icon(Icons.open_in_new, size: 18),
                  onTap: () => _openLegal('/terms.html'),
                ),
                if (_isOffice && widget.onLogout != null) ...[
                  const SizedBox(height: 16),
                  OutlinedButton(
                    onPressed: widget.onLogout,
                    child: const Text('Logga ut'),
                  ),
                ],
              ],
            ),
    );
  }

  List<Widget> _officeBlocks() {
    return [
      const Text('Konto (kontor)', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
      const SizedBox(height: 8),
      TextField(
        controller: _name,
        decoration: const InputDecoration(labelText: 'Bolagsnamn / användarnamn'),
      ),
      const SizedBox(height: 8),
      Align(
        alignment: Alignment.centerLeft,
        child: FilledButton(onPressed: _saveName, child: const Text('Spara namn')),
      ),
      const SizedBox(height: 18),
      Text('Nuvarande e-post', style: TextStyle(fontWeight: FontWeight.w700, color: Colors.grey.shade700)),
      Text(_email.text, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
      const SizedBox(height: 10),
      TextField(
        controller: _newEmail,
        decoration: const InputDecoration(labelText: 'Ny e-post'),
        keyboardType: TextInputType.emailAddress,
      ),
      TextField(
        controller: _emailPassword,
        decoration: const InputDecoration(labelText: 'Bekräfta med lösenord'),
        obscureText: true,
      ),
      const SizedBox(height: 8),
      Align(
        alignment: Alignment.centerLeft,
        child: FilledButton(onPressed: _saveEmail, child: const Text('Byt e-post')),
      ),
      const SizedBox(height: 18),
      const Text('Byt lösenord', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
      TextField(
        controller: _currentPassword,
        decoration: const InputDecoration(labelText: 'Nuvarande lösenord'),
        obscureText: true,
      ),
      TextField(
        controller: _newPassword,
        decoration: const InputDecoration(labelText: 'Nytt lösenord (minst 8)'),
        obscureText: true,
      ),
      const SizedBox(height: 8),
      Align(
        alignment: Alignment.centerLeft,
        child: FilledButton(onPressed: _savePassword, child: const Text('Byt lösenord')),
      ),
      const SizedBox(height: 12),
    ];
  }

  List<Widget> _deviceBlocks() {
    return [
      const Text('Den här telefonen', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
      if (_companyName != null) ...[
        const SizedBox(height: 4),
        Text('Bolag: $_companyName', style: TextStyle(color: Colors.grey.shade700)),
      ],
      const SizedBox(height: 10),
      TextField(
        controller: _label,
        decoration: const InputDecoration(labelText: 'Namn på telefonen'),
      ),
      const SizedBox(height: 8),
      Align(
        alignment: Alignment.centerLeft,
        child: FilledButton(onPressed: _saveLabel, child: const Text('Spara namn')),
      ),
      const SizedBox(height: 14),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.notifications_outlined),
        title: const Text('Notiser', style: TextStyle(fontWeight: FontWeight.w800)),
        subtitle: const Text('Orter och vilka händelser som får störa dig'),
        trailing: const Icon(Icons.chevron_right),
        onTap: _openNotify,
      ),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.logout),
        title: const Text('Lämna denna telefon', style: TextStyle(fontWeight: FontWeight.w800)),
        onTap: _leaveDevice,
      ),
      const SizedBox(height: 12),
    ];
  }
}
