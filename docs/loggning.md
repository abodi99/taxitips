# Loggning av appar och fel

Vad TaxiTips sparar om användarnas appar och fel, varför, och hur länge.
Syftet är ett: att supporten ska kunna felsöka när en kund säger att appen
inte fungerar -- utan att be föraren leta i inställningarna, och utan att
lagra mer än det kräver.

Kod: `taxitips-backend/fleet/client_activity.py` (lagring, tvätt, gallring),
`fleet/client_log_api.py` (appens felrapporter), `fleet/admin_activity.py`
(adminwebbens läsning), `core/middleware.py` + `core/request_context.py`
(request-id), `taxitips-app/lib/client_info.dart` och `lib/client_log.dart`
(appen), `taxitips-web/src/admin/activity.js` (vyn "Appar och fel").

## 1. Senaste läget per konto och telefon (`fleet_client_activity`)

En rad per inloggat konto och en per förartelefon. Varje fält skrivs över
med det senaste värdet -- **ingen historik**.

| Fält | Varifrån | Varför |
|---|---|---|
| Senaste inloggning | JWT:ns `amr`-tidsstämpel (verifierad token) | "Jag kan inte logga in" -- har kontot någonsin lyckats? |
| Senast sedd | Senaste verifierade anrop, exakt på 10 min | Är telefonen igång alls? |
| Appversion, bygge | Header `X-App-Version`, `X-App-Build` | Kör kunden en version med ett känt fel? När kan en gammal version stängas av? |
| Plattform | `X-App-Platform` (android/ios/web) | |
| OS-version, modell | `X-OS-Version`, `X-Device-Model` | Fel som bara finns på en viss telefon eller Android-version |
| Nät | IP-adressen avkortad till /24 (IPv4) eller /48 (IPv6) | Mobilnät eller företagets wifi; pekar inte ut ett hushåll |
| Land | Bara om en proxy framför oss skickar `CF-IPCountry` | Ingen egen GeoIP |

Raden skrivs bara när åtkomstkontrollen verifierat VEM som frågar
(förartoken eller Supabase-JWT). En header ensam skapar aldrig en rad. Samma
konto/telefon med oförändrad metadata skrivs högst var tionde minut.

## 2. Fel (`fleet_client_error`)

* **Appens krascher** -- `FlutterError.onError` och
  `PlatformDispatcher.onError`, kedjade efter Crashlytics (som finns kvar som
  förut på iOS/Android).
* **Misslyckade kritiska flöden** -- inloggning, profil vid start,
  registrering (konto och företag), parkoppling, tipsflödet. Också
  "fel lösenord" och "fel kod": det är just de supporten får frågor om.
* **Serverns 5xx** från `/api/` -- utan feltext; den står i serverloggen under
  samma request-id.

Varje rad bär: tid, antal gånger (samma fel från samma avsändare inom en
timme räknas upp), sort, flöde, feltyp, feltext och stack (tvättade och
kapade till 1 000 resp. 4 000 tecken), HTTP-status och skälkod, request-id,
företag/konto/telefon-id och appens metadata enligt ovan.

**Tvätt innan lagring.** Feltexten rensas från JWT:er, `Bearer`-tokens,
värden efter `password`/`token`/`secret`/`api_key`/`pairing_code` m.fl., långa
slumpsträngar (enhetshemligheter, FCM-tokens), e-postadresser, svenska
mobilnummer, personnummer och koordinater. UUID:n och klassnamn behålls --
de är vad supporten söker på.

**Utan inloggning.** Ett fel vid själva inloggningen kommer från någon som
inte är inloggad. Sådana rapporter tas emot men utan koppling till någon, med
en snävare gräns (10 per nät och timme).

**Gränser.** Kroppen högst 16 KiB. 30 rapporter per telefon/konto och tio
minuter, 3 000 per timme totalt (`fleet/ratelimit.py`). Appen slår själv ihop
samma fel inom fem minuter och skickar högst 40 rapporter per körning, utan kö
-- ett fel som inte når fram offline skickas inte senare.

## 3. Request-id och serverloggen

Varje svar bär `X-Request-Id`, och varje loggrad under begäran får
` [req=… path=… user=… device=…]` (id:n, aldrig tokens). Ett serverfel i
adminwebbens lista har samma id som raden i loggen.

## 4. Vad som inte sparas

Ingen position eller positionshistorik (flödets position går i en header och
lagras inte här), inga meddelanden eller supportchattens innehåll, inga
tokens, lösenord eller koder, inget enhets-id från telefonen, inget namn på
telefonen, ingen fullständig IP-adress, ingen historik över när någon varit
aktiv.

## 5. Gallring

`manage.py purge_old` (schemalagd varje timme, `CELERY_BEAT_SCHEDULE
"purge-old"`) tar bort:

* fel äldre än **30 dygn** (räknat från senaste förekomst);
* aktivitetsrader för konton och telefoner som inte hörts av på **180 dygn**.

## 6. Vem kan läsa

Bara plattformens personal med `ADMIN_VIEW` (support, säljare,
plattformsadministratör), i adminwebben under "Appar och fel", på kundsidan
(hopfälld ruta sist) och i "Konton och spärrar". Tabellerna är stängda för
PostgREST (anon/authenticated, invariant 19). Kunder ser ingenting av detta.

## 7. Driftsättning

Backenden före appen: den nya appen skickar `X-App-*`-headers, och Flutter
web får bara skicka dem när serverns CORS-svar tillåter dem
(`core/middleware.RequestContextMiddleware`). Mobilappen påverkas inte av
ordningen.
