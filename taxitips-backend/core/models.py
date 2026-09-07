"""
Datamodellen för TaxiTips.

Rent Django-schema: den här appen äger sina tabeller och `makemigrations`
fungerar fullt ut. Kolumnnamnen speglar den befintliga Supabase-strukturen
med avsikt -- pipeline-viz och alla frågor jag skrivit under utredningen
fungerar oförändrat mot dem, och datan får ändå hämtas om från källorna.
"""

import uuid

from django.db import models


class SeverityTier(models.TextChoices):
    """
    Hur illa störningen är för någon som behöver ta sig hem.

    Ordningen är inte alfabetisk utan efter hur strandsatt resenären blir --
    det är den enda ordning som betyder något för en taxiförare.
    """

    LINE_PAUSED = "line_paused", "Hela linjen stoppad"
    VEHICLE_CANCELLED = "vehicle_cancelled", "Enstaka avgång inställd"
    LINE_DELAYED = "line_delayed", "Försening på linjen"
    VEHICLE_DELAYED = "vehicle_delayed", "Enstaka avgång försenad"
    ROAD_ACCIDENT_OR_CLOSURE = "road_accident_or_closure", "Olycka/avstängning"
    ROAD_WORK_OR_QUEUE = "road_work_or_queue", "Vägarbete/kö"
    ROAD_WORK = "road_work", "Vägarbete"
    DISRUPTION_UNCLASSIFIED = "disruption_unclassified", "Osäker bedömning"
    IGNORE = "ignore", "Ignoreras"


class Confidence(models.TextChoices):
    HIGH = "high", "Hög — tydligt i källdatan"
    MEDIUM = "medium", "Medel"
    LOW = "low", "Låg — osäker tolkning"


class TransportMode(models.TextChoices):
    TRAIN = "train", "Tåg"
    METRO = "metro", "Tunnelbana"
    TRAM = "tram", "Spårvagn"
    BUS = "bus", "Buss"
    ROAD = "road", "Väg"
    BOAT = "boat", "Båt"
    UNKNOWN = "unknown", "Okänt"


