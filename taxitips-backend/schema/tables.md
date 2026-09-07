# Tabeller i public

Genererad av `manage.py dump_truth`. Redigera inte för hand.

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

## auth_permission  (48 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | integer | NO |  |
| name | character varying | NO |  |
| content_type_id | integer | NO |  |
| codename | character varying | NO |  |

## auth_user  (1 rader)

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

## django_content_type  (12 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | integer | NO |  |
| app_label | character varying | NO |  |
| model | character varying | NO |  |

## django_migrations  (21 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| id | bigint | NO |  |
| app | character varying | NO |  |
| name | character varying | NO |  |
| applied | timestamp with time zone | NO |  |

## django_session  (1 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| session_key | character varying | NO |  |
| session_data | text | NO |  |
| expire_date | timestamp with time zone | NO |  |

## opportunities  (15 rader)

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
| region | character varying | NO |  |
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

## rail_assessment  (0 rader)

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

## rail_station  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| signature | character varying | NO |  |
| name | character varying | NO |  |
| lat | double precision | YES |  |
| lon | double precision | YES |  |
| fetched_at | timestamp with time zone | NO |  |

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

## source_events  (15 rader)

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

## stop_area  (0 rader)

| kolumn | typ | null | default |
|---|---|---|---|
| gid | character varying | NO |  |
| operator | character varying | NO |  |
| name | character varying | NO |  |
| lat | double precision | NO |  |
| lon | double precision | NO |  |
| fetched_at | timestamp with time zone | NO |  |
