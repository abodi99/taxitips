"""
Telefonbyte per inloggat konto.

Vad som räknas som byte
-----------------------
Ett *byte* (device swap) är när ett inloggat kontos koppling flyttar till en
*annan* Device-rad — alltså ett annat installation_id. Det sker när:

* ägar-/adminappen binder JWT:n till en ny telefon (`/api/device/session`), eller
* en förare löser in inbjudan / loggar in igen på en annan telefon
  (`claim_invite` / `_relogin`).

Första kopplingen och omstart på samma telefon räknas **inte**. Parkoppling
med engångskod (företagstelefon som flera förare delar) går inte via kontot
och räknas heller inte — invariant "en aktiv telefon per licens, en bil per
telefon" styrs fortfarande av `fleet_vehicle_session`.

Gräns: två byte per kalendermånad (Europe/Stockholm). Därefter `device_swap_limit`
tills personal med ADMIN_MANAGE ger ett extra tillfälle (`grant_extra_swap`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from billing.models import Device

STOCKHOLM = ZoneInfo("Europe/Stockholm")
MONTHLY_LIMIT = 2

LIMIT_MESSAGE = (
    "Du har bytt telefon två gånger den här månaden. "
    "Kontakta support så hjälper vi dig byta igen."
)


class DeviceSwapError(Exception):
    def __init__(self, reason: str, message: str, status: int = 403):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


def month_key(now=None) -> str:
    now = now or timezone.now()
    local = timezone.localtime(now, STOCKHOLM)
    return f"{local.year:04d}-{local.month:02d}"


def month_bounds(now=None) -> tuple[datetime, datetime]:
    """Start (inkl.) och slut (exkl.) för innevarande kalendermånad i Stockholm."""
    now = now or timezone.now()
    local = timezone.localtime(now, STOCKHOLM)
    start = datetime(local.year, local.month, 1, tzinfo=STOCKHOLM)
    if local.month == 12:
        end = datetime(local.year + 1, 1, 1, tzinfo=STOCKHOLM)
    else:
        end = datetime(local.year, local.month + 1, 1, tzinfo=STOCKHOLM)
    return start, end


def swaps_used(user_id, *, now=None) -> int:
    from fleet.models import DeviceLinkEvent

    start, end = month_bounds(now)
    return DeviceLinkEvent.objects.filter(
        user_id=user_id,
        is_swap=True,
        admin_override=False,
        created_at__gte=start,
        created_at__lt=end,
    ).count()


def grants_this_month(user_id, *, now=None) -> int:
    from fleet.models import DeviceSwapGrant

    return DeviceSwapGrant.objects.filter(
        user_id=user_id, month_key=month_key(now),
    ).count()


def remaining_swaps(user_id, *, now=None) -> int:
    return max(0, MONTHLY_LIMIT + grants_this_month(user_id, now=now) - swaps_used(user_id, now=now))


def assert_can_swap(user_id, *, admin_override: bool = False, now=None) -> None:
    if admin_override:
        return
    if remaining_swaps(user_id, now=now) <= 0:
        raise DeviceSwapError("device_swap_limit", LIMIT_MESSAGE, status=403)


def _previous_device_for_user(user_id, *, exclude_device_id=None) -> Device | None:
    qs = Device.objects.filter(user_id=user_id)
    if exclude_device_id is not None:
        qs = qs.exclude(id=exclude_device_id)
    return qs.order_by("-last_seen_at", "-created_at").first()


@transaction.atomic
def link_account_device(
    *,
    user_id,
    device: Device,
    via: str,
    previous_device_id=None,
    admin_override: bool = False,
    actor_user_id=None,
    note: str = "",
    now=None,
) -> dict:
    """
    Bind kontot till telefonen. Räknar byte om det fanns en annan Device.

    Returnerar ``{is_swap, previous_device_id, remaining}``. Höjer
    DeviceSwapError om månadskvoten är slut (om inte admin_override).
    """
    from fleet.models import DeviceLinkEvent

    now = now or timezone.now()
    user_id = str(user_id)
    if not user_id:
        raise DeviceSwapError("login_required", "Logga in för att fortsätta.", status=401)

    already = bool(device.user_id) and str(device.user_id) == user_id
    if already:
        # Samma telefon igen: städa eventuella orphan-rader, räkna inte om.
        Device.objects.filter(user_id=user_id).exclude(id=device.id).update(user_id=None)
        return {
            "is_swap": False,
            "previous_device_id": None,
            "remaining": remaining_swaps(user_id, now=now),
        }

    prev_id = previous_device_id
    if prev_id is None:
        prev = _previous_device_for_user(user_id, exclude_device_id=device.id)
        prev_id = prev.id if prev is not None else None
    else:
        prev_id = str(prev_id) if prev_id else None
        if prev_id and str(prev_id) == str(device.id):
            prev_id = None

    is_swap = bool(prev_id) and str(prev_id) != str(device.id)
    if is_swap:
        assert_can_swap(user_id, admin_override=admin_override, now=now)

    Device.objects.filter(user_id=user_id).exclude(id=device.id).update(user_id=None)
    Device.objects.filter(id=device.id).update(user_id=user_id)
    device.user_id = uuid.UUID(str(user_id))

    DeviceLinkEvent.objects.create(
        id=uuid.uuid4(),
        user_id=user_id,
        device_id=device.id,
        previous_device_id=prev_id,
        via=(via or "")[:40],
        is_swap=is_swap,
        admin_override=bool(admin_override and is_swap),
        actor_user_id=actor_user_id,
        note=(note or "")[:300],
        created_at=now,
    )
    return {
        "is_swap": is_swap,
        "previous_device_id": str(prev_id) if prev_id else None,
        "remaining": remaining_swaps(user_id, now=now),
    }


@transaction.atomic
def grant_extra_swap(*, user_id, actor_user_id, note: str = "", now=None) -> dict:
    """Personal ger ett extra bytestillfälle den här kalendermånaden."""
    from fleet.models import DeviceSwapGrant

    now = now or timezone.now()
    key = month_key(now)
    row = DeviceSwapGrant.objects.create(
        id=uuid.uuid4(),
        user_id=user_id,
        month_key=key,
        granted_by=actor_user_id,
        note=(note or "")[:300],
        created_at=now,
    )
    return {
        "grantId": str(row.id),
        "month": key,
        "remaining": remaining_swaps(user_id, now=now),
        "used": swaps_used(user_id, now=now),
        "limit": MONTHLY_LIMIT,
        "grants": grants_this_month(user_id, now=now),
    }


def summary_for(user_id, *, now=None, history_limit: int = 20) -> dict:
    from fleet.models import DeviceLinkEvent, DeviceSwapGrant

    now = now or timezone.now()
    start, end = month_bounds(now)
    used = swaps_used(user_id, now=now)
    grants = grants_this_month(user_id, now=now)
    events = list(
        DeviceLinkEvent.objects.filter(user_id=user_id).order_by("-created_at")[:history_limit]
    )
    device_ids = {e.device_id for e in events} | {
        e.previous_device_id for e in events if e.previous_device_id
    }
    labels = {
        str(d.id): (d.label or "")
        for d in Device.objects.filter(id__in=[i for i in device_ids if i])
    }
    grant_rows = list(
        DeviceSwapGrant.objects.filter(user_id=user_id).order_by("-created_at")[:10]
    )
    return {
        "limit": MONTHLY_LIMIT,
        "used": used,
        "grants": grants,
        "remaining": max(0, MONTHLY_LIMIT + grants - used),
        "month": month_key(now),
        "monthStart": start.isoformat(),
        "monthEnd": end.isoformat(),
        "history": [
            {
                "id": str(e.id),
                "at": e.created_at.isoformat() if e.created_at else None,
                "via": e.via,
                "isSwap": e.is_swap,
                "adminOverride": e.admin_override,
                "deviceId": str(e.device_id),
                "deviceLabel": labels.get(str(e.device_id), ""),
                "previousDeviceId": str(e.previous_device_id) if e.previous_device_id else None,
                "previousLabel": labels.get(str(e.previous_device_id), "") if e.previous_device_id else "",
                "note": e.note or "",
            }
            for e in events
        ],
        "grantHistory": [
            {
                "id": str(g.id),
                "at": g.created_at.isoformat() if g.created_at else None,
                "month": g.month_key,
                "note": g.note or "",
            }
            for g in grant_rows
        ],
    }
