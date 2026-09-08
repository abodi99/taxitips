"""
Fyller RegionCompensationRule med lagstadgad förseningsersättning per län.

Källbelagd research, omgjord och utökad 2026-09-08 mot varje huvudmans egen
villkorssida -- se docs/transit-compensation-rules.md för fullständig källa,
ordagranna citat och rättelser mot föregående omgång. Samma "konstanter som
data"-flytt som seed_rules.py, av samma skäl: läsbart, ändringsbart i admin
utan att deploya, och beloppen (knutna till årets "prisbasbelopp") behöver
kunna uppdateras utan kodändring.

BELOPPEN GÄLLER 2026. Nästan alla huvudmän anger taket som 1/40 av
prisbasbeloppet för det år resan skulle ha avslutats (Skånetrafiken 1/20).
Prisbasbeloppet 2026 är 59 200 kr -> 1 480 kr respektive 2 960 kr. Vid
årsskiftet måste hela tabellen ses över; ett par huvudmän släpar dessutom
efter med sina egna publicerade siffror (Dalatrafik, Gotland, Hallandstrafiken).

Regionnycklarna är EXAKT core.geo.REGION_ANCHOR:s nycklar plus `dintur` --
de är redan vad alert["region"] sätts till i core/sources/{sl,vasttrafik,
trafiklab}.py (trafiklab.py skriver a["region"] = operatörskoden rakt av).

MEDVETET INTE SEEDADE: Halland, Södermanland, Jämtland, Västerbotten och
Norrbotten. Reglerna är researchade och dokumenterade i docs/, men pipelinen
hämtar inga händelser för dem (Trafiklab 404:ar på operatörskoderna, se
core/coverage.py:UNAVAILABLE_OPERATORS) och det finns därför ingen
regionnyckel att matcha mot. Att hitta på en nyckel här skulle bara ge en
rad som aldrig träffar.
"""

from django.core.management.base import BaseCommand

from core.models import RegionCompensationRule, TransportMode

