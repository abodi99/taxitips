# Expand only: new nullable/defaulted columns. Nothing is removed.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_opportunity_report_and_suppression"),
    ]

    operations = [
        migrations.AddField(
            model_name="opportunity",
            name="departure_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="destination",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="delay_minutes",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="factors",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Det föraren läser om varför: högst fyra korta rader "
                    '{"text", "sign": "+"|"-"} från core/taxi_context.py -- läget och '
                    "de omständigheter som räknades (tid, ersättning, väder). Inga "
                    "poäng, inga källnamn."
                ),
            ),
        ),
    ]
