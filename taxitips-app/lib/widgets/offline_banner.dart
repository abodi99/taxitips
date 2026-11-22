import 'package:flutter/material.dart';

import '../l10n/l10n.dart';
import '../net_status.dart';
import '../theme.dart';

/// Liten, lugn remsa när nätet är nere. Ersätter inte innehållet: tipsen
/// under visas kvar och märks som gamla.
///
/// Texten säger aldrig att något är "live". Med data: "Offline – visar
/// senaste tips från 12:04". Utan data: bara vad som är fel.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({
    super.key,
    required this.failure,
    this.lastUpdated,
    this.retrying = false,
    this.onRetry,
  });

  final NetFailure failure;

  /// När tipsen som visas hämtades. Null = inga tips att visa.
  final DateTime? lastUpdated;
  final bool retrying;
  final VoidCallback? onRetry;

  /// Bannertexten. Publik för test.
  static String textFor(NetFailure failure, DateTime? lastUpdated) {
    if (lastUpdated == null) return netMessage(failure);
    final at = clockLabel(lastUpdated);
    return switch (failure) {
      NetFailure.offline => tr.offlineBannerOffline(at),
      NetFailure.unreachable => tr.offlineBannerUnreachable(at),
      NetFailure.timeout => tr.offlineBannerTimeout(at),
    };
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Material(
        color: TbColors.vit,
        elevation: 3,
        shadowColor: Colors.black26,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsetsDirectional.fromSTEB(14, 4, 6, 4),
          child: Row(
            children: [
              const Icon(Icons.cloud_off, size: 18, color: TbColors.skiffer),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  textFor(failure, lastUpdated),
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: TbColors.ink,
                  ),
                ),
              ),
              if (retrying)
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 12),
                  child: SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                )
              else if (onRetry != null)
                TextButton(
                  onPressed: onRetry,
                  child: Text(
                    tr.offlineBannerRetry,
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
