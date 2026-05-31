"""Tests for timeframe-aware parameter scaling."""

import math

import pytest

from app.regime.orchestrator import RegimeOrchestrator, timeframe_to_hours


class TestTimeframeToHours:
    def test_1h(self):
        assert timeframe_to_hours("1h") == 1.0

    def test_15m(self):
        assert timeframe_to_hours("15m") == 0.25

    def test_30m(self):
        assert timeframe_to_hours("30m") == 0.5

    def test_4h(self):
        assert timeframe_to_hours("4h") == 4.0

    def test_1d(self):
        assert timeframe_to_hours("1d") == 24.0

    def test_1w(self):
        assert timeframe_to_hours("1w") == 168.0

    def test_case_insensitive(self):
        assert timeframe_to_hours("1H") == 1.0
        assert timeframe_to_hours("15M") == 0.25

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            timeframe_to_hours("bad")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            timeframe_to_hours("")


class TestScaleDefaultsForTimeframe:
    """Test _scale_defaults_for_timeframe static method."""

    def test_1h_no_scaling(self):
        """1h is the reference timeframe -- params unchanged."""
        result = RegimeOrchestrator._scale_defaults_for_timeframe(
            "1h", 1000, 168, 5,
        )
        assert result == (1000, 168, 5)

    def test_15m_scales_by_4x(self):
        """15m = 4x more bars per hour -> multiply by 4."""
        result = RegimeOrchestrator._scale_defaults_for_timeframe(
            "15m", 1000, 168, 5,
        )
        assert result == (4000, 672, 20)

    def test_30m_scales_by_2x(self):
        result = RegimeOrchestrator._scale_defaults_for_timeframe(
            "30m", 1000, 168, 5,
        )
        assert result == (2000, 336, 10)

    def test_4h_scales_by_quarter(self):
        """4h = 4x fewer bars per hour -> divide by 4."""
        result = RegimeOrchestrator._scale_defaults_for_timeframe(
            "4h", 1000, 168, 5,
        )
        assert result == (250, 42, 1)

    def test_1d_scales_by_24th(self):
        result = RegimeOrchestrator._scale_defaults_for_timeframe(
            "1d", 1000, 168, 5,
        )
        assert result == (42, 7, 0) or result[2] >= 1  # min_dwell_bars >= 1
        # Exact: round(1000/24)=42, round(168/24)=7, round(5/24)=0 -> clamped to 1
        assert result == (42, 7, 1)

    def test_min_clamp_to_1(self):
        """All scaled values should be at least 1."""
        result = RegimeOrchestrator._scale_defaults_for_timeframe(
            "1d", 10, 10, 1,
        )
        assert all(v >= 1 for v in result)


class TestWalkForwardPurgeScaling:
    """Test timeframe-aware purge in walk-forward validators."""

    def test_purge_hours_at_1h(self):
        from app.regime.optimization.walk_forward import WalkForwardValidator
        wf = WalkForwardValidator(purge_hours=24.0, timeframe="1h")
        assert wf.purge_bars == 24

    def test_purge_hours_at_15m(self):
        from app.regime.optimization.walk_forward import WalkForwardValidator
        wf = WalkForwardValidator(purge_hours=24.0, timeframe="15m")
        assert wf.purge_bars == 96  # 24 / 0.25

    def test_purge_hours_at_4h(self):
        from app.regime.optimization.walk_forward import WalkForwardValidator
        wf = WalkForwardValidator(purge_hours=24.0, timeframe="4h")
        assert wf.purge_bars == 6  # 24 / 4

    def test_default_purge_without_timeframe(self):
        from app.regime.optimization.walk_forward import WalkForwardValidator
        wf = WalkForwardValidator(purge_bars=30)
        assert wf.purge_bars == 30

    def test_config_purge_bars_for_timeframe(self):
        from app.regime.optimization.models import WalkForwardConfig
        cfg = WalkForwardConfig(purge_hours=24.0)
        assert cfg.purge_bars_for_timeframe("1h") == 24
        assert cfg.purge_bars_for_timeframe("15m") == 96
        assert cfg.purge_bars_for_timeframe("4h") == 6

    def test_combinatorial_purge_scaling(self):
        from app.regime.optimization.walk_forward import CombinatorialPurgedCV
        cv = CombinatorialPurgedCV(
            purge_hours=24.0, embargo_hours=12.0, timeframe="15m",
        )
        assert cv.purge_bars == 96   # 24 / 0.25
        assert cv.embargo_bars == 48  # 12 / 0.25
