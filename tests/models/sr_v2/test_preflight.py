from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from libs.models.sr_v2.config import SRV2ConfigResolver
from libs.models.sr_v2.contracts import ZoneSide
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.research.development import (
    GlobalGeometryResources,
    ResolvedGlobalGeometryConfig,
)
from libs.models.sr_v2.research.optimizer import (
    OPTIMIZER_SCHEMA,
    TARGET_SELECTION_POLICY,
    resolve_optimizer_config,
)
from libs.models.sr_v2.research.preflight import (
    PREFLIGHT_CODE_POLICY_ID,
    PREFLIGHT_RECEIPT_SCHEMA,
    PreflightAssetInput,
    PreflightMeasurement,
    PreflightReceipt,
    PreflightRunResult,
    PreflightStatus,
    run_native_panel_preflight,
    validate_global_geometry_resource_preflight,
)
from libs.models.sr_v2.research.source import SourceBarRecord
from libs.models.sr_v2.research_lab.data import ResearchSourceSetManifest
from libs.models.sr_v2.research_lab.scientific_compiler import ScientificGroupKey


def _config(tmp_path):
    return resolve_optimizer_config(
        {
            "schema": OPTIMIZER_SCHEMA,
            "source": {
                "venue": "binance_usdm",
                "assets": {"BTCUSDT": "BTCUSDT"},
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
                "seed": "fixture",
                "trial_budget": 1,
                "baseline_structural_yaml": "configs/sr_v2.yaml",
                "parameters": {},
            },
            "inference": {
                "joint_utc_block": "1d",
                "epoch": "2024-01-01T00:00:00Z",
                "repetitions": 2,
                "confidence": 0.9,
                "alpha_family": "none@1",
                "degradation_margin": "0",
                "minimum_cell_support": 1,
                "minimum_asset_support": 1,
            },
            "resources": {"max_workers": 1, "receipt_dir": str(tmp_path / "receipts")},
        }
    )


def _manifest_and_records(config):
    records_by_tf = {}
    for timeframe in config.source.ladder:
        duration = grid_for(timeframe).duration
        opened = config.source.start
        bar = SRBar(
            timeframe=timeframe,
            bar_open_at=opened,
            bar_close_at=opened + duration,
            market_as_of=opened + duration,
            open=Decimal(100),
            high=Decimal(101),
            low=Decimal(99),
            close=Decimal(100),
            volume=Decimal(10),
            taker_buy_base=Decimal(5),
        )
        records_by_tf[timeframe] = (
            SourceBarRecord(
                venue="binance_usdm",
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                bar=bar,
                source_identity=f"source-{timeframe}",
                exchange_close_at=bar.bar_close_at,
            ),
        )
    manifest = object.__new__(ResearchSourceSetManifest)
    object.__setattr__(manifest, "manifest_id", "manifest")
    object.__setattr__(manifest, "source_sha256", "source")
    object.__setattr__(manifest, "records", len(records_by_tf))
    object.__setattr__(manifest, "venue", "binance_usdm")
    object.__setattr__(manifest, "instrument_ids", ("BTCUSDT",))
    object.__setattr__(manifest, "timeframes", tuple(config.source.ladder))
    object.__setattr__(manifest, "entries", ())
    object.__setattr__(
        manifest,
        "source_results",
        tuple(
            SimpleNamespace(records=records_by_tf[tf]) for tf in config.source.ladder
        ),
    )
    return manifest, records_by_tf


