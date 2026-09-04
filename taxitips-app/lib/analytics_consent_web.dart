// ignore_for_file: deprecated_member_use, avoid_web_libraries_in_flutter

import 'dart:convert';
import 'dart:html' as html;

const _key = 'tb_cookie_consent_v1';

Future<bool> analyticsConsentGranted() async {
  try {
    final raw = html.window.localStorage[_key];
    if (raw == null || raw.isEmpty) return false;
    final map = jsonDecode(raw);
    if (map is Map && map['analytics'] == true) return true;
  } catch (_) {}
  return false;
}

void listenAnalyticsConsentChanges(void Function(bool granted) onChange) {
  html.window.addEventListener('tb-cookie-consent', (event) {
    final detail = (event as html.CustomEvent).detail;
    final granted = detail is Map && detail['analytics'] == true;
    onChange(granted);
  });
}
