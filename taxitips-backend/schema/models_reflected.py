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


class AisVessels(models.Model):
    id = models.BigAutoField(primary_key=True)
    mmsi = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=100)
    call_sign = models.CharField(max_length=10)
    imo = models.IntegerField(blank=True, null=True)
    ship_type = models.SmallIntegerField(blank=True, null=True)
    ais_class = models.CharField(max_length=1)
    length_m = models.SmallIntegerField(blank=True, null=True)
    width_m = models.SmallIntegerField(blank=True, null=True)
    draught_m = models.FloatField(blank=True, null=True)
    destination = models.CharField(max_length=40)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    speed_knots = models.FloatField(blank=True, null=True)
    course = models.FloatField(blank=True, null=True)
    heading = models.SmallIntegerField(blank=True, null=True)
    nav_status = models.SmallIntegerField(blank=True, null=True)
    port_name = models.CharField(max_length=60)
    last_message_type = models.CharField(max_length=40)
    messages = models.IntegerField()
    position_at = models.DateTimeField(blank=True, null=True)
    static_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'ais_vessels'


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
    last_subscription_event_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'companies'


class CompanyMembers(models.Model):
    id = models.UUIDField(primary_key=True)
    company = models.ForeignKey(Companies, models.DB_CASCADE)
    user_id = models.UUIDField()
    role = models.TextField(blank=True, null=True)
    status = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'company_members'
        unique_together = (('company', 'user_id'),)


class DevicePresence(models.Model):
    device_id = models.UUIDField(primary_key=True)
    cell_lat = models.FloatField()
    cell_lon = models.FloatField()
    updated_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'device_presence'


class DeviceTransferCodes(models.Model):
    code = models.TextField(primary_key=True)
    device_id = models.UUIDField()
    expires_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'device_transfer_codes'
        db_table_comment = 'Utfasad. Byteskoden gav en ny enhetstoken utan att någon godkände telefonen för en bil. Ersatt av fleet_pairing_code och /api/fleet/pairing-codes.'


class Devices(models.Model):
    id = models.UUIDField(primary_key=True)
    company = models.ForeignKey(Companies, models.DB_CASCADE)
    token = models.TextField(unique=True)
    label = models.TextField()
    kind = models.TextField()
    push_token = models.TextField(blank=True, null=True)
    notify_prefs = models.JSONField()
    created_at = models.DateTimeField(blank=True, null=True)
    user_id = models.UUIDField(blank=True, null=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)

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


class Events(models.Model):
    id = models.BigAutoField(primary_key=True)
    source = models.CharField(max_length=30)
    external_id = models.CharField(max_length=120)
    name = models.CharField(max_length=300)
    url = models.CharField(max_length=500)
    source_status = models.CharField(max_length=30)
    category = models.CharField(max_length=20)
    segment = models.CharField(max_length=60)
    genre = models.CharField(max_length=60)
    sub_genre = models.CharField(max_length=60)
    start_date = models.DateField()
    start_at = models.DateTimeField(blank=True, null=True)
    time_known = models.BooleanField()
    end_at = models.DateTimeField(blank=True, null=True)
    end_basis = models.CharField(max_length=10)
    end_note = models.CharField(max_length=200)
    multi_day = models.BooleanField()
    venue_id = models.CharField(max_length=60)
    venue_name = models.CharField(max_length=200)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    lat = models.FloatField(blank=True, null=True)
    lon = models.FloatField(blank=True, null=True)
    region = models.CharField(max_length=30, blank=True, null=True)
    hidden_reason = models.CharField(max_length=200)
    raw = models.JSONField()
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    missing_since = models.DateTimeField(blank=True, null=True)
    attendance = models.IntegerField(blank=True, null=True)
    local_rank = models.SmallIntegerField(blank=True, null=True)
    rank = models.SmallIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'events'
        unique_together = (('source', 'external_id'),)


class FerryArrivals(models.Model):
    id = models.BigAutoField(primary_key=True)
    mmsi = models.BigIntegerField(unique=True)
    ship_name = models.CharField(max_length=100)
    ship_type = models.SmallIntegerField(blank=True, null=True)
    length_m = models.SmallIntegerField(blank=True, null=True)
    destination = models.CharField(max_length=40)
    port_name = models.CharField(max_length=60)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    speed_knots = models.FloatField(blank=True, null=True)
    nav_status = models.SmallIntegerField(blank=True, null=True)
    eta = models.DateTimeField(blank=True, null=True)
    timestamp = models.DateTimeField(blank=True, null=True)
    was_underway = models.BooleanField()
    is_processed = models.BooleanField()
    triggered_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'ferry_arrivals'


