"""
Självregistrering från appen: ett inloggat konto blir ägare till ett nytt
företag med en kortfri provperiod.

**Varför en egen väg.** Appen skapade förut bolaget direkt i Supabase
(`companies` via PostgREST) och skickade sedan köparen till Stripe Checkout
i appen. Två fel: den nya modellen (profil, prov, abonnemang) fick aldrig veta
att företaget fanns, och ett köp av en digital tjänst inne i en app är precis
det Apple och Google kräver sina egna betalsystem för. Här skapas allt i en
transaktion, på servern, och inget i registreringen kostar pengar.

**Betalningen sker utanför appen.** Provet är kortfritt och slutar utan
debitering om inget beställs. En beställning läggs i kundportalen på webben
eller av en säljare i adminwebben (betallänk, faktura eller betald utanför
Stripe) -- aldrig i appen. Se docs/fleet-abonnemang.md §9b.

**Så lite som möjligt från användaren.** Namn, juridiskt namn och postadress
hämtas från Bolagsverket med organisationsnumret (fleet/bolagsverket.py).
Företagsnamnet behöver bara skrivas när registret inte har bolaget -- en
enskild firma -- eller inte svarar. Ett avregistrerat bolag får inget konto.

**Vad som INTE bevisas.** Ett organisationsnummer och en e-post är inte bevis
på att personen får företräda bolaget (§7). Profilen börjar därför som
obekräftad och syns så i adminwebben; provet har samma gränser som annars
(en bil, 7 dagar, ett prov per organisationsnummer och 24 månader), och
provet visar bara tåg och buss (fleet/features.py).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from billing.models import Company, CompanyMember
from fleet import accounts, audit, orders, orgnr, sales, signup_checks, trials
from fleet.models import CompanyProfile, Trial


COMPANY_EXISTS_MESSAGE = (
    "Organisationsnumret har redan ett konto hos TaxiTips. Be den som sköter "
    "kontot att lägga till dig, eller kontakta oss i chatten. Ett nytt konto "
    "eller prov skapas inte."
)


@dataclass
class Registration:
    company: Company
    trial: Trial | None
    trial_message: str
    created: bool


@transaction.atomic
def register(
    *,
    user_id: str,
    email: str,
    org_number: str,
    company_name: str = "",
    contact_name: str = "",
    contact_phone: str = "",
    vehicles: list | None = None,
    country: str = "SE",
    token_payload: dict | None = None,
    now=None,
) -> Registration:
    now = now or timezone.now()
    email = accounts.normalize_email(email)
    if not user_id or not email:
        raise sales.SalesError("login_required", "Logga in för att fortsätta.", status=401)
    accounts.assert_email_allowed(email)

    # Idempotent: en app som tappar svaret och försöker igen ska få samma
    # företag tillbaka, inte ett fel eller ett andra företag.
    existing_member = CompanyMember.objects.filter(user_id=user_id, status="active").first()
    if existing_member is not None:
        company = Company.objects.get(id=existing_member.company_id)
        return Registration(company, trials.active_trial(company.id), "", created=False)

    country = (country or "SE").upper()
    normalized_org = orgnr.normalize(org_number, country)
    other = sales.existing_company_for(normalized_org, country) if normalized_org else None
    if other is not None:
        # Den första som registrerar ett organisationsnummer får kontot; nästa
        # får ingen åtkomst, bara ett besked. Försöket rapporteras av vyn
        # (fleet/api.py:register) med `report_duplicate_attempt` -- här hade
        # rapporten rullats tillbaka tillsammans med transaktionen.
        raise sales.SalesError("company_exists", COMPANY_EXISTS_MESSAGE, status=409)
    checked = precheck(
        org_number=org_number, contact_phone=contact_phone, email=email,
        country=country, token_payload=token_payload, now=now, check_existing=False,
    )
    normalized, kind, phone, registry = checked.org_number, checked.kind, checked.phone, checked.registry
    if signup_checks.phone_used_by_other_trial(phone, now=now):
        # Samma skäl som provspärren på organisationsnumret. Inget om vilket
        # bolag: bara att numret redan använts.
        raise sales.SalesError(
            "phone_in_use",
            "Mobilnumret har redan använts för en provperiod i ett annat företag. "
            "Kontakta TaxiTips så hjälper vi dig.",
            status=409,
        )
    found = registry is not None and registry.found
    name = sales._clean(company_name, 200) or (registry.name if found else "")
    if not name:
        raise sales.SalesError(
            "name_required",
            "Vi hittade inte bolaget hos Bolagsverket. Skriv företagets namn.",
        )

    company = Company.objects.create(
        id=uuid.uuid4(), name=name, email=email, org_number=normalized,
        join_code=sales._new_join_code(), seats=1,
        # Samma skäl som i sales.create_company: den gamla statusen ska inte
        # ge åtkomst i någon äldre kodväg. Provet ger åtkomsten.
        status="inactive", subscription_status="inactive", created_at=now,
    )
    CompanyProfile.objects.create(
        company_id=company.id, country=country, org_number=normalized, legal_name=name,
        contact_name=sales._clean(contact_name, 200), contact_email=email,
        contact_phone=phone, billing_email=email,
        # Supabase Auth utfärdar ingen session förrän länken i mejlet klickats,
        # och precheck har nekat en token som säger något annat.
        email_verified_at=now,
        verification_note=(
            "Självregistrering i appen. Behörigheten är inte kontrollerad."
            + (" Enskild firma: namnet är skrivet av kunden." if kind == "person" else "")
            + (f" Bolagsverket: {registry.name}, {registry.status_text}." if found else "")
        ),
    )
    if registry is not None:
        from fleet import bolagsverket

        bolagsverket.apply_to_profile(CompanyProfile.objects.get(company_id=company.id), registry, now=now)
    CompanyMember.objects.create(
        id=uuid.uuid4(), company_id=company.id, user_id=user_id,
        role="company_owner", status="active", created_at=now,
    )
    orders.get_or_create_subscription(company.id)

    trial = None
    message = ""
    check = trials.eligibility(country=country, org_number=normalized, now=now)
    if check.ok:
        trial = trials.create_trial(
            company_id=company.id, country=country, org_number=normalized,
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
            actor_user_id=user_id, now=now,
        )
        specs = sales._vehicle_specs(vehicles or [])
        if specs:
            sales._add_trial_vehicles(trial, specs, actor_user_id=user_id, now=now)
        message = f"Provperioden på {trials.TRIAL_DAYS} dagar startar när den första telefonen kopplas."
    else:
        message = f"{check.message} Kontakta TaxiTips för att komma igång."

    audit.record(
        "self_registered", company_id=company.id, actor_user_id=user_id,
        actor_kind="customer", subject_type="company", subject_id=company.id,
        detail={
            "org_number": normalized, "name": name, "trial": bool(trial), "kind": kind,
            "registry": (registry.status if registry else "unavailable"),
        },
    )
    return Registration(company, trial, message, created=True)


@dataclass
class Checked:
    org_number: str
    kind: str
    phone: str
    registry: object | None


def precheck(
    *,
    org_number: str,
    contact_phone: str,
    email: str = "",
    country: str = "SE",
    token_payload: dict | None = None,
    now=None,
    check_existing: bool = True,
) -> Checked:
    """
    Allt som går att pröva INNAN kontot skapas: numrets form, om bolaget
    redan har ett konto, registret, telefonen och e-postdomänen. Appen anropar
    samma prövning via /api/fleet/register/check innan Supabase-kontot skapas,
    så att ett felskrivet nummer -- eller ett bolag som redan är kund -- inte
    upptäcks först efter att e-posten bekräftats.

    Att bolaget redan har ett konto sägs utan namn eller ägare: bara att det
    finns och vad man gör. Det är ett B2B-avtal, och den som registrerar sig
    ska få veta det innan ett tomt konto skapas.
    """
    country = (country or "SE").upper()
    try:
        if email:
            signup_checks.check_email(email, token_payload)
        if not orgnr.is_valid(org_number, country):
            raise signup_checks.CheckError(
                "invalid_org_number", "Organisationsnumret går inte att tolka.",
            )
        normalized = orgnr.normalize(org_number, country)
        if check_existing and sales.existing_company_for(normalized, country) is not None:
            raise sales.SalesError("company_exists", COMPANY_EXISTS_MESSAGE, status=409)
        phone = signup_checks.check_phone(contact_phone)
        kind = "organisation"
        registry = None
        if country == "SE":
            from fleet import bolagsverket

            kind = signup_checks.check_identity(normalized, today=timezone.localdate(now))
            registry = bolagsverket.try_lookup(normalized)
            signup_checks.check_registry(normalized, kind, registry)
    except signup_checks.CheckError as exc:
        raise sales.SalesError(exc.reason, exc.message) from exc
    if registry is not None and registry.blocks_signup:
        raise sales.SalesError(
            "company_deregistered",
            f"{registry.name} är avregistrerat hos Bolagsverket ({registry.status_text}). "
            "Kontakta TaxiTips om det är fel.",
            status=409,
        )
    return Checked(normalized, kind, phone, registry)


def report_duplicate_attempt(org_number: str, *, email: str, user_id, country: str = "SE", now=None) -> None:
    """
    Någon med ett verifierat konto försökte registrera ett organisationsnummer
    som redan har ett konto. Bokförs i revisionsloggen (syns under Uppföljning)
    och ägaren får ett mejl, en gång per adress: är det en kollega lägger
    ägaren till hen, är det en främling vet ägaren om det.

    Anropas utanför registreringens transaktion, som rullas tillbaka vid felet.
    """
    from fleet import notifications

    now = now or timezone.now()
    company = sales.existing_company_for(org_number, country)
    if company is None:
        return
    email = accounts.normalize_email(email)
    audit.record(
        "duplicate_signup_attempt", company_id=company.id, actor_user_id=user_id,
        actor_kind="customer", subject_type="company", subject_id=company.id,
        detail={"email": email},
    )
    profile = CompanyProfile.objects.filter(company_id=company.id).first()
    owner_email = (profile.contact_email if profile else "") or company.email or ""
    if not owner_email or owner_email == email:
        return
    notifications.queue(
        category="duplicate_signup_attempt", company_id=company.id, to_address=owner_email,
        subject="Någon försökte registrera ert företag hos TaxiTips",
        body=(
            "Hej!\n\n"
            f"{email} försökte just skapa ett nytt TaxiTips-konto med ert "
            "organisationsnummer. Det gick inte: företaget har redan ett konto, och "
            "ingen fick åtkomst.\n\n"
            "Är det en kollega som ska vara med? Svara på det här mejlet så lägger vi "
            "till personen. Känner ni inte igen adressen behöver ni inte göra något.\n\n"
            "Hälsningar\nTaxiTips"
        ),
        key_parts=(company.id, email),
    )
