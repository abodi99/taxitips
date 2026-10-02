"""
Fyller ScoringRule med taken och golven från scoring.js.

Detta är flytten som gör konstanterna till data. Efter den ska
schema/constants.md innehålla färre hårdkodade tal -- gör den inte det har
flytten inte skett på riktigt.
"""

from django.core.management.base import BaseCommand

from core.models import Confidence, ScoringRule, SeverityTier, TransportMode

# Lägespoängen för fritext som tak (core/text_scoring.py), inte golv: sedan
# 2026-10-02 räknar poängen läge + omständigheter (core/taxi_context.py), och
# en regelrad får skärpa ett läge men aldrig lyfta det. De gamla golven från
# scoring.js (85 för "hela linjen", 70 för "oklart") gjorde varje inställd
# SL-avgång till en Stark notis.
RULES = [
    dict(tier=SeverityTier.LINE_PAUSED, mode="", condition="whole_line_stop",
         floor=None, cap=70, confidence=Confidence.HIGH,
         note="Hela linjen står still, inget alternativ angivet. Strandsatt."),
    dict(tier=SeverityTier.LINE_PAUSED, mode="", condition="ambiguous",
         floor=None, cap=45, confidence=Confidence.LOW,
         note="Allvarligt ordval men varken 'hela linjen' eller 'en avgång' i klartext. "
              "Högst Medel tills det bekräftats."),
    dict(tier=SeverityTier.VEHICLE_CANCELLED, mode=TransportMode.TRAIN,
         condition="stated_alternative", floor=None, cap=25, confidence=Confidence.MEDIUM,
         note="Inställd men källan anvisar ett alternativ."),
    dict(tier=SeverityTier.VEHICLE_CANCELLED, mode=TransportMode.BUS,
         condition="serious", floor=None, cap=45, confidence=Confidence.HIGH,
         note="Bussen inställd utan klockslag: linjen eller en tur, oklart."),
    dict(tier=SeverityTier.LINE_DELAYED, mode="", condition="mediumish",
         floor=None, cap=30, confidence=Confidence.HIGH,
         note="Spårtrafik försenad."),
    dict(tier=SeverityTier.VEHICLE_DELAYED, mode=TransportMode.BUS,
         condition="mediumish", floor=None, cap=15, confidence=Confidence.HIGH,
         note="Buss några minuter sen."),
    dict(tier=SeverityTier.IGNORE, mode="", condition="",
         floor=None, cap=0, confidence=Confidence.MEDIUM,
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
    help = "Seedar poängreglerna (tak per läge, se core/text_scoring.py)"

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
