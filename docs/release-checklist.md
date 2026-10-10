# Release: Google Play och App Store

Läget 2026-10-04 och vad som återstår innan appen kan ligga i butikerna.
"Klart" betyder klart i koden på grenen, inte driftsatt. Saker märkta
**(ägaren)** kan bara du göra: de kräver inloggning i en konsol, ett beslut
eller ett konto i produktion.

---

## 1. Klart i koden

| Område | Läge |
|---|---|
| Inlagda konton | Inloggningen fylls inte längre i med `agare@malmotaxi.se`/`taxitips123`. Förifyllt testkonto bara i debug och bara via `--dart-define=PREFILL_EMAIL/PREFILL_PASSWORD` (DEV.md). Releasebinären är kontrollerad: inget av det finns i `libapp.so`. `test/release_config_test.dart` vaktar. |
| Lösenord i klartext | Appen sparade lösenordet i `shared_preferences` (klartextfil). Nu sparas bara e-posten, och ett gammalt sparat lösenord tas bort vid start. |
| Adminwebbens `#devLogin` | Både knappen, lösenordet och den tomma `<div>`:en finns bara under `npm run dev`. Kontrollerat i `vite build`: ingen träff på `devLogin`, `admin@taxitips.local` eller `taxitips-admin-dev`. |
| Nycklar i git | `key.properties`, `keystore/`, `maps.properties`, `dart_defines.local.json`, `.env` och `Maps.xcconfig` är git-ignorerade. `google-services.json` och `GoogleService-Info.plist` ligger i git med avsikt: de är Firebase-klientkonfiguration (projekt-id, app-id, en API-nyckel som är begränsad till appen) och är inga hemligheter. Samma för Supabase anon-nyckeln i `lib/config.dart` och webbens publika id:n (Firebase web, Umami, Chatwoot). |
| Radera mitt konto | Inställningar -> längst ner -> **Radera mitt konto**. Ägare, kontor och förare. Backend: `POST /api/fleet/account/delete` (`fleet/account_deletion.py`, 15 tester). Se §4. |
| Juridiska länkar | Datapolicy och Villkor öppnade `api.taxitips.se/privacy.html` (Supabase, svarar 401). Nu `https://taxitips.se/privacy.html` och `/terms.html` (båda 200). |
| Inga köp i appen | Vakten i `test/membership_copy_test.dart` täcker nu även `launchUrlString`/`launch`. `release_config_test.dart` vaktar att inga köpbibliotek eller webbvyer läggs till. Demon på webben öppnas med `?app=1` och visar då inga knappar till registrering eller kontakt. |
| Android | Se §2. Signerad `app-release.aab` byggd: 64,1 MB (alla ABI:er + symboltabell; nedladdningen per telefon är en bråkdel). |
| iOS | Se §3. Push-rättigheten fanns inte alls -- utan den får en iPhone aldrig en notis. |

## 2. Android

* `applicationId` `se.taxitips.app`, version ur `pubspec.yaml` (`1.0.1+2` ->
  versionName 1.0.1, versionCode 2). **Höj byggnumret (`+3`, `+4` …) före varje
  uppladdning** -- Play tar aldrig samma versionCode två gånger.
* minSdk 24, targetSdk 36, compileSdk 36 (Flutter 3.44). Play kräver minst 35.
* Releasesignering med uppladdningsnyckeln ur `android/key.properties`
  (alias `upload`, SHA-1 `A8:70:D0:0F:…:C1:F3`). Utan filen varnar bygget och
  signerar med debugnyckeln, som Play avvisar.
* R8 (minify + resurskrympning) slås på av Flutter för release; symboltabellen
  för motorn följer med bunten (`debugSymbolLevel = SYMBOL_TABLE`).
