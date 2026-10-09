# Bara valen för AccountBlock.kind: två nya sorter (pausat företag, pausat
# konto). Kolumnen är oförändrad (varchar(10)) -- ingen SQL körs.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0026_membership_grant_categories'),
    ]

    operations = [
        migrations.AlterField(
            model_name='accountblock',
            name='kind',
            field=models.CharField(choices=[('company', 'Företag'), ('email', 'E-postadress'), ('user', 'Konto'), ('pause', 'Pausat företag'), ('user_pause', 'Pausat konto')], max_length=10),
        ),
    ]