def _measurement(config, asset_input, *, wall=1.0, rss=10):
    groups = tuple(
        sorted(
            ScientificGroupKey(
                asset=asset_input.asset,
                timeframe=timeframe,
                kernel_id=kernel.kernel_id,
                kernel_version=kernel.kernel_version,
                side=side,
            )
            for timeframe in config.source.ladder
            for kernel in config.baseline_config.kernels
            if kernel.enabled_for(timeframe)
            for side in ZoneSide
        )
    )
    return PreflightMeasurement(
        asset=asset_input.asset,
        instrument_id=asset_input.instrument_id,
        source_manifest_id="manifest",
        source_sha256="source",
        source_slice_fingerprint=asset_input.source_slice_fingerprint,
        episode_artifact_id=asset_input.episode_artifact_id,
        model_fingerprint=config.baseline_config.config_fingerprint,
        baseline_structural_yaml_sha256=config.search.baseline_structural_yaml_sha256,
        target_fingerprint="target",
        compiler_fingerprint="compiler",
        family_fingerprint="family",
        code_policy_id=PREFLIGHT_CODE_POLICY_ID,
        steps=4,
        candidates=1,
        transitions=2,
        compiled_observations=2,
        expected_groups=groups,
        present_groups=groups,
        wall_duration_seconds=wall,
        peak_rss_bytes=rss,
        artifact_bytes=256,
        provider_call_count=0,
        peak_active_lineages=2,
        peak_terminal_tombstones=2,
        serialized_state_bytes=128,
        status=PreflightStatus.COMPLETED,
    )


def _process_evaluator(asset_input):
    """Top-level evaluator used to exercise the real process boundary."""

    model = SRV2ConfigResolver.from_yaml("configs/sr_v2.yaml").resolve()
    groups = tuple(
        sorted(
            ScientificGroupKey(
                asset=asset_input.asset,
                timeframe=timeframe,
                kernel_id=kernel.kernel_id,
                kernel_version=kernel.kernel_version,
                side=side,
            )
            for timeframe in model.ladder
            for kernel in model.kernels
            if kernel.enabled_for(timeframe)
            for side in ZoneSide
        )
    )
    return PreflightMeasurement(
        asset=asset_input.asset,
        instrument_id=asset_input.instrument_id,
        source_manifest_id=asset_input.source_manifest_id,
        source_sha256=asset_input.source_sha256,
        source_slice_fingerprint=asset_input.source_slice_fingerprint,
        episode_artifact_id=asset_input.episode_artifact_id,
        model_fingerprint=asset_input.model_fingerprint,
        baseline_structural_yaml_sha256=asset_input.baseline_structural_yaml_sha256,
        target_fingerprint=asset_input.target_fingerprint,
        compiler_fingerprint=asset_input.compiler_fingerprint,
        family_fingerprint=asset_input.family_fingerprint,
        code_policy_id=asset_input.code_policy_id,
        steps=4,
        candidates=1,
        transitions=2,
        compiled_observations=2,
        expected_groups=groups,
        present_groups=groups,
        wall_duration_seconds=0.0,
        peak_rss_bytes=1,
        artifact_bytes=256,
        provider_call_count=0,
        peak_active_lineages=2,
        peak_terminal_tombstones=2,
        serialized_state_bytes=128,
        status=PreflightStatus.COMPLETED,
    )


def _resource_config(tmp_path, assets=("BTCUSDT", "ETHUSDT")):
    config = object.__new__(ResolvedGlobalGeometryConfig)
    object.__setattr__(
        config,
        "source",
        SimpleNamespace(assets={asset: asset for asset in assets}),
    )
    object.__setattr__(
        config,
        "target_freeze",
        SimpleNamespace(baseline_model_fingerprint="m" * 64),
    )
    object.__setattr__(
        config,
        "resources",
        GlobalGeometryResources(
            max_workers=1,
            receipt_dir=str(tmp_path / "receipts"),
            artifact_root=str(tmp_path / "artifacts"),
            max_peak_rss_bytes_per_asset=10,
            max_artifact_bytes_per_asset=100,
            max_wall_seconds_per_asset=10,
            max_total_artifact_bytes=40,
        ),
    )
    return config


