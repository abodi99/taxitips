"""
FCM (Firebase Cloud Messaging) push-sändning, HTTP v1 API. Python-port av
taxitips-api/worker/src/fcmPush.js -- men enklare, inte en ombyggnad: Node-
versionen handrullar JWT-signering med sitt inbyggda crypto specifikt för
att slippa firebase-admin-sdk:ets gRPC/protobuf-vikt; google-auth gör redan
exakt det OAuth2 JWT-bearer-utbytet utan den vikten, så det finns ingen
anledning att portera signeringen för hand här.

Skriven generiskt (send_push tar in title/body/data direkt) så en framtida
port av fcmPush.js:s förar-opportunity-logik (uttryckligen utanför scope för
billing-appen, se billing/tasks.py) kan återanvända den här modulen rakt av.
"""

from __future__ import annotations

import base64
import json
import logging

import time
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


def load_service_account(raw: str) -> dict | None:
    """
    Accepterar antingen rå JSON eller base64-kodad JSON -- samma
    loadServiceAccount()-logik som fcmPush.js, av samma anledning: ett
    service account-nycklels private_key är självt flerradig PEM, och vissa
    env-var-lager (Coolifys inkluderat) kan förvanska en rå flerradig
    JSON-hemlighet på sätt som är svåra att diagnostisera i efterhand.
    """
    if not raw:
        return None
    candidates = [raw]
    try:
        candidates.append(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        pass  # inte giltig base64 -- rå JSON provas ändå nedan
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if parsed.get("client_email") and parsed.get("private_key") and parsed.get("project_id"):
            return parsed
    return None


def get_access_token(service_account_info: dict) -> str:
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info, scopes=[SCOPE]
    )
    credentials.refresh(Request())
    return credentials.token


def send_push(
    service_account_info: dict,
    access_token: str,
    *,
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
    collapse_key: str | None = None,
    ttl_seconds: int | None = None,
) -> dict:
    """
    Skickar ett enda push-meddelande. Returnerar {"ok": True} eller
    {"ok": False, "status": ..., "body": ..., "error_code": ...} -- kastar
    aldrig, exakt som fcmPush.js:s sendPush(): en trasig token får aldrig
    stoppa resten av batchen eller anropande task.

    `collapse_key` gör att en notis som skickas igen efter ett omförsök ersätter
    den förra på telefonen i stället för att visas två gånger. `ttl_seconds`
    låter FCM och APNs kasta notisen om telefonen inte nås i tid.
    """
    project_id = service_account_info["project_id"]
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    message = {
        "token": token,
        "notification": {"title": title, "body": body},
        "data": {k: str(v) for k, v in (data or {}).items()},
    }
    android: dict = {}
    apns_headers: dict = {}
    if collapse_key:
        android["collapse_key"] = collapse_key
        apns_headers["apns-collapse-id"] = collapse_key[:64]
    if ttl_seconds:
        android["ttl"] = f"{int(ttl_seconds)}s"
        apns_headers["apns-expiration"] = str(int(time.time()) + int(ttl_seconds))
    if android:
        message["android"] = android
        message["apns"] = {"headers": apns_headers}

    try:
        res = requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"message": message},
            timeout=10,
        )
    except requests.RequestException as exc:
        return {"ok": False, "status": None, "body": str(exc)[:200], "error_code": ""}

    if res.ok:
        return {"ok": True}
    # Hela felkroppen tolkas: errorCode ligger djupt i JSON:en och kapades bort
    # av de 200 tecken som sparas.
    return {"ok": False, "status": res.status_code, "body": res.text[:2000], "error_code": error_code(res.text)}


# FCM v1:s felkoder som betyder att token aldrig kommer att fungera igen.
# https://firebase.google.com/docs/reference/fcm/rest/v1/ErrorCode
_DEAD_TOKEN_CODES = frozenset({"UNREGISTERED", "SENDER_ID_MISMATCH"})
_RETRY_CODES = frozenset({"UNAVAILABLE", "INTERNAL", "QUOTA_EXCEEDED"})
# None = nätverksfel. 401 = åtkomsttoken har gått ut; nästa cykel hämtar en ny.
_RETRY_STATUS = frozenset({None, 401, 429, 500, 502, 503, 504})


def error_code(body: str | None) -> str:
    try:
        error = (json.loads(body or "") or {}).get("error") or {}
    except (ValueError, AttributeError):
        return ""
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("errorCode"):
            return str(detail["errorCode"])
    return str(error.get("status") or "")


def outcome(result: dict) -> str:
    """
    Vad ett svar från send_push betyder för leveransen:

    * "sent"
    * "retry" -- tillfälligt: nätverk, kvot, serverfel, utgången åtkomsttoken
    * "dead_token" -- appen avinstallerad, eller token från ett annat projekt
    * "failed" -- permanent, men token kan vara hel (t.ex. fel i meddelandet)

    Tidigare nollades token vid varje 400 och 404. En 400 kan lika gärna vara
    ett fel i meddelandet, och då hade en fungerande telefon tystats för gott.
    """
    if result.get("ok"):
        return "sent"
    status = result.get("status")
    body = str(result.get("body") or "")
    code = result.get("error_code") or error_code(body)
    if code in _DEAD_TOKEN_CODES:
        return "dead_token"
    if code == "INVALID_ARGUMENT" and "registration token" in body.lower():
        return "dead_token"
    if status in _RETRY_STATUS or code in _RETRY_CODES:
        return "retry"
    return "failed"
