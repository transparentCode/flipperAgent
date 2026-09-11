"""Safety validation for the PA paper rollout switch.

This module validates config state before runtime paper observation. It is
intentionally conservative: live gates must remain disabled, PA paper can only be
active for BNBUSDT|1h, and paper persistence must stay separate from the main
RegimeV2 shadow log.
"""

from __future__ import annotations

from typing import Any, Mapping

_EXPECTED_ASSET = "BNBUSDT"
_EXPECTED_TIMEFRAME = "1h"
_EXPECTED_MODEL = "PriceAction"
_EXPECTED_DIRECTION = 1
_MAIN_SHADOW_LOG = "logs/regime_v2_shadow_decisions.jsonl"
_DEFAULT_PAPER_LOG = "logs/regime_v2_pa_asset_paper_decisions.jsonl"


def validate_pa_paper_rollout_config(
    selection_config: Mapping[str, Any],
    *,
    expected_asset: str = _EXPECTED_ASSET,
    expected_timeframe: str = _EXPECTED_TIMEFRAME,
    require_enabled: bool = False,
) -> dict[str, Any]:
    """Validate that PA paper rollout config is safe.

    ``require_enabled=False`` validates the default disabled config as safe.
    ``require_enabled=True`` is for pre-rollout checks and requires the expected
    pair to have paper observation and persistence enabled.
    """
    expected_asset = expected_asset.upper()
    expected_pair = (expected_asset, str(expected_timeframe))
    rows = _iter_timeframe_configs(selection_config)
    violations: list[dict[str, Any]] = []
    enabled_pairs: list[str] = []
    persist_enabled_pairs: list[str] = []
    live_gate_enabled_pairs: list[str] = []
    expected_guardrail: dict[str, Any] | None = None

    for asset, timeframe, tf_cfg in rows:
        overlays = tf_cfg.get("overlays", {}) if isinstance(tf_cfg, dict) else {}
        overlays = overlays if isinstance(overlays, dict) else {}
        gate = overlays.get("regime_v2_trend_gate", {})
        gate = gate if isinstance(gate, dict) else {}
        guardrail = overlays.get("regime_v2_pa_asset_guardrail", {})
        guardrail = guardrail if isinstance(guardrail, dict) else {}
        pair = (asset, timeframe)
        pair_key = f"{asset}|{timeframe}"

        if bool(gate.get("enabled", False)):
            live_gate_enabled_pairs.append(pair_key)
            violations.append(_violation(pair_key, "live_gate_enabled", "RegimeV2 live gate must remain disabled."))

        paper_enabled = bool(guardrail.get("paper_enabled", False))
        paper_persist_enabled = bool(guardrail.get("paper_persist_enabled", False))
        paper_log_enabled = bool(guardrail.get("paper_log_enabled", False))
        if paper_enabled:
            enabled_pairs.append(pair_key)
        if paper_persist_enabled:
            persist_enabled_pairs.append(pair_key)

        if pair == expected_pair:
            expected_guardrail = dict(guardrail)
            _validate_expected_guardrail(guardrail, pair_key, violations)
        elif paper_enabled or paper_persist_enabled or paper_log_enabled:
            violations.append(
                _violation(
                    pair_key,
                    "unexpected_pa_paper_enabled",
                    "PA paper guardrail may only be enabled on the expected asset/timeframe.",
                )
            )

    if expected_guardrail is None:
        violations.append(_violation(f"{expected_asset}|{expected_timeframe}", "missing_expected_pair", "Expected PA paper pair is missing."))
    elif require_enabled:
        if not bool(expected_guardrail.get("paper_enabled", False)):
            violations.append(_violation(f"{expected_asset}|{expected_timeframe}", "paper_not_enabled", "Expected PA paper switch is not enabled."))
        if not bool(expected_guardrail.get("paper_persist_enabled", False)):
            violations.append(_violation(f"{expected_asset}|{expected_timeframe}", "paper_persist_not_enabled", "Expected PA paper persistence is not enabled."))

    return {
        "phase": "phase_6n_pa_paper_rollout_safety",
        "summary": {
            "expected_asset": expected_asset,
            "expected_timeframe": str(expected_timeframe),
            "require_enabled": bool(require_enabled),
            "safe": len(violations) == 0,
            "rollout_ready": len(violations) == 0 and bool(expected_guardrail and expected_guardrail.get("paper_enabled") and expected_guardrail.get("paper_persist_enabled")),
            "violation_count": len(violations),
            "enabled_pair_count": len(enabled_pairs),
            "persist_enabled_pair_count": len(persist_enabled_pairs),
            "live_gate_enabled_count": len(live_gate_enabled_pairs),
            "enabled_pairs": enabled_pairs,
            "persist_enabled_pairs": persist_enabled_pairs,
            "live_gate_enabled_pairs": live_gate_enabled_pairs,
            "expected_pair_configured": expected_guardrail is not None,
            "expected_pair_paper_enabled": bool(expected_guardrail and expected_guardrail.get("paper_enabled")),
            "expected_pair_persist_enabled": bool(expected_guardrail and expected_guardrail.get("paper_persist_enabled")),
        },
        "violations": violations,
        "expected_guardrail": expected_guardrail or {},
    }


