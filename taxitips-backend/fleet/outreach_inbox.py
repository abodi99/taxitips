"""
Säljbrevlådans inkorg: svar och studsar (fleet/outreach.py).

**Ett svar stoppar serien.** Den som har svarat ska inte få "jag skrev
häromdagen" två dagar senare. Svaret blir en anteckning på affären och en
uppgift till säljaren -- själva samtalet förs av en människa, i brevlådan.

**En studs spärrar adressen.** Att fortsätta skicka till adresser som inte
finns är det snabbaste sättet att få en avsändare stämplad som skräppost.

**Brevlådan rörs inte.** Mejlen läses med BODY.PEEK, så ingenting markeras
som läst, flyttas eller tas bort. Hur långt vi har läst sparas hos oss
(`CrmMailboxState`), inte i brevlådan.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from dataclasses import dataclass, field
from email.message import Message
from email.utils import getaddresses, parseaddr

from django.conf import settings
from django.utils import timezone

from fleet import crm, crm_tasks, outreach
from fleet.models import CrmCampaignRecipient, CrmDeal, CrmMailboxState

log = logging.getLogger(__name__)

State = CrmCampaignRecipient.State

MAX_PER_POLL = 50
_SENT_NAMES = ("Sent", "INBOX.Sent", "Sent Items", "Sent Messages", "Skickat")

_BOUNCE_SENDER = re.compile(r"^(mailer-daemon|postmaster|mail-daemon)@", re.I)
_ADDRESS = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_HARD_STATUS = re.compile(r"^Status:\s*5\.\d+\.\d+", re.I | re.M)
_SOFT_STATUS = re.compile(r"^Status:\s*4\.\d+\.\d+", re.I | re.M)
# "Nej tack" i ett svar är en avregistrering, även utan länken.
_OPT_OUT = re.compile(
    r"\b(nej tack|avregistrera|ta bort (mig|oss|min|vår)|sluta (mejla|maila|skicka)|"
    r"inte intresserad|ej intresserad|unsubscribe|stop)\b",
    re.I,
)
_QUOTE_START = re.compile(
    r"^(>|-----\s*Ursprungligt|-----\s*Original|Den .{5,80} skrev|On .{5,80} wrote|Från:|From:)",
    re.I,
)


@dataclass
class Verdict:
    kind: str                       # "reply", "bounce", "auto", "other"
    sender: str = ""
    addresses: list[str] = field(default_factory=list)   # studsade mottagare
    hard: bool = False
    text: str = ""
    references: list[str] = field(default_factory=list)


def _text_of(message: Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return _decode(part)
        for part in message.walk():
            if part.get_content_type() == "text/html":
                return re.sub(r"<[^>]+>", " ", _decode(part))
        return ""
    return _decode(message)


def _decode(part: Message) -> str:
    raw = part.get_payload(decode=True)
    if raw is None:
        return str(part.get_payload() or "")
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


def own_words(text: str) -> str:
    """Det avsändaren själv skrev, utan det citerade mejlet under."""
    lines = []
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        if _QUOTE_START.match(line.strip()):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def classify(message: Message) -> Verdict:
    sender = outreach.normalize_email(parseaddr(message.get("From", ""))[1])
    content_type = message.get_content_type()
    report_type = str(message.get_param("report-type") or "").lower()
    whole = message.as_string()
    is_bounce = (
        bool(_BOUNCE_SENDER.match(sender))
        or (content_type == "multipart/report" and report_type == "delivery-status")
    )
    if is_bounce:
        recipients: list[str] = []
        for header in ("Final-Recipient", "Original-Recipient", "X-Failed-Recipients"):
            for match in re.finditer(rf"^{header}:\s*(.+)$", whole, re.I | re.M):
                recipients += _ADDRESS.findall(match.group(1))
        if not recipients:
            # Ingen maskinläsbar rapport: ta adresserna som nämns i texten.
            recipients = _ADDRESS.findall(_text_of(message))
        own = outreach.normalize_email(getattr(settings, "OUTREACH_SMTP_USER", ""))
        cleaned = []
        for address in recipients:
            address = outreach.normalize_email(address)
            if address and address != own and not _BOUNCE_SENDER.match(address) and address not in cleaned:
                cleaned.append(address)
        hard = bool(_HARD_STATUS.search(whole)) or not _SOFT_STATUS.search(whole)
        return Verdict(kind="bounce", sender=sender, addresses=cleaned, hard=hard)

    auto = (message.get("Auto-Submitted") or "no").strip().lower()
    precedence = (message.get("Precedence") or "").strip().lower()
    if auto != "no" or precedence in ("bulk", "junk", "auto_reply", "list") or message.get("X-Autoreply"):
        return Verdict(kind="auto", sender=sender)

    references = re.findall(r"<[^<>\s]+>", f"{message.get('In-Reply-To', '')} {message.get('References', '')}")
    return Verdict(kind="reply", sender=sender, text=own_words(_text_of(message)), references=references)


def _match_reply(verdict: Verdict) -> CrmCampaignRecipient | None:
    """Mottagaren som svarade: först på tråden, sedan på avsändaradressen."""
    base = CrmCampaignRecipient.objects.filter(step__gt=0).select_related("campaign", "account")
    if verdict.references:
        by_thread = base.filter(thread_message_id__in=verdict.references).first()
        if by_thread:
            return by_thread
    if verdict.sender:
        return base.filter(email=verdict.sender).order_by("-last_sent_at").first()
    return None


def apply(verdict: Verdict, *, subject: str = "") -> str:
    """Bokför ett mejl ur inkorgen. Returnerar vad som hände."""
    if verdict.kind == "bounce":
        if not verdict.hard:
            return "soft_bounce"
        known = set(
            CrmCampaignRecipient.objects.filter(email__in=verdict.addresses).values_list("email", flat=True)
        )
        for address in known:
            outreach.suppress(address, outreach.Reason.BOUNCED, "studs i inkorgen")
        return "bounce" if known else "bounce_unknown"
    if verdict.kind != "reply":
        return verdict.kind

    recipient = _match_reply(verdict)
    if recipient is None:
        return "unknown_sender"
    excerpt = verdict.text[:1500] or "(tomt svar)"
    opted_out = bool(_OPT_OUT.search(verdict.text[:400]))
    already = recipient.state == State.REPLIED
    if opted_out:
        outreach.suppress(recipient.email, outreach.Reason.UNSUBSCRIBED, "svarade nej tack")
        recipient.refresh_from_db()
    elif recipient.state in (State.QUEUED, State.ACTIVE, State.FINISHED):
        outreach.stop(recipient, State.REPLIED)
    if recipient.account_id or recipient.deal_id:
        crm.create_note(
            title="Svar på säljmejl" + (" (nej tack)" if opted_out else ""),
            body=f"Från {verdict.sender}\nÄmne: {subject}\n\n{excerpt}",
            account_id=recipient.account_id,
            deal_id=recipient.deal_id,
            author_label="Säljbrevlådan",
        )
    if not opted_out and not already:
        deal = CrmDeal.objects.filter(id=recipient.deal_id).first() if recipient.deal_id else None
        name = recipient.account.name if recipient.account else recipient.email
        try:
            crm_tasks.create_task(
                title=f"Svara {name} (svar på säljmejl)"[:200],
                body=f"{verdict.sender} har svarat. Svaret ligger i säljbrevlådan.\n\n{excerpt}",
                due_date=crm_tasks.today(),
                deal=deal,
            )
        except ValueError:  # pragma: no cover - titeln är aldrig tom
            pass
    return "opt_out" if opted_out else "reply"


# --- IMAP -----------------------------------------------------------------


def configured() -> bool:
    from fleet import mailer

    return mailer.outreach_configured() and bool(getattr(settings, "OUTREACH_IMAP_HOST", ""))


def _connect() -> imaplib.IMAP4_SSL:
    client = imaplib.IMAP4_SSL(
        settings.OUTREACH_IMAP_HOST, int(getattr(settings, "OUTREACH_IMAP_PORT", 993) or 993),
        timeout=20,
    )
    client.login(settings.OUTREACH_SMTP_USER, settings.OUTREACH_SMTP_PASSWORD)
    return client


def poll() -> dict:
    """Läser nya mejl i inkorgen och bokför svar och studsar."""
    if not configured():
        return {"skipped": "not_configured"}
    report: dict = {"read": 0}
    mailbox = outreach.normalize_email(settings.OUTREACH_SMTP_USER)
    state, _ = CrmMailboxState.objects.get_or_create(mailbox=mailbox)
    client = _connect()
    try:
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            return {"skipped": "no_inbox"}
        validity = _uid_validity(client)
        if validity and validity != state.uid_validity:
            # Brevlådan har byggts om: gamla UID gäller inte. Börja om från
            # det som finns nu, i stället för att läsa om hela inkorgen.
            rebuilt = bool(state.uid_validity)
            state.uid_validity = validity
            state.last_uid = _highest_uid(client) if rebuilt else 0
        status, data = client.uid("search", None, f"UID {state.last_uid + 1}:*")
        uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > state.last_uid)
        for uid in uids[:MAX_PER_POLL]:
            status, parts = client.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
            if raw:
                message = email.message_from_bytes(raw)
                try:
                    outcome = apply(classify(message), subject=str(message.get("Subject", ""))[:200])
                except Exception:
                    log.exception("fleet.outreach_inbox: kunde inte bokföra mejl %s", uid)
                    outcome = "error"
                report[outcome] = report.get(outcome, 0) + 1
                report["read"] += 1
            state.last_uid = uid
        state.checked_at = timezone.now()
        state.save()
    finally:
        try:
            client.logout()
        except Exception:  # pragma: no cover
            pass
    return report


def _uid_validity(client) -> int:
    try:
        status, data = client.response("UIDVALIDITY")
        return int(data[0]) if data and data[0] else 0
    except Exception:
        return 0


def _highest_uid(client) -> int:
    status, data = client.uid("search", None, "ALL")
    uids = [int(u) for u in (data[0] or b"").split()]
    return max(uids) if uids else 0


def append_sent(raw: bytes) -> bool:
    """Lägger en kopia av ett skickat mejl i brevlådans Skickat-mapp."""
    if not configured():
        return False
    client = _connect()
    try:
        folder = _sent_folder(client)
        if not folder:
            return False
        status, _ = client.append(folder, "\\Seen", imaplib.Time2Internaldate(timezone.now()), raw)
        return status == "OK"
    finally:
        try:
            client.logout()
        except Exception:  # pragma: no cover
            pass


def _sent_folder(client) -> str:
    status, folders = client.list()
    names: list[str] = []
    for line in folders or []:
        text = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        match = re.match(r'\((?P<flags>[^)]*)\)\s+"?[^"\s]*"?\s+"?(?P<name>.+?)"?$', text)
        if not match:
            continue
        if "\\Sent" in match.group("flags"):
            return _quote(match.group("name"))
        names.append(match.group("name"))
    for wanted in _SENT_NAMES:
        for name in names:
            if name.lower() == wanted.lower():
                return _quote(name)
    return ""


def _quote(name: str) -> str:
    return f'"{name}"' if " " in name and not name.startswith('"') else name
