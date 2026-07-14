"""Opt-in shadow adapter for the independent trendline-family model.

This adapter is deliberately outside RegimeV2 evidence, policy, routing, and
selection inputs. It invokes only the public trendline-family update API and
projects persisted snapshot evidence onto a namespaced shadow payload.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
from time import perf_counter_ns
from typing import Any

import pandas as pd

from libs.models.trendline_family.api import update_trendline_families
from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig
from libs.models.trendline_family.contracts import (
    ContractValidationError,
    FamilyRole,
    FamilyTransitionType,
    TrendlineFamilyOutput,
    TrendlineFamilyState,
)
from libs.models.trendline_family.mtf import MTFGeometrySnapshot, build_mtf_shadow_features
from libs.models.trendline_family.provider import LineCandidateProvider
from libs.models.trendline_family.repository import (
    InMemoryTrendlineFamilyRepository,
    SnapshotVersionError,
    TrendlineFamilyRepository,
)

logger = logging.getLogger(__name__)

_CONFIG_KEYS = frozenset({"enabled", "config_path"})
_CONTINUATION_TRANSITIONS = frozenset(
    {
        FamilyTransitionType.CONTINUE,
        FamilyTransitionType.STRENGTHEN,
        FamilyTransitionType.WEAKEN,
    }
)


FeatureProjector = Callable[..., dict[str, Any]]
MTFSnapshotProvider = Callable[[], MTFGeometrySnapshot | None]


@dataclass(frozen=True)
class TrendlineFamilyShadowConfig:
    """Typed enablement for the diagnostic-only family feature producer."""

    enabled: bool = False
    config_path: str = "configs/trendline_family.yaml"

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("trendline-family shadow enabled must be boolean")
        if not isinstance(self.config_path, str) or not self.config_path:
            raise ValueError("trendline-family shadow config_path must be a non-empty string")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TrendlineFamilyShadowConfig":
        if not isinstance(value, Mapping):
            raise ValueError("trendline-family shadow config must be a mapping")
        unknown = set(value) - _CONFIG_KEYS
        if unknown:
            raise ValueError(f"unknown trendline-family shadow config keys: {sorted(unknown)}")
        return cls(
            enabled=value.get("enabled", False),
            config_path=value.get("config_path", "configs/trendline_family.yaml"),
        )


class FailedTrendlineFamilyShadowProducer:
    """Diagnostic-only producer used when explicitly enabled setup cannot start."""

    min_bars = 0

    def __init__(self, *, error_type: str, error_reason: str) -> None:
        self.error_type = error_type
        self.error_reason = error_reason

    def analyze(self, ohlcv: pd.DataFrame, **_: Any) -> dict[str, Any]:
        """Return a stable enabled failure without touching family state."""

        del ohlcv
        return build_trendline_family_shadow_failure_payload(
            error_type=self.error_type,
            error_reason=self.error_reason,
            state_advanced=False,
        )


class TrendlineFamilyFeatureProducer:
    """Produce persisted family evidence on a shadow-only namespace.

    ``trendline_family_latency_ms`` is operational data. Tests that require
    byte-identical replay inject a deterministic ``clock``; production uses a
    monotonic clock and should aggregate that field separately from semantic
    feature equality.
    """

    min_bars = 0

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        shadow_config: TrendlineFamilyShadowConfig | None = None,
        repository: TrendlineFamilyRepository | None = None,
        resolved_config: ResolvedTrendlineFamilyConfig | None = None,
        provider: LineCandidateProvider | None = None,
        runtime_override: Mapping[str, Any] | None = None,
        clock: Callable[[], int] = perf_counter_ns,
        feature_projector: FeatureProjector | None = None,
        mtf_snapshot_provider: MTFSnapshotProvider | None = None,
    ) -> None:
        if not isinstance(asset, str) or not asset:
            raise ValueError("asset must be a non-empty string")
        if not isinstance(timeframe, str) or not timeframe:
            raise ValueError("timeframe must be a non-empty string")
        if shadow_config is not None and not isinstance(shadow_config, TrendlineFamilyShadowConfig):
            raise ValueError("shadow_config must be TrendlineFamilyShadowConfig")
        if resolved_config is not None and not isinstance(resolved_config, ResolvedTrendlineFamilyConfig):
            raise ValueError("resolved_config must be ResolvedTrendlineFamilyConfig")
        if runtime_override is not None and not isinstance(runtime_override, Mapping):
            raise ValueError("runtime_override must be a mapping when supplied")
        if mtf_snapshot_provider is not None and not callable(mtf_snapshot_provider):
            raise ValueError("mtf_snapshot_provider must be callable when supplied")
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.shadow_config = shadow_config or TrendlineFamilyShadowConfig()
        self.repository = repository or InMemoryTrendlineFamilyRepository()
        self.resolved_config = resolved_config
        self.provider = provider
        self.runtime_override = runtime_override
        self._clock = clock
        self._feature_projector = feature_projector or _features_from_output
        self._mtf_snapshot_provider = mtf_snapshot_provider

    def analyze(
        self,
        ohlcv: pd.DataFrame,
        *,
        observed_at: datetime | None = None,
        runtime_override: Mapping[str, Any] | None = None,
        tick_size: float | None = None,
    ) -> dict[str, Any]:
        """Run one confirmed-bar update without exposing failures to RegimeV2."""

        if not self.shadow_config.enabled:
            return _base_features(enabled=False)

        started_at = _safe_clock_read(self._clock)
        head_before: str | None = None
        head_before_known = False
        try:
            head_before = _repository_head_id(self.repository, self.asset, self.timeframe)
            head_before_known = True
            output = update_trendline_families(
                ohlcv,
                asset=self.asset,
                timeframe=self.timeframe,
                repository=self.repository,
                config=self.resolved_config,
                config_path=Path(self.shadow_config.config_path),
                runtime_override=self.runtime_override if runtime_override is None else runtime_override,
                provider=self.provider,
                observed_at=observed_at,
                tick_size=tick_size,
            )
            features = self._feature_projector(
                output,
                head_before=head_before,
                # Final operational latency is captured after the repository head audit.
                latency_ms=0.0,
            )
            _attach_mtf_shadow_features(
                features,
                self._mtf_snapshot_provider,
                output=output,
            )
            head_after = _repository_head_id(self.repository, self.asset, self.timeframe)
            return _finalize_success_features(
                features,
                head_before=head_before,
                head_after=head_after,
                latency_ms=_safe_elapsed_ms(started_at, self._clock),
            )
        except ContractValidationError as exc:
            head_after, head_after_known = _safe_repository_head_id(
                self.repository,
                self.asset,
                self.timeframe,
            )
            return _failure_features(
                enabled=True,
                error_type=_expected_error_type(exc),
                error_reason=_expected_error_reason(exc),
                head_before=head_before,
                head_after=head_after,
                latency_ms=_safe_elapsed_ms(started_at, self._clock),
                state_advanced=_state_advanced(
                    head_before,
                    head_after,
                    head_before_known=head_before_known,
                    head_after_known=head_after_known,
                ),
            )
        except Exception as exc:  # pragma: no cover - final shadow safety boundary
            logger.exception(
                "Trendline-family shadow producer failed for %s:%s", self.asset, self.timeframe
            )
            head_after, head_after_known = _safe_repository_head_id(
                self.repository,
                self.asset,
                self.timeframe,
            )
            return _failure_features(
                enabled=True,
                error_type="unexpected_error",
                error_reason=exc.__class__.__name__,
                head_before=head_before,
                head_after=head_after,
                latency_ms=_safe_elapsed_ms(started_at, self._clock),
                state_advanced=_state_advanced(
                    head_before,
                    head_after,
                    head_before_known=head_before_known,
                    head_after_known=head_after_known,
                ),
            )


def summarize_trendline_family_shadow_artifacts(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate stream/debug shadow payloads without writing a new log format."""

    payloads = [_shadow_payload(record) for record in records]
    payloads = [payload for payload in payloads if payload is not None]
    enabled = [payload for payload in payloads if payload.get("trendline_family_shadow_enabled") is True]
    valid = [payload for payload in enabled if payload.get("trendline_family_valid") is True]
    invalid = [payload for payload in enabled if payload.get("trendline_family_valid") is not True]
    latencies = [_number(payload.get("trendline_family_latency_ms")) for payload in enabled]
    latencies = [value for value in latencies if value is not None]
    return {
        "summary": {
            "record_count": len(payloads),
            "enabled_row_count": len(enabled),
            "valid_row_count": len(valid),
            "invalid_or_error_row_count": len(invalid),
            "repository_state_advanced_count": sum(
                payload.get("trendline_family_state_advanced") is True for payload in enabled
            ),
            "nearest_support_coverage_count": sum(
                payload.get("nearest_support_family_id") is not None for payload in valid
            ),
            "nearest_resistance_coverage_count": sum(
                payload.get("nearest_resistance_family_id") is not None for payload in valid
            ),
        },
        "distributions": {
            "provider_status": _distribution(enabled, "trendline_family_provider_status"),
            "error_type": _distribution(invalid, "trendline_family_error_type"),
            "error_reason": _distribution(invalid, "trendline_family_error_reason"),
            "active_family_count": _distribution(enabled, "trendline_family_count_active"),
            "dormant_family_count": _distribution(enabled, "trendline_family_count_dormant"),
            "birth_count": _distribution(enabled, "trendline_family_births"),
            "dormancy_count": _distribution(enabled, "trendline_family_dormancies"),
            "reactivation_count": _distribution(enabled, "trendline_family_reactivations"),
            "expiry_count": _distribution(enabled, "trendline_family_expiries"),
            "churn_count": _distribution(enabled, "trendline_family_churn_count"),
            "support_interaction_state": _distribution(valid, "support_interaction_state"),
            "resistance_interaction_state": _distribution(valid, "resistance_interaction_state"),
            "event_state": _sequence_distribution(valid, "trendline_family_event_state_values"),
            "break_pending_count": _distribution(enabled, "trendline_family_break_pending_count"),
            "break_confirmed_count": _distribution(enabled, "trendline_family_break_confirmed_count"),
            "retest_pending_count": _distribution(enabled, "trendline_family_retest_pending_count"),
            "retest_success_count": _distribution(enabled, "trendline_family_retest_success_count"),
            "failed_break_count": _distribution(enabled, "trendline_family_failed_break_count"),
            "role_reversal_count": _distribution(enabled, "trendline_family_role_reversal_count"),
            "pressure_duration": _sequence_distribution(valid, "trendline_family_event_pressure_bars"),
            "confirmation_streak": _sequence_distribution(valid, "trendline_family_event_confirmation_streaks"),
            "rail_count": _sequence_distribution(valid, "trendline_family_rail_counts"),
            "corridor_width_atr": _sequence_distribution(valid, "trendline_family_corridor_width_atr_values"),
            "adjacent_gap_atr": _sequence_distribution(valid, "trendline_family_adjacent_gap_atr_values"),
            "spacing_stability": _sequence_distribution(valid, "trendline_family_spacing_stability_values"),
            "grouping_rejection_reason": _sequence_distribution(valid, "trendline_family_rail_grouping_rejection_reasons"),
            "mtf_source_timeframe_count": _mtf_distribution(enabled, "source_timeframe_count"),
            "mtf_source_timeframe_coverage": _mtf_sequence_distribution(enabled, "source_timeframes"),
            "mtf_source_age_bars": _mtf_sequence_distribution(enabled, "source_age_bars"),
            "mtf_fresh_source_count": _mtf_distribution(enabled, "fresh_source_count"),
            "mtf_stale_included_source_count": _mtf_distribution(enabled, "stale_included_source_count"),
            "mtf_stale_excluded_source_count": _mtf_distribution(enabled, "stale_excluded_source_count"),
            "mtf_projected_family_count": _mtf_distribution(enabled, "projected_family_count"),
            "mtf_cluster_size": _mtf_sequence_distribution(enabled, "cluster_family_sizes"),
            "mtf_cluster_family_size": _mtf_sequence_distribution(enabled, "cluster_family_sizes"),
            "mtf_cluster_distinct_timeframe_count": _mtf_sequence_distribution(enabled, "cluster_timeframe_counts"),
            "mtf_confluence_strength": _mtf_sequence_distribution(enabled, "confluence_strengths"),
            "mtf_normalized_slope_dispersion": _mtf_sequence_distribution(enabled, "normalized_slope_dispersion_values"),
            "mtf_corridor_overlap_ratio": _mtf_sequence_distribution(enabled, "corridor_overlap_ratio_values"),
            "mtf_agreement_relation_count": _mtf_distribution(enabled, "agreement_relation_count"),
            "mtf_conflict_relation_count": _mtf_distribution(enabled, "conflict_relation_count"),
            "mtf_intersection_relation_count": _mtf_distribution(enabled, "intersection_relation_count"),
            "mtf_intersection_seconds_from_decision": _mtf_sequence_distribution(enabled, "intersection_seconds_from_decision_values"),
            "mtf_intersection_horizon_seconds": _mtf_sequence_distribution(enabled, "intersection_horizon_seconds_values"),
            "mtf_exclusion_reason": _mtf_reason_distribution(enabled),
        },
        "latency_ms": _latency_summary(latencies),
    }


