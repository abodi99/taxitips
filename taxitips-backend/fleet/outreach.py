"""
Säljutskick ur CRM: vilka som får mejl, i vilken takt och när serien stannar.

**Bara juridiska personer.** Ett aktiebolag får kontaktas med e-post om det går
att tacka nej (marknadsföringslagen 19 §). En enskild firma är en fysisk person
och kräver samtycke i förväg -- de ringer säljaren, och de kommer aldrig med i
urvalet här. Samma sak med bolag vars form vi inte känner till.

**Långsamt.** taxitips.se har nästan ingen sändhistorik. Brevlådan börjar på
15 mejl om dagen och ökar med 10 var tredje sändningsdag, upp till kampanjens
tak. Mejlen går på vardagar under kontorstid, några åt gången med paus emellan.
Ett utskick som går fortare än så ser ut som ett massutskick, hos filtren och
hos mottagaren.

**Serien stannar av sig själv.** Ett svar, en avregistrering, en studs, ett
startat prov eller en säljare som har flyttat affären vidare -- vilket som helst
av dem betyder att nästa mejl inte ska gå. Och kampanjen pausar sig själv om
för många studsar eller avregistrerar sig: då är det listan eller texten det
är fel på, inte mottagarna.

**Skickat finns på ett ställe.** Varje mejl är en rad i utkorgen
(`OutboxMessage`, kategori `outreach_<steg>`). Mottagarraden håller bara reda
på var i serien bolaget är.
"""

from __future__ import annotations

import base64
import logging
import math
import random
import re
import time as time_module
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from fleet import notifications, outreach_templates
from fleet.models import (
    CompanyProfile,
    CrmAccount,
    CrmCampaign,
    CrmCampaignRecipient,
    CrmDeal,
    CrmDealStage,
    CrmEmailSuppression,
    CrmPerson,
    CrmTagging,
    OutboxMessage,
)

log = logging.getLogger(__name__)

State = CrmCampaignRecipient.State
Reason = CrmEmailSuppression.Reason

CATEGORY_PREFIX = notifications.MARKETING_PREFIX
STEP_COUNT = outreach_templates.STEP_COUNT

JURIDICAL_FORMS = frozenset({
    "aktiebolag", "handelsbolag", "kommanditbolag", "ekonomisk förening",
})

# Säljaren har inte rört affären. Allt annat (möte, offert, vunnen, förlorad)
# betyder att en människa har tagit över eller sagt nej.
UNTOUCHED_STAGES = frozenset({CrmDealStage.NEW, CrmDealStage.SCREENING})

# Kommuner och regioner beställer färdtjänst; de köper inte ett förarverktyg.
_PUBLIC_SECTOR = re.compile(r"(kommun|region|landsting)", re.I)
_EMAIL = re.compile(r"^[^@\s]+@[A-Za-z0-9åäöÅÄÖ.\-]+\.[A-Za-z]{2,}$")

# Sändningsfönster, svensk tid. Tisdag förmiddag läses ett mejl; lördag kväll
# ser det ut som en robot.
WINDOW_START = time(8, 30)
WINDOW_END = time(15, 30)
TICK_MINUTES = 10
MAX_PER_TICK = 3

# Uppvärmning: dagstak = start + steg för var tredje dag det har skickats.
WARMUP_START = 15
WARMUP_STEP = 10
WARMUP_EVERY_DAYS = 3

# När nästa mejl går, efter det som just skickades.
STEP2_WORKDAYS = 4
STEP3_DAYS = 9

# Automatisk broms, räknad på de senaste sju dagarnas utskick.
GUARD_MIN_SENT = 20
GUARD_BOUNCE_RATE = 0.05
# Två studsar på de första 26 mejlen pausade kampanjen 2026-11-24 (en död
# Yahoo-adress och en nedlagd domän). Under tre studsar är andelen slump.
GUARD_MIN_BOUNCES = 3
GUARD_UNSUBSCRIBE_RATE = 0.03

# Röda dagar med fast datum. Rörliga helgdagar (påsk, midsommar) faller oftast
# på helg eller fångas av att ingen svarar -- ett mejl för mycket, inte ett fel.
_HOLIDAYS = frozenset({(1, 1), (1, 6), (5, 1), (6, 6), (12, 24), (12, 25), (12, 26), (12, 31)})

_TOKEN_SALT = "fleet.outreach.unsubscribe"
_TICK_LOCK = "fleet:outreach:tick"


# --- Adresser och spärrlista -----------------------------------------------


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def valid_email(value: str) -> bool:
    return bool(_EMAIL.match(value)) and len(value) <= 254


