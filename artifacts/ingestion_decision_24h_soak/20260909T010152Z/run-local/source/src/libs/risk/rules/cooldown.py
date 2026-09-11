"""CooldownAfterLossRule — reject if last trade was a loss within cooldown window."""

from __future__ import annotations

import time

from libs.contracts.schemas import RiskVerdict
from libs.risk.rules.base import RiskContext, RiskRule, RiskRuleRegistry


@RiskRuleRegistry.register("CooldownAfterLossRule")
class CooldownAfterLossRule(RiskRule):
    """Reject if last closed trade was a loss AND happened < cooldown_seconds ago."""

    @property
    def name(self) -> str:
        return "CooldownAfterLossRule"

    def evaluate(self, context: RiskContext) -> RiskVerdict:
        cooldown_secs = context.risk_config.get("global_limits", {}).get(
            "cooldown_after_loss_seconds", 0,
        )

        if cooldown_secs <= 0:
            return RiskVerdict(action="ALLOW", rule_name=self.name)

        last_pnl = context.account.last_trade_pnl
        last_ts = context.account.last_trade_timestamp

        if last_pnl >= 0:
            return RiskVerdict(action="ALLOW", rule_name=self.name)

        elapsed = time.time() - last_ts
        if elapsed < cooldown_secs:
            return RiskVerdict(
                action="REJECT",
                rule_name=self.name,
                reason=(
                    f"Cooldown active — {elapsed:.0f}s since last loss "
                    f"(requires {cooldown_secs}s)"
                ),
            )

        return RiskVerdict(action="ALLOW", rule_name=self.name)
