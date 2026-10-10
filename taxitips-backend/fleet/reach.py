"""
Kontakter i Hostinger Reach, från webbformulären på taxitips.se.

Nyckeln stannar på TaxiTips-servern. Utan HOSTINGER_API_TOKEN hoppas steget
över: CRM-raden skrivs ändå.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

log = logging.getLogger(__name__)

_TIMEOUT_S = 8


def configured() -> bool:
    return bool(getattr(settings, "HOSTINGER_API_TOKEN", "") and getattr(settings, "REACH_PROFILE_UUID", ""))


def _request(method: str, path: str, body: dict | None = None) -> dict:
    token = settings.HOSTINGER_API_TOKEN
    base = settings.HOSTINGER_API_BASE.rstrip("/")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            # Cloudflare blockerar Pythons standardagent (fel 1010).
            "User-Agent": "TaxiTips/1.0 (backend.taxitips.se)",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as res:
            raw = res.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:300]
        raise RuntimeError(f"reach_{exc.code}: {detail}") from exc
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _find(email: str) -> dict | None:
    query = urllib.parse.urlencode({"search": email, "per_page": "5"})
    data = _request("GET", f"/api/reach/v1/profiles/{settings.REACH_PROFILE_UUID}/contacts?{query}")
    rows = data.get("data") if isinstance(data.get("data"), list) else []
    for row in rows:
        if str(row.get("email") or "").lower() == email:
            return row
    return None


def save_contact(*, email: str, name: str, note: str, tag: str) -> dict:
    """Skapa kontakten, eller uppdatera namn och anteckning om e-posten finns."""
    if not configured():
        return {"ok": False, "skipped": True, "reason": "reach_not_configured"}
    existing = _find(email)
    if existing and existing.get("uuid"):
        patch = {}
        if name:
            patch["name"] = name
        if note:
            patch["note"] = note[:2000]
        if patch:
            _request(
                "PATCH",
                f"/api/reach/v1/profiles/{settings.REACH_PROFILE_UUID}/contacts/{existing['uuid']}",
                patch,
            )
        return {"ok": True, "updated": True}
    _request(
        "POST",
        f"/api/reach/v1/profiles/{settings.REACH_PROFILE_UUID}/contacts",
        {
            "email": email,
            "name": name or "",
            "note": (note or "")[:2000],
            "tag_uuids": [tag] if tag else [],
        },
    )
    return {"ok": True, "created": True}
