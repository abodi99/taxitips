import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Enhetens hemlighet -- den enda credential som bevisar vilken telefon detta
/// är för servern.
///
/// **Varför inte shared_preferences.** Den skriver en klartextfil i appens
/// datakatalog. På en rootad eller jailbreakad telefon, i en backup, eller för
/// en annan app med filåtkomst är hemligheten då läsbar. Keychain (iOS) och
/// Android Keystore (AES-GCM med RSA-inpackad nyckel, standardläget i
/// flutter_secure_storage 11) är plattformarnas egna svar på precis det
/// problemet, och uppdraget kräver att de används.
///
/// **Flytten sker automatiskt och en gång.** En telefon som redan är
/// parkopplad har sin token i shared_preferences. Första gången appen startar
/// efter uppdateringen flyttas den in i säker lagring och tas bort ur den
/// gamla. Att i stället kräva ny parkoppling hade låst ute varje befintlig
/// förare -- och det är just den sortens oannonserade utelåsning som inte får
/// hända.
///
/// **Läsning kan misslyckas.** Keychain är otillgänglig innan telefonen låsts
/// upp första gången efter en omstart, och Androids krypterade lagring kan
/// kasta efter en återställd backup. Varje anrop fångar därför felet och
/// svarar null i stället för att krascha appen -- men skriver ALDRIG tillbaka
/// till den osäkra lagringen som fallback.
class DeviceCredentialStore {
  DeviceCredentialStore({FlutterSecureStorage? storage})
    : _storage =
          storage ??
          const FlutterSecureStorage(
            // AndroidOptions utan argument är Keystore-läget i v11 (AES-GCM,
            // RSA-inpackad nyckel). Den gamla `encryptedSharedPreferences`-
            // flaggan finns inte längre -- den var v9:s sätt att välja just
            // det här, och är nu standard.
            aOptions: AndroidOptions(),
            iOptions: IOSOptions(
              // Hemligheten behövs bara när föraren använder telefonen, och
              // ska inte följa med till en ny enhet via iCloud-backup.
              accessibility: KeychainAccessibility.first_unlock_this_device,
            ),
          );

  final FlutterSecureStorage _storage;

  static const _secureKey = 'tt_device_secret';
  static const _legacyKey = 'tb_device';
  static const _schemeKey = 'tt_credential_scheme';

  String? _cached;

  /// Hemligheten, eller null om telefonen inte är parkopplad.
  Future<String?> read() async {
    if (_cached != null && _cached!.isNotEmpty) return _cached;
    try {
      final value = await _storage.read(key: _secureKey);
      if (value != null && value.isNotEmpty) {
        _cached = value;
        return value;
      }
    } catch (e) {
      debugPrint('DeviceCredentialStore: kunde inte läsa säker lagring: $e');
      // Faller igenom till flytten nedan: en telefon som ännu inte flyttats
      // ska fortfarande fungera.
    }
    return _migrateFromPreferences();
  }

  Future<void> write(String secret, {String scheme = 'hashed_v1'}) async {
    _cached = secret;
    await _storage.write(key: _secureKey, value: secret);
    await _storage.write(key: _schemeKey, value: scheme);
    // Den gamla platsen töms i samma andetag: två kopior av en hemlighet är
    // en kopia för mycket.
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_legacyKey);
  }

  Future<void> clear() async {
    _cached = null;
    try {
      await _storage.delete(key: _secureKey);
      await _storage.delete(key: _schemeKey);
    } catch (e) {
      debugPrint('DeviceCredentialStore: kunde inte rensa säker lagring: $e');
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_legacyKey);
  }

  /// `hashed_v1` för en telefon som parkopplats med engångskod,
  /// `legacy_plaintext` för en som flyttats in från den gamla lagringen.
  Future<String> scheme() async {
    try {
      return await _storage.read(key: _schemeKey) ?? 'legacy_plaintext';
    } catch (_) {
      return 'legacy_plaintext';
    }
  }

  Future<String?> _migrateFromPreferences() async {
    final prefs = await SharedPreferences.getInstance();
    final legacy = prefs.getString(_legacyKey);
    if (legacy == null || legacy.isEmpty) return null;
    try {
      await _storage.write(key: _secureKey, value: legacy);
      await _storage.write(key: _schemeKey, value: 'legacy_plaintext');
      await prefs.remove(_legacyKey);
      _cached = legacy;
      debugPrint('DeviceCredentialStore: flyttade token till säker lagring.');
    } catch (e) {
      // Säker lagring är otillgänglig just nu (t.ex. låst telefon efter
      // omstart). Token ligger kvar där den låg och flyttas nästa gång --
      // hellre det än att föraren står utan flöde mitt i ett skift.
      debugPrint('DeviceCredentialStore: flytt misslyckades, försöker igen: $e');
      _cached = legacy;
    }
    return legacy;
  }
}
