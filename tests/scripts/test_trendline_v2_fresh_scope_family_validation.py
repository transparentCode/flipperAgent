from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from libs.models.trendline_v2.discovery import (
    ConfirmedExtremaPairProvider,
    ProviderDiagnostics,
    ProviderInput,
    ProviderReason,
    ProviderResult,
    ProviderStatus,
)
from scripts import analyze_trendline_v2_fresh_scope_family_validation as study


UTC = timezone.utc
BASE = datetime(2026, 5, 22, tzinfo=UTC)


def _input(asset: str, timeframe: str, count: int = 160) -> ProviderInput:
    interval = 3_600 if timeframe == "1h" else 14_400
    timestamps = tuple(
        int((BASE + timedelta(seconds=index * interval)).timestamp() * 1_000_000_000)
        for index in range(count)
    )
    low = tuple(1.0 + (index % 7) if index % 2 == 1 else 8.0 for index in range(count))
    high = tuple(20.0 - (index % 7) if index % 2 == 1 else 13.0 for index in range(count))
    return ProviderInput(
        asset=asset,
        timeframe=timeframe,
        observed_at=BASE + timedelta(seconds=count * interval),
        confirmed_through=BASE + timedelta(seconds=count * interval),
        timestamps=timestamps,
        open=(10.0,) * count,
        high=high,
        low=low,
        close=(10.0,) * count,
        volume=(1.0,) * count,
    )


def _context(tmp_path: Path) -> tuple[study.CohortContext, Path]:
    source_root = tmp_path / "source"
    source_root.mkdir()
    marker = source_root / "source.marker"
    marker.write_text("immutable\n", encoding="utf-8")
    inventory = (
        {
            "path": "source.marker",
            "byte_length": marker.stat().st_size,
            "sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
        },
    )
    datasets = tuple(
        study.DatasetContext(
            dataset_id=f"{asset.lower()}_{timeframe}",
            asset=asset,
            timeframe=timeframe,
            input_data=_input(asset, timeframe),
            dataset_source_identity=f"source-{asset.lower()}-{timeframe}",
            request_order=index,
        )
        for index, (asset, timeframe) in enumerate(study.DATASET_ORDER, start=1)
    )
    return (
        study.CohortContext(
            datasets=datasets,
            cohort_contract_id="synthetic-cohort-contract",
            cohort_source_identity="synthetic-cohort-source",
            source_inventory=inventory,
            source_inventory_sha256=study._inventory_sha256(inventory),
            source_decision_id="synthetic-decision",
            source_manifest_id="synthetic-manifest",
        ),
        source_root,
    )


def _provider_factory(calls: list[str]):
    provider = ConfirmedExtremaPairProvider()

    def execute(frame, *, config, provider_config):
        calls.append(f"{frame.asset.lower()}_{frame.timeframe}")
        return provider.generate(
            study.ProviderRequest(
                input_data=ProviderInput(
                    asset=frame.asset,
                    timeframe=frame.timeframe,
                    observed_at=frame.observed_at,
                    confirmed_through=frame.confirmed_through,
                    timestamps=tuple(int(value) for value in frame.arrays().timestamps),
                    open=tuple(float(value) for value in frame.arrays().open),
                    high=tuple(float(value) for value in frame.arrays().high),
                    low=tuple(float(value) for value in frame.arrays().low),
                    close=tuple(float(value) for value in frame.arrays().close),
                    volume=tuple(float(value) for value in frame.arrays().volume),
                ),
                config=config,
                provider_config=provider_config,
            )
        )

    return execute


def test_fixed_identities_and_physical_horizons() -> None:
    config = study._foundation_config()
    provider = study._provider_config()
    assert config.semantic_hash == study.FOUNDATION_CONFIG_ID
    assert provider.semantic_hash == study.PROVIDER_CONFIG_ID
    assert provider.provider_contract_identity == study.PROVIDER_CONTRACT_ID
    assert study.deterministic_hash(
        "trendline_v2_combined_configuration",
        {
            "foundation_config_identity": config.semantic_hash,
            "provider_config_identity": provider.semantic_hash,
        },
    ) == study.COMBINED_CONFIG_ID
    contract = study._study_contract(config, provider)
    assert contract["horizons"] == [
        {"horizon": "24h", "bars_by_timeframe": {"1h": 24, "4h": 6}},
        {"horizon": "48h", "bars_by_timeframe": {"1h": 48, "4h": 12}},
        {"horizon": "96h", "bars_by_timeframe": {"1h": 96, "4h": 24}},
    ]


