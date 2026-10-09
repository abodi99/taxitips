"""
Push-steget: vilket tips som får väcka en telefon, och vilkens.

Det här är den saknade halvan. Klientsidan har kunnat registrera en
FCM-token sedan länge (push_service.dart), och notisinställningarna har
gått att ställa in i appen (NotifyPrefsSheet) -- men ingenting har läst dem
och skickat något. `taxitips-api/worker/src/fcmPush.js` gjorde det en gång
mot Supabase; den workern pensioneras, och logiken hör hemma här, bredvid
poängsättningen som avgör vad som är värt att skicka.

Tre grindar, i den ordningen -- och ordningen är inte godtycklig
------------------------------------------------------------------
1. **Är tipset värt att avbryta någon för alls?** `thresholds.is_notify_worthy`.
   Gäller alla, går inte att slå på. En förare ska inte kunna konfigurera
   fram en notis om att en buss är fyra minuter sen.
2. **Vill den här föraren ha just den här sortens notis?** notify_prefs.types.
3. **Kör föraren där?** notify_prefs.regions (län) och .cities (ort).

Grind 1 före 2 och 3 av en praktisk anledning: den är samma för alla och
kan därför köras som ett SQL-filter över hela tabellen, medan 2 och 3 kräver
en jämförelse per enhet.

Varför län är huvudfiltret och ort en förfining
------------------------------------------------
Mätt på 506 aktiva tips i den lokala databasen: **alla 506 bär en `region`,
medan 310 (61%) saknar `places` helt.** Trafiklab skickar ofta bara ett
stop_id som inte går att slå upp, och SL:s fritext namnger inte alltid en
hållplats.

Ett ortsfilter ensamt hade alltså tystat majoriteten av alla riktiga
störningar för varje förare som valde en ort -- raka motsatsen till vad det
är till för. Därför:

* `regions` (län) är det filter som går att lita på, och det som avgör.
* `cities` förfinar inom länet, och släpper alltid igenom tips vars ort är
  okänd. Ett ortsfilter tar bort det vi VET ligger någon annanstans -- det
  får aldrig gömma allt vi inte kunnat placera.

Samma princip som fcmPush.js kom fram till, med länsfiltret tillagt: utan
det var ortsvalet det enda geografiska filtret som fanns, och det matchade
alltså inte på 61% av datan.

Förarens egna val ovanpå grindarna (2026-10-03)
-----------------------------------------------
Allt i `devices.notify_prefs` (JSON, ingen migrering). Ett fält som saknas
betyder "som förut", så en telefon som aldrig rört inställningarna beter sig
exakt som innan fälten fanns:

* `quietHours` {"from": 1, "to": 6} -- inga notiser de timmarna (svensk tid),
  varje natt. Prövas både när notisen köas och strax före sändningen.
* `maxPerHour` -- förarens tak för alla notiser, räknat på köade notiser den
  senaste timmen. Tomt = inget tak.
* `weak` -- föraren vill OCKSÅ ha svaga tips. Grind 1 släpper då igenom tips
  under golvet (se `weak_eligible` och thresholds.NOTIFY_WEAK_*), med ett eget
  tak per timme. Av som standard; "Rekommenderat" har det av.

Färdiga lägen (Rekommenderat, Bara de starkaste, Allt i mina län, Tyst) och
valideringen av det klienten skickar bor i core/notify_prefs.py.

Kastar aldrig
-------------
`run_push_cycle()` och allt den kallar fångar sina egna fel. En trasig
FCM-token, en enhet med sönderskriven notify_prefs eller ett nätverksfel får
aldrig stoppa vare sig resten av batchen eller pollcykeln som anropar den --
samma per-källa-isolering som resten av pipelinen håller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
import hashlib
from collections import Counter
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import areas, presence as presence_rules, thresholds
from core.combine import group_key
from core.coverage import RAIL_REGION_KEY, notify_region_catalog
from core.geo import (
    REGION_ANCHOR,
    REGION_CITIES,
    haversine_km,
    resolve_place_coords,
)
from core.models import Opportunity, PushDelivery
from core.time_limits import reraise_time_limit

log = logging.getLogger(__name__)


# --- Notiskatalogen ------------------------------------------------------
#
# Vilka händelsetyper en förare kan slå på och av. Nycklarna ÄR
# severity_tier, så etiketterna i inställningarna och på korten beskriver
# samma sak med samma ord -- ett andra, fritt formulerat ordförråd i
# notisinställningarna hade gjort "Förseningar" i inställningarna omöjlig
# att koppla till "Försening på linjen" på kortet.
#
# Katalogen bodde i api_client.dart (notifyTypeCatalog) och defaulterna i
# fcmPush.js (DEFAULT_ON_TYPES) -- två filer, två språk, samma lista, och
# ingenting som höll ihop dem. Serveras nu härifrån via /api/notify-prefs.
#
# Bara tiers ur thresholds.NOTIFY_WORTHY_TIERS kan faktiskt ge en notis. De
# tre andra står kvar i katalogen med `notifiable: False` med avsikt: en
# förare som letar efter "Förseningar" ska hitta raden och få veta att den
# syns i listan men aldrig pushas, i stället för att undra om den glömts
# bort.
TYPE_CATALOG: list[dict] = [
    {
        "id": "line_paused",
        "label": "Hela linjen står stilla",
        "short": "Ingen trafik alls på linjen",
        "help": "Störst chans att det finns folk som behöver taxi.",
        "defaultOn": True,
    },
    {
        "id": "vehicle_cancelled",
        "label": "Enstaka avgång inställd",
        "short": "En avgång inställd, andra går som vanligt",
        "help": "Färre påverkade, men kan ändå vara värt en titt.",
        "defaultOn": True,
    },
    {
        "id": "road_accident_or_closure",
        "label": "Olycka eller avstängd väg",
        "short": "Vägtrafik",
        "help": "Påverkar mest bilister som redan sitter i bil, men värt att veta om.",
        "defaultOn": True,
    },
    # `weak`: kan ge notis när föraren slagit på svagare tips -- och då är typen
    # PÅ tills föraren stänger av den (`type_enabled(..., weak=True)`).
    {
        "id": "line_delayed",
        "label": "Förseningar",
        "short": "Linjen kör, men försenad",
        "help": "Svag signal. Ger bara notis om du slagit på svagare tips.",
        "defaultOn": False,
        "weak": True,
    },
    {
        "id": "vehicle_delayed",
        "label": "Enstaka avgång försenad",
        "short": "En avgång är sen",
        "help": "Svag signal. Ger bara notis om du slagit på svagare tips.",
        "defaultOn": False,
        "weak": True,
    },
    # Inte `weak`: köer och vägarbeten når aldrig listan (bara olyckor gör det,
    # thresholds.ROAD_SHOWN_CONDITIONS), så ett reglage för dem hade varit dött.
    {
        "id": "road_work_or_queue",
        "label": "Vägarbete eller köbildning",
        "short": "Vägtrafik",
        "help": "Sällan en taxisignal — syns inte i listan och väcker aldrig telefonen.",
        "defaultOn": False,
        "weak": False,
    },
]

_DEFAULT_ON = {t["id"] for t in TYPE_CATALOG if t["defaultOn"]}

# --- Förarens enkla regler: kategori, nivå och paus ------------------------
#
# Typkatalogen ovan är finkornig (en rad per störningstyp) och ligger kvar
# under "Fler val". De flesta förare vill något enklare: "inga vägnotiser",
# "bara de starka", "tyst i två timmar". Samma kategorier som kartans
# kategorirad (lib/signal_kinds.dart), så att notisen och kartan talar samma
# språk. Allt är PÅ tills föraren stänger av -- en ny kategori ska inte vara
# tyst bara för att den tillkom efter att prefs sparades.

CATEGORY_CATALOG = [
    {"id": "transit", "label": "Tåg & buss"},
    {"id": "road", "label": "Väg"},
    {"id": "flight", "label": "Flyg"},
    {"id": "ferry", "label": "Färja"},
]
_CATEGORY_IDS = {c["id"] for c in CATEGORY_CATALOG}

# Lägsta nivå för en notis. "all" = allt som redan klarat notisgolvet.
LEVELS = ("all", "medium", "high")
_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}
_MIN_RANK = {"all": 0, "medium": 1, "high": 2}

# Längsta paus: en glömd paus ska inte tysta telefonen i en vecka.
MAX_PAUSE_HOURS = 24


def category_of(opportunity) -> str:
    """Kartans kategori för ett tips: kind först, som i appen."""
    kind = getattr(opportunity, "kind", None)
    if kind in ("road", "flight", "ferry"):
        return kind
    mode = getattr(opportunity, "mode", None)
    if mode in ("road", "flight"):
        return mode
    return "transit"


def category_enabled(categories: dict | None, category: str) -> bool:
    if isinstance(categories, dict) and category in categories:
        return categories[category] is not False
    return True


def level_of(opportunity) -> str:
    """Samma styrka som listan visar (core/api.py:_serialize): den sparade."""
    return thresholds.effective_level(opportunity)


def level_allows(min_level: str | None, level: str) -> bool:
    return _LEVEL_RANK.get(level, 0) >= _MIN_RANK.get(min_level or "all", 0)


def paused_until(prefs: dict | None):
    """Pausens slut, eller None. Ett trasigt värde är ingen paus."""
    from django.utils.dateparse import parse_datetime

    raw = (prefs or {}).get("pausedUntil") if isinstance(prefs, dict) else None
    if not raw:
        return None
    parsed = parse_datetime(str(raw))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


_STOCKHOLM = ZoneInfo("Europe/Stockholm")


def quiet_hours(prefs: dict | None) -> tuple[int, int] | None:
    """
    Tysta timmar som (från, till) i hela timmar, svensk tid. None = inga.

    Halvöppet intervall som får korsa midnatt: (1, 6) är 01:00-05:59, (22, 6)
    är 22:00-05:59. Samma från och till är inget intervall -- ett "dygnet runt"
    hade varit en avstängning som inte ser ut som en, och den finns redan
    (`enabled`). Ett trasigt värde är inga tysta timmar, inte tystnad.
    """
    raw = (prefs or {}).get("quietHours") if isinstance(prefs, dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        start, end = int(raw.get("from")), int(raw.get("to"))
    except (TypeError, ValueError):
        return None
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        return None
    return start, end


def in_quiet_hours(prefs: dict | None, now=None) -> bool:
    window = quiet_hours(prefs)
    if window is None:
        return False
    hour = (now or timezone.now()).astimezone(_STOCKHOLM).hour
    start, end = window
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def weak_enabled(prefs: dict | None) -> bool:
    """Har föraren valt att OCKSÅ få svaga tips? Bara ett uttryckligt ja räknas."""
    return isinstance(prefs, dict) and prefs.get("weak") is True


def max_per_hour(prefs: dict | None) -> int | None:
    """Förarens tak för alla notiser per timme, eller None."""
    raw = (prefs or {}).get("maxPerHour") if isinstance(prefs, dict) else None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def silenced(prefs: dict | None, now=None) -> str | None:
    """
    Har föraren tystat telefonen just nu, oavsett tips? Skälet, eller None.

    Samma tre skäl som i decide(), i samma ordning. Prövas igen strax före
    sändningen (_send_due): en paus eller natt som börjat medan notisen låg i
    kön ska gälla -- annars väcks föraren 01:00 av något som köades 00:59.
    """
    prefs = prefs if isinstance(prefs, dict) else {}
    now = now or timezone.now()
    if prefs.get("enabled") is False:
        return "notifications_off"
    pause = paused_until(prefs)
    if pause is not None and pause > now:
        return "paused"
    if in_quiet_hours(prefs, now):
        return "quiet_hours"
    return None


def weak_eligible(opportunity, now=None) -> bool:
    """
    Får tipset gå som en SVAG notis till den som valt det?

    Bara tips föraren också hittar i listan (core/api.feed_for), så att en notis
    aldrig gäller något som listan sedan döljer:

    * aldrig "Övrigt" (`ignore`) och aldrig poäng 0,
    * aldrig avslutat eller långt fram (FEED_HORIZON_HOURS),
    * aldrig undertryckt av personalen,
    * väghändelser bara när de visas (olyckor, thresholds.road_shown),
    * aldrig med angiven ersättningstrafik (invariant 12: bussen går redan).
    """
    now = now or timezone.now()
    if getattr(opportunity, "severity_tier", None) in (None, "", "ignore"):
        return False
    if (getattr(opportunity, "demand_score", 0) or 0) <= 0:
        return False
    end = getattr(opportunity, "end_time", None)
    if end is None or end <= now:
        return False
    start = getattr(opportunity, "start_time", None)
    if start is not None and start > now + timedelta(hours=thresholds.FEED_HORIZON_HOURS):
        return False
    if getattr(opportunity, "suppressed_at", None) is not None:
        return False
    if getattr(opportunity, "has_alternative", False):
        return False
    if getattr(opportunity, "kind", None) == "road" and not thresholds.road_shown(
        getattr(opportunity, "rule_id", None)
    ):
        return False
    return True


def type_catalog() -> list[dict]:
    """
    Katalogen med en ärlig markering av vad som faktiskt kan pushas:
    `notifiable` = kan ge notis för alla, `weakOnly` = bara för den som slagit
    på svagare tips. En typ som är ingetdera visas inte som ett val i appen.
    """
    rows = []
    for t in TYPE_CATALOG:
        notifiable = t["id"] in thresholds.NOTIFY_WORTHY_TIERS
        rows.append({
            **t,
            "notifiable": notifiable,
            "weakOnly": not notifiable and bool(t.get("weak")),
        })
    return rows


def default_prefs() -> dict:
    """Vad en enhet som aldrig rört en inställning har."""
    return {
        "enabled": True,
        "types": {t["id"]: t["defaultOn"] for t in TYPE_CATALOG},
        "regions": [],
        "cities": [],
        "weak": False,
    }


def cities_by_region() -> dict[str, list[str]]:
    """
    Orter man kan kryssa i under varje län i notisinställningarna.

    Samma källa som push-steget förstår: REGION_CITIES i geo.py. Appen
    visar bara orter för de län föraren valt -- annars hade Skåne-orter
    kunnat väljas under Stockholm och sett ut som ett filter.
    """
    return {key: list(cities) for key, cities in REGION_CITIES.items()}


# --- Grind 2 och 3: förarens egna val ------------------------------------


def type_enabled(types: dict | None, severity_tier: str | None, weak: bool = False) -> bool:
    """
    Har föraren slagit på den här händelsetypen?

    En typ som SAKNAS i sparade prefs faller tillbaka på katalogens default
    i stället för att läsas som avstängd. Annars hade varje ny installation
    börjat med noll notiser -- inklusive för den allvarligaste typen -- utan
    att någonsin ha tryckt på något. Samma semantik som NotifyPrefsSheet
    visar i appen, så reglaget och verkligheten säger samma sak.

    `weak=True` (en svag notis till den som valt svagare tips): en typ som
    saknas är PÅ. Valet betyder "ge mig de svaga också", och förseningarna är
    just de svaga; en förare som uttryckligen stängt av en typ har fortfarande
    sista ordet.
    """
    if isinstance(types, dict) and severity_tier in types:
        return types[severity_tier] is True
    if weak:
        return True
    return severity_tier in _DEFAULT_ON


def region_matches(region: str | None, chosen: list | None) -> bool:
    """
    Ligger tipset i ett län föraren valt?

    Tre fall som är lätta att blanda ihop:

    * Inga valda län = föraren har inte begränsat sig. Allt släpps igenom.
    * Tipset saknar `region` (vägtips skrivs utan) -- släpps igenom, av
      samma skäl som ortsfiltret nedan: ett filter tar bort det vi vet
      ligger fel, aldrig det vi inte kunnat placera.
    * Järnvägen skrivs med region "rail" oavsett var i landet stationen
      ligger -- Trafikverkets tågdata har inget länsfält. "rail" är därför
      ett eget val i katalogen, inte ett län. En förare som valt bara sitt
      län får INTE tågtipsen, vilket är rätt: annars hade "Skåne" i
      praktiken betytt "Skåne plus varje tåg i Sverige".
    """
    if not chosen:
        return True
    if not region:
        return True
    return region in set(chosen)


def places_match_cities(places: list | None, cities: list | None) -> bool:
    """
    Nämner tipset en ort föraren valt?

    Delsträngsjämförelse, inte likhet: `cities` bär rena ortnamn ("Malmö")
    medan `places` kan bära mer specifika hållplatsnamn ("Malmö C"). Exakt
    likhet hade tyst aldrig matchat.

    Ett tips UTAN känd plats släpps igenom. Se modulens docstring: 61% av
    tipsen saknar `places`, och att behandla "vi vet inte var" som "matchar
    inte din ort" hade tystat majoriteten av alla riktiga störningar.
    """
    if not cities:
        return True
    if not places:
        return True
    lowered = [str(c).lower() for c in cities if str(c).strip()]
    if not lowered:
        return True
    for place in places:
        p = str(place).lower()
        for city in lowered:
            if city in p or p in city:
                return True
    return False


def within_reach(lat, lon, chosen_regions: list | None) -> bool:
    """
    Ligger tipset inom körhåll från något av de län föraren valt?

    Fjärde grinden, och den fanns inte i fcmPush.js -- det är en riktad
    rättning av en särgång som gick att mäta: en förare i Malmö som valt
    "Skåne + järnväg" väcktes av ett inställt tåg i **Örnsköldsvik**, 1 400 km
    bort, som appens egen lista aldrig hade visat. Marknadsradien fanns bara
    på läsvägen (`feed_for`), inte på pushvägen. Att kunna bli väckt av något
    man sedan inte hittar i appen är precis den sortens tysta särgång
    thresholds.py finns för att förhindra.

    Orsaken är strukturell, inte en bugg i datan: järnvägstips skrivs med
    region "rail" oavsett var i landet stationen ligger, eftersom
    Trafikverkets tågdata saknar länsfält. Länsfiltret ensamt kan därför
    aldrig avgränsa dem geografiskt -- men koordinaten kan, och alla tretton
    aktiva rail-tips bär en.

    Samma MARKET_RADIUS_KM som flödet använder, med avsikt: en notis ska inte
    kunna gälla något som listan sedan filtrerar bort.

    Två fall släpps alltid igenom, av samma skäl som ort- och länsfiltren:

    * Föraren har inte valt något län -- då har hen inte sagt var hen kör,
      och vi har inget att mäta mot.
    * Tipset saknar koordinat -- ett filter tar bort det vi VET ligger fel,
      aldrig det vi inte kunnat placera.
    """
    if not chosen_regions:
        return True
    if lat is None or lon is None:
        return True

    anchors = []
    for key in chosen_regions:
        city = REGION_ANCHOR.get(str(key))
        if not city:
            # "rail" har ingen ankarort -- järnvägen är hela landet. En
            # förare som valt BARA järnväg har inte angett någon geografi,
            # och får då heller ingen avståndsgräns.
            continue
        geo = resolve_place_coords(city)
        if geo:
            anchors.append(geo)
    if not anchors:
        return True

    return any(
        haversine_km(lat, lon, a["lat"], a["lon"]) <= thresholds.MARKET_RADIUS_KM
        for a in anchors
    )


def list_matches_regions(
    region: str | None,
    lat,
    lon,
    chosen_regions: list | None,
) -> bool:
    """
    Hör tipset till de valda länen? Samma regel som appens
    `_matchesSelectedRegions` och som pushens geografi när `rail` lagts till.

    Marknadsnyckel (skane/sl/vt/…) matchar rakt av. Järnväg (`rail`), väg
    (`trafikverket`) och okända/null-regioner filtreras på 150 km mot länens
    ankare -- annars syns Örnsköldsvik när föraren valt Skåne (invariant 14).

    Används av `feed_for` när föraren valt län i listfiltret, så en Malmö-
    GPS inte tyst kapar Stockholm/Göteborg innan klientfiltret hinner se dem.
    """
    if not chosen_regions:
        return True
    chosen = {str(r) for r in chosen_regions}
    r = (str(region).strip() if region is not None else "") or None
    if r and r not in ("rail", "trafikverket") and r in REGION_ANCHOR:
        return r in chosen
    if lat is None or lon is None:
        return r is not None and r in chosen
    return within_reach(lat, lon, list(chosen))


@dataclass(frozen=True)
class Match:
    """Utfallet för en enhet, med skälet kvar -- ett tyst nej går inte att felsöka."""

    ok: bool
    reason: str
    # Släpptes igenom (eller prövades) som en svag notis, för den som valt det.
    weak: bool = False

    def __bool__(self) -> bool:
        return self.ok


# Varje nej har en kod, och varje kod står här. `push_cycle --dry-run`, simuleringen
# och utskicket använder samma decide(), så ett nej i torrkörningen är samma nej
# som i telefonen.
REASONS: dict[str, str] = {
    "match": "skickas",
    "not_notify_worthy": "tipset är inte notisvärt: typ, poäng under golvet eller känt alternativ",
    "ai_only": "bara språkmodellens höjning gör tipset notisvärt, inte regelverket",
    "notifications_off": "föraren har stängt av notiser",
    "paused": "föraren har pausat notiserna en stund",
    "quiet_hours": "föraren har tysta timmar just nu",
    "hourly_limit": "föraren har redan fått så många notiser den här timmen som hen valt",
    "weak_hourly_limit": "föraren har redan fått så många svaga notiser den här timmen som taket tillåter",
    "category_off": "föraren har stängt av notiser för den här kategorin",
    "below_level": "tipset är svagare än den nivå föraren valt för notiser",
    "type_off": "föraren har stängt av den här händelsetypen",
    "no_area": "föraren har inte valt något körområde",
    "unplaced_tip": "tipset går inte att placera i ett län",
    "outside_area": "tipset ligger utanför förarens körområde",
    "city_not_chosen": "tipset nämner ingen av förarens valda orter",
    "near_driver": "föraren är i tjänst och tipset ligger inom radien från förarens ruta",
    "too_far_from_driver": "föraren är i tjänst och tipset ligger utanför radien från förarens ruta",
    "same_group": "föraren har redan fått en notis om samma händelse (samma tåg samma dag)",
}


def decide(prefs: dict | None, opportunity, presence=None, *, now=None, recent=None) -> Match:
    """
    Ska den här enheten få den här notisen? Det enda notisbeslutet.

    Grindarna i ordning; den första som säger nej ger orsakskoden:

    1. `not_notify_worthy` -- thresholds.is_notify_worthy. Anroparen filtrerar
       redan i SQL (candidates), men kontrollen står kvar som skyddsräcke.
       Har föraren valt svagare tips (`weak`) och tipset klarar `weak_eligible`
       går det vidare som en SVAG notis (`Match.weak`) i stället för att fällas
       här; alla grindar nedan gäller den också.
    2. `notifications_off`, `paused` (en tidsbegränsad paus), `quiet_hours`,
       `category_off:<kategori>` (Tåg & buss, Väg, Flyg, Färja) och `below_level`
       (föraren vill bara ha starka eller medel och uppåt -- för de svaga är det
       hur svaga)
    3. `type_off:<tier>`
    4. `no_area` -- inget körområde valt. Ingen rikstäckande standardnotis: en
       förare som inte sagt var hen kör väcks inte av något i andra änden av
       landet. Tidigare släpptes allt igenom när inga län var valda.
    5. `unplaced_tip` -- tipset saknar län. En notis kräver att vi vet var.
    6. `outside_area` -- tipsets län (med grannlän inom bufferten) delar inget
       län med förarens körområde. Ersätter marknadsnyckeln och 150 km-radien
       från länets ankarort.
    7. `city_not_chosen` -- ortsfiltret, som tidigare.

    Är föraren "i tjänst" (`presence`, en gällande ruta från core/presence.py)
    ersätter rutan steg 4-7: tipset måste ha koordinater (`unplaced_tip`) och ligga
    inom presence.RADIUS_KM från rutans mitt (`near_driver`, annars
    `too_far_from_driver`). Utan gällande ruta räknas notisen på körområdet.

    Sist taken per timme, när anroparen räknat dem (`recent` = (alla, svaga)
    köade notiser den senaste timmen för enheten): `hourly_limit` för förarens
    eget `maxPerHour`, `weak_hourly_limit` för thresholds.NOTIFY_WEAK_MAX_PER_HOUR.
    Sist med avsikt: bara en notis som annars hade skickats ska räknas mot taket.
    """
    now = now or timezone.now()
    prefs = prefs if isinstance(prefs, dict) else {}
    weak = False
    worthy = thresholds.is_notify_worthy(
        getattr(opportunity, "severity_tier", None),
        getattr(opportunity, "demand_score", 0),
        getattr(opportunity, "has_alternative", False),
        level=level_of(opportunity),
    )
    ai_raised = getattr(opportunity, "ai_adjusted_at", None) is not None
    if not worthy or ai_raised:
        # Modellen får höja ett tips i listan, men en vanlig notis kräver
        # regelverkets egen bedömning (`ai_only`). Nästa pollrunda skriver
        # regelvärdena och tar bort markeringen. Som svag notis räcker det att
        # tipset finns i listan -- där spelar poängen ingen roll.
        reason = "ai_only" if worthy else "not_notify_worthy"
        if not (weak_enabled(prefs) and weak_eligible(opportunity, now)):
            return Match(False, reason)
        weak = True

    quiet = silenced(prefs, now)
    if quiet:
        return Match(False, quiet, weak)
    category = category_of(opportunity)
    if not category_enabled(prefs.get("categories"), category):
        return Match(False, f"category_off:{category}", weak)
    if not level_allows(prefs.get("minLevel"), level_of(opportunity)):
        return Match(False, "below_level", weak)
    if not type_enabled(prefs.get("types"), opportunity.severity_tier, weak=weak):
        return Match(False, f"type_off:{opportunity.severity_tier}", weak)
    if presence is not None:
        lat, lon = getattr(opportunity, "lat", None), getattr(opportunity, "lon", None)
        if lat is None or lon is None:
            return Match(False, "unplaced_tip", weak)
        if presence_rules.distance_km(presence, lat, lon) > presence_rules.RADIUS_KM:
            return Match(False, "too_far_from_driver", weak)
        verdict = Match(True, "near_driver", weak)
    else:
        # Län och kommuner i samma lista; en vald kommun ersätter sitt län.
        area = areas.device_area_codes(prefs)
        if not area:
            return Match(False, "no_area", weak)
        tip_area = tip_area_codes(opportunity)
        if not tip_area:
            return Match(False, "unplaced_tip", weak)
        if not set(tip_area) & set(area):
            return Match(False, "outside_area", weak)
        if not places_match_cities(opportunity.places, prefs.get("cities")):
            return Match(False, "city_not_chosen", weak)
        verdict = Match(True, "match", weak)
    if recent is not None:
        total, weak_sent = recent
        cap = max_per_hour(prefs)
        if cap is not None and total >= cap:
            return Match(False, "hourly_limit", weak)
        if weak and weak_sent >= thresholds.NOTIFY_WEAK_MAX_PER_HOUR:
            return Match(False, "weak_hourly_limit", weak)
    return verdict


def tip_area_codes(opportunity) -> list[str]:
    """Länen tipset hör till. Sparade vid skrivning; räknas här för äldre rader."""
    stored = getattr(opportunity, "area_codes", None)
    if stored:
        return list(stored)
    return areas.area_for(
        getattr(opportunity, "lat", None), getattr(opportunity, "lon", None), getattr(opportunity, "region", None)
    )[1]


# Äldre namn, kvar för anropare utanför modulen.
match_device = decide

# --- Texten på låsskärmen ------------------------------------------------

_TIER_PUSH_LABEL = {
    "line_paused": "Hela linjen stoppad",
    "vehicle_cancelled": "Avgång inställd",
    "road_accident_or_closure": "Olycka/avstängning",
}
_MODE_PUSH_LABEL = {
    "train": "Tåg",
    "metro": "Tunnelbana",
    "tram": "Spårvagn",
    "bus": "Buss",
    "boat": "Båt",
    "road": "Väg",
}


def push_title(opportunity) -> str:
    """
    En rad en förare läser på en sekund, i rondellen.

    Råtiteln är ofta ett naket "Inställd" eller "Försening" utan
    sammanhang -- Trafiklab skickar genuint inte mer för många larm -- så
    raden leder med det föraren behöver: var, och vilken sorts störning.
    """
    places = opportunity.places or []
    place = str(places[0]) if places else ""
    what = _TIER_PUSH_LABEL.get(opportunity.severity_tier) or opportunity.title or "Ny taxisignal"
    prefix = place or _MODE_PUSH_LABEL.get(opportunity.mode, "")
    return f"{prefix}: {what}" if prefix else what


def push_body(opportunity) -> str:
    """
    Sammanfattningen, med "vad gör resenären i stället?" när vi vet det.

    Nästa avgång är det enda som avgör om det är värt att köra dit: står
    ersättningsbussen redan där finns ingen kund. Vi hittar aldrig på ett
    alternativ -- fältet är tomt när källan inte sagt något, och då säger
    notisen inget heller.
    """
    from core.briefs import current_brief

    parts = []
    summary = (opportunity.summary or "").strip()
    # Förarbeskedet när det hunnit skrivas: samma uppgifter, i förarens ord.
    brief = current_brief(opportunity)
    shown = brief or summary[:140]
    if shown:
        parts.append(shown)
    if opportunity.is_last_departure:
        parts.append("Sista avgången — inget kommer efter.")
    elif (
        getattr(opportunity, "next_departure_at", None) is not None
        and "nästa avgång" not in (brief or summary).lower()
        and not (brief and opportunity.next_departure_at.astimezone(ZoneInfo("Europe/Stockholm")).strftime("%H:%M") in brief)
    ):
        # Järnvägens summary skriver redan ut nästa avgång i sin egen text
        # ("Nästa avgång går 06:13."). Utan den kontrollen stod samma uppgift
        # två gånger på låsskärmen, där varje tecken konkurrerar om en
        # sekunds uppmärksamhet.
        # Klockslag: en push läses minuter eller timmar efter att den skickades,
        # och "om 20 min" är då fel. Utan absolut tid säger notisen inget.
        clock = opportunity.next_departure_at.astimezone(ZoneInfo("Europe/Stockholm")).strftime("%H:%M")
        parts.append(f"Nästa avgång {clock}.")
    return " ".join(parts).strip()


def snapshot_of(opportunity) -> dict:
    """
    Tipset som notishistoriken och favoritlistan bevarar det.

    Bara fälten ett kort behöver för att gå att rendera -- inte hela raden.
    `purge_old` tar bort tipset efter sju dagar, och en notislista som
    tömmer sig själv bakvägen hade varit svårare att förstå än ingen lista.
    """
    return {
        "id": str(opportunity.id),
        "external_id": opportunity.external_id,
        "title": opportunity.title,
        "summary": opportunity.summary,
        "kind": opportunity.kind,
        "mode": opportunity.mode,
        "severity_tier": opportunity.severity_tier,
        # Samma styrka som flödet visar för tipset.
        "level": level_of(opportunity),
        "factors": list(getattr(opportunity, "factors", None) or []),
        "demand_score": opportunity.demand_score,
        "confidence": opportunity.confidence,
        "region": opportunity.region,
        "places": opportunity.places,
        "lat": opportunity.lat,
        "lon": opportunity.lon,
        "reasons": opportunity.reasons,
        "rule_id": opportunity.rule_id,
        # Länskoderna följer med, så att mottagarkontrollen strax före
        # sändningen (fleet/push_gate.py) kan pröva tipsets län mot licensens
        # utan att slå upp ett tips som kan ha gallrats bort.
        "area_codes": list(opportunity.area_codes or []),
        "start_time": opportunity.start_time.isoformat() if opportunity.start_time else None,
        "end_time": opportunity.end_time.isoformat() if opportunity.end_time else None,
        # Händelsen tipset hör till (samma tåg samma dag), så att nästa station
        # längs linjen inte väcker samma förare igen. Se group_key.
        "group": group_key(opportunity),
    }


# --- Cykeln --------------------------------------------------------------


def candidates(now=None, limit: int = 200) -> list[Opportunity]:
    """
    Tips som just blivit värda att pusha och ännu inte pushats.

    `notified_at is null` är grinden som gör att samma störning inte väcker
    samma förare varje pollcykel. Den skrivs bara av det här steget -- se
    Opportunity-docstringen och core/repository.py: pipelinen namnger sina
    kolumner explicit och rör den aldrig.

    Ett tips som först är svagt (poäng under golvet) och senare stärks blir
    en kandidat då i stället -- notified_at är fortfarande NULL. Det är
    avsiktligt: signalen blev verklig senare, och då är notisen befogad.
    """
    now = now or timezone.now()
    return list(
        Opportunity.objects.filter(
            notified_at__isnull=True,
            suppressed_at__isnull=True,
            end_time__gt=now,
            demand_score__gte=thresholds.NOTIFY_SCORE_FLOOR,
            severity_tier__in=sorted(thresholds.NOTIFY_WORTHY_TIERS),
            # Bara Starka: styrkan räknades med läge och omständigheter när
            # tipset skrevs (core/taxi_context.py).
            level="high",
            # Samma grind som thresholds.is_notify_worthy, i SQL: källan har
            # skrivit ut att ersättningstrafik går, och då står ingen kvar.
            # match_device kontrollerar den igen per enhet -- den här raden
            # är till för att cykeln inte ska hämta rader den ändå kastar.
            has_alternative=False,
            # Höjt av språkmodellen: aldrig ensam grund för en notis (se decide).
            ai_adjusted_at__isnull=True,
        ).order_by("-demand_score")[:limit]
    )


def weak_candidates(now=None, limit: int = 200) -> list[Opportunity]:
    """
    Tips som kan gå som SVAG notis till den som valt det: nya (de senaste
    NOTIFY_WEAK_FRESH_MINUTES), synliga i listan och inte notisvärda för alla.

    `notified_at` används inte här och skrivs inte av den här vägen: den är
    notisstunden för ALLA, och ett svagt tips som senare blir starkt ska då få
    sin vanliga notis. Dubbletter stoppas i stället av leveransnyckeln (enhet,
    tips) i push_delivery, och ett tips som redan haft sin notisstund
    (notified_at satt) skickas aldrig som svagt i efterhand.

    SQL-filtret får bara vara vidare än `weak_eligible`, aldrig snävare --
    decide() fäller det slutliga avgörandet per enhet.
    """
    from django.db.models import Q

    now = now or timezone.now()
    rows = (
        Opportunity.objects.filter(
            notified_at__isnull=True,
            suppressed_at__isnull=True,
            end_time__gt=now,
            demand_score__gt=0,
            has_alternative=False,
            computed_at__gte=now - timedelta(minutes=thresholds.NOTIFY_WEAK_FRESH_MINUTES),
        )
        .exclude(severity_tier="ignore")
        .filter(
            Q(start_time__isnull=True)
            | Q(start_time__lte=now + timedelta(hours=thresholds.FEED_HORIZON_HOURS))
        )
        .order_by("-demand_score")[:limit]
    )
    out = []
    for o in rows:
        if not weak_eligible(o, now):
            continue
        worthy = thresholds.is_notify_worthy(
            o.severity_tier, o.demand_score, o.has_alternative, level=level_of(o),
        )
        if worthy and o.ai_adjusted_at is None:
            # Den vanliga vägen tar det (candidates) -- inte två gånger.
            continue
        out.append(o)
    return out


def _devices(require_token: bool = True, weak_only: bool = False):
    """
    Enheter som får ta emot notiser. Importeras lokalt: billing-modellerna
    pekar på Supabase-ägda tabeller, och core ska kunna importeras utan dem
    i en miljö där de inte migrerats.

    `require_token=False` används av simuleringsläget, som kör hela
    urvalslogiken utan att skicka något -- lokalt har ingen enhet en
    FCM-token, och utan den flaggan hade varje lokal körning svarat
    "0 notiser" oavsett hur rätt allting annat var.

    `weak_only=True`: bara telefoner som valt svagare tips. En cykel med bara
    svaga kandidater ska inte läsa varje telefon i landet var 30:e sekund.
    """
    from billing.models import Device

    # Rätten att ta emot bor i fleet.access.company_window -- SAMMA fråga som
    # listan (core/entitlement.py) och sändgrinden (fleet/push_gate.py)
    # ställer. Urvalet läste tidigare legacy-fältet `companies.status`, och
    # då föll varje telefon vars bolag hade ett giltigt prov i `fleet_trial`
    # men `status=canceled` i Supabase bort INNAN grinden ens tillfrågades:
    # svaret blev `no_devices` och `push_delivery` stod på noll rader i hela
    # tabellens liv (mätt 2026-10-07, docs/bearbetning-optimeringar.md §2).
    # company_window prövar spärr, beviljande, prov, betald period, frist och
    # uppsägning i rätt ordning, och faller tillbaka på bolagets status bara
    # när den nya modellen inte vet något -- precis det urvalet ska göra.
    from fleet.access import company_window

    rows = Device.objects.all()
    if weak_only:
        rows = rows.filter(notify_prefs__weak=True)
    if require_token:
        rows = rows.exclude(push_token__isnull=True).exclude(push_token="")
    rows = list(rows)
    # En prövning per bolag, inte per telefon: ett bolag med femtio bilar
    # ska inte kosta femtio uppslag var 30:e sekund.
    now = timezone.now()
    open_by_company: dict = {}
    out = []
    for device in rows:
        company_id = device.company_id
        if company_id is None:
            continue
        if company_id not in open_by_company:
            open_by_company[company_id] = company_window(company_id, now).ok
        if open_by_company[company_id]:
            _heal_area(device, now)
            out.append(device)
    return out


def _heal_area(device, now) -> None:
    """
    Telefonens körområde mot licensens län, här där notisen avgörs. Läkningen
    i läsvägarna (core/api.py) körs bara när appen öppnar vissa vyer; ett extra
    län som köpts under passet ska ge notiser utan att föraren öppnar något.
    Skriver bara när något ändrats. Får aldrig stoppa en notiscykel.
    """
    from fleet import device_prefs
    from fleet.notify_settings import device_entitlement

    try:
        entitled, restricted = device_entitlement(device, now)
        if restricted and entitled:
            prefs, changed = device_prefs.align_prefs_to_entitlement(device.notify_prefs, entitled)
            if changed:
                device_prefs.write_device_prefs(device.id, prefs)
                device.notify_prefs = prefs
    except Exception as exc:  # ett läkningsfel ska inte tysta alla notiser
        reraise_time_limit(exc)
        log.warning("notify: körområdet kunde inte läkas för %s: %s", device.id, type(exc).__name__)


def _has_cap(prefs) -> bool:
    return weak_enabled(prefs) or max_per_hour(prefs) is not None


def _recent_counts(devices, now) -> dict[str, list[int]]:
    """
    Köade notiser den senaste timmen per enhet: [alla, svaga]. En fråga per
    cykel, och bara när någon telefon har ett tak att räkna mot. Räknas på
    köade rader, inte skickade: det är köandet taket ska hålla emot, och en
    notis som sedan inte nådde fram har ändå tagit en plats.
    """
    from django.db.models import Count, Q

    counts: dict[str, list[int]] = {str(d.id): [0, 0] for d in devices}
    ids = [d.id for d in devices if _has_cap(d.notify_prefs)]
    if not ids:
        return counts
    rows = (
        PushDelivery.objects.filter(device_id__in=ids, created_at__gte=now - timedelta(hours=1))
        .values("device_id")
        .annotate(total=Count("id"), weak=Count("id", filter=Q(snapshot__weak=True)))
    )
    for row in rows:
        counts[str(row["device_id"])] = [row["total"], row["weak"]]
    return counts


def _recent_for(counts, device):
    """(alla, svaga) för decide(), eller None när enheten inte har något tak."""
    if not _has_cap(device.notify_prefs):
        return None
    total, weak = counts.get(str(device.id), (0, 0))
    return total, weak


def _tally(counts, device, weak: bool) -> None:
    row = counts.setdefault(str(device.id), [0, 0])
    row[0] += 1
    if weak:
        row[1] += 1


def plan_cycle(now=None, require_token: bool = False) -> list[dict]:
    """
    Vad en cykel SKULLE skicka, utan att skicka något.

    Finns för `manage.py push_cycle --dry-run` och för att en notis som
    uteblev ska gå att förklara utan att läsa loggar: varje enhet får sitt
    `reason` med, även när svaret är nej. Svaga kandidater, prövade mot
    telefonerna som valt dem, står med `weak: true`.
    """
    now = now or timezone.now()
    plan = []
    # Utan token-kravet som standard: en torrkörning ska svara på "vem hade
    # matchat?", och lokalt har ingen enhet en FCM-token. Ett tomt svar hade
    # sett ut som att filtren var fel, inte som att telefonerna saknas.
    devices = _devices(require_token=require_token)
    on_duty = presence_rules.fresh([d.id for d in devices], now)
    counts = _recent_counts(devices, now)
    weak_devices = [d for d in devices if weak_enabled(d.notify_prefs)]
    rounds = [(o, False, devices) for o in candidates(now=now)]
    if weak_devices:
        rounds += [(o, True, weak_devices) for o in weak_candidates(now=now)]
    grouped = _grouped(devices, [o for o, _w, _t in rounds], now)
    for opportunity, weak_round, targets in rounds:
        recipients, rejected = [], []
        group = group_key(opportunity)
        for device in targets:
            if group and (str(device.id), group) in grouped:
                rejected.append({"device_id": str(device.id), "label": device.label, "reason": "same_group"})
                continue
            match = decide(
                device.notify_prefs, opportunity, on_duty.get(str(device.id)),
                now=now, recent=_recent_for(counts, device),
            )
            entry = {"device_id": str(device.id), "label": device.label, "reason": match.reason}
            (recipients if match.ok else rejected).append(entry)
            if match.ok and group:
                # Som _enqueue: nästa station av samma tåg i samma cykel går inte.
                grouped.add((str(device.id), group))
        plan.append(
            {
                "opportunity_id": str(opportunity.id),
                "external_id": opportunity.external_id,
                "title": push_title(opportunity),
                "body": push_body(opportunity),
                "score": opportunity.demand_score,
                "severity_tier": opportunity.severity_tier,
                "region": opportunity.region,
                "places": opportunity.places,
                "weak": weak_round,
                "recipients": recipients,
                "rejected": rejected,
            }
        )
    return plan


# Utkorgen. En notis som inte nått fram inom PUSH_TTL är inte längre värd att
# väcka någon för; tipsets egen sluttid gäller om den kommer först.
PUSH_TTL = timedelta(minutes=30)
PUSH_MAX_ATTEMPTS = 4
# Väntan före försök 2, 3 och 4. Cykeln går var 30:e sekund.
PUSH_RETRY_BACKOFF = (timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=5))
# Hur länge en rad får ligga som `sending` innan en annan cykel tar över den. En
# worker som dödas mitt i en sändning lämnar raden så; efter lånet skickas den
# igen, och collapse key gör att telefonen visar den en gång.
SEND_LEASE = timedelta(minutes=5)
# Hur länge en notis om en händelse (group_key) räcker för föraren. Ett inställt
# tåg rullar ner längs linjen på en dryg timme; sex timmar täcker det med marginal
# utan att nästa dags tåg med samma nummer -- som har en annan nyckel -- berörs.
PUSH_GROUP_WINDOW = timedelta(hours=6)
# Leveranser som når, eller kan nå, telefonen. En notis som aldrig kom fram
# (utgången, misslyckad, undertryckt) har inte berättat något för föraren.
_DELIVERED_OR_ON_ITS_WAY = (
    PushDelivery.Status.PENDING,
    PushDelivery.Status.SENDING,
    PushDelivery.Status.SENT,
)
SEND_BATCH = 500


def run_push_cycle(now=None, sender=None, simulate: bool = False) -> dict:
    """
    Skicka notiserna för den här cykeln.

    Två steg, med utkorgen `push_delivery` emellan:

    1. **Köa.** Varje ny kandidat prövas mot varje enhet med decide(). En träff
       blir en rad med status `pending`; unikheten (enhet, tips) är
       leveransnyckeln, så en cykel som körs två gånger köar inget dubbelt.
       Därefter sätts `notified_at`, oavsett hur många som matchade. Sedan de
       svaga kandidaterna, bara mot telefoner som valt dem (weak_candidates);
       de rör inte `notified_at`.
    2. **Skicka.** Mogna rader tas med ett lån (`sending`) och skickas.
       Tillfälliga fel försöks igen med växande väntan inom notisens
       livslängd; en död token nollas; det som inte hunnit fram före
       `expires_at` markeras `expired` i stället för att väcka någon för sent.

    `sender` injiceras i testerna (och kan pekas om mot en annan transport) --
    signaturen är billing.fcm.send_push:s minus de två första argumenten.
    `simulate=True` kör hela vägen men skickar ingenting: besluten och raderna
    är riktiga, bara transporten simuleras.
    """
    from billing import fcm

    now = now or timezone.now()
    rows = candidates(now=now)
    has_due = _due(now).exists()
    weak_rows = weak_candidates(now=now)
    if not rows and not has_due and not weak_rows:
        return {"sent": 0, "candidates": 0}

    if simulate and sender is None:
        def simulated_sender(**_message):
            return {"ok": True, "simulated": True}

        sender = simulated_sender

    if rows or has_due:
        devices = _devices(require_token=not simulate)
    else:
        # Bara svaga kandidater: bara telefonerna som valt dem behöver läsas.
        devices = _devices(require_token=not simulate, weak_only=True)
    weak_devices = [d for d in devices if weak_enabled(d.notify_prefs)]
    if not rows and not has_due and not weak_devices:
        return {"sent": 0, "candidates": 0}
    if not devices and not has_due:
        # Inga enheter att skicka till. Tipsen lämnas OMARKERADE: markerade
        # hade den första föraren som installerar appen tyst gått miste om
        # allt som hände dessförinnan.
        return {"sent": 0, "candidates": len(rows), "skipped": "no_devices"}

    if sender is None:
        service_account = fcm.load_service_account(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        if not service_account:
            log.warning("notify: FIREBASE_SERVICE_ACCOUNT_JSON saknas, hoppar över push")
            return {"sent": 0, "candidates": len(rows), "skipped": "no_service_account"}
        try:
            access_token = fcm.get_access_token(service_account)
        except Exception as exc:
            reraise_time_limit(exc)
            log.warning("notify: fcm-auth misslyckades: %s", type(exc).__name__)
            return {"sent": 0, "candidates": len(rows), "error": "auth_failed"}

        def fcm_sender(**message):
            return fcm.send_push(service_account, access_token, **message)

        sender = fcm_sender

    gate: dict = {}
    if devices and rows:
        # Osäkra regler (*.ambiguous) läses av den bättre modellen innan någon
        # väcks; grinden får bara stoppa, och släpper igenom om AI:n inte svarar.
        from core import ai_gate

        rows, gate = ai_gate.screen(rows, now)
        # Räknarna följer alltid med när grinden kört, även med noll osäkra
        # kandidater: "grinden kördes men hade inget att pröva" och "grinden
        # kördes aldrig" såg annars likadana ut i svaret, och det var så
        # 0 gate-anrop på 154 osäkra tips kunde gå omärkt i tre veckor.
        gate = {"ran": True, **gate}

    briefed: dict = {}
    if devices and rows:
        # Förarbeskedet för just de tips som går ut nu, efter grinden och före
        # köandet (core/briefs.ensure). Fail-open: hinner det inte går notisen
        # med kortets vanliga text.
        from core import briefs

        try:
            briefed = dict(briefs.ensure(rows, now))
        except Exception as exc:  # ett besked får aldrig stoppa en notis
            reraise_time_limit(exc)
            log.warning("notify: besked misslyckades: %s", type(exc).__name__)
            briefed = {"error": 1}

    counts = _recent_counts(devices, now) if devices else {}
    queued = _enqueue(rows, devices, now, counts) if devices and rows else 0
    weak_queued = (
        _enqueue_weak(weak_rows, weak_devices, now, counts) if weak_devices and weak_rows else 0
    )
    sent = _send_due(sender, devices, now)
    return {
        "sent": sent["sent"],
        "failed": sent["failed"],
        "retrying": sent["retry"],
        "expired": sent["expired"],
        "queued": queued + weak_queued,
        "weakQueued": weak_queued,
        "candidates": len(rows),
        "weakCandidates": len(weak_rows),
        "devices": len(devices),
        **({"aiGate": gate} if gate else {}),
        **({"briefs": briefed} if briefed else {}),
    }


def _due(now):
    return PushDelivery.objects.filter(
        status__in=(PushDelivery.Status.PENDING, PushDelivery.Status.SENDING),
        next_attempt_at__lte=now,
    )


def _expires(opportunity, now):
    expires = now + PUSH_TTL
    if opportunity.end_time and opportunity.end_time < expires:
        expires = opportunity.end_time
    return expires


def _queue_one(device, opportunity, *, now, title, body, snapshot, expires) -> bool:
    _, created = PushDelivery.objects.get_or_create(
        device_id=device.id,
        opportunity_external_id=opportunity.external_id,
        defaults={
            "opportunity": opportunity,
            "device_token": device.token or "",
            "title": title,
            "body": body,
            "snapshot": snapshot,
            "ok": False,
            "status": PushDelivery.Status.PENDING,
            "next_attempt_at": now,
            "expires_at": expires,
        },
    )
    return created


def _grouped(devices, rows, now) -> set[tuple[str, str]]:
    """
    (enhet, händelse) som redan har en notis på väg eller framme inom
    PUSH_GROUP_WINDOW. EN fråga för hela cykeln, inte en per enhet och tips.
    """
    keys = sorted({key for key in (group_key(o) for o in rows) if key})
    if not keys or not devices:
        return set()
    return {
        (str(device_id), key)
        for device_id, key in PushDelivery.objects.filter(
            device_id__in=[d.id for d in devices],
            created_at__gte=now - PUSH_GROUP_WINDOW,
            status__in=_DELIVERED_OR_ON_ITS_WAY,
            snapshot__group__in=keys,
        ).values_list("device_id", "snapshot__group")
    }


def _enqueue(rows, devices, now, counts=None) -> int:
    queued = 0
    counts = counts if counts is not None else _recent_counts(devices, now)
    on_duty = presence_rules.fresh([d.id for d in devices], now)
    grouped = _grouped(devices, rows, now)
    for opportunity in rows:
        title = push_title(opportunity)
        body = push_body(opportunity)
        snapshot = snapshot_of(opportunity)
        group = snapshot["group"]
        expires = _expires(opportunity, now)
        with transaction.atomic():
            for device in devices:
                if group and (str(device.id), group) in grouped:
                    continue
                match = decide(
                    device.notify_prefs, opportunity, on_duty.get(str(device.id)),
                    now=now, recent=_recent_for(counts, device),
                )
                if not match:
                    continue
                if _queue_one(
                    device, opportunity, now=now, title=title, body=body,
                    snapshot={**snapshot, "weak": True} if match.weak else snapshot,
                    expires=expires,
                ):
                    queued += 1
                    _tally(counts, device, match.weak)
                    if group:
                        grouped.add((str(device.id), group))
            # notified_at sätts oavsett hur många som matchade -- även noll.
            # Tipset har passerat sin notisstund; att lämna det omarkerat hade
            # gjort att en förare som ändrar sina inställningar i morgon får en
            # notis om gårdagens störning.
            #
            # update(), aldrig save(): save() skriver hela raden och skulle
            # skriva över det pipelinen just räknat fram. Se repository.py.
            Opportunity.objects.filter(pk=opportunity.pk).update(notified_at=now)
    return queued


def _enqueue_weak(rows, devices, now, counts) -> int:
    """
    De svaga kandidaterna, bara till telefoner som valt dem. Rör aldrig
    `notified_at` (se weak_candidates). Ett tips prövas i varje cykel så länge
    det är nytt; leveranser som redan finns hoppas över med EN fråga, inte en
    per telefon och tips.
    """
    queued = 0
    on_duty = presence_rules.fresh([d.id for d in devices], now)
    already = {
        (str(device_id), external_id)
        for device_id, external_id in PushDelivery.objects.filter(
            device_id__in=[d.id for d in devices],
            opportunity_external_id__in=[o.external_id for o in rows],
        ).values_list("device_id", "opportunity_external_id")
    }
    grouped = _grouped(devices, rows, now)
    for opportunity in rows:
        title = push_title(opportunity)
        body = push_body(opportunity)
        snapshot = {**snapshot_of(opportunity), "weak": True}
        group = snapshot["group"]
        expires = _expires(opportunity, now)
        for device in devices:
            if (str(device.id), opportunity.external_id) in already:
                continue
            if group and (str(device.id), group) in grouped:
                continue
            match = decide(
                device.notify_prefs, opportunity, on_duty.get(str(device.id)),
                now=now, recent=_recent_for(counts, device),
            )
            # Bara svaga träffar här: ett tips som är notisvärt för alla tas av
            # den vanliga vägen, med notified_at.
            if not match or not match.weak:
                continue
            if _queue_one(
                device, opportunity, now=now, title=title, body=body,
                snapshot=snapshot, expires=expires,
            ):
                queued += 1
                _tally(counts, device, True)
                if group:
                    grouped.add((str(device.id), group))
    return queued


def _claim(now) -> list[PushDelivery]:
    """Ta mogna rader med ett lån. SKIP LOCKED: två cykler tar aldrig samma rad."""
    with transaction.atomic():
        claimed = list(
            _due(now).select_for_update(skip_locked=True).order_by("next_attempt_at")[:SEND_BATCH]
        )
        PushDelivery.objects.filter(id__in=[d.id for d in claimed]).update(
            status=PushDelivery.Status.SENDING, next_attempt_at=now + SEND_LEASE,
        )
    return claimed


def _send_due(sender, devices, now) -> Counter:
    from billing import fcm

    by_id = {str(device.id): device for device in devices}
    counts: Counter = Counter()
    for delivery in _claim(now):
        if delivery.expires_at and delivery.expires_at <= now:
            _finish(delivery, PushDelivery.Status.EXPIRED, error="hann inte fram inom notisens livslängd")
            counts["expired"] += 1
            continue
        device = by_id.get(str(delivery.device_id))
        if device is None:
            # Enheten har ingen token längre, eller bolaget är inte aktivt.
            _finish(delivery, PushDelivery.Status.FAILED, error="enheten tar inte längre emot notiser")
            counts["failed"] += 1
            continue

        # Förarens tystnad gäller också i det här ögonblicket: en paus, en
        # avstängning eller tysta timmar som börjat medan notisen låg i kön.
        quiet = silenced(device.notify_prefs, now)
        if quiet:
            _finish(delivery, PushDelivery.Status.SUPPRESSED, error=f"föraren har tystat notiserna: {quiet}")
            counts["suppressed"] += 1
            continue

        # Mottagaren kontrolleras HÄR, inte bara när notisen köades. Mellan de
        # två kan telefonen ha spärrats, bilen tagits över eller perioden löpt
        # ut, och kön bär en titel som beskriver ett skyddat tips (§3).
        from fleet.push_gate import can_receive

        verdict_access = can_receive(device, delivery.snapshot or {}, now=now)
        if not verdict_access.ok:
            _finish(
                delivery, PushDelivery.Status.SUPPRESSED,
                error=f"mottagaren saknar åtkomst: {verdict_access.reason}",
            )
            counts["suppressed"] += 1
            continue

        snapshot = delivery.snapshot or {}
        try:
            result = sender(
                token=device.push_token or "",
                title=delivery.title,
                body=delivery.body,
                data={
                    "opportunity_id": snapshot.get("id") or "",
                    "severity_tier": snapshot.get("severity_tier") or "",
                    "demand_score": snapshot.get("demand_score") or 0,
                    # Färdsättet följer med, så att appens banderoll visar
                    # samma ikon som listan och kartan
                    # (taxitips-app/lib/signal_kinds.categoryOfAlert). Utan det
                    # hade en färja och ett inställt tåg fått samma symbol.
                    "kind": snapshot.get("kind") or "",
                    # Backendens egen bedömning. Appen räknar annars styrkan
                    # själv ur `worth_it_score`, som inte skickas -- och då blir
                    # varje notis "Svag". `level` är samma fält listan visar.
                    "level": snapshot.get("level") or "",
                },
                # Samma händelse ersätter den förra notisen på telefonen.
                collapse_key=collapse_key(snapshot.get("group") or delivery.opportunity_external_id),
                ttl_seconds=int((delivery.expires_at - now).total_seconds()) if delivery.expires_at else None,
            )
        except Exception as exc:  # en enhets fel stoppar aldrig batchen
            reraise_time_limit(exc)
            # Bara typen i loggen: meddelandet kan bära anropets detaljer.
            log.warning("notify: sändning kastade för enhet %s: %s", delivery.device_id, type(exc).__name__)
            result = {"ok": False, "status": None, "body": str(exc)[:200]}

        verdict = fcm.outcome(result)
        attempts = delivery.attempts + 1
        error = "" if result.get("ok") else str(result.get("body") or "")[:300]
        if verdict == "sent":
            _finish(delivery, PushDelivery.Status.SENT, attempts=attempts, ok=True, sent_at=now)
            counts["sent"] += 1
        elif verdict == "retry" and attempts < PUSH_MAX_ATTEMPTS:
            PushDelivery.objects.filter(pk=delivery.pk).update(
                status=PushDelivery.Status.PENDING,
                attempts=attempts,
                next_attempt_at=now + PUSH_RETRY_BACKOFF[min(attempts, len(PUSH_RETRY_BACKOFF)) - 1],
                error=error,
            )
            counts["retry"] += 1
        else:
            if verdict == "dead_token":
                # Appen avinstallerad eller token roterad. Nolla den, annars
                # frågas enheten varje cykel om en sändning som aldrig kan gå.
                clear_push_token(delivery.device_id)
            _finish(delivery, PushDelivery.Status.FAILED, attempts=attempts, error=error)
            counts["failed"] += 1
    return counts


def _finish(delivery, status, *, attempts=None, ok=False, sent_at=None, error="") -> None:
    PushDelivery.objects.filter(pk=delivery.pk).update(
        status=status,
        ok=ok,
        sent_at=sent_at,
        error=error[:300],
        attempts=delivery.attempts if attempts is None else attempts,
        next_attempt_at=None,
    )


def collapse_key(external_id: str) -> str:
    """Samma tips ger samma nyckel: en omsänd notis ersätter den förra på telefonen."""
    return hashlib.sha1(external_id.encode("utf-8")).hexdigest()


def clear_push_token(device_id) -> None:
    from billing.models import Device

    Device.objects.filter(id=device_id).update(push_token=None)


def region_catalog() -> list[dict]:
    """Länen förarens inställningar väljer bland. Se core/coverage.py."""
    return notify_region_catalog()


__all__ = [
    "RAIL_REGION_KEY",
    "TYPE_CATALOG",
    "REASONS",
    "collapse_key",
    "decide",
    "default_prefs",
    "match_device",
    "places_match_cities",
    "plan_cycle",
    "push_body",
    "push_title",
    "region_catalog",
    "region_matches",
    "list_matches_regions",
    "within_reach",
    "run_push_cycle",
    "snapshot_of",
    "type_catalog",
    "type_enabled",
    "in_quiet_hours",
    "quiet_hours",
    "silenced",
    "weak_candidates",
    "weak_eligible",
    "weak_enabled",
]
