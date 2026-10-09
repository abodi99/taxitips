# Valbara tipskategorier per manuellt beviljande (2026-10).
#
# EXPAND, bara additivt: en ny kolumn som får vara NULL. NULL betyder "alla
# kategorier", så varje befintligt beviljande behåller FULL utan backfill och
# utan att någon rad skrivs om. Tabellen är redan stängd för PostgREST (0025);
# en ny kolumn ärver tabellens rättigheter, så ingen ny REVOKE behövs.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0025_membership_grant'),
    ]

    operations = [
        migrations.AddField(
            model_name='membershipgrant',
            name='categories',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