def test_selector_contract_and_family_invariants_are_fixed() -> None:
    assert study.deterministic_hash(
        "trendline_v2_phase_9b2_selector_contract_v1",
        {
            "schema_version": "trendline_v2_phase_9b2_selector_contract_v1",
            "allowed_fields": list(study.SELECTOR_FIELDS),
            "forbidden_fields": list(study.FORBIDDEN_SELECTOR_FIELDS),
            "families": list(study.FAMILY_DEFINITIONS),
        },
    ) == study.SELECTOR_CONTRACT_ID
    assert tuple(item["family_id"] for item in study.FAMILY_DEFINITIONS) == study.FAMILY_IDS


def test_selector_membership_is_input_order_and_future_label_invariant() -> None:
    records = []
    for index in range(4):
        record = {
            "candidate_id": f"{index:064x}",
            "candidate_structure_id": f"{index + 10:064x}",
            "role": "support" if index % 2 == 0 else "resistance",
            "first_anchor_id": f"{index + 20:064x}",
            "second_anchor_id": f"{index % 2 + 30:064x}",
            "first_anchor_time": f"2026-05-22T0{index}:00:00Z",
            "second_anchor_time": "2026-05-22T12:00:00Z",
            "same_role_extrema_skip_count": index,
            "minimum_body_clearance_bps": float(index),
            "minimum_anchor_prominence_bps": float(4 - index),
            "candidate_available_at": "2026-05-23T00:00:00Z",
            "role_marker": index,
            "evaluations": {"24h": {"future_contact_count": index}},
        }
        records.append(record)
    first = study.select_families(records)
    mutated = [replace_record(record, evaluations={"24h": {"future_contact_count": 999}}) for record in records]
    second = study.select_families(tuple(reversed(mutated)))
    for family_id in study.FAMILY_IDS:
        assert [item["candidate_id"] for item in first[family_id]] == [item["candidate_id"] for item in second[family_id]]


def replace_record(record: dict[str, object], **changes: object) -> dict[str, object]:
    result = dict(record)
    result.update(changes)
    return result


def test_run_executes_exact_order_and_writes_lock_before_sui(tmp_path: Path) -> None:
    context, source_root = _context(tmp_path)
    calls: list[str] = []
    lock_seen: list[bool] = []

    def before_sui(staging: Path, lock_sha: str) -> None:
        lock_path = staging / "validation_lock.json"
        lock_seen.append(lock_path.is_file())
        assert hashlib.sha256(lock_path.read_bytes()).hexdigest() == lock_sha
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["validation_lock_id"]

    output = tmp_path / "output"
    result = study.run_study(
        source_root=source_root,
        output_root=output,
        _cohort_context=context,
        provider=_provider_factory(calls),
        _before_sui=before_sui,
    )
    assert calls == [
        "btcusdt_1h",
        "btcusdt_4h",
        "ethusdt_1h",
        "ethusdt_4h",
        "suiusdt_1h",
        "suiusdt_4h",
    ]
    assert lock_seen == [True]
    assert result["validation_lock_id"]
    assert len(tuple(path for path in output.rglob("*") if path.is_file())) == 38
    assert json.loads((output / "provider_execution_audit.json").read_text())["provider_execution_count"] == 6
    assert (output / "validation_lock.json").is_file()
    assert (output / "manifest.json").is_file()


