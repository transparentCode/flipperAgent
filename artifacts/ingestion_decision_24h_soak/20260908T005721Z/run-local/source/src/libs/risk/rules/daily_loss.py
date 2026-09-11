"""DailyLossLimitRule — reject if daily PnL loss exceeds limit."""

from __future__ import annotations

from libs.contracts.schemas import RiskVerdict
from libs.risk.rules.base import RiskContext, RiskRule, RiskRuleRegistry


@RiskRuleRegistry.register("DailyLossLimitRule")
class DailyLossLimitRule(RiskRule):
    """Reject if daily PnL loss > daily_loss_limit_pct of equity."""

    @property
    def name(self) -> str:
        return "DailyLossLimitRule"

    def evaluate(self, context: RiskContext) -> RiskVerdict:
        limit_pct = context.risk_config.get("global_limits", {}).get(
            "daily_loss_limit_pct", 5,
        )
        equity = context.account.equity
        if equity <= 0:
            return RiskVerdict(
                action="REJECT",
                rule_name=self.name,
                reason="Equity is zero or negative",
            )

        daily_loss_pct = abs(min(context.account.daily_pnl, 0.0)) / equity * 100

        if daily_loss_pct > limit_pct:
            return RiskVerdict(
                action="REJECT",
                rule_name=self.name,
                reason=(
                    f"Daily loss {daily_loss_pct:.2f}% exceeds limit {limit_pct}%"
                ),
            )

        return RiskVerdict(action="ALLOW", rule_name=self.name)
