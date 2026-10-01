# CRM-taggar för filter och framtida marknadsanalys-automation.

from django.db import migrations, models
import django.db.models.deletion
import uuid


REVOKE = """
do $$
declare
  r text;
  tbl text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    foreach tbl in array array['fleet_crm_tag', 'fleet_crm_tagging'] loop
      if to_regclass('public.' || tbl) is not null then
        execute format('revoke all on table public.%I from %I', tbl, r);
      end if;
    end loop;
  end loop;
end $$;
"""

# (slug, category, label, sort_order)
SEED_TAGS = [
    # Län — SCB-koder
    ("lan:01", "county", "Stockholms län", 1),
    ("lan:03", "county", "Uppsala län", 3),
    ("lan:04", "county", "Södermanlands län", 4),
    ("lan:05", "county", "Östergötlands län", 5),
    ("lan:06", "county", "Jönköpings län", 6),
    ("lan:07", "county", "Kronobergs län", 7),
    ("lan:08", "county", "Kalmar län", 8),
    ("lan:09", "county", "Gotlands län", 9),
    ("lan:10", "county", "Blekinge län", 10),
    ("lan:12", "county", "Skåne län", 12),
    ("lan:13", "county", "Hallands län", 13),
    ("lan:14", "county", "Västra Götalands län", 14),
    ("lan:17", "county", "Värmlands län", 17),
    ("lan:18", "county", "Örebro län", 18),
    ("lan:19", "county", "Västmanlands län", 19),
    ("lan:20", "county", "Dalarnas län", 20),
    ("lan:21", "county", "Gävleborgs län", 21),
    ("lan:22", "county", "Västernorrlands län", 22),
    ("lan:23", "county", "Jämtlands län", 23),
    ("lan:24", "county", "Västerbottens län", 24),
    ("lan:25", "county", "Norrbottens län", 25),
    ("lan:okand", "county", "Län okänt", 99),
    # ICP / segment från sales_list
    ("icp:stark", "icp", "Stark ICP", 1),
    ("icp:medel", "icp", "Medel ICP", 2),
    ("icp:svag", "icp", "Svag ICP", 3),
    ("icp:ej", "icp", "Ej ICP / ring ej", 4),
    ("segment:a", "segment", "A – Beställningscentral / stort", 1),
    ("segment:b", "segment", "B – Mellanstort (3–9 bilar)", 2),
    ("segment:c", "segment", "C – Litet (1–2 bilar)", 3),
    ("segment:d", "segment", "D – Storlek okänd", 4),
    ("segment:x", "segment", "X – Ring ej", 5),
    ("medlem:taxiforbundet", "segment", "Taxiförbundet", 10),
    # Källa
    ("kalla:marknadsanalys", "source", "Marknadsanalys (sales_list)", 1),
    ("kalla:twenty", "source", "Twenty", 2),
    ("kalla:taxitips_web", "source", "Weblead", 3),
    ("kalla:manuell", "source", "Manuell", 4),
    # Research
    ("research:ej_startad", "research", "Research ej startad", 1),
    ("research:klar", "research", "Research klar", 2),
    ("research:foraldrad", "research", "Research föråldrad", 3),
    # Ringordning
    ("call:1", "call", "Tier 1 – Skåne", 1),
    ("call:2", "call", "Tier 2 – Stockholm", 2),
    ("call:3", "call", "Tier 3 – Västra Götaland", 3),
    ("call:4", "call", "Tier 4 – Halland/Blekinge/Kronoberg", 4),
    ("call:5", "call", "Tier 5 – Övriga Taxiförbundet", 5),
    ("call:6", "call", "Tier 6 – Övriga", 6),
]


def seed_tags(apps, schema_editor):
    CrmTag = apps.get_model("fleet", "CrmTag")
    for slug, category, label, sort_order in SEED_TAGS:
        CrmTag.objects.update_or_create(
            slug=slug,
            defaults={
                "category": category,
                "label": label,
                "sort_order": sort_order,
                "is_active": True,
            },
        )


def unseed_tags(apps, schema_editor):
    CrmTag = apps.get_model("fleet", "CrmTag")
    CrmTag.objects.filter(slug__in=[t[0] for t in SEED_TAGS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0015_crm_module"),
    ]

    operations = [
        migrations.CreateModel(
            name="CrmTag",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("slug", models.CharField(max_length=64, unique=True)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("county", "Län"),
                            ("icp", "ICP"),
                            ("source", "Källa"),
                            ("research", "Research"),
                            ("segment", "Segment"),
                            ("call", "Ringordning"),
                        ],
                        max_length=20,
                    ),
                ),
                ("label", models.CharField(max_length=120)),
                ("sort_order", models.SmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "fleet_crm_tag",
                "indexes": [
                    models.Index(
                        fields=["category", "sort_order"], name="fleet_crm_tag_cat_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CrmTagging",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                (
                    "entity_type",
                    models.CharField(
                        choices=[
                            ("account", "Konto"),
                            ("person", "Person"),
                            ("deal", "Affär"),
                        ],
                        max_length=10,
                    ),
                ),
                ("entity_id", models.UUIDField()),
                ("origin", models.CharField(default="manual", max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "tag",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="taggings",
                        to="fleet.crmtag",
                    ),
                ),
            ],
            options={
                "db_table": "fleet_crm_tagging",
                "indexes": [
                    models.Index(
                        fields=["entity_type", "entity_id"],
                        name="fleet_crm_tagging_ent_idx",
                    ),
                    models.Index(
                        fields=["tag", "entity_type"], name="fleet_crm_tagging_tag_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tag", "entity_type", "entity_id"),
                        name="fleet_crm_tagging_unique",
                    ),
                ],
            },
        ),
        migrations.RunPython(seed_tags, unseed_tags),
        migrations.RunSQL(REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
