import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api_client.dart';
import '../l10n/l10n.dart';
import '../theme.dart';

/// Supportchatten: användaren skriver, TaxiTips svarar från adminwebben.
///
/// Bara text (beslut 2026-09-26). Servern avgör vems konversationen är --
/// kontot om appen är inloggad, annars telefonen -- så skärmen skickar inget
/// id som kunde bytas ut mot någon annans (fleet/support.py).
///
/// Nya svar hämtas var femte sekund medan skärmen är öppen, aldrig i
/// bakgrunden. Ett svar som kommer när appen är stängd blir en notis.
class SupportChatScreen extends StatefulWidget {
  const SupportChatScreen({super.key, required this.api});

  final ApiClient api;

  @override
  State<SupportChatScreen> createState() => _SupportChatScreenState();
}

class _SupportChatScreenState extends State<SupportChatScreen>
    with WidgetsBindingObserver {
  static const _poll = Duration(seconds: 5);
  static const _maxLength = 2000;

  final _input = TextEditingController();
  final _scroll = ScrollController();
  Timer? _timer;
  List<Map<String, dynamic>> _messages = [];
  bool _loading = true;
  bool _sending = false;
  String? _error;
  bool _foreground = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
    _timer = Timer.periodic(_poll, (_) {
      if (mounted && _foreground && !_sending) _load(silent: true);
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    if (_foreground) _load(silent: true);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    try {
      final body = await widget.api.supportConversation(markRead: true);
      if (!mounted) return;
      final rows = ((body['messages'] as List?) ?? const [])
          .whereType<Map>()
          .map((m) => Map<String, dynamic>.from(m))
          .toList();
      final grew = rows.length != _messages.length;
      setState(() {
        _messages = rows;
        _loading = false;
        _error = null;
      });
      if (grew) _scrollToEnd();
    } on ApiException catch (e) {
      if (!mounted) return;
      // En tyst omhämtning som misslyckas ska inte ersätta konversationen
      // med ett fel: nätet i en bil kommer och går.
      if (!silent || _messages.isEmpty) {
        setState(() {
          _loading = false;
          _error = e.message;
        });
      }
    } catch (_) {
      if (!mounted) return;
      if (!silent || _messages.isEmpty) {
        setState(() {
          _loading = false;
          _error = tr.supportChatLoadFailed;
        });
      }
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    setState(() => _sending = true);
    try {
      final body = await widget.api.sendSupportMessage(text);
      if (!mounted) return;
      _input.clear();
      final rows = ((body['messages'] as List?) ?? const [])
          .whereType<Map>()
          .map((m) => Map<String, dynamic>.from(m))
          .toList();
      setState(() {
        _messages = rows;
        _error = null;
      });
      _scrollToEnd();
    } on ApiException catch (e) {
      if (mounted) _snack(e.message);
    } catch (_) {
      if (mounted) _snack(tr.supportChatSendFailed);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _snack(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: TbColors.danger),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: TbColors.foam,
      appBar: AppBar(
        backgroundColor: TbColors.navy,
        foregroundColor: Colors.white,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              tr.supportChatTitle,
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            Text(
              tr.supportChatSubtitle,
              style: const TextStyle(fontSize: 12, color: Colors.white70),
            ),
          ],
        ),
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(child: _body()),
            _composer(),
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
    if (_error != null && _messages.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: TbColors.danger),
              ),
              const SizedBox(height: 12),
              OutlinedButton(
                onPressed: () {
                  setState(() => _loading = true);
                  _load();
                },
                child: Text(tr.supportChatRetry),
              ),
            ],
          ),
        ),
      );
    }
    if (_messages.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.support_agent,
                size: 56,
                color: TbColors.taxiDeep,
              ),
              const SizedBox(height: 16),
              Text(
                tr.supportChatEmptyTitle,
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                tr.supportChatEmptyBody,
                textAlign: TextAlign.center,
                style: const TextStyle(color: TbColors.muted, height: 1.35),
              ),
            ],
          ),
        ),
      );
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(12, 16, 12, 8),
      itemCount: _messages.length,
      itemBuilder: (_, i) {
        final m = _messages[i];
        final previous = i > 0 ? _messages[i - 1] : null;
        return _Bubble(
          message: m,
          showAuthor:
              m['sender'] == 'staff' &&
              (previous == null || previous['sender'] != 'staff'),
        );
      },
    );
  }

  Widget _composer() {
    return Container(
      padding: const EdgeInsetsDirectional.fromSTEB(12, 8, 8, 8),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: TbColors.line)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: TextField(
              controller: _input,
              minLines: 1,
              maxLines: 5,
              maxLength: _maxLength,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                hintText: tr.supportChatHint,
                counterText: '',
                border: InputBorder.none,
              ),
              onChanged: (_) => setState(() {}),
            ),
          ),
          IconButton.filled(
            tooltip: tr.supportChatSend,
            style: IconButton.styleFrom(
              backgroundColor: TbColors.taxi,
              foregroundColor: TbColors.ink,
              disabledBackgroundColor: TbColors.sand,
            ),
            onPressed: _input.text.trim().isEmpty || _sending ? null : _send,
            icon: _sending
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.send),
          ),
        ],
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.message, required this.showAuthor});

  final Map<String, dynamic> message;
  final bool showAuthor;

  @override
  Widget build(BuildContext context) {
    final mine = message['sender'] != 'staff';
    final when = DateTime.tryParse(
      message['createdAt']?.toString() ?? '',
    )?.toLocal();
    return Align(
      alignment: mine
          ? AlignmentDirectional.centerEnd
          : AlignmentDirectional.centerStart,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.8,
        ),
        child: Column(
          crossAxisAlignment: mine
              ? CrossAxisAlignment.end
              : CrossAxisAlignment.start,
          children: [
            if (showAuthor)
              Padding(
                padding: const EdgeInsetsDirectional.only(
                  start: 4,
                  bottom: 2,
                  top: 6,
                ),
                child: Text(
                  message['author']?.toString() ?? 'TaxiTips',
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: TbColors.muted,
                  ),
                ),
              ),
            Container(
              margin: const EdgeInsets.symmetric(vertical: 3),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: mine ? TbColors.navy : Colors.white,
                // Egna meddelanden ligger på slutsidan (höger på svenska,
                // vänster på arabiska); den lilla hörnan pekar mot kanten.
                borderRadius: BorderRadiusDirectional.only(
                  topStart: const Radius.circular(16),
                  topEnd: const Radius.circular(16),
                  bottomStart: Radius.circular(mine ? 16 : 4),
                  bottomEnd: Radius.circular(mine ? 4 : 16),
                ),
                border: mine ? null : Border.all(color: TbColors.line),
              ),
              child: SelectableText(
                message['body']?.toString() ?? '',
                style: TextStyle(
                  color: mine ? Colors.white : TbColors.ink,
                  height: 1.35,
                ),
              ),
            ),
            if (when != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Text(
                  _time(when),
                  style: const TextStyle(fontSize: 11, color: TbColors.muted),
                ),
              ),
          ],
        ),
      ),
    );
  }

  static String _time(DateTime d) {
    final now = DateTime.now();
    final hm = formatTime(d);
    if (d.year == now.year && d.month == now.month && d.day == now.day) {
      return hm;
    }
    // Svenska: "5/3 14:05" som förut. Övriga språk skriver månaden med
    // bokstäver, så att 5/3 inte läses som 3 maj.
    if (currentLanguage == 'sv') return '${d.day}/${d.month} $hm';
    return '${DateFormat.MMMd(currentLanguage).format(d)} $hm';
  }
}
