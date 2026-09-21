"""
Adminwebbens endpoints (admin.html). Alla kräver en aktiv StaffRole -- se
fleet/admin_api.py. Eget prefix, /api/admin/, så att det syns på sökvägen att
det här inte är kundens väg.
"""

from django.urls import path

from fleet import admin_api

urlpatterns = [
    path("overview", admin_api.overview),
    path("companies", admin_api.companies),
    path("companies/<uuid:company_id>", admin_api.company_detail),
    path("companies/<uuid:company_id>/subscription", admin_api.set_subscription),
    path("companies/<uuid:company_id>/pairing-code", admin_api.issue_code),
    path("companies/<uuid:company_id>/test-push", admin_api.test_push),
    path("approvals/<uuid:approval_id>/block", admin_api.block_approval),
    path("notifications", admin_api.notifications),
    path("events", admin_api.events),
    path("events/<int:event_id>/visibility", admin_api.event_visibility),
    path("reviews", admin_api.reviews),
    path("reviews/<uuid:review_id>/resolve", admin_api.resolve_review),
]
