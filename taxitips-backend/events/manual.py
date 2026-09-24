"""
Evenemang som plattformens personal lägger in själv: ett i taget i
adminwebben, eller många från en fil (CSV eller JSON).

Källan heter `manual` och har egen rätt i settings.EVENT_SOURCES: innehållet
är vårt eget, så både lagring och visning i appen har en referens.

**Samma regler som de hämtade.** Kategori ur `timing.CATEGORY_LABELS`,
sluttid ur `timing.finish` (märkt "uppskattad" när den inte anges),
marknadsregion ur koordinaten. En rad utan koordinat avvisas i stället för att
få en påhittad: förarens läns- och avståndsfilter kräver en punkt, och ett
evenemang placerat i länets mitt skickar föraren till fel ställe (invariant 2).

**Importen är allt eller inget per anrop.** Varje rad valideras först; finns
ett enda fel sparas ingenting och svaret säger radnummer och skäl. En halv
import är svårare att rätta än ingen.

`external_id` bär en stabil nyckel (angiven, eller härledd ur namn, datum och
plats), så att samma fil kan importeras igen och uppdaterar i stället för att
dubblera.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re

from django.db import transaction
from django.utils import timezone

from core import thresholds
from events import timing
from events.models import Event

SOURCE = "manual"
MAX_ROWS = 500

# Kolumnnamn som accepteras i en fil, på svenska och engelska.
ALIASES = {
    "name": ("name", "namn", "evenemang", "titel", "title"),
    "date": ("date", "datum", "startdatum", "start_date"),
    "time": ("time", "tid", "starttid", "start_time"),
    "end_time": ("end_time", "sluttid", "slut", "end"),
    "venue": ("venue", "arena", "plats", "lokal", "venue_name"),
    "city": ("city", "stad", "ort"),
    "address": ("address", "adress"),
    "lat": ("lat", "latitude", "latitud"),
    "lon": ("lon", "lng", "longitude", "longitud"),
    "category": ("category", "kategori", "typ"),
    "attendance": ("attendance", "besokare", "besökare", "publik", "antal"),
    "url": ("url", "lank", "länk", "link"),
    "id": ("id", "external_id", "nyckel"),
}

_CATEGORY_WORDS = {
    **{key: key for key in timing.CATEGORY_LABELS},
    **{label.lower(): key for key, label in timing.CATEGORY_LABELS.items()},
    "concert": "konsert", "theatre": "teater", "theater": "teater", "comedy": "humor",
    "sports": "sport", "family": "familj", "conference": "massa", "expo": "massa",
    "mässa": "massa", "konferens": "massa", "other": "ovrigt", "övrigt": "ovrigt",
}


class ImportError_(ValueError):
    """En eller flera rader går inte att spara. `errors` = [(radnr, skäl)]."""

    def __init__(self, errors: list[tuple[int, str]]):
        super().__init__("; ".join(f"rad {n}: {why}" for n, why in errors[:5]))
        self.errors = errors


def _pick(raw: dict, field: str) -> str:
    lowered = {str(k).strip().lower(): v for k, v in raw.items()}
    for alias in ALIASES[field]:
        value = lowered.get(alias)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _float(value: str, what: str) -> float:
    try:
        return float(value.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{what} är inte ett tal") from exc


def _time(value: str) -> dt.time | None:
    if not value:
        return None
    match = re.fullmatch(r"(\d{1,2})[:.](\d{2})", value)
    if not match:
        raise ValueError(f"tiden '{value}' ska skrivas TT:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"tiden '{value}' finns inte")
    return dt.time(hour, minute)


def _category(value: str) -> str:
    if not value:
        return "ovrigt"
    key = _CATEGORY_WORDS.get(value.strip().lower())
    if key is None:
        allowed = ", ".join(sorted(timing.CATEGORY_LABELS))
        raise ValueError(f"okänd kategori '{value}' (använd: {allowed})")
    return key


def normalize(raw: dict, *, today: dt.date) -> dict:
    """Ett evenemang som fält för `Event`. Kastar ValueError med skälet på svenska."""
    name = _pick(raw, "name")[:300]
    if not name:
        raise ValueError("namn saknas")
    date_text = _pick(raw, "date")
    try:
        start_date = dt.date.fromisoformat(date_text)
    except ValueError as exc:
        raise ValueError(f"datumet '{date_text}' ska skrivas ÅÅÅÅ-MM-DD") from exc
    if start_date < today - dt.timedelta(days=1):
        raise ValueError("datumet har redan passerat")

    lat_text, lon_text = _pick(raw, "lat"), _pick(raw, "lon")
    if not lat_text or not lon_text:
        raise ValueError("koordinat saknas (lat och lon) -- välj en känd arena eller klistra in från kartan")
    lat, lon = _float(lat_text, "lat"), _float(lon_text, "lon")
    # Sverige med marginal. En omkastad koordinat (lon, lat) hamnar i Somalia.
    if not (54.5 <= lat <= 69.5 and 10.0 <= lon <= 24.5):
        raise ValueError("koordinaten ligger inte i Sverige (har lat och lon bytt plats?)")

    start_time = _time(_pick(raw, "time"))
    end_time = _time(_pick(raw, "end_time"))
    start_at = (
        dt.datetime.combine(start_date, start_time, tzinfo=timing.STOCKHOLM) if start_time else None
    )
    source_end = None
    if start_at and end_time:
        source_end = dt.datetime.combine(start_date, end_time, tzinfo=timing.STOCKHOLM)
        if source_end <= start_at:
            # Slutar efter midnatt: en klubbkväll 22:00-02:00.
            source_end += dt.timedelta(days=1)

    category = _category(_pick(raw, "category"))
    end_at, basis, note = timing.finish(start_at, source_end, start_at is not None, category, False)
    if basis == timing.BASIS_SOURCE:
        note = "Sluttid angiven av TaxiTips."

    attendance_text = _pick(raw, "attendance").replace(" ", "")
    attendance = None
    if attendance_text:
        if not attendance_text.isdigit():
            raise ValueError("besökare ska vara ett heltal")
        attendance = int(attendance_text)

    venue = _pick(raw, "venue")[:200]
    city = _pick(raw, "city")[:100]
    external = _pick(raw, "id")[:120] or _derived_id(name, start_date, venue or f"{lat:.4f},{lon:.4f}")
    url = _pick(raw, "url")[:500]
    if url and not url.startswith(("http://", "https://")):
        raise ValueError("länken ska börja med http:// eller https://")

    return {
        "external_id": external,
        "name": name,
        "url": url,
        "source_status": "",
        "category": category,
        "segment": "",
        "genre": "",
        "sub_genre": "",
        "start_date": start_date,
        "start_at": start_at,
        "time_known": start_at is not None,
        "end_at": end_at,
        "end_basis": basis,
        "end_note": note,
        "multi_day": False,
        "venue_name": venue,
        "address": _pick(raw, "address")[:200],
        "city": city,
        "lat": lat,
        "lon": lon,
        "region": thresholds.market_region(lat, lon),
        "attendance": attendance,
        "hidden_reason": "",
    }


def _derived_id(name: str, day: dt.date, place: str) -> str:
    key = f"{name.strip().lower()}|{day.isoformat()}|{place.strip().lower()}"
    return "m-" + hashlib.sha1(key.encode()).hexdigest()[:20]


def parse_file(text: str, filename: str = "") -> list[dict]:
    """CSV (komma eller semikolon, rubrikrad först) eller JSON (lista med objekt)."""
    text = (text or "").lstrip("﻿").strip()
    if not text:
        raise ImportError_([(0, "filen är tom")])
    if filename.lower().endswith(".json") or text[:1] in "[{":
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ImportError_([(0, f"JSON går inte att läsa: {exc}")]) from exc
        if isinstance(data, dict):
            data = data.get("events") or [data]
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ImportError_([(0, "JSON ska vara en lista med evenemang")])
        return data
    sample = text.split("\n", 1)[0]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def validate(rows: list[dict], *, today: dt.date | None = None) -> list[dict]:
    today = today or timezone.localdate()
    if len(rows) > MAX_ROWS:
        raise ImportError_([(0, f"högst {MAX_ROWS} rader per import")])
    out, errors = [], []
    for number, raw in enumerate(rows, start=1):
        try:
            out.append(normalize(raw, today=today))
        except ValueError as exc:
            errors.append((number, str(exc)))
    if errors:
        raise ImportError_(errors)
    return out


@transaction.atomic
def save(rows: list[dict], *, now=None) -> dict:
    now = now or timezone.now()
    created = updated = 0
    ids = []
    for row in rows:
        values = dict(row)
        external_id = values.pop("external_id")
        event, was_created = Event.objects.update_or_create(
            source=SOURCE, external_id=external_id,
            defaults={**values, "raw": {"entered_by": "admin"}, "last_seen_at": now, "missing_since": None},
        )
        ids.append(event.id)
        created += was_created
        updated += not was_created
    return {"created": created, "updated": updated, "ids": ids}


def venues(query: str, limit: int = 20) -> list[dict]:
    """Kända arenor med koordinat, ur evenemang vi redan har -- för att slippa slå upp."""
    rows = (
        Event.objects.exclude(venue_name="").exclude(lat__isnull=True)
        .filter(venue_name__icontains=query)
        .values("venue_name", "city", "address", "lat", "lon")
        .order_by("venue_name")
    )
    seen, out = set(), []
    for row in rows[:500]:
        key = (row["venue_name"].lower(), row["city"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "venue": row["venue_name"], "city": row["city"], "address": row["address"],
            "lat": round(row["lat"], 6), "lon": round(row["lon"], 6),
        })
        if len(out) >= limit:
            break
    return out
