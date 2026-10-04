import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/api_client.dart';

/// Det som måste stämma i butiksbygget och som ingen märker förrän granskningen
/// (eller en användare) gör det: inga inlagda konton, rätt behörigheter, push
/// på iPhone och länkar som fungerar. docs/release-checklist.md förklarar varför.
void main() {
  String read(String path) => File(path).readAsStringSync();

  test('inga inlagda konton eller lösenord i appens kod', () {
    final hits = <String>[];
    for (final entity in Directory('lib').listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final lines = entity.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        final line = lines[i];
        if (line.trimLeft().startsWith('//')) continue;
        // Ett standardvärde med en e-postadress, eller testlösenordet ur
        // seed_local_demo, följer med i varje byggd app.
        if (RegExp(r"defaultValue:\s*'[^']*@").hasMatch(line) ||
            line.contains('taxitips123')) {
          hits.add('${entity.path}:${i + 1}: ${line.trim()}');
        }
      }
    }
    expect(hits, isEmpty, reason: hits.join('\n'));
  });

  test('integritetspolicy och villkor öppnas på taxitips.se', () {
    // Inte Supabase (api.taxitips.se), som svarar 401 på /privacy.html.
    expect(ApiClient.webUrl, 'https://taxitips.se');
  });

  test('inga köpbibliotek eller inbäddade webbvyer', () {
    final pubspec = read('pubspec.yaml');
    for (final package in [
      'in_app_purchase',
      'purchases_flutter',
      'webview_flutter',
      'flutter_inappwebview',
    ]) {
      expect(pubspec, isNot(contains(package)), reason: package);
    }
  });

  test('inga dubbla bindestreck i XML-kommentarer (bygget fäller dem)', () {
    for (final path in [
      'android/app/src/main/AndroidManifest.xml',
      'android/app/src/main/res/xml/data_extraction_rules.xml',
      'ios/Runner/PrivacyInfo.xcprivacy',
      'ios/Runner/Runner.entitlements',
    ]) {
      for (final comment in RegExp(
        r'<!--(.*?)-->',
        dotAll: true,
      ).allMatches(read(path))) {
        expect(comment.group(1), isNot(contains('--')), reason: path);
      }
    }
  });

  group('Android', () {
    final manifest = read('android/app/src/main/AndroidManifest.xml');

    test('klartext-HTTP bara i debug', () {
      expect(manifest, isNot(contains('usesCleartextTraffic')));
      expect(
        read('android/app/src/debug/AndroidManifest.xml'),
        contains('usesCleartextTraffic="true"'),
      );
    });

    test('behörigheterna appen använder, inget reklam-id', () {
      for (final permission in [
        'android.permission.INTERNET',
        'android.permission.ACCESS_FINE_LOCATION',
        'android.permission.ACCESS_COARSE_LOCATION',
        'android.permission.POST_NOTIFICATIONS',
      ]) {
        expect(manifest, contains(permission), reason: permission);
      }
      expect(
        manifest,
        contains(
          'com.google.android.gms.permission.AD_ID" tools:node="remove"',
        ),
      );
      for (final adPermission in [
        'android.permission.ACCESS_ADSERVICES_AD_ID',
        'android.permission.ACCESS_ADSERVICES_ATTRIBUTION',
      ]) {
        expect(
          manifest,
          contains('$adPermission" tools:node="remove"'),
          reason: adPermission,
        );
      }
      expect(manifest, isNot(contains('BACKGROUND_LOCATION')));
    });

    test('ingen säkerhetskopia av förarens nyckel', () {
      expect(manifest, contains('android:allowBackup="false"'));
      expect(
        File('android/app/src/main/res/xml/data_extraction_rules.xml')
            .existsSync(),
        isTrue,
      );
    });
  });

  group('iOS', () {
    final plist = read('ios/Runner/Info.plist');

    test('platstext, push i bakgrunden och exportdeklarationen', () {
      expect(plist, contains('NSLocationWhenInUseUsageDescription'));
      // geolocator ber om "Alltid" så fort nyckeln finns -- appen behöver
      // bara platsen medan den används.
      expect(plist, isNot(contains('NSLocationAlways')));
      expect(plist, contains('<string>remote-notification</string>'));
      expect(plist, contains('ITSAppUsesNonExemptEncryption'));
    });

    test('lägsta iOS är samma i Podfile och projektet (15.0)', () {
      // 13.0 fick pod install att vägra: google_maps_flutter_ios kräver 14,
      // Firebase 12 kräver 15.
      expect(read('ios/Podfile'), contains("platform :ios, '15.0'"));
      final project = read('ios/Runner.xcodeproj/project.pbxproj');
      expect(project, isNot(contains('IPHONEOS_DEPLOYMENT_TARGET = 13.0;')));
      expect(
        'IPHONEOS_DEPLOYMENT_TARGET = 15.0;'.allMatches(project).length,
        3,
      );
    });

    test('push-rättigheten är kopplad till alla tre byggen', () {
      expect(read('ios/Runner/Runner.entitlements'), contains('aps-environment'));
      final project = read('ios/Runner.xcodeproj/project.pbxproj');
      expect(
        'CODE_SIGN_ENTITLEMENTS = Runner/Runner.entitlements;'
            .allMatches(project)
            .length,
        3,
      );
    });

    test('integritetsmanifestet finns i appen och spårar inte', () {
      final manifest = read('ios/Runner/PrivacyInfo.xcprivacy');
      expect(manifest, contains('<key>NSPrivacyTracking</key>\n\t<false/>'));
      expect(
        read('ios/Runner.xcodeproj/project.pbxproj'),
        contains('PrivacyInfo.xcprivacy in Resources'),
      );
    });
  });
}