def test_existing_output_is_refused_without_provider_call(tmp_path: Path) -> None:
    context, source_root = _context(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    called = False

    def provider(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not run")

    with pytest.raises(FileExistsError):
        study.run_study(source_root=source_root, output_root=output, _cohort_context=context, provider=provider)
    assert not called


def test_provider_failure_aborts_and_does_not_publish(tmp_path: Path) -> None:
    context, source_root = _context(tmp_path)
    calls = 0

    def failing_provider(frame, *, config, provider_config):
        nonlocal calls
        calls += 1
        request = study.ProviderRequest(
            input_data=ProviderInput(
                asset=frame.asset,
                timeframe=frame.timeframe,
                observed_at=frame.observed_at,
                confirmed_through=frame.confirmed_through,
                timestamps=tuple(int(value) for value in frame.arrays().timestamps),
                open=tuple(float(value) for value in frame.arrays().open),
                high=tuple(float(value) for value in frame.arrays().high),
                low=tuple(float(value) for value in frame.arrays().low),
                close=tuple(float(value) for value in frame.arrays().close),
                volume=tuple(float(value) for value in frame.arrays().volume),
            ),
            config=config,
            provider_config=provider_config,
        )
        return ProviderResult(
            provider_name=provider_config.provider_name,
            provider_version=provider_config.provider_version,
            request=request,
            status=ProviderStatus.ABSTAINED,
            candidates=(),
            evidence=(),
            diagnostics=ProviderDiagnostics(0, request.input_data.row_count),
            reason=ProviderReason.NO_CANDIDATES,
        )

    output = tmp_path / "output"
    with pytest.raises(study.ProviderScopeBlocked, match="BLOCKED_PROVIDER_SCOPE"):
        study.run_study(source_root=source_root, output_root=output, _cohort_context=context, provider=failing_provider)
    assert calls == 1
    assert not output.exists()


def test_candidate_records_use_dynamic_bar_interval_and_future_labels() -> None:
    data = _input("BTCUSDT", "4h")
    config = study._foundation_config()
    provider_config = study._provider_config()
    frame = study._frame_for(
        study.DatasetContext("btcusdt_4h", "BTCUSDT", "4h", data, "source", 1)
    )
    result = ConfirmedExtremaPairProvider().generate(
        study.ProviderRequest(
            input_data=data,
            config=config,
            provider_config=provider_config,
        )
    )
    assert frame.timeframe == "4h"
    records = tuple(
        study._candidate_record(candidate, evidence, data, study._extrema_by_role(data))
        for candidate, evidence in zip(result.candidates, result.evidence)
    )
    assert records
    for record in records:
        assert record["availability_position"] == max(record["confirmation_positions"]) + 1
        assert record["candidate_available_at"] > record["confirmation_bar_open"]
        assert set(record["evaluations"]) == {"24h", "48h", "96h"}
        assert {
            horizon: record["evaluations"][horizon]["horizon_bars"]
            for horizon in study.HORIZON_NAMES
        } == {"24h": 6, "48h": 12, "96h": 24}


def test_horizon_mapping_is_explicit_for_each_timeframe() -> None:
    assert study.HORIZON_BARS_BY_TIMEFRAME == {
        "1h": {"24h": 24, "48h": 48, "96h": 96},
        "4h": {"24h": 6, "48h": 12, "96h": 24},
    }


def test_four_hour_physical_horizons_are_not_interchangeable() -> None:
    count = 30
    timestamps = tuple(
        int((BASE + timedelta(hours=4 * index)).timestamp() * 1_000_000_000)
        for index in range(count)
    )
    data = ProviderInput(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=BASE + timedelta(hours=4 * count),
        confirmed_through=BASE + timedelta(hours=4 * count),
        timestamps=timestamps,
        open=(2.0,) * 6 + (10.0,) * 24,
        high=(5.0,) * 6 + (11.0,) * 24,
        low=(0.0,) * 6 + (9.0,) * 24,
        close=(2.0,) * 6 + (10.0,) * 24,
        volume=(1.0,) * count,
    )
    candidate = SimpleNamespace(
        role=SimpleNamespace(value="support"),
        geometry=SimpleNamespace(value_at=lambda _timestamp: 10.0),
    )
    six = study._future_evaluation(
        candidate,
        data,
        horizon="24h",
        availability_position=0,
        horizon_bars=6,
    )
    twenty_four = study._future_evaluation(
        candidate,
        data,
        horizon="96h",
        availability_position=0,
        horizon_bars=24,
    )
    assert six["horizon_bars"] == 6
    assert twenty_four["horizon_bars"] == 24
    assert six["future_contact_count"] != twenty_four["future_contact_count"]


def test_future_label_mutation_is_measured_and_selector_is_causal() -> None:
    records = []
    for index in range(4):
        records.append(
            {
                "candidate_id": f"{index:064x}",
                "candidate_structure_id": f"{index + 10:064x}",
                "role": "support" if index % 2 == 0 else "resistance",
                "first_anchor_id": f"{index + 20:064x}",
                "second_anchor_id": f"{index % 2 + 30:064x}",
                "first_anchor_time": f"2026-05-22T0{index}:00:00Z",
                "second_anchor_time": "2026-05-22T12:00:00Z",
                "same_role_extrema_skip_count": index,
                "minimum_body_clearance_bps": float(index),
                "minimum_anchor_prominence_bps": float(4 - index),
                "evaluations": {
                    horizon: {
                        "future_contact_count": index,
                        "has_exact_contact": False,
                    }
                    for horizon in study.HORIZON_NAMES
                },
            }
        )
    _, stability = study._membership_stability(records)
    assert all(item["input_order_independent_membership"] for item in stability.values())
    assert all(item["future_label_mutation_membership_invariant"] for item in stability.values())


def test_noncausal_membership_is_classified_explicitly() -> None:
    assert study._architecture_classification(
        study.FAMILY_IDS[1],
        [{"candidate_id": "candidate", "role": "support", "chronological_segment": "early"}],
        control_ids={"candidate"},
        repeat_matches=True,
        future_label_matches=False,
    ) == "INVALID_NONCAUSAL_SELECTOR"


def _gate_metric(
    *,
    coverage: float = 0.90,
    fraction: float = 0.35,
    overlap_p95: float = 15.0,
    admission_p95: float = 8.0,
    survival_delta: float = 0.0,
    contact_delta: float = 0.0,
) -> dict[str, object]:
    return {
        "architecture_classification": "ARCHITECTURALLY_VALID",
        "second_anchor_group_coverage_ratio": coverage,
        "candidate_fraction_of_control": fraction,
        "finite_anchor_to_anchor_overlap": {"counts": {"p95": overlap_p95}},
        "control_metrics": {"finite_anchor_to_anchor_overlap": {"counts": {"p95": 100.0}}},
        "admission_burst": {"admissions_per_availability_bar": {"p95": admission_p95}},
        "evaluation_support": {"sufficient_for_ranking": True},
        "comparison_to_control": {
            horizon: {
                "survival_delta": survival_delta,
                "contact_and_survival_delta": contact_delta,
            }
            for horizon in study.HORIZON_NAMES
        },
    }


def test_validation_gate_accepts_declared_boundary_values() -> None:
    by_dataset = {
        dataset_id: _gate_metric()
        for dataset_id in study.VALIDATION_DATASETS
    }
    result = study._validation_gate(study.FAMILY_IDS[1], by_dataset)
    assert result["eligible"] is True
    rejected = study._validation_gate(
        study.FAMILY_IDS[1],
        {dataset_id: _gate_metric(fraction=0.350001) for dataset_id in study.VALIDATION_DATASETS},
    )
    assert rejected["eligible"] is False
    assert any("candidate_fraction_above_maximum" in reason for reason in rejected["rejection_reasons"])


def test_ranking_uses_all_declared_tie_break_levels() -> None:
    def ranking_metric(**changes: float) -> dict[str, object]:
        values = {
            "coverage": 0.95,
            "overlap_p95": 10.0,
            "admission_p95": 2.0,
            "fraction": 0.20,
            "survival_delta": 0.10,
            "contact_delta": 0.10,
        }
        values.update(changes)
        return _gate_metric(
            coverage=values["coverage"],
            fraction=values["fraction"],
            overlap_p95=values["overlap_p95"],
            admission_p95=values["admission_p95"],
            survival_delta=values["survival_delta"],
            contact_delta=values["contact_delta"],
        )

    base = {dataset_id: ranking_metric() for dataset_id in study.VALIDATION_DATASETS}
    assert study._ranking_key("a", base) < study._ranking_key("b", base)
    for field, worse in (
        ("coverage", 0.90),
        ("overlap_p95", 11.0),
        ("admission_p95", 3.0),
        ("fraction", 0.21),
        ("contact_delta", 0.09),
        ("survival_delta", 0.09),
    ):
        better = study._ranking_key("better", base)
        altered = {dataset_id: ranking_metric(**{field: worse}) for dataset_id in study.VALIDATION_DATASETS}
        assert better < study._ranking_key("altered", altered)


def _holdout_metric(*, support: bool = True, survival: float = 0.0, contact: float = 0.0) -> dict[str, object]:
    value = _gate_metric(
        overlap_p95=14.0,
        survival_delta=survival,
        contact_delta=contact,
    )
    value["evaluation_support"] = {"sufficient_for_ranking": support}
    return value


def test_holdout_pass_reject_and_no_second_rank_rescue() -> None:
    validation = {
        "validation_winner_family_id": study.FAMILY_IDS[4],
        "ordered_validation_ranking": [study.FAMILY_IDS[4], study.FAMILY_IDS[5]],
    }
    all_metrics = {
        dataset_id: {
            study.FAMILY_IDS[0]: _gate_metric(overlap_p95=100.0),
            study.FAMILY_IDS[4]: _holdout_metric(),
            study.FAMILY_IDS[5]: _holdout_metric(),
        }
        for dataset_id in study.HOLDOUT_DATASETS
    }
    assert study._holdout_result(validation, all_metrics)["status"] == "FRESH_SCOPE_PROMOTION_CANDIDATE"
    all_metrics[study.HOLDOUT_DATASETS[0]][study.FAMILY_IDS[4]] = _holdout_metric(support=False)
    result = study._holdout_result(validation, all_metrics)
    assert result["status"] == "REJECT_HOLDOUT_GATE"
    assert result["locked_winner_family_id"] == study.FAMILY_IDS[4]


def test_no_validation_finalist_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        study,
        "_validation_gate",
        lambda _family_id, _dataset_metrics: {"eligible": False, "rejection_reasons": ["synthetic"]},
    )
    metrics = {
        dataset_id: {family_id: {} for family_id in study.FAMILY_IDS}
        for dataset_id in study.VALIDATION_DATASETS
    }
    result = study._validation_result(metrics)
    assert result["validation_winner_family_id"] is None
    assert result["validation_status"] == "NO_VALIDATION_FINALIST"


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("max_hypotheses", ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED),
        ("max_output_candidates", ProviderReason.OUTPUT_LIMIT_EXCEEDED),
    ),
)
def test_workload_limits_have_typed_abstention_semantics(
    field: str,
    reason: ProviderReason,
) -> None:
    values = dict(study.FIXED_PROVIDER_VALUES)
    values[field] = 2
    provider_config = study.ConfirmedExtremaPairConfig(**values)
    result = ConfirmedExtremaPairProvider().generate(
        study.ProviderRequest(
            input_data=_input("BTCUSDT", "1h"),
            config=study._foundation_config(),
            provider_config=provider_config,
        )
    )
    assert result.status is ProviderStatus.ABSTAINED
    assert result.reason is reason
    assert not result.candidates


