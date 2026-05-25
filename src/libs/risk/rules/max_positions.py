"""MaxPositionsRule — reject if open positions >= max_concurrent_positions."""

from __future__ import annotations

from libs.contracts.schemas import RiskVerdict
from libs.risk.rules.base import RiskContext, RiskRule, RiskRuleRegistry


@RiskRuleRegistry.register("MaxPositionsRule")
class MaxPositionsRule(RiskRule):
    """Reject if open positions >= max_concurrent_positions."""

    @property
    def name(self) -> str:
        return "MaxPositionsRule"

    def evaluate(self, context: RiskContext) -> RiskVerdict:
        max_positions = context.risk_config.get("global_limits", {}).get(
            "max_concurrent_positions", 10,
        )
        current_count = context.positions.get_position_count()

        if current_count >= max_positions:
            return RiskVerdict(
                action="REJECT",
                rule_name=self.name,
                reason=(
                    f"Open positions ({current_count}) >= limit ({max_positions})"
                ),
            )

        return RiskVerdict(action="ALLOW", rule_name=self.name)
