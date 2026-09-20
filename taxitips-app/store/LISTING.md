# Taxitips — Store Listing Brief

> **Syfte:** Underlag för Play Store och App Store listning.  
> **Publik:** Taxiförare i Sverige (B2B — bolaget betalar, föraren kör med bolagskod).  
> Inget konsumenttilltal, ingen IAP, inga prenumerationserbjudanden riktade till föraren.

---

## App-metadata

| Fält | Värde |
|---|---|
| **Apptitel** | Taxitips |
| **Package ID (Android)** | `se.taxibehov.taxibehov_app` — ändra **inte**; bryter uppdateringar |
| **Bundle ID (iOS)** | `se.taxibehov.taxibehovApp` — ändra **inte** |
| **Version** | 1.0.0 (build 1) — uppdatera inför release |
| **Kategori Play** | Navigation / Transport |
| **Kategori App Store** | Navigation |
| **Innehållsklassning** | 4+ / Everyone |
| **Privacy policy** | https://taxitips.se/privacy (placeholder — sida behöver skapas) |
| **Support-URL** | https://taxitips.se/#kontakt |
| **Marknadsförings-URL** | https://taxitips.se |

---

## Kortbeskrivning (80 tecken, Play Store)

```
Taxiefterfrågan i realtid – var folk väntar på taxi, just nu.
```
*(62 tecken)*

Alternativ:
```
Hitta passagerare smartare – realtidstips för taxiförare.
```

---

## Lång beskrivning (4 000 tecken, Play + App Store)

```
Taxitips ger dig försteg — innan de andra förarna vet om det.

Appen analyserar tåg- och bussförseningar, vägincidenter och
trafikhändelser i realtid och visar dig var det just nu finns
behov av taxi. Inte "kanske imorgon" — utan ett konkret tips
med förklaring: varför det händer, hur säker signalen är, och
om det är värt att köra dit.

TIPS SOM GÅR ATT LITA PÅ
• Varje tips visar källan: vilka avgångar som är försenade,
  hur många resenärer som berörs och vad som orsakar det.
• Konfidensnivå på varje signal — du vet när det är ett starkt
  fynd och när det är värt att avvakta.
• Inga påhittade siffror. Inga vaga "hög efterfrågan"-meldanden.

NOTISER SOM VÄCKER DIG I RÄTT LÄGE
• Välj vilka städer och regioner du vill bevakas.
• Tysta notiser när det finns ersättningstrafik — du väcks bara
  när det faktiskt saknas alternativ för resenärerna.
• Notishistorik i appen så att du kan se vad du missat.

FÖR HELA KÖRPASSET
• Karta med aktiva hotspots.
• Filtrering på störningstyp, region och prioritet.
• Favoritmarkera platser du vill ha koll på.
• Ingen inloggning med lösenord — kom igång med en bolagskod.

DATAKÄLLOR
Trafikverkets järnväg och väg, SL, Västtrafik och Trafiklab —
täckning i hela Sverige med tyngdpunkt på Skåne och Stockholm.

Taxitips ingår i din bolagsprenumeration. Fråga din arbetsgivare
om ni redan har tillgång — eller be dem besöka taxitips.se.
```

---

## Nyckelord / Söktermer

Play Store: `taxitips, taxi, efterfrågan, tips, förare, realtid, tåg, buss, försening, hotspot`

App Store (100 tecken): `taxi,efterfrågan,realtid,hotspot,förare,tips,tåg,buss,störning,transport`

---

## Skärmdump-storyboard

### Storlekar som krävs

| Plattform | Format | Min antal |
|---|---|---|
| Play Store — telefon | 1080 × 1920 px (9:16) | 2 (max 8) |
| App Store — 6.7" iPhone | 1290 × 2796 px | 3 (max 10) |
| App Store — 6.5" iPhone | 1242 × 2688 px | 3 (max 10) |
| App Store — iPad Pro 12.9" | 2048 × 2732 px | valfritt |
| Feature Graphic (Play) | 1024 × 500 px | 1 |

> Använd 6.7"-varianterna som primär — Play och App Store accepterar
> dem för alla telefonstorlekar om man bara har en uppsättning.

### 5 skärmdumps-captions (prioritetsordning)

Skapa dessa i faktisk app eller i Figma med hårdkodade exempeldata.
Varje bild: enhetsmockup (mörk/ljus) + Swedish caption-text ovanpå.

**Skärm 1 — Kartan med tips**
> "Se var folk väntar på taxi — just nu"
> Visar: `hotspot_map.dart`-vyn med minst 2-3 aktiva pins
> Enhet: iPhone med midnatt statusbar

**Skärm 2 — Tipslistan sorterad på prioritet**
> "Alla störningar, rangordnade för dig"
> Visar: `driver_screen.dart` listvy med 3-5 kort
> Blanda tåg- och busstörning, olika konfidenspills