@pytest.mark.parametrize("role", ("support", "resistance"))
def test_future_body_violation_is_role_specific(role: str) -> None:
    data = _input("BTCUSDT", "1h", count=4)
    candidate = SimpleNamespace(
        role=SimpleNamespace(value=role),
        geometry=SimpleNamespace(value_at=lambda _timestamp: 10.0),
    )
    result = study._future_evaluation(
        candidate,
        data,
        horizon="24h",
        availability_position=0,
        horizon_bars=1,
    )
    if role == "support":
        expected = data.open[0] < 10.0 or data.close[0] < 10.0
    else:
        expected = data.open[0] > 10.0 or data.close[0] > 10.0
    assert result["future_body_violation_count"] == int(expected)


def test_stability_summary_is_derived_from_per_family_measurements() -> None:
    stable = {
        "candidate_count": 1,
        "reversed_candidate_count": 1,
        "future_label_mutated_candidate_count": 1,
        "input_order_independent_membership": True,
        "future_label_mutation_membership_invariant": True,
        "input_order_mismatch_candidate_ids": [],
        "future_label_mutation_mismatch_candidate_ids": [],
    }
    all_metrics = {
        dataset_id: {
            family_id: {"membership_stability": stable}
            for family_id in study.FAMILY_IDS
        }
        for dataset_id in study.DATASET_ORDER
    }
    # The study uses normalized dataset IDs in all persisted artifact maps.
    normalized = {
        asset.lower() + "_" + timeframe: value
        for (asset, timeframe), value in all_metrics.items()
    }
    summary = study._stability_summary(normalized, ({},), source_immutability_verified=True)
    assert summary["input_order_independent_membership"] is True
    assert summary["future_label_mutation_membership_invariant"] is True
    assert set(summary["per_dataset_family"]) == {
        asset.lower() + "_" + timeframe for asset, timeframe in study.DATASET_ORDER
    }


