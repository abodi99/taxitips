"""
"I tjänst": förarens grova position för notiser nära där hen kör just nu.

Föraren slår på "I tjänst" i appen. Så länge appen är öppen skickar den sin
position (avrundad, i headern) högst var femte minut, och servern sparar bara
**rutan** positionen ligger i -- ett rutnät på ungefär 5 km -- på enhetens enda
rad. Inget sparas utan brytaren, ingen historik (raden skrivs över), och raden
gäller i `TTL`: stängs appen eller hamnar i bakgrunden slutar uppdateringarna,
och efter en halvtimme gäller körområdet igen. Ingen bakgrundsspårning.

Så länge rutan gäller ersätter den körområdet i notisbeslutet (core/notify.decide):
ett tips inom `RADIUS_KM` från rutans mitt notifieras, ett längre bort gör det inte,
oavsett län. Förarflödet påverkas inte -- det räknar på positionen i varje anrop och
sparar ingenting.

Rutan loggas inte och skickas aldrig tillbaka i något svar.
"""

from __future__ import annotations

import datetime as dt
import math

from core.geo import haversine_km

# Rutnätet: 0,05° latitud (≈ 5,6 km) och 0,1° longitud (≈ 6,4 km vid Malmö,
# ≈ 3,9 km vid Kiruna).
LAT_STEP = 0.05
LON_STEP = 0.1
TTL = dt.timedelta(minutes=30)
RADIUS_KM = 30.0
# Appen skickar inte oftare än så; servern skriver ändå bara när rutan eller
# livslängden behöver ändras.
CLIENT_INTERVAL = dt.timedelta(minutes=5)


def cell_for(lat: float, lon: float) -> tuple[float, float]:
    """Rutans mittpunkt. Två positioner i samma ruta ger samma svar."""
    cell_lat = (math.floor(lat / LAT_STEP) + 0.5) * LAT_STEP
    cell_lon = (math.floor(lon / LON_STEP) + 0.5) * LON_STEP
    return round(cell_lat, 3), round(cell_lon, 3)


def set_on_duty(device_id, lat: float, lon: float, now: dt.datetime):
    """Spara rutan på enhetens enda rad. Returnerar när den slutar gälla."""
    from core.models import DevicePresence

    cell_lat, cell_lon = cell_for(lat, lon)
    expires_at = now + TTL
    DevicePresence.objects.update_or_create(
        device_id=device_id,
        defaults={"cell_lat": cell_lat, "cell_lon": cell_lon, "updated_at": now, "expires_at": expires_at},
    )
    return expires_at


def set_off_duty(device_id) -> None:
    from core.models import DevicePresence

    DevicePresence.objects.filter(device_id=device_id).delete()


def fresh(device_ids, now: dt.datetime) -> dict:
    """Gällande rutor per enhets-id (som sträng). Utgångna räknas inte."""
    from core.models import DevicePresence

    ids = [str(d) for d in device_ids]
    if not ids:
        return {}
    rows = DevicePresence.objects.filter(device_id__in=ids, expires_at__gt=now)
    return {str(row.device_id): row for row in rows}


def distance_km(presence, lat, lon) -> float | None:
    if presence is None or lat is None or lon is None:
        return None
    return haversine_km(presence.cell_lat, presence.cell_lon, lat, lon)


def purge_expired(now: dt.datetime) -> int:
    """Utgångna rader tas bort -- de används inte, och de ska inte ligga kvar."""
    from core.models import DevicePresence

    deleted, _ = DevicePresence.objects.filter(expires_at__lte=now).delete()
    return deleted
