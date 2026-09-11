"""Bounded structural replay evidence and immutable episode artifacts.

This module intentionally composes :class:`OfflineCompute` instead of
reimplementing the structural loop.  Only compact semantic counters, hashes,
and issuance records cross the collector boundary; the full research trace is
never retained here.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import tempfile
import time
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..config.resolver import ResolvedSRV2Config
from ..contracts import ForecastOutcome, LifecycleState, ZoneSide, require_utc
from ..domain.bars import SRBar
from ..domain.identity import canonical_hash, canonical_json
from ..domain.state import SRState
from ..domain.zones import ZoneLineage, ZoneRecord
from ..features.time import grid_for
from ..forecast.targets import (
    ResolvedTargetSpec,
    ScientificReaction,
    label_scientific_target_indexed,
    scientific_target_fingerprint,
)
from ..lifecycle.transitions import LifecycleTransition, TransitionType
from ..research.placebos import (
    FEASIBLE_RANDOM_PRICE_ID,
    FeasibleRandomPriceNull,
    build_feasible_random_price_null,
)
from ..research.source import SourceBarRecord
from ..runtime.offline import OfflineCompute
from ..serialization.state_codec import encode_state
from ..structural import SRStepResult
from .data import AuthenticatedSourceSlice
from .scientific_compiler import (
    CompiledScientificSet,
    ScientificGroupKey,
    ScientificObservation,
)

EPISODE_EVIDENCE_SCHEMA = "sr_v2.streaming_episode_evidence@2"
EPISODE_ARTIFACT_SCHEMA = "sr_v2.episode_artifact@2"
ISSUANCE_RULE_ID = "committed_created_lineage@1"
ISSUANCE_SEQUENCE_HASH_ALGORITHM = "length_prefixed_canonical_sha256@1"
COMMON_RISK_RECEIPT_SCHEMA = "sr_v2.common_risk_receipt@2"
TARGET_OUTCOME_ROW_SCHEMA = "sr_v2.target_outcome_row@2"
TARGET_COMPILER_RECEIPT_SCHEMA = "sr_v2.indexed_target_compiler@2"
TARGET_MATERIALIZATION_POLICY_ID = "common_risk_indexed_target_rows@1"
TARGET_FAMILY_SCHEMA = "sr_v2.target_family@1"


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes, Linux reports KiB.
    return value if os.uname().sysname == "Darwin" else value * 1024


def _sequence_digest(values: Iterator[Any]) -> str:
    """Hash an ordered sequence without materializing the sequence payload."""

    digest = hashlib.sha256()
    for value in values:
        _sequence_digest_update(digest, value)
    return digest.hexdigest()


def _sequence_digest_update(digest: Any, value: Any) -> None:
    encoded = canonical_json(value).encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _bar(value: SRBar | SourceBarRecord) -> SRBar:
    if isinstance(value, SourceBarRecord):
        return value.bar
    if not isinstance(value, SRBar):
        raise TypeError("source bars must contain SRBar or SourceBarRecord values")
    return value


def _source_identity(value: SRBar | SourceBarRecord) -> str:
    return (
        value.source_identity if isinstance(value, SourceBarRecord) else value.identity
    )


def _direct_source_sha256(
    records_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
) -> str:
    """Derive the identity used by the narrow offline-only source path."""

    return canonical_hash(
        {
            timeframe: tuple(_bar(item) for item in values)
            for timeframe, values in sorted(records_by_timeframe.items())
        }
    )


def _authenticated_slice_fingerprint(
    *,
    source_manifest_id: str,
    source_sha256: str,
    venue: str,
    instrument_id: str,
    asset: str,
    bounds: Sequence[tuple[str, datetime, datetime]],
    records_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
    acquisition_evidence: Sequence[tuple[str, str, datetime, str]],
) -> str:
    identities = tuple(
        sorted(
            (
                timeframe,
                tuple(_source_identity(item) for item in records),
            )
            for timeframe, records in records_by_timeframe.items()
        )
    )
    counts = tuple(
        (timeframe, len(identities_for_timeframe))
        for timeframe, identities_for_timeframe in identities
    )
    return canonical_hash(
        {
            "schema_version": 1,
            "source_manifest_id": source_manifest_id,
            "source_sha256": source_sha256,
            "venue": venue,
            "instrument_id": instrument_id,
            "asset": asset,
            "bounds": tuple(bounds),
            "record_identities": identities,
            "record_counts": counts,
            "acquisition_evidence": tuple(acquisition_evidence),
        }
    )


def _group_mapping(group: ScientificGroupKey) -> Mapping[str, str]:
    return {
        "asset": group.asset,
        "timeframe": group.timeframe,
        "kernel_id": group.kernel_id,
        "kernel_version": group.kernel_version,
        "side": group.side.value,
    }


def _zone_mapping(zone: ZoneLineage) -> Mapping[str, Any]:
    return {
        "zone_id": zone.zone_id,
        "predecessor_id": zone.predecessor_id,
        "venue": zone.venue,
        "instrument_id": zone.instrument_id,
        "asset": zone.asset,
        "source_timeframe": zone.source_timeframe,
        "kernel_id": zone.kernel_id,
        "kernel_version": zone.kernel_version,
        "side": zone.side.value,
        "center": zone.center,
        "lower": zone.lower,
        "upper": zone.upper,
        "source_evidence_id": zone.source_evidence_id,
        "source_candidate_key": zone.source_candidate_key,
        "formed_at": zone.formed_at,
        "available_at": zone.available_at,
        "creation_atr": zone.creation_atr,
        "config_fingerprint": zone.config_fingerprint,
        "identity_schema_version": zone.identity_schema_version,
    }


def _null_mapping(null: FeasibleRandomPriceNull) -> Mapping[str, Any]:
    return {
        "source_observation_id": null.source_observation_id,
        "complete": null.complete,
        "reason": null.reason,
        "opportunity_bar_ids": null.opportunity_bar_ids,
        "excluded_active_zone_ids": null.excluded_active_zone_ids,
        "provenance": null.provenance,
        "zone": None if null.zone is None else _zone_mapping(null.zone),
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class EpisodeIssuance:
    """Compact immutable lineage record used by the episode JSONL index."""

    observation_id: str
    group: ScientificGroupKey
    zone: ZoneLineage
    issuance_cutoff: datetime
    source_close_index: int
    source_close_identity: str
    first_subsequent_trigger_index: int | None
    first_subsequent_trigger_identity: str | None
    feasible_null: FeasibleRandomPriceNull
    cluster_identity: str
    cluster_multiplicity: int = 1

    def __post_init__(self) -> None:
        if self.observation_id != self.zone.zone_id:
            raise ValueError("episode observation identity must equal zone identity")
        if not isinstance(self.group, ScientificGroupKey):
            raise TypeError("episode group must be ScientificGroupKey")
        if self.group.side is not self.zone.side:
            raise ValueError("episode group side differs from zone side")
        require_utc(self.issuance_cutoff, field_name="issuance_cutoff")
        if self.issuance_cutoff != self.zone.available_at:
            raise ValueError("episode issuance cutoff must equal zone availability")
        if isinstance(self.source_close_index, bool) or self.source_close_index < 0:
            raise ValueError("source_close_index must be non-negative")
        if not self.source_close_identity.strip():
            raise ValueError("source_close_identity must be non-empty")
        if self.first_subsequent_trigger_index is None:
            if self.first_subsequent_trigger_identity is not None:
                raise ValueError("missing trigger index cannot have an identity")
        elif (
            self.first_subsequent_trigger_index < 0
            or not self.first_subsequent_trigger_identity
        ):
            raise ValueError("trigger index and identity must be supplied together")
        if not isinstance(self.feasible_null, FeasibleRandomPriceNull):
            raise TypeError("feasible_null must be FeasibleRandomPriceNull")
        if not self.cluster_identity.strip() or self.cluster_multiplicity <= 0:
            raise ValueError("episode cluster identity/multiplicity is invalid")

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "observation_id": self.observation_id,
            "group": _group_mapping(self.group),
            "zone": _zone_mapping(self.zone),
            "issuance_cutoff": self.issuance_cutoff,
            "source_close_index": self.source_close_index,
            "source_close_identity": self.source_close_identity,
            "first_subsequent_trigger_index": self.first_subsequent_trigger_index,
            "first_subsequent_trigger_identity": self.first_subsequent_trigger_identity,
            "feasible_null": _null_mapping(self.feasible_null),
            "cluster_identity": self.cluster_identity,
            "cluster_multiplicity": self.cluster_multiplicity,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class StreamingStructuralReceipt:
    """Semantic and resource evidence from one bounded structural run."""

    schema: str
    source_manifest_id: str
    source_sha256: str
    source_slice_fingerprint: str | None
    asset: str
    venue: str
    instrument_id: str
    analysis_start: datetime
    knowledge_cutoff: datetime
    config_fingerprint: str
    steps: int
    candidates: int
    transitions: int
    created_transitions: int
    tombstone_pruned_transitions: int
    semantic_stream_sha256: str
    final_state_sha256: str
    state_generation: int
    serialized_state_bytes: int
    peak_active_lineages: int
    peak_terminal_tombstones: int
    expected_groups: tuple[ScientificGroupKey, ...]
    present_groups: tuple[ScientificGroupKey, ...]
    issuance_digest_algorithm: str
    issuance_count: int
    issuance_sha256: str
    wall_duration_seconds: float
    peak_rss_bytes: int
    semantic_hash: str

    def __post_init__(self) -> None:
        for name in (
            "schema",
            "source_manifest_id",
            "source_sha256",
            "asset",
            "venue",
            "instrument_id",
            "config_fingerprint",
            "semantic_stream_sha256",
            "final_state_sha256",
            "semantic_hash",
        ):
            if (
                not isinstance(getattr(self, name), str)
                or not getattr(self, name).strip()
            ):
                raise ValueError(f"{name} must be non-empty")
        if self.schema != EPISODE_EVIDENCE_SCHEMA:
            raise ValueError("unsupported streaming receipt schema")
        if self.issuance_digest_algorithm != ISSUANCE_SEQUENCE_HASH_ALGORITHM:
            raise ValueError("unsupported issuance digest algorithm")
        require_utc(self.analysis_start, field_name="analysis_start")
        require_utc(self.knowledge_cutoff, field_name="knowledge_cutoff")
        if self.knowledge_cutoff < self.analysis_start:
            raise ValueError("knowledge_cutoff must follow analysis_start")
        for name in (
            "steps",
            "candidates",
            "transitions",
            "created_transitions",
            "tombstone_pruned_transitions",
            "state_generation",
            "serialized_state_bytes",
            "peak_active_lineages",
            "peak_terminal_tombstones",
            "peak_rss_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.steps <= 0:
            raise ValueError("streaming receipt must contain at least one step")
        if self.wall_duration_seconds < 0:
            raise ValueError("wall_duration_seconds must be non-negative")
        expected = tuple(sorted(self.expected_groups))
        present = tuple(sorted(self.present_groups))
        if any(
            not isinstance(group, ScientificGroupKey) for group in expected + present
        ):
            raise TypeError("receipt groups must contain ScientificGroupKey values")
        if len(set(expected)) != len(expected) or len(set(present)) != len(present):
            raise ValueError("receipt groups must be unique")
        if not set(present) <= set(expected):
            raise ValueError("receipt present groups must be expected groups")
        if (
            isinstance(self.issuance_count, bool)
            or not isinstance(self.issuance_count, int)
            or self.issuance_count < 0
        ):
            raise ValueError("receipt issuance count must be non-negative")
        _strict_receipt_hash = self.issuance_sha256
        if (
            not isinstance(_strict_receipt_hash, str)
            or len(_strict_receipt_hash) != 64
            or _strict_receipt_hash != _strict_receipt_hash.lower()
        ):
            raise ValueError("receipt issuance SHA-256 must be lowercase 64-hex")
        try:
            int(_strict_receipt_hash, 16)
        except ValueError as exc:
            raise ValueError("receipt issuance SHA-256 must be hexadecimal") from exc
        semantic_hash = self._semantic_hash(
            schema=self.schema,
            source_manifest_id=self.source_manifest_id,
            source_sha256=self.source_sha256,
            source_slice_fingerprint=self.source_slice_fingerprint,
            asset=self.asset,
            venue=self.venue,
            instrument_id=self.instrument_id,
            analysis_start=self.analysis_start,
            knowledge_cutoff=self.knowledge_cutoff,
            config_fingerprint=self.config_fingerprint,
            steps=self.steps,
            candidates=self.candidates,
            transitions=self.transitions,
            created_transitions=self.created_transitions,
            tombstone_pruned_transitions=self.tombstone_pruned_transitions,
            semantic_stream_sha256=self.semantic_stream_sha256,
            final_state_sha256=self.final_state_sha256,
            state_generation=self.state_generation,
            serialized_state_bytes=self.serialized_state_bytes,
            peak_active_lineages=self.peak_active_lineages,
            peak_terminal_tombstones=self.peak_terminal_tombstones,
            expected_groups=expected,
            present_groups=present,
            issuance_count=self.issuance_count,
            issuance_sha256=self.issuance_sha256,
            issuance_digest_algorithm=self.issuance_digest_algorithm,
        )
        if self.semantic_hash != semantic_hash:
            raise ValueError("streaming receipt semantic hash mismatch")
        object.__setattr__(self, "expected_groups", expected)
        object.__setattr__(self, "present_groups", present)
        object.__setattr__(
            self, "issuance_digest_algorithm", self.issuance_digest_algorithm
        )
        object.__setattr__(self, "issuance_count", self.issuance_count)
        object.__setattr__(self, "issuance_sha256", self.issuance_sha256)

    @staticmethod
    def _semantic_hash(**values: Any) -> str:
        return canonical_hash(values)

    @property
    def receipt_hash(self) -> str:
        return self.semantic_hash

    def semantic_mapping(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "source_manifest_id": self.source_manifest_id,
            "source_sha256": self.source_sha256,
            "source_slice_fingerprint": self.source_slice_fingerprint,
            "asset": self.asset,
            "venue": self.venue,
            "instrument_id": self.instrument_id,
            "analysis_start": self.analysis_start,
            "knowledge_cutoff": self.knowledge_cutoff,
            "config_fingerprint": self.config_fingerprint,
            "steps": self.steps,
            "candidates": self.candidates,
            "transitions": self.transitions,
            "created_transitions": self.created_transitions,
            "tombstone_pruned_transitions": self.tombstone_pruned_transitions,
            "semantic_stream_sha256": self.semantic_stream_sha256,
            "final_state_sha256": self.final_state_sha256,
            "state_generation": self.state_generation,
            "serialized_state_bytes": self.serialized_state_bytes,
            "peak_active_lineages": self.peak_active_lineages,
            "peak_terminal_tombstones": self.peak_terminal_tombstones,
            "expected_groups": self.expected_groups,
            "present_groups": self.present_groups,
            "issuance_count": self.issuance_count,
            "issuance_sha256": self.issuance_sha256,
            "issuance_digest_algorithm": self.issuance_digest_algorithm,
        }

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            **self.semantic_mapping(),
            "wall_duration_seconds": self.wall_duration_seconds,
            "peak_rss_bytes": self.peak_rss_bytes,
            "semantic_hash": self.semantic_hash,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class StreamingEvidenceResult:
    """Compact streaming result; source bars remain caller-owned."""

    receipt: StreamingStructuralReceipt
    episodes: tuple[EpisodeIssuance, ...]
    source_records_by_timeframe: Mapping[str, tuple[SourceBarRecord | SRBar, ...]]
    acquisition_evidence: tuple[tuple[str, str, datetime, str], ...]
    full_bounds: tuple[tuple[str, datetime, datetime], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, StreamingStructuralReceipt):
            raise TypeError("receipt must be StreamingStructuralReceipt")
        episodes = tuple(
            sorted(
                self.episodes,
                key=lambda item: (item.issuance_cutoff, item.observation_id),
            )
        )
        if any(not isinstance(item, EpisodeIssuance) for item in episodes):
            raise TypeError("episodes must contain EpisodeIssuance values")
        issuance_ids = tuple(item.observation_id for item in episodes)
        if issuance_ids and (
            len(issuance_ids) != self.receipt.issuance_count
            or _sequence_digest(iter(issuance_ids)) != self.receipt.issuance_sha256
        ):
            raise ValueError("receipt issuance digest differs from episode index")
        # The authenticated writer intentionally finishes a collector with no
        # retained episode objects.  Its rolling issuance receipt remains the
        # authority for a non-empty panel; bounded fixtures retain and verify
        # the concrete episode index above.
        records = {
            str(timeframe): tuple(values)
            for timeframe, values in self.source_records_by_timeframe.items()
        }
        if set(records) != {item[0] for item in self.full_bounds}:
            raise ValueError("evidence source records and bounds differ")
        object.__setattr__(self, "episodes", episodes)
        object.__setattr__(
            self, "source_records_by_timeframe", MappingProxyType(records)
        )
        object.__setattr__(
            self, "acquisition_evidence", tuple(self.acquisition_evidence)
        )
        object.__setattr__(self, "full_bounds", tuple(self.full_bounds))


class EpisodeEvidenceCollector:
    """One sequential bounded collector attached to ``OfflineCompute.run``."""

    def __init__(
        self,
        *,
        config: ResolvedSRV2Config,
        source_records_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
        source_manifest_id: str,
        source_sha256: str,
        asset: str,
        venue: str,
        instrument_id: str,
        analysis_start: datetime,
        knowledge_cutoff: datetime,
        null_seed: str,
        source_slice_fingerprint: str | None = None,
        acquisition_evidence: Sequence[tuple[str, str, datetime, str]] = (),
        full_bounds: Mapping[str, tuple[datetime, datetime]] | None = None,
        max_workers: int = 1,
        episode_callback: Callable[[EpisodeIssuance], None] | None = None,
        retain_episodes: bool = True,
    ) -> None:
        if not isinstance(config, ResolvedSRV2Config):
            raise TypeError("config must be ResolvedSRV2Config")
        if max_workers != 1:
            raise ValueError(
                "streaming episode evidence is sequential and requires max_workers=1"
            )
        require_utc(analysis_start, field_name="analysis_start")
        require_utc(knowledge_cutoff, field_name="knowledge_cutoff")
        if knowledge_cutoff < analysis_start:
            raise ValueError("knowledge_cutoff must follow analysis_start")
        if not isinstance(null_seed, str) or not null_seed.strip():
            raise ValueError("null_seed must be non-empty")
        ordered = tuple(config.ladder)
        if set(source_records_by_timeframe) != set(ordered):
            raise ValueError(
                "episode evidence source must cover the exact configured ladder"
            )
        records = {
            timeframe: tuple(source_records_by_timeframe[timeframe])
            for timeframe in ordered
        }
        for timeframe in ordered:
            values = records[timeframe]
            if not values:
                raise ValueError(f"episode evidence source is empty for {timeframe}")
            bars = tuple(_bar(item) for item in values)
            if any(item.timeframe != timeframe for item in bars):
                raise ValueError("episode evidence source timeframe mismatch")
            grid_for(timeframe).validate_contiguous(
                tuple(item.bar_open_at for item in bars),
                tuple(item.bar_close_at for item in bars),
            )
            if any(
                isinstance(item, SourceBarRecord)
                and (
                    item.asset != asset
                    or item.venue != venue
                    or item.instrument_id != instrument_id
                )
                for item in values
            ):
                raise ValueError("episode evidence source record identity mismatch")
        bounds = full_bounds or {
            timeframe: (
                _bar(records[timeframe][0]).bar_open_at,
                _bar(records[timeframe][-1]).bar_close_at,
            )
            for timeframe in ordered
        }
        normalized_bounds = tuple(
            (timeframe, bounds[timeframe][0], bounds[timeframe][1])
            for timeframe in ordered
        )
        for timeframe, start, end in normalized_bounds:
            require_utc(start, field_name=f"{timeframe} source start")
            require_utc(end, field_name=f"{timeframe} source end")
            if (
                _bar(records[timeframe][0]).bar_open_at != start
                or _bar(records[timeframe][-1]).bar_close_at != end
            ):
                raise ValueError(
                    "episode evidence source does not cover declared full bounds"
                )
        if source_slice_fingerprint is None:
            direct_sha256 = _direct_source_sha256(records)
            expected_manifest_id = canonical_hash(
                {"schema": "sr_v2.direct_source@1", "source_sha256": direct_sha256}
            )
            if (
                source_sha256 != direct_sha256
                or source_manifest_id != expected_manifest_id
            ):
                raise ValueError(
                    "unbound streaming source identity must be derived from normalized bars"
                )
        elif (
            not isinstance(source_slice_fingerprint, str)
            or not source_slice_fingerprint.strip()
        ):
            raise ValueError("source_slice_fingerprint must be non-empty when supplied")
        self.config = config
        self.records_by_timeframe = records
        self.source_manifest_id = source_manifest_id
        self.source_sha256 = source_sha256
        self.source_slice_fingerprint = source_slice_fingerprint
        self.asset = asset
        self.venue = venue
        self.instrument_id = instrument_id
        self.analysis_start = analysis_start
        self.knowledge_cutoff = knowledge_cutoff
        self.null_seed = null_seed
        self.acquisition_evidence = tuple(acquisition_evidence)
        self.full_bounds = normalized_bounds
        self.expected_groups = tuple(
            sorted(
                ScientificGroupKey(
                    asset=asset,
                    timeframe=timeframe,
                    kernel_id=kernel.kernel_id,
                    kernel_version=kernel.kernel_version,
                    side=side,
                )
                for timeframe in ordered
                for kernel in config.kernels
                if kernel.enabled_for(timeframe)
                for side in ZoneSide
            )
        )
        self._stream = hashlib.sha256()
        if not isinstance(retain_episodes, bool):
            raise TypeError("retain_episodes must be bool")
        if episode_callback is not None and not callable(episode_callback):
            raise TypeError("episode_callback must be callable")
        self._episode_callback = episode_callback
        self._retain_episodes = retain_episodes
        self.steps = 0
        self.candidates = 0
        self.transitions = 0
        self.created_transitions = 0
        self.tombstone_pruned_transitions = 0
        self.peak_active_lineages = 0
        self.peak_terminal_tombstones = 0
        self._episodes: list[EpisodeIssuance] | None = [] if retain_episodes else None
        self._episode_ids: set[str] | None = set() if retain_episodes else None
        self._cluster_counts: Counter[str] | None = (
            Counter() if retain_episodes else None
        )
        self._issuance_digest = hashlib.sha256()
        self._issuance_count = 0
        self._present_groups: set[ScientificGroupKey] = set()
        self._trigger_bars = tuple(
            _bar(item) for item in self.records_by_timeframe[config.trigger_timeframe]
        )
        self._trigger_opens = tuple(item.bar_open_at for item in self._trigger_bars)
        self._source_indexes = {
            timeframe: tuple(_bar(item).bar_close_at for item in values)
            for timeframe, values in self.records_by_timeframe.items()
        }
        self._started = time.monotonic()

    @classmethod
    def from_authenticated_slice(
        cls,
        source_slice: AuthenticatedSourceSlice,
        *,
        config: ResolvedSRV2Config,
        analysis_start: datetime,
        knowledge_cutoff: datetime,
        null_seed: str,
        max_workers: int = 1,
        episode_callback: Callable[[EpisodeIssuance], None] | None = None,
        retain_episodes: bool = True,
    ) -> EpisodeEvidenceCollector:
        return cls(
            config=config,
            source_records_by_timeframe=source_slice.records_by_timeframe,
            source_manifest_id=source_slice.source_manifest_id,
            source_sha256=source_slice.source_sha256,
            source_slice_fingerprint=source_slice.slice_fingerprint,
            asset=source_slice.asset,
            venue=source_slice.venue,
            instrument_id=source_slice.instrument_id,
            analysis_start=analysis_start,
            knowledge_cutoff=knowledge_cutoff,
            null_seed=null_seed,
            acquisition_evidence=source_slice.acquisition_evidence,
            full_bounds={
                timeframe: (start, end) for timeframe, start, end in source_slice.bounds
            },
            max_workers=max_workers,
            episode_callback=episode_callback,
            retain_episodes=retain_episodes,
        )

    def _append_stream(self, payload: Mapping[str, Any]) -> None:
        encoded = canonical_json(payload).encode("utf-8")
        self._stream.update(len(encoded).to_bytes(8, "big"))
        self._stream.update(encoded)

    @staticmethod
    def _compact_state(state: SRState) -> Mapping[str, Any]:
        """Return the bounded state identity used in the per-step stream.

        The final state is serialized once at ``finish``.  Re-encoding every
        active lineage on every replay step would make the collector's memory
        and CPU cost track the historical trace, which is precisely what this
        evidence path is intended to avoid.
        """

        return {
            "generation": state.generation,
            "last_trigger_at": state.last_trigger_at,
            "source_cutoffs": state.source_cutoffs,
            "source_fingerprints": state.source_fingerprints,
            "active_lineage_count": len(state.active_lineages),
            "terminal_tombstone_count": len(state.terminal_tombstones),
        }

    def _kernel_window(self, zone: ZoneLineage) -> tuple[SRBar, ...]:
        identifier = f"{zone.kernel_id}@{zone.kernel_version}"
        kernel = next(
            (item for item in self.config.kernels if item.identifier == identifier),
            None,
        )
        if kernel is None:
            raise ValueError(f"created lineage kernel is not selected: {identifier}")
        required = int(
            kernel.spec.history_required(kernel.parameters_for(zone.source_timeframe))
        )
        closes = self._source_indexes[zone.source_timeframe]
        end = bisect_right(closes, zone.available_at)
        if end == 0 or closes[end - 1] != zone.available_at or end < required:
            raise ValueError("created lineage lacks exact causal kernel history")
        values = self.records_by_timeframe[zone.source_timeframe][end - required : end]
        return tuple(_bar(item) for item in values)

    def _null_for(
        self, zone: ZoneLineage, result: SRStepResult
    ) -> FeasibleRandomPriceNull:
        active = tuple(record.lineage for record in result.state.active_lineages)
        return build_feasible_random_price_null(
            zone,
            kernel_bars=self._kernel_window(zone),
            active_zones=active,
            seed=self.null_seed,
        )

    def _trigger_identity_after(
        self, issued_at: datetime
    ) -> tuple[int | None, str | None]:
        index = bisect_left(self._trigger_opens, issued_at)
        if index >= len(self._trigger_bars):
            return None, None
        if self._trigger_bars[index].bar_open_at < issued_at:
            index += 1
        if index >= len(self._trigger_bars):
            return None, None
        return index, self._trigger_bars[index].identity

    @staticmethod
    def _committed_records(result: SRStepResult) -> Mapping[str, ZoneRecord]:
        return {
            item.lineage.zone_id: item
            for item in result.state.active_lineages + result.state.terminal_tombstones
        }

    def _record_created(
        self,
        transition: LifecycleTransition,
        result: SRStepResult,
        *,
        committed_records: Mapping[str, ZoneRecord] | None = None,
    ) -> None:
        if result.market_as_of < self.analysis_start:
            return
        if committed_records is None:
            committed_records = self._committed_records(result)
        committed_record = committed_records.get(transition.zone_id)
        if (
            committed_record is None
            or committed_record.lifecycle is LifecycleState.SUPERSEDED
        ):
            return
        record = result.lineage_registry.get(transition.zone_id)
        if not isinstance(record, ZoneRecord):
            raise TypeError("committed CREATED lineage lacks an exact registry record")
        zone = record.lineage
        retain_episodes = getattr(self, "_retain_episodes", True)
        episode_ids = getattr(self, "_episode_ids", None)
        if retain_episodes and episode_ids is not None and zone.zone_id in episode_ids:
            raise ValueError("duplicate committed CREATED lineage identity")
        source_closes = self._source_indexes[zone.source_timeframe]
        source_index = bisect_right(source_closes, zone.available_at) - 1
        if source_index < 0 or source_closes[source_index] != zone.available_at:
            raise ValueError("created lineage has no exact native source close index")
        source_record = self.records_by_timeframe[zone.source_timeframe][source_index]
        null = self._null_for(zone, result)
        group = ScientificGroupKey(
            asset=zone.asset,
            timeframe=zone.source_timeframe,
            kernel_id=zone.kernel_id,
            kernel_version=zone.kernel_version,
            side=zone.side,
        )
        cluster_identity = canonical_hash(
            {
                "issuance_cutoff": zone.available_at,
                "side": zone.side,
                "center": zone.center,
                "lower": zone.lower,
                "upper": zone.upper,
            }
        )
        trigger_index, trigger_identity = self._trigger_identity_after(
            zone.available_at
        )
        episode = EpisodeIssuance(
            observation_id=zone.zone_id,
            group=group,
            zone=zone,
            issuance_cutoff=zone.available_at,
            source_close_index=source_index,
            source_close_identity=_source_identity(source_record),
            first_subsequent_trigger_index=trigger_index,
            first_subsequent_trigger_identity=trigger_identity,
            feasible_null=null,
            cluster_identity=cluster_identity,
        )
        episode_callback = getattr(self, "_episode_callback", None)
        if episode_callback is not None:
            episode_callback(episode)
        encoded_id = canonical_json(episode.observation_id).encode("utf-8")
        self._issuance_digest.update(len(encoded_id).to_bytes(8, "big"))
        self._issuance_digest.update(encoded_id)
        self._issuance_count += 1
        if retain_episodes:
            episodes = getattr(self, "_episodes", None)
            if episodes is None:
                raise RuntimeError("episode retention storage is unavailable")
            cluster_counts = getattr(self, "_cluster_counts", None)
            if cluster_counts is None:
                raise RuntimeError("episode cluster storage is unavailable")
            episodes.append(episode)
            if episode_ids is not None:
                episode_ids.add(zone.zone_id)
            cluster_counts[cluster_identity] += 1
        self._present_groups.add(group)

    def on_step(self, result: SRStepResult) -> None:
        """Consume one structural result while retaining bounded evidence only."""

        if not isinstance(result, SRStepResult):
            raise TypeError("episode evidence callback requires SRStepResult")
        if (
            result.asset != self.asset
            or result.config_fingerprint != self.config.config_fingerprint
        ):
            raise ValueError("episode evidence step identity differs from collector")
        self.steps += 1
        candidate_count = sum(
            len(values) for values in result.candidates_by_timeframe.values()
        )
        self.candidates += candidate_count
        self.transitions += len(result.transitions)
        created = tuple(
            sorted(
                (
                    item
                    for item in result.transitions
                    if item.transition_type is TransitionType.CREATED
                ),
                key=lambda item: item.zone_id,
            )
        )
        self.created_transitions += len(created)
        self.tombstone_pruned_transitions += sum(
            item.transition_type is TransitionType.TOMBSTONE_PRUNED
            for item in result.transitions
        )
        self.peak_active_lineages = max(
            self.peak_active_lineages, len(result.state.active_lineages)
        )
        self.peak_terminal_tombstones = max(
            self.peak_terminal_tombstones,
            len(result.state.terminal_tombstones),
        )
        self._append_stream(
            {
                "cutoff": result.market_as_of,
                "candidate_count": candidate_count,
                "transition_count": len(result.transitions),
                "candidate_ids": tuple(
                    (timeframe, candidate.candidate_key, candidate.source_evidence_id)
                    for timeframe in sorted(result.candidates_by_timeframe)
                    for candidate in result.candidates_by_timeframe[timeframe]
                ),
                "created_ids": tuple(item.zone_id for item in created),
                "tombstone_pruned_count": sum(
                    item.transition_type is TransitionType.TOMBSTONE_PRUNED
                    for item in result.transitions
                ),
                "transition_ids": tuple(
                    item.transition_id for item in result.transitions
                ),
                "source_cutoffs": result.source_cutoffs,
                "source_fingerprints": result.source_fingerprints,
                "state": self._compact_state(result.state),
            }
        )
        committed_records = (
            self._committed_records(result)
            if created and result.market_as_of >= self.analysis_start
            else None
        )
        for transition in created:
            self._record_created(
                transition,
                result,
                committed_records=committed_records,
            )

    def finish(
        self,
        run_state: SRState,
        *,
        wall_duration_seconds: float | None = None,
        peak_rss_bytes: int | None = None,
    ) -> StreamingEvidenceResult:
        if self.steps <= 0:
            raise ValueError("cannot finish episode evidence without structural steps")
        if not isinstance(run_state, SRState):
            raise TypeError("run_state must be SRState")
        if run_state.last_trigger_at != self.knowledge_cutoff:
            raise ValueError(
                "episode evidence state cutoff differs from knowledge cutoff"
            )
        episodes = (
            tuple(sorted(self._episodes, key=lambda item: item.observation_id))
            if self._retain_episodes
            else ()
        )
        if self._retain_episodes:
            # The issuance objects are private until this result is returned.
            # Fill their immutable-by-contract field in place so finalization
            # does not retain a second full object collection for a fixture.
            for item in episodes:
                object.__setattr__(
                    item,
                    "cluster_multiplicity",
                    self._cluster_counts[item.cluster_identity],
                )
        state_bytes = encode_state(run_state)
        expected = tuple(self.expected_groups)
        present = tuple(sorted(self._present_groups))
        semantic_values = {
            "schema": EPISODE_EVIDENCE_SCHEMA,
            "source_manifest_id": self.source_manifest_id,
            "source_sha256": self.source_sha256,
            "source_slice_fingerprint": self.source_slice_fingerprint,
            "asset": self.asset,
            "venue": self.venue,
            "instrument_id": self.instrument_id,
            "analysis_start": self.analysis_start,
            "knowledge_cutoff": self.knowledge_cutoff,
            "config_fingerprint": self.config.config_fingerprint,
            "steps": self.steps,
            "candidates": self.candidates,
            "transitions": self.transitions,
            "created_transitions": self.created_transitions,
            "tombstone_pruned_transitions": self.tombstone_pruned_transitions,
            "semantic_stream_sha256": self._stream.hexdigest(),
            "final_state_sha256": hashlib.sha256(state_bytes).hexdigest(),
            "state_generation": run_state.generation,
            "serialized_state_bytes": len(state_bytes),
            "peak_active_lineages": self.peak_active_lineages,
            "peak_terminal_tombstones": self.peak_terminal_tombstones,
            "expected_groups": expected,
            "present_groups": present,
            "issuance_digest_algorithm": ISSUANCE_SEQUENCE_HASH_ALGORITHM,
            "issuance_count": self._issuance_count,
            "issuance_sha256": self._issuance_digest.hexdigest(),
        }
        receipt = StreamingStructuralReceipt(
            **semantic_values,
            wall_duration_seconds=(
                time.monotonic() - self._started
                if wall_duration_seconds is None
                else wall_duration_seconds
            ),
            peak_rss_bytes=_rss_bytes() if peak_rss_bytes is None else peak_rss_bytes,
            semantic_hash=canonical_hash(semantic_values),
        )
        return StreamingEvidenceResult(
            receipt=receipt,
            episodes=episodes,
            source_records_by_timeframe=self.records_by_timeframe,
            acquisition_evidence=self.acquisition_evidence,
            full_bounds=self.full_bounds,
        )


def run_streaming_episode_evidence(
    *,
    config: ResolvedSRV2Config,
    source_records_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
    source_manifest_id: str,
    source_sha256: str,
    asset: str,
    venue: str,
    instrument_id: str,
    analysis_start: datetime,
    knowledge_cutoff: datetime,
    null_seed: str,
    source_slice_fingerprint: str | None = None,
    acquisition_evidence: Sequence[tuple[str, str, datetime, str]] = (),
    full_bounds: Mapping[str, tuple[datetime, datetime]] | None = None,
    max_workers: int = 1,
) -> StreamingEvidenceResult:
    """Run one sequential structural replay and return compact evidence."""

    collector = EpisodeEvidenceCollector(
        config=config,
        source_records_by_timeframe=source_records_by_timeframe,
        source_manifest_id=source_manifest_id,
        source_sha256=source_sha256,
        source_slice_fingerprint=source_slice_fingerprint,
        asset=asset,
        venue=venue,
        instrument_id=instrument_id,
        analysis_start=analysis_start,
        knowledge_cutoff=knowledge_cutoff,
        null_seed=null_seed,
        acquisition_evidence=acquisition_evidence,
        full_bounds=full_bounds,
        max_workers=max_workers,
    )
    bars = {
        timeframe: tuple(_bar(item) for item in values)
        for timeframe, values in collector.records_by_timeframe.items()
    }
    compute = OfflineCompute(
        config, venue=venue, instrument_id=instrument_id, asset=asset
    )
    result = compute.run(
        bars,
        cutoff=knowledge_cutoff,
        start_cutoff=analysis_start - config.expiry,
        on_step=collector.on_step,
    )
    return collector.finish(result.state)


def run_streaming_episode_evidence_twice(
    **kwargs: Any,
) -> tuple[StreamingEvidenceResult, StreamingEvidenceResult]:
    """Run the frozen baseline twice and require semantic receipt equality."""

    first = run_streaming_episode_evidence(**kwargs)
    second = run_streaming_episode_evidence(**kwargs)
    if first.receipt.semantic_hash != second.receipt.semantic_hash:
        raise ValueError("repeated structural streaming receipts differ semantically")
    if first.receipt.semantic_mapping() != second.receipt.semantic_mapping():
        raise ValueError("repeated structural streaming receipts differ semantically")
    if tuple(item.to_mapping() for item in first.episodes) != tuple(
        item.to_mapping() for item in second.episodes
    ):
        raise ValueError("repeated structural episode indexes differ")
    return first, second


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate artifact key: {key}")
        result[key] = value
    return result


def _decode_artifact_value(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_decode_artifact_value(item) for item in value)
    if not isinstance(value, dict):
        return value
    if set(value) == {"__decimal__"}:
        if not isinstance(value["__decimal__"], str):
            raise ValueError("encoded artifact Decimal is malformed")
        return Decimal(value["__decimal__"])
    if set(value) == {"__datetime__"}:
        if not isinstance(value["__datetime__"], str):
            raise ValueError("encoded artifact datetime is malformed")
        return datetime.fromisoformat(value["__datetime__"])
    if set(value) == {"__timedelta_us__"}:
        micros = value["__timedelta_us__"]
        if isinstance(micros, bool) or not isinstance(micros, int):
            raise ValueError("encoded artifact timedelta is malformed")
        return timedelta(microseconds=micros)
    return {key: _decode_artifact_value(item) for key, item in value.items()}


def _require_mapping_keys(
    value: Any, expected: set[str], name: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{name} keys do not match exactly")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class FixtureIndexedTargetTupleResult:
    """One target tuple materialized from a shared episode index."""

    tuple_id: str
    target_fingerprints: tuple[tuple[str, str], ...]
    compiled: CompiledScientificSet
    risk_observation_ids: tuple[str, ...]
    excluded_observation_ids: tuple[str, ...]
    excluded_reasons: tuple[tuple[str, str], ...]
    target_family_fingerprint: str
    risk_set_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.tuple_id, str) or not self.tuple_id.strip():
            raise ValueError("indexed target tuple_id must be non-empty")
        if not isinstance(self.compiled, CompiledScientificSet):
            raise TypeError(
                "indexed target compiled result must be CompiledScientificSet"
            )
        risk = tuple(self.risk_observation_ids)
        excluded = tuple(self.excluded_observation_ids)
        reasons = tuple(sorted(self.excluded_reasons))
        if len(set(risk)) != len(risk) or len(set(excluded)) != len(excluded):
            raise ValueError("indexed target risk identities must be unique")
        if set(risk) & set(excluded):
            raise ValueError("indexed target risk and excluded identities overlap")
        if tuple(item[0] for item in reasons) != tuple(sorted(excluded)):
            raise ValueError("indexed target exclusions must have one reason each")
        if any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0].strip()
            or not isinstance(item[1], str)
            or not item[1].strip()
            for item in reasons
        ):
            raise ValueError("indexed target exclusion reasons are malformed")
        if len(self.target_family_fingerprint) != 64:
            raise ValueError("indexed target family fingerprint must be SHA-256")
        observed = tuple(item.observation_id for item in self.compiled.observations)
        if observed != tuple(sorted(risk)):
            raise ValueError(
                "indexed target observations do not equal the common risk set"
            )
        expected = canonical_hash(
            {
                "risk_observation_ids": tuple(sorted(risk)),
                "excluded_observation_ids": tuple(sorted(excluded)),
                "excluded_reasons": reasons,
                "target_family_fingerprint": self.target_family_fingerprint,
            }
        )
        if self.risk_set_fingerprint != expected:
            raise ValueError("indexed target risk-set fingerprint mismatch")
        object.__setattr__(self, "risk_observation_ids", tuple(sorted(risk)))
        object.__setattr__(self, "excluded_observation_ids", tuple(sorted(excluded)))
        object.__setattr__(self, "excluded_reasons", reasons)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_observation_ids)


@dataclass(frozen=True, slots=True, kw_only=True)
class FixtureIndexedTargetMaterialization:
    """Compact common-risk plan shared by one-at-a-time target materialization.

    The plan retains only the authenticated shared bars, compact episode index,
    and target specifications.  It deliberately does not retain any compiled
    observations, so iterating many tuples cannot retain the whole panel.
    """

    source_manifest_id: str
    source_sha256: str
    source_slice_fingerprint: str
    expected_groups: tuple[ScientificGroupKey, ...]
    target_specs: tuple[tuple[str, tuple[tuple[str, ResolvedTargetSpec], ...]], ...]
    episodes: tuple[EpisodeIssuance, ...]
    bars_by_timeframe: Mapping[str, tuple[SRBar, ...]]
    source_record_identity_hashes: tuple[tuple[str, str], ...]
    episode_indexes: tuple[tuple[str, int, int], ...]
    knowledge_cutoff: datetime
    risk_observation_ids: tuple[str, ...]
    excluded_observation_ids: tuple[str, ...]
    excluded_reasons: tuple[tuple[str, str], ...]
    target_family_fingerprint: str
    risk_set_fingerprint: str

    def __post_init__(self) -> None:
        if not self.source_manifest_id.strip() or not self.source_sha256.strip():
            raise ValueError("indexed target source identity must be non-empty")
        if len(self.source_slice_fingerprint) != 64:
            raise ValueError("indexed target source slice must be SHA-256")
        risk = tuple(sorted(self.risk_observation_ids))
        excluded = tuple(sorted(self.excluded_observation_ids))
        reasons = tuple(sorted(self.excluded_reasons))
        if tuple(item[0] for item in reasons) != excluded:
            raise ValueError("indexed target exclusions must have one reason each")
        indexes = tuple(sorted(self.episode_indexes))
        if tuple(item[0] for item in indexes) != risk:
            raise ValueError("indexed target indexes must equal the common risk set")
        if len({item[0] for item in indexes}) != len(indexes):
            raise ValueError("indexed target indexes must be unique")
        if not self.target_specs:
            raise ValueError("indexed target materialization requires target tuples")
        tuple_ids = tuple(item[0] for item in self.target_specs)
        if any(not item.strip() for item in tuple_ids) or len(set(tuple_ids)) != len(
            tuple_ids
        ):
            raise ValueError(
                "indexed target tuple identities must be unique non-empty strings"
            )
        if any(
            not isinstance(spec, ResolvedTargetSpec)
            for _, specs in self.target_specs
            for _, spec in specs
        ):
            raise TypeError(
                "indexed target specifications must be ResolvedTargetSpec values"
            )
        if any(
            not isinstance(item, ScientificGroupKey) for item in self.expected_groups
        ):
            raise TypeError(
                "indexed target expected groups must be ScientificGroupKey values"
            )
        require_utc(self.knowledge_cutoff, field_name="knowledge_cutoff")
        bars = {
            str(timeframe): tuple(values)
            for timeframe, values in self.bars_by_timeframe.items()
        }
        if any(
            not values or any(not isinstance(bar, SRBar) for bar in values)
            for values in bars.values()
        ):
            raise ValueError("indexed target materialization bars are malformed")
        expected = canonical_hash(
            {
                "risk_observation_ids": risk,
                "excluded_observation_ids": excluded,
                "excluded_reasons": reasons,
                "target_family_fingerprint": self.target_family_fingerprint,
            }
        )
        if self.risk_set_fingerprint != expected:
            raise ValueError(
                "indexed target materialization risk-set fingerprint mismatch"
            )
        object.__setattr__(self, "expected_groups", tuple(sorted(self.expected_groups)))
        object.__setattr__(self, "target_specs", tuple(self.target_specs))
        object.__setattr__(
            self,
            "episodes",
            tuple(sorted(self.episodes, key=lambda item: item.observation_id)),
        )
        object.__setattr__(self, "bars_by_timeframe", MappingProxyType(bars))
        object.__setattr__(
            self,
            "source_record_identity_hashes",
            tuple(sorted(self.source_record_identity_hashes)),
        )
        object.__setattr__(self, "episode_indexes", indexes)
        object.__setattr__(self, "risk_observation_ids", risk)
        object.__setattr__(self, "excluded_observation_ids", excluded)
        object.__setattr__(self, "excluded_reasons", reasons)

    @property
    def tuple_ids(self) -> tuple[str, ...]:
        return tuple(item[0] for item in self.target_specs)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_observation_ids)

    def specs_for(self, tuple_id: str) -> Mapping[str, ResolvedTargetSpec]:
        for candidate_id, specs in self.target_specs:
            if candidate_id == tuple_id:
                return MappingProxyType(dict(specs))
        raise KeyError(f"unknown indexed target tuple: {tuple_id}")


def _episode_index_lookup(
    materialization: FixtureIndexedTargetMaterialization,
) -> Mapping[str, tuple[int, int]]:
    """Build one ephemeral O(1) lookup for a single target tuple."""

    return MappingProxyType(
        {
            observation_id: (source_index, future_start)
            for observation_id, source_index, future_start in materialization.episode_indexes
        }
    )


def _materialization_context(
    evidence: StreamingEvidenceResult,
) -> tuple[
    str,
    str,
    str,
    tuple[ScientificGroupKey, ...],
    tuple[EpisodeIssuance, ...],
    Mapping[str, tuple[SourceBarRecord | SRBar, ...]] | None,
    Mapping[str, tuple[str, ...] | tuple[str, int]] | None,
    datetime,
]:
    if isinstance(evidence, StreamingEvidenceResult):
        if evidence.receipt.source_slice_fingerprint is None:
            raise ValueError("indexed targets require an authenticated source slice")
        if any(
            not isinstance(item, SourceBarRecord)
            for records in evidence.source_records_by_timeframe.values()
            for item in records
        ):
            raise ValueError("indexed targets require authenticated source records")
        expected_slice_fingerprint = _authenticated_slice_fingerprint(
            source_manifest_id=evidence.receipt.source_manifest_id,
            source_sha256=evidence.receipt.source_sha256,
            venue=evidence.receipt.venue,
            instrument_id=evidence.receipt.instrument_id,
            asset=evidence.receipt.asset,
            bounds=evidence.full_bounds,
            records_by_timeframe=evidence.source_records_by_timeframe,
            acquisition_evidence=evidence.acquisition_evidence,
        )
        if evidence.receipt.source_slice_fingerprint != expected_slice_fingerprint:
            raise ValueError("indexed target source slice is not bound to records")
        return (
            evidence.receipt.source_manifest_id,
            evidence.receipt.source_sha256,
            evidence.receipt.source_slice_fingerprint or "",
            evidence.receipt.expected_groups,
            evidence.episodes,
            evidence.source_records_by_timeframe,
            {
                timeframe: tuple(_source_identity(item) for item in values)
                for timeframe, values in evidence.source_records_by_timeframe.items()
            },
            evidence.receipt.knowledge_cutoff,
        )
    raise TypeError("evidence must be StreamingEvidenceResult")


def prepare_fixture_indexed_target_materialization(
    evidence: StreamingEvidenceResult,
    *,
    target_specs: Sequence[tuple[str, Mapping[str, ResolvedTargetSpec]]],
    bars_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
) -> FixtureIndexedTargetMaterialization:
    """Prepare one common-risk indexed target plan without replay.

    The episode index supplies the exact integer source-close indexes.  One
    common right-edge risk set is computed from the largest requested horizon
    for each source timeframe before any tuple is labeled.
    """

    (
        source_manifest_id,
        source_sha256,
        source_slice_fingerprint,
        expected_groups,
        episodes,
        authenticated_records,
        authenticated_identities,
        knowledge_cutoff,
    ) = _materialization_context(evidence)
    if len(source_slice_fingerprint) != 64:
        raise ValueError(
            "indexed targets require an authenticated source slice fingerprint"
        )
    try:
        int(source_slice_fingerprint, 16)
    except ValueError as exc:
        raise ValueError("indexed target source slice must be SHA-256") from exc
    if not isinstance(bars_by_timeframe, Mapping) or not bars_by_timeframe:
        raise TypeError("bars_by_timeframe must be a non-empty mapping")
    raw_tuples = tuple(target_specs)
    if not raw_tuples:
        raise ValueError("target_specs must contain at least one ordered tuple")
    normalized_specs: list[tuple[str, tuple[tuple[str, ResolvedTargetSpec], ...]]] = []
    seen_tuple_ids: set[str] = set()
    source_timeframes: set[str] = set()
    observation_timeframes: set[str] = set()
    expected_source_keys: set[str] | None = None
    for tuple_id, raw_specs in raw_tuples:
        if (
            not isinstance(tuple_id, str)
            or not tuple_id.strip()
            or tuple_id in seen_tuple_ids
        ):
            raise ValueError("target tuple identities must be unique non-empty strings")
        if not isinstance(raw_specs, Mapping) or not raw_specs:
            raise TypeError(
                "each target tuple must map source timeframes to ResolvedTargetSpec"
            )
        specs = dict(raw_specs)
        if any(not isinstance(spec, ResolvedTargetSpec) for spec in specs.values()):
            raise TypeError("target tuple values must be ResolvedTargetSpec")
        if set(specs) != {spec.source_timeframe for spec in specs.values()}:
            raise ValueError("target tuple keys must equal each spec source timeframe")
        if any(key != spec.source_timeframe for key, spec in specs.items()):
            raise ValueError("target tuple key does not equal spec source timeframe")
        if expected_source_keys is None:
            expected_source_keys = set(specs)
        elif set(specs) != expected_source_keys:
            raise ValueError(
                "indexed target tuples must cover the same source timeframes"
            )
        normalized_specs.append((tuple_id, tuple(sorted(specs.items()))))
        seen_tuple_ids.add(tuple_id)
        source_timeframes.update(specs)
        observation_timeframes.update(
            spec.observation_timeframe for spec in specs.values()
        )
    target_family_fingerprint = target_family_fingerprint_from_choices(
        tuple(
            (
                tuple_id,
                tuple(
                    (timeframe, scientific_target_fingerprint(spec))
                    for timeframe, spec in specs
                ),
            )
            for tuple_id, specs in normalized_specs
        )
    )
    if len(observation_timeframes) != 1:
        raise ValueError("all indexed target tuples must use one observation timeframe")
    required_timeframes = source_timeframes | observation_timeframes
    if set(bars_by_timeframe) != required_timeframes:
        raise ValueError(
            "indexed target bars must cover exactly source and observation timeframes"
        )
    records = {
        timeframe: tuple(bars_by_timeframe[timeframe])
        for timeframe in required_timeframes
    }
    bars = {
        timeframe: tuple(_bar(item) for item in values)
        for timeframe, values in records.items()
    }
    for timeframe, values in bars.items():
        if not values or any(item.timeframe != timeframe for item in values):
            raise ValueError(
                "indexed target bars have an empty or mismatched timeframe"
            )
        grid_for(timeframe).validate_contiguous(
            tuple(item.bar_open_at for item in values),
            tuple(item.bar_close_at for item in values),
        )
    if authenticated_identities is None:
        raise ValueError(
            "indexed target source records require authenticated identities"
        )
    if set(records) - set(authenticated_identities):
        raise ValueError("indexed target source records lack authenticated identities")
    source_record_identity_hashes: list[tuple[str, str]] = []
    for timeframe in sorted(records):
        actual = records[timeframe]
        expected_identity = authenticated_identities[timeframe]
        if (
            isinstance(expected_identity, tuple)
            and len(expected_identity) == 2
            and isinstance(expected_identity[0], str)
            and isinstance(expected_identity[1], int)
        ):
            expected_identities = None
            expected_identity_hash = expected_identity[0]
            expected_count = expected_identity[1]
        elif isinstance(expected_identity, tuple):
            expected_identities = expected_identity
            expected_identity_hash = canonical_hash(expected_identities)
            expected_count = len(expected_identities)
        else:
            expected_identities = None
            expected_identity_hash = str(expected_identity)
            expected_count = None
        if expected_count is not None and expected_count != len(actual):
            raise ValueError(
                "indexed target bars differ from authenticated source records"
            )
        if expected_count is None and len(actual) <= 0:
            raise ValueError("indexed target source records are empty")
        if authenticated_records is not None:
            expected_records = tuple(authenticated_records[timeframe])
            if len(expected_records) != len(actual):
                raise ValueError(
                    "indexed target bars differ from authenticated source records"
                )
            for supplied, authenticated in zip(actual, expected_records, strict=True):
                if _bar(supplied) != _bar(authenticated) or _source_identity(
                    supplied
                ) != _source_identity(authenticated):
                    raise ValueError(
                        "indexed target bars differ from authenticated source records"
                    )
        actual_identities = tuple(_source_identity(item) for item in actual)
        if canonical_hash(actual_identities) != expected_identity_hash:
            raise ValueError(
                "indexed target bars differ from authenticated source identities"
            )
        source_record_identity_hashes.append((timeframe, expected_identity_hash))
    expected_group_set = set(expected_groups)
    if any(not isinstance(group, ScientificGroupKey) for group in expected_groups):
        raise TypeError(
            "indexed target expected groups must be ScientificGroupKey values"
        )
    episodes = tuple(sorted(episodes, key=lambda item: item.observation_id))
    max_lookback = {
        timeframe: max(
            spec.reference_lookback
            for _, specs in normalized_specs
            for key, spec in specs
            if key == timeframe
        )
        for timeframe in source_timeframes
    }
    max_horizon = {
        timeframe: max(
            spec.horizon
            for _, specs in normalized_specs
            for key, spec in specs
            if key == timeframe
        )
        for timeframe in source_timeframes
    }
    observation_timeframe = next(iter(observation_timeframes))
    observation_bars = bars[observation_timeframe]
    observation_opens = tuple(item.bar_open_at for item in observation_bars)
    observation_duration = grid_for(observation_timeframe).duration
    source_indexes: dict[str, tuple[int, int]] = {}
    excluded_reasons: list[tuple[str, str]] = []
    for episode in episodes:
        if episode.group not in expected_group_set:
            raise ValueError(
                "episode group is outside the authenticated expected ontology"
            )
        timeframe = episode.group.timeframe
        if timeframe not in source_timeframes:
            raise ValueError("episode source timeframe has no target specification")
        values = bars[timeframe]
        source_index = episode.source_close_index
        if source_index >= len(values) or source_index < 0:
            raise ValueError(
                "episode source close index is outside the authenticated bars"
            )
        source_bar = records[timeframe][source_index]
        if (
            source_bar.bar_close_at != episode.issuance_cutoff
            or _source_identity(source_bar) != episode.source_close_identity
        ):
            raise ValueError("episode source close index/identity is not authenticated")
        trigger_index = bisect_left(observation_opens, episode.issuance_cutoff)
        expected_trigger_index = (
            trigger_index if trigger_index < len(observation_bars) else None
        )
        expected_trigger_identity = (
            observation_bars[trigger_index].identity
            if expected_trigger_index is not None
            else None
        )
        if (
            episode.first_subsequent_trigger_index != expected_trigger_index
            or episode.first_subsequent_trigger_identity != expected_trigger_identity
        ):
            raise ValueError(
                "episode first subsequent trigger identity is not authenticated"
            )
        if source_index < max_lookback[timeframe]:
            excluded_reasons.append(
                (episode.observation_id, "insufficient_source_history")
            )
            continue
        first = bisect_left(observation_opens, episode.issuance_cutoff)
        if (
            first >= len(observation_bars)
            or observation_opens[first] != episode.issuance_cutoff
        ):
            raise ValueError(
                "indexed target issuance is not aligned to the observation grid"
            )
        horizon_bars = int(max_horizon[timeframe] / observation_duration)
        end_index = first + horizon_bars
        if (
            end_index > len(observation_bars)
            or episode.issuance_cutoff + max_horizon[timeframe] > knowledge_cutoff
        ):
            excluded_reasons.append((episode.observation_id, "right_edge_horizon"))
            continue
        if (
            observation_bars[end_index - 1].bar_close_at
            != episode.issuance_cutoff + max_horizon[timeframe]
        ):
            raise ValueError(
                "indexed target observation bars contain an authenticated gap"
            )
        source_indexes[episode.observation_id] = (source_index, first)
    excluded_reasons_tuple = tuple(sorted(excluded_reasons))
    excluded = tuple(item[0] for item in excluded_reasons_tuple)
    risk_ids = tuple(sorted(source_indexes))
    materialization_risk_fingerprint = canonical_hash(
        {
            "risk_observation_ids": risk_ids,
            "excluded_observation_ids": excluded,
            "excluded_reasons": excluded_reasons_tuple,
            "target_family_fingerprint": target_family_fingerprint,
        }
    )
    return FixtureIndexedTargetMaterialization(
        source_manifest_id=source_manifest_id,
        source_sha256=source_sha256,
        source_slice_fingerprint=source_slice_fingerprint,
        expected_groups=expected_groups,
        target_specs=tuple(normalized_specs),
        episodes=episodes,
        bars_by_timeframe=bars,
        source_record_identity_hashes=tuple(source_record_identity_hashes),
        episode_indexes=tuple(
            (observation_id, values[0], values[1])
            for observation_id, values in source_indexes.items()
        ),
        knowledge_cutoff=knowledge_cutoff,
        risk_observation_ids=risk_ids,
        excluded_observation_ids=excluded,
        excluded_reasons=excluded_reasons_tuple,
        target_family_fingerprint=target_family_fingerprint,
        risk_set_fingerprint=materialization_risk_fingerprint,
    )


def materialize_fixture_indexed_target(
    materialization: FixtureIndexedTargetMaterialization,
    *,
    tuple_id: str,
) -> FixtureIndexedTargetTupleResult:
    """Materialize exactly one target tuple from a prepared common-risk plan."""

    if not isinstance(materialization, FixtureIndexedTargetMaterialization):
        raise TypeError("materialization must be FixtureIndexedTargetMaterialization")
    specs = materialization.specs_for(tuple_id)
    episodes_by_id = {item.observation_id: item for item in materialization.episodes}
    episode_index_lookup = _episode_index_lookup(materialization)
    observations: list[ScientificObservation] = []
    target_fingerprints = tuple(
        (timeframe, scientific_target_fingerprint(spec))
        for timeframe, spec in sorted(specs.items())
    )
    observation_timeframe = next(
        iter({spec.observation_timeframe for spec in specs.values()})
    )
    observation_bars = materialization.bars_by_timeframe[observation_timeframe]
    for observation_id in materialization.risk_observation_ids:
        episode = episodes_by_id[observation_id]
        spec = specs[episode.group.timeframe]
        source_index, first = episode_index_lookup[observation_id]
        count = int(spec.horizon / grid_for(observation_timeframe).duration)
        reference_source = materialization.bars_by_timeframe[spec.source_timeframe]
        reference = reference_source[
            source_index - spec.reference_lookback : source_index + 1
        ]
        actual = label_scientific_target_indexed(
            episode.zone,
            issued_at=episode.issuance_cutoff,
            future_bars=observation_bars,
            future_start_index=first,
            future_end_index=first + count,
            target_spec=spec,
            reference_bars=reference,
        )
        null_target = None
        if episode.feasible_null.zone is not None:
            null_target = label_scientific_target_indexed(
                episode.feasible_null.zone,
                issued_at=episode.issuance_cutoff,
                future_bars=observation_bars,
                future_start_index=first,
                future_end_index=first + count,
                target_spec=spec,
                reference_bars=reference,
            )
        observations.append(
            ScientificObservation(
                observation_id=observation_id,
                group=episode.group,
                zone=episode.zone,
                target=actual,
                feasible_null=episode.feasible_null,
                null_target=null_target,
                source_manifest_id=materialization.source_manifest_id,
                source_sha256=materialization.source_sha256,
                target_fingerprint=scientific_target_fingerprint(spec),
                null_fingerprint=canonical_hash(episode.feasible_null.provenance),
            )
        )
    compiler_fingerprint = canonical_hash(
        {
            "schema": "sr_v2.indexed_target_materialization@1",
            "tuple_id": tuple_id,
            "target_fingerprints": target_fingerprints,
            "source_manifest_id": materialization.source_manifest_id,
            "source_sha256": materialization.source_sha256,
            "source_slice_fingerprint": materialization.source_slice_fingerprint,
            "risk_set_fingerprint": materialization.risk_set_fingerprint,
        }
    )
    compiled = CompiledScientificSet(
        source_manifest_id=materialization.source_manifest_id,
        source_sha256=materialization.source_sha256,
        expected_groups=materialization.expected_groups,
        observations=tuple(observations),
        compiler_fingerprint=compiler_fingerprint,
        knowledge_cutoff=materialization.knowledge_cutoff,
    )
    return FixtureIndexedTargetTupleResult(
        tuple_id=tuple_id,
        target_fingerprints=target_fingerprints,
        compiled=compiled,
        risk_observation_ids=materialization.risk_observation_ids,
        excluded_observation_ids=materialization.excluded_observation_ids,
        excluded_reasons=materialization.excluded_reasons,
        target_family_fingerprint=materialization.target_family_fingerprint,
        risk_set_fingerprint=materialization.risk_set_fingerprint,
    )


def iter_fixture_indexed_targets(
    evidence: StreamingEvidenceResult,
    *,
    target_specs: Sequence[tuple[str, Mapping[str, ResolvedTargetSpec]]],
    bars_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
) -> Iterator[FixtureIndexedTargetTupleResult]:
    """Yield target tuples one at a time from one common-risk plan."""

    plan = prepare_fixture_indexed_target_materialization(
        evidence,
        target_specs=target_specs,
        bars_by_timeframe=bars_by_timeframe,
    )
    for tuple_id in plan.tuple_ids:
        yield materialize_fixture_indexed_target(plan, tuple_id=tuple_id)


# ---------------------------------------------------------------------------
# Compact authenticated artifact @2
#
# The in-memory target helpers above remain bounded fixture APIs.  The public
# artifact boundary below is the only authenticated panel path: rows are
# compact, canonical, and consumed lazily.


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentitySequenceReceipt:
    """Count and ordered digest for one discarded provenance sequence."""

    count: int
    sha256: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.count, bool)
            or not isinstance(self.count, int)
            or self.count < 0
        ):
            raise ValueError("identity sequence count must be non-negative")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or self.sha256 != self.sha256.lower()
        ):
            raise ValueError("identity sequence SHA-256 must be lowercase 64-hex")
        try:
            int(self.sha256, 16)
        except ValueError as exc:
            raise ValueError("identity sequence SHA-256 must be hexadecimal") from exc

    @classmethod
    def from_ids(cls, values: Sequence[str]) -> IdentitySequenceReceipt:
        ids = tuple(values)
        if any(not isinstance(item, str) or not item.strip() for item in ids):
            raise ValueError("identity sequence values must be non-empty strings")
        return cls(count=len(ids), sha256=canonical_hash(ids))

    @classmethod
    def from_mapping(cls, value: Any) -> IdentitySequenceReceipt:
        raw = _require_mapping_keys(value, {"count", "sha256"}, "identity receipt")
        return cls(count=raw["count"], sha256=raw["sha256"])

    def to_mapping(self) -> Mapping[str, Any]:
        return {"count": self.count, "sha256": self.sha256}


_NULL_SEQUENCE_KEYS = (
    ("source_window", "source_window_bar_ids"),
    ("opportunity", "opportunity_bar_ids"),
    ("feasible_opportunity", "feasible_opportunity_bar_ids"),
    ("excluded_active_zone", "excluded_active_zone_ids"),
    ("selected_bar", "selected_bar_ids"),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompactNullReceipt:
    """Compact @3 null receipt with opaque full-provenance identity."""

    source_observation_id: str
    complete: bool
    reason: str | None
    null_fingerprint: str
    zone: ZoneLineage | None
    source_window: IdentitySequenceReceipt
    opportunity: IdentitySequenceReceipt
    feasible_opportunity: IdentitySequenceReceipt
    excluded_active_zone: IdentitySequenceReceipt
    selected_bar: IdentitySequenceReceipt

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_observation_id, str)
            or not self.source_observation_id.strip()
        ):
            raise ValueError("compact null source observation identity is required")
        if not isinstance(self.complete, bool):
            raise TypeError("compact null complete must be bool")
        if self.complete and self.zone is None:
            raise ValueError("complete compact null must contain a zone")
        if not self.complete and self.zone is not None:
            raise ValueError("incomplete compact null must not contain a zone")
        if self.complete and self.reason is not None:
            raise ValueError("complete compact null must not have a reason")
        if not self.complete and (
            not isinstance(self.reason, str) or not self.reason.strip()
        ):
            raise ValueError("incomplete compact null must explain its reason")
        _strict_sha256(self.null_fingerprint, "compact null fingerprint")
        for name in (
            "source_window",
            "opportunity",
            "feasible_opportunity",
            "excluded_active_zone",
            "selected_bar",
        ):
            if not isinstance(getattr(self, name), IdentitySequenceReceipt):
                raise TypeError(f"compact null {name} receipt is malformed")
        if self.zone is not None and self.zone.zone_id == self.source_observation_id:
            raise ValueError("compact null zone must have a distinct identity")

    @classmethod
    def from_null(cls, value: FeasibleRandomPriceNull) -> CompactNullReceipt:
        if not isinstance(value, FeasibleRandomPriceNull):
            raise TypeError("compact null requires FeasibleRandomPriceNull")
        provenance = value.provenance
        expected_fingerprint = canonical_hash(provenance)
        sequences: dict[str, IdentitySequenceReceipt] = {}
        for receipt_name, provenance_name in _NULL_SEQUENCE_KEYS:
            raw = provenance.get(provenance_name, ())
            if raw is None:
                raw = ()
            if not isinstance(raw, (tuple, list)):
                raise TypeError(f"null provenance {provenance_name} is malformed")
            sequences[receipt_name] = IdentitySequenceReceipt.from_ids(tuple(raw))
        if tuple(value.opportunity_bar_ids) != tuple(
            provenance.get("opportunity_bar_ids", ())
        ):
            raise ValueError("null opportunity provenance differs from null receipt")
        if tuple(value.excluded_active_zone_ids) != tuple(
            provenance.get("excluded_active_zone_ids", ())
        ):
            raise ValueError("null exclusion provenance differs from null receipt")
        return cls(
            source_observation_id=value.source_observation_id,
            complete=value.complete,
            reason=value.reason,
            null_fingerprint=expected_fingerprint,
            zone=value.zone,
            **sequences,
        )

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        actual_zone: ZoneLineage,
        manifest: Mapping[str, Any],
    ) -> CompactNullReceipt:
        raw = _require_mapping_keys(
            value,
            {
                "source_observation_id",
                "complete",
                "reason",
                "null_fingerprint",
                "zone",
                "source_window",
                "opportunity",
                "feasible_opportunity",
                "excluded_active_zone",
                "selected_bar",
            },
            "compact feasible null",
        )
        zone_value = raw["zone"]
        zone = None
        if zone_value is not None:
            zone_raw = _require_mapping_keys(
                zone_value,
                {
                    "zone_id",
                    "center",
                    "lower",
                    "upper",
                    "source_candidate_key",
                    "source_evidence_id",
                },
                "compact null zone",
            )
            zone = replace(
                actual_zone,
                zone_id=zone_raw["zone_id"],
                center=zone_raw["center"],
                lower=zone_raw["lower"],
                upper=zone_raw["upper"],
                source_candidate_key=zone_raw["source_candidate_key"],
                source_evidence_id=zone_raw["source_evidence_id"],
            )
        result = cls(
            source_observation_id=raw["source_observation_id"],
            complete=raw["complete"],
            reason=raw["reason"],
            null_fingerprint=raw["null_fingerprint"],
            zone=zone,
            source_window=IdentitySequenceReceipt.from_mapping(raw["source_window"]),
            opportunity=IdentitySequenceReceipt.from_mapping(raw["opportunity"]),
            feasible_opportunity=IdentitySequenceReceipt.from_mapping(
                raw["feasible_opportunity"]
            ),
            excluded_active_zone=IdentitySequenceReceipt.from_mapping(
                raw["excluded_active_zone"]
            ),
            selected_bar=IdentitySequenceReceipt.from_mapping(raw["selected_bar"]),
        )
        if result.source_observation_id != actual_zone.zone_id:
            raise ValueError("compact null source observation differs from actual zone")
        if result.complete and result.zone is None:
            raise ValueError("complete compact null row lacks geometry")
        if result.zone is not None and (
            result.zone.asset != manifest["asset"]
            or result.zone.venue != manifest["venue"]
        ):
            raise ValueError("compact null zone identity differs from artifact")
        return result

    def to_mapping(self) -> Mapping[str, Any]:
        zone = None
        if self.zone is not None:
            zone = {
                "zone_id": self.zone.zone_id,
                "center": self.zone.center,
                "lower": self.zone.lower,
                "upper": self.zone.upper,
                "source_candidate_key": self.zone.source_candidate_key,
                "source_evidence_id": self.zone.source_evidence_id,
            }
        return {
            "source_observation_id": self.source_observation_id,
            "complete": self.complete,
            "reason": self.reason,
            "null_fingerprint": self.null_fingerprint,
            "zone": zone,
            "source_window": self.source_window.to_mapping(),
            "opportunity": self.opportunity.to_mapping(),
            "feasible_opportunity": self.feasible_opportunity.to_mapping(),
            "excluded_active_zone": self.excluded_active_zone.to_mapping(),
            "selected_bar": self.selected_bar.to_mapping(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CompactEpisodeRecord:
    """One compact episode row reconstructed with manifest-owned identity."""

    observation_id: str
    group: ScientificGroupKey
    zone: ZoneLineage
    issuance_cutoff: datetime
    source_close_index: int
    source_close_identity: str
    first_subsequent_trigger_index: int | None
    first_subsequent_trigger_identity: str | None
    feasible_null: CompactNullReceipt
    cluster_identity: str

    def __post_init__(self) -> None:
        if self.observation_id != self.zone.zone_id:
            raise ValueError(
                "compact episode observation identity must equal zone identity"
            )
        if not isinstance(self.group, ScientificGroupKey):
            raise TypeError("compact episode group must be ScientificGroupKey")
        if self.group.asset != self.zone.asset or self.group.side is not self.zone.side:
            raise ValueError("compact episode group and zone identity differ")
        require_utc(self.issuance_cutoff, field_name="compact issuance_cutoff")
        if self.issuance_cutoff != self.zone.available_at:
            raise ValueError("compact issuance cutoff must equal zone availability")
        if (
            isinstance(self.source_close_index, bool)
            or not isinstance(self.source_close_index, int)
            or self.source_close_index < 0
        ):
            raise ValueError("compact source close index must be non-negative")
        if (
            not isinstance(self.source_close_identity, str)
            or not self.source_close_identity.strip()
        ):
            raise ValueError("compact source close identity must be non-empty")
        if self.first_subsequent_trigger_index is None:
            if self.first_subsequent_trigger_identity is not None:
                raise ValueError(
                    "compact missing trigger index cannot have an identity"
                )
        elif (
            self.first_subsequent_trigger_index < 0
            or not self.first_subsequent_trigger_identity
        ):
            raise ValueError(
                "compact trigger index and identity must be supplied together"
            )
        if not isinstance(self.feasible_null, CompactNullReceipt):
            raise TypeError("compact episode null must be CompactNullReceipt")
        if self.feasible_null.source_observation_id != self.observation_id:
            raise ValueError("compact episode null linkage differs from observation")
        _strict_sha256(self.cluster_identity, "compact cluster identity")

    @classmethod
    def from_episode(cls, value: EpisodeIssuance) -> CompactEpisodeRecord:
        if not isinstance(value, EpisodeIssuance):
            raise TypeError("compact episode requires EpisodeIssuance")
        return cls(
            observation_id=value.observation_id,
            group=value.group,
            zone=value.zone,
            issuance_cutoff=value.issuance_cutoff,
            source_close_index=value.source_close_index,
            source_close_identity=value.source_close_identity,
            first_subsequent_trigger_index=value.first_subsequent_trigger_index,
            first_subsequent_trigger_identity=value.first_subsequent_trigger_identity,
            feasible_null=CompactNullReceipt.from_null(value.feasible_null),
            cluster_identity=value.cluster_identity,
        )

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "observation_id": self.observation_id,
            "group": {
                "timeframe": self.group.timeframe,
                "kernel_id": self.group.kernel_id,
                "kernel_version": self.group.kernel_version,
                "side": self.group.side.value,
            },
            "zone": {
                "zone_id": self.zone.zone_id,
                "predecessor_id": self.zone.predecessor_id,
                "source_timeframe": self.zone.source_timeframe,
                "kernel_id": self.zone.kernel_id,
                "kernel_version": self.zone.kernel_version,
                "side": self.zone.side.value,
                "center": self.zone.center,
                "lower": self.zone.lower,
                "upper": self.zone.upper,
                "source_evidence_id": self.zone.source_evidence_id,
                "source_candidate_key": self.zone.source_candidate_key,
                "formed_at": self.zone.formed_at,
                "available_at": self.zone.available_at,
                "creation_atr": self.zone.creation_atr,
                "identity_schema_version": self.zone.identity_schema_version,
            },
            "issuance_cutoff": self.issuance_cutoff,
            "source_close_index": self.source_close_index,
            "source_close_identity": self.source_close_identity,
            "first_subsequent_trigger_index": self.first_subsequent_trigger_index,
            "first_subsequent_trigger_identity": self.first_subsequent_trigger_identity,
            "feasible_null": self.feasible_null.to_mapping(),
            "cluster_identity": self.cluster_identity,
        }


def _strict_sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        raise ValueError(f"{name} must be lowercase 64-hex SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be hexadecimal SHA-256") from exc
    return value


def _cluster_identity_for_row(row: CompactEpisodeRecord) -> str:
    return canonical_hash(
        {
            "issuance_cutoff": row.issuance_cutoff,
            "side": row.zone.side,
            "center": row.zone.center,
            "lower": row.zone.lower,
            "upper": row.zone.upper,
        }
    )


def _compact_zone_from_mapping(value: Any, manifest: Mapping[str, Any]) -> ZoneLineage:
    raw = _require_mapping_keys(
        value,
        {
            "zone_id",
            "predecessor_id",
            "source_timeframe",
            "kernel_id",
            "kernel_version",
            "side",
            "center",
            "lower",
            "upper",
            "source_evidence_id",
            "source_candidate_key",
            "formed_at",
            "available_at",
            "creation_atr",
            "identity_schema_version",
        },
        "compact episode zone",
    )
    return ZoneLineage(
        zone_id=raw["zone_id"],
        predecessor_id=raw["predecessor_id"],
        venue=manifest["venue"],
        instrument_id=manifest["instrument_id"],
        asset=manifest["asset"],
        source_timeframe=raw["source_timeframe"],
        kernel_id=raw["kernel_id"],
        kernel_version=raw["kernel_version"],
        side=ZoneSide(raw["side"]),
        center=raw["center"],
        lower=raw["lower"],
        upper=raw["upper"],
        source_evidence_id=raw["source_evidence_id"],
        source_candidate_key=raw["source_candidate_key"],
        formed_at=raw["formed_at"],
        available_at=raw["available_at"],
        creation_atr=raw["creation_atr"],
        config_fingerprint=manifest["baseline_config_fingerprint"],
        identity_schema_version=raw["identity_schema_version"],
    )


def _compact_group_from_mapping(
    value: Any, manifest: Mapping[str, Any]
) -> ScientificGroupKey:
    raw = _require_mapping_keys(
        value,
        {"timeframe", "kernel_id", "kernel_version", "side"},
        "compact episode group",
    )
    return ScientificGroupKey(
        asset=manifest["asset"],
        timeframe=raw["timeframe"],
        kernel_id=raw["kernel_id"],
        kernel_version=raw["kernel_version"],
        side=ZoneSide(raw["side"]),
    )


def _compact_episode_from_mapping(
    value: Any, manifest: Mapping[str, Any]
) -> CompactEpisodeRecord:
    raw = _require_mapping_keys(
        value,
        {
            "observation_id",
            "group",
            "zone",
            "issuance_cutoff",
            "source_close_index",
            "source_close_identity",
            "first_subsequent_trigger_index",
            "first_subsequent_trigger_identity",
            "feasible_null",
            "cluster_identity",
        },
        "compact episode row",
    )
    zone = _compact_zone_from_mapping(raw["zone"], manifest)
    return CompactEpisodeRecord(
        observation_id=raw["observation_id"],
        group=_compact_group_from_mapping(raw["group"], manifest),
        zone=zone,
        issuance_cutoff=raw["issuance_cutoff"],
        source_close_index=raw["source_close_index"],
        source_close_identity=raw["source_close_identity"],
        first_subsequent_trigger_index=raw["first_subsequent_trigger_index"],
        first_subsequent_trigger_identity=raw["first_subsequent_trigger_identity"],
        feasible_null=CompactNullReceipt.from_mapping(
            raw["feasible_null"], actual_zone=zone, manifest=manifest
        ),
        cluster_identity=raw["cluster_identity"],
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class EpisodeArtifact:
    """Manifest-only handle for one authenticated compact episode artifact."""

    artifact_id: str
    directory: Path
    manifest: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id.strip():
            raise ValueError("episode artifact ID must be non-empty")
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise ValueError("episode artifact directory must be regular")
        frozen_manifest = _freeze_artifact_value(self.manifest)
        if frozen_manifest.get("artifact_id") != self.artifact_id:
            raise ValueError("episode artifact handle identity differs from manifest")
        object.__setattr__(self, "manifest", frozen_manifest)


def _freeze_artifact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_artifact_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_artifact_value(item) for item in value)
    return value


def _group_manifest_value(group: ScientificGroupKey) -> Mapping[str, Any]:
    return {
        "asset": group.asset,
        "timeframe": group.timeframe,
        "kernel_id": group.kernel_id,
        "kernel_version": group.kernel_version,
        "side": group.side.value,
    }


def _group_from_manifest_value(value: Any) -> ScientificGroupKey:
    raw = _require_mapping_keys(
        value,
        {"asset", "timeframe", "kernel_id", "kernel_version", "side"},
        "artifact expected group",
    )
    return ScientificGroupKey(
        asset=raw["asset"],
        timeframe=raw["timeframe"],
        kernel_id=raw["kernel_id"],
        kernel_version=raw["kernel_version"],
        side=ZoneSide(raw["side"]),
    )


def _manifest_source_identity_hashes(
    records_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            timeframe,
            canonical_hash(tuple(_source_identity(item) for item in records)),
        )
        for timeframe, records in sorted(records_by_timeframe.items())
    )


def _manifest_source_counts(
    records_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
) -> tuple[tuple[str, int], ...]:
    return tuple(
        (timeframe, len(records))
        for timeframe, records in sorted(records_by_timeframe.items())
    )


def _artifact_identity_from_manifest_v2(
    manifest: Mapping[str, Any],
) -> Mapping[str, Any]:
    return {key: value for key, value in manifest.items() if key != "artifact_id"}


def _structural_manifest_fields(
    receipt: StreamingStructuralReceipt,
) -> Mapping[str, Any]:
    return {
        "structural_receipt_hash": receipt.semantic_hash,
        "semantic_stream_sha256": receipt.semantic_stream_sha256,
        "final_state_sha256": receipt.final_state_sha256,
        "state_generation": receipt.state_generation,
        "serialized_state_bytes": receipt.serialized_state_bytes,
        "steps": receipt.steps,
        "candidates": receipt.candidates,
        "transitions": receipt.transitions,
        "created_transitions": receipt.created_transitions,
        "tombstone_pruned_transitions": receipt.tombstone_pruned_transitions,
        "peak_active_lineages": receipt.peak_active_lineages,
        "peak_terminal_tombstones": receipt.peak_terminal_tombstones,
        "expected_groups": tuple(
            _group_manifest_value(item) for item in receipt.expected_groups
        ),
        "present_groups": tuple(
            _group_manifest_value(item) for item in receipt.present_groups
        ),
        "issuance_digest_algorithm": receipt.issuance_digest_algorithm,
        "issuance_count": receipt.issuance_count,
        "issuance_sha256": receipt.issuance_sha256,
        "analysis_start": receipt.analysis_start,
        "knowledge_cutoff": receipt.knowledge_cutoff,
        "config_fingerprint": receipt.config_fingerprint,
    }


def _structural_receipt_hash_from_manifest(manifest: Mapping[str, Any]) -> str:
    expected_groups = tuple(
        _group_from_manifest_value(item) for item in manifest["expected_groups"]
    )
    present_groups = tuple(
        _group_from_manifest_value(item) for item in manifest["present_groups"]
    )
    return canonical_hash(
        {
            "schema": EPISODE_EVIDENCE_SCHEMA,
            "source_manifest_id": manifest["source_manifest_id"],
            "source_sha256": manifest["source_sha256"],
            "source_slice_fingerprint": manifest["causal_slice_fingerprint"],
            "asset": manifest["asset"],
            "venue": manifest["venue"],
            "instrument_id": manifest["instrument_id"],
            "analysis_start": manifest["analysis_start"],
            "knowledge_cutoff": manifest["knowledge_cutoff"],
            "config_fingerprint": manifest["config_fingerprint"],
            "steps": manifest["steps"],
            "candidates": manifest["candidates"],
            "transitions": manifest["transitions"],
            "created_transitions": manifest["created_transitions"],
            "tombstone_pruned_transitions": manifest["tombstone_pruned_transitions"],
            "semantic_stream_sha256": manifest["semantic_stream_sha256"],
            "final_state_sha256": manifest["final_state_sha256"],
            "state_generation": manifest["state_generation"],
            "serialized_state_bytes": manifest["serialized_state_bytes"],
            "peak_active_lineages": manifest["peak_active_lineages"],
            "peak_terminal_tombstones": manifest["peak_terminal_tombstones"],
            "expected_groups": expected_groups,
            "present_groups": present_groups,
            "issuance_count": manifest["issuance_count"],
            "issuance_sha256": manifest["issuance_sha256"],
            "issuance_digest_algorithm": manifest["issuance_digest_algorithm"],
        }
    )


def _artifact_manifest_v2(
    *,
    receipt: StreamingStructuralReceipt,
    source_records_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
    acquisition_evidence: Sequence[tuple[str, str, datetime, str]],
    full_bounds: Sequence[tuple[str, datetime, datetime]],
    trigger_timeframe: str,
    baseline_config_fingerprint: str,
    baseline_yaml_sha256: str,
    code_policy_id: str,
    null_seed: str,
    episode_sha256: str,
    episode_bytes: int,
    episode_count: int,
    group_counts: Sequence[tuple[str, int]],
    cluster_count: int,
    cluster_multiplicity_sha256: str,
) -> Mapping[str, Any]:
    manifest: dict[str, Any] = {
        "schema": EPISODE_ARTIFACT_SCHEMA,
        "artifact_id": "",
        "asset": receipt.asset,
        "venue": receipt.venue,
        "instrument_id": receipt.instrument_id,
        "source_manifest_id": receipt.source_manifest_id,
        "source_sha256": receipt.source_sha256,
        "acquisition_evidence": tuple(acquisition_evidence),
        "full_bounds": tuple(full_bounds),
        "trigger_timeframe": trigger_timeframe,
        "source_record_identity_hashes": _manifest_source_identity_hashes(
            source_records_by_timeframe
        ),
        "source_record_counts": _manifest_source_counts(source_records_by_timeframe),
        "causal_slice_fingerprint": receipt.source_slice_fingerprint,
        "baseline_config_fingerprint": baseline_config_fingerprint,
        "baseline_yaml_sha256": baseline_yaml_sha256,
        "code_policy_id": code_policy_id,
        "null_algorithm": FEASIBLE_RANDOM_PRICE_ID,
        "null_seed": null_seed,
        "issuance_rule_id": ISSUANCE_RULE_ID,
        "episode_sha256": episode_sha256,
        "episode_bytes": episode_bytes,
        "episode_count": episode_count,
        "group_counts": tuple(sorted(group_counts)),
        "cluster_count": cluster_count,
        "cluster_multiplicity_sha256": cluster_multiplicity_sha256,
    }
    manifest.update(_structural_manifest_fields(receipt))
    identity = _artifact_identity_from_manifest_v2(manifest)
    manifest["artifact_id"] = canonical_hash(identity)
    return manifest


def _remove_temp_directory(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise ValueError("temporary artifact path is not a regular directory")
    for child in path.iterdir():
        if child.is_symlink() or not child.is_file():
            raise ValueError("temporary artifact contains an unexpected entry")
        child.unlink()
    path.rmdir()


def _finish_artifact_directory(
    *,
    temporary: Path,
    artifact_root: Path,
    asset: str,
    manifest: Mapping[str, Any],
    episodes_path: Path,
) -> EpisodeArtifact:
    try:
        manifest_bytes = (canonical_json(manifest) + "\n").encode("utf-8")
        manifest_path = temporary / "manifest.json"
        with manifest_path.open("wb") as handle:
            handle.write(manifest_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        # Authenticate the complete temporary artifact before it can become
        # visible at its content-addressed path.
        temporary_manifest = _validate_artifact_manifest(
            manifest_bytes, Path(str(manifest["artifact_id"]))
        )
        temporary_artifact = EpisodeArtifact(
            artifact_id=str(manifest["artifact_id"]),
            directory=temporary,
            manifest=temporary_manifest,
        )
        for _ in _iter_validated_artifact_rows(temporary_artifact):
            pass
        directory_fd = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        asset_root = artifact_root / asset
        target = asset_root / str(manifest["artifact_id"])

        def reuse_existing() -> EpisodeArtifact:
            if target.is_symlink() or not target.is_dir():
                raise ValueError("existing episode artifact target is not regular")
            existing = load_episode_artifact(target)
            existing_manifest = canonical_json(existing.manifest) + "\n"
            if existing_manifest.encode(
                "utf-8"
            ) != manifest_bytes or not _file_matches_bytes(
                target / "episodes.jsonl", episodes_path
            ):
                raise FileExistsError(
                    "episode artifact identity already exists with different bytes"
                )
            return existing

        if target.is_symlink() or target.exists():
            existing = reuse_existing()
            _remove_temp_directory(temporary)
            return existing
        try:
            os.rename(temporary, target)
        except FileExistsError:
            existing = reuse_existing()
            _remove_temp_directory(temporary)
            return existing
        except OSError:
            if target.is_symlink() or target.exists():
                existing = reuse_existing()
                _remove_temp_directory(temporary)
                return existing
            raise
        parent_fd = os.open(asset_root, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return EpisodeArtifact(
            artifact_id=str(manifest["artifact_id"]),
            directory=target,
            manifest=manifest,
        )
    except Exception:
        if temporary.exists():
            _remove_temp_directory(temporary)
        raise


def _file_matches_bytes(expected_path: Path, actual_path: Path) -> bool:
    try:
        with expected_path.open("rb") as expected, actual_path.open("rb") as actual:
            while True:
                expected_chunk = expected.read(1024 * 1024)
                actual_chunk = actual.read(1024 * 1024)
                if expected_chunk != actual_chunk:
                    return False
                if not expected_chunk:
                    return True
    except OSError:
        return False


def _validate_artifact_manifest(
    manifest_bytes: bytes, directory: Path
) -> Mapping[str, Any]:
    try:
        raw = json.loads(
            manifest_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
        manifest = _decode_artifact_value(raw)
        expected_keys = {
            "schema",
            "artifact_id",
            "asset",
            "venue",
            "instrument_id",
            "source_manifest_id",
            "source_sha256",
            "acquisition_evidence",
            "full_bounds",
            "trigger_timeframe",
            "source_record_identity_hashes",
            "source_record_counts",
            "causal_slice_fingerprint",
            "baseline_config_fingerprint",
            "baseline_yaml_sha256",
            "code_policy_id",
            "null_algorithm",
            "null_seed",
            "issuance_rule_id",
            "episode_sha256",
            "episode_bytes",
            "episode_count",
            "group_counts",
            "cluster_count",
            "cluster_multiplicity_sha256",
            "structural_receipt_hash",
            "semantic_stream_sha256",
            "final_state_sha256",
            "state_generation",
            "serialized_state_bytes",
            "steps",
            "candidates",
            "transitions",
            "created_transitions",
            "tombstone_pruned_transitions",
            "peak_active_lineages",
            "peak_terminal_tombstones",
            "expected_groups",
            "present_groups",
            "issuance_digest_algorithm",
            "issuance_count",
            "issuance_sha256",
            "analysis_start",
            "knowledge_cutoff",
            "config_fingerprint",
        }
        manifest = dict(
            _require_mapping_keys(manifest, expected_keys, "artifact manifest")
        )
        if canonical_json(manifest).encode("utf-8") + b"\n" != manifest_bytes:
            raise ValueError("artifact manifest is not canonical")
        if manifest["schema"] != EPISODE_ARTIFACT_SCHEMA:
            raise ValueError("unsupported episode artifact schema")
        if manifest["artifact_id"] != directory.name:
            raise ValueError("episode artifact path identity differs from manifest")
        for name in (
            "source_sha256",
            "causal_slice_fingerprint",
            "baseline_config_fingerprint",
            "baseline_yaml_sha256",
            "episode_sha256",
            "cluster_multiplicity_sha256",
            "structural_receipt_hash",
            "semantic_stream_sha256",
            "final_state_sha256",
            "issuance_sha256",
        ):
            _strict_sha256(manifest[name], f"artifact {name}")
        if (
            canonical_hash(_artifact_identity_from_manifest_v2(manifest))
            != manifest["artifact_id"]
        ):
            raise ValueError("episode artifact identity does not match manifest")
        if manifest["null_algorithm"] != FEASIBLE_RANDOM_PRICE_ID:
            raise ValueError("episode artifact null algorithm is unsupported")
        if manifest["issuance_rule_id"] != ISSUANCE_RULE_ID:
            raise ValueError("episode artifact issuance rule is unsupported")
        if manifest["issuance_digest_algorithm"] != ISSUANCE_SEQUENCE_HASH_ALGORITHM:
            raise ValueError("artifact issuance digest algorithm is unsupported")
        if manifest["baseline_config_fingerprint"] != manifest["config_fingerprint"]:
            raise ValueError("artifact baseline and receipt config fingerprints differ")
        for name in (
            "asset",
            "venue",
            "instrument_id",
            "source_manifest_id",
            "code_policy_id",
            "null_seed",
            "config_fingerprint",
        ):
            if not isinstance(manifest[name], str) or not manifest[name].strip():
                raise ValueError(f"artifact {name} must be non-empty")
        require_utc(manifest["analysis_start"], field_name="artifact analysis_start")
        require_utc(
            manifest["knowledge_cutoff"], field_name="artifact knowledge_cutoff"
        )
        if manifest["knowledge_cutoff"] < manifest["analysis_start"]:
            raise ValueError("artifact knowledge cutoff precedes analysis start")
        expected_groups = tuple(
            _group_from_manifest_value(item) for item in manifest["expected_groups"]
        )
        present_groups = tuple(
            _group_from_manifest_value(item) for item in manifest["present_groups"]
        )
        if len(set(expected_groups)) != len(expected_groups) or len(
            set(present_groups)
        ) != len(present_groups):
            raise ValueError("artifact groups must be unique")
        if any(
            group.asset != manifest["asset"]
            for group in expected_groups + present_groups
        ):
            raise ValueError("artifact group asset differs from artifact asset")
        if not set(present_groups) <= set(expected_groups):
            raise ValueError("artifact present groups must be expected groups")
        bounds = tuple(manifest["full_bounds"])
        if not bounds or any(
            not isinstance(item, tuple) or len(item) != 3 for item in bounds
        ):
            raise ValueError("artifact full bounds are malformed")
        bound_timeframes = tuple(item[0] for item in bounds)
        if len(set(bound_timeframes)) != len(bound_timeframes):
            raise ValueError("artifact full bounds contain duplicate timeframes")
        for timeframe, start, end in bounds:
            if not isinstance(timeframe, str) or not timeframe.strip() or end <= start:
                raise ValueError("artifact full bounds are malformed")
            require_utc(start, field_name=f"artifact {timeframe} start")
            require_utc(end, field_name=f"artifact {timeframe} end")
        expected_timeframes = {group.timeframe for group in expected_groups}
        present_timeframes = {group.timeframe for group in present_groups}
        # The trigger lane is authenticated separately from target groups.  The
        # expected target ontology therefore covers every non-trigger lane,
        # while the trigger lane completes the exact source/bounds timeframe
        # set.  Present groups remain a subset of that expected ontology.
        if (expected_timeframes | {manifest["trigger_timeframe"]}) != set(
            bound_timeframes
        ) or not present_timeframes <= expected_timeframes:
            raise ValueError("artifact group and source timeframe sets differ")
        counts = tuple(manifest["source_record_counts"])
        identities = tuple(manifest["source_record_identity_hashes"])
        count_timeframes = tuple(item[0] for item in counts)
        identity_timeframes = tuple(item[0] for item in identities)
        if (
            not counts
            or len(set(count_timeframes)) != len(count_timeframes)
            or len(set(identity_timeframes)) != len(identity_timeframes)
            or set(count_timeframes) != set(identity_timeframes)
            or set(count_timeframes) != set(bound_timeframes)
        ):
            raise ValueError("artifact source record metadata is malformed")
        for timeframe, count in counts:
            if (
                not isinstance(timeframe, str)
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count <= 0
            ):
                raise ValueError("artifact source record counts are malformed")
        for timeframe, digest in identities:
            _strict_sha256(digest, f"artifact {timeframe} source identity hash")
        acquisition = tuple(manifest["acquisition_evidence"])
        if not acquisition or any(
            not isinstance(item, tuple) or len(item) != 4 for item in acquisition
        ):
            raise ValueError("artifact acquisition evidence is malformed")
        acquisition_timeframes = tuple(item[0] for item in acquisition)
        if len(set(acquisition_timeframes)) != len(acquisition_timeframes) or set(
            acquisition_timeframes
        ) != set(bound_timeframes):
            raise ValueError(
                "artifact acquisition evidence contains duplicate timeframes"
            )
        for timeframe, mode, cutoff, digest in acquisition:
            if not isinstance(timeframe, str) or not isinstance(mode, str):
                raise TypeError("artifact acquisition evidence is malformed")
            require_utc(cutoff, field_name=f"artifact {timeframe} acquisition cutoff")
            _strict_sha256(digest, f"artifact {timeframe} acquisition evidence")
        for name in (
            "episode_bytes",
            "episode_count",
            "issuance_count",
            "cluster_count",
            "state_generation",
            "serialized_state_bytes",
            "steps",
            "candidates",
            "transitions",
            "created_transitions",
            "tombstone_pruned_transitions",
            "peak_active_lineages",
            "peak_terminal_tombstones",
        ):
            value = manifest[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"artifact {name} must be non-negative")
        if manifest["issuance_count"] != manifest["episode_count"]:
            raise ValueError("artifact issuance and episode counts differ")
        if (
            not isinstance(manifest["trigger_timeframe"], str)
            or not manifest["trigger_timeframe"].strip()
            or manifest["trigger_timeframe"] not in set(count_timeframes)
        ):
            raise ValueError("artifact trigger timeframe is not in source records")
        group_counts = tuple(manifest["group_counts"])
        if any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or isinstance(item[1], bool)
            or not isinstance(item[1], int)
            or item[1] <= 0
            for item in group_counts
        ):
            raise ValueError("artifact group counts are malformed")
        if len({item[0] for item in group_counts}) != len(group_counts):
            raise ValueError("artifact group counts contain duplicate keys")
        expected_group_keys = {group.key for group in expected_groups}
        present_group_keys = {group.key for group in present_groups}
        count_group_keys = {item[0] for item in group_counts}
        if (
            not count_group_keys <= expected_group_keys
            or count_group_keys != present_group_keys
        ):
            raise ValueError("artifact group counts and present groups differ")
        manifest["group_counts"] = tuple(sorted(group_counts))
        if (
            _structural_receipt_hash_from_manifest(manifest)
            != manifest["structural_receipt_hash"]
        ):
            raise ValueError("artifact structural receipt hash mismatch")
        return MappingProxyType(manifest)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("episode artifact manifest is invalid") from exc


def _validate_compact_row(
    value: Any,
    *,
    manifest: Mapping[str, Any],
    previous: tuple[datetime, str] | None,
    current_ids: set[str],
) -> tuple[CompactEpisodeRecord, tuple[datetime, str], set[str]]:
    row = _compact_episode_from_mapping(value, manifest)
    expected_groups = tuple(
        _group_from_manifest_value(item) for item in manifest["expected_groups"]
    )
    if row.group not in expected_groups:
        raise ValueError("compact episode contains an unexpected group")
    if (
        row.zone.source_timeframe != row.group.timeframe
        or row.zone.kernel_id != row.group.kernel_id
        or row.zone.kernel_version != row.group.kernel_version
        or row.zone.side is not row.group.side
    ):
        raise ValueError("compact episode group and lineage ontology differ")
    if not (
        manifest["analysis_start"]
        <= row.issuance_cutoff
        <= manifest["knowledge_cutoff"]
    ):
        raise ValueError("compact episode issuance cutoff is outside artifact bounds")
    source_counts = dict(manifest["source_record_counts"])
    source_count = source_counts.get(row.zone.source_timeframe)
    if source_count is None or row.source_close_index >= source_count:
        raise ValueError("compact episode source close index is outside source records")
    trigger_count = source_counts[manifest["trigger_timeframe"]]
    trigger_index = row.first_subsequent_trigger_index
    trigger_identity = row.first_subsequent_trigger_identity
    if trigger_index is None:
        if trigger_identity is not None:
            raise ValueError("compact episode trigger index/identity are inconsistent")
    elif (
        isinstance(trigger_index, bool)
        or not isinstance(trigger_index, int)
        or trigger_index < 0
        or trigger_index >= trigger_count
        or not isinstance(trigger_identity, str)
        or not trigger_identity.strip()
    ):
        raise ValueError("compact episode trigger index/identity are invalid")
    if _cluster_identity_for_row(row) != row.cluster_identity:
        raise ValueError("compact episode cluster identity is inconsistent")
    key = (row.issuance_cutoff, row.observation_id)
    if previous is not None and key <= previous:
        raise ValueError("compact episode rows are not in canonical order")
    if previous is None or row.issuance_cutoff != previous[0]:
        current_ids = set()
    null_zone_id = (
        row.feasible_null.zone.zone_id
        if row.feasible_null.complete and row.feasible_null.zone is not None
        else None
    )
    row_zone_ids = {row.observation_id}
    if null_zone_id is not None:
        row_zone_ids.add(null_zone_id)
    if len(row_zone_ids) != (2 if null_zone_id is not None else 1):
        raise ValueError("compact actual and null zone identities collide")
    if row_zone_ids & current_ids:
        raise ValueError("duplicate compact episode identity within issuance cutoff")
    current_ids.update(row_zone_ids)
    return row, key, current_ids


def _iter_validated_artifact_rows(
    artifact: EpisodeArtifact,
) -> Iterator[CompactEpisodeRecord]:
    """Yield rows while deferring final file receipt checks until exhaustion."""

    directory = artifact.directory
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("episode artifact directory must be regular")
    episodes_path = directory / "episodes.jsonl"
    if episodes_path.is_symlink() or not episodes_path.is_file():
        raise ValueError("episode artifact episodes file is partial or symlinked")
    manifest = artifact.manifest
    file_digest = hashlib.sha256()
    issuance_digest = hashlib.sha256()
    total_bytes = 0
    count = 0
    previous: tuple[datetime, str] | None = None
    current_ids: set[str] = set()
    group_counts: Counter[str] = Counter()
    cluster_digest = hashlib.sha256()
    cluster_count = 0
    current_cutoff: datetime | None = None
    current_clusters: Counter[str] = Counter()

    def flush_clusters() -> None:
        nonlocal current_cutoff, current_clusters, cluster_count
        if current_cutoff is None:
            return
        payload = (current_cutoff, tuple(sorted(current_clusters.items())))
        encoded = canonical_json(payload).encode("utf-8")
        cluster_digest.update(len(encoded).to_bytes(8, "big"))
        cluster_digest.update(encoded)
        cluster_count += len(current_clusters)
        current_cutoff = None
        current_clusters = Counter()

    with episodes_path.open("rb") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith(b"\n") or line == b"\n":
                raise ValueError(
                    f"compact episode JSONL is malformed at line {line_number}"
                )
            try:
                decoded = _decode_artifact_value(
                    json.loads(
                        line.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
                    )
                )
                if canonical_json(decoded).encode("utf-8") + b"\n" != line:
                    raise ValueError("compact episode row is not canonical")
                row, previous, current_ids = _validate_compact_row(
                    decoded,
                    manifest=manifest,
                    previous=previous,
                    current_ids=current_ids,
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exc:
                raise ValueError(
                    f"compact episode JSONL is malformed at line {line_number}: {exc}"
                ) from exc
            file_digest.update(line)
            encoded_id = canonical_json(row.observation_id).encode("utf-8")
            issuance_digest.update(len(encoded_id).to_bytes(8, "big"))
            issuance_digest.update(encoded_id)
            total_bytes += len(line)
            count += 1
            group_counts[row.group.key] += 1
            if current_cutoff is not None and row.issuance_cutoff != current_cutoff:
                flush_clusters()
            current_cutoff = row.issuance_cutoff
            current_clusters[row.cluster_identity] += 1
            yield row
    flush_clusters()
    if file_digest.hexdigest() != manifest["episode_sha256"]:
        raise ValueError("episode artifact episode SHA-256 mismatch")
    if total_bytes != manifest["episode_bytes"] or count != manifest["episode_count"]:
        raise ValueError("episode artifact episode count/bytes mismatch")
    if (
        count != manifest["issuance_count"]
        or issuance_digest.hexdigest() != manifest["issuance_sha256"]
    ):
        raise ValueError("episode artifact issuance digest mismatch")
    if tuple(sorted(group_counts.items())) != tuple(manifest["group_counts"]):
        raise ValueError("episode artifact group counts mismatch")
    if cluster_count != manifest["cluster_count"]:
        raise ValueError("episode artifact cluster count mismatch")
    if cluster_digest.hexdigest() != manifest["cluster_multiplicity_sha256"]:
        raise ValueError("episode artifact cluster multiplicity digest mismatch")


def _load_artifact_manifest_handle(path: str | Path) -> EpisodeArtifact:
    """Load and authenticate only an artifact manifest for a bounded rescan."""

    directory = Path(path)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("episode artifact directory must be a regular directory")
    manifest_path = directory / "manifest.json"
    episodes_path = directory / "episodes.jsonl"
    if any(
        item.is_symlink() or not item.is_file()
        for item in (manifest_path, episodes_path)
    ):
        raise ValueError("episode artifact is partial or symlinked")
    manifest = _validate_artifact_manifest(manifest_path.read_bytes(), directory)
    return EpisodeArtifact(
        artifact_id=str(manifest["artifact_id"]),
        directory=directory,
        manifest=manifest,
    )


def load_episode_artifact(path: str | Path) -> EpisodeArtifact:
    """Authenticate a compact artifact without retaining any episode rows."""

    artifact = _load_artifact_manifest_handle(path)
    try:
        for _ in _iter_validated_artifact_rows(artifact):
            pass
    except (OSError, ValueError) as exc:
        raise ValueError(f"episode artifact episodes JSONL is invalid: {exc}") from exc
    return artifact


def iter_episode_records(
    artifact: EpisodeArtifact | str | Path,
) -> Iterator[CompactEpisodeRecord]:
    """Lazily authenticate and yield compact rows in canonical order."""

    if isinstance(artifact, (str, Path)):
        # Authenticate the manifest now, and let this generator own the
        # single JSONL scan.  Final receipt checks intentionally run only once
        # the caller exhausts the stream.
        handle = _load_artifact_manifest_handle(artifact)
    elif isinstance(artifact, EpisodeArtifact):
        # A handle carries location and convenience metadata only; the disk
        # manifest/file remain the authentication authority on every pass.
        handle = _load_artifact_manifest_handle(artifact.directory)
        if artifact.artifact_id != handle.artifact_id or canonical_json(
            artifact.manifest
        ) != canonical_json(handle.manifest):
            raise ValueError("episode artifact handle is stale or forged")
    else:
        raise TypeError("iter_episode_records requires an EpisodeArtifact or path")
    yield from _iter_validated_artifact_rows(handle)


def _write_compact_rows(
    path: Path,
    episodes: Iterator[EpisodeIssuance],
) -> tuple[str, int, int, tuple[tuple[str, int], ...], int, str]:
    """Write compact rows and retain only current-cutoff cluster state."""

    file_digest = hashlib.sha256()
    total_bytes = 0
    count = 0
    group_counts: Counter[str] = Counter()
    cluster_digest = hashlib.sha256()
    cluster_count = 0
    current_cutoff: datetime | None = None
    current_clusters: Counter[str] = Counter()
    previous: tuple[datetime, str] | None = None
    current_ids: set[str] = set()

    def flush_clusters() -> None:
        nonlocal current_cutoff, current_clusters, cluster_count
        if current_cutoff is None:
            return
        payload = (current_cutoff, tuple(sorted(current_clusters.items())))
        encoded = canonical_json(payload).encode("utf-8")
        cluster_digest.update(len(encoded).to_bytes(8, "big"))
        cluster_digest.update(encoded)
        cluster_count += len(current_clusters)
        current_cutoff = None
        current_clusters = Counter()

    with path.open("wb") as handle:
        for episode in episodes:
            row = CompactEpisodeRecord.from_episode(episode)
            if previous is not None and row.issuance_cutoff < previous[0]:
                raise ValueError("episode rows must be ordered by issuance cutoff")
            if previous is None or row.issuance_cutoff != previous[0]:
                current_ids = set()
            row_zone_ids = {row.observation_id}
            if row.feasible_null.complete and row.feasible_null.zone is not None:
                row_zone_ids.add(row.feasible_null.zone.zone_id)
            if len(row_zone_ids) != (
                2
                if row.feasible_null.complete and row.feasible_null.zone is not None
                else 1
            ):
                raise ValueError("actual and null zone identities collide")
            if row_zone_ids & current_ids:
                raise ValueError("duplicate episode identity within issuance cutoff")
            current_ids.update(row_zone_ids)
            previous = (row.issuance_cutoff, row.observation_id)
            encoded = (canonical_json(row.to_mapping()) + "\n").encode("utf-8")
            handle.write(encoded)
            file_digest.update(encoded)
            total_bytes += len(encoded)
            count += 1
            group_counts[row.group.key] += 1
            if current_cutoff is not None and row.issuance_cutoff != current_cutoff:
                flush_clusters()
            current_cutoff = row.issuance_cutoff
            current_clusters[row.cluster_identity] += 1
        flush_clusters()
        handle.flush()
        os.fsync(handle.fileno())
    return (
        file_digest.hexdigest(),
        total_bytes,
        count,
        tuple(sorted(group_counts.items())),
        cluster_count,
        cluster_digest.hexdigest(),
    )


class EpisodeArtifactWriter:
    """Sequential authenticated writer for compact episode artifact @2."""

    def __init__(
        self,
        *,
        source_slice: AuthenticatedSourceSlice,
        config: ResolvedSRV2Config,
        analysis_start: datetime,
        knowledge_cutoff: datetime,
        null_seed: str,
        artifact_root: str | Path,
        baseline_yaml_sha256: str,
        code_policy_id: str,
        baseline_config_fingerprint: str | None = None,
    ) -> None:
        if not isinstance(source_slice, AuthenticatedSourceSlice):
            raise TypeError("episode artifact writer requires AuthenticatedSourceSlice")
        if not isinstance(config, ResolvedSRV2Config):
            raise TypeError("episode artifact writer requires ResolvedSRV2Config")
        require_utc(analysis_start, field_name="analysis_start")
        require_utc(knowledge_cutoff, field_name="knowledge_cutoff")
        if knowledge_cutoff < analysis_start:
            raise ValueError("knowledge_cutoff must follow analysis_start")
        if not isinstance(null_seed, str) or not null_seed.strip():
            raise ValueError("null_seed must be non-empty")
        if not isinstance(code_policy_id, str) or not code_policy_id.strip():
            raise ValueError("code_policy_id must be non-empty")
        _strict_sha256(source_slice.source_sha256, "source_slice source_sha256")
        _strict_sha256(source_slice.slice_fingerprint, "source_slice fingerprint")
        if not source_slice.acquisition_evidence:
            raise ValueError("episode artifact requires acquisition evidence")
        self.source_slice = source_slice
        self.config = config
        self.analysis_start = analysis_start
        self.knowledge_cutoff = knowledge_cutoff
        self.null_seed = null_seed
        self.baseline_yaml_sha256 = _strict_sha256(
            baseline_yaml_sha256, "baseline_yaml_sha256"
        )
        self.code_policy_id = code_policy_id
        self.baseline_config_fingerprint = (
            config.config_fingerprint
            if baseline_config_fingerprint is None
            else baseline_config_fingerprint
        )
        self.baseline_config_fingerprint = _strict_sha256(
            self.baseline_config_fingerprint, "baseline_config_fingerprint"
        )
        if self.baseline_config_fingerprint != config.config_fingerprint:
            raise ValueError(
                "baseline_config_fingerprint must match resolved config fingerprint"
            )
        self.artifact_root = Path(artifact_root)
        if self.artifact_root.exists() and self.artifact_root.is_symlink():
            raise ValueError("episode artifact root must not be a symlink")
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.asset_root = self.artifact_root / source_slice.asset
        if self.asset_root.exists() and self.asset_root.is_symlink():
            raise ValueError("episode artifact asset directory must not be a symlink")
        self.asset_root.mkdir(exist_ok=True)
        self.temporary = Path(
            tempfile.mkdtemp(prefix=".episode-v2-", dir=self.asset_root)
        )
        self.episodes_path = self.temporary / "episodes.jsonl"
        self._episodes_handle = self.episodes_path.open("wb")
        try:
            self._collector = EpisodeEvidenceCollector.from_authenticated_slice(
                source_slice,
                config=config,
                analysis_start=analysis_start,
                knowledge_cutoff=knowledge_cutoff,
                null_seed=null_seed,
                episode_callback=self._accept_episode,
                retain_episodes=False,
            )
        except Exception:
            self._episodes_handle.close()
            _remove_temp_directory(self.temporary)
            raise
        self._current_cutoff: datetime | None = None
        self._current_rows: list[EpisodeIssuance] = []
        self._current_ids: set[str] = set()
        self._previous_cutoff: datetime | None = None
        self._file_digest = hashlib.sha256()
        self._issuance_digest = hashlib.sha256()
        self._episode_bytes = 0
        self._episode_count = 0
        self._group_counts: Counter[str] = Counter()
        self._cluster_digest = hashlib.sha256()
        self._cluster_count = 0
        self._finished = False

    def _abort(self) -> None:
        if not self._episodes_handle.closed:
            self._episodes_handle.close()
        if self.temporary.exists():
            _remove_temp_directory(self.temporary)

    def _accept_episode(self, episode: EpisodeIssuance) -> None:
        if self._finished:
            raise RuntimeError("episode artifact writer is already finished")
        if self._current_cutoff is None:
            raise ValueError("episode callback arrived before a structural step cutoff")
        if episode.issuance_cutoff != self._current_cutoff:
            raise ValueError(
                "episode issuance cutoff differs from structural step cutoff"
            )
        if episode.zone.config_fingerprint != self.baseline_config_fingerprint:
            raise ValueError("episode lineage config differs from artifact baseline")
        row_zone_ids = {episode.observation_id}
        if episode.feasible_null.complete and episode.feasible_null.zone is not None:
            row_zone_ids.add(episode.feasible_null.zone.zone_id)
        if len(row_zone_ids) != (
            2
            if episode.feasible_null.complete and episode.feasible_null.zone is not None
            else 1
        ):
            raise ValueError("actual and null zone identities collide")
        if row_zone_ids & self._current_ids:
            raise ValueError(
                "duplicate observation/zone identity within issuance cutoff"
            )
        self._current_ids.update(row_zone_ids)
        self._current_rows.append(episode)

    def _flush_cutoff(self) -> None:
        if self._current_cutoff is None:
            return
        rows = tuple(sorted(self._current_rows, key=lambda item: item.observation_id))
        if not rows:
            self._current_rows.clear()
            self._current_ids.clear()
            self._current_cutoff = None
            return
        current_clusters: Counter[str] = Counter()
        for episode in rows:
            compact = CompactEpisodeRecord.from_episode(episode)
            encoded = (canonical_json(compact.to_mapping()) + "\n").encode("utf-8")
            self._episodes_handle.write(encoded)
            self._file_digest.update(encoded)
            _sequence_digest_update(self._issuance_digest, compact.observation_id)
            self._episode_bytes += len(encoded)
            self._episode_count += 1
            self._group_counts[compact.group.key] += 1
            current_clusters[compact.cluster_identity] += 1
        payload = (self._current_cutoff, tuple(sorted(current_clusters.items())))
        encoded_cluster = canonical_json(payload).encode("utf-8")
        self._cluster_digest.update(len(encoded_cluster).to_bytes(8, "big"))
        self._cluster_digest.update(encoded_cluster)
        self._cluster_count += len(current_clusters)
        self._current_rows.clear()
        self._current_ids.clear()
        self._current_cutoff = None

    def on_step(self, result: SRStepResult) -> None:
        try:
            if self._finished:
                raise RuntimeError("episode artifact writer is already finished")
            if not isinstance(result, SRStepResult):
                raise TypeError("episode artifact callback requires SRStepResult")
            if (
                self._previous_cutoff is not None
                and result.market_as_of <= self._previous_cutoff
            ):
                raise ValueError(
                    "episode artifact structural steps are not strictly ordered"
                )
            if (
                self._current_cutoff is not None
                and result.market_as_of != self._current_cutoff
            ):
                self._flush_cutoff()
            self._current_cutoff = result.market_as_of
            self._previous_cutoff = result.market_as_of
            self._collector.on_step(result)
        except Exception:
            self._abort()
            raise

    def finish(self, run_state: SRState) -> EpisodeArtifact:
        try:
            if self._finished:
                raise RuntimeError("episode artifact writer is already finished")
            if not isinstance(run_state, SRState):
                raise TypeError("episode artifact writer finish requires SRState")
            self._flush_cutoff()
            self._episodes_handle.flush()
            os.fsync(self._episodes_handle.fileno())
            self._episodes_handle.close()
            self._finished = True
            evidence = self._collector.finish(run_state)
            if (
                self._episode_count != evidence.receipt.issuance_count
                or self._issuance_digest.hexdigest() != evidence.receipt.issuance_sha256
            ):
                raise ValueError("artifact rows differ from collector issuance receipt")
            manifest = _artifact_manifest_v2(
                receipt=evidence.receipt,
                source_records_by_timeframe=self.source_slice.records_by_timeframe,
                acquisition_evidence=self.source_slice.acquisition_evidence,
                full_bounds=self.source_slice.bounds,
                trigger_timeframe=self.config.trigger_timeframe,
                baseline_config_fingerprint=self.baseline_config_fingerprint,
                baseline_yaml_sha256=self.baseline_yaml_sha256,
                code_policy_id=self.code_policy_id,
                null_seed=self.null_seed,
                episode_sha256=self._file_digest.hexdigest(),
                episode_bytes=self._episode_bytes,
                episode_count=self._episode_count,
                group_counts=tuple(self._group_counts.items()),
                cluster_count=self._cluster_count,
                cluster_multiplicity_sha256=self._cluster_digest.hexdigest(),
            )
            return _finish_artifact_directory(
                temporary=self.temporary,
                artifact_root=self.artifact_root,
                asset=self.source_slice.asset,
                manifest=manifest,
                episodes_path=self.episodes_path,
            )
        except Exception:
            self._abort()
            raise


def run_streaming_episode_artifact(
    *,
    config: ResolvedSRV2Config,
    source_slice: AuthenticatedSourceSlice,
    analysis_start: datetime,
    knowledge_cutoff: datetime,
    null_seed: str,
    artifact_root: str | Path,
    baseline_yaml_sha256: str,
    code_policy_id: str,
    baseline_config_fingerprint: str | None = None,
) -> EpisodeArtifact:
    """Replay an authenticated source slice directly into compact artifact @2."""

    writer = EpisodeArtifactWriter(
        source_slice=source_slice,
        config=config,
        analysis_start=analysis_start,
        knowledge_cutoff=knowledge_cutoff,
        null_seed=null_seed,
        artifact_root=artifact_root,
        baseline_yaml_sha256=baseline_yaml_sha256,
        code_policy_id=code_policy_id,
        baseline_config_fingerprint=baseline_config_fingerprint,
    )
    try:
        compute = OfflineCompute(
            config,
            venue=source_slice.venue,
            instrument_id=source_slice.instrument_id,
            asset=source_slice.asset,
        )
        result = compute.run(
            source_slice.bars_by_timeframe,
            cutoff=knowledge_cutoff,
            start_cutoff=analysis_start - config.expiry,
            on_step=writer.on_step,
        )
        return writer.finish(result.state)
    except Exception:
        writer._abort()
        raise


def write_episode_artifact(
    evidence: StreamingEvidenceResult,
    *,
    artifact_root: str | Path,
    baseline_config_fingerprint: str,
    baseline_yaml_sha256: str,
    code_policy_id: str,
    null_seed: str,
) -> EpisodeArtifact:
    """Bounded fixture adapter writing a compact @2 artifact."""

    if not isinstance(evidence, StreamingEvidenceResult):
        raise TypeError("evidence must be StreamingEvidenceResult")
    if evidence.receipt.source_slice_fingerprint is None:
        raise ValueError("episode artifacts require an authenticated source slice")
    _strict_sha256(
        evidence.receipt.source_slice_fingerprint, "source_slice_fingerprint"
    )
    if not evidence.acquisition_evidence:
        raise ValueError("episode artifacts require acquisition evidence")
    if any(
        not isinstance(item, SourceBarRecord)
        for records in evidence.source_records_by_timeframe.values()
        for item in records
    ):
        raise ValueError("episode artifacts require authenticated source records")
    expected_slice = _authenticated_slice_fingerprint(
        source_manifest_id=evidence.receipt.source_manifest_id,
        source_sha256=evidence.receipt.source_sha256,
        venue=evidence.receipt.venue,
        instrument_id=evidence.receipt.instrument_id,
        asset=evidence.receipt.asset,
        bounds=evidence.full_bounds,
        records_by_timeframe=evidence.source_records_by_timeframe,
        acquisition_evidence=evidence.acquisition_evidence,
    )
    if evidence.receipt.source_slice_fingerprint != expected_slice:
        raise ValueError(
            "episode artifact source slice fingerprint is not bound to records"
        )
    if baseline_config_fingerprint != evidence.receipt.config_fingerprint:
        raise ValueError(
            "baseline_config_fingerprint must match structural receipt config"
        )
    baseline_yaml_sha256 = _strict_sha256(baseline_yaml_sha256, "baseline_yaml_sha256")
    for name, value in (
        ("baseline_config_fingerprint", baseline_config_fingerprint),
        ("code_policy_id", code_policy_id),
        ("null_seed", null_seed),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty")
    if any(
        episode.zone.config_fingerprint != baseline_config_fingerprint
        for episode in evidence.episodes
    ):
        raise ValueError("episode lineage config differs from artifact baseline")
    trigger_timeframes = {
        identity.split(":", 1)[0]
        for episode in evidence.episodes
        if (identity := episode.first_subsequent_trigger_identity) is not None
    }
    if len(trigger_timeframes) != 1:
        raise ValueError("fixture artifact requires one identifiable trigger timeframe")
    trigger_timeframe = next(iter(trigger_timeframes))
    root = Path(artifact_root)
    if root.exists() and root.is_symlink():
        raise ValueError("episode artifact root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    asset_root = root / evidence.receipt.asset
    if asset_root.exists() and asset_root.is_symlink():
        raise ValueError("episode artifact asset directory must not be a symlink")
    asset_root.mkdir(exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".episode-v2-", dir=asset_root))
    episodes_path = temporary / "episodes.jsonl"
    try:
        ordered_episodes = tuple(
            sorted(
                evidence.episodes,
                key=lambda item: (item.issuance_cutoff, item.observation_id),
            )
        )
        if (
            len(ordered_episodes) != evidence.receipt.issuance_count
            or _sequence_digest(iter(item.observation_id for item in ordered_episodes))
            != evidence.receipt.issuance_sha256
        ):
            raise ValueError("episode issuance digest differs from structural receipt")
        result = _write_compact_rows(episodes_path, iter(ordered_episodes))
        manifest = _artifact_manifest_v2(
            receipt=evidence.receipt,
            source_records_by_timeframe=evidence.source_records_by_timeframe,
            acquisition_evidence=evidence.acquisition_evidence,
            full_bounds=evidence.full_bounds,
            trigger_timeframe=trigger_timeframe,
            baseline_config_fingerprint=baseline_config_fingerprint,
            baseline_yaml_sha256=baseline_yaml_sha256,
            code_policy_id=code_policy_id,
            null_seed=null_seed,
            episode_sha256=result[0],
            episode_bytes=result[1],
            episode_count=result[2],
            group_counts=result[3],
            cluster_count=result[4],
            cluster_multiplicity_sha256=result[5],
        )
        return _finish_artifact_directory(
            temporary=temporary,
            artifact_root=root,
            asset=evidence.receipt.asset,
            manifest=manifest,
            episodes_path=episodes_path,
        )
    except Exception:
        if temporary.exists():
            _remove_temp_directory(temporary)
        raise


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetOutcome:
    """The exact two-stage outcome projection used by target rows."""

    complete: bool
    touch: bool | None
    reaction: ScientificReaction | None
    reaction_eligible: bool
    censored: bool
    ambiguous: bool
    touch_at: datetime | None
    reaction_at: datetime | None
    observation_end_at: datetime
    last_observed_cutoff: datetime | None
    outcome: ForecastOutcome
    favorable_excursion_atr: Decimal
    adverse_excursion_atr: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.complete, bool):
            raise TypeError("target outcome complete must be bool")
        if self.touch not in (True, False, None):
            raise TypeError("target outcome touch must be bool or None")
        if self.reaction is not None and not isinstance(
            self.reaction, ScientificReaction
        ):
            raise TypeError(
                "target outcome reaction must be ScientificReaction or None"
            )
        for name in ("reaction_eligible", "censored", "ambiguous"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"target outcome {name} must be bool")
        for name in ("observation_end_at",):
            require_utc(getattr(self, name), field_name=f"target outcome {name}")
        for name in ("touch_at", "reaction_at", "last_observed_cutoff"):
            value = getattr(self, name)
            if value is not None:
                require_utc(value, field_name=f"target outcome {name}")
        if self.last_observed_cutoff is not None and (
            self.last_observed_cutoff > self.observation_end_at
        ):
            raise ValueError("target outcome last cutoff exceeds observation end")
        if not isinstance(self.outcome, ForecastOutcome):
            raise TypeError("target outcome outcome must be ForecastOutcome")
        for name in ("favorable_excursion_atr", "adverse_excursion_atr"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"target outcome {name} must be non-negative Decimal")

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "complete": self.complete,
            "touch": self.touch,
            "reaction": None if self.reaction is None else self.reaction.value,
            "reaction_eligible": self.reaction_eligible,
            "censored": self.censored,
            "ambiguous": self.ambiguous,
            "touch_at": self.touch_at,
            "reaction_at": self.reaction_at,
            "observation_end_at": self.observation_end_at,
            "last_observed_cutoff": self.last_observed_cutoff,
            "outcome": self.outcome.value,
            "favorable_excursion_atr": self.favorable_excursion_atr,
            "adverse_excursion_atr": self.adverse_excursion_atr,
        }


def _target_outcome_from_result(result: Any) -> TargetOutcome:
    if not hasattr(result, "view") or not hasattr(result, "event_observation"):
        raise TypeError("target result is not a ScientificTargetResult")
    event = result.event_observation
    view = result.view
    return TargetOutcome(
        complete=result.complete,
        touch=view.touch,
        reaction=view.reaction,
        reaction_eligible=view.reaction_eligible,
        censored=view.censored,
        ambiguous=view.ambiguous,
        touch_at=view.touch_at,
        reaction_at=view.reaction_at,
        observation_end_at=result.observation_end_at,
        last_observed_cutoff=result.last_observed_cutoff,
        outcome=event.outcome,
        favorable_excursion_atr=event.favorable_excursion_atr,
        adverse_excursion_atr=event.adverse_excursion_atr,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetOutcomeRow:
    """One lazy authenticated actual/null outcome row."""

    observation_id: str
    group: ScientificGroupKey
    issuance_cutoff: datetime
    cluster_identity: str
    target_fingerprint: str
    null_fingerprint: str
    null_available: bool
    actual: TargetOutcome
    null: TargetOutcome | None

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, str) or not self.observation_id.strip():
            raise ValueError("target outcome observation_id must be non-empty")
        if not isinstance(self.group, ScientificGroupKey):
            raise TypeError("target outcome group must be ScientificGroupKey")
        require_utc(self.issuance_cutoff, field_name="target outcome issuance_cutoff")
        _strict_sha256(self.cluster_identity, "target outcome cluster_identity")
        _strict_sha256(self.target_fingerprint, "target outcome target_fingerprint")
        _strict_sha256(self.null_fingerprint, "target outcome null_fingerprint")
        if not isinstance(self.null_available, bool):
            raise TypeError("target outcome null_available must be bool")
        if not isinstance(self.actual, TargetOutcome):
            raise TypeError("target outcome actual must be TargetOutcome")
        if not isinstance(self.null_available, bool) or self.null_available != (
            self.null is not None
        ):
            raise ValueError("target outcome null availability does not match null row")
        if self.null is not None and not isinstance(self.null, TargetOutcome):
            raise TypeError("target outcome null must be TargetOutcome or None")

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self.to_mapping())

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "schema": TARGET_OUTCOME_ROW_SCHEMA,
            "observation_id": self.observation_id,
            "group": self.group,
            "issuance_cutoff": self.issuance_cutoff,
            "cluster_identity": self.cluster_identity,
            "target_fingerprint": self.target_fingerprint,
            "null_fingerprint": self.null_fingerprint,
            "null_available": self.null_available,
            "actual": self.actual.to_mapping(),
            "null": None if self.null is None else self.null.to_mapping(),
        }


def _digest_empty() -> str:
    return _sequence_digest(iter(()))


@dataclass(frozen=True, slots=True, kw_only=True)
class CommonRiskReceipt:
    """Digest-only common-risk decisions shared by every target choice."""

    schema: str
    artifact_id: str
    source_manifest_id: str
    source_sha256: str
    source_slice_fingerprint: str
    asset: str
    target_family_fingerprint: str
    materialization_policy_id: str
    sequence_hash_algorithm: str
    included_count: int
    included_observation_sha256: str
    excluded_count: int
    excluded_observation_sha256: str
    excluded_reason_sha256: str
    excluded_reason_counts: tuple[tuple[str, int], ...]
    included_group_sha256: str
    expected_group_counts: tuple[tuple[str, int], ...]
    receipt_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema != COMMON_RISK_RECEIPT_SCHEMA:
            raise ValueError("unsupported common-risk receipt schema")
        for name in (
            "artifact_id",
            "source_manifest_id",
            "source_sha256",
            "source_slice_fingerprint",
            "asset",
            "target_family_fingerprint",
            "materialization_policy_id",
            "sequence_hash_algorithm",
            "included_observation_sha256",
            "excluded_observation_sha256",
            "excluded_reason_sha256",
            "included_group_sha256",
            "receipt_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"common-risk {name} must be non-empty")
        if self.materialization_policy_id != TARGET_MATERIALIZATION_POLICY_ID:
            raise ValueError("common-risk materialization policy is unsupported")
        for name in (
            "source_sha256",
            "source_slice_fingerprint",
            "target_family_fingerprint",
            "included_observation_sha256",
            "excluded_observation_sha256",
            "excluded_reason_sha256",
            "included_group_sha256",
            "receipt_fingerprint",
        ):
            _strict_sha256(getattr(self, name), f"common-risk {name}")
        if self.sequence_hash_algorithm != ISSUANCE_SEQUENCE_HASH_ALGORITHM:
            raise ValueError("unsupported common-risk sequence hash algorithm")
        for name in ("included_count", "excluded_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"common-risk {name} must be non-negative")
        reason_counts = tuple(sorted(self.excluded_reason_counts))
        if any(
            not isinstance(item, tuple)
            or len(item) != 2
            or item[0] not in {"insufficient_source_history", "right_edge_horizon"}
            or isinstance(item[1], bool)
            or not isinstance(item[1], int)
            or item[1] <= 0
            for item in reason_counts
        ):
            raise ValueError("common-risk reason counts are malformed")
        group_counts = tuple(sorted(self.expected_group_counts))
        if any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0].strip()
            or isinstance(item[1], bool)
            or not isinstance(item[1], int)
            or item[1] < 0
            for item in group_counts
        ) or len({item[0] for item in group_counts}) != len(group_counts):
            raise ValueError("common-risk group counts are malformed")
        if sum(value for _, value in reason_counts) != self.excluded_count:
            raise ValueError("common-risk reason counts do not match exclusions")
        if sum(value for _, value in group_counts) != self.included_count:
            raise ValueError("common-risk group counts do not match inclusions")
        expected = canonical_hash(self.semantic_mapping())
        if self.receipt_fingerprint != expected:
            raise ValueError("common-risk receipt fingerprint mismatch")
        object.__setattr__(self, "excluded_reason_counts", reason_counts)
        object.__setattr__(self, "expected_group_counts", group_counts)

    def semantic_mapping(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "artifact_id": self.artifact_id,
            "source_manifest_id": self.source_manifest_id,
            "source_sha256": self.source_sha256,
            "source_slice_fingerprint": self.source_slice_fingerprint,
            "asset": self.asset,
            "target_family_fingerprint": self.target_family_fingerprint,
            "materialization_policy_id": self.materialization_policy_id,
            "sequence_hash_algorithm": self.sequence_hash_algorithm,
            "included_count": self.included_count,
            "included_observation_sha256": self.included_observation_sha256,
            "excluded_count": self.excluded_count,
            "excluded_observation_sha256": self.excluded_observation_sha256,
            "excluded_reason_sha256": self.excluded_reason_sha256,
            "excluded_reason_counts": self.excluded_reason_counts,
            "included_group_sha256": self.included_group_sha256,
            "expected_group_counts": self.expected_group_counts,
        }

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            **self.semantic_mapping(),
            "receipt_fingerprint": self.receipt_fingerprint,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetCompilerReceipt:
    """One digest-only target compilation receipt per asset and choice."""

    schema: str
    artifact_id: str
    source_manifest_id: str
    source_sha256: str
    source_slice_fingerprint: str
    asset: str
    target_choice_id: str
    target_fingerprints: tuple[tuple[str, str], ...]
    common_risk_receipt_fingerprint: str
    null_algorithm: str
    materialization_policy_id: str
    expected_row_count: int
    expected_row_sha256: str
    compiler_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema != TARGET_COMPILER_RECEIPT_SCHEMA:
            raise ValueError("unsupported target compiler receipt schema")
        for name in (
            "artifact_id",
            "source_manifest_id",
            "source_sha256",
            "source_slice_fingerprint",
            "asset",
            "target_choice_id",
            "common_risk_receipt_fingerprint",
            "null_algorithm",
            "materialization_policy_id",
            "expected_row_sha256",
            "compiler_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"target compiler {name} must be non-empty")
        _strict_sha256(self.target_choice_id, "target compiler target_choice_id")
        for name in (
            "source_sha256",
            "source_slice_fingerprint",
            "common_risk_receipt_fingerprint",
            "expected_row_sha256",
            "compiler_fingerprint",
        ):
            _strict_sha256(getattr(self, name), f"target compiler {name}")
        if self.null_algorithm != FEASIBLE_RANDOM_PRICE_ID:
            raise ValueError("target compiler null algorithm is unsupported")
        if self.materialization_policy_id != TARGET_MATERIALIZATION_POLICY_ID:
            raise ValueError("target compiler materialization policy is unsupported")
        if (
            isinstance(self.expected_row_count, bool)
            or not isinstance(self.expected_row_count, int)
            or self.expected_row_count < 0
        ):
            raise ValueError("target compiler expected row count is invalid")
        fingerprints = tuple(sorted(self.target_fingerprints))
        if not fingerprints:
            raise ValueError("target compiler target fingerprints must be non-empty")
        if any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0].strip()
            for item in fingerprints
        ) or len({item[0] for item in fingerprints}) != len(fingerprints):
            raise ValueError("target compiler target fingerprints are malformed")
        for timeframe, fingerprint in fingerprints:
            _strict_sha256(fingerprint, f"target compiler {timeframe} fingerprint")
        object.__setattr__(self, "target_fingerprints", fingerprints)
        if self.compiler_fingerprint != canonical_hash(self.semantic_mapping()):
            raise ValueError("target compiler receipt fingerprint mismatch")

    def semantic_mapping(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "artifact_id": self.artifact_id,
            "source_manifest_id": self.source_manifest_id,
            "source_sha256": self.source_sha256,
            "source_slice_fingerprint": self.source_slice_fingerprint,
            "asset": self.asset,
            "target_choice_id": self.target_choice_id,
            "target_fingerprints": self.target_fingerprints,
            "common_risk_receipt_fingerprint": self.common_risk_receipt_fingerprint,
            "null_algorithm": self.null_algorithm,
            "materialization_policy_id": self.materialization_policy_id,
            "expected_row_count": self.expected_row_count,
            "expected_row_sha256": self.expected_row_sha256,
        }

    @property
    def receipt_fingerprint(self) -> str:
        return self.compiler_fingerprint

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            **self.semantic_mapping(),
            "compiler_fingerprint": self.compiler_fingerprint,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthenticatedTargetPlan:
    """Digest-only common-risk plan over one authenticated asset artifact."""

    artifact: EpisodeArtifact
    source_manifest_id: str
    source_sha256: str
    source_slice_fingerprint: str
    asset: str
    venue: str
    instrument_id: str
    bars_by_timeframe: Mapping[str, tuple[SRBar, ...]]
    source_identities: tuple[tuple[str, tuple[str, ...]], ...]
    source_identity_hashes: tuple[tuple[str, str], ...]
    observation_timeframe: str
    observation_open_index: tuple[datetime, ...]
    target_specs: tuple[tuple[str, tuple[tuple[str, ResolvedTargetSpec], ...]], ...]
    knowledge_cutoff: datetime
    common_risk_receipt: CommonRiskReceipt
    compiler_receipts: tuple[TargetCompilerReceipt, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, EpisodeArtifact):
            raise TypeError("authenticated target plan requires EpisodeArtifact")
        for name in (
            "source_manifest_id",
            "source_sha256",
            "source_slice_fingerprint",
            "asset",
            "venue",
            "instrument_id",
            "observation_timeframe",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"authenticated target plan {name} is required")
        _strict_sha256(self.source_sha256, "target plan source_sha256")
        _strict_sha256(self.source_slice_fingerprint, "target plan source slice")
        require_utc(self.knowledge_cutoff, field_name="target plan knowledge_cutoff")
        if not isinstance(self.common_risk_receipt, CommonRiskReceipt):
            raise TypeError("target plan common risk receipt is required")
        records = {
            str(timeframe): tuple(values)
            for timeframe, values in self.bars_by_timeframe.items()
        }
        if not records or any(
            not values or any(not isinstance(bar, SRBar) for bar in values)
            for values in records.values()
        ):
            raise ValueError("target plan bars are malformed")
        for timeframe, values in records.items():
            grid = grid_for(timeframe)
            if any(bar.timeframe != timeframe for bar in values):
                raise ValueError("target plan bar timeframe differs from lane")
            grid.validate_contiguous(
                tuple(bar.bar_open_at for bar in values),
                tuple(bar.bar_close_at for bar in values),
            )
        identities = tuple(sorted(self.source_identities))
        hashes = tuple(sorted(self.source_identity_hashes))
        identity_timeframes = tuple(timeframe for timeframe, _ in identities)
        hash_timeframes = tuple(timeframe for timeframe, _ in hashes)
        if (
            identity_timeframes != hash_timeframes
            or len(set(identity_timeframes)) != len(identity_timeframes)
            or set(identity_timeframes) != set(records)
        ):
            raise ValueError("target plan source identity metadata differs")
        if any(
            canonical_hash(ids) != digest
            for (timeframe, ids), (_, digest) in zip(identities, hashes, strict=True)
        ):
            raise ValueError("target plan source identity hash differs")
        if any(len(ids) != len(records[timeframe]) for timeframe, ids in identities):
            raise ValueError("target plan source identity counts differ")
        choices = tuple(self.target_specs)
        if not choices or len({item[0] for item in choices}) != len(choices):
            raise ValueError("target plan choices must be unique")
        if self.observation_timeframe not in records:
            raise ValueError("target plan observation timeframe is not in source lanes")
        if tuple(self.observation_open_index) != tuple(
            bar.bar_open_at for bar in records[self.observation_timeframe]
        ):
            raise ValueError("target plan observation index differs from source bars")
        receipts = tuple(
            sorted(self.compiler_receipts, key=lambda item: item.target_choice_id)
        )
        if {item.target_choice_id for item in receipts} != {
            item[0] for item in choices
        }:
            raise ValueError("target plan compiler receipts do not cover choices")
        if (
            self.common_risk_receipt.artifact_id != self.artifact.artifact_id
            or self.common_risk_receipt.source_manifest_id != self.source_manifest_id
            or self.common_risk_receipt.source_sha256 != self.source_sha256
            or self.common_risk_receipt.source_slice_fingerprint
            != self.source_slice_fingerprint
            or self.common_risk_receipt.asset != self.asset
        ):
            raise ValueError("target plan common-risk identity differs")
        if self.common_risk_receipt.target_family_fingerprint != (
            _target_family_fingerprint(choices)
        ):
            raise ValueError("target plan target-family identity differs")
        for receipt in receipts:
            if (
                receipt.artifact_id != self.artifact.artifact_id
                or receipt.source_manifest_id != self.source_manifest_id
                or receipt.source_sha256 != self.source_sha256
                or receipt.source_slice_fingerprint != self.source_slice_fingerprint
                or receipt.asset != self.asset
                or receipt.common_risk_receipt_fingerprint
                != self.common_risk_receipt.receipt_fingerprint
            ):
                raise ValueError("target plan compiler receipt identity differs")
            choice_specs = dict(choices)[receipt.target_choice_id]
            expected_target_fingerprints = tuple(
                (timeframe, scientific_target_fingerprint(spec))
                for timeframe, spec in sorted(choice_specs)
            )
            if receipt.target_fingerprints != expected_target_fingerprints:
                raise ValueError("target plan compiler target fingerprints differ")
        object.__setattr__(self, "bars_by_timeframe", MappingProxyType(records))
        object.__setattr__(self, "source_identities", identities)
        object.__setattr__(self, "source_identity_hashes", hashes)
        object.__setattr__(self, "target_specs", choices)
        object.__setattr__(self, "compiler_receipts", receipts)
        object.__setattr__(
            self, "observation_open_index", tuple(self.observation_open_index)
        )

    def specs_for(self, target_choice_id: str) -> Mapping[str, ResolvedTargetSpec]:
        for choice_id, specs in self.target_specs:
            if choice_id == target_choice_id:
                return MappingProxyType(dict(specs))
        raise KeyError(target_choice_id)

    def receipt_for(self, target_choice_id: str) -> TargetCompilerReceipt:
        for receipt in self.compiler_receipts:
            if receipt.target_choice_id == target_choice_id:
                return receipt
        raise KeyError(target_choice_id)


def _target_family_fingerprint(
    target_specs: tuple[tuple[str, tuple[tuple[str, ResolvedTargetSpec], ...]], ...],
) -> str:
    return target_family_fingerprint_from_choices(
        tuple(
            (
                choice_id,
                tuple(
                    (timeframe, scientific_target_fingerprint(spec))
                    for timeframe, spec in specs
                ),
            )
            for choice_id, specs in target_specs
        )
    )


def target_family_fingerprint_from_choices(
    choices: Sequence[tuple[str, Sequence[tuple[str, str]]]],
) -> str:
    """Return the canonical identity for ordered choice target fingerprints.

    The artifact and optimizer boundaries share this exact helper so the
    common-risk receipt cannot be reinterpreted by a second canonicalization
    formula.
    """

    return canonical_hash(
        {
            "schema": TARGET_FAMILY_SCHEMA,
            "choices": tuple(
                (choice_id, tuple(timeframe_fingerprints))
                for choice_id, timeframe_fingerprints in choices
            ),
        }
    )


def _artifact_for_target_plan(
    artifact: EpisodeArtifact | str | Path,
) -> EpisodeArtifact:
    if isinstance(artifact, EpisodeArtifact):
        fresh = _load_artifact_manifest_handle(artifact.directory)
        if artifact.artifact_id != fresh.artifact_id or canonical_json(
            artifact.manifest
        ) != canonical_json(fresh.manifest):
            raise ValueError("episode artifact handle is stale or forged")
        return fresh
    if isinstance(artifact, (str, Path)):
        return _load_artifact_manifest_handle(artifact)
    raise TypeError("target plan artifact must be EpisodeArtifact or path")


def _source_slice_for_target_plan(
    artifact: EpisodeArtifact,
    source_slice: AuthenticatedSourceSlice,
) -> tuple[
    Mapping[str, tuple[SRBar, ...]],
    tuple[tuple[str, tuple[str, ...]], ...],
    tuple[tuple[str, str], ...],
]:
    if not isinstance(source_slice, AuthenticatedSourceSlice):
        raise TypeError("target plan requires AuthenticatedSourceSlice")
    manifest = artifact.manifest
    identity_fields = (
        ("asset", source_slice.asset),
        ("venue", source_slice.venue),
        ("instrument_id", source_slice.instrument_id),
        ("source_manifest_id", source_slice.source_manifest_id),
        ("source_sha256", source_slice.source_sha256),
        ("causal_slice_fingerprint", source_slice.slice_fingerprint),
    )
    for name, value in identity_fields:
        if manifest[name] != value:
            raise ValueError(f"target plan source {name} differs from artifact")
    if tuple(manifest["full_bounds"]) != tuple(source_slice.bounds):
        raise ValueError("target plan source bounds differ from artifact")
    if tuple(manifest["acquisition_evidence"]) != tuple(
        source_slice.acquisition_evidence
    ):
        raise ValueError("target plan acquisition evidence differs from artifact")
    records = {
        timeframe: tuple(values)
        for timeframe, values in source_slice.records_by_timeframe.items()
    }
    manifest_counts = tuple(manifest["source_record_counts"])
    manifest_identities = tuple(manifest["source_record_identity_hashes"])
    if tuple(sorted(source_slice.record_counts)) != tuple(sorted(manifest_counts)):
        raise ValueError("target plan source record counts differ from artifact")
    if tuple(sorted(source_slice.record_identities)) != tuple(
        sorted(
            (
                timeframe,
                tuple(_source_identity(item) for item in records[timeframe]),
            )
            for timeframe, _ in manifest_identities
        )
    ):
        raise ValueError("target plan source record identities differ from artifact")
    source_hashes = tuple(
        (timeframe, canonical_hash(ids))
        for timeframe, ids in sorted(source_slice.record_identities)
    )
    if source_hashes != tuple(sorted(manifest_identities)):
        raise ValueError("target plan source identity hashes differ from artifact")
    if not records:
        raise ValueError("target plan source slice cannot be empty")
    bars = {
        timeframe: tuple(item.bar for item in values)
        for timeframe, values in records.items()
    }
    if any(
        any(not isinstance(item, SourceBarRecord) for item in values)
        for values in records.values()
    ):
        raise TypeError("target plan source records must be authenticated records")
    return bars, tuple(sorted(source_slice.record_identities)), source_hashes


def _normalize_target_choices(
    target_choices: Sequence[tuple[str, Mapping[str, ResolvedTargetSpec]]],
    *,
    manifest: Mapping[str, Any],
) -> tuple[
    tuple[tuple[str, tuple[tuple[str, ResolvedTargetSpec], ...]], ...],
    str,
]:
    choices: list[tuple[str, tuple[tuple[str, ResolvedTargetSpec], ...]]] = []
    seen: set[str] = set()
    expected_timeframes = {
        _group_from_manifest_value(item).timeframe
        for item in manifest["expected_groups"]
    }
    trigger_timeframe = manifest["trigger_timeframe"]
    expected_source_keys: set[str] | None = None
    observation_timeframes: set[str] = set()
    for item in tuple(target_choices):
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError("target choices must be (choice_id, target-spec mapping)")
        choice_id, raw_specs = item
        if not isinstance(choice_id, str) or not choice_id.strip():
            raise ValueError("target choice IDs must be non-empty strings")
        _strict_sha256(choice_id, "target choice ID")
        if choice_id in seen:
            raise ValueError("target choices must have unique IDs")
        if not isinstance(raw_specs, Mapping) or not raw_specs:
            raise TypeError("target choice specs must be a non-empty mapping")
        specs = dict(raw_specs)
        if any(not isinstance(spec, ResolvedTargetSpec) for spec in specs.values()):
            raise TypeError("target choices must contain ResolvedTargetSpec values")
        if set(specs) != {spec.source_timeframe for spec in specs.values()}:
            raise ValueError("target choice keys must equal source timeframes")
        for timeframe, spec in specs.items():
            if timeframe != spec.source_timeframe:
                raise ValueError("target choice key differs from source timeframe")
            if spec.observation_timeframe != trigger_timeframe:
                raise ValueError(
                    "target choices must use the artifact trigger timeframe"
                )
            observation_timeframes.add(spec.observation_timeframe)
        source_keys = set(specs)
        if expected_source_keys is None:
            expected_source_keys = source_keys
        elif source_keys != expected_source_keys:
            raise ValueError("target choices must cover identical source timeframes")
        choices.append((choice_id, tuple(sorted(specs.items()))))
        seen.add(choice_id)
    if not choices:
        raise ValueError("target choices must not be empty")
    if expected_source_keys != expected_timeframes:
        raise ValueError(
            "target choices must cover the exact expected scientific source lanes"
        )
    if observation_timeframes != {trigger_timeframe}:
        raise ValueError("target choices must share one observation timeframe")
    target_specs = tuple(choices)
    return target_specs, _target_family_fingerprint(target_specs)


def _target_row_source_checks(
    row: CompactEpisodeRecord,
    *,
    plan: AuthenticatedTargetPlan,
    specs: Mapping[str, ResolvedTargetSpec],
) -> tuple[int, int]:
    if row.group.asset != plan.asset or row.group not in {
        _group_from_manifest_value(item)
        for item in plan.artifact.manifest["expected_groups"]
    }:
        raise ValueError("target outcome group is outside artifact ontology")
    timeframe = row.group.timeframe
    spec = specs.get(timeframe)
    if spec is None:
        raise ValueError("target outcome group has no target specification")
    source_records = plan.bars_by_timeframe[timeframe]
    identities = dict(plan.source_identities)[timeframe]
    source_index = row.source_close_index
    if source_index >= len(source_records) or source_index >= len(identities):
        raise ValueError("target outcome source close index is outside source slice")
    source_bar = source_records[source_index]
    if (
        source_bar.bar_close_at != row.issuance_cutoff
        or identities[source_index] != row.source_close_identity
    ):
        raise ValueError(
            "target outcome source close index/identity is not authenticated"
        )
    observation_bars = plan.bars_by_timeframe[plan.observation_timeframe]
    opens = plan.observation_open_index
    first = bisect_left(opens, row.issuance_cutoff)
    expected_trigger_index = first if first < len(observation_bars) else None
    expected_trigger_identity = (
        observation_bars[first].identity if expected_trigger_index is not None else None
    )
    if (
        row.first_subsequent_trigger_index != expected_trigger_index
        or row.first_subsequent_trigger_identity != expected_trigger_identity
    ):
        raise ValueError("target outcome trigger index/identity is not authenticated")
    return source_index, first


def _common_risk_decision(
    row: CompactEpisodeRecord,
    *,
    plan: AuthenticatedTargetPlan,
    specs_by_timeframe: Mapping[str, tuple[ResolvedTargetSpec, ...]],
) -> str | None:
    timeframe = row.group.timeframe
    specs = specs_by_timeframe.get(timeframe)
    if not specs:
        raise ValueError("target outcome source timeframe has no target family")
    source_index, first = _target_row_source_checks(
        row, plan=plan, specs={timeframe: specs[0]}
    )
    max_lookback = max(item.reference_lookback for item in specs)
    max_horizon = max((item.horizon for item in specs), default=timedelta(0))
    if source_index < max_lookback:
        return "insufficient_source_history"
    observation_bars = plan.bars_by_timeframe[plan.observation_timeframe]
    if first >= len(observation_bars):
        return "right_edge_horizon"
    duration = grid_for(plan.observation_timeframe).duration
    horizon_bars = max_horizon // duration
    if max_horizon != duration * horizon_bars:
        raise ValueError("target family horizon is not observation-grid aligned")
    end_index = first + horizon_bars
    if (
        end_index > len(observation_bars)
        or row.issuance_cutoff + max_horizon > plan.knowledge_cutoff
    ):
        return "right_edge_horizon"
    if (
        observation_bars[end_index - 1].bar_close_at
        != row.issuance_cutoff + max_horizon
    ):
        raise ValueError("target outcome observation bars contain an authenticated gap")
    return None


class _CommonRiskReceiptAccumulator:
    """Bounded common-risk receipt state for one authenticated artifact scan."""

    __slots__ = (
        "excluded_count",
        "excluded_digest",
        "expected_groups",
        "group_counts",
        "group_digest",
        "included_count",
        "included_digest",
        "reason_counts",
        "reason_digest",
    )

    def __init__(self, expected_groups: Sequence[ScientificGroupKey]) -> None:
        self.expected_groups = tuple(sorted(expected_groups))
        self.included_digest = hashlib.sha256()
        self.excluded_digest = hashlib.sha256()
        self.reason_digest = hashlib.sha256()
        self.group_digest = hashlib.sha256()
        self.included_count = 0
        self.excluded_count = 0
        self.reason_counts: Counter[str] = Counter()
        self.group_counts: Counter[str] = Counter()

    def consume(self, row: CompactEpisodeRecord, reason: str | None) -> None:
        if reason is None:
            _sequence_digest_update(self.included_digest, row.observation_id)
            _sequence_digest_update(
                self.group_digest, (row.observation_id, row.group.key)
            )
            self.included_count += 1
            self.group_counts[row.group.key] += 1
            return
        _sequence_digest_update(self.excluded_digest, row.observation_id)
        _sequence_digest_update(self.reason_digest, (row.observation_id, reason))
        self.excluded_count += 1
        self.reason_counts[reason] += 1

    def finish(
        self,
        *,
        artifact: EpisodeArtifact,
        source_slice: AuthenticatedSourceSlice,
        target_family_fingerprint: str,
    ) -> CommonRiskReceipt:
        semantic = {
            "schema": COMMON_RISK_RECEIPT_SCHEMA,
            "artifact_id": artifact.artifact_id,
            "source_manifest_id": source_slice.source_manifest_id,
            "source_sha256": source_slice.source_sha256,
            "source_slice_fingerprint": source_slice.slice_fingerprint,
            "asset": source_slice.asset,
            "target_family_fingerprint": target_family_fingerprint,
            "materialization_policy_id": TARGET_MATERIALIZATION_POLICY_ID,
            "sequence_hash_algorithm": ISSUANCE_SEQUENCE_HASH_ALGORITHM,
            "included_count": self.included_count,
            "included_observation_sha256": self.included_digest.hexdigest(),
            "excluded_count": self.excluded_count,
            "excluded_observation_sha256": self.excluded_digest.hexdigest(),
            "excluded_reason_sha256": self.reason_digest.hexdigest(),
            "excluded_reason_counts": tuple(sorted(self.reason_counts.items())),
            "included_group_sha256": self.group_digest.hexdigest(),
            "expected_group_counts": tuple(
                (group.key, self.group_counts.get(group.key, 0))
                for group in self.expected_groups
            ),
        }
        return CommonRiskReceipt(
            **semantic,
            receipt_fingerprint=canonical_hash(semantic),
        )


def _build_common_risk_receipt(
    artifact: EpisodeArtifact,
    *,
    source_slice: AuthenticatedSourceSlice,
    plan: AuthenticatedTargetPlan,
    target_family_fingerprint: str,
    specs_by_timeframe: Mapping[str, tuple[ResolvedTargetSpec, ...]],
) -> CommonRiskReceipt:
    expected_groups = tuple(
        _group_from_manifest_value(item)
        for item in artifact.manifest["expected_groups"]
    )
    receipt = _CommonRiskReceiptAccumulator(expected_groups)
    for row in _iter_validated_artifact_rows(artifact):
        reason = _common_risk_decision(
            row,
            plan=plan,
            specs_by_timeframe=specs_by_timeframe,
        )
        receipt.consume(row, reason)
    return receipt.finish(
        artifact=artifact,
        source_slice=source_slice,
        target_family_fingerprint=target_family_fingerprint,
    )


def _empty_common_risk_receipt(
    *,
    artifact: EpisodeArtifact,
    source_slice: AuthenticatedSourceSlice,
    target_family_fingerprint: str,
) -> CommonRiskReceipt:
    expected_groups = tuple(
        _group_from_manifest_value(item)
        for item in artifact.manifest["expected_groups"]
    )
    semantic = {
        "schema": COMMON_RISK_RECEIPT_SCHEMA,
        "artifact_id": artifact.artifact_id,
        "source_manifest_id": source_slice.source_manifest_id,
        "source_sha256": source_slice.source_sha256,
        "source_slice_fingerprint": source_slice.slice_fingerprint,
        "asset": source_slice.asset,
        "target_family_fingerprint": target_family_fingerprint,
        "materialization_policy_id": TARGET_MATERIALIZATION_POLICY_ID,
        "sequence_hash_algorithm": ISSUANCE_SEQUENCE_HASH_ALGORITHM,
        "included_count": 0,
        "included_observation_sha256": _digest_empty(),
        "excluded_count": 0,
        "excluded_observation_sha256": _digest_empty(),
        "excluded_reason_sha256": _digest_empty(),
        "excluded_reason_counts": (),
        "included_group_sha256": _digest_empty(),
        "expected_group_counts": tuple(
            (group.key, 0) for group in sorted(expected_groups)
        ),
    }
    return CommonRiskReceipt(
        **semantic,
        receipt_fingerprint=canonical_hash(semantic),
    )


def _outcome_rows_for_choice(
    plan: AuthenticatedTargetPlan,
    *,
    target_choice_id: str,
    common_risk: CommonRiskReceipt,
    common_risk_accumulator: _CommonRiskReceiptAccumulator | None = None,
) -> Iterator[TargetOutcomeRow]:
    specs = plan.specs_for(target_choice_id)
    specs_by_timeframe: Mapping[str, tuple[ResolvedTargetSpec, ...]] = {
        timeframe: tuple(
            dict(choice_specs)[timeframe]
            for _, choice_specs in plan.target_specs
            if timeframe in dict(choice_specs)
        )
        for timeframe in specs
    }
    observation_bars = plan.bars_by_timeframe[plan.observation_timeframe]
    for row in _iter_validated_artifact_rows(plan.artifact):
        reason = _common_risk_decision(
            row,
            plan=plan,
            specs_by_timeframe=specs_by_timeframe,
        )
        if common_risk_accumulator is not None:
            common_risk_accumulator.consume(row, reason)
        if reason is not None:
            continue
        source_index, first = _target_row_source_checks(row, plan=plan, specs=specs)
        spec = specs[row.group.timeframe]
        observation_duration = grid_for(plan.observation_timeframe).duration
        horizon_bars = spec.horizon // observation_duration
        if spec.horizon != observation_duration * horizon_bars:
            raise ValueError("target horizon is not observation-grid aligned")
        reference = plan.bars_by_timeframe[spec.source_timeframe][
            source_index - spec.reference_lookback : source_index + 1
        ]
        actual_result = label_scientific_target_indexed(
            row.zone,
            issued_at=row.issuance_cutoff,
            future_bars=observation_bars,
            future_start_index=first,
            future_end_index=first + horizon_bars,
            target_spec=spec,
            reference_bars=reference,
        )
        null_result = None
        null_available = (
            row.feasible_null.complete and row.feasible_null.zone is not None
        )
        if null_available:
            null_result = label_scientific_target_indexed(
                row.feasible_null.zone,
                issued_at=row.issuance_cutoff,
                future_bars=observation_bars,
                future_start_index=first,
                future_end_index=first + horizon_bars,
                target_spec=spec,
                reference_bars=reference,
            )
        result = TargetOutcomeRow(
            observation_id=row.observation_id,
            group=row.group,
            issuance_cutoff=row.issuance_cutoff,
            cluster_identity=row.cluster_identity,
            target_fingerprint=scientific_target_fingerprint(spec),
            null_fingerprint=row.feasible_null.null_fingerprint,
            null_available=null_available,
            actual=_target_outcome_from_result(actual_result),
            null=(
                None
                if null_result is None
                else _target_outcome_from_result(null_result)
            ),
        )
        if result.null_available != (result.null is not None):
            raise ValueError("target outcome null availability is inconsistent")
        yield result


def _compiler_receipt_for_rows(
    plan: AuthenticatedTargetPlan,
    *,
    target_choice_id: str,
    common_risk: CommonRiskReceipt,
) -> TargetCompilerReceipt:
    specs = plan.specs_for(target_choice_id)
    digest = hashlib.sha256()
    count = 0
    for row in _outcome_rows_for_choice(
        plan, target_choice_id=target_choice_id, common_risk=common_risk
    ):
        _sequence_digest_update(digest, row.to_mapping())
        count += 1
    target_fingerprints = tuple(
        (timeframe, scientific_target_fingerprint(spec))
        for timeframe, spec in sorted(specs.items())
    )
    semantic = {
        "schema": TARGET_COMPILER_RECEIPT_SCHEMA,
        "artifact_id": plan.artifact.artifact_id,
        "source_manifest_id": plan.source_manifest_id,
        "source_sha256": plan.source_sha256,
        "source_slice_fingerprint": plan.source_slice_fingerprint,
        "asset": plan.asset,
        "target_choice_id": target_choice_id,
        "target_fingerprints": target_fingerprints,
        "common_risk_receipt_fingerprint": common_risk.receipt_fingerprint,
        "null_algorithm": FEASIBLE_RANDOM_PRICE_ID,
        "materialization_policy_id": TARGET_MATERIALIZATION_POLICY_ID,
        "expected_row_count": count,
        "expected_row_sha256": digest.hexdigest(),
    }
    return TargetCompilerReceipt(
        **semantic,
        compiler_fingerprint=canonical_hash(semantic),
    )


def _placeholder_compiler_receipt(
    *,
    artifact: EpisodeArtifact,
    source_manifest_id: str,
    source_sha256: str,
    source_slice_fingerprint: str,
    asset: str,
    target_specs: tuple[tuple[str, ResolvedTargetSpec], ...],
    target_choice_id: str,
    common_risk: CommonRiskReceipt,
) -> TargetCompilerReceipt:
    target_fingerprints = tuple(
        (timeframe, scientific_target_fingerprint(spec))
        for timeframe, spec in sorted(target_specs)
    )
    semantic = {
        "schema": TARGET_COMPILER_RECEIPT_SCHEMA,
        "artifact_id": artifact.artifact_id,
        "source_manifest_id": source_manifest_id,
        "source_sha256": source_sha256,
        "source_slice_fingerprint": source_slice_fingerprint,
        "asset": asset,
        "target_choice_id": target_choice_id,
        "target_fingerprints": target_fingerprints,
        "common_risk_receipt_fingerprint": common_risk.receipt_fingerprint,
        "null_algorithm": FEASIBLE_RANDOM_PRICE_ID,
        "materialization_policy_id": TARGET_MATERIALIZATION_POLICY_ID,
        "expected_row_count": 0,
        "expected_row_sha256": _digest_empty(),
    }
    return TargetCompilerReceipt(
        **semantic,
        compiler_fingerprint=canonical_hash(semantic),
    )


def prepare_authenticated_target_plan(
    artifact: EpisodeArtifact | str | Path,
    *,
    source_slice: AuthenticatedSourceSlice,
    target_choices: Sequence[tuple[str, Mapping[str, ResolvedTargetSpec]]],
) -> AuthenticatedTargetPlan:
    """Prepare one digest-only target plan over a sealed native artifact."""

    handle = _artifact_for_target_plan(artifact)
    bars, source_identities, source_hashes = _source_slice_for_target_plan(
        handle, source_slice
    )
    target_specs, target_family = _normalize_target_choices(
        target_choices, manifest=handle.manifest
    )
    trigger_timeframe = str(handle.manifest["trigger_timeframe"])
    trigger_bars = bars.get(trigger_timeframe)
    if trigger_bars is None:
        raise ValueError("target plan source slice lacks trigger timeframe")
    observation_opens = tuple(item.bar_open_at for item in trigger_bars)
    placeholder = _empty_common_risk_receipt(
        artifact=handle,
        source_slice=source_slice,
        target_family_fingerprint=target_family,
    )
    plan = AuthenticatedTargetPlan(
        artifact=handle,
        source_manifest_id=source_slice.source_manifest_id,
        source_sha256=source_slice.source_sha256,
        source_slice_fingerprint=source_slice.slice_fingerprint,
        asset=source_slice.asset,
        venue=source_slice.venue,
        instrument_id=source_slice.instrument_id,
        bars_by_timeframe=bars,
        source_identities=source_identities,
        source_identity_hashes=source_hashes,
        observation_timeframe=trigger_timeframe,
        observation_open_index=observation_opens,
        target_specs=target_specs,
        knowledge_cutoff=handle.manifest["knowledge_cutoff"],
        common_risk_receipt=placeholder,
        compiler_receipts=tuple(
            _placeholder_compiler_receipt(
                artifact=handle,
                source_manifest_id=source_slice.source_manifest_id,
                source_sha256=source_slice.source_sha256,
                source_slice_fingerprint=source_slice.slice_fingerprint,
                asset=source_slice.asset,
                target_specs=choice_specs,
                target_choice_id=choice_id,
                common_risk=placeholder,
            )
            for choice_id, choice_specs in target_specs
        ),
    )
    specs_by_timeframe: Mapping[str, tuple[ResolvedTargetSpec, ...]] = {
        timeframe: tuple(
            dict(choice_specs)[timeframe]
            for _, choice_specs in target_specs
            if timeframe in dict(choice_specs)
        )
        for timeframe, _ in target_specs[0][1]
    }
    common_risk = _build_common_risk_receipt(
        handle,
        source_slice=source_slice,
        plan=plan,
        target_family_fingerprint=target_family,
        specs_by_timeframe=specs_by_timeframe,
    )
    plan = replace(
        plan,
        common_risk_receipt=common_risk,
        compiler_receipts=tuple(
            _placeholder_compiler_receipt(
                artifact=handle,
                source_manifest_id=source_slice.source_manifest_id,
                source_sha256=source_slice.source_sha256,
                source_slice_fingerprint=source_slice.slice_fingerprint,
                asset=source_slice.asset,
                target_specs=choice_specs,
                target_choice_id=choice_id,
                common_risk=common_risk,
            )
            for choice_id, choice_specs in target_specs
        ),
    )
    receipts = tuple(
        _compiler_receipt_for_rows(
            plan, target_choice_id=choice_id, common_risk=common_risk
        )
        for choice_id, _ in target_specs
    )
    return replace(plan, compiler_receipts=receipts)


def _source_slice_from_target_plan(
    plan: AuthenticatedTargetPlan,
    *,
    artifact: EpisodeArtifact | None = None,
) -> AuthenticatedSourceSlice:
    handle = plan.artifact if artifact is None else artifact
    return AuthenticatedSourceSlice(
        source_manifest_id=plan.source_manifest_id,
        source_sha256=plan.source_sha256,
        venue=plan.venue,
        instrument_id=plan.instrument_id,
        asset=plan.asset,
        bounds=tuple(handle.manifest["full_bounds"]),
        records_by_timeframe={
            timeframe: tuple(
                SourceBarRecord(
                    venue=plan.venue,
                    instrument_id=plan.instrument_id,
                    asset=plan.asset,
                    bar=bar,
                    source_identity=identities[index],
                )
                for index, bar in enumerate(plan.bars_by_timeframe[timeframe])
            )
            for timeframe, identities in plan.source_identities
        },
        record_identities=plan.source_identities,
        record_counts=tuple(
            (timeframe, len(identities))
            for timeframe, identities in plan.source_identities
        ),
        acquisition_evidence=tuple(handle.manifest["acquisition_evidence"]),
        slice_fingerprint=plan.source_slice_fingerprint,
    )


def _reauthenticated_target_plan(
    plan: AuthenticatedTargetPlan,
) -> AuthenticatedTargetPlan:
    """Refresh a plan's manifest authority without consuming its episode JSONL."""

    fresh = _load_artifact_manifest_handle(plan.artifact.directory)
    if plan.artifact.artifact_id != fresh.artifact_id or canonical_json(
        plan.artifact.manifest
    ) != canonical_json(fresh.manifest):
        raise ValueError("episode artifact handle is stale or forged")
    _source_slice_for_target_plan(
        fresh,
        _source_slice_from_target_plan(plan, artifact=fresh),
    )
    return replace(plan, artifact=fresh)


