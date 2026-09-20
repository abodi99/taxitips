"""
Tidsgränser och lås för Celery-taskarna.

Låset testas här mot en minimal Redis-attrapp. Eager-läge kör varken lås mot
riktig Redis eller tidsgränser, så det ersätter inte integrationskontrollen
med Redis, worker och beat -- se AGENTS.md.
"""

from __future__ import annotations

from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from core import locks, tasks


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        self.ttl[key] = ex
        return True

    def eval(self, script, numkeys, key, token):
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


class SingleRunTests(SimpleTestCase):
    def test_second_run_is_refused_while_the_first_holds_the_lock(self):
        redis = FakeRedis()
        with locks.single_run("poll_road", 300, client=redis) as first:
            with locks.single_run("poll_road", 300, client=redis) as second:
                self.assertTrue(first)
                self.assertFalse(second)
        self.assertEqual(redis.store, {})

    def test_lock_has_a_lifetime(self):
        redis = FakeRedis()
        with locks.single_run("poll_road", 300, client=redis):
            self.assertEqual(redis.ttl["taxitips:lock:poll_road"], 300)

    def test_does_not_release_a_lock_another_run_took_over(self):
        redis = FakeRedis()
        with locks.single_run("poll_road", 300, client=redis):
            # Vårt lås gick ut och en annan runda tog det.
            redis.store["taxitips:lock:poll_road"] = "annan-runda"
        self.assertEqual(redis.store["taxitips:lock:poll_road"], "annan-runda")

    def test_waits_for_a_running_poll_to_finish(self):
        redis = FakeRedis()
        redis.store["taxitips:lock:poll_sl"] = "vanlig-poll"
        sleeps = []

        def finish_running_poll(seconds):
            sleeps.append(seconds)
            redis.store.pop("taxitips:lock:poll_sl", None)

        with mock.patch("core.locks.time.sleep", side_effect=finish_running_poll):
            with locks.single_run("poll_sl", 300, wait_seconds=5, client=redis) as acquired:
                self.assertTrue(acquired)
        self.assertEqual(sleeps, [1])


class RunTests(SimpleTestCase):
    def setUp(self):
        self.redis = FakeRedis()
        patcher = mock.patch("core.locks._client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_skips_when_the_same_poll_is_running(self):
        self.redis.store["taxitips:lock:poll_road"] = "pågående"
        with mock.patch("core.tasks.call_command") as command:
            tasks.poll_road_task()
        command.assert_not_called()

    def test_runs_and_releases(self):
        with mock.patch("core.tasks.call_command") as command:
            tasks.poll_road_task()
        command.assert_called_once_with("poll_road")
        self.assertEqual(self.redis.store, {})

    def test_failure_is_logged_and_releases_the_lock(self):
        with mock.patch("core.tasks.call_command", side_effect=RuntimeError("timeout")):
            with self.assertLogs("core.tasks", level="ERROR"):
                tasks.poll_road_task()
        self.assertEqual(self.redis.store, {})

    def test_lock_outlives_the_hard_time_limit(self):
        with mock.patch("core.tasks.call_command"):
            tasks.poll_events_task()
        self.assertGreater(self.redis.ttl["taxitips:lock:poll_events"], tasks.EVENTS_LIMITS[1])
        with mock.patch("core.tasks.call_command"):
            tasks.poll_rail_task()
        self.assertGreater(self.redis.ttl["taxitips:lock:poll_rail"], settings.CELERY_TASK_TIME_LIMIT)

    def test_push_cycle_skips_while_another_cycle_runs(self):
        self.redis.store["taxitips:lock:push_cycle"] = "pågående"
        with mock.patch("core.notify.run_push_cycle") as cycle:
            result = tasks.push_cycle_task()
        cycle.assert_not_called()
        self.assertEqual(result["sent"], 0)


class ScheduleTests(SimpleTestCase):
    def test_every_task_has_a_time_limit(self):
        self.assertLess(settings.CELERY_TASK_SOFT_TIME_LIMIT, settings.CELERY_TASK_TIME_LIMIT)
        self.assertEqual(tasks.poll_events_task.time_limit, tasks.EVENTS_LIMITS[1])
        self.assertEqual(tasks.refresh_sites_task.soft_time_limit, tasks.SITES_LIMITS[0])
        self.assertEqual(tasks.push_cycle_task.soft_time_limit, tasks.PUSH_LIMITS[0])

    def test_queued_tasks_expire_after_their_interval(self):
        for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
            self.assertEqual(entry["options"]["expires"], entry["schedule"], name)


class TimeLimitTests(SimpleTestCase):
    """
    En runda som når den mjuka tidsgränsen avbryts, även inne i en slinga som
    fångar fel per operatör. Integrationskörningen 2026-09-13 visade motsatsen:
    "otraf: SoftTimeLimitExceeded()" fångades och rundan fortsatte.
    """

    def test_trafiklab_does_not_swallow_the_soft_time_limit(self):
        from celery.exceptions import SoftTimeLimitExceeded

        from core.sources import trafiklab

        with mock.patch.object(trafiklab, "configured_operators", return_value=["otraf", "ul"]):
            with mock.patch.object(trafiklab, "fetch_operator_alerts", side_effect=SoftTimeLimitExceeded()) as fetch:
                with self.assertRaises(SoftTimeLimitExceeded):
                    trafiklab.fetch_trafiklab_alerts("nyckel")
        fetch.assert_called_once()

    def test_an_ordinary_error_is_not_reraised(self):
        from core.time_limits import reraise_time_limit

        reraise_time_limit(RuntimeError("404"))
