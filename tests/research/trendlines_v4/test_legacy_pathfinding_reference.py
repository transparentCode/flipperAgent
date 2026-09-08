"""Tests for the frozen, independent legacy pathfinding reproduction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research.trendlines_v4.legacy_pathfinding_reference import (
    Bar,
    analyze_side,
    extract_pivots,
    read_ohlc_window,
    result_to_payload,
)

_ROOT = Path(__file__).parents[3]
_MANIFEST_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/manifest.json"
_BASELINE_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/baseline.json"


def _bar(
    *, open_price: float, high: float, low: float, close: float | None = None
) -> Bar:
    return Bar(
        open=open_price,
        high=high,
        low=low,
        close=open_price if close is None else close,
    )


def _flat_body_bars(
    highs: list[float], lows: list[float], bodies: list[float] | None = None
) -> tuple[Bar, ...]:
    body_values = (
        bodies
        if bodies is not None
        else [(high + low) / 2 for high, low in zip(highs, lows)]
    )
    return tuple(
        _bar(open_price=body, high=high, low=low)
        for high, low, body in zip(highs, lows, body_values)
    )


def _body_cut_resistance_bars() -> tuple[Bar, ...]:
    return (
        _bar(open_price=0.5, high=1.0, low=0.0),
        _bar(open_price=12.0, high=12.0, low=11.0),
        _bar(open_price=0.5, high=1.0, low=0.0),
        _bar(open_price=10.5, high=11.0, low=9.0),
        _bar(open_price=0.5, high=1.0, low=0.0),
        _bar(open_price=8.0, high=8.0, low=7.0),
        _bar(open_price=0.5, high=1.0, low=0.0),
    )


def _body_cut_support_bars() -> tuple[Bar, ...]:
    return (
        _bar(open_price=20.0, high=21.0, low=19.0),
        _bar(open_price=8.0, high=9.0, low=8.0),
        _bar(open_price=20.0, high=21.0, low=19.0),
        _bar(open_price=9.0, high=10.0, low=9.0),
        _bar(open_price=20.0, high=21.0, low=19.0),
        _bar(open_price=12.0, high=13.0, low=12.0),
        _bar(open_price=20.0, high=21.0, low=19.0),
    )


def _tie_resistance_bars() -> tuple[Bar, ...]:
    return (
        _bar(open_price=0.5, high=1.0, low=0.0),
        _bar(open_price=12.0, high=12.0, low=11.0),
        _bar(open_price=0.5, high=1.0, low=0.0),
        _bar(open_price=9.5, high=11.0, low=9.0),
        _bar(open_price=0.5, high=1.0, low=0.0),
        _bar(open_price=8.0, high=8.0, low=7.0),
        _bar(open_price=0.5, high=1.0, low=0.0),
    )


def test_extracts_local_high_with_inclusive_window() -> None:
    bars = _flat_body_bars([1, 2, 3, 2, 1], [0, 0, 0, 0, 0])

    assert extract_pivots(bars, 1, "resistance") == ((2, 3),)


def test_extracts_local_low_with_inclusive_window() -> None:
    bars = _flat_body_bars([4, 4, 4, 4, 4], [3, 2, 1, 2, 3])

    assert extract_pivots(bars, 1, "support") == ((2, 1),)


def test_retains_equal_adjacent_pivots_like_original_indicator() -> None:
    bars = _flat_body_bars([1, 3, 3, 1, 1], [0, 0, 0, 0, 0])

    assert extract_pivots(bars, 1, "resistance") == ((1, 3), (2, 3))


def test_resistance_body_cut_rejects_direct_edge_but_keeps_multisegment_path() -> None:
    result = analyze_side(_body_cut_resistance_bars(), 1, "resistance")

    assert (1, 5) not in result.valid_edges
    assert (1, 3) in result.valid_edges
    assert (3, 5) in result.valid_edges
    assert result.winning_path == ((1, 12.0), (3, 11.0), (5, 8.0))
    assert result.emitted_line is not None
    assert result.emitted_line.start_index == 3
    assert result.emitted_line.end_index == 5


def test_support_body_cut_rejects_direct_edge_but_keeps_multisegment_path() -> None:
    result = analyze_side(_body_cut_support_bars(), 1, "support")

    assert (1, 5) not in result.valid_edges
    assert (1, 3) in result.valid_edges
    assert (3, 5) in result.valid_edges
    assert result.winning_path == ((1, 8.0), (3, 9.0), (5, 12.0))


def test_wick_crossing_is_allowed_when_body_respect_is_preserved() -> None:
    bars = (
        _bar(open_price=0.5, high=1.0, low=0.0),
        _bar(open_price=12.0, high=12.0, low=11.0),
        _bar(open_price=0.5, high=1.0, low=0.0),
        _bar(open_price=9.5, high=11.0, low=9.0),
        _bar(open_price=0.5, high=1.0, low=0.0),
        _bar(open_price=8.0, high=8.0, low=7.0),
        _bar(open_price=0.5, high=1.0, low=0.0),
    )

    result = analyze_side(bars, 1, "resistance")

    assert (1, 5) in result.valid_edges


def test_support_wick_crossing_is_allowed_when_body_respect_is_preserved() -> None:
    bars = (
        _bar(open_price=20.0, high=21.0, low=19.0),
        _bar(open_price=8.0, high=9.0, low=8.0),
        _bar(open_price=20.0, high=21.0, low=19.0),
        _bar(open_price=10.5, high=11.0, low=9.0),
        _bar(open_price=20.0, high=21.0, low=19.0),
        _bar(open_price=12.0, high=13.0, low=12.0),
        _bar(open_price=20.0, high=21.0, low=19.0),
    )

    result = analyze_side(bars, 1, "support")

    assert (1, 5) in result.valid_edges


def test_dp_uses_strict_improvement_and_earliest_predecessor_on_tie() -> None:
    result = analyze_side(_tie_resistance_bars(), 1, "resistance")

    assert result.dp_scores == ((1, 0), (3, 2), (5, 4))
    assert result.dp_predecessors == ((1, -1), (3, 1), (5, 1))


def test_emitted_line_projects_final_bar_from_only_final_two_path_pivots() -> None:
    result = analyze_side(_body_cut_resistance_bars(), 1, "resistance")
    line = result.emitted_line

    assert line is not None
    assert line.start_price == 11.0
    assert line.end_price == 8.0
    assert line.slope == (8.0 - 11.0) / (5 - 3)
    assert line.intercept == 8.0 - line.slope * 5
    assert line.projected_value_at_final_bar == line.slope * 6 + line.intercept


def test_empty_side_has_no_emitted_line() -> None:
    bars = _flat_body_bars([1, 2, 3, 4, 5, 6, 7], [0, 0, 0, 0, 0, 0, 0])

    result = analyze_side(bars, 1, "resistance")

    assert result.pivots == ()
    assert result.valid_edges == ()
    assert result.winning_path == ()
    assert result.emitted_line is None


def test_invalid_inputs_are_rejected_without_adding_model_policy() -> None:
    with pytest.raises(ValueError, match="pivot_window"):
        extract_pivots((), 0, "support")
    with pytest.raises(ValueError, match="unknown side"):
        extract_pivots((), 1, "other")  # type: ignore[arg-type]


def test_frozen_corpus_source_and_window_metadata_are_exact() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text())

    assert manifest["status"] == "frozen_before_oracle_capture"
    assert len(manifest["sources"]) == 3
    assert all(len(source["windows"]) == 2 for source in manifest["sources"])
    for source in manifest["sources"]:
        path = Path(source["path"])
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["sha256"]
        data_rows = raw.splitlines()[1:]
        assert len(data_rows) == source["data_row_count"]
        for window in source["windows"]:
            selected = data_rows[window["start_index"] : window["end_index_exclusive"]]
            assert len(selected) == 200
            assert (
                hashlib.sha256(b"\n".join(selected)).hexdigest()
                == window["ohlc_input_sha256"]
            )


def test_exact_parity_on_all_frozen_corpus_windows() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text())
    baseline = json.loads(_BASELINE_PATH.read_text())
    assert baseline["oracle"] == manifest["oracle"]
    assert len(baseline["windows"]) == 6

    for source in manifest["sources"]:
        for window in source["windows"]:
            key = f"{source['asset']}:{window['window']}"
            bars = read_ohlc_window(
                source["path"], window["start_index"], window["end_index_exclusive"]
            )
            actual = result_to_payload(
                analyze_side_pair(bars, manifest["oracle"]["pivot_window"])
            )
            assert actual == baseline["windows"][key]


def analyze_side_pair(bars: tuple[Bar, ...], pivot_window: int):
    from research.trendlines_v4.legacy_pathfinding_reference import analyze_legacy

    return analyze_legacy(bars, pivot_window)
