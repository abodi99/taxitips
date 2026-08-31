/// TaxiTips Supabase — defaults to production (Coolify supabase-taxitips).
/// Override for local dev with:
///   flutter run --dart-define=SUPABASE_URL=http://127.0.0.1:54321 --dart-define=SUPABASE_ANON_KEY=... (anon key from `supabase status`)
class TaxiTipsConfig {
  TaxiTipsConfig._();

  static const supabaseUrl = String.fromEnvironment(
    'SUPABASE_URL',
    defaultValue: 'https://api.taxitips.se',
  );

  static const supabaseAnonKey = String.fromEnvironment(
    'SUPABASE_ANON_KEY',
    defaultValue:
        'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJzdXBhYmFzZSIsImlhdCI6MTc4NzQ2Nzk4MCwiZXhwIjo0OTQzMTQxNTgwLCJyb2xlIjoiYW5vbiJ9.wxFoFcVxscjp0h4UlqltO-uBaH-EFiTIECWzyxovuzI',
  );
}
