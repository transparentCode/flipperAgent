"""Local threshold sweep audits for RegimeV2 optimization."""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from libs.models.regime_v2.optimization import optimizer as regime_v2_optimizer
from libs.models.regime_v2.optimization.params import ProfileName, post_process_params
from libs.models.regime_v2.optimization.validation import RegimeV2RollingValidationConfig

DEFAULT_THRESHOLD_PARAMS: tuple[str, ...] = (
    "fusion.trend_threshold",
    "fusion.break_threshold",
    "policy.min_confidence",
    "policy.threshold_width",
    "policy.trend_min_strength",
    "policy.breakout_min_quality",
)


def run_threshold_sweep(
    ohlcv: pd.DataFrame,
    base_params: dict[str, Any],
    *,
    asset: str,
    timeframe: str,
    profile: ProfileName = "core",
    horizon_bars: int = 12,
    validation_config: RegimeV2RollingValidationConfig | None = None,
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    purge_bars: int = 24,
    params: Iterable[str] = DEFAULT_THRESHOLD_PARAMS,
    step: float = 0.02,
    radius: int = 2,
) -> dict[str, Any]:
    """Evaluate a local one-parameter-at-a-time sweep around best params."""
    processed_base = post_process_params(base_params, timeframe=timeframe, profile=profile)
    rows: list[dict[str, Any]] = []
    for param in params:
        if param not in processed_base:
            continue
        base_value = processed_base[param]
        if not isinstance(base_value, int | float):
            continue
        for value in _candidate_values(float(base_value), step=step, radius=radius):
            candidate = dict(processed_base)
            candidate[param] = value
            processed_candidate = post_process_params(candidate, timeframe=timeframe, profile=profile)
            oos = regime_v2_optimizer.evaluate_oos(
                ohlcv,
                processed_candidate,
                asset=asset,
                timeframe=timeframe,
                profile=profile,
                horizon_bars=horizon_bars,
                validation_config=validation_config,
                train_ratio=train_ratio,
                val_ratio=val_ratio,
                purge_bars=purge_bars,
            )
            rows.append(
                {
                    "param": param,
                    "value": processed_candidate[param],
                    "delta": round(float(processed_candidate[param]) - float(base_value), 8),
                    "oos_score": _score(oos),
                    "validation_score": _score(oos, segment="validate"),
                    "deployed": bool(oos.get("deployed")),
                    "rejection_reasons": list(oos.get("rejection_reasons") or []),
                }
            )

    rows.sort(key=lambda row: (not row["deployed"], -(row["oos_score"] or -1_000_000.0)))
    return {
        "params": [param for param in params if param in processed_base],
        "step": float(step),
        "radius": int(radius),
        "rows": rows,
    }


def _candidate_values(base: float, *, step: float, radius: int) -> list[float]:
    values = {
        max(0.0, min(1.0, round(base + offset * step, 8)))
        for offset in range(-int(radius), int(radius) + 1)
    }
    return sorted(values)


def _score(oos: dict[str, Any], *, segment: str = "oos") -> float | None:
    value = (((oos.get(segment) or {}).get("aggregate") or {}).get("score"))
    if value is None:
        return None
    return float(value)


__all__ = ["DEFAULT_THRESHOLD_PARAMS", "run_threshold_sweep"]
