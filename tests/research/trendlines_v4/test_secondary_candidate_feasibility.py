"""Focused contract tests for the N3A secondary-candidate feasibility tape."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from libs.models.trendlines_v4 import core
from research.trendlines_v4 import exact_geometry_identity_persistence as n1
from research.trendlines_v4 import parameter_sensitivity as h0
from research.trendlines_v4 import secondary_candidate_feasibility as n3a

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _history(count: int = 300) -> tuple[core.TrendlineBar, ...]:
    bars: list[core.TrendlineBar] = []
    for index in range(count):
        center = 100.0 + 4.0 * math.sin(index / 5.0) + index * 0.01
        bars.append(
            core.TrendlineBar(
                closed_at=BASE + timedelta(hours=index),
                open=center,
                high=center + 0.4,
                low=center - 0.4,
                close=center,
            )
        )
    return tuple(bars)


def _cutoff(*, partition: str = "development") -> h0.H0Cutoff:
    return h0.H0Cutoff(
        asset="BTCUSDT",
        timeframe="1h",
        window="early",
        cutoff=0,
        source_position=671,
        market_as_of="2025-01-29T00:59:59.999000Z",
        partition=partition,  # type: ignore[arg-type]
    )


def _endpoint(
    endpoint_index: int, score: int, geometry_id: str
) -> n3a.EndpointCandidate:
    return n3a.EndpointCandidate(
        endpoint_index=endpoint_index,
        score=score,
        path=(),
        line=None,
        geometry=None,  # type: ignore[arg-type]
        geometry_id=geometry_id,
    )


def test_n3a_profile_and_membership_authorities_are_fixed() -> None:
    assert n3a.PIVOT_WINDOW == 3
    assert n3a.HISTORY_CAPACITY_BARS == 300
    assert n3a.DEVELOPMENT_MEMBERSHIP_HASH == (
        "e3104d4cc9822abe23c45f566266b5149107b27d65088e7b4f8fa1739fe555d8"
    )
    assert n3a.H1B_MEMBERSHIP_HASH == (
        "71bce66333b89f96d093de764f93a954add7c7e9d4f28848767ed8d67697fbda"
    )
    assert n3a.N3B_MEMBERSHIP_HASH == (
        "42042794f9db09c8120b67a8c0d70e99c2c7f867d9b87313a22a4e1365b1360c"
    )
    for timeframe in ("1h", "4h"):
        profiles = n3a._baseline_profile(timeframe)
        assert profiles.pivot_window == 3
        assert profiles.effective_history_bars == 300


def test_secondary_selector_excludes_exposed_and_preserves_strict_ties() -> None:
    endpoints = (
        _endpoint(0, 9, "structural"),
        _endpoint(1, 12, "first"),
        _endpoint(2, 12, "second"),
        _endpoint(3, 20, "exposed"),
    )
    assert n3a._select_secondary(endpoints, frozenset({"exposed"})) == endpoints[1]
    assert (
        n3a._select_secondary(endpoints, frozenset({"first", "exposed"}))
        == endpoints[2]
    )
    assert (
        n3a._select_secondary(
            endpoints,
            frozenset({"first", "second", "exposed"}),
        )
        == endpoints[0]
    )


def test_secondary_selector_does_not_apply_crossing_or_relevance_filters() -> None:
    candidate = _endpoint(0, 4, "alternate")
    assert n3a._select_secondary((candidate,), frozenset()) is candidate


def test_endpoint_enumeration_matches_frozen_core_roles() -> None:
    history = _history()
    snapshot = core.analyze_trendlines(history)
    for side in n1.SIDES:
        enumeration = n3a._enumerate_side(
            history,
            side,
            asset="BTCUSDT",
            timeframe="1h",
        )
        expected = getattr(snapshot, side)
        assert (
            None if enumeration.structural is None else enumeration.structural.geometry
        ) == expected.structural
        assert (
            None
            if enumeration.current_valid is None
            else enumeration.current_valid.geometry
        ) == expected.current_valid


def test_holdout_cutoffs_are_rejected_before_any_evaluation() -> None:
    cutoff = _cutoff(partition="holdout")
    stream = h0.H0Stream(
        asset="BTCUSDT",
        timeframe="1h",
        bars=(),
        development=(),
        holdout=(cutoff,),
    )
    with pytest.raises(n3a.N3AContractError, match="sealed holdout"):
        n3a._validate_development_cutoff(stream, cutoff)


def test_n3b_ranges_are_provenance_only_and_not_an_evaluation_surface() -> None:
    assert len(n3a.N3B_RANGES) == 8
    assert all(first <= last for _, _, first, last in n3a.N3B_RANGES)
    assert not hasattr(n3a, "evaluate_n3b")


def test_observation_payload_exposes_only_selected_secondary_facts() -> None:
    cutoff = _cutoff()
    observation = n3a.N3AObservation(
        cutoff=cutoff,
        side="support",
        structural=None,
        current_valid=None,
        secondary=None,
        secondary_score=None,
        secondary_endpoint_index=None,
        positive_score_endpoint_count=2,
        exact_distinct_endpoint_geometry_count=2,
        already_exposed_exact_geometry_count=1,
        remaining_alternate_exact_geometry_count=1,
        current_close=100.0,
    )
    payload = observation.as_payload()
    assert payload["candidate_pool"]["secondary_available"] is False
    assert payload["selected_secondary"] is None
    assert "ranked_endpoint_catalogue" not in payload
