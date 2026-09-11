"""Phase 8B orchestration posture wrapper for RegimeV2 shadow reports.

This keeps the older Phase 5 shadow replay report intact and adds a read-only
Phase 8A orchestration posture section. No routing or selection behavior is
changed by this module.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping
import json

from libs.selection.regime_v2_shadow_report import (
    render_regime_v2_shadow_report_markdown,
    run_regime_v2_shadow_report,
)


def build_orchestration_shadow_report(
    shadow_report: Mapping[str, Any],
    orchestration_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine a shadow replay report with 8A orchestration posture metadata."""
    shadow = dict(shadow_report)
    orchestration = _orchestration_summary(orchestration_payload)
    shadow_summary = dict(shadow.get("summary", {}))
    return {
        "phase": "phase_8b_orchestration_shadow_report",
        "summary": {
            "shadow_records_after_filter": shadow_summary.get("records_after_filter", 0),
            "shadow_selection_changed_count": shadow_summary.get("selection_changed_count", 0),
            "shadow_gate_active_count": shadow_summary.get("gate_active_count", 0),
            "orchestration_attached": bool(orchestration_payload),
            "orchestration_row_count": orchestration.get("row_count"),
            "orchestration_routeable_count": orchestration.get("routeable_count"),
            "transition_postures": orchestration.get("transition_postures", []),
            "transition_runtime_enabled_count": orchestration.get("transition_runtime_enabled_count", 0),
            "transition_promotion_ready_count": orchestration.get("transition_promotion_ready_count", 0),
            "runtime_action": _runtime_action(orchestration),
            "recommended_next_step": orchestration.get("recommended_next_step") or "generate_or_attach_phase8a_orchestration_gate",
        },
        "shadow_report": shadow,
        "orchestration_summary": orchestration,
    }


def run_orchestration_shadow_report(
    shadow_log_path: str | Path,
    *,
    orchestration_json_path: str | Path | None = None,
    asset: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Load shadow replay and 8A posture artifacts, then build the 8B report."""
    shadow = run_regime_v2_shadow_report(shadow_log_path, asset=asset, timeframe=timeframe)
    orchestration = _read_json(orchestration_json_path)
    return build_orchestration_shadow_report(shadow, orchestration)


def render_orchestration_shadow_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a Markdown report with 8B posture followed by the base shadow report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 8B Orchestration Shadow Report",
        "",
        "## Orchestration posture",
        "",
        f"- Orchestration attached: {summary.get('orchestration_attached')}",
        f"- Orchestration rows: {summary.get('orchestration_row_count')}",
        f"- Routeable base-state rows: {summary.get('orchestration_routeable_count')}",
        f"- Transition postures: {summary.get('transition_postures')}",
        f"- Transition runtime-enabled rows: {summary.get('transition_runtime_enabled_count')}",
        f"- Transition promotion-ready count: {summary.get('transition_promotion_ready_count')}",
        f"- Runtime action: {summary.get('runtime_action')}",
        f"- Recommended next step: {summary.get('recommended_next_step')}",
        "",
        "## Shadow replay summary",
        "",
        f"- Records after filter: {summary.get('shadow_records_after_filter')}",
        f"- Selection changed: {summary.get('shadow_selection_changed_count')}",
        f"- Gate active: {summary.get('shadow_gate_active_count')}",
        "",
    ]
    base_md = render_regime_v2_shadow_report_markdown(dict(report.get("shadow_report", {})))
    lines.append(base_md)
    return "\n".join(lines)


def _orchestration_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    if "report" in payload:
        return dict(dict(payload.get("report", {})).get("summary", {}))
    if "summary" in payload:
        return dict(payload.get("summary", {}))
    return dict(payload.get("matrix_report", {}).get("summary", {}))


def _runtime_action(orchestration: Mapping[str, Any]) -> str:
    if not orchestration:
        return "orchestration_gate_missing"
    if int(orchestration.get("transition_runtime_enabled_count") or 0) > 0:
        return "unsafe_transition_runtime_detected"
    postures = [str(item) for item in orchestration.get("transition_postures", [])]
    if "frozen_diagnostic" in postures:
        return "base_shadow_report_with_transition_diagnostics_frozen"
    return "base_shadow_report_only"


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


def _counts(values: list[Any]) -> dict[str, int]:
    return dict(Counter(str(value) for value in values).most_common())


__all__ = [
    "build_orchestration_shadow_report",
    "render_orchestration_shadow_report_markdown",
    "run_orchestration_shadow_report",
]
