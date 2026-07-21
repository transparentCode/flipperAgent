"""MTF source-age, freshness, and source-reference derivation."""

from __future__ import annotations

from datetime import datetime
import math

from ..domain.snapshots import TrendlineFamilySnapshot
from .contracts import (
    MTFFreshnessState,
    MTFPolicyAudit,
    MTFSourceSnapshotAudit,
    MTFSourceSnapshotReference,
    MTFSourceStatus,
    _timeframe_key,
    _validate_policy_source_timeframes,
    timeframe_duration_seconds,
)

def _freshness(*, age_bars: float, policy: MTFPolicyAudit) -> tuple[MTFFreshnessState, tuple[str, ...]]:
    if age_bars <= policy.stale_include_age_bars:
        return MTFFreshnessState.FRESH, ("fresh",)
    if age_bars <= policy.max_source_age_bars:
        return MTFFreshnessState.STALE_INCLUDED, ("stale_included",)
    return MTFFreshnessState.STALE_EXCLUDED, ("stale_excluded_hard_max",)


def _source_audit(
    *,
    source_snapshot_audits: tuple[MTFSourceSnapshotAudit, ...],
    decision_timestamp: datetime,
    policy: MTFPolicyAudit,
) -> tuple[tuple[MTFSourceSnapshotReference, ...], tuple[MTFSourceStatus, ...]]:
    references: list[MTFSourceSnapshotReference] = []
    statuses: list[MTFSourceStatus] = []
    _validate_policy_source_timeframes(
        (audit.source_snapshot.timeframe for audit in source_snapshot_audits),
        policy=policy,
    )
    for audit in source_snapshot_audits:
        snapshot = audit.source_snapshot
        timeframe = snapshot.timeframe
        duration = timeframe_duration_seconds(timeframe)
        age_seconds = (decision_timestamp - snapshot.timestamp).total_seconds()
        age_bars = age_seconds / duration
        state, codes = _freshness(age_bars=age_bars, policy=policy)
        reference = MTFSourceSnapshotReference(
            source_snapshot_id=snapshot.snapshot_id,
            source_snapshot_timestamp=snapshot.timestamp,
            source_timeframe=timeframe,
            asset=snapshot.asset,
            model_version=snapshot.model_version,
            config_version=snapshot.config_version,
            resolved_config_hash=snapshot.resolved_config_hash,
            source_normalization_atr=_source_atr(snapshot),
            source_age_seconds=age_seconds,
            source_age_bars=age_bars,
            source_bar_duration_seconds=duration,
            freshness_state=state,
            reason_codes=codes,
        )
        references.append(reference)
        statuses.append(
            MTFSourceStatus(
                source_timeframe=timeframe,
                freshness_state=state,
                reason_codes=codes,
                source_snapshot_id=snapshot.snapshot_id,
                source_snapshot_timestamp=snapshot.timestamp,
                source_age_seconds=age_seconds,
                source_age_bars=age_bars,
            )
        )
    actual = {audit.source_snapshot.timeframe for audit in source_snapshot_audits}
    for timeframe in policy.source_timeframes:
        if timeframe not in actual:
            statuses.append(
                MTFSourceStatus(
                    source_timeframe=timeframe,
                    freshness_state=MTFFreshnessState.MISSING,
                    reason_codes=("missing_source_snapshot",),
                )
            )
    return (
        tuple(sorted(references, key=lambda item: _timeframe_key(item.source_timeframe))),
        tuple(sorted(statuses, key=lambda item: _timeframe_key(item.source_timeframe))),
    )


def _source_atr(snapshot: TrendlineFamilySnapshot) -> float | None:
    value = snapshot.diagnostics.get("normalization_atr")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0.0:
        return None
    return float(value)
