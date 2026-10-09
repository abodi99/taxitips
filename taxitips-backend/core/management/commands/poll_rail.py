"""
Hämtar järnvägsstörningar och skriver dem som tips.

Kör så här:
    python manage.py poll_rail            # en cykel
    python manage.py poll_rail --dry-run  # visa utan att skriva
"""

import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from core.alternatives import route_note

from core.health import polling
from core.models import Opportunity, SourceStatus, Station
from core.repository import upsert_opportunities, upsert_source_events
from core.scoring import classify, taxi_outcome
from core.sources import resrobot
from core.sources.smhi import cached_region_weather
from core.sources.trafikverket_rail import TrafikverketRail

# Frågan till Trafikverket ser bara avgångar vars ANNONSERADE tid ligger framåt
# (`AdvertisedTimeAtLocation > $now`). Ett tåg vars avgångstid passerat saknas
# därför i nästa hämtning utan att störningen är över: de som står kvar efter ett
# inställt eller försenat tåg är just det tipset handlar om, och tipset lever till
# sin egen sluttid (trafikverket_rail.platform_end). Bara en avgång som fortfarande
# borde ha kommit med i hämtningen och saknas har försvunnit ur källan.
# Marginalen täcker klockskillnaden mot Trafikverkets $now.
DEPARTED_MARGIN = timedelta(minutes=2)


def close_vanished(current_ids: list[str], now) -> int:
    """Avslutar järnvägstips vars avgång ännu inte gått men som saknas i hämtningen."""
    return (
        Opportunity.objects.filter(kind="transit", external_id__startswith="tvr:")
        .filter(Q(end_time__gt=now) | Q(end_time__isnull=True))
        .filter(Q(departure_at__isnull=True) | Q(departure_at__gt=now + DEPARTED_MARGIN))
        .exclude(external_id__in=current_ids)
        .update(end_time=now, expired_reason="source_removed", updated_at=now)
    )


def rail_line(a) -> str:
    """Produkt + tågnummer, som i rubriken (core/sources/trafikverket_rail.py)."""
    brand = a.product or a.information_owner or a.operator
    if not a.train:
        return brand or ""
    return f"{brand} {a.train}" if brand else f"Tåg {a.train}"


