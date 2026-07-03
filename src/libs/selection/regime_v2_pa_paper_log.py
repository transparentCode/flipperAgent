"""JSONL logging for the PriceAction asset paper guardrail."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

_DEFAULT_PATH = "logs/regime_v2_pa_asset_paper_decisions.jsonl"


def persist_pa_paper_decision(
    payload: dict[str, Any],
    *,
    asset: str,
    timeframe: str,
    timestamp: float,
    config: dict[str, Any],
    selected_count: int,
) -> Path | None:
    """Write one paper-only decision when persistence is explicitly enabled."""
    if not bool(config.get("paper_persist_enabled", False)):
        return None
    path = Path(str(config.get("paper_persist_path") or _DEFAULT_PATH)).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "record_type": "regime_v2_pa_asset_paper_decision",
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "asset": asset,
        "timeframe": timeframe,
        "timestamp": float(timestamp),
        "selected_count": int(selected_count),
        "paper_active": bool(payload.get("paper_active", False)),
        "paper_reason": payload.get("paper_reason"),
        "target_model": payload.get("target_model"),
        "target_asset": payload.get("target_asset"),
        "target_timeframe": payload.get("target_timeframe"),
        "target_direction": payload.get("target_direction"),
        "suppressed_count": payload.get("suppressed_count"),
        "suppressed_models": list(payload.get("suppressed_models", [])),
        "baseline_selected_model": payload.get("baseline_selected_model"),
        "paper_selected_model": payload.get("paper_selected_model"),
        "baseline_selected_direction": payload.get("baseline_selected_direction"),
        "paper_selected_direction": payload.get("paper_selected_direction"),
        "baseline_edge_score": payload.get("baseline_edge_score"),
        "paper_edge_score": payload.get("paper_edge_score"),
        "baseline_conviction": payload.get("baseline_conviction"),
        "paper_conviction": payload.get("paper_conviction"),
        "baseline_selection_score": payload.get("baseline_selection_score"),
        "paper_selection_score": payload.get("paper_selection_score"),
        "edge_delta": payload.get("edge_delta"),
        "selection_changed": bool(payload.get("selection_changed", False)),
        "paper_selected_count": payload.get("paper_selected_count"),
        "candidate_count": payload.get("candidate_count"),
        "candidate_snapshot_schema_version": payload.get("candidate_snapshot_schema_version"),
        "baseline_ranked_candidates": list(payload.get("baseline_ranked_candidates", [])),
        "paper_ranked_candidates": list(payload.get("paper_ranked_candidates", [])),
        "payload": dict(payload),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return path


__all__ = ["persist_pa_paper_decision"]
