"""Tests for risk rules."""

import time
from unittest.mock import patch

import pytest

from libs.contracts.schemas import RiskVerdict, TradeSignal
from libs.risk.account_state import AccountState
from libs.risk.position_tracker import PositionTracker
from libs.risk.rules.base import RiskContext, RiskRuleRegistry

# Import rules to trigger @register decorators
from libs.risk.rules.max_exposure import MaxExposureRule
from libs.risk.rules.max_positions import MaxPositionsRule
from libs.risk.rules.max_drawdown import MaxDrawdownRule
from libs.risk.rules.daily_loss import DailyLossLimitRule
from libs.risk.rules.cooldown import CooldownAfterLossRule


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------


def _make_signal(**overrides) -> TradeSignal:
    defaults = dict(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_000_000.0,
        direction=1,
        conviction=0.8,
        price=50_000.0,
        idempotency_key="test_key",
        model_name="test_model",
        metadata={},
    )
    defaults.update(overrides)
    return TradeSignal(**defaults)


def _make_context(
    signal: TradeSignal | None = None,
    proposed_size: float = 0.1,
    account: AccountState | None = None,
    positions: PositionTracker | None = None,
    risk_config: dict | None = None,
) -> RiskContext:
    if signal is None:
        signal = _make_signal()
    if account is None:
        account = AccountState(10_000)
    if positions is None:
        positions = PositionTracker()
    if risk_config is None:
        risk_config = {
            "global_limits": {
                "max_total_exposure_pct": 80,
                "max_concurrent_positions": 10,
                "max_drawdown_pct": 15,
                "daily_loss_limit_pct": 5,
                "cooldown_after_loss_seconds": 60,
            },
        }
    return RiskContext(
        signal=signal,
        proposed_size=proposed_size,
        account=account,
        positions=positions,
        risk_config=risk_config,
    )


# -------------------------------------------------------------------
# MaxExposureRule
# -------------------------------------------------------------------


class TestMaxExposureRule:
    def test_allow_when_under_limit(self):
        rule = MaxExposureRule()
        ctx = _make_context(proposed_size=0.01)  # small size
        verdict = rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    def test_reject_when_over_limit(self):
        rule = MaxExposureRule()
        # proposed_size * price = 10 * 50000 = 500000 => 5000% of 10k equity
        ctx = _make_context(proposed_size=10.0)
        verdict = rule.evaluate(ctx)
        assert verdict.action == "REJECT"
        assert "exposure" in verdict.reason.lower() or "exceed" in verdict.reason.lower()

    def test_reject_when_zero_equity(self):
        rule = MaxExposureRule()
        account = AccountState(0)
        ctx = _make_context(account=account, proposed_size=0.01)
        verdict = rule.evaluate(ctx)
        assert verdict.action == "REJECT"


# -------------------------------------------------------------------
# MaxPositionsRule
# -------------------------------------------------------------------


class TestMaxPositionsRule:
    def test_allow_when_under_limit(self):
        rule = MaxPositionsRule()
        ctx = _make_context()
        verdict = rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    @pytest.mark.asyncio
    async def test_reject_when_at_limit(self):
        rule = MaxPositionsRule()
        positions = PositionTracker()
        from libs.contracts.schemas import PositionState

        for i in range(10):
            await positions.open_position(
                PositionState(
                    asset=f"ASSET{i}",
                    direction=1,
                    entry_price=100,
                    current_price=100,
                    size=1,
                    unrealized_pnl=0,
                    entry_timestamp=1_000_000,
                    source_model="test",
                    source_timeframe="1h",
                ),
            )
        ctx = _make_context(positions=positions)
        verdict = rule.evaluate(ctx)
        assert verdict.action == "REJECT"


# -------------------------------------------------------------------
# MaxDrawdownRule
# -------------------------------------------------------------------


class TestMaxDrawdownRule:
    def test_allow_when_no_drawdown(self):
        rule = MaxDrawdownRule()
        ctx = _make_context()
        verdict = rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    def test_reject_when_drawdown_exceeds(self):
        rule = MaxDrawdownRule()
        account = AccountState(10_000)
        # Simulate drawdown: set peak high, then lose realized PnL
        account.peak_equity = 10_000
        account.realized_pnl = -2_000  # equity = 8000, dd = 20%
        ctx = _make_context(account=account)
        verdict = rule.evaluate(ctx)
        assert verdict.action == "REJECT"
        assert "drawdown" in verdict.reason.lower()


# -------------------------------------------------------------------
# DailyLossLimitRule
# -------------------------------------------------------------------


class TestDailyLossLimitRule:
    def test_allow_when_no_daily_loss(self):
        rule = DailyLossLimitRule()
        ctx = _make_context()
        verdict = rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    def test_reject_when_daily_loss_exceeds(self):
        rule = DailyLossLimitRule()
        account = AccountState(10_000)
        account.daily_pnl = -600  # 6% of 10k, limit is 5%
        ctx = _make_context(account=account)
        verdict = rule.evaluate(ctx)
        assert verdict.action == "REJECT"
        assert "daily" in verdict.reason.lower() or "loss" in verdict.reason.lower()


# -------------------------------------------------------------------
# CooldownAfterLossRule
# -------------------------------------------------------------------


class TestCooldownAfterLossRule:
    def test_allow_when_no_cooldown_configured(self):
        rule = CooldownAfterLossRule()
        ctx = _make_context(
            risk_config={
                "global_limits": {"cooldown_after_loss_seconds": 0},
            },
        )
        verdict = rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    def test_allow_when_last_trade_was_profit(self):
        rule = CooldownAfterLossRule()
        account = AccountState(10_000)
        account.last_trade_pnl = 100
        account.last_trade_timestamp = time.time()
        ctx = _make_context(account=account)
        verdict = rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    def test_reject_during_cooldown(self):
        rule = CooldownAfterLossRule()
        account = AccountState(10_000)
        account.last_trade_pnl = -50
        account.last_trade_timestamp = time.time()  # just happened
        ctx = _make_context(account=account)
        verdict = rule.evaluate(ctx)
        assert verdict.action == "REJECT"
        assert "cooldown" in verdict.reason.lower()

    def test_allow_after_cooldown_elapsed(self):
        rule = CooldownAfterLossRule()
        account = AccountState(10_000)
        account.last_trade_pnl = -50
        account.last_trade_timestamp = time.time() - 120  # 2 min ago, cooldown is 60s
        ctx = _make_context(account=account)
        verdict = rule.evaluate(ctx)
        assert verdict.action == "ALLOW"


# -------------------------------------------------------------------
# Registry
# -------------------------------------------------------------------


class TestRiskRuleRegistry:
    def test_all_rules_registered(self):
        expected = {
            "MaxExposureRule",
            "MaxPositionsRule",
            "MaxDrawdownRule",
            "DailyLossLimitRule",
            "CooldownAfterLossRule",
        }
        assert expected.issubset(set(RiskRuleRegistry.list_all()))

    def test_get_returns_class(self):
        cls = RiskRuleRegistry.get("MaxExposureRule")
        assert cls is MaxExposureRule
