"""StopLossCalculator — atr_based, fixed_pct, trailing."""

from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import TradeSignal

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class StopLossCalculator:
    """Calculate initial stop-loss price for a signal."""

    _METHODS = {"atr_based", "fixed_pct", "trailing"}

    def calculate(
        self,
        method: str,
        signal: TradeSignal,
        config: dict[str, Any],
    ) -> float | None:
        """Dispatch to the named SL method. Returns SL price or None."""
        if method not in self._METHODS:
            logger.warning(f"Unknown stop-loss method '{method}', falling back to atr_based")
            method = "atr_based"

        return getattr(self, f"_{method}")(signal, config)

    # ------------------------------------------------------------------
    # Methods
    # ------------------------------------------------------------------

    def _atr_based(self, signal: TradeSignal, config: dict[str, Any]) -> float | None:
        """SL = price -/+ ATR * multiplier (direction-aware).

        Long:  SL = price - ATR * multiplier
        Short: SL = price + ATR * multiplier
        """
        atr = signal.metadata.get("ATR")
        if atr is None or atr <= 0:
            logger.debug("ATR unavailable — cannot compute atr_based stop-loss")
            return None

        multiplier = config.get("atr_based", {}).get("multiplier", 2.0)
        distance = atr * multiplier

        if signal.direction == 1:
            return signal.price - distance
        elif signal.direction == -1:
            return signal.price + distance
        return None

    def _fixed_pct(self, signal: TradeSignal, config: dict[str, Any]) -> float | None:
        """SL = price * (1 -/+ pct/100)."""
        pct = config.get("fixed_pct", {}).get("pct", 2.0)

        if signal.direction == 1:
            return signal.price * (1 - pct / 100.0)
        elif signal.direction == -1:
            return signal.price * (1 + pct / 100.0)
        return None

    def _trailing(self, signal: TradeSignal, config: dict[str, Any]) -> float | None:
        """Initial SL same formula as atr_based but uses trailing config.

        Trailing updates are handled by PositionTracker.update_trailing_stops().
        """
        atr = signal.metadata.get("ATR")
        if atr is None or atr <= 0:
            logger.debug("ATR unavailable — cannot compute trailing stop-loss")
            return None

        multiplier = config.get("trailing", {}).get("atr_multiplier", 2.0)
        distance = atr * multiplier

        if signal.direction == 1:
            return signal.price - distance
        elif signal.direction == -1:
            return signal.price + distance
        return None
