"""Disabled long-horizon candidate validation for PA paper guardrail.

Phase 6Y makes the long-horizon candidate explicit without enabling runtime
paper mode. This module validates the config descriptor and horizon report.
"""

from __future__ import annotations

from typing import Any, Mapping

_EXPECTED_ASSET = "BNBUSDT"
_EXPECTED_TIMEFRAME = "1h"
_EXPECTED_MODEL = "PriceAction"
_EXPECTED_DIRECTION = 1
_EXPECTED_RULE = "rolling_avg_below_002_3"
_EXPECTED_VALID_HORIZONS = (6, 12, 24)
_EXPECTED_INVALID_HORIZONS = (3,)
_EXPECTED_THRESHOLD = -0.002
_EXPECTED_WINDOW = 3


def build_pa_paper_horizon_candidate_report(
    selection_config: Mapping[str, Any],
    horizon_report: Mapping[str, Any] | None = None,
    *,
    asset: str = _EXPECTED_ASSET,
    timeframe: str = _EXPECTED_TIMEFRAME,
) -> dict[str, Any]:
    """Validate that the long-horizon PA candidate is explicit and disabled."""
    overlay = _overlay_config(selection_config, asset=asset, timeframe=timeframe)
    live_gate = _trend_gate_config(selection_config, asset=asset, timeframe=timeframe)
    descriptor = dict(overlay.get("long_horizon_candidate") or {})
    violations = []
    warnings = []

    _expect_false(violations, overlay, "paper_enabled", "paper_runtime_enabled")
    _expect_false(violations, overlay, "paper_log_enabled", "paper_log_enabled")
    _expect_false(violations, overlay, "paper_persist_enabled", "paper_persist_enabled")
    _expect_false(violations, live_gate, "enabled", "live_gate_enabled")
    _expect_false(violations, descriptor, "candidate_enabled", "descriptor_candidate_enabled")
    _expect_false(violations, descriptor, "paper_runtime_enabled", "descriptor_paper_runtime_enabled")

    _expect_equal(violations, overlay.get("model_name"), _EXPECTED_MODEL, "target_model_mismatch")
    _expect_equal(violations, overlay.get("asset"), asset, "target_asset_mismatch")
    _expect_equal(violations, str(overlay.get("timeframe")), str(timeframe), "target_timeframe_mismatch")
    _expect_equal(violations, int(overlay.get("direction") or 0), _EXPECTED_DIRECTION, "target_direction_mismatch")

    _expect_equal(violations, descriptor.get("rule_name"), _EXPECTED_RULE, "rule_name_mismatch")
    _expect_equal(violations, int(descriptor.get("window") or 0), _EXPECTED_WINDOW, "rule_window_mismatch")
    _expect_equal(violations, float(descriptor.get("threshold") or 0.0), _EXPECTED_THRESHOLD, "rule_threshold_mismatch")
    _expect_list_equal(violations, descriptor.get("valid_horizons_bars"), _EXPECTED_VALID_HORIZONS, "valid_horizons_mismatch")
    _expect_list_equal(violations, descriptor.get("invalid_horizons_bars"), _EXPECTED_INVALID_HORIZONS, "invalid_horizons_mismatch")

    source_report = descriptor.get("source_report")
    if not source_report:
        warnings.append("missing_source_report_path")

    horizon_summary = _horizon_summary(horizon_report or {})
    if horizon_report:
        if horizon_summary.get("recommendation") != "long_horizon_paper_candidate":
            violations.append("horizon_report_not_candidate")
        best = dict(horizon_summary.get("best_variant") or {})
        _expect_equal(violations, best.get("name"), _EXPECTED_RULE, "horizon_best_variant_mismatch")
        _expect_equal(violations, bool(horizon_summary.get("long_horizon_candidate")), True, "horizon_candidate_false")
        if int(best.get("long_lost_avoided_loss_count") or 0) != 0:
            violations.append("long_horizon_lost_avoided_losses")
        if int(best.get("short_failed_cell_count") or 0) <= 0:
            warnings.append("short_horizon_not_marked_invalid")

    safe = not violations
    return {
        "phase": "phase_6y_pa_paper_long_horizon_candidate",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "target_model": overlay.get("model_name"),
            "target_direction": overlay.get("direction"),
            "rule_name": descriptor.get("rule_name"),
            "valid_horizons_bars": list(descriptor.get("valid_horizons_bars") or []),
            "invalid_horizons_bars": list(descriptor.get("invalid_horizons_bars") or []),
            "candidate_enabled": bool(descriptor.get("candidate_enabled", False)),
            "paper_runtime_enabled": bool(overlay.get("paper_enabled", False)),
            "paper_log_enabled": bool(overlay.get("paper_log_enabled", False)),
            "paper_persist_enabled": bool(overlay.get("paper_persist_enabled", False)),
            "live_gate_enabled": bool(live_gate.get("enabled", False)),
            "source_report": source_report,
            "horizon_report_recommendation": horizon_summary.get("recommendation"),
            "safe": safe,
            "violation_count": len(violations),
            "warning_count": len(warnings),
            "recommendation": "metadata_candidate_disabled_ok" if safe else "fix_candidate_config_before_any_paper_use",
        },
        "descriptor": descriptor,
        "horizon_summary": horizon_summary,
        "violations": violations,
        "warnings": warnings,
    }


