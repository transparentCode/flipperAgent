"""Offline A/B/C comparison harness for RegimeV2.

The harness intentionally keeps dependencies optional:
- RegimeV2 is always evaluated.
- Legacy ``libs.regime`` and ``RegimeClassification`` are evaluated only when
  available and requested.
- A no-regime baseline is always included for downstream joins/reports.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator


@dataclass(frozen=True)
class RegimeComparisonConfig:
    """Configuration for offline regime comparison."""

    horizon_bars: int = 12
    include_legacy_regime: bool = True
    include_regime_classification: bool = True
    min_rows: int = 80
    legacy_overrides: dict[str, Any] = field(default_factory=dict)
    regime_v2_overrides: dict[str, Any] = field(default_factory=dict)
    regime_classification_params: dict[str, Any] = field(default_factory=dict)
    regime_classification_frozen_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RegimeComparisonResult:
    """Offline comparison result."""

    frame: pd.DataFrame
    summary: dict[str, Any]
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "errors": dict(self.errors),
            "rows": int(len(self.frame)),
            "columns": list(self.frame.columns),
        }


def run_regime_comparison(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    config: RegimeComparisonConfig | None = None,
) -> RegimeComparisonResult:
    """Run old/no-regime/new regime outputs on the same OHLCV frame."""
    cfg = config or RegimeComparisonConfig()
    clean = _clean_price_frame(df)
    errors: dict[str, str] = {}

    frame = pd.DataFrame(index=clean.index)
    frame["close"] = clean["close"].astype(float)
    frame["fwd_return"] = np.log(clean["close"].shift(-cfg.horizon_bars) / clean["close"]).replace(
        [np.inf, -np.inf], np.nan
    )
    frame["fwd_abs_return"] = frame["fwd_return"].abs()
    frame["no_regime_label"] = "always_on"
    frame["no_regime_confidence"] = 1.0

    try:
        frame = frame.join(_regime_v2_frame(clean, asset, timeframe, cfg), how="left")
    except Exception as exc:  # pragma: no cover - defensive path
        errors["regime_v2"] = str(exc)

    if cfg.include_legacy_regime:
        try:
            legacy = _legacy_regime_frame(clean, asset, timeframe, cfg)
            frame = frame.join(legacy, how="left")
        except Exception as exc:
            errors["legacy_regime"] = str(exc)

    if cfg.include_regime_classification:
        try:
            rc = _regime_classification_frame(clean, asset, timeframe, cfg)
            frame = frame.join(rc, how="left")
        except Exception as exc:
            errors["regime_classification"] = str(exc)

    summary = summarize_comparison(frame, horizon_bars=cfg.horizon_bars, errors=errors)
    return RegimeComparisonResult(frame=frame, summary=summary, errors=errors)


def summarize_comparison(
    frame: pd.DataFrame,
    *,
    horizon_bars: int,
    errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build compact summary metrics for quick review."""
    summary: dict[str, Any] = {
        "rows": int(len(frame)),
        "horizon_bars": int(horizon_bars),
        "errors": dict(errors or {}),
        "modules_present": _modules_present(frame),
    }

    if "regime_v2_summary_label" in frame.columns:
        summary["regime_v2"] = {
            "label_distribution": _value_distribution(frame["regime_v2_summary_label"]),
            "mean_confidence": _mean(frame.get("regime_v2_confidence")),
            "mean_uncertainty": _mean(frame.get("regime_v2_uncertainty")),
            "trend_score_ic_abs_return": _corr(frame.get("regime_v2_policy_trend_score"), frame["fwd_abs_return"]),
            "breakout_score_ic_abs_return": _corr(frame.get("regime_v2_policy_breakout_score"), frame["fwd_abs_return"]),
            "mr_score_ic_abs_return": _corr(frame.get("regime_v2_policy_mean_reversion_score"), frame["fwd_abs_return"]),
            "allowed_rates": {
                "trend": _mean_bool(frame.get("regime_v2_policy_allow_trend_following")),
                "breakout": _mean_bool(frame.get("regime_v2_policy_allow_breakout")),
                "mean_reversion": _mean_bool(frame.get("regime_v2_policy_allow_mean_reversion")),
                "scalping": _mean_bool(frame.get("regime_v2_policy_allow_scalping")),
                "countertrend": _mean_bool(frame.get("regime_v2_policy_allow_countertrend")),
            },
            "evidence_quantiles": {
                "trend_strength": _quantiles(frame.get("regime_v2_trend_strength")),
                "chop_risk": _quantiles(frame.get("regime_v2_chop_risk")),
                "breakout_quality": _quantiles(frame.get("regime_v2_breakout_quality")),
                "pre_breakout_setup_score": _quantiles(frame.get("regime_v2_pre_breakout_setup_score")),
                "displacement_breakout_score": _quantiles(frame.get("regime_v2_displacement_breakout_score")),
                "post_breakout_retest_score": _quantiles(frame.get("regime_v2_post_breakout_retest_score")),
                "mean_reversion_score": _quantiles(frame.get("regime_v2_mean_reversion_score")),
            },
            "policy_score_quantiles": {
                "trend": _quantiles(frame.get("regime_v2_policy_trend_score")),
                "breakout": _quantiles(frame.get("regime_v2_policy_breakout_score")),
                "mean_reversion": _quantiles(frame.get("regime_v2_policy_mean_reversion_score")),
                "scalping": _quantiles(frame.get("regime_v2_policy_scalping_score")),
                "countertrend": _quantiles(frame.get("regime_v2_policy_countertrend_score")),
                "breakout_setup": _quantiles(frame.get("regime_v2_policy_breakout_setup_score")),
                "displacement_breakout": _quantiles(frame.get("regime_v2_policy_displacement_breakout_score")),
                "retest_breakout": _quantiles(frame.get("regime_v2_policy_retest_breakout_score")),
            },
        }

    if "legacy_regime_label" in frame.columns:
        summary["legacy_regime"] = {
            "label_distribution": _value_distribution(frame["legacy_regime_label"]),
            "mean_p_trending": _mean(frame.get("legacy_p_trending")),
            "mean_position_scale": _mean(frame.get("legacy_position_scale")),
        }

    if "rc_condition_scale" in frame.columns:
        summary["regime_classification"] = {
            "mean_condition_scale": _mean(frame.get("rc_condition_scale")),
            "mean_vol_percentile": _mean(frame.get("rc_vol_percentile")),
            "mean_changepoint_prob": _mean(frame.get("rc_changepoint_prob")),
            "condition_scale_ic_abs_return": _corr(frame.get("rc_condition_scale"), frame["fwd_abs_return"]),
        }

    return summary


