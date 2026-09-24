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

**Vad som INTE bevisas.** Ett organisationsnummer och en e-post är inte bevis
på att personen får företräda bolaget (§7). Profilen börjar därför som
obekräftad och syns så i adminwebben; provet har samma gränser som annars
(tre bilar, 14 dagar, ett prov per organisationsnummer och 24 månader).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from billing.models import Company, CompanyMember
from fleet import accounts, audit, orders, orgnr, sales, trials
from fleet.models import CompanyProfile, Trial


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
    company_name: str,
    contact_name: str = "",
    contact_phone: str = "",
    vehicles: list | None = None,
    country: str = "SE",
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
    if not orgnr.is_valid(org_number, country):
        raise sales.SalesError("invalid_org_number", "Organisationsnumret går inte att tolka.")
    normalized = orgnr.normalize(org_number, country)
    other = sales.existing_company_for(normalized, country)
    if other is not None:
        # Ingen uppgift om vem som äger det: bara att det finns, och vad man gör.
        raise sales.SalesError(
            "company_exists",
            "Företaget har redan ett konto. Be den som sköter kontot att bjuda in "
            "din e-postadress, eller kontakta TaxiTips.",
            status=409,
        )
    name = sales._clean(company_name, 200)
    if not name:
        raise sales.SalesError("name_required", "Ange företagets namn.")

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
        contact_phone=sales._clean(contact_phone, 40), billing_email=email,
        verification_note="Självregistrering i appen. Behörigheten är inte kontrollerad.",
    )
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
        message = "Provperioden på 14 dagar startar när den första telefonen kopplas."
    else:
        message = f"{check.message} Kontakta TaxiTips för att komma igång."

    audit.record(
        "self_registered", company_id=company.id, actor_user_id=user_id,
        actor_kind="customer", subject_type="company", subject_id=company.id,
        detail={"org_number": normalized, "name": name, "trial": bool(trial)},
    )
    return Registration(company, trial, message, created=True)
