import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'backend_api.dart';
import 'config.dart';
import 'device_credential.dart';
import 'severity_labels.dart';

const _taxiAreaCatalog = [
  'Malmö',
  'Lund',
  'Helsingborg',
  'Kristianstad',
  'Hässleholm',
  'Landskrona',
  'Ystad',
  'Trelleborg',
  'Eslöv',
  'Ängelholm',
  'Bjuv',
  'Bromölla',
  'Burlöv',
  'Båstad',
  'Hörby',
  'Höör',
  'Klippan',
  'Kävlinge',
  'Lomma',
  'Lönsboda',
  'Osby',
  'Perstorp',
  'Simrishamn',
  'Sjöbo',
  'Skurup',
  'Staffanstorp',
  'Svalöv',
  'Svedala',
  'Tomelilla',
  'Vellinge',
  'Åstorp',
  'Örkelljunga',
  'Östra Göinge',
];

class ApiException implements Exception {
  ApiException(this.status, this.message, {this.reason, this.detail});
  final int status;
  final String message;

  /// Maskinläsbart skäl från backend (`takeover_required`, `not_approved`,
  /// `review_required` …). Finns för att appen ska kunna grena på ett stabilt
  /// värde i stället för på den svenska texten -- en omformulering i backend
  /// ska inte kunna slå sönder en dialogruta.
  final String? reason;

  /// Extra fält backend skickade med felet, t.ex. vem som har bilen.
  final Map<String, dynamic>? detail;

  @override
  String toString() => message;
}

/// TaxiTips client against Coolify Supabase (no local Express).
class ApiClient {
  ApiClient({String? supabaseUrl, String? supabaseAnonKey})
    : supabaseUrl = supabaseUrl ?? TaxiTipsConfig.supabaseUrl,
      supabaseAnonKey = supabaseAnonKey ?? TaxiTipsConfig.supabaseAnonKey;

  final String supabaseUrl;
  final String supabaseAnonKey;

  String get baseUrl => supabaseUrl;

  /// Django-backenden, när API_BASE_URL är satt. Null = allt går via
  /// Supabase som förut. Se TaxiTipsConfig.apiBaseUrl.
  final BackendApi? _backend = TaxiTipsConfig.usesDjangoApi
      ? BackendApi()
      : null;

  /// Kundlivscykeln finns bara i Django-backenden. Utan den konfigurerad
  /// säger vi det rakt ut i stället för att tyst falla tillbaka på den gamla
  /// bolagskodsvägen -- det var den som skulle bort.
  BackendApi get _fleet {
    final backend = _backend;
    if (backend == null) {
      throw ApiException(
        503,
        'API_BASE_URL är inte satt. Parkoppling och bilval kräver '
        'TaxiTips-backenden.',
      );
    }
    return backend;
  }

  /// Åtkomsttoken för en inloggad ägare/administratör. Föraren har ingen --
  /// den vägen bär `deviceToken` i stället, och backend godtar båda.
  String? get _accessToken {
    try {
      return _sb.auth.currentSession?.accessToken;
    } catch (_) {
      return null;
    }
  }

  String? sessionToken;
  String? deviceToken;
  String? installationId;

  static const _sessionKey = 'tb_session';
  // Den gamla nyckeln 'tb_device' läses och rensas numera av
  // DeviceCredentialStore, som flyttar hemligheten in i säker lagring första
  // gången appen startar efter uppdateringen. Inget här skriver till den.

  /// Enhetens hemlighet i plattformens säkra lagring. Se device_credential.dart.
  final DeviceCredentialStore credentials = DeviceCredentialStore();
  static const _installationKey = 'tb_installation_id';
  static const _emailKey = 'tb_email';
  static const _passwordKey = 'tb_password';

  SupabaseClient get _sb => Supabase.instance.client;

  Future<void> ensureInitialized() async {
    // Safe to call multiple times; supabase_flutter skips re-init internally.
    await Supabase.initialize(
      url: supabaseUrl,
      publishableKey: supabaseAnonKey,
      debug: false,
    );
  }

  Never _rethrowAsApiException(
    Object e, {
    StackTrace? stackTrace,
    String operation = 'unknown',
  }) {
    debugPrint('ApiClient[$operation] error: $e');
    if (stackTrace != null) {
      debugPrint('ApiClient[$operation] stack: $stackTrace');
    }

    if (e is ApiException) throw e;
    if (e is PostgrestException) {
      final parts = <String>[e.message];
      final details = e.details?.toString() ?? '';
      final hint = e.hint?.toString() ?? '';
      if (details.isNotEmpty) parts.add(details);
      if (hint.isNotEmpty) parts.add('hint: $hint');
      if ((e.code ?? '').isNotEmpty) parts.add('code: ${e.code}');
      final message = 'Databasfel: ${parts.join(' | ')}';
      debugPrint('ApiClient[$operation] PostgREST: $message');
      throw ApiException(500, message);
    }
    if (e is AuthException) {
      throw ApiException(401, 'Auth-fel: ${e.message}');
    }
    throw ApiException(500, e.toString());
  }

  Future<void> loadTokens() async {
    try {
      await ensureInitialized();
    } catch (_) {
      // Allow UI to boot; screens will surface config errors.
    }
    final prefs = await SharedPreferences.getInstance();
    // Hemligheten läses ur säker lagring; finns den bara på den gamla platsen
    // flyttas den dit i samma anrop.
    deviceToken = await credentials.read();
    installationId = prefs.getString(_installationKey);
    if (installationId == null || installationId!.isEmpty) {
      installationId = _newInstallationId();
      await prefs.setString(_installationKey, installationId!);
    }
    try {
      sessionToken = _sb.auth.currentSession?.accessToken;
    } catch (_) {
      sessionToken = null;
    }
    if (sessionToken == null) await prefs.remove(_sessionKey);
  }

  String _newInstallationId() {
    final r = Random.secure();
    final bytes = List<int>.generate(16, (_) => r.nextInt(256));
    // UUID-ish without importing extra packages.
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    String h(int b) => b.toRadixString(16).padLeft(2, '0');
    final s = bytes.map(h).join();
    return '${s.substring(0, 8)}-${s.substring(8, 12)}-'
        '${s.substring(12, 16)}-${s.substring(16, 20)}-${s.substring(20)}';
  }

  Future<String> ensureInstallationId() async {
    if (installationId != null && installationId!.isNotEmpty) {
      return installationId!;
    }
    await loadTokens();
    return installationId!;
  }

