"""Sealed development configuration, target identification, and geometry ranking.

This module is deliberately a small research boundary.  It resolves one
explicit development contract, compiles a finite family before any evaluation,
and ranks already-produced evidence.  It does not load market data, run a
replay, or expose a promotion outcome.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from ..config.resolver import (
    ResolvedSRV2Config,
    SRV2ConfigError,
    SRV2ConfigResolver,
    load_sr_v2_yaml,
)
from ..config.schema import (
    MAX_HORIZONS,
    TIMEFRAME_DURATIONS,
    duration,
    validate_ladder,
)
from ..contracts import ZoneSide, require_utc
from ..domain.identity import canonical_hash, canonical_json
from ..features.time import grid_for
from ..forecast.targets import (
    ResolvedTargetSpec,
    ScientificReaction,
    scientific_target_fingerprint,
)
from ..research_lab.episode_evidence import (
    CommonRiskReceipt,
    TargetCompilerReceipt,
    TargetOutcomeRow,
    target_family_fingerprint_from_choices,
)
from ..research_lab.scientific_compiler import (
    CompiledScientificSet,
    ScientificGroupKey,
)
from .observations import canonical_issuance_calendar_block
from .placebos import FEASIBLE_RANDOM_PRICE_ID

OPTIMIZER_SCHEMA = "sr_v2.sealed_global_finite_choices@1"
SAMPLER_ID = "sealed_global_finite_choices@1"
TARGET_SELECTION_POLICY = "first_feasible@1"
GEOMETRY_RANKING_POLICY_ID = "worst_tf_kernel_side_then_equal_cell@2"
STREAMING_TARGET_DIAGNOSTIC_SCHEMA = "sr_v2.streaming_target_diagnostic@1"
ALPHA_FAMILIES = frozenset({"bonferroni@1", "none@1"})

_SOURCE_KEYS = {
    "venue",
    "assets",
    "ladder",
    "start",
    "end",
    "acquisition_policy",
    "source_mode",
    "cache_root",
}
_SPLIT_KEYS = {"target_design", "geometry_train", "geometry_validation", "embargo"}
_WINDOW_KEYS = {"start", "end"}
_TARGET_KEYS = {
    "tuples",
    "minimum_observation_coverage",
    "minimum_unique_issuance_cutoffs",
    "minimum_joint_utc_blocks",
    "minimum_uncensored_lineages",
    "minimum_touch_class_lineages",
    "minimum_reaction_class_lineages",
    "maximum_censoring_rate",
    "maximum_unresolved_reaction_rate",
    "maximum_ambiguity_rate",
    "maximum_null_unavailable_rate",
    "selection_policy_id",
}
_TARGET_TUPLE_KEYS = {"source_horizon_bars", "reference_lookback", "barrier_multiplier"}
_SEARCH_KEYS = {
    "sampler_id",
    "seed",
    "trial_budget",
    "baseline_structural_yaml",
    "parameters",
}
_INFERENCE_KEYS = {
    "joint_utc_block",
    "epoch",
    "repetitions",
    "confidence",
    "alpha_family",
    "degradation_margin",
    "minimum_cell_support",
    "minimum_asset_support",
}
_RESOURCE_KEYS = {"max_workers", "receipt_dir"}
_APPROVED_PARAMETER_NAMES = {
    "previous_period_anchor@1": frozenset({"atr_period", "zone_half_width_atr"}),
    "plateau_sweep_reclaim@1": frozenset(
        {
            "atr_period",
            "lookback_bars",
            "minimum_plateau_touches",
            "equality_tolerance_atr",
            "minimum_sweep_atr",
            "zone_half_width_atr",
        }
    ),
}


def _require_exact(
    mapping: Mapping[str, Any],
    required: set[str],
    name: str,
    *,
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    unknown = sorted(set(mapping) - allowed)
    missing = sorted(required - set(mapping))
    if unknown:
        raise SRV2ConfigError(f"unknown {name} keys: {', '.join(unknown)}")
    if missing:
        raise SRV2ConfigError(f"missing {name} keys: {', '.join(missing)}")


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SRV2ConfigError(f"{name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise SRV2ConfigError(f"{name} keys must be strings")
    return value


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SRV2ConfigError(f"{name} must be a non-empty string")
    return value.strip()


def _utc(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise SRV2ConfigError(f"{name} must be an ISO-8601 UTC datetime")
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError as exc:
            raise SRV2ConfigError(f"{name} must be an ISO-8601 UTC datetime") from exc
    else:
        raise SRV2ConfigError(f"{name} must be an ISO-8601 UTC datetime")
    try:
        return require_utc(result, field_name=name)
    except (TypeError, ValueError) as exc:
        raise SRV2ConfigError(f"{name} must be timezone-aware UTC") from exc


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SRV2ConfigError(f"{name} must be a positive integer")
    return value


def _finite_decimal(value: object, name: str, *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise SRV2ConfigError(f"{name} must be a finite decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SRV2ConfigError(f"{name} must be a finite decimal") from exc
    if not result.is_finite() or (result < 0 if allow_zero else result <= 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise SRV2ConfigError(f"{name} must be finite and {qualifier}")
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _sequence_digest_update(digest: Any, value: Any) -> None:
    encoded = canonical_json(value).encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


@dataclass(frozen=True, slots=True, kw_only=True)
class OptimizerWindow:
    """One closed UTC development window."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = _utc(self.start, "window.start")
        end = _utc(self.end, "window.end")
        if end <= start:
            raise SRV2ConfigError("window.end must follow window.start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


@dataclass(frozen=True, slots=True, kw_only=True)
class OptimizerSource:
    venue: str
    assets: Mapping[str, str]
    ladder: tuple[str, ...]
    start: datetime
    end: datetime
    acquisition_policy: str
    source_mode: str
    cache_root: str

    def __post_init__(self) -> None:
        venue = _nonempty_string(self.venue, "source.venue")
        if venue != "binance_usdm":
            raise SRV2ConfigError("source.venue must be binance_usdm")
        if not isinstance(self.assets, Mapping) or not self.assets:
            raise SRV2ConfigError("source.assets must contain at least one asset")
        if any(
            not isinstance(asset, str)
            or not asset.strip()
            or not isinstance(instrument, str)
            or not instrument.strip()
            for asset, instrument in self.assets.items()
        ):
            raise SRV2ConfigError(
                "source.assets must map non-empty asset and instrument strings"
            )
        if len(set(self.assets)) != len(self.assets):
            raise SRV2ConfigError("source.assets must contain unique assets")
        ladder = validate_ladder(tuple(self.ladder), "source.ladder")
        start = _utc(self.start, "source.start")
        end = _utc(self.end, "source.end")
        if end <= start:
            raise SRV2ConfigError("source.end must follow source.start")
        for timeframe in ladder:
            grid = grid_for(timeframe)
            grid.validate_bar(start, start + TIMEFRAME_DURATIONS[timeframe])
            grid.validate_bar(end - TIMEFRAME_DURATIONS[timeframe], end)
        mode = _nonempty_string(self.source_mode, "source.source_mode").upper()
        if mode not in {"CACHE_ONLY", "BINANCE_USDM"}:
            raise SRV2ConfigError("source.source_mode is unsupported")
        object.__setattr__(self, "venue", venue)
        object.__setattr__(
            self, "assets", MappingProxyType(dict(sorted(self.assets.items())))
        )
        object.__setattr__(self, "ladder", ladder)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(
            self,
            "acquisition_policy",
            _nonempty_string(self.acquisition_policy, "source.acquisition_policy"),
        )
        object.__setattr__(self, "source_mode", mode)
        object.__setattr__(
            self, "cache_root", _nonempty_string(self.cache_root, "source.cache_root")
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OptimizerSplits:
    target_design: OptimizerWindow
    geometry_train: OptimizerWindow
    geometry_validation: OptimizerWindow
    embargo: timedelta
    maximum_horizon: timedelta

    def __post_init__(self) -> None:
        windows = (self.target_design, self.geometry_train, self.geometry_validation)
        if any(not isinstance(window, OptimizerWindow) for window in windows):
            raise TypeError("splits must contain OptimizerWindow values")
        if not isinstance(self.embargo, timedelta) or self.embargo <= timedelta(0):
            raise SRV2ConfigError("splits.embargo must be positive")
        if self.embargo < self.maximum_horizon:
            raise SRV2ConfigError(
                "splits.embargo must cover the largest target horizon"
            )
        if self.target_design.end + self.embargo > self.geometry_train.start:
            raise SRV2ConfigError(
                "target-design and geometry-train windows overlap embargo"
            )
        if self.geometry_train.end + self.embargo > self.geometry_validation.start:
            raise SRV2ConfigError(
                "geometry-train and geometry-validation windows overlap embargo"
            )

    def purge_intervals(
        self, intervals: Sequence[tuple[datetime, datetime]]
    ) -> tuple[tuple[datetime, datetime], ...]:
        """Retain only intervals wholly inside one non-embargoed split."""

        windows = (self.target_design, self.geometry_train, self.geometry_validation)
        result: list[tuple[datetime, datetime]] = []
        for interval in intervals:
            if not isinstance(interval, tuple) or len(interval) != 2:
                raise ValueError("lineage intervals must be (start, end) tuples")
            start = _utc(interval[0], "lineage.start")
            end = _utc(interval[1], "lineage.end")
            if end <= start:
                raise ValueError("lineage interval must be positive")
            if (
                sum(window.start <= start and end <= window.end for window in windows)
                == 1
            ):
                result.append((start, end))
        return tuple(result)


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetTuple:
    source_horizon_bars: int
    reference_lookback: int
    barrier_multiplier: Decimal

    def __post_init__(self) -> None:
        horizon = _positive_int(
            self.source_horizon_bars, "target tuple source_horizon_bars"
        )
        if horizon > MAX_HORIZONS:
            raise SRV2ConfigError(
                f"target tuple source_horizon_bars must be <= {MAX_HORIZONS}"
            )
        lookback = _positive_int(
            self.reference_lookback, "target tuple reference_lookback"
        )
        barrier = _finite_decimal(
            self.barrier_multiplier, "target tuple barrier_multiplier"
        )
        object.__setattr__(self, "source_horizon_bars", horizon)
        object.__setattr__(self, "reference_lookback", lookback)
        object.__setattr__(self, "barrier_multiplier", barrier)


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetIdentificationConfig:
    tuples: tuple[TargetTuple, ...]
    minimum_observation_coverage: float
    minimum_unique_issuance_cutoffs: int
    minimum_joint_utc_blocks: int
    minimum_uncensored_lineages: int
    minimum_touch_class_lineages: int
    minimum_reaction_class_lineages: int
    maximum_censoring_rate: float
    maximum_unresolved_reaction_rate: float
    maximum_ambiguity_rate: float
    maximum_null_unavailable_rate: float
    selection_policy_id: str

    def __post_init__(self) -> None:
        values = tuple(self.tuples)
        if not values or any(not isinstance(item, TargetTuple) for item in values):
            raise SRV2ConfigError(
                "target_identification.tuples must be non-empty TargetTuple values"
            )
        if len(set(values)) != len(values):
            raise SRV2ConfigError(
                "target_identification.tuples must contain unique choices"
            )
        for name in (
            "minimum_unique_issuance_cutoffs",
            "minimum_joint_utc_blocks",
            "minimum_uncensored_lineages",
            "minimum_touch_class_lineages",
            "minimum_reaction_class_lineages",
        ):
            _positive_int(getattr(self, name), f"target_identification.{name}")
        for name in (
            "minimum_observation_coverage",
            "maximum_censoring_rate",
            "maximum_unresolved_reaction_rate",
            "maximum_ambiguity_rate",
            "maximum_null_unavailable_rate",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 1
            ):
                raise SRV2ConfigError(
                    f"target_identification.{name} must be finite in [0, 1]"
                )
        policy = _nonempty_string(
            self.selection_policy_id, "target_identification.selection_policy_id"
        )
        if policy != TARGET_SELECTION_POLICY:
            raise SRV2ConfigError(f"unsupported target selection policy: {policy}")
        object.__setattr__(self, "tuples", values)
        object.__setattr__(self, "selection_policy_id", policy)


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchConfig:
    sampler_id: str
    seed: str
    trial_budget: int
    baseline_structural_yaml: str
    baseline_structural_yaml_sha256: str
    parameter_choices: Mapping[str, Mapping[str, tuple[Any, ...]]]
    baseline_config: ResolvedSRV2Config

    def __post_init__(self) -> None:
        sampler = _nonempty_string(self.sampler_id, "search.sampler_id")
        if sampler != SAMPLER_ID:
            raise SRV2ConfigError(f"unsupported search.sampler_id: {sampler}")
        seed = _nonempty_string(self.seed, "search.seed")
        budget = _positive_int(self.trial_budget, "search.trial_budget")
        baseline_sha = _nonempty_string(
            self.baseline_structural_yaml_sha256,
            "search.baseline_structural_yaml_sha256",
        )
        if len(baseline_sha) != 64:
            raise SRV2ConfigError(
                "search.baseline_structural_yaml_sha256 must be SHA-256"
            )
        try:
            int(baseline_sha, 16)
        except ValueError as exc:
            raise SRV2ConfigError(
                "search.baseline_structural_yaml_sha256 must be hexadecimal"
            ) from exc
        if not isinstance(self.baseline_config, ResolvedSRV2Config):
            raise TypeError("search.baseline_config must be ResolvedSRV2Config")
        if not isinstance(self.parameter_choices, Mapping):
            raise SRV2ConfigError("search.parameters must be a mapping")
        normalized: dict[str, Mapping[str, tuple[Any, ...]]] = {}
        selected = {kernel.identifier for kernel in self.baseline_config.kernels}
        for kernel_id, raw_parameters in self.parameter_choices.items():
            if kernel_id not in selected or kernel_id not in _APPROVED_PARAMETER_NAMES:
                raise SRV2ConfigError(
                    f"search.parameters contains unsupported kernel: {kernel_id}"
                )
            if not isinstance(raw_parameters, Mapping) or not raw_parameters:
                raise SRV2ConfigError(
                    f"search.parameters.{kernel_id} must be a non-empty mapping"
                )
            names = set(raw_parameters)
            unsupported = sorted(names - _APPROVED_PARAMETER_NAMES[kernel_id])
            if unsupported:
                raise SRV2ConfigError(
                    f"search.parameters.{kernel_id} contains unsupported parameters: {', '.join(unsupported)}"
                )
            values: dict[str, tuple[Any, ...]] = {}
            for name, raw_values in raw_parameters.items():
                if (
                    isinstance(raw_values, (str, bytes))
                    or not isinstance(raw_values, (list, tuple))
                    or not raw_values
                ):
                    raise SRV2ConfigError(
                        f"search.parameters.{kernel_id}.{name} must be a non-empty finite list"
                    )
                choices = tuple(raw_values)
                if any(isinstance(item, (Mapping, list, tuple)) for item in choices):
                    raise SRV2ConfigError(
                        f"search.parameters.{kernel_id}.{name} accepts scalar choices only"
                    )
                canonical_values = tuple(
                    sorted(
                        (
                            _normalize_parameter_choice(kernel_id, name, item)
                            for item in choices
                        ),
                        key=canonical_json,
                    )
                )
                if len({canonical_json(item) for item in canonical_values}) != len(
                    canonical_values
                ):
                    raise SRV2ConfigError(
                        f"search.parameters.{kernel_id}.{name} must contain unique choices"
                    )
                values[name] = canonical_values
            normalized[kernel_id] = MappingProxyType(
                {name: values[name] for name in sorted(values)}
            )
        object.__setattr__(self, "sampler_id", sampler)
        object.__setattr__(self, "seed", seed)
        object.__setattr__(self, "trial_budget", budget)
        object.__setattr__(
            self,
            "baseline_structural_yaml",
            _nonempty_string(
                self.baseline_structural_yaml, "search.baseline_structural_yaml"
            ),
        )
        object.__setattr__(self, "baseline_structural_yaml_sha256", baseline_sha)
        object.__setattr__(
            self,
            "parameter_choices",
            MappingProxyType({key: normalized[key] for key in sorted(normalized)}),
        )


def _normalize_parameter_choice(kernel_id: str, name: str, value: Any) -> Any:
    if name in {"atr_period", "lookback_bars", "minimum_plateau_touches"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SRV2ConfigError(
                f"search parameter {kernel_id}.{name} must use integer choices"
            )
        return value
    return _finite_decimal(value, f"search parameter {kernel_id}.{name}")


@dataclass(frozen=True, slots=True, kw_only=True)
class InferenceConfig:
    joint_utc_block: timedelta
    epoch: datetime
    repetitions: int
    confidence: float
    alpha_family: str
    degradation_margin: Decimal
    minimum_cell_support: int
    minimum_asset_support: int

    def __post_init__(self) -> None:
        if not isinstance(
            self.joint_utc_block, timedelta
        ) or self.joint_utc_block <= timedelta(0):
            raise SRV2ConfigError("inference.joint_utc_block must be positive")
        require_utc(self.epoch, field_name="inference.epoch")
        _positive_int(self.repetitions, "inference.repetitions")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0 < float(self.confidence) < 1
        ):
            raise SRV2ConfigError(
                "inference.confidence must be finite and strictly between zero and one"
            )
        family = _nonempty_string(self.alpha_family, "inference.alpha_family")
        if family not in ALPHA_FAMILIES:
            raise SRV2ConfigError(f"unsupported inference.alpha_family: {family}")
        margin = _finite_decimal(
            self.degradation_margin, "inference.degradation_margin", allow_zero=True
        )
        _positive_int(self.minimum_cell_support, "inference.minimum_cell_support")
        _positive_int(self.minimum_asset_support, "inference.minimum_asset_support")
        object.__setattr__(self, "epoch", _utc(self.epoch, "inference.epoch"))
        object.__setattr__(self, "alpha_family", family)
        object.__setattr__(self, "degradation_margin", margin)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceConfig:
    max_workers: int
    receipt_dir: str

    def __post_init__(self) -> None:
        _positive_int(self.max_workers, "resources.max_workers")
        directory = _nonempty_string(self.receipt_dir, "resources.receipt_dir")
        object.__setattr__(self, "receipt_dir", directory)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedOptimizerConfig:
    schema: str
    source: OptimizerSource
    splits: OptimizerSplits
    target_identification: TargetIdentificationConfig
    search: SearchConfig
    inference: InferenceConfig
    resources: ResourceConfig
    config_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema != OPTIMIZER_SCHEMA:
            raise SRV2ConfigError(f"unsupported optimizer schema: {self.schema}")
        if not isinstance(self.source, OptimizerSource):
            raise TypeError("source must be OptimizerSource")
        if not isinstance(self.splits, OptimizerSplits):
            raise TypeError("splits must be OptimizerSplits")
        if not isinstance(self.target_identification, TargetIdentificationConfig):
            raise TypeError("target_identification must be TargetIdentificationConfig")
        if not isinstance(self.search, SearchConfig):
            raise TypeError("search must be SearchConfig")
        if not isinstance(self.inference, InferenceConfig):
            raise TypeError("inference must be InferenceConfig")
        if not isinstance(self.resources, ResourceConfig):
            raise TypeError("resources must be ResourceConfig")
        if self.inference.joint_utc_block < self.splits.maximum_horizon:
            raise SRV2ConfigError(
                "inference.joint_utc_block must cover the largest target horizon"
            )
        if self.search.baseline_config.ladder != self.source.ladder:
            raise SRV2ConfigError("baseline structural ladder must equal source ladder")
        if self.search.baseline_config.trigger_timeframe != self.source.ladder[-1]:
            raise SRV2ConfigError(
                "baseline trigger must be the finest source timeframe"
            )
        if self.resources.max_workers > len(self.source.assets):
            raise SRV2ConfigError("resources.max_workers cannot exceed asset count")
        if self.inference.minimum_asset_support > len(self.source.assets):
            raise SRV2ConfigError(
                "inference.minimum_asset_support cannot exceed asset count"
            )
        object.__setattr__(
            self,
            "config_fingerprint",
            _nonempty_string(self.config_fingerprint, "optimizer.config_fingerprint"),
        )

    @property
    def baseline_config(self) -> ResolvedSRV2Config:
        return self.search.baseline_config

    @property
    def maximum_horizon(self) -> timedelta:
        return self.splits.maximum_horizon


class TargetIdentificationStatus(str, Enum):
    TARGET_IDENTIFIED = "TARGET_IDENTIFIED"
    TARGET_NOT_IDENTIFIED = "TARGET_NOT_IDENTIFIED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True, kw_only=True)
class FixtureTargetIdentificationInput:
    compiled_by_tuple: Mapping[TargetTuple, CompiledScientificSet]
    source_manifest_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.compiled_by_tuple, Mapping):
            raise TypeError("compiled_by_tuple must be a mapping")
        if any(
            not isinstance(key, TargetTuple)
            or not isinstance(value, CompiledScientificSet)
            for key, value in self.compiled_by_tuple.items()
        ):
            raise TypeError(
                "compiled_by_tuple must map TargetTuple to CompiledScientificSet"
            )
        for name in ("source_manifest_id", "source_sha256"):
            _nonempty_string(getattr(self, name), f"target input {name}")
        object.__setattr__(
            self, "compiled_by_tuple", MappingProxyType(dict(self.compiled_by_tuple))
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetGroupDiagnostic:
    """Per-group target classes and quality rates used by tuple gates.

    Actual quality rates use every actual observation as their denominator.
    Null quality rates use only observations with an available feasible null.
    A zero-sized denominator is represented as a failing rate of ``1.0`` and
    is separately rejected by the availability/class gates.  Unresolved
    reaction counts are touched episodes with neither an eligible bounce or
    break nor ambiguity; ambiguous episodes are not double counted.
    """

    target_tuple: TargetTuple
    group: ScientificGroupKey
    observation_count: int
    issuance_cutoffs: tuple[datetime, ...]
    actual_available_count: int
    null_available_count: int
    uncensored_count: int
    touched_count: int
    untouched_count: int
    censored_count: int
    unresolved_count: int
    actual_touch_count: int
    null_touch_count: int
    bounce_count: int
    break_count: int
    null_untouched_count: int
    null_censored_count: int
    null_unresolved_count: int
    null_bounce_count: int
    null_break_count: int
    null_censored_reaction_count: int
    null_ambiguous_reaction_count: int
    censored_reaction_count: int
    ambiguous_reaction_count: int
    observation_coverage: float
    null_unavailable_rate: float
    actual_censoring_rate: float
    null_censoring_rate: float
    actual_unresolved_reaction_rate: float
    null_unresolved_reaction_rate: float
    actual_ambiguity_rate: float
    null_ambiguity_rate: float
    target_fingerprint: str
    compiler_fingerprint: str
    source_manifest_id: str
    source_sha256: str
    diagnostic_fingerprint: str
    unique_issuance_cutoffs: tuple[datetime, ...] = ()
    joint_utc_blocks: tuple[str, ...] = ()
    cluster_multiplicity: tuple[tuple[str, int], ...] = ()
    issuance_cutoff_count: int = 0
    issuance_cutoff_digest: str = ""
    unique_issuance_cutoff_count: int = 0
    unique_issuance_cutoff_digest: str = ""
    joint_utc_block_count: int = 0
    joint_utc_block_digest: str = ""
    cluster_count: int = 0
    cluster_multiplicity_digest: str = ""


class TargetTupleStatus(str, Enum):
    FEASIBLE = "FEASIBLE"
    INSUFFICIENT = "INSUFFICIENT"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetTupleDiagnostic:
    target_tuple: TargetTuple
    status: TargetTupleStatus
    groups: tuple[TargetGroupDiagnostic, ...]
    reason: str | None
    tuple_fingerprint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetIdentificationReport:
    status: TargetIdentificationStatus
    selected_tuple: TargetTuple | None
    tuple_diagnostics: tuple[TargetTupleDiagnostic, ...]
    report_fingerprint: str


def _target_identification(config: Any) -> TargetIdentificationConfig:
    """Return the target gates for either approved target config shape."""

    value = getattr(config, "target_identification", None)
    if isinstance(value, TargetIdentificationConfig):
        return value
    value = getattr(config, "identifiability", None)
    if isinstance(value, TargetIdentificationConfig):
        return value
    raise TypeError("config does not expose typed target identifiability")


def _target_baseline(config: Any) -> ResolvedSRV2Config:
    """Return the authenticated comparator used for target group ontology."""

    value = getattr(config, "baseline_config", None)
    if isinstance(value, ResolvedSRV2Config):
        return value
    value = getattr(config, "comparator_config", None)
    if isinstance(value, ResolvedSRV2Config):
        return value
    raise TypeError(
        "strict target streaming requires an authenticated comparator_config"
    )


def _target_streaming_config(config: Any) -> Any:
    if isinstance(config, ResolvedOptimizerConfig):
        return config
    if (
        getattr(config, "schema", None) == "sr_v2.development_target_design@1"
        and isinstance(getattr(config, "source", None), OptimizerSource)
        and isinstance(
            getattr(config, "identifiability", None), TargetIdentificationConfig
        )
        and isinstance(getattr(config, "comparator_config", None), ResolvedSRV2Config)
    ):
        return config
    raise TypeError(
        "config must be ResolvedOptimizerConfig or an authenticated target-design config"
    )


def _target_spec_for(
    config: Any, target_tuple: TargetTuple, source_timeframe: str
) -> ResolvedTargetSpec:
    baseline = _target_baseline(config)
    observation_timeframe = baseline.trigger_timeframe
    observation_duration = baseline.trigger_duration
    if not isinstance(config, ResolvedOptimizerConfig):
        observation_timeframe = config.horizon.observation_timeframe
        observation_duration = TIMEFRAME_DURATIONS[observation_timeframe]
    return ResolvedTargetSpec(
        source_timeframe=source_timeframe,
        source_horizon_bars=target_tuple.source_horizon_bars,
        reference_lookback=target_tuple.reference_lookback,
        barrier_multiplier=target_tuple.barrier_multiplier,
        observation_timeframe=observation_timeframe,
        observation_duration=observation_duration,
    )


def _validate_strict_target_window(
    config: Any, target_tuple: TargetTuple, row: TargetOutcomeRow
) -> None:
    """Keep strict target observations wholly inside their authorized split."""

    if getattr(config, "schema", None) != "sr_v2.development_target_design@1":
        return
    window = getattr(config, "target_design_window", None)
    if window is None:
        raise TypeError("strict target-design config lacks target_design_window")
    horizon = _target_spec_for(config, target_tuple, row.group.timeframe).horizon
    if row.issuance_cutoff < window.start or row.issuance_cutoff + horizon > window.end:
        raise ValueError("target outcome issuance is outside target-design window")


def _target_family_fingerprint_for_config(
    config: Any,
) -> str:
    """Derive the expected family identity from the ordered YAML tuples."""

    return target_family_fingerprint_from_choices(
        tuple(
            (
                _target_choice_id_for_tuple(target_tuple),
                tuple(
                    (
                        timeframe,
                        scientific_target_fingerprint(
                            _target_spec_for(config, target_tuple, timeframe)
                        ),
                    )
                    for timeframe in sorted(config.source.ladder)
                ),
            )
            for target_tuple in _target_identification(config).tuples
        )
    )


def _expected_groups(config: Any) -> tuple[ScientificGroupKey, ...]:
    baseline = _target_baseline(config)
    return tuple(
        sorted(
            ScientificGroupKey(
                asset=asset,
                timeframe=timeframe,
                kernel_id=kernel.kernel_id,
                kernel_version=kernel.kernel_version,
                side=side,
            )
            for asset in config.source.assets
            for timeframe in config.source.ladder
            for kernel in baseline.kernels
            if kernel.enabled_for(timeframe)
            for side in ZoneSide
        )
    )


def _diagnostic_for(
    config: ResolvedOptimizerConfig,
    target_tuple: TargetTuple,
    group: ScientificGroupKey,
    compiled: CompiledScientificSet,
    observations: Sequence[Any],
) -> TargetGroupDiagnostic:
    spec = _target_spec_for(config, target_tuple, group.timeframe)
    expected_target = scientific_target_fingerprint(spec)
    cutoffs = tuple(sorted(observation.issued_at for observation in observations))
    unique_cutoffs = tuple(sorted(set(cutoffs)))
    joint_blocks = tuple(
        sorted(
            {
                canonical_issuance_calendar_block(
                    observation.issued_at,
                    block=config.inference.joint_utc_block,
                    epoch=config.inference.epoch,
                )
                for observation in observations
            }
        )
    )
    cluster_counts: dict[str, int] = {}
    for observation in observations:
        zone = getattr(observation, "zone", None)
        cluster = canonical_hash(
            {
                "issued_at": observation.issued_at,
                "side": group.side,
                "center": None if zone is None else zone.center,
                "lower": None if zone is None else zone.lower,
                "upper": None if zone is None else zone.upper,
            }
        )
        cluster_counts[cluster] = cluster_counts.get(cluster, 0) + 1
    cluster_multiplicity = tuple(sorted(cluster_counts.items()))

    def outcome_available(target: Any) -> bool:
        complete = getattr(target, "complete", None)
        if complete is None:
            # Legacy diagnostic fixtures predate the explicit completion bit.
            # Their null availability is established by the feasible-null
            # receipt itself; retain that boundary while using the scientific
            # early-reaction rule for typed targets.
            return True
        return bool(
            complete
            or (
                target.view.reaction is not None
                and target.view.reaction_eligible
                and not target.censored
            )
        )

    actual_available = sum(
        1 for observation in observations if outcome_available(observation.target)
    )
    available_nulls = tuple(
        observation
        for observation in observations
        if observation.feasible_null.complete
        and observation.feasible_null.zone is not None
        and observation.null_target is not None
        and outcome_available(observation.null_target)
    )
    null_available = len(available_nulls)
    uncensored = sum(
        1
        for observation in observations
        if observation.target.view.touch is not None and not observation.target.censored
    )
    touched = sum(
        1
        for observation in observations
        if observation.target.view.touch is True and not observation.target.censored
    )
    untouched = sum(
        1
        for observation in observations
        if observation.target.view.touch is False and not observation.target.censored
    )
    censored = sum(1 for observation in observations if observation.target.censored)
    unresolved = sum(
        1
        for observation in observations
        if observation.target.view.touch is True
        and observation.target.view.reaction is None
        and not observation.target.view.ambiguous
        and not observation.target.view.reaction_eligible
    )
    actual_touch = touched
    null_touch = sum(
        1
        for observation in available_nulls
        if observation.null_target.view.touch is True
        and not observation.null_target.censored
    )
    null_untouched = sum(
        1
        for observation in available_nulls
        if observation.null_target.view.touch is False
        and not observation.null_target.censored
    )
    null_censored = sum(
        1 for observation in available_nulls if observation.null_target.censored
    )
    null_unresolved = sum(
        1
        for observation in available_nulls
        if observation.null_target.view.touch is True
        and observation.null_target.view.reaction is None
        and not observation.null_target.view.ambiguous
        and not observation.null_target.view.reaction_eligible
    )
    bounce = sum(
        1
        for observation in observations
        if observation.target.view.reaction is ScientificReaction.BOUNCE
        and observation.target.view.reaction_eligible
    )
    breaks = sum(
        1
        for observation in observations
        if observation.target.view.reaction is ScientificReaction.BREAK
        and observation.target.view.reaction_eligible
    )
    null_bounce = sum(
        1
        for observation in available_nulls
        if observation.null_target.view.reaction is ScientificReaction.BOUNCE
        and observation.null_target.view.reaction_eligible
    )
    null_break = sum(
        1
        for observation in available_nulls
        if observation.null_target.view.reaction is ScientificReaction.BREAK
        and observation.null_target.view.reaction_eligible
    )
    censored_reaction = sum(
        1
        for observation in observations
        if observation.target.view.touch is True
        and (
            observation.target.censored or not observation.target.view.reaction_eligible
        )
    )
    ambiguous = sum(
        1 for observation in observations if observation.target.view.ambiguous
    )
    null_censored_reaction = sum(
        1
        for observation in available_nulls
        if observation.null_target.view.touch is True
        and (
            observation.null_target.censored
            or not observation.null_target.view.reaction_eligible
        )
    )
    null_ambiguous = sum(
        1 for observation in available_nulls if observation.null_target.view.ambiguous
    )
    count = len(observations)
    coverage = actual_available / count if count else 0.0
    null_rate = 1.0 - null_available / count if count else 1.0
    actual_censoring_rate = censored / count if count else 1.0
    null_censoring_rate = null_censored / null_available if null_available else 1.0
    actual_unresolved_reaction_rate = unresolved / count if count else 1.0
    null_unresolved_reaction_rate = (
        null_unresolved / null_available if null_available else 1.0
    )
    actual_ambiguity_rate = ambiguous / count if count else 1.0
    null_ambiguity_rate = null_ambiguous / null_available if null_available else 1.0
    compiler_fingerprint = compiled.compiler_fingerprint
    diagnostic_fingerprint = canonical_hash(
        {
            "target_tuple": target_tuple,
            "group": group,
            "observation_ids": tuple(
                sorted(observation.observation_id for observation in observations)
            ),
            "counts": {
                "observation": count,
                "actual_available": actual_available,
                "null_available": null_available,
                "uncensored": uncensored,
                "touched": touched,
                "untouched": untouched,
                "censored": censored,
                "unresolved": unresolved,
                "actual_touch": actual_touch,
                "null_touch": null_touch,
                "bounce": bounce,
                "break": breaks,
                "null_untouched": null_untouched,
                "null_censored": null_censored,
                "null_unresolved": null_unresolved,
                "null_bounce": null_bounce,
                "null_break": null_break,
                "null_censored_reaction": null_censored_reaction,
                "null_ambiguous_reaction": null_ambiguous,
                "censored_reaction": censored_reaction,
                "ambiguous": ambiguous,
                "actual_censoring_rate": actual_censoring_rate,
                "null_censoring_rate": null_censoring_rate,
                "actual_unresolved_reaction_rate": actual_unresolved_reaction_rate,
                "null_unresolved_reaction_rate": null_unresolved_reaction_rate,
                "actual_ambiguity_rate": actual_ambiguity_rate,
                "null_ambiguity_rate": null_ambiguity_rate,
                "unique_issuance_cutoffs": unique_cutoffs,
                "joint_utc_blocks": joint_blocks,
                "cluster_multiplicity": cluster_multiplicity,
            },
            "target_fingerprint": expected_target,
            "compiler_fingerprint": compiler_fingerprint,
            "source_manifest_id": compiled.source_manifest_id,
            "source_sha256": compiled.source_sha256,
        }
    )
    return TargetGroupDiagnostic(
        target_tuple=target_tuple,
        group=group,
        observation_count=count,
        issuance_cutoffs=cutoffs,
        actual_available_count=actual_available,
        null_available_count=null_available,
        uncensored_count=uncensored,
        touched_count=touched,
        untouched_count=untouched,
        censored_count=censored,
        unresolved_count=unresolved,
        actual_touch_count=actual_touch,
        null_touch_count=null_touch,
        bounce_count=bounce,
        break_count=breaks,
        null_untouched_count=null_untouched,
        null_censored_count=null_censored,
        null_unresolved_count=null_unresolved,
        null_bounce_count=null_bounce,
        null_break_count=null_break,
        null_censored_reaction_count=null_censored_reaction,
        null_ambiguous_reaction_count=null_ambiguous,
        censored_reaction_count=censored_reaction,
        ambiguous_reaction_count=ambiguous,
        observation_coverage=coverage,
        null_unavailable_rate=null_rate,
        actual_censoring_rate=actual_censoring_rate,
        null_censoring_rate=null_censoring_rate,
        actual_unresolved_reaction_rate=actual_unresolved_reaction_rate,
        null_unresolved_reaction_rate=null_unresolved_reaction_rate,
        actual_ambiguity_rate=actual_ambiguity_rate,
        null_ambiguity_rate=null_ambiguity_rate,
        target_fingerprint=expected_target,
        compiler_fingerprint=compiler_fingerprint,
        source_manifest_id=compiled.source_manifest_id,
        source_sha256=compiled.source_sha256,
        diagnostic_fingerprint=diagnostic_fingerprint,
        unique_issuance_cutoffs=unique_cutoffs,
        joint_utc_blocks=joint_blocks,
        cluster_multiplicity=cluster_multiplicity,
    )


def _diagnostic_unique_cutoff_count(diagnostic: TargetGroupDiagnostic) -> int:
    return (
        diagnostic.unique_issuance_cutoff_count
        if diagnostic.unique_issuance_cutoff_count or diagnostic.issuance_cutoff_count
        else len(diagnostic.unique_issuance_cutoffs)
    )


def _diagnostic_joint_block_count(diagnostic: TargetGroupDiagnostic) -> int:
    return (
        diagnostic.joint_utc_block_count
        if diagnostic.joint_utc_block_count or diagnostic.issuance_cutoff_count
        else len(diagnostic.joint_utc_blocks)
    )


def _evaluate_target_tuple(
    config: ResolvedOptimizerConfig,
    target_tuple: TargetTuple,
    compiled: CompiledScientificSet,
    *,
    source_manifest_id: str,
    source_sha256: str,
) -> tuple[TargetTupleDiagnostic, bool]:
    expected_groups = _expected_groups(config)
    reasons: list[str] = []
    if (
        compiled.source_manifest_id != source_manifest_id
        or compiled.source_sha256 != source_sha256
    ):
        reasons.append("compiled source identity differs from target input")
    if tuple(compiled.expected_groups) != expected_groups:
        reasons.append(
            "compiled expected group ontology differs from resolved source/model ontology"
        )
    if compiled.missing_groups or any(
        observation.group not in expected_groups
        for observation in compiled.observations
    ):
        reasons.append(
            "compiled observation groups do not cover the exact expected ontology"
        )
    by_group: dict[ScientificGroupKey, list[Any]] = {
        group: [] for group in expected_groups
    }
    for observation in compiled.observations:
        if observation.group in by_group:
            by_group[observation.group].append(observation)
        if (
            observation.source_manifest_id != source_manifest_id
            or observation.source_sha256 != source_sha256
        ):
            reasons.append(
                f"observation source identity mismatch: {observation.observation_id}"
            )
        expected_spec = _target_spec_for(
            config, target_tuple, observation.group.timeframe
        )
        if observation.target_fingerprint != scientific_target_fingerprint(
            expected_spec
        ):
            reasons.append(f"target fingerprint mismatch: {observation.observation_id}")
    groups = tuple(
        _diagnostic_for(
            config,
            target_tuple,
            group,
            compiled,
            tuple(sorted(values, key=lambda item: item.observation_id)),
        )
        for group, values in by_group.items()
    )
    gate_failures: list[str] = []
    for diagnostic in groups:
        if diagnostic.observation_count == 0:
            gate_failures.append(f"{diagnostic.group.key}: no observations")
        if (
            _diagnostic_unique_cutoff_count(diagnostic)
            < config.target_identification.minimum_unique_issuance_cutoffs
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: unique issuance-cutoff support below gate"
            )
        if (
            _diagnostic_joint_block_count(diagnostic)
            < config.target_identification.minimum_joint_utc_blocks
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: joint UTC-block support below gate"
            )
        if (
            diagnostic.observation_coverage
            < config.target_identification.minimum_observation_coverage
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: observation coverage below gate"
            )
        if (
            diagnostic.uncensored_count
            < config.target_identification.minimum_uncensored_lineages
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: uncensored support below gate"
            )
        if (
            diagnostic.touched_count
            < config.target_identification.minimum_touch_class_lineages
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: actual touched class below gate"
            )
        if (
            diagnostic.untouched_count
            < config.target_identification.minimum_touch_class_lineages
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: actual untouched class below gate"
            )
        if (
            diagnostic.null_touch_count
            < config.target_identification.minimum_touch_class_lineages
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: null touched class below gate"
            )
        if (
            diagnostic.null_untouched_count
            < config.target_identification.minimum_touch_class_lineages
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: null untouched class below gate"
            )
        if (
            diagnostic.bounce_count
            < config.target_identification.minimum_reaction_class_lineages
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: actual bounce class below gate"
            )
        if (
            diagnostic.break_count
            < config.target_identification.minimum_reaction_class_lineages
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: actual break class below gate"
            )
        if (
            diagnostic.null_bounce_count
            < config.target_identification.minimum_reaction_class_lineages
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: null bounce class below gate"
            )
        if (
            diagnostic.null_break_count
            < config.target_identification.minimum_reaction_class_lineages
        ):
            gate_failures.append(f"{diagnostic.group.key}: null break class below gate")
        if (
            diagnostic.actual_censoring_rate
            > config.target_identification.maximum_censoring_rate
        ):
            gate_failures.append(f"{diagnostic.group.key}: actual censoring above gate")
        if (
            diagnostic.null_censoring_rate
            > config.target_identification.maximum_censoring_rate
        ):
            gate_failures.append(f"{diagnostic.group.key}: null censoring above gate")
        if (
            diagnostic.actual_unresolved_reaction_rate
            > config.target_identification.maximum_unresolved_reaction_rate
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: actual unresolved reaction above gate"
            )
        if (
            diagnostic.null_unresolved_reaction_rate
            > config.target_identification.maximum_unresolved_reaction_rate
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: null unresolved reaction above gate"
            )
        if (
            diagnostic.actual_ambiguity_rate
            > config.target_identification.maximum_ambiguity_rate
        ):
            gate_failures.append(f"{diagnostic.group.key}: actual ambiguity above gate")
        if (
            diagnostic.null_ambiguity_rate
            > config.target_identification.maximum_ambiguity_rate
        ):
            gate_failures.append(f"{diagnostic.group.key}: null ambiguity above gate")
        if (
            diagnostic.null_unavailable_rate
            > config.target_identification.maximum_null_unavailable_rate
        ):
            gate_failures.append(
                f"{diagnostic.group.key}: null availability below gate"
            )
        if diagnostic.null_available_count == 0:
            gate_failures.append(
                f"{diagnostic.group.key}: no available null observations"
            )
    if reasons:
        status = TargetTupleStatus.INVALID
        reason = "; ".join(sorted(set(reasons)))
    elif gate_failures:
        status = TargetTupleStatus.INSUFFICIENT
        reason = "; ".join(sorted(set(gate_failures)))
    else:
        status = TargetTupleStatus.FEASIBLE
        reason = None
    diagnostic = TargetTupleDiagnostic(
        target_tuple=target_tuple,
        status=status,
        groups=groups,
        reason=reason,
        tuple_fingerprint=canonical_hash(
            {
                "target_tuple": target_tuple,
                "groups": groups,
                "status": status.value,
                "reason": reason,
            }
        ),
    )
    return diagnostic, bool(reasons)


def _target_report(
    diagnostics: Sequence[TargetTupleDiagnostic],
    *,
    input_invalid: bool,
    identity_invalid: bool,
    invalid_reasons: Sequence[str] = (),
) -> TargetIdentificationReport:
    invalid_reason_values = tuple(sorted(set(invalid_reasons)))
    if not (identity_invalid or input_invalid):
        selected = next(
            (
                diagnostic.target_tuple
                for diagnostic in diagnostics
                if diagnostic.status is TargetTupleStatus.FEASIBLE
            ),
            None,
        )
        if selected is not None:
            status = TargetIdentificationStatus.TARGET_IDENTIFIED
            return TargetIdentificationReport(
                status=status,
                selected_tuple=selected,
                tuple_diagnostics=tuple(diagnostics),
                report_fingerprint=canonical_hash(
                    {
                        "status": status.value,
                        "selected": selected,
                        "diagnostics": diagnostics,
                        **(
                            {"invalid_reasons": invalid_reason_values}
                            if invalid_reason_values
                            else {}
                        ),
                    }
                ),
            )
    status = (
        TargetIdentificationStatus.INVALID
        if identity_invalid or input_invalid
        else TargetIdentificationStatus.TARGET_NOT_IDENTIFIED
    )
    return TargetIdentificationReport(
        status=status,
        selected_tuple=None,
        tuple_diagnostics=tuple(diagnostics),
        report_fingerprint=canonical_hash(
            {
                "status": status.value,
                "diagnostics": diagnostics,
                **(
                    {"invalid_reasons": invalid_reason_values}
                    if invalid_reason_values
                    else {}
                ),
            }
        ),
    )


def identify_target_from_compiled_fixture(
    config: ResolvedOptimizerConfig, target_input: FixtureTargetIdentificationInput
) -> TargetIdentificationReport:
    """Select the first YAML-ordered target tuple passing every group gate."""

    if not isinstance(config, ResolvedOptimizerConfig):
        raise TypeError("config must be ResolvedOptimizerConfig")
    if not isinstance(target_input, FixtureTargetIdentificationInput):
        raise TypeError("target_input must be FixtureTargetIdentificationInput")
    expected = tuple(config.target_identification.tuples)
    configured_tuples = set(expected)
    supplied_tuples = set(target_input.compiled_by_tuple)
    diagnostics: list[TargetTupleDiagnostic] = [
        TargetTupleDiagnostic(
            target_tuple=target_tuple,
            status=TargetTupleStatus.INVALID,
            groups=(),
            reason="compiled input contains an unexpected target tuple",
            tuple_fingerprint=canonical_hash(
                {"target_tuple": target_tuple, "reason": "unexpected"}
            ),
        )
        for target_tuple in sorted(
            supplied_tuples - configured_tuples, key=canonical_json
        )
    ]
    input_invalid = supplied_tuples != configured_tuples
    identity_invalid = False
    for target_tuple in expected:
        compiled = target_input.compiled_by_tuple.get(target_tuple)
        if compiled is None:
            diagnostics.append(
                TargetTupleDiagnostic(
                    target_tuple=target_tuple,
                    status=TargetTupleStatus.INVALID,
                    groups=(),
                    reason="compiled scientific set is missing for target tuple",
                    tuple_fingerprint=canonical_hash(
                        {"tuple": target_tuple, "reason": "missing"}
                    ),
                )
            )
            identity_invalid = True
            input_invalid = True
            continue
        diagnostic, tuple_identity_invalid = _evaluate_target_tuple(
            config,
            target_tuple,
            compiled,
            source_manifest_id=target_input.source_manifest_id,
            source_sha256=target_input.source_sha256,
        )
        diagnostics.append(diagnostic)
        identity_invalid |= tuple_identity_invalid
        input_invalid |= tuple_identity_invalid
    return _target_report(
        diagnostics,
        input_invalid=input_invalid,
        identity_invalid=identity_invalid,
    )


class _StreamingGroupState:
    __slots__ = (
        "actual_available_count",
        "actual_touch_count",
        "ambiguous_reaction_count",
        "bounce_count",
        "break_count",
        "censored_count",
        "censored_reaction_count",
        "cluster_count",
        "cluster_cutoff",
        "cluster_digest",
        "clusters",
        "compiler_fingerprint",
        "issuance_cutoff_count",
        "issuance_cutoff_digest",
        "joint_utc_block_count",
        "joint_utc_block_digest",
        "last_joint_utc_block",
        "last_unique_cutoff",
        "null_ambiguous_reaction_count",
        "null_available_count",
        "null_bounce_count",
        "null_break_count",
        "null_censored_count",
        "null_censored_reaction_count",
        "null_touch_count",
        "null_unresolved_count",
        "null_untouched_count",
        "observation_count",
        "source_manifest_id",
        "source_sha256",
        "touched_count",
        "uncensored_count",
        "unique_issuance_cutoff_count",
        "unique_issuance_cutoff_digest",
        "unresolved_count",
        "untouched_count",
    )

    def __init__(self) -> None:
        self.observation_count = 0
        self.issuance_cutoff_count = 0
        self.issuance_cutoff_digest = hashlib.sha256()
        self.unique_issuance_cutoff_count = 0
        self.unique_issuance_cutoff_digest = hashlib.sha256()
        self.last_unique_cutoff: datetime | None = None
        self.joint_utc_block_count = 0
        self.joint_utc_block_digest = hashlib.sha256()
        self.last_joint_utc_block: str | None = None
        self.cluster_cutoff: datetime | None = None
        self.clusters: Counter[str] = Counter()
        self.cluster_count = 0
        self.cluster_digest = hashlib.sha256()
        for name in (
            "actual_available_count",
            "null_available_count",
            "uncensored_count",
            "touched_count",
            "untouched_count",
            "censored_count",
            "unresolved_count",
            "actual_touch_count",
            "null_touch_count",
            "bounce_count",
            "break_count",
            "null_untouched_count",
            "null_censored_count",
            "null_unresolved_count",
            "null_bounce_count",
            "null_break_count",
            "null_censored_reaction_count",
            "null_ambiguous_reaction_count",
            "censored_reaction_count",
            "ambiguous_reaction_count",
        ):
            setattr(self, name, 0)
        self.source_manifest_id = ""
        self.source_sha256 = ""
        self.compiler_fingerprint = ""

    @staticmethod
    def _available(outcome: Any) -> bool:
        return bool(
            outcome.complete
            or (
                outcome.reaction is not None
                and outcome.reaction_eligible
                and not outcome.censored
            )
        )

    @staticmethod
    def _unresolved(outcome: Any) -> bool:
        return bool(
            outcome.touch is True
            and outcome.reaction is None
            and not outcome.ambiguous
            and not outcome.reaction_eligible
        )

    def _flush_clusters(self) -> None:
        if self.cluster_cutoff is None:
            return
        payload = (self.cluster_cutoff, tuple(sorted(self.clusters.items())))
        _sequence_digest_update(self.cluster_digest, payload)
        self.cluster_count += len(self.clusters)
        self.cluster_cutoff = None
        self.clusters.clear()

    def consume(
        self,
        row: TargetOutcomeRow,
        *,
        block: str,
        compiler_receipt: TargetCompilerReceipt | None,
        source_manifest_id: str = "",
        source_sha256: str = "",
        compiler_fingerprint: str = "",
    ) -> None:
        if (
            self.cluster_cutoff is not None
            and row.issuance_cutoff < self.cluster_cutoff
        ):
            raise ValueError("target outcome rows are not ordered by issuance cutoff")
        if (
            self.cluster_cutoff is not None
            and row.issuance_cutoff != self.cluster_cutoff
        ):
            self._flush_clusters()
        self.cluster_cutoff = row.issuance_cutoff
        self.clusters[row.cluster_identity] += 1
        self.observation_count += 1
        self.issuance_cutoff_count += 1
        _sequence_digest_update(
            self.issuance_cutoff_digest,
            (row.observation_id, row.issuance_cutoff),
        )
        if self.last_unique_cutoff != row.issuance_cutoff:
            self.unique_issuance_cutoff_count += 1
            _sequence_digest_update(
                self.unique_issuance_cutoff_digest, row.issuance_cutoff
            )
            self.last_unique_cutoff = row.issuance_cutoff
        if self.last_joint_utc_block != block:
            self.joint_utc_block_count += 1
            _sequence_digest_update(self.joint_utc_block_digest, block)
            self.last_joint_utc_block = block
        actual = row.actual
        if self._available(actual):
            self.actual_available_count += 1
        if actual.touch is not None and not actual.censored:
            self.uncensored_count += 1
        if actual.touch is True and not actual.censored:
            self.touched_count += 1
            self.actual_touch_count += 1
        if actual.touch is False and not actual.censored:
            self.untouched_count += 1
        if actual.censored:
            self.censored_count += 1
        if self._unresolved(actual):
            self.unresolved_count += 1
        if actual.reaction is ScientificReaction.BOUNCE and actual.reaction_eligible:
            self.bounce_count += 1
        if actual.reaction is ScientificReaction.BREAK and actual.reaction_eligible:
            self.break_count += 1
        if actual.touch is True and (actual.censored or not actual.reaction_eligible):
            self.censored_reaction_count += 1
        if actual.ambiguous:
            self.ambiguous_reaction_count += 1
        if row.null_available:
            if row.null is None:
                raise ValueError("target outcome null availability is inconsistent")
            null = row.null
            self.null_available_count += 1
            if null.touch is True and not null.censored:
                self.null_touch_count += 1
            if null.touch is False and not null.censored:
                self.null_untouched_count += 1
            if null.censored:
                self.null_censored_count += 1
            if self._unresolved(null):
                self.null_unresolved_count += 1
            if null.reaction is ScientificReaction.BOUNCE and null.reaction_eligible:
                self.null_bounce_count += 1
            if null.reaction is ScientificReaction.BREAK and null.reaction_eligible:
                self.null_break_count += 1
            if null.touch is True and (null.censored or not null.reaction_eligible):
                self.null_censored_reaction_count += 1
            if null.ambiguous:
                self.null_ambiguous_reaction_count += 1
        if compiler_receipt is not None:
            values = (
                compiler_receipt.source_manifest_id,
                compiler_receipt.source_sha256,
                compiler_receipt.compiler_fingerprint,
            )
        elif source_manifest_id or source_sha256 or compiler_fingerprint:
            values = (source_manifest_id, source_sha256, compiler_fingerprint)
        else:
            values = None
        if values is not None:
            if (
                self.source_manifest_id
                and (
                    self.source_manifest_id,
                    self.source_sha256,
                    self.compiler_fingerprint,
                )
                != values
            ):
                raise ValueError("target outcome stream source identity differs")
            self.source_manifest_id, self.source_sha256, self.compiler_fingerprint = (
                values
            )

    def finish(self) -> None:
        self._flush_clusters()


class TargetDiagnosticAccumulator:
    """Fixed-size accumulator for one configured target choice."""

    __slots__ = (
        "_compiler_fingerprints",
        "_groups",
        "config",
        "target_tuple",
    )

    def __init__(
        self,
        config: Any,
        target_tuple: TargetTuple,
    ) -> None:
        _target_streaming_config(config)
        if not isinstance(target_tuple, TargetTuple):
            raise TypeError("target_tuple must be TargetTuple")
        self.config = config
        self.target_tuple = target_tuple
        self._groups = {
            group: _StreamingGroupState() for group in _expected_groups(config)
        }
        self._compiler_fingerprints: dict[ScientificGroupKey, str] = {}

    def consume(
        self,
        row: TargetOutcomeRow,
        *,
        compiler_receipt: TargetCompilerReceipt | None = None,
        source_manifest_id: str | None = None,
        source_sha256: str | None = None,
        compiler_fingerprint: str | None = None,
    ) -> None:
        if not isinstance(row, TargetOutcomeRow):
            raise TypeError("target diagnostic accumulator requires TargetOutcomeRow")
        state = self._groups.get(row.group)
        if state is None:
            raise ValueError("target outcome group is outside configured ontology")
        expected = scientific_target_fingerprint(
            _target_spec_for(self.config, self.target_tuple, row.group.timeframe)
        )
        if row.target_fingerprint != expected:
            raise ValueError("target outcome target fingerprint differs from tuple")
        _validate_strict_target_window(self.config, self.target_tuple, row)
        if compiler_receipt is not None:
            if not isinstance(compiler_receipt, TargetCompilerReceipt):
                raise TypeError("compiler_receipt must be TargetCompilerReceipt")
            if compiler_receipt.target_choice_id != _target_choice_id_for_tuple(
                self.target_tuple
            ):
                raise ValueError("target outcome compiler choice differs from tuple")
            expected_receipt_fingerprints = tuple(
                (
                    timeframe,
                    scientific_target_fingerprint(
                        _target_spec_for(self.config, self.target_tuple, timeframe)
                    ),
                )
                for timeframe in sorted(self.config.source.ladder)
            )
            if compiler_receipt.target_fingerprints != expected_receipt_fingerprints:
                raise ValueError("target outcome compiler fingerprints differ")
            if compiler_receipt.asset != row.group.asset:
                raise ValueError("target outcome compiler asset differs from group")
            source_manifest_id = compiler_receipt.source_manifest_id
            source_sha256 = compiler_receipt.source_sha256
            compiler_fingerprint = compiler_receipt.compiler_fingerprint
        source_manifest_id = "" if source_manifest_id is None else source_manifest_id
        source_sha256 = "" if source_sha256 is None else source_sha256
        compiler_fingerprint = (
            "" if compiler_fingerprint is None else compiler_fingerprint
        )
        block = canonical_issuance_calendar_block(
            row.issuance_cutoff,
            block=self.config.inference.joint_utc_block,
            epoch=self.config.inference.epoch,
        )
        state.consume(
            row,
            block=block,
            compiler_receipt=compiler_receipt,
            source_manifest_id=source_manifest_id,
            source_sha256=source_sha256,
            compiler_fingerprint=compiler_fingerprint,
        )
        if compiler_fingerprint:
            self._compiler_fingerprints[row.group] = compiler_fingerprint

    def _diagnostics(self) -> tuple[TargetGroupDiagnostic, ...]:
        diagnostics: list[TargetGroupDiagnostic] = []
        for group in _expected_groups(self.config):
            state = self._groups[group]
            state.finish()
            count = state.observation_count
            null_count = state.null_available_count
            spec = _target_spec_for(self.config, self.target_tuple, group.timeframe)
            target_fp = scientific_target_fingerprint(spec)
            compiler_fp = self._compiler_fingerprints.get(
                group, state.compiler_fingerprint
            )
            source_manifest = state.source_manifest_id
            source_sha = state.source_sha256
            diagnostic_fingerprint = canonical_hash(
                {
                    "schema": STREAMING_TARGET_DIAGNOSTIC_SCHEMA,
                    "target_tuple": self.target_tuple,
                    "group": group,
                    "observation_count": count,
                    "issuance_cutoff_count": state.issuance_cutoff_count,
                    "issuance_cutoff_digest": state.issuance_cutoff_digest.hexdigest(),
                    "unique_issuance_cutoff_count": state.unique_issuance_cutoff_count,
                    "unique_issuance_cutoff_digest": state.unique_issuance_cutoff_digest.hexdigest(),
                    "joint_utc_block_count": state.joint_utc_block_count,
                    "joint_utc_block_digest": state.joint_utc_block_digest.hexdigest(),
                    "cluster_count": state.cluster_count,
                    "cluster_multiplicity_digest": state.cluster_digest.hexdigest(),
                }
            )
            diagnostics.append(
                TargetGroupDiagnostic(
                    target_tuple=self.target_tuple,
                    group=group,
                    observation_count=count,
                    issuance_cutoffs=(),
                    actual_available_count=state.actual_available_count,
                    null_available_count=null_count,
                    uncensored_count=state.uncensored_count,
                    touched_count=state.touched_count,
                    untouched_count=state.untouched_count,
                    censored_count=state.censored_count,
                    unresolved_count=state.unresolved_count,
                    actual_touch_count=state.actual_touch_count,
                    null_touch_count=state.null_touch_count,
                    bounce_count=state.bounce_count,
                    break_count=state.break_count,
                    null_untouched_count=state.null_untouched_count,
                    null_censored_count=state.null_censored_count,
                    null_unresolved_count=state.null_unresolved_count,
                    null_bounce_count=state.null_bounce_count,
                    null_break_count=state.null_break_count,
                    null_censored_reaction_count=state.null_censored_reaction_count,
                    null_ambiguous_reaction_count=state.null_ambiguous_reaction_count,
                    censored_reaction_count=state.censored_reaction_count,
                    ambiguous_reaction_count=state.ambiguous_reaction_count,
                    observation_coverage=(
                        state.actual_available_count / count if count else 0.0
                    ),
                    null_unavailable_rate=(1.0 - null_count / count if count else 1.0),
                    actual_censoring_rate=(
                        state.censored_count / count if count else 1.0
                    ),
                    null_censoring_rate=(
                        state.null_censored_count / null_count if null_count else 1.0
                    ),
                    actual_unresolved_reaction_rate=(
                        state.unresolved_count / count if count else 1.0
                    ),
                    null_unresolved_reaction_rate=(
                        state.null_unresolved_count / null_count if null_count else 1.0
                    ),
                    actual_ambiguity_rate=(
                        state.ambiguous_reaction_count / count if count else 1.0
                    ),
                    null_ambiguity_rate=(
                        state.null_ambiguous_reaction_count / null_count
                        if null_count
                        else 1.0
                    ),
                    target_fingerprint=target_fp,
                    compiler_fingerprint=compiler_fp,
                    source_manifest_id=source_manifest,
                    source_sha256=source_sha,
                    diagnostic_fingerprint=diagnostic_fingerprint,
                    unique_issuance_cutoffs=(),
                    joint_utc_blocks=(),
                    cluster_multiplicity=(),
                    issuance_cutoff_count=state.issuance_cutoff_count,
                    issuance_cutoff_digest=state.issuance_cutoff_digest.hexdigest(),
                    unique_issuance_cutoff_count=state.unique_issuance_cutoff_count,
                    unique_issuance_cutoff_digest=state.unique_issuance_cutoff_digest.hexdigest(),
                    joint_utc_block_count=state.joint_utc_block_count,
                    joint_utc_block_digest=state.joint_utc_block_digest.hexdigest(),
                    cluster_count=state.cluster_count,
                    cluster_multiplicity_digest=state.cluster_digest.hexdigest(),
                )
            )
        return tuple(diagnostics)

    def finalize(self) -> TargetTupleDiagnostic:
        groups = self._diagnostics()
        failures: list[str] = []
        target = _target_identification(self.config)
        for diagnostic in groups:
            if diagnostic.observation_count == 0:
                failures.append(f"{diagnostic.group.key}: no observations")
            if (
                _diagnostic_unique_cutoff_count(diagnostic)
                < target.minimum_unique_issuance_cutoffs
            ):
                failures.append(
                    f"{diagnostic.group.key}: unique issuance-cutoff support below gate"
                )
            if (
                _diagnostic_joint_block_count(diagnostic)
                < target.minimum_joint_utc_blocks
            ):
                failures.append(
                    f"{diagnostic.group.key}: joint UTC-block support below gate"
                )
            if diagnostic.observation_coverage < target.minimum_observation_coverage:
                failures.append(
                    f"{diagnostic.group.key}: observation coverage below gate"
                )
            if diagnostic.uncensored_count < target.minimum_uncensored_lineages:
                failures.append(
                    f"{diagnostic.group.key}: uncensored support below gate"
                )
            if diagnostic.touched_count < target.minimum_touch_class_lineages:
                failures.append(
                    f"{diagnostic.group.key}: actual touched class below gate"
                )
            if diagnostic.untouched_count < target.minimum_touch_class_lineages:
                failures.append(
                    f"{diagnostic.group.key}: actual untouched class below gate"
                )
            if diagnostic.null_touch_count < target.minimum_touch_class_lineages:
                failures.append(
                    f"{diagnostic.group.key}: null touched class below gate"
                )
            if diagnostic.null_untouched_count < target.minimum_touch_class_lineages:
                failures.append(
                    f"{diagnostic.group.key}: null untouched class below gate"
                )
            if diagnostic.bounce_count < target.minimum_reaction_class_lineages:
                failures.append(
                    f"{diagnostic.group.key}: actual bounce class below gate"
                )
            if diagnostic.break_count < target.minimum_reaction_class_lineages:
                failures.append(
                    f"{diagnostic.group.key}: actual break class below gate"
                )
            if diagnostic.null_bounce_count < target.minimum_reaction_class_lineages:
                failures.append(f"{diagnostic.group.key}: null bounce class below gate")
            if diagnostic.null_break_count < target.minimum_reaction_class_lineages:
                failures.append(f"{diagnostic.group.key}: null break class below gate")
            if diagnostic.actual_censoring_rate > target.maximum_censoring_rate:
                failures.append(f"{diagnostic.group.key}: actual censoring above gate")
            if diagnostic.null_censoring_rate > target.maximum_censoring_rate:
                failures.append(f"{diagnostic.group.key}: null censoring above gate")
            if (
                diagnostic.actual_unresolved_reaction_rate
                > target.maximum_unresolved_reaction_rate
            ):
                failures.append(
                    f"{diagnostic.group.key}: actual unresolved reaction above gate"
                )
            if (
                diagnostic.null_unresolved_reaction_rate
                > target.maximum_unresolved_reaction_rate
            ):
                failures.append(
                    f"{diagnostic.group.key}: null unresolved reaction above gate"
                )
            if diagnostic.actual_ambiguity_rate > target.maximum_ambiguity_rate:
                failures.append(f"{diagnostic.group.key}: actual ambiguity above gate")
            if diagnostic.null_ambiguity_rate > target.maximum_ambiguity_rate:
                failures.append(f"{diagnostic.group.key}: null ambiguity above gate")
            if diagnostic.null_unavailable_rate > target.maximum_null_unavailable_rate:
                failures.append(f"{diagnostic.group.key}: null availability below gate")
            if diagnostic.null_available_count == 0:
                failures.append(
                    f"{diagnostic.group.key}: no available null observations"
                )
        status = (
            TargetTupleStatus.INSUFFICIENT if failures else TargetTupleStatus.FEASIBLE
        )
        reason = "; ".join(sorted(set(failures))) if failures else None
        return TargetTupleDiagnostic(
            target_tuple=self.target_tuple,
            status=status,
            groups=groups,
            reason=reason,
            tuple_fingerprint=canonical_hash(
                {
                    "schema": STREAMING_TARGET_DIAGNOSTIC_SCHEMA,
                    "target_tuple": self.target_tuple,
                    "groups": groups,
                    "status": status.value,
                    "reason": reason,
                }
            ),
        )


def _target_choice_id_for_tuple(target_tuple: TargetTuple) -> str:
    return canonical_hash(
        {"schema": "sr_v2.target_choice@1", "target_tuple": target_tuple}
    )


def _stream_entry_values(
    target_results: Any,
) -> tuple[
    tuple[
        str,
        CommonRiskReceipt,
        tuple[tuple[str, TargetCompilerReceipt, Iterable[TargetOutcomeRow]], ...],
    ],
    ...,
]:
    """Normalize the one canonical, ordered real streaming input shape."""

    if not isinstance(target_results, Mapping):
        raise TypeError(
            "streaming target results must map asset to common-risk choices"
        )
    entries: list[
        tuple[
            str,
            CommonRiskReceipt,
            tuple[tuple[str, TargetCompilerReceipt, Iterable[TargetOutcomeRow]], ...],
        ]
    ] = []
    for asset, value in target_results.items():
        if not isinstance(asset, str) or not asset.strip():
            raise TypeError("streaming target assets must be non-empty strings")
        if not isinstance(value, tuple) or len(value) != 2:
            raise TypeError(
                "streaming target asset must be (CommonRiskReceipt, choices)"
            )
        common_risk, choices = value
        if not isinstance(common_risk, CommonRiskReceipt):
            raise TypeError("streaming target asset requires CommonRiskReceipt")
        if not isinstance(choices, Mapping):
            raise TypeError("streaming target choices must be a mapping")
        choice_entries: list[
            tuple[str, TargetCompilerReceipt, Iterable[TargetOutcomeRow]]
        ] = []
        for choice_id, choice_value in choices.items():
            if not isinstance(choice_id, str) or not choice_id.strip():
                raise TypeError("streaming target choice IDs must be non-empty strings")
            if (
                not isinstance(choice_value, tuple)
                or len(choice_value) != 2
                or not isinstance(choice_value[0], TargetCompilerReceipt)
                or not isinstance(choice_value[1], Iterable)
            ):
                raise TypeError(
                    "streaming target choice must be (TargetCompilerReceipt, rows)"
                )
            choice_entries.append((choice_id, choice_value[0], choice_value[1]))
        entries.append((asset, common_risk, tuple(choice_entries)))
    return tuple(entries)


def _invalid_stream_report(
    config: Any,
    reason: str,
) -> TargetIdentificationReport:
    diagnostics = tuple(
        TargetTupleDiagnostic(
            target_tuple=target_tuple,
            status=TargetTupleStatus.INVALID,
            groups=(),
            reason=reason,
            tuple_fingerprint=canonical_hash(
                {"target_tuple": target_tuple, "reason": reason}
            ),
        )
        for target_tuple in _target_identification(config).tuples
    )
    return _target_report(
        diagnostics,
        input_invalid=True,
        identity_invalid=True,
        invalid_reasons=(reason,),
    )


def _stream_common_compiler_reasons(
    config: ResolvedOptimizerConfig,
    *,
    asset: str,
    target_tuple: TargetTuple | None,
    common_risk: CommonRiskReceipt,
    receipt: TargetCompilerReceipt,
) -> list[str]:
    reasons: list[str] = []
    expected_groups = tuple(
        group for group in _expected_groups(config) if group.asset == asset
    )
    expected_group_keys = tuple(sorted(group.key for group in expected_groups))
    if common_risk.target_family_fingerprint != _target_family_fingerprint_for_config(
        config
    ):
        reasons.append("streaming common-risk target-family fingerprint differs")
    if common_risk.asset != asset:
        reasons.append("streaming common-risk asset identity differs")
    if (
        tuple(key for key, _ in common_risk.expected_group_counts)
        != expected_group_keys
    ):
        reasons.append("streaming common-risk group ontology differs")
    if receipt.asset != asset:
        reasons.append("streaming target compiler asset identity differs")
    if (
        receipt.artifact_id != common_risk.artifact_id
        or receipt.source_manifest_id != common_risk.source_manifest_id
        or receipt.source_sha256 != common_risk.source_sha256
        or receipt.source_slice_fingerprint != common_risk.source_slice_fingerprint
    ):
        reasons.append("streaming compiler source identity differs from common risk")
    if receipt.common_risk_receipt_fingerprint != common_risk.receipt_fingerprint:
        reasons.append("streaming compiler common-risk fingerprint differs")
    if receipt.expected_row_count != common_risk.included_count:
        reasons.append("streaming compiler row count differs from common risk")
    if target_tuple is None:
        reasons.append("streaming target compiler choice is not configured")
    else:
        expected_choice_id = _target_choice_id_for_tuple(target_tuple)
        if receipt.target_choice_id != expected_choice_id:
            reasons.append("streaming target compiler choice differs")
        expected_fingerprints = tuple(
            (
                timeframe,
                scientific_target_fingerprint(
                    _target_spec_for(config, target_tuple, timeframe)
                ),
            )
            for timeframe in sorted(config.source.ladder)
        )
        if receipt.target_fingerprints != expected_fingerprints:
            reasons.append("streaming target compiler ontology differs")
    return reasons


def identify_target_streaming(
    config: Any,
    target_results: Any,
) -> TargetIdentificationReport:
    """Identify a target from authenticated, lazy outcome-row streams."""

    _target_streaming_config(config)
    try:
        entries = _stream_entry_values(target_results)
    except (TypeError, ValueError) as exc:
        return _invalid_stream_report(config, str(exc))
    expected_assets = tuple(config.source.assets)
    expected_tuples = tuple(_target_identification(config).tuples)
    expected_choice_ids = tuple(
        _target_choice_id_for_tuple(target_tuple) for target_tuple in expected_tuples
    )
    invalid_reasons: list[str] = []
    tuple_invalid_reasons: dict[TargetTuple, list[str]] = {
        target_tuple: [] for target_tuple in expected_tuples
    }
    supplied_assets = tuple(asset for asset, _, _ in entries)
    if supplied_assets != expected_assets:
        invalid_reasons.append("streaming target assets are not in configured order")
    if set(supplied_assets) != set(expected_assets):
        invalid_reasons.append(
            "streaming target results do not cover exact configured assets"
        )
        for missing_asset in sorted(set(expected_assets) - set(supplied_assets)):
            for target_tuple in expected_tuples:
                tuple_invalid_reasons[target_tuple].append(
                    f"streaming target results are missing asset {missing_asset}"
                )
    accumulators = {
        target_tuple: TargetDiagnosticAccumulator(config, target_tuple)
        for target_tuple in expected_tuples
    }
    for asset, common_risk, choices in entries:
        supplied_choice_ids = tuple(choice_id for choice_id, _, _ in choices)
        if supplied_choice_ids != expected_choice_ids:
            invalid_reasons.append(
                f"streaming target choices for {asset} are not in configured order"
            )
        missing_choice_ids = set(expected_choice_ids) - set(supplied_choice_ids)
        if missing_choice_ids:
            invalid_reasons.append(
                f"streaming target choices for {asset} are incomplete"
            )
            for target_tuple, choice_id in zip(
                expected_tuples, expected_choice_ids, strict=True
            ):
                if choice_id in missing_choice_ids:
                    tuple_invalid_reasons[target_tuple].append(
                        f"streaming target choice is missing for {asset}"
                    )
        if asset not in expected_assets:
            invalid_reasons.append(
                "streaming target results contain an unexpected asset"
            )
        expected_group_keys = {
            group.key for group in _expected_groups(config) if group.asset == asset
        }
        common_group_keys = {key for key, _ in common_risk.expected_group_counts}
        if common_group_keys != expected_group_keys:
            reason = f"streaming common-risk groups for {asset} differ from ontology"
            invalid_reasons.append(reason)
            for target_tuple in expected_tuples:
                tuple_invalid_reasons[target_tuple].append(reason)
        for choice_id, receipt, rows in choices:
            tuple_for_choice = next(
                (
                    target_tuple
                    for target_tuple in expected_tuples
                    if _target_choice_id_for_tuple(target_tuple) == choice_id
                ),
                None,
            )
            stream_reasons = _stream_common_compiler_reasons(
                config,
                asset=asset,
                target_tuple=tuple_for_choice,
                common_risk=common_risk,
                receipt=receipt,
            )
            if stream_reasons:
                invalid_reasons.extend(stream_reasons)
                if tuple_for_choice is not None:
                    tuple_invalid_reasons[tuple_for_choice].extend(stream_reasons)
            accumulator = (
                accumulators[tuple_for_choice]
                if tuple_for_choice is not None and asset in expected_assets
                else None
            )
            stream_count = 0
            stream_digest = hashlib.sha256()
            observation_digest = hashlib.sha256()
            included_group_digest = hashlib.sha256()
            group_counts: Counter[str] = Counter()
            stream_error: str | None = None
            try:
                for row in rows:
                    stream_count += 1
                    if not isinstance(row, TargetOutcomeRow):
                        stream_error = stream_error or (
                            "streaming target rows must be TargetOutcomeRow"
                        )
                        continue
                    _sequence_digest_update(stream_digest, row.to_mapping())
                    _sequence_digest_update(observation_digest, row.observation_id)
                    _sequence_digest_update(
                        included_group_digest, (row.observation_id, row.group.key)
                    )
                    group_counts[row.group.key] += 1
                    if row.group.asset != asset:
                        stream_error = stream_error or (
                            "streaming target row asset differs from stream"
                        )
                        continue
                    if accumulator is not None:
                        try:
                            accumulator.consume(row, compiler_receipt=receipt)
                        except (TypeError, ValueError) as exc:
                            stream_error = stream_error or str(exc)
            except (TypeError, ValueError) as exc:
                stream_error = stream_error or str(exc)
            if stream_error is not None:
                invalid_reasons.append(stream_error)
                if tuple_for_choice is not None:
                    tuple_invalid_reasons[tuple_for_choice].append(stream_error)
            if (
                stream_count != receipt.expected_row_count
                or stream_digest.hexdigest() != receipt.expected_row_sha256
            ):
                reason = "streaming target rows differ from compiler receipt"
                invalid_reasons.append(reason)
                if tuple_for_choice is not None:
                    tuple_invalid_reasons[tuple_for_choice].append(reason)
            if (
                stream_count != common_risk.included_count
                or observation_digest.hexdigest()
                != common_risk.included_observation_sha256
                or included_group_digest.hexdigest()
                != common_risk.included_group_sha256
                or set(group_counts)
                - {key for key, _ in common_risk.expected_group_counts}
                or tuple(
                    (
                        key,
                        group_counts.get(key, 0),
                    )
                    for key, _ in common_risk.expected_group_counts
                )
                != tuple(common_risk.expected_group_counts)
            ):
                reason = "streaming target rows differ from common-risk receipt"
                invalid_reasons.append(reason)
                if tuple_for_choice is not None:
                    tuple_invalid_reasons[tuple_for_choice].append(reason)
    diagnostics: list[TargetTupleDiagnostic] = []
    for target_tuple in expected_tuples:
        if tuple_invalid_reasons[target_tuple]:
            reason = "; ".join(sorted(set(tuple_invalid_reasons[target_tuple])))
            diagnostic = TargetTupleDiagnostic(
                target_tuple=target_tuple,
                status=TargetTupleStatus.INVALID,
                groups=(),
                reason=reason,
                tuple_fingerprint=canonical_hash(
                    {"tuple": target_tuple, "reason": reason}
                ),
            )
            diagnostics.append(diagnostic)
            continue
        try:
            diagnostic = accumulators[target_tuple].finalize()
        except (TypeError, ValueError) as exc:
            diagnostic = TargetTupleDiagnostic(
                target_tuple=target_tuple,
                status=TargetTupleStatus.INVALID,
                groups=(),
                reason=str(exc),
                tuple_fingerprint=canonical_hash(
                    {"tuple": target_tuple, "reason": str(exc)}
                ),
            )
        diagnostics.append(diagnostic)
    return _target_report(
        diagnostics,
        input_invalid=bool(invalid_reasons),
        identity_invalid=bool(invalid_reasons),
        invalid_reasons=invalid_reasons,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SealedCandidate:
    candidate_id: str
    ordinal: int
    resolved_config: ResolvedSRV2Config
    config_fingerprint: str
    baseline: bool
    assignment: Mapping[str, Mapping[str, Any]]
    family_hash: str
    selection_provenance: str

    def __post_init__(self) -> None:
        if not isinstance(self.resolved_config, ResolvedSRV2Config):
            raise TypeError("candidate resolved_config must be ResolvedSRV2Config")
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            raise ValueError("candidate ordinal must be non-negative")
        for name in (
            "candidate_id",
            "config_fingerprint",
            "family_hash",
            "selection_provenance",
        ):
            _nonempty_string(getattr(self, name), f"candidate.{name}")
        object.__setattr__(self, "assignment", _freeze(self.assignment))


@dataclass(frozen=True, slots=True, kw_only=True)
class SealedCandidateFamily:
    candidates: tuple[SealedCandidate, ...]
    family_hash: str
    sampler_id: str
    seed: str

    def __post_init__(self) -> None:
        values = tuple(self.candidates)
        if not values or any(not isinstance(item, SealedCandidate) for item in values):
            raise ValueError("candidate family must contain candidates")
        if values[0].ordinal != 0 or not values[0].baseline:
            raise ValueError("candidate family baseline must be ordinal zero")
        if sum(item.baseline for item in values) != 1:
            raise ValueError("candidate family must contain one baseline")
        if tuple(item.ordinal for item in values) != tuple(range(len(values))):
            raise ValueError("candidate ordinals must be contiguous")
        if len({item.candidate_id for item in values}) != len(values):
            raise ValueError("candidate IDs must be unique")
        if any(item.family_hash != self.family_hash for item in values):
            raise ValueError("candidate receipt family hash mismatch")
        object.__setattr__(self, "candidates", values)

    @property
    def baseline(self) -> SealedCandidate:
        return self.candidates[0]


def _assignment_combinations(
    search: SearchConfig,
) -> tuple[Mapping[str, Mapping[str, Any]], ...]:
    dimensions: list[tuple[str, str, tuple[Any, ...]]] = []
    for kernel_id in sorted(search.parameter_choices):
        for parameter in sorted(search.parameter_choices[kernel_id]):
            dimensions.append(
                (kernel_id, parameter, search.parameter_choices[kernel_id][parameter])
            )
    if not dimensions:
        return ({},)
    result: list[Mapping[str, Mapping[str, Any]]] = []
    for values in itertools.product(*(item[2] for item in dimensions)):
        assignment: dict[str, dict[str, Any]] = {}
        for (kernel_id, parameter, _), value in zip(dimensions, values, strict=True):
            assignment.setdefault(kernel_id, {})[parameter] = value
        result.append(assignment)
    return tuple(result)


def _candidate_raw(
    baseline: ResolvedSRV2Config, assignment: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any]:
    raw = baseline.to_mapping()
    # ``to_mapping`` retains the resolved kernel order for identity/reporting;
    # the strict YAML resolver accepts that order from the mapping itself.
    raw["runtime"].pop("selected_kernel_order", None)
    for kernel_id, parameters in assignment.items():
        kernel = next(item for item in baseline.kernels if item.identifier == kernel_id)
        for timeframe in baseline.ladder:
            if not kernel.enabled_for(timeframe):
                continue
            lane = raw["kernels"][kernel_id]["timeframes"][timeframe]
            lane.update(parameters)
    return raw


def _candidate_invariants(
    baseline: ResolvedSRV2Config, candidate: ResolvedSRV2Config
) -> None:
    if (
        candidate.ladder != baseline.ladder
        or candidate.trigger_timeframe != baseline.trigger_timeframe
    ):
        raise SRV2ConfigError("sealed candidate changed baseline ladder or trigger")
    if tuple(item.identifier for item in candidate.kernels) != tuple(
        item.identifier for item in baseline.kernels
    ):
        raise SRV2ConfigError("sealed candidate changed baseline kernel order")
    if (
        candidate.expiry != baseline.expiry
        or candidate.break_buffer_atr != baseline.break_buffer_atr
        or candidate.break_confirmation_bars != baseline.break_confirmation_bars
    ):
        raise SRV2ConfigError("sealed candidate changed lifecycle settings")
    if (
        candidate.max_active_lineages != baseline.max_active_lineages
        or candidate.max_terminal_tombstones != baseline.max_terminal_tombstones
    ):
        raise SRV2ConfigError("sealed candidate changed state bounds")
    for before, after in zip(baseline.kernels, candidate.kernels, strict=True):
        for timeframe in baseline.ladder:
            if before.enabled_for(timeframe) != after.enabled_for(timeframe):
                raise SRV2ConfigError("sealed candidate changed kernel enabled flags")


def _compile_candidate_family(
    baseline: ResolvedSRV2Config, search: SearchConfig
) -> SealedCandidateFamily:
    """Compile one finite family from an already-resolved baseline and search."""

    if not isinstance(baseline, ResolvedSRV2Config):
        raise TypeError("baseline must be ResolvedSRV2Config")
    if not isinstance(search, SearchConfig):
        raise TypeError("search must be SearchConfig")
    baseline_id = canonical_hash(
        {"schema": "sr_v2.sealed_candidate@1", "baseline": baseline.config_fingerprint}
    )
    valid: dict[str, tuple[Mapping[str, Mapping[str, Any]], ResolvedSRV2Config]] = {}
    for assignment in _assignment_combinations(search):
        try:
            raw = _candidate_raw(baseline, assignment)
            resolved = SRV2ConfigResolver(raw).resolve()
            _candidate_invariants(baseline, resolved)
        except ValueError:
            # A finite choice may be individually well-formed but invalid in
            # combination (for example touches greater than lookback).  Skip
            # that deterministic assignment; it cannot affect another choice.
            continue
        valid.setdefault(resolved.config_fingerprint, (assignment, resolved))
    valid.pop(baseline.config_fingerprint, None)
    remaining = search.trial_budget - 1
    ordered: list[tuple[str, Mapping[str, Mapping[str, Any]], ResolvedSRV2Config]] = []
    for assignment, resolved in valid.values():
        digest = canonical_json(assignment)
        ordered.append((digest, assignment, resolved))
    if len(ordered) <= remaining:
        ordered.sort(key=lambda item: item[0])
        provenance = "exhaustive_canonical_order@1"
    else:
        ordered.sort(
            key=lambda item: hashlib.sha256(
                f"{search.sampler_id}|{search.seed}|{item[0]}".encode()
            ).hexdigest()
        )
        ordered = ordered[:remaining]
        provenance = "hash_truncated_order@1"
    selected: list[tuple[Mapping[str, Mapping[str, Any]], ResolvedSRV2Config, str]] = [
        ({}, baseline, "baseline@1")
    ]
    selected.extend(
        (assignment, resolved, provenance) for _, assignment, resolved in ordered
    )
    family_identity = {
        "schema": OPTIMIZER_SCHEMA,
        "sampler_id": search.sampler_id,
        "seed": search.seed,
        "trial_budget": search.trial_budget,
        "baseline_structural_yaml_sha256": (search.baseline_structural_yaml_sha256),
        "baseline": baseline.config_fingerprint,
        "candidates": tuple(resolved.config_fingerprint for _, resolved, _ in selected),
    }
    family_hash = canonical_hash(family_identity)
    receipts = tuple(
        SealedCandidate(
            candidate_id=(
                baseline_id
                if ordinal == 0
                else canonical_hash(
                    {
                        "schema": "sr_v2.sealed_candidate@1",
                        "config": resolved.config_fingerprint,
                    }
                )
            ),
            ordinal=ordinal,
            resolved_config=resolved,
            config_fingerprint=resolved.config_fingerprint,
            baseline=ordinal == 0,
            assignment=assignment,
            family_hash=family_hash,
            selection_provenance=provenance,
        )
        for ordinal, (assignment, resolved, provenance) in enumerate(selected)
    )
    return SealedCandidateFamily(
        candidates=receipts,
        family_hash=family_hash,
        sampler_id=search.sampler_id,
        seed=search.seed,
    )


def compile_sealed_candidate_family(
    config: ResolvedOptimizerConfig,
) -> SealedCandidateFamily:
    """Compile and seal every selected global candidate before evaluation."""

    if not isinstance(config, ResolvedOptimizerConfig):
        raise TypeError("config must be ResolvedOptimizerConfig")
    return _compile_candidate_family(config.baseline_config, config.search)


def compile_global_candidate_family(config: Any) -> SealedCandidateFamily:
    """Seal the same finite family for the strict global development config.

    The function intentionally depends only on the already-resolved baseline
    and nested finite choices.  Keeping it here avoids an optimizer-to-schema
    import cycle while preserving one canonical compiler implementation.
    """

    if isinstance(config, ResolvedOptimizerConfig):
        raise TypeError(
            "compile_global_candidate_family requires global geometry config"
        )
    if not (
        hasattr(config, "baseline_config")
        and hasattr(config, "search")
        and getattr(config, "schema", None) == "sr_v2.development_global_geometry@1"
    ):
        raise TypeError("config must be a resolved global geometry config")
    search = config.search
    legacy_search = SearchConfig(
        sampler_id=search.sampler_id,
        seed=search.seed,
        trial_budget=search.trial_budget,
        baseline_structural_yaml=search.baseline_structural_yaml,
        baseline_structural_yaml_sha256=search.baseline_structural_yaml_sha256,
        parameter_choices=search.parameters,
        baseline_config=config.baseline_config,
    )
    return _compile_candidate_family(config.baseline_config, legacy_search)


@dataclass(frozen=True, slots=True, kw_only=True)
class CutoffReactionEvidence:
    cutoff: datetime
    actual_bounce: int
    actual_break: int
    null_bounce: int
    null_break: int
    actual_probability_numerator: int | None = None
    actual_probability_denominator: int | None = None
    null_probability_numerator: int | None = None
    null_probability_denominator: int | None = None
    cutoff_weight: int = 1

    def __post_init__(self) -> None:
        require_utc(self.cutoff, field_name="cutoff")
        for name in ("actual_bounce", "actual_break", "null_bounce", "null_break"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.actual_bounce + self.actual_break <= 0:
            raise ValueError("cutoff actual reaction support must be positive")
        if self.null_bounce + self.null_break <= 0:
            raise ValueError("cutoff null reaction support must be positive")
        for numerator_name, denominator_name in (
            ("actual_probability_numerator", "actual_probability_denominator"),
            ("null_probability_numerator", "null_probability_denominator"),
        ):
            numerator = getattr(self, numerator_name)
            denominator = getattr(self, denominator_name)
            if (numerator is None) != (denominator is None):
                raise ValueError(
                    f"{numerator_name} and {denominator_name} must be supplied together"
                )
            if numerator is not None and (
                isinstance(numerator, bool)
                or not isinstance(numerator, int)
                or numerator < 0
                or isinstance(denominator, bool)
                or not isinstance(denominator, int)
                or denominator <= 0
                or numerator > denominator
            ):
                raise ValueError("cutoff probability fraction is malformed")
        if (
            isinstance(self.cutoff_weight, bool)
            or not isinstance(self.cutoff_weight, int)
            or self.cutoff_weight <= 0
        ):
            raise ValueError("cutoff_weight must be a positive integer")

    @property
    def actual_probability(self) -> float:
        if self.actual_probability_numerator is not None:
            return (
                self.actual_probability_numerator / self.actual_probability_denominator
            )
        return self.actual_bounce / (self.actual_bounce + self.actual_break)

    @property
    def null_probability(self) -> float:
        if self.null_probability_numerator is not None:
            return self.null_probability_numerator / self.null_probability_denominator
        return self.null_bounce / (self.null_bounce + self.null_break)

    @property
    def reaction_lift(self) -> float:
        return self.actual_probability - self.null_probability


@dataclass(frozen=True, slots=True, kw_only=True)
class GeometryCellEvidence:
    candidate_id: str
    group: ScientificGroupKey
    source_manifest_id: str
    source_sha256: str
    target_fingerprint: str
    compiler_fingerprint: str
    null_algorithm_id: str
    lineage_support: int
    cutoff_evidence: tuple[CutoffReactionEvidence, ...]
    touch_count: int = 0
    paired_reaction_lift_interval: tuple[float, float] | None = None
    source_slice_fingerprint: str = ""
    unique_cutoff_count: int = 0
    cluster_count: int = 0
    null_available_count: int = 0
    joint_utc_block_count: int = 0
    censored_count: int = 0
    ambiguous_count: int = 0
    unresolved_reaction_count: int = 0
    tombstone_pruned_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.group, ScientificGroupKey):
            raise TypeError("geometry cell group must be ScientificGroupKey")
        for name in (
            "candidate_id",
            "source_manifest_id",
            "source_sha256",
            "target_fingerprint",
            "compiler_fingerprint",
            "null_algorithm_id",
        ):
            _nonempty_string(getattr(self, name), f"geometry cell {name}")
        if self.source_slice_fingerprint:
            _nonempty_string(
                self.source_slice_fingerprint,
                "geometry cell source_slice_fingerprint",
            )
        for name in ("lineage_support", "touch_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"geometry cell {name} must be a non-negative integer")
        for name in (
            "unique_cutoff_count",
            "cluster_count",
            "null_available_count",
            "censored_count",
            "ambiguous_count",
            "unresolved_reaction_count",
            "tombstone_pruned_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"geometry cell {name} must be a non-negative integer")
        evidence = tuple(self.cutoff_evidence)
        if any(not isinstance(item, CutoffReactionEvidence) for item in evidence):
            raise ValueError("geometry cell cutoff_evidence must contain typed values")
        if len({item.cutoff for item in evidence}) != len(evidence):
            raise ValueError(
                "geometry cell cutoff evidence must contain unique cutoffs"
            )
        if self.paired_reaction_lift_interval is not None:
            if len(self.paired_reaction_lift_interval) != 2:
                raise ValueError(
                    "paired_reaction_lift_interval must contain lower and upper"
                )
            lower, upper = self.paired_reaction_lift_interval
            if (
                any(
                    isinstance(value, bool)
                    or not isinstance(value, (float, int))
                    or not math.isfinite(float(value))
                    for value in (lower, upper)
                )
                or lower > upper
            ):
                raise ValueError(
                    "paired_reaction_lift_interval must be finite and ordered"
                )
        object.__setattr__(
            self,
            "cutoff_evidence",
            tuple(sorted(evidence, key=lambda item: item.cutoff)),
        )

    @property
    def cutoff_count(self) -> int:
        return len(self.cutoff_evidence)

    @property
    def q_actual(self) -> float:
        if not self.cutoff_evidence:
            return float("nan")
        total_weight = sum(item.cutoff_weight for item in self.cutoff_evidence)
        return (
            sum(
                item.actual_probability * item.cutoff_weight
                for item in self.cutoff_evidence
            )
            / total_weight
        )

    @property
    def q_null(self) -> float:
        if not self.cutoff_evidence:
            return float("nan")
        total_weight = sum(item.cutoff_weight for item in self.cutoff_evidence)
        return (
            sum(
                item.null_probability * item.cutoff_weight
                for item in self.cutoff_evidence
            )
            / total_weight
        )

    @property
    def reaction_lift(self) -> float:
        return self.q_actual - self.q_null

    @property
    def touch_rate(self) -> float:
        return (
            self.touch_count / self.lineage_support
            if self.lineage_support
            else float("nan")
        )


class GeometryCandidateStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    INSUFFICIENT = "INSUFFICIENT"
    INCONCLUSIVE = "INCONCLUSIVE"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True, kw_only=True)
class GeometryCandidateResult:
    candidate_id: str
    status: GeometryCandidateStatus
    cells: tuple[GeometryCellEvidence, ...]
    worst_timeframe_kernel_side_lift: float | None
    equal_cell_lift: float | None
    reason: str | None


class GeometryRankingStatus(str, Enum):
    PROVISIONAL_WINNER = "PROVISIONAL_WINNER"
    INVALID = "INVALID"
    INSUFFICIENT = "INSUFFICIENT"
    INCONCLUSIVE = "INCONCLUSIVE"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True, kw_only=True)
class GeometryRankingInput:
    family: SealedCandidateFamily
    cells: tuple[GeometryCellEvidence, ...]
    source_bindings: Mapping[str, tuple[str, str, str, str]]
    target_fingerprints: Mapping[str, str]
    compiler_fingerprints: Mapping[str, Mapping[str, str]]
    null_algorithm_id: str
    family_evidence_receipt_fingerprint: str | None = None
    family_common_joint_utc_block_count: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.family, SealedCandidateFamily):
            raise TypeError("geometry ranking family must be SealedCandidateFamily")
        if not isinstance(self.source_bindings, Mapping) or not self.source_bindings:
            raise TypeError(
                "geometry input source_bindings must be a non-empty mapping"
            )
        source_bindings: dict[str, tuple[str, str, str, str]] = {}
        for asset, raw_binding in self.source_bindings.items():
            if not isinstance(asset, str) or not asset.strip():
                raise ValueError("geometry source binding asset must be non-empty")
            if (
                not isinstance(raw_binding, tuple)
                or len(raw_binding) != 4
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in raw_binding
                )
            ):
                raise ValueError(
                    "geometry source bindings must be asset -> (instrument, manifest, source, slice)"
                )
            source_bindings[asset] = tuple(raw_binding)
        if any(not isinstance(item, GeometryCellEvidence) for item in self.cells):
            raise TypeError("geometry cells must contain GeometryCellEvidence values")
        cell_assets = {cell.group.asset for cell in self.cells}
        if cell_assets and set(source_bindings) != cell_assets:
            raise ValueError("geometry source bindings must cover exact cell assets")
        if (
            not isinstance(self.target_fingerprints, Mapping)
            or not self.target_fingerprints
        ):
            raise TypeError(
                "geometry input target_fingerprints must be a non-empty mapping"
            )
        if any(
            not isinstance(timeframe, str)
            or not isinstance(fingerprint, str)
            or not fingerprint.strip()
            for timeframe, fingerprint in self.target_fingerprints.items()
        ):
            raise ValueError(
                "geometry input target_fingerprints must map non-empty strings"
            )
        compiler_fingerprints = self.compiler_fingerprints
        if not isinstance(compiler_fingerprints, Mapping):
            raise TypeError("geometry input compiler_fingerprints must be a mapping")
        expected_candidate_ids = {
            candidate.candidate_id for candidate in self.family.candidates
        }
        if set(compiler_fingerprints) != expected_candidate_ids:
            raise ValueError(
                "geometry input compiler_fingerprints must cover the exact candidate family"
            )
        compiler_maps: dict[str, Mapping[str, str]] = {}
        expected_assets = set(source_bindings)
        for candidate_id, values in compiler_fingerprints.items():
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                raise ValueError(
                    "geometry input compiler candidate IDs must be non-empty"
                )
            if not isinstance(values, Mapping) or set(values) != expected_assets:
                raise ValueError(
                    "geometry input compiler_fingerprints must cover exact candidate assets"
                )
            if any(
                not isinstance(asset, str)
                or not isinstance(fingerprint, str)
                or not fingerprint.strip()
                for asset, fingerprint in values.items()
            ):
                raise ValueError(
                    "geometry input compiler fingerprints must map non-empty strings"
                )
            compiler_maps[candidate_id] = MappingProxyType(dict(sorted(values.items())))
        null_algorithm_id = _nonempty_string(
            self.null_algorithm_id, "geometry input null_algorithm_id"
        )
        if null_algorithm_id != FEASIBLE_RANDOM_PRICE_ID:
            raise ValueError(
                "geometry input null_algorithm_id is not the accepted feasible null"
            )
        family_receipt = self.family_evidence_receipt_fingerprint
        if family_receipt is not None:
            if (
                not isinstance(family_receipt, str)
                or len(family_receipt) != 64
                or any(
                    character not in "0123456789abcdefABCDEF"
                    for character in family_receipt
                )
            ):
                raise ValueError("geometry family evidence receipt must be a SHA-256")
            family_receipt = family_receipt.lower()
        family_common_blocks = self.family_common_joint_utc_block_count
        if family_common_blocks is not None and (
            isinstance(family_common_blocks, bool)
            or not isinstance(family_common_blocks, int)
            or family_common_blocks < 0
        ):
            raise ValueError(
                "geometry family common block count must be a non-negative integer"
            )
        object.__setattr__(self, "cells", tuple(self.cells))
        object.__setattr__(
            self,
            "source_bindings",
            MappingProxyType(dict(sorted(source_bindings.items()))),
        )
        object.__setattr__(
            self,
            "target_fingerprints",
            MappingProxyType(dict(sorted(self.target_fingerprints.items()))),
        )
        object.__setattr__(
            self,
            "compiler_fingerprints",
            MappingProxyType(dict(sorted(compiler_maps.items()))),
        )
        object.__setattr__(self, "null_algorithm_id", null_algorithm_id)
        object.__setattr__(self, "family_evidence_receipt_fingerprint", family_receipt)


@dataclass(frozen=True, slots=True, kw_only=True)
class GeometryRankingReport:
    status: GeometryRankingStatus
    winner: SealedCandidate | None
    candidates: tuple[GeometryCandidateResult, ...]
    family_hash: str
    report_fingerprint: str


def _cell_aggregate(
    cells: Sequence[GeometryCellEvidence],
    *,
    source_tf_kernel_side: tuple[str, str, ZoneSide],
) -> float:
    selected = [
        cell.reaction_lift
        for cell in cells
        if (
            cell.group.timeframe,
            cell.group.kernel_identifier,
            cell.group.side,
        )
        == source_tf_kernel_side
    ]
    if not selected:
        raise ValueError("missing timeframe/kernel cell")
    return sum(selected) / len(selected)


def _minimum_geometry_cell_support(config: Any) -> int | None:
    inference = config.inference
    value = getattr(inference, "minimum_cell_support", None)
    return value


def _cell_has_geometry_support(cell: GeometryCellEvidence, config: Any) -> bool:
    """Return whether a cell contributes to an asset macro's support gate."""

    minimum_lineages = _minimum_geometry_cell_support(config)
    if minimum_lineages is not None:
        return cell.lineage_support >= minimum_lineages
    inference = config.inference
    return bool(
        cell.cutoff_evidence
        and cell.cluster_count >= inference.minimum_paired_reaction_clusters
        and cell.unique_cutoff_count >= inference.minimum_unique_issuance_cutoffs
        and cell.joint_utc_block_count >= inference.minimum_common_joint_utc_blocks
    )


def rank_geometry_candidates(
    config: ResolvedOptimizerConfig, ranking_input: GeometryRankingInput
) -> GeometryRankingReport:
    """Rank sealed geometry evidence with equal cutoff/asset/cell weighting."""

    if not isinstance(config, ResolvedOptimizerConfig) and not (
        hasattr(config, "baseline_config")
        and hasattr(config, "source")
        and hasattr(config, "search")
        and hasattr(config, "inference")
    ):
        raise TypeError("config must be a resolved optimizer or global geometry config")
    if not isinstance(ranking_input, GeometryRankingInput):
        raise TypeError("ranking_input must be GeometryRankingInput")
    family = ranking_input.family
    if getattr(config, "schema", None) == "sr_v2.development_global_geometry@1":
        expected_family = compile_global_candidate_family(config)
    else:
        expected_family = compile_sealed_candidate_family(config)
    family_hash_matches = family.family_hash == expected_family.family_hash
    expected_groups = _expected_groups(config)
    expected_ids = {candidate.candidate_id for candidate in family.candidates}
    by_candidate: dict[str, list[GeometryCellEvidence]] = {
        candidate_id: [] for candidate_id in expected_ids
    }
    global_invalid: list[str] = []
    global_support_reasons: list[str] = []
    is_global_geometry = getattr(config, "schema", None) == (
        "sr_v2.development_global_geometry@1"
    )
    if not family_hash_matches:
        global_invalid.append(
            "supplied candidate family hash differs from resolved optimizer configuration"
        )
    if ranking_input.null_algorithm_id != FEASIBLE_RANDOM_PRICE_ID:
        global_invalid.append("unsupported geometry input null algorithm")
    if set(ranking_input.target_fingerprints) != set(config.source.ladder):
        global_invalid.append(
            "target fingerprints must cover the exact resolved source ladder"
        )
    expected_assets = set(config.source.assets)
    if set(ranking_input.source_bindings) != expected_assets:
        global_invalid.append(
            "source bindings must cover the exact resolved source assets"
        )
    if set(ranking_input.compiler_fingerprints) != expected_ids:
        global_invalid.append(
            "compiler fingerprints must cover the exact candidate family"
        )
    if is_global_geometry:
        if ranking_input.family_evidence_receipt_fingerprint is None:
            global_invalid.append(
                "global geometry ranking requires shared family evidence receipt"
            )
        if ranking_input.family_common_joint_utc_block_count is None:
            global_invalid.append(
                "global geometry ranking requires common family block count"
            )
        elif (
            ranking_input.family_common_joint_utc_block_count
            < config.inference.minimum_common_joint_utc_blocks
        ):
            global_support_reasons.append(
                "complete-family common UTC-block support below minimum"
            )
    for cell in ranking_input.cells:
        if cell.candidate_id not in expected_ids:
            global_invalid.append(f"unknown candidate cell: {cell.candidate_id}")
            continue
        by_candidate[cell.candidate_id].append(cell)
        binding = ranking_input.source_bindings.get(cell.group.asset)
        if binding is None or (
            cell.source_manifest_id != binding[1]
            or cell.source_sha256 != binding[2]
            or cell.source_slice_fingerprint != binding[3]
        ):
            global_invalid.append(
                f"source identity mismatch: {cell.candidate_id}/{cell.group.key}"
            )
        candidate_compilers = ranking_input.compiler_fingerprints.get(
            cell.candidate_id, {}
        )
        if cell.compiler_fingerprint != candidate_compilers.get(cell.group.asset):
            global_invalid.append(
                f"compiler identity mismatch: {cell.candidate_id}/{cell.group.key}"
            )
        if cell.null_algorithm_id != FEASIBLE_RANDOM_PRICE_ID:
            global_invalid.append(
                f"null algorithm mismatch: {cell.candidate_id}/{cell.group.key}"
            )
        if (
            ranking_input.target_fingerprints.get(cell.group.timeframe)
            != cell.target_fingerprint
        ):
            global_invalid.append(
                f"target identity mismatch: {cell.candidate_id}/{cell.group.key}"
            )
    results: list[GeometryCandidateResult] = []
    for candidate in family.candidates:
        cells = tuple(
            sorted(by_candidate[candidate.candidate_id], key=lambda item: item.group)
        )
        reasons = list(global_invalid)
        groups = {cell.group for cell in cells}
        if groups != set(expected_groups):
            reasons.append(
                f"candidate {candidate.candidate_id} does not have exact cells "
                f"(missing={len(set(expected_groups) - groups)}, extra={len(groups - set(expected_groups))})"
            )
        if len(cells) != len(groups):
            reasons.append(f"candidate {candidate.candidate_id} has duplicate cells")
        if reasons:
            results.append(
                GeometryCandidateResult(
                    candidate_id=candidate.candidate_id,
                    status=GeometryCandidateStatus.INVALID,
                    cells=cells,
                    worst_timeframe_kernel_side_lift=None,
                    equal_cell_lift=None,
                    reason="; ".join(sorted(set(reasons))),
                )
            )
            continue
        minimum_lineages = _minimum_geometry_cell_support(config)
        support_reasons = list(global_support_reasons)
        if minimum_lineages is not None:
            support_reasons.extend(
                f"{cell.group.key}: lineage support below minimum"
                for cell in cells
                if cell.lineage_support < minimum_lineages
            )
        if hasattr(config.inference, "minimum_paired_reaction_clusters"):
            support_reasons.extend(
                f"{cell.group.key}: paired reaction cluster support below minimum"
                for cell in cells
                if cell.cluster_count
                < config.inference.minimum_paired_reaction_clusters
            )
            support_reasons.extend(
                f"{cell.group.key}: unique issuance cutoff support below minimum"
                for cell in cells
                if cell.unique_cutoff_count
                < config.inference.minimum_unique_issuance_cutoffs
            )
            support_reasons.extend(
                f"{cell.group.key}: joint UTC block support below minimum"
                for cell in cells
                if cell.joint_utc_block_count
                < config.inference.minimum_common_joint_utc_blocks
            )
            support_reasons.extend(
                f"{cell.group.key}: no eligible reaction evidence"
                for cell in cells
                if not cell.cutoff_evidence
            )
        macro_keys = tuple(
            sorted(
                {
                    (group.timeframe, group.kernel_identifier, group.side)
                    for group in expected_groups
                },
                key=lambda item: (item[0], item[1], item[2].value),
            )
        )
        for timeframe, kernel_identifier, side in macro_keys:
            assets = {
                cell.group.asset
                for cell in cells
                if (
                    cell.group.timeframe == timeframe
                    and cell.group.kernel_identifier == kernel_identifier
                    and cell.group.side is side
                    and _cell_has_geometry_support(cell, config)
                )
            }
            if len(assets) < config.inference.minimum_asset_support:
                support_reasons.append(
                    f"{timeframe}|{kernel_identifier}|{side.value}: asset support below minimum"
                )
        if support_reasons:
            results.append(
                GeometryCandidateResult(
                    candidate_id=candidate.candidate_id,
                    status=GeometryCandidateStatus.INSUFFICIENT,
                    cells=cells,
                    worst_timeframe_kernel_side_lift=None,
                    equal_cell_lift=None,
                    reason="; ".join(sorted(set(support_reasons))),
                )
            )
            continue
        lifts = tuple(cell.reaction_lift for cell in cells)
        if any(not math.isfinite(value) for value in lifts):
            status = GeometryCandidateStatus.INVALID
            reason = "reaction lift is not finite"
            worst = None
            equal = None
        else:
            macro_lifts = tuple(
                _cell_aggregate(cells, source_tf_kernel_side=item)
                for item in macro_keys
            )
            if any(not math.isfinite(value) for value in macro_lifts):
                status = GeometryCandidateStatus.INVALID
                reason = "macro reaction lift is not finite"
                worst = None
                equal = None
                results.append(
                    GeometryCandidateResult(
                        candidate_id=candidate.candidate_id,
                        status=status,
                        cells=cells,
                        worst_timeframe_kernel_side_lift=worst,
                        equal_cell_lift=equal,
                        reason=reason,
                    )
                )
                continue
            worst = min(macro_lifts)
            equal = sum(lifts) / len(lifts)
            status = GeometryCandidateStatus.VALID
            reason = None
            if candidate.candidate_id != family.baseline.candidate_id:
                # The evaluator supplies an already adjusted paired interval
                # for this candidate-minus-baseline comparison.  This module
                # only applies the configured effect margin once.
                margin = float(config.inference.degradation_margin)
                for cell in cells:
                    interval = cell.paired_reaction_lift_interval
                    if interval is None:
                        status = GeometryCandidateStatus.INCONCLUSIVE
                        reason = "adjusted paired degradation interval is unavailable"
                        break
                    if interval[1] < -margin:
                        status = GeometryCandidateStatus.DEGRADED
                        reason = f"confidently degraded at {cell.group.key}"
                        break
        results.append(
            GeometryCandidateResult(
                candidate_id=candidate.candidate_id,
                status=status,
                cells=cells,
                worst_timeframe_kernel_side_lift=worst,
                equal_cell_lift=equal,
                reason=reason,
            )
        )
    baseline_result = next(
        item for item in results if item.candidate_id == family.baseline.candidate_id
    )
    eligible = tuple(
        item
        for item in results
        if item.status is GeometryCandidateStatus.VALID
        and baseline_result.status is GeometryCandidateStatus.VALID
    )
    winner: SealedCandidate | None = None
    status: GeometryRankingStatus
    if any(item.status is GeometryCandidateStatus.INVALID for item in results):
        status = GeometryRankingStatus.INVALID
    elif eligible:
        selected = min(
            eligible,
            key=lambda item: (
                -(
                    item.worst_timeframe_kernel_side_lift
                    if item.worst_timeframe_kernel_side_lift is not None
                    else float("-inf")
                ),
                -(
                    item.equal_cell_lift
                    if item.equal_cell_lift is not None
                    else float("-inf")
                ),
                item.candidate_id,
            ),
        )
        winner = next(
            candidate
            for candidate in family.candidates
            if candidate.candidate_id == selected.candidate_id
        )
        status = GeometryRankingStatus.PROVISIONAL_WINNER
    else:
        statuses = {item.status for item in results}
        if GeometryCandidateStatus.INVALID in statuses:
            status = GeometryRankingStatus.INVALID
        elif GeometryCandidateStatus.INSUFFICIENT in statuses:
            status = GeometryRankingStatus.INSUFFICIENT
        elif GeometryCandidateStatus.INCONCLUSIVE in statuses:
            status = GeometryRankingStatus.INCONCLUSIVE
        else:
            status = GeometryRankingStatus.DEGRADED
    return GeometryRankingReport(
        status=status,
        winner=winner,
        candidates=tuple(results),
        family_hash=family.family_hash,
        report_fingerprint=canonical_hash(
            {
                "status": status.value,
                "family_hash": family.family_hash,
                "config_fingerprint": config.config_fingerprint,
                "family_binding": {
                    "configured_family_hash": expected_family.family_hash,
                    "supplied_family_hash": family.family_hash,
                    "matched": family_hash_matches,
                },
                "source_bindings": ranking_input.source_bindings,
                "compiler_fingerprints": ranking_input.compiler_fingerprints,
                "null_algorithm_id": ranking_input.null_algorithm_id,
                "family_evidence_receipt_fingerprint": (
                    ranking_input.family_evidence_receipt_fingerprint
                ),
                "family_common_joint_utc_block_count": (
                    ranking_input.family_common_joint_utc_block_count
                ),
                "expected_null_algorithm_id": FEASIBLE_RANDOM_PRICE_ID,
                "ranking_policy_id": getattr(
                    config,
                    "ranking_policy_id",
                    GEOMETRY_RANKING_POLICY_ID,
                ),
                "candidates": results,
                "winner": None if winner is None else winner.candidate_id,
            }
        ),
    )


class _UniqueLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: yaml.Loader, node: yaml.Node, deep: bool = False
) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise SRV2ConfigError("optimizer YAML keys must be strings")
        if key in mapping:
            raise SRV2ConfigError(f"duplicate optimizer YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_optimizer_yaml(path: str | Path) -> Mapping[str, Any]:
    """Load a strict duplicate-key-safe optimizer YAML mapping."""

    try:
        value = yaml.load(Path(path).read_bytes(), Loader=_UniqueLoader)
    except SRV2ConfigError:
        raise
    except Exception as exc:
        raise SRV2ConfigError(f"invalid optimizer YAML: {path}") from exc
    if not isinstance(value, Mapping):
        raise SRV2ConfigError("optimizer YAML root must be a mapping")
    return value


def resolve_optimizer_config(raw: Mapping[str, Any]) -> ResolvedOptimizerConfig:
    """Resolve one complete optimizer mapping without applying defaults."""

    root = _mapping(raw, "optimizer")
    _require_exact(
        root,
        {
            "schema",
            "source",
            "splits",
            "target_identification",
            "search",
            "inference",
            "resources",
        },
        "optimizer",
    )
    schema = _nonempty_string(root["schema"], "schema")
    if schema != OPTIMIZER_SCHEMA:
        raise SRV2ConfigError(f"unsupported optimizer schema: {schema}")

    source_raw = _mapping(root["source"], "source")
    _require_exact(source_raw, _SOURCE_KEYS, "source")
    assets_raw = _mapping(source_raw["assets"], "source.assets")
    source = OptimizerSource(
        venue=source_raw["venue"],
        assets=dict(assets_raw),
        ladder=tuple(source_raw["ladder"]),
        start=_utc(source_raw["start"], "source.start"),
        end=_utc(source_raw["end"], "source.end"),
        acquisition_policy=source_raw["acquisition_policy"],
        source_mode=source_raw["source_mode"],
        cache_root=source_raw["cache_root"],
    )

    splits_raw = _mapping(root["splits"], "splits")
    _require_exact(splits_raw, _SPLIT_KEYS, "splits")
    windows: dict[str, OptimizerWindow] = {}
    for name in ("target_design", "geometry_train", "geometry_validation"):
        item = _mapping(splits_raw[name], f"splits.{name}")
        _require_exact(item, _WINDOW_KEYS, f"splits.{name}")
        window = OptimizerWindow(
            start=_utc(item["start"], f"splits.{name}.start"),
            end=_utc(item["end"], f"splits.{name}.end"),
        )
        if window.start < source.start or window.end > source.end:
            raise SRV2ConfigError(f"splits.{name} must lie within source bounds")
        grid_for(source.ladder[-1]).validate_bar(
            window.start, window.start + grid_for(source.ladder[-1]).duration
        )
        grid_for(source.ladder[-1]).validate_bar(
            window.end - grid_for(source.ladder[-1]).duration, window.end
        )
        windows[name] = window

    target_raw = _mapping(root["target_identification"], "target_identification")
    _require_exact(target_raw, _TARGET_KEYS, "target_identification")
    tuples_raw = target_raw["tuples"]
    if (
        isinstance(tuples_raw, (str, bytes))
        or not isinstance(tuples_raw, (list, tuple))
        or not tuples_raw
    ):
        raise SRV2ConfigError(
            "target_identification.tuples must be a non-empty ordered list"
        )
    target_tuples: list[TargetTuple] = []
    for index, item in enumerate(tuples_raw):
        value = _mapping(item, f"target_identification.tuples[{index}]")
        _require_exact(
            value, _TARGET_TUPLE_KEYS, f"target_identification.tuples[{index}]"
        )
        target_tuples.append(
            TargetTuple(
                source_horizon_bars=_positive_int(
                    value["source_horizon_bars"], "source_horizon_bars"
                ),
                reference_lookback=_positive_int(
                    value["reference_lookback"], "reference_lookback"
                ),
                barrier_multiplier=_finite_decimal(
                    value["barrier_multiplier"], "barrier_multiplier"
                ),
            )
        )
    target_config = TargetIdentificationConfig(
        tuples=tuple(target_tuples),
        minimum_observation_coverage=float(target_raw["minimum_observation_coverage"]),
        minimum_unique_issuance_cutoffs=_positive_int(
            target_raw["minimum_unique_issuance_cutoffs"],
            "minimum_unique_issuance_cutoffs",
        ),
        minimum_joint_utc_blocks=_positive_int(
            target_raw["minimum_joint_utc_blocks"],
            "minimum_joint_utc_blocks",
        ),
        minimum_uncensored_lineages=_positive_int(
            target_raw["minimum_uncensored_lineages"], "minimum_uncensored_lineages"
        ),
        minimum_touch_class_lineages=_positive_int(
            target_raw["minimum_touch_class_lineages"],
            "minimum_touch_class_lineages",
        ),
        minimum_reaction_class_lineages=_positive_int(
            target_raw["minimum_reaction_class_lineages"],
            "minimum_reaction_class_lineages",
        ),
        maximum_censoring_rate=float(target_raw["maximum_censoring_rate"]),
        maximum_unresolved_reaction_rate=float(
            target_raw["maximum_unresolved_reaction_rate"]
        ),
        maximum_ambiguity_rate=float(target_raw["maximum_ambiguity_rate"]),
        maximum_null_unavailable_rate=float(
            target_raw["maximum_null_unavailable_rate"]
        ),
        selection_policy_id=target_raw["selection_policy_id"],
    )
    if any(
        item.source_horizon_bars * TIMEFRAME_DURATIONS[timeframe] > timedelta(days=365)
        for item in target_config.tuples
        for timeframe in source.ladder
    ):
        raise SRV2ConfigError("target horizon exceeds the code-owned maximum horizon")
    maximum_horizon = max(
        (
            TIMEFRAME_DURATIONS[timeframe] * item.source_horizon_bars
            for item in target_config.tuples
            for timeframe in source.ladder
        ),
        default=timedelta(0),
    )
    embargo = duration(splits_raw["embargo"], "splits.embargo")
    splits = OptimizerSplits(
        target_design=windows["target_design"],
        geometry_train=windows["geometry_train"],
        geometry_validation=windows["geometry_validation"],
        embargo=embargo,
        maximum_horizon=maximum_horizon,
    )

    search_raw = _mapping(root["search"], "search")
    _require_exact(search_raw, _SEARCH_KEYS, "search")
    baseline_path = Path(
        _nonempty_string(
            search_raw["baseline_structural_yaml"], "search.baseline_structural_yaml"
        )
    )
    baseline_sha256 = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    baseline = SRV2ConfigResolver(load_sr_v2_yaml(baseline_path)).resolve()
    parameter_choices = search_raw["parameters"]
    search = SearchConfig(
        sampler_id=search_raw["sampler_id"],
        seed=search_raw["seed"],
        trial_budget=_positive_int(search_raw["trial_budget"], "search.trial_budget"),
        baseline_structural_yaml=str(baseline_path),
        baseline_structural_yaml_sha256=baseline_sha256,
        parameter_choices=parameter_choices,
        baseline_config=baseline,
    )

    inference_raw = _mapping(root["inference"], "inference")
    _require_exact(inference_raw, _INFERENCE_KEYS, "inference")
    inference = InferenceConfig(
        joint_utc_block=duration(
            inference_raw["joint_utc_block"], "inference.joint_utc_block"
        ),
        epoch=_utc(inference_raw["epoch"], "inference.epoch"),
        repetitions=_positive_int(
            inference_raw["repetitions"], "inference.repetitions"
        ),
        confidence=float(inference_raw["confidence"]),
        alpha_family=inference_raw["alpha_family"],
        degradation_margin=_finite_decimal(
            inference_raw["degradation_margin"],
            "inference.degradation_margin",
            allow_zero=True,
        ),
        minimum_cell_support=_positive_int(
            inference_raw["minimum_cell_support"], "inference.minimum_cell_support"
        ),
        minimum_asset_support=_positive_int(
            inference_raw["minimum_asset_support"], "inference.minimum_asset_support"
        ),
    )
    if inference.joint_utc_block < maximum_horizon:
        raise SRV2ConfigError(
            "inference.joint_utc_block must cover the largest target horizon"
        )

    resources_raw = _mapping(root["resources"], "resources")
    _require_exact(resources_raw, _RESOURCE_KEYS, "resources")
    resources = ResourceConfig(
        max_workers=_positive_int(
            resources_raw["max_workers"], "resources.max_workers"
        ),
        receipt_dir=resources_raw["receipt_dir"],
    )
    resolved = ResolvedOptimizerConfig(
        schema=schema,
        source=source,
        splits=splits,
        target_identification=target_config,
        search=search,
        inference=inference,
        resources=resources,
        config_fingerprint="pending",
    )
    fingerprint_payload = {
        "schema": schema,
        "source": {
            "venue": source.venue,
            "assets": source.assets,
            "ladder": source.ladder,
            "start": source.start,
            "end": source.end,
            "acquisition_policy": source.acquisition_policy,
            "source_mode": source.source_mode,
            "cache_root": source.cache_root,
        },
        "splits": splits,
        "target_identification": target_config,
        "search": {
            "sampler_id": search.sampler_id,
            "seed": search.seed,
            "trial_budget": search.trial_budget,
            "baseline_structural_yaml_sha256": search.baseline_structural_yaml_sha256,
            "parameter_choices": search.parameter_choices,
            "baseline_config_fingerprint": baseline.config_fingerprint,
        },
        "inference": inference,
        "resources": resources,
    }
    object.__setattr__(
        resolved, "config_fingerprint", canonical_hash(fingerprint_payload)
    )
    return resolved


def load_optimizer_config(path: str | Path) -> ResolvedOptimizerConfig:
    """Load and resolve one optimizer YAML file."""

    return resolve_optimizer_config(load_optimizer_yaml(path))


__all__ = [
    "ALPHA_FAMILIES",
    "GEOMETRY_RANKING_POLICY_ID",
    "OPTIMIZER_SCHEMA",
    "SAMPLER_ID",
    "STREAMING_TARGET_DIAGNOSTIC_SCHEMA",
    "TARGET_SELECTION_POLICY",
    "CutoffReactionEvidence",
    "FixtureTargetIdentificationInput",
    "GeometryCandidateResult",
    "GeometryCandidateStatus",
    "GeometryCellEvidence",
    "GeometryRankingInput",
    "GeometryRankingReport",
    "GeometryRankingStatus",
    "InferenceConfig",
    "OptimizerSource",
    "OptimizerSplits",
    "OptimizerWindow",
    "ResolvedOptimizerConfig",
    "ResourceConfig",
    "SealedCandidate",
    "SealedCandidateFamily",
    "SearchConfig",
    "TargetDiagnosticAccumulator",
    "TargetGroupDiagnostic",
    "TargetIdentificationConfig",
    "TargetIdentificationReport",
    "TargetIdentificationStatus",
    "TargetTuple",
    "TargetTupleDiagnostic",
    "TargetTupleStatus",
    "compile_global_candidate_family",
    "compile_sealed_candidate_family",
    "identify_target_from_compiled_fixture",
    "identify_target_streaming",
    "load_optimizer_config",
    "load_optimizer_yaml",
    "rank_geometry_candidates",
    "resolve_optimizer_config",
]