def _features_from_output(
    output: TrendlineFamilyOutput,
    *,
    head_before: str | None,
    latency_ms: float,
) -> dict[str, Any]:
    snapshot = output.snapshot
    diagnostics = snapshot.diagnostics
    transition_counts = Counter(transition.transition_type for transition in snapshot.transitions)
    features = _base_features(enabled=True)
    features.update(
        {
            "trendline_family_valid": True,
            "trendline_family_model_version": snapshot.model_version,
            "trendline_family_config_version": snapshot.config_version,
            "trendline_family_resolved_config_hash": snapshot.resolved_config_hash,
            "trendline_family_snapshot_id": snapshot.snapshot_id,
            "trendline_family_previous_snapshot_id": snapshot.previous_snapshot_id,
            "trendline_family_timestamp": snapshot.timestamp.isoformat(),
            "trendline_family_asset": snapshot.asset,
            "trendline_family_timeframe": snapshot.timeframe,
            "trendline_family_count_active": len(snapshot.active_families),
            "trendline_family_count_dormant": len(snapshot.dormant_families),
            "trendline_family_births": transition_counts[FamilyTransitionType.BIRTH],
            # Updates are only stable continuation/version-strength transitions.
            "trendline_family_updates": sum(
                transition_counts[transition_type]
                for transition_type in _CONTINUATION_TRANSITIONS
            ),
            "trendline_family_dormancies": transition_counts[FamilyTransitionType.DORMANT],
            "trendline_family_reactivations": transition_counts[FamilyTransitionType.REACTIVATE],
            "trendline_family_expiries": transition_counts[FamilyTransitionType.EXPIRE],
            "trendline_family_churn_count": diagnostics.get("family_churn_count"),
            "trendline_family_churn_rate": diagnostics.get("family_churn_rate"),
            "trendline_family_generated_candidate_count": diagnostics.get("generated_candidate_count"),
            "trendline_family_matched_count": diagnostics.get("matched_count"),
            "trendline_family_rejected_birth_count": diagnostics.get("rejected_birth_count"),
            "trendline_family_provider_status": diagnostics.get("provider_status"),
            "trendline_family_provider_reason_codes": diagnostics.get("provider_reason_codes"),
            "trendline_family_normalization_atr": diagnostics.get("normalization_atr"),
            "trendline_family_interaction_atr": diagnostics.get("interaction_atr"),
            "trendline_family_interaction_observation_count": diagnostics.get(
                "interaction_observation_count"
            ),
            "trendline_family_corridor_count": output.features.get("trendline_family_corridor_count"),
            "trendline_family_singleton_count": output.features.get("trendline_family_singleton_count"),
            "trendline_family_multi_rail_count": output.features.get("trendline_family_multi_rail_count"),
            "trendline_family_total_rail_count": output.features.get("trendline_family_total_rail_count"),
            "trendline_family_rail_counts": tuple(
                corridor.rail_count for corridor in snapshot.corridors
            ),
            "trendline_family_corridor_width_atr_values": tuple(
                corridor.width_atr for corridor in snapshot.corridors
            ),
            "trendline_family_adjacent_gap_atr_values": tuple(
                corridor.max_adjacent_gap_atr
                for corridor in snapshot.corridors
                if corridor.max_adjacent_gap_atr is not None
            ),
            "trendline_family_spacing_stability_values": tuple(
                corridor.spacing_stability
                for corridor in snapshot.corridors
                if corridor.spacing_stability is not None
            ),
            "trendline_family_member_additions": tuple(
                member_id
                for transition in snapshot.transitions
                for member_id in transition.added_member_ids
            ),
            "trendline_family_member_removals": tuple(
                member_id
                for transition in snapshot.transitions
                for member_id in transition.removed_member_ids
            ),
            "trendline_family_representative_change_count": sum(
                transition.representative_changed for transition in snapshot.transitions
            ),
            "trendline_family_rail_grouping_rejection_reasons": diagnostics.get(
                "rail_grouping_rejection_reasons"
            ),
            "trendline_family_event_count": len(snapshot.interaction_events),
            "trendline_family_event_transition_count": len(snapshot.interaction_event_transitions),
            "trendline_family_event_state_values": tuple(
                event.state.value for event in snapshot.interaction_events
            ),
            "trendline_family_break_pending_count": sum(
                event.state.value == "BREAK_PENDING" for event in snapshot.interaction_events
            ),
            "trendline_family_break_confirmed_count": sum(
                event.state.value == "BREAK_CONFIRMED" for event in snapshot.interaction_events
            ),
            "trendline_family_retest_pending_count": sum(
                event.state.value == "RETEST_PENDING" for event in snapshot.interaction_events
            ),
            "trendline_family_retest_success_count": sum(
                event.state.value == "RETEST_SUCCESS" for event in snapshot.interaction_events
            ),
            "trendline_family_failed_break_count": sum(
                event.state.value == "FAILED_BREAK" for event in snapshot.interaction_events
            ),
            "trendline_family_role_reversal_count": sum(
                event.state.value == "ROLE_REVERSED" for event in snapshot.interaction_events
            ),
            "trendline_family_event_pressure_bars": tuple(
                event.pressure_bars for event in snapshot.interaction_events
            ),
            "trendline_family_event_confirmation_streaks": tuple(
                event.close_beyond_streak for event in snapshot.interaction_events
            ),
            "trendline_family_abstained": diagnostics.get("provider_status") != "valid",
            "trendline_family_abstention_reason": diagnostics.get("provider_reason_codes")
            or None,
            "trendline_family_hypothesis_count": len(snapshot.active_families)
            + len(snapshot.dormant_families),
            "trendline_family_support_count": sum(
                family.current_role is FamilyRole.SUPPORT for family in snapshot.active_families
            ),
            "trendline_family_resistance_count": sum(
                family.current_role is FamilyRole.RESISTANCE for family in snapshot.active_families
            ),
            # Ranking scores are intentionally not persisted in Phase D.
            "trendline_family_top_support_score_gap": None,
            "trendline_family_top_resistance_score_gap": None,
            "trendline_family_ambiguity_reason": "ranking_scores_not_persisted_phase_e",
            "trendline_family_latency_ms": latency_ms,
            "trendline_family_failure_count": 0,
            "trendline_family_success_count": 1,
            "trendline_family_coverage": 1.0,
            "trendline_family_state_advanced": snapshot.snapshot_id != head_before,
            "trendline_family_repository_head_before": head_before,
            "trendline_family_repository_head_after": snapshot.snapshot_id,
        }
    )
    _add_nearest_family_features(features, output)
    features["trendline_family_shadow_feature_count"] = len(features)
    return features


