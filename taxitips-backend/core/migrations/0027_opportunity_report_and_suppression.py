# Generated manually for tip reports and staff suppression.

import uuid

from django.db import migrations, models
import django.db.models.deletion
import django.db.models.functions


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_app_version_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="opportunity",
            name="suppressed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="suppressed_by",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="suppression_note",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="OpportunityReport",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("device_token", models.TextField(blank=True, db_index=True)),
                ("reporter_user_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("reason", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Öppen"), ("resolved", "Avslutad")],
                        db_index=True,
                        default="open",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(db_default=django.db.models.functions.Now())),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_by", models.UUIDField(blank=True, null=True)),
                ("resolution_note", models.TextField(blank=True)),
                (
                    "opportunity",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reports",
                        to="core.opportunity",
                    ),
                ),
            ],
            options={
                "db_table": "opportunity_report",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["status", "created_at"], name="opportunity__status_4a8f2d_idx"),
                ],
            },
        ),
    ]
