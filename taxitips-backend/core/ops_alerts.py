"""
Driftlarm: ett mejl när pipelinen går från OK till FAIL, inte varje beat-cykel.

Uptime Kuma kan vakta VPS och HTTP utifrån. Den här tasken vaktar det Kuma
inte ser: beat, worker och källornas last_success_at (Trafiklab m.fl.), samma
sanning som /health/pipeline.

Mottagare: OPS_ALERT_EMAIL i miljön (Coolify), aldrig i git. Avsändare är
befintlig Hostinger-SMTP (FLEET_SMTP_*), från hej@ eller FLEET_MAIL_FROM.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from core import pipeline_health

log = logging.getLogger(__name__)

STATE_SOURCE = "ops_alert_state"
DEBOUNCE_SECONDS = 30 * 60

_PROBLEM_SV = {
    "heartbeat_missing": "Beat-hjärtslag saknas (worker/Redis/beat)",
    "heartbeat_stale": "Beat har inte tickat i tid",
    "db_unreachable": "Databasen svarar inte",
    "trafiklab_stale": "Trafiklab är för gammal",
    "trafikverket_rail_stale": "Trafikverket tåg är för gammal",
    "sl_stale": "SL är för gammal",
    "vt_stale": "Västtrafik är för gammal",
}


def recipient() -> str:
    return (getattr(settings, "OPS_ALERT_EMAIL", "") or "").strip()


def snapshot(now: dt.datetime | None = None) -> dict:
    now = now or timezone.now()
    try:
        health = pipeline_health.evaluate(now)
    except Exception:
        log.exception("ops_alerts: kunde inte läsa pipeline-hälsa")
        return {"ok": False, "problems": ["db_unreachable"]}
    return {"ok": bool(health["ok"]), "problems": list(health.get("problems") or [])}


def decide(current: dict, last: dict, *, now: dt.datetime) -> str | None:
    """
    `down` vid OK→FAIL, `up` vid FAIL→OK. Samma FAIL mejlas inte om.
    Nytt problemset under pågående FAIL mejlas tidigast efter debounce.
    Första körningen larmar bara om det redan är FAIL (ingen 'up' vid deploy).
    """
    last_ok = last.get("ok")
    problems = tuple(current.get("problems") or [])
    last_problems = tuple(last.get("problems") or [])
    if last_ok is None:
        return "down" if not current["ok"] else None
    if last_ok and not current["ok"]:
        return "down"
    if (not last_ok) and current["ok"]:
        return "up"
    if current["ok"] or problems == last_problems:
        return None
    emailed_at = last.get("emailed_at") or ""
    if emailed_at:
        try:
            then = dt.datetime.fromisoformat(emailed_at)
            if then.tzinfo is None:
                then = then.replace(tzinfo=dt.timezone.utc)
            if (now - then).total_seconds() < DEBOUNCE_SECONDS:
                return None
        except ValueError:
            pass
    return "down"


def maybe_notify(now: dt.datetime | None = None) -> dict:
    now = now or timezone.now()
    to = recipient()
    if not to:
        return {"skipped": "no_recipient"}
    current = snapshot(now)
    last = _load_state()
    action = decide(current, last, now=now)
    state = {
        "ok": current["ok"],
        "problems": current["problems"],
        "emailed_at": last.get("emailed_at"),
        "emailed_action": last.get("emailed_action"),
    }
    sent = False
    if action:
        sent = _send(_subject(action), _body(action, current), to)
        if sent:
            state["emailed_at"] = now.isoformat()
            state["emailed_action"] = action
        else:
            return {"ok": current["ok"], "problems": current["problems"], "action": action, "sent": False}
    _save_state(state, ok=current["ok"], now=now)
    return {
        "ok": current["ok"],
        "problems": current["problems"],
        "action": action,
        "sent": sent,
    }


def _load_state() -> dict:
    from core.models import SourceStatus

    row = SourceStatus.objects.filter(source=STATE_SOURCE).first()
    return dict(row.detail or {}) if row else {}


def _save_state(detail: dict, *, ok: bool, now: dt.datetime) -> None:
    from core.models import SourceStatus

    SourceStatus.objects.update_or_create(
        source=STATE_SOURCE,
        defaults={
            "ok": ok,
            "message": ",".join(detail.get("problems") or []),
            "detail": detail,
            "checked_at": now,
        },
    )


def _can_send() -> bool:
    backend = getattr(settings, "EMAIL_BACKEND", "") or ""
    if backend.endswith("locmem.EmailBackend") or backend.endswith("dummy.EmailBackend"):
        return True
    from fleet import mailer

    return mailer.configured()


def _send(subject: str, body: str, to: str) -> bool:
    if not _can_send():
        log.warning("ops_alerts: SMTP saknas, hoppar över mejl")
        return False
    from fleet import mailer, email_layout

    kwargs = {}
    backend = getattr(settings, "EMAIL_BACKEND", "") or ""
    if mailer.configured() and not backend.endswith("locmem.EmailBackend"):
        kwargs["connection"] = mailer._connection()
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=mailer.from_address(),
        to=[to],
        reply_to=[getattr(settings, "FLEET_MAIL_REPLY_TO", "") or "hej@taxitips.se"],
        headers={"X-TaxiTips-Category": "ops_alert"},
        **kwargs,
    )
    message.attach_alternative(email_layout.from_text(subject, body, {}), "text/html")
    message.send()
    return True


def _subject(action: str) -> str:
    if action == "up":
        return "[TaxiTips] Pipeline uppe igen"
    return "[TaxiTips] Pipeline nere"


def _body(action: str, current: dict) -> str:
    if action == "up":
        return (
            "Pipelinen är grön igen: /health/pipeline svarar OK.\n"
            "Beat, worker och kärnkällorna (Trafiklab, tåg, SL, Västtrafik) är färska."
        )
    labels = [_PROBLEM_SV.get(p, p) for p in current.get("problems") or []]
    listed = "\n".join(f"• {row}" for row in labels) or "• okänt"
    return (
        "Pipelinen har gått från OK till FAIL.\n\n"
        f"{listed}\n\n"
        "Kolla /health och /health/pipeline, Coolify-apparna och källstatusarna.\n"
        "Nästa mejl kommer vid återhämtning, eller om felet ändras efter 30 minuter."
    )
