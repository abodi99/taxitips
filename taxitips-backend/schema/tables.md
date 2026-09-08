# Tabeller i public

Genererad av `manage.py dump_truth`. Redigera inte för hand.

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

## auth_permission  (76 rader)

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

## companies  (1 rader)

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

## company_members  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO | gen_random_uuid() |
| company_id | uuid | NO |  |
| user_id | uuid | NO |  |
| role | text | YES |  |
| status | text | YES |  |
| created_at | timestamp with time zone | YES |  |

## device_transfer_codes  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| code | text | NO |  |
| device_id | uuid | NO |  |
| expires_at | timestamp with time zone | NO |  |

## devices  (3 rader)

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

## django_content_type  (19 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | integer | NO |  |
| app_label | character varying | NO |  |
| model | character varying | NO |  |

## django_migrations  (31 rader)

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

## opportunities  (4386 rader)

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

## opportunity_feedback  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| device_token | text | NO |  |
| verdict | character varying | NO |  |
| created_at | timestamp with time zone | NO | statement_timestamp() |
| opportunity_id | uuid | NO |  |

## processed_webhook_events  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| stripe_event_id | text | NO |  |
| event_type | text | NO |  |
| processed_at | timestamp with time zone | NO | now() |
| status | text | NO |  |
| error | text | YES |  |

## profiles  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | uuid | NO |  |
| name | text | YES |  |
| is_platform_owner | boolean | YES |  |
| created_at | timestamp with time zone | YES |  |

## rail_assessment  (18 rader)

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

## scoring_rule  (7 rader)

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

## source_events  (4401 rader)

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

## source_status  (6 rader)

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

## stop_area  (18117 rader)

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
