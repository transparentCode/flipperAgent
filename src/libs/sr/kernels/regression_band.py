"""
Regression Band Kernel
=======================
Consumes the regression module's already-optimized band output and
emits band edges as S/R candidates.

The upper band → resistance, lower band → support.
Center line emitted optionally.

This kernel **wraps** the regression pipeline — it does not re-fit
regression models.  The ``band_width_sigma`` param is passed through
to the regression pipeline if running inline, or the kernel accepts
a pre-computed ``RegressionResult`` via ``config.extra["regression_result"]``.

Config params (via ``KernelConfig.kernel_params``):
  * ``band_width_sigma`` — band width in σ (default 2.0)
  * ``emit_center``      — emit center-line candidate (default False)
  * ``band_strength``    — base strength for band levels (default 0.8)
  * ``center_strength``  — strength for center line (default 0.6)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import register_kernel
from app.sr.models import CandidateLevel

logger = logging.getLogger(__name__)


@register_kernel("regression_band")
class RegressionBandKernel(BaseSRKernel):
    """Regression band edges as S/R candidates."""

    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        params = config.kernel_params
        min_bars = max(1, int(params.get("min_bars", 30)))

        if len(df) < min_bars:
            return []

        atr = self.get_atr(df, config)
        if atr <= 0:
            return []

        band_strength = params.get("band_strength", 0.8)
        center_strength = params.get("center_strength", 0.6)
        emit_center = params.get("emit_center", False)
        band_width_sigma = params.get("band_width_sigma", 2.0)

        upper_val = None
        lower_val = None
        center_val = None
        confidence = 0.5
        timestamp_source = df.index[-1]

        regression_result = config.extra.get("regression_result") if config.extra else None
        extracted = _extract_regression_values(regression_result)

        if extracted is None:
            inline_result = _compute_inline_regression_result(
                df=df,
                config=config,
                band_width_sigma=band_width_sigma,
            )
            extracted = _extract_regression_values(inline_result)

        if extracted is not None:
            upper_val, lower_val, center_val, confidence, timestamp_source = extracted
        else:
            # Fallback: simple linear regression + σ bands
            upper_val, center_val, lower_val, confidence = self._simple_regression_bands(
                df, band_width_sigma,
            )

        timestamp = self._to_datetime(timestamp_source, fallback_index=len(df) - 1)

        half_width = params.get("zone_half_width_atr", 0.1) * atr
        candidates: List[CandidateLevel] = []
        current_close = float(df["close"].iloc[-1])

        if upper_val is not None and np.isfinite(upper_val):
            candidates.append(CandidateLevel(
                center_price=upper_val,
                lower_bound=upper_val - half_width,
                upper_bound=upper_val + half_width,
                level_type=LevelType.RESISTANCE,
                kernel_name="regression_band",
                timeframe=config.timeframe,
                raw_score=band_strength * confidence,
                metadata={
                    "band_role": "upper",
                    "sigma": band_width_sigma,
                    "regression_confidence": confidence,
                },
                timestamp=timestamp,
                atr_at_detection=atr,
            ))

        if lower_val is not None and np.isfinite(lower_val):
            candidates.append(CandidateLevel(
                center_price=lower_val,
                lower_bound=lower_val - half_width,
                upper_bound=lower_val + half_width,
                level_type=LevelType.SUPPORT,
                kernel_name="regression_band",
                timeframe=config.timeframe,
                raw_score=band_strength * confidence,
                metadata={
                    "band_role": "lower",
                    "sigma": band_width_sigma,
                    "regression_confidence": confidence,
                },
                timestamp=timestamp,
                atr_at_detection=atr,
            ))

        if emit_center and center_val is not None and np.isfinite(center_val):
            candidates.append(CandidateLevel(
                center_price=center_val,
                lower_bound=center_val - half_width,
                upper_bound=center_val + half_width,
                level_type=(
                    LevelType.RESISTANCE
                    if center_val > current_close
                    else LevelType.SUPPORT
                ),
                kernel_name="regression_band",
                timeframe=config.timeframe,
                raw_score=center_strength * confidence,
                metadata={
                    "band_role": "center",
                    "sigma": band_width_sigma,
                    "regression_confidence": confidence,
                },
                timestamp=timestamp,
                atr_at_detection=atr,
            ))

        return candidates

    @staticmethod
    def _simple_regression_bands(
        df: pd.DataFrame,
        sigma: float,
    ) -> tuple:
        """Fallback: OLS on close prices with std-dev bands."""
        closes = df["close"].values.astype(float)
        # Filter NaN values to prevent propagation through OLS
        finite_mask = np.isfinite(closes)
        if finite_mask.sum() < 3:
            return None, None, None, 0.0
        closes = closes[finite_mask]
        n = len(closes)
        x = np.arange(n, dtype=float)

        # OLS
        x_mean = x.mean()
        y_mean = closes.mean()
        ss_xx = ((x - x_mean) ** 2).sum()
        if ss_xx == 0:
            return None, None, None, 0.0
        ss_xy = ((x - x_mean) * (closes - y_mean)).sum()

        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean

        fitted = slope * x + intercept
        residuals = closes - fitted
        std_dev = float(np.std(residuals))

        # Zero std_dev means flat data — bands collapse to a point
        if std_dev <= 1e-10:
            return None, None, None, 0.0

        center = float(fitted[-1])
        upper = center + sigma * std_dev
        lower = center - sigma * std_dev

        # R² for confidence
        ss_res = (residuals ** 2).sum()
        ss_tot = ((closes - y_mean) ** 2).sum()
        r_sq = max(0.0, 1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        return upper, center, lower, min(1.0, r_sq)


def _extract_last(arr) -> float | None:
    """Extract last finite value from array-like."""
    if arr is None:
        return None
    if isinstance(arr, (int, float)):
        return float(arr) if np.isfinite(arr) else None
    if hasattr(arr, "values"):
        arr = arr.values
    if isinstance(arr, np.ndarray):
        mask = np.isfinite(arr)
        if mask.any():
            return float(arr[mask][-1])
    return None


def _extract_regression_values(regression_result):
    if regression_result is None or not getattr(regression_result, "is_valid", True):
        return None

    upper_val = _extract_last(getattr(regression_result, "upper_band", None))
    lower_val = _extract_last(getattr(regression_result, "lower_band", None))
    center_val = _extract_last(getattr(regression_result, "mid_line", None))

    if upper_val is None and lower_val is None and center_val is None:
        return None

    confidence = float(getattr(regression_result, "confidence", 0.5))
    timestamp = getattr(regression_result, "timestamp", None)
    return upper_val, lower_val, center_val, confidence, timestamp


@lru_cache(maxsize=4)
def _get_regression_resolver(config_path: str):
    from app.regression.config.resolver import ConfigResolver

    return ConfigResolver.from_yaml(config_path)


def _compute_inline_regression_result(
    df: pd.DataFrame,
    config: KernelConfig,
    band_width_sigma: float,
):
    asset = config.extra.get("asset") if config.extra else None
    if not asset:
        return None

    from app.regression.api import compute_single_tf

    config_path = config.extra.get("regression_config_path") if config.extra else None
    if not config_path:
        config_path = str(
            Path(__file__).resolve().parents[2] / "regression" / "config" / "regression.yaml"
        )

    try:
        resolved = _get_regression_resolver(config_path).resolve(asset, config.timeframe)
        resolved = replace(resolved, band_multiplier=float(band_width_sigma))
        return compute_single_tf(
            df=df,
            asset=asset,
            timeframe=config.timeframe,
            config=resolved,
        )
    except Exception as e:
        logger.debug("Inline regression failed for %s:%s — %s", asset, config.timeframe, e)
        return None