class FerryCalls(models.Model):
    id = models.BigAutoField(primary_key=True)
    call_id = models.CharField(unique=True, max_length=80)
    mmsi = models.BigIntegerField()
    ship_name = models.CharField(max_length=100)
    terminal = models.CharField(max_length=30)
    started_at = models.DateTimeField()
    berth_eta = models.DateTimeField(blank=True, null=True)
    eta_basis = models.CharField(max_length=10)
    distance_km = models.FloatField(blank=True, null=True)
    first_estimate_at = models.DateTimeField(blank=True, null=True)
    first_berth_eta = models.DateTimeField(blank=True, null=True)
    estimates = models.JSONField()
    arrived_at = models.DateTimeField(blank=True, null=True)
    tip_external_id = models.CharField(max_length=160)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'ferry_calls'


class FerryTimetableCalls(models.Model):
    id = models.BigAutoField(primary_key=True)
    service_date = models.DateField()
    trip_id = models.CharField(max_length=40)
    agency = models.CharField(max_length=100)
    route_name = models.CharField(max_length=100)
    stop_id = models.CharField(max_length=40)
    stop_name = models.CharField(max_length=120)
    lat = models.FloatField()
    lon = models.FloatField()
    sequence = models.IntegerField()
    arrival_at = models.DateTimeField(blank=True, null=True)
    departure_at = models.DateTimeField(blank=True, null=True)
    origin_name = models.CharField(max_length=120)
    destination_name = models.CharField(max_length=120)
    imported_at = models.DateTimeField()
    stop_has_road = models.BooleanField()

    class Meta:
        managed = False
        db_table = 'ferry_timetable_calls'


class FleetAccountBlock(models.Model):
    id = models.UUIDField(primary_key=True)
    kind = models.CharField(max_length=10)
    value = models.CharField(max_length=320)
    reason = models.TextField()
    created_by = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField()
    lifted_at = models.DateTimeField(blank=True, null=True)
    lifted_by = models.UUIDField(blank=True, null=True)
    lift_note = models.TextField()

    class Meta:
        managed = False
        db_table = 'fleet_account_block'
        unique_together = (('kind', 'value'),)


class FleetAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField(blank=True, null=True)
    actor_user_id = models.UUIDField(blank=True, null=True)
    actor_kind = models.CharField(max_length=24)
    action = models.CharField(max_length=64)
    subject_type = models.CharField(max_length=32)
    subject_id = models.CharField(max_length=64)
    detail = models.JSONField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'fleet_audit_event'


