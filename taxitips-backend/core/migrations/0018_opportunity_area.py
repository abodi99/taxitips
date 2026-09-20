from django.db import migrations, models


class Migration(migrations.Migration):
    # Additiv: två nya kolumner. Värdena skrivs av upsert_opportunities vid nästa
    # pollrunda, eller direkt med `manage.py backfill_areas`.

    dependencies = [
        ("core", "0017_sourcestatus_last_success"),
    ]

    operations = [
        migrations.AddField(
            model_name="opportunity",
            name="county_code",
            field=models.CharField(blank=True, db_index=True, max_length=2, null=True),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="area_codes",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
