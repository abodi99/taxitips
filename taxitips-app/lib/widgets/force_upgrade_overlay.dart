import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../app_version.dart';
import '../backend_api.dart';
import '../config.dart';
import '../remote_config_service.dart';
import '../theme.dart';

/// Paketnamnet i Play Butik. Reserv när PackageInfo inte svarar.
const kAndroidPackage = 'se.taxitips.app';

typedef ConfigFetcher = Future<Map<String, dynamic>> Function();
typedef InstalledVersionReader = Future<AppVersion?> Function();
typedef RemotePolicyReader = UpgradePolicy? Function(String platform);

/// Tvingad eller föreslagen uppdatering, styrd från servern.
///
/// Gränserna kommer primärt från Firebase Remote Config (versionsnycklar
/// per plattform) och fylls från `/api/config` (`appVersion`) när RC-fält
/// är tomma — adminwebben kan fortfarande styra utan app-deploy.
///
/// Kontrollen görs vid start och varje gång appen kommer tillbaka från
/// bakgrunden -- en förare som öppnat butiken och kommit tillbaka utan att
/// uppdatera ska mötas av samma spärr, och en gräns som sänkts i adminwebben
/// ska släppa utan omstart. Beslutet fattas i `lib/app_version.dart`; går
/// anropet fel blockeras ingenting (se regel 3 där).
///
/// Ligger i `MaterialApp.builder`, alltså ovanför Navigator: spärren täcker
/// välkomst, inloggning och skal lika, och en bakåtknapp byter bara det som
/// ligger under den.
class ForceUpgradeOverlay extends StatefulWidget {
  const ForceUpgradeOverlay({
    super.key,
    required this.child,
    this.fetchConfig,
    this.readRemotePolicy,
    this.installedVersion,
    this.platform,
  });

  final Widget child;

  /// Injicerbara för testerna. Null = den riktiga backenden och PackageInfo.
  final ConfigFetcher? fetchConfig;
  final RemotePolicyReader? readRemotePolicy;
  final InstalledVersionReader? installedVersion;

  /// `android` eller `ios`. Null = läses från enheten (webb och desktop får
  /// ingen spärr -- det finns ingen butik att skicka dem till).
  final String? platform;

  @override
  State<ForceUpgradeOverlay> createState() => _ForceUpgradeOverlayState();
}

