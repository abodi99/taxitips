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

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import areas, presence as presence_rules, thresholds
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
    {
        "id": "line_delayed",
        "label": "Förseningar",
        "short": "Linjen kör, men försenad",
        "help": "Svag signal — syns i listan, men väcker aldrig telefonen.",
        "defaultOn": False,
    },
    {
        "id": "vehicle_delayed",
        "label": "Enstaka avgång försenad",
        "short": "En avgång är sen",
        "help": "Svag signal — syns i listan, men väcker aldrig telefonen.",
        "defaultOn": False,
    },
    {
        "id": "road_work_or_queue",
        "label": "Vägarbete eller köbildning",
        "short": "Vägtrafik",
        "help": "Sällan en taxisignal — syns i listan, men väcker aldrig telefonen.",
        "defaultOn": False,
    },
]

_DEFAULT_ON = {t["id"] for t in TYPE_CATALOG if t["defaultOn"]}


def type_catalog() -> list[dict]:
    """Katalogen med en ärlig markering av vad som faktiskt kan pushas."""
    return [
        {**t, "notifiable": t["id"] in thresholds.NOTIFY_WORTHY_TIERS}
        for t in TYPE_CATALOG
    ]


def default_prefs() -> dict:
    """Vad en enhet som aldrig rört en inställning har."""
    return {
        "enabled": True,
        "types": {t["id"]: t["defaultOn"] for t in TYPE_CATALOG},
        "regions": [],
        "cities": [],
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


def type_enabled(types: dict | None, severity_tier: str | None) -> bool:
    """
    Har föraren slagit på den här händelsetypen?

    En typ som SAKNAS i sparade prefs faller tillbaka på katalogens default
    i stället för att läsas som avstängd. Annars hade varje ny installation
    börjat med noll notiser -- inklusive för den allvarligaste typen -- utan
    att någonsin ha tryckt på något. Samma semantik som NotifyPrefsSheet
    visar i appen, så reglaget och verkligheten säger samma sak.
    """
    if isinstance(types, dict) and severity_tier in types:
        return types[severity_tier] is True
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
    "type_off": "föraren har stängt av den här händelsetypen",
    "no_area": "föraren har inte valt något körområde",
    "unplaced_tip": "tipset går inte att placera i ett län",
    "outside_area": "tipset ligger utanför förarens körområde",
    "city_not_chosen": "tipset nämner ingen av förarens valda orter",
    "near_driver": "föraren är i tjänst och tipset ligger inom radien från förarens ruta",
    "too_far_from_driver": "föraren är i tjänst och tipset ligger utanför radien från förarens ruta",
}


def decide(prefs: dict | None, opportunity, presence=None) -> Match:
    """
    Ska den här enheten få den här notisen? Det enda notisbeslutet.

    Grindarna i ordning; den första som säger nej ger orsakskoden:

    1. `not_notify_worthy` -- thresholds.is_notify_worthy. Anroparen filtrerar
       redan i SQL (candidates), men kontrollen står kvar som skyddsräcke.
    2. `notifications_off`
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
    """
    if not thresholds.is_notify_worthy(
        getattr(opportunity, "severity_tier", None),
        getattr(opportunity, "demand_score", 0),
        getattr(opportunity, "has_alternative", False),
    ):
        return Match(False, "not_notify_worthy")
    if getattr(opportunity, "ai_adjusted_at", None) is not None:
        # Modellen fick höja tipset i listan, men en notis kräver regelverkets egen
        # bedömning. Nästa pollrunda skriver regelvärdena och tar bort markeringen.
        return Match(False, "ai_only")

    prefs = prefs if isinstance(prefs, dict) else {}
    if prefs.get("enabled") is False:
        return Match(False, "notifications_off")
    if not type_enabled(prefs.get("types"), opportunity.severity_tier):
        return Match(False, f"type_off:{opportunity.severity_tier}")
    if presence is not None:
        lat, lon = getattr(opportunity, "lat", None), getattr(opportunity, "lon", None)
        if lat is None or lon is None:
            return Match(False, "unplaced_tip")
        if presence_rules.distance_km(presence, lat, lon) > presence_rules.RADIUS_KM:
            return Match(False, "too_far_from_driver")
        return Match(True, "near_driver")
    # Län och kommuner i samma lista; en vald kommun ersätter sitt län.
    area = areas.device_area_codes(prefs)
    if not area:
        return Match(False, "no_area")
    tip_area = tip_area_codes(opportunity)
    if not tip_area:
        return Match(False, "unplaced_tip")
    if not set(tip_area) & set(area):
        return Match(False, "outside_area")
    if not places_match_cities(opportunity.places, prefs.get("cities")):
        return Match(False, "city_not_chosen")
    return Match(True, "match")


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
    parts = []
    summary = (opportunity.summary or "").strip()
    if summary:
        parts.append(summary[:140])
    if opportunity.is_last_departure:
        parts.append("Sista avgången — inget kommer efter.")
    elif opportunity.next_departure_minutes is not None and "nästa avgång" not in summary.lower():
        # Järnvägens summary skriver redan ut nästa avgång i sin egen text
        # ("Nästa avgång går om 20 min."). Utan den kontrollen blev
        # låsskärmsraden "... Nästa avgång går om 20 min. Nästa avgång om
        # 20 min." -- samma uppgift två gånger, i en text där varje tecken
        # konkurrerar om en sekunds uppmärksamhet.
        parts.append(f"Nästa avgång om {opportunity.next_departure_minutes} min.")
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
        "level": opportunity.level,
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
            end_time__gt=now,
            demand_score__gte=thresholds.NOTIFY_SCORE_FLOOR,
            severity_tier__in=sorted(thresholds.NOTIFY_WORTHY_TIERS),
            # Samma grind som thresholds.is_notify_worthy, i SQL: källan har
            # skrivit ut att ersättningstrafik går, och då står ingen kvar.
            # match_device kontrollerar den igen per enhet -- den här raden
            # är till för att cykeln inte ska hämta rader den ändå kastar.
            has_alternative=False,
            # Höjt av språkmodellen: aldrig ensam grund för en notis (se decide).
            ai_adjusted_at__isnull=True,
        ).order_by("-demand_score")[:limit]
    )


