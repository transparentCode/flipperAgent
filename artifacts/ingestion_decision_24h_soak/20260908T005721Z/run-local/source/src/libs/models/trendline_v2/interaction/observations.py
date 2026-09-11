"""Pure causal exact-line observation functions."""

from __future__ import annotations

from datetime import datetime

from ..domain.validation import ContractValidationError, require_utc
from ..input import ConfirmedOHLCVFrame
from ..tracking import TrackingStatus, TrendlineTrackingSnapshot
from .contracts import (
    ConfirmedInteractionBar,
    ExactLineBarObservation,
    ExactLineObservationPolicy,
    InteractionObservationDiagnostics,
    TrendlineInteractionSnapshot,
)


def interaction_bar_from_frame(
    frame: ConfirmedOHLCVFrame,
    *,
    timestamp: datetime,
) -> ConfirmedInteractionBar:
    """Extract one explicitly named confirmed bar without nearest-row lookup."""

    if not isinstance(frame, ConfirmedOHLCVFrame):
        raise ContractValidationError("interaction frame must be ConfirmedOHLCVFrame")
    timestamp = require_utc(timestamp, field_name="interaction bar timestamp")
    if timestamp >= frame.observed_at:
        raise ContractValidationError(
            "interaction bar timestamp must precede frame.observed_at"
        )
    owned = frame.frame
    matching = owned.loc[owned.index == timestamp]
    if len(matching) != 1:
        raise ContractValidationError(
            "interaction bar timestamp must identify exactly one frame row"
        )
    row = matching.iloc[0]
    return ConfirmedInteractionBar.create(
        asset=frame.asset,
        timeframe=frame.timeframe,
        timestamp=timestamp,
        available_at=frame.observed_at,
        source_input_identity=frame.input_identity,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
    )


def observe_exact_line_interactions(
    tracking: TrendlineTrackingSnapshot,
    bar: ConfirmedInteractionBar,
    *,
    policy: ExactLineObservationPolicy,
) -> TrendlineInteractionSnapshot:
    """Observe frozen active families on one later confirmed bar."""

    if not isinstance(tracking, TrendlineTrackingSnapshot):
        raise ContractValidationError(
            "interaction tracking must be TrendlineTrackingSnapshot"
        )
    if not isinstance(bar, ConfirmedInteractionBar):
        raise ContractValidationError(
            "interaction bar must be ConfirmedInteractionBar"
        )
    if not isinstance(policy, ExactLineObservationPolicy):
        raise ContractValidationError(
            "interaction policy must be ExactLineObservationPolicy"
        )
    if tracking.status not in (
        TrackingStatus.UPDATED,
        TrackingStatus.SOURCE_UNAVAILABLE,
    ):
        raise ContractValidationError("tracking status cannot be observed")
    if bar.asset != tracking.asset or bar.timeframe != tracking.timeframe:
        raise ContractValidationError("interaction market identity mismatch")
    if bar.timestamp < tracking.observed_at:
        raise ContractValidationError("interaction bar precedes tracking observation")
    if bar.available_at <= tracking.observed_at:
        raise ContractValidationError(
            "interaction bar is not available after tracking observation"
        )
    if bar.source_input_identity == tracking.input_identity:
        raise ContractValidationError("interaction source input identity did not advance")

    observations = []
    for family in tracking.active_families:
        if family.last_seen_at > tracking.observed_at:
            raise ContractValidationError("family is newer than tracking observation")
        candidate = family.current_candidate
        if candidate.asset != tracking.asset or candidate.timeframe != tracking.timeframe:
            raise ContractValidationError("family candidate market identity mismatch")
        if bar.timestamp < candidate.geometry.end_time:
            raise ContractValidationError(
                "interaction bar precedes current family geometry"
            )
        observations.append(
            ExactLineBarObservation.create(
                family_id=family.family_id,
                family_version=family.version,
                role=candidate.role,
                source_tracking_snapshot_id=tracking.snapshot_id,
                source_selection_snapshot_id=family.current_selection_snapshot_id,
                source_candidate_id=candidate.candidate_id,
                geometry_id=candidate.geometry.geometry_id,
                bar=bar,
                exact_line_price=candidate.geometry.value_at(bar.timestamp),
            )
        )

    observations_tuple = tuple(observations)
    diagnostics = InteractionObservationDiagnostics(
        source_active_family_count=len(tracking.active_families),
        observation_count=len(observations_tuple),
        support_observation_count=sum(
            item.role.value == "support" for item in observations_tuple
        ),
        resistance_observation_count=sum(
            item.role.value == "resistance" for item in observations_tuple
        ),
        wick_intersection_count=sum(
            item.wick_intersects_line for item in observations_tuple
        ),
        body_intersection_count=sum(
            item.body_intersects_line for item in observations_tuple
        ),
    )
    snapshot = TrendlineInteractionSnapshot.create(
        source_tracking=tracking,
        observation_policy_identity=policy.policy_identity,
        bar=bar,
        observations=observations_tuple,
        diagnostics=diagnostics,
    )
    snapshot.validate_source_tracking(tracking)
    return snapshot


__all__ = [
    "interaction_bar_from_frame",
    "observe_exact_line_interactions",
]
