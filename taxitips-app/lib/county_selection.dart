import 'package:shared_preferences/shared_preferences.dart';

/// Förarens körområde i appen mot licensens län.
///
/// **Licensens län är rättigheten, förarens val får bara smala av.** Valet
/// sparas som en mängd länskoder där en TOM mängd betyder "alla licensens
/// län" -- då följer ett län som admin lägger till med automatiskt.
///
/// När valet är snävare sparas också vilka län licensen hade när valet
/// gjordes ([CountySelectionStore.licensedKey]). Med den anteckningen går det
/// att skilja ett län föraren valt bort från ett som tillkommit sedan dess --
/// exakt samma regel som servern använder för telefonens notisområde
/// (`fleet/device_prefs.align_prefs_to_entitlement`). Utan den låg ett gammalt
/// val med ETT län kvar i appen när admin gav medlemskapet tre, och listan
/// visade bara det första (2026-10-09).

/// Valet efter att licensens län ändrats.
///
/// * [chosen] tom = alla licensens län, och förblir så.
/// * Län som inte längre ingår tas bort.
/// * Län som tillkommit sedan valet gjordes ([recorded]) läggs till.
/// * Saknas anteckningen gäller hela licensen -- samma som servern gör med
///   ett val från före anteckningen.
/// * Blir inget kvar, eller omfattar valet hela licensen, blir svaret tomt
///   (alla).
///
/// Okänd licens ([licensed] tom) rör ingenting.
Set<String> reconcileCounties({
  required Set<String> chosen,
  required Set<String> licensed,
  Set<String>? recorded,
}) {
  if (licensed.isEmpty) return {...chosen};
  if (chosen.isEmpty) return <String>{};
  if (recorded == null) return <String>{};
  final kept = chosen.intersection(licensed)
    ..addAll(licensed.difference(recorded));
  if (kept.isEmpty || kept.containsAll(licensed)) return <String>{};
  return kept;
}

/// Är länet förbockat? Tomt val = alla licensens län.
bool countyChecked(Set<String> chosen, String code) =>
    chosen.isEmpty || chosen.contains(code);

/// Ett tryck på ett läns kryssruta.
///
/// Med känd licens ([licensed] icke-tom) räknas valet mot licensens län: att
/// kryssa ur ett län ur "alla" ger resten, och att kryssa i det sista ger
/// "alla" (tomt) igen. Det sista förbockade länet går inte att kryssa ur --
/// ett körområde utan län ger ingen lista och inga notiser.
///
/// Utan känd licens (bolag som inte är på licensmodellen) gäller den gamla
/// regeln: valet är precis de län som kryssats i.
Set<String> toggleCounty({
  required Set<String> chosen,
  required String code,
  required bool on,
  Set<String>? licensed,
}) {
  if (licensed == null || licensed.isEmpty) {
    final next = {...chosen};
    on ? next.add(code) : next.remove(code);
    return next;
  }
  final effective = chosen.isEmpty
      ? {...licensed}
      : chosen.intersection(licensed);
  on ? effective.add(code) : effective.remove(code);
  if (effective.isEmpty) return {...chosen};
  if (effective.containsAll(licensed)) return <String>{};
  return effective;
}

/// Kommunerna som får ligga kvar: bara i län som ingår i valet (tomt val =
/// alla licensens län).
Set<String> keepMunicipalities(
  Set<String> municipalities, {
  required Set<String> chosen,
  required Set<String> licensed,
}) {
  final area = chosen.isNotEmpty ? chosen : licensed;
  if (area.isEmpty) return {...municipalities};
  return {
    for (final m in municipalities)
      if (m.length >= 2 && area.contains(m.substring(0, 2))) m,
  };
}

/// Länen som ska skickas till servern som telefonens notisområde: valet,
/// eller hela licensen när valet är "alla".
List<String>? countiesForServer(Set<String> chosen, Set<String>? licensed) {
  if (chosen.isNotEmpty) return chosen.toList()..sort();
  if (licensed == null || licensed.isEmpty) return null;
  return licensed.toList()..sort();
}

/// Valet som det ligger på telefonen.
class StoredCountySelection {
  const StoredCountySelection({
    required this.counties,
    required this.municipalities,
    this.licensed,
  });

  final Set<String> counties;
  final Set<String> municipalities;

  /// Licensens län när valet sparades. Null = okänt (val från en äldre app).
  final Set<String>? licensed;
}

/// Samma nycklar som förarskärmen alltid använt, så att ett sparat val inte
/// tappas. Inställningarna och förarskärmen läser och skriver samma ställe.
class CountySelectionStore {
  static const countiesKey = 'tb_filter_counties';
  static const municipalitiesKey = 'tb_filter_municipalities';
  static const licensedKey = 'tb_filter_counties_licensed';

  static Future<StoredCountySelection> load() async {
    final prefs = await SharedPreferences.getInstance();
    final licensed = prefs.getStringList(licensedKey);
    return StoredCountySelection(
      counties: (prefs.getStringList(countiesKey) ?? const []).toSet(),
      municipalities: (prefs.getStringList(municipalitiesKey) ?? const [])
          .toSet(),
      licensed: licensed?.toSet(),
    );
  }

  static Future<void> save({
    required Set<String> counties,
    required Set<String> municipalities,
    Set<String>? licensed,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(countiesKey, counties.toList()..sort());
    await prefs.setStringList(
      municipalitiesKey,
      municipalities.toList()..sort(),
    );
    if (licensed != null && licensed.isNotEmpty) {
      await prefs.setStringList(licensedKey, licensed.toList()..sort());
    }
  }
}

/// Samma län i båda? Null är bara lika med null.
bool sameCounties(Set<String>? a, Set<String>? b) {
  if (a == null || b == null) return a == null && b == null;
  return a.length == b.length && a.containsAll(b);
}