class Command(BaseCommand):
    help = "Hämtar och poängsätter järnvägsstörningar från Trafikverket"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        # Bokför utfallet oavsett hur det går -- en källa som slutat
        # svara ska synas som trasig, inte som lugn trafik. Se
        # core/health.py.
        with polling("trafikverket_rail") as status:
            self._poll(options, status)

    def _poll(self, options, status):
        key = settings.TRAFIKVERKET_API_KEY
        if not key:
            self.stderr.write("TRAFIKVERKET_API_KEY saknas")
            return

        client = TrafikverketRail(key)
        previous = (
            SourceStatus.objects.filter(source="trafikverket_rail").values_list("detail", flat=True).first() or {}
        )
        finder = None
        if settings.RESROBOT_API_KEY:
            # Nästa resa mot samma slutstation för inställda tåg -- se core/sources/resrobot.py.
            now = timezone.now()
            finder = resrobot.AlternativeFinder(
                settings.RESROBOT_API_KEY, stations=client.stations(), now=now,
                state=previous.get("resrobot"), previous=resrobot.previous_answers(now),
            )
        alerts = client.fetch(alternative_for=finder)
        status.events = len(alerts)
        # Unika inställda tåg i fönstret, sidor och komplett-flagga; ResRobot-budgeten och
        # hållplats-id:n bärs vidare till nästa runda här.
        status.detail = {**client.last_stats, **({"resrobot": finder.detail()} if finder else {})}
        if client.last_stats.get("complete") is False:
            status.note = "ofullständig hämtning: sidtaket nåddes"

        # Stationsregistret sparas i stället för att bara leva i processens
        # minne. rail_station-tabellen fanns men inget skrev till den, så
        # den stod på noll rader medan varje pollcykel hämtade samma ~1000
        # stationer på nytt -- och ingen annan del av systemet kunde slå upp
        # en stationskoordinat.
        stations = client.stations()
        if stations:
            now = timezone.now()
            Station.objects.bulk_create(
                [
                    Station(signature=s.signature, name=s.name, lat=s.lat, lon=s.lon, fetched_at=now)
                    for s in stations.values()
                ],
                update_conflicts=True, unique_fields=["signature"],
                update_fields=["name", "lat", "lon", "fetched_at"],
            )
        if not alerts:
            self.stdout.write("inga störningar just nu")
            return

        region_weather = [] if options["dry_run"] else cached_region_weather()
        assessed = [
            (a, r, *taxi_outcome(a, r, region_weather))
            for a, r in ((a, classify(a)) for a in alerts)
        ]

        if options["dry_run"]:
            for a, r, _comp, o in sorted(assessed, key=lambda p: -p[3].score):
                self.stdout.write(f"  {o.score:3} {o.level:6} {r.tier:22} {a.header[:56]}")
            self.stdout.write(f"\n{len(alerts)} störningar (inget skrevs)")
            return

        # Källhändelserna först: tipsen citerar deras id:n, och det är den
        # kopplingen förarens förklaringspanel bygger på.
        source_ids = upsert_source_events([
            {
                "source": "trafikverket_rail",
                "external_id": a.external_id,
                "mode": "train",
                "active_from": a.active_from,
                "active_to": a.active_to,
                "raw": json.dumps({
                    "header": a.header, "description": a.description,
                    "station": a.station, "train": a.train,
                    "cancelled": a.cancelled,
                    "departure_at": a.departure_at.isoformat() if a.departure_at else None,
                    "next_departure_minutes": a.next_departure_minutes,
                    "next_departure_is_bus": a.next_departure_is_bus,
                    "is_last_departure": a.is_last_departure,
                    "track": a.track, "product": a.product,
                    "operator": a.operator, "information_owner": a.information_owner,
                    "destination": a.destination, "cause": a.cause,
                    "web_link": a.web_link or None, "web_link_name": a.web_link_name or None,
                    "has_replacement": a.has_replacement,
                    "replacement_mode": a.replacement_mode,
                    "replacement_note": a.replacement_note,
                    "alternative_basis": a.alternative_basis,
                    "alternative": a.alternative,
                }, ensure_ascii=False),
                "lat": a.lat, "lon": a.lon,
            }
            for a in alerts
        ])

        written = upsert_opportunities([
            {
                "external_id": a.external_id,
                "kind": "transit",
                "mode": "train",
                "severity_tier": r.tier,
                # Läge + omständigheter, räknat i scoring.taxi_outcome. Flödet
                # och notiserna läser styrkan härifrån.
                "level": o.level,
                "factors": json.dumps(o.factors, ensure_ascii=False),
                "title": a.header,
                "summary": a.description,
                # Linjen som på tavlan ("Pågatågen 1612") och stationen -- samma
                # ord som rubriken, ur Trafikverkets egna fält.
                "line": rail_line(a)[:60],
                "station": (a.station or "")[:120],
                "lat": a.lat, "lon": a.lon,
                "h3_index": "",
                "places": json.dumps([a.station], ensure_ascii=False),
                "region": "rail",
                "start_time": a.active_from,
                "end_time": a.active_to,
                "demand_score": o.score,
                "confidence": r.confidence,
                "reasons": json.dumps([*r.reasons, *o.reasons], ensure_ascii=False),
                "rule_id": r.rule_id,
                "source_event_ids": json.dumps(
                    [source_ids[a.external_id]] if a.external_id in source_ids else []
                ),
                # Bara regionala tåg vi kan knyta till en huvudman, och bara
                # när väntan säkert når gränsen -- se compensation.rail_region.
                "compensation_eligible": bool(comp),
                "compensation_amount_kr": comp["cap_kr"] if comp else None,
                "compensation_per_person": comp.get("per_person") if comp else None,
                # Signalerna som gav tiern, sparade som tal -- se
                # Opportunity.next_departure_minutes.
                "next_departure_minutes": a.next_departure_minutes,
                "next_departure_at": a.next_departure_at,
                # Den drabbade avgången -- det föraren ska se först.
                "departure_at": a.departure_at,
                "destination": a.destination,
                "delay_minutes": None if a.cancelled else a.delay_minutes,
                "is_last_departure": a.is_last_departure,
                # Trafikverkets ReplacementTraffic säger rakt ut när
                # ersättningstrafik är insatt -- den starkaste signalen vi
                # har för "resenären står inte kvar", och den nådde
                # tidigare aldrig längre än till poängformeln.
                # En bussavgång från samma station är också ett alternativ,
                # även när Trafikverket inte kopplat den som
                # ersättningstrafik: 16 av 82 inställda avgångar hade en
                # bussavgång inom en timme (docs/api-field-inventory.md).
                "has_alternative": a.has_replacement or a.next_departure_is_bus,
                "alternative_note": (
                    a.replacement_note
                    or (
                        route_note(a.destination, a.alternative_label,
                                   f"{timezone.localtime(a.next_departure_at):%H:%M}",
                                   int((a.alternative or {}).get("changes") or 0))
                        if a.alternative_basis == "resrobot" and a.next_departure_at else ""
                    )
                    or ("Nästa avgång härifrån är en buss" if a.next_departure_is_bus else "")
                ),
            }
            for a, r, comp, o in assessed
        ])

        if client.last_stats.get("complete") is not False:
            close_vanished([a.external_id for a in alerts], timezone.now())

        status.written = written
        spread = sorted({o.score for _a, _r, _c, o in assessed}, reverse=True)
        self.stdout.write(self.style.SUCCESS(
            f"skrev {written} tips | poängnivåer: {spread}"
        ))
