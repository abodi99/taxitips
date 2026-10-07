# Manuellt beviljande av fullt medlemskap utan kostnad (2026-10).
#
# EXPAND, bara additivt: en helt ny tabell. Ingen befintlig rad ändras och
# ingen befintlig väg påverkas -- `company_window` börjar först läsa den när
# det finns en rad i den (fleet/access.py). Se fleet/grants.py.

import uuid

from django.db import migrations, models

# Aldrig via PostgREST (invariant 19, samma skäl som 0003, 0019, 0021 och 0024).
REVOKE = """
do $$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    if to_regclass('public.fleet_membership_grant') is not null then
      execute format('revoke all on table public.fleet_membership_grant from %I', r);
    end if;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0024_membership_assignee'),
    ]

    operations = [
        migrations.CreateModel(
            name='MembershipGrant',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('company_id', models.UUIDField(db_index=True)),
                ('license_created', models.BooleanField(default=False)),
                ('user_id', models.UUIDField(blank=True, db_index=True, null=True)),
                ('email', models.CharField(blank=True, default='', max_length=254)),
                ('counties', models.JSONField(blank=True, default=list)),
                ('all_counties', models.BooleanField(default=True)),
                ('reason', models.TextField()),
                ('starts_at', models.DateTimeField()),
                ('ends_at', models.DateTimeField(blank=True, null=True)),
                ('granted_by', models.UUIDField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_by', models.UUIDField(blank=True, null=True)),
                ('revoke_reason', models.TextField(blank=True, default='')),
                ('license', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='grants', to='fleet.license')),
            ],
            options={
                'db_table': 'fleet_membership_grant',
            },
        ),
        migrations.AddIndex(
            model_name='membershipgrant',
            index=models.Index(fields=['company_id', 'revoked_at'], name='fleet_membe_company_615d82_idx'),
        ),
        migrations.AddIndex(
            model_name='membershipgrant',
            index=models.Index(fields=['user_id', 'revoked_at'], name='fleet_membe_user_id_e7c7cd_idx'),
        ),
        migrations.AddConstraint(
            model_name='membershipgrant',
            constraint=models.UniqueConstraint(
                condition=models.Q(('revoked_at__isnull', True), ('user_id__isnull', False)),
                fields=('company_id', 'user_id'),
                name='fleet_one_open_grant_per_company_user',
            ),
        ),
        migrations.AddConstraint(
            model_name='membershipgrant',
            constraint=models.UniqueConstraint(
                condition=models.Q(('revoked_at__isnull', True)) & ~models.Q(email=''),
                fields=('company_id', 'email'),
                name='fleet_one_open_grant_per_company_email',
            ),
        ),
        migrations.RunSQL(sql=REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
