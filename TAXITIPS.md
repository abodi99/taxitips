# TaxiTips monorepo layout

```
labb/
  taxitips-api/     # Supabase migrations + worker
  taxitips-web/     # Landing, admin, company portal (taxitips.se)
  taxitips-app/     # Flutter
```

## Production

| Tjänst | URL |
|--------|-----|
| Webb | https://taxitips.se |
| Supabase API (Kong) | https://api.taxitips.se |
| Coolify service | `supabase-taxitips` (`kjrcb9ghbpegwyyxb05vjo66`) |

Klienter (`taxitips-app`, `taxitips-web`) har anon key och API-URL inbakade — kör utan `--dart-define`.

Migreringar: `taxitips-api/supabase/ALL_MIGRATIONS.sql` (klistra in i Studio om ej kört).
