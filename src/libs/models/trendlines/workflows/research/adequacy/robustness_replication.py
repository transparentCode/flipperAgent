"""Offline D5B replication contracts for frozen trendline adequacy studies."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real
from typing import Any, Sequence

from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.workflows.research.replay import (
    PreparedTrendlineResearchReplay,
)
from libs.models.trendlines.workflows.research.contracts import (
    PreparedTrendlineResearchRun,
)

from .baselines import TrendlineAdequacyBaselineSpec
from .baseline_comparison import validate_baseline_comparison_bundle
from .contracts import (
    TrendlineAdequacyStudyConfig,
    TrendlineObservationUnit,
)
from .interaction import validate_interaction_utility_bundle
from .robustness_sources import (
    ROBUSTNESS_EXPECTED_ROWS,
    ROBUSTNESS_MEMBER_NAMES,
    ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
    TrendlineRobustnessSourceMatrixBundle,
    TrendlineRobustnessSourceMemberEvidence,
    TrendlineRobustnessSourceMemberSpec,
    validate_robustness_source_member_evidence,
)
from .stability import validate_structural_stability_bundle
from .stochastic_null_comparison import (
    STOCHASTIC_QUANTILE_PROBABILITIES,
    TrendlineStochasticNullComparisonBundle,
    validate_stochastic_null_comparison_bundle,
)


ROBUSTNESS_REPLICATION_PROTOCOL_SEMANTICS_VERSION = (
    "trendlines.adequacy-robustness-replication-protocol.v1"
)
ROBUSTNESS_REPLICATION_MEMBER_SEMANTICS_VERSION = (
    "trendlines.adequacy-robustness-replication-member.v1"
)
ROBUSTNESS_REPLICATION_BUNDLE_SEMANTICS_VERSION = (
    "trendlines.adequacy-robustness-replication-bundle.v1"
)
ROBUSTNESS_REPLICATION_BREAK_POLICY = (
    "resolved_signals_hold_bars_at_first_recorded_point"
)
ROBUSTNESS_REPLICATION_METRICS = (
    "eligible_point_coverage",
    "invalid_point_rate",
    "line_observation_count",
    "ray_observation_count",
    "line_birth_rate",
    "revision_churn_rate",
    "anchor_persistence_rate",
)
ROBUSTNESS_REPLICATION_DETERMINISTIC_BASELINE_IDS = (
    "ddf18905d6cad86f78d83ea45298531f329de23ac4afd214811c181538e3a930",
    "22e405ce85d3fda2352080942e631240e5c9f505cfe187764d9084913856d8c3",
)
ROBUSTNESS_REPLICATION_STOCHASTIC_BASELINE_IDS = (
    "c34573875135b4bfe723ca1f885150524a9b849ba7949b2f84f1258435571e1e",
    "554f85bb1eea413ac1afabd6acbe4db469f845cdf2d297c64205d4bb71cc8401",
)
ROBUSTNESS_REPLICATION_EXPECTED_HOLD_BARS = {"1h": 3, "4h": 1}


class TrendlineRobustnessReplicationError(ValueError):
    """Raised when D5B protocol or member evidence is invalid."""


def _sha(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise TrendlineRobustnessReplicationError(
            f"{name} must be a lowercase SHA-256 identity"
        )
    return value


def _text(value: Any, *, name: str) -> str:
    result = str(value).strip()
    if not result:
        raise TrendlineRobustnessReplicationError(f"{name} is required")
    return result


def _strict_int(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TrendlineRobustnessReplicationError(
            f"{name} must be a non-boolean integer >= {minimum}"
        )
    return value


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TrendlineRobustnessReplicationError(f"{name} must be finite numeric")
    result = float(value)
    if not isfinite(result):
        raise TrendlineRobustnessReplicationError(f"{name} must be finite numeric")
    return result


def _tuple_ints(value: Any, *, name: str, positive: bool = True) -> tuple[int, ...]:
    if not isinstance(value, tuple):
        raise TrendlineRobustnessReplicationError(f"{name} must be an ordered tuple")
    minimum = 1 if positive else 0
    result = tuple(_strict_int(item, name=name, minimum=minimum) for item in value)
    if not result or len(set(result)) != len(result) or result != tuple(sorted(result)):
        raise TrendlineRobustnessReplicationError(
            f"{name} must be non-empty, ordered and unique"
        )
    return result


def _tuple_text(value: Any, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TrendlineRobustnessReplicationError(f"{name} must be an ordered tuple")
    result = tuple(_text(item, name=name) for item in value)
    if not result or len(set(result)) != len(result):
        raise TrendlineRobustnessReplicationError(
            f"{name} must be non-empty and unique"
        )
    return result


@dataclass(frozen=True)
class TrendlineRobustnessReplicationProtocol:
    """Complete, explicit D5B protocol. No numerical defaults are hidden."""

    replay_warmup_start_position: int
    replay_record_start_position: int
    replay_end_position: int
    replay_record_every: int
    include_signals: bool
    minimum_warmup_bars: int
    minimum_prior_executed_prefixes: int
    metric_names: tuple[str, ...]
    line_observation_unit: str
    ray_observation_unit: str
    invalid_point_treatment: str
    availability_policy: str
    stability_horizons_bars: tuple[int, ...]
    interaction_horizons_bars: tuple[int, ...]
    deterministic_baseline_ids: tuple[str, ...]
    stochastic_baseline_specs: tuple[TrendlineAdequacyBaselineSpec, ...]
    quantile_probabilities: tuple[float, ...]
    break_confirmation_policy: str
    semantics_version: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("replay_warmup_start_position", self.replay_warmup_start_position),
            ("replay_record_start_position", self.replay_record_start_position),
            ("replay_end_position", self.replay_end_position),
            ("replay_record_every", self.replay_record_every),
            ("minimum_warmup_bars", self.minimum_warmup_bars),
            (
                "minimum_prior_executed_prefixes",
                self.minimum_prior_executed_prefixes,
            ),
        ):
            _strict_int(value, name=field_name, minimum=1 if field_name == "replay_record_every" else 0)
        if not isinstance(self.include_signals, bool):
            raise TrendlineRobustnessReplicationError("include_signals must be bool")
        if (
            self.replay_record_start_position < self.replay_warmup_start_position
            or self.replay_end_position < self.replay_record_start_position
        ):
            raise TrendlineRobustnessReplicationError("replay positions are not ordered")
        if (
            self.replay_warmup_start_position,
            self.replay_record_start_position,
            self.replay_end_position,
            self.replay_record_every,
        ) != (19, 64, 311, 1):
            raise TrendlineRobustnessReplicationError("D5B replay positions differ")
        if (
            self.minimum_warmup_bars,
            self.minimum_prior_executed_prefixes,
        ) != (45, 45):
            raise TrendlineRobustnessReplicationError("D5B warm-up requirements differ")
        if not self.include_signals:
            raise TrendlineRobustnessReplicationError("D5B requires signals enabled")
        metric_names = _tuple_text(self.metric_names, name="metric_names")
        if metric_names != ROBUSTNESS_REPLICATION_METRICS:
            raise TrendlineRobustnessReplicationError("D5B metric protocol differs")
        if self.line_observation_unit != TrendlineObservationUnit.FITTED_LINE.value:
            raise TrendlineRobustnessReplicationError("D5B line observation unit differs")
        if self.ray_observation_unit != TrendlineObservationUnit.BOUNDARY_RAY.value:
            raise TrendlineRobustnessReplicationError("D5B ray observation unit differs")
        if self.invalid_point_treatment != "retain_and_report_exclude_from_geometry_metrics":
            raise TrendlineRobustnessReplicationError("D5B invalid-point policy differs")
        if self.availability_policy != "causal_prefix_only":
            raise TrendlineRobustnessReplicationError("D5B availability policy differs")
        stability = _tuple_ints(self.stability_horizons_bars, name="stability_horizons_bars")
        interaction = _tuple_ints(
            self.interaction_horizons_bars,
            name="interaction_horizons_bars",
        )
        if stability != (1, 3, 6, 12) or interaction != (1, 3, 6, 12):
            raise TrendlineRobustnessReplicationError("D5B horizons differ")
        deterministic = tuple(_sha(value, name="deterministic baseline ID") for value in self.deterministic_baseline_ids)
        if deterministic != ROBUSTNESS_REPLICATION_DETERMINISTIC_BASELINE_IDS:
            raise TrendlineRobustnessReplicationError("D5B deterministic baselines differ")
        specs = tuple(self.stochastic_baseline_specs)
        if len(specs) != 2 or not all(isinstance(value, TrendlineAdequacyBaselineSpec) for value in specs):
            raise TrendlineRobustnessReplicationError("D5B stochastic specs must be typed")
        if tuple(value.baseline_id for value in specs) != ROBUSTNESS_REPLICATION_STOCHASTIC_BASELINE_IDS:
            raise TrendlineRobustnessReplicationError("D5B stochastic baselines differ")
        probabilities = tuple(_finite(value, name="quantile probability") for value in self.quantile_probabilities)
        if probabilities != STOCHASTIC_QUANTILE_PROBABILITIES:
            raise TrendlineRobustnessReplicationError("D5B quantile probabilities differ")
        if self.break_confirmation_policy != ROBUSTNESS_REPLICATION_BREAK_POLICY:
            raise TrendlineRobustnessReplicationError("D5B break-confirmation policy differs")
        if self.semantics_version != ROBUSTNESS_REPLICATION_PROTOCOL_SEMANTICS_VERSION:
            raise TrendlineRobustnessReplicationError("unsupported D5B protocol semantics")
        object.__setattr__(self, "metric_names", metric_names)
        object.__setattr__(self, "stability_horizons_bars", stability)
        object.__setattr__(self, "interaction_horizons_bars", interaction)
        object.__setattr__(self, "deterministic_baseline_ids", deterministic)
        object.__setattr__(self, "stochastic_baseline_specs", specs)
        object.__setattr__(self, "quantile_probabilities", probabilities)

    @property
    def stability_spec_id(self) -> str:
        from .stability import TrendlineStructuralStabilitySpec

        return TrendlineStructuralStabilitySpec(self.stability_horizons_bars).stability_spec_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "replay_warmup_start_position": self.replay_warmup_start_position,
            "replay_record_start_position": self.replay_record_start_position,
            "replay_end_position": self.replay_end_position,
            "replay_record_every": self.replay_record_every,
            "include_signals": self.include_signals,
            "minimum_warmup_bars": self.minimum_warmup_bars,
            "minimum_prior_executed_prefixes": self.minimum_prior_executed_prefixes,
            "metric_names": list(self.metric_names),
            "line_observation_unit": self.line_observation_unit,
            "ray_observation_unit": self.ray_observation_unit,
            "invalid_point_treatment": self.invalid_point_treatment,
            "availability_policy": self.availability_policy,
            "stability_horizons_bars": list(self.stability_horizons_bars),
            "interaction_horizons_bars": list(self.interaction_horizons_bars),
            "deterministic_baseline_ids": list(self.deterministic_baseline_ids),
            "stochastic_baseline_specs": [value.to_dict() for value in self.stochastic_baseline_specs],
            "quantile_probabilities": list(self.quantile_probabilities),
            "break_confirmation_policy": self.break_confirmation_policy,
            "semantics_version": self.semantics_version,
        }

    @property
    def replication_protocol_id(self) -> str:
        return canonical_hash(
            self.to_dict(),
            semantics_version=ROBUSTNESS_REPLICATION_PROTOCOL_SEMANTICS_VERSION,
        )


def validate_replication_protocol(protocol: TrendlineRobustnessReplicationProtocol) -> None:
    if not isinstance(protocol, TrendlineRobustnessReplicationProtocol):
        raise TypeError("protocol must be TrendlineRobustnessReplicationProtocol")
    if protocol.stability_spec_id != "12d9aa6b154238092835fd9879422a8d57d0a52e61ba8863dd27e8b7822a6271":
        raise TrendlineRobustnessReplicationError("D5B stability spec identity differs")


def _validate_study_config_against_protocol(
    d5a_spec: TrendlineRobustnessSourceMemberSpec,
    study_config: TrendlineAdequacyStudyConfig,
    protocol: TrendlineRobustnessReplicationProtocol,
) -> None:
    """Require member study configuration to implement frozen D5B protocol."""

    if len(study_config.windows) != 1:
        raise TrendlineRobustnessReplicationError(
            "D5B study must contain exactly one member window"
        )
    window = study_config.windows[0]
    expected_window = (
        d5a_spec.timeframe,
        protocol.replay_record_start_position,
        protocol.replay_end_position,
        protocol.minimum_warmup_bars,
        protocol.minimum_prior_executed_prefixes,
    )
    actual_window = (
        window.timeframe,
        window.start_position,
        window.end_position,
        window.minimum_warmup_bars,
        window.minimum_prior_executed_prefixes,
    )
    if actual_window != expected_window:
        raise TrendlineRobustnessReplicationError(
            "D5B study window differs from replication protocol"
        )
    if tuple(study_config.metric_names) != protocol.metric_names:
        raise TrendlineRobustnessReplicationError(
            "D5B study metrics differ from replication protocol"
        )
    if tuple(study_config.decision_rules) != ():
        raise TrendlineRobustnessReplicationError(
            "D5B study decision rules must be empty"
        )
    if study_config.line_observation_unit.value != protocol.line_observation_unit:
        raise TrendlineRobustnessReplicationError(
            "D5B study line observation unit differs"
        )
    if study_config.ray_observation_unit.value != protocol.ray_observation_unit:
        raise TrendlineRobustnessReplicationError(
            "D5B study ray observation unit differs"
        )
    if (
        study_config.invalid_point_treatment.value
        != protocol.invalid_point_treatment
    ):
        raise TrendlineRobustnessReplicationError(
            "D5B study invalid-point treatment differs"
        )
    if study_config.availability_policy.value != protocol.availability_policy:
        raise TrendlineRobustnessReplicationError(
            "D5B study availability policy differs"
        )
    deterministic_ids = tuple(
        spec.baseline_id for spec in study_config.baseline_specs
    )
    if deterministic_ids != protocol.deterministic_baseline_ids:
        raise TrendlineRobustnessReplicationError(
            "D5B study deterministic baseline identities differ"
        )


def _validate_downstream_protocol_bindings(
    study_config: TrendlineAdequacyStudyConfig,
    protocol: TrendlineRobustnessReplicationProtocol,
    d2_bundle: Any,
    d3_bundle: Any,
    d4a_bundle: Any,
    d4b_bundle: TrendlineStochasticNullComparisonBundle,
) -> None:
    """Bind downstream evidence configuration and specs to frozen D5B."""

    study_config_id = study_config.study_config_id
    for name, bundle in (
        ("D2", d2_bundle),
        ("D3", d3_bundle),
        ("D4A", d4a_bundle),
        ("D4B", d4b_bundle),
    ):
        if bundle.study_config_id != study_config_id:
            raise TrendlineRobustnessReplicationError(
                f"{name} study configuration identity differs"
            )
    study_baselines = tuple(
        spec.to_dict() for spec in study_config.baseline_specs
    )
    d4a_baselines = tuple(spec.to_dict() for spec in d4a_bundle.baseline_specs)
    if d4a_baselines != study_baselines:
        raise TrendlineRobustnessReplicationError(
            "D4A baseline specifications differ from study configuration"
        )
    expected_stochastic = tuple(
        spec.to_dict() for spec in protocol.stochastic_baseline_specs
    )
    actual_stochastic = tuple(
        spec.to_dict() for spec in d4b_bundle.stochastic_baseline_specs
    )
    if actual_stochastic != expected_stochastic:
        raise TrendlineRobustnessReplicationError(
            "D4B stochastic baseline specifications differ from protocol"
        )
    if tuple(d4b_bundle.quantile_probabilities) != protocol.quantile_probabilities:
        raise TrendlineRobustnessReplicationError(
            "D4B quantile probabilities differ from protocol"
        )


def _count(value: Any, *, name: str) -> int:
    return _strict_int(value, name=name, minimum=0)


def _id_payload(row: "TrendlineRobustnessReplicationMemberEvidence") -> dict[str, Any]:
    return {
        key: value
        for key, value in row.__dict__.items()
        if key not in {"member_result_id"}
    }


@dataclass(frozen=True)
class TrendlineRobustnessReplicationMemberEvidence:
    """Compact identity/count inventory for one fully replicated member."""

    d5a_member_spec_id: str
    d5a_member_evidence_id: str
    member_name: str
    relation: str
    asset: str
    timeframe: str
    source_id: str
    availability_id: str
    dataset_id: str
    research_configuration_id: str
    preparation_id: str
    replication_protocol_id: str
    replay_id: str
    cohort_id: str
    study_config_id: str
    stability_spec_id: str
    interaction_spec_id: str
    d2_bundle_id: str
    d3_bundle_id: str
    d4a_bundle_id: str
    d4b_bundle_id: str
    resolved_hold_bars: int
    row_count: int
    executed_prefix_count: int
    recorded_position_count: int
    d2_state_count: int
    d2_transition_count: int
    d2_drift_count: int
    d2_episode_count: int
    d2_survival_count: int
    d3_event_count: int
    d3_outcome_count: int
    d3_summary_count: int
    d4a_selection_count: int
    d4a_outcome_count: int
    d4a_comparison_count: int
    d4b_selection_count: int
    d4b_available_selection_count: int
    d4b_abstention_count: int
    d4b_outcome_count: int
    d4b_comparison_count: int
    d4b_distribution_count: int
    semantics_version: str
    member_result_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "d5a_member_spec_id", "d5a_member_evidence_id", "source_id",
            "availability_id", "dataset_id", "research_configuration_id",
            "preparation_id", "replication_protocol_id", "replay_id", "cohort_id",
            "study_config_id", "stability_spec_id", "interaction_spec_id",
            "d2_bundle_id", "d3_bundle_id", "d4a_bundle_id", "d4b_bundle_id",
        ):
            _sha(getattr(self, name), name=name)
        for name in ("member_name", "relation", "asset", "timeframe", "semantics_version"):
            _text(getattr(self, name), name=name)
        for name, value in self.__dict__.items():
            if name.endswith("_count") or name in {"resolved_hold_bars", "row_count"}:
                _count(value, name=name)
        if self.relation not in {"temporal", "cross_asset", "cross_timeframe"}:
            raise TrendlineRobustnessReplicationError("fresh member relation is invalid")
        if self.timeframe not in {"1h", "4h"}:
            raise TrendlineRobustnessReplicationError("fresh member timeframe is invalid")
        if self.resolved_hold_bars != ROBUSTNESS_REPLICATION_EXPECTED_HOLD_BARS[self.timeframe]:
            raise TrendlineRobustnessReplicationError("resolved hold-bars differs for member timeframe")
        if self.row_count != ROBUSTNESS_EXPECTED_ROWS:
            raise TrendlineRobustnessReplicationError("replication member row count differs")
        if self.semantics_version != ROBUSTNESS_REPLICATION_MEMBER_SEMANTICS_VERSION:
            raise TrendlineRobustnessReplicationError("unsupported member-result semantics")
        expected = canonical_hash(
            _id_payload(self),
            semantics_version=ROBUSTNESS_REPLICATION_MEMBER_SEMANTICS_VERSION,
        )
        if self.member_result_id and self.member_result_id != expected:
            raise TrendlineRobustnessReplicationError("member result identity differs")
        object.__setattr__(self, "member_result_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {"member_result_id": self.member_result_id, **_id_payload(self)}


def _bundle_count(bundle: Any, name: str) -> int:
    return len(getattr(bundle, name))


def build_replication_member_evidence(
    d5a_spec: TrendlineRobustnessSourceMemberSpec,
    d5a_evidence: TrendlineRobustnessSourceMemberEvidence,
    protocol: TrendlineRobustnessReplicationProtocol,
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    d2_bundle: Any,
    d3_bundle: Any,
    d4a_bundle: Any,
    d4b_bundle: TrendlineStochasticNullComparisonBundle,
) -> TrendlineRobustnessReplicationMemberEvidence:
    """Build compact member evidence from authoritative typed bundles."""

    timeframe = d5a_spec.timeframe
    replay_frame = replay.timeframes[timeframe]
    return TrendlineRobustnessReplicationMemberEvidence(
        d5a_member_spec_id=d5a_spec.member_spec_id,
        d5a_member_evidence_id=d5a_evidence.member_evidence_id,
        member_name=d5a_spec.name,
        relation=d5a_spec.relation,
        asset=d5a_spec.asset,
        timeframe=timeframe,
        source_id=prepared.dataset.identity.source_refs[timeframe].source_id,
        availability_id=prepared.dataset.identity.availability_ids[timeframe],
        dataset_id=prepared.dataset.dataset_id,
        research_configuration_id=prepared.configuration.research_configuration_id,
        preparation_id=prepared.preparation_id,
        replication_protocol_id=protocol.replication_protocol_id,
        replay_id=replay.replay_id,
        cohort_id=d2_bundle.cohort_id,
        study_config_id=d2_bundle.study_config_id,
        stability_spec_id=d2_bundle.stability_spec_id,
        interaction_spec_id=d3_bundle.interaction_spec_id,
        d2_bundle_id=d2_bundle.structural_stability_bundle_id,
        d3_bundle_id=d3_bundle.interaction_utility_bundle_id,
        d4a_bundle_id=d4a_bundle.baseline_comparison_bundle_id,
        d4b_bundle_id=d4b_bundle.stochastic_null_comparison_bundle_id,
        resolved_hold_bars=d3_bundle.interaction_spec.break_confirmation_bars,
        row_count=len(prepared.dataset.frames[timeframe]),
        executed_prefix_count=replay_frame.executed_position_count,
        recorded_position_count=replay_frame.recorded_position_count,
        d2_state_count=_bundle_count(d2_bundle, "state_rows"),
        d2_transition_count=_bundle_count(d2_bundle, "transition_rows"),
        d2_drift_count=_bundle_count(d2_bundle, "drift_rows"),
        d2_episode_count=_bundle_count(d2_bundle, "episode_rows"),
        d2_survival_count=_bundle_count(d2_bundle, "survival_rows"),
        d3_event_count=_bundle_count(d3_bundle, "events"),
        d3_outcome_count=_bundle_count(d3_bundle, "outcomes"),
        d3_summary_count=_bundle_count(d3_bundle, "summaries"),
        d4a_selection_count=_bundle_count(d4a_bundle, "baseline_selections"),
        d4a_outcome_count=_bundle_count(d4a_bundle, "baseline_outcomes"),
        d4a_comparison_count=_bundle_count(d4a_bundle, "comparison_summaries"),
        d4b_selection_count=_bundle_count(d4b_bundle, "stochastic_selections"),
        d4b_available_selection_count=sum(row.available for row in d4b_bundle.stochastic_selections),
        d4b_abstention_count=sum(not row.available for row in d4b_bundle.stochastic_selections),
        d4b_outcome_count=_bundle_count(d4b_bundle, "null_outcomes"),
        d4b_comparison_count=_bundle_count(d4b_bundle, "repetition_comparisons"),
        d4b_distribution_count=_bundle_count(d4b_bundle, "distribution_summaries"),
        semantics_version=ROBUSTNESS_REPLICATION_MEMBER_SEMANTICS_VERSION,
    )


def validate_replication_member_evidence(
    d5a_spec: TrendlineRobustnessSourceMemberSpec,
    d5a_evidence: TrendlineRobustnessSourceMemberEvidence,
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    study_config: TrendlineAdequacyStudyConfig,
    d2_bundle: Any,
    d3_bundle: Any,
    d4a_bundle: Any,
    d4b_bundle: TrendlineStochasticNullComparisonBundle,
    member_result: TrendlineRobustnessReplicationMemberEvidence,
    protocol: TrendlineRobustnessReplicationProtocol,
) -> None:
    """Validate one result row and its complete D2-D4B evidence chain."""

    validate_replication_protocol(protocol)
    validate_robustness_source_member_evidence(d5a_spec, d5a_evidence)
    if d5a_spec.name not in ROBUSTNESS_MEMBER_NAMES[1:]:
        raise TrendlineRobustnessReplicationError("member is not a fresh D5B member")
    timeframe = d5a_spec.timeframe
    if replay.prepared is not prepared:
        raise TrendlineRobustnessReplicationError("replay does not belong to prepared run")
    frame = prepared.dataset.frames[timeframe]
    if len(frame) != d5a_evidence.row_count:
        raise TrendlineRobustnessReplicationError("prepared frame row count differs from D5A")
    actual_identity = {
        "source_id": prepared.dataset.identity.source_refs[timeframe].source_id,
        "availability_id": prepared.dataset.identity.availability_ids[timeframe],
        "dataset_id": prepared.dataset.dataset_id,
        "research_configuration_id": prepared.configuration.research_configuration_id,
        "preparation_id": prepared.preparation_id,
    }
    expected_identity = {
        key: getattr(d5a_evidence, key) for key in actual_identity
    }
    if actual_identity != expected_identity:
        raise TrendlineRobustnessReplicationError("prepared identity differs from D5A evidence")
    replay_window = replay.replay_spec.windows[timeframe]
    expected_window = (
        protocol.replay_warmup_start_position,
        protocol.replay_record_start_position,
        protocol.replay_end_position,
        protocol.replay_record_every,
    )
    actual_window = (
        replay_window.warmup_start_position,
        replay_window.record_start_position,
        replay_window.end_position,
        replay_window.record_every,
    )
    if actual_window != expected_window or replay.replay_spec.include_signals != protocol.include_signals:
        raise TrendlineRobustnessReplicationError("replay protocol differs")
    replay_frame = replay.timeframes[timeframe]
    if replay_frame.executed_position_count != 293 or replay_frame.recorded_position_count != 248:
        raise TrendlineRobustnessReplicationError("replay counts differ")
    expected_name = f"l2d5b-{d5a_spec.name}-robustness-replication-v1"
    if study_config.study_name != expected_name:
        raise TrendlineRobustnessReplicationError("member study name differs")
    _validate_study_config_against_protocol(d5a_spec, study_config, protocol)
    study_config.validate_for(prepared, replay)
    if d2_bundle.stability_spec_id != protocol.stability_spec_id:
        raise TrendlineRobustnessReplicationError("stability spec differs")
    if d3_bundle.interaction_spec.break_confirmation_bars != ROBUSTNESS_REPLICATION_EXPECTED_HOLD_BARS[timeframe]:
        raise TrendlineRobustnessReplicationError("interaction hold-bars differs")
    if tuple(d3_bundle.interaction_spec.evaluation_horizons_bars) != protocol.interaction_horizons_bars:
        raise TrendlineRobustnessReplicationError("interaction horizons differ")
    _validate_downstream_protocol_bindings(
        study_config,
        protocol,
        d2_bundle,
        d3_bundle,
        d4a_bundle,
        d4b_bundle,
    )
    validate_structural_stability_bundle(d2_bundle)
    validate_interaction_utility_bundle(
        d3_bundle,
        structural_stability_bundle=d2_bundle,
        replay=replay,
    )
    validate_baseline_comparison_bundle(
        d4a_bundle,
        prepared=prepared,
        replay=replay,
        structural_stability_bundle=d2_bundle,
        interaction_bundle=d3_bundle,
        study_config=study_config,
    )
    validate_stochastic_null_comparison_bundle(
        d4b_bundle,
        prepared=prepared,
        replay=replay,
        structural_stability_bundle=d2_bundle,
        interaction_bundle=d3_bundle,
        deterministic_baseline_bundle=d4a_bundle,
        study_config=study_config,
    )
    expected = build_replication_member_evidence(
        d5a_spec,
        d5a_evidence,
        protocol,
        prepared,
        replay,
        d2_bundle,
        d3_bundle,
        d4a_bundle,
        d4b_bundle,
    )
    if member_result.to_dict() != expected.to_dict():
        raise TrendlineRobustnessReplicationError("member result differs from evidence chain")


@dataclass(frozen=True)
class TrendlineRobustnessReplicationBundle:
    """Ordered aggregate D5B evidence for four fresh source members."""

    source_matrix_bundle_id: str
    protocol: TrendlineRobustnessReplicationProtocol
    reference_d2_bundle_id: str
    reference_d3_bundle_id: str
    reference_d4a_bundle_id: str
    reference_d4b_bundle_id: str
    member_results: tuple[TrendlineRobustnessReplicationMemberEvidence, ...]
    semantics_version: str
    robustness_replication_bundle_id: str = ""

    def __post_init__(self) -> None:
        _sha(self.source_matrix_bundle_id, name="source_matrix_bundle_id")
        if not isinstance(self.protocol, TrendlineRobustnessReplicationProtocol):
            raise TrendlineRobustnessReplicationError("replication protocol must be typed")
        for name, value, expected in (
            ("reference_d2_bundle_id", self.reference_d2_bundle_id, ROBUSTNESS_REFERENCE_D2_BUNDLE_ID),
            ("reference_d3_bundle_id", self.reference_d3_bundle_id, ROBUSTNESS_REFERENCE_D3_BUNDLE_ID),
            ("reference_d4a_bundle_id", self.reference_d4a_bundle_id, ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID),
            ("reference_d4b_bundle_id", self.reference_d4b_bundle_id, ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID),
        ):
            if _sha(value, name=name) != expected:
                raise TrendlineRobustnessReplicationError(f"{name} differs")
        rows = tuple(self.member_results)
        if len(rows) != 4 or not all(isinstance(row, TrendlineRobustnessReplicationMemberEvidence) for row in rows):
            raise TrendlineRobustnessReplicationError("D5B requires four typed member results")
        if tuple(row.member_name for row in rows) != ROBUSTNESS_MEMBER_NAMES[1:]:
            raise TrendlineRobustnessReplicationError("D5B member order differs")
        if self.semantics_version != ROBUSTNESS_REPLICATION_BUNDLE_SEMANTICS_VERSION:
            raise TrendlineRobustnessReplicationError("unsupported D5B bundle semantics")
        expected = canonical_hash(
            self._payload(),
            semantics_version=ROBUSTNESS_REPLICATION_BUNDLE_SEMANTICS_VERSION,
        )
        if self.robustness_replication_bundle_id and self.robustness_replication_bundle_id != expected:
            raise TrendlineRobustnessReplicationError("D5B bundle identity differs")
        object.__setattr__(self, "member_results", rows)
        object.__setattr__(self, "robustness_replication_bundle_id", expected)

    def _payload(self) -> dict[str, Any]:
        return {
            "source_matrix_bundle_id": self.source_matrix_bundle_id,
            "protocol": self.protocol.to_dict(),
            "replication_protocol_id": self.protocol.replication_protocol_id,
            "reference_d2_bundle_id": self.reference_d2_bundle_id,
            "reference_d3_bundle_id": self.reference_d3_bundle_id,
            "reference_d4a_bundle_id": self.reference_d4a_bundle_id,
            "reference_d4b_bundle_id": self.reference_d4b_bundle_id,
            "member_results": [row.to_dict() for row in self.member_results],
            "semantics_version": self.semantics_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "robustness_replication_bundle_id": self.robustness_replication_bundle_id,
            **self._payload(),
        }


def build_robustness_replication_bundle(
    source_matrix_bundle: TrendlineRobustnessSourceMatrixBundle,
    protocol: TrendlineRobustnessReplicationProtocol,
    member_results: Sequence[TrendlineRobustnessReplicationMemberEvidence],
) -> TrendlineRobustnessReplicationBundle:
    """Build ordered aggregate D5B result identity."""

    validate_replication_protocol(protocol)
    if not isinstance(source_matrix_bundle, TrendlineRobustnessSourceMatrixBundle):
        raise TypeError("source matrix must be typed")
    expected_fresh = source_matrix_bundle.member_specs[1:]
    rows = tuple(member_results)
    if len(rows) != len(expected_fresh):
        raise TrendlineRobustnessReplicationError("D5B member result count differs")
    for spec, evidence, row in zip(expected_fresh, source_matrix_bundle.member_evidence[1:], rows):
        if row.d5a_member_spec_id != spec.member_spec_id or row.d5a_member_evidence_id != evidence.member_evidence_id:
            raise TrendlineRobustnessReplicationError("member result does not bind D5A evidence")
        if row.replication_protocol_id != protocol.replication_protocol_id:
            raise TrendlineRobustnessReplicationError("member result protocol differs")
    return TrendlineRobustnessReplicationBundle(
        source_matrix_bundle_id=source_matrix_bundle.robustness_source_matrix_bundle_id,
        protocol=protocol,
        reference_d2_bundle_id=source_matrix_bundle.reference_d2_bundle_id,
        reference_d3_bundle_id=source_matrix_bundle.reference_d3_bundle_id,
        reference_d4a_bundle_id=source_matrix_bundle.reference_d4a_bundle_id,
        reference_d4b_bundle_id=source_matrix_bundle.reference_d4b_bundle_id,
        member_results=rows,
        semantics_version=ROBUSTNESS_REPLICATION_BUNDLE_SEMANTICS_VERSION,
    )


def validate_robustness_replication_bundle(
    bundle: TrendlineRobustnessReplicationBundle,
    source_matrix_bundle: TrendlineRobustnessSourceMatrixBundle,
) -> None:
    """Validate exact four-member aggregate scope and identity."""

    if not isinstance(bundle, TrendlineRobustnessReplicationBundle):
        raise TypeError("replication bundle must be typed")
    if not isinstance(source_matrix_bundle, TrendlineRobustnessSourceMatrixBundle):
        raise TypeError("source matrix must be typed")
    expected = build_robustness_replication_bundle(
        source_matrix_bundle,
        bundle.protocol,
        bundle.member_results,
    )
    if bundle.to_dict() != expected.to_dict():
        raise TrendlineRobustnessReplicationError("D5B aggregate evidence differs")


__all__ = [
    "ROBUSTNESS_REPLICATION_BREAK_POLICY",
    "ROBUSTNESS_REPLICATION_BUNDLE_SEMANTICS_VERSION",
    "ROBUSTNESS_REPLICATION_DETERMINISTIC_BASELINE_IDS",
    "ROBUSTNESS_REPLICATION_EXPECTED_HOLD_BARS",
    "ROBUSTNESS_REPLICATION_MEMBER_SEMANTICS_VERSION",
    "ROBUSTNESS_REPLICATION_METRICS",
    "ROBUSTNESS_REPLICATION_PROTOCOL_SEMANTICS_VERSION",
    "ROBUSTNESS_REPLICATION_STOCHASTIC_BASELINE_IDS",
    "TrendlineRobustnessReplicationBundle",
    "TrendlineRobustnessReplicationError",
    "TrendlineRobustnessReplicationMemberEvidence",
    "TrendlineRobustnessReplicationProtocol",
    "build_replication_member_evidence",
    "build_robustness_replication_bundle",
    "validate_replication_member_evidence",
    "validate_replication_protocol",
    "validate_robustness_replication_bundle",
]
