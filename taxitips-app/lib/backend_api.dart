import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'api_client.dart' show ApiException;
import 'config.dart';

/// Klienten mot taxitips-backend (Django) -- tipsflödet, förklaringen och
/// feedbacken.
///
/// Varför en väg till: bedömningen som ligger bakom varje kort räknades
/// tidigare ut på tre ställen. Poängen i Python (pipelinen), urvalet och
/// avståndet i plpgsql (`get_smart_alerts`, omdefinierad sju gånger), och
/// nivågränserna i Dart. Django-API:t svarar med samma fältnamn som RPC:n
/// gjorde -- `worth_it_score`, `is_active`, `distance_km` -- plus det som
/// pipelinen redan räknat ut men RPC:n aldrig exponerade (`level`,
/// `compensation_*`). Kortet, kartan och sorteringen behövde därför inte
/// skrivas om för att byta väg.
///
/// Auth följer med i varje anrop: förarens `X-Device-Token`, och ägarens
/// Supabase-JWT när en sådan finns. Backendens entitlement-kontroll
/// (core/entitlement.py) godtar båda, precis som SQL-funktionen gjorde.
class BackendApi {
  BackendApi({String? baseUrl, http.Client? client})
    : baseUrl = (baseUrl ?? TaxiTipsConfig.apiBaseUrl).replaceAll(
        RegExp(r'/+$'),
        '',
      ),
      // Injicerbar med avsikt: annars går den här klassen bara att prova
      // mot en riktig server, och headern som bär förarens token är just
      // det som tyst kan sluta skickas.
      _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  /// Ett API-anrop får inte hänga kvar längre än en förare orkar vänta vid
  /// ratten. Misslyckas det faller ApiClient tillbaka på Supabase-vägen.
  static const _timeout = Duration(seconds: 12);

  Map<String, String> _headers({String? deviceToken, String? accessToken}) => {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    if (deviceToken != null && deviceToken.isNotEmpty)
      'X-Device-Token': deviceToken,
    if (accessToken != null && accessToken.isNotEmpty)
      'Authorization': 'Bearer $accessToken',
  };

  Future<Map<String, dynamic>> _decode(http.Response res, String op) async {
    Map<String, dynamic> body;
    try {
      body = Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {
      throw ApiException(res.statusCode, 'Ogiltigt svar från backend ($op)');
    }
    if (res.statusCode >= 400) {
      throw ApiException(
        res.statusCode,
        body['error']?.toString() ?? 'Backend svarade ${res.statusCode}',
      );
    }
    return body;
  }

  Future<Map<String, dynamic>> alerts({
    double? lat,
    double? lon,
    String? deviceToken,
    String? accessToken,
  }) async {
    final uri = Uri.parse('$baseUrl/api/alerts').replace(
      queryParameters: {
        if (lat != null) 'lat': '$lat',
        if (lon != null) 'lon': '$lon',
      },
    );
    final res = await _client
        .get(uri, headers: _headers(deviceToken: deviceToken, accessToken: accessToken))
        .timeout(_timeout);
    final body = await _decode(res, 'alerts');
    // `entitled: false` är inte ett fel -- det är svaret "du ser inga tips,
    // och här är varför". Loggas, men bubblar inte upp som en krasch: en
    // förare som inte hunnit få sitt bolag aktiverat ska se en tom lista,
    // inte en röd ruta.
    if (body['entitled'] == false) {
      debugPrint('BackendApi[alerts] ej berättigad: ${body['reason']}');
    }
    return body;
  }

  Future<Map<String, dynamic>> opportunityDetail(
    String opportunityId, {
    String? deviceToken,
    String? accessToken,
  }) async {
    final res = await _client
        .get(
          Uri.parse('$baseUrl/api/opportunities/$opportunityId'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
        )
        .timeout(_timeout);
    return _decode(res, 'opportunityDetail');
  }

  /// `verdict`: heading (🚕), fare (👍) eller empty (👎).
  Future<Map<String, dynamic>> submitFeedback({
    required String opportunityId,
    required String verdict,
    String? deviceToken,
    String? accessToken,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/feedback'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
          body: jsonEncode({
            'opportunity_id': opportunityId,
            'verdict': verdict,
          }),
        )
        .timeout(_timeout);
    return _decode(res, 'feedback');
  }

  Future<Map<String, dynamic>> config() async {
    final res = await _client
        .get(Uri.parse('$baseUrl/api/config'), headers: _headers())
        .timeout(_timeout);
    return _decode(res, 'config');
  }
}
