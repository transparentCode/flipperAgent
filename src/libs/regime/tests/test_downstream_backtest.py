from __future__ import annotations

import json
import pandas as pd

from libs.regime.optimization.downstream_backtest import (
    _aggregate_candidate_metrics,
    _backtest_edge_series,
    _candidate_decision,
    _is_usable_candidates,
    _panel_decision,
    _slice_candidate_metrics,
    _select_top_edges,
    build_panel_summary,
)


def test_select_top_edges_chooses_highest_absolute_edge():
    edge_df = pd.DataFrame(
        {
            "model_a": [0.2, -0.1, 0.0],
            "model_b": [-0.5, 0.05, 0.0],
            "model_c": [0.1, 0.4, 0.0],
        },
        index=pd.RangeIndex(3),
    )

    selected_edges, selected_models = _select_top_edges(edge_df)

    assert selected_edges.tolist() == [-0.5, 0.4, 0.0]
    assert selected_models.tolist() == ["model_b", "model_c", None]


def test_backtest_edge_series_returns_expected_metrics_shape():
    edges = pd.Series([0.0, 1.0, 1.0, -0.5, 0.0], dtype=float)
    close = [100.0, 101.0, 103.0, 102.0, 104.0]

    metrics = _backtest_edge_series(edges, close, timeframe="1h", cost_bps=0.0)

    assert set(metrics) == {
        "sharpe",
        "cumulative_return",
        "max_drawdown",
        "turnover",
        "trade_count",
        "active_ratio",
    }
    assert metrics["trade_count"] >= 1
    assert 0.0 <= metrics["active_ratio"] <= 1.0


def test_candidate_decision_promotes_only_when_all_primary_metrics_improve():
    baseline = {"sharpe": 1.0, "cumulative_return": 0.10, "max_drawdown": -0.20}

    promote = _candidate_decision(
        "breadth_blend",
        {"sharpe": 1.2, "cumulative_return": 0.15, "max_drawdown": -0.10},
        baseline,
    )
    keep = _candidate_decision(
        "breadth_blend",
        {"sharpe": 1.1, "cumulative_return": 0.08, "max_drawdown": -0.25},
        baseline,
    )
    reject = _candidate_decision(
        "breadth_blend",
        {"sharpe": 0.9, "cumulative_return": 0.05, "max_drawdown": -0.30},
        baseline,
    )

    assert promote == "promote_to_integration_design"
    assert keep == "keep_research_only"
    assert reject == "reject"


def test_panel_decision_requires_majority_slice_improvement():
    baseline = {"median_sharpe": 1.0, "median_cumulative_return": 0.10}

    promote = _panel_decision(
        "breadth_blend",
        {"evaluated_slices": 5, "positive_sharpe_lift_slices": 3, "median_sharpe": 1.2, "median_cumulative_return": 0.11},
        baseline,
    )
    keep = _panel_decision(
        "breadth_blend",
        {"evaluated_slices": 5, "positive_sharpe_lift_slices": 2, "median_sharpe": 1.1, "median_cumulative_return": 0.08},
        baseline,
    )
    reject = _panel_decision(
        "breadth_blend",
        {"evaluated_slices": 5, "positive_sharpe_lift_slices": 1, "median_sharpe": 0.9, "median_cumulative_return": 0.05},
        baseline,
    )

    assert promote == "promote_to_integration_design"
    assert keep == "keep_research_only"
    assert reject == "reject"


def test_aggregate_candidate_metrics_merges_selection_counts():
    rows = [
        {
            "sharpe": 1.0,
            "cumulative_return": 0.1,
            "max_drawdown": -0.2,
            "turnover": 2.0,
            "trade_count": 4,
            "active_ratio": 0.5,
            "model_selection_counts": {"a": 2, "b": 1},
        },
        {
            "sharpe": 2.0,
            "cumulative_return": 0.2,
            "max_drawdown": -0.1,
            "turnover": 3.0,
            "trade_count": 5,
            "active_ratio": 0.6,
            "model_selection_counts": {"a": 1, "c": 4},
        },
    ]

    metrics = _aggregate_candidate_metrics(rows)

    assert metrics["sharpe"] == 1.5
    assert metrics["model_selection_counts"] == {"a": 3, "b": 1, "c": 4}


def test_slice_candidate_metrics_returns_json_safe_payload():
    index = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
    candidate = {
        "selected_edge_series": pd.Series([0.0, 1.0, -0.5, 0.0], index=index, dtype=float),
        "selected_model_series": pd.Series(["a", "b", "b", None], index=index, dtype=object),
        "close_series": pd.Series([100.0, 101.0, 103.0, 102.0], index=index, dtype=float),
        "timeframe": "1h",
        "cost_bps": 0.0,
    }

    metrics = _slice_candidate_metrics(candidate, index[1:])
    encoded = json.dumps(metrics)

    assert "selected_edge_series" not in metrics
    assert "selected_model_series" not in metrics
    assert metrics["model_selection_counts"] == {"b": 2}
    assert isinstance(encoded, str)


def test_build_panel_summary_ignores_inactive_slices():
    active_row = {
        "asset": "BTCUSDT",
        "timeframe": "1h",
        "slice_usable": True,
        "candidates": {
            "no_regime": {
                "walk_forward": {"sharpe": -2.0, "cumulative_return": -0.2, "max_drawdown": -0.3, "turnover": 10.0, "trade_count": 5, "active_ratio": 1.0, "model_selection_counts": {"a": 3}, "decision": "baseline"},
                "full_sample": {"turnover": 20.0, "trade_count": 8},
            },
            "breadth_blend": {
                "walk_forward": {"sharpe": -1.0, "cumulative_return": -0.1, "max_drawdown": -0.2, "turnover": 8.0, "trade_count": 4, "active_ratio": 0.8, "model_selection_counts": {"a": 2}, "decision": "keep_research_only"},
                "full_sample": {"turnover": 15.0, "trade_count": 6},
            },
        },
    }
    inactive_row = {
        "asset": "ETHUSDT",
        "timeframe": "1h",
        "slice_usable": False,
        "candidates": {
            "no_regime": {
                "walk_forward": {"sharpe": 0.0, "cumulative_return": 0.0, "max_drawdown": 0.0, "turnover": 0.0, "trade_count": 0, "active_ratio": 0.0, "model_selection_counts": {}, "decision": "baseline"},
                "full_sample": {"turnover": 0.0, "trade_count": 0},
            },
            "breadth_blend": {
                "walk_forward": {"sharpe": 0.0, "cumulative_return": 0.0, "max_drawdown": 0.0, "turnover": 0.0, "trade_count": 0, "active_ratio": 0.0, "model_selection_counts": {}, "decision": "reject"},
                "full_sample": {"turnover": 0.0, "trade_count": 0},
            },
        },
    }

    summary = build_panel_summary([active_row, inactive_row], candidate_names=("no_regime", "breadth_blend"))

    assert summary["usable_slices"] == 1
    assert summary["total_requested_slices"] == 2
    assert summary["candidate_summary"]["breadth_blend"]["evaluated_slices"] == 1


def test_is_usable_candidates_checks_baseline_activity():
    assert _is_usable_candidates({"no_regime": {"walk_forward": {"trade_count": 1}, "full_sample": {"turnover": 0.0}}})
    assert not _is_usable_candidates({"no_regime": {"walk_forward": {"trade_count": 0, "turnover": 0.0}, "full_sample": {"trade_count": 0, "turnover": 0.0}}})
