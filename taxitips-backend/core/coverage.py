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
    ("Västra Götaland (Göteborg)", "vt-adapter", "vastragotaland"),
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


# --- Länskatalogen som förarens notisinställningar väljer ur -------------
#
# Härleds ur COUNTIES ovan i stället för att skrivas en gång till. Skälet är
# hela poängen med den här filen: listan över svenska län fanns redan här,
# och en andra kopia i notisinställningarna hade kunnat säga "Halland" långt
# efter att tabellen ovan slutat påstå att vi hämtar något där.
#
# Nyckeln är `region` som pipelinen faktiskt SKRIVER på ett tips -- inte
# länsnamnet. Trafiklabs operatörskod ÄR regionnyckeln (skane, sl, ul, ...),
# Västtrafik skriver "vt", och järnvägen skriver "rail". Ett filter som
# matchat på länsnamn hade matchat noll rader.
#
# Mätt på 506 aktiva tips: 100% bär en `region`, medan 61% saknar `places`
# helt. Därför är länet det filter som går att lita på, och orten en
# förfining ovanpå det -- inte tvärtom.

# Järnvägen har ingen länsindelning i Trafikverkets data: tipsen skrivs med
# region "rail" oavsett var i landet stationen ligger. Den är alltså inte
# ett län att välja bland de andra, utan ett eget val -- att tyst filtrera
# bort den för alla som valt ett län hade tagit bort tågtipsen, vilket är
# den starkaste signalen i hela flödet.
RAIL_REGION_KEY = "rail"


def notify_region_catalog() -> list[dict]:
    """
    Vad förarens "vilka län vill du ha notiser i?" får välja bland.

    Bara län där en kollektivtrafikkälla faktiskt finns kommer med. Att
    erbjuda Halland hade varit ett löfte vi inte kan hålla: källan 404:ar,
    och en förare som kryssat i länet hade tolkat tystnaden som "lugnt", inte
    som "vi hämtar inte här". `covered: False`-raderna listas separat av
    coverage_rows() ovan, med sitt skäl.
    """
    from core.geo import REGION_ANCHOR

    out = [
        {
            "key": RAIL_REGION_KEY,
            "label": "Järnväg (hela landet)",
            "city": "",
            "note": "Tåg saknar länsindelning i Trafikverkets data.",
        }
    ]
    for label, operator, _county in COUNTIES:
        if operator is None:
            continue
        key = "vt" if operator == "vt-adapter" else operator
        out.append(
            {
                "key": key,
                "label": label,
                "city": REGION_ANCHOR.get(key, ""),
                "note": "",
            }
        )
    return out


def uncovered_counties() -> list[str]:
    """Län utan kollektivtrafikkälla -- visas som en förklaring, inte som val."""
    return [label for label, operator, _ in COUNTIES if operator is None]


# Vägens länsnyckel i COUNTIES -> SCB:s länskod (core/areas.py).
_SCB_CODE = {
    "stockholm": "01", "uppsala": "03", "sodermanland": "04", "ostergotland": "05",
    "jonkoping": "06", "kronoberg": "07", "kalmar": "08", "gotland": "09",
    "blekinge": "10", "skane": "12", "halland": "13", "vastragotaland": "14",
    "varmland": "17", "orebro": "18", "vastmanland": "19", "dalarna": "20",
    "gavleborg": "21", "vasternorrland": "22", "jamtland": "23",
    "vasterbotten": "24", "norrbotten": "25",
}


def county_catalog() -> list[dict]:
    """
    Alla 21 län att välja körområde bland, med vad vi hämtar kollektivtrafik från.

    notify_region_catalog() erbjöd bara län med kollektivtrafikkälla, så
    Norrbotten, Västerbotten, Jämtland, Halland och Sörmland gick inte att välja
    trots att andra källor kan ha tips där. Ett län utan kollektivtrafikkälla
    väljs nu med öppna ögon: `transit` är None och `note` säger det.
    """
    from core.areas import COUNTY_NAMES

    out = []
    for _label, operator, road_key in COUNTIES:
        code = _SCB_CODE[road_key]
        if operator == "vt-adapter":
            transit = "Västtrafik"
        elif operator == "sl":
            transit = "SL"
        elif operator:
            transit = f"Trafiklab ({operator})"
        else:
            transit = None
        out.append({
            "code": code,
            "name": COUNTY_NAMES[code],
            "transit": transit,
            "note": "" if transit else "Ingen kollektivtrafikkälla i länet.",
        })
    return sorted(out, key=lambda c: c["code"])
