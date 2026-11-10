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
        # Provet startar direkt efter e-postbekräftelsen, inte vid första
        # telefonen: kunden har redan väntat på bekräftelselänken. Att dessutom
        # vänta på att telefonerna delas ut skapade bara supportärenden om
        # förlängning. start_trial är atomiskt och idempotent.
        trial = trials.start_trial(trial, now=now)
        # Välkomstmejlet med vägen till portalen. Förut skickades det bara när
        # provet startade vid första telefonen (api._start_trial_on_first_phone),
        # och den vägen ser aldrig ett prov som redan är igång -- en
        # självregistrerad kund fick inget välkomstmejl alls.
        from fleet import notifications

        notifications.trial_started(company.id, email, trial)
        message = f"Provperioden på {trials.TRIAL_DAYS} dagar har startat."
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
    redan har ett konto, registret, telefonen (formen och om den redan använts
    för ett prov) och e-postdomänen. Appen anropar
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
        if signup_checks.phone_used_by_other_trial(phone, now=now):
            # Samma skäl som provspärren på organisationsnumret. Inget om vilket
            # bolag: bara att numret redan använts. Prövas här och inte först i
            # register(): där har e-posten redan bekräftats, och kunden satt
            # kvar med ett konto utan företag som bara kunde loggas ut.
            raise sales.SalesError(
                "phone_in_use",
                "Mobilnumret har redan använts för en provperiod i ett annat företag. "
                "Kontakta TaxiTips så hjälper vi dig.",
                status=409,
            )
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


# ---------------------------------------------------------------------------
# Registrering med BankID (2026-11)
# ---------------------------------------------------------------------------
#
# Så enkelt som möjligt att börja ett prov: BankID, sedan e-post, lösenord,
# mobil och företagets namn. Inget organisationsnummer och ingen
# bekräftelselänk -- personen är legitimerad, och e-posten är bara
# inloggningsnamnet. Organisationsnumret och fakturauppgifterna fylls i när
# kunden beställer (portalen, `orders.require_company_details`).
#
# Spärren flyttar från bolaget till personen: ett konto och ett prov per
# personnummer (`bankid.trial_key`), plus samma mobilnummerspärr som förut.

MIN_PASSWORD_LENGTH = 8

PERSON_HAS_ACCOUNT_MESSAGE = (
    "Du har redan ett konto hos TaxiTips. Logga in, eller välj "
    "\"Glömt lösenord\" och legitimera dig med BankID för att komma in igen."
)
EMAIL_TAKEN_MESSAGE = (
    "E-postadressen har redan ett konto. Logga in, eller använd en annan adress."
)


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise sales.SalesError(
            "weak_password", f"Lösenordet behöver minst {MIN_PASSWORD_LENGTH} tecken.",
        )


def register_with_bankid(
    *,
    ticket: str,
    email: str,
    password: str,
    contact_phone: str,
    company_name: str,
    now=None,
) -> Registration:
    from fleet import auth_admin, bankid, notifications
    from fleet.models import BankIdIdentity

    now = now or timezone.now()
    identity = bankid.read_ticket(ticket, purpose="register")
    email = accounts.normalize_email(email)
    if not email or "@" not in email:
        raise sales.SalesError("invalid_email", "Skriv en e-postadress.")
    accounts.assert_email_allowed(email)
    try:
        signup_checks.check_email(email)
    except signup_checks.CheckError as exc:
        raise sales.SalesError(exc.reason, exc.message) from exc
    _check_password(password)
    name = sales._clean(company_name, 200)
    if not name:
        raise sales.SalesError("name_required", "Skriv namnet på företaget du kör för.")
    try:
        phone = signup_checks.check_phone(contact_phone)
    except signup_checks.CheckError as exc:
        raise sales.SalesError(exc.reason, exc.message) from exc

    if BankIdIdentity.objects.filter(pnr_key=identity.pnr_key).exists():
        raise sales.SalesError("person_has_account", PERSON_HAS_ACCOUNT_MESSAGE, status=409)
    if signup_checks.phone_used_by_other_trial(phone, now=now):
        raise sales.SalesError(
            "phone_in_use",
            "Mobilnumret har redan använts för en provperiod i ett annat företag. "
            "Kontakta TaxiTips så hjälper vi dig.",
            status=409,
        )
    key = bankid.trial_key(identity.pnr_key)
    check = trials.eligibility_for_key(key, now=now)

    # Kontot skapas först, utanför transaktionen: Supabase Auth är en annan
    # databas. Går något i vår del fel tas kontot bort igen.
    try:
        user_id = auth_admin.create_user(email, password, app_metadata={"bankid": True})
    except auth_admin.EmailTaken as exc:
        raise sales.SalesError("email_taken", EMAIL_TAKEN_MESSAGE, status=409) from exc
    except auth_admin.AuthAdminError as exc:
        raise sales.SalesError(
            "signup_unavailable", "Det gick inte att skapa kontot just nu. Försök igen om en stund.",
            status=503,
        ) from exc

    try:
        with transaction.atomic():
            company, trial = _create_bankid_company(
                user_id=user_id, email=email, name=name, phone=phone,
                identity=identity, key=key, eligible=check.ok, now=now,
            )
    except Exception:
        try:
            auth_admin.delete_user(user_id)
        except auth_admin.AuthAdminError:
            # Ett konto utan företag kan inte göra något; det syns i loggen.
            pass
        raise

    if trial is not None:
        notifications.trial_started(company.id, email, trial)
        message = f"Provperioden på {trials.TRIAL_DAYS} dagar har startat."
    else:
        message = f"{check.message} Kontakta TaxiTips för att komma igång."
    return Registration(company, trial, message, created=True)


