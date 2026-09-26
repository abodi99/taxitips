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
        // `message` är fleet-API:ts form, `error` den äldre. Båda finns i
        // produktion just nu.
        body['message']?.toString() ??
            body['error']?.toString() ??
            'Backend svarade ${res.statusCode}',
        reason: body['reason']?.toString(),
        detail: body['detail'] is Map
            ? Map<String, dynamic>.from(body['detail'] as Map)
            : null,
      );
    }
    return body;
  }

  // Senaste flödet och dess ETag för samma anrop (filter + avrundad position).
  // Svarar servern 304 har ingenting ändrats, och det sparade svaret gäller.
  String? _alertsKey;
  String? _alertsEtag;
  Map<String, dynamic>? _alertsBody;

  Future<Map<String, dynamic>> alerts({
    double? lat,
    double? lon,
    bool includeAll = false,
    List<String>? regions,
    List<String>? counties,
    List<String>? municipalities,
    bool roadAll = false,
    String? deviceToken,
    String? accessToken,
  }) async {
    final uri = Uri.parse('$baseUrl/api/alerts').replace(
      queryParameters: {
        if (includeAll) 'all': '1',
        // Väg-läget: alla väghändelser i området, inte bara de 50 närmaste.
        if (roadAll) 'road': 'all',
        if (regions != null && regions.isNotEmpty)
          'regions': (List<String>.from(regions)..sort()).join(','),
        if (counties != null && counties.isNotEmpty)
          'counties': (List<String>.from(counties)..sort()).join(','),
        if (municipalities != null && municipalities.isNotEmpty)
          'municipalities': (List<String>.from(municipalities)..sort()).join(','),
      },
    );
    // Positionen går i en header, avrundad till två decimaler (ungefär en
    // kilometer). I URL:en hamnar den i åtkomstloggar hos varje proxy på vägen.
    final position = (lat != null && lon != null)
        ? '${lat.toStringAsFixed(2)},${lon.toStringAsFixed(2)}'
        : null;
    final key = '$uri|${position ?? ''}';
    final res = await _client
        .get(
          uri,
          headers: {
            ..._headers(deviceToken: deviceToken, accessToken: accessToken),
            'X-TT-Position': ?position,
            if (key == _alertsKey && _alertsEtag != null)
              'If-None-Match': _alertsEtag!,
          },
        )
        .timeout(_timeout);
    if (res.statusCode == 304 && key == _alertsKey && _alertsBody != null) {
      return _alertsBody!;
    }
    final body = await _decode(res, 'alerts');
    _alertsKey = key;
    _alertsEtag = res.headers['etag'];
    _alertsBody = body;
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

  /// Förarens sparade tips. Skickas ALLTID av backend, oavsett filter,
  /// marknadsradie eller om störningen hunnit ta slut -- se
  /// core/api.py:_favorites_for. Appen behöver därför inte gissa vilka som
  /// föll bort ur `alerts` och varför.
  Future<Map<String, dynamic>> favorites({
    double? lat,
    double? lon,
    String? deviceToken,
    String? accessToken,
  }) async {
    final uri = Uri.parse('$baseUrl/api/favorites').replace(
      queryParameters: {
        if (lat != null) 'lat': '$lat',
        if (lon != null) 'lon': '$lon',
      },
    );
    final res = await _client
        .get(
          uri,
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
        )
        .timeout(_timeout);
    return _decode(res, 'favorites');
  }

  /// Sparar eller tar bort en favorit. `favorite: false` tar bort.
  Future<Map<String, dynamic>> setFavorite({
    required String opportunityId,
    required bool favorite,
    String? note,
    String? deviceToken,
    String? accessToken,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/favorites'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
          body: jsonEncode({
            'opportunity_id': opportunityId,
            'favorite': favorite,
            'note': ?note,
          }),
        )
        .timeout(_timeout);
    return _decode(res, 'setFavorite');
  }

  /// Notiserna den HÄR enheten faktiskt fått -- läst ur push_delivery, inte
  /// framräknad på nytt. En lista över "vad du borde ha fått" hade ändrats
  /// retroaktivt varje gång ett reglage rördes.
  Future<Map<String, dynamic>> notifications({
    String? deviceToken,
    String? accessToken,
  }) async {
    final res = await _client
        .get(
          Uri.parse('$baseUrl/api/notifications'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
        )
        .timeout(_timeout);
    return _decode(res, 'notifications');
  }

  Future<Map<String, dynamic>> notifyPrefs({
    String? deviceToken,
    String? accessToken,
  }) async {
    final res = await _client
        .get(
          Uri.parse('$baseUrl/api/notify-prefs'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
        )
        .timeout(_timeout);
    return _decode(res, 'notifyPrefs');
  }

  Future<Map<String, dynamic>> saveNotifyPrefs({
    bool? enabled,
    List<String>? regions,
    List<String>? counties,
    List<String>? municipalities,
    List<String>? cities,
    Map<String, bool>? types,
    Map<String, bool>? categories,
    String? minLevel,
    double? pauseHours,
    String? deviceToken,
    String? accessToken,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/notify-prefs'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
          body: jsonEncode({
            'enabled': ?enabled,
            'regions': ?regions,
            'counties': ?counties,
            'municipalities': ?municipalities,
            'cities': ?cities,
            'types': ?types,
            'categories': ?categories,
            'minLevel': ?minLevel,
            'pauseHours': ?pauseHours,
          }),
        )
        .timeout(_timeout);
    return _decode(res, 'saveNotifyPrefs');
  }

  /// "I tjänst" på eller av. Positionen går i headern, avrundad som för
  /// flödet; servern sparar bara rutan (ungefär 5 km) i 30 minuter och svarar
  /// aldrig med den. Se core/presence.py.
  Future<Map<String, dynamic>> setPresence({
    required bool on,
    double? lat,
    double? lon,
    String? deviceToken,
    String? accessToken,
  }) async {
    final position = (on && lat != null && lon != null)
        ? '${lat.toStringAsFixed(2)},${lon.toStringAsFixed(2)}'
        : null;
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/presence'),
          headers: {
            ..._headers(deviceToken: deviceToken, accessToken: accessToken),
            'X-TT-Position': ?position,
          },
          body: jsonEncode({'on': on}),
        )
        .timeout(_timeout);
    return _decode(res, 'setPresence');
  }

  String? _position(double? lat, double? lon) => (lat != null && lon != null)
      ? '${lat.toStringAsFixed(2)},${lon.toStringAsFixed(2)}'
      : null;

  Map<String, String> _areaQuery(List<String>? counties, List<String>? municipalities) => {
    if (counties != null && counties.isNotEmpty)
      'counties': (List<String>.from(counties)..sort()).join(','),
    if (municipalities != null && municipalities.isNotEmpty)
      'municipalities': (List<String>.from(municipalities)..sort()).join(','),
  };

  /// Färjor på väg in, som lägger till eller ligger vid kaj i förarens område.
  /// Positionen går i headern, som för flödet. Se maritime/views.py.
  Future<Map<String, dynamic>> ferries({
    double? lat,
    double? lon,
    List<String>? counties,
    List<String>? municipalities,
    String? deviceToken,
    String? accessToken,
  }) async {
    final uri = Uri.parse('$baseUrl/api/ferries')
        .replace(queryParameters: _areaQuery(counties, municipalities));
    final res = await _client
        .get(
          uri,
          headers: {
            ..._headers(deviceToken: deviceToken, accessToken: accessToken),
            'X-TT-Position': ?_position(lat, lon),
          },
        )
        .timeout(_timeout);
    return _decode(res, 'ferries');
  }

  /// Kommande evenemang i förarens område. Se events/api.py.
  Future<Map<String, dynamic>> events({
    double? lat,
    double? lon,
    List<String>? counties,
    List<String>? municipalities,
    int days = 14,
    String? from,
    String? to,
    String? deviceToken,
    String? accessToken,
  }) async {
    // En dag eller period (YYYY-MM-DD) när den finns, annars `days` från i dag.
    final uri = Uri.parse('$baseUrl/api/events').replace(queryParameters: {
      if (from != null) 'from': from else 'days': '$days',
      'to': ?to,
      ..._areaQuery(counties, municipalities),
    });
    final res = await _client
        .get(
          uri,
          headers: {
            ..._headers(deviceToken: deviceToken, accessToken: accessToken),
            'X-TT-Position': ?_position(lat, lon),
          },
        )
        .timeout(_timeout);
    return _decode(res, 'events');
  }

  Future<Map<String, dynamic>> config() async {
    final res = await _client
        .get(Uri.parse('$baseUrl/api/config'), headers: _headers())
        .timeout(_timeout);
    return _decode(res, 'config');
  }

  Future<Map<String, dynamic>> deviceSession({
    required String installationId,
    String? pushToken,
    String? label,
    String? platform,
    String? deviceToken,
    String? accessToken,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/device/session'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
          body: jsonEncode({
            'installation_id': installationId,
            'push_token': ?pushToken,
            'label': ?label,
            'platform': ?platform,
          }),
        )
        .timeout(_timeout);
    return _decode(res, 'deviceSession');
  }

  // --- Kundlivscykeln: parkoppling, bilval och skiftbyte -------------------
  //
  // Förarens tre vägar mot /api/fleet/. De bär `X-Device-Token` (utom `pair`,
  // som är det anrop som SKAPAR den) och svarar med samma form som resten av
  // API:t: `ok` plus ett maskinläsbart `reason` och ett svenskt `message` vid
  // ett nej.

  /// Löser in administratörens engångskod. Svarar med hemligheten EN gång --
  /// anroparen måste lägga den i säker lagring direkt (se DeviceCredentialStore).
  Future<Map<String, dynamic>> pair({
    required String code,
    required String installationId,
    String? label,
    String? platform,
    String? pushToken,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/fleet/pair'),
          headers: _headers(),
          body: jsonEncode({
            'code': code,
            'installation_id': installationId,
            'label': ?label,
            'platform': ?platform,
            'push_token': ?pushToken,
          }),
        )
        .timeout(_timeout);
    return _decode(res, 'pair');
  }

  /// Vad den här telefonen får: godkända bilar, vem som har dem just nu, och
  /// vilken bil telefonen själv kör.
  Future<Map<String, dynamic>> fleetStatus({String? deviceToken}) async {
    final res = await _client
        .get(
          Uri.parse('$baseUrl/api/fleet/me'),
          headers: _headers(deviceToken: deviceToken),
        )
        .timeout(_timeout);
    return _decode(res, 'fleetStatus');
  }

  /// Tar bilen. Utan `force` svarar servern `takeover_required` när någon
  /// annan har den -- appen frågar då föraren, och `force: true` är svaret på
  /// den frågan, inte ett sätt att hoppa över den.
  Future<Map<String, dynamic>> startVehicleSession({
    required String licenseId,
    required String deviceToken,
    bool force = false,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/fleet/session'),
          headers: _headers(deviceToken: deviceToken),
          body: jsonEncode({'license_id': licenseId, 'force': force}),
        )
        .timeout(_timeout);
    return _decode(res, 'startVehicleSession');
  }

  Future<Map<String, dynamic>> endVehicleSession({
    required String deviceToken,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/fleet/session/end'),
          headers: _headers(deviceToken: deviceToken),
          body: jsonEncode(const {}),
        )
        .timeout(_timeout);
    return _decode(res, 'endVehicleSession');
  }

  /// Bolagskoden. Skapar en ANSÖKAN -- ingen token, ingen åtkomst.
  Future<Map<String, dynamic>> joinRequest({
    required String joinCode,
    required String installationId,
    String? label,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/fleet/join-request'),
          headers: _headers(),
          body: jsonEncode({
            'join_code': joinCode,
            'installation_id': installationId,
            'label': ?label,
          }),
        )
        .timeout(_timeout);
    return _decode(res, 'joinRequest');
  }

  // Ägarens vägar mot /api/fleet/ (företagsöversikt, registrering, provbilar,
  // förarkoder). De bär Supabase-inloggningen, aldrig en förartoken: en
  // förartelefon ger ingen administrativ behörighet (fleet/access.py).
  Future<Map<String, dynamic>> ownerGet(
    String path, {
    required String accessToken,
  }) async {
    final res = await _client
        .get(
          Uri.parse('$baseUrl/api/fleet/$path'),
          headers: _headers(accessToken: accessToken),
        )
        .timeout(_timeout);
    return _decode(res, path);
  }

  Future<Map<String, dynamic>> ownerPost(
    String path,
    Map<String, dynamic> body, {
    required String accessToken,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/fleet/$path'),
          headers: _headers(accessToken: accessToken),
          body: jsonEncode(body),
        )
        .timeout(_timeout);
    return _decode(res, path);
  }

  // Supportchatten (/api/support). Båda bevisen följer med: servern väljer
  // kontot om appen är inloggad, annars telefonen (fleet/support.py).

  /// Konversationen. `markRead` när chatten visas: då är svaren lästa.
  Future<Map<String, dynamic>> supportConversation({
    String? deviceToken,
    String? accessToken,
    bool markRead = false,
  }) async {
    final res = await _client
        .get(
          Uri.parse('$baseUrl/api/support${markRead ? '?markRead=1' : ''}'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
        )
        .timeout(_timeout);
    return _decode(res, 'supportConversation');
  }

  Future<Map<String, dynamic>> supportUnread({
    String? deviceToken,
    String? accessToken,
  }) async {
    final res = await _client
        .get(
          Uri.parse('$baseUrl/api/support/unread'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
        )
        .timeout(_timeout);
    return _decode(res, 'supportUnread');
  }

  Future<Map<String, dynamic>> supportSend({
    required String body,
    String? deviceToken,
    String? accessToken,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/support/messages'),
          headers: _headers(deviceToken: deviceToken, accessToken: accessToken),
          body: jsonEncode({'body': body}),
        )
        .timeout(_timeout);
    return _decode(res, 'supportSend');
  }
}
