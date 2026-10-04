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
    if to_regclass('public.ai_call') is not null then
      execute format('revoke all on table public.ai_call from %I', r);
    end if;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0028_opportunity_factors'),
    ]

    operations = [
        migrations.CreateModel(
            name='AiCall',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('purpose', models.CharField(help_text='review, extract, gate, brief, report …', max_length=30)),
                ('model', models.CharField(max_length=60)),
                ('ok', models.BooleanField(default=False)),
                ('tokens_in', models.IntegerField(default=0)),
                ('tokens_out', models.IntegerField(default=0)),
                ('cost_micro_usd', models.IntegerField(default=0)),
                ('latency_ms', models.IntegerField(default=0)),
                ('error', models.CharField(blank=True, default='', max_length=200)),
                ('subject', models.CharField(blank=True, default='', help_text='Tipsets external_id när anropet gällde ett tips.', max_length=200)),
            ],
            options={
                'db_table': 'ai_call',
                'ordering': ['-created_at'],
            },
        ),
        migrations.RunSQL(REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