def _devices(require_token: bool = True):
    """
    Enheter som får ta emot notiser. Importeras lokalt: billing-modellerna
    pekar på Supabase-ägda tabeller, och core ska kunna importeras utan dem
    i en miljö där de inte migrerats.

    `require_token=False` används av simuleringsläget, som kör hela
    urvalslogiken utan att skicka något -- lokalt har ingen enhet en
    FCM-token, och utan den flaggan hade varje lokal körning svarat
    "0 notiser" oavsett hur rätt allting annat var.
    """
    from billing.models import Company, Device

    active = set(
        Company.objects.filter(status__in=("trial", "active")).values_list("id", flat=True)
    ) | set(
        Company.objects.filter(subscription_status="active").values_list("id", flat=True)
    )
    # Entitlement gäller även push: ett uppsagt bolags förare ska inte
    # väckas av data de inte får se i appen. Samma bolagskontroll som
    # core/entitlement.py gör för läsvägen -- den hade annars funnits på
    # ett ställe och saknats på det andra.
    rows = Device.objects.all()
    if require_token:
        rows = rows.exclude(push_token__isnull=True).exclude(push_token="")
    return [d for d in rows if d.company_id in active]


def plan_cycle(now=None, require_token: bool = False) -> list[dict]:
    """
    Vad en cykel SKULLE skicka, utan att skicka något.

    Finns för `manage.py push_cycle --dry-run` och för att en notis som
    uteblev ska gå att förklara utan att läsa loggar: varje enhet får sitt
    `reason` med, även när svaret är nej.
    """
    plan = []
    # Utan token-kravet som standard: en torrkörning ska svara på "vem hade
    # matchat?", och lokalt har ingen enhet en FCM-token. Ett tomt svar hade
    # sett ut som att filtren var fel, inte som att telefonerna saknas.
    devices = _devices(require_token=require_token)
    on_duty = presence_rules.fresh([d.id for d in devices], now or timezone.now())
    for opportunity in candidates(now=now):
        recipients, rejected = [], []
        for device in devices:
            match = decide(device.notify_prefs, opportunity, on_duty.get(str(device.id)))
            entry = {"device_id": str(device.id), "label": device.label, "reason": match.reason}
            (recipients if match.ok else rejected).append(entry)
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
SEND_BATCH = 500


def run_push_cycle(now=None, sender=None, simulate: bool = False) -> dict:
    """
    Skicka notiserna för den här cykeln.

    Två steg, med utkorgen `push_delivery` emellan:

    1. **Köa.** Varje ny kandidat prövas mot varje enhet med decide(). En träff
       blir en rad med status `pending`; unikheten (enhet, tips) är
       leveransnyckeln, så en cykel som körs två gånger köar inget dubbelt.
       Därefter sätts `notified_at`, oavsett hur många som matchade.
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
    if not rows and not has_due:
        return {"sent": 0, "candidates": 0}

    if simulate and sender is None:
        def simulated_sender(**_message):
            return {"ok": True, "simulated": True}

        sender = simulated_sender

    devices = _devices(require_token=not simulate)
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

    queued = _enqueue(rows, devices, now) if devices else 0
    counts = _send_due(sender, devices, now)
    return {
        "sent": counts["sent"],
        "failed": counts["failed"],
        "retrying": counts["retry"],
        "expired": counts["expired"],
        "queued": queued,
        "candidates": len(rows),
        "devices": len(devices),
    }


def _due(now):
    return PushDelivery.objects.filter(
        status__in=(PushDelivery.Status.PENDING, PushDelivery.Status.SENDING),
        next_attempt_at__lte=now,
    )


def _enqueue(rows, devices, now) -> int:
    queued = 0
    on_duty = presence_rules.fresh([d.id for d in devices], now)
    for opportunity in rows:
        title = push_title(opportunity)
        body = push_body(opportunity)
        snapshot = snapshot_of(opportunity)
        expires = now + PUSH_TTL
        if opportunity.end_time and opportunity.end_time < expires:
            expires = opportunity.end_time
        with transaction.atomic():
            for device in devices:
                if not decide(device.notify_prefs, opportunity, on_duty.get(str(device.id))):
                    continue
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
                queued += created
            # notified_at sätts oavsett hur många som matchade -- även noll.
            # Tipset har passerat sin notisstund; att lämna det omarkerat hade
            # gjort att en förare som ändrar sina inställningar i morgon får en
            # notis om gårdagens störning.
            #
            # update(), aldrig save(): save() skriver hela raden och skulle
            # skriva över det pipelinen just räknat fram. Se repository.py.
            Opportunity.objects.filter(pk=opportunity.pk).update(notified_at=now)
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
                },
                collapse_key=collapse_key(delivery.opportunity_external_id),
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
]
