"""Tests for RiskEngine."""

import pytest

from libs.contracts.schemas import RiskVerdict, TradeSignal
from libs.risk.account_state import AccountState
from libs.risk.engine import RiskEngine
from libs.risk.position_tracker import PositionTracker
from libs.risk.rules.base import RiskContext, RiskRule
from libs.risk.sizer import PositionSizer
from libs.risk.stop_loss import StopLossCalculator
from libs.risk.take_profit import TakeProfitCalculator


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
        metadata={"ATR": 500.0},
    )
    defaults.update(overrides)
    return TradeSignal(**defaults)


class AlwaysAllowRule(RiskRule):
    @property
    def name(self) -> str:
        return "AlwaysAllowRule"

    def evaluate(self, context: RiskContext) -> RiskVerdict:
        return RiskVerdict(action="ALLOW", rule_name=self.name)


class AlwaysRejectRule(RiskRule):
    @property
    def name(self) -> str:
        return "AlwaysRejectRule"

    def evaluate(self, context: RiskContext) -> RiskVerdict:
        return RiskVerdict(
            action="REJECT",
            rule_name=self.name,
            reason="Always reject",
        )


class HalveSizeRule(RiskRule):
    @property
    def name(self) -> str:
        return "HalveSizeRule"

    def evaluate(self, context: RiskContext) -> RiskVerdict:
        return RiskVerdict(
            action="MODIFY",
            rule_name=self.name,
            adjusted_size=context.proposed_size / 2,
        )


@pytest.fixture
def risk_config():
    return {
        "position_sizing": {
            "default_strategy": "fixed_fractional",
            "fixed_fractional": {"risk_per_trade_pct": 2.0},
        },
        "stop_loss": {
            "default_method": "fixed_pct",
            "fixed_pct": {"pct": 2.0},
        },
        "take_profit": {
            "default_method": "risk_reward",
            "risk_reward": {"ratio": 2.0},
        },
        "global_limits": {"max_concurrent_positions": 10},
    }


def _build_engine(rules: list[RiskRule]) -> RiskEngine:
    return RiskEngine(
        rules=rules,
        sizer=PositionSizer(),
        sl_calc=StopLossCalculator(),
        tp_calc=TakeProfitCalculator(),
    )


class TestRiskEngineAllow:
    def test_all_allow(self, risk_config):
        engine = _build_engine([AlwaysAllowRule(), AlwaysAllowRule()])
        signal = _make_signal()
        account = AccountState(10_000)
        positions = PositionTracker()

        result = engine.assess(signal, account, positions, risk_config)
        assert result.allowed is True
        assert result.proposed_size > 0
        assert len(result.rules_applied) == 2
        assert len(result.verdicts) == 2


class TestRiskEngineReject:
    def test_first_reject_stops_chain(self, risk_config):
        engine = _build_engine([AlwaysRejectRule(), AlwaysAllowRule()])
        signal = _make_signal()
        account = AccountState(10_000)
        positions = PositionTracker()

        result = engine.assess(signal, account, positions, risk_config)
        assert result.allowed is False
        assert result.proposed_size == 0.0
        assert "AlwaysRejectRule" in result.rejection_reason
        # Should have stopped after first rule
        assert len(result.rules_applied) == 1

    def test_reject_after_allow(self, risk_config):
        engine = _build_engine([AlwaysAllowRule(), AlwaysRejectRule()])
        signal = _make_signal()
        account = AccountState(10_000)
        positions = PositionTracker()

        result = engine.assess(signal, account, positions, risk_config)
        assert result.allowed is False
        assert len(result.rules_applied) == 2


class TestRiskEngineModify:
    def test_modify_reduces_size(self, risk_config):
        engine = _build_engine([HalveSizeRule(), AlwaysAllowRule()])
        signal = _make_signal()
        account = AccountState(10_000)
        positions = PositionTracker()

        result = engine.assess(signal, account, positions, risk_config)
        assert result.allowed is True
        # Size should be halved by HalveSizeRule
        original_engine = _build_engine([AlwaysAllowRule()])
        original = original_engine.assess(signal, account, positions, risk_config)
        assert result.proposed_size == pytest.approx(original.proposed_size / 2)


class TestRiskEngineSLTP:
    def test_sl_tp_attached(self, risk_config):
        engine = _build_engine([AlwaysAllowRule()])
        signal = _make_signal()
        account = AccountState(10_000)
        positions = PositionTracker()

        result = engine.assess(signal, account, positions, risk_config)
        assert result.stop_loss_price is not None
        assert result.take_profit_price is not None
        # For long: SL < price < TP
        assert result.stop_loss_price < signal.price
        assert result.take_profit_price > signal.price
