"""Phase 8D runtime safety validator for RegimeV2.

This validator checks the current diagnostic/shadow posture without enabling or
changing runtime behavior. It is intentionally conservative: any live/paper
runtime flag that looks enabled is reported as a blocker.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json

import yaml


def build_runtime_safety_report(
    *,
    selection_config: Mapping[str, Any] | None = None,
    orchestration_payload: Mapping[str, Any] | None = None,
    stop_gate_payload: Mapping[str, Any] | None = None,
    expected_invalid_horizons: tuple[int, ...] = (3,),
) -> dict[str, Any]:
    """Build a Phase 8D runtime safety report."""
    selection = dict(selection_config or {})
    orchestration = _summary(orchestration_payload, preferred_key="report")
    stop_gate = _summary(stop_gate_payload)
    overlay_rows = _overlay_rows(selection)
    trend_rows = [row for row in overlay_rows if row.get("overlay") == "regime_v2_trend_gate"]
    pa_rows = [row for row in overlay_rows if row.get("overlay") == "regime_v2_pa_asset_guardrail"]

    blockers: list[str] = []
    warnings: list[str] = []

    live_trend_enabled = [row for row in trend_rows if bool(row.get("enabled"))]
    if live_trend_enabled:
        blockers.append("live_trend_gate_enabled")
    transition_runtime = int(orchestration.get("transition_runtime_enabled_count") or 0)
    if transition_runtime != 0:
        blockers.append("transition_runtime_enabled")
    postures = [str(item) for item in orchestration.get("transition_postures", [])]
    if orchestration and "frozen_diagnostic" not in postures:
        blockers.append("transition_posture_not_frozen")
    if bool(stop_gate.get("promotion_ready", False)):
        blockers.append("transition_stop_gate_promotion_ready")

    pa_enabled = [row for row in pa_rows if bool(row.get("paper_enabled")) or bool(row.get("paper_runtime_enabled"))]
    if pa_enabled:
        blockers.append("pa_paper_or_runtime_enabled")
    invalid_horizon_issues = _invalid_horizon_issues(pa_rows, expected_invalid_horizons)
    if invalid_horizon_issues:
        blockers.append("invalid_horizon_scope_not_preserved")
    if not orchestration:
        warnings.append("orchestration_payload_missing")
    if not stop_gate:
        warnings.append("stop_gate_payload_missing")
    if not trend_rows:
        warnings.append("trend_gate_config_missing")
    if not pa_rows:
        warnings.append("pa_guardrail_config_missing")

    return {
        "phase": "phase_8d_runtime_safety_validator",
        "summary": {
            "safe": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "trend_gate_config_count": len(trend_rows),
            "trend_gate_live_enabled_count": len(live_trend_enabled),
            "trend_gate_shadow_enabled_count": sum(1 for row in trend_rows if bool(row.get("shadow_enabled"))),
            "pa_guardrail_config_count": len(pa_rows),
            "pa_guardrail_enabled_count": len(pa_enabled),
            "transition_runtime_enabled_count": transition_runtime,
            "transition_postures": postures,
            "transition_stop_gate_decision": stop_gate.get("decision"),
            "transition_stop_gate_promotion_ready": bool(stop_gate.get("promotion_ready", False)),
            "invalid_horizon_issues": invalid_horizon_issues,
            "runtime_posture": "safe_shadow_diagnostic" if not blockers else "blocked_runtime_safety",
        },
        "overlay_rows": overlay_rows,
    }


def run_runtime_safety_report(
    *,
    selection_config_path: str | Path = "configs/selection.yaml",
    orchestration_json_path: str | Path = "research/regime_v2_phase8a_playbook_orchestration_gate.json",
    stop_gate_json_path: str | Path = "research/regime_v2_phase7z_transition_stop_gate.json",
) -> dict[str, Any]:
    """Load repo artifacts and build the runtime safety report."""
    selection = _read_yaml(selection_config_path)
    orchestration = _read_json(orchestration_json_path)
    stop_gate = _read_json(stop_gate_json_path)
    return build_runtime_safety_report(
        selection_config=selection,
        orchestration_payload=orchestration,
        stop_gate_payload=stop_gate,
    )


def render_runtime_safety_markdown(report: Mapping[str, Any]) -> str:
    """Render the runtime safety report as Markdown."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 8D Runtime Safety Validator",
        "",
        f"- Safe: {summary.get('safe')}",
        f"- Runtime posture: {summary.get('runtime_posture')}",
        f"- Blockers: {summary.get('blockers')}",
        f"- Warnings: {summary.get('warnings')}",
        f"- Trend gate live-enabled count: {summary.get('trend_gate_live_enabled_count')}",
        f"- Trend gate shadow-enabled count: {summary.get('trend_gate_shadow_enabled_count')}",
        f"- PA guardrail enabled count: {summary.get('pa_guardrail_enabled_count')}",
        f"- Transition runtime-enabled count: {summary.get('transition_runtime_enabled_count')}",
        f"- Transition postures: {summary.get('transition_postures')}",
        f"- Transition stop-gate decision: {summary.get('transition_stop_gate_decision')}",
        f"- Invalid horizon issues: {summary.get('invalid_horizon_issues')}",
        "",
        "## Overlay rows",
        "",
        "| Asset | Timeframe | Overlay | Enabled | Shadow | Paper | Runtime |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in report.get("overlay_rows", []):
        lines.append(
            "| {asset} | {timeframe} | {overlay} | {enabled} | {shadow_enabled} | {paper_enabled} | {paper_runtime_enabled} |".format(
                asset=row.get("asset"),
                timeframe=row.get("timeframe"),
                overlay=row.get("overlay"),
                enabled=row.get("enabled"),
                shadow_enabled=row.get("shadow_enabled"),
                paper_enabled=row.get("paper_enabled"),
                paper_runtime_enabled=row.get("paper_runtime_enabled"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _overlay_rows(selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    assets = dict(dict(selection.get("selection", {})).get("assets", {}))
    for asset, asset_cfg in assets.items():
        timeframes = dict(dict(asset_cfg or {}).get("timeframes", {}))
        for timeframe, tf_cfg in timeframes.items():
            overlays = dict(dict(tf_cfg or {}).get("overlays", {}))
            for overlay_name, overlay_cfg in overlays.items():
                overlay = dict(overlay_cfg or {})
                long_horizon = dict(overlay.get("long_horizon_candidate", {}) or {})
                rows.append(
                    {
                        "asset": str(asset),
                        "timeframe": str(timeframe),
                        "overlay": str(overlay_name),
                        "enabled": bool(overlay.get("enabled", False)),
                        "shadow_enabled": bool(overlay.get("shadow_enabled", False)),
                        "shadow_persist_enabled": bool(overlay.get("shadow_persist_enabled", False)),
                        "paper_enabled": bool(overlay.get("paper_enabled", False)),
                        "paper_runtime_enabled": bool(overlay.get("paper_runtime_enabled", False)) or bool(long_horizon.get("paper_runtime_enabled", False)),
                        "candidate_enabled": bool(long_horizon.get("candidate_enabled", False)),
                        "valid_horizons_bars": tuple(int(x) for x in long_horizon.get("valid_horizons_bars", []) or []),
                        "invalid_horizons_bars": tuple(int(x) for x in long_horizon.get("invalid_horizons_bars", []) or []),
                    }
                )
    return rows


def _invalid_horizon_issues(pa_rows: list[Mapping[str, Any]], expected_invalid: tuple[int, ...]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    expected = set(int(x) for x in expected_invalid)
    for row in pa_rows:
        invalid = set(int(x) for x in row.get("invalid_horizons_bars", ()) or ())
        valid = set(int(x) for x in row.get("valid_horizons_bars", ()) or ())
        if not expected.issubset(invalid):
            issues.append({"asset": row.get("asset"), "timeframe": row.get("timeframe"), "issue": "expected_invalid_missing", "expected": sorted(expected), "actual_invalid": sorted(invalid)})
        if expected.intersection(valid):
            issues.append({"asset": row.get("asset"), "timeframe": row.get("timeframe"), "issue": "invalid_horizon_marked_valid", "expected_invalid": sorted(expected), "actual_valid": sorted(valid)})
    return issues


def _summary(payload: Mapping[str, Any] | None, *, preferred_key: str | None = None) -> dict[str, Any]:
    if not payload:
        return {}
    if preferred_key and preferred_key in payload:
        return dict(dict(payload.get(preferred_key, {})).get("summary", {}))
    return dict(payload.get("summary", {}))


def _read_json(path: str | Path) -> dict[str, Any] | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


def _read_yaml(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    return yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}


__all__ = ["build_runtime_safety_report", "render_runtime_safety_markdown", "run_runtime_safety_report"]
