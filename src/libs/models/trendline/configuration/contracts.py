"""Typed, immutable, and runtime-validated trendline-family configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from types import MappingProxyType
from typing import Any, Mapping

from ..contracts import ContractValidationError, deterministic_hash


def _string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractValidationError(f"{field_name} must be a boolean")
    return value


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


def _number(value: Any, *, field_name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return result


@dataclass(frozen=True)
class ModelConfig:
    enabled: bool = True
    model_version: str = "trendline_family_v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", _bool(self.enabled, field_name="model.enabled"))
        object.__setattr__(self, "model_version", _string(self.model_version, field_name="model.model_version"))


@dataclass(frozen=True)
class CandidateConfig:
    pivot_provider: str = "fractal"
    fitter: str = "pathfinding"
    lookback_bars: int = 240
    min_bars: int = 40
    fractal_left_bars: int = 3
    fractal_right_bars: int = 3
    min_pivots_per_side: int = 2
    min_candidate_quality: float = 0.35
    birth_quality_threshold: float = 0.45

    def __post_init__(self) -> None:
        object.__setattr__(self, "pivot_provider", _string(self.pivot_provider, field_name="candidate.pivot_provider"))
        object.__setattr__(self, "fitter", _string(self.fitter, field_name="candidate.fitter"))
        object.__setattr__(self, "lookback_bars", _integer(self.lookback_bars, field_name="candidate.lookback_bars", minimum=1))
        object.__setattr__(self, "min_bars", _integer(self.min_bars, field_name="candidate.min_bars", minimum=1))
        object.__setattr__(self, "fractal_left_bars", _integer(self.fractal_left_bars, field_name="candidate.fractal_left_bars", minimum=1))
        object.__setattr__(self, "fractal_right_bars", _integer(self.fractal_right_bars, field_name="candidate.fractal_right_bars", minimum=1))
        object.__setattr__(self, "min_pivots_per_side", _integer(self.min_pivots_per_side, field_name="candidate.min_pivots_per_side", minimum=2))
        if self.min_bars > self.lookback_bars:
            raise ContractValidationError("candidate.min_bars cannot exceed candidate.lookback_bars")
        if self.min_bars < self.fractal_left_bars + self.fractal_right_bars + 1:
            raise ContractValidationError("candidate.min_bars must cover the fractal window")
        object.__setattr__(self, "min_candidate_quality", _number(self.min_candidate_quality, field_name="candidate.min_candidate_quality", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "birth_quality_threshold", _number(self.birth_quality_threshold, field_name="candidate.birth_quality_threshold", minimum=0.0, maximum=1.0))
        if self.birth_quality_threshold < self.min_candidate_quality:
            raise ContractValidationError("candidate.birth_quality_threshold cannot be below candidate.min_candidate_quality")


@dataclass(frozen=True)
class MatchingConfig:
    normalization_atr_window: int = 14
    max_distance_atr: float = 0.75
    max_slope_delta_atr_per_hour: float = 0.10
    minimum_match_score: float = 0.60
    level_weight: float = 0.45
    slope_weight: float = 0.30
    anchor_weight: float = 0.15
    role_weight: float = 0.10

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalization_atr_window", _integer(self.normalization_atr_window, field_name="matching.normalization_atr_window", minimum=1))
        object.__setattr__(self, "max_distance_atr", _number(self.max_distance_atr, field_name="matching.max_distance_atr", minimum=0.0))
        object.__setattr__(self, "max_slope_delta_atr_per_hour", _number(self.max_slope_delta_atr_per_hour, field_name="matching.max_slope_delta_atr_per_hour", minimum=0.0))
        for name in ("minimum_match_score", "level_weight", "slope_weight", "anchor_weight", "role_weight"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=f"matching.{name}", minimum=0.0, maximum=1.0))
        total = self.level_weight + self.slope_weight + self.anchor_weight + self.role_weight
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ContractValidationError("matching weights must sum to one")


@dataclass(frozen=True)
class LifecycleConfig:
    active_grace_bars: int = 3
    dormant_after_bars: int = 6
    expire_after_bars: int = 50
    confidence_decay_per_unmatched_bar: float = 0.05
    reactivation_min_score: float = 0.70
    max_active_families_per_role: int = 8

    def __post_init__(self) -> None:
        for name in ("active_grace_bars", "dormant_after_bars", "expire_after_bars"):
            object.__setattr__(self, name, _integer(getattr(self, name), field_name=f"lifecycle.{name}"))
        if not self.active_grace_bars < self.dormant_after_bars < self.expire_after_bars:
            raise ContractValidationError("lifecycle horizons must be strictly ordered")
        object.__setattr__(self, "max_active_families_per_role", _integer(self.max_active_families_per_role, field_name="lifecycle.max_active_families_per_role", minimum=1))
        object.__setattr__(self, "confidence_decay_per_unmatched_bar", _number(self.confidence_decay_per_unmatched_bar, field_name="lifecycle.confidence_decay_per_unmatched_bar", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "reactivation_min_score", _number(self.reactivation_min_score, field_name="lifecycle.reactivation_min_score", minimum=0.0, maximum=1.0))


@dataclass(frozen=True)
class InteractionConfig:
    atr_window: int = 14
    tolerance_atr: float = 0.25
    approaching_distance_atr: float = 0.75
    minimum_zone_ticks: int = 1
    close_confirmation_bars: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "atr_window", _integer(self.atr_window, field_name="interaction.atr_window", minimum=1))
        object.__setattr__(
            self,
            "minimum_zone_ticks",
            _integer(self.minimum_zone_ticks, field_name="interaction.minimum_zone_ticks", minimum=1),
        )
        object.__setattr__(self, "close_confirmation_bars", _integer(self.close_confirmation_bars, field_name="interaction.close_confirmation_bars", minimum=2))
        object.__setattr__(self, "tolerance_atr", _number(self.tolerance_atr, field_name="interaction.tolerance_atr", minimum=0.0))
        object.__setattr__(self, "approaching_distance_atr", _number(self.approaching_distance_atr, field_name="interaction.approaching_distance_atr", minimum=0.0))
        if self.approaching_distance_atr < self.tolerance_atr:
            raise ContractValidationError("interaction.approaching_distance_atr cannot be below interaction.tolerance_atr")


@dataclass(frozen=True)
class EventsConfig:
    """Phase-F lifecycle timing only; geometry and matching remain elsewhere."""

    pressure_min_bars: int = 3
    rejection_recovery_bars: int = 2
    # A valid retest needs one contact bar plus at least one confirmation bar.
    retest_window_bars: int = 2
    retest_confirmation_bars: int = 1

    def __post_init__(self) -> None:
        for name in (
            "pressure_min_bars",
            "rejection_recovery_bars",
            "retest_window_bars",
            "retest_confirmation_bars",
        ):
            minimum = 2 if name == "retest_window_bars" else 1
            object.__setattr__(self, name, _integer(getattr(self, name), field_name=f"events.{name}", minimum=minimum))


@dataclass(frozen=True)
class RailsConfig:
    """Phase-G deterministic same-timeframe rail grouping controls."""

    max_group_slope_delta_atr_per_hour: float = 0.08
    max_adjacent_gap_atr: float = 0.75
    max_corridor_width_atr: float = 1.50
    minimum_spacing_atr: float = 0.05
    representative_policy: str = "stable_medoid"

    def __post_init__(self) -> None:
        for name in (
            "max_group_slope_delta_atr_per_hour",
            "max_adjacent_gap_atr",
            "max_corridor_width_atr",
            "minimum_spacing_atr",
        ):
            object.__setattr__(
                self,
                name,
                _number(getattr(self, name), field_name=f"rails.{name}", minimum=0.0),
            )
        if self.minimum_spacing_atr >= self.max_adjacent_gap_atr:
            raise ContractValidationError(
                "rails.minimum_spacing_atr must be below rails.max_adjacent_gap_atr"
            )
        if self.minimum_spacing_atr >= self.max_corridor_width_atr:
            raise ContractValidationError(
                "rails.minimum_spacing_atr must be below rails.max_corridor_width_atr"
            )
        object.__setattr__(
            self,
            "representative_policy",
            _string(self.representative_policy, field_name="rails.representative_policy"),
        )
        if self.representative_policy not in {"stable_medoid"}:
            raise ContractValidationError(
                "rails.representative_policy must be stable_medoid"
            )


_TIMEFRAME_PATTERN = re.compile(r"[1-9][0-9]*(?:m|h|d|w)")
_TIMEFRAME_SECONDS = {"m": 60, "h": 3_600, "d": 86_400, "w": 604_800}


def canonical_timeframe_duration_seconds(value: str) -> int:
    """Return fixed duration for one validated Phase-H timeframe label."""

    if not isinstance(value, str) or _TIMEFRAME_PATTERN.fullmatch(value) is None:
        raise ContractValidationError("timeframe must be a canonical duration string")
    return int(value[:-1]) * _TIMEFRAME_SECONDS[value[-1]]


def canonical_mtf_source_timeframes(
    value: Any,
    *,
    field_name: str,
    require_nonempty: bool,
) -> tuple[str, ...]:
    """Validate canonical ordering and reject aliases with equal durations."""

    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise ContractValidationError(f"{field_name} must contain canonical timeframe strings")
    timeframes = tuple(value)
    if any(
        not isinstance(item, str) or _TIMEFRAME_PATTERN.fullmatch(item) is None
        for item in timeframes
    ):
        raise ContractValidationError(f"{field_name} must contain canonical timeframe strings")
    if len(set(timeframes)) != len(timeframes):
        raise ContractValidationError(f"{field_name} must not contain duplicates")
    by_duration: dict[int, str] = {}
    for timeframe in timeframes:
        duration = canonical_timeframe_duration_seconds(timeframe)
        prior = by_duration.setdefault(duration, timeframe)
        if prior != timeframe:
            raise ContractValidationError(
                f"{field_name} must not contain equivalent-duration aliases"
            )
    if require_nonempty and not timeframes:
        raise ContractValidationError(f"{field_name} must not be empty when mtf.enabled is true")
    return tuple(sorted(timeframes, key=_timeframe_sort_key))


@dataclass(frozen=True)
class MTFConfig:
    """Phase-H composition policy; it never changes source tracker state."""

    enabled: bool = False
    source_timeframes: tuple[str, ...] = ()
    minimum_confluence_timeframes: int = 2
    max_source_age_bars: float = 4.0
    stale_include_age_bars: float = 1.0
    max_level_distance_atr: float = 0.75
    max_corridor_separation_atr: float = 0.75
    max_slope_delta_atr_per_hour: float = 0.10
    intersection_horizon_bars: int = 24
    normalization_policy: str = "decision_timeframe_atr"

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", _bool(self.enabled, field_name="mtf.enabled"))
        object.__setattr__(
            self,
            "source_timeframes",
            canonical_mtf_source_timeframes(
                self.source_timeframes,
                field_name="mtf.source_timeframes",
                require_nonempty=self.enabled,
            ),
        )
        object.__setattr__(
            self,
            "minimum_confluence_timeframes",
            _integer(
                self.minimum_confluence_timeframes,
                field_name="mtf.minimum_confluence_timeframes",
                minimum=2,
            ),
        )
        for name in (
            "max_source_age_bars",
            "stale_include_age_bars",
            "max_level_distance_atr",
            "max_corridor_separation_atr",
            "max_slope_delta_atr_per_hour",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=f"mtf.{name}", minimum=0.0))
        if self.max_source_age_bars < self.stale_include_age_bars:
            raise ContractValidationError(
                "mtf.max_source_age_bars cannot be below mtf.stale_include_age_bars"
            )
        object.__setattr__(
            self,
            "intersection_horizon_bars",
            _integer(
                self.intersection_horizon_bars,
                field_name="mtf.intersection_horizon_bars",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "normalization_policy",
            _string(self.normalization_policy, field_name="mtf.normalization_policy"),
        )
        if self.normalization_policy != "decision_timeframe_atr":
            raise ContractValidationError(
                "mtf.normalization_policy must be decision_timeframe_atr"
            )


def _timeframe_sort_key(value: str) -> tuple[int, int, str]:
    return (canonical_timeframe_duration_seconds(value), int(value[:-1]), value)


@dataclass(frozen=True)
class RankingConfig:
    """Reserved Phase-A ownership boundary; no ranking parameters are active yet."""


@dataclass(frozen=True)
class RepositoryConfig:
    """Reserved Phase-A ownership boundary; persistence tuning is intentionally deferred."""


@dataclass(frozen=True)
class RuntimeConfig:
    """Reserved Phase-A ownership boundary; runtime behavior is not implemented yet."""


@dataclass(frozen=True)
class TrendlineFamilyConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    candidate: CandidateConfig = field(default_factory=CandidateConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    lifecycle: LifecycleConfig = field(default_factory=LifecycleConfig)
    interaction: InteractionConfig = field(default_factory=InteractionConfig)
    events: EventsConfig = field(default_factory=EventsConfig)
    rails: RailsConfig = field(default_factory=RailsConfig)
    mtf: MTFConfig = field(default_factory=MTFConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)
    repository: RepositoryConfig = field(default_factory=RepositoryConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def tracking_dict(self) -> dict[str, Any]:
        """Return upstream tracker policy only; Phase-H policy is downstream."""

        payload = self.to_dict()
        payload.pop("mtf")
        return payload


@dataclass(frozen=True)
class ResolvedTrendlineFamilyConfig:
    asset: str
    timeframe: str
    config_version: str
    model: ModelConfig
    candidate: CandidateConfig
    matching: MatchingConfig
    lifecycle: LifecycleConfig
    interaction: InteractionConfig
    events: EventsConfig
    rails: RailsConfig
    mtf: MTFConfig
    ranking: RankingConfig
    repository: RepositoryConfig
    runtime: RuntimeConfig
    field_provenance: Mapping[str, str]
    resolved_config_hash: str
    mtf_config_hash: str
    profile_id: str = "legacy_v1"
    profile_version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _string(self.asset, field_name="asset"))
        object.__setattr__(self, "timeframe", _string(self.timeframe, field_name="timeframe"))
        object.__setattr__(self, "config_version", _string(self.config_version, field_name="config_version"))
        object.__setattr__(self, "profile_id", _string(self.profile_id, field_name="profile_id"))
        object.__setattr__(self, "profile_version", _string(self.profile_version, field_name="profile_version"))
        if not isinstance(self.resolved_config_hash, str) or re.fullmatch(r"[0-9a-f]{64}", self.resolved_config_hash) is None:
            raise ContractValidationError("resolved_config_hash must be a lowercase SHA-256 hex string")
        if not isinstance(self.mtf_config_hash, str) or re.fullmatch(r"[0-9a-f]{64}", self.mtf_config_hash) is None:
            raise ContractValidationError("mtf_config_hash must be a lowercase SHA-256 hex string")
        object.__setattr__(self, "field_provenance", MappingProxyType(dict(self.field_provenance)))

    @property
    def model_version(self) -> str:
        return self.model.model_version

    @property
    def configuration_fingerprint(self) -> str:
        """Trace full resolved values and source provenance without changing domain IDs."""

        return deterministic_hash(
            {
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
                "resolved_values": self.to_dict(),
                "field_provenance": dict(self.field_provenance),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset, "timeframe": self.timeframe, "config_version": self.config_version,
            "model": asdict(self.model), "candidate": asdict(self.candidate), "matching": asdict(self.matching),
            "lifecycle": asdict(self.lifecycle), "interaction": asdict(self.interaction),
            "events": asdict(self.events), "rails": asdict(self.rails),
            "mtf": asdict(self.mtf),
            "ranking": asdict(self.ranking), "repository": asdict(self.repository), "runtime": asdict(self.runtime),
        }

    @classmethod
    def create(
        cls,
        *,
        asset: str,
        timeframe: str,
        config_version: str,
        config: TrendlineFamilyConfig,
        field_provenance: Mapping[str, str],
        profile_id: str = "legacy_v1",
        profile_version: str = "1",
    ) -> "ResolvedTrendlineFamilyConfig":
        tracking_payload = {
            "asset": asset,
            "timeframe": timeframe,
            "config_version": config_version,
            **config.tracking_dict(),
        }
        mtf_payload = {
            "asset": asset,
            "timeframe": timeframe,
            "config_version": config_version,
            "mtf": asdict(config.mtf),
        }
        return cls(asset=asset, timeframe=timeframe, config_version=config_version, model=config.model, candidate=config.candidate,
                   matching=config.matching, lifecycle=config.lifecycle, interaction=config.interaction, events=config.events, rails=config.rails, mtf=config.mtf, ranking=config.ranking,
                   repository=config.repository, runtime=config.runtime, field_provenance=field_provenance,
                   resolved_config_hash=deterministic_hash(tracking_payload),
                   mtf_config_hash=deterministic_hash(mtf_payload), profile_id=profile_id,
                   profile_version=profile_version)
