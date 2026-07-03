"""Tests for Phase 6X PA paper horizon-slice validation."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_hz import _parse_args
from libs.selection.regime_v2_pa_paper_hz import build_pa_paper_horizon_report, render_pa_paper_horizon_markdown


def _cell(horizon: int, *, status: str, improvement: float, recovered: int, lost: int) -> dict:
    return {
        "horizon_bars": horizon,
        "fee_bps": 2.0,
        "status": status,
        "failure_reasons": [] if status == "pass" else ["lost_avoided_losses"],
        "gate": {"improvement": improvement, "recovered": recovered, "lost_avoided": lost},
    }


def test_horizon_report_marks_long_horizon_candidate_when_only_short_fails():
    source = {
        "phase": "phase_6w_pa_paper_gate_search",
        "variants": [
            {
                "name": "candidate",
                "matrix_ready": False,
                "passing_cell_count": 2,
                "cell_count": 3,
                "avg_improvement": 0.01,
                "total_recovered": 5,
                "total_lost_avoided": 1,
                "cells": [
                    _cell(3, status="fail", improvement=0.001, recovered=1, lost=1),
                    _cell(12, status="pass", improvement=0.01, recovered=2, lost=0),
                    _cell(24, status="pass", improvement=0.02, recovered=2, lost=0),
                ],
            }
        ],
    }

    report = build_pa_paper_horizon_report(source, long_horizons=(12, 24), short_horizons=(3,))

    assert report["summary"]["long_horizon_candidate"] is True
    assert report["summary"]["recommendation"] == "long_horizon_paper_candidate"
    variant = report["variants"][0]
    assert variant["long"]["passing_cell_count"] == 2
    assert variant["short"]["failed_cell_count"] == 1
    assert variant["mid"]["failed_cell_count"] == 0


def test_horizon_report_blocks_when_mid_horizon_fails():
    source = {
        "phase": "phase_6w_pa_paper_gate_search",
        "variants": [
            {
                "name": "candidate",
                "cells": [
                    _cell(3, status="fail", improvement=0.001, recovered=1, lost=1),
                    _cell(6, status="fail", improvement=0.001, recovered=1, lost=1),
                    _cell(12, status="pass", improvement=0.01, recovered=2, lost=0),
                    _cell(24, status="pass", improvement=0.02, recovered=2, lost=0),
                ],
            }
        ],
    }

    report = build_pa_paper_horizon_report(source, long_horizons=(12, 24), short_horizons=(3,))

    assert report["summary"]["long_horizon_candidate"] is False
    assert report["summary"]["recommendation"] == "hold_off_no_horizon_candidate"
    assert report["variants"][0]["mid"]["failed_cell_count"] == 1


def test_horizon_markdown_and_cli_defaults():
    source = {"phase": "x", "variants": [{"name": "v", "cells": [_cell(12, status="pass", improvement=0.01, recovered=1, lost=0)]}]}
    report = build_pa_paper_horizon_report(source)
    md = render_pa_paper_horizon_markdown(report)
    assert "# RegimeV2 Phase 6X PA Paper Horizon Slice" in md
    assert "Long-horizon candidate" in md

    args = _parse_args(
        [
            "--gate-search",
            "gs.json",
            "--long-horizon",
            "12",
            "--long-horizon",
            "24",
            "--short-horizon",
            "3",
            "--allow-partial-long",
            "--allow-mid-failures",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )
    assert args.gate_search == "gs.json"
    assert args.long_horizon == [12, 24]
    assert args.short_horizon == [3]
    assert args.allow_partial_long is True
    assert args.allow_mid_failures is True

    defaults = _parse_args([])
    assert defaults.long_horizon == [12, 24]
    assert defaults.short_horizon == [3]
