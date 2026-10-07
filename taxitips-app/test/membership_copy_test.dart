import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:taxitips_app/config.dart';
import 'package:taxitips_app/membership_copy.dart';
import 'package:taxitips_app/signal_kinds.dart';

/// Appen säljer ingenting (Apple 3.1.1/3.1.3(c), Google Play Payments;
/// docs/fleet-abonnemang.md §9c): inga priser, inga köpknappar, inga
/// uppmaningar som leder till ett *köp* utanför butikerna. Admin får en
/// kontohanteringslänk till kundportalen; testerna vaktar skillnaden.
void main() {
  group('membershipNotice', () {
    test('skäl om medlemskap får appens text, aldrig serverns uppmaning', () {
      for (final reason in [
        'trial_ended',
        'period_expired',
        'past_due',
        'canceled',
        'no_subscription',
      ]) {
        final text = membershipNotice(
          reason,
          serverMessage: 'Uppdatera betalmetoden. Kontakta TaxiTips.',
        );
        expect(text, contains(kMembershipOnWeb), reason: reason);
        expect(text, isNot(contains('betalmetoden')), reason: reason);
        expect(text, isNot(contains('Kontakta')), reason: reason);
      }
    });

    test('andra skäl visar serverns text, eller reservtexten', () {
      expect(
        membershipNotice(
          'account_blocked',
          serverMessage: 'Kontot är spärrat.',
        ),
        'Kontot är spärrat.',
      );
      expect(membershipNotice('okänt'), 'Åtkomsten är inte aktiv.');
      expect(membershipNotice('okänt', fallback: ''), '');
    });

    test('texterna är neutrala', () {
      expect(kNotInTrial, 'Ingår inte i provet.');
      expect(
        kMembershipOnWeb,
        'Ditt företags administratör hanterar medlemskapet på webben.',
      );
      expect(kNotInTrialNote, '$kNotInTrial $kMembershipOnWeb');
      expect(
        kBillingOnWeb,
        'Fakturor och medlemskap hanteras av företagets administratör på webben.',
      );
      expect(kPortalAccountTitle, 'Hantera företagskonto');
      expect(
        kPortalAccountSubtitle,
        'Öppnar kundportalen på webben: bilar, fakturor och medlemmar.',
      );
      // Portaltexterna får inte låta som köp-CTA.
      for (final text in [
        kPortalAccountTitle,
        kPortalAccountSubtitle,
      ]) {
        expect(text.toLowerCase(), isNot(contains('prenumer')));
        expect(text.toLowerCase(), isNot(contains('köp')));
        expect(text.toLowerCase(), isNot(contains('betala')));
        expect(text.toLowerCase(), isNot(contains('uppgradera')));
      }
    });
  });

  test('kategorinycklarna i features: events är kartans event', () {
    expect(signalCategoryFromFeatureKey('events'), SignalCategory.event);
    expect(signalCategoryFromFeatureKey('transit'), SignalCategory.transit);
    expect(signalCategoryFromFeatureKey('okänd'), isNull);
    expect(signalCategoryFromFeatureKey(null), isNull);
  });

  test('portal-URL:n är kundportalen, överskrivbar med dart-define', () {
    expect(TaxiTipsConfig.portalUrl, 'https://portal.taxitips.se');
  });

  group('koden', () {
    /// Alla Dart-filer i lib/, utan rena kommentarsrader (kommentarerna får
    /// förklara varför något INTE finns).
    Map<String, List<String>> source() {
      final files = <String, List<String>>{};
      for (final entity in Directory('lib').listSync(recursive: true)) {
        if (entity is! File || !entity.path.endsWith('.dart')) continue;
        files[entity.path] = [
          for (final line in entity.readAsLinesSync())
            if (!line.trimLeft().startsWith('//')) line,
        ];
      }
      return files;
    }

    test('inga köp- eller betalvägar i klienten', () {
      // Kundportalen (portal.taxitips.se / PORTAL_URL) är tillåten som
      // kontohantering för admin — se membership_copy.dart. Stripe Checkout,
      // billing portal-API, IAP och köpord är fortfarande förbjudna.
      final forbidden = RegExp(
        r'stripe|checkout|billingportal|billing/portal|paymentUrl|'
        r'in_app_purchase|purchases_flutter|revenuecat|betallänk|'
        r'uppgradera|prenumerera',
        caseSensitive: false,
      );
      final hits = <String>[];
      source().forEach((path, lines) {
        for (var i = 0; i < lines.length; i++) {
          if (forbidden.hasMatch(lines[i])) {
            hits.add('$path: ${lines[i].trim()}');
          }
        }
      });
      expect(hits, isEmpty, reason: hits.join('\n'));
    });

    test('portal-URL:n används bara i config och Inställningar', () {
      final portalMention = RegExp(
        r'portalUrl|portal\.taxitips|PORTAL_URL',
        caseSensitive: false,
      );
      const allowed = {
        'lib/config.dart',
        'lib/screens/settings_screen.dart',
        'lib/membership_copy.dart',
      };
      final hits = <String>[];
      source().forEach((path, lines) {
        for (final line in lines) {
          if (portalMention.hasMatch(line) && !allowed.contains(path)) {
            hits.add('$path: ${line.trim()}');
          }
        }
      });
      expect(hits, isEmpty, reason: hits.join('\n'));
    });

    test('inget pris i någon text', () {
      // "kr" som pris: "99 kr", "kr/mån". Ersättningsbeloppet för försenade
      // tåg (severity_labels.dart) är en summa att få, inte ett pris att
      // betala, och är det enda undantaget.
      final price = RegExp(r'\d\s?kr(?![a-zåäö])|kr/|\bSEK\b|per månad|/mån');
      final hits = <String>[];
      source().forEach((path, lines) {
        if (path.endsWith('severity_labels.dart')) return;
        for (final line in lines) {
          if (price.hasMatch(line)) hits.add('$path: ${line.trim()}');
        }
      });
      expect(hits, isEmpty, reason: hits.join('\n'));
    });

    test('externa länkar finns bara där de ska', () {
      // Filer som får öppna en webbadress. Ingen av dem är en köpknapp:
      // kartnavigering, appbutiken (uppdatering), juridiska sidor,
      // trafikbolagets och evenemangets egen sida, demon, och adminens
      // kontohantering i kundportalen. Ny fil här = granska att den inte
      // leder till ett köp-CTA, och lägg till den.
      const allowed = {
        'lib/navigation.dart',
        'lib/screens/welcome_screen.dart',
        'lib/screens/settings_screen.dart',
        'lib/screens/driver_screen.dart',
        'lib/widgets/ferry_event_widgets.dart',
        'lib/widgets/force_upgrade_overlay.dart',
      };
      final users = <String>{};
      source().forEach((path, lines) {
        // launchUrlString och den äldre launch() är samma sak med en sträng.
        if (lines.any(
          (l) =>
              l.contains('launchUrl(') ||
              l.contains('launchUrlString(') ||
              RegExp(r'(^|[^\w.])launch\(').hasMatch(l),
        )) {
          users.add(path);
        }
      });
      expect(users.difference(allowed), isEmpty);
    });
  });
}
