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
    service_account_info: dict, access_token: str, *, token: str, title: str, body: str, data: dict | None = None
) -> dict:
    """
    Skickar ett enda push-meddelande. Returnerar {"ok": True} eller
    {"ok": False, "status": ..., "body": ...} -- kastar aldrig, exakt som
    fcmPush.js:s sendPush(): en trasig token får aldrig stoppa resten av
    batchen eller anropande task.
    """
    project_id = service_account_info["project_id"]
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    payload = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": {k: str(v) for k, v in (data or {}).items()},
        }
    }
    try:
        res = requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
    except requests.RequestException as exc:
        return {"ok": False, "status": None, "body": str(exc)[:200]}

    if res.ok:
        return {"ok": True}
    return {"ok": False, "status": res.status_code, "body": res.text[:200]}
