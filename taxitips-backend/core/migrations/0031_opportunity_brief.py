from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0030_railassessment_facts'),
    ]

    operations = [
        migrations.AddField(
            model_name='opportunity',
            name='brief',
            field=models.CharField(blank=True, help_text='En rad för föraren: vad, var, när, varför. Bara siffror som finns i tipset.', max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='opportunity',
            name='brief_key',
            field=models.CharField(blank=True, help_text='Hash av fälten beskedet skrevs från; ett annat värde betyder att det är inaktuellt.', max_length=64, null=True),
        ),
    ]
