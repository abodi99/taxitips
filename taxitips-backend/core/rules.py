"""
Uppslag av ScoringRule -- delad mellan järnvägens strukturella klassificerare
(core/scoring.py) och den textbaserade transitklassificeraren (core/text_scoring.py).

Extraherad ur core/scoring.py:s tidigare privata _rule_for, generaliserad så
`mode` inte är hårdkodat till tåg -- ingen beteendeändring för järnvägen,
bara borttagen dubblering.
"""

from __future__ import annotations

from core.models import ScoringRule


def rule_for(tier: str, mode: str, condition: str = "") -> ScoringRule | None:
    """
    Hämtar regeln för en tier + färdsätt + gren.

    Exakt match på grenen först; först om ingen finns används en regel som
    gäller hela nivån (mode="" täcker alla färdsätt). Saknas båda
    poängsätts ändå -- en tom regeltabell ska aldrig stoppa pipelinen.
    """
    try:
        rules = ScoringRule.objects.filter(tier=tier, mode__in=[mode, ""])
        if condition:
            exact = rules.filter(condition=condition).first()
            if exact:
                return exact
        return rules.filter(condition="").first()
    except Exception:
        return None
