"""
Fartygen AISStream rapporterar, som senast kända läge per fartyg.

En rad per MMSI, inte en rad per ankomst -- samma avvägning som
core.SourceEvent. Frågan raden svarar på är "var är färjan nu, och har vi
redan tipsat om det här anlöpet?". Historiken per ankomst finns i
source_events/opportunities, där varje ankomst får ett eget external_id.

Bara passagerarfartyg (AIS-typ 60-69) sparas. Skärgårdsbåtar ingår -- de är
passagerarfartyg -- men blir aldrig tips; se längdgränsen i maritime/tips.py.
"""

from __future__ import annotations

from django.db import models


class FerryArrival(models.Model):
    mmsi = models.BigIntegerField(unique=True)
    ship_name = models.CharField(max_length=100, blank=True)
    ship_type = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="AIS ShipType. NULL tills fartygets ShipStaticData hörts.",
    )
    length_m = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Dimension A+B. Det enda i AIS som säger något om hur stor färjan är.",
    )
    destination = models.CharField(max_length=40, blank=True, help_text="Fritext från besättningen.")

    port_name = models.CharField(
        max_length=60, blank=True, db_index=True,
        help_text="Hamnrutan fartyget senast sågs i (maritime/ports.py). Tom = utanför alla.",
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    speed_knots = models.FloatField(null=True, blank=True, help_text="SOG. NULL = fartygets AIS säger 'saknas'.")
    nav_status = models.PositiveSmallIntegerField(null=True, blank=True, help_text="5 = förtöjd, 1 = ankrad.")
    eta = models.DateTimeField(
        null=True, blank=True,
        help_text="AIS-ETA mot fartygets nästa destination. NULL när den saknas eller är inaktuell.",
    )
    timestamp = models.DateTimeField(null=True, blank=True, help_text="Senaste positionens AIS-tid.")

    was_underway = models.BooleanField(
        default=False,
        help_text="Setts i fart under det här anlöpet. Krävs för att inbromsning ska räknas som ankomst.",
    )
    is_processed = models.BooleanField(
        default=False, db_index=True,
        help_text="Ankomsten är redan hanterad. Släpps när färjan avgår eller varit tyst i tre timmar.",
    )
    triggered_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ferry_arrivals"
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        where = self.port_name or "utanför hamnarna"
        return f"{self.ship_name or self.mmsi} ({where})"


class AisVessel(models.Model):
    """
    Alla fartyg AISStream hört i hamnrutorna, oavsett typ, som senast kända läge.

    Pipeline-sidans karta läser härifrån. FerryArrival ovan är den smala
    tabellen för ankomstlogiken och rymmer bara passagerarfartyg; den här
    visar vad som faktiskt rör sig i hamnarna -- lastfartyg, bogserbåtar,
    fritidsbåtar -- så att det går att se vad filtret sorterar bort.

    Klass A (större fartyg, PositionReport/ShipStaticData) och klass B
    (mindre, StandardClassBPositionReport/StaticDataReport) hamnar i samma
    rad. Skrivs i klump av lyssnaren varje minut, inte per meddelande.
    """

    mmsi = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=100, blank=True)
    call_sign = models.CharField(max_length=10, blank=True)
    imo = models.PositiveIntegerField(null=True, blank=True)
    ship_type = models.PositiveSmallIntegerField(null=True, blank=True, help_text="AIS ShipType. NULL tills statisk data hörts.")
    ais_class = models.CharField(max_length=1, blank=True, help_text="A eller B, efter vilken meddelandetyp fartyget sänder.")
    length_m = models.PositiveSmallIntegerField(null=True, blank=True)
    width_m = models.PositiveSmallIntegerField(null=True, blank=True)
    draught_m = models.FloatField(null=True, blank=True)
    destination = models.CharField(max_length=40, blank=True)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    speed_knots = models.FloatField(null=True, blank=True)
    course = models.FloatField(null=True, blank=True, help_text="COG i grader. NULL = saknas (360).")
    heading = models.PositiveSmallIntegerField(null=True, blank=True, help_text="TrueHeading. NULL = saknas (511).")
    nav_status = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Bara klass A och långdistans-AIS sänder den.")
    port_name = models.CharField(max_length=60, blank=True, db_index=True)

    last_message_type = models.CharField(max_length=40, blank=True)
    messages = models.PositiveIntegerField(default=0)
    position_at = models.DateTimeField(null=True, blank=True, db_index=True)
    static_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ais_vessels"
        ordering = ["-position_at"]

    def __str__(self) -> str:
        return f"{self.name or self.mmsi} ({self.ais_class or '?'})"


class FerryCall(models.Model):
    """
    Ett anlöp i AIS-piloten (P1): förutsagd kajtid mot faktisk.

    Underlaget för att kalibrera iland-fönstret och avgöra om förvarningen håller:
    hur långt före kaj den första uppskattningen kom, och hur fel den sista var.
    Se maritime/pilot.py och run_ais_pilot.
    """

    call_id = models.CharField(max_length=80, unique=True)
    mmsi = models.BigIntegerField(db_index=True)
    ship_name = models.CharField(max_length=100, blank=True)
    terminal = models.CharField(max_length=30, help_text="Nyckel i maritime.register.TERMINALS.")
    started_at = models.DateTimeField(help_text="Första positionen i bufferten när fartyget sågs närma sig.")
    berth_eta = models.DateTimeField(null=True, blank=True, help_text="Senaste uppskattade kajtid.")
    eta_basis = models.CharField(max_length=10, blank=True, help_text="distance eller ais_eta -- aldrig en blandning.")
    distance_km = models.FloatField(null=True, blank=True)
    first_estimate_at = models.DateTimeField(null=True, blank=True)
    first_berth_eta = models.DateTimeField(null=True, blank=True)
    estimates = models.JSONField(default=list, blank=True, help_text="Uppskattningar som ändrats minst två minuter.")
    arrived_at = models.DateTimeField(null=True, blank=True, help_text="Vid kaj enligt AIS: i terminalrutan under 1 knop.")
    tip_external_id = models.CharField(max_length=160, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ferry_calls"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.ship_name or self.mmsi} -> {self.terminal} ({self.berth_eta or '?'})"


class FerryTimetableCall(models.Model):
    """
    Ett planerat anlöp för en färja, ur GTFS Sverige 3 statisk -- se maritime/timetable.py.

    Härlett: ersätts för de trafikdagar som importeras. Trafiklab har ingen realtid för
    färjorna, så tiderna är planerade; läget kommer från AIS.
    """

    service_date = models.DateField(db_index=True)
    trip_id = models.CharField(max_length=40)
    agency = models.CharField(max_length=100)
    route_name = models.CharField(max_length=100, blank=True)
    stop_id = models.CharField(max_length=40)
    stop_name = models.CharField(max_length=120)
    lat = models.FloatField()
    lon = models.FloatField()
    sequence = models.PositiveIntegerField()
    arrival_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Tom på turens första anlöp.")
    departure_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Tom på turens sista anlöp.")
    origin_name = models.CharField(max_length=120)
    destination_name = models.CharField(max_length=120)
    stop_has_road = models.BooleanField(
        default=True,
        help_text="Buss, spårvagn eller tåg inom 400 m enligt samma GTFS-fil. Nej = troligen en ö utan bilväg.",
    )
    imported_at = models.DateTimeField()

    class Meta:
        db_table = "ferry_timetable_calls"
        indexes = [models.Index(fields=["stop_id", "arrival_at"], name="ferry_tt_stop_arrival_idx")]

    def __str__(self) -> str:
        return f"{self.stop_name} {self.arrival_at or self.departure_at} ({self.agency})"
