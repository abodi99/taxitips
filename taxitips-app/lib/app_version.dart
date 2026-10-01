/// Ska appen tvinga fram en uppdatering, föreslå en, eller låta bli?
///
/// Servern bestämmer gränserna (`appVersion` i `/api/config`, satt i
/// adminwebben -- se taxitips-backend/core/app_version.py). Här finns bara
/// jämförelsen och beslutet, utan Flutter, så att båda går att testa utan en
/// telefon. `widgets/force_upgrade_overlay.dart` visar resultatet.
///
/// Tre regler som är lätta att förenkla bort:
///
/// 1. **Leden jämförs som tal.** `1.0.10` är nyare än `1.0.9`. Som text är den
///    äldre, och då låses varje förare som uppdaterat ute.
/// 2. **Byggnumret räknas bara när gränsen anger ett.** En gräns på `1.0.2`
///    uppfylls av `1.0.2+7`; annars kunde ingen byggning någonsin nå upp.
/// 3. **Allt som är okänt släpper igenom.** Misslyckat anrop, trasigt svar,
///    oläsbar version: ingen blockering. Ett avbrott på servern får inte
///    stänga ute alla förare samtidigt -- en för gammal app en stund till
///    kostar mindre än ett land utan tips.
library;

/// En version som `1.2.3` eller `1.2.3+45`.
class AppVersion implements Comparable<AppVersion> {
  const AppVersion(this.parts, [this.build]);

  final List<int> parts;
  final int? build;

  static final _pattern = RegExp(r'^\d{1,4}(\.\d{1,4}){0,3}(\+\d{1,9})?$');

  /// Null för allt som inte är en version -- anroparen ska då släppa igenom.
  static AppVersion? tryParse(String? value) {
    final text = (value ?? '').trim();
    if (!_pattern.hasMatch(text)) return null;
    final plus = text.indexOf('+');
    final core = plus < 0 ? text : text.substring(0, plus);
    final build = plus < 0 ? null : int.parse(text.substring(plus + 1));
    return AppVersion(core.split('.').map(int.parse).toList(), build);
  }

  /// Installerad version från PackageInfo: `version` + `buildNumber`.
  static AppVersion? installed(String version, String? buildNumber) {
    final build = (buildNumber ?? '').trim();
    return tryParse(build.isEmpty ? version : '$version+$build');
  }

  @override
  int compareTo(AppVersion other) {
    final width = parts.length > other.parts.length
        ? parts.length
        : other.parts.length;
    for (var i = 0; i < width; i++) {
      final a = i < parts.length ? parts[i] : 0;
      final b = i < other.parts.length ? other.parts[i] : 0;
      if (a != b) return a < b ? -1 : 1;
    }
    final a = build, b = other.build;
    if (a != null && b != null && a != b) return a < b ? -1 : 1;
    return 0;
  }

  bool isBelow(AppVersion other) => compareTo(other) < 0;

  @override
  String toString() =>
      build == null ? parts.join('.') : '${parts.join('.')}+$build';
}

/// Serverns gränser för EN plattform.
class UpgradePolicy {
  const UpgradePolicy({
    this.min,
    this.recommended,
    this.storeUrl,
    this.message,
    this.blocked = const [],
  });

  final String? min;
  final String? recommended;
  final String? storeUrl;
  final String? message;

  /// Enskilda versioner som inte får köras, även om de ligger över `min`
  /// (t.ex. en trasig release). `1.4.0` spärrar alla byggen av 1.4.0;
  /// `1.4.0+31` bara det bygget. Från Remote Config
  /// (`android_blocked_versions`, kommaseparerad).
  final List<String> blocked;

  /// Kommaseparerad lista → versioner. Tomt och skräp tas bort.
  static List<String> parseList(String? raw) => (raw ?? '')
      .split(RegExp(r'[,;\s]+'))
      .map((v) => v.trim())
      .where((v) => AppVersion.tryParse(v) != null)
      .toList();

