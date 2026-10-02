"""
Supabase Auths admin-API: lösenordslänk och (för admin) borttagning av konto.

**Varför här och inte i appen.** Länken skapar kontot (eller hittar det som
redan finns) och bevisar, när föraren trycker på den, att hen kommer åt
inkorgen. Det kräver service_role-nyckeln, som aldrig får finnas i en klient.

**Varför `generate_link` och inte `/auth/v1/invite`.** `invite` skickar Supabase
Auths eget mejl, med dess mall och dess SMTP. `generate_link` ger bara länken,
och mejlet går genom vår utkorg (fleet/notifications.py): samma avsändare,
samma omförsök, samma svenska som resten av kundens post -- och inga riktiga
mejl från testerna.

**Ett konto som redan finns** (ägaren bjuder in sig själv, eller en förare som
bjudits in tidigare) ger ingen `invite`-länk -- Supabase svarar att adressen
redan är registrerad. Då blir det en `recovery`-länk i stället, som landar på
samma sida och låter föraren välja lösenord på samma sätt.

Nyckeln används bara i de här anropen. Django skriver fortfarande via sin egen
databasanslutning, inte med service_role (CLAUDE.md, regel 4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 10


class AuthAdminError(Exception):
    """Auth-adminanropet misslyckades. Meddelandet är för loggen, inte för kunden."""


@dataclass(frozen=True)
class AuthLink:
    url: str
    user_id: str | None
    kind: str  # "invite" | "recovery"


def configured() -> bool:
    return bool(
        (getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "") or "").strip()
        and (getattr(settings, "SUPABASE_URL", "") or "").strip()
    )


def _headers() -> dict:
    key = settings.SUPABASE_SERVICE_ROLE_KEY.strip()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict) -> requests.Response:
    return requests.post(
        f"{settings.SUPABASE_URL.rstrip('/')}{path}",
        json=payload,
        headers=_headers(),
        timeout=HTTP_TIMEOUT,
    )


def _delete(path: str) -> requests.Response:
    return requests.delete(
        f"{settings.SUPABASE_URL.rstrip('/')}{path}",
        headers=_headers(),
        timeout=HTTP_TIMEOUT,
    )


def _already_registered(res: requests.Response) -> bool:
    if res.status_code not in (400, 409, 422):
        return False
    text = (res.text or "").lower()
    return "email_exists" in text or "already been registered" in text or "already registered" in text


def _link_from(res: requests.Response, kind: str) -> AuthLink:
    try:
        body = res.json()
    except ValueError as exc:
        raise AuthAdminError(f"generate_link {kind}: svar utan JSON ({res.status_code})") from exc
    # GoTrue lägger länken och användaren på toppnivån; äldre versioner och
    # supabase-js-formen har dem under `properties`/`user`.
    props = body.get("properties") if isinstance(body.get("properties"), dict) else body
    user = body.get("user") if isinstance(body.get("user"), dict) else body
    url = props.get("action_link") or ""
    if not url:
        raise AuthAdminError(f"generate_link {kind}: ingen action_link i svaret")
    user_id = user.get("id")
    return AuthLink(url=url, user_id=str(user_id) if user_id else None, kind=kind)


def invite_link(email: str, redirect_to: str) -> AuthLink:
    """
    Engångslänk där föraren väljer lösenord. Skapar kontot om det inte finns.

    Kastar AuthAdminError när nyckeln saknas eller Supabase Auth inte svarar
    som väntat -- anroparen rullar då tillbaka inbjudan i stället för att lämna
    en inbjudan utan mejl.
    """
    if not configured():
        raise AuthAdminError("SUPABASE_SERVICE_ROLE_KEY saknas")
    try:
        res = _post("/auth/v1/admin/generate_link", {
            "type": "invite", "email": email, "redirect_to": redirect_to,
        })
        if res.status_code < 300:
            return _link_from(res, "invite")
        if not _already_registered(res):
            raise AuthAdminError(f"generate_link invite: {res.status_code} {res.text[:200]}")
        res = _post("/auth/v1/admin/generate_link", {
            "type": "recovery", "email": email, "redirect_to": redirect_to,
        })
        if res.status_code < 300:
            return _link_from(res, "recovery")
        raise AuthAdminError(f"generate_link recovery: {res.status_code} {res.text[:200]}")
    except requests.RequestException as exc:
        raise AuthAdminError(f"generate_link: {exc.__class__.__name__}") from exc


def delete_user(user_id: str) -> None:
    """
    Tar bort kontot i Supabase Auth. 404 räknas som OK (redan borta).
    """
    if not configured():
        raise AuthAdminError("SUPABASE_SERVICE_ROLE_KEY saknas")
    try:
        res = _delete(f"/auth/v1/admin/users/{user_id}")
    except requests.RequestException as exc:
        raise AuthAdminError(f"delete_user: {exc.__class__.__name__}") from exc
    if res.status_code in (200, 204, 404):
        return
    raise AuthAdminError(f"delete_user: {res.status_code} {res.text[:200]}")
