"""
Base Aggregator Interface
=========================
Abstract base class for feature aggregation strategies.
"""

from abc import ABC, abstractmethod

import pandas as pd

from libs.regime.models import ChangePointSignal, HMMState, RegimeFeatures, VolState


class BaseAggregator(ABC):
    """Abstract base for regime feature aggregation."""

    @abstractmethod
    def aggregate(
        self,
        hmm: HMMState,
        vol: VolState,
        cp: ChangePointSignal,
        hilbert_period: float,
        hilbert_confidence: float,
    ) -> RegimeFeatures:
        """Combine 4-layer signals into unified RegimeFeatures."""
        ...

    @abstractmethod
    def aggregate_series(
        self,
        hmm_df: pd.DataFrame,
        vol_df: pd.DataFrame,
        cp_df: pd.DataFrame,
        hilbert_periods=None,
        hilbert_confidences=None,
    ) -> pd.DataFrame:
        """Aggregate full time series from all detectors."""
        ...