def _create_bankid_company(*, user_id, email, name, phone, identity, key, eligible, now):
    from fleet.models import BankIdIdentity, KnownAccount

    # Kontot har ingen token hos oss än; adminwebben och återställningen
    # behöver adressen innan första inloggningen (accounts.seen skriver sedan över).
    KnownAccount.objects.update_or_create(user_id=user_id, defaults={"email": email, "last_seen_at": now})
    # Unik nyckel: två samtidiga registreringar av samma person ger ett konto.
    BankIdIdentity.objects.create(
        user_id=user_id, pnr_key=identity.pnr_key, full_name=identity.full_name[:200],
        verified_at=now,
    )
    company = Company.objects.create(
        id=uuid.uuid4(), name=name, email=email, org_number=None,
        join_code=sales._new_join_code(), seats=1,
        status="inactive", subscription_status="inactive", created_at=now,
    )
    CompanyProfile.objects.create(
        company_id=company.id, country="SE", org_number="", legal_name="",
        contact_name=identity.full_name[:200], contact_email=email,
        contact_phone=phone, billing_email=email,
        verification_note=(
            "Självregistrering i appen med BankID. Personen är legitimerad; "
            "företaget och behörigheten är inte kontrollerade. Organisationsnummer "
            "anges vid beställning."
        ),
    )
    CompanyMember.objects.create(
        id=uuid.uuid4(), company_id=company.id, user_id=user_id,
        role="company_owner", status="active", created_at=now,
    )
    orders.get_or_create_subscription(company.id)

    trial = None
    if eligible:
        trial = trials.create_trial(
            company_id=company.id, country="SE", org_number="", trial_key=key,
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
            actor_user_id=user_id, now=now,
        )
        # Som i register(): klockan startar direkt, kunden ska inte vänta.
        trial = trials.start_trial(trial, now=now)
    audit.record(
        "self_registered", company_id=company.id, actor_user_id=user_id,
        actor_kind="customer", subject_type="company", subject_id=company.id,
        detail={"name": name, "trial": bool(trial), "kind": "bankid"},
    )
    return company, trial


def _account_email(user_id: str, company_id) -> str:
    return accounts.email_for(user_id) or (
        Company.objects.filter(id=company_id).values_list("email", flat=True).first() if company_id else ""
    ) or ""


def bankid_account_email(pnr_key: str) -> str | None:
    """Inloggningen för kontot som hör till personnumret, eller None om det inte finns."""
    from fleet.models import BankIdIdentity

    row = BankIdIdentity.objects.filter(pnr_key=pnr_key).first()
    if row is None:
        return None
    member = CompanyMember.objects.filter(user_id=row.user_id, status="active").first()
    return _account_email(str(row.user_id), member.company_id if member else None)


