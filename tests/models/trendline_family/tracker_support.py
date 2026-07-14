"""Canonical Phase-C test fixtures with no runtime legacy dependencies."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.contracts import (
    AnchorRef,
    FamilyLifecycleState,
    FamilyMember,
    FamilyRole,
    LineCandidate,
    LineDiagnostics,
    LineGeometry,
    LineUncertainty,
    TrendlineFamilyState,
)
from libs.models.trendline_family.provider import CandidateGenerationResult, CandidateGenerationStatus


UTC = timezone.utc

_PHASE_G_DIAGNOSTIC_KEYS = (
    "rail_grouping_enabled",
    "rail_group_count",
    "rail_grouping_rejection_reasons",
    "family_corridor_count",
    "singleton_family_count",
    "multi_rail_family_count",
    "total_rail_count",
    "representative_change_count",
)
_PHASE_G_TRANSITION_FIELDS = (
    "added_member_ids",
    "continued_member_ids",
    "removed_member_ids",
    "previous_representative_member_id",
    "current_representative_member_id",
    "representative_changed",
    "previous_rail_count",
    "current_rail_count",
    "source_group_id",
    "source_group_candidate_ids",
)


def legacy_pre_phase_g_payload(snapshot: Any) -> dict[str, Any]:
    """Strip Phase-G-only fields from a single-rail historical fixture payload."""

    payload = snapshot.to_dict()
    payload.pop("source_group_audits")
    payload.pop("corridors")
    for transition in payload["transitions"]:
        for field in _PHASE_G_TRANSITION_FIELDS:
            transition.pop(field)
    for key in _PHASE_G_DIAGNOSTIC_KEYS:
        payload["diagnostics"].pop(key, None)
    return payload


def timestamp(offset_hours: int = 0) -> datetime:
    return datetime(2024, 1, 2, tzinfo=UTC) + timedelta(hours=offset_hours)


def tracker_ohlcv(observed_at: datetime, *, periods: int = 24) -> pd.DataFrame:
    """Return normalized confirmed bars with finite, positive true range."""

    index = pd.date_range(end=observed_at, periods=periods, freq="h", tz="UTC")
    close = [100.0 + (index % 4) * 0.4 for index in range(periods)]
    return pd.DataFrame(
        {
            "open": [value - 0.2 for value in close],
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
        },
        index=index,
    )


def tracker_config(
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
    config_version: int | str = 1,
    model: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    matching: dict[str, Any] | None = None,
    lifecycle: dict[str, Any] | None = None,
    interaction: dict[str, Any] | None = None,
    events: dict[str, Any] | None = None,
    rails: dict[str, Any] | None = None,
) -> ResolvedTrendlineFamilyConfig:
    candidate_config = {
        "lookback_bars": 24,
        "min_bars": 8,
        "fractal_left_bars": 1,
        "fractal_right_bars": 1,
        "min_pivots_per_side": 2,
        "min_candidate_quality": 0.0,
        "birth_quality_threshold": 0.45,
    }
    matching_config = {
        "normalization_atr_window": 3,
        "max_distance_atr": 0.75,
        "max_slope_delta_atr_per_hour": 0.10,
        "minimum_match_score": 0.60,
        "level_weight": 0.45,
        "slope_weight": 0.30,
        "anchor_weight": 0.15,
        "role_weight": 0.10,
    }
    lifecycle_config = {
        "active_grace_bars": 1,
        "dormant_after_bars": 3,
        "expire_after_bars": 5,
        "confidence_decay_per_unmatched_bar": 0.10,
        "reactivation_min_score": 0.70,
        "max_active_families_per_role": 2,
    }
    interaction_config = {
        "atr_window": 3,
        "tolerance_atr": 0.25,
        "approaching_distance_atr": 0.75,
        "minimum_zone_ticks": 1,
        "close_confirmation_bars": 2,
    }
    events_config = {
        "pressure_min_bars": 3,
        "rejection_recovery_bars": 2,
        "retest_window_bars": 6,
        "retest_confirmation_bars": 1,
    }
    rails_config = {
        "max_group_slope_delta_atr_per_hour": 0.08,
        "max_adjacent_gap_atr": 0.75,
        "max_corridor_width_atr": 1.50,
        "minimum_spacing_atr": 0.05,
        "representative_policy": "stable_medoid",
    }
    candidate_config.update(deepcopy(candidate or {}))
    matching_config.update(deepcopy(matching or {}))
    lifecycle_config.update(deepcopy(lifecycle or {}))
    interaction_config.update(deepcopy(interaction or {}))
    events_config.update(deepcopy(events or {}))
    rails_config.update(deepcopy(rails or {}))
    raw = {
        "version": config_version,
        "defaults": {
            "candidate": candidate_config,
            "matching": matching_config,
            "lifecycle": lifecycle_config,
            "interaction": interaction_config,
            "events": events_config,
            "rails": rails_config,
        },
    }
    if model is not None:
        raw["model"] = deepcopy(model)
    return TrendlineFamilyConfigResolver(raw).resolve(asset=asset, timeframe=timeframe)


def candidate(
    config: ResolvedTrendlineFamilyConfig,
    observed_at: datetime,
    *,
    candidate_id: str = "candidate-support",
    role: FamilyRole = FamilyRole.SUPPORT,
    reference_price: float = 100.0,
    slope_per_hour: float = 0.0,
    quality: float = 0.80,
    anchor_prefix: str = "support",
) -> LineCandidate:
    observed = observed_at.astimezone(UTC)
    first = observed - timedelta(hours=3)
    second = observed - timedelta(hours=1)
    slope_per_second = slope_per_hour / 3600.0
    geometry = LineGeometry(
        reference_time=first,
        reference_price=reference_price,
        slope_per_second=slope_per_second,
    )
    pivot_kind = "low" if role is FamilyRole.SUPPORT else "high"
    anchors = (
        AnchorRef(
            anchor_id=f"{anchor_prefix}-first",
            timestamp=first,
            price=geometry.value_at(first),
            pivot_kind=pivot_kind,
            confirmation_time=first,
        ),
        AnchorRef(
            anchor_id=f"{anchor_prefix}-second",
            timestamp=second,
            price=geometry.value_at(second),
            pivot_kind=pivot_kind,
            confirmation_time=second,
        ),
    )
    return LineCandidate(
        candidate_id=candidate_id,
        asset=config.asset,
        timeframe=config.timeframe,
        observed_at=observed,
        geometry=geometry,
        anchors=anchors,
        role=role,
        method="pathfinding",
        provider="native_deterministic",
        diagnostics=LineDiagnostics(
            raw_score=quality,
            normalized_quality=quality,
            touch_count=2,
            effective_touch_count=2,
            coverage=0.25,
        ),
        source_line_index=0,
        metadata={
            "model_version": config.model_version,
            "config_version": config.config_version,
            "resolved_config_hash": config.resolved_config_hash,
        },
    )


def interaction_family(
    config: ResolvedTrendlineFamilyConfig,
    observed_at: datetime,
    *,
    role: FamilyRole = FamilyRole.SUPPORT,
    reference_price: float = 100.0,
    slope_per_hour: float = 0.0,
    bars_since_touch: int = 0,
    breach_count: int = 0,
    lifecycle_state: FamilyLifecycleState = FamilyLifecycleState.ACTIVE,
) -> TrendlineFamilyState:
    observation = candidate(
        config,
        observed_at,
        candidate_id=f"interaction-{role.value.lower()}",
        role=role,
        reference_price=reference_price,
        slope_per_hour=slope_per_hour,
    )
    member = FamilyMember(
        member_id=f"member-{role.value.lower()}",
        candidate_id=observation.candidate_id,
        geometry=observation.geometry,
        role=role,
        diagnostics=observation.diagnostics,
        anchors=observation.anchors,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
    )
    return TrendlineFamilyState(
        family_id=f"family-{role.value.lower()}",
        asset=config.asset,
        timeframe=config.timeframe,
        created_at=observed_at,
        updated_at=observed_at,
        last_confirmed_at=observed_at,
        age_bars=1,
        representative=member.geometry,
        representative_member_id=member.member_id,
        members=(member,),
        current_role=role,
        lifecycle_state=lifecycle_state,
        confidence=0.80,
        structural_importance=0.80,
        current_relevance=0.50,
        touch_count=member.diagnostics.touch_count,
        effective_touch_count=member.diagnostics.effective_touch_count,
        breach_count=breach_count,
        bars_since_touch=bars_since_touch,
        bars_since_match=0,
        uncertainty=LineUncertainty(),
        version=1,
    )


def valid_result(*candidates: LineCandidate) -> CandidateGenerationResult:
    return CandidateGenerationResult(
        status=CandidateGenerationStatus.VALID,
        candidates=candidates,
        reason_codes=(),
    )


def abstention(status: CandidateGenerationStatus = CandidateGenerationStatus.NO_CONFIRMED_PIVOTS) -> CandidateGenerationResult:
    return CandidateGenerationResult(status=status, candidates=(), reason_codes=(status.value,))


class SequenceProvider:
    """Return a fixed provider observation sequence and record canonical calls."""

    def __init__(self, results: Sequence[CandidateGenerationResult]) -> None:
        self._results = tuple(results)
        self.calls: list[tuple[datetime, int]] = []

    def generate(
        self,
        ohlcv: pd.DataFrame,
        *,
        asset: str,
        timeframe: str,
        observed_at: datetime,
        config: ResolvedTrendlineFamilyConfig,
        context: dict[str, Any] | None = None,
    ) -> CandidateGenerationResult:
        del asset, timeframe, config, context
        self.calls.append((observed_at, len(ohlcv)))
        if not self._results:
            raise AssertionError("unexpected provider call")
        return self._results[len(self.calls) - 1]
