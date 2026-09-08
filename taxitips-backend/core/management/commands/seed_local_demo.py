"""
Fyller den LOKALA databasen med en komplett, inloggningsbar uppsättning:
bolag i tre olika betalningslägen, ägarkonton, förarenheter.

Varför den finns: `supabase/seed.sql` skapar ett bolag och två förartokens,
men inget konto att logga in med och ingen prenumeration att titta på. Att
klicka ihop det för hand efter varje `supabase db reset` är både tråkigt och
en felkälla -- glömmer man kopplingen mellan konto och bolag ser appen
inloggad men tom ut, vilket är exakt det felläget som kostat mest tid i det
här projektet.

Tre bolag, med avsikt, för att de tre tillstånden ser olika ut i appen:

    Taxi Tips Demo AB   trial          ska se allt
    Malmö Taxi AB       betalande      ska se allt, med aktiv prenumeration
    Norrtaxi AB         uppsagd        ska INTE se några tips

Det sista är inte en kuriositet: "obetalt bolag" och "pipelinen hittade
inget" ser identiska ut på skärmen om man inte har något att jämföra med.

Kör bara lokalt. Kommandot vägrar mot en databas som inte är på 127.0.0.1,
och skapar aldrig ett konto med ett riktigt lösenord värt att stjäla.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

PASSWORD = "taxitips123"

COMPANIES = [
    {
        "id": "00000000-0000-4000-8000-000000000001",
        "name": "Taxi Tips Demo AB",
        "email": "demo@taxitips.se",
        "join_code": "DEMO01",
        "seats": 10,
        "status": "trial",
        "subscription_status": "inactive",
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "owner": "demo@taxitips.se",
        "members": [("test@taxitips.se", "company_owner")],
        "devices": [
            ("9a9bf67c6e8885f44c831232afd314788d86067b7ddfcced", "Förare – Anna"),
            ("6c485ae7c5d16fe553a0ed5758f08cde1d1f69b3bc2efb29", "Förare – Kalle"),
        ],
    },
    {
        "id": "00000000-0000-4000-8000-000000000002",
        "name": "Malmö Taxi AB",
        "email": "agare@malmotaxi.se",
        "join_code": "MALMO1",
        "seats": 25,
        "status": "active",
        "subscription_status": "active",
        # Test-mode-id:n i Stripes format. Ingen riktig kund, ingen riktig
        # prenumeration -- de finns för att koden som läser fälten ska ha
        # något realistiskt att läsa.
        "stripe_customer_id": "cus_LOCALDEMO0001",
        "stripe_subscription_id": "sub_LOCALDEMO0001",
        "owner": "agare@malmotaxi.se",
        "members": [("chef@malmotaxi.se", "company_admin")],
        "devices": [
            ("11111111111111111111111111111111111111111111aaaa", "Bil 12 – Ali"),
            ("22222222222222222222222222222222222222222222bbbb", "Bil 14 – Sara"),
            ("33333333333333333333333333333333333333333333cccc", "Bil 21 – Johan"),
        ],
    },
    {
        "id": "00000000-0000-4000-8000-000000000003",
        "name": "Norrtaxi AB",
        "email": "agare@norrtaxi.se",
        "join_code": "NORR01",
        "seats": 5,
        "status": "canceled",
        "subscription_status": "canceled",
        "stripe_customer_id": "cus_LOCALDEMO0002",
        "stripe_subscription_id": "sub_LOCALDEMO0002",
        "owner": "agare@norrtaxi.se",
        "members": [],
        "devices": [
            ("44444444444444444444444444444444444444444444dddd", "Bil 3 – Eva"),
        ],
    },
]


class Command(BaseCommand):
    help = "Fyller den lokala databasen med bolag, prenumerationer, ägarkonton och förare"

    def add_arguments(self, parser):
        parser.add_argument(
            "--supabase-url",
            default=getattr(settings, "SUPABASE_URL", "http://127.0.0.1:54321"),
        )
        parser.add_argument(
            "--service-key",
            default="",
            help="Supabase service_role-nyckel. Utan den skapas inga konton, bara bolag och enheter.",
        )

    def handle(self, *args, **options):
        host = connection.settings_dict.get("HOST", "")
        if host not in ("127.0.0.1", "localhost", ""):
            raise CommandError(
                f"Vägrar köra mot {host}. Kommandot skapar konton med ett känt "
                "lösenord och är bara till för en lokal databas."
            )

        self.url = options["supabase_url"].rstrip("/")
        self.key = options["service_key"]

        created_users = {}
        for company in COMPANIES:
            self._upsert_company(company)
            emails = [company["owner"], *[m[0] for m in company["members"]]]
            for email in emails:
                role = "company_owner" if email == company["owner"] else dict(company["members"])[email]
                user_id = self._ensure_user(email)
                if user_id:
                    created_users[email] = (user_id, company["name"], role)
                    self._ensure_member(company["id"], user_id, role)
            self._upsert_devices(company)

        self._report(created_users)

    # -- databasen ------------------------------------------------------

    def _upsert_company(self, c: dict) -> None:
        with connection.cursor() as cur:
            cur.execute(
                """
                insert into public.companies
                    (id, name, email, join_code, seats, status, created_at,
                     stripe_customer_id, stripe_subscription_id, subscription_status)
                values (%s, %s, %s, %s, %s, %s, now(), %s, %s, %s)
                on conflict (id) do update set
                    name = excluded.name,
                    email = excluded.email,
                    join_code = excluded.join_code,
                    seats = excluded.seats,
                    status = excluded.status,
                    stripe_customer_id = excluded.stripe_customer_id,
                    stripe_subscription_id = excluded.stripe_subscription_id,
                    subscription_status = excluded.subscription_status
                """,
                [c["id"], c["name"], c["email"], c["join_code"], c["seats"], c["status"],
                 c["stripe_customer_id"], c["stripe_subscription_id"], c["subscription_status"]],
            )
        self.stdout.write(
            f"  {c['name']:<20} {c['status']:<9} prenumeration: {c['subscription_status']:<9} "
            f"kod {c['join_code']}"
        )

    def _ensure_member(self, company_id: str, user_id: str, role: str) -> None:
        with connection.cursor() as cur:
            cur.execute(
                """
                insert into public.company_members (id, company_id, user_id, role, status, created_at)
                values (%s, %s, %s, %s, 'active', now())
                on conflict (company_id, user_id) do update set role = excluded.role, status = 'active'
                """,
                [str(uuid.uuid4()), company_id, user_id, role],
            )

    def _upsert_devices(self, c: dict) -> None:
        with connection.cursor() as cur:
            for token, label in c["devices"]:
                cur.execute(
                    """
                    insert into public.devices (id, company_id, token, label, kind, notify_prefs, created_at)
                    values (%s, %s, %s, %s, 'driver', '{}'::jsonb, now())
                    on conflict (token) do update set
                        company_id = excluded.company_id, label = excluded.label
                    """,
                    [str(uuid.uuid4()), c["id"], token, label],
                )

    # -- konton via Supabases admin-API ---------------------------------

    def _ensure_user(self, email: str) -> str | None:
        """
        Skapar kontot om det saknas, och sätter om lösenordet om det finns.

        Går via GoTrues admin-API i stället för att skriva i auth.users
        direkt: lösenordshashen, identitetsraden och metadatan har krav som
        inte syns i tabellen, och ett konto som ser rätt ut i databasen men
        inte kan logga in är svårare att felsöka än inget konto alls.
        """
        if not self.key:
            return self._existing_user_id(email)

        payload = {
            "email": email,
            "password": PASSWORD,
            "email_confirm": True,
            "user_metadata": {"name": email.split("@")[0].title()},
        }
        try:
            body = self._admin("POST", "/auth/v1/admin/users", payload)
            return body.get("id")
        except urllib.error.HTTPError as exc:
            if exc.code not in (409, 422):
                raise CommandError(f"Kunde inte skapa {email}: {exc.read()[:200]!r}")

        # Finns redan: sätt om lösenordet så att listan nedan alltid stämmer.
        user_id = self._existing_user_id(email)
        if user_id:
            try:
                self._admin("PUT", f"/auth/v1/admin/users/{user_id}",
                            {"password": PASSWORD, "email_confirm": True})
            except urllib.error.HTTPError as exc:
                self.stderr.write(f"  kunde inte uppdatera {email}: {exc.code}")
        return user_id

    def _existing_user_id(self, email: str) -> str | None:
        with connection.cursor() as cur:
            cur.execute("select id from auth.users where email = %s", [email])
            row = cur.fetchone()
        return str(row[0]) if row else None

    def _admin(self, method: str, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=json.dumps(payload).encode(),
            method=method,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read() or b"{}")

    # -- utskrift -------------------------------------------------------

    def _report(self, users: dict) -> None:
        if not users:
            self.stdout.write(self.style.WARNING(
                "\nInga konton skapade -- kör med --service-key för att få inloggningar.\n"
                "Nyckeln: cd taxitips-api && supabase status -o json | grep SERVICE_ROLE_KEY"
            ))
            return
        self.stdout.write(self.style.SUCCESS("\nInloggningar (lösenord: " + PASSWORD + ")"))
        for email, (_uid, company, role) in sorted(users.items()):
            self.stdout.write(f"  {email:<24} {role:<14} {company}")
        self.stdout.write(
            "\nFörartokens finns i seed_local_demo.py. Norrtaxi är uppsagt med "
            "avsikt: det bolaget ska INTE se några tips."
        )
