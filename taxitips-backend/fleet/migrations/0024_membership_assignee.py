# Kontobaserat medlemskap (2026-10): en licens (det som köps) tilldelas ett
# KONTO i stället för en bil.
#
# EXPAND, bara additivt -- ingenting tas bort och ingen befintlig väg ändras.
# Kolumnerna på `fleet_license` är NULL-bara, och `fleet_membership_session` är
# en helt ny tabell. Inga befintliga rader får en öppen session, så
# åtkomstkontrollen (fleet/access.py) beter sig exakt som förut tills appen
# börjar ta en session. Se docs/fleet-abonnemang.md.
#
# Backfillen sätter ägarkontot på de licenser som redan hade en godkänd telefon
# med ett inloggat konto, så att befintliga kunder hamnar rätt utan handpåläggning.

import uuid

from django.db import migrations, models

# Aldrig via PostgREST (invariant 19, samma skäl som 0003, 0019 och 0021).
REVOKE = """
do $$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    if to_regclass('public.fleet_membership_session') is not null then
      execute format('revoke all on table public.fleet_membership_session from %I', r);
    end if;
  end loop;
end $$;
"""

# Licenser som redan har en godkänd telefon med ett inloggat konto: deras konto
# blir medlemskapets innehavare. DISTINCT ON plockar senast godkända, så två
# telefoner på samma licens ger ett förutsägbart svar i stället för slumpen.
#
# `devices` ägs av Supabase (managed=False) och finns inte i Djangos testdatabas
# när migrationen körs -- där skapas den först av testharnessen. Void-grinden
# gör backfillen till en no-op då, i stället för att spränga `migrate`.
BACKFILL = """
do $$
begin
  if to_regclass('public.devices') is null
     or to_regclass('public.fleet_device_approval') is null then
    return;
  end if;
  update fleet_license l
  set assignee_user_id = pick.user_id,
      assigned_at = now()
  from (
      select distinct on (a.license_id) a.license_id, d.user_id
      from fleet_device_approval a
      join devices d on d.id = a.device_id
      where a.status = 'active' and d.user_id is not null
      order by a.license_id, a.approved_at desc
  ) as pick
  where pick.license_id = l.id
    and l.assignee_user_id is null;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0023_trial_vehicle_limit_one'),
    ]

    operations = [
        migrations.AddField(
            model_name='license',
            name='assignee_user_id',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='license',
            name='assignee_email',
            field=models.CharField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='license',
            name='assigned_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='license',
            name='assigned_by',
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='MembershipSession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('company_id', models.UUIDField()),
                ('user_id', models.UUIDField(db_index=True)),
                ('device_id', models.UUIDField()),
                ('started_at', models.DateTimeField()),
                ('last_seen_at', models.DateTimeField()),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('ended_reason', models.CharField(blank=True, choices=[('takeover', 'Övertagen av annan enhet'), ('leaving', 'Lämnade medlemskapet'), ('unassigned', 'Medlemskapet togs bort från kontot'), ('device_moved', 'Enheten tog ett annat medlemskap'), ('blocked', 'Spärrad av administratör'), ('expired', 'Tidsgräns')], default='', max_length=20)),
                ('ended_by_device', models.UUIDField(blank=True, null=True)),
                ('license', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='membership_sessions', to='fleet.license')),
            ],
            options={
                'db_table': 'fleet_membership_session',
            },
        ),
        migrations.AddIndex(
            model_name='membershipsession',
            index=models.Index(fields=['user_id', 'ended_at'], name='fleet_membe_user_id_caae27_idx'),
        ),
        migrations.AddIndex(
            model_name='membershipsession',
            index=models.Index(fields=['license', '-started_at'], name='fleet_membe_license_c8c96f_idx'),
        ),
        migrations.AddConstraint(
            model_name='membershipsession',
            constraint=models.UniqueConstraint(condition=models.Q(('ended_at__isnull', True)), fields=('user_id',), name='fleet_one_active_membership_session_per_user'),
        ),
        migrations.AddConstraint(
            model_name='membershipsession',
            constraint=models.UniqueConstraint(condition=models.Q(('ended_at__isnull', True)), fields=('license',), name='fleet_one_active_membership_session_per_license'),
        ),
        migrations.RunSQL(sql=BACKFILL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