def _resource_measurement(
    config,
    asset,
    *,
    wall=1.0,
    rss=1,
    artifact=20,
):
    return PreflightMeasurement(
        asset=asset,
        instrument_id=asset,
        source_manifest_id="a" * 64,
        source_sha256="b" * 64,
        source_slice_fingerprint="c" * 64,
        episode_artifact_id="d" * 64,
        model_fingerprint=config.target_freeze.baseline_model_fingerprint,
        baseline_structural_yaml_sha256="e" * 64,
        target_fingerprint="f" * 64,
        compiler_fingerprint="1" * 64,
        family_fingerprint="2" * 64,
        code_policy_id=PREFLIGHT_CODE_POLICY_ID,
        steps=1,
        candidates=1,
        transitions=1,
        compiled_observations=0,
        expected_groups=(),
        present_groups=(),
        wall_duration_seconds=wall,
        peak_rss_bytes=rss,
        artifact_bytes=artifact,
        provider_call_count=0,
        peak_active_lineages=0,
        peak_terminal_tombstones=0,
        serialized_state_bytes=0,
        status=PreflightStatus.COMPLETED,
    )


def _resource_receipt(
    config,
    asset,
    *,
    primary_wall=1.0,
    primary_rss=1,
    primary_artifact=20,
    repeat_wall=1.0,
    repeat_rss=1,
    repeat_artifact=100,
):
    primary = _resource_measurement(
        config,
        asset,
        wall=primary_wall,
        rss=primary_rss,
        artifact=primary_artifact,
    )
    repeat = _resource_measurement(
        config,
        asset,
        wall=repeat_wall,
        rss=repeat_rss,
        artifact=repeat_artifact,
    )
    return PreflightReceipt(
        measurement=primary,
        repeat_measurement=repeat,
        semantic_hash=primary.semantic_hash,
    )


def test_global_resource_preflight_checks_both_runs_and_primary_scope(tmp_path):
    config = _resource_config(tmp_path)
    receipts = tuple(_resource_receipt(config, asset) for asset in config.source.assets)
    result = PreflightRunResult(receipts=receipts, resumed_assets=())
    validate_global_geometry_resource_preflight(config, result)

    bad_primary = _resource_receipt(config, "BTCUSDT", primary_rss=11)
    with pytest.raises(ValueError, match="peak_rss_bytes"):
        validate_global_geometry_resource_preflight(
            config,
            PreflightRunResult(receipts=(bad_primary, receipts[1]), resumed_assets=()),
        )
    bad_repeat = _resource_receipt(config, "BTCUSDT", repeat_wall=11)
    with pytest.raises(ValueError, match="wall_seconds"):
        validate_global_geometry_resource_preflight(
            config,
            PreflightRunResult(receipts=(bad_repeat, receipts[1]), resumed_assets=()),
        )

    bad_primary_artifact = _resource_receipt(config, "BTCUSDT", primary_artifact=21)
    with pytest.raises(ValueError, match="total ceiling"):
        validate_global_geometry_resource_preflight(
            config,
            PreflightRunResult(
                receipts=(bad_primary_artifact, receipts[1]), resumed_assets=()
            ),
        )


@pytest.mark.parametrize(
    "assets",
    [
        ("BTCUSDT",),
        ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    ],
)
def test_global_resource_preflight_rejects_missing_or_extra_assets(tmp_path, assets):
    config = _resource_config(tmp_path, assets=("BTCUSDT", "ETHUSDT"))
    result = PreflightRunResult(
        receipts=tuple(_resource_receipt(config, asset) for asset in assets),
        resumed_assets=(),
    )
    with pytest.raises(ValueError, match="exact assets"):
        validate_global_geometry_resource_preflight(config, result)


def test_global_resource_preflight_rejects_duplicate_asset_receipts(tmp_path):
    config = _resource_config(tmp_path)
    receipt = _resource_receipt(config, "BTCUSDT")
    result = object.__new__(PreflightRunResult)
    object.__setattr__(result, "receipts", (receipt, receipt))
    object.__setattr__(result, "resumed_assets", ())
    with pytest.raises(ValueError, match="exact assets|unique assets"):
        validate_global_geometry_resource_preflight(config, result)