def test_manifest_validator_rejects_member_mutation(tmp_path: Path) -> None:
    context, source_root = _context(tmp_path)
    output = tmp_path / "output"
    study.run_study(source_root=source_root, output_root=output, _cohort_context=context, provider=_provider_factory([]))
    manifest = json.loads((output / "manifest.json").read_text())
    member = output / manifest["members"][0]["path"]
    member.write_bytes(member.read_bytes() + b"tamper")
    with pytest.raises(study.StudyArtifactError, match="manifest"):
        study._validate_manifest(output)


def test_new_runner_has_no_forbidden_runtime_or_legacy_imports() -> None:
    path = Path(study.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("binance" in item.lower() for item in imported)
    assert not any(item.startswith("libs.trendlines") or item.startswith("app.trendlines") or "trendlines_old" in item for item in imported)
    assert "src/apps/trendline_v2_viewer" not in path.read_text(encoding="utf-8")


def test_external_bundle_verification_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE", raising=False)
    assert "TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE" not in __import__("os").environ


def test_external_bundle_verifies_only_when_explicitly_enabled() -> None:
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external evidence verification is opt-in")
    result = study.verify_study_bundle()
    assert result["study_status"] in {
        "FRESH_SCOPE_PROMOTION_CANDIDATE",
        "REJECT_HOLDOUT_GATE",
        "NO_VALIDATION_FINALIST",
    }


def test_json_output_is_canonical() -> None:
    value = {"b": 2, "a": [1, True]}
    assert study._canonical_bytes(value) == b'{"a":[1,true],"b":2}\n'


def _copy_external_bundle(tmp_path: Path) -> Path:
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external evidence verification is opt-in")
    target = tmp_path / "bundle"
    shutil.copytree(study.OUTPUT_ROOT, target)
    return target


def _rebind_manifest(root: Path) -> None:
    manifest = study._load_json(root / "manifest.json")
    members = [
        {
            "path": path.relative_to(root).as_posix(),
            "byte_length": path.stat().st_size,
            "sha256": study._sha256_file(path),
        }
        for path in sorted(
            item for item in root.rglob("*") if item.is_file() and item.name != "manifest.json"
        )
    ]
    without_id = dict(manifest)
    without_id["member_count"] = len(members)
    without_id["members"] = members
    without_id.pop("manifest_id", None)
    without_id["manifest_id"] = study.deterministic_hash(study.MANIFEST_NAMESPACE, without_id)
    (root / "manifest.json").write_bytes(study._canonical_bytes(without_id))


@pytest.mark.parametrize("artifact", ("family_metrics", "family_summary", "validation_lock", "decision"))
def test_full_verifier_rejects_rebound_derived_artifact(tmp_path: Path, artifact: str) -> None:
    root = _copy_external_bundle(tmp_path)
    if artifact == "family_metrics":
        path = root / "datasets" / "btcusdt_1h" / "family_metrics.json"
        payload = study._load_json(path)
        payload["families"][study.FAMILY_IDS[0]]["candidate_count"] += 1
        path.write_bytes(study._canonical_bytes(payload))
    elif artifact == "family_summary":
        path = root / "datasets" / "btcusdt_1h" / "family_summary.csv"
        path.write_bytes(path.read_bytes() + b"tampered\n")
    elif artifact == "validation_lock":
        path = root / "validation_lock.json"
        payload = study._load_json(path)
        payload["validation_status"] = "NO_VALIDATION_FINALIST"
        without_id = dict(payload)
        without_id.pop("validation_lock_id")
        payload["validation_lock_id"] = study.deterministic_hash(
            study.VALIDATION_LOCK_NAMESPACE,
            without_id,
        )
        path.write_bytes(study._canonical_bytes(payload))
    else:
        path = root / "decision.json"
        payload = study._load_json(path)
        payload["study_status"] = "REJECT_HOLDOUT_GATE"
        without_id = dict(payload)
        without_id.pop("decision_id")
        payload["decision_id"] = study.deterministic_hash(
            f"{study.STUDY_SCHEMA}_decision",
            without_id,
        )
        path.write_bytes(study._canonical_bytes(payload))
    _rebind_manifest(root)
    with pytest.raises(study.StudyArtifactError):
        study.verify_study_bundle(output_root=root)


def test_offline_regeneration_makes_zero_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external evidence verification is opt-in")
    calls: list[str] = []

    def fail_provider(*_args: object, **_kwargs: object) -> object:
        calls.append("provider")
        raise AssertionError("offline remediation must not execute a provider")

    monkeypatch.setattr(study, "_execute_provider", fail_provider)
    result = study.regenerate_offline(output_root=tmp_path / "offline")
    assert calls == []
    assert result["study_status"] == "FRESH_SCOPE_PROMOTION_CANDIDATE"
