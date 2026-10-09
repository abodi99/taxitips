import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_client.dart';
import '../config.dart';
import '../membership_copy.dart';
import '../net_status.dart';
import '../signal_kinds.dart' show countyShort;
import '../theme.dart';
import '../widgets/brand_icons.dart';
import '../widgets/county_checklist.dart';
import '../widgets/notify_prefs_sheet.dart';
import '../widgets/settings_ui.dart';
import 'membership_county_screen.dart';
import 'onboarding_screen.dart';
import 'support_chat_screen.dart';
import 'trial_welcome_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    required this.api,
    this.onLogout,
    this.onLeftDevice,
    this.onShowTour,
  });

  final ApiClient api;
  final VoidCallback? onLogout;
  final VoidCallback? onLeftDevice;

  /// "Visa genomgången igen": stänger Inställningarna och startar den guidade
  /// genomgången på startsidan. Utan den visas ingen rad (ingen död knapp).
  final VoidCallback? onShowTour;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _loading = true;
  String? _error;
  int _supportUnread = 0;

  // Konto/medlemskap (kontobaserad vy, 2026-10): e-postadressen är en
  // upplysning -- den redigeras i kundportalen, inte i appen.
  String? _accountEmail;
  String? _companyName;

  /// Licensens län (rättighet), visningsnamn i kort form.
  List<String> _licenseCountyLabels = const [];

  /// Valda län i notiserna/filtret, om de smalnar av rättigheten.
  List<String> _activeCountyLabels = const [];

  bool get _isOffice => widget.api.sessionToken != null;
  bool get _isDevice => widget.api.deviceToken != null;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    super.dispose();
  }

  Future<void> _openSupportChat() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => SupportChatScreen(api: widget.api),
      ),
    );
    final unread = await widget.api.supportUnread();
    if (mounted) setState(() => _supportUnread = unread);
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    unawaited(
      widget.api.supportUnread().then((n) {
        if (mounted) setState(() => _supportUnread = n);
      }),
    );
    try {
      if (_isOffice) {
        // Företaget hanteras numera i kundportalen; appen visar bara
        // e-postadressen som upplysning.
        _accountEmail = widget.api.currentUserEmail ?? '';
      }
      if (_isDevice) {
        // fleetStatus (= /api/fleet/me) ger företagsnamnet till medlemskapets
        // beskrivning. Fordonen läses inte längre: platsen tilldelas kontot,
        // inte en bil (kontobaserat medlemskap, 2026-10). Fel här ska inte
        // blockera hela sidan.
        try {
          final status = await widget.api.fleetStatus();
          final company = status['company'] is Map
              ? Map<String, dynamic>.from(status['company'] as Map)
              : <String, dynamic>{};
          _companyName = company['name']?.toString();
        } catch (e) {
          debugPrint('SettingsScreen device load: $e');
        }
        try {
          await _loadCounties();
        } catch (e) {
          debugPrint('SettingsScreen counties: $e');
        }
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

  String _cleanError(Object e) => netAwareText(e);

  void _showSnack(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? TbColors.danger : TbColors.live,
      ),
    );
  }

  /// Integritetspolicyn och villkoren på taxitips.se. Förr byggdes länken på
  /// `api.baseUrl` (Supabase, api.taxitips.se), som svarar 401 på sidorna.
  Future<void> _openLegal(String path) async {
    final uri = Uri.parse('${ApiClient.webUrl}$path');
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  /// Kundportalen för företagets administratör (kontohantering på webben).
  /// SFSafariViewController / Chrome Custom Tabs först — synlig system-URL,
  /// inte en dold WebView. Faller tillbaka till extern webbläsare.
  Future<void> _openCompanyPortal() async {
    final uri = Uri.parse(TaxiTipsConfig.portalUrl);
    try {
      if (await launchUrl(uri, mode: LaunchMode.inAppBrowserView)) return;
    } catch (_) {
      // Plattformen saknar in-app-bläddrare; öppna externt.
    }
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  Future<void> _loadCounties() async {
    final data = await widget.api.getNotifyPrefs();
    final names = <String, String>{
      for (final c in (data['countyCatalog'] as List?) ?? const [])
        if (c is Map && c['code'] != null)
          c['code'].toString(): countyShort(c['name']?.toString() ?? ''),
    };
    String label(String code) => names[code] ?? code;
    final licensed = [
      for (final c in (data['licensedCounties'] as List?) ?? const [])
        label(c.toString()),
    ]..sort();
    final prefs = data['prefs'] is Map
        ? Map<String, dynamic>.from(data['prefs'] as Map)
        : <String, dynamic>{};
    final chosenCodes = [
      for (final c in (prefs['counties'] as List?) ?? const []) c.toString(),
    ];
    final licensedCodes = {
      for (final c in (data['licensedCounties'] as List?) ?? const [])
        c.toString(),
    };
    // Visa aktivt filter bara om det smalnar av — annars räcker licensraden.
    final narrowed =
        chosenCodes.isNotEmpty &&
        !(chosenCodes.length == licensedCodes.length &&
            chosenCodes.every(licensedCodes.contains));
    final active = narrowed
        ? ([for (final c in chosenCodes) label(c)]..sort())
        : <String>[];
    if (!mounted) return;
    setState(() {
      _licenseCountyLabels = licensed;
      _activeCountyLabels = active;
    });
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
    if (mounted) {
      try {
        await _loadCounties();
      } catch (_) {}
    }
  }

  /// "Dina län": en kryssruta per län i medlemskapet (CountyPickerSheet),
  /// alla förbockade tills föraren väljer bort något. Länen läses från
  /// servern varje gång, så ett län admin lagt till syns direkt.
  ///
  /// Ett prov får dessutom "Byt provets län" -- där väljer kunden själv länet
  /// (MembershipCountyScreen, setMembershipCounty/chooseTrialCounty). En betald
  /// eller beviljad plats får sina län av företagets admin, och förut öppnade
  /// tryck här en lista med ett enda val bland alla 21 län, som servern sedan
  /// nekade ("Medlemskapet är betalt").
  Future<void> _openCountyPicker() async {
    final navigator = Navigator.of(context);
    final membership = await _activeMembership();
    if (!mounted) return;
    final trial = membership != null && membership['trial'] == true;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: TbColors.foam,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) => ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(ctx).size.height * 0.8,
        ),
        child: CountyPickerSheet(
          api: widget.api,
          onChangeTrialCounty: trial
              ? () {
                  Navigator.of(ctx).pop();
                  navigator.push<void>(
                    MaterialPageRoute(
                      builder: (_) => MembershipCountyScreen(
                        api: widget.api,
                        licenseId: membership['licenseId']?.toString(),
                        onDone: () => navigator.pop(),
                      ),
                    ),
                  );
                }
              : null,
        ),
      ),
    );
    if (mounted) {
      try {
        await _loadCounties();
      } catch (_) {}
    }
  }

  /// Kontots aktiva medlemskap (`licenseId`, `trial`), eller null när kontot
  /// inte har något eller anropet inte är inloggat.
  Future<Map<String, dynamic>?> _activeMembership() async {
    try {
      final data = await widget.api.memberships();
      final list = (data['memberships'] as List? ?? const [])
          .whereType<Map>()
          .map((m) => Map<String, dynamic>.from(m))
          .toList();
      final active = data['activeLicenseId']?.toString();
      for (final m in list) {
        if (active != null && m['licenseId']?.toString() == active) return m;
      }
      return list.isNotEmpty ? list.first : null;
    } catch (_) {
      // Ingen inloggning eller inget medlemskap -- se ovan.
    }
    return null;
  }

  Future<void> _closeAccount() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Avsluta företagskontot?'),
        content: const Text(
          'Medlemskapet förnyas inte. Pågår ett prov avslutas det. '
          'Ni kan använda appen perioden ut.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Avbryt'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: TbColors.danger),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Avsluta'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      final result = await widget.api.closeCompanyAccount();
      _showSnack(result['explanation']?.toString() ?? 'Kontot är avslutat.');
      await _load();
    } catch (e) {
      _showSnack(_cleanError(e), isError: true);
    }
  }

  // ── Grupperna ──────────────────────────────────────────────────────────
  //
  // Varje grupp har en kort rubrik och en rad om vad man kan göra där. Ordning:
  // företaget (ägare), medlemskapet, notiser, konto, hjälp. Längst ner kommer
  // [_Footer]; något nytt som hör hemma sist (t.ex. radera kontot) läggs före
  // den, som en egen grupp.

  /// Företaget, för inloggad ägare/admin. Bilarna och förarna sköts numera i
  /// kundportalen på webben, inte i appen -- här finns bara genvägen dit som
  /// kontohantering, inte en köpknapp (membership_copy.dart).
  List<Widget> _companySection() => [
    const SettingsSectionHeader(
      title: 'Företaget',
      description: 'Hantera företagskontot i kundportalen på webben.',
    ),
    SettingsGroup(
      children: [
        SettingsNavRow(
          icon: Icons.manage_accounts_outlined,
          title: kPortalAccountTitle,
          subtitle: kPortalAccountSubtitle,
          trailingIcon: Icons.open_in_browser,
          onTap: () => unawaited(_openCompanyPortal()),
        ),
      ],
    ),
    const SizedBox(height: 28),
  ];

  /// Medlemskapet och kontot man kör med -- kontobaserad vy (2026-10).
  /// Platsen tilldelas kontot, inte en bil, så ingen "Välj bil"-rad behövs.
  /// Länen kommer från medlemskapet (samma lista som körområdet).
  List<Widget> _membershipSection() {
    final hasEmail = (_accountEmail?.isNotEmpty ?? false);
    if (_licenseCountyLabels.isEmpty && !hasEmail) return const [];
    return [
      SettingsSectionHeader(
        title: 'Medlemskap',
        description: _companyName == null
            ? 'Platsen du kör med och länen du får tips från.'
            : 'Platsen du kör med och länen du får tips från. Företag: $_companyName.',
      ),
      if (_licenseCountyLabels.isNotEmpty) ...[
        _CountiesOverview(
          licenseLabels: _licenseCountyLabels,
          onOpenCountyPicker: _openCountyPicker,
        ),
        const SizedBox(height: 12),
      ],
      if (hasEmail)
        SettingsGroup(
          children: [
            SettingsInfoRow(
              icon: Icons.person_outline,
              title: 'Inloggad som',
              value: _accountEmail!,
            ),
          ],
        ),
      const SizedBox(height: 28),
    ];
  }

  List<Widget> _notifySection() => [
    const SettingsSectionHeader(
      title: 'Notiser',
      description: 'Välj när telefonen ska säga till om ett starkt tips.',
    ),
    SettingsGroup(
      children: [
        SettingsNavRow(
          icon: BrandIcons.notification(size: 24, color: TbColors.muted),
          title: 'Notiser',
          subtitle: _activeCountyLabels.isNotEmpty
              ? 'Filter: ${_activeCountyLabels.join(', ')}'
              : (_licenseCountyLabels.isEmpty ? null : 'Alla dina län'),
          onTap: _openNotify,
        ),
      ],
    ),
    const SizedBox(height: 28),
  ];

  /// Kontot: e-post och lösenord sköts i kundportalen, inte i appen; här loggar
  /// man ut. En förare som bara har en telefon (utan eget konto) kan logga ut.
  /// Att koppla bort telefonen finns inte längre (2026-10-07): byte sker genom
  /// att logga in på en annan telefon, och servern tillåter ett byte per
  /// kalendermånad.
  List<Widget> _accountSection() {
    if (_isOffice) {
      return [
        const SettingsSectionHeader(title: 'Konto'),
        SettingsGroup(
          children: [
            if (widget.onLogout != null)
              SettingsNavRow(
                icon: Icons.logout,
                title: 'Logga ut',
                trailingIcon: Icons.chevron_right,
                onTap: widget.onLogout!,
              ),
          ],
        ),
        const SizedBox(height: 28),
      ];
    }
    if (_isDevice) {
      // Ingen utloggningsknapp att visa -> ingen död Konto-grupp (samma regel
      // som "Visa genomgången igen").
      if (widget.onLogout == null) return const [];
      return [
        const SettingsSectionHeader(
          title: 'Konto',
          description: 'Logga ut om du slutar köra eller byter telefon.',
        ),
        SettingsGroup(
          children: [
            SettingsNavRow(
              icon: Icons.logout,
              title: 'Logga ut',
              trailingIcon: Icons.chevron_right,
              onTap: widget.onLogout!,
            ),
          ],
        ),
        const SizedBox(height: 28),
      ];
    }
    return const [];
  }

  /// Hjälp: hur appen fungerar, genomgången igen och chatten.
  List<Widget> _helpSection() {
    final canChat = widget.api.canUseSupport;
    return [
      const SettingsSectionHeader(
        title: 'Hjälp',
        description: 'Se hur appen fungerar, eller skriv till oss.',
      ),
      SettingsGroup(
        children: [
          // Ägaren ser välkomsten till provet igen; föraren introduktionen.
          SettingsNavRow(
            icon: Icons.help_outline,
            iconColor: TbColors.taxiDeep,
            title: 'Så fungerar Taxi Tips',
            subtitle: _isOffice
                ? 'Provet, medlemskap och förare'
                : 'Fyra korta sidor',
            onTap: () => _isOffice
                ? TrialWelcomeScreen.openFromSettings(context, widget.api)
                : OnboardingScreen.openFromSettings(context),
          ),
          // Stänger Inställningarna; startsidan visar genomgången.
          if (widget.onShowTour != null)
            SettingsNavRow(
              icon: Icons.tour_outlined,
              iconColor: TbColors.taxiDeep,
              title: 'Visa genomgången igen',
              subtitle: 'Visar var du trycker på startsidan',
              onTap: widget.onShowTour!,
            ),
          if (canChat)
            SettingsNavRow(
              icon: Icons.chat_bubble_outline,
              iconColor: TbColors.taxiDeep,
              title: 'Chatta med oss',
              subtitle: _supportUnread > 0
                  ? (_supportUnread == 1
                        ? 'Ett nytt svar'
                        : '$_supportUnread nya svar')
                  : null,
              trailing: _supportUnread > 0
                  ? Badge.count(
                      count: _supportUnread,
                      backgroundColor: TbColors.danger,
                    )
                  : null,
              onTap: _openSupportChat,
            ),
        ],
      ),
      const SizedBox(height: 28),
    ];
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
              onRefresh: () async {
                await _load();
              },
              child: ListView(
                padding: EdgeInsets.fromLTRB(
                  16,
                  8,
                  16,
                  24 + MediaQuery.paddingOf(context).bottom,
                ),
                children: [
                  if (_error != null) ...[
                    _ErrorBanner(message: _error!),
                    const SizedBox(height: 16),
                  ],

                  if (_isOffice) ..._companySection(),
                  if (_isDevice) ..._membershipSection(),
                  if (_isDevice) ..._notifySection(),
                  ..._accountSection(),
                  if (_isOffice || _isDevice) ..._helpSection(),

                  if (!_isOffice && !_isDevice)
                    const Padding(
                      padding: EdgeInsets.only(bottom: 24),
                      child: Text('Logga in för att se inställningarna.'),
                    ),

                  _Footer(
                    onPrivacy: () => _openLegal('/privacy.html'),
                    onTerms: () => _openLegal('/terms.html'),
                    onData: () => showDataInfoDialog(context),
                    onCloseAccount: _isOffice ? _closeAccount : null,
                  ),
                  // Radera mitt konto: allra sist, se _AccountDeletionFooter.
                  // Förare får den neutrala fakturatexten; admin har redan
                  // portalgenvägen ovan och behöver inte samma rad igen.
                  if (_isOffice || _isDevice)
                    _AccountDeletionFooter(
                      onDelete: _deleteAccount,
                      showBillingNote: !_isOffice,
                    ),
                ],
              ),
            ),
    );
  }

  // --- Radera mitt konto (Apple 5.1.1(v)) ---------------------------------
  //
  // Ägare och förare raderar sitt eget konto här. "Avsluta företagskontot"
  // ovan stoppar bara förnyelsen. Reglerna (enda ägaren med ett medlemskap som
  // förnyas får ett nej med förklaring) bor på servern:
  // taxitips-backend/fleet/account_deletion.py.

  Future<void> _deleteAccount() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Radera ditt konto?'),
        content: Text(
          _isOffice
              ? 'Ditt konto och din inloggning tas bort för gott. Enheter du '
                    'kört med kopplas från medlemskapet. Är du ensam ägare avslutas ett '
                    'pågående prov. Det går inte att ångra.'
              : 'Ditt förarkonto tas bort och enheten kopplas från din plats. '
                    'Din chef kan bjuda in dig igen. Det går inte att ångra.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Avbryt'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: TbColors.danger),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Radera'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    unawaited(
      showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (_) => const PopScope(
          canPop: false,
          child: Center(child: CircularProgressIndicator(color: TbColors.taxi)),
        ),
      ),
    );
    Map<String, dynamic>? result;
    Object? error;
    try {
      result = await widget.api.deleteMyAccount();
    } catch (e) {
      error = e;
    }
    navigator.pop();
    if (!mounted) return;

    if (error != null) {
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Kontot raderades inte'),
          content: Text(_cleanError(error!)),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('OK'),
            ),
          ],
        ),
      );
      return;
    }

    messenger.showSnackBar(
      SnackBar(
        content: Text(
          result?['message']?.toString() ?? 'Ditt konto är raderat.',
        ),
        backgroundColor: TbColors.live,
      ),
    );
    // Telefonen har redan glömt kontot (ApiClient.deleteMyAccount). Tillbaka
    // till startskärmen.
    final leave = widget.onLeftDevice ?? widget.onLogout;
    leave?.call();
  }
}

