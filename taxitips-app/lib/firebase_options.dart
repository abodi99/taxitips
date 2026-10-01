// File generated for Firebase project taxitips-se.
// Ignore for file: type=lint
import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart'
    show defaultTargetPlatform, kIsWeb, TargetPlatform;

/// Default [FirebaseOptions] for use with your Firebase apps.
class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    if (kIsWeb) {
      return web;
    }
    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return android;
      case TargetPlatform.iOS:
        return ios;
      case TargetPlatform.macOS:
        return ios;
      default:
        throw UnsupportedError(
          'DefaultFirebaseOptions are not supported for this platform.',
        );
    }
  }

  static const FirebaseOptions web = FirebaseOptions(
    apiKey: 'AIzaSyC8EoR1vv95zfhlnMwIDsnfMikUPh4d1pU',
    appId: '1:1015418824161:web:a8462870b4b2801e859ea0',
    messagingSenderId: '1015418824161',
    projectId: 'taxitips-se',
    authDomain: 'taxitips-se.firebaseapp.com',
    storageBucket: 'taxitips-se.firebasestorage.app',
  );

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'AIzaSyB_7X6J4EhjetJbHsmAdR9kX6_uTT2c7_E',
    appId: '1:1015418824161:android:72ff9fd1ca7234ef859ea0',
    messagingSenderId: '1015418824161',
    projectId: 'taxitips-se',
    storageBucket: 'taxitips-se.firebasestorage.app',
  );

  static const FirebaseOptions ios = FirebaseOptions(
    apiKey: 'AIzaSyDAdOXQP1L1CZw42owaTcytUMaM8ETXQBw',
    appId: '1:1015418824161:ios:6fa297c7276b6d41859ea0',
    messagingSenderId: '1015418824161',
    projectId: 'taxitips-se',
    storageBucket: 'taxitips-se.firebasestorage.app',
    iosBundleId: 'se.taxitips.app',
  );
}
