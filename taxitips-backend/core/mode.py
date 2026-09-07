"""
Klassificerar vilket färdsätt en störning gäller.

Port av worker/src/mode.js. Explicit, egen signal -- inte begravd i
poängsättningen -- eftersom en stoppad tåglinje är en kategoriskt annan
allvarlighetsgrad än en försenad buss, och båda måste kunna skiljas åt
innan poängsättning, inte klumpas ihop i samma hink.

Route type (GTFS static route_type) vore den strukturellt korrekta
signalen, men Trafiklab-porten konsumerar bara GTFS-RT-flödet, som saknar
route_type. Faller tillbaka på nyckelordsmatchning i text/linje-id:n tills
den statiska GTFS-datan är inläst. Returnerar "unknown" hellre än att
gissa när varken tåg- eller bussord matchar.
"""

from __future__ import annotations

import re

from core.taxi_relevance import is_road_alert

_BOILERPLATE_RE = re.compile(
    r"(anslutande tåg eller buss\w*|se .{0,20}app(en)? eller reseplanerare|"
    r"för beräknad avgångstid[^.]*\.|läs mer på \S+)",
    re.IGNORECASE,
)

_SV = "a-zà-öø-ÿ0-9"

# Svenska ordformer (tåget/tågen/tågets, bussen/bussar/...) fäster ändelser
# direkt på stammen, så matcha bara en inledande ordgräns, inte en
# avslutande -- \btåg\b skulle missa "Tåget är inställt" helt.
TRAIN_RE = re.compile(
    rf"(?<![{_SV}])(tåg|påga|pågatåg|öresundståg|krösatåg|kustpilen|pendeltåg|"
    r"spårvagn|spårfel|spårarbete)"
)
BUS_RE = re.compile(rf"(?<![{_SV}])(buss|regionbuss|citybuss|stadsbuss|ersättningsbuss)")

# En buss nämnd som ERSÄTTARE betyder att det trasiga är spåret: "Inställd
# - Buss ersätter" är ett inställt tåg, och att kalla det en buss skulle
# släppa ut det ur den järnvägsallvarlighetsgren som finns just för
# strandsatta resenärer. Kontrolleras före header-vinner-regeln nedan.
_REPLACEMENT_RE = re.compile(
    r"(ersättningsbuss|buss(ar)? ersätter|ersätter (spårvagn|tåg)|ersättningstrafik)",
    re.IGNORECASE,
)


def classify_mode(alert: dict) -> str:
    if is_road_alert(alert):
        return "road"

    # En källa som anger färdsätt rakt av slår all gissning på svensk prosa.
    # SL publicerar transport_mode per påverkad linje (BUS/METRO/TRAIN/TRAM/
    # SHIP) -- använd den när den finns. "metro"/"tram" är nya värden
    # nyckelordsvägen aldrig kan producera.
    mode_hint = alert.get("mode_hint")
    if mode_hint:
        return mode_hint

    header = str(alert.get("header") or "").lower()
    body = _BOILERPLATE_RE.sub(" ", str(alert.get("description") or "").lower())
    text = f"{header} {body} {' '.join(alert.get('routes') or [])}".lower()

    if _REPLACEMENT_RE.search(f"{header} {body}"):
        return "train"

    if BUS_RE.search(header) and not TRAIN_RE.search(header):
        return "bus"
    if TRAIN_RE.search(header) and not BUS_RE.search(header):
        return "train"

    if TRAIN_RE.search(text):
        return "train"
    if BUS_RE.search(text):
        return "bus"
    return "unknown"
