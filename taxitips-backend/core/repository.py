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

from typing import Iterable, Sequence

from django.db import connection
from django.utils import timezone

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
    "computed_at",
    "updated_at",
)


def upsert_opportunities(rows: Iterable[dict]) -> int:
    """
    Skriver tips, uppdaterar befintliga på external_id.

    Returnerar antal rader som skrevs. Tomt in ger 0 utan att röra
    databasen.
    """
    rows = list(rows)
    if not rows:
        return 0

    now = timezone.now()
    values = []
    for row in rows:
        row.setdefault("computed_at", now)
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

    sql = (
        f"insert into opportunities (id, {cols}) "
        f"values (gen_random_uuid(), {placeholders}) "
        f"on conflict (external_id) do update set {updates}"
    )

    with connection.cursor() as cur:
        cur.executemany(sql, values)
    return len(values)


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

    sql = (
        f"insert into source_events (id, {cols}) "
        f"values (gen_random_uuid(), {placeholders}) "
        f"on conflict (external_id) do update set {updates} "
        f"returning external_id, id"
    )

    out: dict[str, str] = {}
    with connection.cursor() as cur:
        # executemany kan inte returnera rader, så en sats per rad. Volymen
        # är några hundra per cykel -- mätbart snabbt nog.
        for row_values in values:
            cur.execute(sql, row_values)
            external_id, row_id = cur.fetchone()
            out[external_id] = str(row_id)
    return out


def purge_old(days: int = 7) -> dict[str, int]:
    """
    Tar bort data äldre än `days`.

    Detta är svaret på retention-frågan: du behöver inte Firestore för att
    slippa gammal data, det räcker med en delete på schema. Postgres
    hanterar volymen utan ansträngning -- databasen har idag 800 tips.
    """
    cutoff = timezone.now() - timezone.timedelta(days=days)
    with connection.cursor() as cur:
        cur.execute("delete from opportunities where end_time < %s", [cutoff])
        opportunities = cur.rowcount
        # Källhändelser som inget kvarvarande tips längre citerar.
        cur.execute(
            """
            delete from source_events se
            where coalesce(se.active_to, se.created_at) < %s
              and not exists (
                select 1 from opportunities o
                where o.source_event_ids ? se.id::text
              )
            """,
            [cutoff],
        )
        source_events = cur.rowcount
    return {"opportunities": opportunities, "source_events": source_events}
