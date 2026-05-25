"""TakeProfitCalculator — risk_reward, fixed_pct, trailing."""

from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import TradeSignal

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class TakeProfitCalculator:
    """Calculate initial take-profit price for a signal."""

    _METHODS = {"risk_reward", "fixed_pct", "trailing"}

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
