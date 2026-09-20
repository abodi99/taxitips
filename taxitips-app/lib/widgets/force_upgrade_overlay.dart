import 'package:firebase_remote_config/firebase_remote_config.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../push_service.dart';
import '../theme.dart';

/// Firebase Remote Config-nyckel: minsta tillåtna appversion (semver, t.ex. "1.0.1").
/// Sätts i Firebase Console för projektet taxibehov. Default = installerad
/// version → ingen blockering förrän du höjer nyckeln.
const kRequiredVersionKey = 'required_version';

/// iOS App Store-ID — fylls i när appen publicerats. Tom = hoppa över iOS-länk.
const kIosAppStoreId = '';

/// Force-update som i Zawajj: om installerad version < Remote Config
/// `required_version` blockeras appen tills användaren öppnar butiken.
///
/// Wrappa runt hela appen via `MaterialApp.builder` så splash/login/shell
/// alla täcks (Zawajj missade login).
class ForceUpgradeOverlay extends StatefulWidget {
  const ForceUpgradeOverlay({super.key, required this.child});

  final Widget child;

  @override
  State<ForceUpgradeOverlay> createState() => _ForceUpgradeOverlayState();
}

class _ForceUpgradeOverlayState extends State<ForceUpgradeOverlay>
    with WidgetsBindingObserver {
  bool _forceUpdate = false;
  String _currentVersion = '';
  String _requiredVersion = '';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _setup();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _checkForUpdates();
    }
  }

  Future<void> _setup() async {
    if (!firebaseReady) {
      // Utan Firebase (t.ex. web utan config) — låt appen köra.
      return;
    }
    try {
      final info = await PackageInfo.fromPlatform();
      final remote = FirebaseRemoteConfig.instance;
      await remote.setConfigSettings(
        RemoteConfigSettings(
          fetchTimeout: const Duration(seconds: 10),
          // Dev: snabb omhämtning. Prod: en timme räcker.
          minimumFetchInterval: kDebugMode
              ? Duration.zero
              : const Duration(hours: 1),
        ),
      );
      await remote.setDefaults({
        kRequiredVersionKey: info.version,
      });
      await remote.fetchAndActivate();
      remote.onConfigUpdated.listen((_) async {
        await remote.activate();
        await _checkForUpdates();
      });
      await _checkForUpdates();
    } catch (e) {
      debugPrint('ForceUpgrade: Remote Config setup failed: $e');
    }
  }

  Future<void> _checkForUpdates() async {
    if (!firebaseReady) return;
    try {
      final info = await PackageInfo.fromPlatform();
      final required =
          FirebaseRemoteConfig.instance.getString(kRequiredVersionKey);
      final force = _shouldForceUpdate(info.version, required);
      if (!mounted) return;
      setState(() {
        _currentVersion = info.version;
        _requiredVersion = required;
        _forceUpdate = force;
      });
      debugPrint(
        'ForceUpgrade: current=${info.version} required=$required force=$force',
      );
    } catch (e) {
      debugPrint('ForceUpgrade: check failed: $e');
    }
  }

  /// true om [current] < [required] (punkt-separerade heltal).
  bool _shouldForceUpdate(String current, String required) {
    if (required.trim().isEmpty) return false;
    try {
      final c = _parseVersion(current);
      final r = _parseVersion(required);
      for (var i = 0; i < r.length; i++) {
        if (i >= c.length) return r[i] > 0;
        if (r[i] > c[i]) return true;
        if (r[i] < c[i]) return false;
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  List<int> _parseVersion(String version) =>
      version.split('.').map((e) => int.tryParse(e) ?? 0).toList();

  Future<void> _openStore() async {
    try {
      final info = await PackageInfo.fromPlatform();
      final String url;
      if (defaultTargetPlatform == TargetPlatform.iOS) {
        if (kIosAppStoreId.isEmpty) {
          debugPrint('ForceUpgrade: iOS App Store-ID saknas');
          return;
        }
        url = 'https://apps.apple.com/app/id$kIosAppStoreId';
      } else if (defaultTargetPlatform == TargetPlatform.android) {
        url =
            'https://play.google.com/store/apps/details?id=${info.packageName}';
      } else {
        url = 'https://taxitips.se';
      }
      final uri = Uri.parse(url);
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      }
    } catch (e) {
      debugPrint('ForceUpgrade: open store failed: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_forceUpdate) return widget.child;

    return Stack(
      fit: StackFit.expand,
      children: [
        widget.child,
        PopScope(
          canPop: false,
          child: Material(
            color: Colors.black54,
            child: Center(
              child: Container(
                margin: const EdgeInsets.all(24),
                padding: const EdgeInsets.all(24),
                decoration: BoxDecoration(
                  color: TbColors.vit,
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: const [
                    BoxShadow(
                      color: Color(0x33000000),
                      blurRadius: 16,
                      offset: Offset(0, 6),
                    ),
                  ],
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.system_update,
                      size: 56,
                      color: TbColors.guld,
                    ),
                    const SizedBox(height: 16),
                    const Text(
                      'Uppdatering krävs',
                      style: TextStyle(
                        fontFamily: kDisplayFont,
                        fontSize: 22,
                        fontWeight: FontWeight.w700,
                        color: TbColors.midnatt,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 10),
                    Text(
                      'En nyare version av TaxiTips behövs för att fortsätta'
                      '${_requiredVersion.isNotEmpty ? ' (minst $_requiredVersion' : ''}'
                      '${_currentVersion.isNotEmpty && _requiredVersion.isNotEmpty ? ', du har $_currentVersion)' : (_requiredVersion.isNotEmpty ? ')' : '')}.',
                      style: const TextStyle(
                        fontSize: 15,
                        height: 1.35,
                        color: TbColors.skiffer,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 22),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: _openStore,
                        child: const Text('Uppdatera nu'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
