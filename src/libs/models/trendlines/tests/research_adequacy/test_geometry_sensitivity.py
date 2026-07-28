"""Focused D5C contract and pure-measurement tests."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from libs.models.trendlines.config.base_config import TrendlinesConfig
from libs.models.trendlines.workflows.research.adequacy import (
    GEOMETRY_SENSITIVITY_PERSISTENCE_POLICY,
    SENSITIVITY_D2_METRICS,
    SENSITIVITY_D3_METRICS,
    SENSITIVITY_D4A_METRICS,
    SENSITIVITY_D4B_METRICS,
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineSpec,
    TrendlineSensitivityDeltaRow,
    TrendlineSensitivityStageDigest,
    build_geometry_sensitivity_bundle,
    build_geometry_sensitivity_protocol,
    event_overlap_inventory,
    frozen_geometry_sensitivity_variants,
    validate_geometry_sensitivity_bundle,
    validate_geometry_sensitivity_capsule,
    validate_variant_root_configuration,
)
from libs.models.trendlines.workflows.research.adequacy.geometry_sensitivity import (
    TrendlineGeometrySensitivityCapsule,
    TrendlineGeometrySensitivityError,
)


def _sha(char: str = "a") -> str:
    return hashlib.sha256(char.encode()).hexdigest()


def _stochastic_specs():
    return (
        TrendlineAdequacyBaselineSpec(
            name="random-valid-pivot-pair-v1",
            kind=TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
            repetitions=2,
            seed=2026072701,
            preserves=("timeframe", "position", "role", "pivot_count", "causal_prefix"),
        ),
        TrendlineAdequacyBaselineSpec(
            name="causal-density-matched-null-v1",
            kind=TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
            repetitions=2,
            seed=2026072702,
            preserves=("timeframe", "position", "role", "ray_count", "observation_density", "causal_prefix"),
        ),
    )


def _protocol():
    return build_geometry_sensitivity_protocol(
        d5a_source_matrix_bundle_id=_sha(),
        d5b_replication_protocol_id=_sha("b"),
        d5b_replication_bundle_id=_sha("c"),
        member_names=(
            "reference-btcusdt-1h-20250101-v1",
            "temporal-btcusdt-1h-20250401-v1",
            "cross-asset-ethusdt-1h-20250401-v1",
            "cross-asset-solusdt-1h-20250401-v1",
            "cross-timeframe-btcusdt-4h-20250401-v1",
        ),
        deterministic_baseline_ids=(
            "ddf18905d6cad86f78d83ea45298531f329de23ac4afd214811c181538e3a930",
            "22e405ce85d3fda2352080942e631240e5c9f505cfe187764d9084913856d8c3",
        ),
        stochastic_baseline_specs=_stochastic_specs(),
    )


MEMBERS = (
    "reference-btcusdt-1h-20250101-v1",
    "temporal-btcusdt-1h-20250401-v1",
    "cross-asset-ethusdt-1h-20250401-v1",
    "cross-asset-solusdt-1h-20250401-v1",
    "cross-timeframe-btcusdt-4h-20250401-v1",
)


def _capsule(member: str, variant_index: int):
    variant = frozen_geometry_sensitivity_variants()[variant_index]
    digests = tuple(
        TrendlineSensitivityStageDigest(
            stage=stage,
            bundle_id=_sha(stage[0]),
            canonical_serialized_sha256=_sha(stage[0]),
            canonical_serialized_byte_length=1,
            summary_row_count=0,
        )
        for stage in ("d2", "d3", "d4a", "d4b")
    )
    return TrendlineGeometrySensitivityCapsule(
        d5a_member_spec_id=_sha("f"),
        d5a_member_evidence_id=_sha("g"),
        baseline_member_result_id=_sha("h"),
        member_name=member,
        relation="reference",
        asset="BTCUSDT",
        timeframe="1h",
        variant_id=variant.variant_id,
        canonical_root_configuration_id=_sha("i"),
        variant_root_configuration_id=_sha("j"),
        canonical_research_configuration_id=_sha("k"),
        variant_research_configuration_id=_sha("l"),
        canonical_preparation_id=_sha("m"),
        variant_preparation_id=_sha("n"),
        variant_replay_id=_sha("o"),
        variant_cohort_id=_sha("p"),
        variant_study_config_id=_sha("q"),
        variant_stability_spec_id=_sha("r"),
        variant_interaction_spec_id=_sha("s"),
        variant_d2_bundle_id=_sha("t"),
        variant_d3_bundle_id=_sha("u"),
        variant_d4a_bundle_id=_sha("v"),
        variant_d4b_bundle_id=_sha("w"),
        resolved_hold_bars=3,
        baseline_count_inventory={},
        variant_count_inventory={},
        event_overlap={"coarse_event_jaccard": None},
        stage_digests=digests,
        d2_summaries=(),
        d3_summaries=(),
        d4a_summaries=(),
        d4b_summaries=(),
        delta_rows=(),
    )


def _member_bindings(protocol):
    return {
        member: (
            SimpleNamespace(member_spec_id=_sha("f")),
            SimpleNamespace(member_evidence_id=_sha("g")),
            _sha("h"),
        )
        for member in protocol.member_names
    }


def test_variants_are_exactly_dense_then_sparse():
    variants = frozen_geometry_sensitivity_variants()
    assert tuple(value.name for value in variants) == ("dense-geometry-v1", "sparse-geometry-v1")


def test_dense_parameters_are_two():
    variant = frozen_geometry_sensitivity_variants()[0]
    assert dict(variant.extractor_params) == {"window_left": 2, "window_right": 2}
    assert dict(variant.fitter_params) == {"line_fit_mode": "endpoint", "pivot_window": 2}


def test_sparse_parameters_are_four():
    variant = frozen_geometry_sensitivity_variants()[1]
    assert dict(variant.extractor_params) == {"window_left": 4, "window_right": 4}
    assert dict(variant.fitter_params) == {"line_fit_mode": "endpoint", "pivot_window": 4}


def test_variant_components_and_endpoint_mode_are_fixed():
    for variant in frozen_geometry_sensitivity_variants():
        assert (variant.extractor, variant.fitter) == ("fractal", "pathfinding")
        assert dict(variant.fitter_params)["line_fit_mode"] == "endpoint"


@pytest.mark.parametrize("field", ["name", "direction", "extractor", "fitter"])
def test_variant_rejects_mutated_component_contract(field):
    variant = frozen_geometry_sensitivity_variants()[0]
    values = {field: "wrong"}
    with pytest.raises(ValueError):
        replace(variant, **values)


def test_variant_rejects_unauthorised_changed_path():
    variant = frozen_geometry_sensitivity_variants()[0]
    with pytest.raises(ValueError):
        replace(variant, changed_field_paths=("signal_weights.foo",))


def test_variant_rejects_wrong_root_id():
    variant = frozen_geometry_sensitivity_variants()[0]
    with pytest.raises(ValueError):
        replace(variant, expected_root_configuration_id=_sha("z"))


def test_protocol_binds_persistence_policy():
    assert _protocol().persistence_policy == GEOMETRY_SENSITIVITY_PERSISTENCE_POLICY


def test_protocol_binds_five_members_and_two_variants():
    protocol = _protocol()
    assert len(protocol.member_names) == 5
    assert len(protocol.variants) == 2


def test_protocol_binds_metric_catalog():
    protocol = _protocol()
    assert dict(protocol.metric_catalog)["d2"] == SENSITIVITY_D2_METRICS
    assert dict(protocol.metric_catalog)["d3"] == SENSITIVITY_D3_METRICS
    assert dict(protocol.metric_catalog)["d4a"] == SENSITIVITY_D4A_METRICS
    assert dict(protocol.metric_catalog)["d4b"] == SENSITIVITY_D4B_METRICS


def test_protocol_binds_quantiles():
    assert _protocol().quantile_probabilities == (0.05, 0.95)


def test_protocol_rejects_wrong_horizon():
    protocol = _protocol()
    with pytest.raises(ValueError):
        replace(protocol, d2_horizons_bars=(1, 2, 3, 4))


def test_protocol_rejects_wrong_variant_order():
    protocol = _protocol()
    with pytest.raises(ValueError):
        replace(protocol, variants=tuple(reversed(protocol.variants)))


def test_protocol_rejects_noncanonical_persistence_policy():
    protocol = _protocol()
    with pytest.raises(ValueError):
        replace(protocol, persistence_policy="full_raw_bundle")


def test_stage_digest_is_content_addressed():
    row = TrendlineSensitivityStageDigest("d2", _sha(), _sha("b"), 12, 2)
    assert row.stage_digest_id
    assert row.to_dict()["canonical_serialized_byte_length"] == 12


def test_stage_digest_rejects_zero_bytes():
    with pytest.raises(ValueError):
        TrendlineSensitivityStageDigest("d2", _sha(), _sha("b"), 0, 2)


def test_stage_digest_rejects_bad_stage():
    with pytest.raises(ValueError):
        TrendlineSensitivityStageDigest("d5", _sha(), _sha("b"), 1, 2)


def test_d2_delta_requires_observation_unit_only():
    row = TrendlineSensitivityDeltaRow("d2", "1h", "birth_rate", "fitted_line", None, None, None, 1, 2, 1)
    assert row.delta == 1.0
    with pytest.raises(ValueError):
        replace(row, role="support")


def test_d3_delta_requires_role_and_horizon():
    row = TrendlineSensitivityDeltaRow("d3", "1h", "touch_rate", None, "support", 3, None, 0.2, 0.4, 0.2)
    assert row.delta == 0.2
    with pytest.raises(ValueError):
        replace(row, horizon_bars=None)


def test_d4_delta_requires_baseline_id():
    row = TrendlineSensitivityDeltaRow("d4a", "1h", "touch_rate_delta", None, "support", 3, _sha(), 0.1, 0.2, 0.1)
    assert row.delta == 0.1
    with pytest.raises(ValueError):
        replace(row, baseline_id=None)


def test_undefined_delta_is_null():
    row = TrendlineSensitivityDeltaRow("d3", "1h", "touch_rate", None, "support", 1, None, None, 0.2, None)
    assert row.delta is None


def test_delta_sign_is_variant_minus_baseline():
    row = TrendlineSensitivityDeltaRow("d3", "1h", "touch_rate", None, "support", 1, None, 0.7, 0.2, -0.5)
    assert row.delta == -0.5


def test_d4b_metric_keeps_distribution_coordinate():
    row = TrendlineSensitivityDeltaRow("d4b", "1h", "mean_delta", None, "support", 1, _sha(), 0.7, 0.2, -0.5)
    assert row.metric_name == "mean_delta"


def test_event_overlap_counts_coarse_and_exact():
    first = SimpleNamespace(timeframe="1h", role="support", selection_position=10, anchor_key=(1, 2))
    same_position = SimpleNamespace(timeframe="1h", role="support", selection_position=10, anchor_key=(3, 4))
    result = event_overlap_inventory((first,), (same_position,))
    assert result["shared_coarse_event_count"] == 1
    assert result["shared_exact_event_count"] == 0
    assert result["coarse_event_jaccard"] == 1.0
    assert result["exact_event_jaccard"] == 0.0


def test_event_overlap_empty_union_is_null():
    result = event_overlap_inventory((), ())
    assert result["coarse_event_jaccard"] is None
    assert result["exact_event_jaccard"] is None


def test_variant_root_configuration_changes_only_three_paths():
    canonical = TrendlinesConfig()
    variant = replace(canonical, extractor_params={"window_left": 2, "window_right": 2}, fitter_params={"pivot_window": 2, "line_fit_mode": "endpoint"})
    validate_variant_root_configuration(canonical, variant, frozen_geometry_sensitivity_variants()[0])


def test_variant_root_configuration_rejects_signal_change():
    canonical = TrendlinesConfig()
    variant = replace(canonical, signal_default_weight=2.0, extractor_params={"window_left": 2, "window_right": 2}, fitter_params={"pivot_window": 2, "line_fit_mode": "endpoint"})
    with pytest.raises(ValueError):
        validate_variant_root_configuration(canonical, variant, frozen_geometry_sensitivity_variants()[0])


def test_capsule_has_no_raw_state_or_outcome_arrays():
    capsule = _capsule(MEMBERS[0], 0)
    payload = capsule.to_dict()
    assert "state_rows" not in payload
    assert "outcomes" not in payload
    assert "null_outcomes" not in payload


def test_capsule_id_changes_with_summary_content():
    first = _capsule(MEMBERS[0], 0)
    second = replace(first, d2_summaries=({"metric": 1},), capsule_id="")
    assert first.capsule_id != second.capsule_id


def test_capsule_rejects_stage_order_change():
    first = _capsule(MEMBERS[0], 0)
    with pytest.raises(ValueError):
        replace(first, stage_digests=tuple(reversed(first.stage_digests)))


def test_bundle_requires_exact_ten_capsules_in_member_variant_order():
    protocol = _protocol()
    capsules = tuple(_capsule(member, index) for member in protocol.member_names for index in (0, 1))
    bundle = build_geometry_sensitivity_bundle(
        d5a_source_matrix_bundle_id=protocol.d5a_source_matrix_bundle_id,
        d5b_replication_bundle_id=protocol.d5b_replication_bundle_id,
        protocol=protocol,
        capsules=capsules,
    )
    assert len(bundle.capsules) == 10
    assert bundle.to_dict()["capsule_ids"] == [row.capsule_id for row in capsules]
    assert "capsules" not in bundle.to_dict()


def test_capsule_validator_rejects_forged_baseline_result_binding():
    capsule = _capsule(MEMBERS[0], 0)
    with pytest.raises(TrendlineGeometrySensitivityError, match="baseline member result"):
        validate_geometry_sensitivity_capsule(
            capsule,
            d5a_member_spec=SimpleNamespace(),
            d5a_member_evidence=SimpleNamespace(),
            expected_baseline_member_result_id=_sha("z"),
            protocol=SimpleNamespace(),
            variant=SimpleNamespace(),
            baseline_bundles={},
            variant_bundles={},
            baseline_prepared=SimpleNamespace(),
            variant_prepared=SimpleNamespace(),
            baseline_replay=SimpleNamespace(),
            variant_replay=SimpleNamespace(),
            baseline_study_config=SimpleNamespace(),
            variant_study_config=SimpleNamespace(),
        )


def test_bundle_validator_binds_d5a_and_baseline_result_ids():
    protocol = _protocol()
    capsules = tuple(_capsule(member, index) for member in protocol.member_names for index in (0, 1))
    bundle = build_geometry_sensitivity_bundle(
        d5a_source_matrix_bundle_id=protocol.d5a_source_matrix_bundle_id,
        d5b_replication_bundle_id=protocol.d5b_replication_bundle_id,
        protocol=protocol,
        capsules=capsules,
    )
    validate_geometry_sensitivity_bundle(
        bundle,
        protocol=protocol,
        member_bindings=_member_bindings(protocol),
    )
    forged = replace(capsules[0], d5a_member_spec_id=_sha("z"), capsule_id="")
    forged_bundle = build_geometry_sensitivity_bundle(
        d5a_source_matrix_bundle_id=protocol.d5a_source_matrix_bundle_id,
        d5b_replication_bundle_id=protocol.d5b_replication_bundle_id,
        protocol=protocol,
        capsules=(forged, *capsules[1:]),
    )
    with pytest.raises(TrendlineGeometrySensitivityError, match="D5A member spec"):
        validate_geometry_sensitivity_bundle(
            forged_bundle,
            protocol=protocol,
            member_bindings=_member_bindings(protocol),
        )


def test_bundle_validator_rejects_wrong_d5a_member_evidence_binding():
    protocol = _protocol()
    capsules = tuple(_capsule(member, index) for member in protocol.member_names for index in (0, 1))
    bundle = build_geometry_sensitivity_bundle(
        d5a_source_matrix_bundle_id=protocol.d5a_source_matrix_bundle_id,
        d5b_replication_bundle_id=protocol.d5b_replication_bundle_id,
        protocol=protocol,
        capsules=capsules,
    )
    bindings = _member_bindings(protocol)
    bindings[MEMBERS[1]] = (
        bindings[MEMBERS[1]][0],
        SimpleNamespace(member_evidence_id=_sha("z")),
        bindings[MEMBERS[1]][2],
    )
    with pytest.raises(TrendlineGeometrySensitivityError, match="D5A member evidence"):
        validate_geometry_sensitivity_bundle(
            bundle,
            protocol=protocol,
            member_bindings=bindings,
        )


def test_bundle_validator_rejects_wrong_member_result_binding():
    protocol = _protocol()
    capsules = tuple(_capsule(member, index) for member in protocol.member_names for index in (0, 1))
    bundle = build_geometry_sensitivity_bundle(
        d5a_source_matrix_bundle_id=protocol.d5a_source_matrix_bundle_id,
        d5b_replication_bundle_id=protocol.d5b_replication_bundle_id,
        protocol=protocol,
        capsules=capsules,
    )
    bindings = _member_bindings(protocol)
    bindings[MEMBERS[0]] = (bindings[MEMBERS[0]][0], bindings[MEMBERS[0]][1], _sha("z"))
    with pytest.raises(TrendlineGeometrySensitivityError, match="baseline member result"):
        validate_geometry_sensitivity_bundle(
            bundle,
            protocol=protocol,
            member_bindings=bindings,
        )


def test_bundle_rejects_permuted_capsules():
    protocol = _protocol()
    capsules = tuple(_capsule(member, index) for member in protocol.member_names for index in (0, 1))
    with pytest.raises(ValueError):
        build_geometry_sensitivity_bundle(
            d5a_source_matrix_bundle_id=protocol.d5a_source_matrix_bundle_id,
            d5b_replication_bundle_id=protocol.d5b_replication_bundle_id,
            protocol=protocol,
            capsules=(capsules[1], capsules[0], *capsules[2:]),
        )


def test_bundle_rejects_missing_capsule():
    protocol = _protocol()
    capsules = tuple(_capsule(member, index) for member in protocol.member_names for index in (0, 1))
    with pytest.raises(ValueError):
        build_geometry_sensitivity_bundle(
            d5a_source_matrix_bundle_id=protocol.d5a_source_matrix_bundle_id,
            d5b_replication_bundle_id=protocol.d5b_replication_bundle_id,
            protocol=protocol,
            capsules=capsules[:-1],
        )


def test_bundle_identity_changes_with_capsule():
    protocol = _protocol()
    capsules = tuple(_capsule(member, index) for member in protocol.member_names for index in (0, 1))
    first = build_geometry_sensitivity_bundle(d5a_source_matrix_bundle_id=protocol.d5a_source_matrix_bundle_id, d5b_replication_bundle_id=protocol.d5b_replication_bundle_id, protocol=protocol, capsules=capsules)
    changed = list(capsules)
    changed[-1] = _capsule(MEMBERS[-1], 1)
    changed[-1] = replace(changed[-1], variant_d4b_bundle_id=_sha("x"), capsule_id="")
    second = build_geometry_sensitivity_bundle(d5a_source_matrix_bundle_id=protocol.d5a_source_matrix_bundle_id, d5b_replication_bundle_id=protocol.d5b_replication_bundle_id, protocol=protocol, capsules=tuple(changed))
    assert first.geometry_sensitivity_bundle_id != second.geometry_sensitivity_bundle_id