def _finalize_success_features(
    features: dict[str, Any],
    *,
    head_before: str | None,
    head_after: str | None,
    latency_ms: float,
) -> dict[str, Any]:
    """Attach repository facts after projection without trusting output assumptions."""

    features.update(
        {
            "trendline_family_latency_ms": latency_ms,
            "trendline_family_repository_head_before": head_before,
            "trendline_family_repository_head_after": head_after,
            "trendline_family_state_advanced": head_after != head_before,
        }
    )
    features["trendline_family_shadow_feature_count"] = len(features)
    return features


def _add_nearest_family_features(
    features: dict[str, Any],
    output: TrendlineFamilyOutput,
) -> None:
    states = {
        family.family_id: family
        for family in output.snapshot.active_families
    }
    _add_role_features(
        features,
        role="support",
        family_id=output.nearest_support_family_id,
        family=states.get(output.nearest_support_family_id),
        output_features=output.features,
    )
    _add_role_features(
        features,
        role="resistance",
        family_id=output.nearest_resistance_family_id,
        family=states.get(output.nearest_resistance_family_id),
        output_features=output.features,
    )


def _add_role_features(
    features: dict[str, Any],
    *,
    role: str,
    family_id: str | None,
    family: TrendlineFamilyState | None,
    output_features: Mapping[str, Any],
) -> None:
    features[f"nearest_{role}_family_id"] = family_id
    features[f"distance_to_{role}_line_atr"] = output_features.get(
        f"distance_to_{role}_line_atr"
    )
    features[f"distance_to_{role}_zone_atr"] = output_features.get(
        f"distance_to_{role}_zone_atr"
    )
    features[f"{role}_interaction_state"] = output_features.get(
        f"{role}_interaction_state"
    )
    features[f"{role}_wick_penetration_atr"] = output_features.get(
        f"{role}_wick_penetration_atr"
    )
    features[f"{role}_body_penetration_atr"] = output_features.get(
        f"{role}_body_penetration_atr"
    )
    features[f"{role}_close_penetration_atr"] = output_features.get(
        f"{role}_close_penetration_atr"
    )
    for field in (
        "event_id",
        "event_state",
        "event_age_bars",
        "event_bars_in_state",
        "pressure_bars",
        "close_beyond_streak",
        "retest_age_bars",
        "max_wick_penetration_atr",
        "max_body_penetration_atr",
        "max_close_penetration_atr",
        "pending_role_reversal",
        "event_compatibility_label",
    ):
        features[f"{role}_{field}"] = output_features.get(f"{role}_{field}")
    for field in (
        "family_age_bars",
        "family_confidence",
        "structural_importance",
        "current_relevance",
        "effective_touch_count",
        "breach_count",
        "bars_since_touch",
        "bars_since_match",
        "projection_horizon_bars",
        "rail_count",
        "ordered_member_ids",
        "representative_member_id",
        "corridor_lower_price",
        "corridor_upper_price",
        "corridor_width_atr",
        "max_adjacent_gap_atr",
        "median_adjacent_gap_atr",
        "spacing_stability",
        "nearest_rail_member_id",
        "nearest_rail_distance_atr",
        "current_corridor_position",
    ):
        features[f"{role}_{field}"] = output_features.get(f"{role}_{field}")
    if family is None:
        return
    features.update(
        {
            f"{role}_family_age_bars": family.age_bars,
            f"{role}_family_confidence": family.confidence,
            f"{role}_structural_importance": family.structural_importance,
            f"{role}_current_relevance": family.current_relevance,
            f"{role}_effective_touch_count": family.effective_touch_count,
            f"{role}_breach_count": family.breach_count,
            f"{role}_bars_since_touch": family.bars_since_touch,
            f"{role}_bars_since_match": family.bars_since_match,
            f"{role}_projection_horizon_bars": family.uncertainty.projection_horizon_bars,
        }
    )


