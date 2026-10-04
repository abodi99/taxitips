import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_client.dart' show ApiException;
import 'client_info.dart';
import 'net_status.dart';

/// POST /api/notify-prefs med de detaljerade valen: färdigt läge (`preset`),
/// svagare tips (`weak`), tysta timmar (`quietHours`, null = inga) och tak per
/// timme (`maxPerHour`, null = inget). Reglerna och valideringen bor på
/// servern (core/notify_prefs.py); appen skickar bara det föraren valt.
///
/// En egen liten väg i stället för fler parametrar på
/// `BackendApi.saveNotifyPrefs`: null betyder där "skicka inte", men här
/// betyder null "ta bort" -- och en karta skickar exakt det som står i den.
/// Samma rubriker som BackendApi (appversion, förartoken, inloggning).
Future<Map<String, dynamic>> postNotifyRules({
  required String baseUrl,
  required Map<String, dynamic> body,
  String? deviceToken,
  String? accessToken,
  http.Client? client,
}) async {
  final c = client ?? NetAwareClient(http.Client());
  try {
    final res = await c
        .post(
          Uri.parse(
            '${baseUrl.replaceAll(RegExp(r'/+$'), '')}/api/notify-prefs',
          ),
          headers: {
            ...ClientInfo.headers,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            if (deviceToken != null && deviceToken.isNotEmpty)
              'X-Device-Token': deviceToken,
            if (accessToken != null && accessToken.isNotEmpty)
              'Authorization': 'Bearer $accessToken',
          },
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 12));
    Map<String, dynamic> decoded;
    try {
      decoded = Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {
      throw ApiException(
        res.statusCode,
        res.statusCode >= 502 && res.statusCode <= 504
            ? netMessage(NetFailure.unreachable)
            : 'Ogiltigt svar från servern',
      );
    }
    if (res.statusCode >= 400) {
      throw ApiException(
        res.statusCode,
        decoded['message']?.toString() ??
            decoded['error']?.toString() ??
            'Servern svarade ${res.statusCode}',
        reason: decoded['reason']?.toString(),
      );
    }
    return decoded;
  } finally {
    if (client == null) c.close();
  }
}
