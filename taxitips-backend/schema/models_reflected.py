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
    region = models.CharField(max_length=30)
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

    class Meta:
        managed = False
        db_table = 'opportunities'


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


class StopArea(models.Model):
    gid = models.CharField(primary_key=True, max_length=40)
    operator = models.CharField(max_length=4)
    name = models.CharField(max_length=160)
    lat = models.FloatField()
    lon = models.FloatField()
    fetched_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'stop_area'