* Behörigheter i det färdiga manifestet: plats (grov + exakt, bara när appen
  används), internet, nätverksstatus, notiser (`POST_NOTIFICATIONS`), FCM
  (`c2dm.RECEIVE`, `WAKE_LOCK`) och Play-installationsreferens. **Reklam-id är
  borttaget** (`AD_ID`, `ACCESS_ADSERVICES_*`), så svaret i Play Console är
  "använder inte reklam-id".
* Klartext-HTTP bara i debug (`src/debug/AndroidManifest.xml`).
* Ingen säkerhetskopia av appdata (`allowBackup=false`,
  `data_extraction_rules.xml`): förarens nyckel och inloggningen hör till
  telefonen. En ny telefon loggar in/kopplas på nytt.

Bygg och kontrollera:

```bash
cd taxitips-app
# dart_defines.local.json: API_BASE_URL=https://backend.taxitips.se,
# SUPABASE_URL=https://api.taxitips.se, SUPABASE_ANON_KEY, CARTO_KEY, GOOGLE_MAPS=true
flutter build appbundle --release --dart-define-from-file=dart_defines.local.json
echo $?          # flutters egen exitkod -- inte via | tail (AGENTS.md)
keytool -printcert -jarfile build/app/outputs/bundle/release/app-release.aab | grep SHA1
```

Utan `--dart-define-from-file` saknar appen `API_BASE_URL` och pratar bara med
Supabase -- bygg aldrig en butiksversion utan filen.

## 3. iOS

* Bundle id `se.taxitips.app`, team `YY88NFX4D7` (A2M Tech AB; var felaktigt `SMKZ5MCAFP`, ett annat team, till 2026-10-10), namnet på hemskärmen
  `Taxitips`, iPhone och iPad. **Lägsta iOS är nu 15.0** (var 13.0, och då
  vägrade `pod install`: google_maps_flutter_ios kräver 14, Firebase 12
  kräver 15). Samma värde i `Podfile` och `Runner.xcodeproj`.
* `Info.plist`: platstext på svenska (`NSLocationWhenInUseUsageDescription`,
  bara "medan appen används" -- lägg **inte** till `NSLocationAlways…`:
  geolocator ber då om "Alltid"), `UIBackgroundModes` med
  `remote-notification` (och `fetch`, som FlutterFire-guiden anger),
  `ITSAppUsesNonExemptEncryption = NO` (bara HTTPS, inget eget krypto ->
  ingen exportdokumentation). Notiser behöver ingen text i Info.plist.
* `Runner.entitlements` med `aps-environment` (ny), kopplad i Debug, Release
  och Profile. Xcode sätter `production` vid export till App Store.
* `PrivacyInfo.xcprivacy` (Apples privacy manifest) beskriver vad appen
  samlar in (§5) och skälet för UserDefaults. Plugins och Firebase har egna.
* Bygge här (2026-10-04): `flutter build ios --release --no-codesign` kom
  förbi `pod install` och in i Xcode-kompileringen, men stoppades av full disk
  på Macen -- inget fel i projektet. Kör det igen med några GB ledigt innan du
  arkiverar. Ett signerat arkiv kräver ditt Apple-konto i Xcode.

**Signering (2026-10-10).** Release signeras manuellt med "Apple Distribution: A2M Tech AB"
och profilen "Taxitips App Store" (push i produktionsläge), skapade med App Store Connect
API-nyckeln `7SL8TDFVJN` (Issuer `d5b5f9e4-…`; nyckelfilen i `~/.appstoreconnect/private_keys`,
certifikatets privata nyckel i `~/.appstoreconnect/signing` -- aldrig i git). Debug behåller
automatisk signering. Första bygget (1.0.1+3) laddades upp till App Store Connect 2026-10-10.

