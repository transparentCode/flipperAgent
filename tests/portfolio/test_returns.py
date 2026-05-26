"""Tests for libs/portfolio/returns.py — resample and return computation."""

import math

import pytest

from libs.contracts.schemas import EquityPoint
from libs.portfolio.returns import (
    compute_log_returns,
    compute_simple_returns,
    get_return_timestamps,
    resample_equity_curve,
)


def _make_point(ts: float, equity: float, **kw) -> EquityPoint:
    defaults = dict(
        timestamp=ts,
        equity=equity,
        balance=equity,
        unrealized_pnl=0.0,
        drawdown_pct=0.0,
        open_position_count=0,
    )
    defaults.update(kw)
    return EquityPoint(**defaults)


# ---------------------------------------------------------------------------
# resample_equity_curve
# ---------------------------------------------------------------------------

class TestResampleEquityCurve:
    def test_empty_input(self):
        assert resample_equity_curve([], 3600) == []

    def test_single_point(self):
        pts = [_make_point(1000, 100)]
        result = resample_equity_curve(pts, 3600)
        assert len(result) == 1
        assert result[0].equity == 100

    def test_exact_interval_alignment(self):
        """Points already on the grid should pass through."""
        pts = [
            _make_point(0, 100),
            _make_point(3600, 110),
            _make_point(7200, 120),
        ]
        result = resample_equity_curve(pts, 3600)
        assert len(result) == 3
        assert [p.equity for p in result] == [100, 110, 120]

    def test_forward_fill(self):
        """Gaps should be filled with last known value."""
        pts = [
            _make_point(0, 100),
            _make_point(7200, 120),
        ]
        result = resample_equity_curve(pts, 3600)
        assert len(result) == 3
        assert result[0].equity == 100
        assert result[1].equity == 100  # forward-filled
        assert result[2].equity == 120

    def test_irregular_timestamps(self):
        """Non-grid timestamps should snap correctly."""
        pts = [
            _make_point(100, 100),
            _make_point(3700, 110),
            _make_point(5000, 115),
            _make_point(7300, 120),
        ]
        result = resample_equity_curve(pts, 3600)
        assert len(result) == 3  # 100, 3700, 7300
        assert result[0].equity == 100
        assert result[1].equity == 110
        assert result[2].equity == 120

    def test_negative_interval_returns_empty(self):
        pts = [_make_point(0, 100)]
        assert resample_equity_curve(pts, -1) == []

    def test_zero_interval_returns_empty(self):
        pts = [_make_point(0, 100)]
        assert resample_equity_curve(pts, 0) == []

    def test_unsorted_input_is_sorted(self):
        """Input need not be sorted."""
        pts = [
            _make_point(7200, 120),
            _make_point(0, 100),
            _make_point(3600, 110),
        ]
        result = resample_equity_curve(pts, 3600)
        assert len(result) == 3
        assert [p.equity for p in result] == [100, 110, 120]

    def test_preserves_fields(self):
        """Non-equity fields should also forward-fill."""
        pts = [
            _make_point(0, 100, drawdown_pct=1.5, open_position_count=2),
            _make_point(7200, 120, drawdown_pct=0.5, open_position_count=1),
        ]
        result = resample_equity_curve(pts, 3600)
        assert result[1].drawdown_pct == 1.5
        assert result[1].open_position_count == 2


# ---------------------------------------------------------------------------
# compute_log_returns
# ---------------------------------------------------------------------------

class TestComputeLogReturns:
    def test_empty(self):
        assert compute_log_returns([]) == []

    def test_single_point(self):
        assert compute_log_returns([_make_point(0, 100)]) == []

    def test_basic(self):
        pts = [_make_point(0, 100), _make_point(1, 110)]
        returns = compute_log_returns(pts)
        assert len(returns) == 1
        assert returns[0] == pytest.approx(math.log(110 / 100))

    def test_multiple(self):
        pts = [
            _make_point(0, 100),
            _make_point(1, 110),
            _make_point(2, 105),
        ]
        returns = compute_log_returns(pts)
        assert len(returns) == 2
        assert returns[0] == pytest.approx(math.log(1.1))
        assert returns[1] == pytest.approx(math.log(105 / 110))

    def test_zero_equity_skipped(self):
        pts = [_make_point(0, 0), _make_point(1, 100)]
        returns = compute_log_returns(pts)
        assert returns[0] == 0.0


# ---------------------------------------------------------------------------
# compute_simple_returns
# ---------------------------------------------------------------------------

class TestComputeSimpleReturns:
    def test_empty(self):
        assert compute_simple_returns([]) == []

    def test_basic(self):
        pts = [_make_point(0, 100), _make_point(1, 110)]
        returns = compute_simple_returns(pts)
        assert len(returns) == 1
        assert returns[0] == pytest.approx(0.1)

    def test_loss(self):
        pts = [_make_point(0, 100), _make_point(1, 90)]
        returns = compute_simple_returns(pts)
        assert returns[0] == pytest.approx(-0.1)


# ---------------------------------------------------------------------------
# get_return_timestamps
# ---------------------------------------------------------------------------

class TestGetReturnTimestamps:
    def test_empty(self):
        assert get_return_timestamps([]) == []

    def test_single_point(self):
        assert get_return_timestamps([_make_point(100, 100)]) == []

    def test_returns_later_timestamps(self):
        pts = [
            _make_point(100, 100),
            _make_point(200, 110),
            _make_point(300, 120),
        ]
        ts = get_return_timestamps(pts)
        assert ts == [200, 300]
