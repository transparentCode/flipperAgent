"""
Regime optimization benchmark tiers.

Tier 1 — strategy_utility    (35%): Sharpe improvement, drawdown reduction
Tier 2 — predictive_power    (35%): Forward IC, vol forecast error, IC decay
Tier 3 — statistical_validity (GATE): Levene p-value, Cohen's d
Tier 4 — stability            (HARD CONSTRAINT, not weighted): Regime duration, flip-flop, transition entropy
Tier 5 — changepoint_quality  (10%): CP precision, recall, detection lag
"""

from . import (
    changepoint_quality,
    predictive_power,
    stability,
    statistical_validity,
    strategy_utility,
)

__all__ = [
    "strategy_utility",
    "predictive_power",
    "statistical_validity",
    "stability",
    "changepoint_quality",
]
