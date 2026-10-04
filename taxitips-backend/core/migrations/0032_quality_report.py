from django.db import migrations, models

# Invariant 19: tabellen nås aldrig via PostgREST. Samma mönster som 0026.
REVOKE = """
do $$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    if to_regclass('public.quality_report') is not null then
      execute format('revoke all on table public.quality_report from %I', r);
    end if;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0031_opportunity_brief'),
    ]

    operations = [
        migrations.CreateModel(
            name='QualityReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day', models.DateField(unique=True)),
                ('stats', models.JSONField(default=dict)),
                ('summary', models.TextField(blank=True, default='')),
                ('suggestions', models.JSONField(blank=True, default=list)),
                ('model', models.CharField(blank=True, default='', max_length=60)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'quality_report',
                'ordering': ['-day'],
            },
        ),
        migrations.RunSQL(REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