**Skärm 3 — Tipskort i detalj**
> "Förstå varför — inte bara vad"
> Visar: expanderat kort med källhänvisning, konfidensnivå och förklaring
> Highlight: "Tåget från Malmö är 38 min försenat — 120 resenärer utan anslutning"

**Skärm 4 — Notis på låst skärm**
> "Väcks i rätt läge — utan onödigt buller"
> Visar: iOS/Android notis med störningstitel + välj dina regioner i inställningar

**Skärm 5 — Inställningar — region och notisfilter**
> "Välj dina marknader, tysta resten"
> Visar: `settings_screen.dart` / `notify_prefs_sheet.dart` med länsval

*(Valfri sjätte bild: login-/bolagskodskärm för att visa enkel onboarding)*

### Feature Graphic (Play Store, 1024×500)

Mörk bakgrund (#14213D), logotypen centrerat till vänster, höger halva:
en stiliserad kartsymbol med 2-3 guldpins. Ingen text utom "Taxitips" i
Montserrat Bold. Format: JPEG eller PNG, max 1 MB.

---

## Checklista — vad som saknas inför publish

- [ ] **Privacy policy-sida** på taxitips.se/privacy (GDPR-krav)
- [ ] **Screenshots** — ta på riktig enhet (se `AGENTS.md §4` för LAN-setup)
  eller bygg i Figma med exempeldata
- [ ] **Feature Graphic** (Play Store)
- [ ] **Signering** — Android release keystore (`taxitips-release.jks`) skapad
  och konfigurerad i `build.gradle.kts` (ta inte debug-nyckeln till store)
- [ ] **iOS Distribution certificate** + provisioning profile i Xcode
- [ ] **App Store Connect** — app skapad, bundle ID verifierat
- [ ] **Google Play Console** — app skapad, paket-ID matchar `se.taxibehov.taxibehov_app`
- [ ] **Launcher-ikon genererad** — kör:
  ```bash
  cd taxitips-app
  flutter pub get
  dart run flutter_launcher_icons
  ```
  Kontrollera `android/app/src/main/res/mipmap-*/` och
  `ios/Runner/Assets.xcassets/AppIcon.appiconset/` efter körning.
- [ ] **Version bumpad** — `pubspec.yaml`: `version: 1.0.0+1`
  (sätt +1 = versionCode 1 för första store-release)

---

## Paket-ID vs. visningsnamn — dokumentation

| Identifierare | Värde | Får ändras? |
|---|---|---|
| Android applicationId | `se.taxibehov.taxibehov_app` | **Nej** — bryter alla befintliga installationer |
| Android namespace | `se.taxibehov.taxibehov_app` | Nej |
| iOS Bundle Identifier | `se.taxibehov.taxibehovApp` | Nej |
| Firebase-projekt | `taxibehov` | Nej |
| Dart package name (pubspec) | `taxibehov_app` | Nej — alla `import`-statements |
| **Android display name** | **Taxitips** ✅ | Ja — ändrat i `AndroidManifest.xml` |
| **iOS CFBundleDisplayName** | **Taxitips** ✅ | Ja — ändrat i `Info.plist` |
| **iOS CFBundleName** | **Taxitips** ✅ | Ja — ändrat i `Info.plist` |
| Flutter app title | `Taxitips` ✅ | Ja — ändrat i `main.dart` |

---

## Granskningsunderlag (P0-C5, 2026-09-13)

**Köp i appen:** inga. Mobilappen (iOS och Android) visar inte längre
"Registrera" eller "Skapa företagskonto" -- det köpflödet öppnade Stripe Checkout
och finns kvar bara i webbversionen. Föraren ansluter med bolagskod; bolaget
tecknar och administrerar abonnemanget på webben. Tjänsten säljs till företag, inte
till konsumenter.

**Anteckning till App Review (utkast):**
> Taxitips is a business tool sold to taxi companies. Drivers join with a company
> code provided by their employer; there are no purchases in the app. Demo access:
> company code `<fylls i>` (a demo company with an active subscription).

**Plats:** "när appen används" (`NSLocationWhenInUseUsageDescription`), bara för
avstånd till tips. Positionen avrundas till ungefär en kilometer, skickas i en
header och sparas inte. Utan plats väljer föraren körområde (län). Ingen
bakgrundsplats.

**I tjänst (valfritt):** föraren slår på det i notisinställningarna. Medan appen
är öppen sparar servern rutan positionen ligger i (ungefär 5 km) på enhetens rad,
förnyad högst var femte minut och borta 30 minuter efter senaste förnyelse.
Ingen historik, ingen hämtning i bakgrunden. Notiser gäller då tips inom 30 km.
Integritetsmanifestet anger grov plats som kopplad till enheten.

**Integritetsmanifest:** `ios/Runner/PrivacyInfo.xcprivacy` -- utkast som ska
stämmas av mot Firebase-konfigurationen och integritetsetiketten i App Store Connect.

**Kvar före inlämning:** riktig integritetspolicy på `https://taxitips.se/privacy`
(se ovan: sidan saknas), demokod för granskaren, skärmbilder med körområdesvalet.
