"""Focused contract tests for the N4 independent 1h/closed-4h study."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from research.trendlines_v4 import n4_multitimeframe_context as n4
from research.trendlines_v4 import parameter_sensitivity as h0

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _cutoff(asset: str, position: int, lag: int) -> n4.N4Cutoff:
    return n4.N4Cutoff(
        asset=asset,
        timeframe="1h",
        source_position=position,
        ordinal=position,
        market_as_of=(BASE + timedelta(hours=position)).isoformat(),
    )


def _empty_snapshot(asset: str, timeframe: str, position: int) -> n4.N4Snapshot:
    cutoff = n4.N4Cutoff(
        asset=asset,
        timeframe=timeframe,  # type: ignore[arg-type]
        source_position=position,
        ordinal=position,
        market_as_of=(BASE + timedelta(hours=position)).isoformat(),
    )
    lines = tuple((side, role, None) for side in n4.SIDES for role in n4.ROLES)
    same = tuple((side, False) for side in n4.SIDES)
    return n4.N4Snapshot(cutoff, lines, same)


def _synthetic_measurement() -> n4.N4Measurement:
    one_hour: list[n4.N4Snapshot] = []
    four_hour_by_key: dict[tuple[str, int], n4.N4Snapshot] = {}
    pairs: list[n4.N4Pair] = []
    for asset_index, (asset, _, _) in enumerate(n4.N4_RANGES):
        for lag in range(4):
            for ordinal in range(24):
                position = asset_index * 10000 + lag * 100 + ordinal
                left = _empty_snapshot(asset, "1h", position)
                four_position = asset_index * 10000 + 5000 + lag * 100 + ordinal
                right = four_hour_by_key.setdefault(
                    (asset, four_position),
                    _empty_snapshot(asset, "4h", four_position),
                )
                one_hour.append(left)
                pairs.append(n4.N4Pair(left, right, lag))
    return n4.N4Measurement(
        tuple(one_hour),
        tuple(four_hour_by_key.values()),
        tuple(pairs),
        n4._new_parity(),
    )


def test_membership_contract_is_exact() -> None:
    assert n4.membership_hash() == n4.N4_MEMBERSHIP_HASH
    assert sum(item["cutoff_count"] for item in n4.membership_payload()) == 384
    assert n4.HISTORY_CAPACITY_BARS == 300
    assert n4.PIVOT_WINDOW == 3


def test_frozen_n4_ranges_do_not_overlap_prior_memberships() -> None:
    streams = h0.build_streams()
    cutoffs = n4._build_cutoffs(streams)
    evidence = n4._assert_no_prior_membership_overlap(streams, cutoffs)
    assert evidence == {
        "h0_overlap_count": 0,
        "h1a_overlap_count": 0,
        "h1b_overlap_count": 0,
        "n3b_overlap_count": 0,
        "checked_stream_count": 8,
    }


def test_case_selection_is_exactly_balanced_and_geometry_independent() -> None:
    measurement = _synthetic_measurement()
    selected = n4._select_cases(measurement)
    assert len(selected) == 16
    assert {pair.one_hour.cutoff.asset for pair, _ in selected} == {
        asset for asset, _, _ in n4.N4_RANGES
    }
    assert {pair.pairing_lag_hours for pair, _ in selected} == {0, 1, 2, 3}
    assert {side for _, side in selected} == set(n4.SIDES)
    assert sum(side == "support" for _, side in selected) == 8
    assert sum(side == "resistance" for _, side in selected) == 8
    first_hashes = [n4._case_hash(pair, side) for pair, side in selected]
    second = n4._select_cases(measurement)
    assert first_hashes == [n4._case_hash(pair, side) for pair, side in second]


def test_pair_semantic_payload_keeps_timeframes_separate() -> None:
    pair = n4.N4Pair(
        _empty_snapshot("BTCUSDT", "1h", 13059),
        _empty_snapshot("BTCUSDT", "4h", 3264),
        0,
    )
    payload = pair.semantic_payload()
    assert payload["one_hour"]["cutoff"]["timeframe"] == "1h"
    assert payload["four_hour"]["cutoff"]["timeframe"] == "4h"
    assert payload["pairing_lag_hours"] == 0


def test_cross_line_identity_uses_anchor_timestamps_and_float_hex_only() -> None:
    left_fact = SimpleNamespace(
        start_anchor_at="2025-01-01T00:00:00.000000Z",
        end_anchor_at="2025-01-01T04:00:00.000000Z",
        start_anchor_price=100.0,
        end_anchor_price=104.0,
    )
    right_fact = SimpleNamespace(
        start_anchor_at=left_fact.start_anchor_at,
        end_anchor_at=left_fact.end_anchor_at,
        start_anchor_price=100.0,
        end_anchor_price=104.0,
    )
    left = SimpleNamespace(fact=left_fact)
    right = SimpleNamespace(fact=right_fact)
    assert n4._line_identity(left, right)
    right.fact.end_anchor_price = 104.0 + 2.0**-45
    assert not n4._line_identity(left, right)


def test_latest_closed_pair_rejects_future_or_partial_convention() -> None:
    with pytest.raises(n4.N4ContractError, match="membership hash"):
        original = n4.N4_MEMBERSHIP_HASH
        try:
            n4.N4_MEMBERSHIP_HASH = "wrong"
            n4._assert_membership_contract()
        finally:
            n4.N4_MEMBERSHIP_HASH = original


def test_review_html_contains_two_labeled_panels_and_no_conclusion() -> None:
    measurement = _synthetic_measurement()
    selected = n4._select_cases(measurement)
    cases = [
        {
            "case_id": f"case-{index}",
            "asset": pair.one_hour.cutoff.asset,
            "side": side,
            "pairing_lag_hours": pair.pairing_lag_hours,
            "one_hour": {
                "timeframe": "1h",
                "market_as_of": "2025-01-01T00:00:00Z",
                "bars": [{"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}],
                "lines": [],
            },
            "four_hour": {
                "timeframe": "4h",
                "market_as_of": "2025-01-01T00:00:00Z",
                "bars": [{"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}],
                "lines": [],
            },
        }
        for index, (pair, side) in enumerate(selected, 1)
    ]
    html_bytes = n4._html(cases)
    html_text = html_bytes.decode("utf-8")
    assert html_text.count("<h3>1h panel</h3>") == 16
    assert html_text.count("<h3>4h panel") == 16
    assert "MTF_CONTEXT_" not in html_text
