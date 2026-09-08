"""Focused contract tests for the V4 N2 relevance-metadata tape."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from libs.models.trendlines_v4.core import TrendlineBar, TrendlineGeometry
from research.trendlines_v4 import current_relevance_metadata as n2
from research.trendlines_v4 import exact_geometry_identity_persistence as n1

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _source_bars(
    count: int,
    *,
    start: datetime = BASE,
) -> tuple[n1.SourceBar, ...]:
    bars: list[n1.SourceBar] = []
    for index in range(count):
        open_price = 100.0 + index * 0.01
        close_price = open_price + (0.2 if index % 2 else -0.1)
        bars.append(
            n1.SourceBar(
                open_at=start + timedelta(hours=index),
                closed_at=start
                + timedelta(hours=index, minutes=59, seconds=59, milliseconds=999),
                open=open_price,
                high=max(open_price, close_price) + 0.5,
                low=min(open_price, close_price) - 0.5,
                close=close_price,
            )
        )
    return tuple(bars)


def _history_bars(
    *,
    default_body: float = 101.0,
    crossing_index: int | None = None,
    start: datetime = BASE,
) -> tuple[TrendlineBar, ...]:
    bars: list[TrendlineBar] = []
    for index in range(n2.MEASUREMENT_BARS):
        body = default_body
        if crossing_index == index:
            body = 99.0 if default_body > 100.0 else 101.0
        bars.append(
            TrendlineBar(
                closed_at=start
                + timedelta(hours=index, minutes=59, seconds=59, milliseconds=999),
                open=body,
                high=body + 1.0,
                low=body - 1.0,
                close=body,
            )
        )
    return tuple(bars)


def _line(
    history: tuple[TrendlineBar, ...],
    side: str,
    *,
    start_index: int = 4,
    end_index: int = 8,
    start_price: float = 100.0,
    end_price: float = 100.0,
    projected: float = 100.0,
    crossed: bool = False,
    cross_count: int = 0,
) -> TrendlineGeometry:
    slope = (end_price - start_price) / (end_index - start_index)
    return TrendlineGeometry(
        side=side,
        start_anchor_at=history[start_index].closed_at,
        start_anchor_price=start_price,
        end_anchor_at=history[end_index].closed_at,
        end_anchor_price=end_price,
        slope_per_bar=slope,
        projected_price_at_market_as_of=projected,
        post_anchor_body_crossed=crossed,
        post_anchor_body_cross_count=cross_count,
        projection_positive=projected > 0,
    )


def _geometry_payloads(
    line: TrendlineGeometry,
    history: tuple[TrendlineBar, ...],
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
) -> dict[str, dict[str, object]]:
    payload = n1.identity_payload(
        line,
        history,
        asset=asset,
        timeframe=timeframe,  # type: ignore[arg-type]
    )
    return {n1.geometry_id(payload): payload}


def _observation(
    line: TrendlineGeometry,
    history: tuple[TrendlineBar, ...],
    *,
    role: str = "structural",
    window: str = "early",
    cutoff: int = 0,
) -> n2.RelevanceObservation:
    return n2.build_observation(
        line,
        history,
        asset="BTCUSDT",
        timeframe="1h",
        window=window,
        cutoff=cutoff,
        role=role,  # type: ignore[arg-type]
        n1_geometry_payloads=_geometry_payloads(line, history),
    )


def test_n1_reference_and_protected_identity_locks_are_exact() -> None:
    reference = n2._load_n1_reference()

    assert reference.report["inventory"] == {
        "episode_count": 2363,
        "measured_snapshot_count": 4800,
        "role_slot_count": 19200,
        "side_snapshot_pair_count": 9600,
        "unique_geometry_count": 1159,
    }
    assert n2._verify_hashes(n2.N1_LOCKS) == {
        name: expected for name, (_, expected) in n2.N1_LOCKS.items()
    }
    assert n2._authority_view()["design"]["sha256"] == (
        "fb5d0d336d7e7441f25f8aeab3c1c5eee4f9e822bf6919e7ded0de0a8706f12d"
    )


def test_history_uses_exact_300_bar_causal_slice_and_published_cutoffs() -> None:
    window = n1.SelectedWindow("early", 700, _source_bars(600))

    first = n2._history_for_cutoff(window, 0)
    last = n2._history_for_cutoff(window, 299)

    assert len(first) == len(last) == 300
    assert first[0].closed_at == window.bars[1].closed_at
    assert first[-1].closed_at == window.bars[300].closed_at
    assert last[0].closed_at == window.bars[300].closed_at
    assert last[-1].closed_at == window.bars[599].closed_at
    assert [window.start_position + 300, window.start_position + 599] == [
        1000,
        1299,
    ]


def test_future_suffix_mutation_cannot_change_an_earlier_observation() -> None:
    original = _source_bars(600)
    changed_suffix = original[:301] + tuple(
        replace(
            bar,
            open=bar.open + 50.0,
            high=bar.high + 50.0,
            low=bar.low + 50.0,
            close=bar.close + 50.0,
        )
        for bar in original[301:]
    )
    first_window = n1.SelectedWindow("early", 0, original)
    changed_window = n1.SelectedWindow("early", 0, changed_suffix)
    first_history = n2._history_for_cutoff(first_window, 0)
    changed_history = n2._history_for_cutoff(changed_window, 0)

    line = _line(first_history, "support")
    assert first_history == changed_history
    assert _observation(line, first_history) == _observation(
        line,
        changed_history,
    )


def test_anchor_positions_are_unique_and_metadata_ages_follow_identity_invariant() -> (
    None
):
    history = _history_bars()
    line = _line(history, "support")
    observation = _observation(line, history)

    assert observation.anchor_span_bars == 4
    assert observation.start_anchor_age_bars == 295
    assert observation.end_anchor_age_bars == 291
    assert observation.start_anchor_headroom_bars == 4
    assert observation.start_anchor_age_bars == (
        observation.end_anchor_age_bars + observation.anchor_span_bars
    )

    duplicate = list(history)
    duplicate[2] = replace(duplicate[2], closed_at=duplicate[1].closed_at)
    duplicate_history = tuple(duplicate)
    duplicate_line = _line(duplicate_history, "support", start_index=1)
    with pytest.raises(n2.N2ContractError, match="uniquely"):
        n2._anchor_positions(duplicate_line, duplicate_history)


def test_close_distance_body_clearance_and_exact_zero_are_side_aware() -> None:
    support_history = _history_bars(default_body=101.0)
    support = _observation(_line(support_history, "support"), support_history)
    assert support.absolute_close_distance_bps == pytest.approx(1.0 / 101.0 * 10_000)
    assert support.body_clearance_bps == pytest.approx(1.0 / 101.0 * 10_000)

    resistance_history = _history_bars(default_body=99.0)
    resistance = _observation(
        _line(resistance_history, "resistance"),
        resistance_history,
    )
    assert resistance.body_clearance_bps == pytest.approx(1.0 / 99.0 * 10_000)

    exact_history = _history_bars(default_body=100.0)
    exact = _observation(_line(exact_history, "support"), exact_history)
    assert exact.absolute_close_distance_bps == 0.0
    assert exact.body_clearance_bps == 0.0


def test_body_clearance_negative_sign_is_preserved_for_support_and_resistance() -> None:
    support_history = _history_bars(default_body=99.0)
    support_line = _line(
        support_history,
        "support",
        cross_count=n2.MEASUREMENT_BARS - 1 - 8,
        crossed=True,
    )
    assert _observation(support_line, support_history).body_clearance_bps < 0.0

    resistance_history = _history_bars(default_body=101.0)
    resistance_line = _line(
        resistance_history,
        "resistance",
        cross_count=n2.MEASUREMENT_BARS - 1 - 8,
        crossed=True,
    )
    assert _observation(resistance_line, resistance_history).body_clearance_bps < 0.0


def test_normalized_slope_preserves_sign_and_uses_current_close() -> None:
    history = _history_bars(default_body=200.0)
    positive = _line(
        history,
        "support",
        start_price=100.0,
        end_price=100.4,
        projected=129.5,
    )
    negative = _line(
        history,
        "support",
        start_price=100.4,
        end_price=100.0,
        projected=70.5,
    )

    positive_observation = _observation(positive, history)
    negative_observation = _observation(negative, history)
    expected = positive.slope_per_bar / 200.0 * 10_000
    assert positive_observation.slope_bps_per_bar == expected
    assert positive_observation.slope_bps_per_bar > 0
    assert negative_observation.slope_bps_per_bar < 0


def test_crossing_metadata_matches_p0_strict_body_semantics() -> None:
    support_history = _history_bars(default_body=101.0, crossing_index=12)
    support = _observation(
        _line(
            support_history,
            "support",
            crossed=True,
            cross_count=1,
        ),
        support_history,
    )
    assert support.post_anchor_bar_count == 291
    assert support.post_anchor_body_cross_count == 1
    assert support.post_anchor_body_cross_rate == pytest.approx(1.0 / 291.0)
    assert support.bars_since_last_body_cross == 287

    resistance_history = _history_bars(default_body=99.0, crossing_index=12)
    resistance = _observation(
        _line(
            resistance_history,
            "resistance",
            crossed=True,
            cross_count=1,
        ),
        resistance_history,
    )
    assert resistance.post_anchor_body_cross_count == 1
    assert resistance.bars_since_last_body_cross == 287

    never_crossed = _observation(
        _line(_history_bars(default_body=101.0), "support"),
        _history_bars(default_body=101.0),
    )
    assert never_crossed.bars_since_last_body_cross is None


def test_crossing_excludes_end_anchor_and_wick_only_penetration() -> None:
    history = list(_history_bars(default_body=101.0))
    history[8] = replace(history[8], open=99.0, close=99.0, low=98.0)
    history[12] = replace(history[12], low=99.0)
    frozen_history = tuple(history)

    observation = _observation(
        _line(frozen_history, "support"),
        frozen_history,
    )
    assert observation.post_anchor_bar_count == 291
    assert observation.post_anchor_body_cross_count == 0
    assert observation.post_anchor_body_cross_rate == 0.0


def test_crossing_count_mismatch_fails_closed() -> None:
    history = _history_bars(default_body=101.0, crossing_index=12)
    with pytest.raises(n2.N2ContractError, match="crossing-count"):
        _observation(
            _line(history, "support", crossed=False, cross_count=0),
            history,
        )


def test_shared_role_duplicates_collapse_and_divergent_metadata_is_rejected() -> None:
    history = _history_bars()
    line = _line(history, "support")
    structural = _observation(line, history, role="structural")
    current = replace(structural, role="current_valid")
    unique: dict[tuple[object, ...], n2.RelevanceObservation] = {}

    n2._register_unique(unique, structural)
    n2._register_unique(unique, current)
    assert len(unique) == 1
    assert unique[next(iter(unique))] == current

    forged = replace(current, body_clearance_bps=math.nextafter(1.0, 2.0))
    with pytest.raises(n2.N2ContractError, match="metadata disagrees"):
        n2._register_unique(unique, forged)


def test_first_five_headroom_counter_is_a_report_only_index_bin() -> None:
    history = _history_bars()
    line = _line(history, "support")
    base = _observation(line, history)
    rows = tuple(
        replace(
            base,
            cutoff=index,
            start_anchor_headroom_bars=index,
            geometry_id=f"geometry-{index}",
        )
        for index in range(6)
    )

    summary = n2.summarize_scope(rows, ())
    assert summary["start_anchor_headroom_zero_count"] == 1
    assert summary["start_anchor_headroom_at_most_four_count"] == 5
    assert summary["unique_geometry_at_cutoff_count"] == 6


def test_report_declares_descriptive_conclusion_without_a_relevance_score() -> None:
    history = _history_bars()
    observation = _observation(_line(history, "support"), history)
    measurement = n2.N2Measurement(
        source_metadata=(),
        windows=(),
        observations=(observation,),
        unique_geometry_observations=(observation,),
        pairs=(),
        n1_geometry_count=1,
        n1_role_slot_count=1,
        n1_pair_count=0,
        n1_episode_count=0,
    )

    report = n2.build_report(measurement)
    assert report["conclusion"] == "CURRENT_RELEVANCE_METADATA_SUPPORTED"
    assert "relevance_score" not in report
    assert "threshold" not in report