def _base_features(*, enabled: bool) -> dict[str, Any]:
    features: dict[str, Any] = {
        "trendline_family_shadow_enabled": enabled,
        "trendline_family_valid": None,
        "trendline_family_error": None,
        "trendline_family_error_type": None,
        "trendline_family_error_reason": None,
        "trendline_family_model_version": None,
        "trendline_family_config_version": None,
        "trendline_family_resolved_config_hash": None,
        "trendline_family_snapshot_id": None,
        "trendline_family_previous_snapshot_id": None,
        "trendline_family_timestamp": None,
        "trendline_family_asset": None,
        "trendline_family_timeframe": None,
        "trendline_family_count_active": None,
        "trendline_family_count_dormant": None,
        "trendline_family_births": None,
        "trendline_family_updates": None,
        "trendline_family_dormancies": None,
        "trendline_family_reactivations": None,
        "trendline_family_expiries": None,
        "trendline_family_churn_count": None,
        "trendline_family_churn_rate": None,
        "trendline_family_generated_candidate_count": None,
        "trendline_family_matched_count": None,
        "trendline_family_rejected_birth_count": None,
        "trendline_family_provider_status": None,
        "trendline_family_provider_reason_codes": None,
        "trendline_family_normalization_atr": None,
        "trendline_family_interaction_atr": None,
        "trendline_family_interaction_observation_count": None,
        "trendline_family_corridor_count": None,
        "trendline_family_singleton_count": None,
        "trendline_family_multi_rail_count": None,
        "trendline_family_total_rail_count": None,
        "trendline_family_rail_counts": None,
        "trendline_family_corridor_width_atr_values": None,
        "trendline_family_adjacent_gap_atr_values": None,
        "trendline_family_spacing_stability_values": None,
        "trendline_family_member_additions": None,
        "trendline_family_member_removals": None,
        "trendline_family_representative_change_count": None,
        "trendline_family_rail_grouping_rejection_reasons": None,
        "trendline_family_event_count": None,
        "trendline_family_event_transition_count": None,
        "trendline_family_event_state_values": None,
        "trendline_family_break_pending_count": None,
        "trendline_family_break_confirmed_count": None,
        "trendline_family_retest_pending_count": None,
        "trendline_family_retest_success_count": None,
        "trendline_family_failed_break_count": None,
        "trendline_family_role_reversal_count": None,
        "trendline_family_event_pressure_bars": None,
        "trendline_family_event_confirmation_streaks": None,
        "trendline_family_abstained": None,
        "trendline_family_abstention_reason": None,
        "trendline_family_hypothesis_count": None,
        "trendline_family_support_count": None,
        "trendline_family_resistance_count": None,
        "trendline_family_top_support_score_gap": None,
        "trendline_family_top_resistance_score_gap": None,
        "trendline_family_ambiguity_reason": None,
        "trendline_family_latency_ms": 0.0,
        "trendline_family_failure_count": 0,
        "trendline_family_success_count": 0,
        "trendline_family_coverage": None,
        "trendline_family_state_advanced": False,
        "trendline_family_repository_head_before": None,
        "trendline_family_repository_head_after": None,
        "trendline_family_shadow_feature_count": None,
    }
    for role in ("support", "resistance"):
        features.update(
            {
                f"nearest_{role}_family_id": None,
                f"distance_to_{role}_line_atr": None,
                f"distance_to_{role}_zone_atr": None,
                f"{role}_interaction_state": None,
                f"{role}_wick_penetration_atr": None,
                f"{role}_body_penetration_atr": None,
                f"{role}_close_penetration_atr": None,
                f"{role}_event_id": None,
                f"{role}_event_state": None,
                f"{role}_event_age_bars": None,
                f"{role}_event_bars_in_state": None,
                f"{role}_pressure_bars": None,
                f"{role}_close_beyond_streak": None,
                f"{role}_retest_age_bars": None,
                f"{role}_max_wick_penetration_atr": None,
                f"{role}_max_body_penetration_atr": None,
                f"{role}_max_close_penetration_atr": None,
                f"{role}_pending_role_reversal": None,
                f"{role}_event_compatibility_label": None,
                f"{role}_family_age_bars": None,
                f"{role}_family_confidence": None,
                f"{role}_structural_importance": None,
                f"{role}_current_relevance": None,
                f"{role}_effective_touch_count": None,
                f"{role}_breach_count": None,
                f"{role}_bars_since_touch": None,
                f"{role}_bars_since_match": None,
                f"{role}_projection_horizon_bars": None,
                f"{role}_rail_count": None,
                f"{role}_ordered_member_ids": None,
                f"{role}_representative_member_id": None,
                f"{role}_corridor_lower_price": None,
                f"{role}_corridor_upper_price": None,
                f"{role}_corridor_width_atr": None,
                f"{role}_max_adjacent_gap_atr": None,
                f"{role}_median_adjacent_gap_atr": None,
                f"{role}_spacing_stability": None,
                f"{role}_nearest_rail_member_id": None,
                f"{role}_nearest_rail_distance_atr": None,
                f"{role}_current_corridor_position": None,
            }
        )
    features["trendline_family_shadow_feature_count"] = len(features)
    return features


