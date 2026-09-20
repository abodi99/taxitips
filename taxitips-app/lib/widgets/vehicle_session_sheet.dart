import 'package:flutter/material.dart';

import '../api_client.dart';
import '../theme.dart';

/// Bilvalet och skiftbytet.
///
/// Telefonen kan vara godkänd för flera bilar. Den här panelen visar dem, vem
/// som kör dem just nu, och låter föraren ta en.
///
/// **Övertagandet frågas alltid.** Servern svarar `takeover_required` när en
/// annan telefon har bilen, och först efter ett uttryckligt "Ta över bilen"
/// skickas anropet om igen med `force`. Panelen har ingen väg som hoppar över
/// frågan -- att lägga den i klienten hade betytt att en app-version kan välja
/// bort den, och det är servern som avgör.
///
/// **Ingen tyst omstart.** En förare som tappar nätet behåller bilen; det är
/// bara ett nytt, uttryckligt övertagande som flyttar den. Panelen gör därför
/// ingenting av sig själv när den öppnas.
class VehicleSessionSheet extends StatefulWidget {
  const VehicleSessionSheet({super.key, required this.api});

  final ApiClient api;

  /// Visar panelen. Returnerar true när föraren tagit en bil, så att den som
  /// öppnade den vet att flödet ska hämtas om.
  static Future<bool> show(BuildContext context, ApiClient api) async {
    final result = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: TbColors.foam,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => VehicleSessionSheet(api: api),
    );
    return result ?? false;
  }

  @override
  State<VehicleSessionSheet> createState() => _VehicleSessionSheetState();
}

class _VehicleSessionSheetState extends State<VehicleSessionSheet> {
  List<Map<String, dynamic>> _vehicles = const [];
  Map<String, dynamic>? _session;
  bool _loading = true;
  bool _busy = false;
  String? _error;

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
      final data = await widget.api.fleetStatus();
      if (!mounted) return;
      setState(() {
        _vehicles = ((data['vehicles'] as List?) ?? const [])
            .map((v) => Map<String, dynamic>.from(v as Map))
            .toList();
        _session = data['session'] == null
            ? null
            : Map<String, dynamic>.from(data['session'] as Map);
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _loading = false;
      });
    }
  }

  Future<void> _take(Map<String, dynamic> vehicle) async {
    final licenseId = vehicle['licenseId']?.toString();
    if (licenseId == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.startVehicleSession(licenseId: licenseId);
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      // Servern -- inte appen -- avgör att bilen är upptagen. Grenen går på
      // `reason`, inte på texten: en omformulering i backend ska inte kunna
      // få frågan att utebli.
      if (e.reason == 'takeover_required') {
        final confirmed = await _confirmTakeover(vehicle, e.message);
        if (confirmed == true) await _forceTake(licenseId);
        return;
      }
      setState(() => _error = e.message);
    }
  }

  Future<bool?> _confirmTakeover(Map<String, dynamic> vehicle, String message) {
    return showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Ta över ${vehicle['plate'] ?? 'bilen'}?'),
        content: Text(
          '$message\n\nDen andra telefonen slutar visa tips för den här bilen '
          'direkt.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Avbryt'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Ta över bilen'),
          ),
        ],
      ),
    );
  }

  Future<void> _forceTake(String licenseId) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.startVehicleSession(licenseId: licenseId, force: true);
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.message;
      });
    }
  }

  Future<void> _leave() async {
    setState(() => _busy = true);
    try {
      await widget.api.endVehicleSession();
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey.shade400,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'Vilken bil kör du?',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 4),
            Text(
              'Tipsen gäller bilens län. En bil kan bara ha en telefon åt gången.',
              style: TextStyle(color: Colors.grey.shade700, height: 1.3),
            ),
            const SizedBox(height: 16),
            if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 32),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_vehicles.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 16),
                child: Text(
                  'Telefonen är inte godkänd för någon bil. Be din '
                  'administratör om en anslutningskod.',
                  style: TextStyle(color: Colors.grey.shade800, height: 1.3),
                ),
              )
            else
              ..._vehicles.map(_vehicleTile),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: const TextStyle(color: Color(0xFFB3261E))),
            ],
            if (_session != null) ...[
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: _busy ? null : _leave,
                icon: const Icon(Icons.logout),
                label: const Text('Lämna bilen'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _vehicleTile(Map<String, dynamic> vehicle) {
    final mine = vehicle['isMine'] == true;
    final occupied = vehicle['occupied'] == true;
    final counties = ((vehicle['counties'] as List?) ?? const [])
        .map((c) => c.toString())
        .toList();
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        leading: Icon(
          mine ? Icons.local_taxi : Icons.directions_car_outlined,
          color: mine ? TbColors.asphalt : Colors.grey.shade600,
        ),
        title: Text(
          vehicle['plate']?.toString() ?? 'Bil',
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: Text(
          [
            if ((vehicle['label']?.toString() ?? '').isNotEmpty)
              vehicle['label'].toString(),
            if (counties.isNotEmpty) '${counties.length} län',
            if (occupied) 'Används av ${vehicle['occupiedBy'] ?? 'en annan telefon'}',
            if (mine) 'Du kör den här',
          ].join(' · '),
        ),
        trailing: mine
            ? const Icon(Icons.check_circle, color: Color(0xFF1B5E20))
            : FilledButton(
                onPressed: _busy ? null : () => _take(vehicle),
                child: Text(occupied ? 'Ta över' : 'Kör'),
              ),
      ),
    );
  }
}