RULES = [
    # Skånetrafiken -- ensam om 1/20 av prisbasbeloppet, dubbelt mot alla andra.
    # "Kostnaden för taxi ersätts med ett maximalt belopp som motsvarar 1/20 av
    # gällande prisbasbelopp. Nämnda maxbelopp gäller per betalande resenär."
    dict(region="skane", threshold_minutes=20, taxi_cap_kr=2960, filing_deadline_days=60,
         # per betalande resenär -- källan skriver det ordagrant.
         cap_per_person=True,
         source_url="https://www.skanetrafiken.se/sa-reser-du-med-oss/villkor/villkor-for-ersattning-vid-forsening/",
         note="1/20 av prisbasbeloppet (2026: 59 200 kr) = 2 960 kr, per betalande "
              "resenär. Samma villkor för buss, Pågatåg och Öresundståg. "
              "Reklamation inom två månader. Närtrafik/SkåneFlex omfattas men "
              "kräver blankett. Verifierad mot sidans egen text 2026-09-08."),

    # SL -- avviker med tre månaders reklamationsfrist, inte två.
    dict(region="sl", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=90,
         # 'Ersättningen blir inte högre om du samåker med någon annan'.
         cap_per_person=False,
         source_url="https://sl.se/kundservice/forseningsersattning",
         note="1/40 av prisbasbeloppet; sidan skriver ut 1 480 kronor för 2026. "
              "AVVIKANDE FRIST: 'Du måste reklamera resan inom 3 månader efter "
              "förseningen' -- därav 90 dagar. Taket gäller per resa: "
              "'Ersättningen blir inte högre om du samåker med någon annan.' "
              "Samma regler för buss, tunnelbana och pendeltåg. "
              "Källan bytt från sl.se/artikel/avsnitt-2 till den kanoniska "
              "kundservicesidan 2026-09-08."),

    # Västtrafik -- fast belopp, inte prisbasbeloppsformel.
    # cap_per_person lämnas None med avsikt: Västtrafiks egen sida skriver
    # både "1 500 kr per person" och "1 500 kr per bil oavsett antal
    # resenärer" om samma ersättning. Att välja en av dem hade varit att
    # gissa åt en förare som kan komma att citera siffran för en resenär.
    dict(region="vt", threshold_minutes=20, taxi_cap_kr=1500, filing_deadline_days=60,
         source_url="https://www.vasttrafik.se/kundservice/forseningsersattning/",
         note="Fast 1 500 kr/person för taxi (1 500 kr per bil oavsett antal "
              "resenärer), inte prisbasbeloppsformel. Samma villkor för buss, "
              "spårvagn, tåg och båt. Reklamation inom två månader. "
              "Undantar färdtjänst, riksfärdtjänst, skolskjuts, förbeställda "
              "sjukresor, abonnerad trafik, museispårvagnar och sightseeingbussar "
              "-- inget av det fångas av excluded_modes, som bara känner färdsätt."),

    dict(region="ul", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         source_url="https://www.ul.se/kundservice/forseningsersattning/",
         note="'Vi ersätter dig då för utlägg upp till 1480 kronor.' Två månader. "
              "Undantar planerade störningar annonserade minst tre dagar i "
              "förväg och byten som inte är en anslutning i UL:s reseplanerare. "
              "Dricks ersätts inte."),

    # Östgötatrafiken -- URL flyttad sedan förra omgången.
    dict(region="otraf", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         # maxbeloppet per person mot delat taxameterkvitto.
         cap_per_person=True,
         source_url="https://www.ostgotatrafiken.se/kontakt-och-hjalp/forseningsersattning",
         note="'Då kan du få ersättning upp till 1 480 kronor (1/40-del av "
              "gällande prisbasbelopp).' Vid delad taxi betalas maxbeloppet per "
              "person mot delat taxameterkvitto. Reklamation inom två månader, "
              "kvitton kan kompletteras inom fyra månader. Skolbiljetten ger "
              "bara prisavdrag. OBS: 20-minuterströskeln är utskriven för "
              "prisavdraget; taxistycket säger bara 'på grund av förseningen' -- "
              "samma tröskel är rimlig men inte ordagrant bekräftad."),

    dict(region="klt", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         # per resenär, får summeras vid samåkning.
         cap_per_person=True,
         source_url="https://kalmarlanstrafik.se/Kundservice/ansok-om-forseningsersattning/",
         note="'För 2026 är högsta belopp 1 480 kronor.' Maxbeloppet gäller per "
              "resenär och får summeras vid samåkning. Taxameterkvitto i "
              "original krävs. Två månader, senare vid särskilda skäl. "
              "Ingen ersättning om störningen publicerats minst tre dygn i förväg."),

    # Värmlandstrafik -- ovanlig kombination: anropsstyrd trafik OMFATTAS,
    # båtbusstrafiken gör det inte. Därav boat i excluded_modes.
    dict(region="varm", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         excluded_modes=[TransportMode.BOAT],
         source_url="https://www.varmlandstrafik.se/varmlandstrafik/kundservice/forseningsersattning",
         note="'Maximalt belopp som vi ersätter för utlägg för taxi eller egen "
              "bil är 1/40 av prisbasbeloppet, för närvarande 1 480 kr.' Gäller "
              "bussar, tåg OCH anropsstyrd trafik i länet -- men "
              "'Båtbusstrafiken omfattas inte av förseningsersättningen', "
              "därav excluded_modes=[boat]. Två månader. Dricks ersätts inte."),

    dict(region="krono", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         source_url="https://lanstrafikenkron.se/forseningsersattning",
         note="'Högsta ersättningsbeloppet är 1 480 kronor vid kontant "
              "utbetalning' (värdekod ger +10 %). Taxameterkvitto i original "
              "krävs; handskrivna kvitton och kontokortskvitton godkänns ej. "
              "Två månader. Ingen ersättning vid störning annonserad tre dygn "
              "i förväg."),

    dict(region="jlt", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         # 'Maxbeloppet gäller per person'.
         cap_per_person=True,
         source_url="https://www.jlt.se/kundservice/forseningsersattning/",
         note="'För år 2026 är högsta ersättningsbeloppet 1 480 kronor.' "
              "Maxbeloppet gäller per person, så samåkande kan tillsammans åka "
              "längre. Två månader. Skriver själva ut gränsdragningen: under "
              "15 mil lag 2015:953, över 15 mil EU 2021/782."),

    # Örebro -- URL flyttad sedan förra omgången.
    dict(region="orebro", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         source_url="https://www.lanstrafiken.se/kundservice/forsenad-och-kvarglomd/vad-galler-for-forseningsersattning/",
         note="'Har du valt att ta en taxi så ersätter vi dig upp till högst "
              "1480 kronor.' Två månader. Taxitaket är lika för buss och tåg; "
              "det som skiljer är hur periodbiljettens värde räknas "
              "(30-dagars delas på 36 för buss, 22 för tåg) -- påverkar "
              "prisavdraget, inte taxin."),

    # Blekingetrafiken -- fristen är nu BEKRÄFTAD, till skillnad från
    # föregående omgång som flaggade den som obekräftad.
    dict(region="blekinge", threshold_minutes=20, taxi_cap_kr=1500, filing_deadline_days=60,
         # per resenär, får summeras vid samåkning.
         cap_per_person=True,
         source_url="https://www.blekingetrafiken.se/kundservice/forseningsersattning/",
         note="Fast 1 500 kr per resenär, får summeras vid samåkning mot delat "
              "kvitto. Fristen är BEKRÄFTAD 2026-09-08 i Resevillkor för "
              "kollektivtrafiken i södra Sverige: 'En reklamation som lämnas "
              "inom två (2) månader ... ska dock alltid anses ha lämnats i rätt "
              "tid.' (Var felaktigt flaggad som obekräftad i föregående "
              "version.) Färdtjänst/Närtrafik har en egen 10-minutersregel."),

    # Dalatrafik -- operatören motsäger sig själv. Vi tar det LÄGRE av de två
    # publicerade beloppen, aldrig formelbeloppet, för att inte lova en förare
    # mer än vad huvudmannen själv skrivit ut för just taxi.
    dict(region="dt", threshold_minutes=20, taxi_cap_kr=1470, filing_deadline_days=60,
         source_url="https://www.dalatrafik.se/kundservice/vanliga-arenden/forsenad-eller-utebliven-tur/",
         note="MOTSTRIDIG KÄLLA: FAQ-sidan säger 'Högsta ersättning för resa "
              "med taxi är 1470 kronor per resenär' men samtidigt 1480 kronor "
              "för egen bil, medan resevillkoren (punkt 22.1) anger 1/40 av "
              "prisbasbeloppet = 1 480 kr för 2026. Taxisiffran ser ut att vara "
              "kvarglömd från 2025. Vi seedar 1 470 -- det lägre publicerade "
              "beloppet. Kontrollera efter årsskiftet. "
              "Fristen är BEKRÄFTAD (var obekräftad tidigare): resevillkoren "
              "säger 'senast två månader efter att händelsen inträffade'. "
              "Separata villkorspunkter för buss (22.1) och tåg (22.2), men "
              "samma tröskel och samma tak."),

    # X-trafik -- den enda huvudmannen som helt nekar taxi vid tågförsening.
    dict(region="xt", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         # '1480 kr per resa'.
         cap_per_person=False,
         excluded_modes=[TransportMode.TRAIN],
         source_url="https://xtrafik.se/forseningsersattning",
         note="Buss: 'Den högsta ersättningen du kan få är 1480 kr per resa.' "
              "Tåg: 'Ersättning ges inte för taxi eller resa med egen bil.' "
              "Motiveringen på sidan är att båda deras tåglinjer "
              "(Gävle-Ljusdal, Gävle-Sundsvall) är längre än 15 mil och därmed "
              "lyder under EU 2021/782, som bara ersätter ersättningsresa med "
              "tåg eller buss -- inte taxi. Två månader."),

    dict(region="vastmanland", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         source_url="https://vl.se/biljetter/villkor-och-ersattning/forseningsersattning/",
         note="HÄRLETT BELOPP: villkoren (punkt 7.1/7.3) anger bara formeln "
              "'1/40 av det prisbasbelopp ... som gäller för det år då resan "
              "skulle ha avslutats' och hänvisar till vl.se för aktuellt tal. "
              "1 480 kr är den formeln tillämpad på 2026 års prisbasbelopp "
              "(59 200 kr), inte en siffra som står på sidan. "
              "Ansökan senast två månader efter händelsen (punkt 7.6). "
              "Skolkort/avgiftsfri linje ger bara ersättning för annan "
              "transport, inget prisavdrag."),

    dict(region="gotland", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         source_url="https://gotland.se/trafik-gator-och-parker/kollektivtrafik/vanliga-fragor-om-kollektivtrafiken/forseningsersattning",
         note="HÄRLETT BELOPP: sidan anger regeln som '1/40 av prisbasbeloppet "
              "enligt 2 kap. 7 § socialförsäkringsbalken' men exemplifierar "
              "fortfarande med 2024 års 1 432,50 kr, trots sidfotens "
              "'Senast uppdaterad 9 juni 2026'. 1 480 kr är deras egen formel "
              "för 2026. Begäran inom två månader. Endast busstrafik (det "
              "finns ingen tågtrafik på Gotland). Undantar närtrafik, "
              "skolskjuts, färdtjänst och förbeställda sjukresor -- fångas "
              "inte av excluded_modes."),

    # Din Tur (Västernorrland) -- ny rad. `dintur` är Trafiklabs operatörskod
    # och därmed vad trafiklab.py sätter som alert["region"].
    dict(region="dintur", threshold_minutes=20, taxi_cap_kr=1480, filing_deadline_days=60,
         excluded_modes=[TransportMode.TRAIN],
         source_url="https://www.dintur.se/det-har-galler-for-ersattning-vid-forsening/",
         note="'Den högsta ersättning du kan få är 1/40 av prisbasbeloppet "
              "enligt Socialförsäkringsbalken (1480 kronor 2026).' "
              "OBEKRÄFTAD ANSÖKNINGSFRIST: sidan säger bara 'skicka in din "
              "ansökan om ersättning så snart som möjligt'. 60 dagar är satt "
              "som branschmönster, INTE en verifierad Din Tur-siffra. "
              "excluded_modes=[train] eftersom villkoren uttryckligen gäller "
              "'alla Din Turs busslinjer' -- Din Tur kör inga tåg, Norrtåg har "
              "egna villkor. Linje 40 (Örnsköldsvik-Östersund) är över 15 mil "
              "och har 120-minutersgräns i stället för 20; det fångas inte av "
              "threshold_minutes, som är per region. Ungdoms- och skolbiljett "
              "undantagna. Taxi får bara beställas mellan hållplatser bussen "
              "trafikerar."),
]


class Command(BaseCommand):
    help = "Seedar lagstadgad förseningsersättning per län (lag 2015:953)"

    def handle(self, *args, **options):
        created = updated = 0
        for rule in RULES:
            rule.setdefault("excluded_modes", [])
            _, was_created = RegionCompensationRule.objects.update_or_create(
                region=rule["region"], defaults=rule,
            )
            created += was_created
            updated += not was_created
        self.stdout.write(self.style.SUCCESS(
            f"{created} nya, {updated} uppdaterade ersättningsregler"
        ))
