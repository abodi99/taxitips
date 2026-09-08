# Spegling av databasen som den ser ut nu, via `manage.py inspectdb`.
# Genererad av `manage.py dump_truth`. Redigera inte för hand.
# Appens egna modeller finns i core/models.py.

# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class AlertFeedback(models.Model):
    id = models.UUIDField(primary_key=True)
    alert = models.ForeignKey('Alerts', models.DB_CASCADE, blank=True, null=True)
    device_token = models.TextField(blank=True, null=True)
    result = models.BooleanField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'alert_feedback'


class Alerts(models.Model):
    id = models.UUIDField(primary_key=True)
    kind = models.TextField(blank=True, null=True)
    level = models.TextField(blank=True, null=True)
    title = models.TextField(blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    lat = models.FloatField(blank=True, null=True)
    lon = models.FloatField(blank=True, null=True)
    places = models.JSONField(blank=True, null=True)
    payload = models.JSONField(blank=True, null=True)
    updated_at = models.DateTimeField()
    h3_index = models.TextField(blank=True, null=True)
    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)
    demand_score = models.IntegerField(blank=True, null=True)
    reasons = models.TextField(blank=True, null=True)  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'alerts'


class AuthGroup(models.Model):
    name = models.CharField(unique=True, max_length=150)

    class Meta:
        managed = False
        db_table = 'auth_group'


class AuthGroupPermissions(models.Model):
    id = models.BigAutoField(primary_key=True)
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)
    permission = models.ForeignKey('AuthPermission', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_group_permissions'
        unique_together = (('group', 'permission'),)


class AuthPermission(models.Model):
    name = models.CharField(max_length=255)
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING)
    codename = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'auth_permission'
        unique_together = (('content_type', 'codename'),)


class AuthUser(models.Model):
    password = models.CharField(max_length=128)
    last_login = models.DateTimeField(blank=True, null=True)
    is_superuser = models.BooleanField()
    username = models.CharField(unique=True, max_length=150)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.CharField(max_length=254)
    is_staff = models.BooleanField()
    is_active = models.BooleanField()
    date_joined = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'auth_user'


