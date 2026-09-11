from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from libs.models.sr_v2.contracts import ForecastOutcome, ZoneSide
from libs.models.sr_v2.domain.identity import canonical_hash
from libs.models.sr_v2.forecast.targets import ScientificReaction
from libs.models.sr_v2.research.development import (
    TARGET_DESIGN_SCHEMA,
    resolve_target_design_config,
)
from libs.models.sr_v2.research.geometry_evidence import (
    GeometryDiagnosticAccumulator,
    compose_geometry_family_evidence,
    geometry_ranking_input_from_family_evidence,
)
from libs.models.sr_v2.research.optimizer import (
    GEOMETRY_RANKING_POLICY_ID,
    OPTIMIZER_SCHEMA,
    TARGET_SELECTION_POLICY,
    CutoffReactionEvidence,
    FixtureTargetIdentificationInput,
    GeometryCandidateStatus,
    GeometryCellEvidence,
    GeometryRankingInput,
    GeometryRankingStatus,
    TargetDiagnosticAccumulator,
    TargetGroupDiagnostic,
    TargetIdentificationStatus,
    TargetTupleStatus,
    _diagnostic_for,
    _target_choice_id_for_tuple,
    _target_spec_for,
    compile_sealed_candidate_family,
    identify_target_from_compiled_fixture,
    identify_target_streaming,
    load_optimizer_yaml,
    rank_geometry_candidates,
    resolve_optimizer_config,
)
from libs.models.sr_v2.research.placebos import FEASIBLE_RANDOM_PRICE_ID
from libs.models.sr_v2.research_lab.episode_evidence import (
    COMMON_RISK_RECEIPT_SCHEMA,
    ISSUANCE_SEQUENCE_HASH_ALGORITHM,
    TARGET_COMPILER_RECEIPT_SCHEMA,
    TARGET_MATERIALIZATION_POLICY_ID,
    CommonRiskReceipt,
    TargetCompilerReceipt,
    TargetOutcome,
    TargetOutcomeRow,
    _sequence_digest,
    target_family_fingerprint_from_choices,
)
from libs.models.sr_v2.research_lab.scientific_compiler import (
    CompiledScientificSet,
    ScientificGroupKey,
)


class _NoMissingCompiledSet(CompiledScientificSet):
    @property
    def missing_groups(self):
        return ()


def _raw(tmp_path: Path, *, assets: dict[str, str] | None = None) -> dict:
    return {
        "schema": OPTIMIZER_SCHEMA,
        "source": {
            "venue": "binance_usdm",
            "assets": assets or {"BTCUSDT": "BTCUSDT"},
            "ladder": ["1d", "6h", "4h", "1h", "30m", "15m"],
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-20T00:00:00Z",
            "acquisition_policy": "CACHE_ONLY",
            "source_mode": "CACHE_ONLY",
            "cache_root": str(tmp_path / "cache"),
        },
        "splits": {
            "target_design": {
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-03T00:00:00Z",
            },
            "geometry_train": {
                "start": "2024-01-04T00:00:00Z",
                "end": "2024-01-08T00:00:00Z",
            },
            "geometry_validation": {
                "start": "2024-01-09T00:00:00Z",
                "end": "2024-01-12T00:00:00Z",
            },
            "embargo": "1d",
        },
        "target_identification": {
            "tuples": [
                {
                    "source_horizon_bars": 1,
                    "reference_lookback": 2,
                    "barrier_multiplier": "0.5",
                }
            ],
            "minimum_observation_coverage": 0.5,
            "minimum_unique_issuance_cutoffs": 1,
            "minimum_joint_utc_blocks": 1,
            "minimum_uncensored_lineages": 1,
            "minimum_touch_class_lineages": 1,
            "minimum_reaction_class_lineages": 1,
            "maximum_censoring_rate": 0.5,
            "maximum_unresolved_reaction_rate": 0.5,
            "maximum_ambiguity_rate": 0.5,
            "maximum_null_unavailable_rate": 0.0,
            "selection_policy_id": TARGET_SELECTION_POLICY,
        },
        "search": {
            "sampler_id": "sealed_global_finite_choices@1",
            "seed": "fixture-seed",
            "trial_budget": 4,
            "baseline_structural_yaml": "configs/sr_v2.yaml",
            "parameters": {
                "previous_period_anchor@1": {
                    "atr_period": [14, 15],
                    "zone_half_width_atr": ["0.25", "0.50"],
                }
            },
        },
        "inference": {
            "joint_utc_block": "1d",
            "epoch": "2024-01-01T00:00:00Z",
            "repetitions": 5,
            "confidence": 0.9,
            "alpha_family": "bonferroni@1",
            "degradation_margin": "0.10",
            "minimum_cell_support": 1,
            "minimum_asset_support": 1,
        },
        "resources": {
            "max_workers": 1,
            "receipt_dir": str(tmp_path / "receipts"),
        },
    }


def test_optimizer_loader_rejects_duplicate_and_unknown_keys(tmp_path):
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema: x\nschema: y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_optimizer_yaml(duplicate)
    raw = _raw(tmp_path)
    raw["unexpected"] = True
    with pytest.raises(ValueError, match="unknown"):
        resolve_optimizer_config(raw)
    missing = _raw(tmp_path)
    del missing["inference"]["epoch"]
    with pytest.raises(ValueError, match="missing"):
        resolve_optimizer_config(missing)


def test_optimizer_requires_explicit_finite_choices_and_fingerprints_change(tmp_path):
    config = resolve_optimizer_config(_raw(tmp_path))
    assert config.config_fingerprint
    changed = _raw(tmp_path)
    changed["target_identification"]["tuples"][0]["barrier_multiplier"] = "0.75"
    assert (
        resolve_optimizer_config(changed).config_fingerprint
        != config.config_fingerprint
    )
    bad = _raw(tmp_path)
    bad["search"]["parameters"]["previous_period_anchor@1"]["atr_period"] = []
    with pytest.raises(ValueError, match="non-empty"):
        resolve_optimizer_config(bad)
    bad = _raw(tmp_path)
    bad["search"]["parameters"]["previous_period_anchor@1"]["not_a_parameter"] = [1]
    with pytest.raises(ValueError, match="unsupported"):
        resolve_optimizer_config(bad)
    bad = _raw(tmp_path)
    bad["inference"]["degradation_margin"] = "NaN"
    with pytest.raises(ValueError, match="finite"):
        resolve_optimizer_config(bad)
    bad = _raw(tmp_path)
    bad["search"]["sampler_id"] = "other@1"
    with pytest.raises(ValueError, match="sampler"):
        resolve_optimizer_config(bad)
    bad = _raw(tmp_path)
    bad["inference"]["minimum_asset_support"] = 2
    with pytest.raises(ValueError, match="asset count"):
        resolve_optimizer_config(bad)


def test_sealed_family_is_order_invariant_and_baseline_is_ordinal_zero(tmp_path):
    raw = _raw(tmp_path)
    first = compile_sealed_candidate_family(resolve_optimizer_config(raw))
    reversed_raw = deepcopy(raw)
    reversed_raw["search"]["parameters"]["previous_period_anchor@1"]["atr_period"] = [
        15,
        14,
    ]
    reversed_raw["search"]["parameters"]["previous_period_anchor@1"][
        "zone_half_width_atr"
    ] = ["0.50", "0.25"]
    second = compile_sealed_candidate_family(resolve_optimizer_config(reversed_raw))
    assert first.family_hash == second.family_hash
    assert [item.candidate_id for item in first.candidates] == [
        item.candidate_id for item in second.candidates
    ]
    assert first.candidates[0].baseline is True
    assert first.candidates[0].ordinal == 0
    assert len(first.candidates) == 4
    assert all(
        item.resolved_config.ladder == first.baseline.resolved_config.ladder
        for item in first.candidates
    )


def test_sealed_family_hash_truncation_does_not_depend_on_outcomes(tmp_path):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 2
    config = resolve_optimizer_config(raw)
    first = compile_sealed_candidate_family(config)
    altered = deepcopy(raw)
    altered["inference"]["degradation_margin"] = "0.90"
    second = compile_sealed_candidate_family(resolve_optimizer_config(altered))
    assert [item.assignment for item in first.candidates] == [
        item.assignment for item in second.candidates
    ]
    assert first.family_hash == second.family_hash


def test_sealed_family_skips_invalid_cartesian_assignments_deterministically(tmp_path):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 2
    raw["search"]["parameters"]["previous_period_anchor@1"]["atr_period"] = [
        0,
        14,
    ]
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    assert len(family.candidates) == 2
    assert family.candidates[0].baseline
    assert all(item.resolved_config for item in family.candidates)


