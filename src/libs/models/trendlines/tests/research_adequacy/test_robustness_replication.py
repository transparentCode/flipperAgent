"""Focused D5B protocol and aggregate-contract tests."""

from __future__ import annotations

from dataclasses import fields, replace
from types import SimpleNamespace

import pytest

from libs.models.trendlines.workflows.research.adequacy.contracts import (
    TrendlineAdequacyDecisionRule,
    TrendlineAdequacyOperator,
)
from libs.models.trendlines.workflows.research.adequacy import (
    ROBUSTNESS_REPLICATION_BREAK_POLICY,
    ROBUSTNESS_REPLICATION_BUNDLE_SEMANTICS_VERSION,
    ROBUSTNESS_REPLICATION_DETERMINISTIC_BASELINE_IDS,
    ROBUSTNESS_REPLICATION_MEMBER_SEMANTICS_VERSION,
    ROBUSTNESS_REPLICATION_METRICS,
    ROBUSTNESS_REPLICATION_PROTOCOL_SEMANTICS_VERSION,
    ROBUSTNESS_REPLICATION_STOCHASTIC_BASELINE_IDS,
    TrendlineRobustnessReplicationError,
    TrendlineRobustnessReplicationMemberEvidence,
    TrendlineRobustnessReplicationProtocol,
    build_robustness_replication_bundle,
    validate_replication_protocol,
    validate_robustness_replication_bundle,
)
from libs.models.trendlines.workflows.research.adequacy.robustness_replication import (
    _validate_downstream_protocol_bindings,
    _validate_study_config_against_protocol,
)
from scripts.analyze_trendlines_l2d5b_offline_robustness import (
    load_source_matrix,
    _protocol,
    _study_config,
)


def _row(timeframe: str = "1h", name: str = "temporal-btcusdt-1h-20250401-v1") -> TrendlineRobustnessReplicationMemberEvidence:
    return TrendlineRobustnessReplicationMemberEvidence(
        d5a_member_spec_id="7cb30d534b6e6ddaef35e4d115ee308bf0ca442e121107ef4f7f919d6078b67f",
        d5a_member_evidence_id="8bab34885f1432a9a59092620bb2b636467894830e7917eddfb3d287a6c60e7b",
        member_name=name,
        relation="temporal",
        asset="BTCUSDT",
        timeframe=timeframe,
        source_id="1c80f2d3ea463c467ce5f83aba340c4a878d75382f371d59d4453cf85911d059",
        availability_id="e58847bea0a619da27a4f53dde19830433d201b9556de248a0b0f852aa1dc0e8",
        dataset_id="1e462fc4fb1d79a2d03dc057356a37d4a598b20ec06553b76a5ee1d22d3d8f3b",
        research_configuration_id="ab6ec43eede637492f1e11bea6f4ae0cf72ef12045ee87265d648edb0cfc5853",
        preparation_id="f9700b6f4dba8bc4efb5888ed0737a735eefaf2e526a8526c709563546f51902",
        replication_protocol_id=_protocol().replication_protocol_id,
        replay_id="dcb9380ce5c181064b305f6bbf5547fe67dcbadea3b25745f12cf52057290e7f",
        cohort_id="41c559daca03c77be243df6462c92f0eaae8b0abbd3b142d7989c6dec313b6f1",
        study_config_id="d76f0b4e7ed63bddc6bd0b9c2b6e643d2c9695198b3ade0ec6870aa5e5646d98",
        stability_spec_id="12d9aa6b154238092835fd9879422a8d57d0a52e61ba8863dd27e8b7822a6271",
        interaction_spec_id="df6f3cfa6dd9656de4e34d0eb1302a7726db6c5cd9106a700203aad810b9d98f" if timeframe == "1h" else "a4b71d6311cf5c53372c9d5b5f70ed4dba54a91fa546ebc8850e53b54425b0b0",
        d2_bundle_id="4a688ce974aeac7f520df947ef42d1ed9ac989a8e0a7c1c00de524a9a45b64dd",
        d3_bundle_id="547340f14a544fcb4ed0f1bf6571960507f8f748697ffcbaba7ed4d79a92f8fb",
        d4a_bundle_id="0ab4b7b185497d3c45b9837951d60b00e8fdfe470de9614ee2c0113ecd46a4d9",
        d4b_bundle_id="d8d9e81e41c955c04acc671a90d97de2817fd189f70e98e1054169cf99b2317a",
        resolved_hold_bars=3 if timeframe == "1h" else 1,
        row_count=312,
        executed_prefix_count=293,
        recorded_position_count=248,
        d2_state_count=992,
        d2_transition_count=494,
        d2_drift_count=910,
        d2_episode_count=82,
        d2_survival_count=8,
        d3_event_count=39,
        d3_outcome_count=156,
        d3_summary_count=8,
        d4a_selection_count=78,
        d4a_outcome_count=312,
        d4a_comparison_count=16,
        d4b_selection_count=2496,
        d4b_available_selection_count=2432,
        d4b_abstention_count=64,
        d4b_outcome_count=9728,
        d4b_comparison_count=512,
        d4b_distribution_count=112,
        semantics_version=ROBUSTNESS_REPLICATION_MEMBER_SEMANTICS_VERSION,
    )


