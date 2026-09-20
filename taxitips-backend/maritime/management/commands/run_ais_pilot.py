"""
AIS-piloten (P1): följer registrets färjor hela vägen in till Visby och Värtahamnen.

    python manage.py run_ais_pilot                  # lyssna tills Ctrl-C
    python manage.py run_ais_pilot --duration 600   # tio minuter
    python manage.py run_ais_pilot --dry-run        # följ och förutsäg, skriv inga tips

EN anslutning till AISStream, filtrerad på registrets MMSI (FiltersShipMMSI) inom
inseglingsrutorna -- liten volym, hela resan. Den kommer UTÖVER run_ais_stream:s
anslutning, och AISStream tillåter tre per konto och IP. Räkna alla miljöer: lokal
lyssnare + pilot + staging eller produktion får inte bli fler än tre.

Varje anlöp sparas i `ferry_calls` med förutsagd och faktisk kajtid, så att
iland-fönstret och förvarningen går att kalibrera. Se maritime/pilot.py.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import random
import signal
import time
from collections import Counter

import websockets
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models.functions import Now
from django.utils import timezone

from core.models import SourceStatus
from maritime import ais, pilot
from maritime.models import AisVessel, FerryCall
from maritime.register import BY_MMSI, REGISTER, TERMINALS

log = logging.getLogger("maritime.pilot")

STREAM_URL = "wss://stream.aisstream.io/v0/stream"
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 300.0
# Tre färjor ger få meddelanden; en tyst timme är normal när alla ligger vid kaj.
IDLE_TIMEOUT_S = 3600.0
STATUS_EVERY_S = 60.0
# Ett anlöp som inte fått någon uppskattning på så länge släpps ur minnet.
FORGET_CALL_AFTER = dt.timedelta(hours=2)


class Command(BaseCommand):
    help = "AIS-pilot: förutsäger kajtid och iland-fönster för registrets färjor"

    def add_arguments(self, parser):
        parser.add_argument("--duration", type=int, default=0, help="Sekunder att lyssna; 0 = tills Ctrl-C.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        key = settings.AISSTREAM_API_KEY
        if not key:
            self.stderr.write("AISSTREAM_API_KEY saknas")
            return
        listener = PilotListener(key, dry_run=options["dry_run"])
        asyncio.run(listener.run(options["duration"]))


# Hur ofta körtiden stäms av mot väggklockan.
DEADLINE_CHECK_S = 30


class PilotListener:
    def __init__(self, api_key: str, *, dry_run: bool = False) -> None:
        self.api_key = api_key
        self.dry_run = dry_run
        self.stop = asyncio.Event()
        self.tracks = {v.mmsi: pilot.Track(v.mmsi, TERMINALS[v.terminal]) for v in REGISTER}
        self.calls: dict[int, FerryCall] = {}
        self.names = {v.mmsi: v.name for v in REGISTER}
        self.lengths: dict[int, int | None] = {}
        self.counts: Counter = Counter()
        self.last_message = 0.0
        self.connected = False
        self.last_error = ""

    async def run(self, duration: int = 0) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except (NotImplementedError, RuntimeError):
                pass
        await self._load()
        tasks = [asyncio.create_task(self._connect_forever()), asyncio.create_task(self._status_loop())]
        try:
            await self._wait_until_done(duration)
        finally:
            self.stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._write_status(final=True)
            log.info("pilot: %s", dict(self.counts))

    async def _wait_until_done(self, duration: int) -> None:
        """
        Tills Ctrl-C, eller tills `duration` sekunder har gått på väggklockan.

        Inte asyncio:s tidsgräns: den går på den monotona klockan, som på macOS står
        still medan datorn sover. En körning med --duration 12600 (3,5 h) startad
        07:04 den 2026-09-14 lyssnade fortfarande 18:05; pmset-loggen visar 44
        insomningar under fönstret.
        """
        if not duration:
            await self.stop.wait()
            return
        deadline = timezone.now() + dt.timedelta(seconds=duration)
        while not self.stop.is_set():
            left = (deadline - timezone.now()).total_seconds()
            if left <= 0:
                return
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=min(left, DEADLINE_CHECK_S))
            except TimeoutError:
                pass

    async def _load(self) -> None:
        async for vessel in AisVessel.objects.filter(mmsi__in=list(BY_MMSI)).values("mmsi", "name", "length_m"):
            self.lengths[vessel["mmsi"]] = vessel["length_m"]
            if vessel["name"]:
                self.names[vessel["mmsi"]] = vessel["name"]
        since = timezone.now() - dt.timedelta(hours=12)
        async for call in FerryCall.objects.filter(arrived_at__isnull=True, started_at__gte=since):
            self.calls[call.mmsi] = call
        log.info("pilot: %d fartyg i registret, %d öppna anlöp", len(REGISTER), len(self.calls))

    async def _connect_forever(self) -> None:
        backoff = BACKOFF_START_S
        while not self.stop.is_set():
            opened = time.monotonic()
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("pilot: anslutningen bröts: %s", self.last_error)
            finally:
                self.connected = False
            if self.stop.is_set():
                break
            if time.monotonic() - opened >= 60:
                backoff = BACKOFF_START_S
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=backoff * random.uniform(0.8, 1.2))
            except TimeoutError:
                pass
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    async def _session(self) -> None:
        async with websockets.connect(
            STREAM_URL, compression="deflate", open_timeout=15, ping_interval=20, ping_timeout=20, max_size=2**20,
        ) as ws:
            await ws.send(json.dumps(pilot.subscription(self.api_key)))
            self.connected = True
            log.info("pilot: ansluten, följer %s", ", ".join(v.name for v in REGISTER))
            while not self.stop.is_set():
                frame = await asyncio.wait_for(ws.recv(), timeout=IDLE_TIMEOUT_S)
                msg = json.loads(frame)
                if isinstance(msg, dict) and msg.get("error"):
                    raise RuntimeError(f"AISStream: {msg['error']}")
                await self.handle(msg, timezone.now())

    async def handle(self, msg, now: dt.datetime) -> None:
        update = ais.parse_message(msg, now)
        if update is None or update.mmsi not in self.tracks:
            return
        self.last_message = time.monotonic()
        self.counts[update.kind] += 1
        track = self.tracks[update.mmsi]
        if update.kind == "static":
            if update.has_voyage:
                track.destination, track.ais_eta = update.destination, update.eta
            if update.length_m:
                self.lengths[update.mmsi] = update.length_m
            return
        track.add(update)
        await self.evaluate(track, now)

    async def evaluate(self, track: pilot.Track, now: dt.datetime) -> None:
        call = self.calls.get(track.mmsi)
        name = self.names.get(track.mmsi) or str(track.mmsi)

        if call is not None and pilot.berthed(track):
            call.arrived_at = track.fixes[-1].at
            await call.asave()
            self.counts["arrived"] += 1
            error = (call.arrived_at - call.berth_eta).total_seconds() / 60 if call.berth_eta else None
            lead = (call.arrived_at - call.first_estimate_at).total_seconds() / 60 if call.first_estimate_at else None
            log.info(
                "pilot: %s vid kaj i %s. Förvarning %s min, sista uppskattningen %s min fel",
                name, track.terminal.port.name,
                f"{lead:.0f}" if lead is not None else "?", f"{error:+.0f}" if error is not None else "?",
            )
            self.calls.pop(track.mmsi, None)
            track.fixes.clear()
            return

        est = pilot.estimate(track, now)
        if est is None:
            if call is not None and call.updated_at and now - call.updated_at > FORGET_CALL_AFTER:
                self.calls.pop(track.mmsi, None)
            return

        if call is None:
            call = FerryCall(
                call_id=pilot.call_id(track), mmsi=track.mmsi, ship_name=name[:100],
                terminal=track.terminal.port_key, started_at=track.fixes[0].at,
            )
            self.calls[track.mmsi] = call
            self.counts["calls"] += 1
            log.info("pilot: %s närmar sig %s", name, track.terminal.port.name)

        if pilot.record_estimate(call, est, now) or call.pk is None:
            await call.asave()
            log.info(
                "pilot: %s -> %s kajtid %s (%s, %.0f km)",
                name, track.terminal.port.name,
                est.berth_eta.astimezone(pilot.STOCKHOLM).strftime("%H:%M"), est.basis, est.distance_km,
            )

        if not self.dry_run and est.berth_eta - now <= pilot.TIP_AHEAD:
            ext = await sync_to_async(pilot.write_tip)(call, est, name=name, length_m=self.lengths.get(track.mmsi))
            if call.tip_external_id != ext:
                call.tip_external_id = ext
                await call.asave()
                self.counts["tips"] += 1

    async def _status_loop(self) -> None:
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=STATUS_EVERY_S)
            except TimeoutError:
                await self._write_status()

    async def _write_status(self, *, final: bool = False) -> None:
        receiving = self.connected and time.monotonic() - self.last_message <= IDLE_TIMEOUT_S
        if final:
            # Ett planerat stopp är inget fel, även om anslutningen bröts under körningen.
            self.connected, self.last_error = False, ""
        await SourceStatus.objects.aupdate_or_create(
            source=pilot.SOURCE,
            defaults={
                "ok": self.connected or not self.last_error,
                "message": "stoppad" if final else ("" if self.connected else self.last_error),
                "events": self.counts["position"] + self.counts["static"],
                "written": self.counts["tips"],
                "duration_ms": 0,
                "detail": {
                    "connected": self.connected,
                    "register": [v.name for v in REGISTER],
                    "openCalls": {self.names.get(m, str(m)): c.berth_eta.isoformat() if c.berth_eta else None
                                  for m, c in self.calls.items()},
                    "counts": dict(self.counts),
                    "dryRun": self.dry_run,
                },
                "checked_at": timezone.now(),
            },
        )
        if receiving:
            await SourceStatus.objects.filter(source=pilot.SOURCE).aupdate(last_success_at=Now(), consecutive_failures=0)