/// Längst ner i Inställningarna: "Radera mitt konto", och för förare en
/// neutral rad om var fakturor sköts (ingen länk -- membership_copy.dart).
class _AccountDeletionFooter extends StatelessWidget {
  const _AccountDeletionFooter({
    required this.onDelete,
    this.showBillingNote = true,
  });

  final VoidCallback onDelete;

  /// Förare: visa [kBillingOnWeb]. Admin har portalgenvägen i företagsdelen.
  final bool showBillingNote;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Column(
        children: [
          if (showBillingNote) ...[
            const Text(
              kBillingOnWeb,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: TbColors.muted,
                fontSize: 13,
                height: 1.35,
              ),
            ),
            const SizedBox(height: 8),
          ],
          TextButton(
            onPressed: onDelete,
            style: TextButton.styleFrom(
              foregroundColor: TbColors.muted,
              minimumSize: const Size(0, 44),
              textStyle: const TextStyle(fontSize: 14),
            ),
            child: const Text('Radera mitt konto'),
          ),
        ],
      ),
    );
  }
}

/// Det man sällan behöver, i liten stil längst ner: villkor, datapolicy,
/// vad tipsen bygger på -- och att avsluta kontot, som måste gå att göra i
/// appen (Apple 5.1.1) men inte ska ligga bredvid vardagsknapparna.
class _Footer extends StatelessWidget {
  const _Footer({
    required this.onPrivacy,
    required this.onTerms,
    required this.onData,
    this.onCloseAccount,
  });