def domain_receives_mail(domain: str) -> bool:
    """
    Har domänen en brevlåda över huvud taget? "hotmail.com_" och "gmail.se"
    studsar varje gång, och studsar är det som snabbast förstör en avsändares
    rykte. Kan vi inte fråga (inget nät, tidsgräns) släpps adressen igenom:
    ett nätfel hos oss ska inte stryka ett bolag ur listan.
    """
    try:
        import dns.exception
        import dns.resolver
    except ImportError:  # pragma: no cover - dnspython följer med Django-miljön
        return True
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4
    for record in ("MX", "A"):
        try:
            if resolver.resolve(domain, record):
                return True
        except dns.resolver.NXDOMAIN:
            return False
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            continue
        except dns.exception.DNSException:
            return True
    return False


def is_suppressed(email: str) -> bool:
    email = normalize_email(email)
    return bool(email) and CrmEmailSuppression.objects.filter(email=email).exists()


_STATE_FOR_REASON = {
    Reason.UNSUBSCRIBED: State.UNSUBSCRIBED,
    Reason.COMPLAINT: State.UNSUBSCRIBED,
    Reason.BOUNCED: State.BOUNCED,
}


def suppress(email: str, reason: str, detail: str = "") -> bool:
    """
    Spärrar adressen för säljmejl och stoppar serierna den är med i. Returnerar
    True om spärren är ny. En befintlig spärr skrivs inte över: den första
    orsaken är den som gäller.
    """
    email = normalize_email(email)
    if not email:
        return False
    _, created = CrmEmailSuppression.objects.get_or_create(
        email=email, defaults={"reason": reason, "detail": (detail or "")[:500]},
    )
    now = timezone.now()
    CrmCampaignRecipient.objects.filter(
        email=email, state__in=[State.QUEUED, State.ACTIVE, State.FINISHED],
    ).update(
        state=_STATE_FOR_REASON.get(reason, State.STOPPED),
        next_send_at=None, stopped_at=now, updated_at=now,
    )
    OutboxMessage.objects.filter(
        to_address__iexact=email, status=OutboxMessage.Status.PENDING,
        category__startswith=CATEGORY_PREFIX,
    ).update(status=OutboxMessage.Status.SUPPRESSED, error="mottagaren är spärrad")
    return created


# --- Avregistreringslänken -------------------------------------------------


def _signer() -> signing.Signer:
    # "." som skiljetecken: ett kolon i en länk klipps av en del mejlklienter.
    return signing.Signer(salt=_TOKEN_SALT, sep=".")


def token_for(recipient: CrmCampaignRecipient) -> str:
    """Mottagarens id, signerat. Kort, så att länken inte bryts över flera rader."""
    packed = base64.urlsafe_b64encode(recipient.id.bytes).rstrip(b"=").decode()
    return _signer().sign(packed)


def recipient_from_token(token: str) -> CrmCampaignRecipient | None:
    try:
        packed = _signer().unsign(token or "")
        recipient_id = uuid.UUID(bytes=base64.urlsafe_b64decode(packed + "=="))
    except (signing.BadSignature, ValueError):
        return None
    return CrmCampaignRecipient.objects.filter(id=recipient_id).first()


def unsubscribe(token: str) -> bool:
    """Avregistrerar adressen bakom länken. Att göra det två gånger är inget fel."""
    recipient = recipient_from_token(token)
    if recipient is None:
        return False
    suppress(recipient.email, Reason.UNSUBSCRIBED, "avregistreringslänken")
    return True


def unsubscribe_urls(recipient: CrmCampaignRecipient) -> tuple[str, str]:
    """(sidan i mejltexten, enklicksadressen i List-Unsubscribe)."""
    token = token_for(recipient)
    site = (getattr(settings, "OUTREACH_SITE_BASE", "") or "https://taxitips.se").rstrip("/")
    api = (getattr(settings, "OUTREACH_API_BASE", "") or "https://backend.taxitips.se").rstrip("/")
    return f"{site}/avregistrera?t={token}", f"{api}/api/crm/avregistrera/{token}"


# --- Urval ------------------------------------------------------------------


@dataclass
class Candidate:
    account: CrmAccount
    person_id: object | None
    deal_id: object | None
    email: str
    priority: int
    skip: str = ""   # tomt = kommer med


_SEGMENT_RANK = {"segment:a": 0, "segment:b": 1, "segment:c": 2, "segment:d": 3}


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def customer_orgs() -> set[str]:
    """Organisationsnummer som redan har ett konto hos oss (prov eller kund)."""
    return {
        _digits(org)
        for org in CompanyProfile.objects.exclude(org_number="").values_list("org_number", flat=True)
    } - {""}