def recover_with_bankid(*, ticket: str, new_password: str = "", new_email: str = "", now=None) -> dict:
    """
    Glömt lösenord eller bytt e-post: legitimering med BankID räcker. Gäller
    bara konton som skapades med BankID; förarna har kvar länken i mejlet.
    """
    from fleet import auth_admin, bankid, notifications
    from fleet.models import BankIdIdentity

    now = now or timezone.now()
    if not new_password and not new_email:
        raise sales.SalesError("nothing_to_change", "Skriv ett nytt lösenord eller en ny e-postadress.")
    if new_password:
        _check_password(new_password)
    if new_email:
        new_email = accounts.normalize_email(new_email)
        if "@" not in new_email:
            raise sales.SalesError("invalid_email", "Skriv en e-postadress.")
        accounts.assert_email_allowed(new_email)
        try:
            signup_checks.check_email(new_email)
        except signup_checks.CheckError as exc:
            raise sales.SalesError(exc.reason, exc.message) from exc

    with transaction.atomic():
        identity = bankid.read_ticket(ticket, purpose="recover", consume=True)
        row = BankIdIdentity.objects.select_for_update().filter(pnr_key=identity.pnr_key).first()
        if row is None:
            raise sales.SalesError(
                "no_bankid_account",
                "Vi hittar inget konto som skapats med ditt BankID. Har du fått en inbjudan "
                "med e-post? Välj då \"Glömt lösenord\" med e-post i stället.",
                status=404,
            )
        user_id = str(row.user_id)
        member = CompanyMember.objects.filter(user_id=user_id, status="active").first()
        company_id = member.company_id if member else None
        old_email = _account_email(user_id, company_id)
        try:
            auth_admin.update_user(user_id, password=new_password, email=new_email)
        except auth_admin.EmailTaken as exc:
            raise sales.SalesError("email_taken", EMAIL_TAKEN_MESSAGE, status=409) from exc
        except auth_admin.AuthAdminError as exc:
            raise sales.SalesError(
                "recover_unavailable", "Det gick inte att ändra kontot just nu. Försök igen om en stund.",
                status=503,
            ) from exc
        row.last_used_at = now
        row.save(update_fields=["last_used_at"])
        if new_email:
            from fleet.models import KnownAccount

            KnownAccount.objects.update_or_create(user_id=user_id, defaults={"email": new_email})
            if company_id and old_email:
                CompanyProfile.objects.filter(company_id=company_id, contact_email=old_email).update(
                    contact_email=new_email
                )
        audit.record(
            "bankid_recovered", company_id=company_id, actor_user_id=user_id,
            actor_kind="customer", subject_type="account", subject_id=user_id,
            detail={"password": bool(new_password), "email": bool(new_email)},
        )
    if new_email and old_email and old_email != new_email:
        notifications.login_email_changed(company_id, old_email, new_email)
    return {"email": new_email or old_email}


def login_with_bankid(*, ticket: str, now=None) -> dict:
    """
    Inloggning med bara BankID, för den som glömt både e-post och lösenord.

    BankID visar vem personen är; kontot hittas på personnumrets nyckel och
    servern lämnar ut en engångsbiljett som appen växlar till en session.
    Inget lösenord ändras och ingen e-post behövs. Gäller konton som skapats
    med BankID -- en förare som bjudits in med e-post har inget sådant.
    """
    from fleet import auth_admin, bankid
    from fleet.models import BankIdIdentity

    now = now or timezone.now()
    with transaction.atomic():
        identity = bankid.read_ticket(ticket, purpose="login", consume=True)
        row = BankIdIdentity.objects.select_for_update().filter(pnr_key=identity.pnr_key).first()
        if row is None:
            raise sales.SalesError(
                "no_bankid_account", "Ditt BankID har inget konto här.", status=404,
            )
        user_id = str(row.user_id)
        member = CompanyMember.objects.filter(user_id=user_id, status="active").first()
        company_id = member.company_id if member else None
        email = _account_email(user_id, company_id)
        if not email:
            raise sales.SalesError(
                "login_unavailable", "Det gick inte att logga in just nu. Försök igen om en stund.",
                status=503,
            )
        accounts.assert_email_allowed(email)
        try:
            token_hash = auth_admin.login_token(email)
        except auth_admin.AuthAdminError as exc:
            raise sales.SalesError(
                "login_unavailable", "Det gick inte att logga in just nu. Försök igen om en stund.",
                status=503,
            ) from exc
        row.last_used_at = now
        row.save(update_fields=["last_used_at"])
        audit.record(
            "bankid_login", company_id=company_id, actor_user_id=user_id,
            actor_kind="customer", subject_type="account", subject_id=user_id, detail={},
        )
    return {"email": email, "tokenHash": token_hash}
