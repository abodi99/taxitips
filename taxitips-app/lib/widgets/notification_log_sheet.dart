import 'package:flutter/material.dart';

import '../api_client.dart';
import '../theme.dart';

/// "Vilka notiser har jag fått?" -- läst ur `push_delivery`, en rad per
/// skickad notis och enhet.
///
/// Listan räknas medvetet INTE fram på nytt ur tipsflödet. En lista över
/// "vad du borde ha fått" hade svarat på en annan fråga än förarens, och
/// skulle skrivas om retroaktivt varje gång någon rörde ett reglage i
/// notisinställningarna. Det här är historik: vad som faktiskt skickades,
/// när, och till den här telefonen.
///
/// Varje rad bär också tipset som det såg ut när notisen gick
/// (`opportunity`-ögonblicksbilden). Därför fungerar listan även efter att
/// tipset gallrats ur databasen efter sju dagar -- den visar då `purged`
/// i stället för ett tomt kort.
class NotificationLogSheet extends StatefulWidget {
  const NotificationLogSheet({
    super.key,
    required this.api,
    this.onOpenOpportunity,
  });

  final ApiClient api;

  /// Öppnar tipset bakom notisen, när det fortfarande finns.
  final void Function(String opportunityId)? onOpenOpportunity;

  @override
  State<NotificationLogSheet> createState() => _NotificationLogSheetState();
}

class _NotificationLogSheetState extends State<NotificationLogSheet> {
  bool _loading = true;
  String? _error;
  String? _reason;
  String? _hint;
  List<Map<String, dynamic>> _rows = const [];

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
      final data = await widget.api.notifications();
      if (!mounted) return;
      setState(() {
        _rows = (data['notifications'] as List?)?.cast<Map<String, dynamic>>() ??
            const [];
        _reason = data['reason']?.toString();
        _hint = data['hint']?.toString();
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString().replaceFirst(
          RegExp(r'^(ApiException|Exception):\s*'),
          '',
        );
      });
    }
  }

  Future<void> _toggleFavorite(Map<String, dynamic> row) async {
    final id = row['opportunity_id']?.toString();
    if (id == null || id.isEmpty) return;
    final next = row['is_favorite'] != true;
    setState(() => row['is_favorite'] = next);
    try {
      await widget.api.setFavorite(opportunityId: id, favorite: next);
    } catch (_) {
      if (!mounted) return;
      setState(() => row['is_favorite'] = !next);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Kunde inte spara tipset')),
      );
    }
  }

  String _when(String? iso) {
    if (iso == null) return '';
    final dt = DateTime.tryParse(iso)?.toLocal();
    if (dt == null) return '';
    final age = DateTime.now().difference(dt);
    if (age.inMinutes < 1) return 'Just nu';
    if (age.inMinutes < 60) return 'För ${age.inMinutes} min sedan';
    if (age.inHours < 24) return 'För ${age.inHours} tim sedan';
    return '${dt.day}/${dt.month} ${dt.hour.toString().padLeft(2, '0')}:'
        '${dt.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.88,
      minChildSize: 0.5,
      maxChildSize: 0.95,
      builder: (context, scroll) {
        if (_loading) {
          return const Center(
            child: CircularProgressIndicator(color: TbColors.taxi),
          );
        }
        return ListView(
          controller: scroll,
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                margin: const EdgeInsets.only(bottom: 14),
                decoration: BoxDecoration(
                  color: Colors.grey.shade400,
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            ),
            const Text(
              'Mina notiser',
              style: TextStyle(
                fontSize: 26,
                fontWeight: FontWeight.w700,
                color: TbColors.ink,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'Notiser som skickats till den här telefonen. Stjärnmarkera '
              'en för att spara den — sparade tips ligger kvar överst i '
              'listan även när filtren gömmer resten.',
              style: TextStyle(
                fontSize: 14,
                height: 1.4,
                color: Colors.grey.shade700,
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: const TextStyle(
                  color: TbColors.danger,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
            const SizedBox(height: 16),
            // "Ingen parad telefon" är ett annat svar än "du har inte fått
            // några notiser än", och en tom lista utan förklaring hade
            // blandat ihop dem. Notiser går till enheter -- en ägare som
            // loggat in på webben har per definition inte fått några.
            if (_reason == 'no_device' || _reason == 'no_backend')
              _EmptyNote(
                title: _reason == 'no_backend'
                    ? 'Notishistorik kräver backend'
                    : 'Ingen parad telefon',
                body: _hint ??
                    'Notiser skickas till en parad enhet. Den här '
                        'inloggningen har ingen.',
              )
            else if (_rows.isEmpty)
              const _EmptyNote(
                title: 'Inga notiser än',
                body: 'Notiser skickas bara för störningar som är värda att '
                    'avbryta för. Är det lugnt i dina län hör du inget — '
                    'och det är meningen.',
              )
            else
              for (final row in _rows) ...[
                _NotificationTile(
                  title: row['title']?.toString() ?? '',
                  body: row['body']?.toString() ?? '',
                  when: _when(row['sentAt']?.toString()),
                  isFavorite: row['is_favorite'] == true,
                  purged: row['purged'] == true,
                  onToggleFavorite: row['purged'] == true
                      ? null
                      : () => _toggleFavorite(row),
                  onTap: row['purged'] == true ||
                          widget.onOpenOpportunity == null
                      ? null
                      : () {
                          final id = row['opportunity_id']?.toString();
                          if (id == null) return;
                          Navigator.pop(context);
                          widget.onOpenOpportunity!(id);
                        },
                ),
                const SizedBox(height: 8),
              ],
          ],
        );
      },
    );
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({
    required this.title,
    required this.body,
    required this.when,
    required this.isFavorite,
    required this.purged,
    this.onToggleFavorite,
    this.onTap,
  });

  final String title;
  final String body;
  final String when;
  final bool isFavorite;
  final bool purged;
  final VoidCallback? onToggleFavorite;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: TbColors.ink,
                      ),
                    ),
                    if (body.isNotEmpty) ...[
                      const SizedBox(height: 3),
                      Text(
                        body,
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 13,
                          height: 1.35,
                          color: Colors.grey.shade700,
                        ),
                      ),
                    ],
                    const SizedBox(height: 5),
                    Row(
                      children: [
                        Text(
                          when,
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: Colors.grey.shade600,
                          ),
                        ),
                        // Tipset finns inte kvar i databasen, men notisen
                        // gör det. Ärligare än ett kort som öppnar tomt.
                        if (purged) ...[
                          const SizedBox(width: 8),
                          Text(
                            '· arkiverad',
                            style: TextStyle(
                              fontSize: 12,
                              color: Colors.grey.shade500,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
              if (onToggleFavorite != null)
                IconButton(
                  onPressed: onToggleFavorite,
                  icon: Icon(
                    isFavorite ? Icons.star : Icons.star_border,
                    color: isFavorite ? TbColors.taxi : TbColors.muted,
                  ),
                  tooltip: isFavorite ? 'Ta bort från sparade' : 'Spara tipset',
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyNote extends StatelessWidget {
  const _EmptyNote({required this.title, required this.body});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TbColors.ljusgraDjup,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              fontSize: 15,
              color: TbColors.ink,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            body,
            style: TextStyle(
              fontSize: 13,
              height: 1.4,
              color: Colors.grey.shade700,
            ),
          ),
        ],
      ),
    );
  }
}
