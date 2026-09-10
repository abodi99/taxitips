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


class RegionCompensationRule(models.Model):
    """
    Lagstadgad förseningsersättning (lag 2015:953 om kollektivtrafik-
    resenärers rättigheter), en rad per län/operatör -- källbelagd research,
    se docs/transit-compensation-rules.md för alla källor.

    Gäller bara textkällorna (SL/Västtrafik/Trafiklab) -- se
    core/compensation.py:s docstring för varför Trafikverkets järnvägsdata
    medvetet är utanför scope (inget regionfält, och blandar regionala
    korttåg med fjärrtåg som lyder under andra EU-regler).
    """

    region = models.CharField(
        max_length=30, unique=True,
        help_text="Samma nyckel som core.geo.REGION_ANCHOR: skane, sl, vt, ul, ...",
    )
    threshold_minutes = models.IntegerField(
        default=20, help_text="Minuter försening som ger rätt till ersättning."
    )
    taxi_cap_kr = models.IntegerField(
        help_text="Högsta ersättning för taxi/alternativ transport, i kronor."
    )
    excluded_modes = models.JSONField(
        default=list, blank=True,
        help_text="Färdsätt där taxi INTE ersätts (t.ex. X-trafik: [\"train\"]).",
    )
    filing_deadline_days = models.IntegerField(
        default=60, help_text="Frist för att ansöka, i dagar."
    )
    cap_per_person = models.BooleanField(
        null=True, blank=True,
        help_text=(
            "Gäller taket per resenär (True) eller per resa/bil (False)? "
            "NULL = källan säger inget, och då påstår vi inget heller. "
            "Skillnaden är stor för en förare: Skånetrafikens 2 960 kr "
            "gäller PER betalande resenär, medan SL uttryckligen skriver "
            "att beloppet inte blir högre om man samåker -- fyra strandsatta "
            "resenärer är två helt olika affärer i de två fallen."
        ),
    )
    source_url = models.TextField(blank=True)
    note = models.TextField(
        blank=True, help_text="Flaggar osäkra/obekräftade siffror -- se docs/.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "region_compensation_rule"
        ordering = ["region"]

    def __str__(self) -> str:
        return f"{self.region}: {self.threshold_minutes} min → {self.taxi_cap_kr} kr"


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
        null=True,
        db_index=True,
        help_text=(
            "Marknad: skane, sl, vt, rail... Bär geofencet för tips UTAN "
            "koordinat -- utan det nådde ett Stockholmstips en Malmöförare. "
            "NULL, aldrig tom sträng, när marknaden är okänd: get_smart_alerts "
            "gör coalesce(region,'skane') för platslösa tips, och '' hade "
            "matchat ingen marknad alls -- tipset hade försvunnit tyst."
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

    # Lagstadgad förseningsersättning -- se core/compensation.py. Rör bara
    # aldrig demand_score/severity_tier, samma princip som SL/VT:s
    # redaktionella signal i text_scoring.py: mäter något annat än hur
    # allvarlig störningen är.
    compensation_eligible = models.BooleanField(default=False)
    compensation_amount_kr = models.IntegerField(null=True, blank=True)
    compensation_per_person = models.BooleanField(
        null=True, blank=True,
        help_text="Gäller taket per resenär? NULL = huvudmannen skriver inte ut det.",
    )

    # Transport Gap, som data i stället för prosa. Järnvägspipelinen har
    # räknat fram båda sedan Fas 2, men de överlevde bara som en mening i
    # `reasons` ("nästa avgång först om 322 min") -- omöjlig att filtrera,
    # sortera eller mäta på. Det är skillnaden mellan att en signal FINNS
    # och att den går att använda: Last Departure Risk och Transport Gap
    # (P1) kan inte kalibreras mot en textrad.
    #
    # NULL betyder "vet inte", inte "ingen lucka": bara källor med
    # tidtabell (Trafikverkets järnväg idag) kan svara på frågan. En
    # textkälla som SL vet aldrig när nästa buss går.
    next_departure_minutes = models.IntegerField(
        null=True, blank=True, db_index=True,
        help_text="Minuter till nästa avgång, mätt när tipset skrevs. NULL = okänt.",
    )
    next_departure_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            "Absolut tidpunkt för nästa avgång. Den som visas för föraren: "
            "minuterna ovan mättes vid pollningen och åldras med tipset, "
            "klockslaget gör inte det."
        ),
    )
    is_last_departure = models.BooleanField(
        default=False,
        help_text="Sista avgången härifrån idag -- ingen kommer efter.",
    )
    has_alternative = models.BooleanField(
        default=False,
        help_text="Källan anger ersättningstrafik eller annan väg vidare.",
    )
    alternative_note = models.TextField(
        blank=True,
        help_text=(
            "Vad källan säger om alternativet, i källans egna ord. Tomt när "
            "inget angetts -- vi hittar aldrig på ett alternativ: en förare "
            "som kör till en perrong där ersättningsbussen redan står gör "
            "en bomresa."
        ),
    )

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
    site_id = models.CharField(
        max_length=20, blank=True, db_index=True,
        help_text=(
            "SL:s site-id, ett ANNAT id-rum än gid (som är stop_area-id). "
            "Behövs för /v1/sites/{site_id}/departures, som är enda vägen "
            "till 'när går nästa buss' i Stockholm. Tomt för Västtrafik."
        ),
    )
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
    Genkits granskning av ett tips.

    Sparas separat från Opportunity så bedömningen kan granskas i
    efterhand. För confidence=low (omklassning) får final_score vara
    modellens poäng även om den är högre än regelns -- regelverket har
    redan sagt att det inte vet. För övriga anrop gäller fortfarande
    min(rule, model).
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
    final_score = models.IntegerField(
        help_text="Omklassning: model_score. Dämpning: min(rule, model)."
    )
    verdict = models.TextField(blank=True, help_text="Modellens motivering.")
    model_name = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rail_assessment"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.rule_score} → {self.final_score}"

    def save(self, *args, **kwargs):
        # Omklassning (confidence=low) sätter _allow_reclassify och får
        # använda modellens poäng rakt av. Övriga anrop får bara sänka.
        if getattr(self, "_allow_reclassify", False):
            self.final_score = max(0, min(100, int(self.model_score)))
        else:
            self.final_score = min(self.rule_score, self.model_score)
        super().save(*args, **kwargs)