def audience(
    campaign: CrmCampaign | None = None, *, segments: set[str] | None = None,
    check_dns: bool = False,
) -> list[Candidate]:
    """
    Alla CRM-konton, med skälet till att ett konto INTE kommer med. Att
    uteslutningarna räknas är poängen: en torrkörning ska visa vad som föll
    bort och varför, inte bara hur många som blev kvar.
    """
    people: dict = {}
    for person in (
        CrmPerson.objects.exclude(email="").exclude(account_id=None)
        .order_by("account_id", "-updated_at")
        .values("id", "account_id", "email")
    ):
        people.setdefault(person["account_id"], person)

    deals: dict = {}
    for deal in (
        CrmDeal.objects.exclude(account_id=None).order_by("account_id", "-updated_at")
        .values("id", "account_id", "stage", "company_id")
    ):
        deals.setdefault(deal["account_id"], deal)

    tags: dict = {}
    for entity_id, slug in CrmTagging.objects.filter(
        entity_type=CrmTagging.EntityType.ACCOUNT,
        tag__category__in=["segment", "call"],
    ).values_list("entity_id", "tag__slug"):
        tags.setdefault(entity_id, set()).add(slug)

    suppressed = set(CrmEmailSuppression.objects.values_list("email", flat=True))
    enrolled = set(CrmCampaignRecipient.objects.values_list("email", flat=True))
    customers = customer_orgs()

    out: list[Candidate] = []
    seen: set[str] = set()
    domains: dict[str, bool] = {}

    def receives(address: str) -> bool:
        domain = address.split("@", 1)[1]
        if domain not in domains:
            domains[domain] = domain_receives_mail(domain)
        return domains[domain]

    for account in CrmAccount.objects.order_by("name", "id"):
        slugs = tags.get(account.id, set())
        segment = next((s for s in _SEGMENT_RANK if s in slugs), "segment:d")
        tier = next(
            (int(s.split(":")[1]) for s in sorted(slugs) if s.startswith("call:") and s[5:].isdigit()),
            6,
        )
        person = people.get(account.id)
        deal = deals.get(account.id)
        email = normalize_email(person["email"]) if person else ""
        candidate = Candidate(
            account=account,
            person_id=person["id"] if person else None,
            deal_id=deal["id"] if deal else None,
            email=email,
            priority=_SEGMENT_RANK[segment] * 100 + tier * 10,
        )
        form = (account.legal_form or "").strip().lower()
        if not form:
            candidate.skip = "okänd bolagsform"
        elif form not in JURIDICAL_FORMS:
            candidate.skip = "enskild firma eller annan fysisk person"
        elif "segment:x" in slugs:
            candidate.skip = "ring ej"
        elif not email:
            candidate.skip = "ingen e-post"
        elif not valid_email(email):
            candidate.skip = "ogiltig e-post"
        elif _PUBLIC_SECTOR.search(email.split("@", 1)[1]):
            candidate.skip = "offentlig beställare"
        elif email in suppressed:
            candidate.skip = "spärrad adress"
        elif deal and deal["company_id"]:
            candidate.skip = "redan kund"
        elif _digits(account.org_number) in customers:
            candidate.skip = "redan kund"
        elif deal and deal["stage"] not in UNTOUCHED_STAGES:
            candidate.skip = "säljaren arbetar redan med affären"
        elif email in enrolled:
            candidate.skip = "redan med i en kampanj"
        elif email in seen:
            candidate.skip = "samma adress som ett annat bolag"
        elif segments and segment.split(":")[1] not in segments:
            candidate.skip = "annat segment"
        elif check_dns and not receives(email):
            candidate.skip = "domänen tar inte emot mejl"
        else:
            seen.add(email)
        out.append(candidate)
    return out


def enroll(
    campaign: CrmCampaign, *, segments: set[str] | None = None,
    limit: int = 0, dry_run: bool = False, check_dns: bool = False,
) -> dict:
    """Lägger urvalet i kampanjens kö. Ingenting skickas förrän kampanjen är aktiv."""
    candidates = audience(campaign, segments=segments, check_dns=check_dns)
    chosen = sorted((c for c in candidates if not c.skip), key=lambda c: c.priority)
    if limit:
        chosen = chosen[:limit]
    report = {
        "enrolled": len(chosen),
        "skipped": dict(Counter(c.skip for c in candidates if c.skip)),
        "dry_run": dry_run,
    }
    if dry_run:
        report["sample"] = [
            f"{c.account.name} ({c.account.city or c.account.county or '-'})" for c in chosen[:10]
        ]
        return report
    CrmCampaignRecipient.objects.bulk_create(
        [
            CrmCampaignRecipient(
                campaign=campaign, account=c.account, person_id=c.person_id,
                deal_id=c.deal_id, email=c.email, priority=c.priority,
            )
            for c in chosen
        ],
        ignore_conflicts=True,
    )
    return report