def _empty_compiled(config, *, source_manifest_id="manifest"):
    return _NoMissingCompiledSet(
        source_manifest_id=source_manifest_id,
        source_sha256="source",
        expected_groups=_groups(config),
        observations=(),
        compiler_fingerprint="compiler",
        knowledge_cutoff=config.source.start,
    )


def _feasible_diagnostic(config, target_tuple, group):
    return TargetGroupDiagnostic(
        target_tuple=target_tuple,
        group=group,
        observation_count=2,
        issuance_cutoffs=(config.source.start, config.source.start),
        unique_issuance_cutoffs=(config.source.start,),
        joint_utc_blocks=("2024-01-01T00:00:00+00:00/2024-01-02T00:00:00+00:00",),
        actual_available_count=2,
        null_available_count=2,
        uncensored_count=2,
        touched_count=1,
        untouched_count=1,
        censored_count=0,
        unresolved_count=0,
        actual_touch_count=1,
        null_touch_count=1,
        bounce_count=1,
        break_count=1,
        null_untouched_count=1,
        null_censored_count=0,
        null_unresolved_count=0,
        null_bounce_count=1,
        null_break_count=1,
        null_censored_reaction_count=0,
        null_ambiguous_reaction_count=0,
        censored_reaction_count=0,
        ambiguous_reaction_count=0,
        observation_coverage=1.0,
        null_unavailable_rate=0.0,
        actual_censoring_rate=0.0,
        null_censoring_rate=0.0,
        actual_unresolved_reaction_rate=0.0,
        null_unresolved_reaction_rate=0.0,
        actual_ambiguity_rate=0.0,
        null_ambiguity_rate=0.0,
        target_fingerprint="target",
        compiler_fingerprint="compiler",
        source_manifest_id="manifest",
        source_sha256="source",
        diagnostic_fingerprint="diagnostic",
    )


def test_target_identification_selects_first_declared_tuple_and_ignores_input_order(
    tmp_path, monkeypatch
):
    raw = _raw(tmp_path)
    raw["target_identification"]["tuples"].append(
        {
            "source_horizon_bars": 1,
            "reference_lookback": 3,
            "barrier_multiplier": "0.5",
        }
    )
    config = resolve_optimizer_config(raw)
    compiled = {
        target_tuple: _empty_compiled(config)
        for target_tuple in config.target_identification.tuples
    }

    def feasible(config_value, target_tuple, group, compiled_value, observations):
        return _feasible_diagnostic(config_value, target_tuple, group)

    monkeypatch.setattr(
        "libs.models.sr_v2.research.optimizer._diagnostic_for", feasible
    )
    report = identify_target_from_compiled_fixture(
        config,
        FixtureTargetIdentificationInput(
            compiled_by_tuple=dict(reversed(tuple(compiled.items()))),
            source_manifest_id="manifest",
            source_sha256="source",
        ),
    )
    assert report.status is TargetIdentificationStatus.TARGET_IDENTIFIED
    assert report.selected_tuple == config.target_identification.tuples[0]


def test_target_identification_has_no_fallback_when_every_tuple_is_insufficient(
    tmp_path,
):
    raw = _raw(tmp_path)
    raw["target_identification"]["tuples"].append(
        {
            "source_horizon_bars": 1,
            "reference_lookback": 3,
            "barrier_multiplier": "0.5",
        }
    )
    config = resolve_optimizer_config(raw)
    compiled = {
        target_tuple: _empty_compiled(config)
        for target_tuple in config.target_identification.tuples
    }
    report = identify_target_from_compiled_fixture(
        config,
        FixtureTargetIdentificationInput(
            compiled_by_tuple=compiled,
            source_manifest_id="manifest",
            source_sha256="source",
        ),
    )
    assert report.status is TargetIdentificationStatus.TARGET_NOT_IDENTIFIED
    assert report.selected_tuple is None
    assert all(item.status.value == "INSUFFICIENT" for item in report.tuple_diagnostics)


@pytest.mark.parametrize(
    ("field", "value", "reason_fragment"),
    [
        ("untouched_count", 0, "actual untouched class"),
        ("bounce_count", 0, "actual bounce class"),
        ("break_count", 0, "actual break class"),
        ("null_touch_count", 0, "null touched class"),
        ("null_untouched_count", 0, "null untouched class"),
        ("null_bounce_count", 0, "null bounce class"),
        ("null_break_count", 0, "null break class"),
        ("actual_censoring_rate", 0.6, "actual censoring"),
        ("null_censoring_rate", 0.6, "null censoring"),
        ("actual_unresolved_reaction_rate", 0.6, "actual unresolved reaction"),
        ("null_unresolved_reaction_rate", 0.6, "null unresolved reaction"),
        ("actual_ambiguity_rate", 0.6, "actual ambiguity"),
        ("null_ambiguity_rate", 0.6, "null ambiguity"),
    ],
)
def test_target_identification_requires_each_class_and_quality_gate(
    tmp_path, monkeypatch, field, value, reason_fragment
):
    config = resolve_optimizer_config(_raw(tmp_path))
    target_tuple = config.target_identification.tuples[0]
    compiled = {_target: _empty_compiled(config) for _target in (target_tuple,)}
    baseline = _feasible_diagnostic(config, target_tuple, _groups(config)[0])

    def altered(config_value, tuple_value, group, compiled_value, observations):
        del config_value, tuple_value, group, compiled_value, observations
        return replace(baseline, **{field: value})

    monkeypatch.setattr("libs.models.sr_v2.research.optimizer._diagnostic_for", altered)
    report = identify_target_from_compiled_fixture(
        config,
        FixtureTargetIdentificationInput(
            compiled_by_tuple=compiled,
            source_manifest_id="manifest",
            source_sha256="source",
        ),
    )
    assert report.status is TargetIdentificationStatus.TARGET_NOT_IDENTIFIED
    assert report.selected_tuple is None
    assert reason_fragment in report.tuple_diagnostics[0].reason


def test_target_identification_materializes_later_invalid_tuple_before_selection(
    tmp_path, monkeypatch
):
    raw = _raw(tmp_path)
    raw["target_identification"]["tuples"].append(
        {
            "source_horizon_bars": 1,
            "reference_lookback": 3,
            "barrier_multiplier": "0.5",
        }
    )
    config = resolve_optimizer_config(raw)
    tuples = config.target_identification.tuples
    compiled = {
        tuples[0]: _empty_compiled(config),
        tuples[1]: _empty_compiled(config, source_manifest_id="wrong-manifest"),
    }

    def feasible(config_value, target_tuple, group, compiled_value, observations):
        return _feasible_diagnostic(config_value, target_tuple, group)

    monkeypatch.setattr(
        "libs.models.sr_v2.research.optimizer._diagnostic_for", feasible
    )
    report = identify_target_from_compiled_fixture(
        config,
        FixtureTargetIdentificationInput(
            compiled_by_tuple=compiled,
            source_manifest_id="manifest",
            source_sha256="source",
        ),
    )
    assert report.status is TargetIdentificationStatus.INVALID
    assert report.selected_tuple is None
    assert len(report.tuple_diagnostics) == 2
    assert report.tuple_diagnostics[0].status.value == "FEASIBLE"
    assert report.tuple_diagnostics[1].status.value == "INVALID"


def _target_view(
    *,
    touch,
    reaction=None,
    reaction_eligible=False,
    censored=False,
    ambiguous=False,
):
    return SimpleNamespace(
        touch=touch,
        reaction=reaction,
        reaction_eligible=reaction_eligible,
        censored=censored,
        ambiguous=ambiguous,
    )


def _diagnostic_observation(index, *, actual_view, null_view):
    return SimpleNamespace(
        observation_id=f"observation-{index}",
        issued_at=datetime(2024, 1, index, tzinfo=UTC),
        target=SimpleNamespace(
            complete=not actual_view.censored,
            censored=actual_view.censored,
            view=actual_view,
        ),
        feasible_null=SimpleNamespace(complete=True, zone=object()),
        null_target=SimpleNamespace(
            censored=null_view.censored,
            view=null_view,
        ),
    )


