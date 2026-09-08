"""
Tester för core/compensation.py -- en per villkor i compensation_signal(),
samma mönster som test_text_scoring.py: bygg minimala alert-dictar direkt,
verifiera mot en känd RegionCompensationRule-rad.
"""

from django.test import TestCase
from django.utils import timezone

from core.compensation import compensation_signal
from core.models import RegionCompensationRule, TransportMode


def _rule(**overrides):
    base = dict(region="skane", threshold_minutes=20, taxi_cap_kr=2960, excluded_modes=[])
    base.update(overrides)
    return RegionCompensationRule.objects.create(**base)


class DefiniteCancellation(TestCase):
    def test_explicit_cancellation_in_known_region_gives_eligible_signal(self):
        _rule(region="skane", taxi_cap_kr=2960)
        alert = {"header": "Tåg 501 inställt", "description": "", "region": "skane"}
        result = compensation_signal(alert, "train")
        self.assertEqual(
            result,
            {"eligible": True, "cap_kr": 2960, "threshold_minutes": 20, "per_person": None},
        )

    def test_per_person_is_carried_through_when_the_source_states_it(self):
        # Skånetrafiken skriver ordagrant "per betalande resenär"; SL
        # skriver att beloppet inte blir högre vid samåkning. Fyra
        # strandsatta resenärer är två olika affärer, och en förare som
        # citerar siffran för dem ska citera rätt.
        _rule(region="skane", taxi_cap_kr=2960, cap_per_person=True)
        alert = {"header": "Tåg 501 inställt", "description": "", "region": "skane"}
        self.assertTrue(compensation_signal(alert, "train")["per_person"])

    def test_per_person_stays_unknown_when_the_source_is_silent(self):
        # None, inte False: "huvudmannen skriver inte ut det" är inte samma
        # sak som "taket gäller per resa".
        _rule(region="vt", taxi_cap_kr=1500)
        alert = {"header": "Buss 16 inställd", "description": "", "region": "vt"}
        self.assertIsNone(compensation_signal(alert, "bus")["per_person"])

    def test_serious_wording_without_explicit_cancellation_is_not_eligible(self):
        # Samma distinktion som redan finns för bus.serious-grenen: bara en
        # entydig utsago räcker, inte "allvarligt" ordval i stort.
        _rule(region="skane")
        alert = {"header": "Buss 173 påverkas av strejk", "description": "", "region": "skane"}
        result = compensation_signal(alert, "bus")
        self.assertIsNone(result)


class RegionGating(TestCase):
    def test_unknown_region_is_not_eligible(self):
        alert = {"header": "Inställd avgång", "description": "", "region": ""}
        self.assertIsNone(compensation_signal(alert, "bus"))

    def test_region_with_no_seeded_rule_is_not_eligible(self):
        alert = {"header": "Inställd avgång", "description": "", "region": "skane"}
        self.assertIsNone(compensation_signal(alert, "bus"))


class ExcludedModes(TestCase):
    def test_xtrafik_excludes_taxi_for_train_delays(self):
        _rule(region="xt", taxi_cap_kr=1480, excluded_modes=[TransportMode.TRAIN])
        alert = {"header": "Tåg inställt", "description": "", "region": "xt"}
        self.assertIsNone(compensation_signal(alert, "train"))

    def test_xtrafik_still_covers_bus(self):
        _rule(region="xt", taxi_cap_kr=1480, excluded_modes=[TransportMode.TRAIN])
        alert = {"header": "Buss inställd", "description": "", "region": "xt"}
        result = compensation_signal(alert, "bus")
        self.assertEqual(result["cap_kr"], 1480)


class AdvanceNoticeExclusion(TestCase):
    def test_disruption_announced_far_in_advance_is_not_eligible(self):
        _rule(region="skane")
        alert = {
            "header": "Inställd avgång", "description": "", "region": "skane",
            "active_from": timezone.now() + timezone.timedelta(days=10),
        }
        self.assertIsNone(compensation_signal(alert, "bus"))

    def test_disruption_starting_soon_is_still_eligible(self):
        _rule(region="skane")
        alert = {
            "header": "Inställd avgång", "description": "", "region": "skane",
            "active_from": timezone.now() + timezone.timedelta(hours=1),
        }
        self.assertIsNotNone(compensation_signal(alert, "bus"))

    def test_disruption_already_underway_is_still_eligible(self):
        _rule(region="skane")
        alert = {
            "header": "Inställd avgång", "description": "", "region": "skane",
            "active_from": timezone.now() - timezone.timedelta(hours=2),
        }
        self.assertIsNotNone(compensation_signal(alert, "bus"))