# --- Personalisering ---------------------------------------------------------

_NOT_A_PERSON = re.compile(r"\b(ab|hb|kb|aktiebolag|taxi|buss|trafik)\b", re.I)


def first_name(person: CrmPerson | None, account: CrmAccount | None) -> str:
    """
    Förnamnet, bara när vi är säkra på det. "Hej," är bättre än "Hej Karl" till
    någon som heter Karl Erik och kallas Erik, eller till en revisor.
    """
    if person is None:
        return ""
    name = (person.name or "").strip()
    if not name or (account and name.lower() == (account.name or "").strip().lower()):
        return ""
    parts = name.split()
    if len(parts) != 2 or _NOT_A_PERSON.search(name) or any(ch.isdigit() for ch in name):
        return ""
    title = (person.title or "").lower()
    if "revisor" in title or "suppleant" in title:
        return ""
    first = parts[0]
    return first.capitalize() if first.isupper() or first.islower() else first


def company_display(name: str) -> str:
    text = re.sub(r"\s+", " ", name or "").strip()
    if text.isupper():
        text = re.sub(r"\b(Ab|Hb|Kb)\b", lambda m: m.group(0).upper(), text.title())
    return re.sub(r"\bAktiebolag(et)?\b", "AB", text).rstrip(" ,;.-")


# Ord i ett bolagsnamn som också är ortnamn någonstans, men som i namnet
# betyder något annat.
_NOT_A_PLACE = frozenset({
    "taxi", "buss", "trafik", "transport", "service", "city", "berg", "strand",
    "dal", "sund", "lund", "holm", "vik", "sjö", "norr", "söder", "öster", "väster",
})
_PLACES_KEY = "fleet:outreach:places"


def known_places() -> frozenset[str]:
    """Orterna som förekommer i CRM, för att känna igen en ort i ett bolagsnamn."""
    places = cache.get(_PLACES_KEY)
    if places is None:
        places = frozenset(
            city.strip().lower()
            for city in CrmAccount.objects.exclude(city="").values_list("city", flat=True).distinct()
            if len(city.strip()) >= 4
        )
        cache.set(_PLACES_KEY, places, 3600)
    return places


def place_in_name(name: str) -> str:
    """
    Orten bolaget självt har i namnet: "Taxi i Borås AB", "Vellinge Taxi AB",
    "Limhamns Taxi AB". Den säger var bolaget kör; postadressen säger bara var
    brevlådan står.
    """
    places = known_places()
    for token in re.findall(r"[A-ZÅÄÖ][a-zåäöé]+(?:-[A-ZÅÄÖ]?[a-zåäöé]+)?", name or ""):
        word = token.lower()
        if word in _NOT_A_PLACE:
            continue
        if word in places:
            return token
        if word.endswith("s") and word[:-1] in places and word[:-1] not in _NOT_A_PLACE:
            return token[:-1]
    return ""


def place_display(account: CrmAccount | None) -> str:
    if account is None:
        return ""
    from_name = place_in_name(account.name)
    if from_name:
        return from_name
    city = (account.city or "").strip()
    if city:
        return city.title() if city.isupper() or city.islower() else city
    return (account.county or "").strip()


def size_for(recipient: CrmCampaignRecipient) -> str:
    """
    Bolagets storlek ur CRM-segmentet, som mottagarens prioritet bär med sig
    (A = 0, B = 100, C = 200, D = 300; se `audience`). Okänd storlek får
    mellanformen: "ni" passar både den som kör själv och den som har förare.
    """
    segment = recipient.priority // 100
    if segment == 0:
        return outreach_templates.LARGE
    if segment == 2:
        return outreach_templates.SOLO
    return outreach_templates.FLEET


# --- Något som hände nyss i bolagets län ------------------------------------

EVENT_MAX_AGE = timedelta(days=4)
EVENT_STATION_MAX = 28
_WEEKDAY_WORDS = (
    "i måndags", "i tisdags", "i onsdags", "i torsdags", "i fredags", "i lördags", "i söndags",
)


def day_word(day: date, today: date) -> str:
    if day == today:
        return "i dag"
    if day == today - timedelta(days=1):
        return "i går"
    return _WEEKDAY_WORDS[day.weekday()]