def test_target_diagnostic_rates_use_explicit_actual_and_available_null_denominators(
    tmp_path,
):
    config = resolve_optimizer_config(_raw(tmp_path))
    target_tuple = config.target_identification.tuples[0]
    group = _groups(config)[0]
    observations = (
        _diagnostic_observation(
            1,
            actual_view=_target_view(
                touch=True,
                reaction=ScientificReaction.BOUNCE,
                reaction_eligible=True,
            ),
            null_view=_target_view(
                touch=True,
                reaction=ScientificReaction.BOUNCE,
                reaction_eligible=True,
            ),
        ),
        _diagnostic_observation(
            2,
            actual_view=_target_view(touch=False),
            null_view=_target_view(touch=False),
        ),
        _diagnostic_observation(
            3,
            actual_view=_target_view(touch=True, censored=True),
            null_view=_target_view(touch=True, censored=True),
        ),
        _diagnostic_observation(
            4,
            actual_view=_target_view(touch=True, ambiguous=True),
            null_view=_target_view(touch=True, ambiguous=True),
        ),
    )
    compiled = SimpleNamespace(
        compiler_fingerprint="compiler",
        source_manifest_id="manifest",
        source_sha256="source",
    )
    diagnostic = _diagnostic_for(config, target_tuple, group, compiled, observations)
    assert diagnostic.actual_censoring_rate == pytest.approx(0.25)
    assert diagnostic.null_censoring_rate == pytest.approx(0.25)
    assert diagnostic.actual_unresolved_reaction_rate == pytest.approx(0.25)
    assert diagnostic.null_unresolved_reaction_rate == pytest.approx(0.25)
    assert diagnostic.actual_ambiguity_rate == pytest.approx(0.25)
    assert diagnostic.null_ambiguity_rate == pytest.approx(0.25)


def _groups(config):
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
            for kernel in config.baseline_config.kernels
            if kernel.enabled_for(timeframe)
            for side in ZoneSide
        )
    )


def _stream_row(config, target_tuple, group, index, *, touch=True, reaction=None):
    issued = datetime(2024, 1, 1 + index, tzinfo=UTC)
    end = issued + config.baseline_config.trigger_duration
    outcome = TargetOutcome(
        complete=True,
        touch=touch,
        reaction=reaction,
        reaction_eligible=reaction is not None,
        censored=False,
        ambiguous=False,
        touch_at=issued + config.baseline_config.trigger_duration if touch else None,
        reaction_at=issued + config.baseline_config.trigger_duration
        if reaction is not None
        else None,
        observation_end_at=end,
        last_observed_cutoff=end,
        outcome=(
            ForecastOutcome.TOUCH_THEN_BOUNCE
            if reaction is ScientificReaction.BOUNCE
            else ForecastOutcome.TOUCH_THEN_BREAK
            if reaction is ScientificReaction.BREAK
            else ForecastOutcome.NO_TOUCH
        ),
        favorable_excursion_atr=Decimal("0.5") if reaction else Decimal(0),
        adverse_excursion_atr=Decimal(0),
    )
    spec = _target_spec_for(config, target_tuple, group.timeframe)
    return TargetOutcomeRow(
        observation_id=f"observation-{group.side.value}-{index}",
        group=group,
        issuance_cutoff=issued,
        cluster_identity=canonical_hash(
            {
                "issuance_cutoff": issued,
                "side": group.side,
                "center": Decimal(100),
                "lower": Decimal(99),
                "upper": Decimal(101),
            }
        ),
        target_fingerprint=spec.target_fingerprint,
        null_fingerprint="a" * 64,
        null_available=True,
        actual=outcome,
        null=outcome,
    )


def _real_stream_payload(
    config,
    target_tuple,
    rows,
    *,
    common_risk=None,
    asset="BTCUSDT",
    source_manifest_id="manifest",
    source_sha256="b" * 64,
    source_slice_fingerprint="a" * 64,
):
    choice_id = _target_choice_id_for_tuple(target_tuple)
    target_fingerprints = tuple(
        (
            timeframe,
            _target_spec_for(config, target_tuple, timeframe).target_fingerprint,
        )
        for timeframe in sorted(config.source.ladder)
    )
    if common_risk is None:
        target_family = target_family_fingerprint_from_choices(
            tuple(
                (
                    _target_choice_id_for_tuple(configured_tuple),
                    tuple(
                        (
                            timeframe,
                            _target_spec_for(
                                config, configured_tuple, timeframe
                            ).target_fingerprint,
                        )
                        for timeframe in sorted(config.source.ladder)
                    ),
                )
                for configured_tuple in config.target_identification.tuples
            )
        )
        semantic = {
            "schema": COMMON_RISK_RECEIPT_SCHEMA,
            "artifact_id": "artifact",
            "source_manifest_id": source_manifest_id,
            "source_sha256": source_sha256,
            "source_slice_fingerprint": source_slice_fingerprint,
            "asset": asset,
            "target_family_fingerprint": target_family,
            "materialization_policy_id": TARGET_MATERIALIZATION_POLICY_ID,
            "sequence_hash_algorithm": ISSUANCE_SEQUENCE_HASH_ALGORITHM,
            "included_count": len(rows),
            "included_observation_sha256": _sequence_digest(
                iter(row.observation_id for row in rows)
            ),
            "excluded_count": 0,
            "excluded_observation_sha256": _sequence_digest(iter(())),
            "excluded_reason_sha256": _sequence_digest(iter(())),
            "excluded_reason_counts": (),
            "included_group_sha256": _sequence_digest(
                iter((row.observation_id, row.group.key) for row in rows)
            ),
            "expected_group_counts": tuple(
                sorted(
                    (group.key, sum(row.group == group for row in rows))
                    for group in _groups(config)
                    if group.asset == asset
                )
            ),
        }
        common_risk = CommonRiskReceipt(
            **semantic,
            receipt_fingerprint=canonical_hash(semantic),
        )
    semantic = {
        "schema": TARGET_COMPILER_RECEIPT_SCHEMA,
        "artifact_id": "artifact",
        "source_manifest_id": source_manifest_id,
        "source_sha256": source_sha256,
        "source_slice_fingerprint": source_slice_fingerprint,
        "asset": asset,
        "target_choice_id": choice_id,
        "target_fingerprints": target_fingerprints,
        "common_risk_receipt_fingerprint": common_risk.receipt_fingerprint,
        "null_algorithm": FEASIBLE_RANDOM_PRICE_ID,
        "materialization_policy_id": TARGET_MATERIALIZATION_POLICY_ID,
        "expected_row_count": common_risk.included_count,
        "expected_row_sha256": _sequence_digest(iter(row.to_mapping() for row in rows)),
    }
    receipt = TargetCompilerReceipt(
        **semantic,
        compiler_fingerprint=canonical_hash(semantic),
    )
    return choice_id, common_risk, receipt


def test_streaming_accumulator_retains_counts_and_digests_not_observation_collections(
    tmp_path,
):
    config = resolve_optimizer_config(_raw(tmp_path))
    target_tuple = config.target_identification.tuples[0]
    group = next(item for item in _groups(config) if item.timeframe == "1h")
    accumulator = TargetDiagnosticAccumulator(config, target_tuple)
    accumulator.consume(
        _stream_row(
            config,
            target_tuple,
            group,
            1,
            reaction=ScientificReaction.BOUNCE,
        ),
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        compiler_fingerprint="c" * 64,
    )
    diagnostic = accumulator.finalize()
    cell = next(item for item in diagnostic.groups if item.group == group)
    assert cell.observation_count == 1
    assert cell.issuance_cutoff_count == 1
    assert cell.unique_issuance_cutoff_count == 1
    assert cell.joint_utc_block_count == 1
    assert cell.cluster_count == 1
    assert cell.issuance_cutoffs == ()
    assert cell.joint_utc_blocks == ()
    assert cell.cluster_multiplicity == ()
    assert not hasattr(accumulator, "observation_ids")
    assert not hasattr(accumulator._groups[group], "unique_cutoffs")
    assert not hasattr(accumulator._groups[group], "joint_blocks")
    repeat = accumulator.finalize()
    repeat_cell = next(item for item in repeat.groups if item.group == group)
    assert cell.diagnostic_fingerprint == repeat_cell.diagnostic_fingerprint
    assert diagnostic.tuple_fingerprint == repeat.tuple_fingerprint


def test_streaming_accumulator_keeps_support_and_resistance_cells_separate(tmp_path):
    config = resolve_optimizer_config(_raw(tmp_path))
    target_tuple = config.target_identification.tuples[0]
    groups = tuple(item for item in _groups(config) if item.timeframe == "1h")
    support = next(item for item in groups if item.side is ZoneSide.SUPPORT)
    resistance = next(item for item in groups if item.side is ZoneSide.RESISTANCE)
    accumulator = TargetDiagnosticAccumulator(config, target_tuple)
    for index, group in enumerate((support, resistance), 1):
        accumulator.consume(
            _stream_row(config, target_tuple, group, index),
            source_manifest_id="manifest",
            source_sha256="b" * 64,
            compiler_fingerprint="c" * 64,
        )
    diagnostic = accumulator.finalize()
    support_cell = next(item for item in diagnostic.groups if item.group == support)
    resistance_cell = next(
        item for item in diagnostic.groups if item.group == resistance
    )
    assert support_cell.observation_count == resistance_cell.observation_count == 1
    assert (
        support_cell.issuance_cutoff_count == resistance_cell.issuance_cutoff_count == 1
    )


