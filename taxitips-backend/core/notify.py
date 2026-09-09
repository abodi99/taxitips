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

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import thresholds
from core.coverage import RAIL_REGION_KEY, notify_region_catalog
from core.geo import REGION_ANCHOR, haversine_km, resolve_place_coords
from core.models import Opportunity, PushDelivery

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


@dataclass(frozen=True)
class Match:
    """Utfallet för en enhet, med skälet kvar -- ett tyst nej går inte att felsöka."""

    ok: bool
    reason: str

    def __bool__(self) -> bool:
        return self.ok


def match_device(prefs: dict | None, opportunity) -> Match:
    """
    Ska den här enheten få den här notisen? Grind 2 och 3.

    Grind 1 (`thresholds.is_notify_worthy`) kontrolleras av anroparen, som
    kör den som ett SQL-filter över hela tabellen -- men kontrolleras även
    här, som skyddsräcke: den dagen någon anropar match_device() från ett
    nytt ställe ska den inte kunna släppa igenom en svag signal.
    """
    if not thresholds.is_notify_worthy(
        getattr(opportunity, "severity_tier", None),
        getattr(opportunity, "demand_score", 0),
        getattr(opportunity, "has_alternative", False),
    ):
        return Match(False, "not_notify_worthy")

    prefs = prefs if isinstance(prefs, dict) else {}
    if prefs.get("enabled") is False:
        return Match(False, "notifications_off")
    if not type_enabled(prefs.get("types"), opportunity.severity_tier):
        return Match(False, f"type_off:{opportunity.severity_tier}")
    if not region_matches(opportunity.region, prefs.get("regions")):
        return Match(False, f"region_not_chosen:{opportunity.region}")
    if not places_match_cities(opportunity.places, prefs.get("cities")):
        return Match(False, "city_not_chosen")
    if not within_reach(opportunity.lat, opportunity.lon, prefs.get("regions")):
        return Match(False, "too_far")
    return Match(True, "match")


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
    for opportunity in candidates(now=now):
        recipients, rejected = [], []
        for device in devices:
            match = match_device(device.notify_prefs, opportunity)
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


def run_push_cycle(now=None, sender=None, simulate: bool = False) -> dict:
    """
    Skicka notiserna för den här cykeln. Kastar aldrig.

    `sender` injiceras i testerna (och kan pekas om mot en annan transport)
    -- signaturen är billing.fcm.send_push:s, minus de två första
    argumenten som cykeln själv håller.

    `simulate=True` kör HELA vägen -- urval, matchning per enhet, bokföring
    i push_delivery, notified_at -- men skickar ingenting. Det gör
    notishistoriken och favoritlistan möjliga att prova lokalt utan ett
    Firebase-konto, på samma sätt som `simulate_stripe_event` gör
    faktureringsvägen provbar utan ett Stripe-konto. Det som simuleras är
    bara transporten; besluten är de riktiga.
    """
    from billing.fcm import get_access_token, load_service_account, send_push

    now = now or timezone.now()
    rows = candidates(now=now)
    if not rows:
        return {"sent": 0, "candidates": 0}

    if simulate and sender is None:
        def simulated_sender(*, token, title, body, data):
            return {"ok": True, "simulated": True}

        sender = simulated_sender

    devices = _devices(require_token=not simulate)
    if not devices:
        # Inga enheter att skicka till. Tipsen lämnas OMARKERADE: markerade
        # hade den första föraren som installerar appen tyst gått miste om
        # allt som hände dessförinnan.
        return {"sent": 0, "candidates": len(rows), "skipped": "no_devices"}

    if sender is None:
        service_account = load_service_account(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        if not service_account:
            log.warning("notify: FIREBASE_SERVICE_ACCOUNT_JSON saknas, hoppar över push")
            return {"sent": 0, "candidates": len(rows), "skipped": "no_service_account"}
        try:
            access_token = get_access_token(service_account)
        except Exception as exc:
            log.warning("notify: fcm-auth misslyckades: %s", exc)
            return {"sent": 0, "candidates": len(rows), "error": "auth_failed"}

        def fcm_sender(*, token, title, body, data):
            return send_push(
                service_account, access_token, token=token, title=title, body=body, data=data
            )

        sender = fcm_sender

    sent = failed = 0
    for opportunity in rows:
        title = push_title(opportunity)
        body = push_body(opportunity)
        snapshot = snapshot_of(opportunity)
        for device in devices:
            if not match_device(device.notify_prefs, opportunity):
                continue
            if PushDelivery.objects.filter(
                device_id=device.id, opportunity_external_id=opportunity.external_id
            ).exists():
                continue

            try:
                result = sender(
                    token=device.push_token or "",
                    title=title,
                    body=body,
                    data={
                        "opportunity_id": str(opportunity.id),
                        "severity_tier": opportunity.severity_tier or "",
                        "demand_score": opportunity.demand_score,
                    },
                )
            except Exception as exc:  # en enhets fel stoppar aldrig batchen
                log.warning("notify: sändning kastade för enhet %s: %s", device.id, exc)
                result = {"ok": False, "status": None, "body": str(exc)[:200]}

            _record(device, opportunity, title, body, snapshot, result)
            if result.get("ok"):
                sent += 1
            else:
                failed += 1
                if result.get("status") in (400, 404):
                    # Token död (appen avinstallerad, token roterad utan att
                    # en registrering hunnit landa). Nolla den, annars frågas
                    # enheten varje cykel om en sändning som aldrig kan gå.
                    from billing.models import Device

                    Device.objects.filter(id=device.id).update(push_token=None)

        # notified_at sätts oavsett hur många som matchade -- även noll.
        # Tipset har passerat sin notisstund; att lämna det omarkerat hade
        # gjort att en förare som ändrar sina inställningar i morgon får en
        # notis om gårdagens störning.
        #
        # update(), aldrig save(): save() skriver hela raden och skulle
        # skriva över det pipelinen just räknat fram. Se repository.py.
        Opportunity.objects.filter(pk=opportunity.pk).update(notified_at=now)

    return {"sent": sent, "failed": failed, "candidates": len(rows), "devices": len(devices)}


def _record(device, opportunity, title, body, snapshot, result) -> None:
    """
    Bokför sändningen. En krock på unikheten är inte ett fel -- det betyder
    att en parallell cykel hann först, och då är raden redan skriven.
    """
    try:
        with transaction.atomic():
            PushDelivery.objects.create(
                opportunity=opportunity,
                opportunity_external_id=opportunity.external_id,
                device_id=device.id,
                device_token=device.token or "",
                title=title,
                body=body,
                snapshot=snapshot,
                ok=bool(result.get("ok")),
                error="" if result.get("ok") else str(result.get("body") or "")[:300],
            )
    except IntegrityError:
        pass


def region_catalog() -> list[dict]:
    """Länen förarens inställningar väljer bland. Se core/coverage.py."""
    return notify_region_catalog()


__all__ = [
    "RAIL_REGION_KEY",
    "TYPE_CATALOG",
    "default_prefs",
    "match_device",
    "places_match_cities",
    "plan_cycle",
    "push_body",
    "push_title",
    "region_catalog",
    "region_matches",
    "within_reach",
    "run_push_cycle",
    "snapshot_of",
    "type_catalog",
    "type_enabled",
]
