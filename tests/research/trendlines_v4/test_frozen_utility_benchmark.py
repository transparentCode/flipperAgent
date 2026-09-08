"""Focused tests for the frozen G6 utility measurements."""

from __future__ import annotations

import json
from pathlib import Path

import research.trendlines_v4.frozen_utility_benchmark as g6


def _bars(count: int = 15) -> tuple[g6.G6Bar, ...]:
    return tuple(
        g6.G6Bar(
            f"2026-01-01T{index:02d}:00:00Z",
            f"2026-01-01T{index:02d}:59:59Z",
            20.0 + index,
            21.0 + index,
            19.0 + index,
            20.5 + index,
        )
        for index in range(count)
    )


def _line(side: str, price: float) -> g6.EmittedLine:
    return g6.EmittedLine(0, 1, price, price, 0.0, price, price)


def _outcome(variant: str, side: str, line: g6.EmittedLine) -> dict[str, object]:
    return g6._future_outcome(
        {
            "variant": variant,
            "asset": "SYNTH",
            "side": side,
            "index": 0,
            "line": line,
            "recovered": False,
        },
        _bars(),
        {horizon: 0.0 for horizon in g6.HORIZONS},
    )


def test_manifest_is_deterministic_and_has_the_frozen_fifteen_windows() -> None:
    first = g6.build_manifest()
    second = g6.build_manifest()

    assert first == second
    assert first["window_count"] == 15
    assert first["row_count"] == 4500
    assert [source["asset"] for source in first["sources"]] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "HYPEUSDT",
    ]
    assert [len(source["windows"]) for source in first["sources"]] == [4, 4, 4, 3]
    assert first["g0_non_overlap"] is True
    assert g6.verify_protected_hashes() == first["protected_hashes"]


def test_window_start_rule_is_exact_integer_floor() -> None:
    assert g6._window_starts("BTCUSDT", 27721) == (5484, 10968, 16452, 21936)
    assert g6._window_starts("HYPEUSDT", 6591) == (1572, 3145, 4718)


def test_next_bar_event_is_not_the_same_bar() -> None:
    line = _line("support", 10.0)
    current = g6.G6Bar("a", "a", 20.0, 20.0, 20.0, 20.0)
    next_bar = g6.G6Bar("b", "b", 11.0, 12.0, 9.0, 11.0)

    assert g6._event(line, current, 0, "support") is None
    assert g6._event(line, next_bar, 1, "support") == "WICK_INTERACTION"


def test_support_and_resistance_events_have_body_precedence() -> None:
    support = _line("support", 10.0)
    resistance = _line("resistance", 10.0)
    support_break = g6.G6Bar("", "", 9.0, 11.0, 8.0, 9.0)
    resistance_break = g6.G6Bar("", "", 11.0, 12.0, 9.0, 11.0)
    support_wick = g6.G6Bar("", "", 11.0, 12.0, 9.0, 11.0)
    resistance_wick = g6.G6Bar("", "", 9.0, 11.0, 8.0, 9.0)

    assert g6._event(support, support_break, 1, "support") == "BODY_BREAK"
    assert g6._event(resistance, resistance_break, 1, "resistance") == "BODY_BREAK"
    assert g6._event(support, support_wick, 1, "support") == "WICK_INTERACTION"
    assert g6._event(resistance, resistance_wick, 1, "resistance") == "WICK_INTERACTION"


def test_episode_grouping_counts_exact_geometry_changes() -> None:
    bars = _bars(4)
    first, second = _line("support", 10.0), _line("support", 11.0)
    selections = (
        g6.Selection(None),
        g6.Selection(first),
        g6.Selection(first),
        g6.Selection(second),
    )

    episodes, changes = g6._episodes(bars, selections, "support")

    assert changes == 1
    assert [episode["duration"] for episode in episodes] == [2, 1]
    assert all(episode["first_event"] is None for episode in episodes)


