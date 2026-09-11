"""Self-sufficient trendlines-native signal orchestrator."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from libs.models.trendlines.boundary import BoundaryResult
from libs.models.trendlines.config import TrendlinesConfig
from libs.models.trendlines.config.resolve import ResolvedConfig, ResolvedSignalConfig
from libs.models.trendlines.contracts.identity import (
    TrendlineSnapshotStage,
    canonical_point_text,
)

from .base import AlphaSignal, BaseAlphaExtractor
from .context import (
    SignalContextContractError,
    TrendlineSignalInputs,
    ValidatedTrendlineSignalInputs,
    validate_signal_inputs,
)
from .fakeout import FakeoutAlphaExtractor
from .patterns import PatternAlphaExtractor
from .structural import StructuralAlphaExtractor
from .temporal import TemporalAlphaExtractor

logger = logging.getLogger("libs.models.trendlines.signals.orchestrator")


def _build_extractors_from_resolved(sig: ResolvedSignalConfig) -> list[BaseAlphaExtractor]:
    """Build extractor instances from a resolved signal config."""
    return [
        StructuralAlphaExtractor(
            asymmetry_threshold=sig.asymmetry_threshold,
            squeeze_threshold=sig.squeeze_threshold,
            full_confidence_touches=sig.full_confidence_touches_structural,
        ),
        TemporalAlphaExtractor(
            min_history=sig.min_history,
            slope_match_tol=sig.slope_match_tol,
            convergence_rate_threshold=sig.convergence_rate_threshold,
            slope_accel_threshold=sig.slope_accel_threshold,
            state_transitions=sig.state_transitions,
        ),
        PatternAlphaExtractor(
            parallel_tol=sig.parallel_tol,
            flat_tol=sig.flat_tol,
            full_confidence_touches=sig.full_confidence_touches_pattern,
        ),
        FakeoutAlphaExtractor(
            hold_bars=sig.hold_bars,
            volume_lookback=sig.volume_lookback,
            wick_rejection_ratio=sig.wick_rejection_ratio,
        ),
    ]


class TrendlineSignalOrchestrator:
    """Run native trendlines signal extractors and aggregate their outputs."""

    DEFAULT_EXTRACTORS = [
        StructuralAlphaExtractor,
        TemporalAlphaExtractor,
        PatternAlphaExtractor,
        FakeoutAlphaExtractor,
    ]

    def __init__(
        self,
        extractors: Optional[List[BaseAlphaExtractor]] = None,
        weights: Optional[Dict[str, float]] = None,
        trendlines_config: TrendlinesConfig | None = None,
        resolved_config: ResolvedConfig | None = None,
    ):
        if extractors is not None:
            self._extractors = list(extractors)
        elif resolved_config is not None:
            self._extractors = _build_extractors_from_resolved(resolved_config.signals)
        elif trendlines_config is not None:
            # Legacy path: use TrendlinesConfig backward-compat shim
            from libs.models.trendlines.config.state_transitions import build_state_transition_table

            self._extractors = [
                StructuralAlphaExtractor(
                    asymmetry_threshold=trendlines_config.defaults.asymmetry_threshold,
                    squeeze_threshold=trendlines_config.defaults.squeeze_threshold,
                ),
                TemporalAlphaExtractor(
                    convergence_rate_threshold=trendlines_config.defaults.convergence_rate_threshold,
                    state_transitions=build_state_transition_table(),
                ),
                PatternAlphaExtractor(),
                FakeoutAlphaExtractor(
                    wick_rejection_ratio=trendlines_config.defaults.wick_rejection_ratio,
                ),
            ]
        else:
            self._extractors = [cls() for cls in self.DEFAULT_EXTRACTORS]

        # Weights resolution
        resolved_weights: Dict[str, float] = {}
        if resolved_config is not None:
            resolved_weights = dict(resolved_config.signals.weights)
        elif trendlines_config is not None:
            resolved_weights = dict(trendlines_config.signal_weights)
        explicit_weights = {
            str(source): float(weight)
            for source, weight in dict(weights or {}).items()
        }
        self._weights: Dict[str, float] = {**resolved_weights, **explicit_weights}

    @property
    def extractor_names(self) -> List[str]:
        return [extractor.name for extractor in self._extractors]

    def run(
        self,
        result: BoundaryResult,
        *,
        signal_inputs: TrendlineSignalInputs,
        frame: pd.DataFrame,
        validation: ValidatedTrendlineSignalInputs | None = None,
    ) -> Dict[str, Any]:
        if not isinstance(frame, pd.DataFrame):
            raise SignalContextContractError("frame must be a pandas DataFrame")
        if validation is None:
            validated = validate_signal_inputs(frame, result, signal_inputs)
        else:
            if not isinstance(validation, ValidatedTrendlineSignalInputs):
                raise SignalContextContractError(
                    "validation must be ValidatedTrendlineSignalInputs"
                )
            identity = result.snapshot_identity
            if validation.inputs is not signal_inputs:
                raise SignalContextContractError(
                    "signal validation does not match supplied signal_inputs"
                )
            if identity is None:
                raise SignalContextContractError(
                    "validated signal inputs require an identity-bearing boundary"
                )
            if identity.stage is not TrendlineSnapshotStage.BOUNDARY:
                raise SignalContextContractError(
                    "validated signal inputs require a boundary-stage identity"
                )
            if identity.asset != result.asset or identity.timeframe != result.timeframe:
                raise SignalContextContractError(
                    "validated signal inputs do not match boundary scope"
                )
            if identity.checkpoint.source.as_of != canonical_point_text(result.timestamp):
                raise SignalContextContractError(
                    "validated signal inputs do not match boundary horizon"
                )
            expected_binding = (
                identity.snapshot_id,
                identity.checkpoint.checkpoint_id,
                identity.checkpoint.source.source_id,
            )
            actual_binding = (
                validation.boundary_snapshot_id,
                validation.checkpoint_id,
                validation.source_id,
            )
            if actual_binding != expected_binding:
                raise SignalContextContractError(
                    "validated signal inputs do not belong to supplied boundary"
                )
            validated = validation

        history = list(validated.history_boundaries)
        context: Dict[str, Any] = {
            "atr": result.boundary_context.get("latest_atr"),
            "volume_is_trustworthy": validated.context.volume_is_trustworthy,
        }
        context["ohlcv"] = frame

        all_signals: List[AlphaSignal] = []
        by_source: Dict[str, List[AlphaSignal]] = {}

        for extractor in self._extractors:
            try:
                sigs = extractor.extract(result, history=history, context=context)
                all_signals.extend(sigs)
                by_source[extractor.name] = sigs
            except Exception as exc:
                logger.warning(
                    "Trendline signal extractor failed: %s (%s)",
                    extractor.name,
                    exc.__class__.__name__,
                )
                by_source[extractor.name] = []

        composite_dir, composite_conf = self._compute_composite(all_signals)

        return {
            "signals": all_signals,
            "composite_direction": composite_dir,
            "composite_confidence": composite_conf,
            "signal_count": len(all_signals),
            "by_source": by_source,
            **validated.metadata(),
        }

    def _compute_composite(self, signals: List[AlphaSignal]) -> tuple[float, float]:
        if not signals:
            return 0.0, 0.0

        weighted_dir = 0.0
        weighted_conf = 0.0
        total_weight = 0.0

        for signal in signals:
            weight = self._weights.get(signal.source, 1.0)
            weighted_dir += signal.direction * signal.confidence * weight
            weighted_conf += signal.confidence * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0, 0.0

        comp_dir = max(-1.0, min(1.0, weighted_dir / total_weight))
        comp_conf = min(1.0, weighted_conf / total_weight)
        return round(comp_dir, 4), round(comp_conf, 4)

    def to_dict(
        self,
        result: BoundaryResult,
        *,
        signal_inputs: TrendlineSignalInputs,
        frame: pd.DataFrame,
    ) -> Dict[str, Any]:
        output = self.run(result, signal_inputs=signal_inputs, frame=frame)
        return {
            "composite_direction": output["composite_direction"],
            "composite_confidence": output["composite_confidence"],
            "signal_count": output["signal_count"],
            "signals": [signal.to_dict() for signal in output["signals"]],
            "signal_input_id": output["signal_input_id"],
        }


__all__ = ["TrendlineSignalOrchestrator"]
