"""Frozen local geometry-width sensitivity contracts for trendline research."""

from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
from math import isclose, isfinite
from numbers import Real
from typing import Any, Mapping, Sequence

from libs.models.trendlines.contracts.identity import canonical_hash

from .baselines import (
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineSpec,
)


GEOMETRY_SENSITIVITY_VARIANT_SEMANTICS_VERSION = (
    "trendlines.adequacy-geometry-sensitivity-variant.v1"
)
GEOMETRY_SENSITIVITY_PROTOCOL_SEMANTICS_VERSION = (
    "trendlines.adequacy-geometry-sensitivity-protocol.v1"
)
SENSITIVITY_STAGE_DIGEST_SEMANTICS_VERSION = (
    "trendlines.adequacy-sensitivity-stage-digest.v1"
)
SENSITIVITY_DELTA_SEMANTICS_VERSION = (
    "trendlines.adequacy-sensitivity-delta.v1"
)
GEOMETRY_SENSITIVITY_CAPSULE_SEMANTICS_VERSION = (
    "trendlines.adequacy-geometry-sensitivity-capsule.v1"
)
GEOMETRY_SENSITIVITY_BUNDLE_SEMANTICS_VERSION = (
    "trendlines.adequacy-geometry-sensitivity-bundle.v1"
)
GEOMETRY_SENSITIVITY_PERSISTENCE_POLICY = (
    "validated_full_chain_compact_capsule_v1"
)
GEOMETRY_SENSITIVITY_STAGES = ("d2", "d3", "d4a", "d4b")
GEOMETRY_SENSITIVITY_VARIANT_NAMES = (
    "dense-geometry-v1",
    "sparse-geometry-v1",
)
GEOMETRY_SENSITIVITY_MEMBER_COUNT = 5
GEOMETRY_SENSITIVITY_MEMBER_NAMES = (
    "reference-btcusdt-1h-20250101-v1",
    "temporal-btcusdt-1h-20250401-v1",
    "cross-asset-ethusdt-1h-20250401-v1",
    "cross-asset-solusdt-1h-20250401-v1",
    "cross-timeframe-btcusdt-4h-20250401-v1",
)
GEOMETRY_SENSITIVITY_DETERMINISTIC_BASELINE_IDS = (
    "ddf18905d6cad86f78d83ea45298531f329de23ac4afd214811c181538e3a930",
    "22e405ce85d3fda2352080942e631240e5c9f505cfe187764d9084913856d8c3",
)
GEOMETRY_SENSITIVITY_CANONICAL_PARAMETERS = (
    ("extractor", "fractal"),
    ("extractor_params.window_left", 3),
    ("extractor_params.window_right", 3),
    ("fitter", "pathfinding"),
    ("fitter_params.pivot_window", 3),
    ("fitter_params.line_fit_mode", "endpoint"),
)
GEOMETRY_SENSITIVITY_BREAK_CONFIRMATION_POLICY = (
    "resolved_signals_hold_bars_at_first_recorded_point"
)
GEOMETRY_SENSITIVITY_COARSE_EVENT_KEY_DEFINITION = (
    "timeframe,role,selection_position"
)
GEOMETRY_SENSITIVITY_EXACT_EVENT_KEY_DEFINITION = (
    "timeframe,role,selection_position,canonical_anchor_key"
)
GEOMETRY_SENSITIVITY_STOCHASTIC_BASELINE_SHAPES = (
    {
        "name": "random-valid-pivot-pair-v1",
        "kind": TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
        "seed": 2026072701,
        "preserves": (
            "timeframe",
            "position",
            "role",
            "pivot_count",
            "causal_prefix",
        ),
    },
    {
        "name": "causal-density-matched-null-v1",
        "kind": TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
        "seed": 2026072702,
        "preserves": (
            "timeframe",
            "position",
            "role",
            "ray_count",
            "observation_density",
            "causal_prefix",
        ),
    },
)

SENSITIVITY_D2_METRICS = (
    "mean_active_anchor_count",
    "birth_rate",
    "revision_churn_rate",
    "anchor_persistence_rate",
    "episode_count",
    "total_birth_count",
    "survival_rate_h1",
    "survival_rate_h3",
    "survival_rate_h6",
    "survival_rate_h12",
)
SENSITIVITY_D3_METRICS = (
    "event_count",
    "eligible_event_count",
    "touch_rate",
    "rejection_rate",
    "confirmed_break_rate",
    "false_break_rate",
    "mean_penetration_atr",
    "mean_favourable_excursion_atr",
    "mean_adverse_excursion_atr",
)
SENSITIVITY_D4A_METRICS = (
    "baseline_coverage_rate",
    "touch_rate_delta",
    "rejection_rate_delta",
    "confirmed_break_rate_delta",
    "false_break_rate_delta",
    "mean_penetration_atr_delta",
    "mean_favourable_excursion_atr_delta",
    "mean_adverse_excursion_atr_delta",
)
SENSITIVITY_D4B_METRICS = (
    "mean_delta",
    "q05_delta",
    "q95_delta",
    "positive_fraction",
    "negative_fraction",
)
SENSITIVITY_METRIC_CATALOG = {
    "d2": SENSITIVITY_D2_METRICS,
    "d3": SENSITIVITY_D3_METRICS,
    "d4a": SENSITIVITY_D4A_METRICS,
    "d4b": SENSITIVITY_D4B_METRICS,
}

_VARIANT_IDENTITIES = {
    "dense-geometry-v1": {
        "reference-btcusdt-1h-20250101-v1": {
            "research_configuration_id": "850c16b4955008258b9e82dcb5edc2fefdfd87fe9544b2dc7f5fbd8810baca20",
            "preparation_id": "631aac0cf7a5977b139f7b4d605ef1fbfa5171b9dda17881545141a2506a1523",
        },
        "temporal-btcusdt-1h-20250401-v1": {
            "research_configuration_id": "850c16b4955008258b9e82dcb5edc2fefdfd87fe9544b2dc7f5fbd8810baca20",
            "preparation_id": "ee1613e873cacaf5e70550094f9143b8580ca1adc5610a3c7e44c602096735ba",
        },
        "cross-asset-ethusdt-1h-20250401-v1": {
            "research_configuration_id": "32be5e6de5a533cc1dff736dea5e471841921e7b6248ca50467e30fd7e4ea060",
            "preparation_id": "2b386bf83a514111020449c30fa28667bf37d2647d6491c8d418a1556dc32894",
        },
        "cross-asset-solusdt-1h-20250401-v1": {
            "research_configuration_id": "4ffffae881e1256e651a9101599c1c690080a1f3a2060c2465153e4907cf41ba",
            "preparation_id": "e16518403b04e8181d528c96a29196c6b285ebce3ae78be90b61419b9898daad",
        },
        "cross-timeframe-btcusdt-4h-20250401-v1": {
            "research_configuration_id": "dfd43eedf14d0c252f290cdb4df83ed279405f0bf03be10593026119ab4f8787",
            "preparation_id": "163d529449565476a69bcfae7faf0faf323828581224dda430eb1ca29bb6cf5e",
        },
    },
    "sparse-geometry-v1": {
        "reference-btcusdt-1h-20250101-v1": {
            "research_configuration_id": "26321eb510984c561bbc5ae495e4fe04d4840b16726b5a54a830613f90199a6b",
            "preparation_id": "bacb2fa69236812fb7f0edd3b23d4d251a087f921e92badb408f4725f6c86ee4",
        },
        "temporal-btcusdt-1h-20250401-v1": {
            "research_configuration_id": "26321eb510984c561bbc5ae495e4fe04d4840b16726b5a54a830613f90199a6b",
            "preparation_id": "d2314a5a2690f9cd40b0951a5bb1e94653d49919c21eb7c162d502c47ccb4b9d",
        },
        "cross-asset-ethusdt-1h-20250401-v1": {
            "research_configuration_id": "7ece25c7e6e8742bb10c52db2977696d6c4c6af6f42cd27175c1b5f4b240ce8d",
            "preparation_id": "c2434ed95c44ed64fe1b84d283eaf09b5f233725ae74f6f311d17b80af5cd793",
        },
        "cross-asset-solusdt-1h-20250401-v1": {
            "research_configuration_id": "3b1295006f59f58d47c781e2292b619b7e148572ace20caed4afcb34460b7207",
            "preparation_id": "cfc454245eeb71cb70c4064685b897f2495e64e010b9ae1464eb37b7a06cc36a",
        },
        "cross-timeframe-btcusdt-4h-20250401-v1": {
            "research_configuration_id": "9232be4d6dbc76e2c75ff295b066d162591d4cb055e46cc86034a24cebe7f985",
            "preparation_id": "5a5034da052803ddb1c40e630d62528f330c39315f924c7310bba0e6e7a8163a",
        },
    },
}


