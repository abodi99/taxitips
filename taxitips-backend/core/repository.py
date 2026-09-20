"""
Skrivningar mot opportunities och source_events.

Varför inte bara Model.save()
-----------------------------
`opportunities.notified_at` skrivs BARA av push-steget, och måste överleva
varje efterföljande uppdatering av raden. I Node fungerade det av en
tillfällighet: supabase-js skickar bara de kolumner man anger, så en
frånvarande kolumn lämnas orörd.

Djangos save() och update_or_create() skriver hela raden. Med dem skulle
notified_at nollas vid varje pollcykel, push-steget skulle tro att tipset
aldrig notifierats, och varje förare skulle få samma notis varje minut.

Därför namnger upsert_opportunities() sina kolumner explicit och nämner
aldrig notified_at. Använd den för allt pipeline-skrivande.
"""

from __future__ import annotations

import json
from typing import Iterable, Sequence

from django.db import connection, transaction
from django.utils import timezone

from core import areas

# Kolumner som pipelinen äger och skriver vid varje cykel.
# notified_at och expired_reason saknas MED AVSIKT -- se modulens docstring.
_OPPORTUNITY_COLUMNS: Sequence[str] = (
    "external_id",
    "kind",
    "mode",
    "severity_tier",
    "level",
    "title",
    "summary",
    "lat",
    "lon",
    "h3_index",
    "places",
    "region",
    "start_time",
    "end_time",
    "demand_score",
    "confidence",
    "reasons",
    "rule_id",
    "source_event_ids",
    "compensation_eligible",
    "compensation_amount_kr",
    "compensation_per_person",
    "next_departure_minutes",
    "next_departure_at",
    "is_last_departure",
    "has_alternative",
    "alternative_note",
    "county_code",
    "municipality_code",
    "area_codes",
    "ai_adjusted_at",
    "computed_at",
    "updated_at",
)


def upsert_opportunities(rows: Iterable[dict]) -> int:
    """
    Skriver tips, uppdaterar befintliga på external_id.

    Returnerar antal rader som skapades eller ändrades -- en rad vars
    innehåll är oförändrat skrivs inte om och räknas inte. Tomt in ger 0
    utan att röra databasen.
    """
    rows = list(rows)
    if not rows:
        return 0

    now = timezone.now()
    values = []
    for row in rows:
        row.setdefault("computed_at", now)
        # NOT NULL med default i modellen -- men den här skrivningen är rå
        # SQL som namnger varje kolumn, så en rad utan nyckeln skickar NULL
        # och avvisas av databasen. Samma mönster som computed_at ovan.
        row.setdefault("is_last_departure", False)
        row.setdefault("has_alternative", False)
        row.setdefault("alternative_note", "")
        # Länet räknas här, inte hos varje källa: alla vägar in i tabellen
        # (ingest, rail, flyg, färjor) går genom den här funktionen.
        if "county_code" not in row or "area_codes" not in row:
            county, municipality, area = areas.place_for(row.get("lat"), row.get("lon"), row.get("region"))
            row.setdefault("county_code", county)
            row.setdefault("municipality_code", municipality)
            row.setdefault("area_codes", area)
        row.setdefault("municipality_code", None)
        if not isinstance(row["area_codes"], str):
            row["area_codes"] = json.dumps(row["area_codes"])
        # Pipelinen skriver alltid regelverkets värden, aldrig modellens: en
        # AI-höjning som hunnit sättas nollställs här (se Opportunity.ai_adjusted_at).
        row["ai_adjusted_at"] = None
        row["updated_at"] = now
        values.append([row.get(col) for col in _OPPORTUNITY_COLUMNS])

    cols = ", ".join(f'"{c}"' for c in _OPPORTUNITY_COLUMNS)
    placeholders = ", ".join(["%s"] * len(_OPPORTUNITY_COLUMNS))
    # computed_at behålls från första skrivningen -- det är när tipset
    # först uppstod, inte när det senast rördes.
    updates = ", ".join(
        f'"{c}" = excluded."{c}"'
        for c in _OPPORTUNITY_COLUMNS
        if c not in ("external_id", "computed_at")
    )

    # Oförändrade rader skrivs inte om. Utan villkoret flyttades updated_at på
    # varje tips vid varje pollrunda även när ingenting hänt, så att "ändrat
    # sedan" aldrig gick att fråga efter -- och en ETag på flödet aldrig kunde
    # bli densamma två gånger i rad. Samma effekt som en innehållshash, utan
    # en ny kolumn: Postgres jämför kolumnerna direkt.
    compared = [c for c in _OPPORTUNITY_COLUMNS if c not in ("external_id", "computed_at", "updated_at")]
    changed = _is_distinct("opportunities", compared)

    sql = (
        f"insert into opportunities (id, {cols}) "
        f"values (gen_random_uuid(), {placeholders}) "
        f"on conflict (external_id) do update set {updates} "
        f"where {changed}"
    )

    with connection.cursor() as cur:
        cur.executemany(sql, values)
        # psycopg 3 summerar radantalet över alla satser i executemany.
        written = cur.rowcount
    return written


