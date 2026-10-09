/// Hur appen talar om medlemskapet -- på ETT ställe.
///
/// **Appen säljer ingenting.** Inga priser, inga köpknappar, inga uppmaningar
/// att köpa utanför butikerna (Apple 3.1.1 och 3.1.3(c) Enterprise Services,
/// Google Play Payments; docs/fleet-abonnemang.md §9c).
///
/// Företagets administratör (inloggad ägare/admin med session) får en genväg
/// till kundportalen för att *hantera företagskontot* — bilar, fakturor och
/// medlemmar. Det är kontostyrning på webben, inte en konsument-CTA att
/// "prenumerera billigare utanför butiken". Förare ser bara neutral text
/// utan länk.
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
/// Visas för förare och i låsta lägen — inte som köpuppmaning.
const kMembershipOnWeb =
    'Ditt företags administratör hanterar medlemskapet på webben.';

/// Raden om fakturor och medlemskap när användaren inte är admin (ingen länk).
const kInvoicesOnWeb =
    'Fakturor och medlemskap hanteras av företagets administratör på webben.';

/// Båda meningarna: det som visas där något är låst.
const kNotInTrialNote = '$kNotInTrial $kMembershipOnWeb';

/// En kategori som ett beviljat medlemskap inte omfattar. Ett beviljande
/// (fleet/grants.py) kan öppna bara vissa kategorier; det är inget prov, och
/// "Ingår inte i provet" vore då fel. Servern kallar planen `grant`.
const kNotInMembership = 'Ingår inte i ditt medlemskap.';

/// Den korta låsraden efter serverns plan (`features.plan`). Okänd eller
/// saknad plan = provet, som var den enda låsta planen före beviljandena.
String notIncludedFor(Object? plan) =>
    plan == 'grant' ? kNotInMembership : kNotInTrial;

/// Hela låstexten efter serverns plan: raden plus vem som sköter medlemskapet.
String lockedNoteFor(Object? plan) => '${notIncludedFor(plan)} $kMembershipOnWeb';

/// Inställningarnas hänvisning för fakturor och medlemskap (förare / footer).
/// Ingen länk, inget pris, ingen knapp -- bara var det sköts.
const kBillingOnWeb =
    'Fakturor och medlemskap hanteras av företagets administratör på webben.';

/// Rubrik på admin-genvägen till kundportalen (Inställningar → Företaget).
/// Formulerad som kontohantering, inte köp.
const kPortalAccountTitle = 'Hantera företagskonto';

/// Underrad till [kPortalAccountTitle]. Inget om att köpa, prenumerera eller pris.
const kPortalAccountSubtitle =
    'Öppnar kundportalen på webben: bilar, fakturor och medlemmar.';

/// Skäl (`access.reason`, fleet/access.py) som handlar om betalning eller
/// avtal. Deras serverstext visas inte; appen använder [membershipNotice].
const _billingReasons = {
  'trial_ended',
  'period_expired',
  'past_due',
  'canceled',
  'no_subscription',
  // Pausat av TaxiTips för att medlemskapet inte betalas (fleet/accounts.py).
  // Samma neutrala besked: inget pris, ingen länk, ingen uppmaning att betala.
  'company_paused',
  'account_paused',
};

/// Besked när provperioden är slut. Pekar på webben utan länk.
const kTrialEndedNotice = 'Provperioden är slut. $kMembershipOnWeb';

/// Besked när medlemskapet är pausat (företaget eller kontot).
const kPausedNotice = 'Medlemskapet är pausat. $kMembershipOnWeb';

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
  if (reason == 'trial_ended') return kTrialEndedNotice;
  if (reason == 'company_paused' || reason == 'account_paused') {
    return kPausedNotice;
  }
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
