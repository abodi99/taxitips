"""
Kundlivscykelns endpoints.

Förarens vägar bär `X-Device-Token`, administratörens `Authorization: Bearer`.
Ingen av dem delar prefix med förarflödet (`/api/alerts` m.fl.), så det går
att se på sökvägen vilken sorts bevis som krävs.
"""

from django.urls import path

from fleet import api

urlpatterns = [
    # Förarens telefon
    path("pair", api.pair),
    path("me", api.driver_status),
    path("session", api.session_start),
    path("session/end", api.session_end),
    path("join-request", api.join_request),
    # Administratören
    path("company", api.company_overview),
    path("vehicles", api.create_vehicle),
    path("pairing-codes", api.issue_pairing_code),
    path("approvals/<uuid:approval_id>/block", api.block_approval),
    path("licenses/<uuid:license_id>/vehicle", api.change_license_vehicle),
    path("quote", api.quote),
    path("orders", api.create_order),
    path("orders/list", api.list_orders),
    path("subscription/cancel", api.cancel),
    path("subscription/undo-cancel", api.undo_cancel),
    # Registrering och prov
    path("signup", api.signup),
    path("trial-eligibility", api.trial_eligibility),
    path("claim-invite", api.claim_invite),
    path("invites", api.create_invite),
    # Företag och behörigheter
    path("members/remove", api.remove_member),
    path("ownership/transfer", api.transfer_ownership),
    path("ownership/<uuid:transfer_id>/accept", api.accept_ownership),
    path("company/close", api.close_account),
    path("company/contracting-party", api.change_contracting_party),
    # Plattformens granskning
    path("reviews/<uuid:review_id>/resolve", api.resolve_review),
]
