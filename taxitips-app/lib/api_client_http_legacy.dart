import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiClient {
  ApiClient({String? baseUrl})
    : baseUrl =
          baseUrl ??
          const String.fromEnvironment(
            'API_BASE',
            defaultValue: 'http://localhost:3847',
          );

  final String baseUrl;
  String? sessionToken;
  String? deviceToken;

  static const _sessionKey = 'tb_session';
  static const _deviceKey = 'tb_device';

  Future<void> loadTokens() async {
    final prefs = await SharedPreferences.getInstance();
    sessionToken = prefs.getString(_sessionKey);
    deviceToken = prefs.getString(_deviceKey);
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

  Map<String, String> _headers({bool json = true}) {
    final h = <String, String>{};
    if (json) h['Content-Type'] = 'application/json';
    if (sessionToken != null && sessionToken!.isNotEmpty) {
      h['Authorization'] = 'Bearer $sessionToken';
    }
    if (deviceToken != null && deviceToken!.isNotEmpty) {
      h['X-Device-Token'] = deviceToken!;
    }
    return h;
  }

  Uri _u(String path, [Map<String, String>? query]) {
    final uri = Uri.parse('$baseUrl$path');
    if (query == null || query.isEmpty) return uri;
    return uri.replace(queryParameters: query);
  }

  Future<Map<String, dynamic>> _decode(http.Response res) async {
    final body = res.body.isEmpty ? <String, dynamic>{} : jsonDecode(res.body);
    if (body is! Map<String, dynamic>) {
      throw ApiException(res.statusCode, 'Ogiltigt svar');
    }
    if (res.statusCode >= 400) {
      throw ApiException(
        res.statusCode,
        body['error']?.toString() ?? 'Fel ${res.statusCode}',
      );
    }
    return body;
  }

  Future<Map<String, dynamic>> signup({
    required String name,
    required String email,
    required String password,
    required String orgNumber,
    int seats = 1,
    bool startCheckout = true,
    String? successUrl,
    String? cancelUrl,
  }) async {
    final res = await http.post(
      _u('/api/signup'),
      headers: _headers(),
      body: jsonEncode({
        'name': name,
        'email': email,
        'password': password,
        'seats': seats,
        'orgNumber': orgNumber,
        'startCheckout': startCheckout,
        'successUrl': ?successUrl,
        'cancelUrl': ?cancelUrl,
      }),
    );
    final data = await _decode(res);
    await saveSession(data['token'] as String?);
    return data;
  }

  Future<Map<String, dynamic>> lookupCompany(String orgNumber) async {
    final res = await http.get(
      _u('/api/company/lookup', {'orgNumber': orgNumber}),
      headers: _headers(json: false),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> pricing() async {
    final res = await http.get(
      _u('/api/pricing'),
      headers: _headers(json: false),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> checkout({int? seats}) async {
    final res = await http.post(
      _u('/api/checkout'),
      headers: _headers(),
      body: jsonEncode({'seats': ?seats}),
    );
    return _decode(res);
  }

  static const _emailKey = 'tb_last_email';
  static const _passwordKey = 'tb_last_password';

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

  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    final res = await http.post(
      _u('/api/login'),
      headers: _headers(),
      body: jsonEncode({'email': email, 'password': password}),
    );
    final data = await _decode(res);
    await saveSession(data['token'] as String?);
    await saveCredentials(email, password);
    return data;
  }

  Future<void> logout() async {
    try {
      await http.post(_u('/api/logout'), headers: _headers());
    } catch (_) {}
    await saveSession(null);
  }

  Future<void> clearDevice() async {
    await saveDevice(null);
  }

  Future<void> leaveAll() async {
    await logout();
    await clearDevice();
  }

  Future<Map<String, dynamic>> me() async {
    final res = await http.get(_u('/api/me'), headers: _headers());
    return _decode(res);
  }

  Future<Map<String, dynamic>> entitlements() async {
    final res = await http.get(
      _u('/api/me/entitlements'),
      headers: _headers(json: false),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> publicConfig() async {
    final res = await http.get(
      _u('/api/config/public'),
      headers: _headers(json: false),
    );
    return _decode(res);
  }

  /// Localhost API only — returns owner email/password for QA autofill.
  Future<({String? email, String? password})> loadDevTestLogin() async {
    try {
      final res = await http.get(
        _u('/api/dev/test-login'),
        headers: _headers(json: false),
      );
      if (res.statusCode != 200) return (email: null, password: null);
      final data = await _decode(res);
      return (
        email: data['email'] as String?,
        password: data['password'] as String?,
      );
    } catch (_) {
      return (email: null, password: null);
    }
  }

  Future<Map<String, dynamic>> getAreas() async {
    final res = await http.get(_u('/api/company/areas'), headers: _headers());
    return _decode(res);
  }

  Future<Map<String, dynamic>> saveAreas(List<String> areas) async {
    final res = await http.patch(
      _u('/api/company/areas'),
      headers: _headers(),
      body: jsonEncode({'watchedAreas': areas}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> regenerateJoinCode() async {
    final res = await http.post(
      _u('/api/company/join-code/regenerate'),
      headers: _headers(),
      body: '{}',
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> joinWithCode({
    required String joinCode,
    String label = 'Förare',
    String kind = 'driver',
  }) async {
    final res = await http.post(
      _u('/api/devices/join'),
      headers: _headers(),
      body: jsonEncode({'joinCode': joinCode, 'label': label, 'kind': kind}),
    );
    final data = await _decode(res);
    await saveDevice(data['token'] as String?);
    return data;
  }

  Future<Map<String, dynamic>> createTransferCode(String deviceId) async {
    final res = await http.post(
      _u('/api/devices/$deviceId/transfer-code'),
      headers: _headers(),
      body: '{}',
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> transferWithCode({
    required String transferCode,
    String? label,
  }) async {
    final res = await http.post(
      _u('/api/devices/transfer'),
      headers: _headers(),
      body: jsonEncode({
        'transferCode': transferCode,
        if (label != null && label.isNotEmpty) 'label': label,
      }),
    );
    final data = await _decode(res);
    await saveDevice(data['token'] as String?);
    return data;
  }

  Future<void> deleteDevice(String id) async {
    final res = await http.delete(_u('/api/devices/$id'), headers: _headers());
    await _decode(res);
  }

  Future<Map<String, dynamic>> claimInvite(String token) async {
    final res = await http.post(
      _u('/api/devices/claim'),
      headers: _headers(),
      body: jsonEncode({'token': token}),
    );
    final data = await _decode(res);
    await saveDevice(data['token'] as String?);
    return data;
  }

  Future<Map<String, dynamic>> registerPushToken({
    required String fcmToken,
    String platform = 'web',
  }) async {
    final res = await http.post(
      _u('/api/devices/push-token'),
      headers: _headers(),
      body: jsonEncode({'fcmToken': fcmToken, 'platform': platform}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> getNotifyPrefs() async {
    final res = await http.get(
      _u('/api/devices/me/notify-prefs'),
      headers: _headers(json: false),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> saveNotifyPrefs({
    bool? enabled,
    List<String>? cities,
    Map<String, bool>? types,
  }) async {
    final res = await http.patch(
      _u('/api/devices/me/notify-prefs'),
      headers: _headers(),
      body: jsonEncode({
        'enabled': ?enabled,
        'cities': ?cities,
        'types': ?types,
      }),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> updateCompanyProfile({
    String? name,
    String? orgNumber,
  }) async {
    final res = await http.patch(
      _u('/api/company/profile'),
      headers: _headers(),
      body: jsonEncode({'name': ?name, 'orgNumber': ?orgNumber}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> changeEmail({
    required String currentPassword,
    required String newEmail,
  }) async {
    final res = await http.patch(
      _u('/api/account/email'),
      headers: _headers(),
      body: jsonEncode({
        'currentPassword': currentPassword,
        'newEmail': newEmail,
      }),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final res = await http.patch(
      _u('/api/account/password'),
      headers: _headers(),
      body: jsonEncode({
        'currentPassword': currentPassword,
        'newPassword': newPassword,
      }),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> getDeviceMe() async {
    final res = await http.get(
      _u('/api/devices/me'),
      headers: _headers(json: false),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> updateDeviceLabel(String label) async {
    final res = await http.patch(
      _u('/api/devices/me'),
      headers: _headers(),
      body: jsonEncode({'label': label}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> taxi({bool demo = false}) async {
    final res = await http.get(
      _u('/api/taxi', demo ? {'demo': '1'} : null),
      headers: _headers(),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> health() async {
    final res = await http.get(
      _u('/api/health'),
      headers: _headers(json: false),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> billingPortal() async {
    final res = await http.post(
      _u('/api/billing/portal'),
      headers: _headers(),
      body: '{}',
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> updateBillingQuantity(int seats) async {
    final res = await http.post(
      _u('/api/billing/quantity'),
      headers: _headers(),
      body: jsonEncode({'seats': seats}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> listMembers() async {
    final res = await http.get(
      _u('/api/company/members'),
      headers: _headers(json: false),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> addMember({
    required String email,
    String name = '',
    String role = 'company_admin',
  }) async {
    final res = await http.post(
      _u('/api/company/members'),
      headers: _headers(),
      body: jsonEncode({'email': email, 'name': name, 'role': role}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> removeMember(String userId) async {
    final res = await http.delete(
      _u('/api/company/members/$userId'),
      headers: _headers(),
    );
    return _decode(res);
  }
}

class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status;
  final String message;

  @override
  String toString() => message;
}
