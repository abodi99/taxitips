import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'config.dart';

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
    if (Supabase.instance.isInitialized) return;
    await Supabase.initialize(url: supabaseUrl, anonKey: supabaseAnonKey);
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
    await ensureInitialized();
    final res = await _sb.auth.signInWithPassword(
      email: email,
      password: password,
    );
    await saveSession(res.session?.accessToken);
    await saveCredentials(email, password);
    return me();
  }

  Future<void> logout() async {
    try {
      if (Supabase.instance.isInitialized) await _sb.auth.signOut();
    } catch (_) {}
    await saveSession(null);
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
    return me();
  }

  String _randomJoinCode() {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    final rnd = Random();
    return List.generate(6, (_) => chars[rnd.nextInt(chars.length)]).join();
  }

  Future<Map<String, dynamic>> me() async {
    await ensureInitialized();
    final user = _sb.auth.currentUser;
    if (user == null) throw ApiException(401, 'Inte inloggad');

    final profile = await _sb
        .from('profiles')
        .select()
        .eq('id', user.id)
        .maybeSingle();
    final memberships = await _sb
        .from('company_members')
        .select('role, status, company:companies(*)')
        .eq('user_id', user.id)
        .eq('status', 'active');

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
  }

  Future<Map<String, dynamic>> entitlements() async => {'ok': true};
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
    final meDev = await getDeviceMe();
    await _sb.from('devices').update({'label': label}).eq('id', meDev['id']);
    return {'label': label};
  }

  Future<Map<String, dynamic>> taxi({bool demo = false}) async {
    await ensureInitialized();
    final rows = await _sb
        .from('alerts')
        .select()
        .order('updated_at', ascending: false)
        .limit(200);
    final alerts = (rows as List).map((r) {
      final m = Map<String, dynamic>.from(r as Map);
      final payload = m['payload'];
      if (payload is Map) return Map<String, dynamic>.from(payload);
      return {
        'id': m['id'],
        'kind': m['kind'],
        'level': m['level'],
        'title': m['title'],
        'summary': m['summary'],
        'lat': m['lat'],
        'lon': m['lon'],
        'taxi': {'level': m['level'], 'places': m['places'] ?? []},
      };
    }).toList();
    return {'alerts': alerts, 'demo': demo};
  }

  Future<Map<String, dynamic>> health() async => {
    'ok': true,
    'backend': 'supabase',
  };

  Future<Map<String, dynamic>> billingPortal() async {
    throw ApiException(
      501,
      'Stripe portal via worker Edge Function — kommer snart',
    );
  }

  Future<Map<String, dynamic>> updateBillingQuantity(int seats) async {
    final meData = await me();
    final company = meData['company'] as Map<String, dynamic>?;
    if (company == null) throw ApiException(400, 'Inget bolag');
    await _sb
        .from('companies')
        .update({'seats': seats})
        .eq('id', company['id']);
    return {'seats': seats};
  }

  Future<Map<String, dynamic>> listMembers() async {
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
