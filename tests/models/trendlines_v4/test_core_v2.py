"""Focused V2 core, frozen parity, and research-selector compatibility tests."""

from __future__ import annotations

import json
from pathlib import Path

from libs.models.trendlines_v4.core import analyze_trendlines
from libs.models.trendlines_v4.core_v2 import (
    GEOMETRY_SCHEMA_VERSION,
    TrendlineBar,
    analyze_trendlines_v2,
)
from research.trendlines_v4 import exact_geometry_identity_persistence as n1
from research.trendlines_v4 import secondary_candidate_feasibility as n3a

ROOT = Path(__file__).resolve().parents[3]
N3A_REPORT = (
    ROOT / "artifacts/trendlines_v4/n3a_secondary_candidate_feasibility_v1/report.json"
)
N3B_REPORT = (
    ROOT / "artifacts/trendlines_v4/n3b_secondary_visual_utility_v1/report.json"
)


def _geometry_id(line, history, *, asset: str, timeframe: str) -> str | None:
    if line is None:
        return None
    return n1.geometry_id(
        n1.identity_payload(line, history, asset=asset, timeframe=timeframe)
    )


def _histories() -> dict[tuple[str, str], tuple[TrendlineBar, ...]]:
    result: dict[tuple[str, str], tuple[TrendlineBar, ...]] = {}
    for spec in n1.SOURCE_SPECS:
        asset = str(spec["asset"])
        one_hour = n1.read_source(spec)
        result[(asset, "1h")] = tuple(n1._core_bars(one_hour))
        result[(asset, "4h")] = tuple(n1._core_bars(n1.derive_4h(one_hour)))
    return result


def test_v2_schema_roles_and_empty_secondary_are_explicit() -> None:
    bars = tuple(
        TrendlineBar(
            closed_at=__import__("datetime").datetime(
                2026, 1, 1, hour=index, tzinfo=__import__("datetime").UTC
            ),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
        )
        for index in range(1, 7)
    )
    snapshot = analyze_trendlines_v2(bars)
    assert snapshot.schema_version == GEOMETRY_SCHEMA_VERSION
    assert snapshot.history_capacity_bars == 300
    assert snapshot.pivot_window == 3
    for side in (snapshot.support, snapshot.resistance):
        assert side.same_geometry is (
            side.structural is not None and side.structural == side.current_valid
        )
        exposed = {line for line in (side.structural, side.current_valid) if line}
        assert side.secondary not in exposed


def test_v2_secondary_selector_matches_frozen_n3a_and_n3b_membership() -> None:
    n3a_report = json.loads(N3A_REPORT.read_text())
    n3b = json.loads(N3B_REPORT.read_text())
    rows = n3a_report["selected_secondary_observations"]
    histories = _histories()
    observed: dict[tuple[str, str, int, str], str | None] = {}
    for row in rows:
        key = (row["asset"], row["timeframe"])
        source = histories[key]
        end = row["source_position"] + 1
        history = source[end - 300 : end]
        assert len(history) == 300
        snapshot_v1 = analyze_trendlines(history)
        snapshot_v2 = analyze_trendlines_v2(history)
        actual_side_v1 = getattr(snapshot_v1, row["side"])
        actual_side_v2 = getattr(snapshot_v2, row["side"])
        assert actual_side_v2.structural == actual_side_v1.structural
        assert actual_side_v2.current_valid == actual_side_v1.current_valid
        expected_secondary = row["selected_secondary"]
        expected_id = (
            None if expected_secondary is None else expected_secondary["geometry_id"]
        )
        actual_id = _geometry_id(
            actual_side_v2.secondary,
            history,
            asset=row["asset"],
            timeframe=row["timeframe"],
        )
        assert actual_id == expected_id
        if actual_side_v2.secondary is not None:
            assert actual_side_v2.secondary != actual_side_v2.structural
            assert actual_side_v2.secondary != actual_side_v2.current_valid
        observed[
            (row["asset"], row["timeframe"], row["source_position"], row["side"])
        ] = actual_id

    assert len(rows) == 9276
    ranges = n3b["membership"]["ranges"]
    n3b_count = 0
    for item in ranges:
        for source_position in range(
            item["first_source_position"], item["last_source_position"] + 1
        ):
            for side in ("support", "resistance"):
                key = (item["asset"], item["timeframe"], source_position, side)
                if key in observed:
                    n3b_count += 1
                    continue
                source = histories[(item["asset"], item["timeframe"])]
                end = source_position + 1
                history = source[end - 300 : end]
                enumeration = n3a._enumerate_side(
                    history,
                    side,
                    asset=item["asset"],
                    timeframe=item["timeframe"],
                )
                exposed = frozenset(
                    candidate.geometry_id
                    for candidate in (enumeration.structural, enumeration.current_valid)
                    if candidate is not None
                )
                expected = n3a._select_secondary(enumeration.endpoints, exposed)
                expected_id = None if expected is None else expected.geometry_id
                actual = analyze_trendlines_v2(history)
                actual_id = _geometry_id(
                    getattr(actual, side).secondary,
                    history,
                    asset=item["asset"],
                    timeframe=item["timeframe"],
                )
                assert actual_id == expected_id
                n3b_count += 1
    assert n3b_count == 1536
    assert n3b["membership"]["membership_hash"] == (
        "42042794f9db09c8120b67a8c0d70e99c2c7f867d9b87313a22a4e1365b1360c"
    )