  /// Läser `appVersion.<platform>` ur /api/config. Null om svaret saknar
  /// blocket (äldre server) eller plattformen -- då gäller ingen gräns.
  static UpgradePolicy? fromConfig(
    Map<String, dynamic>? config,
    String platform,
  ) {
    final block = config?['appVersion'];
    if (block is! Map) return null;
    final part = block[platform];
    if (part is! Map) return null;
    String? text(Object? v) {
      final s = v?.toString().trim() ?? '';
      return s.isEmpty ? null : s;
    }

    return UpgradePolicy(
      min: text(part['min']),
      recommended: text(part['recommended']),
      storeUrl: text(part['storeUrl']),
      message: text(block['message']),
    );
  }

  /// Tomma fält i [primary] fylls från [fallback]. Primär = Remote Config,
  /// reserv = `/api/config` när adminwebben eller nätet sätter annat.
  static UpgradePolicy? merge(UpgradePolicy? primary, UpgradePolicy? fallback) {
    if (primary == null && fallback == null) return null;
    String? pick(String? a, String? b) {
      final ta = (a ?? '').trim();
      if (ta.isNotEmpty) return ta;
      final tb = (b ?? '').trim();
      return tb.isEmpty ? null : tb;
    }

    final p = primary;
    final f = fallback;
    final merged = UpgradePolicy(
      min: pick(p?.min, f?.min),
      recommended: pick(p?.recommended, f?.recommended),
      storeUrl: pick(p?.storeUrl, f?.storeUrl),
      message: pick(p?.message, f?.message),
      blocked: {...?p?.blocked, ...?f?.blocked}.toList(),
    );
    if ((merged.min ?? '').isEmpty &&
        (merged.recommended ?? '').isEmpty &&
        (merged.storeUrl ?? '').isEmpty &&
        (merged.message ?? '').isEmpty &&
        merged.blocked.isEmpty) {
      return null;
    }
    return merged;
  }
}

enum UpgradeAction { none, nudge, block }

class UpgradeDecision {
  const UpgradeDecision(
    this.action, {
    this.required,
    this.storeUrl,
    this.message,
  });

  static const none = UpgradeDecision(UpgradeAction.none);

  final UpgradeAction action;

  /// Gränsen som inte är uppfylld (min vid block, recommended vid nudge).
  final String? required;
  final String? storeUrl;
  final String? message;
}

/// Beslutet. [policy] null = konfigurationen gick inte att hämta.
UpgradeDecision decideUpgrade({
  required AppVersion? installed,
  required UpgradePolicy? policy,
}) {
  if (installed == null || policy == null) return UpgradeDecision.none;
  final min = AppVersion.tryParse(policy.min);
  final recommended = AppVersion.tryParse(policy.recommended);
  final hasStore = (policy.storeUrl ?? '').isNotEmpty;
  // Spärrad version: samma väg som under `min` -- till butiken.
  final blockedHit = policy.blocked.any((raw) {
    final v = AppVersion.tryParse(raw);
    if (v == null) return false;
    return v.build == null
        ? AppVersion(installed.parts).compareTo(v) == 0
        : installed.compareTo(v) == 0 && installed.build == v.build;
  });
  if (blockedHit) {
    return UpgradeDecision(
      hasStore ? UpgradeAction.block : UpgradeAction.nudge,
      required: policy.recommended ?? policy.min,
      storeUrl: policy.storeUrl,
      message: policy.message,
    );
  }
  if (min != null && installed.isBelow(min)) {
    // En spärr utan väg till butiken är bara en utelåsning. Servern vägrar
    // redan spara en iPhone-gräns utan App Store-länk; det här är reserven
    // om länken ändå saknas i svaret.
    return UpgradeDecision(
      hasStore ? UpgradeAction.block : UpgradeAction.nudge,
      required: policy.min,
      storeUrl: policy.storeUrl,
      message: policy.message,
    );
  }
  if (recommended != null && installed.isBelow(recommended)) {
    return UpgradeDecision(
      UpgradeAction.nudge,
      required: policy.recommended,
      storeUrl: policy.storeUrl,
      message: policy.message,
    );
  }
  return UpgradeDecision.none;
}