class TrendlineGeometrySensitivityError(ValueError):
    """Raised when frozen sensitivity evidence is incomplete or inconsistent."""


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineGeometrySensitivityError(f"{name} must be non-empty text")
    return value


def _sha(value: Any, *, name: str) -> str:
    value = _text(value, name=name)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise TrendlineGeometrySensitivityError(f"{name} must be lowercase SHA-256")
    return value


def _nonnegative_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrendlineGeometrySensitivityError(
            f"{name} must be a non-negative non-boolean integer"
        )
    return value


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TrendlineGeometrySensitivityError(
            f"{name} must be a positive non-boolean integer"
        )
    return value


def _number(value: Any, *, name: str) -> float:
    if value is None:
        raise TrendlineGeometrySensitivityError(f"{name} cannot be null here")
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(float(value)):
        raise TrendlineGeometrySensitivityError(f"{name} must be finite numeric")
    return float(value)


def _optional_number(value: Any, *, name: str) -> float | None:
    return None if value is None else _number(value, name=name)


def _mapping_items(value: Any, *, name: str) -> tuple[tuple[str, Any], ...]:
    if isinstance(value, Mapping):
        items = tuple((str(key), item) for key, item in value.items())
    else:
        try:
            items = tuple((str(key), item) for key, item in value)
        except (TypeError, ValueError) as exc:
            raise TrendlineGeometrySensitivityError(f"{name} must be a mapping") from exc
    if not items or len({key for key, _ in items}) != len(items):
        raise TrendlineGeometrySensitivityError(f"{name} must have unique keys")
    return tuple(sorted(items))


def _mapping(items: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    return {key: value for key, value in items}


@dataclass(frozen=True)
class TrendlineGeometrySensitivityVariant:
    """One predeclared geometry-width perturbation."""

    name: str
    direction: str
    extractor: str
    fitter: str
    extractor_params: tuple[tuple[str, Any], ...]
    fitter_params: tuple[tuple[str, Any], ...]
    changed_field_paths: tuple[str, ...]
    expected_root_configuration_id: str
    semantics_version: str = GEOMETRY_SENSITIVITY_VARIANT_SEMANTICS_VERSION
    variant_id: str = ""

    def __post_init__(self) -> None:
        name = _text(self.name, name="variant name")
        if name not in GEOMETRY_SENSITIVITY_VARIANT_NAMES:
            raise TrendlineGeometrySensitivityError("variant name is not frozen")
        direction = _text(self.direction, name="variant direction")
        expected_direction = "denser" if name.startswith("dense") else "sparser"
        if direction != expected_direction:
            raise TrendlineGeometrySensitivityError("variant direction differs")
        if self.extractor != "fractal" or self.fitter != "pathfinding":
            raise TrendlineGeometrySensitivityError("variant components are not frozen")
        extractor_params = _mapping_items(self.extractor_params, name="extractor_params")
        fitter_params = _mapping_items(self.fitter_params, name="fitter_params")
        width = 2 if name.startswith("dense") else 4
        if _mapping(extractor_params) != {"window_left": width, "window_right": width}:
            raise TrendlineGeometrySensitivityError("variant extractor parameters differ")
        if _mapping(fitter_params) != {"line_fit_mode": "endpoint", "pivot_window": width}:
            raise TrendlineGeometrySensitivityError("variant fitter parameters differ")
        paths = tuple(self.changed_field_paths)
        if paths != (
            "extractor_params.window_left",
            "extractor_params.window_right",
            "fitter_params.pivot_window",
        ):
            raise TrendlineGeometrySensitivityError("variant changed-field paths differ")
        _sha(self.expected_root_configuration_id, name="expected root configuration ID")
        if self.semantics_version != GEOMETRY_SENSITIVITY_VARIANT_SEMANTICS_VERSION:
            raise TrendlineGeometrySensitivityError("unsupported variant semantics")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "extractor_params", extractor_params)
        object.__setattr__(self, "fitter_params", fitter_params)
        payload = self.to_dict(include_id=False)
        expected_id = canonical_hash(payload, semantics_version=self.semantics_version)
        if self.variant_id and self.variant_id != expected_id:
            raise TrendlineGeometrySensitivityError("variant ID differs from content")
        object.__setattr__(self, "variant_id", expected_id)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "direction": self.direction,
            "extractor": self.extractor,
            "fitter": self.fitter,
            "extractor_params": _mapping(self.extractor_params),
            "fitter_params": _mapping(self.fitter_params),
            "changed_field_paths": list(self.changed_field_paths),
            "expected_root_configuration_id": self.expected_root_configuration_id,
            "semantics_version": self.semantics_version,
        }
        if include_id:
            payload["variant_id"] = self.variant_id
        return payload


def frozen_geometry_sensitivity_variants() -> tuple[TrendlineGeometrySensitivityVariant, ...]:
    return (
        TrendlineGeometrySensitivityVariant(
            name="dense-geometry-v1",
            direction="denser",
            extractor="fractal",
            fitter="pathfinding",
            extractor_params=(
                ("window_left", 2),
                ("window_right", 2),
            ),
            fitter_params=(("line_fit_mode", "endpoint"), ("pivot_window", 2)),
            changed_field_paths=(
                "extractor_params.window_left",
                "extractor_params.window_right",
                "fitter_params.pivot_window",
            ),
            expected_root_configuration_id=(
                "485757ce8b5604a577fd8b8af3f51587f107534be926c81fa7f8dfc437420b50"
            ),
        ),
        TrendlineGeometrySensitivityVariant(
            name="sparse-geometry-v1",
            direction="sparser",
            extractor="fractal",
            fitter="pathfinding",
            extractor_params=(
                ("window_left", 4),
                ("window_right", 4),
            ),
            fitter_params=(("line_fit_mode", "endpoint"), ("pivot_window", 4)),
            changed_field_paths=(
                "extractor_params.window_left",
                "extractor_params.window_right",
                "fitter_params.pivot_window",
            ),
            expected_root_configuration_id=(
                "e5ca61e9b43e4d5a0224dbbd2890f8a337caac314d05fc613866130a03146c7c"
            ),
        ),
    )


def expected_geometry_variant_identity(variant_name: str, member_name: str) -> dict[str, str]:
    try:
        return dict(_VARIANT_IDENTITIES[variant_name][member_name])
    except KeyError as exc:
        raise TrendlineGeometrySensitivityError(
            f"no frozen sensitivity identity for {variant_name}/{member_name}"
        ) from exc


def validate_variant_root_configuration(
    canonical_config: Any,
    variant_config: Any,
    variant: TrendlineGeometrySensitivityVariant,
) -> None:
    """Require exactly three authorised root-configuration changes."""

    for field in fields(canonical_config):
        name = field.name
        if name in {"extractor_params", "fitter_params"}:
            continue
        if getattr(canonical_config, name) != getattr(variant_config, name):
            raise TrendlineGeometrySensitivityError(
                f"variant changes unauthorised root field: {name}"
            )
    canonical_extractor = dict(canonical_config.extractor_params)
    variant_extractor = dict(variant_config.extractor_params)
    canonical_fitter = dict(canonical_config.fitter_params)
    variant_fitter = dict(variant_config.fitter_params)
    if set(canonical_extractor) != {"window_left", "window_right"}:
        raise TrendlineGeometrySensitivityError("canonical extractor parameters differ")
    if set(canonical_fitter) != {"pivot_window", "line_fit_mode"}:
        raise TrendlineGeometrySensitivityError("canonical fitter parameters differ")
    if variant_config.extractor != "fractal" or variant_config.fitter != "pathfinding":
        raise TrendlineGeometrySensitivityError("variant component names differ")
    if canonical_fitter["line_fit_mode"] != "endpoint" or variant_fitter["line_fit_mode"] != "endpoint":
        raise TrendlineGeometrySensitivityError("line_fit_mode changed")
    width = 2 if variant.name.startswith("dense") else 4
    if variant_extractor != {"window_left": width, "window_right": width}:
        raise TrendlineGeometrySensitivityError("variant extractor width differs")
    if variant_fitter != {"pivot_window": width, "line_fit_mode": "endpoint"}:
        raise TrendlineGeometrySensitivityError("variant fitter width differs")


