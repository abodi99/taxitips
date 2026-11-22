from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Kundtypen på företagsprofilen: företag eller privatperson
    (fleet/company_details.py). Bara tillägg -- kolumnen får ett standardvärde
    i databasen, så att en äldre container kan skriva profiler under
    utrullningen. (Indexnamn och CompanyDiscount.kind som makemigrations också
    ville röra hör inte hit och lämnas till en egen migrering.)
    """

    dependencies = [
        ("fleet", "0029_bookkeeping_record"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="customer_kind",
            field=models.CharField(
                choices=[("company", "Företag"), ("private", "Privatperson")],
                default="company", db_default="company", max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="customer_kind_set_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
