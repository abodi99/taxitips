"""
Linje och plats på tipset, och vems ersättningsregler resenären reser på.

Expand-steget, bara tillägg:

* `opportunities.line`, `opportunities.station` -- tomma som standard
  (`db_default`), så att varje skrivväg som inte nämner dem fungerar som förut.
  Skrivs av insamlingen (core/tip_text.py) och läsningen (core/places_ai.py).
* Index på `opportunities.rule_key`: insamlingen slår upp en sparad
  modelläsning för samma text varje pollrunda.
* `region_compensation_rule.source_name` -- huvudmannens namn. Data-steget
  fyller namnet och, där länken saknas, länken -- båda ordagrant ur
  docs/transit-compensation-rules.md §3 (hämtade 2026-09-08). Aldrig en gissad
  adress: en region som inte står där lämnas orörd.

Ingen RenameIndex för opportunityreport här, fast makemigrations föreslår den:
den driften fanns före den här ändringen och hör inte hit.
"""

from django.db import migrations, models

# docs/transit-compensation-rules.md §3: regionnyckel -> (huvudman, källa).
DOC_SOURCES = {
    "skane": ("Skånetrafiken", "https://www.skanetrafiken.se/sa-reser-du-med-oss/villkor/villkor-for-ersattning-vid-forsening/"),
    "sl": ("SL", "https://sl.se/kundservice/forseningsersattning"),
    "vt": ("Västtrafik", "https://www.vasttrafik.se/kundservice/forseningsersattning/"),
    "ul": ("UL", "https://www.ul.se/kundservice/forseningsersattning/"),
    "otraf": ("Östgötatrafiken", "https://www.ostgotatrafiken.se/kontakt-och-hjalp/forseningsersattning"),
    "klt": ("Kalmar länstrafik", "https://kalmarlanstrafik.se/Kundservice/ansok-om-forseningsersattning/"),
    "krono": ("Länstrafiken Kronoberg", "https://lanstrafikenkron.se/forseningsersattning"),
    "jlt": ("Jönköpings Länstrafik", "https://www.jlt.se/kundservice/forseningsersattning/"),
    "blekinge": ("Blekingetrafiken", "https://www.blekingetrafiken.se/kundservice/forseningsersattning/"),
    "varm": ("Värmlandstrafik", "https://www.varmlandstrafik.se/varmlandstrafik/kundservice/forseningsersattning"),
    "orebro": ("Länstrafiken Örebro", "https://www.lanstrafiken.se/kundservice/forsenad-och-kvarglomd/vad-galler-for-forseningsersattning/"),
    "vastmanland": ("VL", "https://vl.se/biljetter/villkor-och-ersattning/forseningsersattning/"),
    "dt": ("Dalatrafik", "https://www.dalatrafik.se/kundservice/vanliga-arenden/forsenad-eller-utebliven-tur/"),
    "xt": ("X-trafik", "https://xtrafik.se/forseningsersattning"),
    "dintur": ("Din Tur", "https://www.dintur.se/det-har-galler-for-ersattning-vid-forsening/"),
    "gotland": ("Region Gotland", "https://gotland.se/trafik-gator-och-parker/kollektivtrafik/vanliga-fragor-om-kollektivtrafiken/forseningsersattning"),
}


def fill_sources(apps, schema_editor):
    Rule = apps.get_model("core", "RegionCompensationRule")
    for rule in Rule.objects.filter(region__in=list(DOC_SOURCES)):
        name, url = DOC_SOURCES[rule.region]
        fields = []
        if not rule.source_name:
            rule.source_name = name
            fields.append("source_name")
        if not rule.source_url:
            rule.source_url = url
            fields.append("source_url")
        if fields:
            rule.save(update_fields=fields)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0033_opportunity_ai_persist'),
    ]

    operations = [
        migrations.AddField(
            model_name='opportunity',
            name='line',
            field=models.CharField(blank=True, db_default='', default='', max_length=60),
        ),
        migrations.AddField(
            model_name='opportunity',
            name='station',
            field=models.CharField(blank=True, db_default='', default='', max_length=120),
        ),
        migrations.AddField(
            model_name='regioncompensationrule',
            name='source_name',
            field=models.CharField(blank=True, db_default='', default='', max_length=80),
        ),
        migrations.AddIndex(
            model_name='opportunity',
            index=models.Index(fields=['rule_key'], name='opportunities_rule_key_idx'),
        ),
        migrations.RunPython(fill_sources, migrations.RunPython.noop),
    ]
