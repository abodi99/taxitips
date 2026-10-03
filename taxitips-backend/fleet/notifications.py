"""
Bekräftelser och påminnelser: aktivering, provslut, prissteg, betalningsfel,
uppsägning.

**Utkorg, inte direktsändning.** Meddelandet skrivs som en rad och skickas av
ett separat steg. Två skäl: en webhook som kommer två gånger får inte skicka
två mejl (`dedupe_key` är unik), och ett utskick som misslyckas ska kunna tas
om utan att flödet som skapade det körs igen.

**Tjänstemeddelanden är inte marknadsföring.** `category` skiljer dem åt, och
avregistrering från marknadsföring tystar aldrig en faktura som misslyckats
(§10). Det är inte en artighet -- ett företag som inte får veta att betalningen
föll förlorar åtkomsten utan förvarning.

**Testutskick går till sandbox.** Utan avsändare -- varken
`FLEET_OUTBOX_SENDER` eller SMTP-uppgifter (fleet/mailer.py) -- skrivs raden
men skickas inte, och statusen blir `pending`. Ingen riktig mottagare kan nås
av misstag från en utvecklingsmiljö.

**Ett misslyckat utskick tas om.** Ett tillfälligt fel (anslutning, 4xx,
inloggning) lämnar raden `pending` med felet, och nästa körning försöker igen i
upp till två dygn. Bara ett permanent fel -- fel adress, avvisat innehåll --
blir `failed` direkt. Förut blev varje fel slutgiltigt, och en kort
SMTP-störning hade kostat kunden påminnelsen om att provet slutar.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from fleet.models import OutboxMessage

log = logging.getLogger(__name__)

# Tjänstemeddelanden. Ingen av dem får kunna tystas av ett marknadsföringsval.
SERVICE_CATEGORIES = frozenset({
    "activation", "trial_started", "trial_ending", "trial_ended",
    "order_confirmed", "payment_failed", "grace_started", "renewal_reminder",
    "price_step", "cancellation_confirmed", "cancellation_applied",
    "device_blocked", "review_opened", "driver_invite", "member_invite",
})


def dedupe_key(category: str, *parts) -> str:
    raw = ":".join([category, *[str(p) for p in parts]])
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def queue(
    *,
    category: str,
    company_id=None,
    to_address: str = "",
    subject: str = "",
    body: str = "",
    payload: dict | None = None,
    key_parts: tuple = (),
) -> OutboxMessage | None:
    """
    Lägger ett meddelande i utkorgen. Dubbletter tas tyst: samma `dedupe_key`
    betyder att meddelandet redan finns, och det är rätt svar, inte ett fel.
    """
    key = dedupe_key(category, *key_parts)
    existing = OutboxMessage.objects.filter(dedupe_key=key).first()
    if existing is not None:
        return existing
    return OutboxMessage.objects.create(
        company_id=company_id, category=category, to_address=to_address,
        subject=subject, body=body, payload=payload or {}, dedupe_key=key,
    )


def send_pending(limit: int = 50, sender=None) -> dict:
    """
    Skickar det som ligger i utkorgen.

    Utan konfigurerad sändare skickas ingenting och raderna ligger kvar som
    `pending`. Det är avsiktligt: en utvecklingsmiljö ska inte kunna nå en
    riktig kund.
    """
    sender = sender or _configured_sender()
    if sender is None:
        return {"sent": 0, "skipped": "no_sender"}

    from fleet.mailer import PermanentMailError

    sent = failed = retry = 0
    now = timezone.now()
    # Gamla rader skickas aldrig. Utkorgen fylldes i månader utan avsändare,
    # och när SMTP slogs på hade den första körningen annars mejlat "provet
    # har startat" till bolag vars prov tog slut för länge sedan.
    stale = OutboxMessage.objects.filter(
        status=OutboxMessage.Status.PENDING, created_at__lt=now - STALE_AFTER
    ).update(status=OutboxMessage.Status.FAILED, error="stale: för gammalt för att skicka")
    rows = OutboxMessage.objects.filter(status=OutboxMessage.Status.PENDING).order_by(
        "created_at"
    )[:limit]
    for row in rows:
        try:
            sender(row)
        except Exception as exc:
            permanent = isinstance(exc, PermanentMailError) or (
                row.created_at and now - row.created_at > RETRY_WINDOW
            )
            if permanent:
                failed += 1
                OutboxMessage.objects.filter(id=row.id).update(
                    status=OutboxMessage.Status.FAILED, error=str(exc)[:500]
                )
            else:
                retry += 1
                OutboxMessage.objects.filter(id=row.id).update(error=str(exc)[:500])
            continue
        sent += 1
        OutboxMessage.objects.filter(id=row.id).update(
            status=OutboxMessage.Status.SENT, sent_at=timezone.now(), error=""
        )
    return {"sent": sent, "failed": failed, "retry": retry, "stale": stale}


RETRY_WINDOW = timedelta(days=2)
STALE_AFTER = timedelta(days=3)


def _configured_sender():
    path = getattr(settings, "FLEET_OUTBOX_SENDER", "") or ""
    if not path:
        from fleet import mailer

        return mailer.send if mailer.configured() else None
    module_name, _, attr = path.rpartition(".")
    try:
        module = __import__(module_name, fromlist=[attr])
        return getattr(module, attr)
    except Exception as exc:  # pragma: no cover - konfigurationsfel
        log.warning("fleet.notifications: kan inte ladda sändaren %s: %s", path, exc)
        return None


# --- Färdiga meddelanden --------------------------------------------------


def _money(ore: int) -> str:
    return f"{ore // 100:,}".replace(",", " ") + f",{ore % 100:02d} kr"


def portal_url(anchor: str = "") -> str:
    base = (getattr(settings, "FLEET_PORTAL_URL", "") or "https://taxitips.se/portal").rstrip("/")
    return f"{base}#{anchor}" if anchor else base


def trial_offer(company_id, trial) -> dict | None:
    """
    Vad det kostar att fortsätta med provbilarna -- räknat med samma motor och
    samma anrop som offerten i portalen (orders.plan_change), så att mejlet och
    betalsidan aldrig visar olika belopp. None om det inte går att räkna (inga
    provbilar, eller ett fel): då skickas mejlet utan pris hellre än med fel pris.
    """
    from fleet import orders, sessions
    from fleet.models import License

    specs, plates = [], []
    for license in License.objects.filter(trial=trial, status=License.Status.TRIAL):
        vehicle = sessions.current_vehicle(license)
        if vehicle is None:
            continue
        specs.append(orders.VehicleSpec(plate=vehicle.plate, base_county=license.base_county))
        plates.append(vehicle.plate)
    if not specs:
        return None
    try:
        plan = orders.plan_change(company_id, add_vehicles=specs)
    except Exception as exc:  # en påminnelse får aldrig fällas av prisuträkningen
        log.warning("fleet.notifications: kunde inte räkna provets pris: %s", exc)
        return None
    return {
        "count": len(specs), "plates": sorted(plates),
        "monthly_ore": plan.quote.next_period.amount_ore,
        "monthly_total_ore": plan.quote.next_period.total_ore,
    }


def _offer_lines(offer: dict | None) -> str:
    if not offer:
        return (
            "Vill ni fortsätta bekräftar ni bilarna och sparar kort i kundportalen. "
            "Första månadsbeloppet dras när provet tar slut:\n"
        )
    cars = f"{offer['count']} {'bil' if offer['count'] == 1 else 'bilar'}"
    return (
        f"Vill ni fortsätta med era {cars} ({', '.join(offer['plates'])})? Det kostar "
        f"{_money(offer['monthly_ore'])} i månaden exkl. moms "
        f"({_money(offer['monthly_total_ore'])} inkl. moms). Ni sparar kort i "
        "kundportalen; första dragningen sker när provet tar slut, sedan automatiskt "
        "varje månad tills ni säger upp.\n"
    )


# Vad provet visar och vad abonnemanget lägger till (fleet/features.py). Står i
# mejlen och aldrig som köpknapp i appen (docs/fleet-abonnemang.md §9c).
_TRIAL_SCOPE = (
    "Under provet visar appen tåg och buss: inställda tåg, sista avgången och "
    "ersättningstrafik. Med abonnemang får förarna också flyg (ankomster), färjor, "
    "evenemang (när publiken går hem) och trafikolyckor.\n"
)


def _cars(n: int) -> str:
    return "en bil" if n == 1 else f"upp till {n} bilar"


_SIGNATURE = (
    "\nFrågor? Svara på det här mejlet eller chatta med oss i appen "
    "(Inställningar -> Chatta med support).\n\nHälsningar\nTaxiTips"
)


def trial_started(company_id, to_address: str, trial) -> OutboxMessage | None:
    return queue(
        category="trial_started", company_id=company_id, to_address=to_address,
        subject="Välkommen – provperioden har startat",
        body=(
            "Hej!\n\n"
            f"Provperioden har startat och gäller till {trial.ends_at:%Y-%m-%d}. "
            f"Den omfattar {_cars(trial.vehicle_limit)} och kostar ingenting.\n\n"
            + _TRIAL_SCOPE
            + "\nSå kommer ni igång:\n"
            "1. Tryck på bilen i appen (Inställningar) och välj \"Bjud in förare med "
            "e-post\" -- föraren får ett mejl och loggar in i appen. Har föraren "
            "ingen e-post: välj \"Visa kod i stället\".\n"
            "2. Kör ni själva: \"Kör bilen själv med den här telefonen\".\n\n"
            "För att fortsätta efter provet: bekräfta bilarna och spara kort i kundportalen. "
            "Då dras första betalningen automatiskt när provet tar slut. Utan sparat kort "
            "stängs åtkomsten utan debitering.\n\n"
            f"Spara kort här: {portal_url('fortsatt')}\n"
            + _SIGNATURE
        ),
        key_parts=(company_id, trial.id),
    )


def trial_ending(company_id, to_address: str, trial, *, stage: str = "3d") -> OutboxMessage | None:
    """
    Påminnelse före provslut: `3d` / `1d`, samt `card_missing*` när kort saknas.
    """
    offer = trial_offer(company_id, trial)
    when = "i morgon" if stage.endswith("1d") or stage == "1d" else f"{trial.ends_at:%Y-%m-%d}"
    if stage.startswith("card_missing"):
        subject = "Spara kort så ni behåller tipsen efter provet"
        body = (
            "Hej!\n\n"
            f"Provperioden gäller till {trial.ends_at:%Y-%m-%d}. "
            "Ni har ännu inte sparat kort för auto-förnyelse.\n\n"
            + _TRIAL_SCOPE + "\n"
            + _offer_lines(offer)
            + f"\nBekräfta bilarna och spara kort här: {portal_url('fortsatt')}\n\n"
            "Utan sparat kort stängs åtkomsten när provet tar slut -- utan debitering. "
            "Med kort dras första månadsbeloppet automatiskt den dagen.\n"
            + _SIGNATURE
        )
    elif stage == "1d" or stage.endswith("1d"):
        subject = "Sista dagen med provet – spara kort för att fortsätta"
        body = (
            "Hej!\n\n"
            f"Provperioden slutar {when}.\n\n"
            + _offer_lines(offer)
            + f"\nBekräfta bilarna och spara kort: {portal_url('fortsatt')}\n\n"
            "Har ni redan sparat kort dras första betalningen automatiskt i morgon. "
            "Utan kort stängs åtkomsten utan debitering.\n"
            + _SIGNATURE
        )
    else:
        subject = "Provperioden slutar snart"
        body = (
            "Hej!\n\n"
            f"Provperioden slutar {when}.\n\n"
            + _TRIAL_SCOPE + "\n"
            + _offer_lines(offer)
            + f"\nBekräfta bilarna och spara kort: {portal_url('fortsatt')}\n\n"
            "Med sparat kort fortsätter abonnemanget automatiskt. "
            "Utan kort stängs åtkomsten utan debitering.\n"
            + _SIGNATURE
        )
    return queue(
        category="trial_ending", company_id=company_id, to_address=to_address,
        subject=subject,
        body=body,
        payload={"stage": stage, "offer": offer or {}},
        key_parts=(company_id, trial.id, stage),
    )


def trial_ended(company_id, to_address: str, trial) -> OutboxMessage | None:
    """Provet löpte ut utan kort/commit. Dörren står öppen: samma länk."""
    return queue(
        category="trial_ended", company_id=company_id, to_address=to_address,
        subject="Provperioden är slut",
        body=(
            "Hej!\n\n"
            "Provperioden är slut och ingenting har debiterats. Förarna får inga fler "
            "tips förrän ni har valt vilka bilar som ska fortsätta och betalat i "
            "kundportalen. Med abonnemang får förarna också flyg, färjor, evenemang "
            "och trafikolyckor -- inte bara tåg och buss.\n\n"
            f"Fortsätt när ni vill: {portal_url('fortsatt')}\n"
            + _SIGNATURE
        ),
        key_parts=(company_id, trial.id),
    )


def order_confirmed(order) -> OutboxMessage | None:
    return queue(
        category="order_confirmed", company_id=order.company_id,
        subject="Beställningen är bekräftad",
        body=(
            f"Att betala nu: {_money(order.total_now_ore)} inkl. moms. "
            f"Nästa period: {_money(order.next_period_total_ore)} inkl. moms."
        ),
        payload={"orderId": str(order.id), "kind": order.kind},
        key_parts=(order.id,),
    )


def payment_failed(subscription, *, grace_until=None) -> OutboxMessage | None:
    body = "Betalningen gick inte igenom. Uppdatera betalmetoden."
    if grace_until:
        body += f" Åtkomsten gäller till {grace_until:%Y-%m-%d %H:%M}."
    else:
        body += " Ingen betalningsfrist gäller för den här betalningen."
    return queue(
        category="payment_failed", company_id=subscription.company_id,
        subject="Betalningen misslyckades", body=body,
        key_parts=(subscription.company_id, subscription.current_period_end),
    )


def cancellation_confirmed(company_id, effective_at) -> OutboxMessage | None:
    return queue(
        category="cancellation_confirmed", company_id=company_id,
        subject="Uppsägningen är registrerad",
        body=(
            f"Abonnemanget avslutas {effective_at:%Y-%m-%d}. Fram till dess "
            "fungerar allt som vanligt. Du kan ångra uppsägningen fram till det "
            "datumet."
        ),
        key_parts=(company_id, effective_at),
    )


def device_blocked(company_id, approval) -> OutboxMessage | None:
    return queue(
        category="device_blocked", company_id=company_id,
        subject="En telefon har spärrats",
        body="Telefonen kan inte längre se tips eller ta bilen i anspråk.",
        payload={"approvalId": str(approval.id)},
        key_parts=(approval.id,),
    )


def driver_invite(invite, *, link: str, company_name: str, plate: str) -> OutboxMessage | None:
    """
    Förarens inbjudan (fleet/driver_invites.py). Enkel svenska, tre steg:
    föraren kan vara ny i Sverige och har aldrig sett appen.

    Länken är en engångslänk från Supabase Auth. Varje utskick får en egen
    rad (`send_count` i nyckeln): "Skicka igen" ger en ny länk, inte samma rad.
    """
    who = company_name or "Ditt taxibolag"
    car = f" för bilen {plate}" if plate else ""
    return queue(
        category="driver_invite", company_id=invite.company_id, to_address=invite.email,
        subject=f"{who} bjuder in dig till Taxi Tips",
        body=(
            "Hej!\n\n"
            f"{who} har bjudit in dig till Taxi Tips{car}. "
            "Taxi Tips visar var det finns folk som behöver taxi just nu.\n\n"
            "Så kommer du igång:\n"
            f"1. Tryck på länken och välj ett lösenord:\n{link}\n\n"
            "2. Hämta appen Taxi Tips i App Store eller Google Play.\n\n"
            "3. Öppna appen. Tryck \"Jag är förare\". Logga in med "
            f"{invite.email} och ditt lösenord.\n\n"
            "Länken fungerar en gång. Fungerar den inte: tryck \"Glömt lösenord?\" "
            f"i appen och skriv {invite.email}. Eller be {who} skicka inbjudan igen.\n\n"
            "Inbjudan gäller i sju dagar. Väntade du dig inte det här mejlet kan du "
            "strunta i det.\n"
            + _SIGNATURE
        ),
        payload={
            "inviteId": str(invite.id), "kind": "driver_invite",
            "button": {"url": link, "label": "Välj lösenord"},
        },
        key_parts=(invite.id, invite.send_count),
    )


MEMBER_ROLE_TEXT = {
    "company_owner": "som ägare",
    "fleet_admin": "för att sköta bilar och förare",
    "finance": "för att sköta betalning och fakturor",
}


def member_invite(invite, *, link: str, company_name: str, inviter: str = "", send_no: int = 1) -> OutboxMessage | None:
    """
    Inbjudan till kundportalen (fleet/sales.py:invite_owner): ägaren eller
    Taxi Tips lägger till en inloggning i företaget.

    Länken loggar in direkt; portalen knyter kontot till företaget och ber om
    ett lösenord. `send_no` i nyckeln: en ny inbjudan är ett nytt mejl.
    """
    company = company_name or "ert taxibolag"
    who = inviter or "Taxi Tips"
    role = MEMBER_ROLE_TEXT.get(invite.role, "")
    return queue(
        category="member_invite", company_id=invite.company_id, to_address=invite.email,
        subject=f"Du är inbjuden till {company} i Taxi Tips",
        body=(
            "Hej!\n\n"
            f"{who} har bjudit in dig till {company} i Taxi Tips{(' ' + role) if role else ''}.\n\n"
            "Logga in här – du får välja ett lösenord direkt:\n"
            f"{link}\n\n"
            "Du kommer till kundportalen på taxitips.se, där du ser bilarna, förarna och "
            "abonnemanget. Samma inloggning fungerar i appen.\n\n"
            "Länken fungerar en gång och inbjudan gäller i 14 dagar. Har länken gått ut: gå till "
            f"{portal_url()} och tryck \"Glömt lösenord\" med {invite.email}.\n\n"
            "Väntade du dig inte det här mejlet kan du strunta i det.\n"
            + _SIGNATURE
        ),
        payload={
            "inviteId": str(invite.id), "kind": "member_invite",
            "button": {"url": link, "label": "Logga in och välj lösenord"},
        },
        key_parts=(invite.id, send_no),
    )
