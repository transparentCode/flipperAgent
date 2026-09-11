"""SignalAggregator — MTF conflict resolution strategies."""

from __future__ import annotations

from libs.contracts.schemas import TradeSignal
from libs.optim_utils.scoring import BARS_PER_YEAR


def _tf_rank(tf: str) -> int:
    """Lower BARS_PER_YEAR = higher timeframe = higher rank."""
    return -BARS_PER_YEAR.get(tf, 999_999)


class SignalAggregator:
    """Resolve multiple signals for the same asset across timeframes."""

    _STRATEGIES = {
        "conviction_weighted",
        "higher_tf_priority",
        "cancel_on_conflict",
        "independent",
    }

    def aggregate(
        self,
        signals: list[TradeSignal],
        strategy: str,
        tf_weights: dict[str, float],
    ) -> TradeSignal | list[TradeSignal] | None:
        """Dispatch to named strategy. Returns aggregated signal, list, or None."""
        if not signals:
            return None

        if strategy not in self._STRATEGIES:
            strategy = "conviction_weighted"

        method = getattr(self, f"_{strategy}")
        return method(signals, tf_weights)

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def _conviction_weighted(
        self,
        signals: list[TradeSignal],
        tf_weights: dict[str, float],
    ) -> TradeSignal | None:
        """Net direction = sign(sum(direction * conviction * tf_weight)).
        Net conviction = |weighted_sum| / sum(weights).
        Returns None if net direction is 0."""
        weighted_sum = 0.0
        total_weight = 0.0

        for sig in signals:
            w = tf_weights.get(sig.timeframe, 1.0)
            weighted_sum += sig.direction * sig.conviction * w
            total_weight += w

        if total_weight == 0 or weighted_sum == 0:
            return None

        net_direction = 1 if weighted_sum > 0 else -1
        net_conviction = min(abs(weighted_sum) / total_weight, 1.0)

        # Use the latest signal as the base
        base = max(signals, key=lambda s: s.timestamp)
        return TradeSignal(
            asset=base.asset,
            timeframe=base.timeframe,
            timestamp=base.timestamp,
            direction=net_direction,
            conviction=net_conviction,
            price=base.price,
            idempotency_key=base.idempotency_key,
            model_name=base.model_name,
            metadata=base.metadata,
        )

    def _higher_tf_priority(
        self,
        signals: list[TradeSignal],
        tf_weights: dict[str, float],
    ) -> TradeSignal | None:
        """Take the signal from the highest timeframe."""
        sorted_signals = sorted(signals, key=lambda s: _tf_rank(s.timeframe), reverse=True)
        return sorted_signals[0]

    def _cancel_on_conflict(
        self,
        signals: list[TradeSignal],
        tf_weights: dict[str, float],
    ) -> TradeSignal | None:
        """If any disagreement on direction, return None."""
        directions = {s.direction for s in signals}
        if len(directions) > 1:
            return None

        # All agree — use the latest signal
        return max(signals, key=lambda s: s.timestamp)

    def _independent(
        self,
        signals: list[TradeSignal],
        tf_weights: dict[str, float],
    ) -> list[TradeSignal]:
        """Pass all signals through independently — no aggregation or conflict resolution.

        Each signal is evaluated by RiskEngine separately, allowing multiple
        concurrent positions from different timeframes for the same asset.
        Returns the full list; caller receives list[TradeSignal] instead of TradeSignal.
        """
        return list(signals)