def test_future_horizons_are_all_or_none_and_body_break_is_frozen() -> None:
    bars = list(_bars(15))
    bars[1] = g6.G6Bar("", "", 9.0, 10.0, 8.0, 9.0)
    result = g6._future_outcome(
        {
            "variant": "G1",
            "asset": "SYNTH",
            "side": "support",
            "index": 0,
            "line": _line("support", 10.0),
            "recovered": False,
        },
        bars[:5],
        {horizon: 0.0 for horizon in g6.HORIZONS},
    )

    assert result["horizons"]["1"]["available"] is True
    assert result["horizons"]["3"]["available"] is True
    assert result["horizons"]["6"]["available"] is False
    assert result["horizons"]["12"]["available"] is False
    assert result["horizons"]["1"]["future_body_break"] is True


def test_signed_response_and_mfe_mae_mirror_by_side() -> None:
    support = _outcome("G1", "support", _line("support", 1.0))
    resistance = _outcome("G1", "resistance", _line("resistance", 1.0))
    support_12 = support["horizons"]["12"]
    resistance_12 = resistance["horizons"]["12"]

    assert (
        support["horizons"]["1"]["signed_return"]
        == -resistance["horizons"]["1"]["signed_return"]
    )
    assert support_12["mfe"] == -resistance_12["mae"]
    assert support_12["mae"] == -resistance_12["mfe"]


def test_drift_adjustment_is_independent_of_event_values() -> None:
    line = _line("support", 1.0)
    neutral = g6._future_outcome(
        {
            "variant": "G1",
            "asset": "SYNTH",
            "side": "support",
            "index": 0,
            "line": line,
            "recovered": False,
        },
        _bars(),
        {horizon: 0.25 for horizon in g6.HORIZONS},
    )
    changed = g6._future_outcome(
        {
            "variant": "G1",
            "asset": "SYNTH",
            "side": "support",
            "index": 0,
            "line": line,
            "recovered": False,
        },
        _bars(),
        {horizon: 0.5 for horizon in g6.HORIZONS},
    )

    assert (
        neutral["horizons"]["1"]["signed_return"]
        == changed["horizons"]["1"]["signed_return"]
    )
    assert (
        neutral["horizons"]["1"]["signed_excess"]
        != changed["horizons"]["1"]["signed_excess"]
    )


def test_nonpositive_raw_projection_is_reported_as_undefined_log_distance() -> None:
    summary = g6._diagnostic_summary(
        [{"age": 1, "distance": None, "score": 2, "recovered": True}]
    )

    assert summary["selected_count"] == 1
    assert summary["undefined_log_distance_count"] == 1
    assert summary["projected_line_log_distance"]["count"] == 0


def test_response_summary_retains_censor_counts_and_no_composite_metric() -> None:
    result = g6._response_summary([_outcome("G1", "support", _line("support", 1.0))])
    summary = result["SYNTH:support"]["12"]

    assert summary["total_interactions"] == 1
    assert summary["uncensored_observation_count"] == 1
    assert summary["censored_count"] == 0
    assert "score" not in json.dumps(result)


def test_compact_report_has_no_raw_bar_or_prefix_dump() -> None:
    report_path = (
        Path(__file__).parents[3]
        / "artifacts/trendlines_v4/g6_frozen_utility_benchmark_v1/report.json"
    )
    if not report_path.exists():
        return
    report = json.loads(report_path.read_text())
    text = json.dumps(report, sort_keys=True)
    assert report["window_count"] == 15
    assert report["row_count"] == 4500
    assert report["schema_version"] == "g6_frozen_utility_benchmark_v1"
    assert report["report_id"] == g6._digest(
        {key: value for key, value in report.items() if key != "report_id"}
    )
    assert set(report["structural"]) == set(g6.VARIANTS)
    assert set(report["forward_response"]) == set(g6.VARIANTS)
    assert "HYPEUSDT:combined" in report["structural"]["G5"]
    assert all(
        set(report["forward_response"][variant]["combined:combined"])
        == {str(h) for h in g6.HORIZONS}
        for variant in g6.VARIANTS
    )
    assert '"bars"' not in text
    assert "prefix_length" not in text
    assert isinstance(report["report_id"], str)