class OpportunityFeedback(models.Model):
    """
    Förarens svar på ett tips: 🚕 "kör dit", 👍 "fick körning", 👎 "dött".

    Egen tabell i stället för Supabases `alert_feedback`, och det är en
    rättning, inte en dubblering: `alert_feedback.alert_id` har en
    främmande nyckel mot `alerts(id)`, medan appen sedan flytten till
    `opportunities` skickar ett opportunity-id. De två id-rymderna
    överlappar inte i en enda rad (mätt: 0 av 4345), så VARJE tumme upp
    sedan dess har avvisats av databasen -- tyst, i en try/catch som
    returnerar `{'error': ...}` och inget mer. Tabellen har noll rader.

    Den här nyckeln pekar på det tipset faktiskt är. Utan verklig feedback
    finns inget att kalibrera poängen mot, och hela P1-raden "🚕 / 👍 / 👎
    feedback capture" är en tom tabell.
    """

    class Verdict(models.TextChoices):
        HEADING = "heading", "Kör dit"
        FARE = "fare", "Fick körning"
        EMPTY = "empty", "Ingen kund"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name="feedback"
    )
    device_token = models.TextField(db_index=True)
    verdict = models.CharField(max_length=10, choices=Verdict.choices)
    created_at = models.DateTimeField(db_default=models.functions.Now())

    class Meta:
        db_table = "opportunity_feedback"
        ordering = ["-created_at"]
        constraints = [
            # En förare kan mena både "kör dit" och senare "fick körning"
            # om samma tips -- men samma omdöme två gånger är en
            # dubbeltryckning, inte två observationer.
            models.UniqueConstraint(
                fields=["opportunity", "device_token", "verdict"],
                name="uniq_feedback_per_device_verdict",
            )
        ]

    def __str__(self) -> str:
        return f"{self.verdict} · {self.opportunity_id}"


