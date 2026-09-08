"""Focused tests for the bounded G4 emission-filter experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research.trendlines_v4.legacy_pathfinding_reference import (
    Bar,
    EmittedLine,
    LegacyPathfindingResult,
    SidePathResult,
    analyze_side,
    read_ohlc_window,
)
from research.trendlines_v4.post_anchor_filter_impact import (
    audit_corpus,
    filter_legacy_result,
)

_ROOT = Path(__file__).parents[3]
_MANIFEST_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/manifest.json"
_BASELINE_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/baseline.json"
_G2_MODULE_PATH = _ROOT / "research/trendlines_v4/causal_semantics_audit.py"
_G2_REPORT_PATH = _ROOT / "artifacts/trendlines_v4/g2_causal_audit_v1/report.json"
_G3_MODULE_PATH = _ROOT / "research/trendlines_v4/post_anchor_validity_audit.py"
_G3_REPORT_PATH = (
    _ROOT / "artifacts/trendlines_v4/g3_post_anchor_validity_audit_v1/report.json"
)
_G1_MODULE_PATH = _ROOT / "research/trendlines_v4/legacy_pathfinding_reference.py"
_G4_REPORT_PATH = (
    _ROOT / "artifacts/trendlines_v4/g4_post_anchor_filter_impact_v1/report.json"
)
_ORACLE_PATH = Path(
    "/Users/kajukatli/projects/KineticAlphaBot/app/indicators/path_finding_trendline.py"
)
_G1_SHA256 = "29fcee61805265c75f4d436085511bb9764885faf582ee8bed789445ea5dfcca"
_G2_SHA256 = "168dfbc56202698465c0fe852a70ecc555caff6672dbc73da77d533e6518e90a"
_G3_SHA256 = "def469a83b2c8aed608404ac366ab37cf72fb0d22554491fdabe20fb3fa9d169"
_MANIFEST_SHA256 = "77992577e0bb40fa6bd6773630989632a1fa7e896c43bde48853f6af7e1a6b91"
_BASELINE_SHA256 = "e164ba3867ed9666d90744529f400686fd56374dd1ec51c94fe4ec79c266a9ca"
_G2_REPORT_SHA256 = "9dedb3a4abcb10e002b29176beff4265de5c926bb0f64fdad451d92e67d7bee2"
_G3_REPORT_SHA256 = "4da943314936f6a962c315ba911d88bec7499e0df756090c43aba1ab7a905fba"
_ORACLE_SHA256 = "758482545e43a2dbe1a0e239856ae1af02f7a4266e4b968641c56cf614eb4dd1"


def _line(*, end_index: int = 1) -> EmittedLine:
    return EmittedLine(
        start_index=0,
        end_index=end_index,
        start_price=10.0,
        end_price=10.0,
        slope=0.0,
        intercept=10.0,
        projected_value_at_final_bar=10.0,
    )


def _manual_result(side: str, line: EmittedLine | None) -> SidePathResult:
    return SidePathResult(
        side=side,
        pivots=(),
        valid_edges=(),
        dp_scores=(),
        dp_predecessors=(),
        winning_path=(),
        emitted_line=line,
    )


def _bars(body: float, high: float = 11.0, low: float = 9.0) -> tuple[Bar, ...]:
    return (
        Bar(open=10.0, high=11.0, low=9.0, close=10.0),
        Bar(open=10.0, high=11.0, low=9.0, close=10.0),
        Bar(open=body, high=high, low=low, close=body),
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


def test_valid_baseline_line_is_retained_exactly() -> None:
    baseline = _manual_result("resistance", _line())
    result = filter_legacy_result(
        _bars(body=9.0), LegacyPathfindingResult(baseline, baseline)
    )

    assert result.resistance.filtered_line == baseline.emitted_line
    assert result.resistance.post_anchor_crossings == ()
    assert not result.resistance.suppressed


def test_broken_baseline_line_is_suppressed_without_path_reselection() -> None:
    bars = (
        Bar(open=0.5, high=1.0, low=0.0, close=0.5),
        Bar(open=12.0, high=12.0, low=11.0, close=12.0),
        Bar(open=0.5, high=1.0, low=0.0, close=0.5),
        Bar(open=10.5, high=11.0, low=9.0, close=10.5),
        Bar(open=0.5, high=1.0, low=0.0, close=0.5),
        Bar(open=8.0, high=8.0, low=7.0, close=8.0),
        Bar(open=10.0, high=11.0, low=9.0, close=10.0),
    )
    baseline = analyze_side(bars, 1, "resistance")
    result = filter_legacy_result(bars, LegacyPathfindingResult(baseline, baseline))

    assert result.resistance.suppressed
    assert result.resistance.filtered_line is None
    assert result.resistance.post_anchor_crossings
    assert result.resistance.baseline.pivots == baseline.pivots
    assert result.resistance.baseline.valid_edges == baseline.valid_edges
    assert result.resistance.baseline.dp_scores == baseline.dp_scores
    assert result.resistance.baseline.dp_predecessors == baseline.dp_predecessors
    assert result.resistance.baseline.winning_path == baseline.winning_path


def test_wick_only_and_equality_do_not_suppress() -> None:
    support_wick_only = filter_legacy_result(
        _bars(body=11.0, high=20.0, low=0.0),
        LegacyPathfindingResult(
            _manual_result("support", _line()), _manual_result("resistance", _line())
        ),
    )
    resistance_wick_only = filter_legacy_result(
        _bars(body=9.0, high=20.0, low=0.0),
        LegacyPathfindingResult(
            _manual_result("support", _line()), _manual_result("resistance", _line())
        ),
    )
    equal = filter_legacy_result(
        _bars(body=10.0, high=20.0, low=0.0),
        LegacyPathfindingResult(
            _manual_result("support", _line()), _manual_result("resistance", _line())
        ),
    )

    assert not support_wick_only.support.suppressed
    assert not resistance_wick_only.resistance.suppressed
    assert not equal.support.suppressed
    assert not equal.resistance.suppressed


def test_no_baseline_line_remains_none() -> None:
    empty = _manual_result("support", None)
    result = filter_legacy_result(
        _bars(body=10.0), LegacyPathfindingResult(empty, empty)
    )

    assert result.support.filtered_line is None
    assert result.resistance.filtered_line is None
    assert not result.support.suppressed


def test_frozen_corpus_filter_audit_is_deterministic_and_preserves_all_facts() -> None:
    windows = _frozen_windows()
    first = audit_corpus(windows)
    second = audit_corpus(windows)

    assert first == second
    assert first["windows_audited"] == 6
    assert first["prefixes_audited"] == 1200
    assert first["total_baseline_lines"] == 2132
    assert first["total_retained_lines"] + first["total_suppressed_lines"] == 2132
    assert first["retained_line_with_crossing_count"] == 0
    assert first["suppressed_line_without_crossing_count"] == 0
    assert len(first["final_cutoffs"]) == 12


def test_report_matches_recomputed_filter_audit() -> None:
    report = json.loads(_G4_REPORT_PATH.read_text())
    recomputed = audit_corpus(_frozen_windows())
    for key, value in recomputed.items():
        assert report[key] == value
    assert report["schema_version"] == "g4_post_anchor_filter_impact_v1"
    assert report["conclusion"] == "MINIMAL_POST_ANCHOR_FILTER_IMPACT_MEASURED"
    assert report["report_id"] == _report_id(report)
    assert len(_G4_REPORT_PATH.read_bytes()) < 20_000


def test_protected_g0_through_g3_and_oracle_hashes_remain_exact() -> None:
    expected = (
        (_G1_MODULE_PATH, _G1_SHA256),
        (_G2_MODULE_PATH, _G2_SHA256),
        (_G3_MODULE_PATH, _G3_SHA256),
        (_MANIFEST_PATH, _MANIFEST_SHA256),
        (_BASELINE_PATH, _BASELINE_SHA256),
        (_G2_REPORT_PATH, _G2_REPORT_SHA256),
        (_G3_REPORT_PATH, _G3_REPORT_SHA256),
        (_ORACLE_PATH, _ORACLE_SHA256),
    )
    for file_path, digest in expected:
        assert hashlib.sha256(file_path.read_bytes()).hexdigest() == digest
