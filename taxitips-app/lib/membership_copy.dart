/// Hur appen talar om medlemskapet -- på ETT ställe.
///
/// **Appen säljer ingenting.** Inga priser, inga köpknappar, inga länkar eller
/// uppmaningar som leder till en betalning utanför butikerna (Apple 3.1.1 och
/// 3.1.3, Google Play Payments; docs/fleet-abonnemang.md §9c). Medlemskap sköts
/// av företagets administratör på webben, och appen säger bara det: neutral
/// text, ingen länk.
///
/// Texterna här är appens egna. Serverns meddelanden om åtkomst (`message`)
/// kan innehålla en uppmaning ("Uppdatera betalmetoden", "Kontakta TaxiTips för
/// att fortsätta"); de visas därför aldrig rakt av för skäl som handlar om
/// betalning -- se [membershipNotice].
library;

import 'signal_kinds.dart';

/// En kategori eller funktion som provet inte omfattar.
const kNotInTrial = 'Ingår inte i provet.';

/// Vem som sköter medlemskapet. Ingen länk, inget pris, ingen knapp.
const kMembershipOnWeb =
    'Ditt företags administratör hanterar medlemskapet på webben.';

/// Raden om fakturor och medlemskap i Inställningar (ägare). Ingen länk, ingen
/// knapp, inget pris: bara vem som sköter det.
const kInvoicesOnWeb =
    'Fakturor och medlemskap hanteras av företagets administratör på webben.';

/// Båda meningarna: det som visas där något är låst.
const kNotInTrialNote = '$kNotInTrial $kMembershipOnWeb';

/// Skäl (`access.reason`, fleet/access.py) som handlar om betalning eller
/// avtal. Deras serverstext visas inte; appen använder [membershipNotice].
const _billingReasons = {
  'trial_ended',
  'period_expired',
  'past_due',
  'canceled',
  'no_subscription',
};

/// Handlar skälet om medlemskap (prov slut, period slut, betalning, uppsagt)?
bool isMembershipReason(String? reason) => _billingReasons.contains(reason);

/// Texten när åtkomsten inte gäller. Skäl som handlar om medlemskap får
/// appens neutrala text; övriga (spärrat konto, ingen bil vald …) får serverns
/// egen text, eller [fallback] när den saknas.
String membershipNotice(
  String? reason, {
  String? serverMessage,
  String fallback = 'Åtkomsten är inte aktiv.',
}) {
  if (reason == 'trial_ended') return 'Provperioden är slut. $kMembershipOnWeb';
  if (_billingReasons.contains(reason)) {
    return 'Medlemskapet är inte aktivt just nu. $kMembershipOnWeb';
  }
  final message = serverMessage?.trim() ?? '';
  return message.isEmpty ? fallback : message;
}

/// Kategorin bakom en nyckel i serverns `features` (fleet/features.py).
/// Servern kallar evenemangen `events`; kartan och kategoriraden `event`.
SignalCategory? signalCategoryFromFeatureKey(Object? key) =>
    signalCategoryFromKey(key == 'events' ? 'event' : key?.toString());
