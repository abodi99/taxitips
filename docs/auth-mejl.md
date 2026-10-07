# Mejlen: mallar, kod och inbjudningar

Två vägar skickar mejl, med samma utseende (`taxitips-backend/fleet/email_layout.py`):

| Mejl | Skickas av | Mall |
|---|---|---|
| Registreringslänk, inloggningskod, nytt lösenord, byte av e-post, bekräftelsekod | Supabase Auth (GoTrue) | `taxitips-web/public/email/*.html`, hämtas från taxitips.se |
| Inbjudan till kundportalen, förarinbjudan, prov, betalning, uppsägning | Djangos utkorg (`fleet/notifications.py` → `fleet/mailer.py`) | HTML byggs ur mejlets text vid utskick |

Båda skickar från `hej@taxitips.se` via smtp.hostinger.com (SPF/DKIM/DMARC finns på taxitips.se).

## Supabase Auth-mallarna

Mallarna genereras och ska committas efter en ändring:

    cd taxitips-backend && .venv/bin/python manage.py build_auth_email_templates

De publiceras med webben (taxitips-web). GoTrue hämtar dem över HTTPS när ett mejl skickas, så
**webben måste vara driftsatt innan GoTrue pekas om**. Annars faller GoTrue tillbaka på sin
engelska standardmall.

### Inställningar på auth-tjänsten i `supabase-taxitips` (Coolify, prod)

Lägg till på tjänsten `supabase-auth` (Coolify → supabase-taxitips → Edit Compose File, under
`environment:` för auth):

```
GOTRUE_MAILER_TEMPLATES_CONFIRMATION: https://taxitips.se/email/confirmation.html
GOTRUE_MAILER_TEMPLATES_MAGIC_LINK: https://taxitips.se/email/magic_link.html
GOTRUE_MAILER_TEMPLATES_RECOVERY: https://taxitips.se/email/recovery.html
GOTRUE_MAILER_TEMPLATES_INVITE: https://taxitips.se/email/invite.html
GOTRUE_MAILER_TEMPLATES_EMAIL_CHANGE: https://taxitips.se/email/email_change.html
GOTRUE_MAILER_TEMPLATES_REAUTHENTICATION: https://taxitips.se/email/reauthentication.html
GOTRUE_MAILER_SUBJECTS_CONFIRMATION: "Bekräfta din e-post för Taxi Tips"
GOTRUE_MAILER_SUBJECTS_MAGIC_LINK: "Din inloggningskod till Taxi Tips"
GOTRUE_MAILER_SUBJECTS_RECOVERY: "Välj ett nytt lösenord för Taxi Tips"
GOTRUE_MAILER_SUBJECTS_INVITE: "Du är inbjuden till Taxi Tips"
GOTRUE_MAILER_SUBJECTS_EMAIL_CHANGE: "Bekräfta din nya e-post för Taxi Tips"
GOTRUE_MAILER_SUBJECTS_REAUTHENTICATION: "Din kod till Taxi Tips"
GOTRUE_MAILER_OTP_LENGTH: "6"
GOTRUE_MAILER_OTP_EXP: "3600"
GOTRUE_SMTP_SENDER_NAME: "Taxi Tips"
```

`GOTRUE_MAILER_AUTOCONFIRM` ska vara `false`, så att registreringen skickar bekräftelsemejlet. Det är redan
läget i prod: nya konton bekräftas i efterhand.

**Starta om supabase-taxitips från Coolify-gränssnittet, inte via API:t.** En omstart via API
har lämnat alla containrar stoppade, databasen inräknad. Kontrollera efteråt att
`https://api.taxitips.se/auth/v1/health` svarar och att backendens `/health` är grön.

### Prova

1. Registrera ett testkonto i appen med en egen adress. Mejlet ska ha loggan och
   knappen "Bekräfta e-post" – ingen kod (registreringen bekräftas med länken).
2. "Glömt lösenord" i portalen. Knappen ska leda till portalen, där ett nytt lösenord väljs.
3. Logga in med kod i appen.

## Inbjudningar

- **Taxi Tips bjuder in kundens ägare:** Admin → kunden → Inloggningar → "Bjud in en
  inloggning" (roll Ägare, Bilar och förare eller Ekonomi).
- **Kunden bjuder in en kollega:** Portalen → Företag → Inloggningar
  (`POST /api/fleet/members/invite`, roll Bilar och förare eller Ekonomi). En ny ägare går via
  ägarbytet.
- **Förare:** per bil i portalen, appen eller admin (`fleet/driver_invites.py`).

Servern skapar en engångslänk med `generate_link` (`fleet/auth_admin.py`, kräver
`SUPABASE_SERVICE_ROLE_KEY`) och mejlar den själv. GoTrue skickar alltså inget här. Länken
loggar in i portalen, som knyter kontot till företaget (`claim-invite`) och ber om ett lösenord.

Rollerna som ger behörighet finns i `fleet/roles.py`: `company_owner`, `fleet_admin` och
`finance`. `company_admin` är en äldre roll utan behörigheter.
