"""Focused contract tests for the V4 N1 identity and persistence tape."""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from libs.models.trendlines_v4.core import (
    SideGeometry,
    TrendlineBar,
    TrendlineGeometry,
    TrendlineSnapshot,
)
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


def _line(
    history: tuple[TrendlineBar, ...],
    side: str,
    *,
    start_index: int = 4,
    end_index: int = 8,
    start_price: float = 100.0,
    end_price: float = 104.0,
    projected: float = 105.0,
    crossed: bool = False,
    cross_count: int = 0,
) -> TrendlineGeometry:
    span = end_index - start_index
    slope = (end_price - start_price) / span
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


def _fake_snapshot(history: tuple[TrendlineBar, ...]) -> TrendlineSnapshot:
    support = _line(
        history,
        "support",
        start_index=0,
        end_index=1,
        start_price=100.0,
        end_price=101.0,
        projected=101.0,
    )
    resistance = _line(
        history,
        "resistance",
        start_index=0,
        end_index=1,
        start_price=100.0,
        end_price=101.0,
        projected=101.0,
    )
    return TrendlineSnapshot(
        schema_version="trendlines.geometry.v1",
        history_bar_count=len(history),
        history_capacity_bars=300,
        pivot_window=3,
        history_start_at=history[0].closed_at,
        market_as_of=history[-1].closed_at,
        support=SideGeometry(support, support, True),
        resistance=SideGeometry(resistance, resistance, True),
    )


def _role_rows(
    window: str,
    values: list[str | None],
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
) -> list[n1.RoleObservation]:
    return [
        n1.RoleObservation(
            asset=asset,
            timeframe=timeframe,  # type: ignore[arg-type]
            window=window,
            cutoff=cutoff,
            side="support",
            role="structural",
            geometry_id=geometry,
        )
        for cutoff, geometry in enumerate(values)
    ]


def test_identity_excludes_role_cutoff_projection_and_crossing_metadata() -> None:
    history = n1._core_bars(_source_bars(12))
    first = _line(history, "support", projected=105.0)
    second = _line(
        history,
        "support",
        projected=106.0,
        crossed=True,
        cross_count=2,
    )

    first_payload = n1.identity_payload(first, history, asset="BTCUSDT", timeframe="1h")
    second_payload = n1.identity_payload(
        second, history, asset="BTCUSDT", timeframe="1h"
    )

    assert first_payload == second_payload
    assert n1.geometry_id(first_payload) == n1.geometry_id(second_payload)
    assert "role" not in first_payload
    assert "cutoff" not in first_payload
    assert "projected_price_at_market_as_of" not in first_payload
    assert "post_anchor_body_cross_count" not in first_payload


def test_identity_uses_float_hex_and_rejects_slope_drift() -> None:
    history = n1._core_bars(_source_bars(12))
    first = _line(history, "support")
    shifted_start = math.nextafter(100.0, math.inf)
    shifted_end = 104.0
    shifted = _line(
        history,
        "support",
        start_price=shifted_start,
        end_price=shifted_end,
    )

    first_payload = n1.identity_payload(first, history, asset="BTCUSDT", timeframe="1h")
    shifted_payload = n1.identity_payload(
        shifted, history, asset="BTCUSDT", timeframe="1h"
    )
    assert first_payload["start_anchor_price"] == (100.0).hex()
    assert shifted_payload["start_anchor_price"] == shifted_start.hex()
    assert n1.geometry_id(first_payload) != n1.geometry_id(shifted_payload)

    invalid = replace(first, slope_per_bar=first.slope_per_bar + 1e-12)
    with pytest.raises(n1.N1ContractError, match="slope"):
        n1.identity_payload(invalid, history, asset="BTCUSDT", timeframe="1h")


