"""Focused tests for G5 current-valid legacy-score re-selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import research.trendlines_v4.current_valid_legacy_score_reselection as g5
from research.trendlines_v4.current_valid_legacy_score_reselection import (
    audit_corpus,
    reselect_side_result,
)
from research.trendlines_v4.legacy_pathfinding_reference import (
    Bar,
    EmittedLine,
    SidePathResult,
    analyze_legacy,
    read_ohlc_window,
)
from research.trendlines_v4.post_anchor_validity_audit import (
    post_anchor_body_crossings,
)

_ROOT = Path(__file__).parents[3]
_MANIFEST_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/manifest.json"
_BASELINE_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/baseline.json"
_G1_MODULE_PATH = _ROOT / "research/trendlines_v4/legacy_pathfinding_reference.py"
_G2_MODULE_PATH = _ROOT / "research/trendlines_v4/causal_semantics_audit.py"
_G3_MODULE_PATH = _ROOT / "research/trendlines_v4/post_anchor_validity_audit.py"
_G4_MODULE_PATH = _ROOT / "research/trendlines_v4/post_anchor_filter_impact.py"
_G2_REPORT_PATH = _ROOT / "artifacts/trendlines_v4/g2_causal_audit_v1/report.json"
_G3_REPORT_PATH = (
    _ROOT / "artifacts/trendlines_v4/g3_post_anchor_validity_audit_v1/report.json"
)
_G4_REPORT_PATH = (
    _ROOT / "artifacts/trendlines_v4/g4_post_anchor_filter_impact_v1/report.json"
)
_G5_REPORT_PATH = (
    _ROOT
    / "artifacts/trendlines_v4/g5_current_valid_legacy_score_reselection_v1/report.json"
)
_ORACLE_PATH = Path(
    "/Users/kajukatli/projects/KineticAlphaBot/app/indicators/path_finding_trendline.py"
)
_PROTECTED = (
    (
        _G1_MODULE_PATH,
        "29fcee61805265c75f4d436085511bb9764885faf582ee8bed789445ea5dfcca",
    ),
    (
        _G2_MODULE_PATH,
        "168dfbc56202698465c0fe852a70ecc555caff6672dbc73da77d533e6518e90a",
    ),
    (
        _G3_MODULE_PATH,
        "def469a83b2c8aed608404ac366ab37cf72fb0d22554491fdabe20fb3fa9d169",
    ),
    (
        _G4_MODULE_PATH,
        "b11942199426e74051378ee774963a0962acca9aab801f1a488b5464ea4cac33",
    ),
    (
        _MANIFEST_PATH,
        "77992577e0bb40fa6bd6773630989632a1fa7e896c43bde48853f6af7e1a6b91",
    ),
    (
        _BASELINE_PATH,
        "e164ba3867ed9666d90744529f400686fd56374dd1ec51c94fe4ec79c266a9ca",
    ),
    (
        _G2_REPORT_PATH,
        "9dedb3a4abcb10e002b29176beff4265de5c926bb0f64fdad451d92e67d7bee2",
    ),
    (
        _G3_REPORT_PATH,
        "4da943314936f6a962c315ba911d88bec7499e0df756090c43aba1ab7a905fba",
    ),
    (
        _G4_REPORT_PATH,
        "26cf4d9b9ea0b359a18bcad1b7a1b0f187c21d0279d694bd53204b810e35b0fe",
    ),
    (_ORACLE_PATH, "758482545e43a2dbe1a0e239856ae1af02f7a4266e4b968641c56cf614eb4dd1"),
)


def _line(
    start_index: int,
    end_index: int,
    start_price: float,
    end_price: float,
    final_bar_index: int,
) -> EmittedLine:
    slope = (end_price - start_price) / (end_index - start_index)
    intercept = end_price - slope * end_index
    return EmittedLine(
        start_index=start_index,
        end_index=end_index,
        start_price=start_price,
        end_price=end_price,
        slope=slope,
        intercept=intercept,
        projected_value_at_final_bar=slope * final_bar_index + intercept,
    )


def _manual_side(
    *,
    equal_scores: bool = False,
    global_score: int = 4,
    alternate_score: int = 3,
) -> SidePathResult:
    pivots = (
        (1, 10.0),
        (2, 5.0),
        (3, 10.0),
        (4, 8.0),
        (5, 4.0),
        (7, 7.0),
    )
    global_path = (4, 8.0), (7, 7.0)
    scores = (
        (1, 0),
        (2, 0),
        (3, 0),
        (4, 0),
        (5, alternate_score),
        (7, 3 if equal_scores else global_score),
    )
    predecessors = ((1, -1), (2, -1), (3, -1), (4, -1), (5, 2), (7, 4))
    return SidePathResult(
        side="support",
        pivots=pivots,
        valid_edges=((2, 5), (4, 7)),
        dp_scores=scores,
        dp_predecessors=tuple(predecessors),
        winning_path=global_path,
        emitted_line=_line(4, 7, 8.0, 7.0, 8),
    )


def _bars(final_body: float) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            open=final_body if index == 8 else 20.0,
            high=final_body if index == 8 else 20.0,
            low=final_body if index == 8 else 20.0,
            close=final_body if index == 8 else 20.0,
        )
        for index in range(9)
    )


def _frozen_windows() -> list[tuple[str, tuple[Bar, ...]]]:
    manifest = json.loads(_MANIFEST_PATH.read_text())
    windows: list[tuple[str, tuple[Bar, ...]]] = []
    for source in manifest["sources"]:
        for window in source["windows"]:
            windows.append(
                (
                    f"{source['asset']}:{window['window']}",
                    read_ohlc_window(
                        source["path"],
                        window["start_index"],
                        window["end_index_exclusive"],
                    ),
                )
            )
    return windows


def _report_id(payload: dict[str, object]) -> str:
    body = {key: value for key, value in payload.items() if key != "report_id"}
    return hashlib.sha256(
        json.dumps(
            body, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def test_predecessor_chain_reconstruction_uses_stored_dp_state() -> None:
    result = reselect_side_result(_bars(7.0), _manual_side())

    assert [item.endpoint_index for item in result.endpoint_paths] == [5, 7]
    assert result.endpoint_paths[0].path == ((2, 5.0), (5, 4.0))
    assert result.endpoint_paths[1].path == ((4, 8.0), (7, 7.0))
    assert result.baseline.winning_path == ((4, 8.0), (7, 7.0))
    assert result.baseline.valid_edges == ((2, 5), (4, 7))


def test_broken_global_winner_recovers_lower_scored_valid_endpoint() -> None:
    result = reselect_side_result(_bars(6.0), _manual_side())

    assert result.g4_line is None
    assert result.recovered_by_g5
    assert result.selected_endpoint_index == 5
    assert result.selected_dp_score == 3
    assert result.selected_line == _line(2, 5, 5.0, 4.0, 8)


def test_highest_valid_legacy_score_wins() -> None:
    result = reselect_side_result(_bars(20.0), _manual_side())

    assert result.g4_line == result.baseline.emitted_line
    assert result.selected_endpoint_index == 7
    assert result.selected_dp_score == 4
    assert result.selected_line == result.baseline.emitted_line
    assert not result.recovered_by_g5


def test_equal_valid_scores_preserve_original_endpoint_order() -> None:
    result = reselect_side_result(
        _bars(20.0), _manual_side(equal_scores=True, global_score=3)
    )

    assert result.selected_endpoint_index == 5
    assert result.selected_dp_score == 3


def test_no_current_valid_endpoint_emits_no_line() -> None:
    result = reselect_side_result(_bars(0.0), _manual_side())

    assert result.g4_line is None
    assert result.selected_endpoint_index is None
    assert result.selected_dp_score is None
    assert result.selected_line is None
    assert not result.recovered_by_g5


def test_selected_line_passes_exact_post_anchor_body_rule() -> None:
    result = reselect_side_result(_bars(6.0), _manual_side())

    assert result.selected_line is not None
    assert post_anchor_body_crossings(_bars(6.0), result.selected_line, "support") == ()
    assert result.endpoint_paths[1].post_anchor_crossings


def test_reselection_keeps_all_g1_facts_unchanged() -> None:
    bars = _bars(7.0)
    baseline = analyze_legacy(bars, pivot_window=1)
    result = reselect_side_result(bars, baseline.resistance)

    assert result.baseline is baseline.resistance
    assert result.baseline.pivots == baseline.resistance.pivots
    assert result.baseline.valid_edges == baseline.resistance.valid_edges
    assert result.baseline.dp_scores == baseline.resistance.dp_scores
    assert result.baseline.dp_predecessors == baseline.resistance.dp_predecessors
    assert result.baseline.winning_path == baseline.resistance.winning_path
    assert result.baseline.emitted_line == baseline.resistance.emitted_line


def test_frozen_corpus_report_recomputes_exactly() -> None:
    report = json.loads(_G5_REPORT_PATH.read_text())
    recomputed = audit_corpus(_frozen_windows())

    for key, value in recomputed.items():
        assert report[key] == value
    assert report["schema_version"] == "g5_current_valid_legacy_score_reselection_v1"
    assert report["conclusion"] == "CURRENT_VALID_LEGACY_SCORE_RESELECTION_MEASURED"
    assert report["report_id"] == _report_id(report)
    assert report["invariants"] == {
        "g1_pivot_inventory_mismatch": 0,
        "g1_valid_edge_inventory_mismatch": 0,
        "g1_dp_score_inventory_mismatch": 0,
        "g1_predecessor_inventory_mismatch": 0,
        "g5_selected_endpoint_absent_from_g1_inventory": 0,
        "g5_selected_line_with_adverse_post_anchor_body_crossing": 0,
        "g5_retained_geometry_altered_from_endpoint_path": 0,
    }


def test_corpus_invariants_are_measured_from_execution(monkeypatch) -> None:
    original = g5.reselect_side_result
    calls = 0

    def tamper_first_side(bars, side_result):
        nonlocal calls
        result = original(bars, side_result)
        if calls == 0:
            result = result._replace(
                baseline=replace(
                    result.baseline,
                    pivots=result.baseline.pivots + ((999, 0.0),),
                    valid_edges=result.baseline.valid_edges + ((999, 1000),),
                    dp_scores=result.baseline.dp_scores + ((999, 1),),
                    dp_predecessors=result.baseline.dp_predecessors + ((999, -1),),
                )
            )
        calls += 1
        return result

    monkeypatch.setattr(g5, "reselect_side_result", tamper_first_side)
    report = g5.audit_corpus([("synthetic", _bars(7.0))], pivot_window=1)

    assert report["invariants"]["g1_pivot_inventory_mismatch"] == 1
    assert report["invariants"]["g1_valid_edge_inventory_mismatch"] == 1
    assert report["invariants"]["g1_dp_score_inventory_mismatch"] == 1
    assert report["invariants"]["g1_predecessor_inventory_mismatch"] == 1


def _audit_with_endpoint_tamper(monkeypatch, transform):
    original = g5.reselect_side_result
    used = False

    def wrapped(bars, side_result):
        nonlocal used
        result = original(bars, side_result)
        if not used:
            tampered = transform(result)
            if tampered is not None:
                used = True
                return tampered
        return result

    monkeypatch.setattr(g5, "reselect_side_result", wrapped)
    return g5.audit_corpus([("synthetic", _bars(6.0))], pivot_window=1)


def test_g5_endpoint_inventory_invariant_is_measured(monkeypatch) -> None:
    def tamper(result):
        if result.selected_endpoint_index is None:
            return None
        paths = tuple(
            endpoint._replace(endpoint_index=999)
            if endpoint.endpoint_index == result.selected_endpoint_index
            else endpoint
            for endpoint in result.endpoint_paths
        )
        return result._replace(
            endpoint_paths=paths,
            selected_endpoint_index=999,
        )

    report = _audit_with_endpoint_tamper(monkeypatch, tamper)

    assert report["invariants"]["g5_selected_endpoint_absent_from_g1_inventory"] == 1


def test_g5_crossing_invariant_is_measured(monkeypatch) -> None:
    def tamper(result):
        crossing = [
            endpoint
            for endpoint in result.endpoint_paths
            if endpoint.post_anchor_crossings
        ]
        if not crossing:
            return None
        endpoint = max(crossing, key=lambda item: item.dp_score)
        paths = tuple(
            item._replace(post_anchor_crossings=())
            if item.endpoint_index == endpoint.endpoint_index
            else item
            for item in result.endpoint_paths
        )
        return result._replace(
            endpoint_paths=paths,
            selected_endpoint_index=endpoint.endpoint_index,
            selected_dp_score=endpoint.dp_score,
            selected_line=endpoint.line,
        )

    report = _audit_with_endpoint_tamper(monkeypatch, tamper)

    assert (
        report["invariants"]["g5_selected_line_with_adverse_post_anchor_body_crossing"]
        == 1
    )


def test_g5_geometry_invariant_is_measured_from_endpoint_path(monkeypatch) -> None:
    def tamper(result):
        if result.selected_endpoint_index is None:
            return None
        endpoint = next(
            item
            for item in result.endpoint_paths
            if item.endpoint_index == result.selected_endpoint_index
        )
        forged_line = replace(
            endpoint.line,
            projected_value_at_final_bar=endpoint.line.projected_value_at_final_bar
            + 1.0,
        )
        paths = tuple(
            item._replace(line=forged_line)
            if item.endpoint_index == endpoint.endpoint_index
            else item
            for item in result.endpoint_paths
        )
        return result._replace(endpoint_paths=paths, selected_line=forged_line)

    report = _audit_with_endpoint_tamper(monkeypatch, tamper)

    assert report["invariants"]["g5_retained_geometry_altered_from_endpoint_path"] == 1


def test_protected_g0_through_g4_and_oracle_hashes_remain_exact() -> None:
    for file_path, digest in _PROTECTED:
        assert hashlib.sha256(file_path.read_bytes()).hexdigest() == digest