@dataclass(frozen=True)
class TrendlineGeometrySensitivityProtocol:
    """Complete D5C protocol; every execution-affecting field is explicit."""

    d5a_source_matrix_bundle_id: str
    d5b_replication_protocol_id: str
    d5b_replication_bundle_id: str
    member_names: tuple[str, ...]
    variants: tuple[TrendlineGeometrySensitivityVariant, ...]
    canonical_geometry_parameters: tuple[tuple[str, Any], ...]
    d2_horizons_bars: tuple[int, ...]
    interaction_horizons_bars: tuple[int, ...]
    deterministic_baseline_ids: tuple[str, ...]
    stochastic_baseline_specs: tuple[TrendlineAdequacyBaselineSpec, ...]
    quantile_probabilities: tuple[float, ...]
    break_confirmation_policy: str
    coarse_event_key_definition: str
    exact_event_key_definition: str
    metric_catalog: tuple[tuple[str, tuple[str, ...]], ...]
    persistence_policy: str
    semantics_version: str = GEOMETRY_SENSITIVITY_PROTOCOL_SEMANTICS_VERSION
    protocol_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "d5a_source_matrix_bundle_id",
            "d5b_replication_protocol_id",
            "d5b_replication_bundle_id",
        ):
            _sha(getattr(self, name), name=name)
        members = tuple(_text(value, name="member name") for value in self.member_names)
        if members != GEOMETRY_SENSITIVITY_MEMBER_NAMES:
            raise TrendlineGeometrySensitivityError(
                "D5C member scope/order differs from frozen source matrix"
            )
        variants = tuple(self.variants)
        if tuple(value.name for value in variants) != GEOMETRY_SENSITIVITY_VARIANT_NAMES:
            raise TrendlineGeometrySensitivityError("D5C variants must be dense then sparse")
        if tuple(self.d2_horizons_bars) != (1, 3, 6, 12) or tuple(self.interaction_horizons_bars) != (1, 3, 6, 12):
            raise TrendlineGeometrySensitivityError("D5C horizons are not frozen")
        if tuple(self.deterministic_baseline_ids) != (
            *GEOMETRY_SENSITIVITY_DETERMINISTIC_BASELINE_IDS,
        ):
            raise TrendlineGeometrySensitivityError(
                "D5C deterministic baseline identities differ"
            )
        stochastic_specs = tuple(self.stochastic_baseline_specs)
        if len(stochastic_specs) != len(GEOMETRY_SENSITIVITY_STOCHASTIC_BASELINE_SHAPES):
            raise TrendlineGeometrySensitivityError("D5C stochastic baseline scope differs")
        for spec, expected in zip(
            stochastic_specs, GEOMETRY_SENSITIVITY_STOCHASTIC_BASELINE_SHAPES
        ):
            if not isinstance(spec, TrendlineAdequacyBaselineSpec):
                raise TrendlineGeometrySensitivityError("D5C stochastic specs are invalid")
            if (
                spec.name != expected["name"]
                or spec.kind is not expected["kind"]
                or spec.seed != expected["seed"]
                or spec.preserves != expected["preserves"]
            ):
                raise TrendlineGeometrySensitivityError(
                    "D5C stochastic baseline definition differs"
                )
        probabilities = tuple(float(value) for value in self.quantile_probabilities)
        if probabilities != (0.05, 0.95):
            raise TrendlineGeometrySensitivityError("D5C quantiles are not frozen")
        if self.persistence_policy != GEOMETRY_SENSITIVITY_PERSISTENCE_POLICY:
            raise TrendlineGeometrySensitivityError("D5C persistence policy differs")
        catalog = tuple((stage, tuple(metrics)) for stage, metrics in self.metric_catalog)
        if dict(catalog) != SENSITIVITY_METRIC_CATALOG or tuple(stage for stage, _ in catalog) != GEOMETRY_SENSITIVITY_STAGES:
            raise TrendlineGeometrySensitivityError("D5C metric catalog differs")
        if tuple(self.canonical_geometry_parameters) != GEOMETRY_SENSITIVITY_CANONICAL_PARAMETERS:
            raise TrendlineGeometrySensitivityError(
                "D5C canonical geometry parameters differ"
            )
        if self.break_confirmation_policy != GEOMETRY_SENSITIVITY_BREAK_CONFIRMATION_POLICY:
            raise TrendlineGeometrySensitivityError(
                "D5C break-confirmation policy differs"
            )
        if self.coarse_event_key_definition != GEOMETRY_SENSITIVITY_COARSE_EVENT_KEY_DEFINITION:
            raise TrendlineGeometrySensitivityError("D5C coarse event key differs")
        if self.exact_event_key_definition != GEOMETRY_SENSITIVITY_EXACT_EVENT_KEY_DEFINITION:
            raise TrendlineGeometrySensitivityError("D5C exact event key differs")
        if self.semantics_version != GEOMETRY_SENSITIVITY_PROTOCOL_SEMANTICS_VERSION:
            raise TrendlineGeometrySensitivityError("unsupported D5C protocol semantics")
        object.__setattr__(self, "member_names", members)
        object.__setattr__(self, "variants", variants)
        object.__setattr__(self, "deterministic_baseline_ids", tuple(self.deterministic_baseline_ids))
        object.__setattr__(self, "stochastic_baseline_specs", stochastic_specs)
        object.__setattr__(self, "d2_horizons_bars", tuple(self.d2_horizons_bars))
        object.__setattr__(self, "interaction_horizons_bars", tuple(self.interaction_horizons_bars))
        object.__setattr__(self, "quantile_probabilities", probabilities)
        object.__setattr__(self, "metric_catalog", catalog)
        expected_id = canonical_hash(self.to_dict(include_id=False), semantics_version=self.semantics_version)
        if self.protocol_id and self.protocol_id != expected_id:
            raise TrendlineGeometrySensitivityError("D5C protocol ID differs from content")
        object.__setattr__(self, "protocol_id", expected_id)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "d5a_source_matrix_bundle_id": self.d5a_source_matrix_bundle_id,
            "d5b_replication_protocol_id": self.d5b_replication_protocol_id,
            "d5b_replication_bundle_id": self.d5b_replication_bundle_id,
            "member_names": list(self.member_names),
            "variants": [value.to_dict() for value in self.variants],
            "canonical_geometry_parameters": _mapping(self.canonical_geometry_parameters),
            "d2_horizons_bars": list(self.d2_horizons_bars),
            "interaction_horizons_bars": list(self.interaction_horizons_bars),
            "deterministic_baseline_ids": list(self.deterministic_baseline_ids),
            "stochastic_baseline_specs": [value.to_dict() for value in self.stochastic_baseline_specs],
            "quantile_probabilities": list(self.quantile_probabilities),
            "break_confirmation_policy": self.break_confirmation_policy,
            "coarse_event_key_definition": self.coarse_event_key_definition,
            "exact_event_key_definition": self.exact_event_key_definition,
            "metric_catalog": {stage: list(metrics) for stage, metrics in self.metric_catalog},
            "persistence_policy": self.persistence_policy,
            "semantics_version": self.semantics_version,
        }
        if include_id:
            payload["geometry_sensitivity_protocol_id"] = self.protocol_id
        return payload


def build_geometry_sensitivity_protocol(
    *,
    d5a_source_matrix_bundle_id: str,
    d5b_replication_protocol_id: str,
    d5b_replication_bundle_id: str,
    member_names: Sequence[str],
    variants: Sequence[TrendlineGeometrySensitivityVariant] | None = None,
    deterministic_baseline_ids: Sequence[str],
    stochastic_baseline_specs: Sequence[TrendlineAdequacyBaselineSpec],
) -> TrendlineGeometrySensitivityProtocol:
    """Build D5C protocol from explicit prior-protocol values."""

    return TrendlineGeometrySensitivityProtocol(
        d5a_source_matrix_bundle_id=d5a_source_matrix_bundle_id,
        d5b_replication_protocol_id=d5b_replication_protocol_id,
        d5b_replication_bundle_id=d5b_replication_bundle_id,
        member_names=tuple(member_names),
        variants=tuple(variants or frozen_geometry_sensitivity_variants()),
        canonical_geometry_parameters=GEOMETRY_SENSITIVITY_CANONICAL_PARAMETERS,
        d2_horizons_bars=(1, 3, 6, 12),
        interaction_horizons_bars=(1, 3, 6, 12),
        deterministic_baseline_ids=tuple(deterministic_baseline_ids),
        stochastic_baseline_specs=tuple(stochastic_baseline_specs),
        quantile_probabilities=(0.05, 0.95),
        break_confirmation_policy=GEOMETRY_SENSITIVITY_BREAK_CONFIRMATION_POLICY,
        coarse_event_key_definition=GEOMETRY_SENSITIVITY_COARSE_EVENT_KEY_DEFINITION,
        exact_event_key_definition=GEOMETRY_SENSITIVITY_EXACT_EVENT_KEY_DEFINITION,
        metric_catalog=tuple(SENSITIVITY_METRIC_CATALOG.items()),
        persistence_policy=GEOMETRY_SENSITIVITY_PERSISTENCE_POLICY,
    )