def local_event(county: str, now: datetime) -> outreach_templates.LocalEvent | None:
    """
    Det senaste inställda tåget i länet som appen skickade ett tips om, de
    senaste dagarna. Bara rader som faktiskt pushades (notified_at) och som
    personalen inte har tagit bort -- mejlet säger att appen tipsade om det.
    """
    from core.areas import COUNTIES
    from core.models import Opportunity

    code = {name: code for code, name in COUNTIES}.get((county or "").strip())
    if not code:
        return None
    key = f"fleet:outreach:event:{code}:{_local(now):%Y%m%d%H}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    rows = (
        Opportunity.objects.filter(
            county_code=code, kind="transit", notified_at__isnull=False,
            suppressed_at__isnull=True, title__icontains="är inställt från",
            departure_at__gte=now - EVENT_MAX_AGE, departure_at__lte=now,
        )
        .exclude(station="")
        .order_by("-departure_at")
        .values("title", "station", "departure_at")[:10]
    )
    event = None
    for row in rows:
        station = (row["station"] or "").strip()
        if len(station) > EVENT_STATION_MAX:
            continue
        local = timezone.localtime(row["departure_at"])
        event = outreach_templates.LocalEvent(
            when=day_word(local.date(), _local(now).date()),
            clock=f"{local:%H:%M}",
            station=station,
            title=" ".join((row["title"] or "").split()),
            county=county.strip(),
        )
        break
    cache.set(key, event or "", 60 * 60)
    return event


def context_for(recipient: CrmCampaignRecipient, now: datetime | None = None) -> outreach_templates.Context:
    account = recipient.account
    page_url, _ = unsubscribe_urls(recipient)
    return outreach_templates.Context(
        company=company_display(account.name if account else "") or "ert bolag",
        place=place_display(account),
        first_name=first_name(recipient.person, account),
        unsubscribe_url=page_url,
        campaign=recipient.campaign.slug,
        variant=recipient.id.int % 3,
        size=size_for(recipient),
        event=local_event(account.county if account else "", now or timezone.now()),
    )


def thread_subject(recipient: CrmCampaignRecipient) -> str:
    """Ämnet som första mejlet fick, så att "Re: " stämmer även om mallen har ändrats."""
    row = (
        OutboxMessage.objects.filter(
            category=f"{CATEGORY_PREFIX}1", payload__recipient_id=str(recipient.id),
        ).order_by("created_at").values_list("subject", flat=True).first()
    )
    return row or ""


# --- Takt --------------------------------------------------------------------


def _local(now: datetime) -> datetime:
    return timezone.localtime(now)


def is_send_day(day: date) -> bool:
    return day.weekday() < 5 and (day.month, day.day) not in _HOLIDAYS