class ScoringRule(models.Model):
    """
    Poängtaken och -golven som data i stället för hårdkodade tal.

    Idag ligger de spridda i scoring.js (85, 70, 60, 55, 45, 25) och
    tröskeln 50 finns i fyra kopior över tre språk -- se
    schema/constants.md, som genereras av `dump_truth`. Att flytta hit dem
    är hela poängen med Django för det här projektet: reglerna blir
    läsbara, ändringsbara i admin, och möjliga att exportera så att app och
    viz läser samma sanning.

    `floor` och `cap` är avsiktligt separata: en stoppad linje har ett GOLV
    (minst så allvarligt), en inställd avgång har ett TAK (aldrig värre än
    så). Att blanda ihop dem är exakt det fel som gör att alla 27 tågtips
    får identiska 97 poäng idag.
    """

    tier = models.CharField(max_length=40, choices=SeverityTier.choices)
    mode = models.CharField(
        max_length=20,
        choices=TransportMode.choices,
        blank=True,
        help_text="Tomt = gäller alla färdsätt.",
    )
    condition = models.CharField(
        max_length=80,
        blank=True,
        help_text="Vilken gren i klassificeringen, t.ex. 'stated_alternative'.",
    )
    floor = models.IntegerField(
        null=True, blank=True, help_text="Poängen blir minst detta."
    )
    cap = models.IntegerField(
        null=True, blank=True, help_text="Poängen blir högst detta."
    )
    confidence = models.CharField(
        max_length=10, choices=Confidence.choices, default=Confidence.MEDIUM
    )
    note = models.TextField(blank=True, help_text="Varför regeln ser ut så här.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "scoring_rule"
        constraints = [
            models.UniqueConstraint(
                fields=["tier", "mode", "condition"], name="uniq_scoring_rule"
            )
        ]
        ordering = ["tier", "mode"]

    def __str__(self) -> str:
        bound = f"golv {self.floor}" if self.floor is not None else f"tak {self.cap}"
        scope = self.mode or "alla"
        return f"{self.tier}/{scope} → {bound}"

    def apply(self, score: int) -> int:
        """Applicerar golv/tak på en råpoäng."""
        if self.floor is not None:
            score = max(score, self.floor)
        if self.cap is not None:
            score = min(score, self.cap)
        return max(0, min(100, score))


class SourceEvent(models.Model):
    """
    Den råa händelsen från källan, orörd.

    Sparas som senast-kända-tillstånd (upsert på external_id), inte som
    logg -- det räcker för att kunna svara "vilken källhändelse gav det här
    tipset?" i förarens förklaringspanel, utan att växa obegränsat.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(
        max_length=40,
        db_index=True,
        help_text="trafikverket_rail, trafiklab, sl, vt, trafikverket, smhi",
    )
    external_id = models.TextField(unique=True)
    mode = models.CharField(max_length=20, blank=True)
    # db_default, inte auto_now_add: raderna skrivs med rå SQL (se
    # repository.py) och ORM:ets auto_now_add fyller bara i vid .save().
    fetched_at = models.DateTimeField(db_default=models.functions.Now())
    active_from = models.DateTimeField(null=True, blank=True)
    active_to = models.DateTimeField(null=True, blank=True)
    raw = models.JSONField(help_text="Payloaden precis som den kom.")
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=models.functions.Now())

    class Meta:
        db_table = "source_events"
        indexes = [models.Index(fields=["source", "active_to"])]

    def __str__(self) -> str:
        return f"{self.source}:{self.external_id}"


class Opportunity(models.Model):
    """
    Det bedömda tipset -- vad en förare faktiskt ser.

    VIKTIGT om `notified_at`: fältet skrivs BARA av push-steget. Django-ORM:s
    save() skriver hela raden och skulle nolla det vid varje uppdatering,
    vilket får push att tro att tipset aldrig notifierats -- och pusha om
    till varje förare varje minut. Därför skrivs opportunities via
    `upsert_opportunities()` i core/repository.py, som namnger sina
    kolumner explicit och aldrig rör notified_at. Använd inte .save() för
    pipeline-skrivningar.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_id = models.TextField(unique=True)

    kind = models.CharField(max_length=20, help_text="transit eller road")
    mode = models.CharField(
        max_length=20, choices=TransportMode.choices, blank=True, db_index=True
    )
    severity_tier = models.CharField(
        max_length=40,
        choices=SeverityTier.choices,
        default=SeverityTier.DISRUPTION_UNCLASSIFIED,
        db_index=True,
    )
    level = models.CharField(max_length=20, default="medium")

    title = models.TextField(blank=True)
    summary = models.TextField(blank=True)

    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    h3_index = models.CharField(max_length=20, blank=True, db_index=True)
    places = models.JSONField(default=list, blank=True)
    region = models.CharField(
        max_length=30,
        blank=True,
        db_index=True,
        help_text=(
            "Marknad: skane, sl, vt, rail... Bär geofencet för tips UTAN "
            "koordinat -- utan det nådde ett Stockholmstips en Malmöförare."
        ),
    )

    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True, db_index=True)

    demand_score = models.IntegerField(default=0)
    confidence = models.CharField(
        max_length=10, choices=Confidence.choices, default=Confidence.MEDIUM
    )
    reasons = models.JSONField(
        default=list, blank=True, help_text="Motiveringarna bakom poängen."
    )
    rule_id = models.CharField(
        max_length=80, blank=True, help_text="mode.tier, för spårbarhet."
    )
    source_event_ids = models.JSONField(default=list, blank=True)

    computed_at = models.DateTimeField(db_default=models.functions.Now())
    updated_at = models.DateTimeField(db_default=models.functions.Now())
    # Nullbar med avsikt: upserten rör den aldrig (den sätts när ett tips
    # löper ut), så en NOT NULL-kolumn skulle få varje skrivning att fela.
    expired_reason = models.CharField(max_length=60, blank=True, null=True)
    notified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Skrivs ENDAST av push-steget. Se klassdocstringen.",
    )

    class Meta:
        db_table = "opportunities"
        verbose_name_plural = "opportunities"
        indexes = [
            models.Index(fields=["end_time", "severity_tier"]),
            models.Index(fields=["lat", "lon"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(demand_score__gte=0, demand_score__lte=100),
                name="demand_score_0_100",
            )
        ]
        ordering = ["-demand_score"]

    def __str__(self) -> str:
        return f"[{self.demand_score}] {self.title[:60]}"

    @property
    def is_active(self) -> bool:
        from django.utils import timezone

        return bool(self.end_time and self.end_time > timezone.now())


class Station(models.Model):
    """
    Järnvägsstation från Trafikverkets register, med WGS84-koordinat.

    Koordinaten kommer som WKT "POINT (lon lat)" -- lon först. Läses den
    lat-först hamnar Motala i Indiska oceanen, så projektionen sker en gång
    här och aldrig i pipelinen.
    """

    signature = models.CharField(
        max_length=12, primary_key=True, help_text="LocationSignature, t.ex. 'Cst'."
    )
    name = models.CharField(max_length=120)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rail_station"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.signature})"


class StopArea(models.Model):
    """
    Hållplatsregister från SL och Västtrafik, hopslaget.

    Behövs för att geokoda tips vars text namnger en LOKAL hållplats
    ("Elektravägen", "Hässelby strand") som ingen ortlista täcker. Mätt:
    lyfte koordinattäckningen från ~12% till ~59%.

    Västtrafiks koordinater är SWEREF99TM i meter och projiceras till WGS84
    innan de sparas här.
    """

    OPERATOR_CHOICES = [("sl", "SL"), ("vt", "Västtrafik")]

    gid = models.CharField(max_length=40, primary_key=True)
    operator = models.CharField(max_length=4, choices=OPERATOR_CHOICES, db_index=True)
    name = models.CharField(max_length=160, db_index=True)
    lat = models.FloatField()
    lon = models.FloatField()
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stop_area"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.operator})"


class RailAssessment(models.Model):
    """
    Genkits granskning av ett tåg-tips.

    Sparas separat från Opportunity av två skäl: bedömningen ska kunna
    granskas i efterhand, och den får ALDRIG höja en poäng -- bara sänka.
    Ett falskt högt tips kostar en förare en bomresa; ett falskt lågt
    kostar ingenting.
    """

    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name="assessments"
    )
    cache_key = models.CharField(
        max_length=200,
        db_index=True,
        help_text=(
            "Normaliserad form: tier|mode|station|har_alternativ|timme. "
            "INTE titeln -- 28 av 28 tågtitlar är unika, cache på titel "
            "ger 0% träff."
        ),
    )
    rule_score = models.IntegerField(help_text="Vad regelverket gav.")
    model_score = models.IntegerField(help_text="Vad modellen föreslog.")
    final_score = models.IntegerField(help_text="min(rule, model) -- aldrig högre.")
    verdict = models.TextField(blank=True, help_text="Modellens motivering.")
    model_name = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rail_assessment"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.rule_score} → {self.final_score}"

    def save(self, *args, **kwargs):
        # Skyddsräcket i koden, inte bara i dokumentationen: en modell som
        # vill höja poängen ignoreras.
        self.final_score = min(self.rule_score, self.model_score)
        super().save(*args, **kwargs)
