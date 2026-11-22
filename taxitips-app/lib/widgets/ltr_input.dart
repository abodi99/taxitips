import 'package:flutter/widgets.dart';

/// Mobilnummer, e-post och lösenord skrivs alltid vänster till höger, också på
/// arabiska. Annars ritas "070 123 45 67" och "namn@gmail.com" i fel ordning
/// medan man skriver, och markören hoppar. Texten ligger ändå på samma sida
/// som etiketten och ikonen: till höger på arabiska, till vänster annars.
const TextDirection kLtrInputDirection = TextDirection.ltr;

TextAlign ltrInputAlign(BuildContext context) =>
    Directionality.of(context) == TextDirection.rtl
    ? TextAlign.right
    : TextAlign.left;

/// Ett mobilnummer eller en e-postadress mitt i arabisk text ritas annars i
/// fel ordning ("070 123 45 67" blir "67 45 123 070"). Den här lägger varje
/// sådan bit inom vänster-till-höger-markeringar (LRI ... PDI). Texten i
/// översättningsfilerna hålls fri från osynliga tecken; det görs här, när
/// texten visas. Ingen skillnad för svenska och engelska.
String ltrRuns(String text) => text.replaceAllMapped(
  RegExp(r'[0-9A-Za-z+][0-9A-Za-z@._+\- ]*[0-9A-Za-z]'),
  (m) {
    final run = m[0]!;
    // Bara nummer och adresser, inte vanliga latinska ord som "BankID".
    if (!RegExp(r'\d|@').hasMatch(run)) return run;
    return '\u2066$run\u2069';
  },
);
