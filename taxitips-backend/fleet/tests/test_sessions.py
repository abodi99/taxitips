"""
Skiftbyte: exakt en aktiv telefon per billicens, exakt en aktiv bil per telefon.

De två första testerna kör RIKTIGA samtidiga transaktioner i trådar. Ett test
som bara anropar funktionen två gånger i följd bevisar ingenting om
samtidighet -- det är just den sekventiella läsningen som gör att en kontroll i
Python ser korrekt ut ända tills två förare trycker samtidigt.
"""

from __future__ import annotations

import threading
from datetime import timedelta

from django.db import connection, connections
from django.utils import timezone

from fleet import pairing, sessions
from fleet.models import DeviceApproval, VehicleSession
from fleet.tests.base import FleetTestCase, FleetTransactionTestCase


def run_concurrently(targets):
    """
    Kör callables i var sin tråd med var sin databasanslutning.

    En `Barrier` släpper loss alla trådar i samma ögonblick. Utan den hinner
    den första bli klar innan den andra startar, och testet hade provat två
    anrop i följd -- vilket inte är vad det påstår sig prova.
    """
    results: list = [None] * len(targets)
    gate = threading.Barrier(len(targets), timeout=30)

    def wrap(index, fn):
        def runner():
            try:
                gate.wait()
                results[index] = ("ok", fn())
            except Exception as exc:
                results[index] = ("error", exc)
            finally:
                connections.close_all()

        return runner

    threads = [threading.Thread(target=wrap(i, fn)) for i, fn in enumerate(targets)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


class ConcurrentTakeoverTests(FleetTransactionTestCase):
    def test_two_phones_taking_the_same_car_leave_exactly_one_active(self):
        data = self.full_setup()
        company, license, vehicle = data["company"], data["license"], data["vehicle"]
        first, second = data["device"], self.make_device(company, label="Förare 2")
        self.approve(company, license, vehicle, second)

        results = run_concurrently([
            lambda: sessions.start_session(device_id=first.id, license_id=license.id, force=True),
            lambda: sessions.start_session(device_id=second.id, license_id=license.id, force=True),
        ])
        # Minst en lyckas; ingen av dem får lämna två öppna rader.
        self.assertTrue(any(status == "ok" for status, _ in results), results)

        active = VehicleSession.objects.filter(license=license, ended_at__isnull=True)
        self.assertEqual(active.count(), 1, "två telefoner hade bilen samtidigt")

    def test_one_phone_taking_two_cars_leaves_exactly_one_active(self):
        """§3: hantera även samtidiga byten mellan två bilar på samma telefon."""
        data = self.full_setup(plate="AAA111")
        company, device = data["company"], data["device"]
        first_license = data["license"]
        other_vehicle, other_license = self.make_license(company, plate="BBB222")
        self.approve(company, other_license, other_vehicle, device)

        results = run_concurrently([
            lambda: sessions.start_session(
                device_id=device.id, license_id=first_license.id, force=True
            ),
            lambda: sessions.start_session(
                device_id=device.id, license_id=other_license.id, force=True
            ),
        ])
        self.assertTrue(any(status == "ok" for status, _ in results), results)

        active = VehicleSession.objects.filter(device_id=device.id, ended_at__isnull=True)
        self.assertEqual(active.count(), 1, "telefonen hade två bilar samtidigt")

    def test_many_phones_racing_for_one_car(self):
        data = self.full_setup()
        company, license, vehicle = data["company"], data["license"], data["vehicle"]
        devices = [data["device"]]
        for i in range(2, 6):
            device = self.make_device(company, label=f"Förare {i}")
            self.approve(company, license, vehicle, device)
            devices.append(device)

        run_concurrently([
            (lambda d=d: sessions.start_session(device_id=d.id, license_id=license.id, force=True))
            for d in devices
        ])
        self.assertEqual(
            VehicleSession.objects.filter(license=license, ended_at__isnull=True).count(), 1
        )


class ConstraintTests(FleetTestCase):
    """
    De partiella unika indexen är den verkliga garantin -- låsen finns för att
    den som förlorar ska få ett begripligt svar i stället för ett databasfel.

    De här två testerna skriver förbi `start_session` och visar att databasen
    själv vägrar. Skulle någon "förenkla" bort ett index är det här testet det
    som går sönder, inte trådtesterna (som skulle fortsätta passera på låsen).
    """

    def setUp(self):
        super().setUp()
        self.data = self.full_setup()

    def _open_session(self, *, device, license, vehicle, approval):
        now = timezone.now()
        return VehicleSession.objects.create(
            company_id=self.data["company"].id, license=license, vehicle=vehicle,
            device_id=device.id, approval=approval, started_at=now, last_seen_at=now,
        )

    def test_database_refuses_two_open_sessions_on_one_licence(self):
        from django.db import IntegrityError, transaction

        company, license, vehicle = (
            self.data["company"], self.data["license"], self.data["vehicle"]
        )
        self._open_session(
            device=self.data["device"], license=license, vehicle=vehicle,
            approval=self.data["approval"],
        )
        other = self.make_device(company, label="Förare 2")
        approval, _ = self.approve(company, license, vehicle, other)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._open_session(
                device=other, license=license, vehicle=vehicle, approval=approval
            )

    def test_database_refuses_two_open_sessions_on_one_phone(self):
        from django.db import IntegrityError, transaction

        company, device = self.data["company"], self.data["device"]
        self._open_session(
            device=device, license=self.data["license"], vehicle=self.data["vehicle"],
            approval=self.data["approval"],
        )
        other_vehicle, other_license = self.make_license(company, plate="BBB222")
        approval, _ = self.approve(company, other_license, other_vehicle, device)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._open_session(
                device=device, license=other_license, vehicle=other_vehicle,
                approval=approval,
            )


class TakeoverRulesTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.data = self.full_setup()
        self.company = self.data["company"]
        self.license = self.data["license"]
        self.vehicle = self.data["vehicle"]
        self.first = self.data["device"]
        self.second = self.make_device(self.company, label="Förare 2")
        self.approve(self.company, self.license, self.vehicle, self.second)

    def test_takeover_requires_explicit_confirmation(self):
        sessions.start_session(device_id=self.first.id, license_id=self.license.id)
        with self.assertRaises(sessions.SessionError) as caught:
            sessions.start_session(device_id=self.second.id, license_id=self.license.id)
        self.assertEqual(caught.exception.reason, "takeover_required")
        self.assertIn("Vill du ta över", caught.exception.message)
        # Ingenting ändrades av frågan.
        active = VehicleSession.objects.get(license=self.license, ended_at__isnull=True)
        self.assertEqual(str(active.device_id), str(self.first.id))

    def test_confirmed_takeover_ends_the_old_session(self):
        first = sessions.start_session(device_id=self.first.id, license_id=self.license.id)
        result = sessions.start_session(
            device_id=self.second.id, license_id=self.license.id, force=True
        )
        self.assertEqual(result.took_over_from, str(self.first.id))

        first.session.refresh_from_db()
        self.assertIsNotNone(first.session.ended_at)
        self.assertEqual(first.session.ended_reason, VehicleSession.EndReason.TAKEOVER)
        self.assertEqual(
            VehicleSession.objects.filter(license=self.license, ended_at__isnull=True).count(), 1
        )

    def test_old_phone_cannot_reclaim_by_heartbeat(self):
        """
        §3: en gammal telefon får inte återta bilen automatiskt genom
        bakgrundsuppdatering, tokenförnyelse eller återanslutning.
        """
        first = sessions.start_session(device_id=self.first.id, license_id=self.license.id)
        sessions.start_session(device_id=self.second.id, license_id=self.license.id, force=True)

        first.session.refresh_from_db()
        self.assertFalse(sessions.heartbeat(first.session))

        holder = VehicleSession.objects.get(license=self.license, ended_at__isnull=True)
        self.assertEqual(str(holder.device_id), str(self.second.id))

    def test_old_phone_reclaiming_needs_a_new_explicit_takeover(self):
        sessions.start_session(device_id=self.first.id, license_id=self.license.id)
        sessions.start_session(device_id=self.second.id, license_id=self.license.id, force=True)

        with self.assertRaises(sessions.SessionError) as caught:
            sessions.start_session(device_id=self.first.id, license_id=self.license.id)
        self.assertEqual(caught.exception.reason, "takeover_required")

    def test_repeated_start_by_the_same_phone_is_a_heartbeat(self):
        first = sessions.start_session(device_id=self.first.id, license_id=self.license.id)
        again = sessions.start_session(device_id=self.first.id, license_id=self.license.id)
        self.assertEqual(str(first.session.id), str(again.session.id))
        self.assertIsNone(again.took_over_from)

    def test_unapproved_phone_cannot_start_a_session(self):
        stranger = self.make_device(self.company, label="Okänd telefon")
        with self.assertRaises(sessions.SessionError) as caught:
            sessions.start_session(device_id=stranger.id, license_id=self.license.id, force=True)
        self.assertEqual(caught.exception.reason, "not_approved")

    def test_blocking_a_phone_ends_its_session_immediately(self):
        sessions.start_session(device_id=self.first.id, license_id=self.license.id)
        approval = DeviceApproval.objects.get(
            device_id=self.first.id, license=self.license, status=DeviceApproval.Status.ACTIVE
        )
        pairing.block_device(approval=approval, actor_user_id=None, reason="lost_phone")

        self.assertFalse(
            VehicleSession.objects.filter(device_id=self.first.id, ended_at__isnull=True).exists()
        )
        with self.assertRaises(sessions.SessionError) as caught:
            sessions.start_session(device_id=self.first.id, license_id=self.license.id, force=True)
        self.assertEqual(caught.exception.reason, "not_approved")


class BackgroundAndNetworkTests(FleetTestCase):
    """
    §3: tillfälligt nätbortfall eller app i bakgrunden ska inte automatiskt
    släppa licensen, och får inte se ut som ett skiftbyte.
    """

    def setUp(self):
        super().setUp()
        self.data = self.full_setup()
        self.license = self.data["license"]
        self.device = self.data["device"]

    def test_a_long_silence_does_not_end_the_session(self):
        result = sessions.start_session(device_id=self.device.id, license_id=self.license.id)
        VehicleSession.objects.filter(id=result.session.id).update(
            last_seen_at=timezone.now() - timedelta(hours=9)
        )
        # Ingen tidsgräns stänger en session. Den ligger kvar tills någon tar
        # över eller föraren lämnar bilen.
        still_open = VehicleSession.objects.get(license=self.license, ended_at__isnull=True)
        self.assertEqual(str(still_open.device_id), str(self.device.id))

    def test_returning_from_background_is_not_a_shift_change(self):
        result = sessions.start_session(device_id=self.device.id, license_id=self.license.id)
        resumed = sessions.start_session(device_id=self.device.id, license_id=self.license.id)
        self.assertEqual(str(result.session.id), str(resumed.session.id))
        self.assertIsNone(resumed.took_over_from)
        # Ingen risksignal: det här var inget övertagande.
        from fleet.models import RiskSignal

        self.assertEqual(
            RiskSignal.objects.filter(kind=RiskSignal.Kind.TAKEOVER).count(), 0
        )

    def test_driver_leaving_the_car_frees_the_licence(self):
        result = sessions.start_session(device_id=self.device.id, license_id=self.license.id)
        sessions.end_session(result.session, reason=VehicleSession.EndReason.DRIVER_END)
        self.assertIsNone(sessions.active_session_for_license(self.license.id))
