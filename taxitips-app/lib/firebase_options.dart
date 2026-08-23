// File generated for Firebase project taxibehov.
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
    apiKey: 'AIzaSyDoKaLhJptAWUpbw2vh1pJ61YRb7kau2zU',
    appId: '1:963263574599:web:f8fffff4809589607f7762',
    messagingSenderId: '963263574599',
    projectId: 'taxibehov',
    authDomain: 'taxibehov.firebaseapp.com',
    storageBucket: 'taxibehov.firebasestorage.app',
    measurementId: 'G-6ZWTCYKFKS',
  );

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'AIzaSyBcaBKtr2sqEtx9kYtHbAJOw7zaVx0ZtCQ',
    appId: '1:963263574599:android:18f6a9e821aac3e17f7762',
    messagingSenderId: '963263574599',
    projectId: 'taxibehov',
    storageBucket: 'taxibehov.firebasestorage.app',
  );

  static const FirebaseOptions ios = FirebaseOptions(
    apiKey: 'AIzaSyBEkRxD9Vw4GEFuc-TYzTFG1hymtnZwQHE',
    appId: '1:963263574599:ios:64ba2ead7f4db6b77f7762',
    messagingSenderId: '963263574599',
    projectId: 'taxibehov',
    storageBucket: 'taxibehov.firebasestorage.app',
    iosBundleId: 'se.taxibehov.taxibehovApp',
  );
}
