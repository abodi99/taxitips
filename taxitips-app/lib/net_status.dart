import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'api_client.dart' show ApiException;

/// Nätverksfel på ett ställe.
///
/// Varför: SocketException, TimeoutException, ClientException och
/// HandshakeException läckte som råtext ("Connection failed (OS Error: ...)")
/// i rutor som var menade för föraren, och "inget nät" såg ibland ut som "inga
/// störningar" eller "ingen åtkomst". En tunnel är inte ett fel i kontot.
///
/// Skiljer tre nätfel från riktiga serverfel:
/// * [NetFailure.offline]     -- telefonen når inget nät alls.
/// * [NetFailure.unreachable] -- nät finns, men servern svarar inte.
/// * [NetFailure.timeout]     -- svaret kom aldrig i tid (dålig täckning).
/// Serverfel med ett eget meddelande (4xx/5xx) är INTE nätfel och går
/// oförändrade vidare.
enum NetFailure { offline, unreachable, timeout }

/// `reason` på en [ApiException] som bär ett nätfel. Status är då 0: ingen
/// server har svarat.
const netReasonPrefix = 'net_';

String netReason(NetFailure f) => '$netReasonPrefix${f.name}';

/// Kort, enkel svenska -- förare kan ha begränsad svenska.
String netMessage(NetFailure f) => switch (f) {
  NetFailure.offline => 'Ingen internetanslutning',
  NetFailure.unreachable => 'Servern svarar inte just nu',
  NetFailure.timeout => 'Dålig uppkoppling. Försök igen.',
};

/// Null om felet inte är ett nätfel.
NetFailure? netFailureOf(Object error) {
  if (error is ApiException) {
    final r = error.reason;
    if (r != null && r.startsWith(netReasonPrefix)) {
      for (final f in NetFailure.values) {
        if (r == netReason(f)) return f;
      }
    }
    return null;
  }
  if (error is TimeoutException) return NetFailure.timeout;
  // Typnamn i stället för `is SocketException`: dart:io finns inte på webben,
  // och supabase_flutter har egna undantagstyper för samma sak.
  final type = error.runtimeType.toString();
  final text = error.toString();
  final isNet =
      error is http.ClientException ||
      type == 'SocketException' ||
      type == 'HandshakeException' ||
      type == 'TlsException' ||
      type == 'WebSocketException' ||
      type == 'HttpException' ||
      type == 'AuthRetryableFetchException' ||
      type == '_ClientSocketException';
  if (!isNet) return null;
  final lower = text.toLowerCase();
  const noNetwork = [
    'failed host lookup',
    'network is unreachable',
    'no address associated',
    'nodename nor servname',
    'no route to host',
    'failed to fetch', // webbläsarens fetch utan nät
    'software caused connection abort',
    'internet connection appears to be offline',
  ];
  if (noNetwork.any(lower.contains)) return NetFailure.offline;
  if (lower.contains('timed out') || lower.contains('timeout')) {
    return NetFailure.timeout;
  }
  return NetFailure.unreachable;
}

bool isNetworkError(Object error) => netFailureOf(error) != null;

/// Gör vilket fel som helst till en kort text som är okej att visa.
/// Serverns egna meddelanden (ApiException) behålls; nätfel får sin korta
/// text; allt annat får [fallback] i stället för råa undantagstexten.
String friendlyError(
  Object error, {
  String fallback = 'Något gick fel. Försök igen.',
}) {
  final net = netFailureOf(error);
  if (net != null) return netMessage(net);
  if (error is ApiException) return error.message;
  return fallback;
}

/// För ställen som visar `e.toString()` med prefixet bortrensat: nätfel får
/// sin korta text, allt annat är som förut.
String netAwareText(Object error) {
  final net = netFailureOf(error);
  if (net != null) return netMessage(net);
  return error.toString().replaceFirst(
    RegExp(r'^(ApiException|Exception):\s*'),
    '',
  );
}

/// Gör ett nätfel till en [ApiException] (status 0). Andra fel returneras
/// oförändrade. Används där råa undantag annars skulle passera obearbetade.
Object asApiIfNetwork(Object error) {
  final net = netFailureOf(error);
  if (net == null || error is ApiException) return error;
  debugPrint('Nätfel (${net.name}): $error');
  return ApiException(0, netMessage(net), reason: netReason(net));
}

/// Väntetid före nästa försök när nätet är nere: 4, 8, 16, 32, sedan 60 s.
/// Tak så att batteriet och servern skonas i en lång tunnel.
Duration retryDelay(int attempt) {
  final a = attempt < 0 ? 0 : attempt;
  final seconds = a >= 4 ? 60 : 4 * (1 << a);
  return Duration(seconds: seconds > 60 ? 60 : seconds);
}

/// Klockslag "12:04" för en tidpunkt, lokal tid.
String clockLabel(DateTime t) {
  final l = t.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(l.hour)}:${two(l.minute)}';
}

/// HTTP-klient som gör nätfel till [ApiException] redan vid källan, så att
/// varje skärm som visar `e.toString()` eller `e.message` får en vettig text
/// -- utan att alla 25 anrop i BackendApi behöver ändras.
class NetAwareClient extends http.BaseClient {
  NetAwareClient(this._inner);
  final http.Client _inner;

  /// Strax under BackendApis egen gräns (12 s) så att väntan blir ett
  /// [ApiException] med nättext och inte ett rått TimeoutException.
  static const sendTimeout = Duration(seconds: 11);

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    try {
      return await _inner.send(request).timeout(sendTimeout);
    } catch (e) {
      throw asApiIfNetwork(e);
    }
  }

  @override
  void close() => _inner.close();
}
