"""MaxExposureRule — reject if total exposure + proposed exceeds limit."""

from __future__ import annotations

from libs.contracts.schemas import RiskVerdict
from libs.risk.rules.base import RiskContext, RiskRule, RiskRuleRegistry


@RiskRuleRegistry.register("MaxExposureRule")
class MaxExposureRule(RiskRule):
    """Reject if total exposure + proposed > max_total_exposure_pct of equity."""

    @property
    def name(self) -> str:
        return "MaxExposureRule"

    def evaluate(self, context: RiskContext) -> RiskVerdict:
        max_pct = context.risk_config.get("global_limits", {}).get(
            "max_total_exposure_pct", 80,
        )
        equity = context.account.equity
        if equity <= 0:
            return RiskVerdict(
                action="REJECT",
                rule_name=self.name,
                reason="Equity is zero or negative",
            )

        current_exposure = context.positions.get_total_exposure()
        proposed_exposure = context.proposed_size * context.signal.price
        total_exposure = current_exposure + proposed_exposure
        exposure_pct = total_exposure / equity * 100

        if exposure_pct > max_pct:
            return RiskVerdict(
                action="REJECT",
                rule_name=self.name,
                reason=(
                    f"Total exposure {exposure_pct:.1f}% would exceed "
                    f"limit {max_pct}%"
                ),
            )

        return RiskVerdict(action="ALLOW", rule_name=self.name)