def _failure_features(
    *,
    enabled: bool,
    error_type: str,
    error_reason: str,
    head_before: str | None,
    head_after: str | None,
    latency_ms: float,
    state_advanced: bool | None,
) -> dict[str, Any]:
    features = _base_features(enabled=enabled)
    features.update(
        {
            "trendline_family_valid": False,
            "trendline_family_error": error_reason,
            "trendline_family_error_type": error_type,
            "trendline_family_error_reason": error_reason,
            "trendline_family_latency_ms": latency_ms,
            "trendline_family_failure_count": 1,
            "trendline_family_coverage": 0.0,
            "trendline_family_repository_head_before": head_before,
            "trendline_family_repository_head_after": head_after,
            "trendline_family_state_advanced": state_advanced,
        }
    )
    features["trendline_family_shadow_feature_count"] = len(features)
    return features


def build_trendline_family_shadow_failure_payload(
    *,
    error_type: str,
    error_reason: str,
    latency_ms: float = 0.0,
    head_before: str | None = None,
    head_after: str | None = None,
    state_advanced: bool | None = None,
) -> dict[str, Any]:
    """Build an enabled diagnostic failure without repository or model work."""

    return _failure_features(
        enabled=True,
        error_type=error_type,
        error_reason=error_reason,
        head_before=head_before,
        head_after=head_after,
        latency_ms=max(float(latency_ms), 0.0),
        state_advanced=state_advanced,
    )


