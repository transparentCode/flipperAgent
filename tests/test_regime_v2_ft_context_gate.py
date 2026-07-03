"""Tests for Phase 7K pre-confirmation follow-through context gate."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_context_gate import (
    apply_ft_context_gate,
    build_ft_context_gate_matrix_report,
    build_ft_context_gate_report,
    build_ft_context_gate_retest_report,
    render_ft_context_gate_markdown,
)
from libs.models.regime_v2.scripts.report_ft_context_gate import _parse_args


def _ohlcv(n: int = 12) -> pd.DataFrame:
    idx = pd.RangeIndex(0, n)
    close = [100 + i for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [value + 1 for value in close],
            "low": [value - 1 for value in close],
            "close": close,
            "volume": [10] * n,
        },
        index=idx,
    )


def _analysis(n: int = 12) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append(
            {
                "compression_score": 0.80 if i in {0, 1, 3, 4, 6, 7, 9, 10} else 0.20,
                "pre_breakout_setup_score": 0.75 if i in {0, 1, 3, 4, 6, 7, 9, 10} else 0.10,
                "displacement_breakout_score": 0.65 if i in {1, 4, 7, 10} else 0.10,
                "post_breakout_retest_score": 0.50 if i in {1, 4, 7, 10} else 0.10,
                "policy_breakout_setup_score": 0.70 if i in {0, 1, 3, 4, 6, 7, 9, 10} else 0.10,
                "policy_displacement_breakout_score": 0.60 if i in {1, 4, 7, 10} else 0.10,
                "policy_retest_breakout_score": 0.45 if i in {1, 4, 7, 10} else 0.10,
                "false_breakout_risk": 0.20,
                "shock_risk": 0.10,
            }
        )
    return pd.DataFrame(rows, index=pd.RangeIndex(0, n))


def _context(n: int = 12) -> pd.DataFrame:
    rows = []
    for i in range(n):
        bad = i in {3, 4}
        rows.append(
            {
                "playbook_context_market_phase": "breakout_setup" if not bad else "neutral_context",
                "playbook_context_risk_state": "ok" if not bad else "watch",
                "playbook_context_risk_score": 0.20 if not bad else 0.80,
                "playbook_context_dominant_playbook": "breakout" if not bad else "mean_reversion",
                "playbook_context_horizon_bias": "mid_to_long" if not bad else "short_to_mid",
                "playbook_context_alignment": "aligned" if not bad else "mixed",
                "playbook_context_conflict_tags": "" if not bad else "breakout_shock_conflict;context_not_confirmed",
                "playbook_context_conflict_count": 0 if not bad else 2,
                "playbook_context_is_confirmed": True if not bad else False,
                "playbook_context_score_breakout": 0.45 if not bad else 0.05,
            }
        )
    return pd.DataFrame(rows, index=pd.RangeIndex(0, n))


def _states(n: int = 12) -> pd.DataFrame:
    rows = []
    candidates = {0, 1, 3, 4, 6, 7, 9, 10}
    for i in range(n):
        candidate = i in candidates
        rows.append(
            {
                "playbook_state": "BREAKOUT_SETUP" if candidate else "OBSERVE_ONLY",
                "playbook_state_group": "wait" if candidate else "unknown",
                "playbook_state_reason": "unit",
                "playbook_state_is_executable": False,
                "playbook_state_is_wait": candidate,
                "playbook_state_dominant_playbook": "breakout" if candidate else "none",
                "playbook_state_horizon_bias": "mid_to_long" if candidate else "mid",
            }
        )
    return pd.DataFrame(rows, index=pd.RangeIndex(0, n))


def test_ft_context_gate_blocks_weak_context_candidates():
    gated = apply_ft_context_gate(_analysis(), _context(), _states(), min_context_score=0.55)

    assert bool(gated.loc[0, "ft_context_gate_active"]) is True
    assert gated.loc[0, "ft_context_gate_reason"] == "passed"
    assert bool(gated.loc[3, "ft_context_gate_active"]) is False
    assert gated.loc[3, "playbook_state"] == "OBSERVE_ONLY"
    assert gated.loc[3, "playbook_state_reason"] == "context_gate_blocked"
    assert gated.loc[3, "ft_context_gate_reason"] in {"risk_score_high", "too_many_conflicts", "shock_conflict"}


def test_ft_context_gate_report_and_markdown():
    gated = apply_ft_context_gate(_analysis(), _context(), _states(), min_context_score=0.55)
    report = build_ft_context_gate_report(gated, asset="BNBUSDT", timeframe="1h", threshold=0.25)
    md = render_ft_context_gate_markdown(report)

    assert report["summary"]["candidate_before"] == 8
    assert report["summary"]["candidate_after"] == 6
    assert report["summary"]["blocked_count"] == 2
    assert "# RegimeV2 Phase 7K Follow-Through Context Gate" in md


def test_ft_context_gate_retest_and_matrix_summary():
    one = build_ft_context_gate_retest_report(
        _analysis(),
        _context(),
        _states(),
        _ohlcv(),
        asset="BNBUSDT",
        timeframe="1h",
        threshold=0.25,
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=1,
        min_passing_rate=0.5,
        min_context_score=0.55,
    )
    two = build_ft_context_gate_retest_report(
        _analysis(),
        _context(),
        _states(),
        _ohlcv(),
        threshold=0.30,
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=1,
        min_passing_rate=0.5,
        min_context_score=0.55,
    )
    matrix = build_ft_context_gate_matrix_report([one, two])
    md = render_ft_context_gate_markdown(matrix)

    assert one["summary"]["candidate_before"] == 8
    assert one["summary"]["candidate_after"] == 6
    assert matrix["summary"]["variant_count"] == 2
    assert matrix["summary"]["thresholds"] == [0.25, 0.3]
    assert "# RegimeV2 Phase 7K Follow-Through Context Gate Matrix" in md


def test_ft_context_gate_cli_defaults_and_args():
    args = _parse_args(
        [
            "--asset",
            "ETHUSDT",
            "--timeframe",
            "4h",
            "--limit",
            "100",
            "--threshold",
            "0.25",
            "--split-count",
            "3",
            "--horizon",
            "12",
            "--fee-bps",
            "5",
            "--min-context-score",
            "0.60",
            "--max-risk-score",
            "0.65",
            "--max-conflict-count",
            "0",
            "--block-watch-risk",
            "--require-breakout-playbook",
            "--require-confirmed-context",
        ]
    )
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.limit == 100
    assert args.threshold == [0.25]
    assert args.split_count == 3
    assert args.horizon == [12]
    assert args.fee_bps == [5.0]
    assert args.min_context_score == 0.60
    assert args.max_risk_score == 0.65
    assert args.max_conflict_count == 0
    assert args.block_watch_risk is True
    assert args.require_breakout_playbook is True
    assert args.require_confirmed_context is True

    defaults = _parse_args([])
    assert defaults.asset == "BNBUSDT"
    assert defaults.timeframe == "1h"
    assert defaults.threshold == [0.25, 0.30]
    assert defaults.horizon == [3, 6, 12, 24]
    assert defaults.min_context_score == 0.70