def test_reconstruct_episodes_tracks_reappearance_and_resets_per_window() -> None:
    values = ["A", "A", "A", None, "B", "B", None, "A", "A", "A"]
    values.extend([None] * (n1.MEASUREMENT_BARS - len(values)))
    observations = _role_rows("early", values) + _role_rows(
        "late", ["A"] * n1.MEASUREMENT_BARS
    )

    episodes = n1.reconstruct_episodes(observations)
    early = sorted(
        (episode for episode in episodes if episode.window == "early"),
        key=lambda episode: episode.start_cutoff,
    )
    late = [episode for episode in episodes if episode.window == "late"]

    assert [
        (episode.geometry_id, episode.event, episode.lifetime_bars) for episode in early
    ] == [
        ("A", "BIRTH", 3),
        ("B", "BIRTH", 2),
        ("A", "REAPPEAR", 3),
    ]
    assert len(late) == 1
    assert late[0].event == "BIRTH"
    assert late[0].episode_id != early[0].episode_id


def test_derive_4h_uses_exact_contiguous_groups_and_drops_edges() -> None:
    bars = _source_bars(9, start=BASE + timedelta(hours=1))
    aggregated = n1.derive_4h(bars)

    assert len(aggregated) == 1
    group = bars[3:7]
    result = aggregated[0]
    assert result.open_at == group[0].open_at
    assert result.closed_at == group[-1].closed_at
    assert result.open == group[0].open
    assert result.close == group[-1].close
    assert result.high == max(bar.high for bar in group)
    assert result.low == min(bar.low for bar in group)


def test_derive_4h_rejects_an_interior_incomplete_bucket() -> None:
    bars = list(_source_bars(12))
    bars[4] = replace(
        bars[4],
        open_at=BASE + timedelta(hours=5),
        closed_at=BASE + timedelta(hours=5, minutes=59, seconds=59, milliseconds=999),
    )

    with pytest.raises(n1.N1ContractError, match="incomplete|misaligned"):
        n1.derive_4h(bars)


