# Tabeller i public

Genererad av `manage.py dump_truth`. Redigera inte för hand.

## ais_vessels  (1676 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| mmsi | bigint | NO |  |
| name | character varying | NO |  |
| call_sign | character varying | NO |  |
| imo | integer | YES |  |
| ship_type | smallint | YES |  |
| ais_class | character varying | NO |  |
| length_m | smallint | YES |  |
| width_m | smallint | YES |  |
| draught_m | double precision | YES |  |
| destination | character varying | NO |  |
| latitude | double precision | YES |  |
| longitude | double precision | YES |  |
| speed_knots | double precision | YES |  |
| course | double precision | YES |  |
| heading | smallint | YES |  |
| nav_status | smallint | YES |  |
| port_name | character varying | NO |  |
| last_message_type | character varying | NO |  |
| messages | integer | NO |  |
| position_at | timestamp with time zone | YES |  |
| static_at | timestamp with time zone | YES |  |
| updated_at | timestamp with time zone | NO |  |

## alert_feedback  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO | gen_random_uuid() |
| alert_id | uuid | YES |  |
| device_token | text | YES |  |
| result | boolean | YES |  |
| created_at | timestamp with time zone | YES |  |

## alerts  (4345 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO | gen_random_uuid() |
| kind | text | YES |  |
| level | text | YES |  |
| title | text | YES |  |
| summary | text | YES |  |
| lat | double precision | YES |  |
| lon | double precision | YES |  |
| places | jsonb | YES |  |
| payload | jsonb | YES |  |
| updated_at | timestamp with time zone | NO |  |
| h3_index | text | YES |  |
| start_time | timestamp with time zone | YES |  |
| end_time | timestamp with time zone | YES |  |
| demand_score | integer | YES |  |
| reasons | ARRAY | YES |  |

## auth_group  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | integer | NO |  |
| name | character varying | NO |  |

## auth_group_permissions  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| group_id | integer | NO |  |
| permission_id | integer | NO |  |

## auth_permission  (224 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | integer | NO |  |
| name | character varying | NO |  |
| content_type_id | integer | NO |  |
| codename | character varying | NO |  |

## auth_user  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | integer | NO |  |
| password | character varying | NO |  |
| last_login | timestamp with time zone | YES |  |
| is_superuser | boolean | NO |  |
| username | character varying | NO |  |
| first_name | character varying | NO |  |
| last_name | character varying | NO |  |
| email | character varying | NO |  |
| is_staff | boolean | NO |  |
| is_active | boolean | NO |  |
| date_joined | timestamp with time zone | NO |  |

## auth_user_groups  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| user_id | integer | NO |  |
| group_id | integer | NO |  |

## auth_user_user_permissions  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| user_id | integer | NO |  |
| permission_id | integer | NO |  |

## companies  (18 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO | gen_random_uuid() |
| name | text | NO |  |
| email | text | YES |  |
| org_number | text | YES |  |
| join_code | text | NO |  |
| seats | integer | NO | 1 |
| status | text | NO | 'trial'::text |
| watched_areas | ARRAY | NO | '{}'::text[] |
| created_at | timestamp with time zone | NO | now() |
| stripe_customer_id | text | YES |  |
| stripe_subscription_id | text | YES |  |
| subscription_status | text | NO | 'inactive'::text |
| last_subscription_event_at | timestamp with time zone | YES |  |

## company_members  (16 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO | gen_random_uuid() |
| company_id | uuid | NO |  |
| user_id | uuid | NO |  |
| role | text | YES |  |
| status | text | YES |  |
| created_at | timestamp with time zone | YES |  |

## device_presence  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| device_id | uuid | NO |  |
| cell_lat | double precision | NO |  |
| cell_lon | double precision | NO |  |
| updated_at | timestamp with time zone | NO |  |
| expires_at | timestamp with time zone | NO |  |

## device_transfer_codes  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| code | text | NO |  |
| device_id | uuid | NO |  |
| expires_at | timestamp with time zone | NO |  |

## devices  (23 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO | gen_random_uuid() |
| company_id | uuid | NO |  |
| token | text | NO |  |
| label | text | NO |  |
| kind | text | NO |  |
| push_token | text | YES |  |
| notify_prefs | jsonb | NO | '{}'::jsonb |
| created_at | timestamp with time zone | YES |  |
| user_id | uuid | YES |  |
| last_seen_at | timestamp with time zone | YES |  |

