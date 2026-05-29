"""RiskEngine — evaluates rule chain, sizes position, attaches SL/TP."""

from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import RiskAssessment, TradeSignal
from libs.risk.account_state import AccountState
from libs.risk.position_tracker import PositionTracker
from libs.risk.rules.base import RiskContext, RiskRule
from libs.risk.sizer import PositionSizer
from libs.risk.stop_loss import StopLossCalculator
from libs.risk.take_profit import TakeProfitCalculator

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class RiskEngine:
    """Evaluate a signal through sizing, SL/TP, and risk-rule chain."""

    def __init__(
        self,
        rules: list[RiskRule],
        sizer: PositionSizer,
        sl_calc: StopLossCalculator,
        tp_calc: TakeProfitCalculator,
    ) -> None:
        self.rules = rules
        self.sizer = sizer
        self.sl_calc = sl_calc
        self.tp_calc = tp_calc

    def assess(
        self,
        signal: TradeSignal,
        account: AccountState,
        positions: PositionTracker,
        risk_config: dict[str, Any],
    ) -> RiskAssessment:
        """Run the full risk assessment pipeline for a single signal."""

        # 1. Calculate proposed size via PositionSizer
        sizing_strategy = risk_config.get("position_sizing", {}).get(
            "default_strategy", "fixed_fractional",
        )
        proposed_size = self.sizer.calculate(
            sizing_strategy, signal, account, risk_config,
        )

        # 2. Calculate SL/TP
        sl_method = risk_config.get("stop_loss", {}).get("default_method", "atr_based")
        sl_config = risk_config.get("stop_loss", {})
        sl_price = self.sl_calc.calculate(sl_method, signal, sl_config)

        tp_method = risk_config.get("take_profit", {}).get("default_method", "risk_reward")
        tp_config = risk_config.get("take_profit", {})
        tp_price = self.tp_calc.calculate(tp_method, signal, sl_price, tp_config)

        # Multi-TP: compute levels if method is multi_level
        tp_levels: list[float] = []
        tp_portions: list[float] = []
        trail_to_breakeven = False
        if tp_method == "multi_level":
            tp_levels, tp_portions, trail_to_breakeven = self.tp_calc.calculate_multi(
                signal, sl_price, tp_config,
            )
            # In multi-level mode, single tp_price is not used
            tp_price = None

        # 3. Build RiskContext
        context = RiskContext(
            signal=signal,
            proposed_size=proposed_size,
            account=account,
            positions=positions,
            risk_config=risk_config,
        )

        # 4. Iterate rules
        verdicts = []
        rules_applied = []
        rejection_reason = ""

        for rule in self.rules:
            verdict = rule.evaluate(context)
            verdicts.append(verdict)
            rules_applied.append(rule.name)

            if verdict.action == "REJECT":
                rejection_reason = f"{rule.name}: {verdict.reason}"
                logger.info(f"Signal REJECTED by {rule.name} — {verdict.reason}")
                return RiskAssessment(
                    allowed=False,
                    signal=signal,
                    proposed_size=0.0,
                    stop_loss_price=sl_price,
                    take_profit_price=tp_price,
                    rejection_reason=rejection_reason,
                    rules_applied=rules_applied,
                    verdicts=verdicts,
                    tp_levels=tp_levels,
                    tp_portions=tp_portions,
                    trail_to_breakeven=trail_to_breakeven,
                )

            if verdict.action == "MODIFY" and verdict.adjusted_size is not None:
                proposed_size = verdict.adjusted_size
                context.proposed_size = proposed_size

        # 5. All rules passed
        return RiskAssessment(
            allowed=True,
            signal=signal,
            proposed_size=proposed_size,
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            rejection_reason="",
            rules_applied=rules_applied,
            verdicts=verdicts,
            tp_levels=tp_levels,
            tp_portions=tp_portions,
            trail_to_breakeven=trail_to_breakeven,
        )