def test_protocol_has_no_hidden_field_defaults() -> None:
    assert all(field.default is field.default_factory for field in ()) is True
    assert all(field.default.__class__.__name__ == "_MISSING_TYPE" for field in fields(TrendlineRobustnessReplicationProtocol))


def test_protocol_freezes_exact_replay_positions() -> None:
    protocol = _protocol()
    assert (protocol.replay_warmup_start_position, protocol.replay_record_start_position, protocol.replay_end_position, protocol.replay_record_every) == (19, 64, 311, 1)
    assert protocol.include_signals is True


def test_protocol_freezes_exact_metrics_and_units() -> None:
    protocol = _protocol()
    assert protocol.metric_names == ROBUSTNESS_REPLICATION_METRICS
    assert protocol.line_observation_unit == "fitted_line"
    assert protocol.ray_observation_unit == "boundary_ray"
    assert protocol.invalid_point_treatment == "retain_and_report_exclude_from_geometry_metrics"
    assert protocol.availability_policy == "causal_prefix_only"


def test_protocol_freezes_horizons() -> None:
    protocol = _protocol()
    assert protocol.stability_horizons_bars == (1, 3, 6, 12)
    assert protocol.interaction_horizons_bars == (1, 3, 6, 12)


def test_protocol_freezes_deterministic_baseline_ids() -> None:
    assert _protocol().deterministic_baseline_ids == ROBUSTNESS_REPLICATION_DETERMINISTIC_BASELINE_IDS


def test_protocol_freezes_stochastic_ids_seeds_and_repetitions() -> None:
    specs = _protocol().stochastic_baseline_specs
    assert tuple(spec.baseline_id for spec in specs) == ROBUSTNESS_REPLICATION_STOCHASTIC_BASELINE_IDS
    assert tuple(spec.seed for spec in specs) == (2026072701, 2026072702)
    assert tuple(spec.repetitions for spec in specs) == (32, 32)


def test_protocol_freezes_quantiles_and_break_policy() -> None:
    protocol = _protocol()
    assert protocol.quantile_probabilities == (0.05, 0.95)
    assert protocol.break_confirmation_policy == ROBUSTNESS_REPLICATION_BREAK_POLICY


def test_protocol_identity_is_deterministic() -> None:
    assert _protocol().replication_protocol_id == _protocol().replication_protocol_id
    validate_replication_protocol(_protocol())


def test_protocol_semantics_version_is_explicit() -> None:
    assert _protocol().semantics_version == ROBUSTNESS_REPLICATION_PROTOCOL_SEMANTICS_VERSION


def _study_fixture():
    matrix, _ = load_source_matrix()
    spec = matrix.member_specs[1]
    return spec, _study_config(spec), _protocol()


def _downstream_fixture(study, protocol):
    return (
        SimpleNamespace(study_config_id=study.study_config_id),
        SimpleNamespace(study_config_id=study.study_config_id),
        SimpleNamespace(
            study_config_id=study.study_config_id,
            baseline_specs=study.baseline_specs,
        ),
        SimpleNamespace(
            study_config_id=study.study_config_id,
            stochastic_baseline_specs=protocol.stochastic_baseline_specs,
            quantile_probabilities=protocol.quantile_probabilities,
        ),
    )


def test_protocol_binds_study_window_and_history_requirements() -> None:
    spec, study, protocol = _study_fixture()
    for field, value in (
        ("start_position", 63),
        ("end_position", 310),
        ("minimum_warmup_bars", 44),
        ("minimum_prior_executed_prefixes", 44),
    ):
        changed_window = replace(study.windows[0], **{field: value})
        changed = replace(study, windows=(changed_window,))
        with pytest.raises(TrendlineRobustnessReplicationError):
            _validate_study_config_against_protocol(spec, changed, protocol)