def test_serial_preflight_repeats_semantics_and_resumes_without_overwrite(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    manifest, records = _manifest_and_records(config)
    monkeypatch.setattr(
        ResearchSourceSetManifest, "verify", lambda self, **kwargs: None
    )
    asset = PreflightAssetInput(
        asset="BTCUSDT",
        instrument_id="BTCUSDT",
        source_manifest=manifest,
        bars_by_timeframe=records,
        source_slice_fingerprint="c" * 64,
        episode_artifact_id="d" * 64,
        model_fingerprint=config.baseline_config.config_fingerprint,
        baseline_structural_yaml_sha256=config.search.baseline_structural_yaml_sha256,
        target_fingerprint="target",
        compiler_fingerprint="compiler",
        family_fingerprint="family",
    )
    calls = 0

    def evaluate(item):
        nonlocal calls
        calls += 1
        return _measurement(config, item, wall=float(calls), rss=calls)

    first = run_native_panel_preflight(
        config, {"BTCUSDT": asset}, evaluate, serial=True
    )
    assert calls == 2
    assert first.resumed_assets == ()
    receipt_path = tmp_path / "receipts" / "BTCUSDT.json"
    original = receipt_path.read_bytes()
    second = run_native_panel_preflight(
        config, {"BTCUSDT": asset}, evaluate, serial=True
    )
    assert calls == 2
    assert second.resumed_assets == ("BTCUSDT",)
    assert receipt_path.read_bytes() == original
    assert first.receipts[0].semantic_hash == second.receipts[0].semantic_hash
    assert first.receipts[0].repeat_measurement.wall_duration_seconds == 2.0


def test_preflight_semantic_hash_binds_state_peaks_not_wall_or_rss(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    manifest, records = _manifest_and_records(config)
    monkeypatch.setattr(
        ResearchSourceSetManifest, "verify", lambda self, **kwargs: None
    )
    asset = PreflightAssetInput(
        asset="BTCUSDT",
        instrument_id="BTCUSDT",
        source_manifest=manifest,
        bars_by_timeframe=records,
        source_slice_fingerprint="c" * 64,
        episode_artifact_id="d" * 64,
        model_fingerprint=config.baseline_config.config_fingerprint,
        baseline_structural_yaml_sha256=config.search.baseline_structural_yaml_sha256,
        target_fingerprint="target",
        compiler_fingerprint="compiler",
        family_fingerprint="family",
    )
    baseline = _measurement(config, asset)
    resource_variant = replace(
        baseline,
        wall_duration_seconds=9.0,
        peak_rss_bytes=999,
        artifact_bytes=999_999,
    )
    assert resource_variant.semantic_hash == baseline.semantic_hash
    assert (
        replace(
            baseline,
            source_slice_fingerprint="e" * 64,
        ).semantic_hash
        != baseline.semantic_hash
    )
    assert (
        replace(
            baseline,
            episode_artifact_id="f" * 64,
        ).semantic_hash
        != baseline.semantic_hash
    )
    with pytest.raises(ValueError, match="provider_call_count"):
        replace(baseline, provider_call_count=1)
    assert (
        replace(
            baseline, peak_active_lineages=baseline.peak_active_lineages + 1
        ).semantic_hash
        != baseline.semantic_hash
    )
    assert (
        replace(
            baseline,
            peak_terminal_tombstones=baseline.peak_terminal_tombstones + 1,
        ).semantic_hash
        != baseline.semantic_hash
    )

    run_native_panel_preflight(
        config,
        {"BTCUSDT": asset},
        lambda item: _measurement(config, item),
        serial=True,
    )
    path = tmp_path / "receipts" / "BTCUSDT.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["measurement"]["peak_active_lineages"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        run_native_panel_preflight(
            config,
            {"BTCUSDT": asset},
            lambda item: _measurement(config, item),
            serial=True,
        )


def test_preflight_rejects_malformed_or_identity_mismatched_receipt(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    manifest, records = _manifest_and_records(config)
    monkeypatch.setattr(
        ResearchSourceSetManifest, "verify", lambda self, **kwargs: None
    )
    asset = PreflightAssetInput(
        asset="BTCUSDT",
        instrument_id="BTCUSDT",
        source_manifest=manifest,
        bars_by_timeframe=records,
        source_slice_fingerprint="c" * 64,
        episode_artifact_id="d" * 64,
        model_fingerprint=config.baseline_config.config_fingerprint,
        baseline_structural_yaml_sha256=config.search.baseline_structural_yaml_sha256,
        target_fingerprint="target",
        compiler_fingerprint="compiler",
        family_fingerprint="family",
    )
    evaluate = lambda item: _measurement(config, item)
    run_native_panel_preflight(config, {"BTCUSDT": asset}, evaluate, serial=True)
    path = tmp_path / "receipts" / "BTCUSDT.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        run_native_panel_preflight(config, {"BTCUSDT": asset}, evaluate, serial=True)

    path.unlink()
    run_native_panel_preflight(config, {"BTCUSDT": asset}, evaluate, serial=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == PREFLIGHT_RECEIPT_SCHEMA
    assert (
        payload["measurement"]["episode_artifact_schema"] == "sr_v2.episode_artifact@2"
    )

    payload["schema"] = "sr_v2.native_panel_preflight_receipt@1"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        run_native_panel_preflight(config, {"BTCUSDT": asset}, evaluate, serial=True)

    path.unlink()
    run_native_panel_preflight(config, {"BTCUSDT": asset}, evaluate, serial=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["measurement"]["source_manifest_id"] = "different"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        run_native_panel_preflight(config, {"BTCUSDT": asset}, evaluate, serial=True)


def test_preflight_input_is_pickleable_for_process_worker(tmp_path, monkeypatch):
    import pickle

    config = _config(tmp_path)
    manifest, records = _manifest_and_records(config)
    monkeypatch.setattr(
        ResearchSourceSetManifest, "verify", lambda self, **kwargs: None
    )
    asset = PreflightAssetInput(
        asset="BTCUSDT",
        instrument_id="BTCUSDT",
        source_manifest=manifest,
        bars_by_timeframe=records,
        source_slice_fingerprint="c" * 64,
        episode_artifact_id="d" * 64,
        model_fingerprint=config.baseline_config.config_fingerprint,
        baseline_structural_yaml_sha256=config.search.baseline_structural_yaml_sha256,
        target_fingerprint="target",
        compiler_fingerprint="compiler",
        family_fingerprint="family",
    )
    restored = pickle.loads(pickle.dumps(asset))
    assert restored.asset == asset.asset
    assert tuple(restored.bars_by_timeframe) == tuple(asset.bars_by_timeframe)


def test_process_preflight_repeats_semantics_and_resumes(tmp_path, monkeypatch):
    config = _config(tmp_path)
    manifest, records = _manifest_and_records(config)
    monkeypatch.setattr(
        ResearchSourceSetManifest, "verify", lambda self, **kwargs: None
    )
    asset = PreflightAssetInput(
        asset="BTCUSDT",
        instrument_id="BTCUSDT",
        source_manifest=manifest,
        bars_by_timeframe=records,
        source_slice_fingerprint="c" * 64,
        episode_artifact_id="d" * 64,
        model_fingerprint=config.baseline_config.config_fingerprint,
        baseline_structural_yaml_sha256=config.search.baseline_structural_yaml_sha256,
        target_fingerprint="target",
        compiler_fingerprint="compiler",
        family_fingerprint="family",
    )
    first = run_native_panel_preflight(config, {"BTCUSDT": asset}, _process_evaluator)
    second = run_native_panel_preflight(config, {"BTCUSDT": asset}, _process_evaluator)
    assert first.resumed_assets == ()
    assert second.resumed_assets == ("BTCUSDT",)
    assert first.receipts[0].semantic_hash == second.receipts[0].semantic_hash