def _verify_common_risk_receipt(plan: AuthenticatedTargetPlan) -> None:
    specs_by_timeframe: Mapping[str, tuple[ResolvedTargetSpec, ...]] = {
        timeframe: tuple(
            dict(choice_specs)[timeframe]
            for _, choice_specs in plan.target_specs
            if timeframe in dict(choice_specs)
        )
        for timeframe, _ in plan.target_specs[0][1]
    }
    computed = _build_common_risk_receipt(
        plan.artifact,
        source_slice=_source_slice_from_target_plan(plan),
        plan=plan,
        target_family_fingerprint=plan.common_risk_receipt.target_family_fingerprint,
        specs_by_timeframe=specs_by_timeframe,
    )
    if computed != plan.common_risk_receipt:
        raise ValueError("target outcome common-risk receipt differs from plan")


def iter_indexed_target_outcomes(
    plan: AuthenticatedTargetPlan,
    *,
    target_choice_id: str,
) -> Iterator[TargetOutcomeRow]:
    """Lazily rescan and authenticate one target-choice outcome stream."""

    if not isinstance(plan, AuthenticatedTargetPlan):
        raise TypeError("target outcome iterator requires AuthenticatedTargetPlan")

    def stream() -> Iterator[TargetOutcomeRow]:
        authenticated_plan = _reauthenticated_target_plan(plan)
        receipt = authenticated_plan.receipt_for(target_choice_id)
        common_risk = authenticated_plan.common_risk_receipt
        expected_groups = tuple(
            _group_from_manifest_value(item)
            for item in authenticated_plan.artifact.manifest["expected_groups"]
        )
        common_risk_accumulator = _CommonRiskReceiptAccumulator(expected_groups)
        digest = hashlib.sha256()
        count = 0
        for row in _outcome_rows_for_choice(
            authenticated_plan,
            target_choice_id=target_choice_id,
            common_risk=common_risk,
            common_risk_accumulator=common_risk_accumulator,
        ):
            _sequence_digest_update(digest, row.to_mapping())
            count += 1
            yield row
        computed_common_risk = common_risk_accumulator.finish(
            artifact=authenticated_plan.artifact,
            source_slice=_source_slice_from_target_plan(authenticated_plan),
            target_family_fingerprint=common_risk.target_family_fingerprint,
        )
        if computed_common_risk != common_risk:
            raise ValueError("target outcome common-risk receipt differs from plan")
        if (
            count != receipt.expected_row_count
            or digest.hexdigest() != receipt.expected_row_sha256
        ):
            raise ValueError("target outcome stream differs from compiler receipt")

    return stream()