def test_streaming_accumulator_keeps_source_identity_per_asset(tmp_path):
    config = resolve_optimizer_config(
        _raw(tmp_path, assets={"BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT"})
    )
    target_tuple = config.target_identification.tuples[0]
    groups = tuple(item for item in _groups(config) if item.timeframe == "1h")
    btc = next(item for item in groups if item.asset == "BTCUSDT")
    eth = next(item for item in groups if item.asset == "ETHUSDT")
    accumulator = TargetDiagnosticAccumulator(config, target_tuple)
    accumulator.consume(
        _stream_row(config, target_tuple, btc, 1),
        source_manifest_id="manifest-btc",
        source_sha256="b" * 64,
        compiler_fingerprint="c" * 64,
    )
    accumulator.consume(
        _stream_row(config, target_tuple, eth, 1),
        source_manifest_id="manifest-eth",
        source_sha256="e" * 64,
        compiler_fingerprint="d" * 64,
    )
    diagnostics = accumulator.finalize().groups
    btc_cell = next(item for item in diagnostics if item.group == btc)
    eth_cell = next(item for item in diagnostics if item.group == eth)
    assert btc_cell.observation_count == eth_cell.observation_count == 1
    assert btc_cell.source_manifest_id == "manifest-btc"
    assert eth_cell.source_manifest_id == "manifest-eth"


def test_identify_target_streaming_consumes_authenticated_choice_stream(tmp_path):
    raw = _raw(tmp_path)
    target_config = raw["target_identification"]
    target_config.update(
        {
            "minimum_observation_coverage": 0.0,
            "maximum_censoring_rate": 1.0,
            "maximum_unresolved_reaction_rate": 1.0,
            "maximum_ambiguity_rate": 1.0,
        }
    )
    config = resolve_optimizer_config(raw)
    target_tuple = config.target_identification.tuples[0]
    rows = tuple(
        replace(
            _stream_row(
                config,
                target_tuple,
                group,
                index,
                touch=touch,
                reaction=reaction,
            ),
            observation_id=f"observation-{group.key}-{index}",
        )
        for group in _groups(config)
        for index, (touch, reaction) in enumerate(
            (
                (True, ScientificReaction.BOUNCE),
                (True, ScientificReaction.BREAK),
                (False, None),
            ),
            1,
        )
    )
    choice_id, common_risk, receipt = _real_stream_payload(config, target_tuple, rows)
    report = identify_target_streaming(
        config,
        {"BTCUSDT": (common_risk, {choice_id: (receipt, iter(rows))})},
    )
    assert report.status is TargetIdentificationStatus.TARGET_IDENTIFIED
    assert report.selected_tuple == target_tuple


def test_identify_target_streaming_accepts_authenticated_target_design_config(tmp_path):
    raw = _raw(tmp_path)
    raw["target_identification"].update(
        {
            "minimum_observation_coverage": 0.0,
            "maximum_censoring_rate": 1.0,
            "maximum_unresolved_reaction_rate": 1.0,
            "maximum_ambiguity_rate": 1.0,
        }
    )
    comparator = resolve_optimizer_config(raw)
    strict_raw = {
        "schema": TARGET_DESIGN_SCHEMA,
        "source": deepcopy(raw["source"]),
        "target_design_window": deepcopy(raw["splits"]["target_design"]),
        "reference_volatility": {
            "algorithm_id": "simple_true_range_mean@1",
            "selection_policy_id": "first_feasible@1",
        },
        "horizon": {"unit": "source_bars", "observation_timeframe": "15m"},
        "barrier": {
            "derivation_policy_id": "normalized_excursion_breakpoint@1",
            "scan_lower": "0.1",
            "scan_upper": "2.0",
            "candidate_cap": 4,
        },
        "identifiability": deepcopy(raw["target_identification"]),
        "inference": {
            "joint_utc_block": raw["inference"]["joint_utc_block"],
            "epoch": raw["inference"]["epoch"],
        },
        "resources": {
            "max_workers": 1,
            "receipt_dir": str(tmp_path / "target-receipts"),
            "artifact_root": str(tmp_path / "target-artifacts"),
        },
    }
    strict_raw["target_design_window"]["end"] = "2024-01-05T00:00:00Z"
    strict = resolve_target_design_config(
        strict_raw,
        comparator_config=comparator.baseline_config,
    )
    target_tuple = strict.identifiability.tuples[0]
    rows = tuple(
        replace(
            _stream_row(
                comparator,
                target_tuple,
                group,
                index,
                touch=touch,
                reaction=reaction,
            ),
            observation_id=f"strict-{group.key}-{index}",
        )
        for group in _groups(comparator)
        for index, (touch, reaction) in enumerate(
            (
                (True, ScientificReaction.BOUNCE),
                (True, ScientificReaction.BREAK),
                (False, None),
            ),
            1,
        )
    )
    choice_id, common_risk, receipt = _real_stream_payload(
        comparator, target_tuple, rows
    )
    report = identify_target_streaming(
        strict,
        {"BTCUSDT": (common_risk, {choice_id: (receipt, iter(rows))})},
    )
    assert report.status is TargetIdentificationStatus.TARGET_IDENTIFIED
    assert report.selected_tuple == target_tuple


def test_identify_target_streaming_rejects_row_outside_target_design_window(tmp_path):
    raw = _raw(tmp_path)
    raw["target_identification"].update(
        {
            "minimum_observation_coverage": 0.0,
            "maximum_censoring_rate": 1.0,
            "maximum_unresolved_reaction_rate": 1.0,
            "maximum_ambiguity_rate": 1.0,
        }
    )
    comparator = resolve_optimizer_config(raw)
    strict_raw = {
        "schema": TARGET_DESIGN_SCHEMA,
        "source": deepcopy(raw["source"]),
        "target_design_window": {
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-05T00:00:00Z",
        },
        "reference_volatility": {
            "algorithm_id": "simple_true_range_mean@1",
            "selection_policy_id": "first_feasible@1",
        },
        "horizon": {"unit": "source_bars", "observation_timeframe": "15m"},
        "barrier": {
            "derivation_policy_id": "normalized_excursion_breakpoint@1",
            "scan_lower": "0.1",
            "scan_upper": "2.0",
            "candidate_cap": 4,
        },
        "identifiability": deepcopy(raw["target_identification"]),
        "inference": {
            "joint_utc_block": raw["inference"]["joint_utc_block"],
            "epoch": raw["inference"]["epoch"],
        },
        "resources": {
            "max_workers": 1,
            "receipt_dir": str(tmp_path / "target-receipts"),
            "artifact_root": str(tmp_path / "target-artifacts"),
        },
    }
    strict = resolve_target_design_config(
        strict_raw,
        comparator_config=comparator.baseline_config,
    )
    target_tuple = strict.identifiability.tuples[0]
    groups = _groups(comparator)
    rows = tuple(
        replace(
            _stream_row(comparator, target_tuple, group, 1),
            observation_id=f"outside-{group.key}",
        )
        for group in groups
    )
    outside = replace(
        rows[0],
        issuance_cutoff=strict.target_design_window.end,
    )
    rows = (outside, *rows[1:])
    choice_id, common_risk, receipt = _real_stream_payload(
        comparator, target_tuple, rows
    )
    report = identify_target_streaming(
        strict,
        {"BTCUSDT": (common_risk, {choice_id: (receipt, iter(rows))})},
    )
    assert report.status is TargetIdentificationStatus.INVALID
    assert "outside target-design window" in (report.tuple_diagnostics[0].reason or "")


