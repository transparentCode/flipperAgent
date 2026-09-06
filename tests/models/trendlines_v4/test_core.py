"""Contract, isolation, and frozen-parity tests for the V4 production core."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from libs.models.trendlines_v4 import (
    SideGeometry,
    TrendlineBar,
    TrendlineSnapshot,
    analyze_trendlines,
    core,
)
from research.trendlines_v4.current_valid_legacy_score_reselection import (
    reselect_side_result,
)
from research.trendlines_v4.frozen_utility_benchmark import (
    _read_source,
)
from research.trendlines_v4.legacy_pathfinding_reference import analyze_legacy
from research.trendlines_v4.post_anchor_validity_audit import (
    post_anchor_body_crossings,
)

ROOT = Path(__file__).resolve().parents[3]
G0_MANIFEST = ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/manifest.json"
G6_MANIFEST = (
    ROOT / "artifacts/trendlines_v4/g6_frozen_utility_benchmark_v1/manifest.json"
)
G7_CASES = (
    ROOT / "artifacts/trendlines_v4/g7_blinded_recovery_geometry_review_v1/cases.json"
)
G7_MAPPING = (
    ROOT
    / "artifacts/trendlines_v4/g7_blinded_recovery_geometry_review_v1/hidden_mapping.json"
)

LOCKS = {
    ROOT
    / "research/trendlines_v4/legacy_pathfinding_reference.py": "29fcee61805265c75f4d436085511bb9764885faf582ee8bed789445ea5dfcca",
    ROOT
    / "research/trendlines_v4/current_valid_legacy_score_reselection.py": "32abc73bd20f3f6c3ca27352d674c34e9a74a51bab2defb3c66a76ce56ffe4c6",
    ROOT
    / "research/trendlines_v4/post_anchor_validity_audit.py": "def469a83b2c8aed608404ac366ab37cf72fb0d22554491fdabe20fb3fa9d169",
    ROOT
    / "research/trendlines_v4/post_anchor_filter_impact.py": "b11942199426e74051378ee774963a0962acca9aab801f1a488b5464ea4cac33",
    ROOT
    / "research/trendlines_v4/frozen_utility_benchmark.py": "11968e43ef5d8e40558f4b18e57a42bc51e4230a313f5916c8ab3b5092964949",
    ROOT
    / "tests/research/trendlines_v4/test_frozen_utility_benchmark.py": "90c4c9833f21387926ad90a6ab13125ba435fd396e507ddb0de7e171b4499789",
    ROOT
    / "artifacts/trendlines_v4/g0_legacy_corpus_v1/manifest.json": "77992577e0bb40fa6bd6773630989632a1fa7e896c43bde48853f6af7e1a6b91",
    ROOT
    / "artifacts/trendlines_v4/g0_legacy_corpus_v1/baseline.json": "e164ba3867ed9666d90744529f400686fd56374dd1ec51c94fe4ec79c266a9ca",
    ROOT
    / "artifacts/trendlines_v4/g6_frozen_utility_benchmark_v1/manifest.json": "318f3e5b533ce45227452a12a3a84f9ae5bf03a90261371ed97c6ae0ef0bcd6b",
    ROOT
    / "artifacts/trendlines_v4/g6_frozen_utility_benchmark_v1/report.json": "5aae0e57d2d9adbeb4294c9a57e6567fdc121f3f4c7b4d49870bcb12c29ea825",
    ROOT
    / "research/trendlines_v4/causal_semantics_audit.py": "168dfbc56202698465c0fe852a70ecc555caff6672dbc73da77d533e6518e90a",
    ROOT
    / "artifacts/trendlines_v4/g2_causal_audit_v1/report.json": "9dedb3a4abcb10e002b29176beff4265de5c926bb0f64fdad451d92e67d7bee2",
    ROOT
    / "artifacts/trendlines_v4/g3_post_anchor_validity_audit_v1/report.json": "4da943314936f6a962c315ba911d88bec7499e0df756090c43aba1ab7a905fba",
    ROOT
    / "artifacts/trendlines_v4/g4_post_anchor_filter_impact_v1/report.json": "26cf4d9b9ea0b359a18bcad1b7a1b0f187c21d0279d694bd53204b810e35b0fe",
    Path(
        "/Users/kajukatli/projects/KineticAlphaBot/app/indicators/path_finding_trendline.py"
    ): "758482545e43a2dbe1a0e239856ae1af02f7a4266e4b968641c56cf614eb4dd1",
}


def _utc_close(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _production_bars(source_bars) -> tuple[TrendlineBar, ...]:
    return tuple(
        TrendlineBar(
            closed_at=_utc_close(bar.close_time),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in source_bars
    )


def _frozen_windows(manifest_path: Path):
    manifest = json.loads(manifest_path.read_text())
    for source in manifest["sources"]:
        bars, raw_rows = _read_source(source["path"])
        assert len(bars) == source["data_row_count"]
        assert (
            hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()
            == source["sha256"]
        )
        for window in source["windows"]:
            start, end = window["start_index"], window["end_index_exclusive"]
            assert (
                hashlib.sha256(b"\n".join(raw_rows[start:end])).hexdigest()
                == window["ohlc_input_sha256"]
            )
            yield source["asset"], window["window"], tuple(bars[start:end])


def _assert_role(actual, expected, source_bars) -> None:
    if expected is None:
        assert actual is None
        return
    assert actual is not None
    assert actual.start_anchor_price == expected.start_price
    assert actual.end_anchor_price == expected.end_price
    assert actual.slope_per_bar == expected.slope
    assert (
        actual.projected_price_at_market_as_of == expected.projected_value_at_final_bar
    )
    assert actual.start_anchor_at == _utc_close(
        source_bars[expected.start_index].close_time
    )
    assert actual.end_anchor_at == _utc_close(
        source_bars[expected.end_index].close_time
    )
    assert actual.projection_positive is (expected.projected_value_at_final_bar > 0)


def _assert_crossing_metadata(actual, expected, source_bars) -> None:
    if expected is None:
        return
    crossings = post_anchor_body_crossings(source_bars, expected, actual.side)
    assert actual.post_anchor_body_cross_count == len(crossings)
    assert actual.post_anchor_body_crossed is bool(crossings)
    if actual is not None:
        assert actual.post_anchor_body_cross_count >= 0


def _flat_bars(count: int = 13, *, price: float = 10.0) -> tuple[TrendlineBar, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    return tuple(
        TrendlineBar(start + timedelta(hours=index), price, price + 2, price - 2, price)
        for index in range(count)
    )


def _bar(
    index: int,
    *,
    open_: float = 10,
    high: float = 12,
    low: float = 8,
    close: float = 10,
) -> TrendlineBar:
    return TrendlineBar(
        datetime(2025, 2, 1, tzinfo=UTC) + timedelta(hours=index),
        open_,
        high,
        low,
        close,
    )


def test_frozen_inputs_and_dependency_free_source() -> None:
    observed = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in LOCKS}
    assert observed == LOCKS
    source_paths = sorted((ROOT / "src/libs/models/trendlines_v4").glob("*.py"))
    assert source_paths
    forbidden_roots = {
        "research",
        "numpy",
        "pandas",
        "scipy",
        "sklearn",
        "optuna",
        "pydantic",
    }
    for source_path in source_paths:
        tree = ast.parse(source_path.read_text())
        imported_roots = {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 0
        }
        imported_roots |= {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert imported_roots.isdisjoint(forbidden_roots)
    assert "G1" not in core.__all__ and "G5" not in core.__all__
    substantive = sum(
        bool(line.strip()) and not line.lstrip().startswith("#")
        for line in (ROOT / "src/libs/models/trendlines_v4/core.py")
        .read_text()
        .splitlines()
    )
    assert substantive <= 400


def test_runtime_package_import_isolation() -> None:
    script = """