__all__ = [
    "COMMON_RISK_RECEIPT_SCHEMA",
    "EPISODE_ARTIFACT_SCHEMA",
    "EPISODE_EVIDENCE_SCHEMA",
    "ISSUANCE_RULE_ID",
    "ISSUANCE_SEQUENCE_HASH_ALGORITHM",
    "TARGET_COMPILER_RECEIPT_SCHEMA",
    "TARGET_FAMILY_SCHEMA",
    "TARGET_MATERIALIZATION_POLICY_ID",
    "TARGET_OUTCOME_ROW_SCHEMA",
    "AuthenticatedTargetPlan",
    "CommonRiskReceipt",
    "CompactEpisodeRecord",
    "CompactNullReceipt",
    "EpisodeArtifact",
    "EpisodeArtifactWriter",
    "EpisodeEvidenceCollector",
    "EpisodeIssuance",
    "FixtureIndexedTargetMaterialization",
    "FixtureIndexedTargetTupleResult",
    "IdentitySequenceReceipt",
    "StreamingEvidenceResult",
    "StreamingStructuralReceipt",
    "TargetCompilerReceipt",
    "TargetOutcome",
    "TargetOutcomeRow",
    "iter_episode_records",
    "iter_fixture_indexed_targets",
    "iter_indexed_target_outcomes",
    "load_episode_artifact",
    "materialize_fixture_indexed_target",
    "prepare_authenticated_target_plan",
    "prepare_fixture_indexed_target_materialization",
    "run_streaming_episode_artifact",
    "run_streaming_episode_evidence",
    "run_streaming_episode_evidence_twice",
    "target_family_fingerprint_from_choices",
    "write_episode_artifact",
]