## django_admin_log  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | integer | NO |  |
| action_time | timestamp with time zone | NO |  |
| object_id | text | YES |  |
| object_repr | character varying | NO |  |
| action_flag | smallint | NO |  |
| change_message | text | NO |  |
| content_type_id | integer | YES |  |
| user_id | integer | NO |  |

## django_content_type  (56 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | integer | NO |  |
| app_label | character varying | NO |  |
| model | character varying | NO |  |

## django_migrations  (55 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| app | character varying | NO |  |
| name | character varying | NO |  |
| applied | timestamp with time zone | NO |  |

## django_session  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| session_key | character varying | NO |  |
| session_data | text | NO |  |
| expire_date | timestamp with time zone | NO |  |

## events  (404 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| source | character varying | NO |  |
| external_id | character varying | NO |  |
| name | character varying | NO |  |
| url | character varying | NO |  |
| source_status | character varying | NO |  |
| category | character varying | NO |  |
| segment | character varying | NO |  |
| genre | character varying | NO |  |
| sub_genre | character varying | NO |  |
| start_date | date | NO |  |
| start_at | timestamp with time zone | YES |  |
| time_known | boolean | NO |  |
| end_at | timestamp with time zone | YES |  |
| end_basis | character varying | NO |  |
| end_note | character varying | NO |  |
| multi_day | boolean | NO |  |
| venue_id | character varying | NO |  |
| venue_name | character varying | NO |  |
| address | character varying | NO |  |
| city | character varying | NO |  |
| postal_code | character varying | NO |  |
| lat | double precision | YES |  |
| lon | double precision | YES |  |
| region | character varying | YES |  |
| hidden_reason | character varying | NO |  |
| raw | jsonb | NO |  |
| first_seen_at | timestamp with time zone | NO |  |
| last_seen_at | timestamp with time zone | NO |  |
| missing_since | timestamp with time zone | YES |  |
| attendance | integer | YES |  |
| local_rank | smallint | YES |  |
| rank | smallint | YES |  |

## ferry_arrivals  (274 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| mmsi | bigint | NO |  |
| ship_name | character varying | NO |  |
| ship_type | smallint | YES |  |
| length_m | smallint | YES |  |
| destination | character varying | NO |  |
| port_name | character varying | NO |  |
| latitude | double precision | YES |  |
| longitude | double precision | YES |  |
| speed_knots | double precision | YES |  |
| nav_status | smallint | YES |  |
| eta | timestamp with time zone | YES |  |
| timestamp | timestamp with time zone | YES |  |
| was_underway | boolean | NO |  |
| is_processed | boolean | NO |  |
| triggered_at | timestamp with time zone | YES |  |
| updated_at | timestamp with time zone | NO |  |

## ferry_calls  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| call_id | character varying | NO |  |
| mmsi | bigint | NO |  |
| ship_name | character varying | NO |  |
| terminal | character varying | NO |  |
| started_at | timestamp with time zone | NO |  |
| berth_eta | timestamp with time zone | YES |  |
| eta_basis | character varying | NO |  |
| distance_km | double precision | YES |  |
| first_estimate_at | timestamp with time zone | YES |  |
| first_berth_eta | timestamp with time zone | YES |  |
| estimates | jsonb | NO |  |
| arrived_at | timestamp with time zone | YES |  |
| tip_external_id | character varying | NO |  |
| updated_at | timestamp with time zone | NO |  |

## ferry_timetable_calls  (12621 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| service_date | date | NO |  |
| trip_id | character varying | NO |  |
| agency | character varying | NO |  |
| route_name | character varying | NO |  |
| stop_id | character varying | NO |  |
| stop_name | character varying | NO |  |
| lat | double precision | NO |  |
| lon | double precision | NO |  |
| sequence | integer | NO |  |
| arrival_at | timestamp with time zone | YES |  |
| departure_at | timestamp with time zone | YES |  |
| origin_name | character varying | NO |  |
| destination_name | character varying | NO |  |
| imported_at | timestamp with time zone | NO |  |
| stop_has_road | boolean | NO |  |

