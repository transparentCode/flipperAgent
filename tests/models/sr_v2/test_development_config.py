from __future__ import annotations

import hashlib
import shutil
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from libs.models.sr_v2.config.resolver import SRV2ConfigResolver, load_sr_v2_yaml
from libs.models.sr_v2.contracts import ZoneSide
from libs.models.sr_v2.domain.identity import canonical_hash
from libs.models.sr_v2.research.development import (
    GLOBAL_GEOMETRY_SCHEMA,
    TARGET_DESIGN_D_PROPOSAL_POLICY_ID,
    TARGET_DESIGN_SCHEMA,
    GlobalGeometryResources,
    TargetDesignArtifact,
    TargetDesignAssetBinding,
    TargetDesignBarrier,
    TargetDesignHorizon,
    build_target_design_artifact,
    load_target_design_artifact,
    resolve_global_geometry_config,
    resolve_target_design_config,
    runtime_environment_receipt,
    write_target_design_artifact,
)
from libs.models.sr_v2.research.optimizer import (
    TargetGroupDiagnostic,
    TargetIdentificationReport,
    TargetIdentificationStatus,
    TargetTupleDiagnostic,
    TargetTupleStatus,
    load_optimizer_yaml,
)
from libs.models.sr_v2.research.placebos import FEASIBLE_RANDOM_PRICE_ID
from libs.models.sr_v2.research_lab.scientific_compiler import ScientificGroupKey


