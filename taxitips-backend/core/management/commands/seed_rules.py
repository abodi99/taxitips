"""
Fyller ScoringRule med taken och golven från scoring.js.

Detta är flytten som gör konstanterna till data. Efter den ska
schema/constants.md innehålla färre hårdkodade tal -- gör den inte det har
flytten inte skett på riktigt.
"""

from django.core.management.base import BaseCommand

from core.models import Confidence, ScoringRule, SeverityTier, TransportMode

# Exakt vad scoring.js gör idag, rad för rad. Porteras oförändrat så att
# Fas 2 kan verifieras mot samma utfall innan tågfixen ändrar något.
RULES = [
    dict(tier=SeverityTier.LINE_PAUSED, mode="", condition="whole_line_stop",
         floor=85, confidence=Confidence.HIGH,
         note="Stoppad linje utan nämnt alternativ. scoring.js:84"),
    dict(tier=SeverityTier.LINE_PAUSED, mode="", condition="ambiguous",
         floor=70, confidence=Confidence.LOW,
         note="Allvarligt ordval men otydligt. Hit hamnar ALLA tågtips idag "
              "-- därför får 27 av 27 identiska poäng. scoring.js:109"),
    dict(tier=SeverityTier.VEHICLE_CANCELLED, mode=TransportMode.TRAIN,
         condition="stated_alternative", cap=55, confidence=Confidence.MEDIUM,
         note="Inställd men alternativ finns. Tågen når aldrig hit idag: "
              "hasStatedAlternative() letar efter fraser Trafikverket aldrig "
              "skriver. scoring.js:90"),
    dict(tier=SeverityTier.VEHICLE_CANCELLED, mode=TransportMode.BUS,
         condition="serious", cap=60, confidence=Confidence.HIGH,
         note="Allvarlig bussstörning. scoring.js:122"),
    dict(tier=SeverityTier.LINE_DELAYED, mode="", condition="mediumish",
         cap=45, confidence=Confidence.HIGH,
         note="Tåg, medelallvarligt. scoring.js:114"),
    dict(tier=SeverityTier.VEHICLE_DELAYED, mode=TransportMode.BUS,
         condition="mediumish", cap=25, confidence=Confidence.HIGH,
         note="Buss några minuter sen. scoring.js:127"),
    dict(tier=SeverityTier.IGNORE, mode="", condition="",
         cap=0, confidence=Confidence.MEDIUM,
         note="Brus: hiss ur funktion, stängd toalett, cykelplatser."),
    # Flyg har ingen motsvarighet i scoring.js -- källan fanns inte då. Taket
    # håller ankomstvågen under en verkligt stoppad linje: att många landar
    # samtidigt är en stark efterfrågesignal, men till skillnad från ett
    # stoppat tåg vet vi inte att någon faktiskt står utan transport.
    dict(tier=SeverityTier.ARRIVAL_WAVE, mode=TransportMode.FLIGHT, condition="",
         cap=80, confidence=Confidence.MEDIUM,
         note="Ankomstvåg: N landningar i samma halvtimme, sen kväll. "
              "Tröskel per flygplats i core/thresholds.py:AIRPORTS."),
    # Lägre tak än vågen: ett plan är färre resenärer än åtta. Att det ändå
    # är ett tips beror på att ingen lämnar flygplatsen efter det.
    dict(tier=SeverityTier.LAST_ARRIVAL, mode=TransportMode.FLIGHT, condition="",
         cap=65, confidence=Confidence.MEDIUM,
         note="Sista ankomsten: inget mer plan landar inom två timmar. "
              "Gäller de åtta små flygplatserna, där en våg aldrig uppstår."),
]


class Command(BaseCommand):
    help = "Seedar poängreglerna från scoring.js"

    def handle(self, *args, **options):
        created = updated = 0
        for rule in RULES:
            _, was_created = ScoringRule.objects.update_or_create(
                tier=rule["tier"], mode=rule["mode"], condition=rule["condition"],
                defaults=rule,
            )
            created += was_created
            updated += not was_created
        self.stdout.write(self.style.SUCCESS(
            f"{created} nya, {updated} uppdaterade regler"
        ))