import json
import sys

import libs.models.trendlines_v4
import libs.models.trendlines_v4.core

forbidden = (
    "libs.models.trendlines",
    "research",
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "optuna",
    "pydantic",
    "apps.decision_app",
)
loaded = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
)
if loaded:
    raise SystemExit(json.dumps(loaded))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_full_frozen_g0_prefix_parity() -> None:
    prefixes = sides = structural_crossings = current_invalid = 0
    for _, _, source_bars in _frozen_windows(G0_MANIFEST):
        for prefix_length in range(1, len(source_bars) + 1):
            raw_prefix = source_bars[:prefix_length]
            production = analyze_trendlines(_production_bars(raw_prefix))
            oracle = analyze_legacy(raw_prefix)
            prefixes += 1
            for side_name in ("support", "resistance"):
                side_result = getattr(oracle, side_name)
                current = reselect_side_result(raw_prefix, side_result)
                actual_side = getattr(production, side_name)
                _assert_role(
                    actual_side.structural, side_result.emitted_line, raw_prefix
                )
                _assert_role(
                    actual_side.current_valid, current.selected_line, raw_prefix
                )
                _assert_crossing_metadata(
                    actual_side.structural, side_result.emitted_line, raw_prefix
                )
                if actual_side.current_valid is not None:
                    assert actual_side.current_valid.post_anchor_body_cross_count == 0
                sides += 1
                structural_crossings += 1
                current_invalid += int(current.selected_line is None)
    assert prefixes == 6 * 200
    assert sides == 6 * 200 * 2
    assert structural_crossings == sides
    assert current_invalid >= 0


