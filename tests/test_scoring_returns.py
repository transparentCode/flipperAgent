"""Tests for compute_signal_weighted_returns."""

from __future__ import annotations

import numpy as np
import pytest

from libs.optim_utils.scoring import compute_signal_weighted_returns


class TestSignalWeightedReturns:

    def test_basic_long_position(self):
        """Full long position: edge_score=1 at each bar."""
        edge = np.array([1.0, 1.0, 1.0, 1.0])
        close = np.array([100.0, 110.0, 105.0, 120.0])
        ret = compute_signal_weighted_returns(edge, close, cost_bps=0.0)
        expected = np.diff(close) / close[:-1]  # [0.1, -0.0454, 0.1428]
        np.testing.assert_allclose(ret, expected, atol=1e-4)

    def test_zero_positions(self):
        """No position → no returns."""
        edge = np.array([0.0, 0.0, 0.0])
        close = np.array([100.0, 110.0, 105.0])
        ret = compute_signal_weighted_returns(edge, close, cost_bps=0.0)
        np.testing.assert_allclose(ret, [0.0, 0.0], atol=1e-10)

    def test_position_clipping(self):
        """Edge scores beyond max_position are clipped."""
        edge = np.array([5.0, -3.0, 0.0])
        close = np.array([100.0, 110.0, 105.0])
        ret = compute_signal_weighted_returns(edge, close, cost_bps=0.0, max_position=1.0)
        bar_returns = np.diff(close) / close[:-1]
        expected = np.array([1.0 * bar_returns[0], -1.0 * bar_returns[1]])
        np.testing.assert_allclose(ret, expected, atol=1e-10)

    def test_transaction_costs(self):
        """Verify transaction costs are deducted on position changes."""
        edge = np.array([1.0, 1.0, 0.0, 1.0])
        close = np.array([100.0, 110.0, 105.0, 120.0])
        ret_no_cost = compute_signal_weighted_returns(edge, close, cost_bps=0.0)
        ret_with_cost = compute_signal_weighted_returns(edge, close, cost_bps=100.0)
        # With costs, returns should be lower
        assert np.sum(ret_with_cost) < np.sum(ret_no_cost)

    def test_output_length(self):
        """Output length is len(close) - 1."""
        edge = np.array([0.5, -0.3, 0.2, 0.0, 0.1])
        close = np.array([100.0, 101.0, 99.0, 103.0, 100.0])
        ret = compute_signal_weighted_returns(edge, close)
        assert len(ret) == len(close) - 1

    def test_short_position(self):
        """Negative edge_score = short → profit when price drops."""
        edge = np.array([-1.0, -1.0])
        close = np.array([100.0, 90.0])
        ret = compute_signal_weighted_returns(edge, close, cost_bps=0.0)
        # Short position: -1 * (90-100)/100 = -1 * -0.1 = 0.1
        assert ret[0] > 0
