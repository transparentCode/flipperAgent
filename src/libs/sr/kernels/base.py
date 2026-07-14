"""
Base S/R Kernel
===============
Abstract base class for all v2 detection kernels.

Kernels are **stateless pure functions**: OHLCV data + config in →
``List[CandidateLevel]`` out.  No internal state, no side effects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from app.sr.models import AssetMetadata, CandidateLevel, RuleDerivedParams


@dataclass(frozen=True)
class KernelConfig:
    """
    Configuration passed to every kernel invocation.

    Carries resolved per-kernel params, asset metadata, and
    rule-derived values so kernels never need to read raw YAML.
    """
    kernel_name: str
    timeframe: str
    kernel_params: Dict[str, Any]
    metadata: AssetMetadata
    rule_derived: RuleDerivedParams
    extra: Dict[str, Any] = field(default_factory=dict)
    atr_period: int = 14
    precomputed_atr: float = 0.0  # Set by pipeline to avoid redundant ATR calc


class BaseSRKernel(ABC):
    """
    Abstract base for stateless S/R detection kernels.

    Contract:
        * ``compute()`` is a pure function — same inputs → same outputs.
        * All config flows through ``KernelConfig``.
        * Returns ``List[CandidateLevel]`` with zone bounds set.

    Subclasses must:
        * Implement ``compute(df, config)``.
        * Be registered via ``@register_kernel("name")``.
    """

    @abstractmethod
    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        """
        Detect raw candidate levels from OHLCV data.

        Args:
            df: OHLCV DataFrame (columns: open, high, low, close, volume).
                Must have ≥ ``config.rule_derived.n1 + config.rule_derived.n2``
                rows for pivot kernels.
            config: Fully resolved kernel configuration.

        Returns:
            List of immutable ``CandidateLevel`` objects.
        """
        ...

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ATR for the most recent bar (convenience helper)."""
        period = max(1, int(period))
        if len(df) < period + 1:
            if len(df) < 2:
                return 0.0
            period = len(df) - 1

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        tr = []
        for i in range(1, len(high)):
            tr.append(max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            ))
        if not tr:
            return 0.0

        # Simple EMA-style ATR
        atr = sum(tr[:period]) / period
        for val in tr[period:]:
            atr = (atr * (period - 1) + val) / period
        return atr

    @staticmethod
    def get_atr(df: pd.DataFrame, config: "KernelConfig") -> float:
        """Return precomputed ATR if available, else calculate fresh."""
        if config.precomputed_atr > 0:
            return config.precomputed_atr
        return BaseSRKernel.calculate_atr(df, period=config.atr_period)

    @staticmethod
    def _to_datetime(value: object, fallback_index: int = 0) -> datetime:
        """Convert pandas Timestamp / int index / datetime to tz-aware UTC datetime.

        Canonical implementation — all kernels should use this instead of
        defining their own ``_to_datetime`` helpers.
        """
        if isinstance(value, pd.Timestamp):
            if value.tzinfo is None:
                return value.tz_localize(UTC).to_pydatetime()
            return value.to_pydatetime()

        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value

        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value):
            seconds = float(value)
        else:
            seconds = float(fallback_index)

        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
