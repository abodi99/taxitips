# TaxiTips Flutter (iOS / Android / Flutter web)

Pekar mot **https://api.taxitips.se** (Coolify Supabase `supabase-taxitips`). Nycklar ligger i `lib/config.dart` — ingen `--dart-define` behövs.

## Kör

```bash
cd taxitips-app
flutter pub get
flutter run
```

## Backend

Schema/migreringar: [`../taxitips-api/supabase/migrations`](../taxitips-api/supabase/migrations)  
Worker (poller + Stripe): [`../taxitips-api/worker`](../taxitips-api/worker)