  Future<void> saveSession(String? token) async {
    sessionToken = token;
    final prefs = await SharedPreferences.getInstance();
    if (token == null) {
      await prefs.remove(_sessionKey);
    } else {
      await prefs.setString(_sessionKey, token);
    }
  }

  Future<void> saveDevice(String? token, {String scheme = 'hashed_v1'}) async {
    deviceToken = token;
    if (token == null) {
      await credentials.clear();
      return;
    }
    await credentials.write(token, scheme: scheme);
  }

  Future<void> clearDevice() async => saveDevice(null);

  Future<void> leaveAll() async {
    await logout();
    await clearDevice();
  }

  Future<({String? email, String? password})> loadSavedCredentials() async {
    final prefs = await SharedPreferences.getInstance();
    return (
      email: prefs.getString(_emailKey),
      password: prefs.getString(_passwordKey),
    );
  }

  Future<void> saveCredentials(String email, String password) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_emailKey, email);
    await prefs.setString(_passwordKey, password);
  }

  Future<({String? email, String? password})> loadDevTestLogin() async {
    return (email: null, password: null);
  }

  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    try {
      await ensureInitialized();
      final res = await _sb.auth.signInWithPassword(
        email: email,
        password: password,
      );
      final accessToken = res.session?.accessToken;
      if (accessToken == null || accessToken.isEmpty) {
        throw ApiException(401, 'Inloggningen gav ingen giltig session.');
      }
      await saveSession(accessToken);
      await saveCredentials(email, password);
      // Koppla telefonen till kontot + FCM sker i registerForPush efter
      // login (main/login_screen). Här räcker sessionen.

      // Auth is enough to consider login successful; profile/company bootstrap
      // can fail in environments where those tables are not yet provisioned.
      try {
        return await me();
      } catch (_) {
        return {
          'user': {'id': res.user?.id, 'email': res.user?.email, 'name': null},
          'profile': null,
          'company': null,
          'role': null,
          'devices': const [],
          'isOwner': false,
          'degraded': true,
        };
      }
    } catch (e, st) {
      _rethrowAsApiException(e, stackTrace: st, operation: 'login');
    }
  }

  Future<void> logout() async {
    try {
      await ensureInitialized();
      await _sb.auth.signOut();
    } catch (_) {}
    await saveSession(null);
  }

  Future<bool> signInWithGoogle() => _signInWithOAuth(OAuthProvider.google);

  Future<bool> signInWithApple() => _signInWithOAuth(OAuthProvider.apple);

  Future<bool> _signInWithOAuth(OAuthProvider provider) async {
    await ensureInitialized();
    // On mobile the browser returns via a deep link; on web Supabase uses its
    // configured site URL and the page reloads with a fresh session.
    final redirectTo = kIsWeb ? null : 'taxitips://auth-callback';
    final ok = await _sb.auth.signInWithOAuth(provider, redirectTo: redirectTo);
    final session = _sb.auth.currentSession;
    if (session != null) {
      await saveSession(session.accessToken);
    }
    return ok;
  }

  /// Completes a session that was established by an OAuth redirect (mobile).
  void listenForAuthSignIn(void Function() onSignedIn) {
    _sb.auth.onAuthStateChange.listen((state) {
      final session = state.session;
      if (session != null) {
        saveSession(session.accessToken);
        onSignedIn();
      }
    });
  }

  Future<Map<String, dynamic>> signup({
    required String name,
    required String email,
    required String password,
    required String orgNumber,
    String? companyName,
    int seats = 1,
    bool startCheckout = true,
    String? successUrl,
    String? cancelUrl,
  }) async {
    await ensureInitialized();
    final auth = await _sb.auth.signUp(
      email: email,
      password: password,
      data: {'name': name},
    );
    final userId = auth.user?.id;
    if (userId == null) throw ApiException(400, 'Kunde inte skapa konto');

    final company = await _sb
        .from('companies')
        .insert({
          'name': companyName ?? name,
          'email': email,
          'org_number': orgNumber,
          'join_code': _randomJoinCode(),
          'seats': seats,
          'status': 'trial',
        })
        .select()
        .single();

    await _sb.from('company_members').insert({
      'company_id': company['id'],
      'user_id': userId,
      'role': 'company_owner',
      'status': 'active',
    });

    await saveSession(auth.session?.accessToken);
    await saveCredentials(email, password);
    final result = await me();
    if (!startCheckout) return result;
    final checkout = await createCheckoutSession(seats: seats);
    return {
      ...result,
      'checkout': {...checkout, 'mode': 'stripe'},
    };
  }

  String _randomJoinCode() {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    final rnd = Random();
    return List.generate(6, (_) => chars[rnd.nextInt(chars.length)]).join();
  }

  Future<Map<String, dynamic>> me() async {
    try {
      await ensureInitialized();
      final user = _sb.auth.currentUser;
      if (user == null) throw ApiException(401, 'Inte inloggad');

      Map<String, dynamic>? profile;
      try {
        final p = await _sb
            .from('profiles')
            .select()
            .eq('id', user.id)
            .maybeSingle();
        profile = p == null ? null : Map<String, dynamic>.from(p as Map);
      } on PostgrestException {
        profile = null;
      }

      List memberships = const [];
      try {
        memberships = await _sb
            .from('company_members')
            .select('role, status, company:companies(*)')
            .eq('user_id', user.id)
            .eq('status', 'active');
      } on PostgrestException {
        memberships = const [];
      }

      Map<String, dynamic>? company;
      String? role;
      List devices = const [];
      List members = const [];
      if (memberships.isNotEmpty) {
        final m = Map<String, dynamic>.from(memberships.first as Map);
        role = m['role']?.toString();
        company = m['company'] is Map
            ? Map<String, dynamic>.from(m['company'] as Map)
            : null;
        if (company != null) {
          try {
            final devs = await _sb
                .from('devices')
                .select()
                .eq('company_id', company['id']);
            devices = (devs as List).map((d) {
              final row = Map<String, dynamic>.from(d as Map);
              return {
                ...row,
                'hasPush': (row['push_token']?.toString().isNotEmpty ?? false),
              };
            }).toList();
          } on PostgrestException {
            devices = const [];
          }
          try {
            // profiles har namn men inte e-post (e-post bor i auth.users).
            // Visa det vi kan; inbjudan av nya admins sker via webbportalen.
            final rows = await _sb
                .from('company_members')
                .select('role, status, user_id, user:profiles(id, name)')
                .eq('company_id', company['id'])
                .eq('status', 'active');
            members = (rows as List).map((row) {
              final r = Map<String, dynamic>.from(row as Map);
              final u = r['user'] is Map
                  ? Map<String, dynamic>.from(r['user'] as Map)
                  : <String, dynamic>{};
              final uid = r['user_id']?.toString() ?? u['id']?.toString();
              return {
                'userId': uid,
                'role': r['role'],
                'status': r['status'],
                'name': u['name']?.toString() ?? '',
                // Endast inloggad användare har e-post tillgänglig från klienten.
                'email': uid == user.id ? (user.email ?? '') : '',
              };
            }).toList();
          } on PostgrestException {
            members = const [];
          }
        }
      }

      final status = company?['status']?.toString() ?? '';
      final subStatus = company?['subscription_status']?.toString() ?? '';
      final subId = company?['stripe_subscription_id']?.toString();
      final hasSubscription = subId != null && subId.isNotEmpty;

      return {
        'user': {'id': user.id, 'email': user.email, 'name': profile?['name']},
        'profile': profile,
        'company': company == null
            ? null
            : {
                ...company,
                'watchedAreas': company['watched_areas'] ?? [],
                'joinCode': company['join_code'],
                'orgNumber': company['org_number'],
                'subscriptionStatus': subStatus,
                'stripeSubscriptionId': subId,
                'stripeCustomerId': company['stripe_customer_id'],
              },
        'billing': {
          'hasSubscription': hasSubscription,
          'subscriptionId': subId,
          'subscriptionStatus': subStatus,
          'status': status,
          'seats': company?['seats'],
        },
        'role': role,
        'devices': devices,
        'members': members,
        'isOwner': profile?['is_platform_owner'] == true,
      };
    } catch (e, st) {
      _rethrowAsApiException(e, stackTrace: st, operation: 'me');
    }
  }

  Future<Map<String, dynamic>> entitlements() async {
    await ensureInitialized();
    // current_entitlement() also accepts an authenticated owner/manager session
    // (no device pairing needed) via auth.uid() -- so only short-circuit when
    // there's neither a device token nor a logged-in user, since the RPC would
    // have nothing to check either way.
    if (deviceToken == null && _sb.auth.currentUser == null) {
      return {'ok': false, 'entitled': false};
    }
    try {
      final entitled = await _sb.rpc(
        'current_entitlement',
        params: {'p_device_token': deviceToken},
      );
      return {'ok': true, 'entitled': entitled == true};
    } catch (e) {
      debugPrint('ApiClient[entitlements] error: $e');
      return {'ok': false, 'entitled': false};
    }
  }

  Future<Map<String, dynamic>> publicConfig() async => {
    'supabaseUrl': supabaseUrl,
  };
  Future<Map<String, dynamic>> pricing() async => {
    'plans': [
      {
        'plan': 'driver',
        'interval': 'month',
        'unitAmount': 19900,
        'currency': 'sek',
        'displayName': 'Taxi Tips Driver',
        'priceId': 'price_1U7cJrP67HXLcerWkJ3vKy7I',
      },
    ],
  };
  Future<Map<String, dynamic>> lookupCompany(String org) async => {
    'orgNumber': org,
    'name': null,
  };

  Future<Map<String, dynamic>> getAreas() async {
    final meData = await me();
    final company = meData['company'] as Map<String, dynamic>?;
    return {
      'watchedAreas':
          company?['watchedAreas'] ?? company?['watched_areas'] ?? [],
      'catalog': _taxiAreaCatalog,
    };
  }

  Future<Map<String, dynamic>> saveAreas(List<String> areas) async {
    await ensureInitialized();
    final meData = await me();
    final company = meData['company'] as Map<String, dynamic>?;
    if (company == null) throw ApiException(400, 'Inget bolag');
    await _sb
        .from('companies')
        .update({'watched_areas': areas})
        .eq('id', company['id']);
    return {'watchedAreas': areas};
  }

  Future<Map<String, dynamic>> regenerateJoinCode() async {
    await ensureInitialized();
    final meData = await me();
    final company = meData['company'] as Map<String, dynamic>?;
    if (company == null) throw ApiException(400, 'Inget bolag');
    final code = await _sb.rpc(
      'regenerate_join_code',
      params: {'p_company_id': company['id']},
    );
    return {'joinCode': code};
  }

  /// Parkopplar telefonen med administratörens engångskod.
  ///
  /// Ersätter `join_device`-RPC:n, som delade ut en permanent enhetstoken
  /// direkt ur företagets statiska bolagskod. Koden står på ett papper i
  /// fikarummet; den som läste den fick betald data tills någon bytte kod --
  /// och bytet låste ut alla förare på en gång. Se supabase-migrationen
  /// 20260920000001_join_code_is_not_a_credential.sql.
  ///
  /// Hemligheten i svaret lämnar servern EN gång och läggs direkt i säker
  /// lagring.
  Future<Map<String, dynamic>> pairWithCode({
    required String code,
    String label = 'Förare',
    String? platform,
    String? pushToken,
  }) async {
    final installation = await ensureInstallationId();
    final data = await _fleet.pair(
      code: code,
      installationId: installation,
      label: label,
      platform: platform,
      pushToken: pushToken,
    );
    final secret = data['deviceToken']?.toString();
    if (secret == null || secret.isEmpty) {
      throw ApiException(500, 'Servern gav ingen enhetsnyckel.');
    }
    await saveDevice(secret);
    return data;
  }

  /// Bolagskoden hittar företaget och lägger en ANSÖKAN. Ingen token, ingen
  /// åtkomst, ingen administratörsbehörighet.
  Future<Map<String, dynamic>> requestJoin({
    required String joinCode,
    String label = 'Förare',
  }) async {
    final installation = await ensureInstallationId();
    return _fleet.joinRequest(
      joinCode: joinCode,
      installationId: installation,
      label: label,
    );
  }

  /// Vilka bilar telefonen får köra, vem som har dem, och vilken den kör nu.
  Future<Map<String, dynamic>> fleetStatus() async {
    if (deviceToken == null) await loadTokens();
    return _fleet.fleetStatus(deviceToken: deviceToken);
  }

  /// Tar bilen. `force: false` först -- servern svarar `takeover_required`
  /// när någon annan har den, och då frågar appen föraren.
  Future<Map<String, dynamic>> startVehicleSession({
    required String licenseId,
    bool force = false,
  }) async {
    if (deviceToken == null) await loadTokens();
    final token = deviceToken;
    if (token == null) throw ApiException(401, 'Telefonen är inte parkopplad.');
    return _fleet.startVehicleSession(
      licenseId: licenseId,
      deviceToken: token,
      force: force,
    );
  }

  Future<Map<String, dynamic>> endVehicleSession() async {
    if (deviceToken == null) await loadTokens();
    final token = deviceToken;
    if (token == null) return {'ok': true};
    return _fleet.endVehicleSession(deviceToken: token);
  }

  Future<Map<String, dynamic>> createTransferCode(String deviceId) async {
    await ensureInitialized();
    final code = _randomJoinCode() + _randomJoinCode();
    final expires = DateTime.now().toUtc().add(const Duration(hours: 24));
    await _sb.from('device_transfer_codes').upsert({
      'code': code,
      'device_id': deviceId,
      'expires_at': expires.toIso8601String(),
    });
    return {'transferCode': code, 'expiresAt': expires.toIso8601String()};
  }

  Future<Map<String, dynamic>> transferWithCode({
    required String transferCode,
    String? label,
  }) async {
    await ensureInitialized();
    final row = await _sb
        .from('device_transfer_codes')
        .select('*, device:devices(*)')
        .eq('code', transferCode.toUpperCase())
        .maybeSingle();
    if (row == null) throw ApiException(404, 'Ogiltig byteskod');
    final device = Map<String, dynamic>.from(row['device'] as Map);
    final newToken = List.generate(
      32,
      (_) => Random().nextInt(16).toRadixString(16),
    ).join();
    await _sb
        .from('devices')
        .update({
          'token': newToken,
          if (label != null && label.isNotEmpty) 'label': label,
        })
        .eq('id', device['id']);
    await _sb
        .from('device_transfer_codes')
        .delete()
        .eq('code', transferCode.toUpperCase());
    await saveDevice(newToken);
    return {'token': newToken, 'device': device};
  }

  Future<void> deleteDevice(String id) async {
    await ensureInitialized();
    await _sb.from('devices').delete().eq('id', id);
  }

  Future<Map<String, dynamic>> claimInvite(String token) async {
    // Legacy invite tokens — treat as transfer code.
    return transferWithCode(transferCode: token);
  }

  // Event types a driver can toggle notifications for, mirroring
  // severity_tier so the labels match what's already shown on cards instead
  // of introducing a second, inconsistent vocabulary. Kept client-side (no
  // server catalog table) since this is a small, stable, hand-picked list --
  // the same reasoning as severity_labels.dart's tier labels.
  static const notifyTypeCatalog = [
    {
      'id': 'line_paused',
      'label': 'Hela linjen står stilla',
      'short': 'Ingen trafik alls på linjen',
      'help': 'Störst chans att det finns folk som behöver taxi.',
      'defaultOn': true,
    },
    {
      'id': 'vehicle_cancelled',
      'label': 'Enstaka avgång inställd',
      'short': 'En avgång inställd, andra går som vanligt',
      'help': 'Färre påverkade, men kan ändå vara värt en titt.',
      'defaultOn': true,
    },
    {
      'id': 'road_accident_or_closure',
      'label': 'Olycka eller avstängd väg',
      'short': 'Vägtrafik',
      'help': 'Påverkar mest bilister redan på väg, men värt att veta om.',
      'defaultOn': true,
    },
    {
      'id': 'line_delayed',
      'label': 'Förseningar',
      'short': 'Linjen kör, men försenad',
      'help': 'Vanligtvis en svag signal -- av som standard.',
      'defaultOn': false,
    },
    {
      'id': 'road_work_or_queue',
      'label': 'Vägarbete eller köbildning',
      'short': 'Vägtrafik',
      'help': 'Sällan en taxisignal -- av som standard.',
      'defaultOn': false,
    },
  ];

  Future<Map<String, dynamic>> registerPushToken({
    required String fcmToken,
    String platform = 'web',
    String label = 'App',
  }) async {
    await ensureInitialized();
    final installId = await ensureInstallationId();
    final backend = _backend;
    if (backend != null) {
      final body = await backend.deviceSession(
        installationId: installId,
        pushToken: fcmToken.isEmpty ? null : fcmToken,
        label: label,
        platform: platform,
        // Förartoken om den finns; annars JWT → owner_app-enhet.
        deviceToken: deviceToken,
        accessToken: _accessToken,
      );
      final token = body['device_token']?.toString();
      // Ägare utan tidigare förartoken får installation_id som deviceToken
      // så notisprefs och X-Device-Token fungerar vidare i sessionen.
      if ((deviceToken == null || deviceToken!.isEmpty) &&
          token != null &&
          token.isNotEmpty) {
        await saveDevice(token);
      }
      return body;
    }
    // Fallback utan Django: gamla Supabase-uppdateringen kräver deviceToken.
    if (deviceToken == null) {
      throw ApiException(401, 'Ingen enhet — logga in via backend för push');
    }
    if (fcmToken.isEmpty) {
      return {'ok': true, 'linked': 'no_backend_no_fcm'};
    }
    final meDev = await getDeviceMe();
    final device = meDev['device'] as Map? ?? {};
    await _sb
        .from('devices')
        .update({
          'push_token': fcmToken,
          'last_seen_at': DateTime.now().toUtc().toIso8601String(),
        })
        .eq('id', device['id']);
    return {'ok': true};
  }

  /// Koppla installation till inloggat konto utan att kräva FCM-token.
  Future<Map<String, dynamic>> linkDeviceSession({
    String platform = 'web',
    String label = 'App',
  }) async {
    return registerPushToken(fcmToken: '', platform: platform, label: label);
  }

  /// Cities a driver can pick for notifications when their company hasn't
  /// configured watched_areas yet. Without this the sheet renders an empty
  /// city section -- the driver is told they can filter by city, then given
  /// nothing to filter by. These are the Skåne towns that actually appear in
  /// live opportunity data (verified against production), not a guess.
  static const skaneAreaFallback = [
    'Malmö',
    'Lund',
    'Helsingborg',
    'Kristianstad',
    'Hässleholm',
    'Landskrona',
    'Trelleborg',
    'Ystad',
    'Ängelholm',
    'Höör',
    'Eslöv',
    'Kävlinge',
    'Staffanstorp',
    'Svedala',
    'Vellinge',
  ];

  Future<Map<String, dynamic>> getNotifyPrefs() async {
    // Django äger katalogerna när backenden finns: händelsetyperna och
    // länen serveras av /api/notify-prefs, samma lista som push-steget
    // matchar mot (core/notify.py). Tidigare låg typkatalogen här i Dart
    // och defaulterna i fcmPush.js -- två kopior i två språk, utan något
    // som höll ihop dem. En typ kunde vara påslagen i appen och okänd för
    // sändaren.
    final backend = _backend;
    if (backend != null) {
      final body = await backend.notifyPrefs(
        deviceToken: deviceToken,
        accessToken: _accessToken,
      );
      final areas = (body['areaCatalog'] as List?)
              ?.map((e) => e.toString())
              .toList() ??
          skaneAreaFallback;
      final byRegionRaw = body['citiesByRegion'];
      final citiesByRegion = <String, List<String>>{};
      if (byRegionRaw is Map) {
        for (final e in byRegionRaw.entries) {
          final list = e.value;
          if (list is! List) continue;
          citiesByRegion[e.key.toString()] =
              list.map((c) => c.toString()).toList();
        }
      }
      return {
        'prefs': Map<String, dynamic>.from((body['prefs'] as Map?) ?? {}),
        'companyAreas': areas,
        'areaCatalog': areas,
        // Orter per län -- samma källa som push-steget. Tom map = äldre
        // backend; då faller UI tillbaka till den platta areaCatalog.
        'citiesByRegion': citiesByRegion,
        'regionCatalog': (body['regionCatalog'] as List?) ?? const [],
        // Alla 21 län med namn, för notisinställningarnas sammanfattning.
        'countyCatalog': (body['countyCatalog'] as List?) ?? const [],
        // Kommunerna per län (SCB-kod), för att förfina ett valt län.
        'municipalityCatalog': (body['municipalityCatalog'] as Map?) ?? const {},
        'uncoveredCounties': (body['uncoveredCounties'] as List?) ?? const [],
        // true = inloggad ägare utan parad telefon. Katalogerna går att
        // visa, men det finns ingen enhet att spara för -- och det är ett
        // bättre svar än ett formulär som tyst inte sparar.
        'readOnly': body['readOnly'] == true,
        'reason': body['reason'],
        'meta': {
          'catalog': (body['typeCatalog'] as List?) ?? notifyTypeCatalog,
          'tips': const <String>[],
        },
      };
    }
    final meDev = await getDeviceMe();
    final device = meDev['device'] as Map? ?? {};
    final company = meDev['company'] as Map? ?? {};
    final prefs = device['notify_prefs'] ?? {};
    final watchedAreas =
        (company['watched_areas'] as List?)
            ?.map((e) => e.toString())
            .toList() ??
        const <String>[];
    // Company areas take priority when set (the office curated them), else
    // fall back to the region-wide list so the picker is never empty.
    final areas = watchedAreas.isNotEmpty ? watchedAreas : skaneAreaFallback;
    return {
      'prefs': Map<String, dynamic>.from(prefs is Map ? prefs : {}),
      'companyAreas': areas,
      'areaCatalog': areas,
      'meta': {'catalog': notifyTypeCatalog, 'tips': const <String>[]},
    };
  }

  static const _onDutyKey = 'tb_on_duty';
  bool? _onDuty;
  DateTime? _presenceSentAt;

  /// Hur ofta en öppen app förnyar "I tjänst". Servern låter rutan gälla i
  /// 30 minuter, så en förare som stänger appen faller tillbaka på körområdet.
  static const presenceInterval = Duration(minutes: 5);

  Future<bool> onDuty() async {
    if (_onDuty != null) return _onDuty!;
    final prefs = await SharedPreferences.getInstance();
    _onDuty = prefs.getBool(_onDutyKey) ?? false;
    return _onDuty!;
  }

  /// Slår på eller av "I tjänst". Kräver Django-backenden och en parad telefon.
  Future<void> setOnDuty(bool on, {double? lat, double? lon}) async {
    final backend = _backend;
    if (backend == null) {
      throw Exception('I tjänst kräver den nya backenden');
    }
    await backend.setPresence(
      on: on,
      lat: lat,
      lon: lon,
      deviceToken: deviceToken,
      accessToken: _accessToken,
    );
    _onDuty = on;
    _presenceSentAt = on ? DateTime.now() : null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_onDutyKey, on);
  }

  /// Förnyar "I tjänst" högst var femte minut. Anropas bara från skärmens
  /// hämtning, som inte körs i bakgrunden -- ingen bakgrundsspårning.
  Future<void> refreshPresence({double? lat, double? lon}) async {
    final backend = _backend;
    if (backend == null || lat == null || lon == null) return;
    if (!await onDuty()) return;
    final sent = _presenceSentAt;
    if (sent != null && DateTime.now().difference(sent) < presenceInterval) {
      return;
    }
    try {
      await backend.setPresence(
        on: true,
        lat: lat,
        lon: lon,
        deviceToken: deviceToken,
        accessToken: _accessToken,
      );
      _presenceSentAt = DateTime.now();
    } catch (_) {
      // Utan förnyelse går rutan ut, och körområdet gäller igen.
    }
  }

  /// Färjor i förarens område (Django-backenden). Utan den: inga färjor.
  Future<Map<String, dynamic>> ferries({
    double? lat,
    double? lon,
    List<String>? counties,
    List<String>? municipalities,
  }) async {
    final backend = _backend;
    if (backend == null) return const {'ferries': [], 'terminals': []};
    return backend.ferries(
      lat: lat,
      lon: lon,
      counties: counties,
      municipalities: municipalities,
      deviceToken: deviceToken,
      accessToken: _accessToken,
    );
  }

  /// Kommande evenemang i förarens område (Django-backenden).
  Future<Map<String, dynamic>> events({
    double? lat,
    double? lon,
    List<String>? counties,
    List<String>? municipalities,
    String? from,
    String? to,
  }) async {
    final backend = _backend;
    if (backend == null) return const {'events': []};
    return backend.events(
      lat: lat,
      lon: lon,
      counties: counties,
      municipalities: municipalities,
      from: from,
      to: to,
      deviceToken: deviceToken,
      accessToken: _accessToken,
    );
  }

  Future<Map<String, dynamic>> saveNotifyPrefs({
    bool? enabled,
    List<String>? cities,
    List<String>? regions,
    List<String>? counties,
    List<String>? municipalities,
    Map<String, bool>? types,
  }) async {
    final backend = _backend;
    if (backend != null) {
      final body = await backend.saveNotifyPrefs(
        enabled: enabled,
        cities: cities,
        regions: regions,
        counties: counties,
        municipalities: municipalities,
        types: types,
        deviceToken: deviceToken,
        accessToken: _accessToken,
      );
      return Map<String, dynamic>.from((body['prefs'] as Map?) ?? {});
    }
    await ensureInitialized();
    final meDev = await getDeviceMe();
    final device = meDev['device'] as Map? ?? {};
    final current = Map<String, dynamic>.from(
      (device['notify_prefs'] as Map?) ?? {},
    );
    if (enabled != null) current['enabled'] = enabled;
    if (cities != null) current['cities'] = cities;
    if (regions != null) current['regions'] = regions;
    if (counties != null) current['counties'] = counties;
    if (municipalities != null) current['municipalities'] = municipalities;
    if (types != null) current['types'] = types;
    await _sb
        .from('devices')
        .update({'notify_prefs': current})
        .eq('id', device['id']);
    return current;
  }

  Future<Map<String, dynamic>> updateCompanyProfile({
    String? name,
    String? orgNumber,
  }) async {
    await ensureInitialized();
    final meData = await me();
    final company = meData['company'] as Map<String, dynamic>?;
    if (company == null) throw ApiException(400, 'Inget bolag');
    await _sb
        .from('companies')
        .update({'name': ?name, 'org_number': ?orgNumber})
        .eq('id', company['id']);
    return me();
  }

  Future<Map<String, dynamic>> changeEmail({
    required String currentPassword,
    required String newEmail,
  }) async {
    await ensureInitialized();
    await _sb.auth.updateUser(UserAttributes(email: newEmail));
    return {'ok': true};
  }

  Future<Map<String, dynamic>> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    await ensureInitialized();
    await _sb.auth.updateUser(UserAttributes(password: newPassword));
    return {'ok': true};
  }

  Future<void> sendPasswordCode(String email) async {
    await ensureInitialized();
    await _sb.auth.signInWithOtp(
      email: email.trim().toLowerCase(),
      shouldCreateUser: false,
    );
  }

  Future<void> sendEmailChangeCode(String email) async {
    await ensureInitialized();
    await _sb.auth.signInWithOtp(
      email: email.trim().toLowerCase(),
      shouldCreateUser: false,
    );
  }

  Future<void> changeEmailWithCode({
    required String oldEmail,
    required String code,
    required String newEmail,
  }) async {
    await ensureInitialized();
    final response = await _sb.auth.verifyOTP(
      email: oldEmail.trim().toLowerCase(),
      token: code.trim(),
      type: OtpType.email,
    );
    final session = response.session;
    if (session == null) {
      throw ApiException(401, 'Verifieringskoden är ogiltig');
    }
    await saveSession(session.accessToken);
    await _sb.auth.updateUser(
      UserAttributes(email: newEmail.trim().toLowerCase()),
    );
  }

  Future<void> changePasswordWithCode({
    required String email,
    required String code,
    required String newPassword,
  }) async {
    await ensureInitialized();
    final response = await _sb.auth.verifyOTP(
      email: email.trim().toLowerCase(),
      token: code.trim(),
      type: OtpType.email,
    );
    final session = response.session;
    if (session == null) {
      throw ApiException(401, 'Verifieringskoden är ogiltig');
    }
    await saveSession(session.accessToken);
    await _sb.auth.updateUser(UserAttributes(password: newPassword));
  }

  Future<Map<String, dynamic>> getDeviceMe() async {
    await ensureInitialized();
    if (deviceToken == null) throw ApiException(401, 'Ingen enhet');
    final data = await _sb.rpc(
      'device_by_token',
      params: {'p_token': deviceToken},
    );
    return Map<String, dynamic>.from(data as Map);
  }

  Future<Map<String, dynamic>> updateDeviceLabel(String label) async {
    await ensureInitialized();
    final meDev = await getDeviceMe();
    final device = meDev['device'] as Map? ?? {};
    await _sb.from('devices').update({'label': label}).eq('id', device['id']);
    return {'label': label};
  }

  /// 🚕 / 👍 / 👎 -- `verdict` är heading, fare eller empty.
  ///
  /// Django-vägen skriver till `opportunity_feedback`, vars främmande nyckel
  /// pekar på `opportunities`. Supabases `alert_feedback` pekar fortfarande
  /// på `alerts`, och de två id-rymderna överlappar inte i en enda rad --
  /// varje tumme upp sedan flytten till opportunities har därför avvisats av
  /// databasen och landat i catch-blocket nedan, tyst. Tabellen har noll
  /// rader. Utan API_BASE_URL är beteendet oförändrat: det är samma tysta
  /// väg som förut, men den syns nu i loggen.
  Future<Map<String, dynamic>> submitAlertFeedback(
    String alertId,
    bool result, {
    String? verdict,
  }) async {
    final backend = _backend;
    if (backend != null) {
      try {
        await backend.submitFeedback(
          opportunityId: alertId,
          verdict: verdict ?? (result ? 'fare' : 'empty'),
          deviceToken: deviceToken,
          accessToken: _accessToken,
        );
        return {'success': true};
      } catch (e) {
        debugPrint('ApiClient[feedback] backend: $e');
        return {'error': e.toString()};
      }
    }
    try {
      await ensureInitialized();
      await _sb.from('alert_feedback').insert({
        'alert_id': alertId,
        'device_token': deviceToken,
        'result': result,
      });
      return {'success': true};
    } catch (e) {
      debugPrint('ApiClient[feedback] supabase: $e');
      return {'error': e.toString()};
    }
  }

  Future<List> _smartAlertsViaRpc(double? lat, double? lon) async {
    final rows = await _sb.rpc(
      'get_smart_alerts',
      params: {'p_lat': lat, 'p_lon': lon, 'p_device_token': deviceToken},
    );
    return (rows as List?) ?? const [];
  }

  /// Ett tips i den form korten, kartan och sorteringen läser.
  ///
  /// Samma fältnamn oavsett väg -- Django-API:t svarar med RPC:ns namn med
  /// avsikt. Skillnaden är att Django också skickar `level` (bedömningen
  /// redan gjord, se core/thresholds.py) och ersättningsfälten, som RPC:n
  /// aldrig exponerade. Saknas `level` räknar severity_labels.dart ut det
  /// lokalt, så Supabase-vägen ser likadan ut som förut.
  Map<String, dynamic> _alertFromRow(Map<String, dynamic> m) {
    final alert = <String, dynamic>{
      'id': m['id'],
      'title': m['title'],
      'summary': m['summary'],
      'lat': m['lat'],
      'lon': m['lon'],
      'start_time': m['start_time'],
      'end_time': m['end_time'],
      'demand_score': m['demand_score'],
      'reasons': m['reasons'] ?? const [],
      'distance_km': m['distance_km'],
      'worth_it_score': m['worth_it_score'],
      'is_active': m['is_active'] ?? true,
      'kind': m['kind'],
      'mode': m['mode'],
      'region': m['region'],
      'county': m['county'],
      'countyName': m['countyName'],
      'municipality': m['municipality'],
      'severity_tier': m['severity_tier'],
      'confidence': m['confidence'],
      'level': m['level'],
      'notify_worthy': m['notify_worthy'],
      'has_alternative': m['has_alternative'] == true,
      'compensation_eligible': m['compensation_eligible'] == true,
      'compensation_amount_kr': m['compensation_amount_kr'],
      // true/false/null -- null betyder att huvudmannen inte skriver ut
      // det, och då säger kortet inget heller.
      'compensation_per_person': m['compensation_per_person'],
      // "Vad gör resenären i stället?" -- formulerad av backend
      // (core/alternatives.py) så att kort, detaljvy och push säger samma
      // sak. Saknas den (Supabase-vägen) visas ingen rad alls.
      'travel_options': m['travel_options'],
      // Sätts av backend (core/api.py) utifrån förarens sparade favoriter,
      // inte av appen: ett sparat tips ska se likadant ut oavsett vilken
      // enhet det öppnas på.
      'is_favorite': m['is_favorite'] == true,
      // Bara satt på rader ur favoritlistan. true = tipset har gallrats ur
      // databasen och kortet visas ur den sparade ögonblicksbilden.
      'purged': m['purged'] == true,
      'favorited_at': m['favorited_at'],
      'note': m['note'],
    };
    // `taxi.level` hade en egen kopia av gränserna (>50 hög, >20 medel) --
    // en femte kopia av tröskeln som backend redan äger. Nu är det samma
    // bedömning som badgen och pushen använder.
    alert['taxi'] = {
      'level': likelihoodForAlert(alert).name,
      'places': (m['places'] as List?) ?? const [],
    };
    return alert;
  }

  Future<Map<String, dynamic>> taxi({
    bool demo = false,
    double? userLat,
    double? userLon,
    List<String>? regions,
    List<String>? counties,
    List<String>? municipalities,
  }) async {
    try {
      await ensureInitialized();
      final lat = userLat;
      final lon = userLon;

      List rows;
      // Favoriterna kommer med i samma svar som flödet -- backend skickar
      // dem alltid, oavsett filter, radie eller om störningen tagit slut.
      // Ett extra anrop hade gjort favoritlistan tom just när täckningen är
      // dålig, vilket är när en förare oftast tittar på den.
      List favoriteRows = const [];
      var source = 'trafiklab';
      var needsArea = false;
      final backend = _backend;
      if (backend != null) {
        // Django äger både marknadsurvalet och bedömningen. Den äldre
        // RPC-vägen har andra trösklar och kan innehålla inaktuella alerts,
        // så ett backendfel får inte tyst ersättas med felaktiga taxitips.
        // Valda län skickas med så GPS-bubblan inte kapar Stockholm/Göteborg
        // innan listfiltret får se dem.
        final body = await backend.alerts(
          lat: lat,
          lon: lon,
          regions: regions,
          counties: counties,
          municipalities: municipalities,
          deviceToken: deviceToken,
          accessToken: _accessToken,
        );
        rows = (body['alerts'] as List?) ?? const [];
        // Väghändelser ligger i `context` (kapade, låga poäng) — de är
        // sammanhang för vägen dit, inte skäl att köra någonstans. Appen
        // tar med dem så föraren kan filtrera in/ut väg; sorteringen håller
        // dem längst ner eftersom poängen är ≤15.
        final contextRows = (body['context'] as List?) ?? const [];
        if (contextRows.isNotEmpty) {
          rows = [...rows, ...contextRows];
        }
        // Varken plats eller körområde: servern skickar ingen rikstäckande
        // lista, och skärmen ber föraren välja län.
        needsArea = body['needsArea'] == true;
        favoriteRows = (body['favorites'] as List?) ?? const [];
        source = 'django';
      } else {
        rows = await _smartAlertsViaRpc(lat, lon);
      }

      final now = DateTime.now().toUtc();
      final all = [
        for (final r in rows)
          _alertFromRow(Map<String, dynamic>.from(r as Map)),
      ];

      final favorites = [
        for (final r in favoriteRows)
          _alertFromRow(Map<String, dynamic>.from(r as Map)),
      ];

      return {
        'alerts': all,
        'favorites': favorites,
        // Flödet innehåller det senaste dygnet, inte bara det som pågår just
        // nu (`is_active` skiljer dem åt) -- en förare som börjar sitt pass
        // ska kunna se vad som hände i natt.
        'active': all,
        'week': all,
        'events': const [],
        'placeStats': _buildPlaceStats(all),
        'demo': demo,
        'updatedAt': now.millisecondsSinceEpoch,
        'source': source,
        'needsArea': needsArea,
      };
    } on PostgrestException catch (e) {
      // Some environments are not provisioned with the alerts table yet.
      if (e.code == 'PGRST205' && e.message.contains("public.alerts")) {
        debugPrint(
          'ApiClient[taxi.alerts] alerts table missing, returning empty alerts.',
        );
        return {
          'alerts': const [],
          'favorites': const [],
          'active': const [],
          'week': const [],
          'events': const [],
          'placeStats': const [],
          'demo': demo,
          'updatedAt': DateTime.now().millisecondsSinceEpoch,
          'source': 'trafiklab',
        };
      }
      _rethrowAsApiException(e, operation: 'taxi.alerts');
    } catch (e, st) {
      _rethrowAsApiException(e, stackTrace: st, operation: 'taxi.alerts');
    }
  }

  /// Explainability: fetches the raw source event(s) and scoring provenance
  /// (rule_id/confidence) behind one opportunity. Only called on demand when a
  /// driver taps "Varför visas detta?" -- not fetched eagerly for every card, to
  /// avoid hitting the backend for detail nobody asked to see.
  Future<Map<String, dynamic>> opportunityDetail(String opportunityId) async {
    try {
      final backend = _backend;
      if (backend != null) {
        return await backend.opportunityDetail(
          opportunityId,
          deviceToken: deviceToken,
          accessToken: _accessToken,
        );
      }
      await ensureInitialized();
      final data = await _sb.rpc(
        'get_opportunity_detail',
        params: {
          'p_opportunity_id': opportunityId,
          'p_device_token': deviceToken,
        },
      );
      if (data == null) return {};
      return Map<String, dynamic>.from(data as Map);
    } catch (e, st) {
      _rethrowAsApiException(e, stackTrace: st, operation: 'opportunityDetail');
    }
  }

  List<Map<String, dynamic>> _buildPlaceStats(
    List<Map<String, dynamic>> alerts,
  ) {
    final map = <String, Map<String, dynamic>>{};
    for (final a in alerts) {
      final places = ((a['taxi'] as Map?)?['places'] as List?) ?? const [];
      final lat = (a['lat'] as num?)?.toDouble();
      final lon = (a['lon'] as num?)?.toDouble();
      for (final p in places) {
        final name = p.toString();
        if (name.isEmpty) continue;
        final cur = map[name] ?? <String, dynamic>{'name': name, 'count': 0};
        cur['count'] = ((cur['count'] as num?)?.toInt() ?? 0) + 1;
        if (lat != null && lon != null && !cur.containsKey('lat')) {
          cur['lat'] = lat;
          cur['lon'] = lon;
        }
        map[name] = cur;
      }
    }
    return map.values.toList();
  }

  /// Sparar eller tar bort ett tips ur favoritlistan.
  ///
  /// Bara Django-vägen: favoriterna bor i `opportunity_favorite`, en tabell
  /// Django äger. Utan backend är stjärnan inte trasig utan frånvarande --
  /// se `supportsFavorites`, som styr om knappen ritas alls. En knapp som
  /// syns men tyst inte sparar är sämre än ingen knapp.
  Future<bool> setFavorite({
    required String opportunityId,
    required bool favorite,
    String? note,
  }) async {
    final backend = _backend;
    if (backend == null) {
      throw ApiException(501, 'Favoriter kräver Django-backenden');
    }
    try {
      final body = await backend.setFavorite(
        opportunityId: opportunityId,
        favorite: favorite,
        note: note,
        deviceToken: deviceToken,
        accessToken: _accessToken,
      );
      return body['favorite'] == true;
    } catch (e, st) {
      _rethrowAsApiException(e, stackTrace: st, operation: 'setFavorite');
    }
  }

  /// Favoritlistan för sig, utan att hämta hela flödet.
  Future<List<Map<String, dynamic>>> favorites({
    double? userLat,
    double? userLon,
  }) async {
    final backend = _backend;
    if (backend == null) return const [];
    try {
      final body = await backend.favorites(
        lat: userLat,
        lon: userLon,
        deviceToken: deviceToken,
        accessToken: _accessToken,
      );
      return [
        for (final r in (body['favorites'] as List?) ?? const [])
          _alertFromRow(Map<String, dynamic>.from(r as Map)),
      ];
    } catch (e, st) {
      _rethrowAsApiException(e, stackTrace: st, operation: 'favorites');
    }
  }

  /// Notiserna den här enheten faktiskt fått.
  ///
  /// `reason: no_device` betyder att inloggningen saknar parad telefon --
  /// notiser går till enheter, och en ägare som loggat in på webben har
  /// per definition inte fått några. Det är ett svar, inte ett fel, och
  /// skiljer sig från "du har inte fått några notiser än".
  Future<Map<String, dynamic>> notifications() async {
    final backend = _backend;
    if (backend == null) {
      return {'notifications': const [], 'reason': 'no_backend'};
    }
    try {
      final body = await backend.notifications(
        deviceToken: deviceToken,
        accessToken: _accessToken,
      );
      return {
        'notifications': [
          for (final n in (body['notifications'] as List?) ?? const [])
            Map<String, dynamic>.from(n as Map),
        ],
        'reason': body['reason'],
        'hint': body['hint'],
      };
    } catch (e, st) {
      _rethrowAsApiException(e, stackTrace: st, operation: 'notifications');
    }
  }

  /// Finns Django-backenden? Favoriter och notishistorik bor bara där.
  bool get supportsFavorites => _backend != null;

  Future<Map<String, dynamic>> health() async => {
    'ok': true,
    'backend': _backend == null ? 'supabase' : 'django',
  };

  Future<Map<String, dynamic>> _invokeFunction(
    String name, {
    Map<String, dynamic>? body,
  }) async {
    await ensureInitialized();
    try {
      final res = await _sb.functions.invoke(name, body: body);
      final data = res.data;
      if (data is Map<String, dynamic>) {
        final error = data['error']?.toString();
        if (error != null && error.isNotEmpty) {
          throw ApiException(500, error);
        }
        return data;
      }
      return <String, dynamic>{};
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException(
        500,
        e.toString().replaceFirst('FunctionException: ', ''),
      );
    }
  }

  Future<Map<String, dynamic>> billingPortal() =>
      _invokeFunction('billing-portal');

  Future<Map<String, dynamic>> createCheckoutSession({required int seats}) =>
      _invokeFunction('create-checkout-session', body: {'seats': seats});

  Future<Map<String, dynamic>> updateBillingQuantity(int seats) async {
    await ensureInitialized();
    final meData = await me();
    final company = meData['company'] as Map<String, dynamic>?;
    if (company == null) throw ApiException(400, 'Inget bolag');
    final res = await _invokeFunction(
      'update-subscription-quantity',
      body: {'seats': seats},
    );
    return {
      'quantity': res['quantity'] ?? seats,
      'synced': res['synced'] == true,
    };
  }

  Future<Map<String, dynamic>> listMembers() async {
    final meData = await me();
    return {
      'members': (meData['members'] as List?) ?? const [],
    };
  }

  /// Inbjudan av ny admin kräver Auth Admin (skapas på webbportalen).
  /// Klienten kan inte skapa auth-användare med anon-nyckeln.
  Future<Map<String, dynamic>> addMember({
    required String email,
    String name = '',
    String role = 'company_admin',
  }) async {
    throw ApiException(
      501,
      'Bjud in kollegor via webbportalen (taxitips.se) — '
      'appen kan ta bort admins och hantera förartelefoner, '
      'men nya inloggningar skapas med e-postinbjudan där.',
    );
  }

  Future<Map<String, dynamic>> removeMember(String userId) async {
    await ensureInitialized();
    final meData = await me();
    final company = meData['company'] as Map<String, dynamic>?;
    if (company == null) throw ApiException(400, 'Inget bolag');
    await _sb
        .from('company_members')
        .delete()
        .eq('company_id', company['id'])
        .eq('user_id', userId);
    return {'ok': true};
  }
}
