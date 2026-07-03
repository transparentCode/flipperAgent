"""Data quality checks for RegimeV2."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_v2.config import DataQualityConfig
from libs.models.regime_v2.contracts import DataQualityReport
from libs.models.regime_v2.features.utils import rolling_zscore


def validate_ohlcv(df: pd.DataFrame, config: DataQualityConfig) -> DataQualityReport:
    """Validate OHLCV input without mutating it."""
    reasons: list[str] = []
    rows = int(len(df))
    missing_required = tuple(field for field in config.required_fields if field not in df.columns)
    if missing_required:
        reasons.append("missing_required_fields")

    missing_ratio = 1.0
    duplicate_timestamps = 0
    monotonic_index = True
    warmup_complete = rows >= config.min_bars
    anomaly_score = 0.0

    if not warmup_complete:
        reasons.append("insufficient_history")

    if rows > 0 and not missing_required:
        core = df.loc[:, list(config.required_fields)]
        missing_ratio = float(core.isna().mean().mean())
        if missing_ratio > config.max_missing_ratio:
            reasons.append("too_many_missing_values")

        if hasattr(df.index, "is_monotonic_increasing"):
            monotonic_index = bool(df.index.is_monotonic_increasing)
            if not monotonic_index:
                reasons.append("non_monotonic_index")
        if hasattr(df.index, "duplicated"):
            duplicate_timestamps = int(df.index.duplicated().sum())
            if duplicate_timestamps:
                reasons.append("duplicate_timestamps")

        close = core["close"].astype(float)
        invalid_prices = int((core[["open", "high", "low", "close"]].astype(float) <= 0).sum().sum())
        if invalid_prices:
            reasons.append("non_positive_prices")

        lr = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        z = rolling_zscore(lr.abs(), min(max(config.min_bars // 4, 20), 200))
        anomaly_score = float((z > config.extreme_return_z).mean()) if len(z) else 0.0
        if anomaly_score > 0.02:
            reasons.append("extreme_return_anomalies")

        bad_ohlc = ((core["high"] < core[["open", "close"]].max(axis=1)) | (core["low"] > core[["open", "close"]].min(axis=1))).sum()
        if int(bad_ohlc) > 0:
            reasons.append("invalid_ohlc_shape")

    usable = not reasons or reasons == ["insufficient_history"] and rows > 0 and not missing_required
    usable = usable and not missing_required and rows > 0

    return DataQualityReport(
        usable=bool(usable),
        rows=rows,
        required_fields=tuple(config.required_fields),
        missing_required_fields=missing_required,
        missing_ratio=round(float(missing_ratio), 6),
        duplicate_timestamps=duplicate_timestamps,
        monotonic_index=monotonic_index,
        warmup_complete=warmup_complete,
        anomaly_score=round(float(anomaly_score), 6),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def prepare_ohlcv(df: pd.DataFrame, required_fields: tuple[str, ...]) -> pd.DataFrame:
    """Return sorted numeric OHLCV frame for feature computation."""
    if any(field not in df.columns for field in required_fields):
        missing = [field for field in required_fields if field not in df.columns]
        raise ValueError(f"Missing required OHLCV fields: {missing}")
    out = df.copy()
    if hasattr(out.index, "is_monotonic_increasing") and not out.index.is_monotonic_increasing:
        out = out.sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    for field in required_fields:
        out[field] = pd.to_numeric(out[field], errors="coerce")
    return out


__all__ = ["prepare_ohlcv", "validate_ohlcv"]
