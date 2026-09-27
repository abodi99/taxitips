"""
Slår upp ett organisationsnummer hos Bolagsverket och visar vad som hämtas.

    manage.py bolagsverket_lookup 556012-5790
    manage.py bolagsverket_lookup 5560125790 --raw     # hela svaret, för felsökning
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from fleet import bolagsverket, orgnr


class Command(BaseCommand):
    help = "Hämtar namn, adress och status för ett organisationsnummer från Bolagsverket."

    def add_arguments(self, parser):
        parser.add_argument("org_number")
        parser.add_argument("--raw", action="store_true")

    def handle(self, *args, org_number: str, raw: bool, **options):
        if not orgnr.is_valid(org_number, "SE"):
            raise CommandError("Organisationsnumret går inte att tolka.")
        normalized = orgnr.normalize(org_number, "SE")
        try:
            if raw or not hasattr(bolagsverket, "lookup"):
                status, body = bolagsverket.fetch_raw(normalized)
                self.stdout.write(f"HTTP {status}")
                self.stdout.write(json.dumps(body, ensure_ascii=False, indent=2)[:6000])
                return
            info = bolagsverket.lookup(normalized)
        except bolagsverket.RegistryUnavailable as exc:
            raise CommandError(f"Bolagsverket: {exc}") from exc
        self.stdout.write(json.dumps(info.as_dict() if info else None, ensure_ascii=False, indent=2))