```bash
cd taxitips-app
flutter build ios --release --config-only --dart-define-from-file=dart_defines.local.json
xcodebuild -workspace ios/Runner.xcworkspace -scheme Runner -configuration Release \
  -destination 'generic/platform=iOS' -archivePath build/ios/archive/Runner.xcarchive archive
xcodebuild -exportArchive -archivePath build/ios/archive/Runner.xcarchive \
  -exportOptionsPlist ExportOptions.plist -exportPath build/ios/ipa   # method app-store-connect, manual
xcrun altool --upload-app -f build/ios/ipa/Taxitips.ipa -t ios --apiKey 7SL8TDFVJN --apiIssuer <issuer>
```

Bygg och ladda upp (Mac med Xcode):

```bash
cd taxitips-app
flutter build ipa --release --dart-define-from-file=dart_defines.local.json
# Öppna build/ios/archive/Runner.xcarchive i Xcode -> Distribute App -> App Store Connect,
# eller: xcrun altool / Transporter med build/ios/ipa/*.ipa
```

## 4. Butikernas regler, punkt för punkt

| Regel | Läge |
|---|---|
| Apple 3.1.1 / 3.1.3, Google Play Payments: inga köp, priser eller köplänkar i appen | **Klart.** Inget pris, ingen köpknapp, ingen länk till betalning. Medlemskapstexter på ett ställe (`lib/membership_copy.dart`), serverns betalningsmeddelanden visas aldrig rakt av. Inställningarna säger bara: "Fakturor och medlemskap hanteras av företagets administratör på webben." (ingen länk). Webbdemon från appen visar inga säljknappar. Skälet att B2B-modellen är tillåten: `docs/fleet-abonnemang.md` §9c. |
| Apple 5.1.1(v): konto som skapas i appen ska kunna raderas i appen | **Klart.** "Radera mitt konto" längst ner i Inställningar, med bekräftelse. Ägare/kontor: kontot i Supabase Auth, medlemskap, katalog, telefoner kontot kört med. Förare (utan Supabase-session, bara telefonens nyckel): telefonens koppling och förarkontot. Vägrar bara när personen är **enda ägaren och medlemskapet förnyas** -- svaret säger "Avsluta företagskontot först (längst ner i Inställningar) eller låt en kollega ta över ägarrollen", och efter "Avsluta företagskontot" går raderingen igenom direkt. Ett kortfritt prov stoppar inte raderingen (provet avslutas). Personalkonton raderas inte från appen. |
| Apple 5.1.1(i), Google User Data: integritetspolicy nåbar i appen och i butiken | **Klart i appen** (Inställningar -> Datapolicy/Villkor -> taxitips.se). **(ägaren)** Samma adress i App Store Connect och Play Console. Kontrollera att policyn nämner raderingen i appen, Firebase (Crashlytics, Analytics, Performance, Messaging) och hur länge data sparas (`docs/loggning.md`). |
| Apple 5.1.2 / Play Data safety: deklarera insamlad data | **(ägaren)** Fyll i enligt §5. |
| Apple 2.1: granskaren måste kunna logga in | **(ägaren)** Demokonto, §6. |
| Apple 4.0 / 4.2: fungerar, ser ut som en app | Riktig karta, riktiga tips, svenska. Inget att göra i koden. |
| Platsbehörighet bara vid användning | **Klart.** Ingen bakgrundsplats på Android eller iOS. |

## 5. Sekretessetikett (App Store) och Data safety (Play)

Samma lista i båda och i `ios/Runner/PrivacyInfo.xcprivacy`. Ingen spårning,
ingen reklam, inget säljs eller delas med tredje part (Firebase och Supabase är
personuppgiftsbiträden). All överföring är krypterad (HTTPS). Användaren kan
radera kontot i appen.

| Data | Kopplad till person | Syfte |
|---|---|---|
| E-post, namn, telefonnummer (registrering, inloggning) | Ja | Appfunktion, konto |
| Konto-id, enhets-id (installations-id, push-token) | Ja | Appfunktion |
| Ungefärlig plats (avrundad; "I tjänst" sparar en ruta på ca 5 km i 30 min) | Ja | Appfunktion |
| Supportchatt, rapporter med fritext | Ja | Appfunktion, support |
| Feedback på tips ("Fick körning"/"Ingen kund") | Ja | Appfunktion, analys |
| Diagnostik: appversion, telefonmodell, OS, appens fel | Ja | Appfunktion, support |
| Kraschrapporter (Crashlytics) | Nej | Appfunktion |
| Prestanda (Firebase Performance) | Nej | Appfunktion |
| Användning (Firebase Analytics) | Nej | Analys |

