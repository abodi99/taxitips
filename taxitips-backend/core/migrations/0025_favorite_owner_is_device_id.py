"""
Favoriternas ägarnyckel blir telefonens id i stället för telefonens token.

`owner_key` var förarens X-Device-Token i klartext. Sedan parkopplingen
lämnar ut en hashad hemlighet (fleet.DeviceCredential) är token en
inloggning, och en kopia i favorittabellen gjorde hashningen verkningslös.
Nyckeln blir `device:<uuid>`; ägarvägen (`user:<uuid>`) rörs inte.

Nycklar som inte går att knyta till någon telefon (okänd eller återkallad
token) tas bort -- de är hemligheter utan ägare, och ingen app kan längre
läsa dem.
"""

import hashlib

from django.db import migrations


def forwards(apps, schema_editor):
    Favorite = apps.get_model("core", "OpportunityFavorite")
    Credential = apps.get_model("fleet", "DeviceCredential")
    connection = schema_editor.connection

    # `devices` ägs av Supabases migrationer och finns inte i en naken testdatabas.
    with connection.cursor() as cur:
        cur.execute("select to_regclass('public.devices') is not null")
        has_devices = bool(cur.fetchone()[0])

    keys = set(
        Favorite.objects.exclude(owner_key__startswith="user:")
        .exclude(owner_key__startswith="device:")
        .values_list("owner_key", flat=True)
    )
    for token in keys:
        device_id = None
        credential = Credential.objects.filter(
            token_hash=hashlib.sha256(token.encode()).hexdigest(), revoked_at__isnull=True
        ).first()
        if credential is not None:
            device_id = credential.device_id
        elif has_devices:
            # Äldre telefoner: klartexttoken i Supabases `devices`, som Django inte migrerar.
            with connection.cursor() as cur:
                cur.execute("select id from devices where token = %s limit 1", [token])
                row = cur.fetchone()
            if row:
                device_id = row[0]
        rows = Favorite.objects.filter(owner_key=token)
        if device_id is None:
            rows.delete()
            continue
        new_key = f"device:{device_id}"
        existing = set(
            Favorite.objects.filter(owner_key=new_key).values_list("opportunity_external_id", flat=True)
        )
        rows.filter(opportunity_external_id__in=existing).delete()
        rows.update(owner_key=new_key)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_alter_pushdelivery_status"),
        ("fleet", "0004_sales"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