@dataclass(frozen=True)
class TrendlineSensitivityStageDigest:
    stage: str
    bundle_id: str
    canonical_serialized_sha256: str
    canonical_serialized_byte_length: int
    summary_row_count: int
    semantics_version: str = SENSITIVITY_STAGE_DIGEST_SEMANTICS_VERSION
    stage_digest_id: str = ""

    def __post_init__(self) -> None:
        if self.stage not in GEOMETRY_SENSITIVITY_STAGES:
            raise TrendlineGeometrySensitivityError("stage is invalid")
        _sha(self.bundle_id, name="stage bundle ID")
        _sha(self.canonical_serialized_sha256, name="stage serialized SHA-256")
        _nonnegative_int(self.canonical_serialized_byte_length, name="stage byte length")
        if self.canonical_serialized_byte_length < 1:
            raise TrendlineGeometrySensitivityError("stage byte length must be positive")
        _nonnegative_int(self.summary_row_count, name="stage summary row count")
        if self.semantics_version != SENSITIVITY_STAGE_DIGEST_SEMANTICS_VERSION:
            raise TrendlineGeometrySensitivityError("stage digest semantics are unsupported")
        expected = canonical_hash(self.to_dict(include_id=False), semantics_version=self.semantics_version)
        if self.stage_digest_id and self.stage_digest_id != expected:
            raise TrendlineGeometrySensitivityError("stage digest ID differs from content")
        object.__setattr__(self, "stage_digest_id", expected)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "stage": self.stage,
            "bundle_id": self.bundle_id,
            "canonical_serialized_sha256": self.canonical_serialized_sha256,
            "canonical_serialized_byte_length": self.canonical_serialized_byte_length,
            "summary_row_count": self.summary_row_count,
            "semantics_version": self.semantics_version,
        }
        if include_id:
            payload["stage_digest_id"] = self.stage_digest_id
        return payload


