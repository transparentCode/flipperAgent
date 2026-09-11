"""Phase 4 validation matrix and shadow-promotion decision gate for RegimeV2.

The earlier RegimeV2 evaluation helpers answer one narrow question at a time:
compare one OHLCV frame, run one downstream ablation, or validate one rolling
window setup.  This module coordinates those helpers across assets, timeframes,
horizons, and fee assumptions, then emits a conservative decision:

- ``PROMOTE_TO_SHADOW_CANDIDATE``: evidence is broad enough to start disabled
  shadow-mode plumbing / logging work.
- ``HOLD_FOR_MORE_EVIDENCE``: keep RegimeV2 disabled and continue research.

This is intentionally an offline gate.  It must not enable live RegimeV2 usage.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from libs.models.regime_v2.evaluation.failure_diagnostics import summarize_failure_diagnostics
from libs.models.regime_v2.evaluation.overlay_validation import (
    OverlayWindowValidationConfig,
    run_overlay_window_validation,
)

PROMOTE_TO_SHADOW_CANDIDATE = "PROMOTE_TO_SHADOW_CANDIDATE"
HOLD_FOR_MORE_EVIDENCE = "HOLD_FOR_MORE_EVIDENCE"


@dataclass(frozen=True)
class Phase4DecisionConfig:
    """Conservative criteria for moving from Phase 4 to shadow-mode work."""

    min_valid_windows_per_fee: int = 2
    min_positive_rate: float = 0.55
    min_mean_lift: float = 0.0
    require_all_fees: bool = True
    min_passed_combos: int = 2
    min_combo_pass_rate: float = 0.60


@dataclass(frozen=True)
class Phase4OverlayMatrixConfig:
    """Batch-validation matrix for RegimeV2 trend-overlay experiments."""

    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    horizon_bars_values: tuple[int, ...] = (6, 12)
    window_bars: int = 300
    step_bars: int = 150
    min_count: int = 10
    fee_bps_values: tuple[float, ...] = (0.0, 2.0, 5.0)
    candidate_models: tuple[str, ...] = ("Momentum", "TrendFollowing", "PriceAction")
    min_abs_edge: float = 0.01
    top_k: int = 1
    aligned_boost: float = 0.35
    conflict_penalty: float = 0.70
    trend_score_floor: float = 0.24
    breakout_score_floor: float = 0.24
    mean_reversion_score_floor: float = 0.24
    include_window_metrics: bool = True
    decision: Phase4DecisionConfig = field(default_factory=Phase4DecisionConfig)


def run_phase4_overlay_matrix(
    fetch_ohlcv: Callable[[str, str], pd.DataFrame],
    *,
    config: Phase4OverlayMatrixConfig,
) -> dict[str, Any]:
    """Run the Phase 4 validation matrix with a synchronous OHLCV fetcher."""
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    for asset in config.assets:
        for timeframe in config.timeframes:
            frames[(asset.upper(), timeframe)] = fetch_ohlcv(asset.upper(), timeframe)
    return run_phase4_overlay_matrix_from_frames(frames, config=config)


async def run_phase4_overlay_matrix_async(
    fetch_ohlcv: Callable[[str, str], Awaitable[pd.DataFrame]],
    *,
    config: Phase4OverlayMatrixConfig,
) -> dict[str, Any]:
    """Run the Phase 4 validation matrix with an async OHLCV fetcher."""
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    for asset in config.assets:
        for timeframe in config.timeframes:
            frames[(asset.upper(), timeframe)] = await fetch_ohlcv(asset.upper(), timeframe)
    return run_phase4_overlay_matrix_from_frames(frames, config=config)


def run_phase4_overlay_matrix_from_frames(
    frames: Mapping[tuple[str, str], pd.DataFrame],
    *,
    config: Phase4OverlayMatrixConfig,
) -> dict[str, Any]:
    """Run the Phase 4 validation matrix from preloaded OHLCV frames.

    ``frames`` is keyed by ``(ASSET, timeframe)``.  This entry point is the most
    testable/reproducible form because data fetching is kept outside the gate.
    """
    combo_rows: list[dict[str, Any]] = []
    all_window_metrics: list[dict[str, Any]] = []

    for asset in config.assets:
        asset_key = asset.upper()
        for timeframe in config.timeframes:
            frame_key = (asset_key, timeframe)
            if frame_key not in frames:
                raise ValueError(f"Missing OHLCV frame for {asset_key}:{timeframe}")
            ohlcv = frames[frame_key]
            for horizon_bars in config.horizon_bars_values:
                validation = run_overlay_window_validation(
                    ohlcv,
                    asset=asset_key,
                    timeframe=timeframe,
                    config=OverlayWindowValidationConfig(
                        horizon_bars=int(horizon_bars),
                        window_bars=config.window_bars,
                        step_bars=config.step_bars,
                        min_count=config.min_count,
                        fee_bps_values=config.fee_bps_values,
                        candidate_models=config.candidate_models,
                        min_abs_edge=config.min_abs_edge,
                        top_k=config.top_k,
                        aligned_boost=config.aligned_boost,
                        conflict_penalty=config.conflict_penalty,
                        trend_score_floor=config.trend_score_floor,
                        breakout_score_floor=config.breakout_score_floor,
                        mean_reversion_score_floor=config.mean_reversion_score_floor,
                    ),
                )
                combo_decision = _combo_decision(validation["summary"], config.decision)
                combo_rows.append(
                    {
                        "asset": asset_key,
                        "timeframe": timeframe,
                        "horizon_bars": int(horizon_bars),
                        "ohlcv_rows": int(len(ohlcv)),
                        "passed": combo_decision["passed"],
                        "decision": combo_decision["decision"],
                        "failure_reasons": combo_decision["failure_reasons"],
                        "summary": validation["summary"],
                    }
                )
                if config.include_window_metrics:
                    for metric in validation["metrics"]:
                        all_window_metrics.append(
                            {
                                "asset": asset_key,
                                "timeframe": timeframe,
                                "horizon_bars": int(horizon_bars),
                                **metric,
                            }
                        )

    matrix_summary = _matrix_summary(combo_rows, config.decision)
    return {
        "phase": "phase_4_downstream_validation",
        "decision": matrix_summary["decision"],
        "summary": matrix_summary,
        "combos": combo_rows,
        "window_metrics": all_window_metrics,
        "config": {
            **asdict(config),
            "decision": asdict(config.decision),
        },
    }


def render_phase4_overlay_matrix_markdown(result: Mapping[str, Any]) -> str:
    """Render a compact Markdown report for the Phase 4 validation matrix."""
    summary = dict(result.get("summary", {}))
    combos = list(result.get("combos", []))
    lines = [
        "# RegimeV2 Phase 4 Overlay Validation Matrix",
        "",
        f"Decision: **{result.get('decision', HOLD_FOR_MORE_EVIDENCE)}**",
        "",
        "## Summary",
        "",
        f"- Total combos: {summary.get('combo_count', 0)}",
        f"- Passed combos: {summary.get('passed_combo_count', 0)}",
        f"- Pass rate: {summary.get('combo_pass_rate')}",
        f"- Failure reasons: {', '.join(summary.get('failure_reasons', [])) or 'none'}",
        f"- Top diagnostic reason: {_top_diagnostic_reason(summary)}",
        "",
        "## Combo Results",
        "",
        "| Asset | TF | Horizon | Passed | Mean lift by fee | Positive rate by fee |",
        "|---|---:|---:|---:|---|---|",
    ]
    for combo in combos:
        fee_summary = combo.get("summary", {}).get("fee_summary", {})
        mean_lifts = ", ".join(
            f"{fee}: {stats.get('mean_gated_lift')}" for fee, stats in sorted(fee_summary.items())
        )
        positive_rates = ", ".join(
            f"{fee}: {stats.get('positive_gated_rate')}" for fee, stats in sorted(fee_summary.items())
        )
        lines.append(
            "| {asset} | {timeframe} | {horizon_bars} | {passed} | {mean_lifts} | {positive_rates} |".format(
                asset=combo.get("asset"),
                timeframe=combo.get("timeframe"),
                horizon_bars=combo.get("horizon_bars"),
                passed=combo.get("passed"),
                mean_lifts=mean_lifts or "n/a",
                positive_rates=positive_rates or "n/a",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _combo_decision(summary: Mapping[str, Any], cfg: Phase4DecisionConfig) -> dict[str, Any]:
    fee_summary = summary.get("fee_summary", {})
    fee_rows = []
    failure_reasons: list[str] = []

    for raw_fee, stats in fee_summary.items():
        fee = str(raw_fee)
        valid_count = int(stats.get("valid_window_count") or 0)
        positive_rate = stats.get("positive_gated_rate")
        mean_lift = stats.get("mean_gated_lift")
        fee_passed = True
        fee_reasons: list[str] = []

        if valid_count < cfg.min_valid_windows_per_fee:
            fee_passed = False
            fee_reasons.append(f"fee_{fee}_valid_windows_below_{cfg.min_valid_windows_per_fee}")
        if positive_rate is None or float(positive_rate) < cfg.min_positive_rate:
            fee_passed = False
            fee_reasons.append(f"fee_{fee}_positive_rate_below_{cfg.min_positive_rate}")
        if mean_lift is None or float(mean_lift) < cfg.min_mean_lift:
            fee_passed = False
            fee_reasons.append(f"fee_{fee}_mean_lift_below_{cfg.min_mean_lift}")

        fee_rows.append({"fee_bps": fee, "passed": fee_passed, "failure_reasons": fee_reasons})
        failure_reasons.extend(fee_reasons)

    if not fee_rows:
        return {
            "passed": False,
            "decision": HOLD_FOR_MORE_EVIDENCE,
            "failure_reasons": ["no_fee_summary_available"],
            "fee_decisions": [],
        }

    passed = all(row["passed"] for row in fee_rows) if cfg.require_all_fees else any(row["passed"] for row in fee_rows)
    if not passed and not failure_reasons:
        failure_reasons.append("fee_gate_failed")
    return {
        "passed": bool(passed),
        "decision": PROMOTE_TO_SHADOW_CANDIDATE if passed else HOLD_FOR_MORE_EVIDENCE,
        "failure_reasons": sorted(set(failure_reasons)),
        "fee_decisions": fee_rows,
    }


def _matrix_summary(combo_rows: list[dict[str, Any]], cfg: Phase4DecisionConfig) -> dict[str, Any]:
    combo_count = len(combo_rows)
    passed_count = sum(1 for row in combo_rows if row["passed"])
    pass_rate = _round(passed_count / combo_count) if combo_count else None
    failure_reasons = sorted({reason for row in combo_rows for reason in row.get("failure_reasons", [])})

    decision = HOLD_FOR_MORE_EVIDENCE
    if (
        combo_count > 0
        and passed_count >= cfg.min_passed_combos
        and pass_rate is not None
        and pass_rate >= cfg.min_combo_pass_rate
    ):
        decision = PROMOTE_TO_SHADOW_CANDIDATE
    else:
        if passed_count < cfg.min_passed_combos:
            failure_reasons.append(f"passed_combos_below_{cfg.min_passed_combos}")
        if pass_rate is None or pass_rate < cfg.min_combo_pass_rate:
            failure_reasons.append(f"combo_pass_rate_below_{cfg.min_combo_pass_rate}")

    return {
        "decision": decision,
        "combo_count": combo_count,
        "passed_combo_count": passed_count,
        "combo_pass_rate": pass_rate,
        "failure_reasons": sorted(set(failure_reasons)),
        "failure_diagnostics": summarize_failure_diagnostics(
            [row.get("summary", {}).get("failure_diagnostics", {}) for row in combo_rows]
        ),
        "criteria": asdict(cfg),
    }


def _top_diagnostic_reason(summary: Mapping[str, Any]) -> str:
    diagnostics = summary.get("failure_diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        return "none"
    top_reasons = diagnostics.get("top_reasons", [])
    if not top_reasons:
        return "none"
    top = top_reasons[0]
    if not isinstance(top, Mapping):
        return "none"
    return f"{top.get('reason')} ({top.get('count')})"


def _round(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 8)


__all__ = [
    "HOLD_FOR_MORE_EVIDENCE",
    "PROMOTE_TO_SHADOW_CANDIDATE",
    "Phase4DecisionConfig",
    "Phase4OverlayMatrixConfig",
    "render_phase4_overlay_matrix_markdown",
    "run_phase4_overlay_matrix",
    "run_phase4_overlay_matrix_async",
    "run_phase4_overlay_matrix_from_frames",
]
