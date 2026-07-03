"""Phase 7Z transition stop-gate.

This module consolidates Phase 7W/7Y evidence and decides whether transition
micro-states should be promoted, frozen as diagnostics, or sent to a later
feature-enrichment branch. It does not add or change trading behavior.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def build_transition_stop_gate_report(
    robust_payload: Mapping[str, Any],
    context_payload: Mapping[str, Any],
    *,
    min_support_ready_assets: int = 2,
    require_context_tag: bool = True,
    require_runtime_disabled: bool = True,
) -> dict[str, Any]:
    """Build a promotion/stop-gate decision from 7W and 7Y evidence."""
    robust_matrix = dict(robust_payload.get("matrix_report", robust_payload))
    context_matrix = dict(context_payload.get("matrix_report", context_payload))
    robust_summary = dict(robust_matrix.get("summary", {}))
    context_summary = dict(context_matrix.get("summary", {}))
    robust_variants = [dict(row) for row in robust_matrix.get("variants", [])]
    context_variants = [dict(row) for row in context_matrix.get("variants", [])]

    runtime_enabled = int(robust_summary.get("runtime_enabled_count") or 0)
    support_ready_assets = int(robust_summary.get("support_ready_asset_count") or 0)
    supported_windows = int(robust_summary.get("supported_window_count") or 0)
    supported_better = int(robust_summary.get("supported_breakout_better_count") or 0)
    context_tag_count = int(context_summary.get("candidate_tag_count") or 0)
    mixed_windows = int(context_summary.get("mixed_window_count") or 0)

    blockers = []
    if require_runtime_disabled and runtime_enabled != 0:
        blockers.append("runtime_enabled_not_zero")
    if support_ready_assets < int(min_support_ready_assets):
        blockers.append("insufficient_support_ready_assets")
    if supported_windows <= 0 or supported_better < supported_windows:
        blockers.append("not_all_supported_windows_breakout_better")
    if require_context_tag and context_tag_count <= 0 and mixed_windows > 0:
        blockers.append("no_policy_safe_context_tag_for_mixed_failures")
    if _has_mixed_assets(robust_variants):
        blockers.append("asset_level_mixed_robustness")

    decision = "freeze_transition_micro_states_diagnostic" if blockers else "candidate_ready_for_separate_enrichment_review"
    return {
        "phase": "phase_7z_transition_stop_gate",
        "summary": {
            "decision": decision,
            "promotion_ready": not blockers,
            "runtime_enabled_count": runtime_enabled,
            "support_ready_asset_count": support_ready_assets,
            "supported_window_count": supported_windows,
            "supported_breakout_better_count": supported_better,
            "mixed_window_count": mixed_windows,
            "candidate_context_tag_count": context_tag_count,
            "blockers": blockers,
            "next_allowed_paths": _next_paths(blockers),
            "criteria": {
                "min_support_ready_assets": int(min_support_ready_assets),
                "require_context_tag": bool(require_context_tag),
                "require_runtime_disabled": bool(require_runtime_disabled),
            },
        },
        "asset_gate": _asset_gate(robust_variants, context_variants),
        "evidence": {
            "robust_summary": robust_summary,
            "context_summary": context_summary,
        },
    }


def render_transition_stop_gate_markdown(report: Mapping[str, Any]) -> str:
    """Render the Phase 7Z stop-gate report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7Z Transition Stop-Gate",
        "",
        f"- Decision: {summary.get('decision')}",
        f"- Promotion ready: {summary.get('promotion_ready')}",
        f"- Runtime-enabled count: {summary.get('runtime_enabled_count')}",
        f"- Support-ready assets: {summary.get('support_ready_asset_count')}",
        f"- Supported windows: {summary.get('supported_breakout_better_count')}/{summary.get('supported_window_count')}",
        f"- Mixed windows: {summary.get('mixed_window_count')}",
        f"- Context tags: {summary.get('candidate_context_tag_count')}",
        f"- Blockers: {summary.get('blockers')}",
        "",
        "## Asset gate",
        "",
        "| Asset | Robust status | Context status | Decision | Key blocker |",
        "|---|---|---|---|---|",
    ]
    for row in report.get("asset_gate", []):
        lines.append(
            "| {asset} | {robust_status} | {context_status} | {asset_decision} | {key_blocker} |".format(
                asset=row.get("asset"),
                robust_status=row.get("robust_status"),
                context_status=row.get("context_status"),
                asset_decision=row.get("asset_decision"),
                key_blocker=row.get("key_blocker"),
            )
        )
    lines.extend([
        "",
        "## Next allowed paths",
        "",
    ])
    for item in summary.get("next_allowed_paths", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _asset_gate(robust_rows: Sequence[Mapping[str, Any]], context_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    context_by_asset = {str(row.get("asset")): row for row in context_rows}
    out = []
    for robust in robust_rows:
        asset = str(robust.get("asset"))
        context = dict(context_by_asset.get(asset, {}))
        support_ready = bool(robust.get("support_ready"))
        mixed_count = int(context.get("mixed_window_count") or 0)
        tag_count = int(context.get("candidate_tag_count") or 0)
        if support_ready and (mixed_count == 0 or tag_count > 0):
            status = "diagnostic_watch"
            blocker = "tail_or_support_review_required"
        elif support_ready:
            status = "diagnostic_watch"
            blocker = "support_ready_but_no_context_tag"
        else:
            status = "blocked"
            blocker = "robustness_mixed_or_support_thin"
        out.append(
            {
                "asset": asset,
                "robust_status": "support_ready" if support_ready else "not_support_ready",
                "context_status": "context_tag_found" if tag_count > 0 else ("no_mixed_failures" if mixed_count == 0 else "no_context_tag"),
                "asset_decision": status,
                "key_blocker": blocker,
                "supported_window_count": robust.get("supported_window_count"),
                "supported_breakout_better_count": robust.get("supported_breakout_better_count"),
                "mixed_window_count": mixed_count,
                "candidate_tag_count": tag_count,
            }
        )
    return out


def _has_mixed_assets(rows: Sequence[Mapping[str, Any]]) -> bool:
    return any(str(row.get("recommendation")) == "micro_state_split_window_mixed" or bool(row.get("support_ready")) is False for row in rows)


def _next_paths(blockers: Sequence[str]) -> list[str]:
    paths = [
        "freeze_transition_micro_states_as_diagnostic_only",
        "return_to_broader_playbook_orchestration",
    ]
    if "no_policy_safe_context_tag_for_mixed_failures" in blockers:
        paths.append("optional_later_feature_enrichment_branch")
    if "insufficient_support_ready_assets" in blockers:
        paths.append("collect_more_assets_or_longer_history_before_promotion")
    return paths


__all__ = ["build_transition_stop_gate_report", "render_transition_stop_gate_markdown"]
