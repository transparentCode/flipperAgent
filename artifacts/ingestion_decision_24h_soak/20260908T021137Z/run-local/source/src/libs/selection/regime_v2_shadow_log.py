"""Durable JSONL logging for RegimeV2 shadow-selection decisions.

The logger is intentionally tiny and disabled by default. It is called from the
selection path only after a shadow payload has already been computed. When the
persistence flag is off, it is an exact no-op; when enabled, it appends one JSON
object per selection event so Phase 5B/5C reports can replay shadow drift.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

_DEFAULT_SHADOW_LOG_PATH = "logs/regime_v2_shadow_decisions.jsonl"


def persist_regime_v2_shadow_decision(
    payload: dict[str, Any],
    *,
    asset: str,
    timeframe: str,
    timestamp: float,
    config: dict[str, Any],
    selected_count: int,
) -> Path | None:
    """Append one RegimeV2 shadow decision event to JSONL when enabled.

    Returns the written path when a record is persisted, otherwise ``None``.
    The function deliberately raises I/O errors to the caller so runtime code can
    decide whether to log/suppress them. ``SelectionLayer`` suppresses them to
    preserve live selection behavior.
    """
    if not bool(config.get("shadow_persist_enabled", False)):
        return None

    path = Path(str(config.get("shadow_persist_path") or _DEFAULT_SHADOW_LOG_PATH)).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = _shadow_decision_record(
        payload,
        asset=asset,
        timeframe=timeframe,
        timestamp=timestamp,
        selected_count=selected_count,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return path


def _shadow_decision_record(
    payload: dict[str, Any],
    *,
    asset: str,
    timeframe: str,
    timestamp: float,
    selected_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "regime_v2_shadow_decision",
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "asset": asset,
        "timeframe": timeframe,
        "timestamp": float(timestamp),
        "selected_count": int(selected_count),
        "baseline_selected_model": payload.get("baseline_selected_model"),
        "shadow_selected_model": payload.get("shadow_selected_model"),
        "baseline_selected_direction": payload.get("baseline_selected_direction"),
        "shadow_selected_direction": payload.get("shadow_selected_direction"),
        "baseline_edge_score": payload.get("baseline_edge_score"),
        "shadow_edge_score": payload.get("shadow_edge_score"),
        "baseline_conviction": payload.get("baseline_conviction"),
        "shadow_conviction": payload.get("shadow_conviction"),
        "selection_changed": bool(payload.get("selection_changed", False)),
        "reason": payload.get("reason"),
        "gate_active": bool(payload.get("gate_active", False)),
        "gate_reason": payload.get("gate_reason"),
        "regime_side": payload.get("regime_side"),
        "active_playbooks": list(payload.get("active_playbooks", [])),
        "shadow_subset_name": payload.get("shadow_subset_name"),
        "shadow_subset_only": bool(payload.get("shadow_subset_only", False)),
        "include_non_target_models": bool(payload.get("include_non_target_models", True)),
        "baseline_selection_score": payload.get("baseline_selection_score"),
        "shadow_selection_score": payload.get("shadow_selection_score"),
        "edge_delta": payload.get("edge_delta"),
        "allow_trend_following": payload.get("allow_trend_following"),
        "allow_breakout": payload.get("allow_breakout"),
        "allow_mean_reversion": payload.get("allow_mean_reversion"),
        "trend_score": payload.get("trend_score"),
        "breakout_score": payload.get("breakout_score"),
        "mean_reversion_score": payload.get("mean_reversion_score"),
        "min_trend_score": payload.get("min_trend_score"),
        "min_breakout_score": payload.get("min_breakout_score"),
        "min_mean_reversion_score": payload.get("min_mean_reversion_score"),
        "min_confidence": payload.get("min_confidence"),
        "confidence": payload.get("confidence"),
        "uncertainty": payload.get("uncertainty"),
        "baseline_candidate_count": payload.get("baseline_candidate_count"),
        "shadow_candidate_count": payload.get("shadow_candidate_count"),
        "shadow_selected_count": payload.get("shadow_selected_count"),
        "target_candidate_count": payload.get("target_candidate_count"),
        "target_models": list(payload.get("target_models", [])),
        "aligned_target_models": list(payload.get("aligned_target_models", [])),
        "conflict_target_models": list(payload.get("conflict_target_models", [])),
        "candidate_playbooks": dict(payload.get("candidate_playbooks", {})),
        **_trendline_record_fields(payload),
        "payload": dict(payload),
    }


def _trendline_record_fields(payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("trendline_context")
    if not isinstance(context, dict):
        return {"trendline_context": {}}
    keys = (
        "trendline_valid",
        "trendline_interaction",
        "trendline_structure_state",
        "trendline_market_position_state",
        "trendline_has_closed_channel",
        "trendline_inside_channel",
        "trendline_above_channel",
        "trendline_below_channel",
        "trendline_near_support",
        "trendline_near_resistance",
        "trendline_mid_channel_noise",
        "trendline_hull_width_atr",
        "trendline_hull_position",
        "trendline_channel_compression_score",
        "trendline_support_quality_score",
        "trendline_resistance_quality_score",
        "trendline_mean_normalized_quality",
        "trendline_history_count",
        "trendline_interaction_transition",
        "trendline_market_position_transition",
        "trendline_ray_persistence_bias",
        "trendline_hull_convergence_rate",
        "trendline_hull_expansion_rate",
        "trendline_risk_context",
        "trendline_confidence_annotation",
        "trendline_annotation_reason",
        "trendline_no_trade_warning",
        "trendline_mid_channel_noise_warning",
        "trendline_low_quality_warning",
        "trendline_reversal_context",
        "trendline_breakout_context",
        "trendline_breakdown_context",
        "trendline_pressure_watch",
        "trendline_continuation_watch",
        "trendline_breakout_watch_high_quality",
        "trendline_breakout_watch_positive_persistence",
        "trendline_breakout_watch_hull_expansion",
        "trendline_breakout_watch_clean_context",
        "trendline_breakout_watch_confirmed_interaction",
        "trendline_breakout_watch_strict_score",
        "trendline_breakout_watch_strict_context",
    )
    out = {key: context.get(key) for key in keys if key in context}
    out["trendline_context"] = dict(context)
    return out


__all__ = ["persist_regime_v2_shadow_decision"]