## fleet_account_block  (2 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| kind | character varying | NO |  |
| value | character varying | NO |  |
| reason | text | NO |  |
| created_by | uuid | YES |  |
| created_at | timestamp with time zone | NO |  |
| lifted_at | timestamp with time zone | YES |  |
| lifted_by | uuid | YES |  |
| lift_note | text | NO |  |

## fleet_audit_event  (166 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | YES |  |
| actor_user_id | uuid | YES |  |
| actor_kind | character varying | NO |  |
| action | character varying | NO |  |
| subject_type | character varying | NO |  |
| subject_id | character varying | NO |  |
| detail | jsonb | NO |  |
| created_at | timestamp with time zone | NO |  |

## fleet_change_review  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| kind | character varying | NO |  |
| status | character varying | NO |  |
| customer_message | text | NO |  |
| detail | jsonb | NO |  |
| created_at | timestamp with time zone | NO |  |
| resolved_at | timestamp with time zone | YES |  |
| resolved_by | uuid | YES |  |
| resolution_note | text | NO |  |
| license_id | uuid | YES |  |
| vehicle_id | uuid | YES |  |

## fleet_company_profile  (15 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| company_id | uuid | NO |  |
| country | character varying | NO |  |
| org_number | character varying | NO |  |
| legal_name | text | NO |  |
| contact_name | text | NO |  |
| contact_role | text | NO |  |
| contact_email | text | NO |  |
| contact_phone | text | NO |  |
| email_verified_at | timestamp with time zone | YES |  |
| phone_verified_at | timestamp with time zone | YES |  |
| payment_method_verified_at | timestamp with time zone | YES |  |
| verification_status | character varying | NO |  |
| verification_note | text | NO |  |
| billing_email | text | NO |  |
| billing_reference | text | NO |  |
| billing_address | jsonb | NO |  |
| terms_version | character varying | NO |  |
| terms_accepted_at | timestamp with time zone | YES |  |
| terms_accepted_by | uuid | YES |  |
| legacy_access_until | timestamp with time zone | YES |  |
| legacy_counties | jsonb | NO |  |
| created_at | timestamp with time zone | NO |  |
| updated_at | timestamp with time zone | NO |  |

## fleet_coupon  (5 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| code | character varying | NO |  |
| description | text | NO |  |
| days | integer | NO |  |
| vehicle_limit | integer | NO |  |
| max_redemptions | integer | YES |  |
| redemption_count | integer | NO |  |
| valid_until | timestamp with time zone | YES |  |
| is_active | boolean | NO |  |
| created_by | uuid | YES |  |
| created_at | timestamp with time zone | NO |  |
| deactivated_at | timestamp with time zone | YES |  |

## fleet_coupon_redemption  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| effect | character varying | NO |  |
| days | integer | NO |  |
| detail | jsonb | NO |  |
| redeemed_by | uuid | YES |  |
| created_at | timestamp with time zone | NO |  |
| coupon_id | uuid | NO |  |
| trial_id | uuid | YES |  |

## fleet_device_approval  (5 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| device_id | uuid | NO |  |
| status | character varying | NO |  |
| label | text | NO |  |
| approved_at | timestamp with time zone | NO |  |
| approved_by | uuid | YES |  |
| revoked_at | timestamp with time zone | YES |  |
| revoked_by | uuid | YES |  |
| revoke_reason | text | NO |  |
| license_id | uuid | NO |  |
| vehicle_id | uuid | NO |  |

## fleet_device_credential  (5 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| device_id | uuid | NO |  |
| company_id | uuid | NO |  |
| token_hash | character varying | NO |  |
| prefix | character varying | NO |  |
| scheme | character varying | NO |  |
| created_at | timestamp with time zone | NO |  |
| last_used_at | timestamp with time zone | YES |  |
| revoked_at | timestamp with time zone | YES |  |
| revoke_reason | text | NO |  |
| approval_id | uuid | YES |  |

## fleet_join_request  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| label | text | NO |  |
| installation_hash | character varying | NO |  |
| status | character varying | NO |  |
| created_at | timestamp with time zone | NO |  |
| expires_at | timestamp with time zone | NO |  |
| resolved_at | timestamp with time zone | YES |  |
| resolved_by | uuid | YES |  |

