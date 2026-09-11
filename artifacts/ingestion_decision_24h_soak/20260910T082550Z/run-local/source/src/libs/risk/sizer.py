"""PositionSizer — dispatches to fixed_fractional, volatility_scaled, kelly, equal_weight."""

from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import TradeSignal
from libs.risk.account_state import AccountState

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class PositionSizer:
    """Calculate position size based on a named sizing strategy."""

    _STRATEGIES = {
        "fixed_fractional",
        "volatility_scaled",
        "kelly",
        "equal_weight",
    }

    def calculate(
        self,
        strategy: str,
        signal: TradeSignal,
        account: AccountState,
        risk_config: dict[str, Any],
    ) -> float:
        """Dispatch to the appropriate sizing method. Returns size in base-asset units."""
        if strategy not in self._STRATEGIES:
            logger.warning(f"Unknown sizing strategy '{strategy}', falling back to fixed_fractional")
            strategy = "fixed_fractional"

        method = getattr(self, f"_{strategy}")
        size = method(signal, account, risk_config)
        return max(size, 0.0)

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def _fixed_fractional(
        self,
        signal: TradeSignal,
        account: AccountState,
        config: dict[str, Any],
    ) -> float:
        """size = (equity * risk_per_trade_pct / 100) / (price * stop_distance_pct / 100)"""
        sizing = config.get("position_sizing", {})
        risk_pct = sizing.get("fixed_fractional", {}).get("risk_per_trade_pct", 2.0)
        stop_distance_pct = config.get("stop_loss", {}).get("fixed_pct", {}).get("pct", 2.0)

        if signal.price <= 0 or stop_distance_pct <= 0:
            return 0.0

        risk_amount = account.equity * risk_pct / 100.0
        stop_distance = signal.price * stop_distance_pct / 100.0
        return risk_amount / stop_distance

    def _volatility_scaled(
        self,
        signal: TradeSignal,
        account: AccountState,
        config: dict[str, Any],
    ) -> float:
        """size = (equity * target_risk_pct / 100) / (ATR * atr_multiplier)

        ATR is sourced from signal.metadata.get("ATR").
        Falls back to fixed_fractional if ATR is unavailable.
        """
        sizing = config.get("position_sizing", {})
        vol_config = sizing.get("volatility_scaled", {})
        target_risk_pct = vol_config.get("target_risk_pct", 1.0)
        atr_multiplier = vol_config.get("atr_multiplier", 2.0)

        atr = signal.metadata.get("ATR")
        if atr is None or atr <= 0:
            logger.debug("ATR unavailable in signal metadata — falling back to fixed_fractional")
            return self._fixed_fractional(signal, account, config)

        risk_amount = account.equity * target_risk_pct / 100.0
        denominator = atr * atr_multiplier
        if denominator <= 0:
            return 0.0
        return risk_amount / denominator

    def _kelly(
        self,
        signal: TradeSignal,
        account: AccountState,
        config: dict[str, Any],
    ) -> float:
        """size = kelly_fraction * (win_rate - (1 - win_rate) / rr_ratio) * equity / price

        Falls back to fixed_fractional if historical win_rate is unavailable.
        """
        sizing = config.get("position_sizing", {})
        kelly_config = sizing.get("kelly", {})
        fraction = kelly_config.get("fraction", 0.5)
        win_rate = signal.metadata.get("win_rate")
        rr_ratio = signal.metadata.get("rr_ratio")

        if win_rate is None or rr_ratio is None or rr_ratio <= 0:
            logger.debug("win_rate/rr_ratio unavailable — falling back to fixed_fractional")
            return self._fixed_fractional(signal, account, config)

        kelly_raw = win_rate - (1 - win_rate) / rr_ratio
        if kelly_raw <= 0 or signal.price <= 0:
            return 0.0

        return fraction * kelly_raw * account.equity / signal.price

    def _equal_weight(
        self,
        signal: TradeSignal,
        account: AccountState,
        config: dict[str, Any],
    ) -> float:
        """size = equity / (max_concurrent_positions * price)"""
        max_positions = config.get("global_limits", {}).get("max_concurrent_positions", 10)

        if signal.price <= 0 or max_positions <= 0:
            return 0.0

        return account.equity / (max_positions * signal.price)