def test_geometry_accumulator_rejects_row_outside_geometry_train_window(tmp_path):
    config = resolve_optimizer_config(_raw(tmp_path))
    family = compile_sealed_candidate_family(config)
    target_tuple = config.target_identification.tuples[0]
    group = _groups(config)[0]
    row = _stream_row(config, target_tuple, group, 1)
    _, _, receipt = _real_stream_payload(
        config,
        target_tuple,
        (row,),
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        source_slice_fingerprint="a" * 64,
    )
    strict_global = SimpleNamespace(
        schema="sr_v2.development_global_geometry@1",
        baseline_config=config.baseline_config,
        source=config.source,
        target_freeze=SimpleNamespace(selected_tuple=target_tuple),
        splits=SimpleNamespace(
            geometry_train=SimpleNamespace(
                start=datetime(2024, 1, 7, tzinfo=UTC),
                end=datetime(2024, 1, 10, tzinfo=UTC),
            )
        ),
        inference=config.inference,
    )
    accumulator = GeometryDiagnosticAccumulator(
        strict_global,
        family,
        family.baseline.candidate_id,
        source_bindings={"BTCUSDT": ("BTCUSDT", "manifest", "b" * 64, "a" * 64)},
        target_fingerprints={
            timeframe: _target_spec_for(
                config, target_tuple, timeframe
            ).target_fingerprint
            for timeframe in config.source.ladder
        },
        compiler_fingerprints={"BTCUSDT": receipt.compiler_fingerprint},
    )
    with pytest.raises(ValueError, match="outside geometry-train window"):
        accumulator.consume("BTCUSDT", receipt, (row,))


def test_identify_target_streaming_rejects_resealed_wrong_target_family(tmp_path):
    raw = _raw(tmp_path)
    raw["target_identification"].update(
        {
            "minimum_observation_coverage": 0.0,
            "maximum_censoring_rate": 1.0,
            "maximum_unresolved_reaction_rate": 1.0,
            "maximum_ambiguity_rate": 1.0,
        }
    )
    config = resolve_optimizer_config(raw)
    target_tuple = config.target_identification.tuples[0]
    rows = tuple(
        _stream_row(config, target_tuple, group, 1) for group in _groups(config)
    )
    choice_id, common_risk, receipt = _real_stream_payload(config, target_tuple, rows)
    common_semantic = dict(common_risk.semantic_mapping())
    common_semantic["target_family_fingerprint"] = "e" * 64
    wrong_family = replace(
        common_risk,
        target_family_fingerprint="e" * 64,
        receipt_fingerprint=canonical_hash(common_semantic),
    )
    receipt_semantic = dict(receipt.semantic_mapping())
    receipt_semantic["common_risk_receipt_fingerprint"] = (
        wrong_family.receipt_fingerprint
    )
    resealed_receipt = replace(
        receipt,
        common_risk_receipt_fingerprint=wrong_family.receipt_fingerprint,
        compiler_fingerprint=canonical_hash(receipt_semantic),
    )
    report = identify_target_streaming(
        config,
        {"BTCUSDT": (wrong_family, {choice_id: (resealed_receipt, iter(rows))})},
    )
    assert report.status is TargetIdentificationStatus.INVALID
    assert "target-family" in (report.tuple_diagnostics[0].reason or "")


def test_identify_target_streaming_rejects_group_assignment_swap_with_resealed_rows(
    tmp_path,
):
    raw = _raw(tmp_path)
    raw["target_identification"].update(
        {
            "minimum_observation_coverage": 0.0,
            "maximum_censoring_rate": 1.0,
            "maximum_unresolved_reaction_rate": 1.0,
            "maximum_ambiguity_rate": 1.0,
        }
    )
    config = resolve_optimizer_config(raw)
    target_tuple = config.target_identification.tuples[0]
    groups = tuple(item for item in _groups(config) if item.timeframe == "1h")
    support = next(item for item in groups if item.side is ZoneSide.SUPPORT)
    resistance = next(item for item in groups if item.side is ZoneSide.RESISTANCE)
    rows = tuple(
        _stream_row(config, target_tuple, group, 1) for group in (support, resistance)
    )
    choice_id, common_risk, receipt = _real_stream_payload(config, target_tuple, rows)
    swapped = tuple(
        replace(row, group=resistance if row.group == support else support)
        for row in rows
    )
    receipt_semantic = dict(receipt.semantic_mapping())
    receipt_semantic["expected_row_sha256"] = _sequence_digest(
        iter(row.to_mapping() for row in swapped)
    )
    resealed_receipt = replace(
        receipt,
        expected_row_sha256=receipt_semantic["expected_row_sha256"],
        compiler_fingerprint=canonical_hash(receipt_semantic),
    )
    report = identify_target_streaming(
        config,
        {"BTCUSDT": (common_risk, {choice_id: (resealed_receipt, iter(swapped))})},
    )
    assert report.status is TargetIdentificationStatus.INVALID
    assert "common-risk" in (report.tuple_diagnostics[0].reason or "")


def test_identify_target_streaming_rejects_asset_order_and_choice_set_drift(tmp_path):
    raw = _raw(tmp_path, assets={"BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT"})
    raw["target_identification"].update(
        {
            "minimum_observation_coverage": 0.0,
            "maximum_censoring_rate": 1.0,
            "maximum_unresolved_reaction_rate": 1.0,
            "maximum_ambiguity_rate": 1.0,
        }
    )
    config = resolve_optimizer_config(raw)
    target_tuple = config.target_identification.tuples[0]
    payloads = {}
    for asset in config.source.assets:
        rows = tuple(
            _stream_row(config, target_tuple, group, 1)
            for group in _groups(config)
            if group.asset == asset
        )
        choice_id, common_risk, receipt = _real_stream_payload(
            config, target_tuple, rows, asset=asset
        )
        payloads[asset] = (common_risk, {choice_id: (receipt, iter(rows))})
    reversed_assets = dict(reversed(tuple(payloads.items())))
    assert (
        identify_target_streaming(config, reversed_assets).status
        is TargetIdentificationStatus.INVALID
    )
    assert (
        identify_target_streaming(config, {"BTCUSDT": payloads["BTCUSDT"]}).status
        is TargetIdentificationStatus.INVALID
    )
    extra_asset = dict(payloads)
    extra_asset["XRPUSDT"] = payloads["BTCUSDT"]
    assert (
        identify_target_streaming(config, extra_asset).status
        is TargetIdentificationStatus.INVALID
    )

    common_risk, choices = payloads["BTCUSDT"]
    choice_id, choice_value = next(iter(choices.items()))
    assert (
        identify_target_streaming(
            config,
            {"BTCUSDT": (common_risk, {})},
        ).status
        is TargetIdentificationStatus.INVALID
    )
    assert (
        identify_target_streaming(
            config,
            {"BTCUSDT": (common_risk, {"f" * 64: choice_value})},
        ).status
        is TargetIdentificationStatus.INVALID
    )


def test_identify_target_streaming_rejects_truncated_rows_against_both_receipts(
    tmp_path,
):
    raw = _raw(tmp_path)
    target_config = raw["target_identification"]
    target_config.update(
        {
            "minimum_observation_coverage": 0.0,
            "maximum_censoring_rate": 1.0,
            "maximum_unresolved_reaction_rate": 1.0,
            "maximum_ambiguity_rate": 1.0,
        }
    )
    config = resolve_optimizer_config(raw)
    target_tuple = config.target_identification.tuples[0]
    rows = tuple(
        _stream_row(config, target_tuple, group, index)
        for group in _groups(config)
        for index in (1,)
    )
    choice_id, common_risk, receipt = _real_stream_payload(config, target_tuple, rows)
    report = identify_target_streaming(
        config,
        {
            "BTCUSDT": (
                common_risk,
                {choice_id: (receipt, iter(rows[:-1]))},
            )
        },
    )
    assert report.status is TargetIdentificationStatus.INVALID
    assert report.tuple_diagnostics[0].status is TargetTupleStatus.INVALID
    assert "common-risk" in (report.tuple_diagnostics[0].reason or "")


def test_identify_target_streaming_preserves_configured_zero_group_counts(tmp_path):
    raw = _raw(tmp_path)
    config = resolve_optimizer_config(raw)
    target_tuple = config.target_identification.tuples[0]
    group = _groups(config)[0]
    rows = (_stream_row(config, target_tuple, group, 1),)
    choice_id, common_risk, receipt = _real_stream_payload(config, target_tuple, rows)
    report = identify_target_streaming(
        config,
        {
            "BTCUSDT": (
                common_risk,
                {choice_id: (receipt, iter(rows))},
            )
        },
    )
    assert report.status is not TargetIdentificationStatus.INVALID


def test_identify_target_streaming_rejects_common_compiler_identity_drift(tmp_path):
    raw = _raw(tmp_path)
    config = resolve_optimizer_config(raw)
    target_tuple = config.target_identification.tuples[0]
    rows = tuple(
        _stream_row(config, target_tuple, group, 1) for group in _groups(config)
    )
    choice_id, common_risk, receipt = _real_stream_payload(config, target_tuple, rows)
    semantic = dict(receipt.semantic_mapping())
    semantic["common_risk_receipt_fingerprint"] = "e" * 64
    forged_receipt = TargetCompilerReceipt(
        **semantic,
        compiler_fingerprint=canonical_hash(semantic),
    )
    report = identify_target_streaming(
        config,
        {
            "BTCUSDT": (
                common_risk,
                {choice_id: (forged_receipt, iter(rows))},
            )
        },
    )
    assert report.status is TargetIdentificationStatus.INVALID
    assert "common-risk fingerprint" in (report.tuple_diagnostics[0].reason or "")


