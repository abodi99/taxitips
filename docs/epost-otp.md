# E-postkod (OTP) vid registrering

Den som registrerar ett företag bekräftar sin e-post med en **6-siffrig kod** i
appen i stället för att klicka på en länk. Rätt kod loggar in direkt och
registrerar företaget (`ApiClient.verifySignupCode` → Supabase `verifyOTP`
med `type: signup`). Länken i samma mejl finns kvar som reserv.

## Vad som krävs i Supabase (prod)

Standardmallen för "Confirm signup" innehåller bara länken. Koden kommer med
först när mallen har `{{ .Token }}`. Mallen ligger i
`taxitips-web/public/email-templates/bekrafta-konto.html` och publiceras med
webben på `https://taxitips.se/email-templates/bekrafta-konto.html`.

1. **Driftsätt webben** och kontrollera att mallen svarar 200 på adressen ovan.
2. **Sätt miljövariablerna** på Supabase-tjänsten `supabase-taxitips` (auth):

   ```
   GOTRUE_MAILER_TEMPLATES_CONFIRMATION=https://taxitips.se/email-templates/bekrafta-konto.html
   GOTRUE_MAILER_SUBJECTS_CONFIRMATION=Din kod till Taxi Tips
   ```

   Standardvärdena räcker för resten: `GOTRUE_MAILER_OTP_LENGTH=6`,
   `GOTRUE_MAILER_OTP_EXP=86400` (24 h). `GOTRUE_MAILER_AUTOCONFIRM` ska vara
   `false` (annars skickas inget mejl och ingen kod behövs).
3. **Starta om Supabase från Coolify-gränssnittet**, inte via API:t. En omstart
   via API har lämnat alla containrar stoppade två gånger. Kontrollera
   inloggningen och `backend.taxitips.se/health/pipeline` efteråt.
4. **Prova:** registrera med en testadress → mejlet har en 6-siffrig kod → skriv
   den i appen → du hamnar inloggad med företaget registrerat.

Innan steg 2–3 är gjorda får användaren ett mejl med bara länken. Appen visar
då kodsteget, men koden finns inte i mejlet. Länken och "Tryckte på länken?
Logga in" fungerar som förut. Gör därför steg 1–3 i samma veva som appen släpps.

Lokalt (`taxitips-api/supabase/config.toml`) är `enable_confirmations = false`:
där skapas kontot utan bekräftelse och kodsteget visas inte.

## Tvingad uppdatering (Remote Config, projekt `taxitips-se`)

| Nyckel | Effekt |
|---|---|
| `android_min_version` / `ios_min_version` | Allt under versionen spärras och skickas till butiken. |
| `android_blocked_versions` / `ios_blocked_versions` | Kommaseparerade versioner som spärras även om de är över min, t.ex. `1.4.0, 1.4.1+33`. `1.4.0` spärrar alla byggen av 1.4.0. |
| `android_recommended_version` / `ios_recommended_version` | Banderoll som föreslår uppdatering. |
| `android_store_url` / `ios_store_url` | Butikslänk. Utan iOS-länk blir en iOS-spärr bara en banderoll. |
| `force_upgrade_message` | Valfri text på spärren. |

Appen hämtar Remote Config vid start (högst en gång i timmen) och prövar igen
varje gång den kommer tillbaka från bakgrunden. Samma gränser kan också sättas
i adminwebben (`/api/config` → `appVersion`); Remote Config vinner när båda är satta.
