"""Focused tests for the evidence-only V4 G2 causal audit."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

from research.trendlines_v4.causal_semantics_audit import (
    audit_window,
    pivot_available_at_prefix,
    pivot_confirmation_index,
    unconfirmed_path_pivots,
)
from research.trendlines_v4.legacy_pathfinding_reference import (
    Bar,
    analyze_legacy,
    read_ohlc_window,
)

_ROOT = Path(__file__).parents[3]
_MANIFEST_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/manifest.json"
_BASELINE_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/baseline.json"
_G2_REPORT_PATH = _ROOT / "artifacts/trendlines_v4/g2_causal_audit_v1/report.json"
_G1_PATH = _ROOT / "research/trendlines_v4/legacy_pathfinding_reference.py"
_ORACLE_PATH = Path(
    "/Users/kajukatli/projects/KineticAlphaBot/app/indicators/path_finding_trendline.py"
)
_G1_SHA256 = "29fcee61805265c75f4d436085511bb9764885faf582ee8bed789445ea5dfcca"
_MANIFEST_SHA256 = "77992577e0bb40fa6bd6773630989632a1fa7e896c43bde48853f6af7e1a6b91"
_BASELINE_SHA256 = "e164ba3867ed9666d90744529f400686fd56374dd1ec51c94fe4ec79c266a9ca"
_ORACLE_SHA256 = "758482545e43a2dbe1a0e239856ae1af02f7a4266e4b968641c56cf614eb4dd1"
_PIVOT_WINDOW = 3
_SPOT_CHECK_PREFIXES = (25, 50, 100, 150, 200)


def _synthetic_bars() -> tuple[Bar, ...]:
    highs = (2.0, 5.0, 2.0, 4.0, 1.0, 3.0, 1.0, 2.0, 1.0, 2.0)
    lows = (0.0, -2.0, 0.0, -1.0, 0.0, -1.0, 0.0, -1.0, 0.0, -1.0)
    return tuple(
        Bar(open=(high + low) / 2, high=high, low=low, close=(high + low) / 2)
        for high, low in zip(highs, lows)
    )


def _frozen_windows() -> list[tuple[str, tuple[Bar, ...]]]:
    manifest = json.loads(_MANIFEST_PATH.read_text())
    windows: list[tuple[str, tuple[Bar, ...]]] = []
    for source in manifest["sources"]:
        for window in source["windows"]:
            key = f"{source['asset']}:{window['window']}"
            bars = read_ohlc_window(
                source["path"],
                window["start_index"],
                window["end_index_exclusive"],
            )
            windows.append((key, bars))
    return windows


def _load_original_oracle() -> type:
    module_name = "_trendlines_v4_g2_original_pathfinding"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing.PathfindingTrendline

    spec = importlib.util.spec_from_file_location(module_name, _ORACLE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load original oracle: {_ORACLE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.PathfindingTrendline


def _invoke_original(
    oracle: object, method_name: str, dataframe: pd.DataFrame
) -> tuple[tuple[int, ...], tuple[tuple[int, float], ...]]:
    state: dict[str, tuple[int, ...]] = {}
    oracle_filename = str(_ORACLE_PATH)
    previous_trace = sys.gettrace()

    def trace(frame, event, arg):  # type: ignore[no-untyped-def]
        if (
            event == "return"
            and frame.f_code.co_filename == oracle_filename
            and frame.f_code.co_name == method_name
        ):
            state["pivots"] = tuple(int(index) for index in frame.f_locals["pivots"])
        return trace

    sys.settrace(trace)
    try:
        raw_path = getattr(oracle, method_name)(dataframe)
    finally:
        sys.settrace(previous_trace)

    path = tuple((int(index), float(price)) for index, price in raw_path)
    return state.get("pivots", ()), path


def _dataframe(bars: tuple[Bar, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [bar.open for bar in bars],
            "high": [bar.high for bar in bars],
            "low": [bar.low for bar in bars],
            "close": [bar.close for bar in bars],
        }
    )


def _assert_original_side_parity(
    actual_side, oracle, method_name: str, bars: tuple[Bar, ...]
) -> None:
    pivot_indices, original_path = _invoke_original(
        oracle, method_name, _dataframe(bars)
    )
    actual_pivot_indices = tuple(index for index, _ in actual_side.pivots)
    assert actual_pivot_indices == pivot_indices
    assert actual_side.winning_path == original_path

    original_line = oracle.get_projected_line(list(original_path), len(bars) - 1)
    actual_line = actual_side.emitted_line
    if original_line is None:
        assert actual_line is None
        return

    assert actual_line is not None
    assert len(original_path) >= 2
    previous_index, previous_price = original_path[-2]
    last_index, last_price = original_path[-1]
    assert actual_line.start_index == previous_index
    assert actual_line.end_index == last_index
    assert actual_line.start_price == previous_price
    assert actual_line.end_price == last_price
    assert actual_line.slope == float(original_line["slope"])
    assert actual_line.intercept == float(original_line["intercept"])
    assert actual_line.projected_value_at_final_bar == float(
        original_line["current_price_projection"]
    )


def _report_id(payload: dict[str, object]) -> str:
    body = {key: value for key, value in payload.items() if key != "report_id"}
    encoded = json.dumps(
        body, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_pivot_availability_uses_strict_prefix_boundary() -> None:
    assert pivot_confirmation_index(4, 3) == 7
    assert not pivot_available_at_prefix(4, 7, 3)
    assert pivot_available_at_prefix(4, 8, 3)


def test_unconfirmed_winning_path_reference_is_detectable_without_repair() -> None:
    assert unconfirmed_path_pivots(((1, 10.0), (5, 8.0)), 8, 3) == ((5, 8),)


def test_fixed_confirmation_truth_is_not_rewritten_by_later_bars() -> None:
    base = _synthetic_bars()
    later = base + (
        Bar(open=50.0, high=100.0, low=-100.0, close=50.0),
        Bar(open=60.0, high=110.0, low=-110.0, close=60.0),
    )

    base_summary = audit_window(base, 1)
    later_summary = audit_window(later, 1)
    assert base_summary.post_confirmation_truth_revisions == 0
    assert later_summary.post_confirmation_truth_revisions == 0


def test_all_six_frozen_windows_complete_prefix_audit() -> None:
    windows = _frozen_windows()
    assert len(windows) == 6
    for key, bars in windows:
        summary = audit_window(bars, _PIVOT_WINDOW)
        assert summary.prefixes_audited == 200, key
        assert summary.total_emitted_paths > 0, key
        assert summary.path_pivot_references >= summary.total_emitted_paths, key
        assert summary.unconfirmed_path_pivot_violations == 0, key
        assert summary.confirmed_pivots_audited > 0, key
        assert summary.post_confirmation_truth_revisions == 0, key


def test_original_oracle_matches_g1_at_all_sixty_spot_checks() -> None:
    oracle_class = _load_original_oracle()
    checks = 0
    for _, full_bars in _frozen_windows():
        for prefix_length in _SPOT_CHECK_PREFIXES:
            bars = full_bars[:prefix_length]
            actual = analyze_legacy(bars, _PIVOT_WINDOW)
            oracle = oracle_class(_PIVOT_WINDOW)
            _assert_original_side_parity(
                actual.support, oracle, "find_support_path", bars
            )
            checks += 1
            _assert_original_side_parity(
                actual.resistance, oracle, "find_resistance_path", bars
            )
            checks += 1
    assert checks == 60


def test_report_is_compact_aggregate_evidence_only() -> None:
    report = json.loads(_G2_REPORT_PATH.read_text())
    assert report["schema_version"] == "g2_causal_audit_v1"
    assert report["manifest_sha256"] == _MANIFEST_SHA256
    assert report["g1_implementation_sha256"] == _G1_SHA256
    assert report["oracle_sha256"] == _ORACLE_SHA256
    assert report["pivot_window"] == _PIVOT_WINDOW
    assert report["windows_audited"] == 6
    assert report["prefixes_audited"] == 1200
    assert report["unconfirmed_path_pivot_violations"] == 0
    assert report["post_confirmation_truth_revisions"] == 0
    assert report["oracle_spot_checks"] == {"checks": 60, "mismatches": 0}
    assert report["conclusion"] == "NO_DECISION_TIME_CAUSAL_VIOLATION_FOUND"
    assert report["report_id"] == _report_id(report)
    assert len(_G2_REPORT_PATH.read_bytes()) < 20_000
    forbidden = {"bars", "ohlc", "per_prefix", "prefix_tape", "raw_ohlc"}
    assert forbidden.isdisjoint(report)
    assert len(report["window_summaries"]) == 6


def test_frozen_g0_g1_and_original_oracle_hashes_are_exact() -> None:
    assert hashlib.sha256(_G1_PATH.read_bytes()).hexdigest() == _G1_SHA256
    assert hashlib.sha256(_MANIFEST_PATH.read_bytes()).hexdigest() == _MANIFEST_SHA256
    assert hashlib.sha256(_BASELINE_PATH.read_bytes()).hexdigest() == _BASELINE_SHA256
    assert hashlib.sha256(_ORACLE_PATH.read_bytes()).hexdigest() == _ORACLE_SHA256
