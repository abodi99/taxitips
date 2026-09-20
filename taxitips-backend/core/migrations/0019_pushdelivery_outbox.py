from django.db import migrations, models


def mark_failed(apps, schema_editor):
    # Rader skrivna innan utkorgen fanns: skickade eller misslyckade, aldrig väntande.
    PushDelivery = apps.get_model("core", "PushDelivery")
    PushDelivery.objects.filter(ok=False).update(status="failed")


class Migration(migrations.Migration):
    # Additiv: nya kolumner med standardvärden, inget tas bort eller döps om.

    dependencies = [
        ("core", "0018_opportunity_area"),
    ]

    operations = [
        migrations.AddField(
            model_name="pushdelivery",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Väntar"),
                    ("sending", "Skickas"),
                    ("sent", "Skickad"),
                    ("failed", "Misslyckad"),
                    ("expired", "Utgången"),
                ],
                default="sent",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="pushdelivery",
            name="attempts",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="pushdelivery",
            name="next_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="pushdelivery",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="pushdelivery",
            name="sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="pushdelivery",
            index=models.Index(fields=["status", "next_attempt_at"], name="push_delivery_status_due_idx"),
        ),
        migrations.RunPython(mark_failed, migrations.RunPython.noop),
    ]
