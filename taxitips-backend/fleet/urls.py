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
    # Registreringen: bolagets namn från Bolagsverket, före inloggning.
    path("registry", api.registry_lookup),
    # Administratören
    path("company", api.company_overview),
    path("vehicles", api.create_vehicle),
    path("pairing-codes", api.issue_pairing_code),
    path("approvals/<uuid:approval_id>/block", api.block_approval),
    path("approvals/<uuid:approval_id>/label", api.rename_approval),
    path("licenses/<uuid:license_id>/vehicle", api.change_license_vehicle),
    path("quote", api.quote),
    path("orders", api.create_order),
    path("orders/list", api.list_orders),
    path("subscription/cancel", api.cancel),
    path("subscription/undo-cancel", api.undo_cancel),
    # Registrering och prov
    path("signup", api.signup),
    path("register", api.register),
    path("trial/vehicles", api.trial_vehicles),
    path("trial/vehicles/<uuid:license_id>/county", api.trial_vehicle_county),
    path("trial/vehicles/<uuid:license_id>/remove", api.trial_vehicle_remove),
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