  final VoidCallback onPrivacy;
  final VoidCallback onTerms;
  final VoidCallback onData;
  final VoidCallback? onCloseAccount;

  @override
  Widget build(BuildContext context) {
    TextButton link(String text, VoidCallback onTap, {Color? color}) =>
        TextButton(
          onPressed: onTap,
          style: TextButton.styleFrom(
            foregroundColor: color ?? TbColors.muted,
            padding: const EdgeInsets.symmetric(horizontal: 8),
            minimumSize: const Size(48, 48),
            textStyle: const TextStyle(fontSize: 13),
          ),
          child: Text(text),
        );
    return Column(
      children: [
        Wrap(
          alignment: WrapAlignment.center,
          children: [
            link('Om tipsen', onData),
            link('Datapolicy', onPrivacy),
            link('Villkor', onTerms),
          ],
        ),
        if (onCloseAccount != null)
          link(
            'Avsluta företagskontot',
            onCloseAccount!,
            color: TbColors.muted,
          ),
      ],
    );
  }
}

/// Översikt över medlemskapets län -- de län platsen omfattar. Ett tryck
/// öppnar "Dina län" (CountyPickerSheet): en kryssruta per län i medlemskapet.
/// Notisfiltret nås i stället via "Notiser"-raden.
class _CountiesOverview extends StatelessWidget {
  const _CountiesOverview({
    required this.licenseLabels,
    required this.onOpenCountyPicker,
  });

  final List<String> licenseLabels;
  final VoidCallback onOpenCountyPicker;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: TbColors.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onOpenCountyPicker,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.map_outlined, size: 22, color: TbColors.muted),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Dina län',
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 16,
                      ),
                    ),
                  ),
                  const Icon(
                    Icons.chevron_right,
                    size: 20,
                    color: TbColors.muted,
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final name in licenseLabels)
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 7,
                      ),
                      decoration: BoxDecoration(
                        color: TbColors.ljusgra,
                        borderRadius: BorderRadius.circular(999),
                        border: Border.all(
                          color: TbColors.guld.withValues(alpha: 0.55),
                        ),
                      ),
                      child: Text(
                        name,
                        style: const TextStyle(
                          fontWeight: FontWeight.w600,
                          fontSize: 14,
                          color: TbColors.ink,
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                licenseLabels.length == 1
                    ? 'Tips och notiser i det här länet.'
                    : 'Tips och notiser i dina län. Tryck för att välja vilka.',
                style: const TextStyle(
                  fontSize: 13,
                  color: TbColors.muted,
                  height: 1.35,
                ),
              ),
            ],
          ),
        ),
      ),
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
