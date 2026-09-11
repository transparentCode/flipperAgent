"""Manifest-bound Phase 1 study coordination and explicit conclusion gates."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from ..config.resolver import ResolvedSRV2Config, SRV2ConfigResolver
from ..config.schema import (
    MAX_HORIZON,
    MAX_HORIZONS,
    TIMEFRAME_DURATIONS,
    bounded_int,
    duration,
    finite_probability,
    require_exact_keys,
    require_mapping,
)
from ..contracts import require_utc
from ..domain.bars import SRBar
from ..domain.identity import canonical_hash
from ..forecast.targets import label_forecast, target_fingerprint
from .consumption import claim_consumption
from .labels import target_provenance_fingerprint
from .metrics import ResearchMetrics, compare_against_nulls, evaluate_observations
from .observations import ResearchObservation, canonical_matching_strata
from .placebos import build_random_price_nulls, build_shuffled_time_nulls
from .source import ProtectedManifest, load_protected_manifest
from .splits import ChronologicalSplits, validate_splits

CONCLUSION_GATE_KEYS = frozenset(
    {
        "positive_requires_all_groups",
        "negative_requires_adequate_support",
        "require_paired_deltas",
        "require_ece",
        "require_no_resolved_reversal",
        "allow_significant_primary_aggregate_degradation",
    }
)
SR_V2_RESEARCH_CODE_VERSION = "sr_v2.research.phase1@2"


def _normalize_forecasts(
    forecasts: Mapping[tuple[object, object], Mapping[Any, float]],
) -> Mapping[str, Mapping[str, float]]:
    return {
        f"{key[0]}|{key[1]}": {
            getattr(outcome, "value", str(outcome)): float(probability)
            for outcome, probability in probabilities.items()
        }
        for key, probabilities in forecasts.items()
    }


def _forecast_fingerprint(value: Mapping[str, Mapping[tuple[object, object], Mapping[Any, float]]]) -> str:
    return canonical_hash({group: _normalize_forecasts(forecasts) for group, forecasts in value.items()})


def _sha256_identity(value: object, name: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be a 64-character SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be hexadecimal") from exc
    return value.lower()


def _canonical_matching_strata(values: Iterable[object]) -> tuple[str, ...]:
    return canonical_matching_strata(tuple(values))


@dataclass(frozen=True, slots=True, kw_only=True)
class NullSpec:
    name: str
    algorithm: str
    version: str
    seed: str
    max_abs_shift_atr: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("null specification name must be non-empty")
        if self.algorithm not in {"random_price", "shuffled_time"}:
            raise ValueError(f"unsupported matched null algorithm: {self.algorithm}")
        if self.version != "1":
            raise ValueError(f"unsupported matched null version: {self.algorithm}@{self.version}")
        if not isinstance(self.seed, str) or not self.seed.strip():
            raise ValueError("null specification seed must be non-empty")
        if self.algorithm == "random_price":
            if not isinstance(self.max_abs_shift_atr, Decimal) or not self.max_abs_shift_atr.is_finite() or self.max_abs_shift_atr <= 0:
                raise ValueError("random_price nulls require a positive max_abs_shift_atr")
        elif self.max_abs_shift_atr is not None:
            raise ValueError("shuffled_time nulls must not carry max_abs_shift_atr")

    @property
    def identifier(self) -> str:
        return f"{self.algorithm}@{self.version}"


@dataclass(frozen=True, slots=True, kw_only=True)
class TrialConfig:
    version: int
    model_path: str
    model_sha256: str
    model_config_fingerprint: str
    model_catalog_fingerprint: str
    observation_timeframe: str
    observation_duration: timedelta
    horizons: tuple[timedelta, ...]
    bounce_excursion_atr: Decimal
    target_break_buffer_atr: Decimal
    target_break_confirmation_bars: int
    data_status: str
    protected_manifest: str | None
    protected_manifest_sha256: str | None
    protected_manifest_content_id: str | None
    evidence_root: str | None
    splits: ChronologicalSplits
    null_specs: tuple[NullSpec, ...]
    matching_strata: tuple[str, ...]
    bootstrap_repetitions: int
    bootstrap_block: timedelta
    bootstrap_epoch: datetime
    confidence: float
    ece_bins: int
    minimum_uncensored_lineages: int
    minimum_touched_lineages: int
    maximum_ece: float
    conclusion_gates: Mapping[str, bool]
    config_fingerprint: str

    def __post_init__(self) -> None:
        if self.version != 2:
            raise ValueError("unsupported trial config version")
        for name in ("model_path", "model_config_fingerprint", "model_catalog_fingerprint"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        _sha256_identity(self.model_sha256, "model_sha256", required=True)
        if not self.horizons or len(set(self.horizons)) != len(self.horizons):
            raise ValueError("trial horizons must be non-empty and unique")
        if not isinstance(self.observation_timeframe, str) or self.observation_timeframe not in TIMEFRAME_DURATIONS:
            raise ValueError("observation_timeframe must be a supported timeframe")
        if not isinstance(self.observation_duration, timedelta) or self.observation_duration != TIMEFRAME_DURATIONS[self.observation_timeframe]:
            raise ValueError("observation_duration must derive from observation_timeframe")
        if self.bounce_excursion_atr <= 0 or self.target_break_buffer_atr <= 0:
            raise ValueError("trial target thresholds must be positive")
        if self.target_break_confirmation_bars <= 0:
            raise ValueError("trial target confirmation must be positive")
        require_utc(self.bootstrap_epoch, field_name="bootstrap_epoch")
        if not self.null_specs or len({item.name for item in self.null_specs}) != len(self.null_specs):
            raise ValueError("trial null specifications must be unique")
        if any(not isinstance(item, NullSpec) for item in self.null_specs):
            raise TypeError("null_specs must contain NullSpec values")
        if self.data_status not in {"PENDING_PROTECTED_MANIFEST", "READY"}:
            raise ValueError("unsupported trial data status")
        if self.data_status == "READY":
            if not self.protected_manifest:
                raise ValueError("READY trials require a protected manifest")
            _sha256_identity(self.protected_manifest_sha256, "protected_manifest_sha256", required=True)
            if not isinstance(self.protected_manifest_content_id, str) or not self.protected_manifest_content_id.strip():
                raise ValueError("READY trials require protected manifest content ID")
        elif self.protected_manifest or self.protected_manifest_sha256 or self.protected_manifest_content_id:
            raise ValueError("pending trials must leave protected manifest identity null")
        if self.evidence_root is not None and (not isinstance(self.evidence_root, str) or not self.evidence_root.strip()):
            raise ValueError("evidence_root must be a non-empty path or null")
        selected_strata = canonical_matching_strata(self.matching_strata)
        if tuple(self.matching_strata) != selected_strata:
            raise ValueError("matching_strata must be a unique supported selection")
        object.__setattr__(self, "matching_strata", selected_strata)
        if self.bootstrap_repetitions <= 0 or self.bootstrap_block <= timedelta(0):
            raise ValueError("bootstrap settings must be positive")
        if not 0 < self.confidence < 1:
            raise ValueError("confidence must be in (0, 1)")
        if self.ece_bins <= 0 or self.minimum_uncensored_lineages <= 0 or self.minimum_touched_lineages <= 0:
            raise ValueError("trial support and ECE bins must be positive")
        if not 0 <= self.maximum_ece <= 1:
            raise ValueError("maximum_ece must be in [0, 1]")
        gates = dict(self.conclusion_gates)
        if set(gates) != CONCLUSION_GATE_KEYS or any(not isinstance(value, bool) for value in gates.values()):
            raise ValueError("conclusion_gates must match the approved boolean schema exactly")
        object.__setattr__(self, "conclusion_gates", MappingProxyType(gates))

    @property
    def null_seeds(self) -> tuple[str, ...]:
        return tuple(item.seed for item in self.null_specs)

    @property
    def target_fingerprint(self) -> str:
        return target_fingerprint(
            horizons=self.horizons,
            bounce_excursion_atr=self.bounce_excursion_atr,
            break_buffer_atr=self.target_break_buffer_atr,
            break_confirmation_bars=self.target_break_confirmation_bars,
            observation_timeframe=self.observation_timeframe,
            observation_duration=self.observation_duration,
        )


def _window(value: object, name: str) -> tuple[datetime, datetime]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must contain start and end")
    result = tuple(
        item if isinstance(item, datetime) else datetime.fromisoformat(str(item))
        for item in value
    )
    if result[0].tzinfo != UTC or result[1].tzinfo != UTC:
        raise ValueError(f"{name} must use UTC")
    if result[1] <= result[0]:
        raise ValueError(f"{name} end must follow start")
    return result  # type: ignore[return-value]


def load_trial_config(path: str | Path) -> TrialConfig:
    class _Loader(yaml.SafeLoader):
        pass

    def construct_mapping(loader: yaml.Loader, node: yaml.Node, deep: bool = False):
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError(f"duplicate trial config key: {key}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    _Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
    raw = yaml.load(Path(path).read_bytes(), Loader=_Loader)
    if not isinstance(raw, Mapping):
        raise TypeError("trial config root must be a mapping")
    require_exact_keys(raw, {"version", "model", "targets", "research"}, "trial config")
    model = require_mapping(raw["model"], "trial.model")
    require_exact_keys(model, {"path"}, "trial.model")
    model_path = (Path(path).parent / str(model["path"])).resolve()
    if model_path.is_symlink() or not model_path.is_file():
        raise ValueError("trial.model.path must resolve to a regular file")
    model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
    model_config = SRV2ConfigResolver.from_yaml(model_path).resolve()
    targets = require_mapping(raw["targets"], "trial.targets")
    require_exact_keys(targets, {"horizons", "bounce_excursion_atr"}, "trial.targets")
    horizons_raw = targets["horizons"]
    if not isinstance(horizons_raw, (list, tuple)) or not horizons_raw:
        raise ValueError("trial.targets.horizons must be a non-empty sequence")
    if len(horizons_raw) > MAX_HORIZONS:
        raise ValueError("trial.targets.horizons exceeds the supported count")
    horizons = tuple(duration(item, "trial target horizon") for item in horizons_raw)
    if any(item > MAX_HORIZON for item in horizons):
        raise ValueError("trial target horizon exceeds the supported maximum")
    try:
        bounce = Decimal(str(targets["bounce_excursion_atr"]))
    except Exception as exc:
        raise ValueError("trial.targets.bounce_excursion_atr must be numeric") from exc
    if not bounce.is_finite() or bounce <= 0:
        raise ValueError("trial.targets.bounce_excursion_atr must be positive")
    research = require_mapping(raw["research"], "research")
    required = {
        "data_status", "protected_manifest", "protected_manifest_sha256", "protected_manifest_content_id", "evidence_root",
        "train_window", "calibration_window", "validation_window", "holdout_window", "embargo", "matching_strata",
        "nulls", "bootstrap", "calibration", "support", "conclusion_gates",
    }
    require_exact_keys(research, required, "trial.research")
    gates = require_mapping(research["conclusion_gates"], "research.conclusion_gates")
    if set(gates) != CONCLUSION_GATE_KEYS:
        raise ValueError("research conclusion_gates keys do not match exactly")
    splits = ChronologicalSplits(
        development_train=_window(research["train_window"], "train_window"),
        calibration=_window(research["calibration_window"], "calibration_window"),
        validation=_window(research["validation_window"], "validation_window"),
        protected_holdout=_window(research["holdout_window"], "holdout_window"),
        embargo=duration(research["embargo"], "research.embargo"),
    )
    bootstrap = require_mapping(research["bootstrap"], "trial.research.bootstrap")
    require_exact_keys(bootstrap, {"repetitions", "block", "epoch", "confidence"}, "trial.research.bootstrap")
    bootstrap_block = duration(bootstrap["block"], "trial.research.bootstrap.block")
    bootstrap_epoch = bootstrap["epoch"] if isinstance(bootstrap["epoch"], datetime) else datetime.fromisoformat(str(bootstrap["epoch"]))
    require_utc(bootstrap_epoch, field_name="bootstrap_epoch")
    confidence = finite_probability(bootstrap["confidence"], "trial.research.bootstrap.confidence")
    validate_splits(splits, max_horizon=max(horizons))
    nulls_raw = research["nulls"]
    if not isinstance(nulls_raw, (list, tuple)) or not nulls_raw:
        raise ValueError("trial.research.nulls must be a non-empty sequence")
    null_specs = []
    for index, item in enumerate(nulls_raw):
        entry = require_mapping(item, f"trial.research.nulls[{index}]")
        keys = {"name", "algorithm", "version", "seed", "max_abs_shift_atr"}
        require_exact_keys(entry, keys, f"trial.research.nulls[{index}]")
        for field_name in ("name", "algorithm", "version", "seed"):
            if not isinstance(entry[field_name], str) or not entry[field_name].strip():
                raise ValueError(f"trial.research.nulls[{index}].{field_name} must be a non-empty string")
        try:
            max_shift = None if entry["max_abs_shift_atr"] is None else Decimal(str(entry["max_abs_shift_atr"]))
        except Exception as exc:
            raise ValueError(f"trial.research.nulls[{index}].max_abs_shift_atr must be numeric or null") from exc
        if max_shift is not None and (not max_shift.is_finite() or max_shift <= 0):
            raise ValueError("null max_abs_shift_atr must be positive")
        null_specs.append(NullSpec(name=entry["name"], algorithm=entry["algorithm"], version=entry["version"], seed=entry["seed"], max_abs_shift_atr=max_shift))
    calibration = require_mapping(research["calibration"], "trial.research.calibration")
    require_exact_keys(calibration, {"ece_bins", "maximum_ece"}, "trial.research.calibration")
    support = require_mapping(research["support"], "trial.research.support")
    require_exact_keys(support, {"minimum_uncensored_lineages", "minimum_touched_lineages"}, "trial.research.support")
    config_mapping = dict(raw)
    matching_strata = _canonical_matching_strata(research["matching_strata"])
    canonical_research = dict(research)
    canonical_research["matching_strata"] = matching_strata
    config_mapping["research"] = canonical_research
    return TrialConfig(
        version=bounded_int(raw["version"], "trial.version", minimum=2, maximum=2),
        model_path=str(model_path),
        model_sha256=model_sha256,
        model_config_fingerprint=model_config.config_fingerprint,
        model_catalog_fingerprint=model_config.catalog_fingerprint,
        observation_timeframe=model_config.trigger_timeframe,
        observation_duration=model_config.trigger_duration,
        horizons=horizons,
        bounce_excursion_atr=bounce,
        target_break_buffer_atr=model_config.break_buffer_atr,
        target_break_confirmation_bars=model_config.break_confirmation_bars,
        data_status=str(research["data_status"]),
        protected_manifest=(None if research["protected_manifest"] is None else str(research["protected_manifest"])),
        protected_manifest_sha256=_sha256_identity(research["protected_manifest_sha256"], "research.protected_manifest_sha256"),
        protected_manifest_content_id=(None if research["protected_manifest_content_id"] is None else str(research["protected_manifest_content_id"])),
        evidence_root=(None if research["evidence_root"] is None else str(research["evidence_root"])),
        splits=splits,
        null_specs=tuple(null_specs),
        matching_strata=matching_strata,
        bootstrap_repetitions=bounded_int(bootstrap["repetitions"], "trial.research.bootstrap.repetitions", minimum=1, maximum=1_000_000),
        bootstrap_block=bootstrap_block,
        bootstrap_epoch=bootstrap_epoch,
        confidence=confidence,
        ece_bins=bounded_int(calibration["ece_bins"], "trial.research.calibration.ece_bins", minimum=1, maximum=100),
        minimum_uncensored_lineages=bounded_int(support["minimum_uncensored_lineages"], "trial.research.support.minimum_uncensored_lineages", minimum=1, maximum=1_000_000),
        minimum_touched_lineages=bounded_int(support["minimum_touched_lineages"], "trial.research.support.minimum_touched_lineages", minimum=1, maximum=1_000_000),
        maximum_ece=finite_probability(calibration["maximum_ece"], "trial.research.calibration.maximum_ece"),
        conclusion_gates={str(key): value for key, value in gates.items()},
        config_fingerprint=canonical_hash({"trial": config_mapping, "model_sha256": model_sha256, "model_config_fingerprint": model_config.config_fingerprint, "model_catalog_fingerprint": model_config.catalog_fingerprint}),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class StudyResult:
    metrics_by_group: Mapping[str, ResearchMetrics]
    conclusion: str
    promotion_recommendation: str
    data_status: str = "PENDING_PROTECTED_MANIFEST"
    reason: str | None = None
    protected_manifest: ProtectedManifest | None = None
    manifest_sha256: str | None = None
    manifest_content_id: str | None = None
    trial_config_fingerprint: str | None = None
    consumption_identity: str | None = None
    evidence_id: str | None = None
    consumption_marker: Path | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProtectedEvaluationEvidence:
    """Immutable, content-bound inputs/results for one protected holdout use."""

    manifest: ProtectedManifest
    trial_config: TrialConfig
    metrics_by_group: Mapping[str, ResearchMetrics]
    null_metrics_by_group: Mapping[str, Mapping[str, ResearchMetrics]]
    runtime_config_fingerprint: str
    target_fingerprint: str
    code_fingerprint: str
    kernel_fingerprint: str
    deterministic_seeds: tuple[str, ...]
    observation_fingerprint: str
    forecast_fingerprint: str
    null_fingerprint: str
    consumption_identity: str
    evidence_id: str

    def __post_init__(self) -> None:
        if self.manifest.manifest_sha256 is None:
            raise ValueError("protected evidence requires a byte-authenticated manifest")
        if self.trial_config.data_status != "READY":
            raise ValueError("protected evidence requires a READY trial")
        if self.manifest.manifest_sha256 != self.trial_config.protected_manifest_sha256:
            raise ValueError("protected evidence manifest SHA does not match trial")
        if self.manifest.content_id != self.trial_config.protected_manifest_content_id:
            raise ValueError("protected evidence manifest content ID does not match trial")
        if tuple(self.deterministic_seeds) != self.trial_config.null_seeds:
            raise ValueError("protected evidence seed identity does not match trial")
        for name in (
            "runtime_config_fingerprint", "target_fingerprint", "code_fingerprint", "kernel_fingerprint",
            "observation_fingerprint", "forecast_fingerprint", "null_fingerprint", "consumption_identity",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        expected_consumption = canonical_hash(
            {
                "manifest_sha256": self.manifest.manifest_sha256,
                "manifest_content_id": self.manifest.content_id,
                "trial_config_fingerprint": self.trial_config.config_fingerprint,
                "splits": self.trial_config.splits,
                "runtime_config_fingerprint": self.runtime_config_fingerprint,
                "target_fingerprint": self.target_fingerprint,
                "code_fingerprint": self.code_fingerprint,
                "kernel_fingerprint": self.kernel_fingerprint,
                "seeds": self.deterministic_seeds,
                "observation_fingerprint": self.observation_fingerprint,
            }
        )
        if self.consumption_identity != expected_consumption:
            raise ValueError("protected holdout consumption identity is not content-addressed")
        expected_evidence = canonical_hash(
            {
                "consumption_identity": self.consumption_identity,
                "metrics": self.metrics_by_group,
                "null_metrics": self.null_metrics_by_group,
            }
        )
        if self.evidence_id != expected_evidence:
            raise ValueError("protected evidence ID does not match bound evidence")


def _adequate(metric: ResearchMetrics, *, minimum_uncensored: int, minimum_touched: int) -> bool:
    uncensored = metric.uncensored_count or metric.sample_count
    touched = metric.touched_count
    return uncensored >= minimum_uncensored and touched >= minimum_touched


def evaluate_conclusion_gates(
    metrics_by_group: Mapping[str, ResearchMetrics],
    *,
    trial_config: TrialConfig,
    null_metrics_by_group: Mapping[str, Mapping[str, ResearchMetrics]] | None = None,
) -> tuple[str, str]:
    """Pure gate helper; it is not a protected-evaluation entry point."""

    if not isinstance(trial_config, TrialConfig):
        raise TypeError("conclusion gates require a resolved TrialConfig")
    minimum_uncensored = trial_config.minimum_uncensored_lineages
    minimum_touched = trial_config.minimum_touched_lineages
    max_ece = trial_config.maximum_ece
    gates = trial_config.conclusion_gates
    if not metrics_by_group:
        return "INCONCLUSIVE", "no primary groups"
    null_metrics_by_group = null_metrics_by_group or {}
    statuses: list[bool] = []
    aggregate_worse = False
    incomplete = False
    for group, metric in metrics_by_group.items():
        if gates["negative_requires_adequate_support"] and not _adequate(
            metric, minimum_uncensored=minimum_uncensored, minimum_touched=minimum_touched
        ):
            return "INCONCLUSIVE", f"support is insufficient for {group}"
        if gates["require_ece"] and (not isfinite(metric.expected_calibration_error) or metric.expected_calibration_error > max_ece):
            if not isfinite(metric.expected_calibration_error):
                incomplete = True
            statuses.append(False)
            continue
        nulls = null_metrics_by_group.get(group, {})
        if not nulls:
            incomplete = True
            statuses.append(False)
            continue
        group_positive = True
        for null_name in nulls:
            deltas = metric.paired_delta_intervals.get(null_name)
            if gates["require_paired_deltas"] and (
                deltas is None or set(deltas) != {"brier", "log_loss"}
                or deltas["brier"][1] >= 0
                or deltas["log_loss"][1] >= 0
            ):
                if deltas is None or set(deltas) != {"brier", "log_loss"}:
                    incomplete = True
                group_positive = False
            if gates["require_no_resolved_reversal"] and null_name in metric.resolved_reversals:
                group_positive = False
            if metric.brier_delta_upper is not None and metric.brier_delta_upper > 0 and metric.sign_reversal:
                aggregate_worse = True
        statuses.append(group_positive)
    if all(statuses) and gates["positive_requires_all_groups"]:
        return "POSITIVE", "all primary groups passed paired null, ECE, and support gates"
    if any(statuses) and not all(statuses):
        return "INCONCLUSIVE", "mixed primary group gate outcomes"
    if incomplete:
        return "INCONCLUSIVE", "paired, calibration, or null evidence is incomplete"
    if aggregate_worse and gates["allow_significant_primary_aggregate_degradation"]:
        return "NEGATIVE", "primary aggregate is significantly worse than matched nulls"
    if not any(statuses) and all(_adequate(metric, minimum_uncensored=minimum_uncensored, minimum_touched=minimum_touched) for metric in metrics_by_group.values()):
        return "INCONCLUSIVE", "adequate support but no primary group passed the complete positive rule"
    return "INCONCLUSIVE", "positive gates are incomplete without resolved aggregate degradation"


def _authenticated_manifest(
    protected_manifest: str | Path,
    trial_config: TrialConfig,
) -> ProtectedManifest:
    return load_protected_manifest(
        protected_manifest,
        expected_sha256=trial_config.protected_manifest_sha256,
        expected_content_id=trial_config.protected_manifest_content_id,
    )


def _holdout_observation_fingerprint(
    observations_by_group: Mapping[str, tuple[ResearchObservation, ...]],
) -> str:
    """Hash holdout identity/lineage, independent of labels and input order."""

    payload: dict[str, tuple[Mapping[str, object], ...]] = {}
    for group, values in sorted(observations_by_group.items()):
        records = []
        for item in values:
            records.append(
                {
                    "source_observation_id": item.observation_id,
                    "source_file_path": item.source_file_path,
                    "source_record_identity": item.source_record_identity,
                    "asset": item.asset,
                    "timeframe": item.timeframe,
                    "side": item.side,
                    "width_stratum": item.width_stratum,
                    "issuance_calendar_block": item.issuance_calendar_block,
                    "normalized_distance_stratum": item.normalized_distance_stratum,
                    "volatility_stratum": item.volatility_stratum,
                    "level_density_stratum": item.level_density_stratum,
                    "touch_opportunity_stratum": item.touch_opportunity_stratum,
                    "formed_at": item.formed_at,
                    "issued_at": item.issued_at,
                    "observation_end_at": item.observation_end_at,
                    "zone": item.zone,
                }
            )
        payload[group] = tuple(sorted(records, key=lambda record: str(record["source_observation_id"])))
    return canonical_hash(payload)


def _validate_observation_scope(
    values: Iterable[ResearchObservation],
    *,
    manifest: ProtectedManifest,
    trial_config: TrialConfig,
) -> None:
    allowed_timeframes = set(manifest.allowed_timeframes)
    holdout_start, holdout_end = trial_config.splits.protected_holdout
    for item in values:
        if item.source_file_path is None or item.source_record_identity is None:
            raise ValueError("protected observation requires exact source file and record identity")
        source_record = manifest.source_record_for(
            file_path=item.source_file_path,
            source_record_identity=item.source_record_identity,
        )
        if item.timeframe not in allowed_timeframes:
            raise ValueError("protected observation timeframe is outside manifest allowlist")
        if source_record.asset != item.asset or source_record.bar.timeframe != item.timeframe:
            raise ValueError("protected observation identity differs from authenticated source record")
        if source_record.bar.bar_close_at > item.issued_at:
            raise ValueError("protected observation is issued before its authenticated source record closes")
        if item.issued_at < holdout_start or item.observation_end_at > holdout_end:
            raise ValueError("protected observation is outside the declared holdout window")
        if item.observation_end_at > manifest.creation_cutoff:
            raise ValueError("protected observation exceeds manifest creation cutoff")


def _authenticated_future_bars(
    item: ResearchObservation,
    *,
    manifest: ProtectedManifest,
    observation_timeframe: str,
) -> tuple[SRBar, ...]:
    """Return the complete authenticated bar series relevant to one observation."""

    if item.source_file_path is None or item.source_record_identity is None:
        raise ValueError("protected target labeling requires source identity")
    source_record = manifest.source_record_for(
        file_path=item.source_file_path,
        source_record_identity=item.source_record_identity,
    )
    records = [
        record
        for protected_file in manifest.files
        for record in protected_file.source_records
        if (
            record.venue == source_record.venue
            and record.instrument_id == source_record.instrument_id
            and record.asset == item.asset
            and record.bar.timeframe == observation_timeframe
        )
    ]
    return tuple(record.bar for record in sorted(records, key=lambda record: record.bar.bar_open_at))


def _validate_authenticated_target(
    item: ResearchObservation,
    *,
    manifest: ProtectedManifest,
    trial_config: TrialConfig,
) -> None:
    if item.zone is None:
        raise ValueError("protected target labeling requires canonical zone geometry")
    target = item.require_target()
    if target.horizon not in trial_config.horizons:
        raise ValueError("protected target horizon is outside the configured target semantics")
    expected = label_forecast(
        item.zone,
        issued_at=item.issued_at,
        future_bars=_authenticated_future_bars(
            item,
            manifest=manifest,
            observation_timeframe=trial_config.observation_timeframe,
        ),
        horizon=target.horizon,
        bounce_excursion_atr=trial_config.bounce_excursion_atr,
        break_buffer_atr=trial_config.target_break_buffer_atr,
        break_confirmation_bars=trial_config.target_break_confirmation_bars,
        observation_timeframe=trial_config.observation_timeframe,
        observation_duration=trial_config.observation_duration,
    )
    expected_provenance = target_provenance_fingerprint(
        item.zone,
        expected,
        target_fingerprint=trial_config.target_fingerprint,
    )
    if target != expected or item.target_provenance != expected_provenance:
        raise ValueError("protected target label is not recomputed from authenticated future bars")


def _source_observation_id(item: ResearchObservation) -> str:
    """Return the immutable candidate identity used for null matching."""

    identity = item.source_observation_id if item.record_type != "candidate" else item.observation_id
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("research observation source_observation_id must be non-empty")
    return identity


def _index_source_observations(
    values: Iterable[ResearchObservation],
    *,
    candidate: bool,
) -> dict[str, ResearchObservation]:
    indexed: dict[str, ResearchObservation] = {}
    for item in values:
        if candidate:
            if item.record_type != "candidate":
                raise ValueError("protected candidate observations must be candidate records")
            if item.source_observation_id is not None:
                raise ValueError("candidate observations must not carry a null source_observation_id")
        identity = _source_observation_id(item)
        if identity in indexed:
            raise ValueError("duplicate source_observation_id in matched observations")
        indexed[identity] = item
    return indexed


def _null_family_spec(
    null_name: str,
    trial_config: TrialConfig,
) -> tuple[str, str, Any, Decimal | None]:
    """Resolve a caller label to one of the two approved deterministic generators."""

    lowered = null_name.lower()
    for spec in trial_config.null_specs:
        if spec.name.lower() != lowered:
            continue
        if spec.algorithm == "random_price" and spec.version == "1":
            return "random_price@1", spec.seed, build_random_price_nulls, spec.max_abs_shift_atr
        if spec.algorithm == "shuffled_time" and spec.version == "1":
            return "shuffled_time@1", spec.seed, build_shuffled_time_nulls, None
        raise ValueError(f"unsupported matched null algorithm: {spec.algorithm}@{spec.version}")
    raise ValueError("matched null family is not configured")


def _verify_null_family(
    candidates: tuple[ResearchObservation, ...],
    supplied: tuple[ResearchObservation, ...],
    *,
    null_name: str,
    trial_config: TrialConfig,
    matching_strata: object,
) -> None:
    """Prove supplied nulls are the internally reproducible approved family."""

    candidate_by_id = _index_source_observations(candidates, candidate=True)
    generator_name, seed, generator, max_shift = _null_family_spec(null_name, trial_config)
    if max_shift is None:
        expected = tuple(generator(candidates, seed=seed, matching_strata=matching_strata))
    else:
        expected = tuple(
            generator(
                candidates,
                seed=seed,
                max_abs_shift_atr=max_shift,
                matching_strata=matching_strata,
            )
        )
    expected_by_id = _index_source_observations(expected, candidate=False)
    supplied_by_id = _index_source_observations(supplied, candidate=False)
    if set(supplied_by_id) != set(candidate_by_id):
        raise ValueError("matched nulls must have an exact one-to-one source_observation_id set")
    if set(expected_by_id) != set(candidate_by_id):
        raise ValueError("approved null generator did not preserve source_observation_id set")
    for source_id in sorted(candidate_by_id):
        expected_item = expected_by_id[source_id]
        supplied_item = supplied_by_id[source_id]
        if supplied_item.strata_key_for(matching_strata) != expected_item.strata_key_for(matching_strata):
            raise ValueError("matched null strata keys differ from the approved generator")
        # Labels are produced after null generation, so compare the complete
        # structural record while deliberately excluding only the target.
        if replace(supplied_item, target=None, target_provenance=None) != replace(
            expected_item,
            target=None,
            target_provenance=None,
        ):
            raise ValueError(
                f"{generator_name} null provenance does not match source_observation_id {source_id}"
            )
        if supplied_item.target is None:
            raise ValueError("protected matched nulls must carry authenticated target labels")


def build_protected_evaluation(
    trial_config: TrialConfig,
    *,
    target_config: ResolvedSRV2Config,
    observations_by_group: Mapping[str, Iterable[ResearchObservation]],
    probabilities_by_group: Mapping[str, Mapping[tuple[str, object], Mapping[Any, float]]],
    null_observations_by_group: Mapping[str, Mapping[str, Iterable[ResearchObservation]]],
    null_probabilities_by_group: Mapping[str, Mapping[str, Mapping[tuple[str, object], Mapping[Any, float]]]],
) -> ProtectedEvaluationEvidence:
    """Authenticate the manifest and construct all candidate/null evidence."""

    if not isinstance(target_config, ResolvedSRV2Config):
        raise TypeError("protected evaluation requires the resolved model config")
    if trial_config.data_status != "READY" or not trial_config.protected_manifest:
        raise ValueError("protected evaluation requires a READY trial manifest")
    if target_config.config_fingerprint != trial_config.model_config_fingerprint:
        raise ValueError("protected target model fingerprint does not match trial model")
    if target_config.catalog_fingerprint != trial_config.model_catalog_fingerprint:
        raise ValueError("protected kernel catalog fingerprint does not match trial model")
    runtime_config_fingerprint = target_config.config_fingerprint
    kernel_fingerprint = target_config.catalog_fingerprint
    resolved_target_fingerprint = trial_config.target_fingerprint
    code_fingerprint = SR_V2_RESEARCH_CODE_VERSION
    manifest = _authenticated_manifest(trial_config.protected_manifest, trial_config)
    observations = {group: tuple(values) for group, values in observations_by_group.items()}
    probabilities = dict(probabilities_by_group)
    null_observations = {
        group: {name: tuple(values) for name, values in nulls.items()}
        for group, nulls in null_observations_by_group.items()
    }
    null_probabilities = {group: dict(nulls) for group, nulls in null_probabilities_by_group.items()}
    for group, group_values in observations.items():
        _index_source_observations(group_values, candidate=True)
        _validate_observation_scope(group_values, manifest=manifest, trial_config=trial_config)
        for item in group_values:
            _validate_authenticated_target(item, manifest=manifest, trial_config=trial_config)
        if group not in probabilities:
            raise ValueError(f"missing candidate probabilities for group {group}")
    for group, group_nulls in null_observations.items():
        for null_values in group_nulls.values():
            _validate_observation_scope(null_values, manifest=manifest, trial_config=trial_config)
        if group not in null_probabilities:
            raise ValueError(f"missing null probabilities for group {group}")
    metrics: dict[str, ResearchMetrics] = {}
    null_metrics: dict[str, dict[str, ResearchMetrics]] = {}
    for group, values in observations.items():
        metrics[group] = evaluate_observations(
            values,
            probabilities[group],
            bootstrap_repetitions=trial_config.bootstrap_repetitions,
            bootstrap_seed=f"{trial_config.config_fingerprint}:{group}:candidate",
            bootstrap_block=trial_config.bootstrap_block,
            bootstrap_epoch=trial_config.bootstrap_epoch,
            ece_bins=trial_config.ece_bins,
            confidence=trial_config.confidence,
            matching_strata=trial_config.matching_strata,
        )
        null_metrics[group] = {}
        for null_name, null_values in null_observations.get(group, {}).items():
            if null_name not in null_probabilities[group]:
                raise ValueError(f"missing probabilities for matched null {group}/{null_name}")
            _verify_null_family(
                values,
                null_values,
                null_name=null_name,
                trial_config=trial_config,
                matching_strata=trial_config.matching_strata,
            )
            for item in null_values:
                _validate_authenticated_target(item, manifest=manifest, trial_config=trial_config)
            null_metrics[group][null_name] = evaluate_observations(
                null_values,
                null_probabilities[group][null_name],
                bootstrap_repetitions=trial_config.bootstrap_repetitions,
                bootstrap_seed=f"{trial_config.config_fingerprint}:{group}:{null_name}",
                bootstrap_block=trial_config.bootstrap_block,
                bootstrap_epoch=trial_config.bootstrap_epoch,
                ece_bins=trial_config.ece_bins,
                confidence=trial_config.confidence,
                matching_strata=trial_config.matching_strata,
            )
        metrics[group] = compare_against_nulls(
            metrics[group],
            null_metrics[group],
            bootstrap_repetitions=trial_config.bootstrap_repetitions,
            bootstrap_seed=f"{trial_config.config_fingerprint}:{group}:paired",
            confidence=trial_config.confidence,
        )
    observation_fingerprint = _holdout_observation_fingerprint(observations)
    forecast_fingerprint = _forecast_fingerprint(probabilities)
    null_forecast_payload = {
        group: {name: _normalize_forecasts(forecasts) for name, forecasts in nulls.items()}
        for group, nulls in null_probabilities.items()
    }
    null_fingerprint = canonical_hash({"observations": null_observations, "probabilities": null_forecast_payload})
    identity_mapping = {
        "manifest_sha256": manifest.manifest_sha256,
        "manifest_content_id": manifest.content_id,
        "trial_config_fingerprint": trial_config.config_fingerprint,
        "splits": trial_config.splits,
        "runtime_config_fingerprint": runtime_config_fingerprint,
        "target_fingerprint": resolved_target_fingerprint,
        "code_fingerprint": code_fingerprint,
        "kernel_fingerprint": kernel_fingerprint,
        "seeds": trial_config.null_seeds,
        "observation_fingerprint": observation_fingerprint,
    }
    consumption_identity = canonical_hash(identity_mapping)
    evidence_id = canonical_hash({"consumption_identity": consumption_identity, "metrics": metrics, "null_metrics": null_metrics})
    return ProtectedEvaluationEvidence(
        manifest=manifest,
        trial_config=trial_config,
        metrics_by_group=metrics,
        null_metrics_by_group=null_metrics,
        runtime_config_fingerprint=runtime_config_fingerprint,
        target_fingerprint=resolved_target_fingerprint,
        code_fingerprint=code_fingerprint,
        kernel_fingerprint=kernel_fingerprint,
        deterministic_seeds=trial_config.null_seeds,
        observation_fingerprint=observation_fingerprint,
        forecast_fingerprint=forecast_fingerprint,
        null_fingerprint=null_fingerprint,
        consumption_identity=consumption_identity,
        evidence_id=evidence_id,
    )


def run_protected_phase1_evaluation(
    evidence: ProtectedEvaluationEvidence,
    *,
    evidence_root: str | Path | None = None,
) -> StudyResult:
    """Consume one protected holdout identity and apply the preregistered gates."""

    if not isinstance(evidence, ProtectedEvaluationEvidence):
        raise TypeError("protected evaluation requires ProtectedEvaluationEvidence")
    resolved_root = evidence_root if evidence_root is not None else evidence.trial_config.evidence_root
    if resolved_root is None:
        raise ValueError("protected evaluation requires a caller-supplied or configured evidence_root")
    consumption_marker = claim_consumption(
        resolved_root,
        identity=evidence.consumption_identity,
        metadata={
            "evidence_id": evidence.evidence_id,
            "manifest_sha256": evidence.manifest.manifest_sha256,
            "manifest_content_id": evidence.manifest.content_id,
            "trial_config_fingerprint": evidence.trial_config.config_fingerprint,
        },
    )
    conclusion, reason = evaluate_conclusion_gates(
        evidence.metrics_by_group,
        trial_config=evidence.trial_config,
        null_metrics_by_group=evidence.null_metrics_by_group,
    )
    return StudyResult(
        metrics_by_group=evidence.metrics_by_group,
        conclusion=conclusion,
        promotion_recommendation="NO_PROMOTION",
        data_status="READY",
        reason=reason,
        protected_manifest=evidence.manifest,
        manifest_sha256=evidence.manifest.manifest_sha256,
        manifest_content_id=evidence.manifest.content_id,
        trial_config_fingerprint=evidence.trial_config.config_fingerprint,
        consumption_identity=evidence.consumption_identity,
        evidence_id=evidence.evidence_id,
        consumption_marker=consumption_marker,
    )


def run_phase1_study(
    metrics_by_group: Mapping[str, ResearchMetrics],
    *,
    protected_manifest: ProtectedManifest | str | Path | None = None,
    trial_config: TrialConfig | None = None,
    null_metrics_by_group: Mapping[str, Mapping[str, ResearchMetrics]] | None = None,
    protected_evidence: ProtectedEvaluationEvidence | None = None,
    evidence_root: str | Path | None = None,
) -> StudyResult:
    """Reject caller-forged raw metrics from the protected conclusion path."""

    if protected_evidence is not None:
        return run_protected_phase1_evaluation(protected_evidence, evidence_root=evidence_root)
    if protected_manifest is None:
        return StudyResult(
            metrics_by_group=metrics_by_group,
            conclusion="INCONCLUSIVE",
            promotion_recommendation="NO_PROMOTION",
            data_status="PENDING_PROTECTED_MANIFEST",
            reason="protected evidence is required",
        )
    if trial_config is not None and trial_config.data_status == "READY":
        if isinstance(protected_manifest, (str, Path)):
            manifest = _authenticated_manifest(protected_manifest, trial_config)
        else:
            manifest = protected_manifest
        return StudyResult(
            metrics_by_group=metrics_by_group,
            conclusion="INCONCLUSIVE",
            promotion_recommendation="NO_PROMOTION",
            data_status="READY",
            reason="raw ResearchMetrics cannot produce a protected conclusion; build ProtectedEvaluationEvidence",
            protected_manifest=manifest,
            manifest_sha256=manifest.manifest_sha256,
            manifest_content_id=manifest.content_id,
            trial_config_fingerprint=trial_config.config_fingerprint,
        )
    return StudyResult(
        metrics_by_group=metrics_by_group,
        conclusion="INCONCLUSIVE",
        promotion_recommendation="NO_PROMOTION",
        data_status="PENDING_PROTECTED_MANIFEST",
        reason="protected trial is not READY",
    )


__all__ = [
    "CONCLUSION_GATE_KEYS",
    "NullSpec",
    "ProtectedEvaluationEvidence",
    "StudyResult",
    "TrialConfig",
    "build_protected_evaluation",
    "evaluate_conclusion_gates",
    "load_trial_config",
    "run_phase1_study",
    "run_protected_phase1_evaluation",
]
