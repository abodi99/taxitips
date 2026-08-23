# TaxiTips Web (landing + admin + portal)

Statisk webb kopplad till **Supabase** på `https://api.taxitips.se`.

## Kör lokalt

```bash
cd taxitips-web
npx --yes serve -l 5173 .
```

Öppna http://localhost:5173

## Supabase

- URL och anon key: `js/config.js` (production defaults).
- API-hjälpare: `js/supabase-api.js` (`window.tt.api`).
- Login: Supabase Auth (`login.html`).
