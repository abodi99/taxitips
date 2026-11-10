"""
Flytta ett betalande företag till en annan prislista.

    manage.py move_price_version --company <uuid> --to 2026-11-v1            # bara planen
    manage.py move_price_version --company <uuid> --to 2026-11-v1 --apply    # verkställ

Utan `--apply` skrivs bara planen ut (kund, nuvarande och nytt belopp, datum och
vad som ändras i Stripe) och inget rörs. `--apply` ändrar en riktig faktura i
Stripe och får aldrig köras utan att ägaren sagt ja i chatten. Verkställandet är
dessutom ännu inte byggt (se `fleet.price_moves.apply_move_to_price_version`).
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from fleet import price_moves
from fleet.models import Subscription


class Command(BaseCommand):
    help = "Visar (standard) eller verkställer (--apply) en flytt till en annan prislista."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Företagets id (uuid).")
        parser.add_argument("--to", required=True, help="Målets prislista, t.ex. 2026-11-v1.")
        parser.add_argument("--apply", action="store_true",
                            help="Verkställ. Utan flaggan skrivs bara planen ut.")

    def handle(self, *args, **options):
        subscription = Subscription.objects.filter(
            company_id=options["company"]
        ).select_related("price_version").first()
        if subscription is None:
            raise CommandError("Företaget har inget abonnemang.")
        try:
            plan = price_moves.plan_move_to_price_version(subscription, options["to"])
        except price_moves.PriceMoveError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(plan, indent=2, ensure_ascii=False))
        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Planen ovan är en torrkörning. Inget ändrades."))
            return
        try:
            price_moves.apply_move_to_price_version(subscription, options["to"])
        except NotImplementedError as exc:
            raise CommandError(str(exc)) from exc
