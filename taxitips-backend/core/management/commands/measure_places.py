"""
Mäter hur många tips som visar linje, plats och "Därför" -- per källa.

    python manage.py measure_places --hours 24
    python manage.py measure_places --hours 24 --replay   # + vad dagens regler ger på samma texter

Utan --replay: det som står i databasen (det föraren ser just nu). Med
--replay läses varje tips text om med dagens regler (core/tip_text.py,
core/text_scoring.py) utan att något skrivs -- före/efter på samma data.
AI-raderna kommer ur `ai_call` för samma fönster.

Kolumner:
  rader      tips i fönstret (aktiva någon gång i det)
  ej övrigt  severity_tier != ignore
  plats      `places` inte tom
  linje      `line` inte tom
  hållplats  `station` inte tom
  koord      `station` satt OCH en koordinat som inte är länets mittpunkt
  därför     `factors` inte tom
  tomt dfr   tips som INTE är övrigt men saknar "Därför" (ska vara 0)
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Count, Q, Sum
from django.utils import timezone

from core import ai_client
from core.models import AiCall

_SQL = """
select coalesce(se.source, '?') as source,
       case when se.source = 'trafiklab' then coalesce(o.region, '?') else '' end as region,
       o.id, o.severity_tier, o.places, o.line, o.station, o.lat, o.factors, o.reasons,
       o.title, o.summary, o.mode, se.raw
from opportunities o
left join source_events se on se.id::text = (o.source_event_ids ->> 0)
where o.kind = 'transit'
  and (o.computed_at >= %s or o.end_time >= %s)
  and o.computed_at <= %s
"""


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


class Command(BaseCommand):
    help = "Linje, plats och Därför per källa, före/efter (se modulens docstring)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)
        parser.add_argument("--replay", action="store_true", help="Läs om texterna med dagens regler.")

    def handle(self, *args, hours=24, replay=False, **options):
        now = timezone.now()
        since = now - timedelta(hours=hours)
        with connection.cursor() as cur:
            cur.execute(_SQL, [since, since, now])
            rows = cur.fetchall()

        stored = defaultdict(lambda: defaultdict(int))
        replayed = defaultdict(lambda: defaultdict(int))
        for source, region, _id, tier, places, line, station, lat, factors, reasons, title, summary, mode, raw in rows:
            key = f"{source}{':' + region if region else ''}"
            reasons = _json(reasons) or []
            approx = any(str(r).startswith("plats: ungefärlig") for r in reasons)
            c = stored[key]
            c["rader"] += 1
            c["ej övrigt"] += tier != "ignore"
            c["plats"] += bool(_json(places))
            c["linje"] += bool(line)
            c["hållplats"] += bool(station)
            c["koord"] += bool(station) and lat is not None and not approx
            c["därför"] += bool(_json(factors))
            c["tomt dfr"] += tier != "ignore" and not _json(factors)
            if replay and source not in ("trafikverket_rail", "?"):
                self._replay(replayed[key], _json(raw) or {}, title, summary, region or source)

        self._table("I databasen", stored)
        if replay:
            self._table("Dagens regler på samma texter (inget skrivet)", replayed)
        self._ai(since)

    def _replay(self, c, raw: dict, title, summary, region):
        from core import taxi_context
        from core.geo import resolve_coords
        from core.ingest import text_factors
        from core.models import SeverityTier
        from core.taxi_relevance import enrich_alert
        from core.text_scoring import classify_transit_alert
        from core.tip_text import extract, registry_coords

        alert = {
            "id": "replay", "header": raw.get("header") or title or "",
            "description": raw.get("description") or summary or "",
            "cause": raw.get("cause"), "effect": raw.get("effect"), "areas": raw.get("areas") or [],
            "routes": raw.get("routes") or [], "stops": raw.get("stops") or [], "url": raw.get("url"),
            "region": raw.get("region") or region, "route_label": raw.get("route_label"),
            "mode_hint": raw.get("mode_hint"), "sl": raw.get("sl"), "vt": raw.get("vt"),
            "active_from": None, "active_to": None,
        }
        taxi = enrich_alert(alert)
        result = classify_transit_alert(alert, taxi)
        tf = extract(alert["header"], alert["description"], route_label=alert["route_label"], mode=result.mode)
        alert["_text"] = tf
        lat, _lon, precision = resolve_coords(alert, taxi)
        if tf.station and precision in ("region", "none", "gazetteer"):
            hit = registry_coords(tf.station, alert["region"])
            if hit:
                lat, precision = hit[0], "stop"
        if result.tier == SeverityTier.IGNORE:
            factors = [taxi_context.ignore_factor(result.reasons)]
        else:
            factors = text_factors(alert, result)
        c["rader"] += 1
        c["ej övrigt"] += result.tier != SeverityTier.IGNORE
        c["plats"] += bool(taxi.get("places") or tf.places)
        c["linje"] += bool(tf.line)
        c["hållplats"] += bool(tf.station)
        c["koord"] += bool(tf.station) and lat is not None and precision != "region"
        c["därför"] += bool(factors)
        c["tomt dfr"] += result.tier != SeverityTier.IGNORE and not factors

    def _table(self, heading: str, counts):
        cols = ("rader", "ej övrigt", "plats", "linje", "hållplats", "koord", "därför", "tomt dfr")
        self.stdout.write(f"\n{heading}")
        self.stdout.write(f"  {'källa':22}" + "".join(f"{c:>11}" for c in cols))
        total = defaultdict(int)
        for key in sorted(counts, key=lambda k: -counts[k]["rader"]):
            c = counts[key]
            for col in cols:
                total[col] += c[col]
            self.stdout.write(f"  {key:22}" + "".join(self._cell(c, col) for col in cols))
        self.stdout.write(f"  {'TOTALT':22}" + "".join(self._cell(total, col) for col in cols))

    @staticmethod
    def _cell(c, col) -> str:
        if col == "rader":
            return f"{c[col]:>11}"
        pct = c[col] * 100 // c["rader"] if c["rader"] else 0
        return f"{c[col]:>6} {pct:>3}%"

    def _ai(self, since):
        rows = (
            AiCall.objects.filter(created_at__gte=since)
            .values("purpose")
            .annotate(n=Count("id"), ok=Count("id", filter=Q(ok=True)),
                      tin=Sum("tokens_in"), tout=Sum("tokens_out"), cost=Sum("cost_micro_usd"))
            .order_by("purpose")
        )
        self.stdout.write("\nAI-anrop i fönstret (ai_call)")
        if not rows:
            self.stdout.write("  inga")
            return
        for r in rows:
            usd = (r["cost"] or 0) / 1_000_000
            per_call = (r["cost"] or 0) / r["ok"] / 1_000_000 if r["ok"] else 0
            self.stdout.write(
                f"  {r['purpose']:10} {r['n']:6} anrop, {r['ok']:6} ok, "
                f"{r['tin'] or 0:>9} tokens in, {r['tout'] or 0:>8} ut, "
                f"{usd:.4f} USD ({ai_client.kronor(r['cost'] or 0):.2f} kr), {per_call:.6f} USD/ok anrop"
            )