class AuthUserGroups(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_groups'
        unique_together = (('user', 'group'),)


class AuthUserUserPermissions(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    permission = models.ForeignKey(AuthPermission, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_user_permissions'
        unique_together = (('user', 'permission'),)


class Companies(models.Model):
    id = models.UUIDField(primary_key=True)
    name = models.TextField()
    email = models.TextField(blank=True, null=True)
    org_number = models.TextField(blank=True, null=True)
    join_code = models.TextField(unique=True)
    seats = models.IntegerField()
    status = models.TextField()
    watched_areas = models.TextField()  # This field type is a guess.
    created_at = models.DateTimeField()
    stripe_customer_id = models.TextField(blank=True, null=True)
    stripe_subscription_id = models.TextField(blank=True, null=True)
    subscription_status = models.TextField()

    class Meta:
        managed = False
        db_table = 'companies'


class CompanyMembers(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    user_id = models.UUIDField()
    role = models.TextField(blank=True, null=True)
    status = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'company_members'
        unique_together = (('company_id', 'user_id'),)


class DeviceTransferCodes(models.Model):
    code = models.TextField(primary_key=True)
    device_id = models.UUIDField()
    expires_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'device_transfer_codes'


class Devices(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    token = models.TextField(unique=True)
    label = models.TextField()
    kind = models.TextField()
    push_token = models.TextField(blank=True, null=True)
    notify_prefs = models.JSONField()
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'devices'


class DjangoAdminLog(models.Model):
    action_time = models.DateTimeField()
    object_id = models.TextField(blank=True, null=True)
    object_repr = models.CharField(max_length=200)
    action_flag = models.SmallIntegerField()
    change_message = models.TextField()
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'django_admin_log'


class DjangoContentType(models.Model):
    app_label = models.CharField(max_length=100)
    model = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'django_content_type'
        unique_together = (('app_label', 'model'),)


class DjangoMigrations(models.Model):
    id = models.BigAutoField(primary_key=True)
    app = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    applied = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_migrations'


class DjangoSession(models.Model):
    session_key = models.CharField(primary_key=True, max_length=40)
    session_data = models.TextField()
    expire_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_session'


class GtfsFeedVersions(models.Model):
    id = models.UUIDField(primary_key=True)
    operator = models.TextField(unique=True)
    fetched_at = models.DateTimeField()
    is_current = models.BooleanField()
    stop_count = models.IntegerField(blank=True, null=True)
    trip_count = models.IntegerField(blank=True, null=True)
    stop_time_count = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    source_etag = models.TextField(blank=True, null=True)
    source_last_modified = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'gtfs_feed_versions'


class GtfsServiceExceptions(models.Model):
    id = models.BigAutoField(primary_key=True)
    feed_version = models.ForeignKey(GtfsFeedVersions, models.DB_CASCADE)
    service_id = models.TextField()
    exception_date = models.DateField()
    exception_type = models.SmallIntegerField()

    class Meta:
        managed = False
        db_table = 'gtfs_service_exceptions'


class GtfsStopDepartures(models.Model):
    id = models.BigAutoField(primary_key=True)
    feed_version = models.ForeignKey(GtfsFeedVersions, models.DB_CASCADE)
    operator = models.TextField()
    stop_id = models.TextField()
    trip_id = models.TextField()
    route_id = models.TextField(blank=True, null=True)
    route_type = models.IntegerField(blank=True, null=True)
    service_id = models.TextField()
    departure_seconds = models.IntegerField()
    stop_sequence = models.IntegerField(blank=True, null=True)
    days_of_week = models.SmallIntegerField()
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'gtfs_stop_departures'


class GtfsStops(models.Model):
    id = models.BigAutoField(primary_key=True)
    feed_version = models.ForeignKey(GtfsFeedVersions, models.DB_CASCADE)
    stop_id = models.TextField()
    stop_code = models.TextField(blank=True, null=True)
    stop_name = models.TextField(blank=True, null=True)
    parent_station = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'gtfs_stops'


class Opportunities(models.Model):
    id = models.UUIDField(primary_key=True)
    external_id = models.TextField(unique=True)
    kind = models.CharField(max_length=20)
    mode = models.CharField(max_length=20)
    severity_tier = models.CharField(max_length=40)
    level = models.CharField(max_length=20)
    title = models.TextField()
    summary = models.TextField()
    lat = models.FloatField(blank=True, null=True)
    lon = models.FloatField(blank=True, null=True)
    h3_index = models.CharField(max_length=20)
    places = models.JSONField()
    region = models.CharField(max_length=30, blank=True, null=True)
    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)
    demand_score = models.IntegerField()
    confidence = models.CharField(max_length=10)
    reasons = models.JSONField()
    rule_id = models.CharField(max_length=80)
    source_event_ids = models.JSONField()
    computed_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    expired_reason = models.CharField(max_length=60, blank=True, null=True)
    notified_at = models.DateTimeField(blank=True, null=True)
    compensation_amount_kr = models.IntegerField(blank=True, null=True)
    compensation_eligible = models.BooleanField()
    is_last_departure = models.BooleanField()
    next_departure_minutes = models.IntegerField(blank=True, null=True)
    alternative_note = models.TextField()
    has_alternative = models.BooleanField()
    next_departure_at = models.DateTimeField(blank=True, null=True)
    compensation_per_person = models.BooleanField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'opportunities'


class OpportunityFeedback(models.Model):
    id = models.UUIDField(primary_key=True)
    device_token = models.TextField()
    verdict = models.CharField(max_length=10)
    created_at = models.DateTimeField()
    opportunity = models.ForeignKey(Opportunities, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'opportunity_feedback'
        unique_together = (('opportunity', 'device_token', 'verdict'),)


class ProcessedWebhookEvents(models.Model):
    stripe_event_id = models.TextField(primary_key=True)
    event_type = models.TextField()
    processed_at = models.DateTimeField()
    status = models.TextField()
    error = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'processed_webhook_events'


class Profiles(models.Model):
    id = models.UUIDField(primary_key=True)
    name = models.TextField(blank=True, null=True)
    is_platform_owner = models.BooleanField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'profiles'


class RailAssessment(models.Model):
    id = models.BigAutoField(primary_key=True)
    cache_key = models.CharField(max_length=200)
    rule_score = models.IntegerField()
    model_score = models.IntegerField()
    final_score = models.IntegerField()
    verdict = models.TextField()
    model_name = models.CharField(max_length=60)
    created_at = models.DateTimeField()
    opportunity = models.ForeignKey(Opportunities, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'rail_assessment'


class RailStation(models.Model):
    signature = models.CharField(primary_key=True, max_length=12)
    name = models.CharField(max_length=120)
    lat = models.FloatField(blank=True, null=True)
    lon = models.FloatField(blank=True, null=True)
    fetched_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'rail_station'


class RegionCompensationRule(models.Model):
    id = models.BigAutoField(primary_key=True)
    region = models.CharField(unique=True, max_length=30)
    threshold_minutes = models.IntegerField()
    taxi_cap_kr = models.IntegerField()
    excluded_modes = models.JSONField()
    filing_deadline_days = models.IntegerField()
    source_url = models.TextField()
    note = models.TextField()
    updated_at = models.DateTimeField()
    cap_per_person = models.BooleanField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'region_compensation_rule'


class ScoringRule(models.Model):
    id = models.BigAutoField(primary_key=True)
    tier = models.CharField(max_length=40)
    mode = models.CharField(max_length=20)
    condition = models.CharField(max_length=80)
    floor = models.IntegerField(blank=True, null=True)
    cap = models.IntegerField(blank=True, null=True)
    confidence = models.CharField(max_length=10)
    note = models.TextField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'scoring_rule'
        unique_together = (('tier', 'mode', 'condition'),)


class SlSites(models.Model):
    stop_area_id = models.TextField(primary_key=True)
    site_id = models.TextField()
    name = models.TextField(blank=True, null=True)
    lat = models.FloatField()
    lon = models.FloatField()
    fetched_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'sl_sites'


class SourceEvents(models.Model):
    id = models.UUIDField(primary_key=True)
    source = models.CharField(max_length=40)
    external_id = models.TextField(unique=True)
    mode = models.CharField(max_length=20)
    fetched_at = models.DateTimeField()
    active_from = models.DateTimeField(blank=True, null=True)
    active_to = models.DateTimeField(blank=True, null=True)
    raw = models.JSONField()
    lat = models.FloatField(blank=True, null=True)
    lon = models.FloatField(blank=True, null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'source_events'


class SourceStatus(models.Model):
    source = models.CharField(primary_key=True, max_length=40)
    ok = models.BooleanField()
    message = models.TextField()
    events = models.IntegerField()
    written = models.IntegerField()
    duration_ms = models.IntegerField()
    checked_at = models.DateTimeField()
    detail = models.JSONField()

    class Meta:
        managed = False
        db_table = 'source_status'


class StopArea(models.Model):
    gid = models.CharField(primary_key=True, max_length=40)
    operator = models.CharField(max_length=4)
    name = models.CharField(max_length=160)
    lat = models.FloatField()
    lon = models.FloatField()
    fetched_at = models.DateTimeField()
    site_id = models.CharField(max_length=20)

    class Meta:
        managed = False
        db_table = 'stop_area'


class VtStopAreas(models.Model):
    gid = models.TextField(primary_key=True)
    name = models.TextField(blank=True, null=True)
    lat = models.FloatField()
    lon = models.FloatField()
    fetched_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'vt_stop_areas'
