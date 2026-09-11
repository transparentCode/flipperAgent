"""MaxDrawdownRule — circuit breaker that rejects all trades when drawdown is too high."""

from __future__ import annotations

from libs.contracts.schemas import RiskVerdict
from libs.risk.rules.base import RiskContext, RiskRule, RiskRuleRegistry


@RiskRuleRegistry.register("MaxDrawdownRule")
class MaxDrawdownRule(RiskRule):
    """Reject ALL new trades if current_drawdown_pct > max_drawdown_pct."""

    @property
    def name(self) -> str:
        return "MaxDrawdownRule"

    def evaluate(self, context: RiskContext) -> RiskVerdict:
        max_dd_pct = context.risk_config.get("global_limits", {}).get(
            "max_drawdown_pct", 15,
        )
        current_dd = context.account.current_drawdown_pct

        if current_dd > max_dd_pct:
            return RiskVerdict(
                action="REJECT",
                rule_name=self.name,
                reason=(
                    f"Drawdown {current_dd:.2f}% exceeds circuit breaker "
                    f"limit {max_dd_pct}%"
                ),
            )

        return RiskVerdict(action="ALLOW", rule_name=self.name)