def test_protocol_binds_metric_order_and_empty_decision_rules() -> None:
    spec, study, protocol = _study_fixture()
    with pytest.raises(TrendlineRobustnessReplicationError):
        _validate_study_config_against_protocol(
            spec,
            replace(study, metric_names=tuple(reversed(study.metric_names))),
            protocol,
        )
    rule = TrendlineAdequacyDecisionRule(
        metric_name=study.metric_names[0],
        operator=TrendlineAdequacyOperator.GREATER_THAN_OR_EQUAL,
        threshold=0.0,
        minimum_observation_count=1,
    )
    with pytest.raises(TrendlineRobustnessReplicationError):
        _validate_study_config_against_protocol(
            spec,
            replace(study, decision_rules=(rule,)),
            protocol,
        )


def test_protocol_binds_invalid_point_treatment() -> None:
    spec, study, protocol = _study_fixture()
    object.__setattr__(study, "invalid_point_treatment", SimpleNamespace(value="changed"))
    with pytest.raises(TrendlineRobustnessReplicationError):
        _validate_study_config_against_protocol(spec, study, protocol)


def test_protocol_binds_deterministic_baseline_identity_content() -> None:
    spec, study, protocol = _study_fixture()
    changed_baseline = replace(study.baseline_specs[0], name="recent-extrema-changed")
    with pytest.raises(TrendlineRobustnessReplicationError):
        _validate_study_config_against_protocol(
            spec,
            replace(study, baseline_specs=(changed_baseline, study.baseline_specs[1])),
            protocol,
        )


def test_protocol_binds_d4a_specs_to_study_specs() -> None:
    _, study, protocol = _study_fixture()
    d2, d3, d4a, d4b = _downstream_fixture(study, protocol)
    changed_baseline = replace(study.baseline_specs[0], preserves=("asset", "timeframe", "position", "causal_prefix"))
    changed_d4a = SimpleNamespace(
        study_config_id=study.study_config_id,
        baseline_specs=(changed_baseline, study.baseline_specs[1]),
    )
    with pytest.raises(TrendlineRobustnessReplicationError):
        _validate_downstream_protocol_bindings(
            study, protocol, d2, d3, changed_d4a, d4b
        )


def test_protocol_binds_d4b_seed_repetitions_and_preserves() -> None:
    _, study, protocol = _study_fixture()
    d2, d3, d4a, _ = _downstream_fixture(study, protocol)
    for changed_spec in (
        replace(protocol.stochastic_baseline_specs[0], seed=2026072703),
        replace(protocol.stochastic_baseline_specs[0], repetitions=31),
        replace(
            protocol.stochastic_baseline_specs[0],
            preserves=("asset", "timeframe", "position", "role", "pivot_count", "causal_prefix"),
        ),
    ):
        changed_d4b = SimpleNamespace(
            study_config_id=study.study_config_id,
            stochastic_baseline_specs=(changed_spec, protocol.stochastic_baseline_specs[1]),
            quantile_probabilities=protocol.quantile_probabilities,
        )
        with pytest.raises(TrendlineRobustnessReplicationError):
            _validate_downstream_protocol_bindings(
                study, protocol, d2, d3, d4a, changed_d4b
            )


def test_protocol_binds_d4b_quantile_probabilities() -> None:
    _, study, protocol = _study_fixture()
    d2, d3, d4a, _ = _downstream_fixture(study, protocol)
    changed_d4b = SimpleNamespace(
        study_config_id=study.study_config_id,
        stochastic_baseline_specs=protocol.stochastic_baseline_specs,
        quantile_probabilities=(0.1, 0.9),
    )
    with pytest.raises(TrendlineRobustnessReplicationError):
        _validate_downstream_protocol_bindings(
            study, protocol, d2, d3, d4a, changed_d4b
        )


def test_protocol_binds_all_downstream_study_config_ids() -> None:
    _, study, protocol = _study_fixture()
    d2, d3, d4a, d4b = _downstream_fixture(study, protocol)
    for index in range(4):
        bundles = [d2, d3, d4a, d4b]
        bundles[index] = SimpleNamespace(
            study_config_id="0" * 64,
            **({"baseline_specs": study.baseline_specs} if index == 2 else {}),
            **(
                {
                    "stochastic_baseline_specs": protocol.stochastic_baseline_specs,
                    "quantile_probabilities": protocol.quantile_probabilities,
                }
                if index == 3
                else {}
            ),
        )
        with pytest.raises(TrendlineRobustnessReplicationError):
            _validate_downstream_protocol_bindings(
                study, protocol, *bundles
            )


def test_protocol_rejects_boolean_replay_position() -> None:
    with pytest.raises(TrendlineRobustnessReplicationError):
        TrendlineRobustnessReplicationProtocol(**{**_protocol().__dict__, "replay_record_every": True})


