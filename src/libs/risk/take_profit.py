"""TakeProfitCalculator — risk_reward, fixed_pct, trailing."""

from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import TradeSignal

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class TakeProfitCalculator:
    """Calculate initial take-profit price for a signal."""

    _METHODS = {"risk_reward", "fixed_pct", "trailing", "multi_level"}

    def calculate(
        self,
        method: str,
        signal: TradeSignal,
        stop_loss_price: float | None,
        config: dict[str, Any],
    ) -> float | None:
        """Dispatch to the named TP method. Returns TP price or None."""
        if method not in self._METHODS:
            logger.warning(f"Unknown take-profit method '{method}', falling back to risk_reward")
            method = "risk_reward"

        if method == "multi_level":
            # Multi-level TP uses calculate_multi() instead; no single TP price
            return None

        return getattr(self, f"_{method}")(signal, stop_loss_price, config)

    # ------------------------------------------------------------------
    # Methods
    # ------------------------------------------------------------------

    def _risk_reward(
        self,
        signal: TradeSignal,
        stop_loss_price: float | None,
        config: dict[str, Any],
    ) -> float | None:
        """TP = entry +/- (|entry - SL| * ratio).

        Long:  TP = price + risk_distance * ratio
        Short: TP = price - risk_distance * ratio
        """
        if stop_loss_price is None:
            logger.debug("No stop-loss price — cannot compute risk_reward take-profit")
            return None

        ratio = config.get("risk_reward", {}).get("ratio", 2.0)
        risk_distance = abs(signal.price - stop_loss_price)

        if signal.direction == 1:
            return signal.price + risk_distance * ratio
        elif signal.direction == -1:
            return signal.price - risk_distance * ratio
        return None

    def _fixed_pct(
        self,
        signal: TradeSignal,
        stop_loss_price: float | None,
        config: dict[str, Any],
    ) -> float | None:
        """TP = price * (1 +/- pct/100)."""
        pct = config.get("fixed_pct", {}).get("pct", 4.0)

        if signal.direction == 1:
            return signal.price * (1 + pct / 100.0)
        elif signal.direction == -1:
            return signal.price * (1 - pct / 100.0)
        return None

    def _trailing(
        self,
        signal: TradeSignal,
        stop_loss_price: float | None,
        config: dict[str, Any],
    ) -> float | None:
        """Initial TP same formula as risk_reward but uses trailing config.

        Trailing updates are handled by PositionTracker at runtime.
        """
        if stop_loss_price is None:
            logger.debug("No stop-loss price — cannot compute trailing take-profit")
            return None

        ratio = config.get("trailing", {}).get("atr_multiplier", 3.0)
        risk_distance = abs(signal.price - stop_loss_price)

        if signal.direction == 1:
            return signal.price + risk_distance * ratio
        elif signal.direction == -1:
            return signal.price - risk_distance * ratio
        return None

    # ------------------------------------------------------------------
    # Multi-level TP
    # ------------------------------------------------------------------

    def calculate_multi(
        self,
        signal: TradeSignal,
        stop_loss_price: float | None,
        config: dict[str, Any],
    ) -> tuple[list[float], list[float], bool]:
        """Compute multi-level TP prices and portions from config.

        Returns
        -------
        tp_levels : list[float]
            TP prices in ascending order (long) or descending order (short).
        tp_portions : list[float]
            Fraction of original position to close at each level.
        trail_to_breakeven : bool
            Whether to move SL to entry after first TP hit.
        """
        ml_cfg = config.get("multi_level", {})
        levels = ml_cfg.get("levels", [])
        trail = ml_cfg.get("trail_to_breakeven", False)

        if not levels:
            logger.warning("multi_level config has no levels defined")
            return [], [], trail

        tp_prices: list[float] = []
        tp_portions: list[float] = []

        for lvl in levels:
            pct = lvl.get("pct", 0.0)
            portion = lvl.get("portion", 0.0)

            if signal.direction == 1:
                tp_prices.append(signal.price * (1 + pct / 100.0))
            elif signal.direction == -1:
                tp_prices.append(signal.price * (1 - pct / 100.0))
            else:
                continue

            tp_portions.append(portion)

        total_portion = sum(tp_portions)
        if total_portion > 1.0 + 1e-9:
            logger.warning(
                f"multi_level portions sum to {total_portion:.4f} > 1.0, "
                "normalizing to 1.0",
            )
            tp_portions = [p / total_portion for p in tp_portions]

        logger.debug(
            f"Multi-TP calculated — direction={signal.direction}, "
            f"entry={signal.price:.4f}, levels={tp_prices}, "
            f"portions={tp_portions}, trail={trail}",
        )
        return tp_prices, tp_portions, trail