def test_identify_target_streaming_requires_yaml_choice_order(tmp_path):
    raw = _raw(tmp_path)
    raw["target_identification"]["tuples"].append(
        {
            "source_horizon_bars": 1,
            "reference_lookback": 3,
            "barrier_multiplier": "0.5",
        }
    )
    config = resolve_optimizer_config(raw)
    payloads = []
    common_risk = None
    for target_tuple in config.target_identification.tuples:
        rows = tuple(
            _stream_row(config, target_tuple, group, 1) for group in _groups(config)
        )
        choice_id, choice_common, receipt = _real_stream_payload(
            config, target_tuple, rows, common_risk=common_risk
        )
        if common_risk is None:
            common_risk = choice_common
        payloads.append((choice_id, receipt, rows))
    assert common_risk is not None
    reversed_choices = {
        choice_id: (receipt, iter(rows))
        for choice_id, receipt, rows in reversed(payloads)
    }
    report = identify_target_streaming(
        config,
        {"BTCUSDT": (common_risk, reversed_choices)},
    )
    ordered_choices = {
        choice_id: (receipt, iter(rows)) for choice_id, receipt, rows in payloads
    }
    ordered_report = identify_target_streaming(
        config,
        {"BTCUSDT": (common_risk, ordered_choices)},
    )
    assert report.status is TargetIdentificationStatus.INVALID
    assert report.selected_tuple is None
    assert report.report_fingerprint != ordered_report.report_fingerprint


def test_identify_target_streaming_selects_first_yaml_feasible_choice(tmp_path):
    raw = _raw(tmp_path)
    raw["target_identification"]["tuples"].append(
        {
            "source_horizon_bars": 1,
            "reference_lookback": 3,
            "barrier_multiplier": "0.5",
        }
    )
    raw["target_identification"].update(
        {
            "minimum_observation_coverage": 0.0,
            "maximum_censoring_rate": 1.0,
            "maximum_unresolved_reaction_rate": 1.0,
            "maximum_ambiguity_rate": 1.0,
        }
    )
    config = resolve_optimizer_config(raw)
    common_risk = None
    choices = {}
    for target_tuple in config.target_identification.tuples:
        rows = tuple(
            _stream_row(
                config,
                target_tuple,
                group,
                index,
                touch=touch,
                reaction=reaction,
            )
            for group in _groups(config)
            for index, (touch, reaction) in enumerate(
                (
                    (True, ScientificReaction.BOUNCE),
                    (True, ScientificReaction.BREAK),
                    (False, None),
                ),
                1,
            )
        )
        choice_id, choice_common, receipt = _real_stream_payload(
            config,
            target_tuple,
            rows,
            common_risk=common_risk,
        )
        if common_risk is None:
            common_risk = choice_common
        choices[choice_id] = (receipt, iter(rows))
    assert common_risk is not None
    report = identify_target_streaming(
        config,
        {"BTCUSDT": (common_risk, choices)},
    )
    assert report.status is TargetIdentificationStatus.TARGET_IDENTIFIED
    assert report.selected_tuple == config.target_identification.tuples[0]


def _cells(
    family,
    groups,
    *,
    cutoff_evidence,
    paired_intervals=None,
    compiler_fingerprint="compiler",
    null_algorithm_id=FEASIBLE_RANDOM_PRICE_ID,
):
    result = []
    for candidate in family.candidates:
        for group in groups:
            result.append(
                GeometryCellEvidence(
                    candidate_id=candidate.candidate_id,
                    group=group,
                    source_manifest_id="manifest",
                    source_sha256="source",
                    source_slice_fingerprint="slice",
                    target_fingerprint="target",
                    compiler_fingerprint=compiler_fingerprint,
                    null_algorithm_id=null_algorithm_id,
                    lineage_support=2,
                    cutoff_evidence=cutoff_evidence,
                    touch_count=1,
                    paired_reaction_lift_interval=(
                        (0.0, 1.0)
                        if paired_intervals is None
                        else paired_intervals[candidate.candidate_id]
                    ),
                )
            )
    return tuple(result)


def _target_fingerprints(config):
    return {timeframe: "target" for timeframe in config.source.ladder}


def _source_bindings(config):
    return {
        asset: (instrument, "manifest", "source", "slice")
        for asset, instrument in config.source.assets.items()
    }


def _compiler_fingerprints(family, config):
    return {
        candidate.candidate_id: {asset: "compiler" for asset in config.source.assets}
        for candidate in family.candidates
    }


def test_geometry_equal_cutoff_weighting_and_deterministic_winner(tmp_path):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 1
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    groups = _groups(config)
    cutoff_evidence = (
        CutoffReactionEvidence(
            cutoff=datetime(2024, 1, 1, tzinfo=UTC),
            actual_bounce=10,
            actual_break=0,
            null_bounce=0,
            null_break=10,
        ),
        CutoffReactionEvidence(
            cutoff=datetime(2024, 1, 2, tzinfo=UTC),
            actual_bounce=0,
            actual_break=10,
            null_bounce=0,
            null_break=10,
        ),
    )
    evidence = _cells(family, groups, cutoff_evidence=cutoff_evidence)
    report = rank_geometry_candidates(
        config,
        GeometryRankingInput(
            family=family,
            cells=evidence,
            source_bindings=_source_bindings(config),
            target_fingerprints=_target_fingerprints(config),
            compiler_fingerprints=_compiler_fingerprints(family, config),
            null_algorithm_id=FEASIBLE_RANDOM_PRICE_ID,
        ),
    )
    assert report.status is GeometryRankingStatus.PROVISIONAL_WINNER
    assert report.winner == family.baseline
    assert report.candidates[0].equal_cell_lift == pytest.approx(0.5)


def test_geometry_missing_cells_and_identity_mismatch_are_invalid(tmp_path):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 1
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    groups = _groups(config)
    evidence = list(
        _cells(
            family,
            groups,
            cutoff_evidence=(
                CutoffReactionEvidence(
                    cutoff=datetime(2024, 1, 1, tzinfo=UTC),
                    actual_bounce=1,
                    actual_break=1,
                    null_bounce=1,
                    null_break=1,
                ),
            ),
        )
    )
    evidence.pop()
    evidence[0] = GeometryCellEvidence(
        candidate_id=evidence[0].candidate_id,
        group=evidence[0].group,
        source_manifest_id="different",
        source_sha256=evidence[0].source_sha256,
        target_fingerprint=evidence[0].target_fingerprint,
        compiler_fingerprint=evidence[0].compiler_fingerprint,
        null_algorithm_id=evidence[0].null_algorithm_id,
        lineage_support=evidence[0].lineage_support,
        cutoff_evidence=evidence[0].cutoff_evidence,
    )
    report = rank_geometry_candidates(
        config,
        GeometryRankingInput(
            family=family,
            cells=tuple(evidence),
            source_bindings=_source_bindings(config),
            target_fingerprints=_target_fingerprints(config),
            compiler_fingerprints=_compiler_fingerprints(family, config),
            null_algorithm_id=FEASIBLE_RANDOM_PRICE_ID,
        ),
    )
    assert report.status is GeometryRankingStatus.INVALID


def test_geometry_degradation_uses_adjusted_paired_interval_and_fixed_margin(tmp_path):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 2
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    groups = _groups(config)
    evidence = _cells(
        family,
        groups,
        cutoff_evidence=(
            CutoffReactionEvidence(
                cutoff=datetime(2024, 1, 1, tzinfo=UTC),
                actual_bounce=1,
                actual_break=1,
                null_bounce=1,
                null_break=1,
            ),
        ),
        paired_intervals={
            candidate.candidate_id: (0.0, 1.0) if candidate.baseline else (-0.2, -0.11)
            for candidate in family.candidates
        },
    )
    report = rank_geometry_candidates(
        config,
        GeometryRankingInput(
            family=family,
            cells=tuple(evidence),
            source_bindings=_source_bindings(config),
            target_fingerprints=_target_fingerprints(config),
            compiler_fingerprints=_compiler_fingerprints(family, config),
            null_algorithm_id=FEASIBLE_RANDOM_PRICE_ID,
        ),
    )
    assert report.status is GeometryRankingStatus.PROVISIONAL_WINNER
    assert report.winner == family.baseline
    assert all(item.status.value == "DEGRADED" for item in report.candidates[1:])


