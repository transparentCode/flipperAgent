"""Focused tests for the evidence-only V4 G3 post-anchor audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research.trendlines_v4.legacy_pathfinding_reference import (
    Bar,
    EmittedLine,
    read_ohlc_window,
)
from research.trendlines_v4.post_anchor_validity_audit import (
    audit_window,
    post_anchor_body_crossings,
)

_ROOT = Path(__file__).parents[3]
_MANIFEST_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/manifest.json"
_BASELINE_PATH = _ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/baseline.json"
_G2_MODULE_PATH = _ROOT / "research/trendlines_v4/causal_semantics_audit.py"
_G2_REPORT_PATH = _ROOT / "artifacts/trendlines_v4/g2_causal_audit_v1/report.json"
_G3_REPORT_PATH = (
    _ROOT / "artifacts/trendlines_v4/g3_post_anchor_validity_audit_v1/report.json"
)
_G1_MODULE_PATH = _ROOT / "research/trendlines_v4/legacy_pathfinding_reference.py"
_ORACLE_PATH = Path(
    "/Users/kajukatli/projects/KineticAlphaBot/app/indicators/path_finding_trendline.py"
)
_G1_SHA256 = "29fcee61805265c75f4d436085511bb9764885faf582ee8bed789445ea5dfcca"
_G2_SHA256 = "168dfbc56202698465c0fe852a70ecc555caff6672dbc73da77d533e6518e90a"
_MANIFEST_SHA256 = "77992577e0bb40fa6bd6773630989632a1fa7e896c43bde48853f6af7e1a6b91"
_BASELINE_SHA256 = "e164ba3867ed9666d90744529f400686fd56374dd1ec51c94fe4ec79c266a9ca"
_G2_REPORT_SHA256 = "9dedb3a4abcb10e002b29176beff4265de5c926bb0f64fdad451d92e67d7bee2"
_ORACLE_SHA256 = "758482545e43a2dbe1a0e239856ae1af02f7a4266e4b968641c56cf614eb4dd1"


def _flat_line(*, end_index: int = 1) -> EmittedLine:
    return EmittedLine(
        start_index=0,
        end_index=end_index,
        start_price=10.0,
        end_price=10.0,
        slope=0.0,
        intercept=10.0,
        projected_value_at_final_bar=10.0,
    )


def _bars_after_anchor(open_price: float, high: float, low: float) -> tuple[Bar, ...]:
    return (
        Bar(open=10.0, high=11.0, low=9.0, close=10.0),
        Bar(open=10.0, high=11.0, low=9.0, close=10.0),
        Bar(open=open_price, high=high, low=low, close=open_price),
    )


def _frozen_windows() -> list[tuple[str, tuple[Bar, ...]]]:
    manifest = json.loads(_MANIFEST_PATH.read_text())
    windows: list[tuple[str, tuple[Bar, ...]]] = []
    for source in manifest["sources"]:
        for window in source["windows"]:
            key = f"{source['asset']}:{window['window']}"
            windows.append(
                (
                    key,
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
    encoded = json.dumps(
        body, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _recomputed_report_evidence() -> tuple[
    dict[str, dict[str, object]], dict[str, int]
]:
    window_summaries = {
        key: audit_window(bars).to_payload() for key, bars in _frozen_windows()
    }
    aggregate_fields = (
        "prefixes_audited",
        "support_emitted_lines",
        "resistance_emitted_lines",
        "emitted_lines_with_post_anchor_exposure",
        "post_anchor_bars_inspected",
        "emitted_lines_with_body_crossing",
        "support_lines_body_broken_at_cutoff",
        "resistance_lines_body_broken_at_cutoff",
        "total_body_crossings",
    )
    aggregate = {
        field: sum(summary[field] for summary in window_summaries.values())
        for field in aggregate_fields
    }
    return window_summaries, aggregate


def test_support_body_crossing_after_final_anchor_is_detected() -> None:
    crossings = post_anchor_body_crossings(
        _bars_after_anchor(open_price=8.0, high=12.0, low=7.0),
        _flat_line(),
        "support",
    )

    assert crossings == ((2, 10.0, 8.0),)


def test_resistance_body_crossing_after_final_anchor_is_detected() -> None:
    crossings = post_anchor_body_crossings(
        _bars_after_anchor(open_price=12.0, high=13.0, low=11.0),
        _flat_line(),
        "resistance",
    )

    assert crossings == ((2, 10.0, 12.0),)


def test_wick_only_crossings_are_ignored() -> None:
    support_bars = _bars_after_anchor(open_price=11.0, high=20.0, low=0.0)
    resistance_bars = _bars_after_anchor(open_price=9.0, high=20.0, low=0.0)

    assert post_anchor_body_crossings(support_bars, _flat_line(), "support") == ()
    assert post_anchor_body_crossings(resistance_bars, _flat_line(), "resistance") == ()


def test_body_equality_with_projected_line_is_not_a_violation() -> None:
    bars = _bars_after_anchor(open_price=10.0, high=20.0, low=0.0)

    assert post_anchor_body_crossings(bars, _flat_line(), "support") == ()
    assert post_anchor_body_crossings(bars, _flat_line(), "resistance") == ()


def test_no_post_anchor_bars_produces_no_crossing() -> None:
    bars = (
        Bar(open=10.0, high=11.0, low=9.0, close=10.0),
        Bar(open=10.0, high=11.0, low=9.0, close=10.0),
    )

    assert post_anchor_body_crossings(bars, _flat_line(end_index=1), "support") == ()


def test_invalid_side_and_anchor_are_rejected() -> None:
    bars = _bars_after_anchor(open_price=10.0, high=11.0, low=9.0)
    with pytest.raises(ValueError, match="unknown side"):
        post_anchor_body_crossings(bars, _flat_line(), "other")

    invalid_line = EmittedLine(
        start_index=0,
        end_index=3,
        start_price=10.0,
        end_price=10.0,
        slope=0.0,
        intercept=10.0,
        projected_value_at_final_bar=10.0,
    )
    with pytest.raises(ValueError, match="end_index"):
        post_anchor_body_crossings(bars, invalid_line, "support")


def test_all_six_frozen_windows_are_audited_without_filtering_emitted_lines() -> None:
    windows = _frozen_windows()
    assert len(windows) == 6
    for key, bars in windows:
        first = audit_window(bars)
        second = audit_window(bars)
        assert first == second, key
        assert first.prefixes_audited == 200, key
        assert first.total_emitted_lines > 0, key
        assert first.emitted_lines_with_post_anchor_exposure > 0, key
        assert first.post_anchor_bars_inspected > 0, key
        assert first.total_emitted_lines >= first.emitted_lines_with_body_crossing, key


def test_report_is_compact_and_matches_deterministic_audit() -> None:
    report = json.loads(_G3_REPORT_PATH.read_text())
    recomputed_windows, recomputed_aggregate = _recomputed_report_evidence()
    assert report["schema_version"] == "g3_post_anchor_validity_audit_v1"
    assert report["g1_implementation_sha256"] == _G1_SHA256
    assert report["g2_audit_sha256"] == _G2_SHA256
    assert report["g2_report_sha256"] == _G2_REPORT_SHA256
    assert report["manifest_sha256"] == _MANIFEST_SHA256
    assert report["windows_audited"] == 6
    assert report["prefixes_audited"] == 1200
    assert report["report_id"] == _report_id(report)
    assert report["window_summaries"] == recomputed_windows
    for field, value in recomputed_aggregate.items():
        assert report[field] == value
    assert report["first_violation"] == next(
        (
            summary["first_violation"]
            for summary in recomputed_windows.values()
            if summary["first_violation"] is not None
        ),
        None,
    )
    assert report["conclusion"] in {
        "NO_POST_ANCHOR_VALIDITY_DEFECT_FOUND",
        "POST_ANCHOR_VALIDITY_DEFECT_FOUND",
        "INCONCLUSIVE",
    }
    assert len(_G3_REPORT_PATH.read_bytes()) < 20_000
    assert len(report["window_summaries"]) == 6
    assert "per_prefix" not in report
    assert "bars" not in report
    assert "ohlc" not in report


def test_frozen_g0_g1_g2_and_oracle_hashes_remain_exact() -> None:
    assert hashlib.sha256(_G1_MODULE_PATH.read_bytes()).hexdigest() == _G1_SHA256
    assert hashlib.sha256(_G2_MODULE_PATH.read_bytes()).hexdigest() == _G2_SHA256
    assert hashlib.sha256(_MANIFEST_PATH.read_bytes()).hexdigest() == _MANIFEST_SHA256
    assert hashlib.sha256(_BASELINE_PATH.read_bytes()).hexdigest() == _BASELINE_SHA256
    assert hashlib.sha256(_G2_REPORT_PATH.read_bytes()).hexdigest() == _G2_REPORT_SHA256
    assert hashlib.sha256(_ORACLE_PATH.read_bytes()).hexdigest() == _ORACLE_SHA256