def canonical_bundle_bytes(bundle: Any) -> bytes:
    """Canonical bytes used for full-chain stage digests."""

    if not hasattr(bundle, "to_dict"):
        raise TrendlineGeometrySensitivityError("bundle must expose to_dict")
    try:
        return (
            json.dumps(bundle.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TrendlineGeometrySensitivityError("bundle cannot be canonical serialized") from exc


def build_stage_digest(stage: str, bundle: Any, summary_row_count: int) -> TrendlineSensitivityStageDigest:
    serialized = canonical_bundle_bytes(bundle)
    identity_fields = {
        "d2": "structural_stability_bundle_id",
        "d3": "interaction_utility_bundle_id",
        "d4a": "baseline_comparison_bundle_id",
        "d4b": "stochastic_null_comparison_bundle_id",
    }
    return TrendlineSensitivityStageDigest(
        stage=stage,
        bundle_id=_sha(getattr(bundle, identity_fields[stage], ""), name="stage bundle ID"),
        canonical_serialized_sha256=hashlib.sha256(serialized).hexdigest(),
        canonical_serialized_byte_length=len(serialized),
        summary_row_count=summary_row_count,
    )


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _event_key(event: Any, *, exact: bool) -> str:
    payload: list[Any] = [event.timeframe, event.role, event.selection_position]
    if exact:
        payload.append(event.anchor_key)
    return _json_key(payload)


def event_overlap_inventory(baseline_events: Sequence[Any], variant_events: Sequence[Any]) -> dict[str, Any]:
    """Return exact coarse and anchor-aware event-population overlap."""

    result: dict[str, Any] = {
        "baseline_event_count": len(baseline_events),
        "variant_event_count": len(variant_events),
    }
    for label, exact in (("coarse", False), ("exact", True)):
        left = {_event_key(event, exact=exact) for event in baseline_events}
        right = {_event_key(event, exact=exact) for event in variant_events}
        union = left | right
        result[f"shared_{label}_event_count"] = len(left & right)
        result[f"union_{label}_event_count"] = len(union)
        result[f"{label}_event_jaccard"] = len(left & right) / len(union) if union else None
    return result


def _summary_metric(summary: Any, metric: str) -> float | int | None:
    if metric.startswith("survival_rate_h"):
        horizon = int(metric.removeprefix("survival_rate_h"))
        for row in summary.survival:
            if row.horizon_bars == horizon:
                return row.survival_rate
        raise TrendlineGeometrySensitivityError("D2 summary is missing survival horizon")
    value = getattr(summary, metric)
    return None if value is None else float(value) if isinstance(value, Real) else value


def _metric_rows(stage: str, bundle: Any) -> tuple[tuple[dict[str, Any], Any], ...]:
    if stage == "d2":
        return tuple((row.to_dict(), row) for row in bundle.summaries)
    if stage == "d3":
        return tuple((row.to_dict(), row) for row in bundle.summaries)
    if stage == "d4a":
        return tuple((row.to_dict(), row) for row in bundle.comparison_summaries)
    if stage == "d4b":
        return tuple((row.to_dict(), row) for row in bundle.distribution_summaries)
    raise TrendlineGeometrySensitivityError("unknown sensitivity stage")


def build_sensitivity_delta_rows(
    baseline_bundles: Mapping[str, Any],
    variant_bundles: Mapping[str, Any],
    *,
    semantics_version: str = SENSITIVITY_DELTA_SEMANTICS_VERSION,
) -> tuple["TrendlineSensitivityDeltaRow", ...]:
    """Build descriptive variant-minus-canonical deltas from typed summaries."""

    rows: list[TrendlineSensitivityDeltaRow] = []
    for stage in GEOMETRY_SENSITIVITY_STAGES:
        base = baseline_bundles[stage]
        variant = variant_bundles[stage]
        if stage == "d2":
            base_rows = {row.observation_unit.value: row for row in base.summaries}
            var_rows = {row.observation_unit.value: row for row in variant.summaries}
            if set(base_rows) != set(var_rows):
                raise TrendlineGeometrySensitivityError("D2 summary coordinates differ")
            for unit in sorted(base_rows):
                for metric in SENSITIVITY_D2_METRICS:
                    rows.append(_delta_row(stage, variant.timeframe if hasattr(variant, "timeframe") else base_rows[unit].timeframe, metric, base_rows[unit], var_rows[unit], observation_unit=unit, semantics_version=semantics_version))
        elif stage == "d3":
            base_rows = {(row.timeframe, row.role, row.horizon_bars): row for row in base.summaries}
            var_rows = {(row.timeframe, row.role, row.horizon_bars): row for row in variant.summaries}
            if set(base_rows) != set(var_rows):
                raise TrendlineGeometrySensitivityError("D3 summary coordinates differ")
            for timeframe, role, horizon in sorted(base_rows):
                for metric in SENSITIVITY_D3_METRICS:
                    rows.append(_delta_row(stage, timeframe, metric, base_rows[(timeframe, role, horizon)], var_rows[(timeframe, role, horizon)], role=role, horizon_bars=horizon, semantics_version=semantics_version))
        elif stage == "d4a":
            base_rows = {(row.baseline_id, row.timeframe, row.role, row.horizon_bars): row for row in base.comparison_summaries}
            var_rows = {(row.baseline_id, row.timeframe, row.role, row.horizon_bars): row for row in variant.comparison_summaries}
            if set(base_rows) != set(var_rows):
                raise TrendlineGeometrySensitivityError("D4A comparison coordinates differ")
            for baseline_id, timeframe, role, horizon in sorted(base_rows):
                for metric in SENSITIVITY_D4A_METRICS:
                    rows.append(_delta_row(stage, timeframe, metric, base_rows[(baseline_id, timeframe, role, horizon)], var_rows[(baseline_id, timeframe, role, horizon)], role=role, horizon_bars=horizon, baseline_id=baseline_id, semantics_version=semantics_version))
        else:
            base_rows = {(row.baseline_id, row.timeframe, row.role, row.horizon_bars, row.metric): row for row in base.distribution_summaries}
            var_rows = {(row.baseline_id, row.timeframe, row.role, row.horizon_bars, row.metric): row for row in variant.distribution_summaries}
            if set(base_rows) != set(var_rows):
                raise TrendlineGeometrySensitivityError("D4B distribution coordinates differ")
            for baseline_id, timeframe, role, horizon, metric in sorted(base_rows):
                for value_metric in SENSITIVITY_D4B_METRICS:
                    rows.append(_delta_row(stage, timeframe, value_metric, base_rows[(baseline_id, timeframe, role, horizon, metric)], var_rows[(baseline_id, timeframe, role, horizon, metric)], role=role, horizon_bars=horizon, baseline_id=baseline_id, metric_suffix=metric, semantics_version=semantics_version))
    return tuple(rows)


def _delta_row(stage: str, timeframe: str, metric: str, baseline: Any, variant: Any, *, observation_unit: str | None = None, role: str | None = None, horizon_bars: int | None = None, baseline_id: str | None = None, metric_suffix: str | None = None, semantics_version: str) -> "TrendlineSensitivityDeltaRow":
    if stage == "d4b":
        if metric == "positive_fraction":
            baseline_value = (
                baseline.positive_delta_count / baseline.defined_repetition_count
                if baseline.defined_repetition_count
                else None
            )
            variant_value = (
                variant.positive_delta_count / variant.defined_repetition_count
                if variant.defined_repetition_count
                else None
            )
        elif metric == "negative_fraction":
            baseline_value = (
                baseline.negative_delta_count / baseline.defined_repetition_count
                if baseline.defined_repetition_count
                else None
            )
            variant_value = (
                variant.negative_delta_count / variant.defined_repetition_count
                if variant.defined_repetition_count
                else None
            )
        else:
            baseline_value = getattr(baseline, metric)
            variant_value = getattr(variant, metric)
        metric_name = f"{metric_suffix}.{metric}"
    else:
        baseline_value = _summary_metric(baseline, metric)
        variant_value = _summary_metric(variant, metric)
        metric_name = metric
    return TrendlineSensitivityDeltaRow(
        stage=stage,
        timeframe=timeframe,
        metric_name=metric_name,
        observation_unit=observation_unit,
        role=role,
        horizon_bars=horizon_bars,
        baseline_id=baseline_id,
        baseline_value=baseline_value,
        variant_value=variant_value,
        delta=None if baseline_value is None or variant_value is None else float(variant_value) - float(baseline_value),
        semantics_version=semantics_version,
    )


@dataclass(frozen=True)
class TrendlineSensitivityDeltaRow:
    stage: str
    timeframe: str
    metric_name: str
    observation_unit: str | None
    role: str | None
    horizon_bars: int | None
    baseline_id: str | None
    baseline_value: float | int | None
    variant_value: float | int | None
    delta: float | None
    semantics_version: str = SENSITIVITY_DELTA_SEMANTICS_VERSION
    delta_row_id: str = ""

    def __post_init__(self) -> None:
        if self.stage not in GEOMETRY_SENSITIVITY_STAGES:
            raise TrendlineGeometrySensitivityError("delta stage is invalid")
        if self.metric_name not in SENSITIVITY_METRIC_CATALOG[self.stage] and not (
            self.stage == "d4b" and any(self.metric_name.endswith(f".{value}") for value in SENSITIVITY_D4B_METRICS)
        ):
            raise TrendlineGeometrySensitivityError("delta metric is not accepted")
        _text(self.timeframe, name="delta timeframe")
        if self.stage == "d2":
            if self.observation_unit is None or self.role is not None or self.horizon_bars is not None or self.baseline_id is not None:
                raise TrendlineGeometrySensitivityError("D2 delta coordinates are invalid")
        elif self.stage == "d3":
            if self.observation_unit is not None or self.role is None or self.horizon_bars is None or self.baseline_id is not None:
                raise TrendlineGeometrySensitivityError("D3 delta coordinates are invalid")
        else:
            if self.observation_unit is not None or self.role is None or self.horizon_bars is None or self.baseline_id is None:
                raise TrendlineGeometrySensitivityError("D4 delta coordinates are invalid")
            _sha(self.baseline_id, name="delta baseline ID")
        if self.horizon_bars is not None:
            _positive_int(self.horizon_bars, name="delta horizon")
        for name, value in (("baseline_value", self.baseline_value), ("variant_value", self.variant_value), ("delta", self.delta)):
            if value is not None:
                _number(value, name=name)
        expected_delta = (
            None
            if self.baseline_value is None or self.variant_value is None
            else float(self.variant_value) - float(self.baseline_value)
        )
        if expected_delta is None:
            delta_matches = self.delta is None
        else:
            delta_matches = self.delta is not None and isclose(
                float(self.delta), expected_delta, rel_tol=0.0, abs_tol=1e-12
            )
        if not delta_matches:
            raise TrendlineGeometrySensitivityError("delta is not variant minus baseline")
        if self.semantics_version != SENSITIVITY_DELTA_SEMANTICS_VERSION:
            raise TrendlineGeometrySensitivityError("delta semantics are unsupported")
        expected = canonical_hash(self.to_dict(include_id=False), semantics_version=self.semantics_version)
        if self.delta_row_id and self.delta_row_id != expected:
            raise TrendlineGeometrySensitivityError("delta row identity differs")
        object.__setattr__(self, "delta_row_id", expected)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "stage": self.stage,
            "timeframe": self.timeframe,
            "metric_name": self.metric_name,
            "observation_unit": self.observation_unit,
            "role": self.role,
            "horizon_bars": self.horizon_bars,
            "baseline_id": self.baseline_id,
            "baseline_value": self.baseline_value,
            "variant_value": self.variant_value,
            "delta": self.delta,
            "semantics_version": self.semantics_version,
        }
        if include_id:
            payload["delta_row_id"] = self.delta_row_id
        return payload


def _check_summary_rows(rows: Sequence[Mapping[str, Any]], *, name: str) -> tuple[dict[str, Any], ...]:
    result = tuple(dict(row) for row in rows)
    if any(any(key in row for key in ("state_rows", "outcomes", "null_outcomes", "stochastic_selections")) for row in result):
        raise TrendlineGeometrySensitivityError(f"{name} contains forbidden raw evidence rows")
    return result


@dataclass(frozen=True)
class TrendlineGeometrySensitivityCapsule:
    d5a_member_spec_id: str
    d5a_member_evidence_id: str
    baseline_member_result_id: str
    member_name: str
    relation: str
    asset: str
    timeframe: str
    variant_id: str
    canonical_root_configuration_id: str
    variant_root_configuration_id: str
    canonical_research_configuration_id: str
    variant_research_configuration_id: str
    canonical_preparation_id: str
    variant_preparation_id: str
    variant_replay_id: str
    variant_cohort_id: str
    variant_study_config_id: str
    variant_stability_spec_id: str
    variant_interaction_spec_id: str
    variant_d2_bundle_id: str
    variant_d3_bundle_id: str
    variant_d4a_bundle_id: str
    variant_d4b_bundle_id: str
    resolved_hold_bars: int
    baseline_count_inventory: Mapping[str, Any]
    variant_count_inventory: Mapping[str, Any]
    event_overlap: Mapping[str, Any]
    stage_digests: tuple[TrendlineSensitivityStageDigest, ...]
    d2_summaries: tuple[Mapping[str, Any], ...]
    d3_summaries: tuple[Mapping[str, Any], ...]
    d4a_summaries: tuple[Mapping[str, Any], ...]
    d4b_summaries: tuple[Mapping[str, Any], ...]
    delta_rows: tuple[TrendlineSensitivityDeltaRow, ...]
    semantics_version: str = GEOMETRY_SENSITIVITY_CAPSULE_SEMANTICS_VERSION
    capsule_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "d5a_member_spec_id", "d5a_member_evidence_id", "baseline_member_result_id",
            "variant_id", "canonical_root_configuration_id", "variant_root_configuration_id",
            "canonical_research_configuration_id", "variant_research_configuration_id",
            "canonical_preparation_id", "variant_preparation_id", "variant_replay_id",
            "variant_cohort_id", "variant_study_config_id", "variant_stability_spec_id",
            "variant_interaction_spec_id", "variant_d2_bundle_id", "variant_d3_bundle_id",
            "variant_d4a_bundle_id", "variant_d4b_bundle_id",
        ):
            _sha(getattr(self, name), name=name)
        for name in ("member_name", "relation", "asset", "timeframe"):
            _text(getattr(self, name), name=name)
        _positive_int(self.resolved_hold_bars, name="resolved hold bars")
        if self.semantics_version != GEOMETRY_SENSITIVITY_CAPSULE_SEMANTICS_VERSION:
            raise TrendlineGeometrySensitivityError("capsule semantics are unsupported")
        if tuple(row.stage for row in self.stage_digests) != GEOMETRY_SENSITIVITY_STAGES:
            raise TrendlineGeometrySensitivityError("capsule stage digest order differs")
        if not all(isinstance(row, TrendlineSensitivityStageDigest) for row in self.stage_digests):
            raise TrendlineGeometrySensitivityError("capsule stage digests are untyped")
        d2 = _check_summary_rows(self.d2_summaries, name="D2 summaries")
        d3 = _check_summary_rows(self.d3_summaries, name="D3 summaries")
        d4a = _check_summary_rows(self.d4a_summaries, name="D4A summaries")
        d4b = _check_summary_rows(self.d4b_summaries, name="D4B summaries")
        if not all(isinstance(row, TrendlineSensitivityDeltaRow) for row in self.delta_rows):
            raise TrendlineGeometrySensitivityError("capsule delta rows are untyped")
        object.__setattr__(self, "d2_summaries", d2)
        object.__setattr__(self, "d3_summaries", d3)
        object.__setattr__(self, "d4a_summaries", d4a)
        object.__setattr__(self, "d4b_summaries", d4b)
        expected = canonical_hash(self.to_dict(include_id=False), semantics_version=self.semantics_version)
        if self.capsule_id and self.capsule_id != expected:
            raise TrendlineGeometrySensitivityError("capsule ID differs from content")
        object.__setattr__(self, "capsule_id", expected)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "d5a_member_spec_id": self.d5a_member_spec_id,
            "d5a_member_evidence_id": self.d5a_member_evidence_id,
            "baseline_member_result_id": self.baseline_member_result_id,
            "member_name": self.member_name,
            "relation": self.relation,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "variant_id": self.variant_id,
            "canonical_root_configuration_id": self.canonical_root_configuration_id,
            "variant_root_configuration_id": self.variant_root_configuration_id,
            "canonical_research_configuration_id": self.canonical_research_configuration_id,
            "variant_research_configuration_id": self.variant_research_configuration_id,
            "canonical_preparation_id": self.canonical_preparation_id,
            "variant_preparation_id": self.variant_preparation_id,
            "variant_replay_id": self.variant_replay_id,
            "variant_cohort_id": self.variant_cohort_id,
            "variant_study_config_id": self.variant_study_config_id,
            "variant_stability_spec_id": self.variant_stability_spec_id,
            "variant_interaction_spec_id": self.variant_interaction_spec_id,
            "variant_d2_bundle_id": self.variant_d2_bundle_id,
            "variant_d3_bundle_id": self.variant_d3_bundle_id,
            "variant_d4a_bundle_id": self.variant_d4a_bundle_id,
            "variant_d4b_bundle_id": self.variant_d4b_bundle_id,
            "resolved_hold_bars": self.resolved_hold_bars,
            "baseline_count_inventory": dict(self.baseline_count_inventory),
            "variant_count_inventory": dict(self.variant_count_inventory),
            "event_overlap": dict(self.event_overlap),
            "stage_digests": [row.to_dict() for row in self.stage_digests],
            "d2_summaries": list(self.d2_summaries),
            "d3_summaries": list(self.d3_summaries),
            "d4a_summaries": list(self.d4a_summaries),
            "d4b_summaries": list(self.d4b_summaries),
            "delta_rows": [row.to_dict() for row in self.delta_rows],
            "semantics_version": self.semantics_version,
        }
        if include_id:
            payload["geometry_sensitivity_capsule_id"] = self.capsule_id
        return payload