## fleet_known_account  (9 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| user_id | uuid | NO |  |
| email | text | NO |  |
| first_seen_at | timestamp with time zone | NO |  |
| last_seen_at | timestamp with time zone | NO |  |

## fleet_license  (19 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| status | character varying | NO |  |
| base_county | character varying | NO |  |
| scheduled_base_county | character varying | NO |  |
| created_at | timestamp with time zone | NO |  |
| canceled_at | timestamp with time zone | YES |  |
| ends_at | timestamp with time zone | YES |  |
| trial_id | uuid | YES |  |

## fleet_license_county  (31 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| county_code | character varying | NO |  |
| kind | character varying | NO |  |
| active_from | timestamp with time zone | NO |  |
| active_to | timestamp with time zone | YES |  |
| created_at | timestamp with time zone | NO |  |
| license_id | uuid | NO |  |
| order_id | uuid | YES |  |

## fleet_order  (5 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| kind | character varying | NO |  |
| status | character varying | NO |  |
| quantity_before | integer | NO |  |
| quantity_after | integer | NO |  |
| amount_now_ore | integer | NO |  |
| vat_now_ore | integer | NO |  |
| total_now_ore | integer | NO |  |
| next_period_amount_ore | integer | NO |  |
| next_period_vat_ore | integer | NO |  |
| next_period_total_ore | integer | NO |  |
| currency | character varying | NO |  |
| effective_at | timestamp with time zone | YES |  |
| lines | jsonb | NO |  |
| request | jsonb | NO |  |
| terms_version | character varying | NO |  |
| created_by | uuid | YES |  |
| created_at | timestamp with time zone | NO |  |
| idempotency_key | character varying | YES |  |
| stripe_invoice_id | text | NO |  |
| stripe_payment_intent_id | text | NO |  |
| stripe_checkout_session_id | text | NO |  |
| paid_at | timestamp with time zone | YES |  |
| failed_at | timestamp with time zone | YES |  |
| failure_reason | text | NO |  |
| price_version_id | character varying | NO |  |
| stripe_payment_url | text | NO |  |

## fleet_outbox_message  (5 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | YES |  |
| category | character varying | NO |  |
| channel | character varying | NO |  |
| to_address | text | NO |  |
| subject | text | NO |  |
| body | text | NO |  |
| payload | jsonb | NO |  |
| dedupe_key | character varying | NO |  |
| status | character varying | NO |  |
| created_at | timestamp with time zone | NO |  |
| sent_at | timestamp with time zone | YES |  |
| error | text | NO |  |

## fleet_owner_invite  (5 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| email | text | NO |  |
| role | character varying | NO |  |
| status | character varying | NO |  |
| created_by | uuid | YES |  |
| created_at | timestamp with time zone | NO |  |
| expires_at | timestamp with time zone | NO |  |
| consumed_at | timestamp with time zone | YES |  |
| consumed_by_user | uuid | YES |  |

## fleet_ownership_transfer  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| from_user_id | uuid | NO |  |
| to_user_id | uuid | NO |  |
| status | character varying | NO |  |
| created_at | timestamp with time zone | NO |  |
| expires_at | timestamp with time zone | NO |  |
| resolved_at | timestamp with time zone | YES |  |

## fleet_pairing_code  (10 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| code_hash | character varying | NO |  |
| label | text | NO |  |
| status | character varying | NO |  |
| attempts | integer | NO |  |
| max_attempts | integer | NO |  |
| created_by | uuid | YES |  |
| created_at | timestamp with time zone | NO |  |
| expires_at | timestamp with time zone | NO |  |
| consumed_at | timestamp with time zone | YES |  |
| consumed_by_device | uuid | YES |  |
| license_id | uuid | NO |  |
| vehicle_id | uuid | NO |  |

## fleet_pending_change  (5 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| kind | character varying | NO |  |
| status | character varying | NO |  |
| payload | jsonb | NO |  |
| effective_at | timestamp with time zone | NO |  |
| created_by | uuid | YES |  |
| created_at | timestamp with time zone | NO |  |
| applied_at | timestamp with time zone | YES |  |
| canceled_at | timestamp with time zone | YES |  |
| order_id | uuid | YES |  |

