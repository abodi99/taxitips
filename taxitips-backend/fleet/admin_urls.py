"""
Adminwebbens endpoints (admin.html). Alla kräver en aktiv StaffRole -- se
fleet/admin_api.py. Eget prefix, /api/admin/, så att det syns på sökvägen att
det här inte är kundens väg.
"""

from django.urls import path

from fleet import admin_accounts, admin_api, admin_sales, admin_vehicles

urlpatterns = [
    path("overview", admin_api.overview),
    path("companies", admin_api.companies),
    path("companies/new", admin_sales.create_company),
    path("companies/<uuid:company_id>", admin_api.company_detail),
    path("companies/<uuid:company_id>/profile", admin_sales.update_profile),
    path("companies/<uuid:company_id>/quote", admin_sales.quote),
    path("companies/<uuid:company_id>/orders", admin_sales.create_order),
    path("companies/<uuid:company_id>/trial", admin_sales.start_trial),
    path("companies/<uuid:company_id>/coupon", admin_sales.redeem_coupon),
    path("companies/<uuid:company_id>/cancel", admin_sales.cancel_subscription),
    path("companies/<uuid:company_id>/undo-cancel", admin_sales.undo_cancel),
    path("companies/<uuid:company_id>/owner-invite", admin_sales.invite_owner),
    path("companies/<uuid:company_id>/subscription", admin_api.set_subscription),
    path("companies/<uuid:company_id>/pairing-code", admin_api.issue_code),
    path("companies/<uuid:company_id>/test-push", admin_api.test_push),
    path("approvals/<uuid:approval_id>/block", admin_api.block_approval),
    path("licenses/<uuid:license_id>/vehicle", admin_vehicles.change_vehicle),
    path("licenses/<uuid:license_id>/counties", admin_vehicles.set_trial_counties),
    path("licenses/<uuid:license_id>/remove", admin_vehicles.remove_license),
    path("orders/<uuid:order_id>/payment-link", admin_sales.order_payment_link),
    path("orders/<uuid:order_id>/refresh", admin_sales.order_refresh),
    path("orders/<uuid:order_id>/mark-paid", admin_sales.order_mark_paid),
    path("orders/<uuid:order_id>/cancel", admin_sales.order_cancel),
    path("sales/config", admin_sales.config),
    path("sales/lookup", admin_sales.lookup),
    path("coupons", admin_sales.coupons),
    path("coupons/new", admin_sales.create_coupon),
    path("coupons/<uuid:coupon_id>/deactivate", admin_sales.deactivate_coupon),
    path("notifications", admin_api.notifications),
    path("events", admin_api.events),
    path("events/new", admin_api.event_create),
    path("events/import", admin_api.event_import),
    path("events/venues", admin_api.event_venues),
    path("events/<int:event_id>/visibility", admin_api.event_visibility),
    path("events/<int:event_id>/delete", admin_api.event_delete),
    path("accounts", admin_accounts.search),
    path("blocks", admin_accounts.blocks),
    path("blocks/new", admin_accounts.create_block),
    path("blocks/<uuid:block_id>/lift", admin_accounts.lift_block),
    path("companies/<uuid:company_id>/members/<uuid:user_id>", admin_accounts.set_member),
    path("companies/<uuid:company_id>/verification", admin_accounts.verify_company),
    path("staff", admin_accounts.staff),
    path("staff/set", admin_accounts.set_staff),
    path("reviews", admin_api.reviews),
    path("reviews/<uuid:review_id>/resolve", admin_api.resolve_review),
]
