"""Focused contract tests for the N3B pre-rating blind review packet."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from research.trendlines_v4 import exact_geometry_identity_persistence as n1
from research.trendlines_v4 import n3b_secondary_visual_utility as n3b
from research.trendlines_v4 import parameter_sensitivity as h0

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _fact(
    role: str,
    *,
    side: str = "support",
    geometry_id: str = "geometry",
    projected: float = 100.0,
) -> h0.H0LineFact:
    return h0.H0LineFact(
        side=side,  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        geometry_id=geometry_id,
        start_anchor_at="2025-01-01T10:00:00.000000Z",
        end_anchor_at="2025-01-01T20:00:00.000000Z",
        start_anchor_price=99.0,
        end_anchor_price=100.0,
        projected_price=projected,
        projected_price_hex=projected.hex(),
        slope_per_bar=0.1,
        projection_positive=True,
        absolute_close_distance_bps=1.0,
        body_clearance_bps=2.0,
        anchor_span_bars=10,
        start_anchor_age_bars=289,
        end_anchor_age_bars=279,
        start_anchor_headroom_bars=10,
        left_pivot_eligibility_margin_bars=7,
        slope_bps_per_bar=10.0,
        post_anchor_bar_count=279,
        post_anchor_adverse_body_bar_count=0,
        post_anchor_adverse_body_bar_rate=0.0,
        bars_since_last_adverse_body_bar=None,
        current_body_adverse_side="respecting",
        projection_non_positive=False,
    )


def _line(role: str, number: int, *, side: str = "support") -> n3b.N3BLine:
    fact = _fact(
        role,
        side=side,
        geometry_id=f"geometry-{number}",
        projected=100.0 + number,
    )
    return n3b.N3BLine(role, fact, 10 + number, 20 + number, 98.0)


def _observation(
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
    side: str = "support",
    source_position: int = 299,
) -> n3b.N3BObservation:
    cutoff = n3b.N3BCutoff(
        asset=asset,
        timeframe=timeframe,  # type: ignore[arg-type]
        source_position=source_position,
        ordinal=0,
        market_as_of="2025-01-13T00:59:59.999000Z",
    )
    return n3b.N3BObservation(
        cutoff=cutoff,
        side=side,  # type: ignore[arg-type]
        structural=_line("structural", 1, side=side),
        current_valid=_line("current_valid", 2, side=side),
        secondary=_line("secondary", 3, side=side),
        positive_score_endpoint_count=4,
        exact_distinct_endpoint_geometry_count=4,
        exposed_exact_geometry_count=2,
    )


def _source_bars() -> tuple[n1.SourceBar, ...]:
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
        for index in range(300)
    )


def test_n3b_membership_is_exact_and_disjoint_from_h1b_authority() -> None:
    assert n3b.membership_hash() == n3b.N3B_MEMBERSHIP_HASH
    assert sum(item[3] - item[2] + 1 for item in n3b.N3B_RANGES) == 768
    assert n3b.N3B_MEMBERSHIP_HASH != n3b.H1B_MEMBERSHIP_HASH
    assert len(n3b.membership_payload()) == 8


def test_role_permutations_are_deterministic_and_nonconstant() -> None:
    values = tuple(
        n3b._role_permutation(n3b._digest({"scope": index})) for index in range(16)
    )
    assert values == tuple(
        n3b._role_permutation(n3b._digest({"scope": index})) for index in range(16)
    )
    assert len(set(values)) > 1
    assert all(set(value) == set(n3b.BLIND_ROLE_SET) for value in values)


def test_case_selection_is_exactly_balanced_across_frozen_strata() -> None:
    observations = tuple(
        _observation(asset=asset, timeframe=timeframe, side=side)
        for asset in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "HYPEUSDT")
        for timeframe in ("1h", "4h")
        for side in ("support", "resistance")
    )
    measurement = n3b.N3BMeasurement(
        observations=observations,
        parity={},
        eligible_case_count=len(observations),
    )
    selected = n3b._select_cases(measurement)
    assert len(selected) == 16
    assert sum(item.cutoff.timeframe == "1h" for item in selected) == 8
    assert sum(item.cutoff.timeframe == "4h" for item in selected) == 8
    assert sum(item.side == "support" for item in selected) == 8
    assert sum(item.side == "resistance" for item in selected) == 8


def test_public_case_and_html_never_publish_hidden_role_identity() -> None:
    observation = _observation()
    stream = h0.H0Stream(
        asset="BTCUSDT",
        timeframe="1h",
        bars=_source_bars(),
        development=(),
        holdout=(),
    )
    public = n3b._build_public_cases((observation,), (stream,))[0]
    serialized = json.dumps(public, sort_keys=True)
    assert set(public["lines"]) == {"A", "B", "C"}
    for forbidden in (
        "structural",
        "current_valid",
        "secondary",
        "legacy_score",
        "mapping",
    ):
        assert forbidden not in serialized
    html = n3b._html((public,))
    assert "A+B+C" in html
    assert "CLUTTERED" in html and "UNSURE" in html
    assert "structural" not in html
    assert "current_valid" not in html
    assert "secondary" not in html
    assert "mapping" not in html
    assert html.count('data-anchor="A-start"') == 1
    assert html.count('data-anchor="B-start"') == 1
    assert html.count('data-anchor="C-start"') == 1


def test_public_case_is_causal_and_anchor_complete() -> None:
    observation = _observation()
    stream = h0.H0Stream(
        asset="BTCUSDT",
        timeframe="1h",
        bars=_source_bars(),
        development=(),
        holdout=(),
    )
    public = n3b._build_public_cases((observation,), (stream,))[0]
    assert public["anchor_complete"] is True
    assert public["causal_cutoff_only"] is True
    assert public["display_end_source_position"] == public["source_position"]
    assert all(
        bar["source_position"] <= public["source_position"] for bar in public["bars"]
    )


def test_authority_groups_remain_explicitly_separate() -> None:
    assert set(n3b.verify_authorities()) == {"n3b", "production", "n3a"}
    assert set(n3b.verify_authorities()["n3b"]) == {
        "handoff",
        "design",
        "approval",
        "n3a_approval",
    }