def _target_raw(tmp_path: Path, *, assets: dict[str, str] | None = None) -> dict:
    return {
        "schema": TARGET_DESIGN_SCHEMA,
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
        "target_design_window": {
            "start": "2024-01-03T00:00:00Z",
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
        "identifiability": {
            "tuples": [
                {
                    "source_horizon_bars": 1,
                    "reference_lookback": 3,
                    "barrier_multiplier": "0.5",
                },
                {
                    "source_horizon_bars": 2,
                    "reference_lookback": 4,
                    "barrier_multiplier": "0.75",
                },
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
            "maximum_null_unavailable_rate": 0.5,
            "selection_policy_id": "first_feasible@1",
        },
        "inference": {
            "joint_utc_block": "2d",
            "epoch": "2024-01-01T00:00:00Z",
        },
        "resources": {
            "max_workers": 1,
            "receipt_dir": str(tmp_path / "receipts"),
            "artifact_root": str(tmp_path / "artifacts"),
        },
    }


def _binding(instrument: str = "BTCUSDT") -> TargetDesignAssetBinding:
    return TargetDesignAssetBinding(
        instrument_id=instrument,
        source_manifest_id="a" * 64,
        source_sha256="b" * 64,
        source_slice_fingerprint="c" * 64,
        baseline_episode_artifact_id="d" * 64,
        common_risk_receipt_fingerprint="e" * 64,
        selected_compiler_fingerprint="f" * 64,
    )


def _comparator_config():
    return SRV2ConfigResolver(load_sr_v2_yaml("configs/sr_v2.yaml")).resolve()


def _target_report(config, *, status=TargetTupleStatus.FEASIBLE):
    if config.comparator_config is None:
        raise ValueError("fixture target report requires comparator_config")
    target_tuple = config.identifiability.tuples[0]
    target_fingerprints = config.target_fingerprints(target_tuple)
    groups = tuple(
        TargetGroupDiagnostic(
            target_tuple=target_tuple,
            group=group,
            observation_count=1,
            issuance_cutoffs=(config.target_design_window.start,),
            actual_available_count=1,
            null_available_count=1,
            uncensored_count=1,
            touched_count=1,
            untouched_count=0,
            censored_count=0,
            unresolved_count=0,
            actual_touch_count=1,
            null_touch_count=1,
            bounce_count=1,
            break_count=0,
            null_untouched_count=0,
            null_censored_count=0,
            null_unresolved_count=0,
            null_bounce_count=1,
            null_break_count=0,
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
            target_fingerprint=target_fingerprints[group.timeframe],
            compiler_fingerprint="f" * 64,
            source_manifest_id="a" * 64,
            source_sha256="b" * 64,
            diagnostic_fingerprint="1" * 64,
        )
        for asset in config.source.assets
        for timeframe in config.source.ladder
        for kernel in config.comparator_config.kernels
        if kernel.enabled_for(timeframe)
        for side in ZoneSide
        for group in (
            ScientificGroupKey(
                asset=asset,
                timeframe=timeframe,
                kernel_id=kernel.kernel_id,
                kernel_version=kernel.kernel_version,
                side=side,
            ),
        )
    )
    diagnostics = tuple(
        TargetTupleDiagnostic(
            target_tuple=target_tuple,
            status=status if index else TargetTupleStatus.FEASIBLE,
            groups=groups if index == 0 else (),
            reason=None if index == 0 else "fixture not selected",
            tuple_fingerprint=(str(index + 1) * 64),
        )
        for index, target_tuple in enumerate(config.identifiability.tuples)
    )
    selected = config.identifiability.tuples[0]
    return TargetIdentificationReport(
        status=TargetIdentificationStatus.TARGET_IDENTIFIED,
        selected_tuple=selected,
        tuple_diagnostics=diagnostics,
        report_fingerprint=canonical_hash(
            {
                "status": TargetIdentificationStatus.TARGET_IDENTIFIED.value,
                "selected": selected,
                "diagnostics": diagnostics,
            }
        ),
    )


def test_target_design_schema_is_strict_and_fingerprinted(tmp_path):
    config = resolve_target_design_config(_target_raw(tmp_path))
    assert config.schema == TARGET_DESIGN_SCHEMA
    assert config.resources.max_workers == 1
    assert (
        config.target_spec(config.identifiability.tuples[0], "1d").source_horizon_bars
        == 1
    )
    altered = deepcopy(_target_raw(tmp_path))
    altered["unexpected"] = True
    with pytest.raises(ValueError, match="unknown"):
        resolve_target_design_config(altered)
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema: one\nschema: two\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_optimizer_yaml(duplicate)
    bad_policy = deepcopy(_target_raw(tmp_path))
    bad_policy["reference_volatility"]["algorithm_id"] = "pending"
    with pytest.raises(ValueError, match="algorithm"):
        resolve_target_design_config(bad_policy)


def test_target_design_horizon_exposes_exact_dataclass_fields():
    assert set(TargetDesignHorizon.__dataclass_fields__) == {
        "unit",
        "observation_timeframe",
    }


def test_target_barrier_requires_the_approved_derivation_policy():
    barrier = TargetDesignBarrier(
        derivation_policy_id=TARGET_DESIGN_D_PROPOSAL_POLICY_ID,
        scan_lower="0.75",
        scan_upper="1.25",
        candidate_cap=3,
    )
    assert barrier.derivation_policy_id == TARGET_DESIGN_D_PROPOSAL_POLICY_ID
    with pytest.raises(ValueError, match="derivation policy"):
        TargetDesignBarrier(
            derivation_policy_id="other@1",
            scan_lower="0.75",
            scan_upper="1.25",
            candidate_cap=3,
        )


@pytest.mark.parametrize(
    "lower,upper",
    [("0.75", "1.25"), ("0.1", "0.49")],
)
def test_target_design_rejects_barrier_multiplier_outside_scan(tmp_path, lower, upper):
    raw = _target_raw(tmp_path)
    raw["barrier"]["scan_lower"] = lower
    raw["barrier"]["scan_upper"] = upper
    with pytest.raises(ValueError, match="barrier multipliers"):
        resolve_target_design_config(raw)


def test_target_design_counts_reused_barrier_multiplier_once(tmp_path):
    raw = _target_raw(tmp_path)
    raw["barrier"]["scan_lower"] = "0.5"
    raw["barrier"]["scan_upper"] = "0.5"
    raw["barrier"]["candidate_cap"] = 1
    raw["identifiability"]["tuples"][1]["barrier_multiplier"] = "0.5"
    config = resolve_target_design_config(raw)
    assert {item.barrier_multiplier for item in config.identifiability.tuples} == {
        config.barrier.scan_lower
    }


def test_approved_target_design_proposal_has_three_distinct_barriers(tmp_path):
    raw = _target_raw(tmp_path)
    raw["barrier"] = {
        "derivation_policy_id": TARGET_DESIGN_D_PROPOSAL_POLICY_ID,
        "scan_lower": "0.75",
        "scan_upper": "1.25",
        "candidate_cap": 3,
    }
    raw["identifiability"]["tuples"] = [
        {
            "source_horizon_bars": 5,
            "reference_lookback": 5,
            "barrier_multiplier": "1.00",
        },
        {
            "source_horizon_bars": 5,
            "reference_lookback": 5,
            "barrier_multiplier": "0.75",
        },
        {
            "source_horizon_bars": 5,
            "reference_lookback": 5,
            "barrier_multiplier": "1.25",
        },
        {
            "source_horizon_bars": 5,
            "reference_lookback": 7,
            "barrier_multiplier": "1.00",
        },
        {
            "source_horizon_bars": 5,
            "reference_lookback": 10,
            "barrier_multiplier": "1.00",
        },
    ]
    raw["inference"]["joint_utc_block"] = "5d"
    config = resolve_target_design_config(raw)
    assert len({item.barrier_multiplier for item in config.identifiability.tuples}) == 3


def test_target_design_rejects_too_many_distinct_barriers(tmp_path):
    raw = _target_raw(tmp_path)
    raw["barrier"]["candidate_cap"] = 1
    with pytest.raises(ValueError, match="candidate cap"):
        resolve_target_design_config(raw)


def test_global_resource_run_boundaries_and_invalid_values():
    resources = GlobalGeometryResources(
        max_workers=1,
        receipt_dir="receipts",
        artifact_root="artifacts",
        max_peak_rss_bytes_per_asset=10,
        max_artifact_bytes_per_asset=20,
        max_wall_seconds_per_asset=30,
        max_total_artifact_bytes=40,
    )
    resources.validate_completed_run(
        peak_rss_bytes=10, artifact_bytes=20, wall_seconds=30
    )
    with pytest.raises(ValueError, match="peak_rss_bytes"):
        resources.validate_completed_run(
            peak_rss_bytes=11, artifact_bytes=20, wall_seconds=30
        )
    with pytest.raises(ValueError, match="artifact_bytes"):
        resources.validate_completed_run(
            peak_rss_bytes=10, artifact_bytes=21, wall_seconds=30
        )
    with pytest.raises(ValueError, match="wall_seconds"):
        resources.validate_completed_run(
            peak_rss_bytes=10, artifact_bytes=20, wall_seconds=31
        )
    for value in (True, 0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            resources.validate_completed_run(
                peak_rss_bytes=value, artifact_bytes=1, wall_seconds=1
            )
        with pytest.raises(ValueError):
            resources.validate_completed_run(
                peak_rss_bytes=1, artifact_bytes=value, wall_seconds=1
            )
    for value in (True, 0, -1, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            resources.validate_completed_run(
                peak_rss_bytes=1, artifact_bytes=1, wall_seconds=value
            )


def test_global_resource_retained_artifact_scope_and_boundaries():
    resources = GlobalGeometryResources(
        max_workers=1,
        receipt_dir="receipts",
        artifact_root="artifacts",
        max_peak_rss_bytes_per_asset=10,
        max_artifact_bytes_per_asset=30,
        max_wall_seconds_per_asset=30,
        max_total_artifact_bytes=40,
    )
    resources.validate_retained_artifacts(
        {
            ("baseline", "BTCUSDT"): 20,
            ("candidate", "ETHUSDT"): 20,
        }
    )
    with pytest.raises(ValueError, match="total ceiling"):
        resources.validate_retained_artifacts(
            {
                ("baseline", "BTCUSDT"): 21,
                ("candidate", "ETHUSDT"): 20,
            }
        )
    with pytest.raises(ValueError, match="per-asset ceiling"):
        resources.validate_retained_artifacts({("baseline", "BTCUSDT"): 31})
    for key in (
        ("", "BTCUSDT"),
        ("baseline", ""),
        ("baseline",),
        ["baseline", "BTCUSDT"],
    ):
        with pytest.raises((TypeError, ValueError)):
            resources.validate_retained_artifacts({key: 1})
    for value in (True, 0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            resources.validate_retained_artifacts({("baseline", "BTCUSDT"): value})


def test_protected_phase1_yaml_hash_is_unchanged():
    assert (
        hashlib.sha256(
            Path("configs/sr_v2_trials/phase1.yaml").read_bytes()
        ).hexdigest()
        == "96b05813904b5ead8919a06a1d08ff9ca9d3242cf09961a1aa28fc48d4be8547"
    )


def test_target_artifact_factory_enforces_identified_first_feasible(tmp_path):
    config = resolve_target_design_config(
        _target_raw(tmp_path), comparator_config=_comparator_config()
    )
    bindings = {"BTCUSDT": _binding()}
    report = _target_report(config)
    comparator_model_fingerprint = config.comparator_config.config_fingerprint
    artifact = build_target_design_artifact(
        config=config,
        report=report,
        target_design_yaml_sha256="1" * 64,
        comparator_yaml_sha256="2" * 64,
        comparator_model_fingerprint=comparator_model_fingerprint,
        asset_bindings=bindings,
        implementation_digest="4" * 64,
        runtime_environment_receipt={"schema": "fixture-runtime@1", "value": "fixture"},
    )
    with pytest.raises(ValueError, match="comparator model fingerprint"):
        build_target_design_artifact(
            config=config,
            report=report,
            target_design_yaml_sha256="1" * 64,
            comparator_yaml_sha256="2" * 64,
            comparator_model_fingerprint="3" * 64,
            asset_bindings=bindings,
            implementation_digest="4" * 64,
            runtime_environment_receipt={
                "schema": "fixture-runtime@1",
                "value": "fixture",
            },
        )
    path = write_target_design_artifact(artifact, tmp_path / "artifacts")
    assert load_target_design_artifact(path).artifact_id == artifact.artifact_id
    mismatched_binding = replace(bindings["BTCUSDT"], source_manifest_id="9" * 64)
    with pytest.raises(ValueError, match="identity"):
        build_target_design_artifact(
            config=config,
            report=report,
            target_design_yaml_sha256="1" * 64,
            comparator_yaml_sha256="2" * 64,
            comparator_model_fingerprint=comparator_model_fingerprint,
            asset_bindings={"BTCUSDT": mismatched_binding},
            implementation_digest="4" * 64,
            runtime_environment_receipt={
                "schema": "fixture-runtime@1",
                "value": "fixture",
            },
        )
    invalid = TargetIdentificationReport(
        status=TargetIdentificationStatus.TARGET_NOT_IDENTIFIED,
        selected_tuple=None,
        tuple_diagnostics=report.tuple_diagnostics,
        report_fingerprint="5" * 64,
    )
    with pytest.raises(ValueError, match="TARGET_IDENTIFIED"):
        build_target_design_artifact(
            config=config,
            report=invalid,
            target_design_yaml_sha256="1" * 64,
            comparator_yaml_sha256="2" * 64,
            comparator_model_fingerprint=comparator_model_fingerprint,
            asset_bindings=bindings,
            implementation_digest="4" * 64,
            runtime_environment_receipt={
                "schema": "fixture-runtime@1",
                "value": "fixture",
            },
        )
    reordered = TargetIdentificationReport(
        status=report.status,
        selected_tuple=config.identifiability.tuples[1],
        tuple_diagnostics=report.tuple_diagnostics,
        report_fingerprint=canonical_hash(
            {
                "status": report.status.value,
                "selected": config.identifiability.tuples[1],
                "diagnostics": report.tuple_diagnostics,
            }
        ),
    )
    with pytest.raises(ValueError, match="first feasible"):
        build_target_design_artifact(
            config=config,
            report=reordered,
            target_design_yaml_sha256="1" * 64,
            comparator_yaml_sha256="2" * 64,
            comparator_model_fingerprint=comparator_model_fingerprint,
            asset_bindings=bindings,
            implementation_digest="4" * 64,
            runtime_environment_receipt={
                "schema": "fixture-runtime@1",
                "value": "fixture",
            },
        )
    with pytest.raises(ValueError, match="first feasible"):
        TargetDesignArtifact(
            target_design_yaml_sha256=artifact.target_design_yaml_sha256,
            config_fingerprint=artifact.config_fingerprint,
            source_window_fingerprint=artifact.source_window_fingerprint,
            comparator_yaml_sha256=artifact.comparator_yaml_sha256,
            comparator_model_fingerprint=artifact.comparator_model_fingerprint,
            asset_bindings=artifact.asset_bindings,
            tuple_diagnostics=artifact.tuple_diagnostics,
            report_fingerprint=artifact.report_fingerprint,
            selected_tuple=config.identifiability.tuples[1],
            target_fingerprints=artifact.target_fingerprints,
            target_family_fingerprint=artifact.target_family_fingerprint,
            null_algorithm_id=artifact.null_algorithm_id,
            implementation_digest=artifact.implementation_digest,
            runtime_environment_receipt=artifact.runtime_environment_receipt,
            artifact_id="pending",
        )
    forged_fingerprints = dict(artifact.target_fingerprints)
    forged_fingerprints["1d"] = "9" * 64
    with pytest.raises(ValueError, match="target_fingerprints"):
        TargetDesignArtifact(
            target_design_yaml_sha256=artifact.target_design_yaml_sha256,
            config_fingerprint=artifact.config_fingerprint,
            source_window_fingerprint=artifact.source_window_fingerprint,
            comparator_yaml_sha256=artifact.comparator_yaml_sha256,
            comparator_model_fingerprint=artifact.comparator_model_fingerprint,
            asset_bindings=artifact.asset_bindings,
            tuple_diagnostics=artifact.tuple_diagnostics,
            report_fingerprint=artifact.report_fingerprint,
            selected_tuple=artifact.selected_tuple,
            target_fingerprints=forged_fingerprints,
            target_family_fingerprint=artifact.target_family_fingerprint,
            null_algorithm_id=artifact.null_algorithm_id,
            implementation_digest=artifact.implementation_digest,
            runtime_environment_receipt=artifact.runtime_environment_receipt,
            artifact_id="pending",
        )


def test_operational_paths_do_not_change_target_or_global_fingerprints(tmp_path):
    target_raw = _target_raw(tmp_path)
    first = resolve_target_design_config(target_raw)
    relocated_target_raw = deepcopy(target_raw)
    relocated_target_raw["source"]["cache_root"] = str(tmp_path / "other-cache")
    relocated_target_raw["resources"]["receipt_dir"] = str(tmp_path / "other-receipts")
    relocated_target_raw["resources"]["artifact_root"] = str(
        tmp_path / "other-artifacts"
    )
    second = resolve_target_design_config(relocated_target_raw)
    assert second.config_fingerprint == first.config_fingerprint


def test_runtime_receipt_uses_explicit_distribution_allowlist(tmp_path):
    receipt = runtime_environment_receipt(Path("."))
    names = {name.lower() for name, _ in receipt["third_party_distributions"]}
    assert "pyyaml" in names
    assert "pytest" not in names


def _global_raw(tmp_path: Path, artifact_path: Path, artifact) -> dict:
    baseline_path = Path("configs/sr_v2.yaml")
    baseline = SRV2ConfigResolver(load_sr_v2_yaml(baseline_path)).resolve()
    baseline_sha = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    runtime_fp = canonical_hash(artifact.runtime_environment_receipt)
    bindings = {
        asset: binding.to_mapping()
        for asset, binding in artifact.asset_bindings.items()
    }
    return {
        "schema": GLOBAL_GEOMETRY_SCHEMA,
        "source": _target_raw(tmp_path)["source"],
        "splits": {
            "target_design": {
                "start": "2024-01-03T00:00:00Z",
                "end": "2024-01-05T00:00:00Z",
            },
            "geometry_train": {
                "start": "2024-01-07T00:00:00Z",
                "end": "2024-01-10T00:00:00Z",
            },
            "geometry_validation": {
                "start": "2024-01-12T00:00:00Z",
                "end": "2024-01-15T00:00:00Z",
            },
            "embargo": {"start": "2024-01-10T00:00:00Z", "end": "2024-01-11T00:00:00Z"},
        },
        "target_freeze": {
            "target_design_artifact_path": str(artifact_path),
            "target_design_artifact_sha256": hashlib.sha256(
                artifact_path.read_bytes()
            ).hexdigest(),
            "target_design_artifact_id": artifact.artifact_id,
            "target_selection_report_fingerprint": artifact.report_fingerprint,
            "target_family_fingerprint": artifact.target_family_fingerprint,
            "baseline_structural_yaml_sha256": baseline_sha,
            "baseline_model_fingerprint": baseline.config_fingerprint,
            "selected_tuple": {
                "source_horizon_bars": artifact.selected_tuple.source_horizon_bars,
                "reference_lookback": artifact.selected_tuple.reference_lookback,
                "barrier_multiplier": artifact.selected_tuple.barrier_multiplier,
            },
            "target_fingerprints": dict(artifact.target_fingerprints),
            "null_algorithm_id": FEASIBLE_RANDOM_PRICE_ID,
            "implementation_digest": artifact.implementation_digest,
            "runtime_environment_fingerprint": runtime_fp,
            "asset_bindings": bindings,
        },
        "search": {
            "sampler_id": "sealed_global_finite_choices@1",
            "seed": "fixture-seed",
            "trial_budget": 1,
            "baseline_structural_yaml": str(baseline_path),
            "parameters": {},
        },
        "inference": {
            "joint_utc_block": "2d",
            "epoch": "2024-01-01T00:00:00Z",
            "repetitions": 3,
            "confidence": 0.9,
            "alpha_family": "bonferroni@1",
            "degradation_margin": "0.1",
            "minimum_paired_reaction_clusters": 1,
            "minimum_unique_issuance_cutoffs": 1,
            "minimum_common_joint_utc_blocks": 1,
            "minimum_asset_support": 1,
        },
        "resources": {
            "max_workers": 1,
            "receipt_dir": str(tmp_path / "global-receipts"),
            "artifact_root": str(tmp_path / "global-artifacts"),
            "max_peak_rss_bytes_per_asset": 1,
            "max_artifact_bytes_per_asset": 1,
            "max_wall_seconds_per_asset": 1,
            "max_total_artifact_bytes": 1,
        },
        "ranking_policy_id": "worst_tf_kernel_side_then_equal_cell@2",
    }


def test_global_schema_authenticates_target_runtime_instrument_and_purge(tmp_path):
    target_config = resolve_target_design_config(
        _target_raw(tmp_path), comparator_config=_comparator_config()
    )
    artifact = build_target_design_artifact(
        config=target_config,
        report=_target_report(target_config),
        target_design_yaml_sha256="1" * 64,
        comparator_yaml_sha256=hashlib.sha256(
            Path("configs/sr_v2.yaml").read_bytes()
        ).hexdigest(),
        comparator_model_fingerprint=SRV2ConfigResolver(
            load_sr_v2_yaml("configs/sr_v2.yaml")
        )
        .resolve()
        .config_fingerprint,
        asset_bindings={"BTCUSDT": _binding()},
        implementation_digest="4" * 64,
        runtime_environment_receipt={"schema": "fixture-runtime@1", "value": "fixture"},
    )
    path = write_target_design_artifact(artifact, tmp_path / "artifacts")
    raw = _global_raw(tmp_path, path, artifact)
    resolved = resolve_global_geometry_config(raw)
    assert resolved.schema == GLOBAL_GEOMETRY_SCHEMA
    bad_runtime = deepcopy(raw)
    bad_runtime["target_freeze"]["runtime_environment_fingerprint"] = "5" * 64
    with pytest.raises(ValueError, match="runtime"):
        resolve_global_geometry_config(bad_runtime)
    bad_instrument = deepcopy(raw)
    bad_instrument["target_freeze"]["asset_bindings"]["BTCUSDT"]["instrument_id"] = (
        "OTHER"
    )
    with pytest.raises(ValueError, match="instrument"):
        resolve_global_geometry_config(bad_instrument)
    bad_gap = deepcopy(raw)
    bad_gap["splits"]["geometry_train"]["start"] = "2024-01-05T12:00:00Z"
    with pytest.raises(ValueError, match="purge gap"):
        resolve_global_geometry_config(bad_gap)
    bad_target_window = deepcopy(raw)
    bad_target_window["splits"]["target_design"]["start"] = "2024-01-04T00:00:00Z"
    with pytest.raises(ValueError, match="source or target-design window"):
        resolve_global_geometry_config(bad_target_window)


def test_operational_paths_do_not_change_global_fingerprint(tmp_path):
    target_config = resolve_target_design_config(
        _target_raw(tmp_path), comparator_config=_comparator_config()
    )
    artifact = build_target_design_artifact(
        config=target_config,
        report=_target_report(target_config),
        target_design_yaml_sha256="1" * 64,
        comparator_yaml_sha256=hashlib.sha256(
            Path("configs/sr_v2.yaml").read_bytes()
        ).hexdigest(),
        comparator_model_fingerprint=SRV2ConfigResolver(
            load_sr_v2_yaml("configs/sr_v2.yaml")
        )
        .resolve()
        .config_fingerprint,
        asset_bindings={"BTCUSDT": _binding()},
        implementation_digest="4" * 64,
        runtime_environment_receipt={"schema": "fixture-runtime@1", "value": "fixture"},
    )
    path = write_target_design_artifact(artifact, tmp_path / "artifacts")
    raw = _global_raw(tmp_path, path, artifact)
    first = resolve_global_geometry_config(raw)

    relocated = tmp_path / "relocated"
    relocated.mkdir()
    relocated_artifact = relocated / path.name
    shutil.copyfile(path, relocated_artifact)
    baseline_copy = relocated / "baseline.yaml"
    shutil.copyfile("configs/sr_v2.yaml", baseline_copy)
    moved = deepcopy(raw)
    moved["source"]["cache_root"] = str(tmp_path / "other-cache")
    moved["target_freeze"]["target_design_artifact_path"] = str(relocated_artifact)
    moved["search"]["baseline_structural_yaml"] = str(baseline_copy)
    moved["resources"]["receipt_dir"] = str(tmp_path / "other-receipts")
    moved["resources"]["artifact_root"] = str(tmp_path / "other-artifacts")
    second = resolve_global_geometry_config(moved)
    assert second.config_fingerprint == first.config_fingerprint