def build_sensitivity_capsule(
    *,
    d5a_member_spec: Any,
    d5a_member_evidence: Any,
    baseline_member_result_id: str,
    variant: TrendlineGeometrySensitivityVariant,
    baseline_prepared: Any,
    baseline_replay: Any,
    baseline_bundles: Mapping[str, Any],
    variant_prepared: Any,
    variant_replay: Any,
    variant_bundles: Mapping[str, Any],
    protocol: TrendlineGeometrySensitivityProtocol,
) -> TrendlineGeometrySensitivityCapsule:
    """Snapshot validated chain summaries into one compact capsule."""

    stages = tuple(
        build_stage_digest(stage, variant_bundles[stage], len(_metric_rows(stage, variant_bundles[stage])))
        for stage in GEOMETRY_SENSITIVITY_STAGES
    )
    deltas = build_sensitivity_delta_rows(baseline_bundles, variant_bundles)
    return TrendlineGeometrySensitivityCapsule(
        d5a_member_spec_id=d5a_member_spec.member_spec_id,
        d5a_member_evidence_id=d5a_member_evidence.member_evidence_id,
        baseline_member_result_id=baseline_member_result_id,
        member_name=d5a_member_spec.name,
        relation=d5a_member_spec.relation.value if hasattr(d5a_member_spec.relation, "value") else str(d5a_member_spec.relation),
        asset=d5a_member_spec.asset,
        timeframe=d5a_member_spec.timeframe,
        variant_id=variant.variant_id,
        canonical_root_configuration_id=baseline_prepared.configuration.root_configuration_id,
        variant_root_configuration_id=variant_prepared.configuration.root_configuration_id,
        canonical_research_configuration_id=baseline_prepared.configuration.research_configuration_id,
        variant_research_configuration_id=variant_prepared.configuration.research_configuration_id,
        canonical_preparation_id=baseline_prepared.preparation_id,
        variant_preparation_id=variant_prepared.preparation_id,
        variant_replay_id=variant_replay.replay_id,
        variant_cohort_id=variant_bundles["d2"].cohort_id,
        variant_study_config_id=variant_bundles["d2"].study_config_id,
        variant_stability_spec_id=variant_bundles["d2"].stability_spec_id,
        variant_interaction_spec_id=variant_bundles["d3"].interaction_spec_id,
        variant_d2_bundle_id=variant_bundles["d2"].structural_stability_bundle_id,
        variant_d3_bundle_id=variant_bundles["d3"].interaction_utility_bundle_id,
        variant_d4a_bundle_id=variant_bundles["d4a"].baseline_comparison_bundle_id,
        variant_d4b_bundle_id=variant_bundles["d4b"].stochastic_null_comparison_bundle_id,
        resolved_hold_bars=variant_bundles["d3"].interaction_spec.break_confirmation_bars,
        baseline_count_inventory=_count_inventory(baseline_bundles),
        variant_count_inventory=_count_inventory(variant_bundles),
        event_overlap=event_overlap_inventory(baseline_bundles["d3"].events, variant_bundles["d3"].events),
        stage_digests=stages,
        d2_summaries=tuple(row.to_dict() for row in variant_bundles["d2"].summaries),
        d3_summaries=tuple(row.to_dict() for row in variant_bundles["d3"].summaries),
        d4a_summaries=tuple(row.to_dict() for row in variant_bundles["d4a"].comparison_summaries),
        d4b_summaries=tuple(row.to_dict() for row in variant_bundles["d4b"].distribution_summaries),
        delta_rows=deltas,
    )


def _count_inventory(bundles: Mapping[str, Any]) -> dict[str, Any]:
    d2, d3, d4a, d4b = (bundles[key] for key in GEOMETRY_SENSITIVITY_STAGES)
    return {
        "d2_state_count": len(d2.state_rows),
        "d2_transition_count": len(d2.transition_rows),
        "d2_drift_count": len(d2.drift_rows),
        "d2_episode_count": len(d2.episode_rows),
        "d2_survival_count": len(d2.survival_rows),
        "d2_summary_count": len(d2.summaries),
        "d3_event_count": len(d3.events),
        "d3_outcome_count": len(d3.outcomes),
        "d3_summary_count": len(d3.summaries),
        "d4a_selection_count": len(d4a.baseline_selections),
        "d4a_outcome_count": len(d4a.baseline_outcomes),
        "d4a_comparison_count": len(d4a.comparison_summaries),
        "d4b_selection_count": len(d4b.stochastic_selections),
        "d4b_available_selection_count": sum(row.available for row in d4b.stochastic_selections),
        "d4b_abstention_count": sum(not row.available for row in d4b.stochastic_selections),
        "d4b_outcome_count": len(d4b.null_outcomes),
        "d4b_comparison_count": len(d4b.repetition_comparisons),
        "d4b_distribution_count": len(d4b.distribution_summaries),
    }


def _relation_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _study_config_without_name(study_config: Any) -> dict[str, Any]:
    if not hasattr(study_config, "to_dict"):
        raise TrendlineGeometrySensitivityError("study config must expose to_dict")
    payload = dict(study_config.to_dict())
    payload.pop("study_name", None)
    return payload


def _validate_d5a_binding(
    capsule: TrendlineGeometrySensitivityCapsule,
    *,
    d5a_member_spec: Any,
    d5a_member_evidence: Any,
    prepared: Any,
) -> None:
    if capsule.d5a_member_spec_id != d5a_member_spec.member_spec_id:
        raise TrendlineGeometrySensitivityError("capsule D5A member spec differs")
    if capsule.d5a_member_evidence_id != d5a_member_evidence.member_evidence_id:
        raise TrendlineGeometrySensitivityError("capsule D5A member evidence differs")
    expected_member = {
        "member_name": d5a_member_spec.name,
        "relation": _relation_text(d5a_member_spec.relation),
        "asset": d5a_member_spec.asset,
        "timeframe": d5a_member_spec.timeframe,
    }
    actual_member = {
        key: getattr(capsule, key)
        for key in expected_member
    }
    if actual_member != expected_member:
        raise TrendlineGeometrySensitivityError("capsule D5A member binding differs")
    if prepared.spec.asset != d5a_member_spec.asset:
        raise TrendlineGeometrySensitivityError("prepared asset differs from D5A member")
    if d5a_member_spec.timeframe not in prepared.spec.timeframes:
        raise TrendlineGeometrySensitivityError("prepared timeframe differs from D5A member")
    source_ref = prepared.dataset.identity.source_refs[d5a_member_spec.timeframe]
    actual_identity = {
        "source_id": source_ref.source_id,
        "availability_id": prepared.dataset.identity.availability_ids[d5a_member_spec.timeframe],
        "dataset_id": prepared.dataset.dataset_id,
        "research_configuration_id": prepared.configuration.research_configuration_id,
        "preparation_id": prepared.preparation_id,
    }
    expected_identity = {
        "source_id": d5a_member_evidence.source_id,
        "availability_id": d5a_member_evidence.availability_id,
        "dataset_id": d5a_member_evidence.dataset_id,
        "research_configuration_id": d5a_member_evidence.research_configuration_id,
        "preparation_id": d5a_member_evidence.preparation_id,
    }
    if actual_identity != expected_identity:
        raise TrendlineGeometrySensitivityError("prepared identity differs from D5A evidence")


