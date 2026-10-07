import 'package:flutter/material.dart';

import '../api_client.dart';
import '../net_status.dart';
import '../theme.dart';

/// Efter registreringen och den bekräftade koden: välj län för provet.
///
/// En plats i provet tilldelas KONTOT självt -- ingen annan behöver göra
/// något, och ingen bil behövs. Länen väljs här, och servern skapar platsen
/// och sätter länen i ett svep (`POST /api/fleet/memberships/trial`). Har
/// kontot redan en plats (t.ex. en inbjuden förare) byts länen bara.
///
/// **Inget säljs här.** Ett län ingår i provet; fler platser och fler län
/// köps och tilldelas andra konton i kundportalen, aldrig i appen
/// (lib/membership_copy.dart, §9c).
class MembershipCountyScreen extends StatefulWidget {
  const MembershipCountyScreen({
    super.key,
    required this.api,
    required this.onDone,
    this.licenseId,
  });

  final ApiClient api;
  final VoidCallback onDone;

  /// Satt när kontot redan har en plats: då byts länen på den i stället för
  /// att en ny skapas.
  final String? licenseId;

  @override
  State<MembershipCountyScreen> createState() => _MembershipCountyScreenState();
}

class _MembershipCountyScreenState extends State<MembershipCountyScreen> {
  bool _loading = true;
  bool _busy = false;
  String? _error;
  String? _picked;
  List<MapEntry<String, String>> _counties = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // Länen kommer från servern (samma lista som körområdet), inte från en
      // egen kopia i appen.
      final data = await widget.api.fleetCompany();
      final entries = <MapEntry<String, String>>[];
      for (final c in (data['countyCatalog'] as List?) ?? const []) {
        if (c is Map) {
          entries.add(
            MapEntry(c['code'].toString(), c['name']?.toString() ?? ''),
          );
        }
      }
      entries.sort((a, b) => a.value.compareTo(b.value));
      if (!mounted) return;
      setState(() {
        _counties = entries;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = _message(e);
        _loading = false;
      });
    }
  }

  String _message(Object e) {
    if (e is ApiException) return e.message;
    final net = netFailureOf(e);
    if (net != null) return netMessage(net);
    return 'Kunde inte hämta länen. Dra ner för att försöka igen.';
  }

  Future<void> _save() async {
    final code = _picked;
    if (code == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = widget.licenseId != null && widget.licenseId!.isNotEmpty
          ? await widget.api.setMembershipCounty(widget.licenseId!, code)
          : await widget.api.chooseTrialCounty(code);
      // Ta platsen i appen på en gång, så flödet använder den direkt. Ett fel
      // här är inte kritiskt; nästa start försöker igen.
      final member = result['membership'];
      final licenseId = member is Map ? member['licenseId']?.toString() : null;
      try {
        await widget.api.startMembershipSession(licenseId: licenseId);
      } catch (_) {}
      if (!mounted) return;
      widget.onDone();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = _message(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.navy,
      body: SafeArea(
        child: Column(
          children: [
            const _Header(),
            Expanded(child: _body()),
          ],
        ),
      ),
    );
  }

  Widget _body() {
    if (_loading) {
      return const Center(
        child: CircularProgressIndicator(color: TbColors.taxi),
      );
    }
    if (_error != null && _counties.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: TbColors.foam, height: 1.4),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _load,
                style: FilledButton.styleFrom(
                  backgroundColor: TbColors.taxi,
                  foregroundColor: TbColors.ink,
                ),
                child: const Text('Försök igen'),
              ),
            ],
          ),
        ),
      );
    }
    return Column(
      children: [
        Expanded(
          child: Container(
            margin: const EdgeInsets.fromLTRB(16, 0, 16, 0),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(20),
            ),
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: _counties.length,
              itemBuilder: (ctx, i) {
                final entry = _counties[i];
                final selected = entry.key == _picked;
                return ListTile(
                  title: Text(
                    entry.value,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: TbColors.ink,
                    ),
                  ),
                  trailing: selected
                      ? const Icon(Icons.check_circle, color: TbColors.live)
                      : null,
                  onTap: _busy
                      ? null
                      : () => setState(() => _picked = entry.key),
                );
              },
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              if (_error != null) ...[
                Text(
                  _error!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: TbColors.taxi,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 10),
              ],
              FilledButton(
                onPressed: _busy || _picked == null ? null : _save,
                style: FilledButton.styleFrom(
                  backgroundColor: TbColors.taxi,
                  foregroundColor: TbColors.ink,
                  minimumSize: const Size.fromHeight(54),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
                child: _busy
                    ? const SizedBox(
                        height: 22,
                        width: 22,
                        child: CircularProgressIndicator(
                          color: TbColors.ink,
                          strokeWidth: 2.5,
                        ),
                      )
                    : const Text(
                        'Fortsätt',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _Header extends StatelessWidget {
  const _Header();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.fromLTRB(24, 28, 24, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Var vill du köra?',
            style: TextStyle(
              fontFamily: kDisplayFont,
              color: Colors.white,
              fontSize: 26,
              fontWeight: FontWeight.w800,
            ),
          ),
          SizedBox(height: 8),
          Text(
            'Välj länet där du kör mest. Du får ett län i provet, och kan byta '
            'senare. Provet börjar när du öppnar appen.',
            style: TextStyle(color: TbColors.foam, fontSize: 15, height: 1.4),
          ),
        ],
      ),
    );
  }
}
