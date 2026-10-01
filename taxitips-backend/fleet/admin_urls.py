"""
Adminwebbens endpoints (admin.html). Alla kräver en aktiv StaffRole -- se
fleet/admin_api.py. Eget prefix, /api/admin/, så att det syns på sökvägen att
det här inte är kundens väg.
"""

from django.urls import path

from fleet import (
    admin_accounts, admin_activity, admin_api, admin_app_version, admin_crm, admin_followup, admin_sales,
    admin_status, admin_support, admin_tip_reports, admin_vehicles,
)

urlpatterns = [
    path("overview", admin_api.overview),
    # Varje koppling (databas, kö, källor, Stripe, Bolagsverket, Firebase, SMTP).
    path("status", admin_status.status),
    # Minsta och rekommenderade appversion per plattform -- se core/app_version.py.
    path("app-version", admin_app_version.app_version_view),
    path("companies", admin_api.companies),
    # Säljarens uppföljning av prov (vem ska ringas, vad sa de).
    path("followups", admin_followup.followups),
    path("followups/<uuid:company_id>", admin_followup.update_followup),
    path("crm/status", admin_crm.crm_status),
    path("crm/pipeline", admin_crm.pipeline),
    path("crm/deals", admin_crm.deal_create),
    path("crm/deals/<uuid:deal_id>", admin_crm.deal_detail),
    path("crm/deals/<uuid:deal_id>/update", admin_crm.deal_update),
    path("crm/deals/<uuid:deal_id>/link-company", admin_crm.deal_link_company),
    path("crm/deals/<uuid:deal_id>/notes", admin_crm.deal_note),
    # Alias tills admin-UI:n bara använder /deals
    path("crm/leads", admin_crm.deal_create),
    path("crm/leads/<uuid:lead_id>", admin_crm.deal_detail),
    path("crm/leads/<uuid:lead_id>/update", admin_crm.deal_update),
    path("crm/leads/<uuid:lead_id>/link-company", admin_crm.deal_link_company),
    path("crm/leads/<uuid:lead_id>/notes", admin_crm.deal_note),
    path("companies/<uuid:company_id>/crm", admin_crm.company_crm),
    path("companies/<uuid:company_id>/crm/notes", admin_crm.company_crm_note),
    path("companies/new", admin_sales.create_company),
    path("companies/<uuid:company_id>", admin_api.company_detail),
    path("companies/<uuid:company_id>/profile", admin_sales.update_profile),
    path("companies/<uuid:company_id>/registry", admin_sales.refresh_registry),
    path("companies/<uuid:company_id>/archive", admin_api.archive_company),
    path("companies/<uuid:company_id>/delete", admin_api.delete_company),
    path("companies/<uuid:company_id>/support", admin_support.start_with_company),
    # Supportchatten
    path("support/threads", admin_support.threads),
    path("support/summary", admin_support.summary),
    path("support/threads/<uuid:thread_id>", admin_support.thread_detail),
    path("support/threads/<uuid:thread_id>/messages", admin_support.reply),
    path("support/threads/<uuid:thread_id>/status", admin_support.set_status),
    path("companies/<uuid:company_id>/quote", admin_sales.quote),
    path("companies/<uuid:company_id>/orders", admin_sales.create_order),
    path("companies/<uuid:company_id>/trial", admin_sales.start_trial),
    path("companies/<uuid:company_id>/trial/extend", admin_sales.extend_trial),
    path("companies/<uuid:company_id>/discount", admin_sales.set_discount),
    path("companies/<uuid:company_id>/discount/clear", admin_sales.clear_discount),
    path("companies/<uuid:company_id>/discounts", admin_sales.list_discounts),
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
    # Appar och fel: senaste inloggning, version och telefon per konto och
    # telefon, och appens/serverns fel. Se fleet/admin_activity.py.
    path("activity/clients", admin_activity.clients),
    path("activity/errors", admin_activity.errors),
    path("blocks", admin_accounts.blocks),
    path("blocks/new", admin_accounts.create_block),
    path("blocks/<uuid:block_id>/lift", admin_accounts.lift_block),
    path("companies/<uuid:company_id>/members/<uuid:user_id>", admin_accounts.set_member),
    path("companies/<uuid:company_id>/verification", admin_accounts.verify_company),
    path("staff", admin_accounts.staff),
    path("staff/set", admin_accounts.set_staff),
    path("reviews", admin_api.reviews),
    path("reviews/<uuid:review_id>/resolve", admin_api.resolve_review),
    path("tip-reports/summary", admin_tip_reports.summary),
    path("tip-reports", admin_tip_reports.list_reports),
    path("tip-reports/<uuid:report_id>", admin_tip_reports.report_detail),
    path("tip-reports/<uuid:report_id>/resolve", admin_tip_reports.resolve_report),
    path("opportunities/<uuid:opportunity_id>/suppress", admin_tip_reports.suppress_opportunity),
]
