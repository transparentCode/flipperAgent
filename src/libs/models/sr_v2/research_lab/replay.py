"""Exact trailing-window causal structural replay."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..config.resolver import ResolvedSRV2Config
from ..contracts import require_utc
from ..domain.bars import SRBar
from ..domain.identity import canonical_hash
from ..domain.state import SRState
from ..features.time import grid_for
from ..research.source import SourceBarRecord
from ..runtime.offline import OfflineCompute, OfflineMode
from ..structural import SRStepResult
from .config import ReplayIdentityMode, ResolvedSRV2ResearchNotebookConfig
from .trace import (
    LifecycleTransition,
    ReplaySnapshot,
    SnapshotZoneState,
    SRV2ResearchTrace,
    build_lifecycle_tables,
)

if TYPE_CHECKING:
    from .data import ResearchSourceSetManifest


class SRV2ResearchReplay:
    """Replay closed trigger cutoffs without handing future bars to core."""

    def __init__(
        self,
        config: ResolvedSRV2Config,
        research_config: ResolvedSRV2ResearchNotebookConfig,
    ) -> None:
        if not isinstance(config, ResolvedSRV2Config):
            raise TypeError("config must be ResolvedSRV2Config")
        self.config = config
        self.research_config = research_config

    def preflight_replay_steps(
        self,
        *,
        analysis_start: datetime | None = None,
        knowledge_cutoff: datetime | None = None,
    ) -> int:
        start = analysis_start or self.research_config.analysis_start
        end = knowledge_cutoff or self.research_config.knowledge_cutoff
        reconstruction_start = start - self.config.expiry
        require_utc(start, field_name="analysis_start")
        require_utc(end, field_name="knowledge_cutoff")
        if end <= reconstruction_start:
            raise ValueError("knowledge_cutoff must follow reconstruction_start")
        steps = int((end - reconstruction_start) / self.config.trigger_duration) + 1
        if steps > self.research_config.max_replay_steps:
            raise ValueError(
                "research replay exceeds max_replay_steps before provider access"
            )
        return steps

    def run(
        self,
        bars_by_timeframe: Mapping[str, Sequence[SRBar | SourceBarRecord]],
        *,
        source_manifest: ResearchSourceSetManifest | None = None,
        source_manifest_id: str | None = None,
        source_sha256: str | None = None,
        analysis_start: datetime | None = None,
        knowledge_cutoff: datetime | None = None,
        initial_state: SRState | None = None,
        identity_mode: str | None = None,
        research_callback: Callable[[SRStepResult, SRBar], None] | None = None,
    ) -> SRV2ResearchTrace:
        start = analysis_start or self.research_config.analysis_start
        end = knowledge_cutoff or self.research_config.knowledge_cutoff
        self._validate_bounds(start, end)
        reconstruction_start = start - self.config.expiry
        self.preflight_replay_steps(analysis_start=start, knowledge_cutoff=end)
        if source_manifest is not None:
            from .data import ResearchSourceSetManifest

            if not isinstance(source_manifest, ResearchSourceSetManifest):
                raise TypeError(
                    "source_manifest must be an authenticated aggregate source-set manifest"
                )
        mode = (identity_mode or self.research_config.replay_identity_mode).upper()
        if mode not in {
            ReplayIdentityMode.EXACT_CHECKPOINT,
            ReplayIdentityMode.WINDOW_RELATIVE,
        }:
            raise ValueError(
                "unsupported replay identity mode; FULL_SOURCE is not available"
            )
        if mode == ReplayIdentityMode.WINDOW_RELATIVE and initial_state is not None:
            raise ValueError("WINDOW_RELATIVE replay cannot accept an exact checkpoint")
        if source_manifest is not None:
            if (
                source_manifest_id is not None
                and source_manifest_id != source_manifest.manifest_id
            ):
                raise ValueError(
                    "source_manifest_id does not match authenticated source manifest"
                )
            if (
                source_sha256 is not None
                and source_sha256 != source_manifest.source_sha256
            ):
                raise ValueError(
                    "source_sha256 does not match authenticated source manifest"
                )
            source_manifest.verify(
                ladder=self.config.ladder,
                venue=self.research_config.venue,
                instrument_id=self.research_config.instrument_id,
                asset=self.research_config.asset,
                bounds=self._source_bounds(start, end),
            )
        elif source_manifest_id is not None or source_sha256 is not None:
            raise ValueError(
                "source identity must come from an authenticated aggregate source-set manifest"
            )
        if mode == ReplayIdentityMode.EXACT_CHECKPOINT:
            self._validate_checkpoint_identity(initial_state)
        normalized = self._normalize_source(bars_by_timeframe)
        if source_manifest is not None:
            self._validate_source_set_bars(normalized, source_manifest)
        trigger_values = normalized[self.config.trigger_timeframe]
        trigger_bar_by_close = {
            (item.bar if isinstance(item, SourceBarRecord) else item).bar_close_at: (
                item.bar if isinstance(item, SourceBarRecord) else item
            )
            for item in trigger_values
        }
        if not any(
            (item.bar if isinstance(item, SourceBarRecord) else item).bar_close_at
            == end
            for item in trigger_values
        ):
            raise ValueError(
                "research replay must observe the declared knowledge_cutoff on the closed trigger grid"
            )
        if mode == ReplayIdentityMode.EXACT_CHECKPOINT:
            self._validate_checkpoint_progression(
                initial_state, reconstruction_start=reconstruction_start
            )
        callback = research_callback
        manifest_id = source_manifest_id or (
            source_manifest.manifest_id if source_manifest else "unbound-source"
        )
        source_sha = source_sha256 or (
            source_manifest.source_sha256 if source_manifest else "unbound-source"
        )
        bars_for_compute = {
            timeframe: tuple(
                item.bar if isinstance(item, SourceBarRecord) else item
                for item in values
            )
            for timeframe, values in normalized.items()
        }
        offline = OfflineCompute(
            self.config,
            venue=self.research_config.venue,
            instrument_id=self.research_config.instrument_id,
            asset=self.research_config.asset,
        )
        all_transitions: list[LifecycleTransition] = []
        lineage_registry: dict[str, Any] = {}
        feature_rows: list[Mapping[str, Any]] = []
        candidate_rows: list[Mapping[str, Any]] = []
        peak_active = 0
        peak_terminal = 0
        trigger_closes: list[datetime] = []

        def collect(result: SRStepResult) -> None:
            nonlocal peak_active, peak_terminal
            cutoff = result.market_as_of
            trigger_closes.append(cutoff)
            peak_active = max(peak_active, len(result.state.active_lineages))
            peak_terminal = max(peak_terminal, len(result.state.terminal_tombstones))
            all_transitions.extend(result.transitions)
            lineage_registry.update(result.lineage_registry)
            if cutoff >= start:
                feature_rows.extend(result.feature_rows)
                for timeframe, candidates in result.candidates_by_timeframe.items():
                    for candidate in candidates:
                        candidate_rows.append(
                            {
                                "cutoff": cutoff,
                                "timeframe": timeframe,
                                "candidate_key": candidate.candidate_key,
                                "source_evidence_id": candidate.source_evidence_id,
                                "kernel_id": candidate.kernel_id,
                                "kernel_version": candidate.kernel_version,
                                "side": candidate.side.value,
                                "center": candidate.center,
                                "lower": candidate.lower,
                                "upper": candidate.upper,
                                "formed_at": candidate.formed_at,
                                "available_at": candidate.available_at,
                            }
                        )
            if callback is not None and cutoff >= start:
                try:
                    trigger_bar = trigger_bar_by_close[cutoff]
                except KeyError as exc:
                    raise ValueError(
                        "research callback cutoff has no exact closed trigger bar"
                    ) from exc
                callback(result, trigger_bar)

        run_result = offline.run(
            bars_for_compute,
            checkpoint=initial_state
            if mode == ReplayIdentityMode.EXACT_CHECKPOINT
            else None,
            cutoff=end,
            mode=(
                OfflineMode.CHECKPOINT_EXACT
                if mode == ReplayIdentityMode.EXACT_CHECKPOINT
                else OfflineMode.GENESIS_EXACT
            ),
            start_cutoff=(
                reconstruction_start
                if mode == ReplayIdentityMode.WINDOW_RELATIVE
                else None
            ),
            on_step=collect,
        )
        last_result = run_result.final_result
        trigger_closes = tuple(trigger_closes)
        if last_result is None:
            raise ValueError("research replay produced no structural result")
        final_snapshot_id = canonical_hash(
            {
                "source_manifest_id": manifest_id,
                "source_sha256": source_sha,
                "config_fingerprint": self.config.config_fingerprint,
                "cutoff": end,
                "source_cutoffs": last_result.source_cutoffs,
                "state_generation": last_result.state.generation,
            }
        )
        transitions = tuple(
            item.with_ordinal(index) for index, item in enumerate(all_transitions)
        )
        intervals, episodes = build_lifecycle_tables(
            transitions, zones_by_id=lineage_registry, trace_end=end
        )
        snapshot = ReplaySnapshot(
            cutoff=end,
            current_price=last_result.current_price,
            zones_by_timeframe={
                timeframe: tuple(
                    SnapshotZoneState.from_zone_record(record)
                    for record in last_result.state.active_lineages
                    if record.lineage.source_timeframe == timeframe
                )
                for timeframe in self.config.ladder
            },
            candidates_by_timeframe={
                timeframe: last_result.candidates_by_timeframe.get(timeframe, ())
                for timeframe in self.config.ladder
            },
            transitions=last_result.transitions,
            replay_point_id=final_snapshot_id,
        )
        bars_for_trace = {
            timeframe: tuple(
                item.bar if isinstance(item, SourceBarRecord) else item
                for item in values
            )
            for timeframe, values in normalized.items()
        }
        replay_id = canonical_hash(
            {
                "source_manifest_id": manifest_id,
                "source_sha256": source_sha,
                "config_fingerprint": self.config.config_fingerprint,
                "research_config_fingerprint": self.research_config.config_fingerprint,
                "analysis_start": start,
                "reconstruction_start": reconstruction_start,
                "knowledge_cutoff": end,
                "identity_mode": mode,
                "cutoffs": trigger_closes,
            }
        )
        provenance = (
            ()
            if source_manifest is None
            else tuple(
                {
                    "timeframe": entry["timeframe"],
                    "source_mode": entry["source_mode"],
                    "cache_access_mode": entry["cache_access_mode"],
                    "origin_mode": entry["origin_mode"],
                    "acquisition_cutoff": entry["acquisition_cutoff"],
                    "acquisition_evidence_sha256": entry["acquisition_evidence_sha256"],
                }
                for entry in source_manifest.entries
            )
        )
        return SRV2ResearchTrace(
            schema_version=2,
            source_manifest_id=manifest_id,
            source_sha256=source_sha,
            config_fingerprint=self.config.config_fingerprint,
            replay_id=replay_id,
            identity_mode=mode,
            analysis_start=start,
            knowledge_cutoff=end,
            reconstruction_start=reconstruction_start,
            snapshots=(snapshot,),
            lifecycle_intervals=intervals,
            touch_episodes=episodes,
            configured_timeframes=tuple(self.config.ladder),
            transitions=transitions,
            feature_rows=tuple(feature_rows),
            candidate_rows=tuple(candidate_rows),
            lineage_records=lineage_registry,
            bars_by_timeframe=bars_for_trace,
            metadata={
                "source_mode": self.research_config.source_mode,
                "window_semantics": mode,
                "configured_timeframes": tuple(self.config.ladder),
                "source_provenance": provenance,
                "peak_active_lineages": peak_active,
                "peak_terminal_tombstones": peak_terminal,
                "snapshot_scope": "FINAL_ACTIVE_LINEAGES_ONLY; full cutoff snapshots are not retained",
            },
        )

    def _validate_checkpoint_identity(self, initial_state: SRState | None) -> None:
        if not isinstance(initial_state, SRState):
            raise TypeError("EXACT_CHECKPOINT replay requires an initial SRState")
        if initial_state.config_fingerprint != self.config.config_fingerprint:
            raise ValueError(
                "checkpoint config fingerprint does not match runtime config"
            )
        if (initial_state.venue, initial_state.instrument_id, initial_state.asset) != (
            self.research_config.venue,
            self.research_config.instrument_id,
            self.research_config.asset,
        ):
            raise ValueError(
                "checkpoint runtime identity does not match research config"
            )
        if initial_state.last_trigger_at is None:
            raise ValueError("EXACT_CHECKPOINT replay requires a checkpoint cutoff")
        if (
            set(initial_state.source_cutoffs) != set(self.config.ladder)
            or set(initial_state.source_fingerprints) != set(self.config.ladder)
            or set(initial_state.source_fingerprint_sequences)
            != set(self.config.ladder)
        ):
            raise ValueError(
                "checkpoint source identities must cover the exact SR v2 ladder"
            )
        for timeframe, cutoff in initial_state.source_cutoffs.items():
            if cutoff != grid_for(timeframe).expected_closed_cutoff(
                initial_state.last_trigger_at
            ):
                raise ValueError(
                    f"checkpoint source cutoff is inconsistent for {timeframe}"
                )

    def _validate_checkpoint_progression(
        self, initial_state: SRState | None, *, reconstruction_start: datetime
    ) -> None:
        if initial_state is None or initial_state.last_trigger_at is None:
            raise ValueError("checkpoint cutoff is required")
        if initial_state.last_trigger_at not in {
            reconstruction_start - self.config.trigger_duration,
            reconstruction_start,
        }:
            raise ValueError(
                "checkpoint cutoff does not advance exactly to reconstruction_start"
            )

    @staticmethod
    def _validate_source_set_bars(
        bars_by_timeframe: Mapping[str, Sequence[SourceBarRecord | SRBar]],
        source_manifest: ResearchSourceSetManifest,
    ) -> None:
        expected_by_timeframe = {
            timeframe: result.records
            for timeframe, result in zip(
                source_manifest.timeframes, source_manifest.source_results, strict=True
            )
        }
        for timeframe, expected_records in expected_by_timeframe.items():
            actual = tuple(bars_by_timeframe[timeframe])
            if len(actual) != len(expected_records):
                raise ValueError(
                    "replay bars do not match authenticated source-set record count"
                )
            for actual_record, expected_record in zip(
                actual, expected_records, strict=True
            ):
                if isinstance(actual_record, SourceBarRecord):
                    matches = actual_record == expected_record
                else:
                    matches = actual_record == expected_record.bar
                if not matches:
                    raise ValueError(
                        "replay bars do not match authenticated source-set records"
                    )

    def _source_bounds(
        self, analysis_start: datetime, knowledge_cutoff: datetime
    ) -> Mapping[str, tuple[datetime, datetime]]:
        reconstruction_start = analysis_start - self.config.expiry
        requirements = dict(self.config.history_requirements())
        return {
            timeframe: (
                grid_for(timeframe).expected_closed_cutoff(reconstruction_start)
                - grid_for(timeframe).duration * requirements[timeframe],
                grid_for(timeframe).expected_closed_cutoff(knowledge_cutoff),
            )
            for timeframe in self.config.ladder
        }

    def _normalize_source(
        self, bars_by_timeframe: Mapping[str, Sequence[SRBar | SourceBarRecord]]
    ) -> Mapping[str, tuple[SRBar | SourceBarRecord, ...]]:
        if set(bars_by_timeframe) != set(self.config.ladder):
            raise ValueError("research source must cover the exact SR v2 ladder")
        result: dict[str, tuple[SRBar | SourceBarRecord, ...]] = {}
        for timeframe in self.config.ladder:
            values = tuple(bars_by_timeframe[timeframe])
            if not values:
                raise ValueError(f"research source has no bars for {timeframe}")
            bars = tuple(
                item.bar if isinstance(item, SourceBarRecord) else item
                for item in values
            )
            if any(not isinstance(item, (SRBar,)) for item in bars):
                raise TypeError(
                    "research source must contain SRBar or SourceBarRecord values"
                )
            if any(item.timeframe != timeframe for item in bars):
                raise ValueError("research source timeframe mismatch")
            grid_for(timeframe).validate_contiguous(
                tuple(item.bar_open_at for item in bars),
                tuple(item.bar_close_at for item in bars),
            )
            result[timeframe] = values
        return result

    def _validate_bounds(self, start: datetime, end: datetime) -> None:
        require_utc(start, field_name="analysis_start")
        require_utc(end, field_name="knowledge_cutoff")
        if start >= end:
            raise ValueError("replay analysis_start must precede knowledge_cutoff")
        trigger_timeframe = self.config.trigger_timeframe
        if not grid_for(trigger_timeframe).is_aligned(start) or not grid_for(
            trigger_timeframe
        ).is_aligned(end):
            raise ValueError("replay bounds must align to closed trigger grid")


__all__ = ["SRV2ResearchReplay"]
