import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'config.dart';

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
  ApiException(this.status, this.message);
  final int status;
  final String message;
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

  String? sessionToken;
  String? deviceToken;

  static const _sessionKey = 'tb_session';
  static const _deviceKey = 'tb_device';
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
    deviceToken = prefs.getString(_deviceKey);
    try {
      sessionToken = _sb.auth.currentSession?.accessToken;
    } catch (_) {
      sessionToken = prefs.getString(_sessionKey);
    }
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

  Future<void> saveDevice(String? token) async {
    deviceToken = token;
    final prefs = await SharedPreferences.getInstance();
    if (token == null) {
      await prefs.remove(_deviceKey);
    } else {
      await prefs.setString(_deviceKey, token);
    }
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
      await saveSession(res.session?.accessToken);
      await saveCredentials(email, password);

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
        }
      }

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
              },
        'role': role,
        'devices': devices,
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

  Future<Map<String, dynamic>> joinWithCode({
    required String joinCode,
    String label = 'Förare',
    String kind = 'driver',
  }) async {
    await ensureInitialized();
    final data = await _sb.rpc(
      'join_device',
      params: {'p_join_code': joinCode, 'p_label': label},
    );
    final map = Map<String, dynamic>.from(data as Map);
    await saveDevice(map['token']?.toString());
    return map;
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

  Future<Map<String, dynamic>> registerPushToken({
    required String fcmToken,
    String platform = 'web',
  }) async {
    await ensureInitialized();
    if (deviceToken == null) throw ApiException(401, 'Ingen enhet');
    final meDev = await getDeviceMe();
    await _sb
        .from('devices')
        .update({'push_token': fcmToken})
        .eq('id', meDev['id']);
    return {'ok': true};
  }

  Future<Map<String, dynamic>> getNotifyPrefs() async {
    final meDev = await getDeviceMe();
    final prefs = meDev['notify_prefs'] ?? meDev['notifyPrefs'] ?? {};
    return Map<String, dynamic>.from(prefs is Map ? prefs : {});
  }

  Future<Map<String, dynamic>> saveNotifyPrefs({
    bool? enabled,
    List<String>? cities,
    Map<String, bool>? types,
  }) async {
    await ensureInitialized();
    final current = await getNotifyPrefs();
    if (enabled != null) current['enabled'] = enabled;
    if (cities != null) current['cities'] = cities;
    if (types != null) current['types'] = types;
    final meDev = await getDeviceMe();
    await _sb
        .from('devices')
        .update({'notify_prefs': current})
        .eq('id', meDev['id']);
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
    await _sb.from('devices').update({'label': label}).eq('id', meDev['id']);
    return {'label': label};
  }

  Future<Map<String, dynamic>> submitAlertFeedback(
    String alertId,
    bool result,
  ) async {
    try {
      await ensureInitialized();
      await _sb.from('alert_feedback').insert({
        'alert_id': alertId,
        'device_token': deviceToken,
        'result': result,
      });
      return {'success': true};
    } catch (e) {
      return {'error': e.toString()};
    }
  }

  Future<Map<String, dynamic>> taxi({
    bool demo = false,
    double? userLat,
    double? userLon,
  }) async {
    try {
      await ensureInitialized();
      final rows = await _sb.rpc(
        'get_smart_alerts',
        params: {
          'p_lat': userLat ?? 55.604981, // Default Malmö if no location
          'p_lon': userLon ?? 13.003822,
          'p_device_token': deviceToken,
        },
      );

      final now = DateTime.now().toUtc();
      final active = <Map<String, dynamic>>[];
      final week = <Map<String, dynamic>>[];
      final all = <Map<String, dynamic>>[];
      for (final r in (rows as List)) {
        final m = Map<String, dynamic>.from(r as Map);
        // Map the RPC output back to the format the UI expects, plus the new fields
        final alert = <String, dynamic>{
          'id': m['id'],
          'title': m['title'],
          'summary': m['summary'],
          'lat': m['lat'],
          'lon': m['lon'],
          'end_time': m['end_time'],
          'demand_score': m['demand_score'],
          'reasons': m['reasons'] ?? [],
          'distance_km': m['distance_km'],
          'worth_it_score': m['worth_it_score'],
          'kind': m['kind'],
          'mode': m['mode'],
          'severity_tier': m['severity_tier'],
          'confidence': m['confidence'],
          'taxi': {
            'level': m['worth_it_score'] > 50
                ? 'high'
                : (m['worth_it_score'] > 20 ? 'medium' : 'low'),
            'places': [],
          }, // Mock place/level for compatibility
        };
        alert['id'] ??= m['id'];

        // The RPC 'get_smart_alerts' already filters for end_time > NOW(),
        // so we can safely consider all returned alerts as active.
        active.add(alert);
        week.add(alert);
        all.add(alert);
      }

      return {
        'alerts': all,
        'active': active,
        'week': week,
        'events': const [],
        'placeStats': _buildPlaceStats(all),
        'demo': demo,
        'updatedAt': now.millisecondsSinceEpoch,
        'source': 'trafiklab',
      };
    } on PostgrestException catch (e) {
      // Some environments are not provisioned with the alerts table yet.
      if (e.code == 'PGRST205' && e.message.contains("public.alerts")) {
        debugPrint(
          'ApiClient[taxi.alerts] alerts table missing, returning empty alerts.',
        );
        return {
          'alerts': const [],
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

  Future<Map<String, dynamic>> health() async => {
    'ok': true,
    'backend': 'supabase',
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
    try {
      final res = await _invokeFunction(
        'update-subscription-quantity',
        body: {'seats': seats},
      );
      return {'quantity': seats, 'synced': res['synced'] == true};
    } catch (_) {
      return {'quantity': seats, 'synced': false};
    }
  }

  Future<Map<String, dynamic>> listMembers() async {
    await ensureInitialized();
    final meData = await me();
    final company = meData['company'] as Map<String, dynamic>?;
    if (company == null) return {'members': []};
    final rows = await _sb
        .from('company_members')
        .select('role, status, user:profiles(id, email, name)')
        .eq('company_id', company['id']);
    return {'members': rows};
  }

  Future<Map<String, dynamic>> addMember({
    required String email,
    String name = '',
    String role = 'company_admin',
  }) async {
    throw ApiException(
      501,
      'Bjud in medlem via Supabase Auth invite (edge) — använd Studio tills vidare',
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
