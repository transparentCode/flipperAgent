"""Compare global guarded replay with allowlist/veto guarded replay."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from libs.selection.regime_v2_trendline_guarded_replay import (
    GuardedReplayConfig,
    build_trendline_guarded_replay,
)


def build_guarded_replay_comparison(
    records: Iterable[Mapping[str, Any]],
    *,
    allow_asset_timeframes: tuple[str, ...],
    veto_asset_timeframes: tuple[str, ...] = (),
    source_path: str | None = None,
) -> dict[str, Any]:
    rows = [dict(record) for record in records]
    global_replay = build_trendline_guarded_replay(rows, source_path=source_path)
    guarded_replay = build_trendline_guarded_replay(
        rows,
        source_path=source_path,
        config=GuardedReplayConfig(
            allowed_asset_timeframes=allow_asset_timeframes,
            veto_asset_timeframes=veto_asset_timeframes,
        ),
    )
    return {
        "phase": "phase_tl_h22_guarded_replay_comparison",
        "summary": _comparison_summary(global_replay["summary"], guarded_replay["summary"]),
        "global_replay": global_replay,
        "allow_veto_replay": guarded_replay,
    }


def _comparison_summary(global_summary: Mapping[str, Any], guarded_summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "global_guarded_count": global_summary.get("guarded_count"),
        "allow_veto_guarded_count": guarded_summary.get("guarded_count"),
        "guarded_count_delta": _num(guarded_summary.get("guarded_count")) - _num(global_summary.get("guarded_count")),
        "global_loss_saved_rate": global_summary.get("loss_saved_rate"),
        "allow_veto_loss_saved_rate": guarded_summary.get("loss_saved_rate"),
        "loss_saved_rate_delta": _num(guarded_summary.get("loss_saved_rate")) - _num(global_summary.get("loss_saved_rate")),
        "global_missed_good_count": global_summary.get("missed_good_count"),
        "allow_veto_missed_good_count": guarded_summary.get("missed_good_count"),
        "missed_good_count_delta": _num(guarded_summary.get("missed_good_count")) - _num(global_summary.get("missed_good_count")),
        "global_net_lift_delta": global_summary.get("net_lift_delta"),
        "allow_veto_net_lift_delta": guarded_summary.get("net_lift_delta"),
        "net_lift_delta_improvement": _num(guarded_summary.get("net_lift_delta")) - _num(global_summary.get("net_lift_delta")),
        "global_replayed_avg_shadow_lift": global_summary.get("replayed_avg_shadow_lift"),
        "allow_veto_replayed_avg_shadow_lift": guarded_summary.get("replayed_avg_shadow_lift"),
        "replayed_avg_shadow_lift_improvement": _num(guarded_summary.get("replayed_avg_shadow_lift")) - _num(global_summary.get("replayed_avg_shadow_lift")),
        "allow_asset_timeframes": guarded_summary.get("allowed_asset_timeframes", []),
        "veto_asset_timeframes": guarded_summary.get("veto_asset_timeframes", []),
    }


def _num(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["build_guarded_replay_comparison"]
