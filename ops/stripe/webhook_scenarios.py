"""
Scenariotester för Stripe-webhooken (taxitips-api/supabase/functions/stripe-webhook)
mot en LOKAL Supabase. Inga riktiga Stripe-anrop och inga riktiga nycklar.

    # 1. Testhemlighet i en fil utanför repot
    printf 'STRIPE_SECRET_KEY=sk_test_lokal\\nSTRIPE_WEBHOOK_SECRET=whsec_lokal_test\\n' > /tmp/functions.env
    # 2. Kör funktionen lokalt
    cd taxitips-api && supabase functions serve stripe-webhook --no-verify-jwt --env-file /tmp/functions.env
    # 3. Kör scenarierna med samma testhemlighet
    STRIPE_WEBHOOK_SECRET=whsec_lokal_test python3 ops/stripe/webhook_scenarios.py

Skriptet skapar ett testbolag och egna händelserader och tar bort just dem
efteråt. Databasen nås via `docker exec` i den lokala Supabase-containern.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("WEBHOOK_URL", "http://127.0.0.1:54321/functions/v1/stripe-webhook")
SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
DB_CONTAINER = os.environ.get("DB_CONTAINER", "supabase_db_taxitips")
COMPANY = "00000000-0000-4000-8000-00000000c3c3"
CUSTOMER = "cus_taxitips_scenario"
PREFIX = "evt_taxitips_scenario_"


def sql(query: str) -> str:
    out = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "psql", "-U", "postgres", "-At", "-v", "ON_ERROR_STOP=1"],
        input=query, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def send(event: dict, signed: bool = True) -> tuple[int, str]:
    payload = json.dumps(event)
    stamp = str(int(time.time()))
    digest = hmac.new(SECRET.encode(), f"{stamp}.{payload}".encode(), hashlib.sha256).hexdigest()
    signature = f"t={stamp},v1={digest if signed else '0' * 64}"
    request = urllib.request.Request(
        URL, data=payload.encode(), method="POST",
        headers={"Content-Type": "application/json", "Stripe-Signature": signature},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def event(name: str, kind: str, created: int, obj: dict) -> dict:
    return {"id": PREFIX + name, "object": "event", "type": kind, "created": created, "data": {"object": obj}}


def subscription(status: str, quantity: int = 1) -> dict:
    return {"id": "sub_taxitips_scenario", "customer": CUSTOMER, "status": status, "items": {"data": [{"quantity": quantity}]}}


def company() -> tuple[str, str, int]:
    status, subscription_status, seats = sql(
        f"select status, subscription_status, seats from companies where id = '{COMPANY}';"
    ).split("|")
    return status, subscription_status, int(seats)


def event_status(name: str) -> str:
    return sql(f"select coalesce((select status from processed_webhook_events where stripe_event_id = '{PREFIX}{name}'), 'saknas');")


def cleanup() -> None:
    sql(
        f"delete from processed_webhook_events where stripe_event_id like '{PREFIX}%';"
        f"delete from companies where id = '{COMPANY}';"
    )


def main() -> int:
    cleanup()
    sql(
        "insert into companies (id, name, join_code, seats, status, stripe_customer_id, subscription_status) "
        f"values ('{COMPANY}', 'Webhookscenario AB', 'WHSCEN', 1, 'trial', '{CUSTOMER}', 'inactive');"
    )
    t0 = int(time.time()) - 1000
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))

    try:
        code, _ = send(event("badsig", "customer.subscription.updated", t0, subscription("active")), signed=False)
        check("fel signatur avvisas", code == 400 and event_status("badsig") == "saknas", f"http {code}")

        code, body = send(event("active", "customer.subscription.updated", t0 + 100, subscription("active", 3)))
        check("korrekt signatur tillämpas", code == 200 and company() == ("active", "active", 3), f"http {code} {company()}")

        code, body = send(event("active", "customer.subscription.updated", t0 + 100, subscription("active", 3)))
        count = sql(f"select count(*) from processed_webhook_events where stripe_event_id = '{PREFIX}active';")
        check("dubblett tillämpas en gång", code == 200 and "duplicate" in body and count == "1", f"http {code} rader {count}")

        code, _ = send(event("older", "customer.subscription.updated", t0 + 50, subscription("past_due", 3)))
        check("äldre händelse skriver inte över nyare", code == 200 and company()[0] == "active", f"http {code} {company()}")

        sql(
            "insert into processed_webhook_events (stripe_event_id, event_type, status, error) "
            f"values ('{PREFIX}retry', 'customer.subscription.updated', 'error', 'tidigare fel');"
        )
        code, _ = send(event("retry", "customer.subscription.updated", t0 + 200, subscription("past_due", 3)))
        check(
            "misslyckad händelse tas om vid omleverans",
            code == 200 and company()[0] == "past_due" and event_status("retry") == "ok",
            f"http {code} {company()} rad {event_status('retry')}",
        )

        sql(
            "insert into processed_webhook_events (stripe_event_id, event_type, status) "
            f"values ('{PREFIX}inflight', 'customer.subscription.updated', 'processing');"
        )
        code, _ = send(event("inflight", "customer.subscription.updated", t0 + 250, subscription("active", 3)))
        check("pågående försök ger 409, inte 200", code == 409 and company()[0] == "past_due", f"http {code}")

        checkout = {"id": "cs_taxitips_scenario", "subscription": "sub_taxitips_scenario", "metadata": {"company_id": COMPANY}}
        code, _ = send(event("unpaid", "checkout.session.completed", t0 + 260, {**checkout, "payment_status": "unpaid"}))
        check("obetald checkout aktiverar inte", code == 200 and company()[0] == "past_due", f"http {code} {company()}")

        code, _ = send(event("paid", "checkout.session.async_payment_succeeded", t0 + 270, {**checkout, "payment_status": "paid"}))
        check("betald checkout aktiverar", code == 200 and company()[0] == "active", f"http {code} {company()}")

        code, _ = send(event("deleted", "customer.subscription.deleted", t0 + 300, subscription("canceled", 3)))
        check("uppsagd prenumeration stänger bolaget", code == 200 and company()[:2] == ("canceled", "canceled"), f"http {code} {company()}")
    finally:
        cleanup()

    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print(f"{'OK  ' if ok else 'FEL '} {name:<{width}}  {detail}")
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} av {len(results)} scenarier godkända")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