def in_window(now: datetime) -> bool:
    local = _local(now)
    return is_send_day(local.date()) and WINDOW_START <= local.time() < WINDOW_END


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = _local(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _outreach_rows():
    return OutboxMessage.objects.filter(category__startswith=CATEGORY_PREFIX)


def sending_days_before(now: datetime) -> int:
    """Antal tidigare dagar då brevlådan har skickat säljmejl."""
    start, _ = _day_bounds(now)
    stamps = _outreach_rows().filter(
        status=OutboxMessage.Status.SENT, sent_at__lt=start,
    ).values_list("sent_at", flat=True)
    return len({_local(stamp).date() for stamp in stamps})


def daily_cap(campaign_cap: int, now: datetime) -> int:
    warm = WARMUP_START + WARMUP_STEP * (sending_days_before(now) // WARMUP_EVERY_DAYS)
    return max(0, min(int(campaign_cap), warm))


def used_today(now: datetime) -> int:
    start, end = _day_bounds(now)
    return _outreach_rows().filter(created_at__gte=start, created_at__lt=end).exclude(
        status=OutboxMessage.Status.SUPPRESSED,
    ).count()


def tick_budget(campaign_cap: int, now: datetime) -> int:
    """
    Hur många mejl som får gå i den här körningen: det som är kvar av dagen,
    jämnt fördelat över de körningar som är kvar i fönstret.
    """
    remaining = daily_cap(campaign_cap, now) - used_today(now)
    if remaining <= 0:
        return 0
    local = _local(now)
    minutes_left = (
        datetime.combine(local.date(), WINDOW_END) - datetime.combine(local.date(), local.time())
    ).total_seconds() / 60
    ticks_left = max(1, math.ceil(minutes_left / TICK_MINUTES))
    return min(MAX_PER_TICK, remaining, math.ceil(remaining / ticks_left))


def _add_workdays(start: datetime, days: int) -> datetime:
    current = start
    while days > 0:
        current += timedelta(days=1)
        if is_send_day(_local(current).date()):
            days -= 1
    return current


def next_send_after(step: int, now: datetime) -> datetime | None:
    """När mejlet efter `step` går. None = serien är slut."""
    if step == 1:
        return _add_workdays(now, STEP2_WORKDAYS)
    if step == 2:
        return now + timedelta(days=STEP3_DAYS)
    return None


# --- Stopp --------------------------------------------------------------------


def stop(recipient: CrmCampaignRecipient, state: str) -> None:
    recipient.state = state
    recipient.next_send_at = None
    recipient.stopped_at = timezone.now()
    recipient.save(update_fields=["state", "next_send_at", "stopped_at", "updated_at"])


def _stop_reason(recipient: CrmCampaignRecipient, customers: set[str]) -> str:
    """Varför nästa mejl inte ska gå, eller tomt."""
    if is_suppressed(recipient.email):
        return State.UNSUBSCRIBED
    account = recipient.account
    if account is None:
        return State.STOPPED
    if (account.legal_form or "").strip().lower() not in JURIDICAL_FORMS:
        return State.STOPPED
    if _digits(account.org_number) in customers:
        return State.CONVERTED if recipient.step else State.STOPPED
    deal = CrmDeal.objects.filter(id=recipient.deal_id).first() if recipient.deal_id else None
    if deal is not None:
        if deal.company_id:
            return State.CONVERTED if recipient.step else State.STOPPED
        if deal.stage not in UNTOUCHED_STAGES:
            return State.STOPPED
    return ""


def mark_conversions() -> int:
    """Bolag som har startat ett prov efter att de fick mejl räknas som resultat."""
    customers = customer_orgs()
    if not customers:
        return 0
    changed = 0
    open_states = [State.QUEUED, State.ACTIVE, State.FINISHED, State.REPLIED]
    for recipient in CrmCampaignRecipient.objects.filter(
        state__in=open_states,
    ).exclude(account=None).select_related("account"):
        if _digits(recipient.account.org_number) in customers:
            stop(recipient, State.CONVERTED if recipient.step else State.STOPPED)
            changed += 1
    return changed


# --- Automatisk broms ---------------------------------------------------------


def guard(campaign: CrmCampaign, now: datetime) -> str:
    """Skälet att pausa kampanjen, eller tomt."""
    since = now - timedelta(days=7)
    sent = OutboxMessage.objects.filter(
        category__startswith=CATEGORY_PREFIX, status=OutboxMessage.Status.SENT,
        sent_at__gte=since, payload__campaign_id=str(campaign.id),
    ).count()
    if sent < GUARD_MIN_SENT:
        return ""
    stopped = CrmCampaignRecipient.objects.filter(campaign=campaign, stopped_at__gte=since)
    bounced = stopped.filter(state=State.BOUNCED).count()
    unsubscribed = stopped.filter(state=State.UNSUBSCRIBED).count()
    if bounced >= GUARD_MIN_BOUNCES and bounced / sent > GUARD_BOUNCE_RATE:
        return f"{bounced} studsar på {sent} mejl de senaste sju dagarna"
    if unsubscribed / sent > GUARD_UNSUBSCRIBE_RATE:
        return f"{unsubscribed} avregistreringar på {sent} mejl de senaste sju dagarna"
    return ""


def pause(campaign: CrmCampaign, reason: str, *, alert: bool = True) -> None:
    campaign.status = CrmCampaign.Status.PAUSED
    campaign.paused_reason = reason[:1000]
    campaign.save(update_fields=["status", "paused_reason", "updated_at"])
    log.warning("fleet.outreach: kampanjen %s pausad: %s", campaign.slug, reason)
    if alert:
        _alert(
            f"Säljutskicket \"{campaign.name}\" är pausat",
            f"Kampanjen pausades automatiskt: {reason}.\n\n"
            "Inga fler säljmejl går förrän någon trycker Fortsätt i adminwebben "
            "(CRM -> Utskick). Titta på listan och texten först.",
        )


def resume(campaign: CrmCampaign) -> None:
    campaign.status = CrmCampaign.Status.ACTIVE
    campaign.paused_reason = ""
    campaign.save(update_fields=["status", "paused_reason", "updated_at"])


def _alert(subject: str, body: str) -> None:
    try:
        from core import ops_alerts

        to = ops_alerts.recipient()
        if to:
            ops_alerts._send(subject, body, to)
    except Exception:  # pragma: no cover - larmet får inte fälla utskicket
        log.exception("fleet.outreach: kunde inte skicka larm")


# --- Utfallet av ett utskick (anropas från notifications.deliver) -------------


def _recipient_for(row) -> CrmCampaignRecipient | None:
    recipient_id = (row.payload or {}).get("recipient_id")
    if not recipient_id:
        return None
    return CrmCampaignRecipient.objects.filter(id=recipient_id).first()


def on_sent(row) -> None:
    recipient = _recipient_for(row)
    if recipient is None:
        return
    message_id = (row.payload or {}).get("message_id") or ""
    if message_id and not recipient.thread_message_id:
        recipient.thread_message_id = message_id[:255]
        recipient.save(update_fields=["thread_message_id", "updated_at"])


def on_failed(row, exc) -> None:
    """
    Servern tog inte emot mejlet. Är det mottagaren det är fel på spärras
    adressen. Allt annat (avvisat innehåll, sändgräns) är vårt problem, och då
    ska inte nästa mottagare få samma fel: kampanjen pausas.
    """
    from fleet.mailer import RecipientRefused

    recipient = _recipient_for(row)
    if isinstance(exc, RecipientRefused):
        suppress(row.to_address, Reason.BOUNCED, str(exc))
        return
    if recipient is None:
        return
    stop(recipient, State.STOPPED)
    campaign = recipient.campaign
    if campaign.status == CrmCampaign.Status.ACTIVE:
        pause(campaign, f"servern avvisade ett mejl ({str(exc)[:200]})")


# --- Körningen ----------------------------------------------------------------


def enabled() -> bool:
    """
    Påslaget, brevlådan inlagd och en namngiven avsändare. Utan namnet hade
    mejlen börjat "Jag heter Taxi Tips" -- hellre inget utskick än det.
    """
    from fleet import mailer

    return (
        bool(getattr(settings, "OUTREACH_ENABLED", False))
        and mailer.outreach_configured()
        and bool((getattr(settings, "OUTREACH_SENDER_NAME", "") or "").strip())
    )


def due(now: datetime, limit: int) -> list[CrmCampaignRecipient]:
    """Uppföljningar först (de har en tråd att avsluta), sedan nya bolag i prioritetsordning."""
    if limit <= 0:
        return []
    base = CrmCampaignRecipient.objects.filter(
        campaign__status=CrmCampaign.Status.ACTIVE,
    ).select_related("campaign", "account", "person")
    follow_ups = list(
        base.filter(state=State.ACTIVE, next_send_at__lte=now).order_by("next_send_at")[:limit]
    )
    rest = limit - len(follow_ups)
    fresh = list(
        base.filter(state=State.QUEUED).order_by("priority", "created_at")[:rest]
    ) if rest > 0 else []
    return follow_ups + fresh


def send_step(recipient: CrmCampaignRecipient, now: datetime, *, sender=None) -> str:
    """Köar och skickar nästa mejl i serien. Returnerar utfallet från utkorgen."""
    step = recipient.step + 1
    if step > STEP_COUNT:
        stop(recipient, State.FINISHED)
        return "finished"
    subject, body = outreach_templates.render(
        step, context_for(recipient, now),
        thread_subject=thread_subject(recipient) if step > 1 else "",
    )
    _, one_click = unsubscribe_urls(recipient)
    account = recipient.account
    # Raden och mottagarens steg skrivs i samma transaktion som utskicket.
    # Utkorgens vanliga körning ser då aldrig en väntande rad som den här
    # körningen redan håller på att skicka -- annars hade bolaget fått två mejl.
    with transaction.atomic():
        row = notifications.queue(
            category=f"{CATEGORY_PREFIX}{step}",
            to_address=recipient.email,
            subject=subject,
            body=body,
            payload={
                "campaign": recipient.campaign.slug,
                "campaign_id": str(recipient.campaign_id),
                "recipient_id": str(recipient.id),
                "deal_id": str(recipient.deal_id) if recipient.deal_id else "",
                "account_id": str(account.id) if account else "",
                "account_name": account.name if account else "",
                "step": step,
                "one_click_url": one_click,
                "thread": recipient.thread_message_id,
            },
            key_parts=(recipient.id, step),
        )
        recipient.step = step
        recipient.last_sent_at = now
        recipient.next_send_at = next_send_after(step, now)
        recipient.state = State.ACTIVE if recipient.next_send_at else State.FINISHED
        recipient.save(update_fields=[
            "step", "last_sent_at", "next_send_at", "state", "updated_at",
        ])
        if row.status != OutboxMessage.Status.PENDING:
            return "duplicate"
        return notifications.deliver(row, sender=sender, now=now)


def _pause_between() -> None:
    time_module.sleep(random.uniform(15, 45))


def tick(now: datetime | None = None, *, sender=None, wait=_pause_between) -> dict:
    """
    En körning: bokför startade prov, kontrollera bromsen och skicka några mejl
    om det är kontorstid och dagens tak inte är nått.
    """
    now = now or timezone.now()
    if sender is None:
        if not enabled():
            return {"skipped": "disabled"}
        from fleet import mailer

        sender = mailer.send
    if not cache.add(_TICK_LOCK, "1", timeout=TICK_MINUTES * 60 - 60):
        return {"skipped": "locked"}
    try:
        return _tick(now, sender, wait)
    finally:
        cache.delete(_TICK_LOCK)


def _tick(now: datetime, sender, wait) -> dict:
    report: dict = {"converted": mark_conversions(), "sent": 0, "stopped": 0, "failed": 0}
    active = list(CrmCampaign.objects.filter(status=CrmCampaign.Status.ACTIVE))
    for campaign in active:
        reason = guard(campaign, now)
        if reason:
            pause(campaign, reason)
    active = [c for c in active if c.status == CrmCampaign.Status.ACTIVE]
    if not active:
        report["skipped"] = "no_active_campaign"
        return report
    if not in_window(now):
        report["skipped"] = "outside_window"
        return report

    budget = tick_budget(min(c.daily_cap for c in active), now)
    report["budget"] = budget
    customers = customer_orgs()
    # Hämta några extra: en del faller bort på stoppreglerna.
    queue = due(now, budget * 3)
    for recipient in queue:
        if report["sent"] >= budget:
            break
        reason = _stop_reason(recipient, customers)
        if reason:
            stop(recipient, reason)
            report["stopped"] += 1
            continue
        if report["sent"]:
            wait()
        recipient.campaign.refresh_from_db(fields=["status"])
        if recipient.campaign.status != CrmCampaign.Status.ACTIVE:
            break
        outcome = send_step(recipient, now, sender=sender)
        if outcome == "sent":
            report["sent"] += 1
        elif outcome in ("failed", "suppressed"):
            report["failed"] += 1

    for campaign in active:
        open_left = campaign.recipients.filter(state__in=[State.QUEUED, State.ACTIVE]).exists()
        if not open_left and campaign.recipients.exists():
            CrmCampaign.objects.filter(
                id=campaign.id, status=CrmCampaign.Status.ACTIVE,
            ).update(status=CrmCampaign.Status.DONE)
    return report


# --- Siffror till adminwebben -------------------------------------------------


def stats(campaign: CrmCampaign, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    states = Counter(campaign.recipients.values_list("state", flat=True))
    rows = OutboxMessage.objects.filter(
        category__startswith=CATEGORY_PREFIX, payload__campaign_id=str(campaign.id),
    )
    sent = rows.filter(status=OutboxMessage.Status.SENT)
    per_step = Counter(sent.values_list("category", flat=True))
    return {
        "id": str(campaign.id),
        "slug": campaign.slug,
        "name": campaign.name,
        "status": campaign.status,
        "pausedReason": campaign.paused_reason,
        "dailyCap": campaign.daily_cap,
        "capToday": daily_cap(campaign.daily_cap, now),
        "usedToday": used_today(now),
        "recipients": sum(states.values()),
        "waiting": states.get(State.QUEUED, 0),
        "inSequence": states.get(State.ACTIVE, 0),
        "finished": states.get(State.FINISHED, 0),
        "replied": states.get(State.REPLIED, 0),
        "unsubscribed": states.get(State.UNSUBSCRIBED, 0),
        "bounced": states.get(State.BOUNCED, 0),
        "converted": states.get(State.CONVERTED, 0),
        "stopped": states.get(State.STOPPED, 0),
        "sent": sent.count(),
        "sentPerStep": {
            str(step): per_step.get(f"{CATEGORY_PREFIX}{step}", 0)
            for step in range(1, STEP_COUNT + 1)
        },
        "failed": rows.filter(status=OutboxMessage.Status.FAILED).count(),
    }


def message_row(row: OutboxMessage, *, with_body: bool = False) -> dict:
    payload = row.payload or {}
    out = {
        "id": str(row.id),
        "to": row.to_address,
        "subject": row.subject,
        "step": payload.get("step"),
        "status": row.status,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "sentAt": row.sent_at.isoformat() if row.sent_at else None,
        "error": row.error,
        "accountName": payload.get("account_name") or "",
        "dealId": payload.get("deal_id") or None,
        "campaign": payload.get("campaign") or "",
    }
    if with_body:
        out["body"] = row.body
    return out


def messages(*, campaign_id=None, deal_id=None, limit: int = 50, offset: int = 0) -> dict:
    rows = _outreach_rows().order_by("-created_at")
    if campaign_id:
        rows = rows.filter(payload__campaign_id=str(campaign_id))
    if deal_id:
        rows = rows.filter(payload__deal_id=str(deal_id))
    total = rows.count()
    return {
        "total": total,
        "rows": [message_row(row) for row in rows[offset:offset + limit]],
    }
