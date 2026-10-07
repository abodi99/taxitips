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

  /// Django-backendens bas-URL (taxitips-backend, Spår B). Tom = appen läser
  /// tips via Supabase-RPC:erna som förut.
  ///
  /// Bara tipsflödet flyttar: inloggning, bolag, enheter och Stripe ligger
  /// kvar i Supabase. Det som byter väg är det som pipelinen numera räknar ut
  /// i Python -- lista, förklaring och feedback -- så att bedömningen görs på
  /// ett ställe i stället för i plpgsql och Dart parallellt.
  ///
  ///   flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000
  static const apiBaseUrl = String.fromEnvironment('API_BASE_URL');

  static bool get usesDjangoApi => apiBaseUrl.isNotEmpty;

  /// Den interaktiva demon på webben. Appen har ingen egen demo längre --
  /// startskärmen öppnar den här sidan i telefonens webbläsare. `app=1`
  /// döljer demons knappar till registrering och kontakt (src/demo/main.js):
  /// appen leder inte vidare till något köp (membership_copy.dart).
  static const demoUrl = 'https://taxitips.se/demo?app=1';

  /// Kundportalen där företagets administratör hanterar kontot (bilar,
  /// fakturor, medlemmar). Bara synlig för inloggad ägare/admin i
  /// Inställningar — inte en köpväg för förare (membership_copy.dart).
  ///
  ///   flutter run --dart-define=PORTAL_URL=https://portal.taxitips.se
  static const portalUrl = String.fromEnvironment(
    'PORTAL_URL',
    defaultValue: 'https://portal.taxitips.se',
  );
}
