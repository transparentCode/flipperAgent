"""Tests for VolCircuitBreakerRule."""
import pytest
from unittest.mock import MagicMock

from libs.contracts.risk import RiskVerdict
from libs.contracts.signal import TradeSignal
from libs.risk.engine import RiskEngine
from libs.risk.rules.base import RiskContext, RiskRuleRegistry
from libs.risk.rules.vol_circuit_breaker import VolCircuitBreakerRule


def _make_context(
    vol_percentile=None,
    changepoint_prob=None,
    drawdown_pct=0.0,
    proposed_size=1.0,
    timestamp=1000000.0,
    cb_config=None,
):
    """Build a RiskContext with optional regime data."""
    metadata = {}
    if vol_percentile is not None or changepoint_prob is not None:
        regime = {}
        if vol_percentile is not None:
            regime["vol_percentile"] = vol_percentile
        if changepoint_prob is not None:
            regime["changepoint_prob"] = changepoint_prob
        metadata["regime_classification"] = regime

    signal = TradeSignal(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=timestamp,
        direction=1,
        price=50000.0,
        idempotency_key="test-key",
        metadata=metadata,
    )

    account = MagicMock()
    account.current_drawdown_pct = drawdown_pct

    config = {
        "vol_circuit_breaker": cb_config or {
            "enabled": True,
            "vol_percentile_reject_threshold": 95,
            "drawdown_velocity_reject_pct": 2.0,
            "drawdown_velocity_window_hours": 4,
            "vol_scaling_enabled": True,
            "vol_scaling_start_percentile": 70,
            "vol_scaling_floor": 0.25,
            "changepoint_reject_threshold": 0.85,
            "cooldown_bars": 6,
        },
    }

    return RiskContext(
        signal=signal,
        proposed_size=proposed_size,
        account=account,
        positions=MagicMock(),
        risk_config=config,
    )


class TestVolCircuitBreakerRule:
    def setup_method(self):
        self.rule = VolCircuitBreakerRule()

    def test_registered(self):
        assert "VolCircuitBreakerRule" in RiskRuleRegistry.list_all()

    def test_allow_normal_conditions(self):
        ctx = _make_context(vol_percentile=50.0, changepoint_prob=0.3)
        verdict = self.rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    def test_reject_vol_spike(self):
        ctx = _make_context(vol_percentile=97.0)
        verdict = self.rule.evaluate(ctx)
        assert verdict.action == "REJECT"
        assert "Vol percentile" in verdict.reason

    def test_reject_changepoint_spike(self):
        ctx = _make_context(changepoint_prob=0.90)
        verdict = self.rule.evaluate(ctx)
        assert verdict.action == "REJECT"
        assert "Changepoint" in verdict.reason

    def test_modify_high_vol_scaling(self):
        ctx = _make_context(vol_percentile=85.0, proposed_size=1.0)
        verdict = self.rule.evaluate(ctx)
        assert verdict.action == "MODIFY"
        assert verdict.adjusted_size is not None
        assert verdict.adjusted_size < 1.0
        assert verdict.adjusted_size >= 0.25  # floor

    def test_no_scaling_below_threshold(self):
        ctx = _make_context(vol_percentile=65.0)
        verdict = self.rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    def test_allow_without_regime_data(self):
        """Rule should ALLOW when no regime data is available and no drawdown velocity trigger."""
        ctx = _make_context()  # no regime data
        verdict = self.rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    def test_reads_nested_risk_yaml_config(self):
        ctx = _make_context(
            vol_percentile=97.0,
            cb_config=None,
        )
        ctx.risk_config = {
            "global_limits": {
                "vol_circuit_breaker": {
                    "enabled": True,
                    "vol_percentile_reject_threshold": 95,
                }
            }
        }

        verdict = self.rule.evaluate(ctx)

        assert verdict.action == "REJECT"

    def test_disabled(self):
        ctx = _make_context(
            vol_percentile=99.0,
            cb_config={"enabled": False},
        )
        verdict = self.rule.evaluate(ctx)
        assert verdict.action == "ALLOW"

    def test_drawdown_velocity_reject(self):
        """Rapid drawdown velocity triggers REJECT even without regime data."""
        rule = VolCircuitBreakerRule()

        # Simulate drawdown history: 0% -> 3% in 2 hours
        base_ts = 1000000.0
        ctx1 = _make_context(drawdown_pct=0.0, timestamp=base_ts)
        rule.evaluate(ctx1)  # seed history

        ctx2 = _make_context(drawdown_pct=3.0, timestamp=base_ts + 7200)
        verdict = rule.evaluate(ctx2)
        assert verdict.action == "REJECT"
        assert "velocity" in verdict.reason.lower()

    def test_vol_scaling_at_boundary(self):
        """At scale_start, scale should be 1.0 (no reduction)."""
        ctx = _make_context(vol_percentile=70.0, proposed_size=1.0)
        verdict = self.rule.evaluate(ctx)
        # At exactly scale_start, scale = 1.0, so ALLOW
        assert verdict.action == "ALLOW"

    def test_vol_scaling_at_100(self):
        """At vol_percentile 100, should be at floor but not REJECT (below reject threshold)."""
        ctx = _make_context(
            vol_percentile=94.0,  # below reject threshold of 95, but high
            proposed_size=1.0,
        )
        verdict = self.rule.evaluate(ctx)
        assert verdict.action == "MODIFY"
        assert verdict.adjusted_size is not None
        # At 94 percentile, scale = 1.0 - 0.75 * (94-70)/30 = 1.0 - 0.6 = 0.4
        assert 0.25 <= verdict.adjusted_size <= 0.5

    def test_risk_engine_applies_modify_adjusted_size(self):
        sizer = MagicMock()
        sizer.calculate.return_value = 1.0
        sl_calc = MagicMock()
        sl_calc.calculate.return_value = 49_000.0
        tp_calc = MagicMock()
        tp_calc.calculate.return_value = 52_000.0
        engine = RiskEngine(
            rules=[VolCircuitBreakerRule()],
            sizer=sizer,
            sl_calc=sl_calc,
            tp_calc=tp_calc,
        )
        signal = TradeSignal(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000000.0,
            direction=1,
            price=50_000.0,
            idempotency_key="engine-test",
            metadata={"regime_classification": {"vol_percentile": 85.0}},
        )
        account = MagicMock()
        account.current_drawdown_pct = 0.0
        positions = MagicMock()
        risk_config = {
            "vol_circuit_breaker": {
                "enabled": True,
                "vol_percentile_reject_threshold": 95,
                "vol_scaling_enabled": True,
                "vol_scaling_start_percentile": 70,
                "vol_scaling_floor": 0.25,
                "drawdown_velocity_reject_pct": 2.0,
                "drawdown_velocity_window_hours": 4,
                "changepoint_reject_threshold": 0.85,
            }
        }

        assessment = engine.assess(signal, account, positions, risk_config)

        assert assessment.allowed is True
        assert assessment.proposed_size < 1.0
        assert assessment.verdicts[0].action == "MODIFY"