def render_pa_paper_rollout_safety_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for a PA paper rollout safety report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6N PA Paper Rollout Safety",
        "",
        "## Summary",
        "",
        f"- Expected pair: {summary.get('expected_asset')}|{summary.get('expected_timeframe')}",
        f"- Require enabled: {summary.get('require_enabled')}",
        f"- Safe: {summary.get('safe')}",
        f"- Rollout ready: {summary.get('rollout_ready')}",
        f"- Violations: {summary.get('violation_count', 0)}",
        f"- Enabled pairs: {summary.get('enabled_pairs', [])}",
        f"- Persist-enabled pairs: {summary.get('persist_enabled_pairs', [])}",
        f"- Live gate enabled pairs: {summary.get('live_gate_enabled_pairs', [])}",
        "",
        "## Violations",
        "",
    ]
    violations = list(report.get("violations", []))
    if not violations:
        lines.append("- none")
    else:
        for item in violations:
            lines.append(f"- {item.get('pair')}: {item.get('code')} — {item.get('message')}")
    lines.append("")
    return "\n".join(lines)


def _validate_expected_guardrail(guardrail: Mapping[str, Any], pair_key: str, violations: list[dict[str, Any]]) -> None:
    if not guardrail:
        violations.append(_violation(pair_key, "missing_guardrail", "Expected pair is missing PA paper guardrail config."))
        return
    if str(guardrail.get("model_name") or "") != _EXPECTED_MODEL:
        violations.append(_violation(pair_key, "wrong_model", "PA paper guardrail must target PriceAction only."))
    if str(guardrail.get("asset") or "").upper() != _EXPECTED_ASSET:
        violations.append(_violation(pair_key, "wrong_asset", "PA paper guardrail asset must be BNBUSDT."))
    if str(guardrail.get("timeframe") or "") != _EXPECTED_TIMEFRAME:
        violations.append(_violation(pair_key, "wrong_timeframe", "PA paper guardrail timeframe must be 1h."))
    if _int_value(guardrail.get("direction"), 0) != _EXPECTED_DIRECTION:
        violations.append(_violation(pair_key, "wrong_direction", "PA paper guardrail direction must be 1."))
    paper_path = str(guardrail.get("paper_persist_path") or _DEFAULT_PAPER_LOG)
    if paper_path == _MAIN_SHADOW_LOG:
        violations.append(_violation(pair_key, "paper_path_conflicts_with_shadow_log", "Paper log must not use the main RegimeV2 shadow log path."))


def _iter_timeframe_configs(selection_config: Mapping[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    root = dict(selection_config)
    if "selection" in root and isinstance(root["selection"], dict):
        root = dict(root["selection"])
    assets = root.get("assets", {})
    if not isinstance(assets, dict):
        return []
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for asset, asset_cfg in assets.items():
        if not isinstance(asset_cfg, dict):
            continue
        timeframes = asset_cfg.get("timeframes", {})
        if not isinstance(timeframes, dict):
            continue
        for timeframe, tf_cfg in timeframes.items():
            if isinstance(tf_cfg, dict):
                rows.append((str(asset).upper(), str(timeframe), dict(tf_cfg)))
    return rows


def _violation(pair: str, code: str, message: str) -> dict[str, str]:
    return {"pair": pair, "code": code, "message": message}


def _int_value(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = ["render_pa_paper_rollout_safety_markdown", "validate_pa_paper_rollout_config"]
