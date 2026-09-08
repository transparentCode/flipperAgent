"""Focused contract tests for the research-only F1A candidate tape."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from inspect import getsource
from pathlib import Path

import pytest

from libs.models.trendlines_v4.engine.pivots import _pivots
from libs.models.trendlines_v4.engine.types import TrendlineBar
from research.trendlines_v4 import pivot_consensus_candidate_tape as f1a


def _bars(count: int = 25, *, three_pivots: bool = True) -> tuple[TrendlineBar, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    result: list[TrendlineBar] = []
    support_lows = {4: 10.0, 12: 12.0}
    if three_pivots:
        support_lows[8] = 10.0
    resistance_highs = {4: 50.0, 12: 48.0}
    if three_pivots:
        resistance_highs[8] = 49.0
    for index in range(count):
        low = support_lows.get(index, 15.0 + 0.02 * index)
        high = resistance_highs.get(index, 40.0 - 0.02 * index)
        opening = 25.0
        closing = 25.0
        if index == 8 and three_pivots:
            # This candle body intersects the support 4 -> 12 line at 11.0.
            low, high, opening, closing = 10.0, 49.0, 11.0, 11.0
        result.append(
            TrendlineBar(
                closed_at=start + timedelta(hours=index),
                open=opening,
                high=high,
                low=low,
                close=closing,
            )
        )
    return tuple(result)


def _support_pair_candidates(
    tape: f1a.PivotConsensusTape,
) -> tuple[f1a.PivotConsensusCandidate, ...]:
    return tuple(
        candidate
        for candidate in tape.candidates_for_side("support")
        if candidate.start_pivot.index == 4 and candidate.end_pivot.index == 12
    )


def _shifted_bars(prefix_bars: int) -> tuple[TrendlineBar, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC) - timedelta(hours=prefix_bars)
    count = 25 + prefix_bars
    support_lows = {
        4 + prefix_bars: 10.0,
        8 + prefix_bars: 10.0,
        12 + prefix_bars: 12.0,
    }
    resistance_highs = {
        4 + prefix_bars: 50.0,
        8 + prefix_bars: 49.0,
        12 + prefix_bars: 48.0,
    }
    result: list[TrendlineBar] = []
    for index in range(count):
        shifted_index = index - prefix_bars
        low = support_lows.get(index, 15.0 + 0.02 * shifted_index)
        high = resistance_highs.get(index, 40.0 - 0.02 * shifted_index)
        opening = 25.0
        closing = 25.0
        if index == 8 + prefix_bars:
            low, high, opening, closing = 10.0, 49.0, 11.0, 11.0
        result.append(
            TrendlineBar(
                closed_at=start + timedelta(hours=index),
                open=opening,
                high=high,
                low=low,
                close=closing,
            )
        )
    return tuple(result)


def _decimal_anchor_bars() -> tuple[TrendlineBar, ...]:
    start = datetime(2026, 2, 1, tzinfo=UTC)
    result: list[TrendlineBar] = []
    for index in range(12):
        low = 0.5 + 0.01 * index
        opening = closing = 0.75
        if index == 3:
            low = 0.1
            opening = closing = 0.1
        elif index == 7:
            low = 0.2
            opening = closing = 0.2
        result.append(
            TrendlineBar(
                closed_at=start + timedelta(hours=index),
                open=opening,
                high=1.0 + 0.01 * index,
                low=low,
                close=closing,
            )
        )
    return tuple(result)


def test_canonical_preparation_keeps_only_the_last_300_bars() -> None:
    bars = _bars(305)
    tape = f1a.build_candidate_tape(bars)

    assert tape.history_bar_count == 300
    assert tape.bars == bars[-300:]
    assert tape.market_as_of == bars[-1].closed_at


def test_only_existing_causally_confirmed_pivots_are_used() -> None:
    bars = _bars()
    tape = f1a.build_candidate_tape(bars)

    for side, observed in (
        ("support", tape.support_pivots),
        ("resistance", tape.resistance_pivots),
    ):
        canonical = _pivots(tape.bars, side)
        assert tuple((item.index, item.wick_price) for item in observed) == canonical
        assert all(3 <= item.index < len(tape.bars) - 3 for item in observed)


def test_one_ordered_pivot_pair_emits_exactly_four_anchor_modes() -> None:
    tape = f1a.build_candidate_tape(_bars(25, three_pivots=False))
    pair = _support_pair_candidates(tape)

    assert len(tape.support_pivots) == 2
    assert len(pair) == 4
    assert {item.anchor_mode for item in pair} == set(f1a.ANCHOR_MODES)


def test_wick_and_close_prices_use_the_declared_candle_fields() -> None:
    tape = f1a.build_candidate_tape(_bars())
    support = next(item for item in tape.support_pivots if item.index == 4)
    resistance = next(item for item in tape.resistance_pivots if item.index == 4)

    assert support.wick_price == tape.bars[4].low
    assert resistance.wick_price == tape.bars[4].high
    assert support.close_price == tape.bars[4].close
    assert resistance.close_price == tape.bars[4].close
    assert support.price("wick") == tape.bars[4].low
    assert resistance.price("close") == tape.bars[4].close


def test_body_intersections_are_evidence_and_do_not_remove_candidates() -> None:
    tape = f1a.build_candidate_tape(_bars())
    candidates = _support_pair_candidates(tape)

    assert len(candidates) == 4
    assert any(item.body_intersection_count > 0 for item in candidates)
    assert all(
        item.full_range_intersection_count >= item.body_intersection_count
        for item in candidates
    )


def test_interaction_bar_count_is_the_active_suffix() -> None:
    tape = f1a.build_candidate_tape(_bars())
    candidate = _support_pair_candidates(tape)[0]

    assert f1a._interaction_bar_count(300, 0) == 300
    assert (
        candidate.interaction_bar_count == len(tape.bars) - candidate.start_pivot.index
    )
    assert candidate.interaction_bar_count != len(tape.bars)
    assert candidate.as_payload()["interaction_bar_count"] == 21


def test_intersection_rates_use_known_active_interval_counts() -> None:
    tape = f1a.build_candidate_tape(_bars())
    candidate = next(
        item
        for item in _support_pair_candidates(tape)
        if item.anchor_mode == "wick->wick" and item.body_intersection_count > 0
    )
    summary = f1a._audit_rows((candidate,))

    assert candidate.interaction_bar_count == 21
    assert summary["body_intersection_rate"]["mean"] == (
        candidate.body_intersection_count / 21
    )
    assert summary["full_range_intersection_rate"]["mean"] == (
        candidate.full_range_intersection_count / 21
    )
    assert 0 <= summary["body_intersection_rate"]["mean"] <= 1
    assert 0 <= summary["full_range_intersection_rate"]["mean"] <= 1
    assert summary["body_intersection_rate"]["mean"] != (
        candidate.body_intersection_count / len(tape.bars)
    )


def test_candle_interaction_counts_are_deterministic() -> None:
    first = f1a.build_candidate_tape(_bars())
    second = f1a.build_candidate_tape(_bars())

    assert [item.body_intersection_count for item in first.candidates] == [
        item.body_intersection_count for item in second.candidates
    ]
    assert [item.full_range_intersection_count for item in first.candidates] == [
        item.full_range_intersection_count for item in second.candidates
    ]


def test_additional_pivots_produce_continuous_wick_and_close_residuals() -> None:
    tape = f1a.build_candidate_tape(_bars())
    candidate = next(
        item
        for item in _support_pair_candidates(tape)
        if item.anchor_mode == "wick->wick"
    )

    assert [item.pivot_index for item in candidate.pivot_evidence] == [4, 8, 12]
    assert len(candidate.non_anchor_evidence) == 1
    evidence = candidate.non_anchor_evidence[0]
    assert evidence.wick_residual_bps >= 0
    assert evidence.close_residual_bps >= 0
    assert evidence.nearest_residual_bps == min(
        evidence.wick_residual_bps, evidence.close_residual_bps
    )
    assert evidence.nearest_source in {"wick", "close", "both"}
    assert (
        candidate.best_non_anchor_nearest_residual_bps == evidence.nearest_residual_bps
    )


def test_no_residual_threshold_is_used_for_candidate_inclusion() -> None:
    tape = f1a.build_candidate_tape(_bars())

    assert len(tape.candidates_for_side("support")) == 12
    assert len(tape.candidates_for_side("resistance")) == 12
    assert any(
        item.best_non_anchor_nearest_residual_bps is not None
        and item.best_non_anchor_nearest_residual_bps > 1000
        for item in tape.candidates
    )


def test_candidate_order_and_identity_are_stable() -> None:
    first = f1a.build_candidate_tape(_bars())
    second = f1a.build_candidate_tape(_bars())

    assert first == second
    assert first.tape_id == second.tape_id
    assert [item.candidate_id for item in first.candidates] == [
        item.candidate_id for item in second.candidates
    ]
    assert [item.anchor_mode for item in first.candidates[:8]] == [
        "wick->wick",
        "wick->close",
        "close->wick",
        "close->close",
        "wick->wick",
        "wick->close",
        "close->wick",
        "close->close",
    ]


def test_provenance_distinct_candidates_can_have_identical_geometry() -> None:
    bars = list(_bars(25, three_pivots=False))
    bars[4] = replace(bars[4], open=10.0, close=10.0, low=10.0)
    bars[12] = replace(bars[12], open=12.0, close=12.0, low=12.0)
    tape = f1a.build_candidate_tape(tuple(bars))
    pair = _support_pair_candidates(tape)
    wick_wick = next(item for item in pair if item.anchor_mode == "wick->wick")
    close_close = next(item for item in pair if item.anchor_mode == "close->close")

    assert wick_wick.candidate_id != close_close.candidate_id
    assert wick_wick.geometry_id == close_close.geometry_id
    assert tape.geometry_duplicate_count() >= 2


def test_candidate_payload_contains_factual_metadata_only() -> None:
    candidate = _support_pair_candidates(f1a.build_candidate_tape(_bars()))[0]
    payload = candidate.as_payload()

    assert "body_intersection_count" in payload
    assert "full_range_intersection_count" in payload
    assert "pivot_evidence" in payload
    assert "wick_intersection_count" not in payload
    assert not any(name in payload for name in ("score", "rank", "selected", "quality"))


def test_defining_anchor_prices_and_residuals_are_exact() -> None:
    tape = f1a.build_candidate_tape(_decimal_anchor_bars())
    candidates = tuple(
        candidate
        for candidate in tape.candidates_for_side("support")
        if candidate.start_pivot.index == 3 and candidate.end_pivot.index == 7
    )

    assert len(candidates) == 4
    for candidate in candidates:
        assert candidate.line_price_at(3) == candidate.start_price
        assert candidate.line_price_at(7) == candidate.end_price
        evidence_by_index = {
            item.pivot_index: item for item in candidate.pivot_evidence
        }
        start_evidence = evidence_by_index[3]
        end_evidence = evidence_by_index[7]
        assert getattr(start_evidence, f"{candidate.start_source}_residual_bps") == 0.0
        assert getattr(end_evidence, f"{candidate.end_source}_residual_bps") == 0.0
        assert candidate.anchor_full_range_intersection_count == 2


def test_contact_decomposition_is_full_range_and_non_anchor_explicit() -> None:
    tape = f1a.build_candidate_tape(_bars())

    for candidate in tape.candidates:
        assert candidate.anchor_full_range_intersection_count == 2
        assert candidate.body_intersection_count == (
            candidate.anchor_body_intersection_count
            + candidate.non_anchor_body_intersection_count
        )
        assert candidate.full_range_intersection_count == (
            candidate.anchor_full_range_intersection_count
            + candidate.non_anchor_full_range_intersection_count
        )
        assert 0 <= candidate.body_intersection_count
        assert (
            candidate.body_intersection_count <= candidate.full_range_intersection_count
        )
        assert (
            candidate.full_range_intersection_count <= candidate.interaction_bar_count
        )
        assert (
            candidate.wick_intersection_count == candidate.full_range_intersection_count
        )


def test_observable_from_is_the_second_pivot_confirmation_time() -> None:
    tape = f1a.build_candidate_tape(_bars())
    candidate = _support_pair_candidates(tape)[0]

    assert (
        candidate.observable_from_index == candidate.end_pivot.index + f1a.PIVOT_WINDOW
    )
    assert (
        candidate.observable_from_at
        == tape.bars[candidate.observable_from_index].closed_at
    )
    assert candidate.observable_from_at > candidate.end_pivot.at
    payload = candidate.as_payload()
    assert payload["observable_from_index"] == candidate.observable_from_index
    assert payload["observable_from_at"] == candidate.observable_from_at.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def test_candidate_id_is_origin_stable_but_geometry_id_is_local() -> None:
    origin_a = f1a.build_candidate_tape(_shifted_bars(0))
    origin_b = f1a.build_candidate_tape(_shifted_bars(1))
    candidate_a = next(
        candidate
        for candidate in origin_a.candidates_for_side("support")
        if candidate.anchor_mode == "wick->wick"
        and candidate.start_pivot.index == 4
        and candidate.end_pivot.index == 12
    )
    candidate_b = next(
        candidate
        for candidate in origin_b.candidates_for_side("support")
        if candidate.anchor_mode == "wick->wick"
        and candidate.start_pivot.index == 5
        and candidate.end_pivot.index == 13
    )

    assert candidate_a.start_pivot.at == candidate_b.start_pivot.at
    assert candidate_a.end_pivot.at == candidate_b.end_pivot.at
    assert candidate_a.candidate_id == candidate_b.candidate_id
    assert candidate_a.geometry_id != candidate_b.geometry_id


def test_prefix_candidate_is_independent_of_unsupplied_future_bars() -> None:
    prefix = _bars(25)
    future = list(_bars(35)[25:])
    future[0] = replace(future[0], low=1.0, high=60.0, open=30.0, close=30.0)

    first = f1a.build_candidate_tape(prefix)
    second = f1a.build_candidate_tape((*prefix, *future))

    assert first == f1a.build_candidate_tape(prefix)
    assert second != first
    assert first.tape_id == f1a.build_candidate_tape(prefix).tape_id


def test_exact_cardinality_preflight_includes_dense_flat_history_without_materializing() -> (
    None
):
    ordinary = f1a.candidate_cardinality_preflight(2, 3)
    assert ordinary == {
        "support_pivot_count": 2,
        "resistance_pivot_count": 3,
        "support_candidate_count": 4,
        "resistance_candidate_count": 12,
        "total_candidate_count": 16,
        "support_potential_pivot_evidence_rows": 8,
        "resistance_potential_pivot_evidence_rows": 32,
        "total_potential_pivot_evidence_rows": 40,
    }

    dense = f1a.candidate_cardinality_preflight(294, 294)
    assert dense == {
        "support_pivot_count": 294,
        "resistance_pivot_count": 294,
        "support_candidate_count": 172284,
        "resistance_candidate_count": 172284,
        "total_candidate_count": 344568,
        "support_potential_pivot_evidence_rows": 33882520,
        "resistance_potential_pivot_evidence_rows": 33882520,
        "total_potential_pivot_evidence_rows": 67765040,
    }


def test_audit_report_is_incremental_and_mode_descriptive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = {
        "manifest_id": "synthetic-g6-manifest",
        "sources": [
            {
                "asset": "TESTUSDT",
                "timeframe": "1h",
                "windows": [
                    {
                        "window": "synthetic",
                        "first_open_time": "",
                        "last_close_time": "",
                        "start_index": 0,
                        "end_index_exclusive": 25,
                        "ohlc_input_sha256": "synthetic-window",
                    }
                ],
                "path": "synthetic.csv",
                "sha256": "synthetic-source",
                "data_row_count": 25,
            }
        ],
    }
    monkeypatch.setattr(f1a, "authenticate_g6_sources", lambda: manifest)
    monkeypatch.setattr(
        f1a,
        "_window_bars_from_manifest",
        lambda source, window: _bars(),
    )

    audit_manifest, report = f1a.audit_frozen_g6_sources()

    assert audit_manifest["window_count"] == 1
    assert report["global"]["candidate_count"] == 24
    assert set(report["by_anchor_mode"]) == set(f1a.ANCHOR_MODES)
    assert all(
        report["by_anchor_mode"][mode]["candidate_count"] == 6
        for mode in f1a.ANCHOR_MODES
    )
    assert "full_range_intersection_count" in report["global"]
    assert "full_range_intersection_rate" in report["global"]
    assert "wick_intersection_count" not in report["global"]
    assert set(report["global"]["nearest_source_counts"]) == {
        "wick",
        "close",
        "both",
    }
    audit_source = getsource(f1a.audit_frozen_g6_sources)
    assert "all_candidates" not in audit_source
    assert "build_candidate_tape" not in audit_source
    assert "include_evidence=False" in audit_source


def test_no_selector_or_arbitrary_filter_was_added() -> None:
    source = Path(f1a.__file__).read_text()

    assert "top_k" not in source
    assert "candidate_cap" not in source
    assert "isclose" not in source
    assert "quality_score" not in source


def test_prefix_analysis_is_point_in_time_and_ignores_later_bars() -> None:
    full = _bars(60)
    cutoff = 25
    from_prefix = f1a.build_candidate_tape(full[:cutoff])
    from_same_prefix = f1a.build_candidate_tape(full[:cutoff] + full[cutoff:])
    expected_prefix = f1a.build_candidate_tape(full[:cutoff])

    assert from_prefix == expected_prefix
    assert from_prefix.bars == full[:cutoff]
    assert from_same_prefix != from_prefix
    assert from_prefix.market_as_of == full[cutoff - 1].closed_at


def test_malformed_history_fails_closed_through_canonical_v4_validation() -> None:
    bars = _bars()
    with pytest.raises(ValueError, match="strictly increasing"):
        f1a.build_candidate_tape((bars[0], bars[2], bars[1], *bars[3:]))
    with pytest.raises(TypeError, match="only TrendlineBar"):
        f1a.build_candidate_tape((bars[0], object()))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be UTC"):
        TrendlineBar(
            closed_at=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
        )
    with pytest.raises(ValueError, match="finite"):
        TrendlineBar(
            closed_at=datetime(2026, 1, 1, tzinfo=UTC),
            open=float("nan"),
            high=2.0,
            low=0.5,
            close=1.5,
        )


def test_g6_source_manifest_is_authenticated_without_network() -> None:
    manifest = f1a.authenticate_g6_sources()

    assert (
        manifest["manifest_id"]
        == "e239a408f8220cb822d8f056957178a3c32c6775f9d1db63999f4c47c811d298"
    )
    assert manifest["window_count"] == 15
    assert manifest["row_count"] == 4500
    assert [source["asset"] for source in manifest["sources"]] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "HYPEUSDT",
    ]


def test_research_module_does_not_change_production_surface() -> None:
    module_source = Path(f1a.__file__).read_text()
    assert "trendlines_v4.core" not in module_source
    assert "trendlines_v4.core_v2" not in module_source
    assert "trendlines@" not in module_source
