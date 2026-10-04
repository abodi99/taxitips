from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0029_ai_call'),
    ]

    operations = [
        migrations.AddField(
            model_name='railassessment',
            name='facts',
            field=models.JSONField(blank=True, help_text='Det modellen läste ut (core/tip_facts.TipFacts). Poängen räknas från den av reglerna.', null=True),
        ),
    ]
