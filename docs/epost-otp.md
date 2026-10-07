# E-postbekräftelse vid registrering

Den som registrerar ett företag bekräftar sin e-post genom att **trycka på
länken i mejlet** – samma väg som "Glömt lösenord". Tidigare skrevs en
6-siffrig engångskod in i appen; det steget togs bort 2026-10-10 eftersom länken
räcker och koden bara var ett extra steg. Företaget registreras vid nästa
inloggning (`completePendingRegistration`, `lib/api_client.dart` och
`portal/main.js`).

Länken är Supabases `{{ .ConfirmationURL }}` och går till
`https://taxitips.se/bekraftad` (`ApiClient._confirmedPage`).

## Vad som krävs i Supabase (prod)

Standardmallen för "Confirm signup" innehåller bara länken, och det är vad vi
vill ha. Mallen genereras av `manage.py build_auth_email_templates` och
publiceras med webben på `https://taxitips.se/email/confirmation.html`
(se `docs/auth-mejl.md`).

1. **Driftsätt webben** och kontrollera att
   `https://taxitips.se/email/confirmation.html` svarar 200. (Den äldre
   `email-templates/bekrafta-konto.html` är kvar men ska inte användas.)
2. **Sätt miljövariablerna** på Supabase-tjänsten `supabase-taxitips` (auth):

   ```
   GOTRUE_MAILER_TEMPLATES_CONFIRMATION=https://taxitips.se/email/confirmation.html
   GOTRUE_MAILER_SUBJECTS_CONFIRMATION=Bekräfta din e-post för Taxi Tips
   ```

   `GOTRUE_MAILER_AUTOCONFIRM` ska vara `false` (annars skickas inget mejl och
   länken behövs inte). `GOTRUE_MAILER_OTP_LENGTH`/`_OTP_EXP` styr fortfarande
   engångskoden för **inloggning** (`magic_link`), inte registreringen.
3. **Starta om Supabase från Coolify-gränssnittet**, inte via API:t. En omstart
   via API har lämnat alla containrar stoppade två gånger. Kontrollera
   inloggningen och `backend.taxitips.se/health/pipeline` efteråt.
4. **Prova:** registrera med en testadress → mejlet har knappen "Bekräfta
   e-post" → tryck på den → logga in i appen → företaget registreras.

Lokalt (`taxitips-api/supabase/config.toml`) är `enable_confirmations = false`:
där skapas kontot utan bekräftelse och bekräftelsekortet visas inte.

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