def _regime_v2_frame(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    cfg: RegimeComparisonConfig,
) -> pd.DataFrame:
    orch = RegimeV2Orchestrator.create(asset, timeframe, **cfg.regime_v2_overrides)
    raw = orch.analyze_series(df)
    prefix = "regime_v2_"
    keep = [
        "summary_label",
        "confidence",
        "uncertainty",
        "trend_direction",
        "trend_strength",
        "volatility_percentile",
        "mean_reversion_score",
        "chop_risk",
        "structural_break_risk",
        "breakout_quality",
        "pre_breakout_setup_score",
        "displacement_breakout_score",
        "post_breakout_retest_score",
        "breakout_direction",
        "policy_allow_trend_following",
        "policy_allow_breakout",
        "policy_allow_mean_reversion",
        "policy_allow_scalping",
        "policy_allow_countertrend",
        "policy_max_position_scale",
        "policy_trend_score",
        "policy_breakout_score",
        "policy_breakout_setup_score",
        "policy_displacement_breakout_score",
        "policy_retest_breakout_score",
        "policy_mean_reversion_score",
        "policy_scalping_score",
        "policy_countertrend_score",
        "policy_no_trade_reason",
    ]
    cols = [col for col in keep if col in raw.columns]
    return raw[cols].add_prefix(prefix)