def _repository_head_id(
    repository: TrendlineFamilyRepository,
    asset: str,
    timeframe: str,
) -> str | None:
    snapshot = repository.latest_snapshot(asset, timeframe)
    return None if snapshot is None else snapshot.snapshot_id


def _safe_repository_head_id(
    repository: TrendlineFamilyRepository,
    asset: str,
    timeframe: str,
) -> tuple[str | None, bool]:
    try:
        return _repository_head_id(repository, asset, timeframe), True
    except Exception:  # pragma: no cover - diagnostic best effort only
        return None, False


def _state_advanced(
    head_before: str | None,
    head_after: str | None,
    *,
    head_before_known: bool,
    head_after_known: bool,
) -> bool | None:
    if not head_before_known or not head_after_known:
        return None
    return head_after != head_before


def _expected_error_type(exc: Exception) -> str:
    if isinstance(exc, SnapshotVersionError):
        return "repository_lineage_error"
    return "family_contract_error"


def _expected_error_reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "tick_size" in message:
        return "invalid_tick_size"
    if "interaction atr" in message:
        return "interaction_atr_failure"
    if "repository head identity mismatch" in message or "previous_snapshot_id" in message:
        return "repository_lineage_mismatch"
    if "config" in message and "identity" in message:
        return "config_request_identity_mismatch"
    if "config" in message:
        return "config_resolution_failure"
    if "ohlcv" in message or "confirmed" in message or "datetimeindex" in message:
        return "invalid_confirmed_ohlcv"
    return exc.__class__.__name__.lower()


