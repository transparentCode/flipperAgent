"""Strict, authenticated development target and geometry configuration.

The development YAMLs are deliberately separate from the legacy combined
optimizer fixture schema.  This module only resolves policy supplied values
and authenticates already-produced evidence; it does not load market data or
run a replay.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from importlib import metadata
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..config.resolver import ResolvedSRV2Config, SRV2ConfigResolver, load_sr_v2_yaml
from ..config.schema import SUPPORTED_TIMEFRAMES, TIMEFRAME_DURATIONS, duration
from ..contracts import ZoneSide
from ..domain.identity import canonical_hash, canonical_json
from ..forecast.targets import ResolvedTargetSpec, scientific_target_fingerprint
from ..research_lab.episode_evidence import target_family_fingerprint_from_choices
from ..research_lab.scientific_compiler import ScientificGroupKey

# Importing these types is intentionally one-way: optimizer imports this
# module only after defining its legacy fixture types.
from .optimizer import (
    OptimizerSource,
    OptimizerWindow,
    SearchConfig,
    TargetIdentificationConfig,
    TargetIdentificationReport,
    TargetIdentificationStatus,
    TargetTuple,
    TargetTupleStatus,
    _finite_decimal,
    _mapping,
    _nonempty_string,
    _positive_int,
    _require_exact,
    _target_choice_id_for_tuple,
    _utc,
    compile_global_candidate_family,
    load_optimizer_yaml,
)
from .placebos import FEASIBLE_RANDOM_PRICE_ID

TARGET_DESIGN_SCHEMA = "sr_v2.development_target_design@1"
GLOBAL_GEOMETRY_SCHEMA = "sr_v2.development_global_geometry@1"
TARGET_DESIGN_REFERENCE_VOLATILITY_ID = "simple_true_range_mean@1"
TARGET_DESIGN_SELECTION_POLICY_ID = "first_feasible@1"
TARGET_DESIGN_N_PROPOSAL_POLICY_ID = "source_tr_only_n_proposal@1"
TARGET_DESIGN_D_PROPOSAL_POLICY_ID = "normalized_excursion_breakpoint@1"
TARGET_DESIGN_OBSERVATION_TIMEFRAME = "15m"
_RUNTIME_CRITICAL_DISTRIBUTIONS = (
    "PyYAML",
    "binance-futures-connector",
    "numpy",
    "pandas",
)
SCIENTIFIC_SOURCE_LADDER = tuple(
    sorted(SUPPORTED_TIMEFRAMES, key=TIMEFRAME_DURATIONS.__getitem__, reverse=True)
)

_TARGET_DESIGN_KEYS = {
    "schema",
    "source",
    "target_design_window",
    "reference_volatility",
    "horizon",
    "barrier",
    "identifiability",
    "inference",
    "resources",
}
_TARGET_REFERENCE_KEYS = {"algorithm_id", "selection_policy_id"}
_TARGET_HORIZON_KEYS = {"unit", "observation_timeframe"}
_TARGET_BARRIER_KEYS = {
    "derivation_policy_id",
    "scan_lower",
    "scan_upper",
    "candidate_cap",
}
_TARGET_INFERENCE_KEYS = {"joint_utc_block", "epoch"}
_TARGET_RESOURCE_KEYS = {"max_workers", "receipt_dir", "artifact_root"}
_GLOBAL_KEYS = {
    "schema",
    "source",
    "splits",
    "target_freeze",
    "search",
    "inference",
    "resources",
    "ranking_policy_id",
}
_GLOBAL_FREEZE_KEYS = {
    "target_design_artifact_path",
    "target_design_artifact_sha256",
    "target_design_artifact_id",
    "target_selection_report_fingerprint",
    "target_family_fingerprint",
    "baseline_structural_yaml_sha256",
    "baseline_model_fingerprint",
    "selected_tuple",
    "target_fingerprints",
    "null_algorithm_id",
    "implementation_digest",
    "runtime_environment_fingerprint",
    "asset_bindings",
}
_GLOBAL_BINDING_KEYS = {
    "instrument_id",
    "source_manifest_id",
    "source_sha256",
    "source_slice_fingerprint",
    "baseline_episode_artifact_id",
    "common_risk_receipt_fingerprint",
    "selected_compiler_fingerprint",
}
_GLOBAL_SEARCH_KEYS = {
    "sampler_id",
    "seed",
    "trial_budget",
    "baseline_structural_yaml",
    "parameters",
}
_GLOBAL_INFERENCE_KEYS = {
    "joint_utc_block",
    "epoch",
    "repetitions",
    "confidence",
    "alpha_family",
    "degradation_margin",
    "minimum_paired_reaction_clusters",
    "minimum_unique_issuance_cutoffs",
    "minimum_common_joint_utc_blocks",
    "minimum_asset_support",
}
_GLOBAL_RESOURCE_KEYS = {
    "max_workers",
    "receipt_dir",
    "artifact_root",
    "max_peak_rss_bytes_per_asset",
    "max_artifact_bytes_per_asset",
    "max_wall_seconds_per_asset",
    "max_total_artifact_bytes",
}
_SPLIT_NAMES = ("target_design", "geometry_train", "geometry_validation", "embargo")


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError(f"{name} must be a SHA-256 hexadecimal string")
    return value.lower()


def _decode_canonical(value: Any) -> Any:
    """Decode the small tagged values emitted by ``canonical_json``."""

    if isinstance(value, list):
        return tuple(_decode_canonical(item) for item in value)
    if isinstance(value, Mapping):
        if set(value) == {"__decimal__"}:
            return Decimal(value["__decimal__"])
        if set(value) == {"__datetime__"}:
            return datetime.fromisoformat(value["__datetime__"])
        if set(value) == {"__timedelta_us__"}:
            return timedelta(microseconds=int(value["__timedelta_us__"]))
        return {key: _decode_canonical(item) for key, item in value.items()}
    return value


def _strict_mapping(value: object, name: str) -> Mapping[str, Any]:
    return _mapping(value, name)


def _source(raw: object, name: str = "source") -> OptimizerSource:
    value = _strict_mapping(raw, name)
    _require_exact(
        value,
        {
            "venue",
            "assets",
            "ladder",
            "start",
            "end",
            "acquisition_policy",
            "source_mode",
            "cache_root",
        },
        name,
    )
    assets = _strict_mapping(value["assets"], f"{name}.assets")
    source = OptimizerSource(
        venue=value["venue"],
        assets=dict(assets),
        ladder=tuple(value["ladder"]),
        start=_utc(value["start"], f"{name}.start"),
        end=_utc(value["end"], f"{name}.end"),
        acquisition_policy=value["acquisition_policy"],
        source_mode=value["source_mode"],
        cache_root=value["cache_root"],
    )
    if source.ladder != SCIENTIFIC_SOURCE_LADDER:
        raise ValueError("source.ladder must be the exact six-lane scientific ladder")
    return source


def _window(raw: object, name: str) -> OptimizerWindow:
    value = _strict_mapping(raw, name)
    _require_exact(value, {"start", "end"}, name)
    return OptimizerWindow(
        start=_utc(value["start"], f"{name}.start"),
        end=_utc(value["end"], f"{name}.end"),
    )


def _inside(window: OptimizerWindow, source: OptimizerSource, name: str) -> None:
    if window.start < source.start or window.end > source.end:
        raise ValueError(f"{name} must lie within source bounds")


def _tuple_values(raw: object, name: str) -> tuple[TargetTuple, ...]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or not raw:
        raise ValueError(f"{name} must be a non-empty ordered list")
    values: list[TargetTuple] = []
    for index, item in enumerate(raw):
        mapping = _strict_mapping(item, f"{name}[{index}]")
        _require_exact(
            mapping,
            {"source_horizon_bars", "reference_lookback", "barrier_multiplier"},
            f"{name}[{index}]",
        )
        values.append(
            TargetTuple(
                source_horizon_bars=_positive_int(
                    mapping["source_horizon_bars"],
                    f"{name}[{index}].source_horizon_bars",
                ),
                reference_lookback=_positive_int(
                    mapping["reference_lookback"],
                    f"{name}[{index}].reference_lookback",
                ),
                barrier_multiplier=_finite_decimal(
                    mapping["barrier_multiplier"],
                    f"{name}[{index}].barrier_multiplier",
                ),
            )
        )
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must contain unique tuples")
    return tuple(values)


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetDesignReferenceVolatility:
    algorithm_id: str
    selection_policy_id: str

    def __post_init__(self) -> None:
        if self.algorithm_id != TARGET_DESIGN_REFERENCE_VOLATILITY_ID:
            raise ValueError("unsupported target reference volatility algorithm")
        if self.selection_policy_id != TARGET_DESIGN_SELECTION_POLICY_ID:
            raise ValueError("unsupported target volatility selection policy")


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetDesignHorizon:
    unit: str
    observation_timeframe: str

    def __post_init__(self) -> None:
        if self.unit != "source_bars":
            raise ValueError("target horizon unit must be source_bars")
        if self.observation_timeframe != TARGET_DESIGN_OBSERVATION_TIMEFRAME:
            raise ValueError("target observation timeframe must be 15m")


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetDesignBarrier:
    derivation_policy_id: str
    scan_lower: Any
    scan_upper: Any
    candidate_cap: int

    def __post_init__(self) -> None:
        lower = _finite_decimal(self.scan_lower, "barrier.scan_lower")
        upper = _finite_decimal(self.scan_upper, "barrier.scan_upper")
        if upper < lower:
            raise ValueError("barrier.scan_upper must be >= scan_lower")
        policy = _nonempty_string(
            self.derivation_policy_id, "barrier.derivation_policy_id"
        )
        if policy != TARGET_DESIGN_D_PROPOSAL_POLICY_ID:
            raise ValueError("unsupported target barrier derivation policy")
        cap = _positive_int(self.candidate_cap, "barrier.candidate_cap")
        object.__setattr__(self, "scan_lower", lower)
        object.__setattr__(self, "scan_upper", upper)
        object.__setattr__(self, "derivation_policy_id", policy)
        object.__setattr__(self, "candidate_cap", cap)


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetDesignInference:
    joint_utc_block: timedelta
    epoch: datetime

    def __post_init__(self) -> None:
        if not isinstance(
            self.joint_utc_block, timedelta
        ) or self.joint_utc_block <= timedelta(0):
            raise ValueError("inference.joint_utc_block must be positive")
        object.__setattr__(self, "epoch", _utc(self.epoch, "inference.epoch"))


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetDesignResources:
    max_workers: int
    receipt_dir: str
    artifact_root: str

    def __post_init__(self) -> None:
        if _positive_int(self.max_workers, "resources.max_workers") != 1:
            raise ValueError("target design resources.max_workers must equal one")
        object.__setattr__(
            self,
            "receipt_dir",
            _nonempty_string(self.receipt_dir, "resources.receipt_dir"),
        )
        object.__setattr__(
            self,
            "artifact_root",
            _nonempty_string(self.artifact_root, "resources.artifact_root"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedTargetDesignConfig:
    schema: str
    source: OptimizerSource
    target_design_window: OptimizerWindow
    reference_volatility: TargetDesignReferenceVolatility
    horizon: TargetDesignHorizon
    barrier: TargetDesignBarrier
    identifiability: TargetIdentificationConfig
    inference: TargetDesignInference
    resources: TargetDesignResources
    config_fingerprint: str
    comparator_config: ResolvedSRV2Config | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.schema != TARGET_DESIGN_SCHEMA:
            raise ValueError(f"unsupported target design schema: {self.schema}")
        if not isinstance(self.source, OptimizerSource):
            raise TypeError("target design source must be OptimizerSource")
        if not isinstance(self.target_design_window, OptimizerWindow):
            raise TypeError("target design window must be OptimizerWindow")
        _inside(self.target_design_window, self.source, "target_design_window")
        if not isinstance(self.reference_volatility, TargetDesignReferenceVolatility):
            raise TypeError("reference_volatility must be typed")
        if not isinstance(self.horizon, TargetDesignHorizon):
            raise TypeError("horizon must be typed")
        if not isinstance(self.barrier, TargetDesignBarrier):
            raise TypeError("barrier must be typed")
        if not isinstance(self.identifiability, TargetIdentificationConfig):
            raise TypeError("identifiability must be TargetIdentificationConfig")
        if not isinstance(self.inference, TargetDesignInference):
            raise TypeError("inference must be typed")
        if not isinstance(self.resources, TargetDesignResources):
            raise TypeError("resources must be typed")
        barrier_multipliers = {
            target.barrier_multiplier for target in self.identifiability.tuples
        }
        if any(
            multiplier < self.barrier.scan_lower or multiplier > self.barrier.scan_upper
            for multiplier in barrier_multipliers
        ):
            raise ValueError(
                "target tuple barrier multipliers must lie within the barrier scan"
            )
        if len(barrier_multipliers) > self.barrier.candidate_cap:
            raise ValueError(
                "distinct target barrier multipliers exceed barrier candidate cap"
            )
        if self.comparator_config is not None:
            if not isinstance(self.comparator_config, ResolvedSRV2Config):
                raise TypeError("target design comparator_config must be resolved")
            if self.comparator_config.ladder != self.source.ladder:
                raise ValueError("target design comparator ladder differs from source")
            if (
                self.comparator_config.trigger_timeframe
                != self.horizon.observation_timeframe
            ):
                raise ValueError(
                    "target design observation timeframe differs from comparator trigger"
                )
        maximum = max(
            TIMEFRAME_DURATIONS[timeframe] * target.source_horizon_bars
            for target in self.identifiability.tuples
            for timeframe in self.source.ladder
        )
        if self.inference.joint_utc_block < maximum:
            raise ValueError(
                "target inference block must cover the largest target horizon"
            )
        object.__setattr__(
            self,
            "config_fingerprint",
            _sha256(self.config_fingerprint, "target design config_fingerprint"),
        )

    @property
    def maximum_horizon(self) -> timedelta:
        return max(
            TIMEFRAME_DURATIONS[timeframe] * target.source_horizon_bars
            for target in self.identifiability.tuples
            for timeframe in self.source.ladder
        )

    def target_spec(
        self, target_tuple: TargetTuple, timeframe: str
    ) -> ResolvedTargetSpec:
        if target_tuple not in self.identifiability.tuples:
            raise ValueError("target tuple is not configured")
        if timeframe not in self.source.ladder:
            raise ValueError("target timeframe is not configured")
        return ResolvedTargetSpec(
            source_timeframe=timeframe,
            source_horizon_bars=target_tuple.source_horizon_bars,
            reference_lookback=target_tuple.reference_lookback,
            barrier_multiplier=target_tuple.barrier_multiplier,
            observation_timeframe=self.horizon.observation_timeframe,
            observation_duration=TIMEFRAME_DURATIONS[
                self.horizon.observation_timeframe
            ],
        )

    def target_fingerprints(self, target_tuple: TargetTuple) -> Mapping[str, str]:
        return MappingProxyType(
            {
                timeframe: scientific_target_fingerprint(
                    self.target_spec(target_tuple, timeframe)
                )
                for timeframe in self.source.ladder
            }
        )


def _target_design_mapping(config: ResolvedTargetDesignConfig) -> Mapping[str, Any]:
    source = config.source
    target_window = config.target_design_window
    reference = config.reference_volatility
    horizon = config.horizon
    barrier = config.barrier
    ident = config.identifiability
    inference = config.inference
    resources = config.resources
    return {
        "schema": config.schema,
        "source": {
            "venue": source.venue,
            "assets": dict(source.assets),
            "ladder": source.ladder,
            "start": source.start,
            "end": source.end,
            "acquisition_policy": source.acquisition_policy,
            "source_mode": source.source_mode,
        },
        "target_design_window": {
            "start": target_window.start,
            "end": target_window.end,
        },
        "reference_volatility": {
            "algorithm_id": reference.algorithm_id,
            "selection_policy_id": reference.selection_policy_id,
        },
        "horizon": {
            "unit": horizon.unit,
            "observation_timeframe": horizon.observation_timeframe,
        },
        "barrier": {
            "derivation_policy_id": barrier.derivation_policy_id,
            "scan_lower": barrier.scan_lower,
            "scan_upper": barrier.scan_upper,
            "candidate_cap": barrier.candidate_cap,
        },
        "identifiability": {
            "tuples": ident.tuples,
            "minimum_observation_coverage": ident.minimum_observation_coverage,
            "minimum_unique_issuance_cutoffs": ident.minimum_unique_issuance_cutoffs,
            "minimum_joint_utc_blocks": ident.minimum_joint_utc_blocks,
            "minimum_uncensored_lineages": ident.minimum_uncensored_lineages,
            "minimum_touch_class_lineages": ident.minimum_touch_class_lineages,
            "minimum_reaction_class_lineages": ident.minimum_reaction_class_lineages,
            "maximum_censoring_rate": ident.maximum_censoring_rate,
            "maximum_unresolved_reaction_rate": ident.maximum_unresolved_reaction_rate,
            "maximum_ambiguity_rate": ident.maximum_ambiguity_rate,
            "maximum_null_unavailable_rate": ident.maximum_null_unavailable_rate,
            "selection_policy_id": ident.selection_policy_id,
        },
        "inference": {
            "joint_utc_block": inference.joint_utc_block,
            "epoch": inference.epoch,
        },
        "resources": {
            "max_workers": resources.max_workers,
        },
    }


def _target_fingerprints_for_tuple(target_tuple: TargetTuple) -> Mapping[str, str]:
    """Derive the six target identities from code-owned target semantics."""

    return MappingProxyType(
        {
            timeframe: scientific_target_fingerprint(
                ResolvedTargetSpec(
                    source_timeframe=timeframe,
                    source_horizon_bars=target_tuple.source_horizon_bars,
                    reference_lookback=target_tuple.reference_lookback,
                    barrier_multiplier=target_tuple.barrier_multiplier,
                    observation_timeframe=TARGET_DESIGN_OBSERVATION_TIMEFRAME,
                    observation_duration=TIMEFRAME_DURATIONS[
                        TARGET_DESIGN_OBSERVATION_TIMEFRAME
                    ],
                )
            )
            for timeframe in SCIENTIFIC_SOURCE_LADDER
        }
    )


def _target_family_fingerprint_for_tuples(
    target_tuples: Sequence[TargetTuple],
) -> str:
    return target_family_fingerprint_from_choices(
        tuple(
            (
                _target_choice_id_for_tuple(target_tuple),
                tuple(
                    (timeframe, fingerprints[timeframe])
                    for timeframe in sorted(fingerprints)
                ),
            )
            for target_tuple in target_tuples
            for fingerprints in (_target_fingerprints_for_tuple(target_tuple),)
        )
    )


def resolve_target_design_config(
    raw: Mapping[str, Any], *, comparator_config: ResolvedSRV2Config | None = None
) -> ResolvedTargetDesignConfig:
    root = _strict_mapping(raw, "target_design")
    _require_exact(root, _TARGET_DESIGN_KEYS, "target_design")
    schema = _nonempty_string(root["schema"], "schema")
    if schema != TARGET_DESIGN_SCHEMA:
        raise ValueError(f"unsupported target design schema: {schema}")
    source = _source(root["source"])
    window = _window(root["target_design_window"], "target_design_window")
    _inside(window, source, "target_design_window")

    volatility_raw = _strict_mapping(
        root["reference_volatility"], "reference_volatility"
    )
    _require_exact(volatility_raw, _TARGET_REFERENCE_KEYS, "reference_volatility")
    volatility = TargetDesignReferenceVolatility(
        algorithm_id=volatility_raw["algorithm_id"],
        selection_policy_id=volatility_raw["selection_policy_id"],
    )
    horizon_raw = _strict_mapping(root["horizon"], "horizon")
    _require_exact(horizon_raw, _TARGET_HORIZON_KEYS, "horizon")
    horizon = TargetDesignHorizon(
        unit=horizon_raw["unit"],
        observation_timeframe=horizon_raw["observation_timeframe"],
    )
    if comparator_config is not None:
        if not isinstance(comparator_config, ResolvedSRV2Config):
            raise TypeError("comparator_config must be ResolvedSRV2Config")
        if comparator_config.trigger_timeframe != horizon.observation_timeframe:
            raise ValueError(
                "target observation timeframe differs from comparator trigger"
            )
        if comparator_config.ladder != source.ladder:
            raise ValueError("target source ladder differs from comparator ladder")

    barrier_raw = _strict_mapping(root["barrier"], "barrier")
    _require_exact(barrier_raw, _TARGET_BARRIER_KEYS, "barrier")
    barrier = TargetDesignBarrier(
        derivation_policy_id=barrier_raw["derivation_policy_id"],
        scan_lower=barrier_raw["scan_lower"],
        scan_upper=barrier_raw["scan_upper"],
        candidate_cap=barrier_raw["candidate_cap"],
    )
    ident_raw = _strict_mapping(root["identifiability"], "identifiability")
    ident_keys = {
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
    _require_exact(ident_raw, ident_keys, "identifiability")
    ident = TargetIdentificationConfig(
        tuples=_tuple_values(ident_raw["tuples"], "identifiability.tuples"),
        minimum_observation_coverage=float(ident_raw["minimum_observation_coverage"]),
        minimum_unique_issuance_cutoffs=_positive_int(
            ident_raw["minimum_unique_issuance_cutoffs"],
            "identifiability.minimum_unique_issuance_cutoffs",
        ),
        minimum_joint_utc_blocks=_positive_int(
            ident_raw["minimum_joint_utc_blocks"],
            "identifiability.minimum_joint_utc_blocks",
        ),
        minimum_uncensored_lineages=_positive_int(
            ident_raw["minimum_uncensored_lineages"],
            "identifiability.minimum_uncensored_lineages",
        ),
        minimum_touch_class_lineages=_positive_int(
            ident_raw["minimum_touch_class_lineages"],
            "identifiability.minimum_touch_class_lineages",
        ),
        minimum_reaction_class_lineages=_positive_int(
            ident_raw["minimum_reaction_class_lineages"],
            "identifiability.minimum_reaction_class_lineages",
        ),
        maximum_censoring_rate=float(ident_raw["maximum_censoring_rate"]),
        maximum_unresolved_reaction_rate=float(
            ident_raw["maximum_unresolved_reaction_rate"]
        ),
        maximum_ambiguity_rate=float(ident_raw["maximum_ambiguity_rate"]),
        maximum_null_unavailable_rate=float(ident_raw["maximum_null_unavailable_rate"]),
        selection_policy_id=ident_raw["selection_policy_id"],
    )
    if ident.selection_policy_id != TARGET_DESIGN_SELECTION_POLICY_ID:
        raise ValueError("unsupported target tuple selection policy")
    inference_raw = _strict_mapping(root["inference"], "inference")
    _require_exact(inference_raw, _TARGET_INFERENCE_KEYS, "inference")
    inference = TargetDesignInference(
        joint_utc_block=duration(
            inference_raw["joint_utc_block"], "inference.joint_utc_block"
        ),
        epoch=_utc(inference_raw["epoch"], "inference.epoch"),
    )
    resources_raw = _strict_mapping(root["resources"], "resources")
    _require_exact(resources_raw, _TARGET_RESOURCE_KEYS, "resources")
    resources = TargetDesignResources(
        max_workers=resources_raw["max_workers"],
        receipt_dir=resources_raw["receipt_dir"],
        artifact_root=resources_raw["artifact_root"],
    )
    pending = ResolvedTargetDesignConfig(
        schema=schema,
        source=source,
        target_design_window=window,
        reference_volatility=volatility,
        horizon=horizon,
        barrier=barrier,
        identifiability=ident,
        inference=inference,
        resources=resources,
        config_fingerprint="0" * 64,
        comparator_config=comparator_config,
    )
    object.__setattr__(
        pending, "config_fingerprint", canonical_hash(_target_design_mapping(pending))
    )
    return pending


def load_target_design_config(
    path: str | Path, *, comparator_config: ResolvedSRV2Config | None = None
) -> ResolvedTargetDesignConfig:
    return resolve_target_design_config(
        load_optimizer_yaml(path), comparator_config=comparator_config
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetDesignAssetBinding:
    instrument_id: str
    source_manifest_id: str
    source_sha256: str
    source_slice_fingerprint: str
    baseline_episode_artifact_id: str
    common_risk_receipt_fingerprint: str
    selected_compiler_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _nonempty_string(self.instrument_id, "asset binding instrument_id"),
        )
        for name in (
            "source_manifest_id",
            "source_sha256",
            "source_slice_fingerprint",
            "baseline_episode_artifact_id",
            "common_risk_receipt_fingerprint",
            "selected_compiler_fingerprint",
        ):
            object.__setattr__(
                self, name, _sha256(getattr(self, name), f"asset binding {name}")
            )

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "source_manifest_id": self.source_manifest_id,
            "source_sha256": self.source_sha256,
            "source_slice_fingerprint": self.source_slice_fingerprint,
            "baseline_episode_artifact_id": self.baseline_episode_artifact_id,
            "common_risk_receipt_fingerprint": self.common_risk_receipt_fingerprint,
            "selected_compiler_fingerprint": self.selected_compiler_fingerprint,
        }


def _source_window_mapping(
    source: OptimizerSource,
    target_design_window: OptimizerWindow,
    asset_bindings: Mapping[str, TargetDesignAssetBinding | FrozenAssetTargetBinding],
) -> Mapping[str, Any]:
    """Canonical source/window identity shared by target and global schemas."""

    return {
        "schema": "sr_v2.target_design_source_window@1",
        "source": {
            "venue": source.venue,
            "assets": dict(source.assets),
            "ladder": source.ladder,
            "start": source.start,
            "end": source.end,
            "acquisition_policy": source.acquisition_policy,
            "source_mode": source.source_mode,
        },
        "target_design_window": {
            "start": target_design_window.start,
            "end": target_design_window.end,
        },
        "asset_bindings": {
            asset: binding.to_mapping()
            for asset, binding in sorted(asset_bindings.items())
        },
    }


def _source_window_fingerprint(
    source: OptimizerSource,
    target_design_window: OptimizerWindow,
    asset_bindings: Mapping[str, TargetDesignAssetBinding | FrozenAssetTargetBinding],
) -> str:
    return canonical_hash(
        _source_window_mapping(source, target_design_window, asset_bindings)
    )


def _diagnostic_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        result = dict(value)
        if "target_tuple" in result:
            result["target_tuple"] = _target_tuple_value(
                result["target_tuple"], "target diagnostic target_tuple"
            )
        if "status" in result:
            result["status"] = getattr(result["status"], "value", result["status"])
        return result
    if hasattr(value, "target_tuple") and hasattr(value, "status"):
        status = value.status.value if hasattr(value.status, "value") else value.status
        return {
            "target_tuple": value.target_tuple,
            "status": status,
            "groups": tuple(getattr(value, "groups", ())),
            "reason": getattr(value, "reason", None),
            "tuple_fingerprint": getattr(value, "tuple_fingerprint", None),
        }
    raise TypeError(
        "target diagnostics must be mappings or TargetTupleDiagnostic values"
    )


def _target_tuple_value(value: object, name: str) -> TargetTuple:
    if isinstance(value, TargetTuple):
        return value
    if isinstance(value, Mapping):
        keys = {"source_horizon_bars", "reference_lookback", "barrier_multiplier"}
        if set(value) != keys:
            raise ValueError(f"{name} has unknown or missing keys")
        return TargetTuple(
            source_horizon_bars=value["source_horizon_bars"],
            reference_lookback=value["reference_lookback"],
            barrier_multiplier=value["barrier_multiplier"],
        )
    raise TypeError(f"{name} must be a TargetTuple")


def build_target_design_artifact(
    *,
    config: ResolvedTargetDesignConfig,
    report: Any,
    target_design_yaml_sha256: str,
    comparator_yaml_sha256: str,
    comparator_model_fingerprint: str,
    asset_bindings: Mapping[str, TargetDesignAssetBinding],
    implementation_digest: str,
    runtime_environment_receipt: Mapping[str, Any],
) -> TargetDesignArtifact:
    """Build an artifact only from an authenticated target-identification report.

    The report's ordered diagnostics are the authority for the YAML-first stop
    rule.  Keeping that check in this factory prevents a caller from writing a
    plausible-looking freeze with an arbitrary feasible tuple.
    """

    if not isinstance(config, ResolvedTargetDesignConfig):
        raise TypeError("target artifact config must be ResolvedTargetDesignConfig")
    if not isinstance(config.comparator_config, ResolvedSRV2Config):
        raise TypeError("target artifact requires an authenticated comparator_config")
    if comparator_model_fingerprint != config.comparator_config.config_fingerprint:
        raise ValueError(
            "target artifact comparator model fingerprint differs from config"
        )
    if not isinstance(report, TargetIdentificationReport):
        raise TypeError("target artifact report must be a TargetIdentificationReport")
    status = getattr(report.status, "value", report.status)
    if status != TargetIdentificationStatus.TARGET_IDENTIFIED.value:
        raise ValueError("target artifact requires TARGET_IDENTIFIED report")
    selected = getattr(report, "selected_tuple", None)
    if not isinstance(selected, TargetTuple):
        raise TypeError("target artifact report must select a target tuple")
    diagnostics = tuple(report.tuple_diagnostics)
    configured = tuple(config.identifiability.tuples)
    if len(diagnostics) != len(configured):
        raise ValueError(
            "target artifact diagnostics must cover exact configured tuples"
        )
    diagnostic_tuples = tuple(
        getattr(item, "target_tuple", None) for item in diagnostics
    )
    if diagnostic_tuples != configured:
        raise ValueError("target artifact diagnostics must preserve YAML tuple order")
    first_feasible = next(
        (
            getattr(item, "target_tuple", None)
            for item in diagnostics
            if getattr(
                getattr(item, "status", None), "value", getattr(item, "status", None)
            )
            == TargetTupleStatus.FEASIBLE.value
        ),
        None,
    )
    if first_feasible is None or selected != first_feasible:
        raise ValueError(
            "target artifact selected tuple is not the first feasible tuple"
        )
    if not isinstance(report.report_fingerprint, str):
        raise TypeError("target artifact report fingerprint must be supplied")
    expected_report_fingerprint = canonical_hash(
        {
            "status": TargetIdentificationStatus.TARGET_IDENTIFIED.value,
            "selected": selected,
            "diagnostics": diagnostics,
        }
    )
    if report.report_fingerprint != expected_report_fingerprint:
        raise ValueError("target artifact report fingerprint is not authenticated")
    bindings = dict(asset_bindings)
    if set(bindings) != set(config.source.assets):
        raise ValueError("target artifact bindings must cover exact source assets")
    for asset, binding in bindings.items():
        if not isinstance(binding, TargetDesignAssetBinding):
            raise TypeError("target artifact bindings must be typed")
        if binding.instrument_id != config.source.assets[asset]:
            raise ValueError(f"target artifact instrument differs for {asset}")
    target_fingerprints = config.target_fingerprints(selected)
    expected_groups = tuple(
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
            for kernel in config.comparator_config.kernels
            if kernel.enabled_for(timeframe)
            for side in ZoneSide
        )
    )
    selected_diagnostics = tuple(
        item for item in diagnostics if getattr(item, "target_tuple", None) == selected
    )
    if len(selected_diagnostics) != 1:
        raise ValueError("target artifact selected tuple diagnostic is missing")
    selected_groups = tuple(getattr(selected_diagnostics[0], "groups", ()))
    selected_group_keys = tuple(
        sorted(getattr(item, "group", None) for item in selected_groups)
    )
    if selected_group_keys != expected_groups:
        raise ValueError(
            "target artifact selected diagnostic does not cover exact expected groups"
        )
    for group_diagnostic in selected_groups:
        group = group_diagnostic.group
        binding = bindings[group.asset]
        if (
            group_diagnostic.source_manifest_id != binding.source_manifest_id
            or group_diagnostic.source_sha256 != binding.source_sha256
            or group_diagnostic.compiler_fingerprint
            != binding.selected_compiler_fingerprint
            or group_diagnostic.target_fingerprint
            != target_fingerprints[group.timeframe]
        ):
            raise ValueError(
                "target artifact selected diagnostic identity differs from binding"
            )
    target_family = target_family_fingerprint_from_choices(
        tuple(
            (
                _target_choice_id_for_tuple(target_tuple),
                tuple(
                    (timeframe, config.target_fingerprints(target_tuple)[timeframe])
                    for timeframe in sorted(config.source.ladder)
                ),
            )
            for target_tuple in configured
        )
    )
    return TargetDesignArtifact(
        target_design_yaml_sha256=target_design_yaml_sha256,
        config_fingerprint=config.config_fingerprint,
        source_window_fingerprint=_source_window_fingerprint(
            config.source,
            config.target_design_window,
            bindings,
        ),
        comparator_yaml_sha256=comparator_yaml_sha256,
        comparator_model_fingerprint=comparator_model_fingerprint,
        asset_bindings=bindings,
        tuple_diagnostics=diagnostics,
        report_fingerprint=report.report_fingerprint,
        selected_tuple=selected,
        target_fingerprints=target_fingerprints,
        target_family_fingerprint=target_family,
        null_algorithm_id=FEASIBLE_RANDOM_PRICE_ID,
        implementation_digest=implementation_digest,
        runtime_environment_receipt=runtime_environment_receipt,
        artifact_id="pending",
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetDesignArtifact:
    target_design_yaml_sha256: str
    config_fingerprint: str
    source_window_fingerprint: str
    comparator_yaml_sha256: str
    comparator_model_fingerprint: str
    asset_bindings: Mapping[str, TargetDesignAssetBinding]
    tuple_diagnostics: tuple[object, ...]
    report_fingerprint: str
    selected_tuple: TargetTuple
    target_fingerprints: Mapping[str, str]
    target_family_fingerprint: str
    null_algorithm_id: str
    implementation_digest: str
    runtime_environment_receipt: Mapping[str, Any]
    artifact_id: str
    artifact_sha256: str | None = None
    schema: str = TARGET_DESIGN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TARGET_DESIGN_SCHEMA:
            raise ValueError("unsupported target design artifact schema")
        for name in (
            "target_design_yaml_sha256",
            "config_fingerprint",
            "source_window_fingerprint",
            "comparator_yaml_sha256",
            "comparator_model_fingerprint",
            "report_fingerprint",
            "target_family_fingerprint",
            "implementation_digest",
        ):
            object.__setattr__(
                self, name, _sha256(getattr(self, name), f"artifact {name}")
            )
        if self.artifact_sha256 is not None:
            object.__setattr__(
                self,
                "artifact_sha256",
                _sha256(self.artifact_sha256, "artifact artifact_sha256"),
            )
        if not isinstance(self.selected_tuple, TargetTuple):
            raise TypeError("artifact selected_tuple must be TargetTuple")
        bindings = self.asset_bindings
        if not isinstance(bindings, Mapping) or not bindings:
            raise ValueError("artifact asset_bindings must be non-empty")
        if any(
            not isinstance(asset, str)
            or not asset.strip()
            or not isinstance(binding, TargetDesignAssetBinding)
            for asset, binding in bindings.items()
        ):
            raise TypeError(
                "artifact asset_bindings must map asset names to typed bindings"
            )
        diagnostics = tuple(
            _diagnostic_mapping(item) for item in self.tuple_diagnostics
        )
        if not diagnostics:
            raise ValueError("artifact tuple_diagnostics must be non-empty")
        diagnostic_statuses = tuple(
            getattr(item.get("status"), "value", item.get("status"))
            for item in diagnostics
        )
        if any(
            status
            not in {
                TargetTupleStatus.FEASIBLE.value,
                TargetTupleStatus.INSUFFICIENT.value,
                TargetTupleStatus.INVALID.value,
            }
            for status in diagnostic_statuses
        ):
            raise ValueError("artifact tuple diagnostics contain an unsupported status")
        diagnostic_tuples = tuple(
            _target_tuple_value(
                item.get("target_tuple"), "artifact diagnostic target_tuple"
            )
            for item in diagnostics
        )
        first_feasible = next(
            (
                target_tuple
                for target_tuple, status in zip(
                    diagnostic_tuples, diagnostic_statuses, strict=True
                )
                if status == TargetTupleStatus.FEASIBLE.value
            ),
            None,
        )
        if first_feasible is None or first_feasible != self.selected_tuple:
            raise ValueError(
                "artifact selected tuple is not the first feasible diagnostic"
            )
        expected_report_fingerprint = canonical_hash(
            {
                "status": TargetIdentificationStatus.TARGET_IDENTIFIED.value,
                "selected": self.selected_tuple,
                "diagnostics": diagnostics,
            }
        )
        if self.report_fingerprint != expected_report_fingerprint:
            raise ValueError("artifact report fingerprint is not TARGET_IDENTIFIED")
        target_fps = dict(self.target_fingerprints)
        if set(target_fps) != set(SCIENTIFIC_SOURCE_LADDER):
            raise ValueError("artifact target_fingerprints must cover exact six lanes")
        for timeframe, fingerprint in target_fps.items():
            _sha256(fingerprint, f"artifact target_fingerprints.{timeframe}")
        expected_target_fps = dict(_target_fingerprints_for_tuple(self.selected_tuple))
        if target_fps != expected_target_fps:
            raise ValueError("artifact target_fingerprints do not match selected tuple")
        expected_target_family = _target_family_fingerprint_for_tuples(
            diagnostic_tuples
        )
        if self.target_family_fingerprint != expected_target_family:
            raise ValueError("artifact target family fingerprint is not authenticated")
        if self.null_algorithm_id != FEASIBLE_RANDOM_PRICE_ID:
            raise ValueError("artifact null algorithm must be feasible_random_price@3")
        runtime = self.runtime_environment_receipt
        if not isinstance(runtime, Mapping) or not runtime:
            raise ValueError("artifact runtime_environment_receipt must be non-empty")
        object.__setattr__(
            self, "asset_bindings", MappingProxyType(dict(sorted(bindings.items())))
        )
        object.__setattr__(self, "tuple_diagnostics", diagnostics)
        object.__setattr__(
            self,
            "target_fingerprints",
            MappingProxyType(dict(sorted(target_fps.items()))),
        )
        object.__setattr__(self, "runtime_environment_receipt", _freeze(runtime))
        identity = canonical_hash(self.semantic_mapping())
        if self.artifact_id in {"", "pending"}:
            object.__setattr__(self, "artifact_id", identity)
        elif self.artifact_id != identity:
            raise ValueError("target design artifact ID mismatch")

    def semantic_mapping(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "target_design_yaml_sha256": self.target_design_yaml_sha256,
            "config_fingerprint": self.config_fingerprint,
            "source_window_fingerprint": self.source_window_fingerprint,
            "comparator_yaml_sha256": self.comparator_yaml_sha256,
            "comparator_model_fingerprint": self.comparator_model_fingerprint,
            "asset_bindings": {
                asset: binding.to_mapping()
                for asset, binding in self.asset_bindings.items()
            },
            "tuple_diagnostics": self.tuple_diagnostics,
            "report_fingerprint": self.report_fingerprint,
            "selected_tuple": self.selected_tuple,
            "target_fingerprints": self.target_fingerprints,
            "target_family_fingerprint": self.target_family_fingerprint,
            "null_algorithm_id": self.null_algorithm_id,
            "implementation_digest": self.implementation_digest,
            "runtime_environment_receipt": self.runtime_environment_receipt,
        }

    def to_mapping(self) -> Mapping[str, Any]:
        return {**self.semantic_mapping(), "artifact_id": self.artifact_id}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _artifact_path(root: str | Path, artifact: TargetDesignArtifact) -> Path:
    directory = Path(root)
    if directory.exists() and directory.is_symlink():
        raise ValueError("target artifact root must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"target-design-{artifact.artifact_id}.json"


def write_target_design_artifact(
    artifact: TargetDesignArtifact, artifact_root: str | Path
) -> Path:
    if not isinstance(artifact, TargetDesignArtifact):
        raise TypeError("write_target_design_artifact requires TargetDesignArtifact")
    path = _artifact_path(artifact_root, artifact)
    payload = (canonical_json(artifact.to_mapping()) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise ValueError("target design artifact collision")
        return path
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except FileExistsError as exc:
        raise ValueError("target design artifact collision") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _parse_artifact_mapping(payload: Mapping[str, Any]) -> TargetDesignArtifact:
    expected = set(TargetDesignArtifact.__dataclass_fields__) - {"artifact_sha256"}
    if set(payload) != expected:
        raise ValueError("target design artifact has unknown or missing keys")
    binding_values: dict[str, TargetDesignAssetBinding] = {}
    raw_bindings = _strict_mapping(payload["asset_bindings"], "artifact.asset_bindings")
    for asset, raw in raw_bindings.items():
        value = _strict_mapping(raw, f"artifact.asset_bindings.{asset}")
        _require_exact(value, _GLOBAL_BINDING_KEYS, f"artifact.asset_bindings.{asset}")
        binding_values[asset] = TargetDesignAssetBinding(**value)
    selected_raw = _strict_mapping(payload["selected_tuple"], "artifact.selected_tuple")
    _require_exact(
        selected_raw,
        {"source_horizon_bars", "reference_lookback", "barrier_multiplier"},
        "artifact.selected_tuple",
    )
    selected = TargetTuple(
        source_horizon_bars=selected_raw["source_horizon_bars"],
        reference_lookback=selected_raw["reference_lookback"],
        barrier_multiplier=selected_raw["barrier_multiplier"],
    )
    return TargetDesignArtifact(
        target_design_yaml_sha256=payload["target_design_yaml_sha256"],
        config_fingerprint=payload["config_fingerprint"],
        source_window_fingerprint=payload["source_window_fingerprint"],
        comparator_yaml_sha256=payload["comparator_yaml_sha256"],
        comparator_model_fingerprint=payload["comparator_model_fingerprint"],
        asset_bindings=binding_values,
        tuple_diagnostics=tuple(payload["tuple_diagnostics"]),
        report_fingerprint=payload["report_fingerprint"],
        selected_tuple=selected,
        target_fingerprints=payload["target_fingerprints"],
        target_family_fingerprint=payload["target_family_fingerprint"],
        null_algorithm_id=payload["null_algorithm_id"],
        implementation_digest=payload["implementation_digest"],
        runtime_environment_receipt=payload["runtime_environment_receipt"],
        artifact_id=payload["artifact_id"],
    )


def load_target_design_artifact(path: str | Path) -> TargetDesignArtifact:
    file_path = Path(path)
    if file_path.is_symlink():
        raise ValueError("target design artifact path must not be a symlink")
    try:
        payload = _decode_canonical(json.loads(file_path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ValueError("target design artifact is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise TypeError("target design artifact must be a mapping")
    artifact = _parse_artifact_mapping(payload)
    if artifact.artifact_id != canonical_hash(artifact.semantic_mapping()):
        raise ValueError("target design artifact authentication failed")
    return artifact


@dataclass(frozen=True, slots=True, kw_only=True)
class FrozenAssetTargetBinding:
    instrument_id: str
    source_manifest_id: str
    source_sha256: str
    source_slice_fingerprint: str
    baseline_episode_artifact_id: str
    common_risk_receipt_fingerprint: str
    selected_compiler_fingerprint: str

    def __post_init__(self) -> None:
        self_binding = TargetDesignAssetBinding(
            instrument_id=self.instrument_id,
            source_manifest_id=self.source_manifest_id,
            source_sha256=self.source_sha256,
            source_slice_fingerprint=self.source_slice_fingerprint,
            baseline_episode_artifact_id=self.baseline_episode_artifact_id,
            common_risk_receipt_fingerprint=self.common_risk_receipt_fingerprint,
            selected_compiler_fingerprint=self.selected_compiler_fingerprint,
        )
        for name in self_binding.__dataclass_fields__:
            object.__setattr__(self, name, getattr(self_binding, name))

    def to_mapping(self) -> Mapping[str, Any]:
        return {name: getattr(self, name) for name in _GLOBAL_BINDING_KEYS}


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetFreeze:
    target_design_artifact_path: str
    target_design_artifact_sha256: str
    target_design_artifact_id: str
    target_selection_report_fingerprint: str
    target_family_fingerprint: str
    baseline_structural_yaml_sha256: str
    baseline_model_fingerprint: str
    selected_tuple: TargetTuple
    target_fingerprints: Mapping[str, str]
    null_algorithm_id: str
    implementation_digest: str
    runtime_environment_fingerprint: str
    asset_bindings: Mapping[str, FrozenAssetTargetBinding]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_design_artifact_path",
            _nonempty_string(
                self.target_design_artifact_path,
                "target_freeze.target_design_artifact_path",
            ),
        )
        for name in (
            "target_design_artifact_sha256",
            "target_selection_report_fingerprint",
            "target_family_fingerprint",
            "baseline_structural_yaml_sha256",
            "baseline_model_fingerprint",
            "implementation_digest",
            "runtime_environment_fingerprint",
        ):
            object.__setattr__(
                self, name, _sha256(getattr(self, name), f"target_freeze.{name}")
            )
        object.__setattr__(
            self,
            "target_design_artifact_id",
            _sha256(
                self.target_design_artifact_id,
                "target_freeze.target_design_artifact_id",
            ),
        )
        if not isinstance(self.selected_tuple, TargetTuple):
            raise TypeError("target_freeze.selected_tuple must be TargetTuple")
        fps = dict(self.target_fingerprints)
        if set(fps) != set(SCIENTIFIC_SOURCE_LADDER):
            raise ValueError(
                "target_freeze target_fingerprints must cover exact six lanes"
            )
        for key, value in fps.items():
            _sha256(value, f"target_freeze.target_fingerprints.{key}")
        if self.null_algorithm_id != FEASIBLE_RANDOM_PRICE_ID:
            raise ValueError(
                "target_freeze null algorithm must be feasible_random_price@3"
            )
        bindings = self.asset_bindings
        if (
            not isinstance(bindings, Mapping)
            or not bindings
            or any(
                not isinstance(item, FrozenAssetTargetBinding)
                for item in bindings.values()
            )
        ):
            raise ValueError("target_freeze asset_bindings must be non-empty and typed")
        object.__setattr__(
            self, "target_fingerprints", MappingProxyType(dict(sorted(fps.items())))
        )
        object.__setattr__(
            self, "asset_bindings", MappingProxyType(dict(sorted(bindings.items())))
        )

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "target_design_artifact_path": self.target_design_artifact_path,
            "target_design_artifact_sha256": self.target_design_artifact_sha256,
            "target_design_artifact_id": self.target_design_artifact_id,
            "target_selection_report_fingerprint": self.target_selection_report_fingerprint,
            "target_family_fingerprint": self.target_family_fingerprint,
            "baseline_structural_yaml_sha256": self.baseline_structural_yaml_sha256,
            "baseline_model_fingerprint": self.baseline_model_fingerprint,
            "selected_tuple": self.selected_tuple,
            "target_fingerprints": self.target_fingerprints,
            "null_algorithm_id": self.null_algorithm_id,
            "implementation_digest": self.implementation_digest,
            "runtime_environment_fingerprint": self.runtime_environment_fingerprint,
            "asset_bindings": {
                asset: binding.to_mapping()
                for asset, binding in self.asset_bindings.items()
            },
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class GlobalGeometryInference:
    joint_utc_block: timedelta
    epoch: datetime
    repetitions: int
    confidence: float
    alpha_family: str
    degradation_margin: Any
    minimum_paired_reaction_clusters: int
    minimum_unique_issuance_cutoffs: int
    minimum_common_joint_utc_blocks: int
    minimum_asset_support: int

    def __post_init__(self) -> None:
        if not isinstance(
            self.joint_utc_block, timedelta
        ) or self.joint_utc_block <= timedelta(0):
            raise ValueError("global inference block must be positive")
        object.__setattr__(self, "epoch", _utc(self.epoch, "inference.epoch"))
        for name in (
            "repetitions",
            "minimum_paired_reaction_clusters",
            "minimum_unique_issuance_cutoffs",
            "minimum_common_joint_utc_blocks",
            "minimum_asset_support",
        ):
            object.__setattr__(
                self, name, _positive_int(getattr(self, name), f"inference.{name}")
            )
        if (
            not isinstance(self.confidence, (int, float))
            or isinstance(self.confidence, bool)
            or not 0 < float(self.confidence) < 1
        ):
            raise ValueError("inference.confidence must be in (0, 1)")
        if self.alpha_family != "bonferroni@1":
            raise ValueError("global geometry requires bonferroni@1")
        object.__setattr__(
            self,
            "degradation_margin",
            _finite_decimal(
                self.degradation_margin, "inference.degradation_margin", allow_zero=True
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GlobalGeometryResources:
    max_workers: int
    receipt_dir: str
    artifact_root: str
    max_peak_rss_bytes_per_asset: int
    max_artifact_bytes_per_asset: int
    max_wall_seconds_per_asset: int
    max_total_artifact_bytes: int

    def __post_init__(self) -> None:
        if _positive_int(self.max_workers, "resources.max_workers") != 1:
            raise ValueError("global resources.max_workers must equal one")
        for name in (
            "max_peak_rss_bytes_per_asset",
            "max_artifact_bytes_per_asset",
            "max_wall_seconds_per_asset",
            "max_total_artifact_bytes",
        ):
            object.__setattr__(
                self, name, _positive_int(getattr(self, name), f"resources.{name}")
            )
        object.__setattr__(
            self,
            "receipt_dir",
            _nonempty_string(self.receipt_dir, "resources.receipt_dir"),
        )
        object.__setattr__(
            self,
            "artifact_root",
            _nonempty_string(self.artifact_root, "resources.artifact_root"),
        )

    def validate_completed_run(
        self, *, peak_rss_bytes: int, artifact_bytes: int, wall_seconds: float
    ) -> None:
        """Validate one completed asset run against its declared ceilings."""

        for value, name in (
            (peak_rss_bytes, "peak_rss_bytes"),
            (artifact_bytes, "artifact_bytes"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, (int, float))
            or not math.isfinite(float(wall_seconds))
            or wall_seconds <= 0
        ):
            raise ValueError("wall_seconds must be finite and positive")
        if peak_rss_bytes > self.max_peak_rss_bytes_per_asset:
            raise ValueError("peak_rss_bytes exceeds the per-asset ceiling")
        if artifact_bytes > self.max_artifact_bytes_per_asset:
            raise ValueError("artifact_bytes exceeds the per-asset ceiling")
        if wall_seconds > self.max_wall_seconds_per_asset:
            raise ValueError("wall_seconds exceeds the per-asset ceiling")

    def validate_retained_artifacts(
        self, artifact_bytes_by_candidate_asset: Mapping[tuple[str, str], int]
    ) -> None:
        """Validate unique sealed-family EpisodeArtifact@2 bytes.

        The mapping covers only unique retained ``(candidate_id, asset)``
        EpisodeArtifact@2 directories for the sealed family.  The baseline is
        counted once per asset.  Repeat copies, receipts, target artifacts, and
        source caches are excluded.
        """

        if not isinstance(artifact_bytes_by_candidate_asset, Mapping):
            raise TypeError("retained artifacts must be a mapping")
        seen: set[tuple[str, str]] = set()
        total = 0
        for key, artifact_bytes in artifact_bytes_by_candidate_asset.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or any(not isinstance(part, str) or not part.strip() for part in key)
            ):
                raise ValueError(
                    "retained artifact keys must be non-empty (candidate_id, asset) tuples"
                )
            if key in seen:
                raise ValueError("retained artifact keys must be unique")
            seen.add(key)
            if (
                isinstance(artifact_bytes, bool)
                or not isinstance(artifact_bytes, int)
                or artifact_bytes <= 0
            ):
                raise ValueError("retained artifact bytes must be a positive integer")
            if artifact_bytes > self.max_artifact_bytes_per_asset:
                raise ValueError("retained artifact exceeds the per-asset ceiling")
            total += artifact_bytes
        if total > self.max_total_artifact_bytes:
            raise ValueError("retained artifact bytes exceed the total ceiling")


@dataclass(frozen=True, slots=True, kw_only=True)
class GlobalGeometrySearch:
    sampler_id: str
    seed: str
    trial_budget: int
    baseline_structural_yaml: str
    parameters: Mapping[str, Mapping[str, tuple[Any, ...]]]
    baseline_structural_yaml_sha256: str
    baseline_config: ResolvedSRV2Config

    def __post_init__(self) -> None:
        if self.sampler_id != "sealed_global_finite_choices@1":
            raise ValueError("unsupported global search sampler")
        object.__setattr__(self, "seed", _nonempty_string(self.seed, "search.seed"))
        object.__setattr__(
            self,
            "trial_budget",
            _positive_int(self.trial_budget, "search.trial_budget"),
        )
        object.__setattr__(
            self,
            "baseline_structural_yaml",
            _nonempty_string(
                self.baseline_structural_yaml, "search.baseline_structural_yaml"
            ),
        )
        object.__setattr__(
            self,
            "baseline_structural_yaml_sha256",
            _sha256(
                self.baseline_structural_yaml_sha256,
                "search.baseline_structural_yaml_sha256",
            ),
        )
        if not isinstance(self.baseline_config, ResolvedSRV2Config):
            raise TypeError("search baseline_config must be ResolvedSRV2Config")
        object.__setattr__(self, "parameters", _freeze(self.parameters))

    @property
    def parameter_choices(self) -> Mapping[str, Mapping[str, tuple[Any, ...]]]:
        return self.parameters


@dataclass(frozen=True, slots=True, kw_only=True)
class GlobalGeometrySplits:
    target_design: OptimizerWindow
    geometry_train: OptimizerWindow
    geometry_validation: OptimizerWindow
    embargo: OptimizerWindow
    maximum_horizon: timedelta

    def __post_init__(self) -> None:
        windows = (
            self.target_design,
            self.geometry_train,
            self.geometry_validation,
            self.embargo,
        )
        if any(not isinstance(window, OptimizerWindow) for window in windows):
            raise TypeError("global split windows must be OptimizerWindow values")
        if self.geometry_train.start - self.target_design.end < self.maximum_horizon:
            raise ValueError("target design to geometry train purge gap is too short")
        if (
            self.geometry_train.end > self.embargo.start
            or self.embargo.end > self.geometry_validation.start
        ):
            raise ValueError("embargo must lie between train and validation")
        if self.embargo.end - self.embargo.start < self.maximum_horizon:
            raise ValueError("embargo must cover the selected maximum horizon")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedGlobalGeometryConfig:
    schema: str
    source: OptimizerSource
    splits: GlobalGeometrySplits
    target_freeze: TargetFreeze
    search: GlobalGeometrySearch
    inference: GlobalGeometryInference
    resources: GlobalGeometryResources
    ranking_policy_id: str
    config_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema != GLOBAL_GEOMETRY_SCHEMA:
            raise ValueError(f"unsupported global geometry schema: {self.schema}")
        if self.search.baseline_config.ladder != self.source.ladder:
            raise ValueError("global baseline ladder differs from source ladder")
        if self.search.baseline_config.trigger_timeframe != self.source.ladder[-1]:
            raise ValueError("global baseline trigger must be finest source timeframe")
        if self.target_freeze.asset_bindings.keys() != self.source.assets.keys():
            raise ValueError(
                "global target freeze asset bindings differ from source assets"
            )
        object.__setattr__(
            self,
            "config_fingerprint",
            _sha256(self.config_fingerprint, "global config_fingerprint"),
        )

    @property
    def baseline_config(self) -> ResolvedSRV2Config:
        return self.search.baseline_config

    @property
    def maximum_horizon(self) -> timedelta:
        return self.splits.maximum_horizon


def _load_baseline(search_raw: Mapping[str, Any]) -> tuple[ResolvedSRV2Config, str]:
    path = Path(
        _nonempty_string(
            search_raw["baseline_structural_yaml"], "search.baseline_structural_yaml"
        )
    )
    raw = load_sr_v2_yaml(path)
    baseline = SRV2ConfigResolver(raw).resolve()
    return baseline, hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_binding(asset: str, raw: object, name: str) -> FrozenAssetTargetBinding:
    value = _strict_mapping(raw, name)
    _require_exact(value, _GLOBAL_BINDING_KEYS, name)
    return FrozenAssetTargetBinding(**value)


def _authenticate_target_freeze(
    raw: Mapping[str, Any], source: OptimizerSource
) -> TargetFreeze:
    value = _strict_mapping(raw, "target_freeze")
    _require_exact(value, _GLOBAL_FREEZE_KEYS, "target_freeze")
    path = Path(
        _nonempty_string(
            value["target_design_artifact_path"],
            "target_freeze.target_design_artifact_path",
        )
    )
    artifact = load_target_design_artifact(path)
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if file_sha != _sha256(
        value["target_design_artifact_sha256"],
        "target_freeze.target_design_artifact_sha256",
    ):
        raise ValueError("target design artifact file SHA mismatch")
    if artifact.artifact_id != value["target_design_artifact_id"]:
        raise ValueError("target design artifact ID mismatch")
    if artifact.report_fingerprint != value["target_selection_report_fingerprint"]:
        raise ValueError("target selection report fingerprint mismatch")
    if artifact.target_family_fingerprint != value["target_family_fingerprint"]:
        raise ValueError("target family fingerprint mismatch")
    if artifact.comparator_yaml_sha256 != value["baseline_structural_yaml_sha256"]:
        raise ValueError("baseline structural YAML SHA differs from target artifact")
    if artifact.comparator_model_fingerprint != value["baseline_model_fingerprint"]:
        raise ValueError("baseline model fingerprint differs from target artifact")
    runtime_fingerprint = _sha256(
        value["runtime_environment_fingerprint"],
        "target_freeze.runtime_environment_fingerprint",
    )
    if runtime_fingerprint != canonical_hash(artifact.runtime_environment_receipt):
        raise ValueError(
            "target freeze runtime environment differs from target artifact"
        )
    selected_raw = _strict_mapping(
        value["selected_tuple"], "target_freeze.selected_tuple"
    )
    selected = TargetTuple(**selected_raw)
    if selected != artifact.selected_tuple:
        raise ValueError("selected target tuple differs from target artifact")
    target_fps = dict(value["target_fingerprints"])
    if target_fps != dict(artifact.target_fingerprints):
        raise ValueError("target fingerprints differ from target artifact")
    if target_fps != dict(_target_fingerprints_for_tuple(selected)):
        raise ValueError("target fingerprints do not match selected tuple semantics")
    diagnostic_tuples = tuple(
        _target_tuple_value(
            _diagnostic_mapping(item).get("target_tuple"),
            "target artifact diagnostic target_tuple",
        )
        for item in artifact.tuple_diagnostics
    )
    if (
        _target_family_fingerprint_for_tuples(diagnostic_tuples)
        != value["target_family_fingerprint"]
    ):
        raise ValueError("target family fingerprint does not match tuple semantics")
    if value["null_algorithm_id"] != artifact.null_algorithm_id:
        raise ValueError("target null algorithm differs from target artifact")
    if value["implementation_digest"] != artifact.implementation_digest:
        raise ValueError("target implementation digest differs from target artifact")
    raw_bindings = _strict_mapping(
        value["asset_bindings"], "target_freeze.asset_bindings"
    )
    if set(raw_bindings) != set(source.assets):
        raise ValueError(
            "target freeze asset bindings do not cover exact source assets"
        )
    bindings = {
        asset: _parse_binding(asset, item, f"target_freeze.asset_bindings.{asset}")
        for asset, item in raw_bindings.items()
    }
    for asset, binding in bindings.items():
        if binding.instrument_id != source.assets[asset]:
            raise ValueError(f"target freeze instrument differs for {asset}")
        artifact_binding = artifact.asset_bindings.get(asset)
        if (
            artifact_binding is None
            or binding.to_mapping() != artifact_binding.to_mapping()
        ):
            raise ValueError(
                f"target freeze binding differs from target artifact for {asset}"
            )
    return TargetFreeze(
        target_design_artifact_path=str(path),
        target_design_artifact_sha256=value["target_design_artifact_sha256"],
        target_design_artifact_id=value["target_design_artifact_id"],
        target_selection_report_fingerprint=value[
            "target_selection_report_fingerprint"
        ],
        target_family_fingerprint=value["target_family_fingerprint"],
        baseline_structural_yaml_sha256=value["baseline_structural_yaml_sha256"],
        baseline_model_fingerprint=value["baseline_model_fingerprint"],
        selected_tuple=selected,
        target_fingerprints=target_fps,
        null_algorithm_id=value["null_algorithm_id"],
        implementation_digest=value["implementation_digest"],
        runtime_environment_fingerprint=value["runtime_environment_fingerprint"],
        asset_bindings=bindings,
    )


def resolve_global_geometry_config(
    raw: Mapping[str, Any],
) -> ResolvedGlobalGeometryConfig:
    root = _strict_mapping(raw, "global_geometry")
    _require_exact(root, _GLOBAL_KEYS, "global_geometry")
    if root["schema"] != GLOBAL_GEOMETRY_SCHEMA:
        raise ValueError(f"unsupported global geometry schema: {root['schema']}")
    source = _source(root["source"])
    splits_raw = _strict_mapping(root["splits"], "splits")
    _require_exact(splits_raw, set(_SPLIT_NAMES), "splits")
    split_windows = {
        name: _window(splits_raw[name], f"splits.{name}") for name in _SPLIT_NAMES
    }
    for name, window in split_windows.items():
        _inside(window, source, f"splits.{name}")
    freeze = _authenticate_target_freeze(root["target_freeze"], source)
    target_artifact = load_target_design_artifact(freeze.target_design_artifact_path)
    expected_source_window = _source_window_fingerprint(
        source,
        split_windows["target_design"],
        freeze.asset_bindings,
    )
    if target_artifact.source_window_fingerprint != expected_source_window:
        raise ValueError(
            "global source or target-design window differs from target artifact"
        )
    maximum = max(
        TIMEFRAME_DURATIONS[timeframe] * freeze.selected_tuple.source_horizon_bars
        for timeframe in source.ladder
    )
    splits = GlobalGeometrySplits(
        target_design=split_windows["target_design"],
        geometry_train=split_windows["geometry_train"],
        geometry_validation=split_windows["geometry_validation"],
        embargo=split_windows["embargo"],
        maximum_horizon=maximum,
    )
    search_raw = _strict_mapping(root["search"], "search")
    _require_exact(search_raw, _GLOBAL_SEARCH_KEYS, "search")
    baseline, baseline_sha = _load_baseline(search_raw)
    if baseline_sha != freeze.baseline_structural_yaml_sha256:
        raise ValueError(
            "search baseline structural YAML SHA differs from target freeze"
        )
    if baseline.config_fingerprint != freeze.baseline_model_fingerprint:
        raise ValueError("search baseline model fingerprint differs from target freeze")
    # Reuse the legacy strict finite-parameter validator, then expose the
    # exact nested map under the development schema.
    search_validator = SearchConfig(
        sampler_id=search_raw["sampler_id"],
        seed=search_raw["seed"],
        trial_budget=search_raw["trial_budget"],
        baseline_structural_yaml=str(Path(search_raw["baseline_structural_yaml"])),
        baseline_structural_yaml_sha256=baseline_sha,
        parameter_choices=search_raw["parameters"],
        baseline_config=baseline,
    )
    search = GlobalGeometrySearch(
        sampler_id=search_validator.sampler_id,
        seed=search_validator.seed,
        trial_budget=search_validator.trial_budget,
        baseline_structural_yaml=search_validator.baseline_structural_yaml,
        parameters=search_validator.parameter_choices,
        baseline_structural_yaml_sha256=baseline_sha,
        baseline_config=baseline,
    )
    inference_raw = _strict_mapping(root["inference"], "inference")
    _require_exact(inference_raw, _GLOBAL_INFERENCE_KEYS, "inference")
    inference = GlobalGeometryInference(
        joint_utc_block=duration(
            inference_raw["joint_utc_block"], "inference.joint_utc_block"
        ),
        epoch=_utc(inference_raw["epoch"], "inference.epoch"),
        repetitions=inference_raw["repetitions"],
        confidence=inference_raw["confidence"],
        alpha_family=inference_raw["alpha_family"],
        degradation_margin=inference_raw["degradation_margin"],
        minimum_paired_reaction_clusters=inference_raw[
            "minimum_paired_reaction_clusters"
        ],
        minimum_unique_issuance_cutoffs=inference_raw[
            "minimum_unique_issuance_cutoffs"
        ],
        minimum_common_joint_utc_blocks=inference_raw[
            "minimum_common_joint_utc_blocks"
        ],
        minimum_asset_support=inference_raw["minimum_asset_support"],
    )
    if inference.joint_utc_block < maximum:
        raise ValueError("global inference block must cover selected maximum horizon")
    if inference.minimum_asset_support > len(source.assets):
        raise ValueError("global minimum_asset_support exceeds asset count")
    resources_raw = _strict_mapping(root["resources"], "resources")
    _require_exact(resources_raw, _GLOBAL_RESOURCE_KEYS, "resources")
    resources = GlobalGeometryResources(**resources_raw)
    ranking_policy_id = _nonempty_string(root["ranking_policy_id"], "ranking_policy_id")
    if ranking_policy_id != "worst_tf_kernel_side_then_equal_cell@2":
        raise ValueError("unsupported geometry ranking policy")
    pending = ResolvedGlobalGeometryConfig(
        schema=GLOBAL_GEOMETRY_SCHEMA,
        source=source,
        splits=splits,
        target_freeze=freeze,
        search=search,
        inference=inference,
        resources=resources,
        ranking_policy_id=ranking_policy_id,
        config_fingerprint="0" * 64,
    )
    object.__setattr__(
        pending,
        "config_fingerprint",
        canonical_hash(_global_geometry_mapping(pending)),
    )
    return pending


def load_global_geometry_config(path: str | Path) -> ResolvedGlobalGeometryConfig:
    return resolve_global_geometry_config(load_optimizer_yaml(path))


def _global_geometry_mapping(
    config: ResolvedGlobalGeometryConfig,
) -> Mapping[str, Any]:
    source = config.source
    splits = config.splits
    search = config.search
    inference = config.inference
    resources = config.resources
    return {
        "schema": config.schema,
        "source": {
            "venue": source.venue,
            "assets": dict(source.assets),
            "ladder": source.ladder,
            "start": source.start,
            "end": source.end,
            "acquisition_policy": source.acquisition_policy,
            "source_mode": source.source_mode,
        },
        "splits": {
            "target_design": {
                "start": splits.target_design.start,
                "end": splits.target_design.end,
            },
            "geometry_train": {
                "start": splits.geometry_train.start,
                "end": splits.geometry_train.end,
            },
            "geometry_validation": {
                "start": splits.geometry_validation.start,
                "end": splits.geometry_validation.end,
            },
            "embargo": {
                "start": splits.embargo.start,
                "end": splits.embargo.end,
            },
        },
        "target_freeze": {
            "target_design_artifact_sha256": (
                config.target_freeze.target_design_artifact_sha256
            ),
            "target_design_artifact_id": config.target_freeze.target_design_artifact_id,
            "target_selection_report_fingerprint": (
                config.target_freeze.target_selection_report_fingerprint
            ),
            "target_family_fingerprint": config.target_freeze.target_family_fingerprint,
            "baseline_structural_yaml_sha256": (
                config.target_freeze.baseline_structural_yaml_sha256
            ),
            "baseline_model_fingerprint": config.target_freeze.baseline_model_fingerprint,
            "selected_tuple": config.target_freeze.selected_tuple,
            "target_fingerprints": config.target_freeze.target_fingerprints,
            "null_algorithm_id": config.target_freeze.null_algorithm_id,
            "implementation_digest": config.target_freeze.implementation_digest,
            "runtime_environment_fingerprint": (
                config.target_freeze.runtime_environment_fingerprint
            ),
            "asset_bindings": {
                asset: binding.to_mapping()
                for asset, binding in config.target_freeze.asset_bindings.items()
            },
        },
        "search": {
            "sampler_id": search.sampler_id,
            "seed": search.seed,
            "trial_budget": search.trial_budget,
            "parameters": search.parameters,
            "baseline_structural_yaml_sha256": search.baseline_structural_yaml_sha256,
            "baseline_model_fingerprint": search.baseline_config.config_fingerprint,
        },
        "inference": {
            "joint_utc_block": inference.joint_utc_block,
            "epoch": inference.epoch,
            "repetitions": inference.repetitions,
            "confidence": inference.confidence,
            "alpha_family": inference.alpha_family,
            "degradation_margin": inference.degradation_margin,
            "minimum_paired_reaction_clusters": inference.minimum_paired_reaction_clusters,
            "minimum_unique_issuance_cutoffs": inference.minimum_unique_issuance_cutoffs,
            "minimum_common_joint_utc_blocks": inference.minimum_common_joint_utc_blocks,
            "minimum_asset_support": inference.minimum_asset_support,
        },
        "resources": {
            "max_workers": resources.max_workers,
            "max_peak_rss_bytes_per_asset": resources.max_peak_rss_bytes_per_asset,
            "max_artifact_bytes_per_asset": resources.max_artifact_bytes_per_asset,
            "max_wall_seconds_per_asset": resources.max_wall_seconds_per_asset,
            "max_total_artifact_bytes": resources.max_total_artifact_bytes,
        },
        "ranking_policy_id": config.ranking_policy_id,
    }


def implementation_digest(repo_root: str | Path) -> str:
    """Return the code-owned implementation digest used by target freezes."""

    root = Path(repo_root)
    prefixes = (
        root / "src/libs/models/sr_v2/config",
        root / "src/libs/models/sr_v2/domain",
        root / "src/libs/models/sr_v2/features",
        root / "src/libs/models/sr_v2/forecast",
        root / "src/libs/models/sr_v2/kernels",
        root / "src/libs/models/sr_v2/lifecycle",
        root / "src/libs/models/sr_v2/serialization",
        root / "src/libs/models/sr_v2/research",
    )
    explicit = (
        root / "src/libs/models/sr_v2/contracts.py",
        root / "src/libs/models/sr_v2/structural.py",
        root / "src/libs/models/sr_v2/runtime/offline.py",
        root / "src/libs/models/sr_v2/research_lab/data.py",
        root / "src/libs/models/sr_v2/research_lab/episode_evidence.py",
        root / "src/libs/models/sr_v2/research_lab/scientific_compiler.py",
        root / "src/libs/market_data/__init__.py",
        root / "src/libs/market_data/binance_native.py",
    )
    paths = set(explicit)
    for prefix in prefixes:
        if prefix.exists():
            paths.update(prefix.rglob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(path for path in paths if path.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def runtime_environment_receipt(repo_root: str | Path) -> Mapping[str, Any]:
    pyproject = Path(repo_root) / "pyproject.toml"
    distributions: list[tuple[str, str]] = []
    for name in _RUNTIME_CRITICAL_DISTRIBUTIONS:
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        canonical_name = distribution.metadata.get("Name", name)
        distributions.append((canonical_name, distribution.version))
    distributions.sort(key=lambda item: item[0].lower())
    return {
        "schema": "sr_v2.runtime_environment_receipt@1",
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "python_abi": getattr(sys, "abiflags", ""),
        "os": platform.system(),
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
        "pyproject_sha256": hashlib.sha256(pyproject.read_bytes()).hexdigest(),
        "third_party_distributions": tuple(distributions),
    }


__all__ = [
    "GLOBAL_GEOMETRY_SCHEMA",
    "SCIENTIFIC_SOURCE_LADDER",
    "TARGET_DESIGN_D_PROPOSAL_POLICY_ID",
    "TARGET_DESIGN_N_PROPOSAL_POLICY_ID",
    "TARGET_DESIGN_OBSERVATION_TIMEFRAME",
    "TARGET_DESIGN_REFERENCE_VOLATILITY_ID",
    "TARGET_DESIGN_SCHEMA",
    "TARGET_DESIGN_SELECTION_POLICY_ID",
    "FrozenAssetTargetBinding",
    "GlobalGeometryInference",
    "GlobalGeometryResources",
    "GlobalGeometrySearch",
    "GlobalGeometrySplits",
    "ResolvedGlobalGeometryConfig",
    "ResolvedTargetDesignConfig",
    "TargetDesignArtifact",
    "TargetDesignAssetBinding",
    "TargetDesignBarrier",
    "TargetDesignHorizon",
    "TargetDesignInference",
    "TargetDesignReferenceVolatility",
    "TargetDesignResources",
    "TargetFreeze",
    "build_target_design_artifact",
    "compile_global_candidate_family",
    "implementation_digest",
    "load_global_geometry_config",
    "load_target_design_artifact",
    "load_target_design_config",
    "resolve_global_geometry_config",
    "resolve_target_design_config",
    "runtime_environment_receipt",
    "write_target_design_artifact",
]
