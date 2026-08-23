/// Native apps: Analytics is disclosed in privacy policy.
/// No cookie banner; collection on until we add an in-app toggle.
Future<bool> analyticsConsentGranted() async => true;

void listenAnalyticsConsentChanges(void Function(bool granted) onChange) {
  // No-op on IO platforms.
}
