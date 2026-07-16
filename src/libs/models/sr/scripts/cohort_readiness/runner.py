"""Ordered V1.7 source-preparation and network-free evaluation stages."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
from typing import Any

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.scripts.baseline_trial.config import (
    load_and_resolve_input_config,
    load_resolved_sr_config,
)

from .artifacts import (
    load_source_bundle,
    publish_evaluation_bundle,
    publish_source_bundle,
)
from .config import CohortConfig, load_cohort_config
from .contracts import (
    APPROVED_ASSETS,
    FROZEN_INPUT_HASH,
    FROZEN_SR_CONFIG_HASH,
    SourceBundle,
)
from .metrics import evaluate_cohort
from .source import (
    HistoricalOHLCVAdapter,
    build_source_bundle,
    default_provider_adapter,
    fetch_new_asset_sources,
    load_taousdt_source,
)


def repository_commit(repo_root: str | Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(Path(repo_root).resolve()), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractValidationError("cannot determine implementation commit") from exc


def _root_path(repo_root: str | Path, relative: str, *, field_name: str) -> Path:
    root = Path(repo_root).resolve()
    path = (root / relative).resolve()
    if root not in path.parents and path != root:
        raise ContractValidationError(f"{field_name} escaped repository root")
    return path


def _load_config(config_path: str | Path, repo_root: str | Path) -> CohortConfig:
    path = Path(config_path)
    if not path.is_absolute():
        path = Path(repo_root).resolve() / path
    return load_cohort_config(path)


def _assert_no_overrides(path: Path) -> None:
    raw = load_sr_config(path)
    if raw.get("timeframes") != {} or raw.get("assets") != {}:
        raise ContractValidationError("V1.7 requires empty timeframe and asset override sections")


def _assert_frozen_sr_config(config: CohortConfig, resolved: ResolvedSRConfig) -> None:
    if resolved.timeframe != config.timeframe or resolved.asset not in APPROVED_ASSETS:
        raise ContractValidationError("resolved SR configuration ownership mismatch")
    if resolved.asset == "TAOUSDT" and resolved.resolved_config_hash != FROZEN_SR_CONFIG_HASH:
        raise ContractValidationError("TAOUSDT resolved SR hash does not match V1.6")
    expected_provenance = tuple((path, "defaults") for path, _ in resolved.field_provenance)
    if resolved.field_provenance != expected_provenance:
        raise ContractValidationError("V1.7 forbids SR timeframe or asset overrides")
    fields = (
        ("detection", "pivot_span_bars", 5),
        ("detection", "zone_half_width_atr", 0.25),
        ("association", "merge_distance_atr", 0.50),
        ("lifecycle", "touch_tolerance_atr", 0.25),
        ("lifecycle", "break_buffer_atr", 0.25),
        ("lifecycle", "break_confirm_closes", 2),
        ("lifecycle", "max_age_bars", 50),
        ("runtime", "max_active_zones", 8),
    )
    for section, field_name, expected in fields:
        if getattr(getattr(resolved, section), field_name) != expected:
            raise ContractValidationError(f"frozen SR parameter changed: {section}.{field_name}")


def _assert_frozen_input(config: CohortConfig, resolved: Any) -> None:
    if resolved.timeframe != config.timeframe or resolved.asset not in APPROVED_ASSETS:
        raise ContractValidationError("resolved input configuration ownership mismatch")
    if resolved.asset == "TAOUSDT" and resolved.resolved_input_hash != FROZEN_INPUT_HASH:
        raise ContractValidationError("TAOUSDT resolved input hash does not match V1.6")
    if resolved.atr_method != "wilder_rma" or resolved.atr_period != 14 or resolved.atr_seed != "sma":
        raise ContractValidationError("V1.7 ATR input is not frozen Wilder RMA(14) SMA-seeded")
    if tuple((path, "defaults") for path, _ in resolved.field_provenance) != resolved.field_provenance:
        raise ContractValidationError("V1.7 forbids input timeframe or asset overrides")


def resolve_frozen_configs(config: CohortConfig, *, repo_root: str | Path) -> tuple[dict[str, ResolvedSRConfig], dict[str, Any], dict[str, tuple[str, str]]]:
    root = Path(repo_root).resolve()
    sr_path = _root_path(root, config.sr_config_path, field_name="sr_config_path")
    input_path = _root_path(root, config.input_config_path, field_name="input_config_path")
    _assert_no_overrides(sr_path)
    _assert_no_overrides(input_path)
    sr_configs: dict[str, ResolvedSRConfig] = {}
    input_configs: dict[str, Any] = {}
    hashes: dict[str, tuple[str, str]] = {}
    for asset in APPROVED_ASSETS:
        sr = load_resolved_sr_config(sr_path, asset=asset, timeframe=config.timeframe)
        resolved_input = load_and_resolve_input_config(input_path, asset=asset, timeframe=config.timeframe)
        _assert_frozen_sr_config(config, sr)
        _assert_frozen_input(config, resolved_input)
        sr_configs[asset] = sr
        input_configs[asset] = resolved_input
        hashes[asset] = (sr.resolved_config_hash, resolved_input.resolved_input_hash)
    return sr_configs, input_configs, hashes


async def prepare_source_stage_async(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    adapter: HistoricalOHLCVAdapter | None = None,
    implementation_commit: str | None = None,
) -> dict[str, Any]:
    config = _load_config(config_path, repo_root)
    commit = implementation_commit or repository_commit(repo_root)
    sr_configs, input_configs, resolved_hashes = resolve_frozen_configs(config, repo_root=repo_root)
    tao = load_taousdt_source(
        config,
        repo_root=repo_root,
        resolved_sr_config_hash=resolved_hashes["TAOUSDT"][0],
        resolved_input_hash=resolved_hashes["TAOUSDT"][1],
    )
    provider = adapter or default_provider_adapter()
    new_sources = await fetch_new_asset_sources(
        config,
        adapter=provider,
        expected_grid=tuple(bar.open_time for bar in tao.bars),
        resolved_hashes=resolved_hashes,
    )
    bundle = build_source_bundle(
        config,
        implementation_commit=commit,
        tao_source=tao,
        new_sources=new_sources,
        resolved_hashes=resolved_hashes,
        resolved_sr_field_provenance={asset: sr_configs[asset].field_provenance for asset in APPROVED_ASSETS},
        resolved_input_field_provenance={asset: input_configs[asset].field_provenance for asset in APPROVED_ASSETS},
    )
    output_root = _root_path(repo_root, config.output_root, field_name="output_root")
    bundle_id, path = publish_source_bundle(bundle, output_root=output_root)
    return {
        "source_bundle_id": bundle_id,
        "source_bundle_path": str(path),
        "assets": list(APPROVED_ASSETS),
        "provider_calls": {source.asset: source.provider_calls for source in bundle.assets},
        "rows": {source.asset: source.row_count for source in bundle.assets},
    }


def prepare_source_stage(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    adapter: HistoricalOHLCVAdapter | None = None,
    implementation_commit: str | None = None,
) -> dict[str, Any]:
    return asyncio.run(prepare_source_stage_async(config_path, repo_root=repo_root, adapter=adapter, implementation_commit=implementation_commit))


def _source_path(config: CohortConfig, *, repo_root: str | Path, source_bundle_id: str | None) -> Path:
    output_root = _root_path(repo_root, config.output_root, field_name="output_root")
    if source_bundle_id is not None:
        candidate = (output_root / "source" / source_bundle_id).resolve()
        source_root = (output_root / "source").resolve()
        if source_root not in candidate.parents:
            raise ContractValidationError("source_bundle_id escaped output root")
        return candidate
    root = output_root / "source"
    matches = tuple(path for path in sorted(root.iterdir(), key=lambda item: item.name) if path.is_dir() and not path.is_symlink()) if root.is_dir() else ()
    if len(matches) != 1:
        raise ContractValidationError("evaluation requires exactly one explicit source bundle")
    return matches[0]


def evaluate_stage(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    source_bundle_id: str | None = None,
    source_bundle: SourceBundle | None = None,
    implementation_commit: str | None = None,
) -> dict[str, Any]:
    config = _load_config(config_path, repo_root)
    commit = implementation_commit or repository_commit(repo_root)
    sr_configs, input_configs, _ = resolve_frozen_configs(config, repo_root=repo_root)
    bundle = source_bundle or load_source_bundle(_source_path(config, repo_root=repo_root, source_bundle_id=source_bundle_id), config=config, expected_bundle_id=source_bundle_id)
    evaluation = evaluate_cohort(config, bundle, sr_configs, input_configs, implementation_commit=commit)
    output_root = _root_path(repo_root, config.output_root, field_name="output_root")
    bundle_id, path = publish_evaluation_bundle(evaluation, output_root=output_root, config=config, source_bundle=bundle)
    return {
        "evaluation_bundle_id": bundle_id,
        "evaluation_bundle_path": str(path),
        "evaluation_id": evaluation.evaluation_id,
        "disposition": evaluation.disposition.value,
    }


def validate_evaluation_stage(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    evaluation_bundle_path: str | Path,
    source_bundle_id: str | None = None,
) -> dict[str, Any]:
    from .artifacts import validate_evaluation_bundle

    config = _load_config(config_path, repo_root)
    sr_configs, input_configs, _ = resolve_frozen_configs(config, repo_root=repo_root)
    source = load_source_bundle(_source_path(config, repo_root=repo_root, source_bundle_id=source_bundle_id), config=config, expected_bundle_id=source_bundle_id)
    evaluation = validate_evaluation_bundle(evaluation_bundle_path, config=config, source_bundle=source, resolved_configs=sr_configs, resolved_inputs=input_configs)
    return {"evaluation_id": evaluation.evaluation_id, "disposition": evaluation.disposition.value}


# Descriptive aliases keep the stage names explicit for callers without
# introducing a second execution path.
evaluate_cohort_stage = evaluate_stage
prepare_source = prepare_source_stage


__all__ = [
    "evaluate_stage", "prepare_source_stage", "prepare_source_stage_async", "repository_commit",
    "resolve_frozen_configs", "validate_evaluation_stage", "evaluate_cohort_stage", "prepare_source",
]