def _legacy_regime_frame(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    cfg: RegimeComparisonConfig,
) -> pd.DataFrame:
    from libs.regime.orchestrator import RegimeOrchestrator

    orch = RegimeOrchestrator.create(asset.upper(), timeframe, **cfg.legacy_overrides)
    raw = orch.analyze_series(df)
    mapping = {
        "regime": "legacy_regime_label",
        "p_trending": "legacy_p_trending",
        "vol_percentile": "legacy_vol_percentile",
        "changepoint_prob": "legacy_changepoint_prob",
        "position_scale": "legacy_position_scale",
        "adaptive_period": "legacy_adaptive_period",
    }
    cols = {old: new for old, new in mapping.items() if old in raw.columns}
    return raw[list(cols)].rename(columns=cols)


def _regime_classification_frame(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    cfg: RegimeComparisonConfig,
) -> pd.DataFrame:
    del asset  # RegimeClassificationModel is parameter/timeframe driven.
    from libs.models.regime_classification.model import RegimeClassificationModel

    model = RegimeClassificationModel(
        params=cfg.regime_classification_params,
        timeframe=timeframe,
        frozen_overrides=cfg.regime_classification_frozen_overrides,
    )
    raw = model.batch_evaluate(df)
    expanded = pd.DataFrame(list(raw), index=raw.index)
    mapping = {
        "condition_scale": "rc_condition_scale",
        "vol_percentile": "rc_vol_percentile",
        "changepoint_prob": "rc_changepoint_prob",
        "trend_strength": "rc_trend_strength",
        "hurst": "rc_hurst",
        "fwd_vol_ewma": "rc_fwd_vol_ewma",
    }
    cols = {old: new for old, new in mapping.items() if old in expanded.columns}
    return expanded[list(cols)].rename(columns=cols)


def _clean_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    required = ["open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")
    out = df.copy()
    if hasattr(out.index, "is_monotonic_increasing") and not out.index.is_monotonic_increasing:
        out = out.sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    for col in required:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _modules_present(frame: pd.DataFrame) -> dict[str, bool]:
    return {
        "no_regime": "no_regime_label" in frame.columns,
        "regime_v2": "regime_v2_summary_label" in frame.columns,
        "legacy_regime": "legacy_regime_label" in frame.columns,
        "regime_classification": "rc_condition_scale" in frame.columns or "rc_vol_percentile" in frame.columns,
    }


def _value_distribution(series: pd.Series) -> dict[str, float]:
    valid = series.dropna()
    if valid.empty:
        return {}
    return {str(k): round(float(v), 4) for k, v in valid.value_counts(normalize=True).sort_index().items()}


def _mean(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    valid = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if valid.empty:
        return None
    return round(float(valid.mean()), 6)


def _mean_bool(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    valid = series.dropna()
    if valid.empty:
        return None
    return round(float(valid.astype(bool).mean()), 6)


def _quantiles(series: pd.Series | None) -> dict[str, float] | None:
    if series is None:
        return None
    valid = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if valid.empty:
        return None
    return {
        "p50": round(float(valid.quantile(0.50)), 6),
        "p75": round(float(valid.quantile(0.75)), 6),
        "p90": round(float(valid.quantile(0.90)), 6),
        "p95": round(float(valid.quantile(0.95)), 6),
        "p99": round(float(valid.quantile(0.99)), 6),
    }


def _corr(left: pd.Series | None, right: pd.Series | None) -> float | None:
    if left is None or right is None:
        return None
    pair = pd.concat(
        [pd.to_numeric(left, errors="coerce"), pd.to_numeric(right, errors="coerce")],
        axis=1,
    ).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pair) < 20:
        return None
    if pair.iloc[:, 0].nunique(dropna=True) <= 1 or pair.iloc[:, 1].nunique(dropna=True) <= 1:
        return None
    value = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman")
    if pd.isna(value):
        return None
    return round(float(value), 6)


__all__ = [
    "RegimeComparisonConfig",
    "RegimeComparisonResult",
    "run_regime_comparison",
    "summarize_comparison",
]