def test_full_frozen_g6_prefix_parity() -> None:
    prefixes = sides = structural_crossings = current_invalid = 0
    for _, _, source_bars in _frozen_windows(G6_MANIFEST):
        for prefix_length in range(1, len(source_bars) + 1):
            raw_prefix = source_bars[:prefix_length]
            production = analyze_trendlines(_production_bars(raw_prefix))
            oracle = analyze_legacy(raw_prefix)
            prefixes += 1
            for side_name in ("support", "resistance"):
                side_result = getattr(oracle, side_name)
                current = reselect_side_result(raw_prefix, side_result)
                actual_side = getattr(production, side_name)
                _assert_role(
                    actual_side.structural, side_result.emitted_line, raw_prefix
                )
                _assert_role(
                    actual_side.current_valid, current.selected_line, raw_prefix
                )
                _assert_crossing_metadata(
                    actual_side.structural, side_result.emitted_line, raw_prefix
                )
                assert actual_side.same_geometry is (
                    actual_side.structural is not None
                    and actual_side.structural == actual_side.current_valid
                )
                if actual_side.current_valid is not None:
                    assert actual_side.current_valid.post_anchor_body_cross_count == 0
                sides += 1
                structural_crossings += 1
                current_invalid += int(current.selected_line is None)
    assert prefixes == 15 * 300
    assert sides == 15 * 300 * 2
    assert structural_crossings == sides
    assert current_invalid >= 0


def test_g7_selected_case_parity_and_hidden_map_integrity() -> None:
    cases = json.loads(G7_CASES.read_text())
    mapping = json.loads(G7_MAPPING.read_text())
    assert cases["case_count"] == 8
    assert mapping["case_count"] == 8
    by_case = {item["case_id"]: item for item in mapping["mappings"]}
    comparisons = 0
    for case in cases["cases"]:
        asset, number = case["window"].split(":")
        source_bars = next(
            bars
            for item_asset, item_number, bars in _frozen_windows(G6_MANIFEST)
            if item_asset == asset and str(item_number) == number
        )
        raw_prefix = source_bars[: case["cutoff"] + 1]
        production = analyze_trendlines(_production_bars(raw_prefix))
        oracle = analyze_legacy(raw_prefix)
        assert case["case_id"] in by_case
        for side_name in ("support", "resistance"):
            expected = getattr(oracle, side_name)
            current = reselect_side_result(raw_prefix, expected)
            actual = getattr(production, side_name)
            _assert_role(actual.structural, expected.emitted_line, raw_prefix)
            _assert_role(actual.current_valid, current.selected_line, raw_prefix)
            comparisons += 2
    assert comparisons == 8 * 2 * 2


def test_latest_300_bar_trimming_is_exact() -> None:
    history = _flat_bars(320)
    assert analyze_trendlines(history) == analyze_trendlines(history[-300:])
    trimmed = analyze_trendlines(history)
    assert trimmed.history_bar_count == 300
    assert trimmed.history_start_at == history[20].closed_at
    assert trimmed.market_as_of == history[-1].closed_at