Play Console: "Data delas inte", "Data krypteras under överföring", "Användaren
kan begära radering" -- ja, i appen och via hej@taxitips.se. Reklam-id: nej.

App Store Connect: "Data Used to Track You": inget. IDFA: nej (appen frågar
aldrig om spårning).

## 6. Det du måste göra själv (ägaren)

**Google Play Console**
1. Skapa appen `se.taxitips.app` (namn i butiken: välj "Taxi Tips" -- mejlen och
   `taxitips.se/forare` säger "Hämta appen Taxi Tips"; hemskärmen visar
   `Taxitips`).
2. Butiksinfo: kort och lång beskrivning, ikon 512x512, funktionsgrafik
   1024x500, minst två skärmbilder per formfaktor (`taxitips-app/store/`).
3. Appinnehåll: integritetspolicy (`https://taxitips.se/privacy.html`), Data
   safety (§5), reklam-id: nej, innehållsklassning (enkätens svar: verktyg,
   inget våld/spel/användarinnehåll som delas mellan användare), målgrupp
   vuxna (18+), "Appåtkomst": ange demokontot (punkt 1 under App Store nedan,
   samma konto går bra).
4. Intern testning: ladda upp `app-release.aab`, lägg till testare, installera
   från Play. Kontrollera inloggning, notis, karta (Google Maps-nyckeln:
   lägg till **Play-signeringsnyckelns SHA-1** från Play Console -> Appintegritet
   i Google Cloud-nyckelns begränsning, annars blir kartan tom i Play-versionen;
   samma SHA-1 i Firebase för `se.taxitips.app`).
5. Stängd/öppen testning eller direkt produktion. Nya personliga
   utvecklarkonton kräver 12 testare i 14 dagar innan produktion;
   organisationskonton gör det inte.

**App Store Connect**
1. **Demokonto för granskarna, skapat i produktion och angivet bara i App
   Store Connect (App Review Information), aldrig i koden.** Förslag: ett eget
   bolag ("TaxiTips Granskning AB" eller liknande) upplagt av en säljare i
   adminwebben med ett prov eller en kupong, en ägare med e-post och starkt
   lösenord, och en bil med län där det finns tips (Stockholm/Skåne). Skriv i
   granskningsanteckningarna: vad appen gör, att den är B2B (taxibolag betalar
   utanför appen, 3.1.3(c)/§9c), hur man loggar in, att "Radera mitt konto"
   finns längst ner i Inställningar -- och att raderingen tar bort demokontot
   (skapa ett nytt om granskaren provar den).
2. Skapa appen med bundle id `se.taxitips.app` (Identifiers: slå på Push
   Notifications).
3. Sekretessetikett enligt §5, integritetspolicyns adress, åldersgräns,
   kategori (Navigation eller Business), exportfrågan: "Nej" (följer av
   `ITSAppUsesNonExemptEncryption`).
4. Skärmbilder: 6,9" iPhone (krävs) och 13" iPad (krävs eftersom appen
   stöder iPad -- annars ta bort iPad i Xcode, `TARGETED_DEVICE_FAMILY = 1`).
5. TestFlight: ladda upp med `flutter build ipa`, intern testning, prova
   inloggning, notis och radering på en riktig iPhone.
6. När appen är publicerad: sätt `APP_IOS_STORE_URL` på backenden (tvingad
   uppdatering länkar dit).

**Firebase** (`taxitips-se`)
* Ladda upp en **APNs-autentiseringsnyckel (.p8)** under Project settings ->
  Cloud Messaging -> Apple app. Utan den når inga notiser iPhone.
