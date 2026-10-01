# Uppföljning: strukturerad avhoppsorsak + utfall "vill komma tillbaka".

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0012_trial_planned_days_and_discount"),
    ]

    operations = [
        migrations.AddField(
            model_name="salesfollowup",
            name="churn_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("not_asked", "Ej frågat"),
                    ("price", "Pris"),
                    ("low_usage", "Använder inte"),
                    ("competitor", "Bytt leverantör"),
                    ("business", "Sålt/lägger ner"),
                    ("features", "Saknar funktion"),
                    ("support", "Support/teknik"),
                    ("temporary", "Paus – kan komma tillbaka"),
                    ("other", "Annat"),
                ],
                default="not_asked",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="salesfollowup",
            name="outcome",
            field=models.CharField(
                choices=[
                    ("not_contacted", "Inte kontaktad"),
                    ("no_answer", "Svarade inte"),
                    ("call_back", "Ring igen"),
                    ("interested", "Intresserad"),
                    ("not_interested", "Inte intresserad"),
                    ("wrong_details", "Fel uppgifter"),
                    ("customer", "Blev kund"),
                    ("win_back", "Vill komma tillbaka"),
                ],
                default="not_contacted",
                max_length=20,
            ),
        ),
    ]
