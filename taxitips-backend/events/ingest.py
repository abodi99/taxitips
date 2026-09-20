"""
Från källornas rådata till evenemangsrader: normalisera, bedöm, spara, rensa.

Vad som får sparas avgörs per källa av events/rights.py: Ticketmaster enligt sina
publicerade villkor, PredictHQ bara med en referens till ett skriftligt avtal. Utan
den visas PredictHQ live i pipeline-sidan (events/live.py) och sparas inte.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.db.models import Q

from core import thresholds
from events import timing
from events.rights import StorageNotPermitted, rights_for
from events.models import Event
from events.sources import predicthq, thesportsdb, ticketmaster

TICKETMASTER = "ticketmaster"
PREDICTHQ = "predicthq"
THESPORTSDB = "thesportsdb"
# Källorna poll_events går igenom. Om de får hämtas och sparas avgörs per källa och
# miljö av events/rights.py -- PredictHQ sparas inte utan skriftligt avtal.
SOURCES = (TICKETMASTER, PREDICTHQ, THESPORTSDB)
# Det första namnet; kvar så att äldre anrop fungerar.
SOURCE = TICKETMASTER

# Hämtningens fönster. Bakåt: ett evenemang som startade för en timme sedan
# och pågår är precis det föraren behöver se, men Ticketmaster filtrerar på
# starttid och skulle annars sluta lista det -- och det hade räknats som borta.
LOOKBACK = dt.timedelta(hours=12)
DEFAULT_HORIZON_DAYS = 120
# Samma kadens som CELERY_BEAT_SCHEDULE["poll-events"]. Evenemang ändras på
# dagar, och villkoren tillåter att appar som gör många anrop som inte kommer
# från en användare stryps. Fyra rundor om dygnet är ett trettiotal anrop av 5000.
CADENCE_HOURS = 6

# Ticketmasters villkor: lagring bara "for reasonable periods", och bort inom
# 24 timmar på begäran. Ett evenemang som försvunnit ur källan kan vara just
# ett sådant, så det döljs direkt och raderas efter ett dygn. Dygnet är vårt
# eget val; villkorets 24 timmar gäller borttagning på begäran.
MISSING_RETENTION = dt.timedelta(hours=24)
PAST_RETENTION = dt.timedelta(hours=24)


def build_row(raw_event: dict, source: str = TICKETMASTER) -> dict | None:
    if source == PREDICTHQ:
        return _build_predicthq(raw_event)
    elif source == THESPORTSDB:
        return _build_thesportsdb(raw_event)
    
    row = ticketmaster.normalize(raw_event)
    if row is None:
        return None
    sub_type = row.pop("sub_type")
    source_end = row.pop("source_end")
    category = timing.category_for(row["segment"], row["genre"], sub_type)
    end_at, basis, note = timing.finish(row["start_at"], source_end, row["time_known"], category, row["multi_day"])
    row.update(
        category=category,
        end_at=end_at,
        end_basis=basis,
        end_note=note,
        # Avgörs mot övriga evenemang efter sparningen -- se resolve_addons().
        hidden_reason="",
        region=_region(row),
        raw=ticketmaster.trimmed(raw_event),
    )
    return row

def _build_thesportsdb(raw_event: dict) -> dict | None:
    row = thesportsdb.normalize(raw_event)
    if row is None:
        return None
    # Segment och genre sparas: genren ("Ice Hockey") avgör sporten i filtret.
    category = timing.category_for(row["segment"], row["genre"], "")
    sport = timing.sport_for(THESPORTSDB, category, row["genre"], "", row["name"])
    source_end = row.pop("source_end")
    end_at, basis, note = timing.finish(
        row["start_at"], source_end, row["time_known"], category, row["multi_day"], sport=sport,
    )
    row.update(
        category=category,
        end_at=end_at,
        end_basis=basis,
        end_note=note,
        hidden_reason="",
        region=_region(row),
        raw=thesportsdb.trimmed(raw_event)
    )
    return row


def _build_predicthq(raw_event: dict) -> dict | None:
    """Samma regler som för Ticketmaster, för en rad som bara lever i minnet."""
    row = predicthq.normalize(raw_event)
    if row is None:
        return None
    labels = row.pop("labels")
    source_end = row.pop("source_end")
    predicted_end = row.pop("predicted_end")
    category = timing.category_for_phq(row["segment"], labels)
    end_at, basis, note = timing.finish(
        row["start_at"], source_end, row["time_known"], category, row["multi_day"], predicted_end,
    )
    row.update(category=category, end_at=end_at, end_basis=basis, end_note=note, hidden_reason="", region=_region(row))
    return row


def _region(row: dict) -> str | None:
    if row["lat"] is None or row["lon"] is None:
        return None
    return thresholds.market_region(row["lat"], row["lon"])


@transaction.atomic
def save(rows: list[dict], *, source: str, now: dt.datetime, fetched_until: dt.date, complete: bool = True) -> dict:
    """
    Spara raderna och markera det källan inte längre listar inom det hämtade fönstret.

    `complete=False` när hämtningen kapades (ett fönster med 1000 träffar eller
    fler): då är svaret ett urval, och det som saknas är inte borta ur källan.
    """
    rights = rights_for(source)
    if not rights.may_store():
        raise StorageNotPermitted(f"{source}: {rights.refusal('store')}")
    # Källans rad kan bära fält modellen inte har; bara modellens fält sparas.
    fields = {f.name for f in Event._meta.get_fields()}
    seen = set()
    created = updated = 0
    for row in rows:
        values = {key: value for key, value in row.items() if key in fields}
        external_id = values.pop("external_id")
        seen.add(external_id)
        _, was_created = Event.objects.update_or_create(
            source=source,
            external_id=external_id,
            defaults={**values, "last_seen_at": now, "missing_since": None},
        )
        created += was_created
        updated += not was_created
    missing = 0
    if complete:
        missing = (
            Event.objects.filter(source=source, start_date__lte=fetched_until, missing_since__isnull=True)
            .exclude(external_id__in=seen)
            .update(missing_since=now)
        )
    hidden = resolve_addons(source)
    return {"created": created, "updated": updated, "markedMissing": missing, "hidden": hidden}


def resolve_addons(source: str) -> int:
    """
    Dölj en tilläggsprodukt bara när huvudevenemanget finns samma dag på samma plats.

    Att dölja på namnet ensamt tog bort de största konserterna ur kalendern:
    för 12 av 13 "Platinum Tickets"-poster (mätt 2026-09-12) fanns ingen annan
    post alls. Utan huvudevenemang ÄR tilläggsposten konserten, och visas.
    Två tilläggsposter för samma föreställning blir en.
    """
    candidates = [e for e in Event.objects.filter(source=source) if timing.ADDON_PATTERN.search(e.name)]
    candidates.sort(key=lambda e: (e.start_date, e.start_at is None, e.start_at or e.first_seen_at, e.external_id))
    kept: set[tuple] = set()
    hidden = 0
    for event in candidates:
        same_place = Q(venue_id=event.venue_id) if event.venue_id else Q(address=event.address)
        main = next(
            (m for m in Event.objects.filter(same_place, source=source, start_date=event.start_date).exclude(pk=event.pk)
             if not timing.ADDON_PATTERN.search(m.name)),
            None,
        )
        if main is not None:
            reason = f'{timing.addon_reason(event.name)} Huvudevenemanget "{main.name[:50]}" finns samma dag på samma plats.'
        else:
            key = (event.start_date, event.venue_id or event.address, timing.display_name(event.name).lower())
            reason = "Samma föreställning är redan listad som en annan tilläggspost." if key in kept else ""
            kept.add(key)
        reason = reason[:200]
        if event.hidden_reason != reason:
            event.hidden_reason = reason
            event.save(update_fields=["hidden_reason"])
        hidden += bool(reason)
    return hidden


def purge(now: dt.datetime) -> dict:
    cutoff = now - PAST_RETENTION
    cutoff_date = cutoff.astimezone(timing.STOCKHOLM).date()
    missing, _ = Event.objects.filter(missing_since__lt=now - MISSING_RETENTION).delete()
    past, _ = Event.objects.filter(
        Q(end_at__lt=cutoff)
        | Q(end_at__isnull=True, start_at__lt=cutoff, multi_day=False)
        | Q(end_at__isnull=True, start_at__isnull=True, start_date__lt=cutoff_date, multi_day=False)
    ).delete()
    return {"purgedMissing": missing, "purgedPast": past}