def render_pa_paper_horizon_candidate_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for Phase 6Y candidate safety report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6Y PA Long-Horizon Candidate",
        "",
        "## Summary",
        "",
        f"- Pair: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Target: {summary.get('target_model')} direction {summary.get('target_direction')}",
        f"- Rule: {summary.get('rule_name')}",
        f"- Valid horizons: {summary.get('valid_horizons_bars')}",
        f"- Invalid horizons: {summary.get('invalid_horizons_bars')}",
        f"- Candidate enabled: {summary.get('candidate_enabled')}",
        f"- Paper runtime enabled: {summary.get('paper_runtime_enabled')}",
        f"- Live gate enabled: {summary.get('live_gate_enabled')}",
        f"- Horizon report recommendation: {summary.get('horizon_report_recommendation')}",
        f"- Safe: {summary.get('safe')}",
        f"- Recommendation: {summary.get('recommendation')}",
        "",
        "## Violations",
        "",
    ]
    violations = list(report.get("violations", []))
    lines.extend([f"- {item}" for item in violations] or ["- none"])
    lines.extend(["", "## Warnings", ""])
    warnings = list(report.get("warnings", []))
    lines.extend([f"- {item}" for item in warnings] or ["- none"])
    lines.append("")
    return "\n".join(lines)


def _overlay_config(config: Mapping[str, Any], *, asset: str, timeframe: str) -> dict[str, Any]:
    return dict(_tf_config(config, asset=asset, timeframe=timeframe).get("overlays", {}).get("regime_v2_pa_asset_guardrail", {}))


def _trend_gate_config(config: Mapping[str, Any], *, asset: str, timeframe: str) -> dict[str, Any]:
    return dict(_tf_config(config, asset=asset, timeframe=timeframe).get("overlays", {}).get("regime_v2_trend_gate", {}))


def _tf_config(config: Mapping[str, Any], *, asset: str, timeframe: str) -> dict[str, Any]:
    assets = dict(dict(config.get("selection", {})).get("assets", {}))
    asset_cfg = dict(assets.get(asset, {}))
    tfs = dict(asset_cfg.get("timeframes", {}))
    return dict(tfs.get(timeframe) or tfs.get("default") or {})


def _horizon_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return dict(report.get("summary") or {})


def _expect_false(violations: list[str], mapping: Mapping[str, Any], key: str, name: str) -> None:
    if bool(mapping.get(key, False)):
        violations.append(name)


def _expect_equal(violations: list[str], actual: Any, expected: Any, name: str) -> None:
    if actual != expected:
        violations.append(name)


def _expect_list_equal(violations: list[str], actual: Any, expected: tuple[int, ...], name: str) -> None:
    values = tuple(int(value) for value in (actual or ()))
    if values != tuple(expected):
        violations.append(name)


__all__ = ["build_pa_paper_horizon_candidate_report", "render_pa_paper_horizon_candidate_markdown"]