def test_read_source_rejects_a_one_hour_gap(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_text = """open_time,open,high,low,close,close_time
2025-01-01 00:00:00,100,101,99,100.5,2025-01-01 00:59:59.999
2025-01-01 02:00:00,100.5,102,100,101,2025-01-01 02:59:59.999
"""
    source_path = tmp_path / "gap.csv"
    source_bytes = csv_text.encode("utf-8")
    source_path.write_bytes(source_bytes)
    monkeypatch.setattr(n1, "ROOT", tmp_path)
    spec = {
        "asset": "SYNTHETIC",
        "path": source_path.name,
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "row_count": 2,
    }

    with pytest.raises(n1.N1ContractError, match="gap or overlap"):
        n1.read_source(spec)


def test_select_windows_uses_frozen_floor_rule() -> None:
    windows = n1.select_windows(_source_bars(605))

    assert [(window.label, window.start_position) for window in windows] == [
        ("early", 1),
        ("late", 4),
    ]
    assert all(len(window.bars) == n1.WINDOW_LENGTH for window in windows)


def test_window_metadata_records_the_actual_first_and_last_measurement_cutoffs() -> (
    None
):
    window = n1.SelectedWindow("early", 7176, _source_bars(n1.WINDOW_LENGTH))

    metadata = n1._window_metadata("BTCUSDT", "1h", window)

    assert metadata["measurement_cutoffs"]["source_positions"] == [7476, 7775]
    assert metadata["measurement_cutoffs"]["source_positions"] == [
        window.start_position + 300,
        window.start_position + 599,
    ]
    first_slice = window.bars[1:301]
    last_slice = window.bars[300:600]
    assert first_slice[-1] is window.bars[300]
    assert last_slice[-1] is window.bars[599]


def test_measure_window_makes_exact_300_core_calls_with_300_bar_slices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bars(n1.WINDOW_LENGTH)
    window = n1.SelectedWindow("early", 0, source)
    calls: list[tuple[int, datetime, datetime]] = []

    def fake_analyze(history: tuple[TrendlineBar, ...]) -> TrendlineSnapshot:
        calls.append((len(history), history[0].closed_at, history[-1].closed_at))
        return _fake_snapshot(history)

    monkeypatch.setattr(n1, "analyze_trendlines", fake_analyze)
    content: dict[str, dict[str, object]] = {}
    observations, pairs = n1.measure_window("BTCUSDT", "1h", window, content)

    assert len(calls) == n1.MEASUREMENT_BARS
    assert {count for count, _, _ in calls} == {n1.MEASUREMENT_BARS}
    assert calls[0][1] == source[1].closed_at
    assert calls[0][2] == source[300].closed_at
    assert calls[-1][1] == source[300].closed_at
    assert calls[-1][2] == source[599].closed_at
    assert len(observations) == n1.MEASUREMENT_BARS * 4
    assert len(pairs) == n1.MEASUREMENT_BARS * 2
    assert len(content) == n1.MEASUREMENT_BARS * 2


def test_measure_window_rejects_identity_content_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bars(n1.WINDOW_LENGTH)
    window = n1.SelectedWindow("early", 0, source)
    calls = 0

    def changing_snapshot(history: tuple[TrendlineBar, ...]) -> TrendlineSnapshot:
        nonlocal calls
        calls += 1
        start_index = 0 if calls == 1 else 1
        return TrendlineSnapshot(
            schema_version="trendlines.geometry.v1",
            history_bar_count=len(history),
            history_capacity_bars=300,
            pivot_window=3,
            history_start_at=history[0].closed_at,
            market_as_of=history[-1].closed_at,
            support=SideGeometry(
                _line(
                    history,
                    "support",
                    start_index=start_index,
                    end_index=start_index + 1,
                ),
                _line(
                    history,
                    "support",
                    start_index=start_index,
                    end_index=start_index + 1,
                ),
                True,
            ),
            resistance=SideGeometry(
                _line(
                    history,
                    "resistance",
                    start_index=start_index,
                    end_index=start_index + 1,
                ),
                _line(
                    history,
                    "resistance",
                    start_index=start_index,
                    end_index=start_index + 1,
                ),
                True,
            ),
        )

    monkeypatch.setattr(n1, "analyze_trendlines", changing_snapshot)
    monkeypatch.setattr(n1, "geometry_id", lambda _payload: "forced-collision")
    with pytest.raises(n1.N1ContractError, match="content collision"):
        n1.measure_window("BTCUSDT", "1h", window, {})


def test_report_reconciles_compact_measurement_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bars(n1.WINDOW_LENGTH)
    window = n1.SelectedWindow("early", 0, source)
    monkeypatch.setattr(n1, "analyze_trendlines", _fake_snapshot)
    content: dict[str, dict[str, object]] = {}
    observations, pairs = n1.measure_window("BTCUSDT", "1h", window, content)
    measurement = n1.Measurement(
        source_metadata=(),
        windows=(
            {
                "asset": "BTCUSDT",
                "timeframe": "1h",
                "window": "early",
            },
        ),
        observations=observations,
        pair_observations=pairs,
        episodes=n1.reconstruct_episodes(observations),
        geometry_payloads=content,
        identity_collision_count=0,
        identity_content_mismatch_count=0,
        source_gap_failure_count=0,
        aggregation_failure_count=0,
    )

    report = n1.build_report(measurement)
    assert report["inventory"] == {
        "measured_snapshot_count": 300,
        "role_slot_count": 1200,
        "side_snapshot_pair_count": 600,
        "unique_geometry_count": 600,
        "episode_count": 1200,
    }
    assert report["groups"]["global"]["shared_structural_current_geometry_count"] == 600
    assert report["groups"]["global"]["replacement_count"] == 1196
    assert report["groups"]["global"]["replacement_rate_per_100_cutoffs"] == 100.0


def test_protected_production_hashes_are_authenticated() -> None:
    observed = n1._protected_hashes()
    assert observed == {
        name: expected for name, (_, expected) in n1.PROTECTED_HASHES.items()
    }


def test_n1_design_and_approval_authority_is_authenticated() -> None:
    observed = n1._authority_hashes()
    assert observed == {
        name: {
            "path": path.relative_to(n1.ROOT).as_posix(),
            "sha256": expected,
        }
        for name, (path, expected) in n1.N1_AUTHORITY_HASHES.items()
    }