def _validate_chain_protocol_binding(
    bundles: Mapping[str, Any],
    *,
    protocol: TrendlineGeometrySensitivityProtocol,
    study_config: Any,
    hold_bars: int,
) -> None:
    from .stability import TrendlineStructuralStabilitySpec

    if set(bundles) != set(GEOMETRY_SENSITIVITY_STAGES):
        raise TrendlineGeometrySensitivityError("full-chain stages are incomplete")
    d2, d3, d4a, d4b = (bundles[key] for key in GEOMETRY_SENSITIVITY_STAGES)
    if d2.study_config_id != study_config.study_config_id:
        raise TrendlineGeometrySensitivityError("D2 study config differs from chain study config")
    if d3.study_config_id != study_config.study_config_id:
        raise TrendlineGeometrySensitivityError("D3 study config differs from chain study config")
    if d4a.study_config_id != study_config.study_config_id:
        raise TrendlineGeometrySensitivityError("D4A study config differs from chain study config")
    if d4b.study_config_id != study_config.study_config_id:
        raise TrendlineGeometrySensitivityError("D4B study config differs from chain study config")
    expected_stability_spec_id = TrendlineStructuralStabilitySpec(
        protocol.d2_horizons_bars
    ).stability_spec_id
    if d2.stability_spec_id != expected_stability_spec_id:
        raise TrendlineGeometrySensitivityError("D2 horizons differ from sensitivity protocol")
    if tuple(d3.interaction_spec.evaluation_horizons_bars) != protocol.interaction_horizons_bars:
        raise TrendlineGeometrySensitivityError("D3 horizons differ from sensitivity protocol")
    if d3.interaction_spec.break_confirmation_bars != hold_bars:
        raise TrendlineGeometrySensitivityError("D3 hold-bars differ from resolved chain value")
    if tuple(spec.to_dict() for spec in d4a.baseline_specs) != tuple(
        spec.to_dict() for spec in study_config.baseline_specs
    ):
        raise TrendlineGeometrySensitivityError("D4A specs differ from study config")
    if tuple(spec.to_dict() for spec in d4b.stochastic_baseline_specs) != tuple(
        spec.to_dict() for spec in protocol.stochastic_baseline_specs
    ):
        raise TrendlineGeometrySensitivityError(
            "D4B stochastic specs differ from sensitivity protocol"
        )
    if tuple(d4b.quantile_probabilities) != protocol.quantile_probabilities:
        raise TrendlineGeometrySensitivityError(
            "D4B quantiles differ from sensitivity protocol"
        )


def validate_geometry_sensitivity_capsule(
    capsule: TrendlineGeometrySensitivityCapsule,
    *,
    d5a_member_spec: Any,
    d5a_member_evidence: Any,
    expected_baseline_member_result_id: str,
    protocol: TrendlineGeometrySensitivityProtocol,
    variant: TrendlineGeometrySensitivityVariant,
    baseline_bundles: Mapping[str, Any],
    variant_bundles: Mapping[str, Any],
    baseline_prepared: Any,
    variant_prepared: Any,
    baseline_replay: Any,
    variant_replay: Any,
    baseline_study_config: Any,
    variant_study_config: Any,
) -> None:
    """Validate D5A binding, full chains, capsule content and stage digests."""

    if not isinstance(capsule, TrendlineGeometrySensitivityCapsule):
        raise TrendlineGeometrySensitivityError("capsule must be typed")
    _sha(
        expected_baseline_member_result_id,
        name="expected baseline member result ID",
    )
    if capsule.baseline_member_result_id != expected_baseline_member_result_id:
        raise TrendlineGeometrySensitivityError(
            "capsule baseline member result differs from committed binding"
        )
    if capsule.variant_id != variant.variant_id:
        raise TrendlineGeometrySensitivityError("capsule variant differs")
    if capsule.member_name not in protocol.member_names:
        raise TrendlineGeometrySensitivityError("capsule member is outside protocol scope")
    if d5a_member_spec.name != capsule.member_name:
        raise TrendlineGeometrySensitivityError("D5A member differs from capsule member")
    _validate_d5a_binding(
        capsule,
        d5a_member_spec=d5a_member_spec,
        d5a_member_evidence=d5a_member_evidence,
        prepared=baseline_prepared,
    )
    expected_variant_identity = expected_geometry_variant_identity(
        variant.name, capsule.member_name
    )
    if capsule.variant_root_configuration_id != variant.expected_root_configuration_id:
        raise TrendlineGeometrySensitivityError("variant root configuration differs")
    if capsule.variant_research_configuration_id != expected_variant_identity["research_configuration_id"]:
        raise TrendlineGeometrySensitivityError("variant research configuration differs")
    if capsule.variant_preparation_id != expected_variant_identity["preparation_id"]:
        raise TrendlineGeometrySensitivityError("variant preparation differs")
    if capsule.resolved_hold_bars != variant_bundles["d3"].interaction_spec.break_confirmation_bars:
        raise TrendlineGeometrySensitivityError("capsule hold-bars differ from D3 spec")
    if _study_config_without_name(baseline_study_config) != _study_config_without_name(
        variant_study_config
    ):
        raise TrendlineGeometrySensitivityError(
            "variant study config changes fields beyond study name"
        )
    validate_variant_root_configuration(
        baseline_prepared.configuration.pipeline_configs[capsule.timeframe].trendlines_config,
        variant_prepared.configuration.pipeline_configs[capsule.timeframe].trendlines_config,
        variant,
    )
    _validate_chain_protocol_binding(
        baseline_bundles,
        protocol=protocol,
        study_config=baseline_study_config,
        hold_bars=baseline_bundles["d3"].interaction_spec.break_confirmation_bars,
    )
    _validate_chain_protocol_binding(
        variant_bundles,
        protocol=protocol,
        study_config=variant_study_config,
        hold_bars=variant_bundles["d3"].interaction_spec.break_confirmation_bars,
    )
    _validate_full_chain(
        baseline_bundles,
        baseline_prepared,
        baseline_replay,
        baseline_study_config,
    )
    _validate_full_chain(
        variant_bundles,
        variant_prepared,
        variant_replay,
        variant_study_config,
    )
    expected = build_sensitivity_capsule(
        d5a_member_spec=d5a_member_spec,
        d5a_member_evidence=d5a_member_evidence,
        baseline_member_result_id=expected_baseline_member_result_id,
        variant=variant,
        baseline_prepared=baseline_prepared,
        baseline_replay=baseline_replay,
        baseline_bundles=baseline_bundles,
        variant_prepared=variant_prepared,
        variant_replay=variant_replay,
        variant_bundles=variant_bundles,
        protocol=protocol,
    )
    if expected.to_dict() != capsule.to_dict():
        raise TrendlineGeometrySensitivityError("capsule does not match full-chain recomputation")


def _validate_full_chain(
    bundles: Mapping[str, Any],
    prepared: Any,
    replay: Any,
    study_config: Any,
) -> None:
    from .baseline_comparison import validate_baseline_comparison_bundle
    from .interaction import validate_interaction_utility_bundle
    from .stability import validate_structural_stability_bundle
    from .stochastic_null_comparison import validate_stochastic_null_comparison_bundle

    d2, d3, d4a, d4b = (bundles[key] for key in GEOMETRY_SENSITIVITY_STAGES)
    validate_structural_stability_bundle(d2)
    validate_interaction_utility_bundle(d3, structural_stability_bundle=d2, replay=replay)
    validate_baseline_comparison_bundle(
        d4a,
        prepared=prepared,
        replay=replay,
        structural_stability_bundle=d2,
        interaction_bundle=d3,
        study_config=study_config,
    )
    validate_stochastic_null_comparison_bundle(
        d4b,
        prepared=prepared,
        replay=replay,
        structural_stability_bundle=d2,
        interaction_bundle=d3,
        deterministic_baseline_bundle=d4a,
        study_config=study_config,
    )


