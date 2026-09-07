from django.urls import path

from billing.webhooks import stripe_webhook

urlpatterns = [
    path("stripe/webhook", stripe_webhook),
]
