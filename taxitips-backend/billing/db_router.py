"""
Riktar all billing-appens ORM-trafik mot "supabase"-DB-aliaset (se
config/settings.py:s DATABASES) i stället för "default" (Djangos egen
taxitips-databas). allow_migrate returnerar False oavsett riktning --
Supabase äger dessa tabellers migrationer, Django ska aldrig försöka skapa,
ändra eller ta bort dem.
"""


class DatabaseRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label == "billing":
            return "supabase"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == "billing":
            return "supabase"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        billing_labels = {"billing"}
        labels = {obj1._meta.app_label, obj2._meta.app_label}
        if labels & billing_labels:
            return labels <= billing_labels
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == "billing":
            return False
        return None