def _reaction_evidence_for_lift(lift, *, cutoff=None):
    cutoff = cutoff or datetime(2024, 1, 1, tzinfo=UTC)
    if lift > 0:
        actual_bounce, actual_break = 9, 1
        null_bounce, null_break = 1, 9
    elif lift < 0:
        actual_bounce, actual_break = 1, 9
        null_bounce, null_break = 9, 1
    else:
        actual_bounce = actual_break = null_bounce = null_break = 1
    return (
        CutoffReactionEvidence(
            cutoff=cutoff,
            actual_bounce=actual_bounce,
            actual_break=actual_break,
            null_bounce=null_bounce,
            null_break=null_break,
        ),
    )


def _rank(
    config,
    family,
    cells,
    *,
    compiler_fingerprints=None,
    null_algorithm_id=FEASIBLE_RANDOM_PRICE_ID,
):
    if compiler_fingerprints is None:
        compiler_fingerprints = _compiler_fingerprints(family, config)
    return rank_geometry_candidates(
        config,
        GeometryRankingInput(
            family=family,
            cells=tuple(cells),
            source_bindings=_source_bindings(config),
            target_fingerprints=_target_fingerprints(config),
            compiler_fingerprints=compiler_fingerprints,
            null_algorithm_id=null_algorithm_id,
        ),
    )


def test_geometry_composer_authenticates_two_assets_and_shared_family_draw(tmp_path):
    raw = _raw(
        tmp_path,
        assets={"BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT"},
    )
    raw["search"]["trial_budget"] = 2
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    target_tuple = config.target_identification.tuples[0]
    target_fingerprints = {
        timeframe: _target_spec_for(config, target_tuple, timeframe).target_fingerprint
        for timeframe in config.source.ladder
    }
    source_bindings = {
        "BTCUSDT": ("BTCUSDT", "manifest-btc", "b" * 64, "a" * 64),
        "ETHUSDT": ("ETHUSDT", "manifest-eth", "e" * 64, "d" * 64),
    }
    streams_by_candidate = {}
    compiler_fingerprints = {}
    for candidate in family.candidates:
        streams = {}
        candidate_compilers = {}
        for asset in source_bindings:
            asset_groups = tuple(
                group for group in _groups(config) if group.asset == asset
            )
            rows = tuple(
                sorted(
                    (
                        _stream_row(
                            config,
                            target_tuple,
                            group,
                            cutoff_index,
                            reaction=ScientificReaction.BOUNCE,
                        )
                        for cutoff_index in range(2)
                        for group in asset_groups
                    ),
                    key=lambda row: (row.issuance_cutoff, row.observation_id),
                )
            )
            _, _, receipt = _real_stream_payload(
                config,
                target_tuple,
                rows,
                asset=asset,
                source_manifest_id=source_bindings[asset][1],
                source_sha256=source_bindings[asset][2],
                source_slice_fingerprint=source_bindings[asset][3],
            )
            streams[asset] = (receipt, iter(rows))
            candidate_compilers[asset] = receipt.compiler_fingerprint
        streams_by_candidate[candidate.candidate_id] = streams
        compiler_fingerprints[candidate.candidate_id] = candidate_compilers
    composed = compose_geometry_family_evidence(
        config,
        family,
        streams_by_candidate,
        source_bindings=source_bindings,
        target_fingerprints=target_fingerprints,
        compiler_fingerprints=compiler_fingerprints,
    )
    assert composed.family_size == (len(family.candidates) - 1) * len(_groups(config))
    assert len(composed.block_draws) == config.inference.repetitions
    assert all(
        cell.paired_reaction_lift_interval is not None
        for candidate_id, cells in composed.cells_by_candidate.items()
        if candidate_id != family.baseline.candidate_id
        for cell in cells
    )
    assert {
        cell.group.asset
        for cells in composed.cells_by_candidate.values()
        for cell in cells
    } == {
        "BTCUSDT",
        "ETHUSDT",
    }
    assert composed.config_fingerprint == config.config_fingerprint
    assert composed.common_block_labels
    assert len(composed.receipt_fingerprint) == 64
    ranking_input = geometry_ranking_input_from_family_evidence(
        config,
        family,
        composed,
        source_bindings=source_bindings,
        target_fingerprints=target_fingerprints,
        compiler_fingerprints=compiler_fingerprints,
    )
    assert (
        ranking_input.family_evidence_receipt_fingerprint
        == composed.receipt_fingerprint
    )
    assert ranking_input.family_common_joint_utc_block_count == len(
        composed.common_block_labels
    )


def test_global_ranking_rejects_insufficient_complete_family_common_blocks(
    tmp_path, monkeypatch
):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 1
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    cells = tuple(
        replace(
            cell,
            cluster_count=1,
            unique_cutoff_count=1,
            joint_utc_block_count=1,
        )
        for cell in _cells(
            family,
            _groups(config),
            cutoff_evidence=(
                CutoffReactionEvidence(
                    cutoff=datetime(2024, 1, 1, tzinfo=UTC),
                    actual_bounce=1,
                    actual_break=1,
                    null_bounce=1,
                    null_break=1,
                ),
            ),
        )
    )
    global_config = SimpleNamespace(
        schema="sr_v2.development_global_geometry@1",
        baseline_config=config.baseline_config,
        source=config.source,
        search=config.search,
        inference=SimpleNamespace(
            minimum_paired_reaction_clusters=1,
            minimum_unique_issuance_cutoffs=1,
            minimum_common_joint_utc_blocks=1,
            minimum_asset_support=1,
            degradation_margin=Decimal("0.1"),
        ),
        config_fingerprint="g" * 64,
        ranking_policy_id=GEOMETRY_RANKING_POLICY_ID,
    )
    monkeypatch.setattr(
        "libs.models.sr_v2.research.optimizer.compile_global_candidate_family",
        lambda value: family,
    )
    report = rank_geometry_candidates(
        global_config,
        GeometryRankingInput(
            family=family,
            cells=cells,
            source_bindings=_source_bindings(config),
            target_fingerprints=_target_fingerprints(config),
            compiler_fingerprints=_compiler_fingerprints(family, config),
            null_algorithm_id=FEASIBLE_RANDOM_PRICE_ID,
            family_evidence_receipt_fingerprint="f" * 64,
            family_common_joint_utc_block_count=0,
        ),
    )
    assert report.status is GeometryRankingStatus.INSUFFICIENT
    assert "complete-family common UTC-block" in (report.candidates[0].reason or "")


def test_composer_common_block_receipt_drives_global_insufficient_status(
    tmp_path, monkeypatch
):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 2
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    target_tuple = config.target_identification.tuples[0]
    source_bindings = {"BTCUSDT": ("BTCUSDT", "manifest", "b" * 64, "a" * 64)}
    target_fingerprints = {
        timeframe: _target_spec_for(config, target_tuple, timeframe).target_fingerprint
        for timeframe in config.source.ladder
    }
    streams_by_candidate = {}
    compiler_fingerprints = {}
    common_risk = None
    for candidate in family.candidates:
        index_start = 1 if candidate.baseline else 3
        rows = tuple(
            sorted(
                (
                    _stream_row(config, target_tuple, group, index)
                    for index in (index_start, index_start + 1)
                    for group in _groups(config)
                ),
                key=lambda row: (row.issuance_cutoff, row.observation_id),
            )
        )
        choice_id, candidate_common_risk, receipt = _real_stream_payload(
            config,
            target_tuple,
            rows,
            common_risk=common_risk,
        )
        if common_risk is None:
            common_risk = candidate_common_risk
        streams_by_candidate[candidate.candidate_id] = {
            "BTCUSDT": (receipt, iter(rows)),
        }
        compiler_fingerprints[candidate.candidate_id] = {
            "BTCUSDT": receipt.compiler_fingerprint
        }
        assert choice_id == _target_choice_id_for_tuple(target_tuple)
    composed = compose_geometry_family_evidence(
        config,
        family,
        streams_by_candidate,
        source_bindings=source_bindings,
        target_fingerprints=target_fingerprints,
        compiler_fingerprints=compiler_fingerprints,
    )
    assert composed.common_block_labels == ()
    ranking_input = geometry_ranking_input_from_family_evidence(
        config,
        family,
        composed,
        source_bindings=source_bindings,
        target_fingerprints=target_fingerprints,
        compiler_fingerprints=compiler_fingerprints,
    )
    global_config = SimpleNamespace(
        schema="sr_v2.development_global_geometry@1",
        baseline_config=config.baseline_config,
        source=config.source,
        search=config.search,
        inference=SimpleNamespace(
            minimum_paired_reaction_clusters=1,
            minimum_unique_issuance_cutoffs=1,
            minimum_common_joint_utc_blocks=1,
            minimum_asset_support=1,
            degradation_margin=Decimal("0.1"),
        ),
        config_fingerprint="h" * 64,
        ranking_policy_id=GEOMETRY_RANKING_POLICY_ID,
    )
    monkeypatch.setattr(
        "libs.models.sr_v2.research.optimizer.compile_global_candidate_family",
        lambda value: family,
    )
    report = rank_geometry_candidates(global_config, ranking_input)
    assert report.status is GeometryRankingStatus.INSUFFICIENT
    assert all(
        "complete-family common UTC-block" in (candidate.reason or "")
        for candidate in report.candidates
    )


