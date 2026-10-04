"""
Förarens detaljerade notisval (core/notify.py, core/notify_prefs.py): tysta
timmar, tak per timme, svagare tips som eget val och de färdiga lägena.

Det som går sönder tyst: ett nytt fält som råkar tysta telefoner som aldrig rört
det, svaga notiser som når någon som inte valt dem, eller ett tak som räknar
fel och låter telefonen pipa var femte minut.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from core import notify, notify_prefs, thresholds
from core.models import Opportunity, PushDelivery, SeverityTier
from core.test_notify import FakeDevice, SupabaseCompanyMixin, opportunity

STHLM = ZoneInfo("Europe/Stockholm")
SKANE = {"counties": ["12"]}


def at(hour, minute=0):
    return datetime(2026, 10, 4, hour, minute, tzinfo=STHLM)


def strong(**kw):
    return opportunity(**{"severity_tier": SeverityTier.LINE_PAUSED, "demand_score": 80, **kw})


def weak_tip(**kw):
    fields = {"severity_tier": SeverityTier.VEHICLE_DELAYED, "demand_score": 25, **kw}
    return opportunity(**fields)


class QuietHoursTests(SupabaseCompanyMixin, TestCase):
    def test_quiet_hours_across_midnight(self):
        prefs = {**SKANE, "quietHours": {"from": 23, "to": 6}}
        self.assertTrue(notify.in_quiet_hours(prefs, at(23, 30)))
        self.assertTrue(notify.in_quiet_hours(prefs, at(3)))
        self.assertFalse(notify.in_quiet_hours(prefs, at(6)))
        self.assertFalse(notify.in_quiet_hours(prefs, at(22, 59)))

    def test_decide_respects_quiet_hours_on_svensk_tid(self):
        tip = strong(end_time=timezone.now() + timedelta(days=2))
        prefs = {**SKANE, "quietHours": {"from": 1, "to": 6}}
        self.assertEqual(notify.decide(prefs, tip, now=at(2)).reason, "quiet_hours")
        self.assertTrue(notify.decide(prefs, tip, now=at(7)).ok)

    def test_a_broken_or_empty_value_is_not_silence(self):
        tip = strong()
        for raw in ({"from": 3, "to": 3}, {"from": "x"}, "01-06", None, {"from": 25, "to": 2}):
            with self.subTest(raw=raw):
                self.assertTrue(notify.decide({**SKANE, "quietHours": raw}, tip).ok)

    def test_quiet_hours_also_stop_a_queued_notification_at_send_time(self):
        """En notis köad 00:59 ska inte väcka någon 01:00."""
        hour = timezone.now().astimezone(STHLM).hour
        device = FakeDevice(dict(SKANE))
        tip = strong()
        PushDelivery.objects.create(
            opportunity=tip, opportunity_external_id=tip.external_id,
            device_id=device.id, device_token=device.token, title="t", body="b",
            snapshot={}, ok=False, status=PushDelivery.Status.PENDING,
            next_attempt_at=timezone.now() - timedelta(seconds=1),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        Opportunity.objects.filter(pk=tip.pk).update(notified_at=timezone.now())
        device.notify_prefs = {**SKANE, "quietHours": {"from": hour, "to": (hour + 1) % 24}}
        sent = []
        with patch.object(notify, "_devices", return_value=[device]):
            notify.run_push_cycle(sender=lambda **m: sent.append(m) or {"ok": True})
        self.assertEqual(sent, [])
        self.assertEqual(PushDelivery.objects.get().status, PushDelivery.Status.SUPPRESSED)


class WeakNotifyDecisionTests(TestCase):
    """Svaga notiser: av som standard, ett uttryckligt val, aldrig Övrigt eller avslutat."""

    def test_a_weak_tip_never_reaches_a_driver_who_has_not_chosen_it(self):
        tip = weak_tip()
        self.assertEqual(notify.decide(SKANE, tip).reason, "not_notify_worthy")
        self.assertEqual(notify.decide({**SKANE, "weak": False}, tip).reason, "not_notify_worthy")
        # "true" som sträng är inget val.
        self.assertEqual(notify.decide({**SKANE, "weak": "true"}, tip).reason, "not_notify_worthy")

    def test_a_weak_tip_reaches_a_driver_who_chose_it(self):
        match = notify.decide({**SKANE, "weak": True}, weak_tip())
        self.assertTrue(match.ok, match.reason)
        self.assertTrue(match.weak)

    def test_never_ovrigt_ended_or_with_replacement_traffic(self):
        prefs = {**SKANE, "weak": True}
        cases = {
            "ovrigt": weak_tip(severity_tier=SeverityTier.IGNORE, demand_score=0),
            "ended": weak_tip(end_time=timezone.now() - timedelta(minutes=1)),
            "replacement": weak_tip(has_alternative=True),
            "suppressed": weak_tip(suppressed_at=timezone.now()),
            "road_queue": weak_tip(kind="road", mode="road", severity_tier=SeverityTier.ROAD_WORK_OR_QUEUE,
                                   demand_score=10, rule_id="road.medium.queue"),
        }
        for name, tip in cases.items():
            with self.subTest(name):
                self.assertFalse(notify.decide(prefs, tip).ok)

    def test_weak_notifications_keep_the_area_quiet_hours_and_pause(self):
        tip = weak_tip()
        prefs = {"counties": ["01"], "weak": True}
        self.assertEqual(notify.decide(prefs, tip).reason, "outside_area")
        pause = (timezone.now() + timedelta(hours=1)).isoformat()
        self.assertEqual(notify.decide({**SKANE, "weak": True, "pausedUntil": pause}, tip).reason, "paused")
        self.assertEqual(
            notify.decide({**SKANE, "weak": True, "quietHours": {"from": 1, "to": 6}}, tip, now=at(3)).reason,
            "quiet_hours",
        )

    def test_the_weak_cap_per_hour_does_not_touch_strong_tips(self):
        prefs = {**SKANE, "weak": True}
        cap = thresholds.NOTIFY_WEAK_MAX_PER_HOUR
        self.assertTrue(notify.decide(prefs, weak_tip(), recent=(cap - 1, cap - 1)).ok)
        self.assertEqual(notify.decide(prefs, weak_tip(), recent=(cap, cap)).reason, "weak_hourly_limit")
        # Ett starkt tips trängs aldrig undan av de svaga.
        self.assertTrue(notify.decide(prefs, strong(), recent=(cap, cap)).ok)

    def test_the_drivers_own_cap_counts_everything(self):
        prefs = {**SKANE, "maxPerHour": 2}
        self.assertTrue(notify.decide(prefs, strong(), recent=(1, 0)).ok)
        self.assertEqual(notify.decide(prefs, strong(), recent=(2, 0)).reason, "hourly_limit")

    def test_the_new_reasons_are_documented(self):
        for code in ("quiet_hours", "hourly_limit", "weak_hourly_limit"):
            self.assertIn(code, notify.REASONS)


class WeakPushCycleTests(SupabaseCompanyMixin, TestCase):
    def setUp(self):
        self.sent = []

    def sender(self, *, token, **_):
        self.sent.append(token)
        return {"ok": True}

    def cycle(self, devices):
        with patch.object(notify, "_devices", return_value=devices):
            return notify.run_push_cycle(sender=self.sender)

    def test_weak_tips_are_sent_only_to_phones_that_chose_them(self):
        tip = weak_tip()
        wants = FakeDevice({**SKANE, "weak": True}, label="Vill ha svaga")
        standard = FakeDevice(dict(SKANE), label="Rekommenderat")
        self.cycle([wants, standard])
        self.assertEqual(self.sent, [wants.push_token])
        self.assertTrue(PushDelivery.objects.get().snapshot["weak"])
        # notified_at är notisstunden för alla -- en svag notis rör den inte.
        tip.refresh_from_db()
        self.assertIsNone(tip.notified_at)
        # Och samma tips skickas inte igen nästa cykel.
        self.sent.clear()
        self.cycle([wants, standard])
        self.assertEqual(self.sent, [])

    def test_the_weak_cap_holds_in_the_cycle(self):
        for _ in range(thresholds.NOTIFY_WEAK_MAX_PER_HOUR + 2):
            weak_tip()
        wants = FakeDevice({**SKANE, "weak": True})
        self.cycle([wants])
        self.assertEqual(len(self.sent), thresholds.NOTIFY_WEAK_MAX_PER_HOUR)

    def test_an_old_weak_tip_is_not_sent_when_the_driver_switches_it_on(self):
        tip = weak_tip()
        Opportunity.objects.filter(pk=tip.pk).update(
            computed_at=timezone.now() - timedelta(minutes=thresholds.NOTIFY_WEAK_FRESH_MINUTES + 5)
        )
        self.cycle([FakeDevice({**SKANE, "weak": True})])
        self.assertEqual(self.sent, [])


class PresetTests(TestCase):
    def test_a_new_phone_is_recommended(self):
        self.assertEqual(notify_prefs.preset_of({}), "recommended")
        self.assertEqual(notify_prefs.preset_of(notify.default_prefs()), "recommended")

    def test_each_preset_reads_back_as_itself(self):
        for preset in ("recommended", "strongest", "everything", "silent"):
            with self.subTest(preset):
                prefs = notify_prefs.apply_update(
                    {"counties": ["12"]}, {"preset": preset}, entitled=["12"], restricted=True,
                )
                self.assertEqual(notify_prefs.preset_of(prefs, entitled=["12"]), preset)

    def test_recommended_follows_the_scoring(self):
        """Rekommenderat = notisgolvet och de notisvärda typerna, inget mer och inget mindre."""
        prefs = notify_prefs.apply_update({"counties": ["12"]}, {"preset": "recommended"})
        self.assertTrue(notify.decide(prefs, strong()).ok)
        self.assertTrue(notify.decide(prefs, strong(severity_tier=SeverityTier.VEHICLE_CANCELLED, level="high")).ok)
        self.assertFalse(notify.decide(prefs, weak_tip()).ok)

    def test_strongest_drops_single_cancellations(self):
        prefs = notify_prefs.apply_update({"counties": ["12"]}, {"preset": "strongest"})
        self.assertTrue(notify.decide(prefs, strong()).ok)
        cancelled = strong(severity_tier=SeverityTier.VEHICLE_CANCELLED, level="high")
        self.assertEqual(notify.decide(prefs, cancelled).reason, "type_off:vehicle_cancelled")

    def test_everything_takes_the_whole_licence(self):
        prefs = notify_prefs.apply_update(
            {"counties": ["12"], "municipalities": ["1280"]}, {"preset": "everything"},
            entitled=["12", "13"], restricted=True,
        )
        self.assertEqual(prefs["counties"], ["12", "13"])
        self.assertEqual(prefs["municipalities"], [])
        self.assertTrue(prefs["weak"])

    def test_unknown_values_are_not_stored(self):
        prefs = notify_prefs.apply_update(
            {}, {"preset": "allt", "maxPerHour": 999, "quietHours": {"from": 2, "to": 2}, "x": 1},
        )
        self.assertEqual(prefs, {})

    def test_weak_with_only_strong_means_at_least_medium(self):
        prefs = notify_prefs.apply_update({}, {"minLevel": "high", "weak": True})
        self.assertEqual(prefs["minLevel"], "medium")
