"""Latest confirmed source-snapshot store for MTF composition."""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from ..configuration.contracts import ResolvedTrendlineFamilyConfig
from ..domain.snapshots import TrendlineFamilySnapshot
from ..domain.validation import ContractValidationError
from .composition import compose_mtf_snapshot
from .contracts import (
    MTFGeometrySnapshot,
    MTFNormalizationContext,
    _text,
    _timeframe_key,
    _validate_confirmed_phase_g_source,
)

class LatestMTFSnapshotStore:
    """Small deterministic wrapper for independently arriving confirmed source snapshots."""

    def __init__(self, *, asset: str) -> None:
        self._asset = _text(asset, field_name="MTF store asset")
        self._snapshots: dict[str, TrendlineFamilySnapshot] = {}

    def update(self, snapshot: TrendlineFamilySnapshot) -> bool:
        if not isinstance(snapshot, TrendlineFamilySnapshot):
            raise ContractValidationError("MTF source update requires TrendlineFamilySnapshot")
        if snapshot.asset != self._asset:
            raise ContractValidationError("MTF source update asset mismatch")
        # Round-trip first: no caller-owned object reaches the latest-source head.
        canonical = TrendlineFamilySnapshot.from_dict(snapshot.to_dict())
        _validate_confirmed_phase_g_source(canonical)
        previous = self._snapshots.get(canonical.timeframe)
        if previous is not None:
            if canonical.snapshot_id == previous.snapshot_id:
                return False
            if canonical.timestamp <= previous.timestamp:
                raise ContractValidationError("older or conflicting MTF source snapshot cannot replace head")
            if canonical.previous_snapshot_id != previous.snapshot_id:
                raise ContractValidationError("MTF source update must continue the stored source lineage")
        self._snapshots[canonical.timeframe] = canonical
        return True

    def latest_sources(self) -> Mapping[str, TrendlineFamilySnapshot]:
        return MappingProxyType({
            timeframe: TrendlineFamilySnapshot.from_dict(snapshot.to_dict())
            for timeframe, snapshot in sorted(self._snapshots.items(), key=lambda item: _timeframe_key(item[0]))
        })

    def compose(
        self,
        *,
        decision_timestamp: datetime,
        normalization_context: MTFNormalizationContext,
        config: ResolvedTrendlineFamilyConfig,
    ) -> MTFGeometrySnapshot:
        return compose_mtf_snapshot(
            source_snapshots=self.latest_sources(),
            decision_timestamp=decision_timestamp,
            normalization_context=normalization_context,
            config=config,
        )