def test_geometry_ranking_keeps_opposite_sides_in_separate_macros(tmp_path):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 2
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    cells = []
    for cell in _cells(
        family,
        _groups(config),
        cutoff_evidence=_reaction_evidence_for_lift(0.0),
    ):
        if cell.candidate_id == family.baseline.candidate_id:
            lift = 0.8 if cell.group.side is ZoneSide.SUPPORT else -0.8
        else:
            lift = 0.0
        cells.append(replace(cell, cutoff_evidence=_reaction_evidence_for_lift(lift)))
    report = _rank(config, family, cells)
    baseline_result = report.candidates[0]
    candidate_result = report.candidates[1]
    assert baseline_result.status is GeometryCandidateStatus.VALID
    assert baseline_result.worst_timeframe_kernel_side_lift == pytest.approx(-0.8)
    assert baseline_result.equal_cell_lift == pytest.approx(0.0)
    assert candidate_result.worst_timeframe_kernel_side_lift == pytest.approx(0.0)
    assert report.winner == family.candidates[1]


def test_geometry_ranking_counts_distinct_assets_per_side_macro(tmp_path):
    config = resolve_optimizer_config(
        _raw(tmp_path, assets={"BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT"})
    )
    family = compile_sealed_candidate_family(config)
    cells = list(
        _cells(
            family,
            _groups(config),
            cutoff_evidence=_reaction_evidence_for_lift(0.1),
        )
    )
    target = next(
        cell
        for cell in cells
        if cell.group.asset == "ETHUSDT" and cell.group.side is ZoneSide.RESISTANCE
    )
    cells[cells.index(target)] = replace(target, lineage_support=0)
    report = _rank(config, family, cells)
    assert report.status is GeometryRankingStatus.INSUFFICIENT
    assert report.candidates[0].status is GeometryCandidateStatus.INSUFFICIENT
    assert "RESISTANCE" in (report.candidates[0].reason or "")


def test_geometry_duplicate_cell_cannot_inflate_support(tmp_path):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 1
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    cells = list(
        _cells(
            family,
            _groups(config),
            cutoff_evidence=_reaction_evidence_for_lift(0.1),
        )
    )
    cells.append(cells[0])
    report = _rank(config, family, cells)
    assert report.status is GeometryRankingStatus.INVALID
    assert report.winner is None
    assert report.candidates[0].status is GeometryCandidateStatus.INVALID


def test_geometry_order_and_policy_identity_are_deterministic(tmp_path):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 1
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    cells = _cells(
        family,
        _groups(config),
        cutoff_evidence=_reaction_evidence_for_lift(0.1),
    )
    first = _rank(config, family, cells)
    second = _rank(config, family, reversed(cells))
    assert first.report_fingerprint == second.report_fingerprint
    assert GEOMETRY_RANKING_POLICY_ID == "worst_tf_kernel_side_then_equal_cell@2"


def test_geometry_incomplete_family_cannot_produce_winner(tmp_path):
    raw = _raw(tmp_path)
    raw["search"]["trial_budget"] = 2
    config = resolve_optimizer_config(raw)
    family = compile_sealed_candidate_family(config)
    cells = list(
        _cells(
            family,
            _groups(config),
            cutoff_evidence=_reaction_evidence_for_lift(0.1),
        )
    )
    candidate_id = family.candidates[-1].candidate_id
    cells = [
        cell
        for cell in cells
        if not (cell.candidate_id == candidate_id and cell.group == _groups(config)[0])
    ]
    report = _rank(config, family, cells)
    assert report.status is GeometryRankingStatus.INVALID
    assert report.winner is None
    assert report.candidates[-1].status is GeometryCandidateStatus.INVALID


def test_geometry_input_requires_exact_compiler_candidate_keys(tmp_path):
    config = resolve_optimizer_config(_raw(tmp_path))
    family = compile_sealed_candidate_family(config)
    cells = _cells(
        family,
        _groups(config),
        cutoff_evidence=_reaction_evidence_for_lift(0.1),
    )
    with pytest.raises(ValueError, match="compiler_fingerprints"):
        _rank(config, family, cells, compiler_fingerprints={})
    extra = _compiler_fingerprints(family, config)
    extra["unexpected-candidate"] = {
        asset: "compiler" for asset in config.source.assets
    }
    with pytest.raises(ValueError, match="compiler_fingerprints"):
        _rank(config, family, cells, compiler_fingerprints=extra)


def test_geometry_cell_compiler_identity_mismatch_is_invalid(tmp_path):
    config = resolve_optimizer_config(_raw(tmp_path))
    family = compile_sealed_candidate_family(config)
    cells = list(
        _cells(
            family,
            _groups(config),
            cutoff_evidence=_reaction_evidence_for_lift(0.1),
        )
    )
    cells[0] = replace(cells[0], compiler_fingerprint="wrong-compiler")
    report = _rank(config, family, cells)
    assert report.status is GeometryRankingStatus.INVALID
    assert report.winner is None
    assert "compiler identity mismatch" in (report.candidates[0].reason or "")


def test_geometry_input_rejects_unsupported_null_algorithm(tmp_path):
    config = resolve_optimizer_config(_raw(tmp_path))
    family = compile_sealed_candidate_family(config)
    cells = _cells(
        family,
        _groups(config),
        cutoff_evidence=_reaction_evidence_for_lift(0.1),
    )
    with pytest.raises(ValueError, match="null_algorithm_id"):
        _rank(config, family, cells, null_algorithm_id="unsupported@1")


def test_geometry_cell_null_algorithm_mismatch_is_invalid(tmp_path):
    config = resolve_optimizer_config(_raw(tmp_path))
    family = compile_sealed_candidate_family(config)
    cells = list(
        _cells(
            family,
            _groups(config),
            cutoff_evidence=_reaction_evidence_for_lift(0.1),
        )
    )
    cells[0] = replace(cells[0], null_algorithm_id="unsupported@1")
    report = _rank(config, family, cells)
    assert report.status is GeometryRankingStatus.INVALID
    assert report.winner is None
    assert "null algorithm mismatch" in (report.candidates[0].reason or "")


def test_geometry_report_binds_compiler_map_null_and_family_identity(tmp_path):
    config = resolve_optimizer_config(_raw(tmp_path))
    family = compile_sealed_candidate_family(config)
    cells = _cells(
        family,
        _groups(config),
        cutoff_evidence=_reaction_evidence_for_lift(0.1),
    )
    first = _rank(config, family, cells)
    alternate_cells = _cells(
        family,
        _groups(config),
        cutoff_evidence=_reaction_evidence_for_lift(0.1),
        compiler_fingerprint="alternate-compiler",
    )
    alternate_map = {
        candidate.candidate_id: {
            asset: "alternate-compiler" for asset in config.source.assets
        }
        for candidate in family.candidates
    }
    second = _rank(
        config,
        family,
        alternate_cells,
        compiler_fingerprints=alternate_map,
    )
    assert first.status is GeometryRankingStatus.PROVISIONAL_WINNER
    assert second.status is GeometryRankingStatus.PROVISIONAL_WINNER
    assert first.report_fingerprint != second.report_fingerprint

    other_raw = deepcopy(_raw(tmp_path))
    other_raw["search"]["seed"] = "different-family-seed"
    other_config = resolve_optimizer_config(other_raw)
    other_family = compile_sealed_candidate_family(other_config)
    other_cells = _cells(
        other_family,
        _groups(config),
        cutoff_evidence=_reaction_evidence_for_lift(0.1),
    )
    report = _rank(
        config,
        other_family,
        other_cells,
        compiler_fingerprints=_compiler_fingerprints(other_family, config),
    )
    assert report.status is GeometryRankingStatus.INVALID
    assert report.winner is None
    assert "family hash" in (report.candidates[0].reason or "")
