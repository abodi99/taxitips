"""
Täckning per län: vad vi faktiskt hämtar, och var det inte går.

Frågan som fick den här filen att bli till: "varför hittar ni mycket i
Stockholm, Göteborg och Skåne men nästan inget i Halland, Kalmar, Blekinge
och Jönköping -- hämtar ni ens något där?"

Svaret är tre olika saker som ser likadana ut i en tom tabell:

1. **Källan finns inte.** Halland, Jämtland, Västerbotten, Norrbotten och
   Sörmland 404:ar på Trafiklabs ServiceAlerts -- produkten täcker dem inte,
   och ingen nyckel i världen ändrar det.
2. **Källan finns och svarar tomt.** Blekinge svarade 200 med noll larm när
   det här skrevs. Det är en lugn dag i ett litet nät, inte ett fel.
3. **Nätet är litet.** Kalmar gav 11 larm och Jönköping 16 i samma stund som
   Stockholm gav 202. Skillnaden är antal linjer och resenärer, inte täckning.

Tabellen nedan är den enda hårdkodade delen; allt annat (utfall, antal)
läses ur `SourceStatus` och `opportunities` vid varje anrop, så raden kan
inte påstå att en källa fungerar när den slutat göra det.
"""

from __future__ import annotations

# län -> (namn, trafiklab-operatörskod, vägens länsnyckel i COUNTY)
# None som operatörskod = ingen kollektivtrafikkälla finns för länet.
COUNTIES: list[tuple[str, str | None, str]] = [
    ("Stockholm", "sl", "stockholm"),
    ("Uppsala", "ul", "uppsala"),
    ("Södermanland", None, "sodermanland"),
    ("Östergötland", "otraf", "ostergotland"),
    ("Jönköping", "jlt", "jonkoping"),
    ("Kronoberg", "krono", "kronoberg"),
    ("Kalmar", "klt", "kalmar"),
    ("Gotland", "gotland", "gotland"),
    ("Blekinge", "blekinge", "blekinge"),
    ("Skåne", "skane", "skane"),
    ("Halland", None, "halland"),
    # Västtrafik har en egen adapter (core/sources/vasttrafik.py) därför att
    # operatörskoden `vt` 404:ar hos Trafiklab -- Sveriges andra stad hade
    # annars saknat kollektivtrafikdata helt.
    ("Västra Götaland", "vt-adapter", "vastragotaland"),
    ("Värmland", "varm", "varmland"),
    ("Örebro", "orebro", "orebro"),
    ("Västmanland", "vastmanland", "vastmanland"),
    ("Dalarna", "dt", "dalarna"),
    ("Gävleborg", "xt", "gavleborg"),
    ("Västernorrland", "dintur", "vasternorrland"),
    ("Jämtland", None, "jamtland"),
    ("Västerbotten", None, "vasterbotten"),
    ("Norrbotten", None, "norrbotten"),
]

# Operatörskoder som provats och bevisligen inte finns i produkten. Sparade
# för att svaret "vi hämtar inte där" ska gå att skilja från "vi har inte
# provat" -- se docs/data-sources.md för mätningarna.
UNAVAILABLE_OPERATORS = {
    "halland", "sormland", "ostgota", "vt", "vasterbotten",
    "norrbotten", "jamtland", "vasternorrland", "sj",
}


def coverage_rows(now) -> list[dict]:
    from django.db.models import Count

    from core.models import Opportunity, SourceStatus

    statuses = {s.source: s for s in SourceStatus.objects.all()}
    trafiklab = statuses.get("trafiklab")
    detail = (trafiklab.detail or {}) if trafiklab else {}

    from core.sources.trafikverket_road import configured_counties, COUNTY

    road_codes = set(configured_counties())

    tips = dict(
        Opportunity.objects.filter(end_time__gt=now)
        .values_list("region")
        .annotate(n=Count("id"))
        .values_list("region", "n")
    )

    rows = []
    for label, operator, county in COUNTIES:
        if operator == "vt-adapter":
            vt = statuses.get("vt")
            transit = {
                "source": "Västtrafik (egen adapter)",
                "state": "ok" if (vt and vt.ok) else ("fel" if vt else "okörd"),
                "alerts": vt.events if vt else 0,
            }
            region_key = "vt"
        elif operator is None:
            transit = {
                "source": "—",
                "state": "saknas",
                "alerts": 0,
            }
            region_key = None
        else:
            d = detail.get(operator)
            transit = {
                "source": f"Trafiklab · {operator}",
                "state": "ok" if (d and d.get("ok")) else ("fel" if d else "okörd"),
                "alerts": (d or {}).get("alerts", 0),
                "error": (d or {}).get("error", ""),
            }
            region_key = operator

        rows.append({
            "county": label,
            "transit": transit,
            "road": {
                "polled": COUNTY.get(county) in road_codes,
                "county": county,
            },
            "activeTips": tips.get(region_key, 0) if region_key else 0,
        })
    return rows
