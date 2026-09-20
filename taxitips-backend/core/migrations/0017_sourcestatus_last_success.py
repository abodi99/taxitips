from django.db import migrations, models
from django.db.models import F


def backfill(apps, schema_editor):
    # En rad vars senaste försök gick igenom har sin senaste lyckade hämtning i
    # checked_at. Rader med fel får vänta på nästa lyckade runda.
    SourceStatus = apps.get_model("core", "SourceStatus")
    SourceStatus.objects.filter(ok=True).update(last_success_at=F("checked_at"))


class Migration(migrations.Migration):
    # Additiv: två nya kolumner, inget tas bort eller döps om.

    dependencies = [
        ("core", "0016_alter_opportunity_severity_tier_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sourcestatus",
            name="last_success_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sourcestatus",
            name="consecutive_failures",
            field=models.IntegerField(default=0),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
