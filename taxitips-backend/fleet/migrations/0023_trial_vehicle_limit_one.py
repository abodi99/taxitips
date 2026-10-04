from django.db import migrations, models


class Migration(migrations.Migration):
    """Standardvärdet följer regeln: ett prov har en bil. Ingen SQL (Python-default)."""

    dependencies = [
        ('fleet', '0022_company_notify_default'),
    ]

    operations = [
        migrations.AlterField(
            model_name='trial',
            name='vehicle_limit',
            field=models.IntegerField(default=1),
        ),
    ]