## fleet_price_version  (1 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | character varying | NO |  |
| label | text | NO |  |
| currency | character varying | NO |  |
| vat_rate_bp | integer | NO |  |
| base_price_ore | integer | NO |  |
| volume_price_ore | integer | NO |  |
| volume_threshold | integer | NO |  |
| extra_county_price_ore | integer | NO |  |
| intro_price_ore | integer | NO |  |
| intro_months | integer | NO |  |
| intro_enabled | boolean | NO |  |
| launch_date | date | YES |  |
| intro_signup_window_days | integer | NO |  |
| terms_version | character varying | NO |  |
| is_default | boolean | NO |  |
| active_from | timestamp with time zone | NO |  |
| created_at | timestamp with time zone | NO |  |

## fleet_risk_config  (1 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | integer | NO |  |
| new_pairings_per_vehicle_24h | integer | NO |  |
| takeovers_per_hour | integer | NO |  |
| vehicle_changes_per_30d | integer | NO |  |
| pairing_code_ttl_seconds | integer | NO |  |
| updated_at | timestamp with time zone | NO |  |

## fleet_risk_signal  (6 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| kind | character varying | NO |  |
| device_id | uuid | YES |  |
| case_ref | uuid | YES |  |
| created_at | timestamp with time zone | NO |  |
| license_id | uuid | YES |  |
| vehicle_id | uuid | YES |  |

## fleet_sales_invite  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| code_hash | character varying | NO |  |
| created_by | uuid | NO |  |
| country | character varying | NO |  |
| org_number | character varying | NO |  |
| company_name | text | NO |  |
| contact_name | text | NO |  |
| contact_email | text | NO |  |
| contact_phone | text | NO |  |
| verification_note | text | NO |  |
| status | character varying | NO |  |
| expires_at | timestamp with time zone | NO |  |
| consumed_at | timestamp with time zone | YES |  |
| consumed_by_company | uuid | YES |  |
| created_at | timestamp with time zone | NO |  |

## fleet_staff_role  (2 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| user_id | uuid | NO |  |
| role | character varying | NO |  |
| is_active | boolean | NO |  |
| note | text | NO |  |
| created_at | timestamp with time zone | NO |  |

## fleet_subscription  (16 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| status | character varying | NO |  |
| stripe_customer_id | text | NO |  |
| stripe_subscription_id | text | NO |  |
| current_period_start | timestamp with time zone | YES |  |
| current_period_end | timestamp with time zone | YES |  |
| cancel_at_period_end | boolean | NO |  |
| canceled_at | timestamp with time zone | YES |  |
| access_until | timestamp with time zone | YES |  |
| grace_until | timestamp with time zone | YES |  |
| grace_origin | timestamp with time zone | YES |  |
| had_successful_payment | boolean | NO |  |
| renewal_stopped_at | timestamp with time zone | YES |  |
| intro_started_at | timestamp with time zone | YES |  |
| intro_ends_at | timestamp with time zone | YES |  |
| intro_months_used | integer | NO |  |
| last_stripe_event_at | timestamp with time zone | YES |  |
| created_at | timestamp with time zone | NO |  |
| updated_at | timestamp with time zone | NO |  |
| price_version_id | character varying | NO |  |

## fleet_trial  (14 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| org_key | character varying | NO |  |
| source | character varying | NO |  |
| requires_payment_method | boolean | NO |  |
| status | character varying | NO |  |
| vehicle_limit | integer | NO |  |
| started_at | timestamp with time zone | YES |  |
| ends_at | timestamp with time zone | YES |  |
| ended_reason | text | NO |  |
| created_at | timestamp with time zone | NO |  |
| invite_id | uuid | YES |  |

## fleet_vehicle  (19 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| plate | character varying | NO |  |
| label | text | NO |  |
| status | character varying | NO |  |
| created_at | timestamp with time zone | NO |  |
| archived_at | timestamp with time zone | YES |  |

## fleet_vehicle_assignment  (19 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| kind | character varying | NO |  |
| case_ref | uuid | NO |  |
| started_at | timestamp with time zone | NO |  |
| planned_end | timestamp with time zone | YES |  |
| ended_at | timestamp with time zone | YES |  |
| ended_reason | text | NO |  |
| created_by | uuid | YES |  |
| license_id | uuid | NO |  |
| vehicle_id | uuid | NO |  |