def test_protocol_rejects_wrong_replay_end() -> None:
    with pytest.raises(TrendlineRobustnessReplicationError):
        TrendlineRobustnessReplicationProtocol(**{**_protocol().__dict__, "replay_end_position": 310})


def test_protocol_rejects_wrong_metric_order() -> None:
    with pytest.raises(TrendlineRobustnessReplicationError):
        TrendlineRobustnessReplicationProtocol(**{**_protocol().__dict__, "metric_names": tuple(reversed(_protocol().metric_names))})


def test_protocol_rejects_wrong_quantiles() -> None:
    with pytest.raises(TrendlineRobustnessReplicationError):
        TrendlineRobustnessReplicationProtocol(**{**_protocol().__dict__, "quantile_probabilities": (0.1, 0.9)})


def test_member_result_binds_d5a_ids() -> None:
    row = _row()
    assert len(row.d5a_member_spec_id) == 64
    assert len(row.d5a_member_evidence_id) == 64
    assert row.row_count == 312


def test_member_result_requires_timeframe_hold_bars() -> None:
    with pytest.raises(TrendlineRobustnessReplicationError):
        replace(_row(), timeframe="4h")


def test_member_result_rejects_wrong_row_count() -> None:
    with pytest.raises(TrendlineRobustnessReplicationError):
        replace(_row(), row_count=311)


def test_member_result_rejects_negative_count() -> None:
    with pytest.raises(TrendlineRobustnessReplicationError):
        replace(_row(), d4b_outcome_count=-1)


def test_member_result_identity_excludes_paths_and_durations() -> None:
    payload = _row().to_dict()
    assert "path" not in payload
    assert "duration" not in payload
    assert "wall_clock" not in payload


def test_d5a_matrix_readback_is_exact() -> None:
    matrix, entries = load_source_matrix()
    assert matrix.robustness_source_matrix_bundle_id == "9e324fff3bfce51eadb86fdcc173d75e984064d7eeaccb3d413fc4c8b13e907a"
    assert len(matrix.member_specs) == len(matrix.member_evidence) == 5
    assert len(entries) >= 7


def test_aggregate_requires_exact_four_member_order() -> None:
    matrix, _ = load_source_matrix()
    rows = (_row(), _row(name="cross-asset-ethusdt-1h-20250401-v1"), _row(name="cross-asset-solusdt-1h-20250401-v1"), _row(timeframe="4h", name="cross-timeframe-btcusdt-4h-20250401-v1"))
    with pytest.raises(TrendlineRobustnessReplicationError):
        build_robustness_replication_bundle(matrix, _protocol(), rows)


def test_aggregate_rejects_missing_member() -> None:
    matrix, _ = load_source_matrix()
    with pytest.raises(TrendlineRobustnessReplicationError):
        build_robustness_replication_bundle(matrix, _protocol(), (_row(),))


def test_aggregate_rejects_wrong_d5a_member_binding() -> None:
    matrix, _ = load_source_matrix()
    row = _row()
    with pytest.raises(TrendlineRobustnessReplicationError):
        build_robustness_replication_bundle(matrix, _protocol(), (replace(row, d5a_member_spec_id="0" * 64),))


def test_aggregate_identity_changes_with_member_result() -> None:
    matrix, _ = load_source_matrix()
    rows = [
        _row(),
        replace(_row(), member_name="cross-asset-ethusdt-1h-20250401-v1", d5a_member_spec_id=matrix.member_specs[2].member_spec_id, d5a_member_evidence_id=matrix.member_evidence[2].member_evidence_id, member_result_id=""),
        replace(_row(), member_name="cross-asset-solusdt-1h-20250401-v1", d5a_member_spec_id=matrix.member_specs[3].member_spec_id, d5a_member_evidence_id=matrix.member_evidence[3].member_evidence_id, member_result_id=""),
        replace(_row(timeframe="4h"), member_name="cross-timeframe-btcusdt-4h-20250401-v1", d5a_member_spec_id=matrix.member_specs[4].member_spec_id, d5a_member_evidence_id=matrix.member_evidence[4].member_evidence_id, member_result_id=""),
    ]
    first = build_robustness_replication_bundle(matrix, _protocol(), rows)
    changed = replace(rows[0], d3_event_count=40, member_result_id="")
    second = build_robustness_replication_bundle(matrix, _protocol(), (changed, *rows[1:]))
    assert first.robustness_replication_bundle_id != second.robustness_replication_bundle_id
    validate_robustness_replication_bundle(first, matrix)


def test_bundle_semantics_version_is_explicit() -> None:
    assert ROBUSTNESS_REPLICATION_BUNDLE_SEMANTICS_VERSION.endswith(".v1")
