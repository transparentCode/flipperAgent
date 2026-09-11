"""Streaming, causal compilation of the SR v2 scientific development set."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ..config.resolver import ResolvedSRV2Config
from ..config.schema import SUPPORTED_TIMEFRAMES
from ..contracts import ZoneSide, require_utc
from ..domain.bars import SRBar
from ..domain.candidates import Candidate
from ..domain.identity import canonical_hash
from ..domain.zones import ZoneLineage, ZoneRecord
from ..forecast.targets import (
    ResolvedTargetSpec,
    ScientificTargetResult,
    label_scientific_target,
    scientific_target_fingerprint,
)
from ..lifecycle.transitions import LifecycleTransition, TransitionType
from ..research.placebos import (
    FEASIBLE_RANDOM_PRICE_ID,
    FeasibleRandomPriceNull,
    build_feasible_random_price_null,
)
from ..research.source import SourceBarRecord
from ..structural import SRStepResult
from .replay import SRV2ResearchReplay

if TYPE_CHECKING:
    from .data import ResearchSourceSetManifest


@dataclass(frozen=True, slots=True, order=True)
class ScientificGroupKey:
    """The immutable asset/timeframe/kernel cell in development evidence."""

    asset: str
    timeframe: str
    kernel_id: str
    kernel_version: str
    side: ZoneSide

    def __post_init__(self) -> None:
        for name in ("asset", "timeframe", "kernel_id", "kernel_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.side, ZoneSide):
            raise TypeError("side must be ZoneSide")

    @property
    def kernel_identifier(self) -> str:
        return f"{self.kernel_id}@{self.kernel_version}"

    @property
    def key(self) -> str:
        return (
            f"{self.asset}|{self.timeframe}|{self.kernel_identifier}|{self.side.value}"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ScientificObservation:
    """One actual scientific target and its required matched feasible null."""

    observation_id: str
    group: ScientificGroupKey
    zone: ZoneLineage
    target: ScientificTargetResult
    feasible_null: FeasibleRandomPriceNull
    null_target: ScientificTargetResult | None
    source_manifest_id: str
    source_sha256: str
    target_fingerprint: str
    null_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, str) or not self.observation_id.strip():
            raise ValueError("observation_id must be non-empty")
        if not isinstance(self.group, ScientificGroupKey):
            raise TypeError("group must be ScientificGroupKey")
        if not isinstance(self.zone, ZoneLineage):
            raise TypeError("zone must be ZoneLineage")
        if self.observation_id != self.zone.zone_id:
            raise ValueError("observation identity must equal actual zone identity")
        if not isinstance(self.target, ScientificTargetResult):
            raise TypeError("target must be ScientificTargetResult")
        if self.target.zone_id != self.observation_id:
            raise ValueError("target identity differs from observation identity")
        if not isinstance(self.feasible_null, FeasibleRandomPriceNull):
            raise TypeError("feasible_null must be FeasibleRandomPriceNull")
        if self.feasible_null.source_observation_id != self.observation_id:
            raise ValueError("feasible null linkage differs from observation identity")
        if self.null_target is not None:
            if not isinstance(self.null_target, ScientificTargetResult):
                raise TypeError("null_target must be ScientificTargetResult or None")
            if self.feasible_null.zone is None:
                raise ValueError(
                    "an unavailable feasible null cannot have a null target"
                )
            if self.null_target.zone_id != self.feasible_null.zone.zone_id:
                raise ValueError("null target identity differs from null zone")
        for name in (
            "source_manifest_id",
            "source_sha256",
            "target_fingerprint",
            "null_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        expected_group = ScientificGroupKey(
            asset=self.zone.asset,
            timeframe=self.zone.source_timeframe,
            kernel_id=self.zone.kernel_id,
            kernel_version=self.zone.kernel_version,
            side=self.zone.side,
        )
        if self.group != expected_group:
            raise ValueError("observation group does not match actual zone provenance")

    @property
    def issued_at(self) -> datetime:
        return self.target.issued_at


@dataclass(frozen=True, slots=True, kw_only=True)
class CompiledScientificSet:
    """Immutable observations plus the exact expected group ontology."""

    source_manifest_id: str
    source_sha256: str
    expected_groups: tuple[ScientificGroupKey, ...]
    observations: tuple[ScientificObservation, ...]
    compiler_fingerprint: str
    knowledge_cutoff: datetime
    finalized_incomplete_count: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_manifest_id, str)
            or not self.source_manifest_id.strip()
        ):
            raise ValueError("source_manifest_id must be non-empty")
        if not isinstance(self.source_sha256, str) or not self.source_sha256.strip():
            raise ValueError("source_sha256 must be non-empty")
        groups = tuple(sorted(self.expected_groups))
        if any(not isinstance(item, ScientificGroupKey) for item in groups):
            raise TypeError("expected_groups must contain ScientificGroupKey values")
        observations = tuple(
            sorted(self.observations, key=lambda item: item.observation_id)
        )
        if any(not isinstance(item, ScientificObservation) for item in observations):
            raise TypeError("observations must contain ScientificObservation values")
        identities = tuple(item.observation_id for item in observations)
        if len(set(identities)) != len(identities):
            raise ValueError("compiled observations must have unique identities")
        if any(item.group not in groups for item in observations):
            raise ValueError(
                "compiled observation group is outside expected group ontology"
            )
        require_utc(self.knowledge_cutoff, field_name="knowledge_cutoff")
        if (
            isinstance(self.finalized_incomplete_count, bool)
            or not isinstance(self.finalized_incomplete_count, int)
            or self.finalized_incomplete_count < 0
        ):
            raise ValueError(
                "finalized_incomplete_count must be a non-negative integer"
            )
        if (
            not isinstance(self.compiler_fingerprint, str)
            or not self.compiler_fingerprint.strip()
        ):
            raise ValueError("compiler_fingerprint must be non-empty")
        object.__setattr__(self, "expected_groups", groups)
        object.__setattr__(self, "observations", observations)

    @property
    def missing_groups(self) -> tuple[ScientificGroupKey, ...]:
        present = {item.group for item in self.observations}
        return tuple(group for group in self.expected_groups if group not in present)

    @property
    def observations_by_group(
        self,
    ) -> Mapping[ScientificGroupKey, tuple[ScientificObservation, ...]]:
        grouped: dict[ScientificGroupKey, list[ScientificObservation]] = {
            group: [] for group in self.expected_groups
        }
        for observation in self.observations:
            grouped[observation.group].append(observation)
        return MappingProxyType(
            {group: tuple(values) for group, values in grouped.items()}
        )


@dataclass(slots=True)
class _Episode:
    zone: ZoneLineage
    group: ScientificGroupKey
    target_spec: ResolvedTargetSpec
    reference_bars: tuple[SRBar, ...]
    feasible_null: FeasibleRandomPriceNull
    future_bars: list[SRBar] = field(default_factory=list)
    last_future_cutoff: datetime | None = None


class ScientificObservationCompiler:
    """Consume eligible replay steps and compile actual/null episodes."""

    def __init__(
        self,
        source_bars: Mapping[str, Mapping[str, Sequence[SRBar | SourceBarRecord]]],
        *,
        model_config: ResolvedSRV2Config,
        target_specs: Mapping[str, ResolvedTargetSpec],
        null_seed: str,
        source_manifest: ResearchSourceSetManifest | None = None,
        source_sha256: str | None = None,
    ) -> None:
        if not isinstance(model_config, ResolvedSRV2Config):
            raise TypeError("model_config must be ResolvedSRV2Config")
        if not isinstance(target_specs, Mapping):
            raise TypeError("target_specs must be a mapping keyed by source timeframe")
        if not isinstance(null_seed, str) or not null_seed.strip():
            raise ValueError("null_seed must be non-empty")
        if source_manifest is not None:
            from .data import ResearchSourceSetManifest

            if not isinstance(source_manifest, ResearchSourceSetManifest):
                raise TypeError("source_manifest must be ResearchSourceSetManifest")
        self.model_config = model_config
        self._sources = self._normalize_sources(source_bars, ladder=model_config.ladder)
        self.assets = tuple(sorted(self._sources))
        self.target_specs = self._normalize_target_specs(target_specs)
        self.source_manifest = source_manifest
        normalized_digest = self._source_digest(self._sources)
        if source_manifest is not None:
            self._verify_source_manifest(source_manifest)
            if (
                source_sha256 is not None
                and source_sha256 != source_manifest.source_sha256
            ):
                raise ValueError("source_sha256 does not match source manifest")
            derived_manifest_id = source_manifest.manifest_id
            resolved_source_sha256 = source_manifest.source_sha256
        else:
            if source_sha256 is not None and source_sha256 != normalized_digest:
                raise ValueError("source_sha256 does not match normalized source bars")
            derived_manifest_id = canonical_hash(
                {"schema": "sr_v2.direct_source@1", "source_sha256": normalized_digest}
            )
            resolved_source_sha256 = normalized_digest
        self.source_manifest_id = derived_manifest_id
        self.source_sha256 = resolved_source_sha256
        self.null_seed = null_seed
        self.expected_groups = tuple(
            sorted(
                {
                    ScientificGroupKey(
                        asset=asset,
                        timeframe=timeframe,
                        kernel_id=kernel.kernel_id,
                        kernel_version=kernel.kernel_version,
                        side=side,
                    )
                    for asset in self.assets
                    for timeframe in model_config.ladder
                    for kernel in model_config.kernels
                    if kernel.enabled_for(timeframe)
                    for side in ZoneSide
                }
            )
        )
        self.compiler_fingerprint = canonical_hash(
            {
                "schema": "sr_v2.scientific_compiler@2",
                "source_manifest_id": self.source_manifest_id,
                "source_sha256": self.source_sha256,
                "model_config_fingerprint": model_config.config_fingerprint,
                "target_fingerprints": {
                    timeframe: scientific_target_fingerprint(spec)
                    for timeframe, spec in sorted(self.target_specs.items())
                },
                "null_algorithm": FEASIBLE_RANDOM_PRICE_ID,
                "null_seed": null_seed,
                "expected_groups": self.expected_groups,
            }
        )
        self._episodes: dict[str, _Episode] = {}
        self._compiled: dict[str, ScientificObservation] = {}
        self._seen_steps: set[tuple[str, datetime]] = set()
        self._latest_result: SRStepResult | None = None

    @staticmethod
    def _normalize_sources(
        source_bars: Mapping[str, Mapping[str, Sequence[SRBar | SourceBarRecord]]],
        *,
        ladder: Sequence[str],
    ) -> dict[str, dict[str, tuple[SRBar | SourceBarRecord, ...]]]:
        if not isinstance(source_bars, Mapping) or not source_bars:
            raise TypeError("source_bars must be a non-empty mapping")
        if any(not isinstance(value, Mapping) for value in source_bars.values()):
            raise TypeError("source_bars must be nested asset-to-timeframe mappings")
        raw_by_asset = source_bars
        normalized: dict[str, dict[str, tuple[SRBar | SourceBarRecord, ...]]] = {}
        supported = set(SUPPORTED_TIMEFRAMES)
        expected_ladder = set(ladder)
        for asset, raw in raw_by_asset.items():
            if not isinstance(asset, str) or not asset.strip():
                raise ValueError("source asset keys must be non-empty")
            if not isinstance(raw, Mapping):
                raise TypeError("asset source values must be mappings")
            if set(raw) - supported:
                raise ValueError("source timeframe keys are unsupported")
            if set(raw) != expected_ladder:
                missing = sorted(expected_ladder - set(raw))
                extra = sorted(set(raw) - expected_ladder)
                raise ValueError(
                    f"source bars must cover exact resolved ladder (missing={missing}, extra={extra})"
                )
            values_by_timeframe: dict[str, tuple[SRBar | SourceBarRecord, ...]] = {}
            for timeframe in ladder:
                values = tuple(raw[timeframe])
                if not values:
                    raise ValueError(f"source bars are empty for {asset}/{timeframe}")
                bars = tuple(
                    item.bar if isinstance(item, SourceBarRecord) else item
                    for item in values
                )
                if any(not isinstance(item, SRBar) for item in bars):
                    raise TypeError(
                        "source bars must contain SRBar or SourceBarRecord values"
                    )
                if any(item.timeframe != timeframe for item in bars):
                    raise ValueError(
                        "source bar timeframe does not match its mapping key"
                    )
                from ..features.time import grid_for

                grid_for(timeframe).validate_contiguous(
                    tuple(item.bar_open_at for item in bars),
                    tuple(item.bar_close_at for item in bars),
                )
                for item in values:
                    if isinstance(item, SourceBarRecord) and item.asset != asset:
                        raise ValueError(
                            "source record asset does not match its mapping key"
                        )
                values_by_timeframe[timeframe] = values
            normalized[asset] = values_by_timeframe
        if not normalized:
            raise ValueError("source bars must contain at least one asset")
        return normalized

    @staticmethod
    def _source_digest(
        sources: Mapping[str, Mapping[str, Sequence[SRBar | SourceBarRecord]]],
    ) -> str:
        return canonical_hash(
            {
                asset: {
                    timeframe: tuple(
                        item.bar if isinstance(item, SourceBarRecord) else item
                        for item in values
                    )
                    for timeframe, values in sorted(by_timeframe.items())
                }
                for asset, by_timeframe in sorted(sources.items())
            }
        )

    def _verify_source_manifest(self, manifest: ResearchSourceSetManifest) -> None:
        if tuple(manifest.timeframes) != tuple(self.model_config.ladder):
            raise ValueError("source manifest must cover the exact resolved ladder")
        manifest_assets = {
            str(entry["asset"]) for entry in manifest.entries if "asset" in entry
        }
        if manifest_assets != set(self.assets):
            raise ValueError(
                "source manifest and source bars must cover the same assets"
            )
        expected_by_timeframe = {
            timeframe: result.records
            for timeframe, result in zip(
                manifest.timeframes, manifest.source_results, strict=True
            )
        }
        if len(self.assets) != 1:
            raise ValueError(
                "ResearchSourceSetManifest currently authenticates one asset"
            )
        asset = self.assets[0]
        for timeframe in self.model_config.ladder:
            actual = self._sources[asset][timeframe]
            expected = expected_by_timeframe[timeframe]
            if len(actual) != len(expected):
                raise ValueError(
                    "source bars do not match authenticated source record count"
                )
            for actual_record, expected_record in zip(actual, expected, strict=True):
                matches = (
                    actual_record == expected_record
                    if isinstance(actual_record, SourceBarRecord)
                    else actual_record == expected_record.bar
                )
                if not matches:
                    raise ValueError(
                        "source bars do not match authenticated source records"
                    )

    def _normalize_target_specs(
        self, values: Mapping[str, ResolvedTargetSpec]
    ) -> dict[str, ResolvedTargetSpec]:
        required = {
            timeframe
            for timeframe in self.model_config.ladder
            if any(
                kernel.enabled_for(timeframe) for kernel in self.model_config.kernels
            )
        }
        if set(values) != required:
            raise ValueError(
                "target_specs must cover every enabled source timeframe exactly"
            )
        result = dict(values)
        if any(not isinstance(spec, ResolvedTargetSpec) for spec in result.values()):
            raise TypeError("target_specs must contain ResolvedTargetSpec values")
        for timeframe, spec in result.items():
            if timeframe != spec.source_timeframe:
                raise ValueError("target_specs keys must equal source_timeframe")
            if spec.observation_timeframe != self.model_config.trigger_timeframe:
                raise ValueError(
                    "target observation timeframe must equal model trigger timeframe"
                )
        return result

    def _source_for(self, asset: str, timeframe: str) -> tuple[SRBar, ...]:
        try:
            values = self._sources[asset][timeframe]
        except KeyError as exc:
            raise ValueError(f"source bars do not cover {asset}/{timeframe}") from exc
        return tuple(
            item.bar if isinstance(item, SourceBarRecord) else item for item in values
        )

    def _window_for(
        self, asset: str, timeframe: str, cutoff: datetime, count: int
    ) -> tuple[SRBar, ...]:
        require_utc(cutoff, field_name="scientific cutoff")
        values = self._source_for(asset, timeframe)
        closes = tuple(item.bar_close_at for item in values)
        end = bisect_right(closes, cutoff)
        if end == 0 or values[end - 1].bar_close_at != cutoff:
            raise ValueError(
                f"source bars lack exact closed cutoff for {asset}/{timeframe}"
            )
        if end < count:
            raise ValueError(
                f"source bars lack exact causal history for {asset}/{timeframe}"
            )
        return values[end - count : end]

    def _kernel_window(self, zone: ZoneLineage) -> tuple[SRBar, ...]:
        identifier = f"{zone.kernel_id}@{zone.kernel_version}"
        kernel = next(
            (
                item
                for item in self.model_config.kernels
                if item.identifier == identifier
            ),
            None,
        )
        if kernel is None:
            raise ValueError(f"created lineage kernel is not selected: {identifier}")
        required = int(
            kernel.spec.history_required(kernel.parameters_for(zone.source_timeframe))
        )
        return self._window_for(
            zone.asset, zone.source_timeframe, zone.available_at, required
        )

    @staticmethod
    def _candidate_matches(zone: ZoneLineage, candidate: Candidate) -> bool:
        return (
            isinstance(candidate, Candidate)
            and candidate.candidate_key
            == (zone.source_candidate_key or zone.source_evidence_id)
            and candidate.source_evidence_id == zone.source_evidence_id
            and candidate.source_timeframe == zone.source_timeframe
            and candidate.kernel_id == zone.kernel_id
            and candidate.kernel_version == zone.kernel_version
            and candidate.side is zone.side
            and candidate.center == zone.center
            and candidate.lower == zone.lower
            and candidate.upper == zone.upper
            and candidate.available_at == zone.available_at
        )

    def _created_zone(
        self, transition: LifecycleTransition, result: SRStepResult
    ) -> ZoneLineage:
        if transition.transition_type is not TransitionType.CREATED:
            raise ValueError("scientific compiler accepts only CREATED transitions")
        record = result.lineage_registry.get(transition.zone_id)
        if not isinstance(record, ZoneRecord):
            raise TypeError("CREATED transition has no exact lineage-registry record")
        zone = record.lineage
        candidates = result.candidates_by_timeframe.get(zone.source_timeframe, ())
        if not any(
            self._candidate_matches(zone, candidate) for candidate in candidates
        ):
            raise ValueError(
                "CREATED lineage has no exact current-step kernel candidate"
            )
        return zone

    def _new_episode(self, zone: ZoneLineage) -> _Episode:
        if self._latest_result is None:
            raise RuntimeError("scientific episode requires a consumed replay result")
        spec = self.target_specs[zone.source_timeframe]
        reference = self._window_for(
            zone.asset,
            spec.source_timeframe,
            zone.available_at,
            spec.reference_lookback + 1,
        )
        kernel_window = self._kernel_window(zone)
        active = tuple(
            record.lineage
            for record in self._latest_result.state.active_lineages
            if record.lineage.asset == zone.asset
        )
        feasible_null = build_feasible_random_price_null(
            zone,
            kernel_bars=kernel_window,
            active_zones=active,
            seed=self.null_seed,
        )
        return _Episode(
            zone=zone,
            group=ScientificGroupKey(
                asset=zone.asset,
                timeframe=zone.source_timeframe,
                kernel_id=zone.kernel_id,
                kernel_version=zone.kernel_version,
                side=zone.side,
            ),
            target_spec=spec,
            reference_bars=reference,
            feasible_null=feasible_null,
        )

    def _label_episode(
        self, episode: _Episode
    ) -> tuple[ScientificTargetResult, ScientificTargetResult | None]:
        actual = label_scientific_target(
            episode.zone,
            issued_at=episode.zone.available_at,
            future_bars=tuple(episode.future_bars),
            target_spec=episode.target_spec,
            reference_bars=episode.reference_bars,
        )
        if episode.feasible_null.zone is None:
            return actual, None
        null = label_scientific_target(
            episode.feasible_null.zone,
            issued_at=episode.zone.available_at,
            future_bars=tuple(episode.future_bars),
            target_spec=episode.target_spec,
            reference_bars=episode.reference_bars,
        )
        return actual, null

    @staticmethod
    def _target_ready(target: ScientificTargetResult) -> bool:
        return target.complete or target.reaction is not None

    def _maybe_compile(self, episode: _Episode, *, force: bool) -> None:
        actual, null_target = self._label_episode(episode)
        if not force and not (
            self._target_ready(actual)
            and (null_target is None or self._target_ready(null_target))
        ):
            return
        self._compiled[episode.zone.zone_id] = ScientificObservation(
            observation_id=episode.zone.zone_id,
            group=episode.group,
            zone=episode.zone,
            target=actual,
            feasible_null=episode.feasible_null,
            null_target=null_target,
            source_manifest_id=self.source_manifest_id,
            source_sha256=self.source_sha256,
            target_fingerprint=scientific_target_fingerprint(episode.target_spec),
            null_fingerprint=canonical_hash(episode.feasible_null.provenance),
        )
        self._episodes.pop(episode.zone.zone_id, None)

    def consume(self, result: SRStepResult, trigger_bar: SRBar) -> None:
        """Consume one eligible structural step and its exact trigger candle."""

        if not isinstance(result, SRStepResult) or not isinstance(trigger_bar, SRBar):
            raise TypeError("scientific callback requires SRStepResult and SRBar")
        if trigger_bar.timeframe != self.model_config.trigger_timeframe:
            raise ValueError(
                "research callback bar is not the resolved trigger timeframe"
            )
        if trigger_bar.bar_close_at != result.market_as_of:
            raise ValueError("research callback bar does not match structural cutoff")
        if result.config_fingerprint != self.model_config.config_fingerprint:
            raise ValueError("research callback config fingerprint differs")
        if result.asset not in self.assets:
            raise ValueError(
                "research callback asset is outside the authenticated source set"
            )
        if set(result.source_cutoffs) != set(self.model_config.ladder):
            raise ValueError(
                "research callback source cutoffs do not cover the resolved ladder"
            )
        step_key = (result.asset, result.market_as_of)
        if step_key in self._seen_steps:
            raise ValueError("duplicate scientific replay callback cutoff")
        self._seen_steps.add(step_key)
        self._latest_result = result
        for episode in tuple(self._episodes.values()):
            if (
                episode.zone.asset != result.asset
                or trigger_bar.bar_open_at < episode.zone.available_at
            ):
                continue
            if episode.last_future_cutoff == trigger_bar.bar_close_at:
                raise ValueError("duplicate trigger candle in scientific episode")
            episode.future_bars.append(trigger_bar)
            episode.last_future_cutoff = trigger_bar.bar_close_at
            self._maybe_compile(episode, force=False)
        created = sorted(
            (
                transition
                for transition in result.transitions
                if transition.transition_type is TransitionType.CREATED
            ),
            key=lambda item: (item.ordinal, item.zone_id),
        )
        for transition in created:
            if transition.event_at > result.market_as_of:
                raise ValueError(
                    "CREATED transition is after the current replay cutoff"
                )
            zone = self._created_zone(transition, result)
            if (
                zone.zone_id not in self._episodes
                and zone.zone_id not in self._compiled
            ):
                self._episodes[zone.zone_id] = self._new_episode(zone)

    def finalize(self, *, knowledge_cutoff: datetime) -> CompiledScientificSet:
        """Emit all open episodes using the frozen incomplete-window rule."""

        require_utc(knowledge_cutoff, field_name="knowledge_cutoff")
        if not self._seen_steps:
            raise ValueError("cannot finalize without consumed eligible replay cutoffs")
        consumed = {cutoff for _, cutoff in self._seen_steps}
        if knowledge_cutoff not in consumed or max(consumed) != knowledge_cutoff:
            raise ValueError(
                "knowledge_cutoff must equal the latest consumed trigger cutoff"
            )
        pending_count = len(self._episodes)
        for episode in tuple(self._episodes.values()):
            self._maybe_compile(episode, force=True)
        if self._episodes:
            raise ValueError("scientific finalization left uncompiled episodes")
        return CompiledScientificSet(
            source_manifest_id=self.source_manifest_id,
            source_sha256=self.source_sha256,
            expected_groups=self.expected_groups,
            observations=tuple(self._compiled.values()),
            compiler_fingerprint=self.compiler_fingerprint,
            knowledge_cutoff=knowledge_cutoff,
            finalized_incomplete_count=pending_count,
        )

    def compile(
        self,
        replay: SRV2ResearchReplay,
        *,
        bars_by_timeframe: Mapping[str, Sequence[SRBar | SourceBarRecord]]
        | None = None,
        **run_kwargs: Any,
    ) -> CompiledScientificSet:
        """Run one authenticated replay lane with this compiler callback."""

        if not isinstance(replay, SRV2ResearchReplay):
            raise TypeError("replay must be SRV2ResearchReplay")
        if replay.config.config_fingerprint != self.model_config.config_fingerprint:
            raise ValueError(
                "replay config fingerprint differs from compiler model config"
            )
        if len(self.assets) != 1:
            raise ValueError(
                "compile accepts one replay lane; consume panel lanes separately"
            )
        dataset = (
            self._sources[self.assets[0]]
            if bars_by_timeframe is None
            else bars_by_timeframe
        )
        if self.source_manifest is not None:
            if "source_manifest" in run_kwargs:
                raise ValueError("source_manifest is owned by the compiler")
            run_kwargs["source_manifest"] = self.source_manifest
        trace = replay.run(dataset, research_callback=self.consume, **run_kwargs)
        return self.finalize(knowledge_cutoff=trace.knowledge_cutoff)


__all__ = [
    "CompiledScientificSet",
    "ScientificGroupKey",
    "ScientificObservation",
    "ScientificObservationCompiler",
]