## fleet_vehicle_session  (2 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| company_id | uuid | NO |  |
| device_id | uuid | NO |  |
| started_at | timestamp with time zone | NO |  |
| last_seen_at | timestamp with time zone | NO |  |
| ended_at | timestamp with time zone | YES |  |
| ended_reason | character varying | NO |  |
| ended_by_device | uuid | YES |  |
| approval_id | uuid | NO |  |
| license_id | uuid | NO |  |
| vehicle_id | uuid | NO |  |

## gtfs_feed_versions  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO | gen_random_uuid() |
| operator | text | NO |  |
| fetched_at | timestamp with time zone | NO | now() |
| is_current | boolean | NO | false |
| stop_count | integer | YES |  |
| trip_count | integer | YES |  |
| stop_time_count | integer | YES |  |
| created_at | timestamp with time zone | NO | now() |
| source_etag | text | YES |  |
| source_last_modified | text | YES |  |

## gtfs_service_exceptions  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| feed_version_id | uuid | NO |  |
| service_id | text | NO |  |
| exception_date | date | NO |  |
| exception_type | smallint | NO |  |

## gtfs_stop_departures  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| feed_version_id | uuid | NO |  |
| operator | text | NO |  |
| stop_id | text | NO |  |
| trip_id | text | NO |  |
| route_id | text | YES |  |
| route_type | integer | YES |  |
| service_id | text | NO |  |
| departure_seconds | integer | NO |  |
| stop_sequence | integer | YES |  |
| days_of_week | smallint | NO | 0 |
| start_date | date | YES |  |
| end_date | date | YES |  |

## gtfs_stops  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| feed_version_id | uuid | NO |  |
| stop_id | text | NO |  |
| stop_code | text | YES |  |
| stop_name | text | YES |  |
| parent_station | text | YES |  |

## opportunities  (21943 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| external_id | text | NO |  |
| kind | character varying | NO |  |
| mode | character varying | NO |  |
| severity_tier | character varying | NO |  |
| level | character varying | NO |  |
| title | text | NO |  |
| summary | text | NO |  |
| lat | double precision | YES |  |
| lon | double precision | YES |  |
| h3_index | character varying | NO |  |
| places | jsonb | NO |  |
| region | character varying | YES |  |
| start_time | timestamp with time zone | YES |  |
| end_time | timestamp with time zone | YES |  |
| demand_score | integer | NO |  |
| confidence | character varying | NO |  |
| reasons | jsonb | NO |  |
| rule_id | character varying | NO |  |
| source_event_ids | jsonb | NO |  |
| computed_at | timestamp with time zone | NO | statement_timestamp() |
| updated_at | timestamp with time zone | NO | statement_timestamp() |
| expired_reason | character varying | YES |  |
| notified_at | timestamp with time zone | YES |  |
| compensation_amount_kr | integer | YES |  |
| compensation_eligible | boolean | NO |  |
| is_last_departure | boolean | NO |  |
| next_departure_minutes | integer | YES |  |
| alternative_note | text | NO |  |
| has_alternative | boolean | NO |  |
| next_departure_at | timestamp with time zone | YES |  |
| compensation_per_person | boolean | YES |  |
| county_code | character varying | YES |  |
| area_codes | jsonb | NO |  |
| ai_adjusted_at | timestamp with time zone | YES |  |
| municipality_code | character varying | YES |  |

## opportunity_combinations  (2 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| rule_id | character varying | NO |  |
| effect | character varying | NO |  |
| primary_external_id | text | NO |  |
| member_external_ids | jsonb | NO |  |
| boost | integer | NO |  |
| reason | text | NO |  |
| computed_at | timestamp with time zone | NO |  |
| expires_at | timestamp with time zone | NO |  |

## opportunity_favorite  (1 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| owner_key | text | NO |  |
| opportunity_external_id | text | NO |  |
| snapshot | jsonb | NO |  |
| note | text | NO |  |
| created_at | timestamp with time zone | NO | statement_timestamp() |
| opportunity_id | uuid | YES |  |