def test_segment_body_rules_and_crossing_metadata() -> None:
    bars = list(_flat_bars(9))
    bars[4] = _bar(4, open_=10, high=12, low=1, close=11)
    assert core._segment_is_valid(bars, 0, 8, 8, 8, "support")
    assert core._segment_is_valid(bars, 0, 12, 8, 12, "resistance")
    equality_bars = list(_flat_bars(9))
    equality_bars[4] = _bar(4, open_=8, high=12, low=8, close=9)
    assert core._segment_is_valid(equality_bars, 0, 8, 8, 8, "support")
    assert core._segment_is_valid(equality_bars, 0, 12, 8, 12, "resistance")
    support_bad = list(_flat_bars(9))
    support_bad[4] = _bar(4, open_=9, high=12, low=8, close=10)
    assert not core._segment_is_valid(support_bad, 0, 10, 8, 10, "support")
    resistance_bad = list(_flat_bars(9))
    resistance_bad[4] = _bar(4, open_=10, high=12, low=8, close=11)
    assert not core._segment_is_valid(resistance_bad, 0, 10, 8, 10, "resistance")
    line = core._Line(1, 3, 10, 12, 1, 9, 18)
    crossing_bars = list(_flat_bars(8))
    crossing_bars[4] = _bar(4, open_=9, high=12, low=8, close=9)
    geometry = core._geometry(crossing_bars, "support", line)
    assert geometry is not None
    assert geometry.post_anchor_body_crossed
    assert geometry.post_anchor_body_cross_count == 4


def test_current_valid_selection_keeps_original_scores_and_ties(monkeypatch) -> None:
    bars = _flat_bars(16)
    pivots = ((3, 10.0), (5, 9.0), (7, 8.0), (10, 9.0), (12, 11.0))
    valid_pairs = {(3, 7), (3, 10), (5, 12)}
    monkeypatch.setattr(core, "_pivots", lambda _bars, _side: pivots)
    monkeypatch.setattr(
        core,
        "_segment_is_valid",
        lambda _bars, previous, _previous_price, current, _current_price, _side: (
            (previous, current) in valid_pairs
        ),
    )
    monkeypatch.setattr(
        core,
        "_crossing_count",
        lambda _bars, line, _side: 1 if line.end_index == 10 else 0,
    )
    state = core._solve_side(bars, "support")
    assert state.structural is not None and state.structural.end_index == 10
    assert state.current_valid is not None and state.current_valid.end_index == 12
    monkeypatch.setattr(core, "_crossing_count", lambda *_args: 0)
    tied = core._solve_side(bars, "support")
    assert tied.current_valid is not None and tied.current_valid.end_index == 10


def test_no_valid_endpoint_preserves_structural_line(monkeypatch) -> None:
    bars = _flat_bars(12)
    pivots = ((3, 10.0), (7, 8.0))
    monkeypatch.setattr(core, "_pivots", lambda _bars, _side: pivots)
    monkeypatch.setattr(core, "_segment_is_valid", lambda *_args: True)
    monkeypatch.setattr(core, "_crossing_count", lambda *_args: 1)
    state = core._solve_side(bars, "support")
    assert state.structural is not None
    assert state.current_valid is None


def test_nonpositive_projection_is_metadata_not_selection() -> None:
    bars = list(_flat_bars(price=20))
    bars[3] = TrendlineBar(bars[3].closed_at, 11, 12, 10, 12)
    bars[7] = TrendlineBar(bars[7].closed_at, 3, 4, 2, 4)
    result = analyze_trendlines(bars)
    assert result.support.structural is not None
    assert result.support.current_valid is not None
    assert result.support.structural.projection_positive is False
    assert result.support.current_valid.projection_positive is False


def test_public_contract_validation_and_empty_history() -> None:
    bars = _flat_bars(1)
    with pytest.raises(ValueError):
        analyze_trendlines(())
    with pytest.raises(TypeError):
        TrendlineBar(datetime.now(UTC), True, 2, 1, 1)
    with pytest.raises(ValueError):
        TrendlineBar(datetime.now(UTC), 1, 2, 0, 1)
    with pytest.raises(ValueError):
        TrendlineBar(datetime.now(UTC), 1, 2, 1, 3)
    with pytest.raises(ValueError):
        analyze_trendlines((bars[0], TrendlineBar(bars[0].closed_at, 10, 12, 8, 10)))
    with pytest.raises(ValueError):
        TrendlineSnapshot(
            "wrong",
            1,
            300,
            3,
            bars[0].closed_at,
            bars[0].closed_at,
            SideGeometry(None, None, False),
            SideGeometry(None, None, False),
        )
    assert {
        "TrendlineBar",
        "TrendlineGeometry",
        "SideGeometry",
        "TrendlineSnapshot",
        "analyze_trendlines",
    } <= set(core.__all__)