* Lägg till Play-signeringsnyckelns SHA-1/SHA-256 för Android-appen.

**Stripe live** -- `docs/fleet-abonnemang.md` och minnesanteckningen om
adminwebben: momssats, `ALLOW_LIVE`, och att webhooken pekar rätt. Inget av det
rör appen, men kunderna som provar i appen ska kunna fortsätta i portalen.

**SMTP och mejl**
* Utkorgen (`FLEET_SMTP_USER`/`FLEET_SMTP_PASSWORD`, Hostinger) på workern.
* Supabase Auth: `GOTRUE_SMTP_*` och mallarna `GOTRUE_MAILER_TEMPLATES_*` ->
  `https://taxitips.se/email/*.html` (`docs/auth-mejl.md`). Kör
  `manage.py build_auth_email_templates` efter ändringar i layouten.
* `API_EXTERNAL_URL=https://api.taxitips.se` och `SITE_URL=https://taxitips.se`.

**Supabase Auth** -- tillåtna `redirect_to` (kontrollerat 2026-10-04 med en
ogiltig token mot `api.taxitips.se/auth/v1/verify`): `taxitips.se/forare`,
`/bekraftad`, `/portal`, `/admin` och `portal.taxitips.se` godtas; en okänd
adress faller tillbaka på `https://taxitips.se`. Rätt.

**Före varje butiksversion**
1. Höj `version:` i `pubspec.yaml` (byggnumret alltid, versionsnamnet vid behov).
2. `flutter analyze && flutter test`, backendens tester, `npx vite build`.
3. Driftsätt backenden först om appen behöver en ny endpoint (den här
   versionen behöver `POST /api/fleet/account/delete` -- utan den svarar
   "Radera mitt konto" med ett fel).
4. Bygg (§2, §3), prova på en riktig telefon, ladda upp.

## 7. Mejlens länkar (kontrollerat 2026-10-04)

| Mejl | Länk | Mål |
|---|---|---|
| Provet startat / tre dagar kvar / sista dygnet / provet slut (`fleet/notifications.py`) | `FLEET_PORTAL_URL#fortsatt` (standard `https://taxitips.se/portal#fortsatt`) | `/portal` svarar 302 till `portal.taxitips.se`; webbläsaren behåller `#fortsatt`. `src/portal/main.js` sparar ankaret över inloggningen och öppnar kortet "Fortsätt med provbilarna". |
| Inbjudan till portalen (`sales.invite_owner`, `member_invite`) | Supabase-länk med `redirect_to` = portalen | Godkänd adress; portalen visar GoTrue-fel (`otp_expired`) begripligt. |
| Förarinbjudan (`driver_invites.py`) | Supabase-länk med `redirect_to` = `FLEET_DRIVER_INVITE_REDIRECT` (`https://taxitips.se/forare`) | `forare.html` + `src/forare.js`: väljer lösenord ur sessionen i hashen, visar fel vid förbrukad länk, säger "Hämta appen Taxi Tips". |
| Supabase-mallarna (`public/email/*.html`) | `{{ .ConfirmationURL }}` = `API_EXTERNAL_URL/auth/v1/verify?…&redirect_to=…` och `https://taxitips.se` | `api.taxitips.se/auth/v1/verify` svarar och skickar vidare enligt tillåtelselistan. |
| Bekräfta e-post vid registrering i appen | `redirect_to` = `https://taxitips.se/bekraftad` | `bekraftad.html` visar "bekräftad, logga in i appen" eller felet. |

Inte kontrollerat härifrån: produktionens faktiska värde på `FLEET_PORTAL_URL`
och `GOTRUE_MAILER_TEMPLATES_*` (Coolify-MCP:n i den här miljön visar den gamla
instansen, inte Hostinger-VPS:en). Skicka ett testmejl av varje sort till dig
själv före lanseringen.
