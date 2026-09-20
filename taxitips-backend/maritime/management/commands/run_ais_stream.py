"""
Lyssnar på AISStream.io och gör passagerarfärjor som lägger till i svenska
hamnar till tips.

Kör lokalt
----------
Postgres från `supabase start` måste vara igång, och AISSTREAM_API_KEY stå i
taxitips-backend/.env.

    python manage.py migrate maritime
    python manage.py run_ais_stream                  # kör tills Ctrl-C
    python manage.py run_ais_stream --duration 600   # tio minuter, avsluta sedan
    python manage.py run_ais_stream -v 2             # logga varje position
    python manage.py run_ais_stream --dry-run        # spara fartyg, skriv inga tips

Läget syns på pipeline-sidan (källan "AISStream fartyg") och i tabellen
source_status, raden `aisstream`, som skrivs varje minut.

Produktion på Coolify
---------------------
Det här är en långlivad process med en öppen WebSocket, inte ett Celery-jobb.
Beat kan inte hålla en ström öppen, och en hämtning var femte minut hade
missat just det ögonblick färjan saktar in. Kör den som en EGEN tjänst:

1. Ny Application i Coolify från samma repo och samma Dockerfile
   (taxitips-backend/), bredvid web, worker och beat.
2. Miljövariabler: APP_ROLE=ais, AISSTREAM_API_KEY, DATABASE_URL (samma som
   web). Dockerfilens CMD startar `python manage.py run_ais_stream` när
   APP_ROLE=ais -- samma rollväxel som worker och beat, av samma skäl:
   Coolifys start_command skriver ibland över CMD.
3. Ingen domän och ingen port: tjänsten svarar inte på HTTP. Stäng av
   Coolifys HTTP-healthcheck för den. Hälsan syns i stället i source_status
   och på pipeline-sidan; en rad äldre än tio minuter betyder att processen
   är död, inte att hamnarna är tomma.
4. EN instans. AISStream tillåter tre anslutningar per nyckel, och två
   lyssnare mot samma databas skriver varje ankomst två gånger. En lokal
   körning med samma nyckel räknas också mot de tre.
5. Migrationen körs av web-deployen (`manage.py migrate`). Den lägger bara
   till tabellen ferry_arrivals, men ta pg_dump först ändå -- CLAUDE.md.

Docker Compose: tjänsten `ais` i docker-compose.yml.
Procfile-plattform: `ais: python manage.py run_ais_stream`.

Tolkningen och ankomstlogiken står i maritime/ais.py, poängen i maritime/tips.py.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import random
import signal
import sys
import time
from collections import Counter, deque

import websockets
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from core.models import SourceStatus
from maritime import ais, tips
from maritime.models import AisVessel, FerryArrival
from maritime.ports import PORTS, by_name, port_for

log = logging.getLogger("maritime.ais")

STREAM_URL = "wss://stream.aisstream.io/v0/stream"

# Återanslutning: 1, 2, 4 ... 300 sekunder, med ±20 % jitter så att flera
# omstartade tjänster inte slår mot AISStream i samma sekund.
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 300.0
# En anslutning som hållit så här länge räknas som frisk; nästa fel börjar
# om backoffen från en sekund.
HEALTHY_AFTER_S = 60.0
# Stockholms inre hamn sänder flera gånger i minuten dygnet runt. Fem minuter
# helt utan meddelanden är en död anslutning som inte märkt det själv.
IDLE_TIMEOUT_S = 300.0

STATUS_EVERY_S = 60.0
# Ett förtöjt fartyg sänder var tredje minut i timmar. Spara bara när något
# som betyder något ändrats, eller högst så här ofta.
SAVE_EVERY_S = 30.0
# Positioner för fartyg vars typ vi inte hört än. Taket skyddar minnet mot
# en ström full av lastfartyg vars ShipStaticData aldrig kommer.
PENDING_MAX = 2000
IN_PORT_FRESH_S = 15 * 60
MAX_CONSECUTIVE_HANDLER_ERRORS = 20

# Alla fartyg (ais_vessels, kartan) hålls i minnet och skrivs i klump varje
# statusminut. Efter ett dygn utan position släpps fartyget ur minnet; raden
# i databasen ligger kvar.
FLEET_FORGET_AFTER_S = 24 * 3600
FLEET_FIELDS = (
    "name", "call_sign", "imo", "ship_type", "ais_class", "length_m", "width_m",
    "draught_m", "destination", "latitude", "longitude", "speed_knots", "course",
    "heading", "nav_status", "port_name", "last_message_type", "messages",
    "position_at", "static_at",
)
_FLEET_TEXT_FIELDS = ("name", "call_sign", "ais_class", "destination", "port_name", "last_message_type")


class AisStreamError(RuntimeError):
    """AISStream svarade med {"error": ...} -- oftast en ogiltig nyckel."""


class Command(BaseCommand):
    help = "Lyssnar på AISStream och skriver tips när passagerarfärjor lägger till"

    def add_arguments(self, parser):
        parser.add_argument(
            "--duration", type=int, default=0,
            help="Avsluta efter så här många sekunder (0 = kör tills avbrutet).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Spara fartygen men skriv inga tips.",
        )

    def handle(self, *args, **options):
        api_key = os.environ.get("AISSTREAM_API_KEY") or getattr(settings, "AISSTREAM_API_KEY", "")
        if not api_key:
            raise CommandError(
                "AISSTREAM_API_KEY saknas. Lägg den i taxitips-backend/.env lokalt, "
                "eller som miljövariabel på tjänsten i Coolify."
            )
        _configure_logging(options["verbosity"])
        listener = AisListener(api_key, dry_run=options["dry_run"])
        asyncio.run(_main(listener, options["duration"]))
        log.info("Avslutad. Totalt: %s", listener.summary(listener.totals))


def _configure_logging(verbosity: int) -> None:
    level = logging.DEBUG if verbosity >= 2 else logging.INFO if verbosity >= 1 else logging.WARNING
    log.setLevel(level)
    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        log.addHandler(handler)
        log.propagate = False


async def _main(listener: "AisListener", duration: int) -> None:
    loop = asyncio.get_running_loop()
    # SIGTERM är vad Coolify/Docker skickar vid stopp och omdeploy. Utan den
    # dödas processen mitt i en skrivning och sista statusen blir aldrig skriven.
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, listener.stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass
    await listener.run(duration)


class AisListener:
    def __init__(self, api_key: str, *, dry_run: bool = False) -> None:
        self.api_key = api_key
        self.dry_run = dry_run
        self.stop = asyncio.Event()

        # Bara passagerarfartyg. Nyckeln är MMSI.
        self.vessels: dict[int, FerryArrival] = {}
        self.non_passenger: set[int] = set()
        # Positioner för fartyg vars typ ännu inte hörts -- se ais.buffer_position.
        self.pending: dict[int, deque] = {}
        self._last_saved: dict[int, tuple[float, tuple]] = {}
        # För pipeline-sidan (maritime/explain.py): vad som finns i rutorna
        # utöver passagerarfartygen, hur ett råmeddelande ser ut, och de
        # senaste ankomstbesluten med utfall.
        self.seen: set[int] = set()
        self.ship_types: dict[int, int | None] = {}
        self.samples: dict[str, dict] = {}
        self.decisions: deque = deque(maxlen=25)
        self.by_type: Counter = Counter()
        self.compression: bool | None = None
        # Alla fartyg, inte bara passagerarfartyg -- för kartan. MMSI -> AisVessel-fält.
        self.fleet: dict[int, dict] = {}
        self.fleet_dirty: set[int] = set()

        self.totals: Counter = Counter()
        self.window: Counter = Counter()
        self.connected = False
        self.connected_since = None
        self.reconnects = 0
        self.last_error = ""
        self.started = time.monotonic()

    # -- livscykel ------------------------------------------------------------

    async def run(self, duration: int = 0) -> None:
        await self._warm_cache()
        tasks = [
            asyncio.create_task(self._connect_forever(), name="ais-connect"),
            asyncio.create_task(self._status_loop(), name="ais-status"),
        ]
        try:
            if duration:
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=duration)
                except TimeoutError:
                    log.info("--duration %d s nådd, avslutar", duration)
            else:
                await self.stop.wait()
        finally:
            self.stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.connected = False
            try:
                await self._flush_fleet()
                await self._write_status(final=True)
            except Exception:
                log.exception("Kunde inte skriva slutstatus")

    async def _warm_cache(self) -> None:
        # Fartygstypen kommer bara var sjätte minut. Utan cachen är varje
        # omstart sex minuter blind för färjor vi redan känner.
        async for vessel in FerryArrival.objects.all():
            self.vessels[vessel.mmsi] = vessel
        log.info("%d kända passagerarfartyg laddade från databasen", len(self.vessels))
        # Resten av flottan, så att första klumpskrivningen efter en omstart
        # inte skriver över kända namn och typer med tomma fält.
        since = timezone.now() - dt.timedelta(seconds=FLEET_FORGET_AFTER_S)
        async for row in AisVessel.objects.filter(updated_at__gte=since).values("mmsi", *FLEET_FIELDS):
            self.fleet[row["mmsi"]] = row
        log.info("%d fartyg från senaste dygnet laddade för kartan", len(self.fleet))

    async def _connect_forever(self) -> None:
        backoff = BACKOFF_START_S
        while not self.stop.is_set():
            opened = time.monotonic()
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except AisStreamError as exc:
                self.last_error = f"AISStream: {exc}"
                log.error("AISStream nekade: %s", exc)
            except (websockets.exceptions.WebSocketException, OSError, TimeoutError) as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("Anslutningen bröts: %s", self.last_error)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("Oväntat fel i strömmen")
            finally:
                self.connected = False

            if self.stop.is_set():
                break
            if time.monotonic() - opened >= HEALTHY_AFTER_S:
                backoff = BACKOFF_START_S
            delay = backoff * random.uniform(0.8, 1.2)
            self.reconnects += 1
            log.warning("Ansluter igen om %.0f s (återanslutning %d)", delay, self.reconnects)
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    async def _session(self) -> None:
        async with websockets.connect(
            STREAM_URL,
            compression="deflate",
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=2**20,
        ) as ws:
            await ws.send(json.dumps(ais.subscription(self.api_key)))
            self.connected = True
            self.connected_since = timezone.now()
            log.info(
                "Ansluten till AISStream. Lyssnar på %d hamnar: %s",
                len(PORTS), ", ".join(p.name for p in PORTS),
            )
            try:
                await self._write_status()
            except Exception:
                log.exception("Kunde inte skriva status")

            failures = 0
            while not self.stop.is_set():
                try:
                    frame = await asyncio.wait_for(ws.recv(), timeout=IDLE_TIMEOUT_S)
                except TimeoutError:
                    raise TimeoutError(f"inga meddelanden på {IDLE_TIMEOUT_S:.0f} s") from None
                try:
                    msg = json.loads(frame)
                except ValueError:
                    self._count("bad_frame")
                    continue
                if isinstance(msg, dict) and msg.get("error"):
                    raise AisStreamError(msg["error"])
                try:
                    await self._handle(msg)
                    failures = 0
                except Exception:
                    # Ett konstigt meddelande ska inte fälla strömmen. Tjugo i
                    # rad är däremot databasen eller en bugg -- då backoff.
                    failures += 1
                    log.exception("Kunde inte hantera meddelandet")
                    if failures >= MAX_CONSECUTIVE_HANDLER_ERRORS:
                        raise

    # -- meddelanden ----------------------------------------------------------

    def _count(self, key: str, n: int = 1) -> None:
        self.totals[key] += n
        self.window[key] += n

    async def _handle(self, msg) -> None:
        mtype = msg.get("MessageType") if isinstance(msg, dict) else None
        if mtype:
            self.by_type[mtype] += 1
        if mtype == "SubscriptionConfirmation":
            self.compression = (msg.get("Message") or {}).get("CompressionEnabled")
            log.info("Prenumerationen bekräftad (komprimering: %s)", "på" if self.compression else "AV")
            if not self.compression:
                # Från september 2026 får okomprimerade anslutningar ett
                # bandbreddstak, och meddelanden över taket kastas utan fel.
                log.warning("Komprimeringen förhandlades inte fram -- AISStream kan kasta meddelanden")
            return
        now = timezone.now()
        update = ais.parse_message(msg, now)
        if update is None:
            self._count("ignored")
            return
        self._count(update.kind)
        self.seen.add(update.mmsi)
        self.samples[mtype] = msg
        self._track(update)
        if update.has_static:
            # ShipStaticData, StaticDataReport del B, och ExtendedClassB som
            # bär typ och storlek i samma meddelande som positionen.
            await self._on_static(update, now)
        elif update.kind == "static":
            await self._on_name(update)
        if update.kind == "position":
            await self._on_position(update, now)

    def _track(self, update: ais.AisUpdate) -> None:
        """Alla fartyg, för kartan. Skrivs till ais_vessels i klump av statusloopen."""
        ship = self.fleet.setdefault(update.mmsi, {"mmsi": update.mmsi, "messages": 0})
        ship["messages"] = (ship.get("messages") or 0) + 1
        ship["last_message_type"] = update.message_type
        ship["ais_class"] = update.ais_class or ship.get("ais_class") or ""
        if update.name:
            ship["name"] = update.name[:100]
        if update.kind == "position":
            port = port_for(update.lat, update.lon)
            ship.update(
                latitude=update.lat, longitude=update.lon, speed_knots=update.sog,
                course=update.cog, heading=update.heading, nav_status=update.nav_status,
                port_name=port.name if port else "", position_at=update.timestamp,
            )
        if update.has_static:
            ship["ship_type"] = update.ship_type
            ship["static_at"] = update.timestamp
            if update.length_m:
                ship["length_m"] = update.length_m
            if update.width_m:
                ship["width_m"] = update.width_m
        if update.call_sign:
            ship["call_sign"] = update.call_sign[:10]
        if update.imo:
            ship["imo"] = update.imo
        if update.draught_m:
            ship["draught_m"] = update.draught_m
        if update.has_voyage:
            ship["destination"] = update.destination[:40]
        self.fleet_dirty.add(update.mmsi)

    async def _flush_fleet(self) -> None:
        if not self.fleet_dirty:
            return
        dirty, self.fleet_dirty = self.fleet_dirty, set()
        rows = []
        for mmsi in dirty:
            ship = self.fleet.get(mmsi)
            if ship is None:
                continue
            values = {field: ship.get(field) for field in FLEET_FIELDS}
            for field in _FLEET_TEXT_FIELDS:
                values[field] = values[field] or ""
            values["messages"] = values["messages"] or 0
            rows.append(AisVessel(mmsi=mmsi, **values))
        try:
            await AisVessel.objects.abulk_create(
                rows, update_conflicts=True, unique_fields=["mmsi"],
                update_fields=[*FLEET_FIELDS, "updated_at"],
            )
        except Exception:
            self.fleet_dirty |= dirty  # försök igen nästa minut
            raise
        cutoff = timezone.now() - dt.timedelta(seconds=FLEET_FORGET_AFTER_S)
        for mmsi in [m for m, s in self.fleet.items() if s.get("position_at") and s["position_at"] < cutoff]:
            del self.fleet[mmsi]

    async def _on_name(self, update: ais.AisUpdate) -> None:
        """StaticDataReport del A: bara namnet. Rör aldrig fartygets typ."""
        vessel = self.vessels.get(update.mmsi)
        if vessel is not None and update.name and vessel.ship_name != update.name[:100]:
            vessel.ship_name = update.name[:100]
            await self._save(vessel, force=True)

    async def _on_static(self, update: ais.AisUpdate, now) -> None:
        mmsi = update.mmsi
        self.ship_types[mmsi] = update.ship_type
        if not ais.is_passenger(update.ship_type):
            if self.vessels.pop(mmsi, None):
                log.info("MMSI %s rapporterar nu typ %s, släpps", mmsi, update.ship_type)
            self.non_passenger.add(mmsi)
            self.pending.pop(mmsi, None)
            return
        self.non_passenger.discard(mmsi)

        stored, created = await FerryArrival.objects.aupdate_or_create(
            mmsi=mmsi, defaults=ais.static_fields(update),
        )
        vessel = self.vessels.get(mmsi)
        if vessel is None:
            vessel = self.vessels[mmsi] = stored
            log.info(
                "Passagerarfartyg: %-22s MMSI %s  typ %s  %s m  destination %s",
                vessel.ship_name or "?", mmsi, vessel.ship_type,
                vessel.length_m or "?", vessel.destination or "-",
            )
        else:
            ais.apply_static(vessel, update)

        pending = self.pending.pop(mmsi, None)
        if pending:
            # Alla väntande positioner i tidsordning: "var i fart" måste ses innan
            # inbromsningen, annars blir ankomsten aldrig en ankomst.
            for buffered in sorted(pending, key=lambda u: u.timestamp):
                await self._on_position(buffered, now)
        else:
            await self._evaluate(vessel, now)

    async def _on_position(self, update: ais.AisUpdate, now) -> None:
        mmsi = update.mmsi
        if mmsi in self.non_passenger:
            return
        vessel = self.vessels.get(mmsi)
        if vessel is None:
            if mmsi not in self.pending and len(self.pending) >= PENDING_MAX:
                self.pending.pop(next(iter(self.pending)))
            self.pending[mmsi] = ais.buffer_position(self.pending.get(mmsi), update)
            return

        previous_port = vessel.port_name
        if not ais.apply_position(vessel, update):
            return
        if vessel.port_name and vessel.port_name != previous_port:
            log.info(
                "%s i %s: %s knop",
                vessel.ship_name or mmsi, vessel.port_name, _knots(vessel.speed_knots),
            )
        log.debug(
            "%-22s %-22s %.5f,%.5f  %s kn  status %s",
            vessel.ship_name or mmsi, vessel.port_name or "-",
            vessel.latitude, vessel.longitude, _knots(vessel.speed_knots), vessel.nav_status,
        )
        await self._evaluate(vessel, now)

    async def _evaluate(self, vessel: FerryArrival, now) -> None:
        reason = ais.evaluate(vessel, now)
        await self._save(vessel, force=bool(reason))
        if reason:
            await self.on_arrival(vessel, reason, now)

    async def _save(self, vessel: FerryArrival, *, force: bool) -> None:
        flags = (vessel.port_name, vessel.was_underway, vessel.is_processed)
        last = self._last_saved.get(vessel.mmsi)
        clock = time.monotonic()
        if not force and last and last[1] == flags and clock - last[0] < SAVE_EVERY_S:
            return
        await vessel.asave()
        self._last_saved[vessel.mmsi] = (clock, flags)

    async def on_arrival(self, vessel: FerryArrival, reason: str, now) -> None:
        """Färjan lägger till. Anropas en gång per anlöp -- is_processed spärrar resten."""
        self._count("arrivals")
        port = by_name(vessel.port_name)
        label = "saktar in" if reason == ais.REASON_SLOWING else "ETA inom en timme"
        if not port.tips:
            # Hamnen visas på kartan men ger inga tips -- se Port.tips och Port.note.
            self.decisions.appendleft({
                "at": now.isoformat(), "ship": vessel.ship_name or str(vessel.mmsi),
                "mmsi": vessel.mmsi, "port": port.name, "lengthM": vessel.length_m,
                "knots": vessel.speed_knots, "trigger": reason, "score": None, "confidence": None,
                "verdict": "bara karta",
            })
            log.info("Ankomst %s -> %s (%s): hamnen ger inga tips", vessel.ship_name or vessel.mmsi, port.name, label)
            return
        assessment = tips.assess(vessel, port, reason, now)
        self.decisions.appendleft({
            "at": now.isoformat(), "ship": vessel.ship_name or str(vessel.mmsi),
            "mmsi": vessel.mmsi, "port": port.name, "lengthM": vessel.length_m,
            "knots": vessel.speed_knots, "trigger": reason,
            "score": assessment.score if assessment else None,
            "confidence": assessment.confidence if assessment else None,
            "verdict": "för kort" if assessment is None else ("dry-run" if self.dry_run else "tips"),
        })
        if assessment is None:
            log.info(
                "Ankomst %s -> %s (%s), %s m: under %d m, inget tips",
                vessel.ship_name or vessel.mmsi, port.name, label,
                vessel.length_m or "okänd längd", tips.MIN_TIP_LENGTH_M,
            )
            return
        log.info(
            "ANKOMST %s -> %s (%s, %s m): %d poäng, säkerhet %s",
            vessel.ship_name or vessel.mmsi, port.name, label,
            vessel.length_m, assessment.score, assessment.confidence,
        )
        if self.dry_run:
            log.info("  --dry-run: tipset skrevs inte")
            return
        external_id = await sync_to_async(tips.write_tip)(vessel, port, assessment, reason)
        self._count("tips_written")
        log.info("  tips skrivet: %s", external_id)

    # -- status ---------------------------------------------------------------

    async def _status_loop(self) -> None:
        while True:
            await asyncio.sleep(STATUS_EVERY_S)
            try:
                # En process som lever i veckor överlever Postgres-omstarter
                # bara om döda anslutningar städas bort.
                await sync_to_async(close_old_connections)()
                await self._flush_fleet()
                await self._write_status()
            except Exception:
                log.exception("Kunde inte skriva status")
            log.info("Senaste minuten: %s", self.summary(self.window))
            self.window.clear()

    def _in_port(self) -> Counter:
        now = timezone.now()
        return Counter(
            v.port_name for v in self.vessels.values()
            if v.port_name and v.timestamp
            and (now - v.timestamp).total_seconds() <= IN_PORT_FRESH_S
        )

    def summary(self, counts: Counter) -> str:
        return (
            f"{counts['position']} positioner, {counts['static']} statiska, "
            f"{len(self.vessels)} passagerarfartyg kända, {counts['arrivals']} ankomster, "
            f"{counts['tips_written']} tips, {self.reconnects} återanslutningar"
        )

    async def _write_status(self, *, final: bool = False) -> None:
        if self.connected:
            ok, message = True, ""
        elif final:
            ok, message = True, "stoppad"
        else:
            ok, message = False, self.last_error or "inte ansluten"
        await SourceStatus.objects.aupdate_or_create(
            source=tips.SOURCE,
            defaults={
                "ok": ok,
                "message": message[:500],
                # Meddelanden senaste minuten: en ström har ingen "hämtning"
                # att räkna, och noll här är det som syns när den tystnat.
                "events": self.window["position"] + self.window["static"],
                "written": self.totals["tips_written"],
                "duration_ms": int((time.monotonic() - self.started) * 1000),
                "detail": {
                    "connected": self.connected,
                    "connectedSince": self.connected_since.isoformat() if self.connected_since else None,
                    "reconnects": self.reconnects,
                    "lastError": self.last_error,
                    "dryRun": self.dry_run,
                    "passengerShips": len(self.vessels),
                    "inPort": dict(self._in_port()),
                    "lastMinute": dict(self.window),
                    "total": dict(self.totals),
                    "uniqueShips": len(self.seen),
                    "shipTypes": dict(Counter(str(t) for t in self.ship_types.values())),
                    "unknownTypeShips": len(self.pending),
                    "samples": self.samples,
                    "decisions": list(self.decisions),
                    "messageTypes": dict(self.by_type),
                    "compressionEnabled": self.compression,
                    "fleetTracked": len(self.fleet),
                    "classBShips": sum(1 for m in self.seen if (self.fleet.get(m) or {}).get("ais_class") == "B"),
                },
                "checked_at": timezone.now(),
            },
        )
        if self.connected and self.window["position"] + self.window["static"]:
            # En ström har ingen runda. Ansluten och med meddelanden senaste
            # minuten är dess motsvarighet till en lyckad hämtning.
            from django.db.models.functions import Now

            await SourceStatus.objects.filter(source=tips.SOURCE).aupdate(
                last_success_at=Now(), consecutive_failures=0,
            )


def _knots(value: float | None) -> str:
    return "?" if value is None else f"{value:.1f}"