class FleetChangeReview(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    kind = models.CharField(max_length=24)
    status = models.CharField(max_length=16)
    customer_message = models.TextField()
    detail = models.JSONField()
    created_at = models.DateTimeField()
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolved_by = models.UUIDField(blank=True, null=True)
    resolution_note = models.TextField()
    license = models.ForeignKey('FleetLicense', models.DO_NOTHING, blank=True, null=True)
    vehicle = models.ForeignKey('FleetVehicle', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_change_review'


class FleetCompanyProfile(models.Model):
    company_id = models.UUIDField(primary_key=True)
    country = models.CharField(max_length=2)
    org_number = models.CharField(max_length=32)
    legal_name = models.TextField()
    contact_name = models.TextField()
    contact_role = models.TextField()
    contact_email = models.TextField()
    contact_phone = models.TextField()
    email_verified_at = models.DateTimeField(blank=True, null=True)
    phone_verified_at = models.DateTimeField(blank=True, null=True)
    payment_method_verified_at = models.DateTimeField(blank=True, null=True)
    verification_status = models.CharField(max_length=20)
    verification_note = models.TextField()
    billing_email = models.TextField()
    billing_reference = models.TextField()
    billing_address = models.JSONField()
    terms_version = models.CharField(max_length=32)
    terms_accepted_at = models.DateTimeField(blank=True, null=True)
    terms_accepted_by = models.UUIDField(blank=True, null=True)
    legacy_access_until = models.DateTimeField(blank=True, null=True)
    legacy_counties = models.JSONField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'fleet_company_profile'
        unique_together = (('country', 'org_number'),)


class FleetCoupon(models.Model):
    id = models.UUIDField(primary_key=True)
    code = models.CharField(unique=True, max_length=32)
    description = models.TextField()
    days = models.IntegerField()
    vehicle_limit = models.IntegerField()
    max_redemptions = models.IntegerField(blank=True, null=True)
    redemption_count = models.IntegerField()
    valid_until = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField()
    created_by = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField()
    deactivated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_coupon'


class FleetCouponRedemption(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    effect = models.CharField(max_length=20)
    days = models.IntegerField()
    detail = models.JSONField()
    redeemed_by = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField()
    coupon = models.ForeignKey(FleetCoupon, models.DO_NOTHING)
    trial = models.ForeignKey('FleetTrial', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_coupon_redemption'
        unique_together = (('coupon', 'company_id'),)


class FleetDeviceApproval(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    device_id = models.UUIDField()
    status = models.CharField(max_length=16)
    label = models.TextField()
    approved_at = models.DateTimeField()
    approved_by = models.UUIDField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    revoked_by = models.UUIDField(blank=True, null=True)
    revoke_reason = models.TextField()
    license = models.ForeignKey('FleetLicense', models.DO_NOTHING)
    vehicle = models.ForeignKey('FleetVehicle', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'fleet_device_approval'
        unique_together = (('device_id', 'license'),)


class FleetDeviceCredential(models.Model):
    id = models.UUIDField(primary_key=True)
    device_id = models.UUIDField()
    company_id = models.UUIDField()
    token_hash = models.CharField(unique=True, max_length=64)
    prefix = models.CharField(max_length=12)
    scheme = models.CharField(max_length=20)
    created_at = models.DateTimeField()
    last_used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    revoke_reason = models.TextField()
    approval = models.ForeignKey(FleetDeviceApproval, models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_device_credential'


class FleetJoinRequest(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    label = models.TextField()
    installation_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolved_by = models.UUIDField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_join_request'


class FleetKnownAccount(models.Model):
    user_id = models.UUIDField(primary_key=True)
    email = models.TextField()
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'fleet_known_account'


class FleetLicense(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    status = models.CharField(max_length=20)
    base_county = models.CharField(max_length=4)
    scheduled_base_county = models.CharField(max_length=4)
    created_at = models.DateTimeField()
    canceled_at = models.DateTimeField(blank=True, null=True)
    ends_at = models.DateTimeField(blank=True, null=True)
    trial = models.ForeignKey('FleetTrial', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_license'


class FleetLicenseCounty(models.Model):
    id = models.UUIDField(primary_key=True)
    county_code = models.CharField(max_length=4)
    kind = models.CharField(max_length=8)
    active_from = models.DateTimeField()
    active_to = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField()
    license = models.ForeignKey(FleetLicense, models.DO_NOTHING)
    order = models.ForeignKey('FleetOrder', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_license_county'
        unique_together = (('license', 'county_code'),)


class FleetOrder(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    kind = models.CharField(max_length=24)
    status = models.CharField(max_length=20)
    quantity_before = models.IntegerField()
    quantity_after = models.IntegerField()
    amount_now_ore = models.IntegerField()
    vat_now_ore = models.IntegerField()
    total_now_ore = models.IntegerField()
    next_period_amount_ore = models.IntegerField()
    next_period_vat_ore = models.IntegerField()
    next_period_total_ore = models.IntegerField()
    currency = models.CharField(max_length=3)
    effective_at = models.DateTimeField(blank=True, null=True)
    lines = models.JSONField()
    request = models.JSONField()
    terms_version = models.CharField(max_length=32)
    created_by = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField()
    idempotency_key = models.CharField(unique=True, max_length=64, blank=True, null=True)
    stripe_invoice_id = models.TextField()
    stripe_payment_intent_id = models.TextField()
    stripe_checkout_session_id = models.TextField()
    paid_at = models.DateTimeField(blank=True, null=True)
    failed_at = models.DateTimeField(blank=True, null=True)
    failure_reason = models.TextField()
    price_version = models.ForeignKey('FleetPriceVersion', models.DO_NOTHING)
    stripe_payment_url = models.TextField()

    class Meta:
        managed = False
        db_table = 'fleet_order'


class FleetOutboxMessage(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField(blank=True, null=True)
    category = models.CharField(max_length=40)
    channel = models.CharField(max_length=16)
    to_address = models.TextField()
    subject = models.TextField()
    body = models.TextField()
    payload = models.JSONField()
    dedupe_key = models.CharField(unique=True, max_length=128)
    status = models.CharField(max_length=16)
    created_at = models.DateTimeField()
    sent_at = models.DateTimeField(blank=True, null=True)
    error = models.TextField()

    class Meta:
        managed = False
        db_table = 'fleet_outbox_message'


class FleetOwnerInvite(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    email = models.TextField()
    role = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    created_by = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(blank=True, null=True)
    consumed_by_user = models.UUIDField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_owner_invite'
        unique_together = (('company_id', 'email'),)


class FleetOwnershipTransfer(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField(unique=True)
    from_user_id = models.UUIDField()
    to_user_id = models.UUIDField()
    status = models.CharField(max_length=16)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_ownership_transfer'


class FleetPairingCode(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    code_hash = models.CharField(unique=True, max_length=64)
    label = models.TextField()
    status = models.CharField(max_length=16)
    attempts = models.IntegerField()
    max_attempts = models.IntegerField()
    created_by = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(blank=True, null=True)
    consumed_by_device = models.UUIDField(blank=True, null=True)
    license = models.ForeignKey(FleetLicense, models.DO_NOTHING)
    vehicle = models.ForeignKey('FleetVehicle', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'fleet_pairing_code'


class FleetPendingChange(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    kind = models.CharField(max_length=24)
    status = models.CharField(max_length=16)
    payload = models.JSONField()
    effective_at = models.DateTimeField()
    created_by = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField()
    applied_at = models.DateTimeField(blank=True, null=True)
    canceled_at = models.DateTimeField(blank=True, null=True)
    order = models.ForeignKey(FleetOrder, models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_pending_change'


class FleetPriceVersion(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    label = models.TextField()
    currency = models.CharField(max_length=3)
    vat_rate_bp = models.IntegerField()
    base_price_ore = models.IntegerField()
    volume_price_ore = models.IntegerField()
    volume_threshold = models.IntegerField()
    extra_county_price_ore = models.IntegerField()
    intro_price_ore = models.IntegerField()
    intro_months = models.IntegerField()
    intro_enabled = models.BooleanField()
    launch_date = models.DateField(blank=True, null=True)
    intro_signup_window_days = models.IntegerField()
    terms_version = models.CharField(max_length=32)
    is_default = models.BooleanField(unique=True)
    active_from = models.DateTimeField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'fleet_price_version'


class FleetRiskConfig(models.Model):
    id = models.IntegerField(primary_key=True)
    new_pairings_per_vehicle_24h = models.IntegerField()
    takeovers_per_hour = models.IntegerField()
    vehicle_changes_per_30d = models.IntegerField()
    pairing_code_ttl_seconds = models.IntegerField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'fleet_risk_config'


class FleetRiskSignal(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    kind = models.CharField(max_length=20)
    device_id = models.UUIDField(blank=True, null=True)
    case_ref = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField()
    license = models.ForeignKey(FleetLicense, models.DO_NOTHING, blank=True, null=True)
    vehicle = models.ForeignKey('FleetVehicle', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_risk_signal'


class FleetSalesInvite(models.Model):
    id = models.UUIDField(primary_key=True)
    code_hash = models.CharField(unique=True, max_length=64)
    created_by = models.UUIDField()
    country = models.CharField(max_length=2)
    org_number = models.CharField(max_length=32)
    company_name = models.TextField()
    contact_name = models.TextField()
    contact_email = models.TextField()
    contact_phone = models.TextField()
    verification_note = models.TextField()
    status = models.CharField(max_length=16)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(blank=True, null=True)
    consumed_by_company = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'fleet_sales_invite'


class FleetStaffRole(models.Model):
    id = models.UUIDField(primary_key=True)
    user_id = models.UUIDField(unique=True)
    role = models.CharField(max_length=20)
    is_active = models.BooleanField()
    note = models.TextField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'fleet_staff_role'


class FleetSubscription(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField(unique=True)
    status = models.CharField(max_length=20)
    stripe_customer_id = models.TextField()
    stripe_subscription_id = models.TextField()
    current_period_start = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    cancel_at_period_end = models.BooleanField()
    canceled_at = models.DateTimeField(blank=True, null=True)
    access_until = models.DateTimeField(blank=True, null=True)
    grace_until = models.DateTimeField(blank=True, null=True)
    grace_origin = models.DateTimeField(blank=True, null=True)
    had_successful_payment = models.BooleanField()
    renewal_stopped_at = models.DateTimeField(blank=True, null=True)
    intro_started_at = models.DateTimeField(blank=True, null=True)
    intro_ends_at = models.DateTimeField(blank=True, null=True)
    intro_months_used = models.IntegerField()
    last_stripe_event_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    price_version = models.ForeignKey(FleetPriceVersion, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'fleet_subscription'


class FleetTrial(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField(unique=True)
    org_key = models.CharField(max_length=40)
    source = models.CharField(max_length=20)
    requires_payment_method = models.BooleanField()
    status = models.CharField(max_length=16)
    vehicle_limit = models.IntegerField()
    started_at = models.DateTimeField(blank=True, null=True)
    ends_at = models.DateTimeField(blank=True, null=True)
    ended_reason = models.TextField()
    created_at = models.DateTimeField()
    invite = models.ForeignKey(FleetSalesInvite, models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_trial'


class FleetVehicle(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    plate = models.CharField(max_length=16)
    label = models.TextField()
    status = models.CharField(max_length=16)
    created_at = models.DateTimeField()
    archived_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fleet_vehicle'
        unique_together = (('company_id', 'plate'),)


class FleetVehicleAssignment(models.Model):
    id = models.UUIDField(primary_key=True)
    kind = models.CharField(max_length=16)
    case_ref = models.UUIDField()
    started_at = models.DateTimeField()
    planned_end = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    ended_reason = models.TextField()
    created_by = models.UUIDField(blank=True, null=True)
    license = models.OneToOneField(FleetLicense, models.DO_NOTHING)
    vehicle = models.ForeignKey(FleetVehicle, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'fleet_vehicle_assignment'


class FleetVehicleSession(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    device_id = models.UUIDField(unique=True)
    started_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    ended_at = models.DateTimeField(blank=True, null=True)
    ended_reason = models.CharField(max_length=20)
    ended_by_device = models.UUIDField(blank=True, null=True)
    approval = models.ForeignKey(FleetDeviceApproval, models.DO_NOTHING)
    license = models.OneToOneField(FleetLicense, models.DO_NOTHING)
    vehicle = models.ForeignKey(FleetVehicle, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'fleet_vehicle_session'


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
    county_code = models.CharField(max_length=2, blank=True, null=True)
    area_codes = models.JSONField()
    ai_adjusted_at = models.DateTimeField(blank=True, null=True)
    municipality_code = models.CharField(max_length=4, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'opportunities'


class OpportunityCombinations(models.Model):
    id = models.BigAutoField(primary_key=True)
    rule_id = models.CharField(max_length=40)
    effect = models.CharField(max_length=10)
    primary_external_id = models.TextField()
    member_external_ids = models.JSONField()
    boost = models.IntegerField()
    reason = models.TextField()
    computed_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'opportunity_combinations'


class OpportunityFavorite(models.Model):
    id = models.UUIDField(primary_key=True)
    owner_key = models.TextField()
    opportunity_external_id = models.TextField()
    snapshot = models.JSONField()
    note = models.TextField()
    created_at = models.DateTimeField()
    opportunity = models.ForeignKey(Opportunities, models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'opportunity_favorite'
        unique_together = (('owner_key', 'opportunity_external_id'),)


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


class PushDelivery(models.Model):
    id = models.UUIDField(primary_key=True)
    opportunity_external_id = models.TextField()
    device_id = models.UUIDField()
    device_token = models.TextField()
    title = models.TextField()
    body = models.TextField()
    snapshot = models.JSONField()
    ok = models.BooleanField()
    error = models.TextField()
    created_at = models.DateTimeField()
    opportunity = models.ForeignKey(Opportunities, models.DO_NOTHING, blank=True, null=True)
    status = models.CharField(max_length=10)
    attempts = models.IntegerField()
    next_attempt_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'push_delivery'
        unique_together = (('device_id', 'opportunity_external_id'),)


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
    last_success_at = models.DateTimeField(blank=True, null=True)
    consecutive_failures = models.IntegerField()

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
