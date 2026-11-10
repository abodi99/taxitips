"""
"Fortsätt här": betalning i två tryck efter att provet tagit slut.

Mejlet (och ett valfritt SMS) före och efter provslut bär en personlig länk
till EN webbsida (`/fortsatt`). Sidan visar vad som fortsätter och vad det
kostar, ber om organisationsnumret om det saknas och skickar kunden vidare till
Stripe Checkout. Ingen inloggning, inget portalbesök. Appen säljer inget och
länkar inte hit (App Store- och Play-reglerna); länken finns bara i mejlet.

**Länken är en signerad biljett, inte en inloggning.** Samma mönster som
BankID-biljetten (`fleet/bankid.py`): `django.core.signing` med ett eget salt
och Djangos SECRET_KEY. Den bär bolagets id och när den utfärdades -- inget
annat, och ingenting sparas i databasen (inga migrationer, ingen tabell att
städa). Giltig i 30 dagar.

Den som har länken FÅR:

* läsa fortsättningserbjudandet: bolagets namn, platserna och månadspriset,
* ange organisationsnumret EN gång, när bolaget saknar ett (en kund som
  registrerat sig med BankID; ett befintligt nummer byts aldrig härifrån),
* starta Stripe-betalningen för provets platser -- exakt de som servern själv
  räknar fram, aldrig en plan från klienten.

Den som har länken FÅR INTE: logga in, nå kundportalen, se förare, telefoner
eller e-postadresser, ändra antal platser, län eller något annat i kontot. Den
som får tag i en vidarebefordrad länk kan alltså högst betala för bolagets
egna platser.

**Token i fragmentet.** Webbadressen är `/fortsatt#t=<token>`. Det som står
efter `#` skickas aldrig till servern och hamnar därför varken i våra
åtkomstloggar eller i proxyns. Sidan läser fragmentet, sparar det i
`sessionStorage` och tar bort det ur adressfältet.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core import signing
from django.utils import timezone

log = logging.getLogger(__name__)

SALT = "fleet.continue_link.v1"
MAX_AGE = timedelta(days=30)

EXPIRED_MESSAGE = (
    "Länken fungerar inte längre. Be om en ny i appens chatt eller logga in i kundportalen."
)


class ContinueLinkError(Exception):
    """Bär reason/message/status som `api.handle` kräver av alla domänfel."""

    def __init__(self, reason: str, message: str, status: int = 400, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail


# ---------------------------------------------------------------------------
# Biljetten
# ---------------------------------------------------------------------------


def issue(company_id, *, now: datetime | None = None) -> str:
    """
    Utfärdar länkens biljett för ett bolag. Se modulens text för exakt vad den
    ger rätt till. Tidpunkten ligger i själva nyttolasten (och inte bara i
    signeringens egen tidsstämpel) så att giltigheten går att pröva på en
    given tidpunkt i tester.
    """
    now = now or timezone.now()
    return signing.dumps(
        {"c": str(company_id), "i": int(now.timestamp())}, salt=SALT, compress=True,
    )


def read(token, *, now: datetime | None = None) -> str:
    """Bolagets id ur en giltig biljett, annars ContinueLinkError."""
    if not isinstance(token, str) or not token.strip():
        raise ContinueLinkError("invalid_link", EXPIRED_MESSAGE, status=400)
    try:
        data = signing.loads(token.strip(), salt=SALT)
        company_id = str(data["c"])
        issued = datetime.fromtimestamp(int(data["i"]), tz=timezone.get_current_timezone())
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise ContinueLinkError("invalid_link", EXPIRED_MESSAGE, status=400) from None
    if (now or timezone.now()) - issued > MAX_AGE:
        raise ContinueLinkError("expired_link", EXPIRED_MESSAGE, status=410)
    return company_id


def site_url() -> str:
    """
    Webbplatsens rot (`https://taxitips.se`), hämtad ur samma inställning som
    portallänken i mejlen (`FLEET_PORTAL_URL`, som pekar på `.../portal`).
    """
    base = (getattr(settings, "FLEET_PORTAL_URL", "") or "https://taxitips.se/portal").strip()
    parts = urlparse(base)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return "https://taxitips.se"


def url(company_id) -> str:
    """Länken som skickas. Biljetten i fragmentet, aldrig i frågesträngen."""
    return f"{site_url()}/fortsatt#t={issue(company_id)}"


# ---------------------------------------------------------------------------
# Erbjudandet
# ---------------------------------------------------------------------------


def _items(rows: list[dict]) -> list[dict]:
    """Korta svenska rader: "ABC123 · Skåne", "2 platser · Stockholm"."""
    from core.areas import COUNTY_NAMES

    out: list[dict] = []
    seats: dict[str, int] = {}
    for row in rows:
        county = COUNTY_NAMES.get(str(row["baseCounty"]), str(row["baseCounty"]))
        if row["kind"] == "vehicle":
            out.append({"label": f"{row['plate']} · {county}"})
        else:
            seats[county] = seats.get(county, 0) + 1
    for county, count in seats.items():
        out.append({"label": f"{count} {'plats' if count == 1 else 'platser'} · {county}"})
    return out


def _company_name(company_id) -> str:
    from billing.models import Company
    from fleet.models import CompanyProfile

    profile = CompanyProfile.objects.filter(company_id=company_id).first()
    if profile is not None and profile.legal_name:
        return profile.legal_name
    company = Company.objects.filter(id=company_id).first()
    return (company.name if company else "") or ""


def _state(company_id) -> tuple[str, object | None]:
    """
    ("trial" | "ended" | "paid" | "nothing", provet).

    * paid: bolaget har redan en betald plats (aktiv eller på väg att sägas
      upp), eller har bekräftat fortsättningen med sparat kort -- då är det
      inget mer att betala här.
    * trial / ended: det finns platser att fortsätta med
      (`trials.continue_vehicles`) och provet pågår respektive har löpt ut.
    * nothing: varken betalt eller något att fortsätta med.
    """
    from fleet import commerce, licensing, trials
    from fleet.models import Trial

    if licensing.active_licenses(company_id).exists():
        return "paid", None
    if commerce.trial_commit_status(company_id)["committed"]:
        return "paid", None
    running = trials.active_trial(company_id)
    if running is not None:
        return ("trial", running) if trials.continue_vehicles(company_id, running) else ("nothing", None)
    last = (
        Trial.objects.filter(company_id=company_id, status=Trial.Status.ENDED)
        .order_by("-created_at").first()
    )
    if last is not None and trials.continue_vehicles(company_id, last):
        return "ended", last
    return "nothing", None


def offer(company_id) -> dict:
    """
    Det sidan visar. Beloppen kommer ENBART från `trials.continue_offer`, som
    räknar med samma motor som portalens offert, så att mejlet, sidan och
    Stripe aldrig visar olika belopp. Går priset inte att räkna visas hellre
    inget än fel pris.
    """
    from fleet import company_details, trials

    state, trial = _state(company_id)
    out = {
        "ok": True, "companyName": _company_name(company_id), "state": state,
        "needsOrgNumber": company_details.needs_org_number(company_id),
    }
    if state in ("paid", "nothing"):
        return out
    rows = trials.continue_vehicles(company_id, trial)
    quote = trials.continue_offer(company_id, trial)
    if quote is None:
        raise ContinueLinkError(
            "offer_unavailable", "Priset kan inte visas just nu. Försök igen om en stund.", status=503,
        )
    amount, total = quote["monthly_ore"], quote["monthly_total_ore"]
    out.update({
        "items": _items(rows),
        "monthlyOre": amount,
        "monthlyTotalOre": total,
        "currency": quote["currency"],
        # Momssatsen räknas ur samma offert, inte ur en egen konstant.
        "vatPercent": round((total - amount) * 100 / amount) if amount else 25,
        "trialEndsAt": trial.ends_at.isoformat() if trial and trial.ends_at else None,
    })
    return out


# ---------------------------------------------------------------------------
# Organisationsnumret och kassan
# ---------------------------------------------------------------------------


def set_org_number(company_id, body: dict) -> dict:
    """Bara en gång och bara när numret saknas -- se company_details."""
    from fleet import company_details

    return company_details.set_org_number_for_link(company_id, body)


def _owner_user_id(company_id):
    """Ägaren som ordern läggs i namn av; annars valfri aktiv medlem."""
    from billing.models import CompanyMember

    active = CompanyMember.objects.filter(company_id=company_id, status="active").order_by("created_at")
    member = active.filter(role="company_owner").first() or active.first()
    if member is None:
        raise ContinueLinkError(
            "no_owner", "Vi hittar ingen kontoansvarig för bolaget. Kontakta oss i appens chatt.",
            status=409,
        )
    return member.user_id


def checkout(company_id, body: dict) -> dict:
    """
    Startar Stripe-betalningen för provets platser.

    Planen byggs här av `trials.continue_vehicles` -- samma platser som
    portalens "Fortsätt med provet" skickar -- och klienten får inte skicka
    någon. Samma gren som portalen: pågående prov -> `commit_trial_continuation`,
    utgånget prov -> vanlig beställning (`commerce.place_order`).
    """
    from fleet import commerce, company_details, notifications, orders, trials

    if body.get("accepted") is not True:
        raise orders.OrderError(
            "acceptance_required", "Godkänn priset och villkoren för att betala.",
        )
    state, trial = _state(company_id)
    if state == "paid":
        return {"ok": True, "paymentUrl": None, "alreadyCommitted": True, "cardOnFile": True}
    if state == "nothing":
        raise ContinueLinkError("nothing_to_continue", "Det finns inget att betala.", status=409)
    company_details.require_company_details(company_id)

    plan = orders.plan_change(
        company_id, add_vehicles=trials.continue_specs(trials.continue_vehicles(company_id, trial)),
    )
    owner = _owner_user_id(company_id)
    site = site_url()
    # Inget token i adresserna: sidan sparade det i sessionStorage före avresan.
    success, cancel = f"{site}/fortsatt?betalning=klar", f"{site}/fortsatt?betalning=avbruten"

    if state == "trial":
        _order, info = commerce.commit_trial_continuation(
            company_id, plan, created_by=owner, success_url=success, cancel_url=cancel,
        )
        return {
            "ok": True, "paymentUrl": info.get("paymentUrl"),
            "alreadyCommitted": bool(info.get("alreadyCommitted")),
            "cardOnFile": bool(info.get("cardOnFile")),
        }

    order, info = commerce.place_order(
        company_id, plan, created_by=owner, actor_kind="customer",
        payment=commerce.PAYMENT_CARD, success_url=success, cancel_url=cancel,
    )
    if info.get("stripeError"):
        raise orders.OrderError(
            info["stripeError"]["reason"], info["stripeError"]["message"], status=502,
        )
    notifications.order_confirmed(order)
    return {
        "ok": True, "paymentUrl": info.get("paymentUrl"),
        "alreadyCommitted": False, "cardOnFile": False,
    }
