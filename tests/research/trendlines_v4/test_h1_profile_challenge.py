"""Focused contract tests for the outcome-blind V4 H1A challenge."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from libs.models.trendlines_v4 import core
from research.trendlines_v4 import exact_geometry_identity_persistence as n1
from research.trendlines_v4 import h1_profile_challenge as h1
from research.trendlines_v4 import parameter_sensitivity as h0

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _bars(count: int = 120) -> tuple[n1.SourceBar, ...]:
    return tuple(
        n1.SourceBar(
            open_at=BASE + timedelta(hours=index),
            closed_at=BASE
            + timedelta(hours=index, minutes=59, seconds=59, milliseconds=999),
            open=100.0 + index * 0.01,
            high=101.0 + index * 0.01,
            low=99.0 + index * 0.01,
            close=100.5 + index * 0.01,
        )
        for index in range(count)
    )


def _cutoff(source_position: int = 119) -> h0.H0Cutoff:
    return h0.H0Cutoff(
        asset="BTCUSDT",
        timeframe="1h",
        window="holdout",
        cutoff=0,
        source_position=source_position,
        market_as_of=n1._timestamp(
            BASE
            + timedelta(
                hours=source_position,
                minutes=59,
                seconds=59,
                milliseconds=999,
            )
        ),
        partition="holdout",
    )


def _fact(geometry_id: str, side: str = "support") -> h0.H0LineFact:
    return h0.H0LineFact(
        side=side,  # type: ignore[arg-type]
        role="structural",
        geometry_id=geometry_id,
        start_anchor_at="2025-01-01T00:59:59.999000Z",
        end_anchor_at="2025-01-01T05:59:59.999000Z",
        start_anchor_price=100.0,
        end_anchor_price=100.5,
        projected_price=101.0,
        projected_price_hex=(101.0).hex(),
        slope_per_bar=0.1,
        projection_positive=True,
        absolute_close_distance_bps=1.0,
        body_clearance_bps=2.0,
        anchor_span_bars=5,
        start_anchor_age_bars=114,
        end_anchor_age_bars=109,
        start_anchor_headroom_bars=1,
        left_pivot_eligibility_margin_bars=1,
        slope_bps_per_bar=10.0,
        post_anchor_bar_count=113,
        post_anchor_adverse_body_bar_count=0,
        post_anchor_adverse_body_bar_rate=0.0,
        bars_since_last_adverse_body_bar=None,
        current_body_adverse_side="respecting",
        projection_non_positive=False,
    )


def _snapshot(cutoff: h0.H0Cutoff, support_fact: h0.H0LineFact) -> h0.H0Snapshot:
    lines = tuple(
        (
            side,
            role,
            support_fact if side == "support" and role == "structural" else None,
        )
        for side in n1.SIDES
        for role in n1.ROLES
    )
    return h0.H0Snapshot(cutoff, lines)


def test_policy_set_and_profile_resolution_are_exact() -> None:
    assert tuple(policy.policy_id for policy in h1.POLICIES) == (
        "C0",
        "C1",
        "C2",
        "C3",
        "C4",
    )
    assert h1.POLICIES[0].profile("1h").is_baseline is True
    assert h1.POLICIES[1].profile("1h").pivot_window == 2
    assert h1.POLICIES[2].profile("4h").pivot_window == 5
    assert h1.POLICIES[3].profile("1h").effective_history_bars == 600
    assert h1.POLICIES[4].profile("1h").effective_history_bars == 672
    assert h1.POLICIES[4].profile("4h").effective_history_bars == 168


def test_membership_hashes_and_confirmation_seal_are_frozen() -> None:
    membership = h1.build_membership(h0.build_streams())
    assert membership["selection"]["cutoff_count"] == 768
    assert membership["selection"]["membership_hash"] == h1.SELECTION_MEMBERSHIP_HASH
    assert membership["confirmation"]["cutoff_count"] == 768
    assert (
        membership["confirmation"]["membership_hash"] == h1.CONFIRMATION_MEMBERSHIP_HASH
    )
    assert membership["selection"]["results_published"] is True
    assert membership["confirmation"]["results_published"] is False


def test_selection_cutoffs_exclude_sealed_confirmation_membership() -> None:
    streams = h0.build_streams()
    membership = h1.build_membership(streams)
    cutoffs = h1._selection_cutoffs(streams, membership)
    assert len(cutoffs) == 768
    assert all(cutoff.partition == "holdout" for cutoff in cutoffs)
    selection_positions = {
        (cutoff.asset, cutoff.timeframe, cutoff.source_position)
        for stream in streams
        for cutoff in stream.holdout[:96]
    }
    confirmation_positions = {
        (stream.asset, stream.timeframe, stream.holdout[96].source_position)
        for stream in streams
    }
    assert {(c.asset, c.timeframe, c.source_position) for c in cutoffs} == (
        selection_positions
    )
    assert not (
        {(c.asset, c.timeframe, c.source_position) for c in cutoffs}
        & confirmation_positions
    )


def test_selection_history_rejects_confirmation_cutoff() -> None:
    stream = h0.build_streams()[0]
    selection = stream.holdout[:96]
    positions = h1._selection_position_keys(selection)
    confirmation = stream.holdout[96]
    with pytest.raises(h1.H1ContractError):
        h1._selection_history(
            stream,
            confirmation,
            h1.POLICIES[0].profile(stream.timeframe).effective_history_bars,
            positions,
        )


def test_semantic_rerun_equality_is_exact_and_resource_independent() -> None:
    first = h1._SemanticMatrix({}, h1.EXPECTED_SEMANTIC_EVALUATIONS, {}, {"x": 1})
    second = h1._SemanticMatrix(
        {}, h1.EXPECTED_SEMANTIC_EVALUATIONS, {"wall_seconds": 99}, {"x": 1}
    )
    h1._assert_semantic_rerun_equal(first, second)
    second.semantic_payload["x"] = 2
    with pytest.raises(h1.H1NumericalSemanticsBlocked):
        h1._assert_semantic_rerun_equal(first, second)


def test_profile_constants_restore_after_analysis_exception(monkeypatch) -> None:
    profile = h1.POLICIES[1].profile("1h")

    def fail(_history):
        raise RuntimeError("synthetic analysis failure")

    monkeypatch.setattr(core, "analyze_trendlines", fail)
    with pytest.raises(RuntimeError, match="synthetic analysis failure"):
        h0.analyze_profile(profile, ())
    assert (core.PIVOT_WINDOW, core.HISTORY_CAPACITY_BARS) == (3, 300)


def test_blind_line_contains_geometry_but_no_selection_metadata() -> None:
    payload = h1._blind_line(_fact("geometry"))
    assert set(payload) == {
        "start_anchor_at",
        "end_anchor_at",
        "start_anchor_price",
        "end_anchor_price",
        "slope_per_bar",
        "projected_price",
    }
    assert "body_clearance_bps" not in payload
    assert "post_anchor_adverse_body_bar_count" not in payload


def test_eligible_case_uses_same_causal_context_for_both_lines() -> None:
    cutoff = _cutoff()
    stream = h0.H0Stream(
        asset="BTCUSDT",
        timeframe="1h",
        bars=_bars(),
        development=(),
        holdout=(cutoff,),
    )
    baseline = _snapshot(cutoff, _fact("baseline"))
    challenger = _snapshot(cutoff, _fact("challenger"))
    baseline_run = h1._PolicyRun(
        h1.POLICIES[0], {}, {cutoff.key(): baseline}, (), {}, ""
    )
    challenger_run = h1._PolicyRun(
        h1.POLICIES[1], {}, {cutoff.key(): challenger}, (), {}, ""
    )
    cases = h1._eligible_cases(
        "C1",
        baseline_run,
        challenger_run,
        (stream,),
        (cutoff,),
    )
    assert len(cases) == 1
    assert cases[0]["source_position"] == cutoff.source_position
    assert len(cases[0]["bars"]) == 120
    assert cases[0]["baseline_line"]["projected_price"] == 101.0
    assert cases[0]["challenger_line"]["projected_price"] == 101.0


def test_choose_case_is_deterministic_and_prefers_unseen_dimensions() -> None:
    candidates = (
        {
            "asset": "BTCUSDT",
            "role": "structural",
            "scope_hash": "b",
            "timeframe": "1h",
            "side": "support",
        },
        {
            "asset": "ETHUSDT",
            "role": "current_valid",
            "scope_hash": "a",
            "timeframe": "1h",
            "side": "support",
        },
    )
    chosen = h1._choose_case(candidates, "1h", "support", {"BTCUSDT"}, {"structural"})
    assert chosen["asset"] == "ETHUSDT"


def test_original_scope_inventory_is_excluded_from_replacement() -> None:
    scopes = h1._original_scope_hashes()
    assert len(scopes) == 16
    assert h1.SELECTION_MEMBERSHIP_HASH == (
        "16c0dc0aec55c745c63323e68009f99ed509d7140c72b7097533eca53ccb4968"
    )


def test_replacement_candidate_context_contains_all_four_anchor_positions() -> None:
    cutoff = _cutoff()
    stream = h0.H0Stream(
        asset="BTCUSDT",
        timeframe="1h",
        bars=_bars(),
        development=(),
        holdout=(cutoff,),
    )
    baseline = _snapshot(cutoff, _fact("baseline"))
    challenger = _snapshot(cutoff, _fact("challenger"))
    baseline_run = h1._PolicyRun(
        h1.POLICIES[0], {}, {cutoff.key(): baseline}, (), {}, ""
    )
    challenger_run = h1._PolicyRun(
        h1.POLICIES[1], {}, {cutoff.key(): challenger}, (), {}, ""
    )
    candidates = h1._replacement_eligible_cases(
        "C1",
        baseline_run,
        challenger_run,
        (stream,),
        (cutoff,),
        frozenset(),
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["display_start"] == 0
    assert candidate["display_end"] == 119
    assert candidate["anchor_positions"] == {
        "A": {"start": 0, "end": 5},
        "B": {"start": 0, "end": 5},
    }


def test_replacement_renderer_scales_and_marks_both_panel_anchors() -> None:
    bars = [h1._bar_payload(bar) for bar in _bars(400)]
    line = {
        "start_anchor_at": "2025-01-01T00:59:59.999000Z",
        "end_anchor_at": "2025-01-01T05:59:59.999000Z",
        "start_anchor_price": 100.0,
        "end_anchor_price": 100.5,
        "slope_per_bar": 0.1,
        "projected_price": 140.0,
    }
    case = {
        "case_id": "review2-case-01",
        "bars": bars,
        "panels": [
            {
                "label": "A",
                "line": line,
                "anchors": [
                    {"kind": "start", "index": 10, "at": line["start_anchor_at"]},
                    {"kind": "end", "index": 15, "at": line["end_anchor_at"]},
                ],
            },
            {
                "label": "B",
                "line": line,
                "anchors": [
                    {"kind": "start", "index": 20, "at": line["start_anchor_at"]},
                    {"kind": "end", "index": 25, "at": line["end_anchor_at"]},
                ],
            },
        ],
    }
    svg = h1._replacement_case_svg(case)
    assert 'width="1290"' in svg
    assert 'data-anchor="A-start"' in svg
    assert 'data-anchor="A-end"' in svg
    assert 'data-anchor="B-start"' in svg
    assert 'data-anchor="B-end"' in svg


def test_blind_html_does_not_publish_policy_identity() -> None:
    payload = {
        "cases": [
            {
                "case_id": "case-01",
                "asset": "BTCUSDT",
                "timeframe": "1h",
                "side": "support",
                "role": "structural",
                "bars": [_bar for _bar in []],
                "panels": [],
            }
        ]
    }
    with pytest.raises(h1.H1ContractError):
        h1._build_blind_html(payload)


def test_replacement_manifest_hides_policy_and_panel_identity() -> None:
    manifest_path = h1.REMEDIATION_OUTPUT_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    public_text = json.dumps(manifest, sort_keys=True)
    assert manifest["panel_counts"] == {"A": 10, "B": 6}
    assert "assignment_counts" not in manifest
    assert "challenger_counts" not in manifest
    assert "baseline" not in public_text.lower()
    assert "challenger" not in public_text.lower()
    assert re.search(r"(?<![A-Za-z0-9])C[0-4](?![A-Za-z0-9])", public_text) is None