class SourceStatus(models.Model):
    """
    Senaste hämtningen per källa -- se core/health.py för varför.

    `ok=False` med ett meddelande är det enda som skiljer "källan svarade
    att allt är lugnt" från "källan svarade inte alls". Utan raden är de
    två tillstånden identiska i databasen.
    """

    source = models.CharField(
        max_length=40, primary_key=True,
        help_text="trafikverket_rail, trafiklab, sl, vt, trafikverket, smhi",
    )
    ok = models.BooleanField(default=True)
    message = models.TextField(blank=True)
    events = models.IntegerField(default=0, help_text="Antal larm källan gav.")
    written = models.IntegerField(default=0, help_text="Antal tips som skrevs.")
    duration_ms = models.IntegerField(default=0)
    detail = models.JSONField(
        default=dict, blank=True,
        help_text=(
            "Utfall per delkälla, när källan har flera. Trafiklab pollar "
            "femton regionala operatörer och en av dem kan 404:a utan att "
            "hämtningen som helhet misslyckas -- utan det här fältet syns "
            "bara summan, och en region som tyst försvunnit ser ut som en "
            "region utan störningar."
        ),
    )
    checked_at = models.DateTimeField()

    class Meta:
        db_table = "source_status"
        verbose_name_plural = "source statuses"
        ordering = ["source"]

    def __str__(self) -> str:
        return f"{self.source}: {'ok' if self.ok else 'FEL'} ({self.checked_at:%H:%M})"

    @property
    def age_minutes(self) -> int:
        from django.utils import timezone

        return int((timezone.now() - self.checked_at).total_seconds() // 60)


class PushDelivery(models.Model):
    """
    En skickad notis, per enhet -- notishistoriken appen visar, och pushens
    egen dubblettspärr.

    Varför en rad per enhet och inte bara `opportunities.notified_at`:
    `notified_at` svarar på "har det här tipset pushats alls?" och är det
    enda push-steget får skriva på tipsraden (se Opportunity-docstringen).
    Den kan däremot inte svara på förarens fråga -- "vilka notiser har JAG
    fått?" -- och utan det svaret finns ingen lista att markera favoriter i.

    `snapshot` är hela tipset som det såg ut när notisen gick. Utan den
    tömmer `purge_old` (sju dagar) notishistoriken bakvägen: raden finns
    kvar men pekar på ett borttaget tips, och listan visar tomma kort.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
        help_text="NULL efter att tipset gallrats -- snapshot bär innehållet.",
    )
    # Egen kolumn, inte bara FK:n: identiteten måste överleva gallringen,
    # och det är den nyckel dubblettspärren nedan jämför på.
    opportunity_external_id = models.TextField(db_index=True)

    # devices ägs av Supabase (billing/models.py, managed=False) -- ingen FK
    # över den gränsen, samma linje som core/entitlement.py håller.
    device_id = models.UUIDField(db_index=True)
    device_token = models.TextField(blank=True, db_index=True)

    title = models.TextField(blank=True)
    body = models.TextField(blank=True)
    snapshot = models.JSONField(
        default=dict, blank=True, help_text="Tipset som det såg ut när notisen gick."
    )

    ok = models.BooleanField(default=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(db_default=models.functions.Now())

    class Meta:
        db_table = "push_delivery"
        verbose_name_plural = "push deliveries"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["device_token", "-created_at"])]
        constraints = [
            # Samma tips, samma enhet, en gång. Skyddar mot en cykel som
            # hinner skicka men dör innan notified_at hunnit skrivas --
            # utan den får föraren notisen igen vid nästa varv.
            models.UniqueConstraint(
                fields=["device_id", "opportunity_external_id"],
                name="uniq_push_per_device_opportunity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.title[:40]} → {self.device_id}"


class OpportunityFavorite(models.Model):
    """
    Ett tips föraren sparat. Visas ALLTID, oavsett vad filtren säger.

    Hela poängen är att överleva de tre saker som annars tar bort ett tips ur
    vyn: filtren i appen, marknadsradien, och att störningen tar slut. Ett
    sparat tips är ett aktivt val -- "jag vill kunna gå tillbaka till det
    här" -- och ett filter som föraren råkar ha kvar sedan förra passet ska
    inte kunna gömma det.

    `owner_key` i stället för `device_token`: entitlement har TVÅ vägar
    (invariant 6 i AGENTS.md). En ägare som loggat in med e-post har ingen
    förartoken alls, och en favoritlista nycklad enbart på device_token hade
    varit tyst tom för varje sådan inloggning -- inklusive i webbläsaren,
    som är där det här först provas. Se `owner_key_for()` i core/api.py.

    `snapshot` av samma skäl som i PushDelivery: `purge_old` tar bort tipset
    efter sju dagar, och en favoritlista som tömmer sig själv är värre än
    ingen favoritlista.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_key = models.TextField(
        db_index=True,
        help_text="Förarens device-token, eller 'user:<uuid>' för inloggad ägare.",
    )
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="favorites",
    )
    opportunity_external_id = models.TextField(db_index=True)
    snapshot = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True, help_text="Förarens egen anteckning.")
    created_at = models.DateTimeField(db_default=models.functions.Now())

    class Meta:
        db_table = "opportunity_favorite"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner_key", "-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["owner_key", "opportunity_external_id"],
                name="uniq_favorite_per_owner",
            )
        ]

    def __str__(self) -> str:
        return f"★ {self.opportunity_external_id}"
