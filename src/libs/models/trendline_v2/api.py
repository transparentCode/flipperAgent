"""Small explicit public discovery path for Trendline V2."""

from __future__ import annotations

from .configuration import (
    ConfirmedExtremaPairConfig,
    ResolvedTrendlineV2Config,
)
from .discovery import ConfirmedExtremaPairProvider, ProviderInput, ProviderRequest, ProviderResult
from .domain.validation import ContractValidationError
from .input import ConfirmedOHLCVFrame
from .domain.snapshots import DiscoverySnapshot
from .selection import (
    CandidateSelectionSnapshot,
    LatestValidPredecessorPolicy,
    select_latest_valid_predecessors,
)
from .tracking import (
    ExactSelectedStructureTrackingPolicy,
    TrackedTrendlineFamily,
    TrendlineTrackingSnapshot,
    track_selected_trendlines,
)


def discover_trendlines(
    frame: ConfirmedOHLCVFrame,
    *,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
) -> ProviderResult:
    """Execute confirmed-extrema discovery over one validated causal frame."""

    if not isinstance(frame, ConfirmedOHLCVFrame):
        raise ContractValidationError("discover_trendlines.frame must be ConfirmedOHLCVFrame")
    if not isinstance(config, ResolvedTrendlineV2Config):
        raise ContractValidationError(
            "discover_trendlines.config must be ResolvedTrendlineV2Config"
        )
    if not isinstance(provider_config, ConfirmedExtremaPairConfig):
        raise ContractValidationError(
            "discover_trendlines.provider_config must be ConfirmedExtremaPairConfig"
        )

    arrays = frame.arrays()
    provider_input = ProviderInput(
        asset=frame.asset,
        timeframe=frame.timeframe,
        observed_at=frame.observed_at,
        confirmed_through=frame.confirmed_through,
        timestamps=tuple(int(value) for value in arrays.timestamps),
        open=tuple(float(value) for value in arrays.open),
        high=tuple(float(value) for value in arrays.high),
        low=tuple(float(value) for value in arrays.low),
        close=tuple(float(value) for value in arrays.close),
        volume=tuple(float(value) for value in arrays.volume),
    )
    request = ProviderRequest(
        input_data=provider_input,
        config=config,
        provider_config=provider_config,
    )
    return ConfirmedExtremaPairProvider().generate(request)


def select_trendline_candidates(
    snapshot: DiscoverySnapshot,
    *,
    policy: LatestValidPredecessorPolicy,
) -> CandidateSelectionSnapshot:
    """Select candidates using an explicitly supplied policy."""

    return select_latest_valid_predecessors(snapshot, policy=policy)


def track_trendline_families(
    selection: CandidateSelectionSnapshot,
    *,
    previous: TrendlineTrackingSnapshot | None,
    policy: ExactSelectedStructureTrackingPolicy,
) -> TrendlineTrackingSnapshot:
    """Track one explicitly selected source snapshot through exact identity."""

    return track_selected_trendlines(selection, previous=previous, policy=policy)


__all__ = [
    "ExactSelectedStructureTrackingPolicy",
    "TrackedTrendlineFamily",
    "TrendlineTrackingSnapshot",
    "discover_trendlines",
    "select_trendline_candidates",
    "track_trendline_families",
]