def _safe_clock_read(clock: Callable[[], int]) -> int | None:
    try:
        return clock()
    except Exception:  # pragma: no cover - defensive observability boundary
        return None


def _safe_elapsed_ms(started_at: int | None, clock: Callable[[], int]) -> float:
    """Return a deterministic fallback when operational timing is unavailable."""

    if started_at is None:
        return 0.0
    finished_at = _safe_clock_read(clock)
    if finished_at is None:
        return 0.0
    try:
        return max(float(finished_at - started_at) / 1_000_000.0, 0.0)
    except Exception:  # pragma: no cover - malformed injected clock values only
        return 0.0


def _shadow_payload(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    nested = record.get("trendline_family_shadow")
    if isinstance(nested, Mapping):
        return nested
    if "trendline_family_shadow_enabled" in record:
        return record
    return None


def _attach_mtf_shadow_features(
    features: dict[str, Any],
    provider: MTFSnapshotProvider | None,
    *,
    output: TrendlineFamilyOutput,
) -> None:
    """Read a pre-composed MTF snapshot only; this adapter never composes it."""

    if provider is None:
        return
    try:
        snapshot = provider()
        if snapshot is None or not _mtf_snapshot_matches_output(snapshot, output):
            features["mtf"] = build_mtf_shadow_features(None, enabled=False)
            return
        features["mtf"] = build_mtf_shadow_features(snapshot, enabled=snapshot is not None)
    except Exception:  # pragma: no cover - MTF observability cannot break shadow tracking
        features["mtf"] = build_mtf_shadow_features(None, enabled=False)


def _mtf_snapshot_matches_output(
    snapshot: MTFGeometrySnapshot,
    output: TrendlineFamilyOutput,
) -> bool:
    """MTF evidence attaches only to exact current single-timeframe output."""

    if not isinstance(snapshot, MTFGeometrySnapshot):
        return False
    source = output.snapshot
    return (
        snapshot.asset == source.asset
        and snapshot.normalization_context.decision_timeframe == source.timeframe
        and snapshot.decision_timestamp == source.timestamp
    )


def _mtf_distribution(records: Iterable[Mapping[str, Any]], field_name: str) -> dict[str, int]:
    return _distribution(
        (mtf for record in records if isinstance((mtf := record.get("mtf")), Mapping)),
        field_name,
    )


def _mtf_reason_distribution(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        mtf = record.get("mtf")
        if not isinstance(mtf, Mapping):
            continue
        reasons = mtf.get("exclusion_reason_distribution")
        if not isinstance(reasons, Mapping):
            continue
        for reason, count in reasons.items():
            if isinstance(reason, str) and isinstance(count, int) and not isinstance(count, bool):
                counts[reason] += count
    return dict(sorted(counts.items()))


def _mtf_sequence_distribution(
    records: Iterable[Mapping[str, Any]],
    field_name: str,
) -> dict[str, int]:
    return _sequence_distribution(
        (mtf for record in records if isinstance((mtf := record.get("mtf")), Mapping)),
        field_name,
    )


def _distribution(records: Iterable[Mapping[str, Any]], field_name: str) -> dict[str, int]:
    counts = Counter(
        str(value)
        for record in records
        if (value := record.get(field_name)) is not None
    )
    return dict(sorted(counts.items()))


def _sequence_distribution(records: Iterable[Mapping[str, Any]], field_name: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        values = record.get(field_name)
        if not isinstance(values, (tuple, list)):
            continue
        counts.update(str(value) for value in values)
    return dict(sorted(counts.items()))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _latency_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


__all__ = [
    "FailedTrendlineFamilyShadowProducer",
    "TrendlineFamilyFeatureProducer",
    "TrendlineFamilyShadowConfig",
    "build_trendline_family_shadow_failure_payload",
    "summarize_trendline_family_shadow_artifacts",
]
