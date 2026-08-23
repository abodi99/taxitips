import 'dart:io' show Platform;

String pushPlatformName() {
  if (Platform.isIOS) return 'ios';
  if (Platform.isAndroid) return 'android';
  return 'unknown';
}
