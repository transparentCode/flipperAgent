from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config.schema import PluginConfig, ResolvedPipelineConfig
from .config.validator import ConfigValidator
from .contracts.context import CascadeContext, PipelineRequest
from .contracts.result import (
    DegradationLevel,
    EnsembleResult,
    FeatureSet,
    MethodResult,
    RegressionResult,
)
from .ensemble.base import EnsembleRegistry
from .features.base import FeatureRegistry
from .methods.base import MethodRegistry
from .state import NullStateManager, StateManager
from .uncertainty.base import UncertaintyRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BarArrays:
    timestamps: np.ndarray
    close_raw: np.ndarray
    high_raw: np.ndarray
    low_raw: np.ndarray
    volume_raw: np.ndarray

    def __len__(self) -> int:
        return len(self.close_raw)


class RegressionPipeline:
    """Single-timeframe regression pipeline.

    Stages: Features → Methods → Uncertainty → Ensemble

    Config is pre-validated (ResolvedPipelineConfig).
    State management is optional (NullStateManager by default).
    """

    def __init__(
        self,
        config: ResolvedPipelineConfig,
        state_manager: Optional[StateManager] = None,
        validate: bool = True,
    ) -> None:
        self.config = config
        self.state_manager = state_manager or NullStateManager()

        if validate:
            ConfigValidator().validate(config)

        # Instantiate plugins from registries
        self._features = self._build_features()
        self._methods = self._build_methods()
        self._uncertainty = self._build_uncertainty()
        self._ensemble = self._build_ensemble()

        self._bars_seen = 0

    # ── Public API ──

    def compute(self, request: PipelineRequest) -> RegressionResult:
        """Compute regression for a single bar (live mode).

        Args:
            request: PipelineRequest with df, resolved config, and optional context.

        Returns:
            RegressionResult with degradation level.
        """
        self._bars_seen += 1
        window = request.resolve_window()
        bars = self._extract_bar_arrays(request.df)

        if len(bars) < window:
            return self._empty_result(request, window, DegradationLevel.FAILED)

        window_bars = self._slice_bar_arrays(bars, len(bars) - window, len(bars))

        return self._compute_window(request, window_bars, window)

    def compute_series(self, request: PipelineRequest) -> List[RegressionResult]:
        """Compute regression over a rolling window (backtest mode).

        Resets all stateful components, then loops from window to end.
        """
        self.reset()
        window = request.resolve_window()
        bars = self._extract_bar_arrays(request.df)
        results = []

        if len(bars) < window:
            return results

        for end in range(window, len(bars) + 1):
            self._bars_seen += 1
            window_bars = self._slice_bar_arrays(bars, end - window, end)
            result = self._compute_window(request, window_bars, window)
            results.append(result)

        return results

    def reset(self) -> None:
        """Reset all stateful components."""
        self._bars_seen = 0
        for method in self._methods.values():
            method.reset_state()
        self._ensemble.reset_state()

    def _compute_window(
        self,
        request: PipelineRequest,
        bars: _BarArrays,
        window: int,
    ) -> RegressionResult:
        # Stage 1: Feature extraction
        features, feat_degradation = self._run_features(request, bars)
        if features is None:
            return self._empty_result(request, window, DegradationLevel.FAILED)

        # Apply valid_mask
        mask = features.valid_mask
        n_valid = int(np.sum(mask))
        if n_valid < 3:
            return self._empty_result(request, window, DegradationLevel.FAILED)

        X_valid = np.arange(len(mask), dtype=np.float64)[mask]
        y_valid = features.log_prices[mask]
        w_valid = features.weights[mask]
        X_full = np.arange(len(mask), dtype=np.float64)

        # Stage 2: Method fitting
        method_results, method_degradation = self._run_methods(
            request, X_valid, y_valid, w_valid, X_full, features
        )
        if not method_results:
            return self._empty_result(request, window, DegradationLevel.FAILED)

        # Stage 3: Uncertainty wrapping (per-method bands)
        method_results = self._run_uncertainty(
            request, method_results, X_valid, y_valid, w_valid, X_full
        )

        # Compute ATR before ensemble — direction classification needs atr_norm
        atr_norm = self._compute_atr_norm(bars)
        request.metadata["atr_norm"] = atr_norm

        # Stage 4: Ensemble
        ensemble_result = self._run_ensemble(request, method_results)

        # Build mid-line and parallel bands from ensemble
        mid_line, upper_band, lower_band = self._build_bands(
            ensemble_result, X_full
        )

        # Z-score
        z_score = self._compute_z_score(
            features.close_raw[-1], mid_line, upper_band, lower_band
        )

        # Overall degradation
        degradation = self._aggregate_degradation(
            feat_degradation, method_degradation, ensemble_result.degradation
        )

        result = RegressionResult(
            asset=request.asset,
            timeframe=request.timeframe,
            timestamp=datetime.now(timezone.utc),
            config_hash=request.config.config_hash,
            slope=ensemble_result.slope,
            direction=ensemble_result.direction,
            confidence=ensemble_result.confidence,
            upper_band=upper_band,
            lower_band=lower_band,
            mid_line=mid_line,
            band_width_avg=float(np.mean(upper_band - lower_band)),
            atr_norm=atr_norm,
            z_score=z_score,
            method_outputs={name: r for name, r in method_results.items()},
            method_weights=ensemble_result.method_weights,
            ensemble_result=ensemble_result,
            signals=[],
            window_used=window,
            warm_up_bars_needed=self._max_warmup(),
            is_warmed_up=self._bars_seen >= self._max_warmup(),
            bars_since_init=self._bars_seen,
            regime_applied=request.regime is not None and request.config.regime_context_enabled,
            mtf_applied=request.cascade is not None,
            is_valid=ensemble_result.is_valid,
            degradation=degradation,
        )

        return result

    # ── Stage Runners ──

    def _run_features(
        self, request: PipelineRequest, bars: _BarArrays
    ) -> tuple[Optional[FeatureSet], DegradationLevel]:
        n = len(bars)
        features = FeatureSet(
            valid_mask=np.ones(n, dtype=bool),
            timestamps=bars.timestamps,
            close_raw=bars.close_raw,
            log_prices=np.empty(n, dtype=np.float64),
            weights=np.ones(n, dtype=np.float64),
            volume_raw=bars.volume_raw,
            volume_clipped=np.empty(n, dtype=np.float64),
        )

        degradation = DegradationLevel.FULL
        for extractor in self._features:
            try:
                extractor.extract(request, features)
            except Exception as e:
                logger.warning("Feature extractor %s failed: %s", type(extractor).__name__, e)
                degradation = DegradationLevel.PARTIAL

        # Session-aware emits a mask; apply it once after all extractors have run so
        # every downstream method sees the same effective validity and weights.
        if features.session_mask is not None:
            session_mask = np.asarray(features.session_mask, dtype=bool)
            features.session_mask = session_mask
            features.valid_mask &= session_mask
            features.weights[~session_mask] = 0.0

        return features, degradation

    def _run_methods(
        self,
        request: PipelineRequest,
        X_valid: np.ndarray,
        y_valid: np.ndarray,
        w_valid: np.ndarray,
        X_full: np.ndarray,
        features: FeatureSet,
    ) -> tuple[Dict[str, MethodResult], DegradationLevel]:
        results: Dict[str, MethodResult] = {}
        degradation = DegradationLevel.FULL

        for name, method in self._methods.items():
            try:
                # Load state if stateful
                if method.stateful:
                    method.load_state(self.state_manager, request.asset, request.timeframe)

                method.fit(X_valid, y_valid, w_valid, request.config)
                slope = method.get_slope()
                conf = method.get_confidence()

                # Center line in price space
                center = np.exp(slope * X_full + method.intercept)

                result = MethodResult(
                    method_name=name,
                    slope=slope,
                    intercept=method.intercept,
                    center=center,
                    confidence=conf,
                    r_squared=method.get_metadata().get("r_squared", 0.0),
                    is_valid=method.is_valid,
                    band_type=method.band_type,
                    metadata=method.get_metadata(),
                )
                results[name] = result

                # Save state if stateful
                if method.stateful:
                    method.save_state(self.state_manager, request.asset, request.timeframe)

            except Exception as e:
                logger.warning("Method %s failed: %s", name, e)
                degradation = DegradationLevel.PARTIAL

        return results, degradation

    def _run_uncertainty(
        self,
        request: PipelineRequest,
        method_results: Dict[str, MethodResult],
        X_valid: np.ndarray,
        y_valid: np.ndarray,
        w_valid: np.ndarray,
        X_full: np.ndarray,
    ) -> Dict[str, MethodResult]:
        for name, result in method_results.items():
            if not result.is_valid:
                continue
            try:
                upper, lower, mid = self._uncertainty.wrap(
                    X_valid, y_valid, w_valid,
                    result.slope, result.intercept,
                    request.config.band_multiplier,
                    X_full,
                    request.config,
                )
                result.upper = upper
                result.lower = lower
                result.center = mid
            except Exception as e:
                logger.warning("Uncertainty wrapping failed for %s: %s", name, e)

        return method_results

    def _run_ensemble(
        self,
        request: PipelineRequest,
        method_results: Dict[str, MethodResult],
    ) -> EnsembleResult:
        try:
            if self._ensemble.stateful:
                self._ensemble.load_state(self.state_manager, request.asset, request.timeframe)

            result = self._ensemble.combine(method_results, request, request.cascade)

            if self._ensemble.stateful:
                self._ensemble.save_state(self.state_manager, request.asset, request.timeframe)

            return result
        except Exception as e:
            logger.warning("Ensemble failed: %s", e)
            return EnsembleResult(
                center=0.0,
                is_valid=False,
                degradation=DegradationLevel.FAILED,
            )

    # ── Helpers ──

    def _extract_bar_arrays(self, df: pd.DataFrame) -> _BarArrays:
        close_raw = df["close"].to_numpy(dtype=np.float64, copy=False)
        high_raw = (
            df["high"].to_numpy(dtype=np.float64, copy=False)
            if "high" in df.columns
            else close_raw
        )
        low_raw = (
            df["low"].to_numpy(dtype=np.float64, copy=False)
            if "low" in df.columns
            else close_raw
        )
        volume_raw = (
            df["volume"].to_numpy(dtype=np.float64, copy=False)
            if "volume" in df.columns
            else np.ones(len(df), dtype=np.float64)
        )

        return _BarArrays(
            timestamps=df.index.to_numpy(copy=False),
            close_raw=close_raw,
            high_raw=high_raw,
            low_raw=low_raw,
            volume_raw=volume_raw,
        )

    def _slice_bar_arrays(self, bars: _BarArrays, start: int, end: int) -> _BarArrays:
        return _BarArrays(
            timestamps=bars.timestamps[start:end],
            close_raw=bars.close_raw[start:end],
            high_raw=bars.high_raw[start:end],
            low_raw=bars.low_raw[start:end],
            volume_raw=bars.volume_raw[start:end],
        )

    def _build_features(self) -> list:
        extractors = []
        for fc in self.config.features:
            if not fc.enabled:
                continue
            if FeatureRegistry.has(fc.name):
                cls = FeatureRegistry.get(fc.name)
                extractors.append(cls(fc))
            else:
                logger.warning("Feature plugin '%s' not registered, skipping", fc.name)
        return extractors

    def _build_methods(self) -> Dict[str, "RegressionMethod"]:
        methods = {}
        for name, mc in self.config.methods:
            if not mc.enabled:
                continue
            if MethodRegistry.has(name):
                cls = MethodRegistry.get(name)
                methods[name] = cls(name, mc)
            else:
                logger.warning("Method plugin '%s' not registered, skipping", name)
        return methods

    def _build_uncertainty(self):
        uc = self.config.uncertainty
        if UncertaintyRegistry.has(uc.name):
            cls = UncertaintyRegistry.get(uc.name)
            return cls(uc)
        logger.warning("Uncertainty plugin '%s' not registered", uc.name)
        return _StubUncertainty(uc)

    def _build_ensemble(self):
        ec = self.config.ensemble
        if EnsembleRegistry.has(ec.name):
            cls = EnsembleRegistry.get(ec.name)
            return cls(ec)
        logger.warning("Ensemble plugin '%s' not registered", ec.name)
        return _StubEnsemble(ec)

    def _compute_atr_norm(self, bars: _BarArrays) -> float:
        high = bars.high_raw
        low = bars.low_raw
        close = bars.close_raw

        if len(close) < 2:
            return 0.0

        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            ),
        )
        period = min(self.config.atr_period, len(tr))
        atr = np.mean(tr[-period:])
        return float(atr / close[-1]) if close[-1] > 0 else 0.0

    def _build_bands(
        self, ensemble: EnsembleResult, X_full: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if ensemble.slope == 0.0 and ensemble.intercept == 0.0:
            empty = np.zeros(len(X_full))
            return empty, empty, empty

        mid_line = np.exp(ensemble.slope * X_full + ensemble.intercept)

        if ensemble.upper is not None and ensemble.lower is not None:
            upper_dist = ensemble.upper - ensemble.center
            lower_dist = ensemble.center - ensemble.lower
            upper_band = mid_line + upper_dist
            lower_band = mid_line - lower_dist
        else:
            upper_band = mid_line
            lower_band = mid_line

        return mid_line, upper_band, lower_band

    def _compute_z_score(
        self,
        current_close: float,
        mid_line: np.ndarray,
        upper_band: np.ndarray,
        lower_band: np.ndarray,
    ) -> float:
        if len(mid_line) == 0:
            return 0.0
        center = mid_line[-1]
        half_width = (upper_band[-1] - lower_band[-1]) / 2
        if half_width <= 0:
            return 0.0
        return float((current_close - center) / half_width)

    def _max_warmup(self) -> int:
        warmups = [f.min_warmup_bars for f in self._features]
        warmups.extend(m.min_warmup_bars for m in self._methods.values())
        return max(warmups) if warmups else 0

    def _aggregate_degradation(self, *levels: DegradationLevel) -> DegradationLevel:
        priority = {
            DegradationLevel.FAILED: 3,
            DegradationLevel.FALLBACK: 2,
            DegradationLevel.PARTIAL: 1,
            DegradationLevel.FULL: 0,
        }
        worst = max(levels, key=lambda l: priority.get(l, 0))
        return worst

    def _empty_result(
        self, request: PipelineRequest, window: int, degradation: DegradationLevel
    ) -> RegressionResult:
        empty = np.array([])
        return RegressionResult(
            asset=request.asset,
            timeframe=request.timeframe,
            timestamp=datetime.now(timezone.utc),
            config_hash=request.config.config_hash,
            slope=0.0,
            direction="NEUTRAL",
            confidence=0.0,
            upper_band=empty,
            lower_band=empty,
            mid_line=empty,
            band_width_avg=0.0,
            atr_norm=0.0,
            z_score=0.0,
            method_outputs={},
            method_weights={},
            ensemble_result=EnsembleResult(center=0.0, is_valid=False, degradation=degradation),
            window_used=window,
            is_valid=False,
            degradation=degradation,
        )


# ── Stub plugins for graceful degradation when registry is empty ──


class _StubUncertainty:
    def __init__(self, config):
        self.config = config

    def wrap(self, X_valid, y_valid, w_valid, slope, intercept, multiplier, X_full, pipeline_config):
        mid = np.exp(slope * X_full + intercept)
        return mid, mid, mid


class _StubEnsemble:
    def __init__(self, config):
        self.config = config
        self.stateful = False

    def combine(self, results, request, cascade=None):
        return EnsembleResult(center=0.0, is_valid=False, degradation=DegradationLevel.FAILED)

    def reset_state(self):
        pass