@dataclass(frozen=True)
class TrendlineGeometrySensitivityBundle:
    d5a_source_matrix_bundle_id: str
    d5b_replication_bundle_id: str
    sensitivity_protocol: TrendlineGeometrySensitivityProtocol
    capsules: tuple[TrendlineGeometrySensitivityCapsule, ...]
    geometry_sensitivity_bundle_id: str = ""

    @property
    def geometry_sensitivity_protocol_id(self) -> str:
        return self.sensitivity_protocol.protocol_id

    @property
    def capsule_ids(self) -> tuple[str, ...]:
        return tuple(row.capsule_id for row in self.capsules)

    def __post_init__(self) -> None:
        _sha(self.d5a_source_matrix_bundle_id, name="D5A matrix ID")
        _sha(self.d5b_replication_bundle_id, name="D5B bundle ID")
        if not isinstance(self.sensitivity_protocol, TrendlineGeometrySensitivityProtocol):
            raise TrendlineGeometrySensitivityError("sensitivity protocol must be typed")
        if not isinstance(self.capsules, tuple) or not all(isinstance(row, TrendlineGeometrySensitivityCapsule) for row in self.capsules):
            raise TrendlineGeometrySensitivityError("sensitivity capsules must be typed tuples")
        expected_order = tuple(
            (member, variant.variant_id)
            for member in self.sensitivity_protocol.member_names
            for variant in self.sensitivity_protocol.variants
        )
        actual_order = tuple((row.member_name, row.variant_id) for row in self.capsules)
        if actual_order != expected_order:
            raise TrendlineGeometrySensitivityError(
                "sensitivity bundle capsule order or coverage differs"
            )
        if len(set(self.capsule_ids)) != len(self.capsule_ids):
            raise TrendlineGeometrySensitivityError(
                "sensitivity bundle capsule IDs must be unique"
            )
        expected = canonical_hash(self.to_dict(include_id=False), semantics_version=GEOMETRY_SENSITIVITY_BUNDLE_SEMANTICS_VERSION)
        if self.geometry_sensitivity_bundle_id and self.geometry_sensitivity_bundle_id != expected:
            raise TrendlineGeometrySensitivityError("sensitivity bundle ID differs from content")
        object.__setattr__(self, "geometry_sensitivity_bundle_id", expected)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "d5a_source_matrix_bundle_id": self.d5a_source_matrix_bundle_id,
            "d5b_replication_bundle_id": self.d5b_replication_bundle_id,
            "sensitivity_protocol": self.sensitivity_protocol.to_dict(),
            "geometry_sensitivity_protocol_id": self.sensitivity_protocol.protocol_id,
            "capsule_ids": list(self.capsule_ids),
            "semantics_version": GEOMETRY_SENSITIVITY_BUNDLE_SEMANTICS_VERSION,
        }
        if include_id:
            payload["geometry_sensitivity_bundle_id"] = self.geometry_sensitivity_bundle_id
        return payload


def build_geometry_sensitivity_bundle(
    *,
    d5a_source_matrix_bundle_id: str,
    d5b_replication_bundle_id: str,
    protocol: TrendlineGeometrySensitivityProtocol,
    capsules: Sequence[TrendlineGeometrySensitivityCapsule],
) -> TrendlineGeometrySensitivityBundle:
    return TrendlineGeometrySensitivityBundle(
        d5a_source_matrix_bundle_id=d5a_source_matrix_bundle_id,
        d5b_replication_bundle_id=d5b_replication_bundle_id,
        sensitivity_protocol=protocol,
        capsules=tuple(capsules),
    )


def validate_geometry_sensitivity_bundle(
    bundle: TrendlineGeometrySensitivityBundle,
    *,
    protocol: TrendlineGeometrySensitivityProtocol,
    member_bindings: Mapping[str, tuple[Any, Any, str]],
) -> None:
    if not isinstance(bundle, TrendlineGeometrySensitivityBundle):
        raise TrendlineGeometrySensitivityError("sensitivity bundle must be typed")
    if bundle.sensitivity_protocol.to_dict() != protocol.to_dict():
        raise TrendlineGeometrySensitivityError("sensitivity protocol differs")
    if bundle.d5a_source_matrix_bundle_id != protocol.d5a_source_matrix_bundle_id:
        raise TrendlineGeometrySensitivityError("D5A matrix identity differs")
    if bundle.d5b_replication_bundle_id != protocol.d5b_replication_bundle_id:
        raise TrendlineGeometrySensitivityError("D5B bundle identity differs")
    if set(member_bindings) != set(protocol.member_names):
        raise TrendlineGeometrySensitivityError(
            "sensitivity member bindings differ from protocol scope"
        )
    expected_order = tuple(
        (member, variant.variant_id)
        for member in protocol.member_names
        for variant in protocol.variants
    )
    actual_order = tuple((row.member_name, row.variant_id) for row in bundle.capsules)
    if actual_order != expected_order:
        raise TrendlineGeometrySensitivityError(
            "sensitivity bundle capsule order or coverage differs"
        )
    for capsule in bundle.capsules:
        try:
            d5a_member_spec, d5a_member_evidence, expected_baseline_result_id = (
                member_bindings[capsule.member_name]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TrendlineGeometrySensitivityError(
                "sensitivity capsule member binding is malformed"
            ) from exc
        if capsule.d5a_member_spec_id != d5a_member_spec.member_spec_id:
            raise TrendlineGeometrySensitivityError(
                "sensitivity capsule D5A member spec differs"
            )
        if capsule.d5a_member_evidence_id != d5a_member_evidence.member_evidence_id:
            raise TrendlineGeometrySensitivityError(
                "sensitivity capsule D5A member evidence differs"
            )
        if capsule.baseline_member_result_id != expected_baseline_result_id:
            raise TrendlineGeometrySensitivityError(
                "sensitivity capsule baseline member result differs"
            )
        _sha(
            expected_baseline_result_id,
            name="expected baseline member result ID",
        )
        expected_capsule_id = canonical_hash(
            capsule.to_dict(include_id=False),
            semantics_version=GEOMETRY_SENSITIVITY_CAPSULE_SEMANTICS_VERSION,
        )
        if capsule.capsule_id != expected_capsule_id:
            raise TrendlineGeometrySensitivityError(
                "sensitivity capsule identity differs"
            )
    expected = canonical_hash(bundle.to_dict(include_id=False), semantics_version=GEOMETRY_SENSITIVITY_BUNDLE_SEMANTICS_VERSION)
    if bundle.geometry_sensitivity_bundle_id != expected:
        raise TrendlineGeometrySensitivityError("sensitivity bundle identity differs")


__all__ = [
    "GEOMETRY_SENSITIVITY_BUNDLE_SEMANTICS_VERSION",
    "GEOMETRY_SENSITIVITY_CAPSULE_SEMANTICS_VERSION",
    "GEOMETRY_SENSITIVITY_CANONICAL_PARAMETERS",
    "GEOMETRY_SENSITIVITY_BREAK_CONFIRMATION_POLICY",
    "GEOMETRY_SENSITIVITY_COARSE_EVENT_KEY_DEFINITION",
    "GEOMETRY_SENSITIVITY_DETERMINISTIC_BASELINE_IDS",
    "GEOMETRY_SENSITIVITY_EXACT_EVENT_KEY_DEFINITION",
    "GEOMETRY_SENSITIVITY_MEMBER_COUNT",
    "GEOMETRY_SENSITIVITY_MEMBER_NAMES",
    "GEOMETRY_SENSITIVITY_PERSISTENCE_POLICY",
    "GEOMETRY_SENSITIVITY_PROTOCOL_SEMANTICS_VERSION",
    "GEOMETRY_SENSITIVITY_STAGES",
    "GEOMETRY_SENSITIVITY_VARIANT_NAMES",
    "GEOMETRY_SENSITIVITY_VARIANT_SEMANTICS_VERSION",
    "GEOMETRY_SENSITIVITY_STOCHASTIC_BASELINE_SHAPES",
    "SENSITIVITY_D2_METRICS",
    "SENSITIVITY_D3_METRICS",
    "SENSITIVITY_D4A_METRICS",
    "SENSITIVITY_D4B_METRICS",
    "SENSITIVITY_METRIC_CATALOG",
    "SENSITIVITY_DELTA_SEMANTICS_VERSION",
    "TrendlineGeometrySensitivityError",
    "TrendlineGeometrySensitivityVariant",
    "TrendlineGeometrySensitivityProtocol",
    "TrendlineSensitivityStageDigest",
    "TrendlineSensitivityDeltaRow",
    "TrendlineGeometrySensitivityCapsule",
    "TrendlineGeometrySensitivityBundle",
    "frozen_geometry_sensitivity_variants",
    "expected_geometry_variant_identity",
    "validate_variant_root_configuration",
    "build_geometry_sensitivity_protocol",
    "canonical_bundle_bytes",
    "build_stage_digest",
    "event_overlap_inventory",
    "build_sensitivity_delta_rows",
    "build_sensitivity_capsule",
    "validate_geometry_sensitivity_capsule",
    "build_geometry_sensitivity_bundle",
    "validate_geometry_sensitivity_bundle",
]
