"""Tests for Phase 7G follow-through robustness matrix."""

from __future__ import annotations

from libs.models.regime_v2.evaluation.playbook_ft_matrix import build_ft_matrix_report, render_ft_matrix_markdown
from libs.models.regime_v2.scripts.report_ft_matrix import _parse_args, _pairs


def _variant(asset: str = "BNBUSDT", timeframe: str = "1h", threshold: float = 0.25, active: int = 12, passing: int = 8, worst: float = -0.0005, avg: float = 0.001) -> dict:
    cells = []
    for idx in range(12):
        is_pass = idx < passing
        cells.append(
            {
                "horizon_bars": [3, 6, 12, 24][idx % 4],
                "fee_bps": [2.0, 5.0, 10.0][idx % 3],
                "labeled_count": active,
                "avg_directional_net_return": avg if is_pass else worst,
                "directional_positive_rate": 0.60 if is_pass else 0.40,
            }
        )
    return {
        "asset": asset,
        "timeframe": timeframe,
        "threshold": threshold,
        "followthrough_report": {
            "summary": {
                "asset": asset,
                "timeframe": timeframe,
                "active_count": active,
                "eligible_count": 100,
                "direction_distribution": {"up": active // 2, "down": active - active // 2},
            }
        },
        "outcome_matrix": {
            "summary": {
                "best_cell": {"horizon_bars": 3, "fee_bps": 2.0},
                "worst_cell": {"horizon_bars": 24, "fee_bps": 10.0},
            },
            "cells": cells,
        },
    }


def test_ft_matrix_marks_ready_variant_when_support_and_cells_pass():
    report = build_ft_matrix_report([_variant()], min_support=10, min_passing_rate=0.60, max_cell_loss=0.001)

    assert report["summary"]["variant_count"] == 1
    assert report["summary"]["ready_variant_count"] == 1
    assert report["summary"]["recommendation"] == "candidate_found"
    assert report["variants"][0]["ready"] is True
    assert report["variants"][0]["passing_cells"] == 8


def test_ft_matrix_blocks_low_support_bad_worst_and_single_direction():
    bad = _variant(active=4, passing=4, worst=-0.005, avg=0.0005)
    bad["followthrough_report"]["summary"]["direction_distribution"] = {"up": 4}

    report = build_ft_matrix_report([bad], min_support=10, min_passing_rate=0.60, max_cell_loss=0.001)

    variant = report["variants"][0]
    assert variant["ready"] is False
    assert "low_support" in variant["reasons"]
    assert "worst_cell_too_negative" in variant["reasons"]
    assert "single_direction" in variant["reasons"]
    assert report["summary"]["recommendation"] == "hold_off_collect_more_or_refine"


def test_ft_matrix_markdown_and_cli_args():
    report = build_ft_matrix_report([_variant(asset="ETHUSDT", timeframe="4h", threshold=0.3)])
    md = render_ft_matrix_markdown(report)
    assert "# RegimeV2 Phase 7G Follow-Through Matrix" in md
    assert "ETHUSDT|4h" in md

    args = _parse_args(
        [
            "--pair",
            "BTCUSDT|4h",
            "--limit",
            "100",
            "--threshold",
            "0.2",
            "--threshold",
            "0.3",
            "--horizon",
            "12",
            "--fee-bps",
            "5",
            "--min-support",
            "5",
            "--min-passing-rate",
            "0.5",
        ]
    )
    assert _pairs(args) == [("BTCUSDT", "4h")]
    assert args.threshold == [0.2, 0.3]
    assert args.horizon == [12]
    assert args.fee_bps == [5.0]
    assert args.min_support == 5
    assert args.min_passing_rate == 0.5

    defaults = _parse_args([])
    assert len(_pairs(defaults)) == 4
    assert defaults.threshold == [0.2, 0.25, 0.3, 0.35]
    assert defaults.horizon == [3, 6, 12, 24]
