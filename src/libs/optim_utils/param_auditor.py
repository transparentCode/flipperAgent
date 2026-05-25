"""Audit and benchmark proposed params against current params.

Runs model.batch_evaluate() with both param sets on the same historical
data and produces a ParamAuditReport with standardized performance deltas.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import ParamAuditReport
from libs.models.registry import ModelRegistry
from libs.optim_utils.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
    compute_win_rate,
)

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

# Thresholds for automatic recommendation
_SHARPE_IMPROVEMENT_THRESHOLD = 0.1
_DRAWDOWN_DEGRADATION_THRESHOLD = 0.05


class ParamAuditor:
    """Compare current vs proposed params via standardized metrics.

    Uses the shared scoring utilities for consistent metric computation
    across all models — independent of each model's optimization objective.
    """

    def __init__(
        self,
        feature_df: pd.DataFrame,
        timeframe: str = "1h",
        cost_bps: float = 10.0,
    ) -> None:
        if "close" not in feature_df.columns:
            raise ValueError("feature_df must contain a 'close' column")
        self.feature_df = feature_df
        self.timeframe = timeframe
        self.cost_bps = cost_bps

    def _score(self, model) -> dict[str, float]:
        """Run batch_evaluate and compute standardized metrics."""
        directions = model.batch_evaluate(self.feature_df)
        close = self.feature_df["close"].values
        returns, trade_mask = compute_returns(
            directions.values, close, cost_bps=self.cost_bps,
        )
        return {
            "sharpe": compute_sharpe(returns, self.timeframe),
            "max_drawdown": compute_max_drawdown(returns),
            "win_rate": compute_win_rate(returns, trade_mask),
            "total_trades": float(np.sum(trade_mask)),
        }

    def audit(
        self,
        model_name: str,
        asset: str,
        timeframe: str,
        current_params: dict[str, Any],
        proposed_params: dict[str, Any],
    ) -> ParamAuditReport:
        """Run both param sets and compare."""
        model_cls = ModelRegistry.get(model_name)

        current_metrics = self._score(model_cls(current_params))
        proposed_metrics = self._score(model_cls(proposed_params))

        deltas = {k: proposed_metrics[k] - current_metrics[k] for k in current_metrics}
        recommendation, reason = self._recommend(deltas)

        report = ParamAuditReport(
            model_name=model_name,
            asset=asset,
            timeframe=timeframe,
            current_params=current_params,
            proposed_params=proposed_params,
            current_metrics=current_metrics,
            proposed_metrics=proposed_metrics,
            deltas=deltas,
            recommendation=recommendation,
            reason=reason,
        )

        logger.info(
            f"Param audit for {model_name}/{asset}/{timeframe}: "
            f"recommendation={recommendation}, "
            f"sharpe_delta={deltas['sharpe']:+.4f}, "
            f"dd_delta={deltas['max_drawdown']:+.4f}"
        )
        return report

    @staticmethod
    def _recommend(deltas: dict[str, float]) -> tuple[str, str]:
        sharpe_d = deltas.get("sharpe", 0.0)
        dd_d = deltas.get("max_drawdown", 0.0)
        dd_worsened = dd_d < -_DRAWDOWN_DEGRADATION_THRESHOLD

        if dd_worsened:
            return "reject", (
                f"Drawdown worsened by {abs(dd_d):.4f} "
                f"(threshold: {_DRAWDOWN_DEGRADATION_THRESHOLD})"
            )
        if sharpe_d >= _SHARPE_IMPROVEMENT_THRESHOLD:
            return "adopt", (
                f"Sharpe improved by {sharpe_d:+.4f} "
                f"without significant drawdown degradation"
            )
        return "review", (
            f"Sharpe delta {sharpe_d:+.4f} below auto-adopt threshold "
            f"({_SHARPE_IMPROVEMENT_THRESHOLD}); manual review recommended"
        )