def _is_distinct(table: str, columns: Sequence[str]) -> str:
    existing = ", ".join(f'{table}."{c}"' for c in columns)
    incoming = ", ".join(f'excluded."{c}"' for c in columns)
    return f"({existing}) is distinct from ({incoming})"


_SOURCE_EVENT_COLUMNS: Sequence[str] = (
    "source",
    "external_id",
    "mode",
    "active_from",
    "active_to",
    "raw",
    "lat",
    "lon",
)


def upsert_source_events(rows: Iterable[dict]) -> dict[str, str]:
    """
    Skriver råhändelser och returnerar {external_id: id}.

    Id:na behövs för att tipsen ska kunna citera sina källor i
    source_event_ids -- det är den kopplingen förklaringspanelen bygger på.
    """
    rows = list(rows)
    if not rows:
        return {}

    values = [[row.get(col) for col in _SOURCE_EVENT_COLUMNS] for row in rows]
    cols = ", ".join(f'"{c}"' for c in _SOURCE_EVENT_COLUMNS)
    placeholders = ", ".join(["%s"] * len(_SOURCE_EVENT_COLUMNS))
    updates = ", ".join(
        f'"{c}" = excluded."{c}"'
        for c in _SOURCE_EVENT_COLUMNS
        if c != "external_id"
    )
    # fetched_at sattes bara vid första skrivningen, så en väderpunkt vars prognos byts
    # varje timme såg elva dygn gammal ut. Nu: när innehållet senast ändrades.
    updates += ', "fetched_at" = now()'

    changed = _is_distinct("source_events", [c for c in _SOURCE_EVENT_COLUMNS if c != "external_id"])
    sql = (
        f"insert into source_events (id, {cols}) "
        f"values (gen_random_uuid(), {placeholders}) "
        f"on conflict (external_id) do update set {updates} "
        f"where {changed} "
        f"returning external_id, id"
    )

    out: dict[str, str] = {}
    with connection.cursor() as cur:
        # executemany kan inte returnera rader, så en sats per rad. Volymen
        # är några hundra per cykel -- mätbart snabbt nog.
        for row_values in values:
            cur.execute(sql, row_values)
            hit = cur.fetchone()
            if hit:
                out[hit[0]] = str(hit[1])
        # En oförändrad rad skrivs inte om och returnerar därför inget id --
        # men tipsen ska fortfarande kunna citera den.
        unchanged = [row["external_id"] for row in rows if row["external_id"] not in out]
        if unchanged:
            cur.execute(
                "select external_id, id from source_events where external_id = any(%s)",
                [unchanged],
            )
            out.update({external_id: str(row_id) for external_id, row_id in cur.fetchall()})
    return out


# Gallringen i batchar: varje batch är en egen kort transaktion med
# statement_timeout, så att gallringen aldrig håller lås över hela tabellen
# medan pollarna skriver.
PURGE_BATCH_SIZE = 5000
PURGE_STATEMENT_TIMEOUT = "30s"


def purge_old(days: int = 7, batch_size: int = PURGE_BATCH_SIZE) -> dict[str, int]:
    """
    Tar bort data äldre än `days`, i batchar.

    Detta är svaret på retention-frågan: du behöver inte Firestore för att
    slippa gammal data, det räcker med en delete på schema. Schemat är
    `purge-old` i CELERY_BEAT_SCHEDULE; före P0-A5 fanns funktionen men kördes
    aldrig, och tabellerna växte obegränsat.
    """
    cutoff = timezone.now() - timezone.timedelta(days=days)
    opportunities = _delete_in_batches(
        """
        delete from opportunities where id in (
            select id from opportunities where end_time < %s limit %s
        )
        """,
        [cutoff],
        batch_size,
    )
    # Källhändelser som inget kvarvarande tips längre citerar. NOT IN mot en
    # mängd id:n i stället för `source_event_ids ? id` per rad: det senare är
    # en genomsökning av alla tips för varje källhändelse.
    source_events = _delete_in_batches(
        """
        delete from source_events where id in (
            select se.id from source_events se
            where coalesce(se.active_to, se.created_at) < %s
              and se.id::text not in (
                select jsonb_array_elements_text(o.source_event_ids)
                from opportunities o
                where jsonb_typeof(o.source_event_ids) = 'array'
              )
            limit %s
        )
        """,
        [cutoff],
        batch_size,
    )
    return {"opportunities": opportunities, "source_events": source_events}


def _delete_in_batches(sql: str, params: list, batch_size: int) -> int:
    total = 0
    while True:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"set local statement_timeout = '{PURGE_STATEMENT_TIMEOUT}'")
            cur.execute(sql, [*params, batch_size])
            deleted = cur.rowcount
        total += deleted
        if deleted < batch_size:
            return total
