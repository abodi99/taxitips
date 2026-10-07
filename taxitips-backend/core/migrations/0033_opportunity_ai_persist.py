"""
AI-domen överlever pollrundan.

Expand-steget: tre nullbara kolumner, inget tas bort. Insamlingens upsert
(core/repository.py) skriver `rule_key` och behåller de AI-satta kolumnerna
när `ai_rule_key` är lika; granskningen (core/genkit._apply) skriver
`ai_rule_key` och `ai_facts`.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0032_quality_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='opportunity',
            name='rule_key',
            field=models.CharField(blank=True, max_length=40, null=True),
        ),
        migrations.AddField(
            model_name='opportunity',
            name='ai_rule_key',
            field=models.CharField(blank=True, max_length=40, null=True),
        ),
        migrations.AddField(
            model_name='opportunity',
            name='ai_facts',
            field=models.JSONField(blank=True, help_text='Det granskningen läste ut (core/tip_facts.TipFacts) -- förarbeskedets underlag.', null=True),
        ),
    ]
