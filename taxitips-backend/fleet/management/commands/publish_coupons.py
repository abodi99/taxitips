"""
Lägger upp aktiva kuponger från adminwebben som kampanjkoder i Stripe-kassan.

Nya kuponger publiceras när de skapas (fleet/admin_sales.py). Det här är för
dem som skapades innan, eller när Stripe inte svarade. Idempotent: en kupong
som redan har sin kampanjkod hoppas över.

    manage.py publish_coupons            # visar vad som skulle göras
    manage.py publish_coupons --apply    # skapar dem i Stripe
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from fleet import stripe_sync
from fleet.models import Coupon


class Command(BaseCommand):
    help = "Lägger upp aktiva kuponger som kampanjkoder i Stripe."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Skapa dem i Stripe på riktigt.")
        parser.add_argument("--code", default="", help="Bara den här koden.")

    def handle(self, *args, **options):
        now = timezone.now()
        rows = Coupon.objects.filter(is_active=True).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gt=now)
        ).order_by("created_at")
        if options["code"]:
            rows = rows.filter(code=options["code"].strip().upper())
        for coupon in rows:
            months = stripe_sync.coupon_months(coupon.days)
            if not options["apply"]:
                self.stdout.write(f"{coupon.code}: {coupon.days} dagar -> 100 % i {months} mån (torrkörning)")
                continue
            result = stripe_sync.publish_coupon(coupon)
            self.stdout.write(f"{coupon.code}: {result}")