## opportunity_feedback  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| device_token | text | NO |  |
| verdict | character varying | NO |  |
| created_at | timestamp with time zone | NO | statement_timestamp() |
| opportunity_id | uuid | NO |  |

## processed_webhook_events  (3 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| stripe_event_id | text | NO |  |
| event_type | text | NO |  |
| processed_at | timestamp with time zone | NO | now() |
| status | text | NO |  |
| error | text | YES |  |

## profiles  (20 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| name | text | YES |  |
| is_platform_owner | boolean | YES |  |
| created_at | timestamp with time zone | YES |  |

## push_delivery  (27 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| opportunity_external_id | text | NO |  |
| device_id | uuid | NO |  |
| device_token | text | NO |  |
| title | text | NO |  |
| body | text | NO |  |
| snapshot | jsonb | NO |  |
| ok | boolean | NO |  |
| error | text | NO |  |
| created_at | timestamp with time zone | NO | statement_timestamp() |
| opportunity_id | uuid | YES |  |
| status | character varying | NO |  |
| attempts | integer | NO |  |
| next_attempt_at | timestamp with time zone | YES |  |
| expires_at | timestamp with time zone | YES |  |
| sent_at | timestamp with time zone | YES |  |

## rail_assessment  (63 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| cache_key | character varying | NO |  |
| rule_score | integer | NO |  |
| model_score | integer | NO |  |
| final_score | integer | NO |  |
| verdict | text | NO |  |
| model_name | character varying | NO |  |
| created_at | timestamp with time zone | NO |  |
| opportunity_id | uuid | NO |  |

## rail_station  (718 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| signature | character varying | NO |  |
| name | character varying | NO |  |
| lat | double precision | YES |  |
| lon | double precision | YES |  |
| fetched_at | timestamp with time zone | NO |  |

## region_compensation_rule  (16 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| region | character varying | NO |  |
| threshold_minutes | integer | NO |  |
| taxi_cap_kr | integer | NO |  |
| excluded_modes | jsonb | NO |  |
| filing_deadline_days | integer | NO |  |
| source_url | text | NO |  |
| note | text | NO |  |
| updated_at | timestamp with time zone | NO |  |
| cap_per_person | boolean | YES |  |

## scoring_rule  (9 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| tier | character varying | NO |  |
| mode | character varying | NO |  |
| condition | character varying | NO |  |
| floor | integer | YES |  |
| cap | integer | YES |  |
| confidence | character varying | NO |  |
| note | text | NO |  |
| updated_at | timestamp with time zone | NO |  |

## sl_sites  (6935 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| stop_area_id | text | NO |  |
| site_id | text | NO |  |
| name | text | YES |  |
| lat | double precision | NO |  |
| lon | double precision | NO |  |
| fetched_at | timestamp with time zone | NO | now() |

## source_events  (22133 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| source | character varying | NO |  |
| external_id | text | NO |  |
| mode | character varying | NO |  |
| fetched_at | timestamp with time zone | NO | statement_timestamp() |
| active_from | timestamp with time zone | YES |  |
| active_to | timestamp with time zone | YES |  |
| raw | jsonb | NO |  |
| lat | double precision | YES |  |
| lon | double precision | YES |  |
| created_at | timestamp with time zone | NO | statement_timestamp() |

## source_status  (15 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| source | character varying | NO |  |
| ok | boolean | NO |  |
| message | text | NO |  |
| events | integer | NO |  |
| written | integer | NO |  |
| duration_ms | integer | NO |  |
| checked_at | timestamp with time zone | NO |  |
| detail | jsonb | NO |  |
| last_success_at | timestamp with time zone | YES |  |
| consecutive_failures | integer | NO |  |

## stop_area  (18125 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| gid | character varying | NO |  |
| operator | character varying | NO |  |
| name | character varying | NO |  |
| lat | double precision | NO |  |
| lon | double precision | NO |  |
| fetched_at | timestamp with time zone | NO |  |
| site_id | character varying | NO |  |

## vt_stop_areas  (11181 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| gid | text | NO |  |
| name | text | YES |  |
| lat | double precision | NO |  |
| lon | double precision | NO |  |
| fetched_at | timestamp with time zone | NO | now() |