class _ForceUpgradeOverlayState extends State<ForceUpgradeOverlay>
    with WidgetsBindingObserver {
  UpgradeDecision _decision = UpgradeDecision.none;
  AppVersion? _installed;
  bool _checking = false;

  /// Den rekommenderade versionen föraren stängt banderollen för. Höjs
  /// gränsen igen visas den igen; annars inte förrän nästa start.
  String? _dismissedNudge;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    remoteConfigRevision.addListener(_onRemoteConfigChanged);
    unawaited(_check());
  }

  @override
  void dispose() {
    remoteConfigRevision.removeListener(_onRemoteConfigChanged);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  void _onRemoteConfigChanged() => unawaited(_check());

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(_check());
  }

  String? get _platform {
    if (widget.platform != null) return widget.platform;
    if (kIsWeb) return null;
    return switch (defaultTargetPlatform) {
      TargetPlatform.android => 'android',
      TargetPlatform.iOS => 'ios',
      _ => null,
    };
  }

  Future<AppVersion?> _readInstalled() async {
    final reader = widget.installedVersion;
    if (reader != null) return reader();
    final info = await PackageInfo.fromPlatform();
    return AppVersion.installed(info.version, info.buildNumber);
  }

  Future<Map<String, dynamic>>? _fetch() {
    final fetch = widget.fetchConfig;
    if (fetch != null) return fetch();
    // Utan Django-backend finns ingen gräns att fråga efter.
    if (!TaxiTipsConfig.usesDjangoApi) return null;
    return BackendApi().config();
  }

  Future<void> _check() async {
    final platform = _platform;
    if (platform == null || _checking) return;
    _checking = true;
    try {
      final installed = _installed ??= await _readInstalled();
      UpgradePolicy? remotePolicy;
      try {
        final readRemote = widget.readRemotePolicy ?? remoteUpgradePolicy;
        remotePolicy = readRemote(platform);
      } catch (e) {
        debugPrint('ForceUpgrade: remote config: $e');
      }
      UpgradePolicy? backendPolicy;
      try {
        final pending = _fetch();
        backendPolicy = pending == null
            ? null
            : UpgradePolicy.fromConfig(await pending, platform);
      } catch (e) {
        debugPrint('ForceUpgrade: config gick inte att hämta: $e');
      }
      final policy = UpgradePolicy.merge(remotePolicy, backendPolicy);
      if (policy == null && remotePolicy == null && backendPolicy == null) {
        // Båda källor nere: behåll eventuell befintlig spärr.
        return;
      }
      final decision = decideUpgrade(installed: installed, policy: policy);
      if (!mounted) return;
      setState(() => _decision = decision);
    } catch (e) {
      debugPrint('ForceUpgrade: kontrollen misslyckades: $e');
    } finally {
      _checking = false;
    }
  }

  Future<void> _openStore() async {
    final storeUrl = _decision.storeUrl;
    try {
      if (_platform == 'android') {
        // Play Butik-appen direkt; webbsidan bara om butiken saknas (t.ex. en
        // telefon utan Google-tjänster).
        var package = kAndroidPackage;
        try {
          final info = await PackageInfo.fromPlatform();
          if (info.packageName.isNotEmpty) package = info.packageName;
        } catch (_) {}
        final market = Uri.parse('market://details?id=$package');
        if (await launchUrl(market, mode: LaunchMode.externalApplication)) {
          return;
        }
      }
      if (storeUrl == null || storeUrl.isEmpty) return;
      await launchUrl(
        Uri.parse(storeUrl),
        mode: LaunchMode.externalApplication,
      );
    } catch (e) {
      debugPrint('ForceUpgrade: butiken gick inte att öppna: $e');
      if (storeUrl != null && storeUrl.isNotEmpty) {
        try {
          await launchUrl(
            Uri.parse(storeUrl),
            mode: LaunchMode.externalApplication,
          );
        } catch (_) {}
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final blocked = _decision.action == UpgradeAction.block;
    final nudge =
        _decision.action == UpgradeAction.nudge &&
        _dismissedNudge != _decision.required;
    return Stack(
      fit: StackFit.expand,
      children: [
        // Alltid samma omslag, bara växlat: byts trädet ut förloras appens
        // tillstånd under spärren. Utan dem gick det att nå knappar under en
        // halvgenomskinlig spärr med skärmläsare eller tangentbord.
        IgnorePointer(
          ignoring: blocked,
          child: ExcludeSemantics(
            excluding: blocked,
            child: ExcludeFocus(excluding: blocked, child: widget.child),
          ),
        ),
        if (blocked)
          _BlockScreen(
            decision: _decision,
            installed: _installed,
            onUpdate: _openStore,
          )
        else if (nudge)
          _NudgeBanner(
            decision: _decision,
            onUpdate: _openStore,
            onClose: () => setState(() => _dismissedNudge = _decision.required),
          ),
      ],
    );
  }
}

class _BlockScreen extends StatelessWidget {
  const _BlockScreen({
    required this.decision,
    required this.installed,
    required this.onUpdate,
  });

  final UpgradeDecision decision;
  final AppVersion? installed;
  final VoidCallback onUpdate;

  @override
  Widget build(BuildContext context) {
    final message = decision.message;
    return Material(
      color: TbColors.midnatt,
      child: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(28),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.system_update,
                    size: 64,
                    color: TbColors.guld,
                  ),
                  const SizedBox(height: 20),
                  const Text(
                    'Uppdatera appen',
                    style: TextStyle(
                      fontFamily: kDisplayFont,
                      fontSize: 24,
                      fontWeight: FontWeight.w700,
                      color: TbColors.vit,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Den här versionen fungerar inte längre. '
                    'Uppdatera för att fortsätta.',
                    style: TextStyle(
                      fontSize: 16,
                      height: 1.4,
                      color: TbColors.vit,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  if (message != null) ...[
                    const SizedBox(height: 12),
                    Text(
                      message,
                      style: const TextStyle(
                        fontSize: 15,
                        height: 1.4,
                        color: TbColors.ljusgraDjup,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ],
                  const SizedBox(height: 28),
                  SizedBox(
                    width: double.infinity,
                    height: 52,
                    child: FilledButton.icon(
                      onPressed: onUpdate,
                      icon: const Icon(Icons.download),
                      label: const Text(
                        'Uppdatera',
                        style: TextStyle(fontSize: 17),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    'Din version: ${installed ?? '?'}  ·  '
                    'Krävs: ${decision.required ?? '?'}',
                    style: const TextStyle(
                      fontSize: 13,
                      color: TbColors.ljusgraDjup,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _NudgeBanner extends StatelessWidget {
  const _NudgeBanner({
    required this.decision,
    required this.onUpdate,
    required this.onClose,
  });

  final UpgradeDecision decision;
  final VoidCallback onUpdate;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final message = decision.message;
    final canUpdate = (decision.storeUrl ?? '').isNotEmpty;
    return Align(
      alignment: Alignment.topCenter,
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: Material(
            color: TbColors.midnatt,
            elevation: 6,
            borderRadius: BorderRadius.circular(14),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 10, 4, 10),
              child: Row(
                children: [
                  const Icon(Icons.system_update, color: TbColors.guld),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Ny version finns. Uppdatera när du kan.',
                          style: TextStyle(
                            color: TbColors.vit,
                            fontWeight: FontWeight.w600,
                            fontSize: 14,
                          ),
                        ),
                        if (message != null)
                          Text(
                            message,
                            style: const TextStyle(
                              color: TbColors.ljusgraDjup,
                              fontSize: 13,
                            ),
                          ),
                      ],
                    ),
                  ),
                  if (canUpdate)
                    TextButton(
                      onPressed: onUpdate,
                      style: TextButton.styleFrom(
                        foregroundColor: TbColors.guld,
                      ),
                      child: const Text('Uppdatera'),
                    ),
                  // Ingen tooltip: banderollen ligger ovanför Navigator, där
                  // det inte finns någon Overlay att visa den i.
                  Semantics(
                    label: 'Stäng',
                    button: true,
                    child: IconButton(
                      onPressed: onClose,
                      icon: const Icon(Icons.close, color: TbColors.vit),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
